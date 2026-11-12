"""Tests for the Stop-TDD-loop cooperative flag (micro_cosmos/orchestration/driver.py).

Uses skip_llm=True so every phase goes through _direct_tool_fallback — no LM Studio
connection required, matching the convention in test_pipeline.py. Drives the full
run_full_pipeline() generator with every gate auto-approved, setting
orch.stop_requested=True as soon as the first seam starts, then asserts:

  - the TDD loop actually halts (a tdd_loop_stopped event is yielded)
  - the flag is fully consumed (doesn't leak into a later re-run of _run_all_seams,
    e.g. a Gate-5-rejection retry — see driver.py's stop_occurred/result["stopped"])
  - the post-loop single-attempt retry pass is skipped, since retrying a seam the
    user just asked to stop would defeat the request
  - the pipeline still reaches PR Reviewer / Gate 5 with whatever seams completed
"""

from __future__ import annotations

import json

import pytest

ESTATE = "examples/legacy_estate"


@pytest.fixture
def skip_llm_orch(monkeypatch, tmp_path):
    import micro_cosmos.settings as settings_mod
    s = settings_mod.Settings(skip_llm=True, runs_dir=str(tmp_path))
    monkeypatch.setattr(settings_mod, "_settings", s)
    from micro_cosmos.orchestration.pipeline import MicroCosmosOrchestrator
    return MicroCosmosOrchestrator(run_id="stop-test-run")


async def _run_and_stop_at_first_seam(orch, estate=ESTATE, source_lang="cobol", target_lang="go"):
    """Drive run_full_pipeline to completion, auto-approving every gate, and set
    orch.stop_requested=True as soon as the first seam starts. Returns the full
    event list for assertions."""
    from micro_cosmos.orchestration.driver import run_full_pipeline

    events = []
    stopped_once = False
    async for ev in run_full_pipeline(orch, estate, source_lang, target_lang):
        events.append(ev)
        if ev.kind == "gate_opened":
            orch.approve_gate(ev.payload["gate_id"], "test-reviewer")
        if ev.kind == "seam_started" and not stopped_once:
            orch.stop_requested = True
            stopped_once = True
    assert stopped_once, "expected at least one seam_started event to trigger the stop"
    return events


async def test_stop_requested_halts_tdd_loop_and_reaches_gate_5(skip_llm_orch):
    orch = skip_llm_orch
    events = await _run_and_stop_at_first_seam(orch)
    kinds = [ev.kind for ev in events]

    assert "tdd_loop_stopped" in kinds
    assert not any(ev.kind == "retry_pass_started" for ev in events), (
        "a user-requested stop must not trigger the post-loop retry pass"
    )
    assert any(
        ev.kind == "gate_opened" and ev.payload.get("gate_id") == "gate_5" for ev in events
    ), "pipeline must still reach Gate 5 with whatever seams completed"
    assert any(ev.kind == "pipeline_completed" for ev in events)


async def test_stop_flag_is_fully_consumed(skip_llm_orch):
    """Regression test: the flag must be reset by whichever checkpoint sees it
    first, or it silently leaks into a later re-run of _run_all_seams() (e.g. a
    Gate-5-rejection retry), sabotaging seams the user never asked to stop."""
    orch = skip_llm_orch
    await _run_and_stop_at_first_seam(orch)
    assert orch.stop_requested is False


async def test_stopped_seam_marked_failed_with_reason(skip_llm_orch):
    orch = skip_llm_orch
    await _run_and_stop_at_first_seam(orch)

    seam_report = json.loads((orch.run_dir / "seam.json").read_text())
    seams = seam_report.get("seams", [])
    if not seams:
        pytest.skip(
            "this estate's deterministic fallback produced no seam.json entries "
            "(get_all_seams_data() fell back to a synthetic bounded-context seam "
            "not reflected on disk) — unrelated to the stop feature"
        )
    for seam in seams:
        proc = seam.get("processing", {})
        assert proc.get("status") == "failed"
        assert "stop" in (proc.get("failure_reason") or "").lower()
