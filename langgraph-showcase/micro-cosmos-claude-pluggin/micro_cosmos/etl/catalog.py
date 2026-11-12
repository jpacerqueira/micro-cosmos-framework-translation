"""Which example maps to which target.

ETL estates (Databricks, BigQuery + Dataform, Snowflake + dbt) translate
only onto the other data platforms. Application estates (Java, COBOL, C#,
web front ends, and anything without an ETL marker) translate only onto
application languages.
"""

from __future__ import annotations

import os
from pathlib import Path

ETL_PLATFORMS: dict[str, dict[str, str]] = {
    "databricks": {
        "id": "databricks",
        "label": "Databricks",
        "family": "etl",
    },
    "bigquery_dataform": {
        "id": "bigquery_dataform",
        "label": "BigQuery + Dataform",
        "family": "etl",
    },
    "snowflake_dbt": {
        "id": "snowflake_dbt",
        "label": "Snowflake + dbt",
        "family": "etl",
    },
}

# Same options the launch form offered before the ETL split, minus the
# data-platform target, which now lives only on ETL estates.
APPLICATION_TARGETS: list[dict[str, str]] = [
    {"id": "java21", "label": "java21"},
    {"id": "python3", "label": "python3"},
    {"id": "go", "label": "go"},
    {"id": "rust", "label": "rust"},
    {"id": "kotlin", "label": "kotlin"},
    {"id": "javascript", "label": "javascript"},
    {"id": "typescript", "label": "typescript"},
    {"id": "csharp", "label": "csharp"},
    {"id": "scala", "label": "scala"},
    {"id": "swift", "label": "swift"},
]

FAMILY_LABELS: dict[str, dict[str, str]] = {
    "etl": {
        "id": "etl",
        "label": "ETL",
        "rule": (
            "Databricks, BigQuery + Dataform, and Snowflake + dbt map only "
            "to the other data platforms. An estate does not map to itself."
        ),
    },
    "application": {
        "id": "application",
        "label": "Web & Java applications",
        "rule": (
            "COBOL, Java, C#, and other application estates map only to "
            "application languages such as java21, python3, go, and kotlin."
        ),
    },
}

_SKIP_DIRS = {
    ".git", "node_modules", "target", "build", ".venv", "venv",
    "__pycache__", ".mypy_cache", ".pytest_cache", "dist",
}


def is_etl_target(target_lang: str) -> bool:
    return (target_lang or "").strip() in ETL_PLATFORMS


def _walk_files(root: Path):
    if not root.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in _SKIP_DIRS and not d.startswith(".")
        ]
        for name in filenames:
            yield Path(dirpath) / name


def _detect_at(root: Path) -> str | None:
    """Classify one directory tree. Does not look at parent folders."""
    if not root.is_dir():
        return None
    has_dataform = False
    has_dbt = False
    has_databricks = False
    for path in _walk_files(root):
        name = path.name.lower()
        suffix = path.suffix.lower()
        if suffix == ".sqlx" or name in ("workflow_settings.yaml", "dataform.json"):
            has_dataform = True
        elif name == "dbt_project.yml":
            has_dbt = True
        elif name in ("databricks.yml", "databricks.yaml", "databricks-requirements.txt"):
            has_databricks = True
        elif suffix == ".json" and not has_databricks:
            try:
                head = path.read_text(encoding="utf-8", errors="ignore")[:4000]
            except OSError:
                head = ""
            if "DatabricksNotebook" in head:
                has_databricks = True
        elif suffix == ".py" and not has_databricks:
            try:
                with path.open(encoding="utf-8", errors="ignore") as fh:
                    first = fh.readline()
            except OSError:
                first = ""
            if "Databricks notebook source" in first:
                has_databricks = True
    if has_dataform:
        return "bigquery_dataform"
    if has_dbt:
        return "snowflake_dbt"
    if has_databricks:
        return "databricks"
    return None


def detect_etl_platform(source_path: str | Path) -> str | None:
    """Return the ETL platform id for this path, or None for an application estate.

    A subfolder inherits its project: markers are checked on the path itself,
    then on each parent, and the walk stops at a directory named ``examples``.
    """
    raw = Path(source_path)
    if not raw.exists():
        return None
    current = raw if raw.is_dir() else raw.parent
    while True:
        # ``examples/`` contains every estate. Scanning it would classify a
        # Java app as Dataform because a sibling project has .sqlx files.
        if current.name == "examples":
            return None
        found = _detect_at(current)
        if found:
            return found
        if current.parent == current:
            return None
        current = current.parent


def allowed_targets(source_path: str | Path) -> list[dict[str, str]]:
    platform = detect_etl_platform(source_path)
    if platform:
        return [ETL_PLATFORMS[key] for key in ETL_PLATFORMS if key != platform]
    return list(APPLICATION_TARGETS)


def classify_example(source_path: str | Path) -> dict:
    """Card metadata: family, source platform, and the targets it is allowed to use."""
    platform = detect_etl_platform(source_path)
    family = "etl" if platform else "application"
    targets = allowed_targets(source_path)
    info = FAMILY_LABELS[family]
    platform_label = ETL_PLATFORMS[platform]["label"] if platform else "Application"
    return {
        "family": family,
        "family_label": info["label"],
        "family_rule": info["rule"],
        "platform": platform or "",
        "platform_label": platform_label,
        "targets": targets,
        "maps_to": ", ".join(t["label"] for t in targets),
    }


def pairing_error(source_path: str | Path, target_lang: str) -> str | None:
    """None when this source may be launched at this target."""
    target = (target_lang or "").strip()
    if not target:
        return "Choose a target."
    platform = detect_etl_platform(source_path)
    if platform:
        source_label = ETL_PLATFORMS[platform]["label"]
        if target == platform:
            return (
                f"{source_label} is already the source platform. "
                "Choose one of the other data platforms."
            )
        if target not in ETL_PLATFORMS:
            others = ", ".join(
                ETL_PLATFORMS[key]["label"] for key in ETL_PLATFORMS if key != platform
            )
            return (
                f"This example is an ETL estate ({source_label}). "
                f"It maps only to other data platforms: {others}."
            )
        return None
    if target in ETL_PLATFORMS:
        return (
            "This example is a web or application estate. "
            "It maps to application languages, not to Databricks, "
            "BigQuery + Dataform, or Snowflake + dbt."
        )
    return None
