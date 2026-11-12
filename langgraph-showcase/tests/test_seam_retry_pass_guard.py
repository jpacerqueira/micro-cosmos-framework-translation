"""Regression tests for the post-seam-loop retry pass reading seam.json unguarded.

Real incident (run e1acbc0c, 2026-08-19): an AttributeError in the ADF scheduler
detector made pipeline.py's post-OBSERVER seam-production hook fail. That hook
swallows its own exceptions, so the run continued with no seam.json on disk —
but _run_all_seams() still iterated (get_all_seams_data() falls back to a
synthetic seam when the real count is zero), and then the retry pass did an
unguarded (run_dir / "seam.json").read_text(), turning a recoverable
"nothing to retry" state into an uncaught FileNotFoundError that killed the run.

These tests pin the guard independently of the ADF bug that exposed it: any
future reason seam.json is missing must degrade to "no seams to retry", not crash.

Uses skip_llm=True so every phase goes through _direct_tool_fallback — no LM
Studio connection required, matching the convention in test_pipeline.py and
test_stop_tdd_loop.py.
"""

from __future__ import annotations

import pytest

ESTATE = "examples/legacy_estate"


@pytest.fixture
def skip_llm_orch(monkeypatch, tmp_path):
    import micro_cosmos.settings as settings_mod
    s = settings_mod.Settings(skip_llm=True, runs_dir=str(tmp_path))
    monkeypatch.setattr(settings_mod, "_settings", s)
    from micro_cosmos.orchestration.pipeline import MicroCosmosOrchestrator
    return MicroCosmosOrchestrator(run_id="retry-guard-run")


async def test_pipeline_survives_missing_seam_json_at_retry_pass(skip_llm_orch):
    """Delete seam.json the moment the seam loop starts, so the retry pass hits
    exactly the state run e1acbc0c was in. The pipeline must still complete."""
    from micro_cosmos.orchestration.driver import run_full_pipeline

    orch = skip_llm_orch
    deleted = False
    kinds = []

    async for ev in run_full_pipeline(orch, ESTATE, "cobol", "go"):
        kinds.append(ev.kind)
        if ev.kind == "gate_opened":
            orch.approve_gate(ev.payload["gate_id"], "test-reviewer")
        if ev.kind == "seam_started" and not deleted:
            seam_path = orch.run_dir / "seam.json"
            if seam_path.exists():
                seam_path.unlink()
            deleted = True

    # The whole point: no FileNotFoundError escaped run_full_pipeline().
    assert "pipeline_completed" in kinds, (
        "pipeline must reach completion even with seam.json absent at the retry pass"
    )
    assert any(
        k == "gate_opened" for k in kinds
    ), "gates must still open normally"
    assert not (orch.run_dir / "seam.json").exists(), (
        "sanity check: seam.json really was absent for the retry pass"
    )


async def test_retry_pass_is_skipped_when_seam_json_absent(skip_llm_orch):
    """With no seam.json there are no failed seams to retry, so the retry pass
    must no-op silently rather than emitting retry_pass_started against nothing."""
    from micro_cosmos.orchestration.driver import run_full_pipeline

    orch = skip_llm_orch
    events = []

    async for ev in run_full_pipeline(orch, ESTATE, "cobol", "go"):
        events.append(ev)
        if ev.kind == "gate_opened":
            orch.approve_gate(ev.payload["gate_id"], "test-reviewer")
        if ev.kind == "seam_started":
            seam_path = orch.run_dir / "seam.json"
            if seam_path.exists():
                seam_path.unlink()

    started = [e for e in events if e.kind == "retry_pass_started"]
    assert started == [], (
        f"retry pass must not start with no seam.json on disk, got {started}"
    )
