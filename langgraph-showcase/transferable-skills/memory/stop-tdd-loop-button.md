---
name: stop-tdd-loop-button
description: "Stop TDD loop" button for LLM-mode runs — cooperative-flag design (not Task.cancel), a real flag-leak bug found and fixed during testing, and how it was verified (2026-08-10)
metadata:
  type: project
---

Joao asked for a button to stop an in-progress LLM-mode run's per-seam TDD loop (Code Writer →
Skeptical/Test/Functional Review) without killing the whole run/container. The existing "↩
Restart from here" gate control already does full-task `asyncio.Task.cancel()` on `Run._task`
(`micro_cosmos/web/app.py`'s `restart()`) — the wrong shape here, since `asyncio.CancelledError` is
`BaseException` (not `Exception`) since Python 3.8, so it isn't swallowed by any of `run_phase()`'s
`except Exception:` blocks and propagates cleanly through every nested `async for`/`yield` up to
`Run._run_pipeline`'s single `except asyncio.CancelledError:` handler, terminating the whole
`run_full_pipeline()` generator. It never falls through to PR Reviewer/Gate 5 — exactly what
"stop just the TDD loop" needed to do.

## Design: cooperative flag, not cancellation

`MicroCosmosOrchestrator.stop_requested: bool` (`micro_cosmos/orchestration/pipeline.py`, next to the
existing `_gate_events` dict) — a plain bool, not an `asyncio.Event`, since nothing ever *awaits*
it; it's only read synchronously at loop-top checkpoints, the same way `orch.current_phase` is
already mutated. Two checkpoints in `micro_cosmos/orchestration/driver.py`:

- **Top of each TDD iteration**, inside `_run_tdd_loop_for_seam()` — halts the *current* seam
  mid-loop, sets `result["stopped"] = True`, marks it failed with a "stopped by user" reason.
- **Top of each seam**, inside `_run_all_seams()` — halts *before* the next seam starts, marks
  every remaining seam failed with a "skipped — stopped before this seam started" reason.

New `POST /runs/{run_id}/stop-tdd-loop` (mirrors `restart_run`'s style in `app.py`) sets the flag
and broadcasts a `tdd_loop_stop_requested` event immediately, independent of when the pipeline
generator actually notices — instant UI feedback even though the actual halt only happens at the
next checkpoint. `_run_all_seams` yields `tdd_loop_stopped` once the loop genuinely halts.
`PipelineEvent.kind` is a plain `str`, so both are new string values with zero schema changes.

New Stop button is **static markup in `run.html`**, not dynamically injected like `gate-restart`
— rendered only inside `{% if not run.skip_llm %}` so it's absent from the DOM entirely in
deterministic-mode runs (no separate JS-side mode check needed). Uses htmx's native `hx-confirm`
for a confirmation dialog before stopping — deliberately more cautious than the confirmation-free
"Restart from here", since a stop can discard in-progress seam work rather than just re-running
an already-completed phase. `dashboard.js` shows the button on `phase_started`/`seam_started` for
any of the 4 TDD-loop phases, hides it on `gate_opened`/`pipeline_completed`/`error`/the new
`tdd_loop_stopped`.

## Real bug found and fixed during testing

First version only reset `orch.stop_requested` at the seam-boundary checkpoint. If the stop
happened on the **last seam** (mid-seam checkpoint fires, but the seam-boundary checkpoint is
never re-entered because there's no next seam), the flag stayed `True` past the end of
`_run_all_seams()`. Two knock-on failure modes, both reproduced during reasoning-before-testing:

1. The post-loop single-attempt retry pass (which retries any seam left `status="failed"`,
   including the one just stopped) would either wrongly re-run the stopped seam with real Code
   Writer calls (if something else had reset the flag first) — defeating the whole point of
   stopping — or silently do nothing while still emitting a `retry_pass_started` event, a
   confusing but harmless UX inconsistency.
2. Worse: the leaked `True` flag would carry forward into a **future** Gate-5-rejection re-run of
   `_run_all_seams()` on the *same* `MicroCosmosOrchestrator` instance (`driver.py`'s
   `while gate_state.decision.value == "REJECTED":` loop calls `_run_all_seams()` again) —
   immediately triggering the seam-boundary checkpoint on seam #1 of that unrelated re-run and
   marking every seam skipped, sabotaging a rejection retry the user never asked to stop.

Fixed by having **both** checkpoints consume the flag (`orch.stop_requested = False` at the top
of the mid-seam checkpoint too, not just the seam-boundary one), plus a local `stop_occurred`
bool tracked across the whole `_run_all_seams()` call — checked once, right after the seam loop,
to skip the retry pass unconditionally whenever a stop fired anywhere in that pass, regardless of
which checkpoint happened to catch it.

## How this was verified

**Automated regression test** — `tests/test_stop_tdd_loop.py`, new file, reusing the
`skip_llm_orch` deterministic-mode fixture pattern already established in `test_pipeline.py`
(no LM Studio connection needed; every phase goes through `_direct_tool_fallback`). Drives
`run_full_pipeline()` end-to-end with every `gate_opened` auto-approved via `orch.approve_gate()`,
sets `orch.stop_requested = True` on the first `seam_started` event, and asserts:
`tdd_loop_stopped` fires, `retry_pass_started` never fires, Gate 5 and `pipeline_completed` are
still reached, and — the actual regression check for the bug above — `orch.stop_requested is
False` again by the end. All pass.

**Confirmed no regressions**: ran the same test files against a `git stash` of this branch (i.e.
the pre-existing code with none of these changes) and got the *identical* 5 pre-existing
failures in `test_pipeline.py`/`test_gates.py` (e.g. `test_initial_gate_states_pending` still
expects 5 gates, stale since Gate 4.5 was added) — confirming those failures predate this feature
and aren't caused by it. Popped the stash back immediately after.

**Live via Playwright**: deterministic-mode run → `document.getElementById("run-controls")` is
`null` (button genuinely absent from the DOM, not just hidden). LLM-mode run → element present
with `hidden: true` before Code Writer starts, `hx-post="/runs/<id>/stop-tdd-loop"` and the
expected `hx-confirm` text both wired up correctly. One real snag while driving this test: the
first few attempts silently produced no run at all — LLM-mode submissions go through the existing
inline confirmation panel from [[llm-mode-confirm-toggle]] (`.llm-confirm-inline`, a *second*
click on "Continue with LLM mode" required), which the test script wasn't clicking through yet;
once fixed, submission worked immediately. A separate incident during manual verification —
deleting a still-live LLM-mode run's directory (`docker exec rm -rf`) while its background task
was actively calling into ADK — caused the container to crash and auto-restart via
`restart: unless-stopped`; recovered cleanly with no data loss beyond that one run, consistent
with the pre-existing risk already documented in cross-session memory (check for a live
background task before deleting a run directory).

## Files changed

| File | Change |
|---|---|
| `micro_cosmos/orchestration/pipeline.py` | New `MicroCosmosOrchestrator.stop_requested: bool` |
| `micro_cosmos/orchestration/driver.py` | Two cooperative checkpoints; `stop_occurred` tracking to skip the retry pass after any stop |
| `micro_cosmos/web/app.py` | New `_TDD_LOOP_PHASES` + `POST /runs/{run_id}/stop-tdd-loop` |
| `micro_cosmos/web/templates/run.html` | New `#run-controls`/`#tdd-stop-form`, LLM-mode-only |
| `micro_cosmos/web/static/js/dashboard.js` | Visibility wiring + 2 new WS event cases |
| `tests/test_stop_tdd_loop.py` | New automated regression test |
