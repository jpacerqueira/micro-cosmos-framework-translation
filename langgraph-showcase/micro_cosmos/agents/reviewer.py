"""PR Reviewer Agent — sequential automated code review.

Reads every translated file from the output directory and applies seven
sequential checks (decimal hygiene, import integrity, TODO density,
method coverage, port presence, bracket balance, file coverage).
Emits a review_report artifact consumed by Gate 5."""

from __future__ import annotations

from micro_cosmos.langgraph_runtime import FunctionTool, LlmAgent

from micro_cosmos.settings import get_settings
from micro_cosmos.tools.reviewer_tools import review_output_files


REVIEWER_INSTRUCTION = """\
You are the PR Reviewer Agent. You perform a rigorous automated code review.

Call `review_output_files` with:
- run_dir: `{run_dir?}`
- target_lang: `{target_lang?}`
- source_lang: `{source_lang?}`

The tool runs seven sequential checks across all translated files:
  1. File coverage — translated source files exist (not just port stubs)
  2. Decimal hygiene — no float/double on monetary fields
  3. Import integrity — decimal imports present where used
  4. TODO density — < 40% TODO comment lines per file
  5. Method coverage — each class has at least one method
  6. Port presence — hexagonal port interfaces exist
  7. Structural parse — brace balance in compiled-language files

After the tool returns, respond with its complete JSON result — no markdown fences, no prose.
"""


def build_pr_reviewer_agent() -> LlmAgent:
    s = get_settings()
    return LlmAgent(
        name="pr_reviewer_agent",
        model=s.build_llm("fast"),
        description=(
            "Performs a rigorous sequential code review of every translated file "
            "in the output directory. Reports BLOCKER / MAJOR / MINOR findings."
        ),
        instruction=REVIEWER_INSTRUCTION,
        tools=[FunctionTool(review_output_files)],
        output_key="review_report",
    )
