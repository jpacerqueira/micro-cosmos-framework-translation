---
name: claude-pluggin-directory
description: Micro-Focus is published as a Claude directory plugin from its own public repo, with a square listing icon and no installer-credential reads (2026-10-14)
metadata:
  type: project
---

Joao asked for the LangGraph showcase pipeline to become a Claude directory plugin. The plugin lives in this folder at `claude-pluggin/`. The directory submission is not this monorepo. It is the public repository `jpacerqueira/micro-focus-claude-pluggin`, whose root is the plugin (`.claude-plugin/plugin.json` at the top, portal plugin path left empty). A local clone of that repo is `public-git/micro-focus-claude-pluggin`.

## What the plugin is

It is an application framework translation. Claude follows the showcase phases on a source folder the user selects. It does not call `micro-cosmos run` or LangGraph. There is no `.mcp.json`, no `bin/`, and no hooks.

Phases, in order: Observer, Cartographer, Architect, Security analysis, Framework translation planner, Code translation. `/micro-focus:plan` stops after the planner, before any translated code. `/micro-focus:translate` continues through the seam loop and stops when the translated tree exists. Neither command opens Gates 1–5 or stops on `_is_valid_artifact`. A thin artifact is written, the gap goes in `gaps.md`, and the next phase starts.

Deterministic mode uses only what the files and the phase rules state. LLM mode uses the Claude session. If an LLM phase produces nothing usable, the deterministic rules for that phase run and the run continues. One pipeline start is one usage in either mode.

Web frameworks named in the listing: Spring Boot, Axon Framework, NestJS, React, Django, Flask, ASP.NET Core, plus Eventuate, Lagom, MediatR, NServiceBus, and Wolverine. Data engineering frameworks: Databricks, Azure Data Factory, BigQuery with Dataform, and Snowflake with dbt. The same lists are in `skills/micro-focus/references/frameworks.md`. An application estate translates onto an application language. A data-engineering estate translates only onto another of those platforms.

The first 10 runs on an account are free. After that the license is $10 a month. Anthropic's directory does not collect that fee. The rules and the checker are in `entitlement/`, not a folder named `license`, because on a case-insensitive disk that name is the same path as `LICENSE`.

A free Claude account cannot submit to the directory. Submission needs Pro, Max, Team, or Enterprise.

## Directory review, 2026-10-14

Two findings blocked the first submission.

The credential hold ("uses a credential from the user's machine") came from the security phase telling Claude to open `.env` files and copy private values. Removing that instruction clears the hold. Security analysis reads dependency manifest names in the source tree and notes missing authorization checks and string-built SQL. Do not put environment-file reads, secret copying, or `$GITHUB_TOKEN`-style environment reads back into the plugin. If a later feature must receive a value the user chooses to share, pass `${user_config.KEY}` from `plugin.json`. Do not read a credential that is already on the machine.

The icon finding requires a square PNG or JPEG at `.claude-plugin/icon.png`, or an `icon` path in `plugin.json`. Side length 512 to 2048 pixels, under 2 MB. SVG and WebP are rejected. The artwork Joao added under `icon/` was 310×274. The listing file is that artwork padded to 1024×1024. The directory keeps the icon from the first save or submission. Changing the file later does not change the listing icon, so the compliant PNG has to be in the commit that is validated before the first successful submit.

`tests/test_plugin.py` checks the manifest, the framework lists, the two commands, the 10-run then $10 rule, and the icon dimensions. Run it from `claude-pluggin/` with `python3 -m unittest tests.test_plugin`.
