"""Writer Agent — materialises the seam PR onto disk.

Reads seam_result from the run directory, writes every translated file
to runs/{run_id}/output/, and emits a write_manifest artifact."""

from __future__ import annotations

from micro_cosmos.langgraph_runtime import FunctionTool, LlmAgent

from micro_cosmos.settings import get_settings
from micro_cosmos.tools.writer_tools import write_output_files


WRITER_INSTRUCTION = """\
You are the Writer Agent. You materialise the seam PR onto disk.

IMPORTANT: Your ONLY tool is write_output_files. Do NOT call submit_seam_translation,
submit_code_review, or any other tool — those belong to different agents.

Call `write_output_files` with:
- source_path: `{source_path?}`
- source_lang: `{source_lang?}`
- target_lang: `{target_lang?}`
- seam_name: `{current_seam?}`
- run_dir: `{run_dir?}`

The tool reads seam_result.json from run_dir, writes all translated files to the project output
directory, and returns a manifest listing each file's path, size, and language.

After the tool returns, respond with its complete JSON result — no markdown fences, no prose.
"""


def build_writer_agent() -> LlmAgent:
    s = get_settings()
    return LlmAgent(
        name="writer_agent",
        model=s.build_llm("fast"),
        description=(
            "Reads the seam_result artifact and writes all translated source files "
            "to the run output directory, producing a write manifest."
        ),
        instruction=WRITER_INSTRUCTION,
        tools=[FunctionTool(write_output_files)],
        output_key="write_manifest",
    )
