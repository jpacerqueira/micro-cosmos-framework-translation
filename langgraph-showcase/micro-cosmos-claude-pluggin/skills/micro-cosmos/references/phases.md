# Pipeline phases

Read `frameworks.md`, `modes.md`, and `no-gates.md` before the first phase. The plan command stops after the framework translation planner. The translate command continues into code translation and stops when the translated tree exists.

`run_pipeline.py` runs these phases with the LangGraph pipeline in `micro_cosmos/`. Observer, Cartographer, Architect, Security, and the Feature Specifier use the AST, tree-sitter, and regex tools in `micro_cosmos/tools/`. Deterministic mode sets `skip_llm`. LLM mode uses the agents on those same tools.

The run folder is `<source>/.micro-cosmos/<run-id>/`. `run-id` is a UTC timestamp `YYYYMMDDTHHMMSSZ`.

## Plan depth

Observer, Cartographer, Architect, Security analysis, then the framework translation planner. This is `pause_after_planning` in the driver. The run then writes:

- `run.json` with `source_path`, `source_lang`, `target_lang`, `mode`, `depth`, `account_id`, and `frameworks_detected`
- `ir_graph.json`
- `bounded_context_map.json`
- `seam.json`
- `work_streams.json`
- `tnas.json`
- `security_report.json`
- `feature_specs.json`
- `framework_translation_plan.md`
- `gaps.md`
- `PLAN_COMPLETE.md`, which lists those files and the sentence "Code translation did not start."

A plan run does not start the seam loop.

## Translate depth

The same prefix, then code translation. For each seam the pipeline runs Code Writer, Skeptical Review, Test Review, and Functional Review, up to 3 times, then the Writer. The translated tree is `reports/<project>_<target>/`. `<project>` is the source folder name.

When that tree exists, the run stops. It does not open a PR gate and it does not wait for Gate 5.

The same analysis files are written, plus `gaps.md` and `framework_translation_plan.md`. `PLAN_COMPLETE.md` is not written.

A thin artifact is recorded in `gaps.md`. The next phase still starts.
