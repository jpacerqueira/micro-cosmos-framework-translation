---
name: adf-scheduler-non-dict-json-crash
description: A list-rooted JSON build artifact in a plain Java estate crashed the ADF scheduler detector, silently costing 3 phases their artifacts and then killing the run at an unguarded seam.json read — the detector runs for every language, not just Databricks (2026-08-19)
metadata:
  type: project
---

Run `e1acbc0c` (`java · examples/java-bankxyz_fraud_detection → kotlin`, deterministic,
`auto_approve_gates: true`) died with `FileNotFoundError` on `seam.json`. Full writeup:
`docs/bug-1-AttributeError-in-the-ADF-scheduler-detector-cascading-through-3-phases.MD`.

## The headline lesson: a component named after one ecosystem broke a completely unrelated one

The crash was inside `adf_scheduler_tools.py` — Azure Data Factory code — on a plain Maven/Java
project with zero Databricks involvement. Joao pushed back on exactly this ("is the plan wrong?
this was not a databricks run"), and the pushback was the right instinct: the name genuinely does
imply the wrong scope. The reason it isn't scoped that way is architectural, and worth remembering
before assuming any detector in `scheduler_tools.py`'s registry is inert for your language:

`discover_task_graph()` is called **unconditionally, for every estate, in every language** — from
`seam_tools.py::_detect_seams()` (guarded only by `if source_path:`, always true) and
`cartographer_tools.py::analyse_bounded_contexts()` (Step 1a, no guard at all). There is no
`source_lang` check anywhere upstream. So every registered detector runs against every estate.

## Why the ADF detector specifically is the dangerous one in that registry

`detect_databricks_bundle()` checks for a **filename** (`databricks.yml`) — cheap, and it touches
nothing else. `detect_adf_scheduler()` has to identify pipelines by **content shape**, because real
ADF exports follow no filename convention. So it does `root.rglob("*.json")` over the **entire**
estate — `target/`, `build/`, `node_modules/`, generated test reports, everything — and parses each
one.

`_load_json()` caught `OSError`/`json.JSONDecodeError` and was annotated `-> dict`. But a
well-formed JSON document doesn't have to be an object: a list, string, number, bool or null are
all valid roots. `_is_adf_pipeline()` trusted that annotation and called `doc.get("properties")`.
`examples/java-bankxyz_fraud_detection/target/cucumber-report/cucumber.json` — a Maven Cucumber
report, a JSON **array** — produced `AttributeError: 'list' object has no attribute 'get'`.

**The misleading type annotation was part of the bug, not incidental to it.** `-> dict` is exactly
what made the caller's unguarded `.get()` look type-safe on review. Fixed both: the annotation is
now `-> object`, and `_is_adf_pipeline()` starts with `if not isinstance(doc, dict): return False`.

## How one exception silently cost three phases their artifacts

Every consumer of `discover_task_graph()` already sat inside a broad `except Exception` that logs
and continues — individually reasonable, collectively catastrophic:

1. post-OBSERVER hook (`pipeline.py`) → no `seam.json`, no `work_streams.json`
2. Cartographer's `_direct_tool_fallback` → no `bounded_context_map.json`
3. Architect's (via `derive_tnas` → `analyse_bounded_contexts`) → no `tnas.json`

Each degraded to a single log line and a non-fatal `warning` event. With `auto_approve_gates: true`
every gate self-approved instantly, so **no human ever saw those three warnings** — the run sailed
into the seam loop with four artifacts missing. Worth remembering as a general risk of auto-approve:
it removes the human checkpoint that would otherwise catch a silently-degraded phase.

`get_all_seams_data()`'s synthetic-seam fallback then kept the seam loop running on a placeholder
seam (which is why the review JSONs and Kiro/Skills output exist on disk for a run that produced no
real seams — a genuinely confusing artifact state to debug cold). Finally `driver.py`'s retry pass
did an unguarded `(run_dir / "seam.json").read_text()` and turned a recoverable "nothing to retry"
into an uncaught `FileNotFoundError` that killed the whole pipeline. Fixed with `.exists()` — worth
fixing independently of the ADF bug, since it converts *any* future upstream seam-production failure
from a crash into a no-op.

## Transferable rules

- **A content-shape detector that scans arbitrary files runs for every estate unless it is
  explicitly language-gated.** Name-based intuition about scope ("this is the Databricks bit") is
  not a safety guarantee. Check the call chain.
- **"Valid JSON" ≠ "valid dict".** Anything parsing untrusted/arbitrary JSON files must
  `isinstance(..., dict)` before `.get()`. Never let a `-> dict` annotation stand on a function that
  returns `json.loads()` output unnarrowed.
- **A blanket `except Exception` per call site can hide a single shared root cause N times over.**
  Three separate "defensive" handlers here turned one bug into three silent artifact losses plus one
  unrelated-looking crash several phases downstream.

## Verification worth reusing

The regression sweep pattern is the reusable part: drive `initialise_session()` → `run_phase()` for
OBSERVER/CARTOGRAPHER/ARCHITECT against **every** estate under `examples/`, snapshot IR node/edge
counts, contexts, seam counts/types/points, work streams, TNAS services and the artifact file list,
then diff before vs after. Must go through `run_phase()`, not `identify_seams()` directly — seam
production is a *post-phase side effect* of `run_phase()`, and calling the tool function standalone
skips the `bcm`-driven branch (the same trap already flagged in [[scheduler-registry-adf-support]]).

Result: exactly one row changed (the broken estate, 0 → 11 contexts / 0 → 53 seams / 2 errors → 0),
ten byte-identical across Java ×3, COBOL ×2, C#, Python ×2, PySpark ×3. Suite 150 → 161 passed, and
all 11 new tests were confirmed to fail against the unfixed code *before* being accepted — a step
worth keeping, since a regression test that passes both ways proves nothing.

Related: [[scheduler-registry-adf-support]] (introduced this detector), [[databricks-bundle-task-graph-seams]].
