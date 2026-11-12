# Micro-Focus Claude plugin

This folder is the plugin. It is also the complete plan. A Claude directory submission uses a new Git repository whose root is this folder and nothing else. The micro-cosmos repository is not the submission. `.claude-plugin/plugin.json` sits at the root of that new repository, so the portal plugin path is left empty. The showcase, its examples, and its runs stay out. The new repository can stay private while it is validated at [claude.ai/directory/manage](https://claude.ai/directory/manage) and must be public before the listing goes live. Creating or pushing that remote is a separate step.

## What it is

Micro-Focus is an application framework translation. The publication text in `README.md` and `.claude-plugin/plugin.json` names the frameworks it works with.

Web frameworks: Spring Boot, Axon Framework, NestJS, React, Django, Flask, and ASP.NET Core. On those stacks it also recognises Eventuate, Lagom, MediatR, NServiceBus, and Wolverine.

Data engineering frameworks: Databricks, Azure Data Factory, BigQuery with Dataform, and Snowflake with dbt.

The same lists are in `skills/micro-focus/references/frameworks.md`, which a run reads before it names a framework. An application estate translates onto an application language. A data-engineering estate translates only onto another of those data platforms.

## What a run does

The plugin performs the Micro-Cosmos pipeline tasks on a source folder the user selects. It does not open Gates 1, 2, 3, 4, 4.5, or 5, and it does not stop on an artifact validity check. A thin artifact is still written, the gap goes in `gaps.md`, and the next phase starts.

The phases, in order, are:

1. Observer writes `ir_graph.json`.
2. Cartographer writes `bounded_context_map.json`, `seam.json`, and `work_streams.json`.
3. Architect writes `tnas.json`, including detected framework hints.
4. Security analysis writes `security_report.json`.
5. The framework translation planner writes `feature_specs.json` and `framework_translation_plan.md`. This is the planning step after security and before any code is translated.
6. Code translation is the seam loop: Code Writer, Skeptical Review, Test Review, Functional Review, then the translated tree. Up to 3 review passes per seam, then the best result is kept. Translated files go under `reports/<project>_<target>/`. The source tree is not overwritten.

`/micro-focus:plan` runs phases 1 through 5 and stops before code translation.

`/micro-focus:translate` runs all six phases and stops when the translated tree exists. It does not wait for a PR gate.

Each command asks once for deterministic or LLM mode. Source language is detected from the folder. Target language is asked once at the start. Deterministic mode uses only what the files and the phase rules state. LLM mode uses the Claude session. If an LLM phase produces nothing usable, the deterministic rules for that phase run, the gap is recorded, and the run continues.

One pipeline start counts as one usage in either mode and on either command. Artifacts go in `<source>/.micro-focus/<run-id>/`.

## License

Anthropic's directory has no price field and does not collect a subscription. The plugin still meters use. The rules are in `entitlement/ENTITLEMENT.md`. The checker is `entitlement/entitlement.py`.

The folder is named `entitlement` because a folder named `license` is the same path as `LICENSE` on a case-insensitive disk. `LICENSE` stays at the plugin root for the listing, and `plugin.json` also sets `"license": "MIT"`.

- The first 10 pipeline runs on an account are free.
- After that, a license costs $10 a month and allows unlimited runs.
- A run with no remaining free uses and no active license does not start.
- The counter is the account ledger at `~/.micro-focus/accounts/<account_id>.json`.
- The $10 is the Micro-Focus license. Claude usage stays on the user's own Claude subscription.

The submitter needs a paid Claude plan (Pro, Max, Team, or Enterprise) to open the developer portal.

## Files

- `PLAN.md` — this plan, including the plugin-only submission repository
- `.claude-plugin/plugin.json` — name `micro-focus`, display name `Micro-Focus`, version `1.0.1`, MIT, author Joao Pedro Afonso Cerqueira. The description states that this is application framework translation and names the web and data-engineering frameworks. The listing icon is the square PNG beside that manifest
- `README.md` — the directory listing. It declares the same frameworks, the two commands, both modes, the source folder, and the license
- `LICENSE` — MIT
- `commands/plan.md` and `commands/translate.md`
- `skills/micro-focus/SKILL.md`
- `skills/micro-focus/references/phases.md`
- `skills/micro-focus/references/modes.md`
- `skills/micro-focus/references/no-gates.md`
- `skills/micro-focus/references/frameworks.md`
- `entitlement/ENTITLEMENT.md` and `entitlement/entitlement.py`

No `.mcp.json`, hooks, `bin/`, or binaries. Dependency risk in the security phase is a read of manifests and config, not a Trivy install.

## To-dos

These are done by the files in this folder:

1. This plan is `PLAN.md`.
2. The manifest, the MIT license, and the directory README are at the plugin root.
3. The six phases, both run modes, the no-gate rule, and the framework lists are under `skills/micro-focus/references/`.
4. The plan and translate commands and the `micro-focus` skill are in this folder.
5. The 10 free runs and the $10 monthly license are in `entitlement/`.
6. This file records that directory submission uses a new Git repository whose root is only the plugin.
