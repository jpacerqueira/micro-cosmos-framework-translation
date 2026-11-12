---
name: micro-cosmos
description: Translate an application framework from a source folder with the Micro-Cosmos pipeline. Use when the user asks to analyse a codebase, plan a framework translation, or translate web or data-engineering source, including a stop before code translation.
---

Micro-Cosmos is an application framework translation. It runs the LangGraph pipeline in `micro_cosmos/`, including the AST, tree-sitter, and regex analyzers. Web frameworks: Spring Boot, Axon Framework, NestJS, React, Django, Flask, and ASP.NET Core. Data engineering frameworks: Databricks, Azure Data Factory, BigQuery Dataform, and Snowflake dbt. Read `references/frameworks.md` before naming a framework.

When the user asks for a plan, a stop before code translation, or analysis only, set the depth to `plan`. When the user asks to translate the code, set the depth to `translate`. If they did not choose, ask once.

Then:

1. Read `references/no-gates.md`, `references/modes.md`, and `references/phases.md`.
2. Confirm the source folder. Use the folder the user selected. Do not use a folder they did not name.
3. Ask for the target and for `deterministic` or `llm` if either is missing.
4. Check the license in `entitlement/ENTITLEMENT.md` at the plugin root. Run `python3` on `entitlement/entitlement.py` with `consume` and the account ledger path from that file. If the command exits without success, tell the user the price and stop. Do not start a phase.
5. Run `python3 run_pipeline.py` for the depth you set. Plan depth is `pause_after_planning`. Translate depth stops when the translated tree exists and does not open a PR gate.

Write artifacts under `<source>/.micro-cosmos/<run-id>/`. Leave the source files unchanged.
