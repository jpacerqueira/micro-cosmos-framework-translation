---
name: deterministic-mode-trivy-scan
description: Source-side Trivy scan now runs in Deterministic mode too (2026-07-20) — run_phase()'s skip_llm branch previously returned before ever reaching the Trivy prescan hook
metadata:
  type: project
---

## What changed and why

`micro_cosmos/orchestration/pipeline.py::run_phase()` had a `skip_llm` branch
(lines 456-513) that always returned before line 516's
`if phase == PipelinePhase.SECURITY: async for ev in self._run_trivy_prescan(): yield ev`
was ever reached. Result: `trivy_report.json` (the source-side Trivy scan)
was **only ever written in LLM mode** — every Deterministic-mode run had
an empty "Input Trivy scan" Artifacts-tab button, no exceptions, since the
day this branch was written (`git blame`: 2026-05-20, Chris Jones — long
before the button existed).

Confirmed via direct code reading (not guessed) that this was safe to
change: `_run_trivy_prescan()` and `micro_cosmos/tools/security_tools.py::run_trivy_scan()`
only need `source_path`/`source_lang` (written into session state
unconditionally at `initialise_session()`, before any phase runs, in
**both** modes) and `self.run_dir` — zero LLM/agent-output dependency.
Trivy + JDK 21 + Gradle + the .NET SDK are already baked into the Docker
image (`Dockerfile` lines 26-36) for LLM mode's use of the same function,
so no new container dependency was needed either.

**Fix**: added the same `_run_trivy_prescan()` call inside the `skip_llm`
branch, for `phase == PipelinePhase.SECURITY`, mirroring the existing
pattern right above it — the OBSERVER/CARTOGRAPHER seam-production hooks
(`produce_seam_report`/`produce_work_streams`) already run unconditionally
in both modes, for the identical reason (no LLM dependency, needed
downstream regardless of mode).

**Deliberately out of scope** (confirmed via explicit product-owner
choice, not assumed): Trivy's CVE findings are **not** merged into
`security_report.json` (the separate regex-based deterministic scanner's
own artifact — see [[project_trivy_security_scanning]]). `trivy_report.json`
stays its own artifact, exactly as it already was in LLM mode — the HTML
report (`scripts/generate_security.js`) already reads both files
independently and renders Trivy's CVEs as their own section, so nothing
else needed to change for the data to actually be visible somewhere once
it exists.

**Not changed, a related but separate gap**: `security-report.html`
generation itself only happens in the LLM-mode post-drain hook
(`pipeline.py:667-684`), not inside the `skip_llm` branch — so a
Deterministic run still doesn't auto-generate that HTML report inline
(it can be regenerated on demand via the web app's report-regeneration
endpoint, since that only needs the JSON artifacts to exist on disk).
Flagged as a possible future follow-up, not fixed here.

## Real verification performed

Rebuilt the Docker image (`docker compose up --build -d`), then drove a
brand-new Deterministic-mode run (`skip_llm=true`) against
`examples/java-bankxyz_fraud_detection` end-to-end via curl (login →
`POST /runs` → approve `gate_1`/`gate_2`/`gate_3` → wait for `gate_4`):

```
runs/<id>/trivy_report.json:
{
  "summary": {"total": 32, "HIGH": 16, "MEDIUM": 13, "CRITICAL": 1, "LOW": 2},
  "vulnerabilities": [
    {"cve_id": "CVE-2025-52999", "pkg_name": "com.fasterxml.jackson.core:jackson-core", ...},
    ...
  ]
}
```
This is a **real** `trivy fs` scan result against the actual Maven
dependencies in that example project — not a stub. Confirmed the generic
`GET /runs/{id}/artifacts/trivy_report` endpoint serves it correctly, and
that this run's `gate_4` (Security review) reached `PENDING` normally —
i.e. the added Trivy call didn't break or slow the Security phase's own
completion in any observable way.

## Lesson generalizing from this and the sibling "Input Trivy scan button" fix

Both this fix and the earlier button-addition ([[project_input_trivy_scan_button]])
were found by simply asking "does clicking X actually show real data,"
not just "does the button/endpoint exist." The actual gap here
(`run_phase()`'s early return) was invisible from the UI/API layer alone —
it only surfaced by tracing the exact code path a Deterministic-mode
Security phase takes, line by line, against what an LLM-mode phase does
differently.
