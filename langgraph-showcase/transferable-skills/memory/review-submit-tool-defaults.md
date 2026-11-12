---
name: review-submit-tool-defaults
description: Missing Python defaults on submit_code_review/submit_test_review/submit_functional_review caused ADK to silently reject the tool call whenever a model omitted run_dir or a boolean flag — found via /debug-run on a real run, same bug class already flagged (but unfixed) for submit_security_findings (2026-08-10)
metadata:
  type: project
---

`/debug-run bbe6edc5` (a real LLM-mode run, C#→Java21) surfaced three warnings on the same seam
across all 3 TDD iterations:

```
WARNING  skeptical_review  skeptical_reviewer_agent  Agent produced an invalid 'skeptical_review'
         artifact and the direct-tool fallback also failed.
WARNING  test_review       test_reviewer_agent       Agent produced an invalid 'test_review'
         artifact and the direct-tool fallback also failed.
WARNING  functional_review tdd_loop                  TDD loop did not reach a clean pass after
         3 iteration(s). Proceeding with best available translation.
```

## Diagnosis process (worth repeating for future `/debug-run` sessions)

1. Checked `runs/bbe6edc5/` for which artifacts existed: `seam_result.json` had 21 real files
   (17 impl + 4 tests) — **Code Writer succeeded**. But `skeptical_review.json`, `test_review.
   json`, and `functional_review.json` were **all absent** — every reviewer failed, every
   iteration, on this seam.
2. The "functional_review" tag on the final "TDD loop did not reach a clean pass" warning is a
   red herring — that's a hardcoded phase label on driver.py's give-up message, not evidence that
   Functional Reviewer specifically was the failing one. All three reviewers failed equally.
3. Traced the exact warning text (`"Agent produced an invalid '{output_key}' artifact and the
   direct-tool fallback also failed"`) to `pipeline.py`'s `run_phase()`: after an agent's turn,
   if `output_key` never landed in `session.state` (i.e. the submit tool was never successfully
   called) AND `_direct_tool_fallback()` has no case for that phase, this exact message fires.
   `_direct_tool_fallback()` has no case for `CODE_WRITER`/`SKEPTICAL_REVIEW`/`TEST_REVIEW`/
   `FUNCTIONAL_REVIEW` by design (LLM mode is expected to succeed on its own for these) — so the
   "fallback also failed" half of the message is *always* true for these 4 phases and doesn't by
   itself indicate a bug.
4. The real question: why did the submit tool call never land? Checked `micro_cosmos/tools/
   coding_loop_tools.py`'s three submit functions' signatures and found `run_dir: str` with no
   default on all three, plus `has_happy_path`/`has_rule_violation`/`has_edge_case: bool` with no
   default on `submit_test_review`. ADK treats any parameter without a Python default as
   mandatory and **silently rejects the entire tool call** if the model's function-call JSON
   omits one — no exception surfaces anywhere in the trace beyond the generic "invalid artifact"
   message, no file gets written.

This is the exact same bug class the project's own `/debug-run` skill already documents (but
hadn't actually fixed) for `submit_security_findings`'s `scope_summary`/`source_architecture_risk`
— worth checking the skill's "ADK tool validation patterns" section for other function signatures
in this codebase that might have the same gap; `security_tools.py`'s fields are still unfixed as
of this writing, out of scope for this specific fix but a known follow-up.

## Fix

Added defaults to all three functions in `micro_cosmos/tools/coding_loop_tools.py`:
- `submit_code_review(findings, passed, run_dir: str = "")`
- `submit_test_review(findings, passed, has_happy_path: bool = False, has_rule_violation: bool =
  False, has_edge_case: bool = False, run_dir: str = "")`
- `submit_functional_review(findings, passed, run_dir: str = "")`

All three already did `run_dir = run_dir or _current_run_dir` internally (the same
`set_run_dir()`-backed module-global fallback pattern used across `coder_tools.py`/
`coding_loop_tools.py`/`source_tools.py`), so defaulting the parameter itself to `""` is safe —
this only stops ADK from rejecting a call outright when a model omits the field; a well-formed
call's behavior is completely unchanged.

A smaller/local model is a plausible trigger — this dev environment runs `google/gemma-4-e4b`
locally, not the deployed 31B-parameter production model from `gcloud-run-setup-vllm.txt` — but
the fix is correct regardless of which model triggered it; any model can drop a "boilerplate"
parameter like `run_dir` deep into a long tool-calling turn, and there's no reason this class of
tool should ever hard-require it when the module-global fallback already exists for exactly this
case.

## Verification

New `tests/test_review_submit_defaults.py` (3 tests) — calls each function with only
`findings`/`passed` (the fields most likely to be reliably supplied) and confirms it still writes
its JSON file correctly, with `has_happy_path`/`has_rule_violation`/`has_edge_case` correctly
defaulting to `False` on `submit_test_review`. All pass. Full suite: 33 passed (up from 30 earlier
the same day), 1 skipped, the same 5 pre-existing unrelated failures.

## Files changed

| File | Change |
|---|---|
| `micro_cosmos/tools/coding_loop_tools.py` | Added missing defaults to all three review-submit functions |
| `tests/test_review_submit_defaults.py` | New automated regression test |
