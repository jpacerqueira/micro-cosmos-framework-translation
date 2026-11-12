---
name: adk-session-architecture
description: ADK InMemorySessionService session architecture — cross-agent contamination issue, fixes applied 2026-06-29, residual concurrent-run risk
metadata:
  type: project
---

## Architecture

All 11 pipeline agents share a single `InMemorySessionService` session keyed `"source-session"` (`pipeline.py:273`). Each agent runs through its own ADK `Runner` but all runners share the same session service instance per `MicroCosmosOrchestrator`.

**Why:** The session service propagates state (`source_path`, `source_lang`, `target_lang`, `run_dir`, artifacts) from one phase to the next without explicit parameter passing.

## Known issue — FIXED, and confirmed still active as of 2026-07-23

The shared session accumulates the full event/conversation history of every agent. When a subsequent agent starts its own `Runner`, the ADK replays all prior events and labels those from other agents as "unknown". In the TDD loop this causes three symptoms (first observed in run `a23b8d06`):

1. Code_writer events replayed 3× (once per reviewer) — same event UUIDs logged as "unknown agent"
2. LLM cross-agent tool hallucination: `code_writer_agent` calling `submit_skeptical_review` (leaked from reviewer session history)
3. `run_dir=None` crash in `submit_functional_review`: reviewer system prompts have `{run_dir?}` placeholders that ADK does not substitute at runtime; LLM passed null

**History, corrected**: the fix (commit `50f4e45`, 2026-06-30 14:06) was reverted same-day (`952a9e7`, 16:30), then **re-applied** less than seven hours later (`a80dea6`, 23:07) and has stayed in ever since — this file previously said "NOT YET FIXED (reverted 2026-06-30)," which described the ~2.5-hour window between those last two commits, not the current state. Re-verified directly against the live code on 2026-07-23 while investigating a separate `ContextWindowExceededError` incident (see [[project_gcp_deployment]]'s matching entry): `driver.py`'s `_run_tdd_loop_for_seam` calls `await orch.reset_session()` before each of `SKEPTICAL_REVIEW`/`TEST_REVIEW`/`FUNCTIONAL_REVIEW`, and again before each new seam and before the retry pass — all four call sites from the fix below are present and active.

**Fix, applied and active:**
- `reset_session()` before each of the three reviewer phases in `_run_tdd_loop_for_seam` (`driver.py`)
- `"current_seam"` added to preserved keys in `reset_session()` (`pipeline.py`)
- `set_run_dir` pre-phase hook extended from `CODE_WRITER` only to all four code-gen phases (`pipeline.py`)
- `_current_run_dir` module global + `set_run_dir()` + `run_dir or _current_run_dir` fallback in `coding_loop_tools.py`

**Caveat found 2026-07-23, not covered by this fix**: `reset_session()` preserves *every* artifact under 50KB (toon-dumped) into the new session's state on every call, with no aggregate size cap — only a per-key one. This doesn't reintroduce the cross-agent event-history contamination above, but it is a separate, real source of prompt growth across a run. See the `ContextWindowExceededError` entry in [[project_gcp_deployment]] for the live incident this caused.

## Residual Risk — concurrent CODE_WRITER runs (not yet fixed)

`_current_run_dir` in `coder_tools.py` is a **process-wide module-level global**. If two LLM runs reach CODE_WRITER concurrently, the second `set_run_dir()` call overwrites the first.

**Mitigation path:** Replace with `contextvars.ContextVar`. Blast radius: concurrent LLM runs only; deterministic mode and single-active-run are unaffected.
