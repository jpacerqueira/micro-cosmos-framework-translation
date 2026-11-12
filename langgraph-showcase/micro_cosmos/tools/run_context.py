"""Shared, concurrency-safe home for the "current run directory" tool-context
global. Replaces three independent process-wide module globals (in
coder_tools.py, coding_loop_tools.py, source_tools.py) that were flagged as
an unresolved known issue in CLAUDE.md: two simultaneous LLM runs would race
on a plain module-level string. A contextvars.ContextVar is captured per
asyncio.Task at creation time — since Run.start() gives each run its own
Task, two concurrent runs naturally get independent values with no locking.
"""

from __future__ import annotations

import contextvars

_run_dir: contextvars.ContextVar[str] = contextvars.ContextVar("run_dir", default="")


def set_run_dir(run_dir: str) -> None:
    _run_dir.set(run_dir)


def get_run_dir() -> str:
    return _run_dir.get()
