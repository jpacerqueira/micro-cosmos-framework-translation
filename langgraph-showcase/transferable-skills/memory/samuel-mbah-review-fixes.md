---
name: samuel-mbah-review-fixes
description: Fixed 5 of 7 code-review findings on the FAISS/review-defaults work — a real concurrency-fix consolidation, two more missing-tool-default instances, a seam-file-matching bug that turned out worse than reported, a defensive case-fix, and an in-memory index cache; 2 findings were confirmed intentional behavior, not bugs (2026-08-10)
metadata:
  type: project
---

Samuel Mbah reviewed the two prior same-day commits ([[context-window-source-search]] and
[[review-submit-tool-defaults]]). Joao triaged the 7 findings before any fix started: points 1-2
(Stop button staying disabled after one use; Stop not propagating into the retry pass) are
**intentional** — the Stop button is a deliberate one-shot "wind this run down cleanly" action for
a Cloud Run + vLLM deployment, not a resumable/repeatable control. Points 3-7 were real and fixed,
each verified against the actual current code before touching anything (one turned out to be worse
than the review text implied — see point 5).

## 3. Consolidated three copies of a known unresolved issue into one `ContextVar`

CLAUDE.md already flagged `_current_run_dir` module globals in `coder_tools.py`/
`coding_loop_tools.py` as an unresolved concurrency risk with `contextvars.ContextVar` as the
stated mitigation. The FAISS work ([[context-window-source-search]]) added a *third* independent
copy in `source_tools.py` rather than fixing the underlying issue. Fixed properly instead of
patching the third copy: new `micro_cosmos/tools/run_context.py` — one `ContextVar`-backed
`set_run_dir()`/`get_run_dir()`, imported and re-exported by all three modules.
`pipeline.py`'s three separate `set_run_dir()` calls collapsed into one. Since each `Run` gets its
own `asyncio.Task` (`Run.start()`), `ContextVar` values are captured per-Task at creation — two
concurrent runs get independent values with no locking needed.

**A real debugging detour while verifying this**: a deterministic-mode end-to-end check showed
`get_run_dir()` empty after a full run. Six increasingly targeted isolated `contextvars`
propagation tests (plain async generators, 3-level nested async-generator delegation,
set-after-first-yield, task-spawning-and-awaiting) all passed — the mechanism itself was never
broken. The actual explanation: `pipeline.py::run_phase()`'s `set_run_dir()` call sits *after* the
`skip_llm` branch's early `return` — so deterministic mode never reaches it. Confirmed via
`git`-equivalent reasoning that the *original* three-separate-globals code had the identical
early-return structure, so this predates the fix entirely and isn't a regression — and it's
harmless in practice, since `list_source_files`/`search_relevant_source` only ever run as
LLM-agent-invoked FunctionTools, which only happens past that same early-return. Re-verified by
short-circuiting `_drain_runner` right after the `set_run_dir()` call (avoiding any real network
call) and confirmed `get_run_dir()` correctly matches `orch.run_dir` in the actual LLM-mode path.
Lesson: when a live check fails, isolate the mechanism first (contextvars propagation, proven
sound) before assuming the integration is broken — the bug was in test coverage/assumptions, not
the fix.

## 4. Two more missing-tool-default instances

Same failure mode as [[review-submit-tool-defaults]]: `security_tools.py::
submit_security_findings` (`scope_summary`/`findings`/`source_architecture_risk`/
`destination_architecture_risk` all lacked defaults) and this session's own new
`source_search_tools.py::search_relevant_source` (`seam_name`/`query`/`source_path`/`source_lang`
lacked defaults). Both functions already handled `None`/empty values safely internally, so adding
defaults was a pure availability fix.

## 5. Seam-file matching was worse than "missing a path-separator check"

The review said this needed a path-boundary check to avoid "Payment" matching "PaymentGateway/".
Investigating the actual data revealed a bigger problem: `seam.json`'s `side_a`/`side_b` fields
mean **different things depending on seam type** (`seam_tools.py`) — real top-level directory
names with a trailing `/` for directory-based `link` seams; bounded-context names or
scheduler-task labels (never filesystem paths) for context-boundary/scheduler-task `link` seams;
human-readable prose ("3 caller(s)", "concrete implementation") for `boundary`/`object`/
`preprocessing` seams. Treating all of these as directory-prefix strings was imprecise for the
one case where it was even semantically appropriate, and simply wrong for the other three. Fixed
by only using a side as a directory filter when `(root / side).is_dir()` actually resolves —
walking *inside* the confirmed real directory (not string-prefix-matching every file) closes the
false-positive class entirely and correctly no-ops for every seam type where these fields were
never paths to begin with. Worth remembering: when a review flags a matching bug, check what the
matched-against data actually *means* across all its producers before assuming the fix is just
"add a boundary check."

## 6. Applied a defensive fix even though it isn't a live bug today

`work_streams.json`'s `risk` field is always lowercase today, so `_streamCard`'s unguarded
`` `ws-risk-${ws.risk}` `` isn't currently broken — but it's the identical unguarded pattern that
*was* a real bug for `tnas.migration_risk` (uppercase) until fixed in `_targetServiceCard`. Added
the same `.toLowerCase()` normalization for robustness against a future data-shape change, not
because it's failing right now.

## 7. In-memory cache for the source vector index

`search_relevant_source` called `load_source_index()` on every invocation — many times per run,
across every seam/iteration — which re-read the index sidecar from disk every time, directly
undercutting the point of [[context-window-source-search]] building it once. Added a bounded
in-memory cache (20-entry cap mirroring `app.py`'s `_MAX_RUNS` convention) so only the first call
per run touches disk.

## Follow-up: point 6 was only fixed in one of two spots

Samuel caught this in a second look at the merged commit: the point-6 fix only normalized
`ws.risk` in `_streamCard` (`dashboard.js:1443`) — `exportSeamReport()` (`dashboard.js:1680`, the
standalone downloadable seam-report HTML) has the structurally identical `ws.risk === "high"`
ternary and was still unnormalized. Same one-line fix applied there too. Worth remembering: when
a "same pattern exists elsewhere, fix defensively" finding lands, grep for *every* occurrence of
the pattern (`ws.risk`/`ws-risk` in this case) before considering it closed — `_streamCard` and
`exportSeamReport()` render the same data two different ways and both needed the fix.

## Verification

New/updated tests: `tests/test_review_submit_defaults.py` and `tests/test_source_search.py`
updated to call `set_run_dir()` (the public API) instead of monkeypatching the now-removed
per-module attribute. Three new tests: prose/label `side_a`/`side_b` matches nothing; a real
"Payment/" seam matches only files under it, not a sibling "PaymentGateway/"; `load_source_index()`
hits disk exactly once across two calls for the same run. Full suite: 36 passed (up from 33), 1
skipped, the same 5 pre-existing unrelated failures already documented in earlier same-day
entries.

## Files changed

| File | Change |
|---|---|
| `micro_cosmos/tools/run_context.py` (new) | Shared `ContextVar`-backed `set_run_dir()`/`get_run_dir()` |
| `micro_cosmos/tools/coder_tools.py`, `micro_cosmos/tools/coding_loop_tools.py`, `micro_cosmos/tools/source_tools.py` | Use the shared module; `source_tools.py` also gets the directory-validation fix |
| `micro_cosmos/orchestration/pipeline.py` | Collapsed 3 `set_run_dir()` calls into 1 |
| `micro_cosmos/tools/security_tools.py`, `micro_cosmos/tools/source_search_tools.py` | Missing defaults |
| `micro_cosmos/retrieval/source_index.py` | In-memory index cache |
| `micro_cosmos/web/static/js/dashboard.js` | `_streamCard` risk-badge case normalization |
| `CLAUDE.md` | Updated the now-fixed concurrency note |
| `tests/test_review_submit_defaults.py`, `tests/test_source_search.py` | Updated + 3 new tests |
