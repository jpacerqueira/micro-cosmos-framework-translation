---
name: scheduler-registry-adf-support
description: Extensible ETL-scheduler registry (DAB + Azure Data Factory) driving Cartographer/seam detection, replacing the DAB-only integration (PR #23, 2026-08-06)
metadata:
  type: project
---

## The ask

Follow-on to [[databricks-bundle-task-graph-seams]]. After the Databricks Asset Bundle (DAB) fix shipped, Joao asked (still testing live, mid-call) whether it would be "too complicated" for the pipeline to also discover an *external* scheduler — specifically Azure Data Factory (ADF) — orchestrating Databricks notebooks. He then pushed two real ADF-scheduled examples directly onto this branch and said: "the issue is, in Microsoft Azure there can be at least 3-4 schedulers for this: Fabric ADF, Databricks cron, Databricks Asset Bundle YAML, and this Azure Scheduler James talked about... Try to adapt to both databricks projects to have seams... it will [prove] we can do multiple different ones."

That's an explicit ask for extensibility, not just a second hardcoded parser.

## What was built

**`micro_cosmos/tools/adf_scheduler_tools.py`** — new parser, same task-graph output shape as `databricks_bundle_tools.py`. Detects ADF pipeline JSON by *content shape* (`properties.activities` is a list), not filename convention — real ADF exports don't follow one fixed naming pattern. Each activity's `dependsOn` becomes the task graph edges; `notebookPath`/`pythonFile` are resolved to real files.

**Notebook-path resolution had to handle two genuinely different conventions**, discovered only because Joao pushed two examples that happened to differ:
- `examples/databricks_adf_notebooks_project`: `notebookPath: "/project_domain/notebooks/..."` — a bare project-root prefix that matches a real on-disk directory name.
- `examples/databricks_adf_project1_profile`: `notebookPath: "/Repos/retail-platform/notebooks/..."` — Databricks *Repos*-style workspace path, where `Repos` and `retail-platform` are workspace scaffolding with **no on-disk equivalent at all**.

An ancestor-directory-matching resolver (which worked for the first example) fails outright on the second. Fixed with a general suffix-search: try the full path against the estate root, then progressively drop the leading segment and retry, stopping at the first match. This covers both conventions (and any other `/<n-segments-of-scaffolding>/<real-path>` convention) without hardcoding "Repos" or any other keyword. Also handles `pythonFile` activities pointing at `dbfs:/...` paths with no on-disk equivalent at all (`IngestItemSeason` in the profile example) — tolerated as an unresolved-but-still-present task, not an error, same as DAB's unmatched `pipeline_id` references.

**`micro_cosmos/tools/scheduler_tools.py`** — new registry: `discover_task_graph(source_path)` tries every registered `(detect_fn, parse_fn)` pair and merges their task dicts. This is the actual extension point Joao asked for — adding Databricks cron, Fabric pipelines, or "the Azure Scheduler James mentioned" later means adding one tuple to `_SCHEDULERS`, not touching Cartographer or seam detection at all.

`cartographer_tools.py`'s Step 1a and `seam_tools.py`'s scheduler-seam pass were both **rewired to call the registry instead of the DAB parser directly** — this is a strict generalization, not a parallel code path. Rationale/evidence text was also de-specialized (no longer says "databricks.yml job" unconditionally) since it now has to describe whichever scheduler(s) actually fired.

## Bug found while re-testing: CamelCase names got mangled

`task_context_label()` used `str.title()` after splitting on `-`/`_`. DAB task_keys are snake_case (`"notebook_task"` → `"NotebookTask"`, correct). ADF activity names are PascalCase with **no delimiter to split on** (`"RunCustomer360"`) — `"RunCustomer360".title()` produces `"Runcustomer360"` (title-case only respects word boundaries at non-letter characters; embedded capitals aren't boundaries to it). Fixed: only split-and-title when there's an actual `-`/`_` to split on; otherwise return the name unchanged. Found by actually reading the Cartographer output, not by reasoning about the function in the abstract — same "verify against real output, don't assume" pattern as every fix in this thread.

## Verified against all three Databricks examples + COBOL (negative control + regression)

| Estate | Scheduler | Contexts | Seams (before this work: 0 for all three DAB/ADF estates) |
|---|---|---|---|
| `databricks_bundle_default_python` | DAB | 4 (unchanged from prior fix) | 2 |
| `databricks_adf_notebooks_project` | ADF, bare-prefix paths | 4 | 4 |
| `databricks_adf_project1_profile` | ADF, Repos-style paths + one unresolvable `dbfs:` activity | 8 | 8 |
| `cobol-bankxyz_fraud_detection` | none (negative control) | unchanged | 11 (3 object, 8 link — byte-for-byte identical to the pre-existing baseline) |

Verified through the real orchestrator dispatch (`_direct_tool_fallback` for CARTOGRAPHER then ARCHITECT), not just the tool functions directly. Full test suite: same 9 pre-existing failures, plus 13 new passing tests (6 DAB, 7 ADF).

## Lesson

Joao naming multiple concrete scheduler formats *before* a second one was even built was the signal to build a registry, not a second if/elif branch — the cost of the abstraction was small (one new module, ~15 lines of dispatch logic) and it immediately paid for itself: the two ADF examples he pushed used two different, incompatible path conventions, which would have been two separate special cases in an if/elif design but were just two branches of one general "search decreasing suffixes" algorithm here.

## Follow-up (2026-08-19): this detector crashed a plain Java run

`detect_adf_scheduler()`'s content-shape scan (`rglob("*.json")` over the whole estate) raised
`AttributeError` on a list-rooted Maven build artifact in `examples/java-bankxyz_fraud_detection`,
silently costing three phases their artifacts and then killing the run. Because
`discover_task_graph()` is never language-gated, this registry runs for **every** estate — a
detector named after one ecosystem can break an unrelated one. See
[[adf-scheduler-non-dict-json-crash]] for the full incident and the `isinstance` fix.
