# Deterministic and LLM modes

Ask once, before any phase, unless the user already named the mode. The two values are `deterministic` and `llm`. Record the choice in `run.json`. One pipeline start counts as one usage in either mode.

## Deterministic

Use only what the source files, manifests, and the phase rules state. Do not add a summary, a product name, a business rationale, or a target idiom that is not written in the source. Do not make a second creative pass inside a phase. Framework names come from `frameworks.md` and from a manifest or import you can point at.

## LLM

Use the Claude session this plugin is running in. Perform the same phase tasks: read the source, name the framework, and write the same JSON files. You may add the summaries, seam names, feature titles, and idiomatic target code the phase asks for. Stay inside the frameworks in `frameworks.md`.

If an LLM phase writes nothing usable, or the JSON is missing the keys that phase requires, run that phase again with the deterministic rules, append the gap, and continue. Do not halt for a gate.

## Shared rules

Do not call the Micro-Cosmos web app, LangGraph, or a model server. The source folder stays where the user selected it. Never overwrite a source file. Write only under `<source>/.micro-focus/<run-id>/`.
