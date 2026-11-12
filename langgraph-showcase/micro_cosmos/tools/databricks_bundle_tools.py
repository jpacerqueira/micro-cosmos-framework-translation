"""Databricks Asset Bundle (DAB) parser.

Resolves a bundle's `databricks.yml` + `resources/*.yml` job/pipeline
definitions into a task dependency graph, with each task linked to the
source files it owns (notebook path, python_wheel package, or a referenced
pipeline's glob-owned transformation files).

Why this exists: Cartographer's `_classify_prog_node` guesses bounded
contexts from directory-path structure, which works for source-code-only
estates but has no signal for how a Databricks project's own ETL scheduler
(the ".job.yml"/".pipeline.yml" resources) actually groups and sequences
work. The bundle's own job/task definitions are a far more reliable seam
signal than path heuristics for this format — a task_key IS the intended
substitution boundary, and `depends_on` IS the real cross-boundary call
graph, both already declared by the estate's own author.
"""

from __future__ import annotations

import glob as _glob
import re
from pathlib import Path


def detect_databricks_bundle(source_path: str) -> bool:
    return (Path(source_path) / "databricks.yml").is_file()


def task_context_label(task_key: str) -> str:
    """Title-case a task_key into a bounded-context/seam label (e.g.
    "notebook_task" -> "NotebookTask"). Shared by cartographer_tools.py and
    seam_tools.py so a task's context label and its seam label always match.

    ADF activity names are typically already PascalCase ("RunCustomer360",
    "IngestFactSalesOrders") with no "-"/"_" to split on — str.title() would
    mangle these (embedded capitals aren't word boundaries to it, so
    "RunCustomer360".title() == "Runcustomer360"). Only split-and-title when
    there's an actual delimiter to split on; otherwise the name is already
    a usable label as-is.
    """
    if re.search(r"[-_]", task_key):
        return "".join(w.title() for w in re.split(r"[-_]", task_key))
    return task_key


def _load_yaml(path: Path) -> dict:
    import yaml  # type: ignore[import]  # PyYAML

    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _resolve_glob(base_dir: Path, pattern: str) -> list[Path]:
    matches = _glob.glob(str(base_dir / pattern), recursive=True)
    return [Path(m).resolve() for m in matches if Path(m).is_file()]


_PIPELINE_ID_REF = re.compile(r"^\$\{resources\.pipelines\.([^.}]+)\.id\}$")


def parse_databricks_bundle(source_path: str) -> dict:
    """Parse a Databricks Asset Bundle into a task graph.

    Returns:
        {
            "tasks": {
                task_key: {
                    "job": job_key,
                    "kind": "notebook" | "python_wheel" | "pipeline" | "unknown",
                    "depends_on": [task_key, ...],
                    "owns_files": [resolved absolute Path, ...],
                }
            },
            "pipelines": {pipeline_key: {"owns_files": [...]}},
        }
    Empty dict values if no `databricks.yml` is found at source_path's root.
    """
    root = Path(source_path)
    bundle_file = root / "databricks.yml"
    if not bundle_file.is_file():
        return {"tasks": {}, "pipelines": {}}

    bundle = _load_yaml(bundle_file)
    resource_files: list[Path] = []
    for pattern in bundle.get("include", []) or []:
        resource_files.extend(Path(p) for p in _glob.glob(str(root / pattern)))

    pipelines: dict[str, dict] = {}
    for rf in resource_files:
        doc = _load_yaml(rf)
        for pkey, pdef in ((doc.get("resources") or {}).get("pipelines") or {}).items():
            owns: list[Path] = []
            for lib in pdef.get("libraries", []) or []:
                inc = (lib.get("glob") or {}).get("include")
                if inc:
                    owns.extend(_resolve_glob(rf.parent, inc))
            pipelines[pkey] = {"owns_files": sorted(set(owns))}

    tasks: dict[str, dict] = {}
    for rf in resource_files:
        doc = _load_yaml(rf)
        for jkey, jdef in ((doc.get("resources") or {}).get("jobs") or {}).items():
            for task in jdef.get("tasks", []) or []:
                task_key = task.get("task_key")
                if not task_key:
                    continue
                depends_on = [
                    d.get("task_key") for d in (task.get("depends_on") or []) if d.get("task_key")
                ]
                owns: list[Path] = []
                kind = "unknown"
                if "notebook_task" in task:
                    kind = "notebook"
                    nb_path = (task["notebook_task"] or {}).get("notebook_path")
                    if nb_path:
                        resolved = (rf.parent / nb_path).resolve()
                        if resolved.is_file():
                            owns.append(resolved)
                elif "python_wheel_task" in task:
                    kind = "python_wheel"
                    pkg = (task["python_wheel_task"] or {}).get("package_name")
                    if pkg:
                        pkg_dir = root / "src" / pkg
                        if pkg_dir.is_dir():
                            owns.extend(p.resolve() for p in pkg_dir.rglob("*.py"))
                elif "pipeline_task" in task:
                    kind = "pipeline"
                    ref = (task["pipeline_task"] or {}).get("pipeline_id", "")
                    m = _PIPELINE_ID_REF.match(ref.strip()) if isinstance(ref, str) else None
                    if m:
                        owns.extend(pipelines.get(m.group(1), {}).get("owns_files", []))
                tasks[task_key] = {
                    "job": jkey,
                    "kind": kind,
                    "depends_on": depends_on,
                    "owns_files": sorted(set(owns)),
                }

    return {"tasks": tasks, "pipelines": pipelines}
