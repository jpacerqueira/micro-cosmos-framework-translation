"""Tests for the data contract the new "Target architecture & features" section of
the Seams tab depends on (micro_cosmos/web/static/js/dashboard.js's loadTargetPanel()/
renderTargetPanel()).

The dashboard joins tnas.json's services[] to its own context_decisions[] by matching
`service.service_id` (or the older `service.name`) against `decision.context`. If
these two identifiers ever drift apart, the join silently renders every target
service with no communication-style/pattern tag — this test locks in that contract.

Uses skip_llm=True (same fixture and estate as test_pipeline.py) so no LM Studio
connection is required.
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
    return MicroCosmosOrchestrator(run_id="target-arch-test")


async def test_tnas_service_id_matches_a_context_decision(skip_llm_orch):
    from micro_cosmos.orchestration.pipeline import PipelinePhase
    orch = skip_llm_orch
    await orch.initialise_session(ESTATE, "cobol", "go")

    for phase in [PipelinePhase.OBSERVER, PipelinePhase.CARTOGRAPHER, PipelinePhase.ARCHITECT]:
        async for _ in orch.run_phase(phase):
            pass

    tnas = orch.artifacts.get("tnas", {})
    services = tnas.get("services", [])
    decisions = tnas.get("context_decisions", [])
    assert services, "expected at least one target service from _work_for_seam's bounded contexts"
    assert decisions, "expected at least one context_decision"

    decision_contexts = {d["context"] for d in decisions}
    for svc in services:
        service_id = svc.get("service_id") or svc.get("name")
        assert service_id, f"service missing both service_id and name: {svc}"
        assert service_id in decision_contexts, (
            f"service_id {service_id!r} has no matching context_decision — "
            "the dashboard's target-architecture panel would render this service "
            "with no communication-style/pattern tag"
        )


async def test_tnas_migration_risk_is_uppercase(skip_llm_orch):
    """Regression guard: the dashboard lowercases migration_risk before using it as a
    CSS class suffix (.ws-risk-low/-medium/-high). If this ever silently changed to
    already-lowercase, that's fine (still lowercases correctly) — but if it ever
    changed to a different vocabulary (e.g. "Med"/"med"), the badge would render
    unstyled. Lock in the current uppercase LOW/MEDIUM/HIGH vocabulary."""
    from micro_cosmos.orchestration.pipeline import PipelinePhase
    orch = skip_llm_orch
    await orch.initialise_session(ESTATE, "cobol", "go")

    for phase in [PipelinePhase.OBSERVER, PipelinePhase.CARTOGRAPHER, PipelinePhase.ARCHITECT]:
        async for _ in orch.run_phase(phase):
            pass

    tnas = orch.artifacts.get("tnas", {})
    for svc in tnas.get("services", []):
        assert svc.get("migration_risk") in ("LOW", "MEDIUM", "HIGH")


async def test_feature_specs_available_after_feature_specifier(skip_llm_orch):
    """Uses a richer Java estate — legacy_estate's COBOL sample produces zero real
    seams in seam.json for this pipeline, and read_seam_data() (unlike
    MicroCosmosOrchestrator.get_all_seams_data()) has no synthetic-seam fallback, so
    feature_specs.json would come out empty regardless of this feature's correctness."""
    from micro_cosmos.orchestration.pipeline import PipelinePhase
    orch = skip_llm_orch
    await orch.initialise_session("examples/java-springboot-legacy-app", "java21", "kotlin")

    for phase in [
        PipelinePhase.OBSERVER, PipelinePhase.CARTOGRAPHER, PipelinePhase.ARCHITECT,
        PipelinePhase.SECURITY, PipelinePhase.FEATURE_SPECIFIER,
    ]:
        async for _ in orch.run_phase(phase):
            pass

    fs_path = orch.run_dir / "feature_specs.json"
    assert fs_path.exists(), "feature_specs.json should be written to disk after the Feature Specifier phase"
    specs = json.loads(fs_path.read_text()).get("specs", [])
    assert specs, "expected at least one feature spec"
    for spec in specs:
        assert "title" in spec
        assert "business_value" in spec
        assert "story_points" in spec
        assert "api_surface" in spec  # present (possibly null) — the field the dashboard's "API" tag checks
