"""Extensible registry of ETL scheduler task-graph parsers.

Azure/Databricks estates can be orchestrated by more than one scheduler
format — a real estate might use a Databricks Asset Bundle for job/pipeline
management, Azure Data Factory for cross-workspace orchestration, or (per
Joao, 2026-08-06) Databricks' own native job cron schedules, Microsoft
Fabric's pipelines, or others not yet supported here. Rather than hardcode
an if/elif per format, every known parser is tried and its results merged —
this is the extension point for adding a new scheduler format later: add
its (detect_fn, parse_fn) pair to _SCHEDULERS.

Every parser returns the same shape, so Cartographer and seam detection can
treat any scheduler's task graph identically regardless of which format(s)
an estate actually uses:
    {"tasks": {task_key: {"job": str, "kind": str,
                           "depends_on": [task_key, ...],
                           "owns_files": [resolved absolute Path, ...]}}}
"""

from __future__ import annotations

from micro_cosmos.tools.adf_scheduler_tools import detect_adf_scheduler, parse_adf_scheduler
from micro_cosmos.tools.databricks_bundle_tools import detect_databricks_bundle, parse_databricks_bundle

_SCHEDULERS = (
    (detect_databricks_bundle, parse_databricks_bundle),
    (detect_adf_scheduler, parse_adf_scheduler),
)


def discover_task_graph(source_path: str) -> dict:
    """Merge task graphs from every scheduler format detected in source_path.

    Task keys are assumed unique across schedulers within one estate — if two
    formats ever produced a colliding key, the later scheduler in
    _SCHEDULERS wins, same last-write-wins behaviour as within a single
    parser's own activities/tasks dict.
    """
    merged_tasks: dict[str, dict] = {}
    for detect, parse in _SCHEDULERS:
        if detect(source_path):
            merged_tasks.update(parse(source_path).get("tasks", {}))
    return {"tasks": merged_tasks}


def detect_any_scheduler(source_path: str) -> bool:
    return any(detect(source_path) for detect, _ in _SCHEDULERS)
