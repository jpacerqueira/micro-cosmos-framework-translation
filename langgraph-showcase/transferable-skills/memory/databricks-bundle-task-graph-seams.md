---
name: databricks-bundle-task-graph-seams
description: Seam-by-seam bounded contexts for Databricks Asset Bundles, derived from the bundle's own job/pipeline YAML task graph instead of path heuristics (PR #23, 2026-08-05)
metadata:
  type: project
---

## The ask

Joao's direction after the Cartographer path-classification fix ([[databricks-cartographer-classification]]): don't stop at path heuristics for Databricks estates — a DAB (Databricks Asset Bundle) project already declares its real task boundaries and execution order in its own `databricks.yml` + `resources/*.job.yml`/`*.pipeline.yml` files. Use that as the seam signal directly. He pushed a real example (`examples/databricks_bundle_default_python`) onto this PR's branch to work against, and asked specifically for something that "looks for YAML files with jobs, and creates the glue and linkage of the ETL pipeline tasks."

## What a DAB job/pipeline YAML actually encodes

- `databricks.yml`: bundle root, `include: [resources/*.yml]` — the actual resource files live under `resources/`.
- A `*.pipeline.yml` resource declares a pipeline with `libraries: [glob: {include: <pattern>}]` — the pipeline "owns" every file the glob matches.
- A `*.job.yml` resource declares a job with a `tasks:` list. Each task has a `task_key`, an optional `depends_on: [{task_key: ...}]` (the real execution-order graph), and exactly one of three type-specific blocks:
  - `notebook_task.notebook_path` — a direct relative path to a notebook file.
  - `python_wheel_task.package_name` (+ `entry_point`) — resolves via the bundle's src-layout convention to `src/<package_name>/**`.
  - `pipeline_task.pipeline_id: ${resources.pipelines.<key>.id}` — an interpolation reference to a pipeline resource, whose own glob then resolves to the actual owned files.

None of this is inferable from directory paths alone — `pipeline_task` in particular is a level of indirection (task → pipeline resource → glob) that has no path-based analogue at all.

## What was built

`micro_cosmos/tools/databricks_bundle_tools.py` — new module, `parse_databricks_bundle(source_path)`. Resolves `include:` globs, parses every job's tasks and every pipeline's owned files, and resolves all three task kinds down to actual resolved file paths plus the `depends_on` graph between `task_key`s.

Wired into `analyse_bounded_contexts()` (`cartographer_tools.py`) as a new **Step 1a**, before the existing Step 1b (Java/C#/COBOL/generic over-broad drill-deeper): when `databricks.yml` is present, any `prog.*` node whose `source_location` resolves to a file a task owns gets its context **overridden** to that `task_key` (title-cased), taking priority over path-rule classification. Each task's `depends_on` is folded directly into `cross_context_calls` as an explicit pair — this is the scheduler's own declared order, not inferred from any source-code `CALLS` edge at all. Files no task claims (e.g. `tests/`) fall through to the existing path-rule classifier unchanged.

## Verified against the real example

`examples/databricks_bundle_default_python` (1 job, 3 tasks; 1 pipeline) produces exactly:
- Contexts: `NotebookTask`, `PythonWheelTask`, `RefreshPipeline` (plus `DatabricksBundleDefaultPython` for the 2 test files no task references).
- `cross_context_calls`: `(NotebookTask, PythonWheelTask)` and `(NotebookTask, RefreshPipeline)` — matching the YAML's two `depends_on: [notebook_task]` declarations exactly.
- `refresh_pipeline`'s `pipeline_task.pipeline_id` interpolation correctly resolves through to the pipeline's glob-owned transformation files (`sample_trips_default_python.py`, `sample_zones_default_python.py`) — confirming the two-level indirection resolves correctly, not just the direct task kinds.

Regression-checked: both previously-fixed Databricks examples (`project1_databricks_adf`, the synthetic notebook repro — see [[databricks-cartographer-classification]]) produce byte-for-byte identical output before/after, since neither has a `databricks.yml` and Step 1a is a no-op for them. Full test suite before/after: same 9 pre-existing unrelated failures, plus 4 new passing tests (`tests/test_databricks_bundle.py`).

## Lesson

The path-rule classifier (Rule 9, Rule 14c, the generic drill-deeper) is fundamentally a *guessing* mechanism for estates with no better signal. Where an estate's own tooling already declares its real structure — a build manifest, a scheduler config, an asset bundle — that declared structure should take priority over guessing, not just feed into it as one more path pattern to special-case. This is a genuinely different integration shape (an override step, not a new path rule) precisely because the signal source is structurally different (a YAML task graph, not a file path).

## Follow-up, same day: Cartographer showed the task graph, but SEAMS was 0

Joao ran this live (via the Web UI, deterministic mode) and reported: Cartographer's repo map correctly showed `NotebookTask`/`PythonWheelTask`/`RefreshPipeline` with the right arrows between them, but the SEAMS tab showed "0 seams · 0 pts · 0 streams" — and with zero seams, Feature Specifier has nothing to plan against, so it can't produce a spec at all.

**Root cause:** bounded-context classification (`cartographer_tools.py`) and seam detection (`seam_tools.py`) are two separate mechanisms, and only the first one got the DAB-awareness fix. `_detect_seams()` finds seams two ways: fan-in on real `CALLS` edges, or (given a `bcm`) `CALLS` edges that cross a bounded-context boundary. A DAB job's tasks are chained by the *scheduler* (`depends_on` in the YAML) — `notebook_task` and `python_wheel_task` share no actual function call in the source code at all, so neither mechanism had anything to find. This was invisible until it was actually run live — the earlier verification only checked that Cartographer's bounded-context-map output was correct, not that anything downstream of it (seams, work streams) still worked.

**Deeper gap found along the way:** `identify_seams()` — the public entry point — never passed `bcm` into `_detect_seams()` at all (`return _detect_seams(ir)`, defaulting to `None`), even though `_detect_seams()` had a fully-implemented `bcm`-driven "context boundary seams" branch. Only the real pipeline's own direct call to `produce_seam_report(ir, bcm=bcm)` (in `pipeline.py`) ever exercised that branch. Calling `identify_seams()` directly to "regression check" a language, as had been done earlier in this same investigation, is therefore not equivalent to how the live pipeline actually behaves — worth remembering before trusting a quick manual check over actually running the phase.

**Fix:** added a `source_path` parameter threaded through `identify_seams()` → `produce_seam_report()` → `_detect_seams()`, and a new pass in `_detect_seams()` that calls `parse_databricks_bundle()` directly and turns every task's `depends_on` into a `link`-type seam — using `task_context_label()` (factored out of `cartographer_tools.py` into `databricks_bundle_tools.py` so both modules produce identical labels). Wired into all 4 of `pipeline.py`'s `produce_seam_report()` call sites, including the two in the always-runs "post-phase hooks" section that needed their own independent session-state fetch (the two inside the `skip_llm` branch already had `state` in scope).

**Verified through the real orchestrator, not just the tool functions:** ran `MicroCosmosOrchestrator.run_phase()` for OBSERVER then CARTOGRAPHER exactly as the live UI does, and read the actual `seam.json`/`work_streams.json` written to disk — `2 seams, 6 pts` / `1 stream, 6 pts` (both were `0` before). Regression-checked against COBOL (still `11` seams — `3 object, 8 link` — byte-for-byte, since that estate has no `databricks.yml`) and `project1_databricks_adf` (still `1`, unaffected). 5 tests in `tests/test_databricks_bundle.py`, full suite unchanged (same 9 pre-existing failures).

**Still open:** the seam does land in a work stream now (`ws_11_features_contracts`, via the existing hardcoded work-stream template), but that bucket's name ("Features Module Internal Contracts") reads oddly for a Databricks migration — `produce_work_streams()`'s stream template is a fixed, generic set of buckets that predates this work and wasn't designed with Databricks in mind. Not fixed here — flagged as a known cosmetic gap, not blocking Feature Specifier from having real seams to plan against.
