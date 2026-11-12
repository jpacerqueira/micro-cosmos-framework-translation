"""Regression tests for Azure Data Factory (ADF) scheduler-driven seams.

Covers two real ADF-scheduled estates, deliberately different in
notebookPath convention to prove the resolver isn't tuned to just one:

- examples/databricks_adf_notebooks_project: notebookPath uses a bare
  project-root prefix ("/project_domain/notebooks/...").
- examples/databricks_adf_project1_profile: notebookPath uses Databricks
  Repos-style paths ("/Repos/<repo-name>/notebooks/...") — the repo name is
  workspace scaffolding with no on-disk equivalent, and one activity
  (IngestItemSeason) uses pythonFile pointing at a dbfs:/ path with no
  on-disk equivalent at all, which must be tolerated, not crash.
"""

from __future__ import annotations

import json

import pytest

from micro_cosmos.tools.adf_scheduler_tools import (
    _is_adf_pipeline,
    detect_adf_scheduler,
    parse_adf_scheduler,
)
from micro_cosmos.tools.cartographer_tools import analyse_bounded_contexts
from micro_cosmos.tools.scheduler_tools import discover_task_graph
from micro_cosmos.tools.seam_tools import identify_seams

NOTEBOOKS_ESTATE = "examples/databricks_adf_notebooks_project"
PROFILE_ESTATE = "examples/databricks_adf_project1_profile"


def test_detects_adf_via_pipeline_json_shape() -> None:
    assert detect_adf_scheduler(NOTEBOOKS_ESTATE)
    assert detect_adf_scheduler(PROFILE_ESTATE)
    assert not detect_adf_scheduler("examples/cobol-bankxyz_fraud_detection")


def test_resolves_bare_project_root_notebook_paths() -> None:
    bundle = parse_adf_scheduler(NOTEBOOKS_ESTATE)
    tasks = bundle["tasks"]
    assert tasks["RunOrderIngestion"]["depends_on"] == ["RunCustomer360"]
    assert any(f.name == "BISHubAnalytics.py" for f in tasks["RunCustomer360"]["owns_files"])
    # RunBISAnalytics fans in from two activities — real diamond dependency.
    assert set(tasks["RunBISAnalytics"]["depends_on"]) == {"RunOrderIngestion", "RunProductMaster"}


def test_resolves_databricks_repos_style_notebook_paths() -> None:
    """notebookPath "/Repos/retail-platform/notebooks/03_etl_jobs/RunETLPipeline"
    has no "Repos" or "retail-platform" directory anywhere on disk — the
    resolver must still find notebooks/03_etl_jobs/RunETLPipeline.py by
    dropping the leading workspace-scaffolding segments.
    """
    bundle = parse_adf_scheduler(PROFILE_ESTATE)
    tasks = bundle["tasks"]
    assert any(f.name == "RunETLPipeline.py" for f in tasks["IngestCustomerTransactions"]["owns_files"])
    assert any(f.name == "BISAnalytics.py" for f in tasks["RunBISAnalytics"]["owns_files"])


def test_pythonfile_activity_with_no_disk_equivalent_does_not_crash() -> None:
    """IngestItemSeason's pythonFile points at "dbfs:/FileStore/scripts/..." —
    a scratch path never checked into source control. It must still appear
    in the task graph (so its place in the depends_on chain isn't lost),
    just with an empty owns_files rather than raising.
    """
    bundle = parse_adf_scheduler(PROFILE_ESTATE)
    tasks = bundle["tasks"]
    assert "IngestItemSeason" in tasks
    assert tasks["IngestItemSeason"]["owns_files"] == []
    assert tasks["IngestItemSeason"]["depends_on"] == ["IngestNmItemSupplier"]
    assert tasks["IngestFactSalesOrders"]["depends_on"] == ["IngestItemSeason"]


def test_scheduler_registry_merges_task_graphs() -> None:
    graph = discover_task_graph(NOTEBOOKS_ESTATE)["tasks"]
    assert "RunCustomer360" in graph
    assert graph is not parse_adf_scheduler(NOTEBOOKS_ESTATE)["tasks"]  # actually merged, not passed through


def test_cartographer_uses_adf_activity_graph_as_bounded_contexts() -> None:
    result = analyse_bounded_contexts(NOTEBOOKS_ESTATE, "pyspark")
    context_names = {c["name"] for c in result["contexts"]}
    assert {"RunBISAnalytics", "RunBrandedAttributionReplace", "RunWarehouseStaging"} <= context_names
    # ADF activity names (PascalCase, no separator) must not be mangled by
    # title-casing — "RunCustomer360" must stay "RunCustomer360", not
    # collapse to "Runcustomer360".
    cross_calls = [tuple(pair) for pair in result["cross_context_calls"]]
    assert ("RunCustomer360", "RunOrderIngestion") in cross_calls


def test_seams_derived_from_adf_activity_dependson() -> None:
    """Same reasoning as the DAB case: ADF activities are chained by the
    pipeline's own dependsOn, not by any source-code CALLS relationship.
    """
    result = identify_seams(NOTEBOOKS_ESTATE, "pyspark")
    assert result["total"] >= 4
    locations = {s["location"] for s in result["seams"]}
    assert "RunCustomer360 ↔ RunOrderIngestion" in locations
    assert all(s["type"] == "link" for s in result["seams"] if "↔" in s["location"])


def test_every_adf_activity_is_its_own_context_and_calls_its_notebook() -> None:
    from micro_cosmos.tools.observer_tools import _ir_cache, _source_files_cache, parse_source_estate
    from micro_cosmos.tools.seam_tools import produce_seam_report, produce_work_streams

    _source_files_cache.clear()
    _ir_cache.clear()
    ir = parse_source_estate(NOTEBOOKS_ESTATE, "pyspark")
    calls = {
        (edge["source_id"], edge["target_id"])
        for edge in ir["edges"]
        if edge["type"] == "CALLS"
    }
    assert ("act.RunCustomer360", "prog.Bishubanalytics") in calls
    assert ("act.RunOrderIngestion", "prog.Bishubanalytics") in calls
    assert ("act.RunProductMaster", "prog.Bishubanalytics") in calls
    assert ("act.RunBISAnalytics", "prog.Bishubanalytics") in calls
    assert ("act.RunCustomer360", "act.RunOrderIngestion") in calls
    assert ("act.RunBrandedReplace", "prog.Brandedreplaceload") in calls
    assert ("act.RunBrandedAttributionReplace", "prog.Brandedreplaceload") in calls

    result = analyse_bounded_contexts(NOTEBOOKS_ESTATE, "pyspark")
    names = {ctx["name"] for ctx in result["contexts"]}
    assert {
        "RunCustomer360", "RunOrderIngestion", "RunProductMaster", "RunBISAnalytics",
        "RunBrandedReplace", "RunBrandedAttributionReplace",
        "RunWarehouseStaging", "RunWarehouseStreamingStaging",
    } <= names
    by_name = {ctx["name"]: ctx["node_ids"] for ctx in result["contexts"]}
    assert "act.RunCustomer360" in by_name["RunCustomer360"]
    assert "act.RunOrderIngestion" in by_name["RunOrderIngestion"]

    report = produce_seam_report(ir, source_path=NOTEBOOKS_ESTATE, target_lang="snowflake_dbt")
    activities = [seam for seam in report["seams"] if _evidence(seam, "scheduler activity:")]
    deps = [seam for seam in report["seams"] if _evidence(seam, "declared task dependency")]
    assert len(activities) >= 8
    assert len(deps) == 4
    for seam in activities + deps:
        assert seam["work"]["effort"] in {"XS", "S", "M", "L", "XL"}
        assert seam["work"]["story_points"] > 0
        assert seam["target"]["platform"] == "snowflake_dbt"
        assert "ESLint" not in " ".join(seam["work"]["steps"])
    analytics = next(seam for seam in activities if seam["target"]["model"] == "RunBISAnalytics")
    assert analytics["work"]["effort"] == "M"
    streams = produce_work_streams(report)
    populated = [stream for stream in streams["work_streams"] if stream["seam_count"]]
    assert {stream["id"] for stream in populated} == {"ws_etl_activities", "ws_etl_dependencies"}
    assert streams["total_story_points"] > 0


def test_pyspark_imports_link_notebooks_to_etl_classes() -> None:
    from micro_cosmos.tools.observer_tools import _ir_cache, _source_files_cache, parse_source_estate

    _source_files_cache.clear()
    _ir_cache.clear()
    ir = parse_source_estate(PROFILE_ESTATE, "pyspark")
    calls = {
        (edge["source_id"], edge["target_id"])
        for edge in ir["edges"]
        if edge["type"] == "CALLS"
    }
    assert ("prog.Runetlpipeline", "prog.EtlPipeline") in calls
    assert ("prog.EtlPipeline", "prog.QualityChecker") in calls
    assert ("prog.EtlPipeline", "prog.Profiler") in calls
    assert ("prog.BisPipeline", "prog.QualityChecker") in calls
    assert ("prog.BisPipeline", "prog.BisQualityRules") in calls
    assert ("act.IngestCustomerTransactions", "prog.Runetlpipeline") in calls
    assert ("act.IngestFactSalesOrders", "prog.Runetlpipeline") in calls
    assert ("act.RunBISAnalytics", "prog.Bisanalytics") in calls
    assert ("act.RunWooPaymentsDiagnostics", "prog.Paymentdiagnostics") in calls
    assert ("act.RunAmazonPayDiagnostics", "prog.Paymentdiagnostics") in calls
    assert ("act.RunPaymentDiagnostics", "prog.Paymentdiagnostics") in calls
    # Klarna is a DatabricksSparkJar activity: it has no notebook, and it
    # runs after the two notebook diagnostics.
    assert ("act.RunKlarnaReconciliation", "prog.Paymentdiagnostics") not in calls
    assert ("act.RunWooPaymentsDiagnostics", "act.RunKlarnaReconciliation") in calls
    assert ("act.RunAmazonPayDiagnostics", "act.RunKlarnaReconciliation") in calls
    assert ("act.IngestNmItemSupplier", "act.IngestItemSeason") in calls
    assert ("act.IngestItemSeason", "act.IngestFactSalesOrders") in calls

    result = analyse_bounded_contexts(PROFILE_ESTATE, "pyspark")
    names = {ctx["name"] for ctx in result["contexts"]}
    assert {
        "IngestCustomerTransactions", "IngestProductInventory", "IngestNmItemSupplier",
        "IngestItemSeason", "IngestFactSalesOrders", "RunBISAnalytics", "RunPaymentDiagnostics",
        "RunWooPaymentsDiagnostics", "RunAmazonPayDiagnostics", "RunKlarnaReconciliation",
    } <= names
    report_seams = identify_seams(PROFILE_ESTATE, "pyspark")
    assert not any(seam["id"] == "seam_preprocessing_prog.AzureAuthConfig" for seam in report_seams["seams"])


def _evidence(seam: dict, prefix: str) -> bool:
    return any(item.startswith(prefix) or prefix in item for item in seam.get("evidence", []))


# ── Regression: non-dict-rooted JSON anywhere in the estate ────────────────
# _find_pipeline_files() rglobs EVERY *.json under the estate root (ADF
# pipelines have no fixed filename convention, unlike a DAB's databricks.yml),
# and discover_task_graph() is called unconditionally for every estate in every
# language — so a stray build artifact whose JSON root is a list used to raise
# AttributeError and silently break seam production, Cartographer and Architect.
# Real incident: examples/java-bankxyz_fraud_detection's Maven-generated
# target/cucumber-report/cucumber.json (run e1acbc0c, 2026-08-19).

_VALID_ADF_PIPELINE = {
    "name": "TestETL",
    "properties": {
        "activities": [
            {
                "name": "RunFirst",
                "type": "DatabricksNotebook",
                "typeProperties": {"notebookPath": "/proj/notebooks/RunFirst"},
                "dependsOn": [],
            },
            {
                "name": "RunSecond",
                "type": "DatabricksNotebook",
                "typeProperties": {"notebookPath": "/proj/notebooks/RunSecond"},
                "dependsOn": [{"activity": "RunFirst", "dependencyConditions": ["Succeeded"]}],
            },
        ]
    },
}


@pytest.mark.parametrize(
    "doc",
    [
        [],
        [{"name": "a Cucumber-style scenario array"}],
        "a bare JSON string",
        42,
        3.14,
        True,
        None,
    ],
)
def test_is_adf_pipeline_rejects_non_dict_documents(doc) -> None:
    """A well-formed JSON document need not be an object. _is_adf_pipeline must
    return False for any non-dict root, never raise AttributeError."""
    assert _is_adf_pipeline(doc) is False


def test_non_dict_json_in_estate_does_not_crash_detection(tmp_path) -> None:
    """An estate containing a list-rooted JSON file (a Cucumber report, in the
    real incident) must not break detection — and the genuine ADF pipeline
    sitting alongside it must still be found."""
    nb = tmp_path / "proj" / "notebooks"
    nb.mkdir(parents=True)
    (nb / "RunFirst.py").write_text("# notebook\n", encoding="utf-8")
    (nb / "RunSecond.py").write_text("# notebook\n", encoding="utf-8")

    (tmp_path / "pipeline.json").write_text(json.dumps(_VALID_ADF_PIPELINE), encoding="utf-8")

    # the exact shape that caused the incident, plus the other non-dict roots
    report = tmp_path / "target" / "cucumber-report"
    report.mkdir(parents=True)
    (report / "cucumber.json").write_text(
        json.dumps([{"keyword": "Feature", "elements": []}]), encoding="utf-8"
    )
    (tmp_path / "scalar.json").write_text("42", encoding="utf-8")
    (tmp_path / "string.json").write_text('"hello"', encoding="utf-8")
    (tmp_path / "null.json").write_text("null", encoding="utf-8")

    estate = str(tmp_path)
    assert detect_adf_scheduler(estate) is True

    tasks = parse_adf_scheduler(estate)["tasks"]
    assert set(tasks) == {"RunFirst", "RunSecond"}
    assert tasks["RunSecond"]["depends_on"] == ["RunFirst"]

    # and through the registry, the path Cartographer/seam detection actually use
    assert "RunFirst" in discover_task_graph(estate)["tasks"]


def test_non_adf_estate_with_non_dict_json_stays_undetected(tmp_path) -> None:
    """The guard must not turn a non-ADF estate INTO a detected one — an estate
    whose only JSON files are non-dict must still report no scheduler."""
    (tmp_path / "cucumber.json").write_text(json.dumps([{"a": 1}]), encoding="utf-8")
    (tmp_path / "app.py").write_text("print('x')\n", encoding="utf-8")
    assert detect_adf_scheduler(str(tmp_path)) is False
    assert discover_task_graph(str(tmp_path))["tasks"] == {}
