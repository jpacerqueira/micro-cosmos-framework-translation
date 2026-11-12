"""Pattern Agent — extracts the modern software design patterns implicit in
the source structure: aggregates, domain events, ports, and FSMs."""

from __future__ import annotations

from micro_cosmos.langgraph_runtime import FunctionTool, LlmAgent

from micro_cosmos.settings import get_settings
from micro_cosmos.tools.pattern_tools import extract_domain_model


PATTERN_INSTRUCTION = """\
You are the Pattern Agent. Extract the domain model and enrich it with business meaning.
Rejection constraints: {gate_3_constraints?}

1. Call extract_domain_model(source_path="{source_path?}", source_lang="{source_lang?}").

2. For each aggregate add:
   - "business_description": one sentence — what real-world concept this aggregate owns
   - "invariants": list of rules that must never be violated (e.g. "balance must never go negative")

3. For each FSM add "trigger_descriptions": for each transition, one sentence explaining why it
   fires in business terms (not technical terms).

4. Add a top-level "summary" field: 2–3 sentences written for a human reviewer explaining
   what domain was found, what the key aggregates represent, and why the model is structured
   this way. This is the first thing a reviewer will read before approving the gate.

Respond with the enriched JSON result only. No prose outside the JSON. No markdown.
"""


def build_pattern_agent() -> LlmAgent:
    s = get_settings()
    return LlmAgent(
        name="pattern_agent",
        model=s.build_llm("reasoning"),
        description=(
            "Extracts the domain model — aggregates, events, ports, FSMs — from "
            "the source estate."
        ),
        instruction=PATTERN_INSTRUCTION,
        tools=[FunctionTool(extract_domain_model)],
        output_key="domain_model",
    )
