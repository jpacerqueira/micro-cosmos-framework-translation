---
name: tdd-writer-hardening
description: TDD Code Writer loop hardening (2026-07-20) — 3-attempt cap, per-seam status/attempts/failure_reason persisted into seam.json, new "Processing" UI tab, post-loop retry pass for failed seams, and MAX_TDD_ITERATIONS_PER_SEAM wired into both deploy environments
metadata:
  type: project
---

## What changed and why

Before this change, `micro_cosmos/orchestration/driver.py`'s per-seam TDD loop
(`_run_tdd_loop_for_seam`) retried Code Writer → Skeptical/Test/Functional
review up to a hardcoded `MAX_TDD_ITERATIONS = 5`, and whether a seam
converged or exhausted the budget, `_run_all_seams()` treated it
identically — ran Writer, emitted a bare `seam_completed` event with no
`status`/`attempts` field, moved on. Nothing was ever persisted about which
seams actually passed review, so after a run there was no way to see
(without reading raw trace logs) which parts of the translated project were
trustworthy vs. best-effort scaffolding, and a seam that failed got no
second chance.

Four things changed together:
1. Cap lowered to 3 attempts (configurable), and a seam that exhausts it is
   marked `"failed"` — Writer still runs regardless (best-effort code is
   always packaged, per explicit product-owner choice).
2. `status`/`attempts`/`retry_attempts`/`failure_reason` are persisted
   **directly onto each seam's existing entry in `runs/<run_id>/seam.json`**
   (the same tree the "Seams" UI tab already renders from) rather than a
   new artifact — a `processing` sub-object per seam plus a run-level
   `processing_summary`.
3. A new **"Processing"** tab, positioned right after "Trace" in the UI,
   renders this as a live-updating `<table>`.
4. After the full seam set has been processed once, every seam left
   `"failed"` gets exactly **one** more focused retry attempt, with the
   Code Writer kickoff prompt enriched with the accumulated failure reason
   from the first pass.

## Files changed

| File | What |
|---|---|
| `micro_cosmos/settings.py` | New `max_tdd_iterations_per_seam: int = 3` field (env var `MAX_TDD_ITERATIONS_PER_SEAM`), floor-of-1 validator — same pattern as `llm_ready_timeout_seconds` |
| `micro_cosmos/tools/seam_tools.py` | New `init_seam_processing()`, `update_seam_processing()`, `summarize_seam_failure()` (factored out of driver.py's finding-collection logic so the persisted `failure_reason`, the in-loop FIX prompt, and the retry-pass kickoff all share one implementation) |
| `micro_cosmos/orchestration/driver.py` | `MAX_TDD_ITERATIONS` now reads the setting; `_run_tdd_loop_for_seam` gained `max_iterations`/`result` params (async generators can't return a value through `async for`, so the outcome — attempts/passed/failure_reason — comes back via a caller-owned dict); `_run_all_seams()` now inits/updates processing status per seam and runs the retry pass afterward; the Gate-5-rejection re-run branch force-resets every seam's processing back to pending first |
| `micro_cosmos/web/templates/run.html` | New "Processing" tab button + panel, inserted right after Trace |
| `micro_cosmos/web/static/js/dashboard.js` | `loadProcessingPanel()`/`renderProcessingPanel()` (always re-fetches, unlike the Seams tab's one-shot load), `switchTab()` hook, new `retry_pass_started`/`retry_pass_completed` WS cases, `seam_completed` case now shows status/attempts and triggers a live table refresh |
| `micro_cosmos/web/static/css/app.css` | Ported `.demo-table` (previously only inline in `fraud_demo.html`) + `.status-ok`/`.status-fail`/`.status-pending` classes |
| `docker-compose.yml`, `deployment/deploy_cloudrun-micro-cosmos-app.py`, `.env.example` | `MAX_TDD_ITERATIONS_PER_SEAM` threaded through exactly like `SKIP_LLM` already is — hardcoded in docker-compose, read-then-passed via `--set-env-vars` in the Cloud Run deploy script |

One bug fixed as a side effect, not a new feature: `MicroCosmosOrchestrator.load_artifact()`
(`pipeline.py:353-370`) caches `self.artifacts["seam"]` on first read and
never invalidated it. Since `seam.json` is now mutated mid-run, every
`update_seam_processing`/`init_seam_processing` call in driver.py is
followed by `orch.artifacts.pop("seam", None)` so `GET /runs/{id}/seams`
and `GET /runs/{id}/artifacts/seam` never serve a stale cached copy.

## Where this sits in the pipeline

```
... Gate 4.5 "Planning" (human checkpoint)
  → for each seam:
       Code Writer → Skeptical/Test/Functional review   (up to 3x, was 5x)
         ├─ all three passed  → processing.status = "success"
         └─ cap exhausted     → processing.status = "failed" (+ failure_reason)
       → Writer  (always runs — best-effort code always packaged)
  → after ALL seams done once:
       for each seam still "failed":
         Code Writer (kickoff enriched with prior failure_reason) → reviews  (exactly 1x)
         → Writer
         → processing.status updated, retry_attempts = 1
  → PR Reviewer → Gate 5
       if REJECTED: every seam's processing resets to "pending" first,
       then the whole seam loop above runs again from scratch
```

`seam.json`'s `processing`/`processing_summary` fields are additive — the
Cartographer/Observer producers of `seam.json` (`produce_seam_report()`)
are untouched; the new fields are only ever written after Gate 4.5, well
after `seam.json` is otherwise finalized.

## Real verification performed (2026-07-20)

Standalone harness (no ADK/docker needed — `micro_cosmos.tools` package's
`__init__.py` eagerly imports `google-adk`, so `seam_tools.py` was loaded
directly via `importlib.util` to dodge that chain, same technique already
established in this repo's Trivy work):
```
python3 - <<'EOF'
... init_seam_processing / update_seam_processing / summarize_seam_failure
    exercised against a scratch seam.json + review JSON files ...
EOF
```
All assertions passed: idempotent init, force-reset, attempts/retry_attempts
tracked independently, failure_reason correctly built from real
BLOCKER/missing-test-category findings, and the "no review files at all"
fallback string.

Then a full live run against the rebuilt Docker image
(`docker compose up --build -d`), deterministic mode (`SKIP_LLM=true`,
the default): **important finding** — in deterministic mode there is no
`_direct_tool_fallback` case for `CODE_WRITER`/`SKEPTICAL_REVIEW`/
`TEST_REVIEW`/`FUNCTIONAL_REVIEW`/`WRITER` in `pipeline.py`, so every seam
in a deterministic run will always exhaust the attempt cap and end up
`"failed"` — this is expected, not a bug, and is exactly why deterministic
mode was actually a *good* way to exercise the new failure-tracking/retry
logic without needing a real LLM backend.

Ran `examples/java-bankxyz_fraud_detection` (58 real seams) end-to-end via
curl (login → `POST /runs` → approve `gate_1`…`gate_4_5` → observe the seam
loop → reject `gate_5`):
```
runs/<id>/seam.json → processing_summary: {"total": 58, "pending": 0, "success": 0, "failed": 58}
first seam: {"status": "failed", "attempts": 3, "retry_attempts": 1,
             "failure_reason": "Code Writer produced no verifiable output and
             review phase(s) did not run — see trace for details."}
```
Confirms: cap is 3 (not the old 5), Writer ran regardless, retry pass ran
exactly once per failed seam. `GET /runs/{id}/seams` and
`GET /runs/{id}/artifacts/seam` both returned this live (not stale-cached).

Rejected `gate_5` and confirmed the reset via the real container log line:
```
micro-cosmos-1  | 12:28:37 INFO micro_cosmos.tools.seam_tools · seam processing reset for 58 seam(s) in /app/runs/41577975/seam.json
```
then confirmed the seam set re-ran from a clean slate — final state was
`attempts: 3, retry_attempts: 1` again (not `6`/`2`), proving the reset
actually took effect rather than the counts accumulating across the
rejection boundary.

UI verified with a real headless-browser session (`playwright`, installed
fresh into the scratchpad — `npx playwright install chromium`, no
Playwright/browser was present in this environment beforehand): logged in
as `demo`/`demobxyz`, opened the run page, clicked the "Processing" tab,
confirmed via the DOM (not just visual inspection) that the tab sits
between Trace and Artifacts, the table renders all 58 rows with correct
`status-fail` styling, the attempts cell reads `"3 (+1 retry)"`, the
failure-reason column shows the real summarized text, and the tab badge
does *not* increment while that tab is the active one. Screenshot taken and
visually confirmed too.

Both test run directories (`runs/03ad40b1`, `runs/41577975`) were deleted
after verification — they were throwaway test artifacts, not real runs.

## Known caveat for future readers

If a deterministic-mode run's Processing tab shows every seam "failed",
that is *expected* given the current lack of a deterministic fallback for
the code-generation phases — it does not by itself indicate a regression
in this feature. Check `run_meta.json`'s `skip_llm` flag before assuming
otherwise (same standing advice as [[project_trivy_security_scanning]]'s
note about deterministic-mode security findings).
