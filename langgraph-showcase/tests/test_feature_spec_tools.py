"""Unit tests for feature_spec_tools.py's batching support (BUG-7).

Large estates go through driver.py's per-batch Feature Specifier loop —
one LLM call per slice of seams, instead of one call covering every seam
at once (confirmed live to exceed the model's context window and hang
indefinitely on a real 53-seam estate). These tests cover the two
data-integrity guarantees that design depends on: read_seam_data can be
scoped to just one batch's seam IDs, and submit_feature_specs merges a
later batch's specs on top of an earlier batch's without erasing them.
"""

from __future__ import annotations

import json

from micro_cosmos.tools.feature_spec_tools import read_seam_data, submit_feature_specs


def _write_seam_json(run_dir, seam_ids):
    (run_dir / "seam.json").write_text(json.dumps({
        "seams": [
            {"id": sid, "type": "object", "location": "", "work": {"title": sid}}
            for sid in seam_ids
        ],
    }))


def test_read_seam_data_with_no_filter_returns_everything(tmp_path):
    _write_seam_json(tmp_path, ["seam_a", "seam_b", "seam_c"])
    data = read_seam_data(str(tmp_path))
    assert {s["id"] for s in data["seams"]} == {"seam_a", "seam_b", "seam_c"}


def test_read_seam_data_seam_ids_filters_to_just_that_batch(tmp_path):
    _write_seam_json(tmp_path, ["seam_a", "seam_b", "seam_c"])
    data = read_seam_data(str(tmp_path), seam_ids=["seam_b"])
    assert {s["id"] for s in data["seams"]} == {"seam_b"}


def test_read_seam_data_seam_ids_with_no_match_returns_empty_not_everything(tmp_path):
    """A batch asking for IDs that don't exist must get zero seams back —
    silently falling back to "everything" would defeat the whole point of
    scoping a batch and could re-submit specs for seams another batch
    already owns."""
    _write_seam_json(tmp_path, ["seam_a", "seam_b"])
    data = read_seam_data(str(tmp_path), seam_ids=["seam_nonexistent"])
    assert data["seams"] == []


def _spec(seam_id: str) -> dict:
    return {
        "seam_id": seam_id, "title": seam_id, "description": "d", "business_value": "v",
        "acceptance_criteria": ["ok"], "technical_notes": "n", "migration_phase": "phase-1",
        "story_points": 3, "effort": "M", "risk": "MEDIUM",
        "work_stream_id": "ws_default", "jira_issue_type": "Story",
    }


def test_submit_feature_specs_second_batch_merges_not_overwrites(tmp_path):
    """The core guarantee batching depends on: submitting batch 2 must not
    erase batch 1's already-written specs."""
    run_dir = str(tmp_path)
    r1 = submit_feature_specs(specs=[_spec("seam_a"), _spec("seam_b")], run_dir=run_dir)
    assert r1["ok"] is True

    r2 = submit_feature_specs(specs=[_spec("seam_c")], run_dir=run_dir)
    assert r2["ok"] is True

    on_disk = json.loads((tmp_path / "feature_specs.json").read_text())
    assert {s["seam_id"] for s in on_disk["specs"]} == {"seam_a", "seam_b", "seam_c"}


def test_submit_feature_specs_resubmitting_same_seam_id_replaces_not_duplicates(tmp_path):
    """A Gate 4.5 rejection re-runs every batch — re-submitting a seam that's
    already on disk must replace it, not create a duplicate entry."""
    run_dir = str(tmp_path)
    submit_feature_specs(specs=[_spec("seam_a")], run_dir=run_dir)

    updated = _spec("seam_a")
    updated["title"] = "updated title"
    submit_feature_specs(specs=[updated], run_dir=run_dir)

    on_disk = json.loads((tmp_path / "feature_specs.json").read_text())
    matching = [s for s in on_disk["specs"] if s["seam_id"] == "seam_a"]
    assert len(matching) == 1
    assert matching[0]["title"] == "updated title"


def test_submit_feature_specs_accepts_json_string_payload(tmp_path):
    """Gemma via LiteLLM calls submit_feature_specs with specs as one JSON
    string. That used to raise ``'str' object has no attribute 'keys'``,
    the batch never landed on disk, and the driver replaced it with the
    deterministic fallback."""
    run_dir = str(tmp_path)
    payload = json.dumps([_spec("seam_a"), _spec("seam_b")])
    result = submit_feature_specs(specs=payload, run_dir=run_dir)
    assert result["ok"] is True
    on_disk = json.loads((tmp_path / "feature_specs.json").read_text())
    assert {s["seam_id"] for s in on_disk["specs"]} == {"seam_a", "seam_b"}
    assert on_disk["specs"][0]["description"] == "d"


def test_submit_feature_specs_accepts_list_of_json_strings_and_string_points(tmp_path):
    spec = _spec("seam_a")
    spec["story_points"] = "5"
    spec["acceptance_criteria"] = json.dumps(["one", "two"])
    result = submit_feature_specs(specs=[json.dumps(spec)], run_dir=str(tmp_path))
    assert result["ok"] is True
    on_disk = json.loads((tmp_path / "feature_specs.json").read_text())
    saved = on_disk["specs"][0]
    assert saved["story_points"] == 5
    assert saved["acceptance_criteria"] == ["one", "two"]
    assert on_disk["summary"]["total_story_points"] == 5
