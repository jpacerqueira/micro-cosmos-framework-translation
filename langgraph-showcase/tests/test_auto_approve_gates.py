"""Tests for the auto-approve-gates feature.

`auto_approve_gates`/`auto_approve_reviewer_name` follow the same per-run,
fixed-at-construction pattern as `skip_llm` (not the live-mid-run
`stop_requested` pattern) — see CLAUDE.md's "Auto-approve gates" section.
"""

from __future__ import annotations

import asyncio
import json

import pytest


ESTATE = "examples/legacy_estate"


@pytest.fixture
def auto_approve_orch(monkeypatch, tmp_path):
    import micro_cosmos.settings as settings_mod
    s = settings_mod.Settings(skip_llm=True, runs_dir=str(tmp_path))
    monkeypatch.setattr(settings_mod, "_settings", s)
    from micro_cosmos.orchestration.pipeline import MicroCosmosOrchestrator
    return MicroCosmosOrchestrator(
        run_id="auto-approve-unit-test",
        skip_llm=True,
        auto_approve_gates=True,
        auto_approve_reviewer_name="Jane Reviewer",
    )


@pytest.fixture
def manual_orch(monkeypatch, tmp_path):
    import micro_cosmos.settings as settings_mod
    s = settings_mod.Settings(skip_llm=True, runs_dir=str(tmp_path))
    monkeypatch.setattr(settings_mod, "_settings", s)
    from micro_cosmos.orchestration.pipeline import MicroCosmosOrchestrator
    return MicroCosmosOrchestrator(run_id="manual-gate-unit-test", skip_llm=True)


# ── open_gate() bypass ──────────────────────────────────────────────────────

async def test_open_gate_bypasses_wait_immediately(auto_approve_orch):
    from micro_cosmos.orchestration.pipeline import PipelinePhase
    from micro_cosmos.schema.gate import GateDecision

    orch = auto_approve_orch
    # This test is about approve/reject mechanics, not artifact validity —
    # seed a trivially-valid ir_graph so the #63/BUG-14 validity check
    # (added after this test was written) doesn't also emit a "warning"
    # event here, which would be a red herring for what this test asserts.
    orch.artifacts["ir_graph"] = {"nodes": []}
    events = [ev async for ev in orch.open_gate(PipelinePhase.GATE_1)]

    assert [ev.kind for ev in events] == ["gate_opened", "gate_resolved"]

    state = orch.gate_states["gate_1"]
    assert state.decision == GateDecision.APPROVED
    assert state.approvals[-1].reviewer_name == "Jane Reviewer"
    assert state.approvals[-1].notes == "auto-approved to next gate"

    resolved = events[-1]
    assert resolved.payload["reviewer_name"] == "Jane Reviewer"
    assert resolved.payload["notes"] == "auto-approved to next gate"
    assert resolved.payload["decision"] == "APPROVED"


async def test_open_gate_without_auto_approve_still_blocks(manual_orch):
    from micro_cosmos.orchestration.pipeline import PipelinePhase

    orch = manual_orch
    orch.artifacts["ir_graph"] = {"nodes": []}  # see comment in the test above

    async def _drain():
        return [ev async for ev in orch.open_gate(PipelinePhase.GATE_1)]

    task = asyncio.ensure_future(_drain())
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(asyncio.shield(task), timeout=0.05)

    orch.approve_gate("gate_1", "human reviewer")
    events = await asyncio.wait_for(task, timeout=2)
    assert [ev.kind for ev in events] == ["gate_opened", "gate_resolved"]
    assert events[-1].payload["reviewer_name"] == "human reviewer"


# ── POST /runs validation + persistence ─────────────────────────────────────

@pytest.fixture
def client(monkeypatch, tmp_path):
    import micro_cosmos.settings as settings_mod
    s = settings_mod.Settings(skip_llm=True, runs_dir=str(tmp_path))
    monkeypatch.setattr(settings_mod, "_settings", s)

    import importlib
    from fastapi.testclient import TestClient
    # NOT `import micro_cosmos.web.app as app_module` — micro_cosmos/web/__init__.py does
    # `from micro_cosmos.web.app import app`, which shadows the `app` *submodule*
    # attribute on the `micro_cosmos.web` package with the FastAPI *instance*. A
    # dotted `import x.y.z as w` resolves via attribute-chain traversal, not a
    # direct sys.modules lookup, so it would silently bind `app_module` to the
    # FastAPI app object instead of the module. importlib.import_module()
    # bypasses that shadowing entirely.
    app_module = importlib.import_module("micro_cosmos.web.app")

    async def _noop_start(self):
        return None

    monkeypatch.setattr(app_module.Run, "start", _noop_start)

    c = TestClient(app_module.app)
    resp = c.post("/login", data={
        "username": settings_mod.get_settings().demo_username,
        "password": settings_mod.get_settings().demo_password,
    })
    assert resp.status_code in (200, 303)
    return c, app_module, tmp_path


def test_post_runs_rejects_blank_reviewer_name_when_auto_approve_on(client):
    c, _app_module, _tmp_path = client
    resp = c.post("/runs", data={
        "source_path": ESTATE,
        "source_lang": "cobol",
        "target_lang": "go",
        "skip_llm": "true",
        "auto_approve_gates": "true",
        "auto_approve_reviewer_name": "   ",
    })
    assert resp.status_code == 400
    assert "approver name" in resp.text.lower()


def test_post_runs_success_persists_auto_approve_fields(client):
    c, _app_module, tmp_path = client
    resp = c.post("/runs", data={
        "source_path": ESTATE,
        "source_lang": "cobol",
        "target_lang": "go",
        "skip_llm": "true",
        "auto_approve_gates": "true",
        "auto_approve_reviewer_name": "Jane Reviewer",
    })
    assert resp.status_code == 200

    run_dirs = list(tmp_path.iterdir())
    assert len(run_dirs) == 1
    meta = json.loads((run_dirs[0] / "run_meta.json").read_text())
    assert meta["auto_approve_gates"] is True
    assert meta["auto_approve_reviewer_name"] == "Jane Reviewer"


# ── _restore_run() round-trip ────────────────────────────────────────────────

def test_restore_run_round_trips_auto_approve_fields(monkeypatch, tmp_path):
    import micro_cosmos.settings as settings_mod
    s = settings_mod.Settings(skip_llm=True, runs_dir=str(tmp_path))
    monkeypatch.setattr(settings_mod, "_settings", s)

    import importlib
    app_module = importlib.import_module("micro_cosmos.web.app")  # see comment above re: shadowed `app` attribute

    run_id = "restore-test"
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "run_meta.json").write_text(json.dumps({
        "source_path": ESTATE, "source_lang": "cobol", "target_lang": "go",
        "skip_llm": True,
        "auto_approve_gates": True,
        "auto_approve_reviewer_name": "Restored Reviewer",
    }))

    app_module.RUNS.pop(run_id, None)
    run = app_module._restore_run(run_id)
    assert run is not None
    assert run.auto_approve_gates is True
    assert run.auto_approve_reviewer_name == "Restored Reviewer"
    assert run.orchestrator.auto_approve_gates is True
    assert run.orchestrator.auto_approve_reviewer_name == "Restored Reviewer"


# ── Run.restart() preserves the flag ─────────────────────────────────────────

async def test_run_restart_preserves_auto_approve_fields(monkeypatch, tmp_path):
    import micro_cosmos.settings as settings_mod
    s = settings_mod.Settings(skip_llm=True, runs_dir=str(tmp_path))
    monkeypatch.setattr(settings_mod, "_settings", s)

    import importlib
    app_module = importlib.import_module("micro_cosmos.web.app")  # see comment above re: shadowed `app` attribute
    from micro_cosmos.orchestration.pipeline import PipelinePhase

    async def _noop_run_pipeline(self, start_phase=None):
        return None

    monkeypatch.setattr(app_module.Run, "_run_pipeline", _noop_run_pipeline)

    run = app_module.Run(
        "restart-test", ESTATE, "cobol", "go",
        skip_llm=True, auto_approve_gates=True, auto_approve_reviewer_name="X",
    )
    old_orch = run.orchestrator
    await run.restart(PipelinePhase.OBSERVER)

    assert run.orchestrator is not old_orch
    assert run.orchestrator.auto_approve_gates is True
    assert run.orchestrator.auto_approve_reviewer_name == "X"


# ── Live/integration: full pipeline with zero manual approvals ──────────────

async def test_full_pipeline_auto_approves_all_six_gates(auto_approve_orch):
    from micro_cosmos.orchestration.driver import run_full_pipeline

    orch = auto_approve_orch

    async def _drive():
        return [ev async for ev in run_full_pipeline(orch, ESTATE, "cobol", "go")]

    events = await asyncio.wait_for(_drive(), timeout=60)
    kinds = [ev.kind for ev in events]
    assert "pipeline_completed" in kinds

    gate_resolved = [ev for ev in events if ev.kind == "gate_resolved"]
    resolved_ids = {ev.payload["gate_id"] for ev in gate_resolved}
    assert resolved_ids == {"gate_1", "gate_2", "gate_3", "gate_4", "gate_4_5", "gate_5"}
    assert all(ev.payload["decision"] == "APPROVED" for ev in gate_resolved)
    assert all(ev.payload["reviewer_name"] == "Jane Reviewer" for ev in gate_resolved)
    assert all(ev.payload["notes"] == "auto-approved to next gate" for ev in gate_resolved)
