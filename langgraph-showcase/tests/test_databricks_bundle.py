"""Regression tests for Databricks Asset Bundle (DAB) task-graph-driven seams.

Covers examples/databricks_bundle_default_python: a real DAB project with
one job (3 tasks: notebook_task, python_wheel_task, refresh_pipeline) and
one pipeline (default_python_etl). The job's own YAML already declares the
real task boundaries and execution order — this must take priority over
Cartographer's path-rule classification for the files each task owns, and
each task's depends_on must surface as an explicit cross-context call.
"""

from __future__ import annotations

from micro_cosmos.tools.cartographer_tools import analyse_bounded_contexts
from micro_cosmos.tools.databricks_bundle_tools import detect_databricks_bundle, parse_databricks_bundle
from micro_cosmos.tools.seam_tools import identify_seams

ESTATE = "examples/databricks_bundle_default_python"


def test_detects_bundle_via_databricks_yml() -> None:
    assert detect_databricks_bundle(ESTATE)
    assert not detect_databricks_bundle("examples/project1_databricks_adf")


def test_parses_task_graph_with_resolved_owned_files() -> None:
    bundle = parse_databricks_bundle(ESTATE)
    tasks = bundle["tasks"]
    assert set(tasks) == {"notebook_task", "python_wheel_task", "refresh_pipeline"}

    assert tasks["notebook_task"]["depends_on"] == []
    assert any(f.name == "sample_notebook.ipynb" for f in tasks["notebook_task"]["owns_files"])

    assert tasks["python_wheel_task"]["depends_on"] == ["notebook_task"]
    assert any(f.name == "main.py" for f in tasks["python_wheel_task"]["owns_files"])

    # refresh_pipeline references default_python_etl via
    # "${resources.pipelines.default_python_etl.id}" — must resolve through
    # the pipeline's own glob-owned transformation files, not just the
    # literal interpolation string.
    assert tasks["refresh_pipeline"]["depends_on"] == ["notebook_task"]
    assert any(
        f.name == "sample_trips_default_python.py" for f in tasks["refresh_pipeline"]["owns_files"]
    )


def test_cartographer_uses_task_graph_as_bounded_contexts() -> None:
    result = analyse_bounded_contexts(ESTATE, "pyspark")
    context_names = {c["name"] for c in result["contexts"]}
    assert {"NotebookTask", "PythonWheelTask", "RefreshPipeline"} <= context_names

    cross_calls = [tuple(pair) for pair in result["cross_context_calls"]]
    assert ("NotebookTask", "PythonWheelTask") in cross_calls
    assert ("NotebookTask", "RefreshPipeline") in cross_calls


def test_dab_context_rationale_names_the_real_source() -> None:
    """The rationale shown at Gate 3 (Architect echoes bcm's context rationale
    verbatim) must not claim "classified by path rules" for contexts that were
    actually overridden by the bundle's task graph — that's a real, visible
    lie about why the classification happened, even though the classification
    itself is correct. The one context Step 1a never touches (unreferenced
    test files) must still get the genuine path-rules rationale.
    """
    result = analyse_bounded_contexts(ESTATE, "pyspark")
    rationale = {c["name"]: c["rationale"] for c in result["contexts"]}

    for task_ctx in ("NotebookTask", "PythonWheelTask", "RefreshPipeline"):
        assert "by path rules" not in rationale[task_ctx]
        assert "scheduler definition" in rationale[task_ctx]
    assert "Depends on: NotebookTask" in rationale["PythonWheelTask"]

    assert "by path rules" in rationale["DatabricksBundleDefaultPython"]


def test_non_bundle_databricks_estate_is_unaffected() -> None:
    """project1_databricks_adf has no databricks.yml — Step 1a must be a
    no-op for it, leaving the existing path-rule classification untouched.
    """
    result = analyse_bounded_contexts("examples/project1_databricks_adf", "python")
    context_names = {c["name"] for c in result["contexts"]}
    assert "NotebookTask" not in context_names
    assert "PythonWheelTask" not in context_names


def test_seams_derived_from_task_depends_on_not_source_calls() -> None:
    """A DAB job's tasks are chained by the scheduler (depends_on), not by
    any source-code CALLS relationship — notebook_task and python_wheel_task
    share no actual function call, so neither the fan-in passes nor the
    CALLS-derived context-boundary pass in _detect_seams() can ever find
    these boundaries on their own. Without the dedicated DAB pass, this
    estate produces zero seams, which is exactly what Joao reported live.
    """
    result = identify_seams(ESTATE, "pyspark")
    links = [seam for seam in result["seams"] if seam["type"] == "link"]
    activities = [seam for seam in result["seams"] if seam["id"].startswith("seam_object_act.")]
    assert len(links) == 2
    assert len(activities) == 3
    locations = {seam["location"] for seam in links}
    assert "NotebookTask ↔ PythonWheelTask" in locations
    assert "NotebookTask ↔ RefreshPipeline" in locations
