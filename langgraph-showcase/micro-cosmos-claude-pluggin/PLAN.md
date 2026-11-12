# Micro-Cosmos Claude plugin

This folder is the real Micro-Cosmos plugin. The sibling `claude-pluggin` folder, published as `micro-focus-claude-pluggin`, is the planning guide. This one runs the LangGraph pipeline in `micro_cosmos/`.

The repository for this folder is the private repo `micro-cosmos-claude-pluggin`. Its root is the plugin, so the directory plugin path is left empty. The micro-cosmos monorepo is not the submission repository.

## What a run does

`run_pipeline.py` calls `run_full_pipeline` with `skip_gate_validation`. A thin artifact is kept and the next phase starts. The run does not wait for Gates 1, 2, 3, 4, 4.5, or 5.

`--depth plan` sets `pause_after_planning`. The run uses Observer, Cartographer, Architect, Security, and the Feature Specifier, then stops before code translation. It writes the same plan artifacts as the plan command: `run.json`, the analysis JSON, `framework_translation_plan.md`, `gaps.md`, and `PLAN_COMPLETE.md`.

`--depth translate` runs that same prefix, then the seam loop, and stops when `reports/<project>_<target>/` exists. `stop_after_code_translation` returns before PR Reviewer and Gate 5.

`--mode deterministic` sets `skip_llm` and uses the symbolic analyzers: tree-sitter where a grammar is installed, otherwise the AST and regex parsers in `micro_cosmos/tools/`. `--mode llm` uses the LangGraph agents on those same tools. The model URL and key are passed only when the user types them.

Artifacts go in `<source>/.micro-cosmos/<run-id>/`.

## Frameworks

Web: Spring Boot, Axon Framework, NestJS, React, Django, Flask, ASP.NET Core, plus Eventuate, Lagom, MediatR, NServiceBus, and Wolverine.

Data engineering: Databricks, Azure Data Factory, BigQuery with Dataform, and Snowflake with dbt.

## License

The first 5 runs are free. After that a license is $15 a month. The rules are in `entitlement/ENTITLEMENT.md`. The user supplies the account id.

## Files

- `.claude-plugin/plugin.json` and the square listing icon beside it
- `run_pipeline.py`
- `micro_cosmos/` — the pipeline, including observer, cartographer, architect, security, feature specifier, and the code-translation loop
- `skills/micro-cosmos/` and `commands/plan.md`, `commands/translate.md`
- `PLAN.md` — this plan
