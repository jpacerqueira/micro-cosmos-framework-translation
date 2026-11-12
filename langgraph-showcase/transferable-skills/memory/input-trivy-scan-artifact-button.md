---
name: input-trivy-scan-artifact-button
description: Added the missing "Input Trivy scan" Artifacts-tab button (2026-07-20) — the source-side Trivy artifact already existed and was already servable, just had no UI button
metadata:
  type: project
---

## What changed

`micro_cosmos/web/templates/run.html`'s Artifacts tab had a button for the
**output**-side Trivy scan (`trivy_output_report`, produced by
`pipeline.py::_run_trivy_output_scan()` after Gate 5) but none for the
**source**-side scan that already existed and already ran before Gate 4.

## Why no backend/JS work was needed

`micro_cosmos/tools/security_tools.py::run_trivy_scan()` already writes
`runs/<id>/trivy_report.json` (called via `_run_trivy_prescan()` in
`pipeline.py`, gated only on `phase == PipelinePhase.SECURITY` — not
skip_llm-gated at the call-site level, though see the caveat below). The
generic `GET /runs/{run_id}/artifacts/{key}` route
(`micro_cosmos/web/app.py:485-493`) already serves any `<run_dir>/<key>.json`
file via `orch.load_artifact(key)` — so `GET /runs/{id}/artifacts/trivy_report`
already worked with zero backend changes, and `dashboard.js` already
fetched it (line ~1012) to enrich the Gate 4 summary popover. It just had
no Artifacts-tab button of its own. Fix was a single line:
```html
<button class="art-btn" data-key="trivy_report">Input Trivy scan</button>
```
placed between `security_report` and `review_report` — every `.art-btn` is
auto-wired generically (`dashboard.js` querySelectorAll), so no JS change
was needed either, mirroring the already-shipped `trivy_output_report`
button exactly.

## Caveat confirmed live during verification

In **deterministic mode** (`skip_llm=true`, the default), `trivy_report.json`
is never produced — confirmed by running `examples/java-bankxyz_fraud_detection`
end-to-end through Gate 4 and finding no `trivy_report.json` on disk, only
`security_report.json` (the separate regex-based deterministic-mode
placeholder — see [[project_trivy_security_scanning]]'s existing note on
this exact distinction). This isn't a bug in this change — the *output*
Trivy button has the identical gap in deterministic mode (confirmed via a
live 404 in the container logs for `trivy_output_report` on an earlier
deterministic run this same session). Both buttons only return real data
in LLM mode; clicking either in deterministic mode surfaces the existing
generic "not yet available" message, same as any other not-yet-produced
artifact.

## Verification performed

- Grepped the running container's `run.html` after rebuild to confirm the
  new button landed in the image (`docker exec ... grep`).
- Real headless-browser session (Playwright): opened a live run's
  Artifacts tab, read every `.art-btn`'s `data-key`/label pair back out of
  the DOM — confirmed `trivy_report` → "Input Trivy scan" sits between
  `security_report` and `review_report`, exactly as placed.
- **Render confirmed, not just button presence**: since deterministic mode
  never produces a real `trivy_report.json` (see caveat above) and no LLM
  backend was available to generate one for real, a sample file matching
  the real schema (`summary` + `vulnerabilities` with CVE ids, package
  names, severities) was placed directly into a scratch run's directory.
  `GET /runs/{id}/artifacts/trivy_report` returned it correctly, and a
  Playwright session clicking the actual "Input Trivy scan" button
  confirmed the pretty-printed CVE JSON renders in `#artifact-view` and the
  button gets the `.ready` class — i.e. the full click-to-render path
  works, not just the button's existence in the DOM.
- Test run directories deleted after verification (kept the user's own
  manually-started run untouched).
