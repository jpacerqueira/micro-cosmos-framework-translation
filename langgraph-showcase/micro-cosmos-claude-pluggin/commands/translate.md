---
description: Run the full Micro-Cosmos pipeline through code translation
---

Run Micro-Cosmos as an application framework translation through code translation. Stop when the translated tree exists. Do not wait for a PR gate.

Read `skills/micro-cosmos/references/frameworks.md`, `skills/micro-cosmos/references/no-gates.md`, `skills/micro-cosmos/references/modes.md`, and `skills/micro-cosmos/references/phases.md` from this plugin. The depth is `translate`.

Confirm the source folder. Ask once for the target language and for deterministic or LLM mode if the user has not named them. Web frameworks in scope are Spring Boot, Axon Framework, NestJS, React, Django, Flask, and ASP.NET Core. Data engineering frameworks in scope are Databricks, Azure Data Factory, BigQuery Dataform, and Snowflake dbt.

Check `entitlement/ENTITLEMENT.md` and consume one run with `entitlement/entitlement.py` before Observer. If the license check refuses the run, say that a license is $15 a month after 5 free runs, and stop.

Then run the LangGraph pipeline, which is the code in `micro_cosmos/`:

`python3 run_pipeline.py --source "<source folder>" --target "<target>" --mode "<deterministic or llm>" --depth translate --account "<account id>"`

Pass `--llm-base-url` and `--llm-api-key` only with values the user typed in this conversation, and only for LLM mode.

The run uses the same prefix as the plan command, then the seam loop: Code Writer, Skeptical Review, Test Review, Functional Review, and the Writer. The translated tree is `reports/<project>_<target>/` under `<source>/.micro-cosmos/<run-id>/`. After that tree exists, stop. Do not open a PR gate. Do not modify the source folder's own files. Record gaps and continue when an artifact is incomplete.
