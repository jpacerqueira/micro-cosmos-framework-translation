"""Mechanical ETL project translation.

Reads models out of a Dataform, dbt, or Databricks estate and writes a
complete project for one of the other two platforms. SQL is rewritten
only where the dialect difference is mechanical (date helpers, null
helpers, and cross-model references). PySpark files that contain no SQL
become a documented table so the destination project still has a task
for that step.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from micro_cosmos.etl.catalog import detect_etl_platform

_SKIP_DIRS = {
    ".git", "node_modules", "target", "build", ".venv", "venv",
    "__pycache__", ".mypy_cache", ".pytest_cache", "dist",
}
_MAX_MODELS = 40
_MAX_SQL_CHARS = 20_000

_CATALOG = "retail"
_SCHEMA = "analytics"


@dataclass
class EtlModel:
    name: str
    sql: str
    deps: list[str] = field(default_factory=list)
    description: str = ""
    source_file: str = ""
    kind: str = "sql"


def build_translation_files(source_path: str, target_lang: str) -> list[dict]:
    """Return ``{path, content}`` files for the destination project."""
    source_platform, models = load_models(source_path)
    if target_lang not in ("databricks", "bigquery_dataform", "snowflake_dbt"):
        return []
    if target_lang == source_platform:
        return []
    models = _order_models(models)
    if target_lang == "databricks":
        return _emit_databricks(models, source_platform, source_path)
    if target_lang == "bigquery_dataform":
        return _emit_dataform(models, source_platform, source_path)
    return _emit_dbt(models, source_platform, source_path)


def write_translation(files: list[dict], dest_dir: Path) -> list[str]:
    """Write a translation file list. Rejects paths that escape ``dest_dir``."""
    written: list[str] = []
    root = dest_dir.resolve()
    root.mkdir(parents=True, exist_ok=True)
    for item in files:
        rel = str(item.get("path", "")).lstrip("/").replace("\\", "/")
        if not rel or rel.startswith("../") or "/../" in f"/{rel}":
            continue
        dest = (root / rel).resolve()
        if root != dest and root not in dest.parents:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(item.get("content", ""), encoding="utf-8")
        written.append(rel)
    return written


def load_models(source_path: str) -> tuple[str, list[EtlModel]]:
    platform = detect_etl_platform(source_path) or ""
    root = Path(source_path)
    if platform == "bigquery_dataform":
        models = _load_dataform(root)
    elif platform == "snowflake_dbt":
        models = _load_dbt(root)
    elif platform == "databricks":
        models = _load_databricks(root)
    else:
        models = []
    if not models:
        models = [_placeholder(platform or "unknown", root)]
    sql_models = [model for model in models if model.kind == "sql"]
    steps = [model for model in models if model.kind != "sql"]
    return platform, _unique_names(sql_models + steps)[:_MAX_MODELS]


def rewrite_sql(sql: str, source_platform: str, target_platform: str, model_names: set[str]) -> str:
    """Rewrite refs and a small set of dialect functions. Leaves the rest of the SQL intact."""
    text = sql.strip()
    text = _replace_refs(text, target_platform, model_names)

    if target_platform == "bigquery_dataform":
        text = _to_bigquery(text)
    elif target_platform == "snowflake_dbt":
        text = _to_snowflake(text)
    elif target_platform == "databricks":
        text = _to_databricks(text)
    return text.strip() + "\n"


def _replace_refs(text: str, target_platform: str, model_names: set[str]) -> str:
    def _dataform_ref(match: re.Match) -> str:
        return _ref_token(match.group(1), target_platform)

    def _dbt_ref(match: re.Match) -> str:
        return _ref_token(match.group(1), target_platform)

    def _dbt_source(match: re.Match) -> str:
        name = _safe_name(match.group(1))
        if name in model_names:
            return _ref_token(name, target_platform)
        if target_platform == "bigquery_dataform":
            return f"`retail_raw.{name}`"
        if target_platform == "databricks":
            return f"{_CATALOG}.{_SCHEMA}.{name}"
        return "{{ source('retail', '" + name + "') }}"

    text = re.sub(
        r"""\$\{\s*ref\(\s*["']([^"']+)["']\s*\)\s*\}""",
        _dataform_ref,
        text,
    )
    text = re.sub(
        r"""\{\{\s*ref\(\s*['"]([^'"]+)['"]\s*\)\s*\}\}""",
        _dbt_ref,
        text,
    )
    text = re.sub(
        r"""\{\{\s*source\(\s*['"][^'"]+['"]\s*,\s*['"]([^'"]+)['"]\s*\)\s*\}\}""",
        _dbt_source,
        text,
    )
    # Bare model names in FROM / JOIN become the target reference form when
    # they are one of this project's models. Longer names are replaced first
    # so a short name cannot eat a longer one.
    for name in sorted(model_names, key=len, reverse=True):
        if len(name) < 3:
            continue
        token = _ref_token(name, target_platform)
        text = re.sub(
            rf"(\b(?:FROM|JOIN)\s+)(`?{re.escape(name)}`?)(\b)",
            lambda m, token=token: f"{m.group(1)}{token}{m.group(3)}",
            text,
            flags=re.IGNORECASE,
        )
    return text


def _ref_token(name: str, target_platform: str) -> str:
    safe = _safe_name(name)
    if target_platform == "bigquery_dataform":
        return '${ref("' + safe + '")}'
    if target_platform == "snowflake_dbt":
        return "{{ ref('" + safe + "') }}"
    return f"{_CATALOG}.{_SCHEMA}.{safe}"


def _to_bigquery(text: str) -> str:
    text = re.sub(r"\bGETDATE\s*\(\s*\)", "CURRENT_TIMESTAMP()", text, flags=re.IGNORECASE)
    text = re.sub(r"\bISNULL\s*\(", "IFNULL(", text, flags=re.IGNORECASE)
    text = re.sub(r"\bNVL\s*\(", "IFNULL(", text, flags=re.IGNORECASE)
    text = re.sub(r"\bLEN\s*\(", "LENGTH(", text, flags=re.IGNORECASE)
    text = re.sub(
        r"DATEADD\s*\(\s*day\s*,\s*(-?\d+)\s*,\s*(?:CURRENT_DATE|CURRENT_TIMESTAMP)\s*\(\s*\)\s*\)",
        lambda m: _date_sub(int(m.group(1))),
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"date_sub\s*\(\s*current_date\s*\(\s*\)\s*,\s*(\d+)\s*\)",
        lambda m: f"DATE_SUB(CURRENT_DATE(), INTERVAL {m.group(1)} DAY)",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"DATEDIFF\s*\(\s*day\s*,\s*(?P<start>.+?)\s*,\s*(?P<end>[A-Za-z_][\w.]*\s*\([^()]*\))\s*\)",
        r"DATE_DIFF(\g<end>, \g<start>, DAY)",
        text,
        flags=re.IGNORECASE,
    )
    return text


def _to_snowflake(text: str) -> str:
    text = re.sub(
        r"DATE_SUB\s*\(\s*CURRENT_DATE\s*\(\s*\)\s*,\s*INTERVAL\s+(\d+)\s+DAY\s*\)",
        r"DATEADD(day, -\1, CURRENT_DATE())",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"date_sub\s*\(\s*current_date\s*\(\s*\)\s*,\s*(\d+)\s*\)",
        r"DATEADD(day, -\1, CURRENT_DATE())",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"\bGETDATE\s*\(\s*\)", "CURRENT_TIMESTAMP()", text, flags=re.IGNORECASE)
    text = re.sub(r"\bIFNULL\s*\(", "NVL(", text, flags=re.IGNORECASE)
    text = re.sub(r"\bISNULL\s*\(", "NVL(", text, flags=re.IGNORECASE)
    text = re.sub(r"\bLENGTH\s*\(", "LEN(", text, flags=re.IGNORECASE)
    return text


def _to_databricks(text: str) -> str:
    text = re.sub(r"\bGETDATE\s*\(\s*\)", "current_timestamp()", text, flags=re.IGNORECASE)
    text = re.sub(r"\bIFNULL\s*\(", "coalesce(", text, flags=re.IGNORECASE)
    text = re.sub(r"\bISNULL\s*\(", "coalesce(", text, flags=re.IGNORECASE)
    text = re.sub(r"\bNVL\s*\(", "coalesce(", text, flags=re.IGNORECASE)
    text = re.sub(r"\bLEN\s*\(", "length(", text, flags=re.IGNORECASE)
    text = re.sub(
        r"DATE_SUB\s*\(\s*CURRENT_DATE\s*\(\s*\)\s*,\s*INTERVAL\s+(\d+)\s+DAY\s*\)",
        r"date_sub(current_date(), \1)",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"DATEADD\s*\(\s*day\s*,\s*(-?\d+)\s*,\s*(?:current_timestamp|CURRENT_DATE|CURRENT_TIMESTAMP)\s*\(\s*\)\s*\)",
        lambda m: _spark_date_add(int(m.group(1))),
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"DATEDIFF\s*\(\s*day\s*,\s*(?P<start>.+?)\s*,\s*(?P<end>[A-Za-z_][\w.]*\s*\([^()]*\))\s*\)",
        r"datediff(\g<end>, \g<start>)",
        text,
        flags=re.IGNORECASE,
    )
    return text


def _date_sub(days: int) -> str:
    if days < 0:
        return f"DATE_SUB(CURRENT_DATE(), INTERVAL {abs(days)} DAY)"
    if days > 0:
        return f"DATE_ADD(CURRENT_DATE(), INTERVAL {days} DAY)"
    return "CURRENT_DATE()"


def _spark_date_add(days: int) -> str:
    if days < 0:
        return f"date_sub(current_date(), {abs(days)})"
    if days > 0:
        return f"date_add(current_date(), {days})"
    return "current_date()"


def _load_dataform(root: Path) -> list[EtlModel]:
    models: list[EtlModel] = []
    for path in _candidate_files(root, {".sqlx"}):
        text = _read_limited(path)
        if not text:
            continue
        config_match = re.search(r"config\s*\{(.*?)\}", text, flags=re.DOTALL)
        config = config_match.group(1) if config_match else ""
        body = text[config_match.end():].strip() if config_match else text.strip()
        name = _config_string(config, "name") or path.stem
        deps = _config_list(config, "dependencies")
        deps += re.findall(r"""\$\{\s*ref\(\s*["']([^"']+)["']\s*\)\s*\}""", body)
        description = _config_string(config, "description") or f"Dataform model {name}"
        models.append(EtlModel(
            name=_safe_name(name),
            sql=body[:_MAX_SQL_CHARS],
            deps=[_safe_name(d) for d in deps],
            description=description,
            source_file=_rel(root, path),
        ))
    return models


def _load_dbt(root: Path) -> list[EtlModel]:
    models: list[EtlModel] = []
    for path in _candidate_files(root, {".sql"}):
        rel = _rel(root, path)
        # dbt models live under models/. SQL elsewhere (seeds, analyses) stays out.
        if not rel.startswith("models/") and "/models/" not in f"/{rel}":
            continue
        text = _read_limited(path)
        if not text:
            continue
        body = re.sub(r"\{\{\s*config\(.*?\)\s*\}\}", "", text, flags=re.DOTALL).strip()
        deps = re.findall(r"""\{\{\s*ref\(\s*['"]([^'"]+)['"]\s*\)\s*\}\}""", text)
        deps += re.findall(
            r"""\{\{\s*source\(\s*['"][^'"]+['"]\s*,\s*['"]([^'"]+)['"]\s*\)\s*\}\}""",
            text,
        )
        models.append(EtlModel(
            name=_safe_name(path.stem),
            sql=body[:_MAX_SQL_CHARS],
            deps=[_safe_name(d) for d in deps],
            description=f"dbt model {path.stem}",
            source_file=rel,
        ))
    return models


def _load_databricks(root: Path) -> list[EtlModel]:
    models: list[EtlModel] = []
    for path in _candidate_files(root, {".py", ".sql", ".ipynb"}):
        rel = _rel(root, path)
        if _skip_source(rel):
            continue
        text = _read_limited(path)
        if not text:
            continue
        blocks = _sql_blocks(path, text)
        if blocks:
            for index, sql in enumerate(blocks):
                suffix = "" if index == 0 else f"_{index + 1}"
                models.append(EtlModel(
                    name=_safe_name(f"{path.stem}{suffix}"),
                    sql=sql[:_MAX_SQL_CHARS],
                    description=f"SQL extracted from Databricks source {rel}",
                    source_file=rel,
                ))
            continue
        if path.suffix.lower() == ".py" and _looks_like_transform(text):
            models.append(EtlModel(
                name=_safe_name(path.stem),
                sql=(
                    f"SELECT '{_safe_name(path.stem)}' AS pipeline_step, "
                    "'pyspark' AS source_kind"
                ),
                description=(
                    f"PySpark step from {rel}. No spark.sql() string was found; "
                    "the table records the step so the destination job still schedules it."
                ),
                source_file=rel,
                kind="step",
            ))
    _attach_name_deps(models)
    return models


def _sql_blocks(path: Path, text: str) -> list[str]:
    blocks: list[str] = []
    if path.suffix.lower() == ".sql":
        return [text.strip()] if text.strip() else []
    if path.suffix.lower() == ".ipynb":
        try:
            notebook = json.loads(text)
        except json.JSONDecodeError:
            return []
        for cell in notebook.get("cells", []):
            source = cell.get("source", "")
            if isinstance(source, list):
                source = "".join(source)
            stripped = source.strip()
            if stripped.startswith("%sql"):
                blocks.append(stripped.split("\n", 1)[1] if "\n" in stripped else "")
        return [b.strip() for b in blocks if b.strip()]

    cells = re.split(r"^# COMMAND ----------\s*$", text, flags=re.MULTILINE)
    for cell in cells:
        if "# MAGIC %sql" not in cell:
            continue
        lines: list[str] = []
        started = False
        for line in cell.splitlines():
            if not started:
                if line.strip() in ("# MAGIC %sql", "# MAGIC %sql "):
                    started = True
                continue
            if line.startswith("# MAGIC "):
                lines.append(line[len("# MAGIC "):])
            elif line.startswith("# MAGIC"):
                lines.append(line[len("# MAGIC"):])
            else:
                # Some notebooks keep the SQL body as plain lines after the
                # magic marker instead of prefixing every line with "# MAGIC ".
                lines.append(line)
        body = "\n".join(lines).strip()
        if body:
            blocks.append(body)

    for match in re.finditer(
        "spark\\.sql\\(\\s*[fFrRbB]*(?P<quote>'''|\"\"\")(?P<body>.*?)(?P=quote)",
        text,
        flags=re.DOTALL,
    ):
        body = match.group("body").strip()
        if body:
            blocks.append(body)
    return blocks


def _attach_name_deps(models: list[EtlModel]) -> None:
    names = {m.name for m in models}
    for model in models:
        found = set(model.deps)
        for other in names:
            if other == model.name or len(other) < 3:
                continue
            if re.search(rf"\b{re.escape(other)}\b", model.sql):
                found.add(other)
        model.deps = sorted(found)


def _order_models(models: list[EtlModel]) -> list[EtlModel]:
    by_name = {m.name: m for m in models}
    deps = {
        m.name: [d for d in m.deps if d in by_name and d != m.name]
        for m in models
    }
    remaining = set(by_name)
    ordered: list[EtlModel] = []
    while remaining:
        ready = sorted(
            name for name in remaining
            if not any(dep in remaining for dep in deps[name])
        )
        if not ready:
            name = sorted(remaining)[0]
            deps[name] = []
            ready = [name]
        for name in ready:
            remaining.remove(name)
            ordered.append(by_name[name])
    seen: set[str] = set()
    for model in ordered:
        model.deps = list(dict.fromkeys(d for d in model.deps if d in seen))
        seen.add(model.name)
    return ordered


def _emit_databricks(models: list[EtlModel], source_platform: str, source_path: str) -> list[dict]:
    names = {m.name for m in models}
    sql_files: list[dict] = []
    task_blocks: list[str] = []
    for model in models:
        sql = rewrite_sql(model.sql, source_platform, "databricks", names)
        wrapped = _wrap_create(sql, f"{_CATALOG}.{_SCHEMA}.{model.name}")
        header = (
            f"-- {model.description}\n"
            f"-- source: {model.source_file}\n"
            f"-- migrated from {source_platform or 'unknown'} to Databricks\n"
        )
        rel = f"src/sql/{model.name}.sql"
        sql_files.append({"path": rel, "content": header + wrapped})
        depends = ""
        if model.deps:
            dep_lines = "\n".join(f"            - task_key: {dep}" for dep in model.deps)
            depends = f"\n          depends_on:\n{dep_lines}"
        task_blocks.append(
            f"        - task_key: {model.name}{depends}\n"
            f"          sql_task:\n"
            f"            file:\n"
            f"              path: ../{rel}\n"
            f"            warehouse_id: ${{var.warehouse_id}}\n"
        )
    job = (
        "resources:\n"
        "  jobs:\n"
        "    migrated_etl:\n"
        "      name: migrated_etl\n"
        "      tasks:\n"
        + "".join(task_blocks)
    )
    bundle = (
        "bundle:\n"
        "  name: migrated_etl\n"
        "\n"
        "include:\n"
        "  - resources/*.yml\n"
        "\n"
        "variables:\n"
        "  warehouse_id:\n"
        "    description: SQL warehouse that runs the migrated tasks\n"
        "  catalog:\n"
        "    default: retail\n"
        "  schema:\n"
        "    default: analytics\n"
        "\n"
        "targets:\n"
        "  dev:\n"
        "    mode: development\n"
        "    default: true\n"
        "    workspace:\n"
        "      host: https://company.databricks.com\n"
    )
    return [
        {"path": "databricks.yml", "content": bundle},
        {"path": "resources/migrated_etl.job.yml", "content": job},
        *sql_files,
        {"path": "migration_manifest.json", "content": _manifest(source_platform, "databricks", source_path, models)},
        {"path": "README.md", "content": _readme(source_platform, "databricks", models)},
    ]


def _emit_dataform(models: list[EtlModel], source_platform: str, source_path: str) -> list[dict]:
    names = {m.name for m in models}
    files = [{
        "path": "workflow_settings.yaml",
        "content": (
            "defaultProject: retail-analytics\n"
            "defaultLocation: US\n"
            "defaultDataset: analytics\n"
            "defaultAssertionDataset: analytics_assertions\n"
            "dataformCoreVersion: 3.0.0\n"
        ),
    }]
    for model in models:
        sql = rewrite_sql(model.sql, source_platform, "bigquery_dataform", names)
        deps = ""
        if model.deps:
            inner = ", ".join(f'"{dep}"' for dep in model.deps)
            deps = f"\n  dependencies: [{inner}],"
        description = model.description.replace('"', "'")
        content = (
            "config {\n"
            '  type: "table",\n'
            '  schema: "analytics",\n'
            f'  name: "{model.name}",{deps}\n'
            f'  description: "{description}"\n'
            "}\n"
            "\n"
            f"{sql}"
        )
        files.append({"path": f"definitions/{model.name}.sqlx", "content": content})
    files.append({
        "path": "migration_manifest.json",
        "content": _manifest(source_platform, "bigquery_dataform", source_path, models),
    })
    files.append({
        "path": "README.md",
        "content": _readme(source_platform, "bigquery_dataform", models),
    })
    return files


def _emit_dbt(models: list[EtlModel], source_platform: str, source_path: str) -> list[dict]:
    names = {m.name for m in models}
    files = [
        {
            "path": "dbt_project.yml",
            "content": (
                "name: migrated_etl\n"
                'version: "1.0.0"\n'
                "profile: snowflake_migrated\n"
                "model-paths: [\"models\"]\n"
                "models:\n"
                "  migrated_etl:\n"
                "    +materialized: table\n"
            ),
        },
        {
            "path": "profiles.yml.example",
            "content": (
                "snowflake_migrated:\n"
                "  target: dev\n"
                "  outputs:\n"
                "    dev:\n"
                "      type: snowflake\n"
                "      account: \"{{ env_var('SNOWFLAKE_ACCOUNT') }}\"\n"
                "      user: \"{{ env_var('SNOWFLAKE_USER') }}\"\n"
                "      role: TRANSFORMER\n"
                "      database: RETAIL\n"
                "      schema: ANALYTICS\n"
                "      warehouse: MIGRATION_WH\n"
            ),
        },
    ]
    for model in models:
        sql = rewrite_sql(model.sql, source_platform, "snowflake_dbt", names)
        content = (
            "{{ config(materialized='table') }}\n"
            f"-- {model.description}\n"
            f"-- source: {model.source_file}\n"
            "\n"
            f"{sql}"
        )
        files.append({"path": f"models/marts/{model.name}.sql", "content": content})
    files.append({
        "path": "migration_manifest.json",
        "content": _manifest(source_platform, "snowflake_dbt", source_path, models),
    })
    files.append({
        "path": "README.md",
        "content": _readme(source_platform, "snowflake_dbt", models),
    })
    return files


def _wrap_create(sql: str, table: str) -> str:
    without_comments = re.sub(r"(?m)^\s*--.*\n", "", sql).lstrip().lower()
    if without_comments.startswith(("create ", "insert ", "merge ")):
        return sql if sql.endswith("\n") else sql + "\n"
    return f"CREATE OR REPLACE TABLE {table} AS\n{sql if sql.endswith(chr(10)) else sql + chr(10)}"


def _manifest(source_platform: str, target_platform: str, source_path: str, models: list[EtlModel]) -> str:
    payload = {
        "source_platform": source_platform,
        "target_platform": target_platform,
        "source_path": str(source_path),
        "models": [
            {"name": m.name, "source_file": m.source_file, "depends_on": m.deps}
            for m in models
        ],
    }
    return json.dumps(payload, indent=2) + "\n"


def _readme(source_platform: str, target_platform: str, models: list[EtlModel]) -> str:
    from micro_cosmos.etl.catalog import ETL_PLATFORMS
    source_label = ETL_PLATFORMS.get(source_platform, {}).get("label", source_platform or "unknown")
    target_label = ETL_PLATFORMS.get(target_platform, {}).get("label", target_platform)
    rows = "\n".join(
        f"| `{m.name}` | `{m.source_file}` | {', '.join(m.deps) or '—'} |"
        for m in models
    )
    return (
        f"# {target_label}\n"
        "\n"
        f"Migrated from **{source_label}** to **{target_label}** by Micro-Cosmos.\n"
        "\n"
        "This is an ETL estate. It maps only to the other data platforms "
        "(Databricks, BigQuery + Dataform, Snowflake + dbt), never to a "
        "web or Java application language, and never back onto itself.\n"
        "\n"
        "## Models\n"
        "\n"
        "| Model | Source file | Depends on |\n"
        "|-------|-------------|-------------|\n"
        f"{rows}\n"
    )


def _placeholder(platform: str, root: Path) -> EtlModel:
    return EtlModel(
        name="migrated_pipeline",
        sql="SELECT 'migrated_pipeline' AS pipeline_step",
        description=f"No SQL models were found under {root.name} ({platform}).",
        source_file=root.name,
    )


def _candidate_files(root: Path, suffixes: set[str]):
    if not root.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in _SKIP_DIRS and not d.startswith(".")
        ]
        for name in filenames:
            path = Path(dirpath) / name
            if path.suffix.lower() in suffixes:
                yield path


def _skip_source(rel: str) -> bool:
    parts = rel.split("/")
    if any(part in ("tests", "test", "__pycache__") for part in parts):
        return True
    base = parts[-1]
    if base in ("__init__.py", "conftest.py"):
        return True
    if base.startswith("test_") or base.endswith("_test.py"):
        return True
    return False


def _looks_like_transform(text: str) -> bool:
    return "def " in text and ("spark" in text.lower() or "dataframe" in text.lower())


def _read_limited(path: Path) -> str:
    try:
        if path.stat().st_size > 400_000:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _safe_name(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", name).strip("_").lower()
    if not slug:
        slug = "model"
    if slug[0].isdigit():
        slug = f"model_{slug}"
    return slug[:80]


def _unique_names(models: list[EtlModel]) -> list[EtlModel]:
    seen: dict[str, int] = {}
    for model in models:
        count = seen.get(model.name, 0)
        seen[model.name] = count + 1
        if count:
            model.name = _safe_name(f"{model.name}_{count + 1}")
    return models


def _config_string(config: str, key: str) -> str:
    match = re.search(rf'{key}\s*:\s*"([^"]*)"', config)
    if match:
        return match.group(1).strip()
    match = re.search(rf"{key}\s*:\s*'([^']*)'", config)
    return match.group(1).strip() if match else ""


def _config_list(config: str, key: str) -> list[str]:
    match = re.search(rf"{key}\s*:\s*\[(.*?)\]", config, flags=re.DOTALL)
    if not match:
        return []
    return re.findall(r"""["']([^"']+)["']""", match.group(1))
