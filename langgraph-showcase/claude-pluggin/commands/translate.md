---
description: Run the full Micro-Focus pipeline through code translation
---

Run Micro-Focus as an application framework translation through code translation.

Read `skills/micro-focus/references/frameworks.md`, `skills/micro-focus/references/no-gates.md`, `skills/micro-focus/references/modes.md`, and `skills/micro-focus/references/phases.md` from this plugin. The depth is `translate`.

Confirm the source folder. Ask once for the target language and for deterministic or LLM mode if the user has not named them. Web frameworks in scope are Spring Boot, Axon Framework, NestJS, React, Django, Flask, and ASP.NET Core. Data engineering frameworks in scope are Databricks, Azure Data Factory, BigQuery Dataform, and Snowflake dbt.

Check `entitlement/ENTITLEMENT.md` and consume one run with `entitlement/entitlement.py` before Observer. If the license check refuses the run, say that a license is $10 a month after 10 free runs, and stop.

Follow every phase, including code translation. Write the translated tree under the run's `reports/` directory. Do not modify the source folder's own files. Do not open a gate, and do not stop because an artifact is incomplete. Record gaps and continue to the next phase. After the last seam, stop. Do not wait for a PR approval.
