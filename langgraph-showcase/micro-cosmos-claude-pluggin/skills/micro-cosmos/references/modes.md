# Deterministic and LLM modes

Ask once, before any phase, unless the user already named the mode. The two values are `deterministic` and `llm`. Record the choice in `run.json`. One pipeline start counts as one usage in either mode.

## Deterministic

`run_pipeline.py --mode deterministic` sets `skip_llm`. Each phase calls the symbolic tool in `micro_cosmos/tools/`: tree-sitter where a grammar is installed, otherwise the AST and regex parsers. The phase writes the same JSON files as LLM mode.

## LLM

`run_pipeline.py --mode llm` uses the LangGraph agents in `micro_cosmos/langgraph_runtime.py` on those same tools. Pass `--llm-base-url` and `--llm-api-key` only with values the user typed for this run.

If an LLM phase writes nothing usable, the pipeline's deterministic fallback fills that artifact, a line is added to `gaps.md`, and the run continues. Do not halt for a gate.

## Shared rules

The source folder stays where the user selected it. Never overwrite a source file. Write only under `<source>/.micro-cosmos/<run-id>/`.
