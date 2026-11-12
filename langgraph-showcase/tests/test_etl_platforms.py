"""ETL family split: examples, allowed targets, and destination projects.

Databricks, BigQuery + Dataform, and Snowflake + dbt each translate to the
other two platforms. Application estates stay on application languages.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from micro_cosmos.etl.catalog import (
    classify_example,
    detect_etl_platform,
    pairing_error,
)
from micro_cosmos.etl.translate import build_translation_files, write_translation
from micro_cosmos.tools.coder_tools import submit_seam_translation
from micro_cosmos.tools.run_context import set_run_dir

DATAFORM = "examples/bigquery_dataform_retail"
SNOWFLAKE = "examples/snowflake_dbt_retail"
DATABRICKS_NOTEBOOKS = "examples/databricks_adf_notebooks_project"
DATABRICKS_BUNDLE = "examples/databricks_bundle_default_python"
JAVA_APP = "examples/java-springboot-legacy-app"

ETL_EXAMPLES = {
    "bigquery_dataform_retail",
    "snowflake_dbt_retail",
    "databricks_adf_notebooks_project",
    "databricks_adf_project1_profile",
    "databricks_bundle_default_python",
}


def _joined(files: list[dict]) -> str:
    return "\n".join(item["content"] for item in files)


def _by_path(files: list[dict]) -> dict[str, str]:
    return {item["path"]: item["content"] for item in files}


@pytest.mark.parametrize(
    ("path", "platform"),
    [
        (DATAFORM, "bigquery_dataform"),
        (SNOWFLAKE, "snowflake_dbt"),
        (DATABRICKS_NOTEBOOKS, "databricks"),
        (DATABRICKS_BUNDLE, "databricks"),
        ("examples/databricks_adf_project1_profile", "databricks"),
        (JAVA_APP, None),
        ("examples/legacy_estate", None),
        ("examples/cobol-mainframe-banking-teller", None),
    ],
)
def test_platform_detection(path: str, platform: str | None) -> None:
    assert detect_etl_platform(path) == platform


def test_every_example_lands_in_one_family() -> None:
    root = Path("examples")
    etl_names = set()
    app_names = set()
    for entry in root.iterdir():
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        info = classify_example(entry)
        if info["family"] == "etl":
            etl_names.add(entry.name)
            assert info["platform"]
            assert info["platform"] not in {t["id"] for t in info["targets"]}
        else:
            app_names.add(entry.name)
            assert "databricks" not in {t["id"] for t in info["targets"]}
            assert "bigquery_dataform" not in {t["id"] for t in info["targets"]}
            assert "java21" in {t["id"] for t in info["targets"]}
    assert etl_names == ETL_EXAMPLES
    assert JAVA_APP.split("/", 1)[1] in app_names


def test_cross_family_pairs_are_rejected() -> None:
    assert pairing_error(DATAFORM, "databricks") is None
    assert pairing_error(DATAFORM, "snowflake_dbt") is None
    assert pairing_error(DATAFORM, "bigquery_dataform") is not None
    assert pairing_error(DATAFORM, "java21") is not None
    assert pairing_error(SNOWFLAKE, "databricks") is None
    assert pairing_error(SNOWFLAKE, "bigquery_dataform") is None
    assert pairing_error(SNOWFLAKE, "snowflake_dbt") is not None
    assert pairing_error(DATABRICKS_NOTEBOOKS, "bigquery_dataform") is None
    assert pairing_error(DATABRICKS_NOTEBOOKS, "snowflake_dbt") is None
    assert pairing_error(DATABRICKS_NOTEBOOKS, "databricks") is not None
    assert pairing_error(JAVA_APP, "java21") is None
    assert pairing_error(JAVA_APP, "databricks") is not None
    assert pairing_error(JAVA_APP, "bigquery_dataform") is not None
    assert pairing_error(JAVA_APP, "snowflake_dbt") is not None


@pytest.mark.parametrize(
    ("source", "target", "marker", "model_file", "snippet"),
    [
        (DATAFORM, "databricks", "databricks.yml", "src/sql/daily_revenue.sql", "date_sub(current_date(), 90)"),
        (DATAFORM, "snowflake_dbt", "dbt_project.yml", "models/marts/daily_revenue.sql", "DATEADD(day, -90, CURRENT_DATE())"),
        (SNOWFLAKE, "databricks", "databricks.yml", "src/sql/customer_lifetime_value.sql", "retail.analytics.stg_orders"),
        (SNOWFLAKE, "bigquery_dataform", "workflow_settings.yaml", "definitions/customer_lifetime_value.sqlx", "DATE_SUB(CURRENT_DATE(), INTERVAL 90 DAY)"),
        (DATABRICKS_NOTEBOOKS, "bigquery_dataform", "workflow_settings.yaml", None, "CURRENT_TIMESTAMP()"),
        (DATABRICKS_NOTEBOOKS, "snowflake_dbt", "dbt_project.yml", None, "CURRENT_TIMESTAMP()"),
        (DATABRICKS_NOTEBOOKS, "databricks", None, None, None),
    ],
)
def test_translation_pairs(source: str, target: str, marker, model_file, snippet) -> None:
    files = build_translation_files(source, target)
    if marker is None:
        assert files == []
        return
    paths = _by_path(files)
    assert marker in paths
    blob = _joined(files)
    if model_file is not None:
        assert model_file in paths
    if snippet is not None:
        assert snippet in blob
    manifest = json.loads(paths["migration_manifest.json"])
    assert manifest["source_platform"] == detect_etl_platform(source)
    assert manifest["target_platform"] == target
    assert manifest["models"]


def test_dataform_to_databricks_keeps_model_order() -> None:
    files = _by_path(build_translation_files(DATAFORM, "databricks"))
    job = files["resources/migrated_etl.job.yml"]
    assert "task_key: raw_orders" in job
    assert "task_key: stg_orders" in job
    assert "task_key: daily_revenue" in job
    revenue_at = job.index("task_key: daily_revenue")
    orders_at = job.index("task_key: stg_orders")
    assert orders_at < revenue_at
    assert "depends_on:" in job
    sql = files["src/sql/stg_orders.sql"]
    assert "CREATE OR REPLACE TABLE retail.analytics.stg_orders" in sql
    assert "retail.analytics.raw_orders" in sql
    assert "GETDATE" not in sql
    assert "${ref(" not in sql


def test_snowflake_to_dataform_uses_sqlx_refs() -> None:
    files = _by_path(build_translation_files(SNOWFLAKE, "bigquery_dataform"))
    sqlx = files["definitions/customer_lifetime_value.sqlx"]
    assert '${ref("stg_customers")}' in sqlx
    assert '${ref("stg_orders")}' in sqlx
    assert "NVL(" not in sqlx
    assert "DATEADD" not in sqlx


def test_databricks_notebook_sql_survives_into_both_targets() -> None:
    for target, suffix in (("bigquery_dataform", ".sqlx"), ("snowflake_dbt", ".sql")):
        files = build_translation_files(DATABRICKS_NOTEBOOKS, target)
        blob = _joined(files)
        assert "customer_orders" in blob
        assert "GETDATE" not in blob
        assert any(item["path"].endswith(suffix) for item in files)


def test_bundle_python_still_emits_a_project() -> None:
    files = build_translation_files(DATABRICKS_BUNDLE, "bigquery_dataform")
    assert any(item["path"].endswith(".sqlx") for item in files)
    assert "workflow_settings.yaml" in _by_path(files)


def test_write_translation_rejects_path_escape(tmp_path: Path) -> None:
    written = write_translation(
        [
            {"path": "databricks.yml", "content": "bundle:\n  name: ok\n"},
            {"path": "../escape.txt", "content": "nope"},
        ],
        tmp_path / "out",
    )
    assert written == ["databricks.yml"]
    assert (tmp_path / "out" / "databricks.yml").is_file()
    assert not (tmp_path / "escape.txt").exists()


def test_submit_writes_databricks_project(tmp_path: Path) -> None:
    set_run_dir(str(tmp_path))
    result = submit_seam_translation(
        files=[],
        source_path=DATAFORM,
        source_lang="sqlx",
        target_lang="databricks",
        seam_name="daily_revenue",
        run_dir=str(tmp_path),
    )
    assert result["etl_translation"] is True
    assert result["passed"] is True
    output = Path(result["output_dir"])
    assert (output / "databricks.yml").is_file()
    assert (output / "src" / "sql" / "daily_revenue.sql").is_file()
    saved = json.loads((tmp_path / "seam_result.json").read_text(encoding="utf-8"))
    assert any(item["path"] == "databricks.yml" for item in saved["pr"]["files"])


@pytest.fixture
def client(monkeypatch, tmp_path):
    import importlib

    from fastapi.testclient import TestClient

    import micro_cosmos.settings as settings_mod

    settings = settings_mod.Settings(skip_llm=True, runs_dir=str(tmp_path))
    monkeypatch.setattr(settings_mod, "_settings", settings)
    app_module = importlib.import_module("micro_cosmos.web.app")

    async def _noop_start(self):
        return None

    monkeypatch.setattr(app_module.Run, "start", _noop_start)
    test_client = TestClient(app_module.app)
    login = test_client.post("/login", data={
        "username": settings_mod.get_settings().demo_username,
        "password": settings_mod.get_settings().demo_password,
    })
    assert login.status_code in (200, 303)
    return test_client


def test_menu_splits_etl_and_applications(client) -> None:
    page = client.get("/")
    assert page.status_code == 200
    body = page.text
    assert 'id="menu-etl"' in body
    assert 'id="menu-application"' in body
    assert "Web &amp; Java applications" in body or "Web & Java applications" in body
    assert "bigquery_dataform_retail" in body
    assert "snowflake_dbt_retail" in body
    assert "Maps to Databricks, Snowflake + dbt" in body
    assert "Maps to BigQuery + Dataform, Snowflake + dbt" in body
    # Application card does not offer a data platform.
    java_at = body.index("java-springboot-legacy-app")
    java_card = body[java_at:java_at + 800]
    assert "databricks" not in java_card
    assert "java21" in body


def test_create_run_rejects_illegal_pairs(client) -> None:
    app_to_etl = client.post("/runs", data={
        "source_path": JAVA_APP,
        "source_lang": "java",
        "target_lang": "databricks",
        "skip_llm": "true",
    })
    assert app_to_etl.status_code == 400
    assert "application" in app_to_etl.text.lower()

    etl_to_app = client.post("/runs", data={
        "source_path": DATAFORM,
        "source_lang": "sqlx",
        "target_lang": "java21",
        "skip_llm": "true",
    })
    assert etl_to_app.status_code == 400
    assert "ETL" in etl_to_app.text

    same_platform = client.post("/runs", data={
        "source_path": SNOWFLAKE,
        "source_lang": "sql",
        "target_lang": "snowflake_dbt",
        "skip_llm": "true",
    })
    assert same_platform.status_code == 400

    allowed = client.post("/runs", data={
        "source_path": DATAFORM,
        "source_lang": "sqlx",
        "target_lang": "databricks",
        "skip_llm": "true",
    })
    assert allowed.status_code == 200


def _fresh_sqlx_ir() -> dict:
    from micro_cosmos.tools.observer_tools import _ir_cache, _source_files_cache, parse_source_estate

    _source_files_cache.clear()
    _ir_cache.clear()
    return parse_source_estate(DATAFORM, "sqlx")


def test_sqlx_ir_records_tables_columns_and_refs() -> None:
    ir = _fresh_sqlx_ir()
    by_id = {node["id"]: node for node in ir["nodes"]}
    stg = by_id["prog.StgOrders"]
    assert stg["attributes"]["materialization"] == "table"
    assert stg["attributes"]["schema"] == "staging"
    assert stg["attributes"]["dialect"] == "bigquery"
    assert stg["summary"]
    assert any(col["name"] == "amount" and col["type"] == "NUMERIC" for col in stg["inputs"])
    assert by_id["prog.RawOrders"]["attributes"]["materialization"] == "view"
    assert by_id["prog.DailyRevenue"]["attributes"]["has_aggregation"] == "true"
    calls = {
        (edge["source_id"], edge["target_id"])
        for edge in ir["edges"]
        if edge["type"] == "CALLS"
    }
    assert ("prog.StgOrders", "prog.RawOrders") in calls
    assert ("prog.DailyRevenue", "prog.StgOrders") in calls
    assert ("prog.StgCustomers", "prog.RawCustomers") in calls
    reads = {
        (edge["source_id"], edge["target_id"])
        for edge in ir["edges"]
        if edge["type"] == "READS"
    }
    assert any(src == "prog.RawOrders" and tgt.startswith("table.retail_raw.orders") for src, tgt in reads)


def test_sqlx_seams_carry_targets_and_efforts_for_both_warehouses() -> None:
    from micro_cosmos.tools.architect_tools import derive_tnas
    from micro_cosmos.tools.cartographer_tools import analyse_bounded_contexts
    from micro_cosmos.tools.seam_tools import produce_seam_report, produce_work_streams

    ir = _fresh_sqlx_ir()
    bcm = analyse_bounded_contexts(DATAFORM, "sqlx")
    contexts = {ctx["name"] for ctx in bcm["contexts"]}
    assert {"Raw", "Staging", "Marts"} <= contexts

    for target, store in (("databricks", "databricks"), ("snowflake_dbt", "snowflake")):
        report = produce_seam_report(ir, bcm=bcm, source_path=DATAFORM, target_lang=target)
        models = [seam for seam in report["seams"] if _is_model(seam)]
        refs = [seam for seam in report["seams"] if _is_ref(seam)]
        assert len(models) == 5
        assert len(refs) == 3
        for seam in models + refs:
            assert seam["work"]["effort"] in {"XS", "S", "M", "L", "XL"}
            assert seam["work"]["story_points"] > 0
            assert seam["target"]["platform"] == target
            assert seam["target"]["platform_label"]
            assert seam["target"]["relation"]
        revenue = next(seam for seam in models if seam["target"]["model"] == "daily_revenue")
        assert revenue["work"]["effort"] == "M"
        streams = produce_work_streams(report, bcm=bcm)
        assert streams["total_story_points"] > 0
        populated = [stream for stream in streams["work_streams"] if stream["seam_count"]]
        assert populated
        assert {stream["id"] for stream in populated} >= {
            "ws_etl_raw", "ws_etl_staging", "ws_etl_marts", "ws_etl_dependencies",
        }
        assert all(stream["dominant_effort"] != "—" for stream in populated)
        tnas = derive_tnas(DATAFORM, "sqlx", target)
        assert tnas["target_lang"] == target
        assert tnas["context_decisions"]
        assert all(decision["data_store"] == store for decision in tnas["context_decisions"])
        assert all(decision["target_platform"] == target for decision in tnas["context_decisions"])
        assert all(decision["communication_style"] == "async-event" for decision in tnas["context_decisions"])


def test_deterministic_etl_project_is_written_for_both_targets(tmp_path: Path) -> None:
    from micro_cosmos.tools.coder_tools import _submit_etl_translation

    for target, marker in (("databricks", "databricks.yml"), ("snowflake_dbt", "dbt_project.yml")):
        result = _submit_etl_translation(
            DATAFORM, "sqlx", target, "deterministic", str(tmp_path / target),
        )
        output = Path(result["output_dir"])
        assert result["has_impl"] is True
        assert result["target_lang"] == target
        assert (output / marker).is_file()
        assert any(output.rglob("*.sql"))


def _is_model(seam: dict) -> bool:
    return any(item.startswith("dataform model:") for item in seam.get("evidence", []))


def _is_ref(seam: dict) -> bool:
    return any(item.startswith("1 Dataform ref:") for item in seam.get("evidence", []))
