---
name: processing-tab-deterministic-messaging
description: PR #18 review fix (2026-07-21) — the Processing tab (added in tdd-writer-hardening.md) needed explicit messaging for two unexplained states, not a real logic bug
metadata:
  type: project
---

## What prompted this

PR #18 review comment: "the new Processing tab has no deterministic-mode
handling — I confirmed live that it shows all 58 seams as permanently
'pending' with zero explanation when SKIP_LLM=true." Rather than assume
either the reviewer's framing or my own prior testing was right, this was
reproduced live, fresh, against the current committed state of the branch.

## Two distinct gaps found, not one

**Gap 1 — before the seam TDD loop starts** (confirmed on a run held at
Gate 4.5, not yet approved): `seam.json` has no `processing`/
`processing_summary` fields at all yet (`init_seam_processing()` only runs
inside `_run_all_seams()`, which only starts after Gate 4.5 is approved).
`dashboard.js`'s `renderProcessingPanel()` previously defaulted every seam
to `{status: "pending"}` in this case with no other context. **Not
Deterministic-mode-specific** — this happens identically for an LLM-mode
run sitting at the same gate. This is almost certainly what the reviewer
actually saw.

**Gap 2 — after the loop completes, in Deterministic mode specifically**:
confirmed all 58 seams correctly show `"failed"` with a real
`failure_reason` — this is [[project_tdd_writer_hardening]]'s code working
exactly as designed, since Deterministic mode has no Code
Writer/review LLM fallback (see [[project_tdd_writer_hardening]] and
`.claude/commands/debug-run.md`'s "Processing tab / seam-status patterns"
section). But with zero context, "100% of seams failed" reads as a
regression to anyone reviewing it, not as expected behavior.

## Fix

Both handled client-side in `renderProcessingPanel()`
(`micro_cosmos/web/static/js/dashboard.js`), no backend changes:
- If `seamData.processing_summary` is absent (Gap 1): show "Seam
  processing hasn't started yet — waiting for Gate 4.5 approval" instead
  of the table.
- If present, and the page's existing `.run-mode-badge` element has class
  `mode-det` (Gap 2 — reused the existing server-rendered mode indicator,
  no new fetch/backend call needed): prepend a `.processing-det-banner`
  explaining this is expected before the table, table/data unchanged.

## Verification

Rebuilt the image, drove a fresh Deterministic run through both states via
curl (gate approvals) + a real Playwright session:
- Confirmed the exact Gap 1 message renders while held at Gate 4.5.
- Confirmed the Gap 2 banner renders (exact text extracted from the live
  DOM) once Gate 4.5 is approved and the seam loop completes, alongside
  the correct `58 failed` summary and 58 table rows.
- One test-script false alarm caught and correctly diagnosed, not
  mistaken for a bug: a later screenshot appeared to show the Gates panel
  instead of Processing. Root cause was the pipeline had already reached
  Gate 5 by that point in the test, and the pre-existing (intentional)
  `case "gate_opened": ... switchTab("gates")` handler fired and switched
  tabs out from under the test — confirmed via `gate_5: PENDING` on the
  run and by re-checking the earlier, still-valid content extraction
  (banner text + row count), which had already proven the fix correct
  before that race occurred.

## Lesson

Two "reproduce it live before touching code" findings in one review pass:
the actual root causes were both narrower and more precise than the
review comment's own framing (mislabeled as purely a Deterministic-mode
issue, when Gap 1 isn't mode-specific at all) — worth always reproducing
a reviewer's claim directly rather than pattern-matching it against
memory of how the feature was built.
