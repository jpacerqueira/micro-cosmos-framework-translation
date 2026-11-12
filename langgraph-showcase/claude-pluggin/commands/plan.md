---
description: Run Micro-Focus from Observer through the framework translation planner and stop before code translation
---

Run Micro-Focus as an application framework translation and stop before code translation.

Read `skills/micro-focus/references/frameworks.md`, `skills/micro-focus/references/no-gates.md`, `skills/micro-focus/references/modes.md`, and `skills/micro-focus/references/phases.md` from this plugin. The depth is `plan`.

Confirm the source folder. Ask once for the target language and for deterministic or LLM mode if the user has not named them. Web frameworks in scope are Spring Boot, Axon Framework, NestJS, React, Django, Flask, and ASP.NET Core. Data engineering frameworks in scope are Databricks, Azure Data Factory, BigQuery Dataform, and Snowflake dbt.

Check `entitlement/ENTITLEMENT.md` and consume one run with `entitlement/entitlement.py` before Observer. If the license check refuses the run, say that a license is $10 a month after 10 free runs, and stop.

Follow the phases through the framework translation planner. Write `PLAN_COMPLETE.md`. Do not start code translation. Do not open a gate, and do not stop because an artifact is incomplete. Record gaps and continue to the next phase.
