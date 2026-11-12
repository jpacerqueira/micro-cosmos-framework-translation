"""Cartographer Agent — identifies bounded contexts via three-way voted analysis."""

from __future__ import annotations

from micro_cosmos.langgraph_runtime import FunctionTool, LlmAgent

from micro_cosmos.settings import get_settings
from micro_cosmos.tools.cartographer_tools import analyse_bounded_contexts


CARTOGRAPHER_INSTRUCTION = """\
You are the Cartographer Agent. Map the source estate to bounded contexts.
Rejection constraints: {gate_2_constraints?}

1. Call analyse_bounded_contexts(source_path="{source_path?}", source_lang="{source_lang?}").

2. The tool returns the complete bounded_context_map. Output it EXACTLY as returned.

CRITICAL RULES — validated after you respond; violation causes immediate retry:
- Output the JSON object returned by the tool. Do not invent, summarise, or paraphrase it.
- node_ids must be copied verbatim from the tool response. Never substitute "prog.*",
  "class.*", or any other pattern/glob — every entry must be a real node ID string.
- Do not add, remove, or modify any context in the contexts[] array.
- Do not change node_ids, confidence, or cross_context_calls.
- Do not wrap the output in markdown fences or add any prose outside the JSON.

Respond with the JSON object only.
"""


def build_cartographer_agent() -> LlmAgent:
    s = get_settings()
    return LlmAgent(
        name="cartographer_agent",
        model=s.build_llm("reasoning"),
        description=(
            "Identifies bounded contexts via three-way voted analysis over the IR."
        ),
        instruction=CARTOGRAPHER_INSTRUCTION,
        tools=[FunctionTool(analyse_bounded_contexts)],
        output_key="bounded_context_map",
    )
