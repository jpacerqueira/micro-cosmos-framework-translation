"""Azure Data Factory (ADF) pipeline scheduler parser.

Resolves ADF pipeline JSON (activities + dependsOn) into the same task-graph
shape as databricks_bundle_tools.parse_databricks_bundle() — see
scheduler_tools.py for why that shape is shared across scheduler formats.
An ADF pipeline activity is the real task boundary; its dependsOn is the
real cross-boundary execution order — same reasoning as a Databricks Asset
Bundle job task, just declared in a different scheduler's own format.

ADF pipeline JSON shape (Data Factory Git-integrated export):
    {"name": "BISMasterETL", "properties": {"activities": [
        {"name": "RunBISAnalytics", "type": "DatabricksNotebook",
         "typeProperties": {"notebookPath": "/project_domain/notebooks/01_bis_hub/BISHubAnalytics"},
         "dependsOn": [{"activity": "RunOrderIngestion", "dependencyConditions": ["Succeeded"]}]},
        ...
    ]}}

notebookPath/pythonFile are Databricks *workspace* paths, not filesystem
paths, and different ADF authors mount the workspace differently — some use
a bare project-root prefix ("/project_domain/notebooks/..."), others use
Databricks Repos-style paths ("/Repos/<repo-name>/notebooks/..." — the repo
name is workspace scaffolding, not a real directory on disk). Rather than
special-case either convention, resolution tries the path's full remaining
suffix against the estate root, then progressively drops the leading
segment and retries — this covers both without hardcoding "Repos".
"""

from __future__ import annotations

import json
from pathlib import Path

_LOCATOR_KEYS = ("notebookPath", "pythonFile")


def _load_json(path: Path) -> object:
    # Return type is `object`, not `dict`: json.loads happily returns a list,
    # str, int, float, bool or None for a well-formed non-object document.
    # Callers must narrow the type themselves — see _is_adf_pipeline().
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _is_adf_pipeline(doc: object) -> bool:
    # doc is whatever json.loads returned for an arbitrary *.json file found
    # anywhere under the estate — a list, string, number, bool or null are all
    # valid JSON documents, not just objects. _find_pipeline_files() scans the
    # whole tree (build output, test reports, everything), so a non-dict root
    # is routine, not exceptional, and must not raise.
    if not isinstance(doc, dict):
        return False
    props = doc.get("properties")
    return isinstance(props, dict) and isinstance(props.get("activities"), list)


def _find_pipeline_files(source_path: str) -> list[Path]:
    root = Path(source_path)
    if not root.is_dir():
        return []
    return [f for f in root.rglob("*.json") if _is_adf_pipeline(_load_json(f))]


def detect_adf_scheduler(source_path: str) -> bool:
    return bool(_find_pipeline_files(source_path))


def _resolve_workspace_path(source_root: Path, workspace_path: str) -> Path | None:
    stripped = workspace_path.split(":", 1)[-1].lstrip("/")  # strip any "dbfs:" scheme too
    if not stripped:
        return None
    parts = stripped.split("/")
    # Try the full suffix first, then drop leading segments one at a time —
    # handles both a bare project-root prefix and Databricks Repos-style
    # "/Repos/<repo-name>/..." paths without hardcoding either.
    for start in range(len(parts) - 1):
        base = source_root / "/".join(parts[start:])
        for candidate in (base, base.with_suffix(".py"), base.with_suffix(".ipynb")):
            if candidate.is_file():
                return candidate.resolve()
    return None


def parse_adf_scheduler(source_path: str) -> dict:
    """Parse every ADF pipeline JSON under source_path into a task graph.

    Returns:
        {"tasks": {activity_name: {"job": pipeline_name, "kind": activity_type,
                                    "depends_on": [activity_name, ...],
                                    "owns_files": [resolved absolute Path, ...]}}}
    Multiple activities may point at the same file (a real pattern in
    hand-authored ADF pipelines that haven't split notebooks per activity
    yet), and some activities may reference a path with no on-disk
    equivalent (e.g. a dbfs:/ scratch script never checked into source
    control) — both are tolerated, not errors. Downstream bounded-context
    assignment naturally collapses shared files to whichever task is
    applied last; unresolved activities still surface in the task graph
    with an empty owns_files, so their place in the depends_on chain is
    never lost even when no file backs them.
    """
    source_root = Path(source_path)
    tasks: dict[str, dict] = {}
    for pf in _find_pipeline_files(source_path):
        doc = _load_json(pf)
        pipeline_name = doc.get("name", pf.stem)
        activities = doc.get("properties", {}).get("activities", []) or []
        for act in activities:
            act_name = act.get("name")
            if not act_name:
                continue
            depends_on = [
                d.get("activity") for d in (act.get("dependsOn") or []) if d.get("activity")
            ]
            owns: list[Path] = []
            type_props = act.get("typeProperties") or {}
            for key in _LOCATOR_KEYS:
                locator = type_props.get(key)
                if locator:
                    resolved = _resolve_workspace_path(source_root, locator)
                    if resolved:
                        owns.append(resolved)
            tasks[act_name] = {
                "job": pipeline_name,
                "kind": act.get("type", "unknown"),
                "depends_on": depends_on,
                "owns_files": owns,
            }
    return {"tasks": tasks}
