"""Regression test for a real incident (run bbe6edc5): submit_code_review,
submit_test_review, and submit_functional_review (micro_cosmos/tools/coding_loop_tools.py)
all declared run_dir (and, for submit_test_review, three boolean flags) with no
Python default. ADK treats any parameter without a default as mandatory and
silently rejects the whole tool call if the model's function-call JSON omits
it — no file gets written, no exception surfaces, and there's no deterministic
fallback for these phases, so the reviewer's turn just produces an "invalid
artifact" warning every time. Locks in that all three can be called with only
the fields a model is likely to actually supply.
"""

from __future__ import annotations

import json

from micro_cosmos.tools.coding_loop_tools import (
    submit_code_review,
    submit_functional_review,
    submit_test_review,
)


def test_submit_code_review_works_without_run_dir(tmp_path):
    from micro_cosmos.tools.run_context import set_run_dir
    set_run_dir(str(tmp_path))

    result = submit_code_review(findings=[], passed=True)  # no run_dir passed

    assert result["passed"] is True
    assert (tmp_path / "skeptical_review.json").exists()


def test_submit_test_review_works_without_optional_args(tmp_path):
    from micro_cosmos.tools.run_context import set_run_dir
    set_run_dir(str(tmp_path))

    result = submit_test_review(findings=[], passed=True)  # no has_*/run_dir passed

    assert result["has_happy_path"] is False
    assert (tmp_path / "test_review.json").exists()
    data = json.loads((tmp_path / "test_review.json").read_text())
    assert data["has_happy_path"] is False
    assert data["has_rule_violation"] is False
    assert data["has_edge_case"] is False


def test_submit_functional_review_works_without_run_dir(tmp_path):
    from micro_cosmos.tools.run_context import set_run_dir
    set_run_dir(str(tmp_path))

    result = submit_functional_review(findings=[], passed=True)  # no run_dir passed

    assert result["passed"] is True
    assert (tmp_path / "functional_review.json").exists()


def test_submit_test_review_forced_to_fail_by_real_execution_result(tmp_path):
    """The Test Agent's real signal (fitness_runner.run_accumulated_test_execution,
    written as test_execution.json) must override an otherwise-passing review —
    a seam can no longer pass on static/LLM judgement alone while its real
    tests are actually failing. See coding_loop_tools.submit_test_review."""
    (tmp_path / "test_execution.json").write_text(json.dumps({
        "ran": True,
        "passed": False,
        "message": "Tests failed with no output.",
        "exec_result": {"passed": False, "message": "1 test failed: test_calculates_total"},
    }))

    result = submit_test_review(
        findings=[],
        passed=True,
        has_happy_path=True,
        has_rule_violation=True,
        has_edge_case=True,
        run_dir=str(tmp_path),
    )

    assert result["passed"] is False
    assert result["severity_counts"]["BLOCKER"] == 1
    assert any(f["test_file"] == "<real execution>" for f in result["findings"])


def test_submit_test_review_unaffected_when_real_execution_passed(tmp_path):
    (tmp_path / "test_execution.json").write_text(json.dumps({
        "ran": True,
        "passed": True,
        "message": "Tests passed.",
        "exec_result": {"passed": True, "message": "Tests passed."},
    }))

    result = submit_test_review(
        findings=[],
        passed=True,
        has_happy_path=True,
        has_rule_violation=True,
        has_edge_case=True,
        run_dir=str(tmp_path),
    )

    assert result["passed"] is True


def test_submit_test_review_unaffected_when_execution_never_ran(tmp_path):
    """ran=False means "nothing to execute yet" (e.g. no seam_result.json) —
    not a failure, and must not force the review to fail."""
    (tmp_path / "test_execution.json").write_text(json.dumps({
        "ran": False,
        "passed": True,
        "message": "No seam_result.json yet — nothing to execute.",
        "exec_result": None,
    }))

    result = submit_test_review(
        findings=[],
        passed=True,
        has_happy_path=True,
        has_rule_violation=True,
        has_edge_case=True,
        run_dir=str(tmp_path),
    )

    assert result["passed"] is True
