"""Observer Agent — reads source code and produces a semantic IR property graph."""

from __future__ import annotations

from micro_cosmos.langgraph_runtime import FunctionTool, LlmAgent

from micro_cosmos.settings import get_settings
from micro_cosmos.tools.source_tools import list_source_files, read_source_file
from micro_cosmos.tools.observer_tools import submit_observer_output


OBSERVER_INSTRUCTION = """\
You are the Observer Agent. Read the source code and submit detailed semantic observations.
This works for any language: COBOL, Java, Go, Python, PHP, Rust, JavaScript, or anything else.
Rejection constraints: {gate_1_constraints?}

1. Call list_source_files(source_path="{source_path?}", source_lang="{source_lang?}").
   For any truncated file containing critical logic, call read_source_file(file_path=...).

2. Read every file. For every function, method, procedure, subroutine, and class — regardless
   of language — identify:
   - What it does (one clear sentence)
   - Every parameter: its name, data type (infer if not explicit), and what it represents
   - What it returns or produces, including the type

3. Call submit_observer_output with ONLY these two arguments:

   llm_observations=["<insight 1>", ...]
   Up to 15 estate-level insights: business domain, invariants, state machines,
   coupling patterns, technical debt, data flow, external dependencies.

   function_summaries=[
     {
       "name": "<exact class, service, or key method name>",
       "summary": "<one sentence: what it does and why>",
       "inputs": [
         {"name": "<param>", "type": "<data type>", "description": "<what it represents>"}
       ],
       "output": "<return type and description of what is produced>"
     }
   ]
   Include: all classes/interfaces, all public/protected methods on service and controller
   classes, and any methods containing core business logic. Omit getters, setters,
   constructors, toString/equals/hashCode, and simple accessors. Maximum 60 entries.
   For languages without explicit types (COBOL, Python 2, JavaScript) infer the type
   from context (e.g. "string", "decimal", "boolean", "customer record").

   Do NOT pass source_path or source_lang — the tool reads them from session state automatically.

Respond with the submit_observer_output result only. No prose. No markdown.
"""


def build_observer_agent() -> LlmAgent:
    s = get_settings()
    return LlmAgent(
        name="observer_agent",
        model=s.build_llm("reasoning"),
        description=(
            "Reads source files and produces semantic observations that enrich "
            "the IR property graph built by the deterministic symbolic parser."
        ),
        instruction=OBSERVER_INSTRUCTION,
        tools=[
            FunctionTool(list_source_files),
            FunctionTool(read_source_file),
            FunctionTool(submit_observer_output),
        ],
        output_key="ir_graph",
    )
