---
description: Run Micro-Cosmos from Observer through the framework translation planner and stop before code translation
---

Run Micro-Cosmos as an application framework translation and stop before code translation. This is `pause_after_planning`.

Read `skills/micro-cosmos/references/frameworks.md`, `skills/micro-cosmos/references/no-gates.md`, `skills/micro-cosmos/references/modes.md`, and `skills/micro-cosmos/references/phases.md` from this plugin. The depth is `plan`.

Confirm the source folder. Ask once for the target language and for deterministic or LLM mode if the user has not named them. Web frameworks in scope are Spring Boot, Axon Framework, NestJS, React, Django, Flask, and ASP.NET Core. Data engineering frameworks in scope are Databricks, Azure Data Factory, BigQuery Dataform, and Snowflake dbt.

Check `entitlement/ENTITLEMENT.md` and consume one run with `entitlement/entitlement.py` before Observer. If the license check refuses the run, say that a license is $15 a month after 5 free runs, and stop.

Then run the LangGraph pipeline, which is the code in `micro_cosmos/`:

`python3 run_pipeline.py --source "<source folder>" --target "<target>" --mode "<deterministic or llm>" --depth plan --account "<account id>"`

Pass `--llm-base-url` and `--llm-api-key` only with values the user typed in this conversation, and only for LLM mode.

The run writes `<source>/.micro-cosmos/<run-id>/` with the same plan artifacts as the plan command: `run.json`, `ir_graph.json`, `bounded_context_map.json`, `seam.json`, `work_streams.json`, `tnas.json`, `security_report.json`, `feature_specs.json`, `framework_translation_plan.md`, `gaps.md`, and `PLAN_COMPLETE.md`. Code translation does not start. Do not open a gate, and do not stop because an artifact is incomplete.
