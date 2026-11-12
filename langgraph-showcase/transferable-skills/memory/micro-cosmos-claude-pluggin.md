---
name: micro-cosmos-claude-pluggin
description: Micro-Cosmos Claude plugin runs the LangGraph pipeline; plan stops before code translation and translate stops when the tree exists (2026-10-14)
metadata:
  type: project
---

Joao asked for a second Claude directory plugin, distinct from Micro-Focus. Micro-Focus stays the planning guide in `claude-pluggin/` and in `jpacerqueira/micro-focus-claude-pluggin`. This one is the real pipeline. It lives in `micro-cosmos-claude-pluggin/` and is submitted from its own private repository `jpacerqueira/micro-cosmos-claude-pluggin`, whose root is the plugin.

## Commands

`/micro-cosmos:plan` is `pause_after_planning`. Observer, Cartographer, Architect, Security, and the framework translation planner run, then the driver returns. Code translation does not start. The run folder `<source>/.micro-cosmos/<run-id>/` holds the same plan artifacts as Micro-Focus: `run.json`, `ir_graph.json`, `bounded_context_map.json`, `seam.json`, `work_streams.json`, `tnas.json`, `security_report.json`, `feature_specs.json`, `framework_translation_plan.md`, `gaps.md`, and `PLAN_COMPLETE.md` with the sentence "Code translation did not start."

`/micro-cosmos:translate` runs that same prefix, then the seam loop (Code Writer, Skeptical Review, Test Review, Functional Review, Writer). `stop_after_code_translation` returns once that loop finishes. PR Reviewer and Gate 5 are not opened. The translated tree is `reports/<project>_<target>/`.

Both depths set `skip_gate_validation`. A thin artifact is kept, the gap goes in `gaps.md`, and the next phase starts. Deterministic mode is `skip_llm`. LLM mode uses the LangGraph agents on the same tools. The model URL and key are arguments the user types for that run.

## Engine

`micro_cosmos/` in the plugin is the showcase pipeline, including the AST, tree-sitter, and regex tools. The web UI is not included. Deterministic Writer calls the existing `write_output_files` tool so the seam tree is written from `seam_result.json`. The planner's document is stored as `feature_specs_result.json`; the run record also writes `feature_specs.json`, which is the name the plan command uses.

The same `pause_after_planning`, `skip_gate_validation`, `stop_after_code_translation`, and Writer fallback are in the showcase `micro_cosmos/orchestration/` so the plugin copy and the showcase stay aligned. Defaults leave a normal showcase run on the PR gate.

## Listing

Plugin name `micro-cosmos`, display name Micro-Cosmos, version 1.0.0. Square icon at `.claude-plugin/icon.png`. The listing names the same web and data-engineering frameworks as Micro-Focus. The first 5 runs are free, then $15 a month, checked by `entitlement/entitlement.py` against `<source>/.micro-cosmos/account-ledger.json`. Do not tell the plugin to open environment files or copy private values. The vendored settings object does not load an env file.

`tests/test_plugin.py` checks the two depths, the artifact names, and the icon. Run it from `micro-cosmos-claude-pluggin/` with `python3 -m unittest tests.test_plugin`. A deterministic plan and translate of a small Python folder needs Python 3.13 or older; Python 3.15 cannot build the current pydantic wheels.
