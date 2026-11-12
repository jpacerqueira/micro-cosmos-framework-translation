"""Tests for the pause-after-planning feature and the /demo -> / landing-page move.

`pause_after_planning` follows the same per-run, fixed-at-construction pattern as
`skip_llm`/`auto_approve_gates` (not the live-mid-run `stop_requested` pattern) —
see CLAUDE.md's "Pause after planning" section.
"""

from __future__ import annotations

import json

import pytest


ESTATE = "examples/legacy_estate"

# Everything the pipeline must NOT reach when it pauses after planning.
_POST_PLANNING_PHASES = {
    "code_writer", "skeptical_review", "test_review",
    "functional_review", "writer", "pr_reviewer", "gate_5",
}


@pytest.fixture
def paused_orch(monkeypatch, tmp_path):
    import micro_cosmos.settings as settings_mod
    s = settings_mod.Settings(skip_llm=True, runs_dir=str(tmp_path))
    monkeypatch.setattr(settings_mod, "_settings", s)
    from micro_cosmos.orchestration.pipeline import MicroCosmosOrchestrator
    return MicroCosmosOrchestrator(
        run_id="pause-after-planning-test",
        skip_llm=True,
        auto_approve_gates=True,
        auto_approve_reviewer_name="Jane Reviewer",
        pause_after_planning=True,
    )


@pytest.fixture
def client(monkeypatch, tmp_path):
    import micro_cosmos.settings as settings_mod
    s = settings_mod.Settings(skip_llm=True, runs_dir=str(tmp_path))
    monkeypatch.setattr(settings_mod, "_settings", s)

    import importlib
    from fastapi.testclient import TestClient
    # importlib, not `import micro_cosmos.web.app as app_module` — see the long
    # note in test_auto_approve_gates.py about the shadowed `app` attribute.
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


# ── Pipeline stops after Gate 4.5 ───────────────────────────────────────────

async def test_pipeline_stops_after_planning_gate(paused_orch):
    from micro_cosmos.orchestration.driver import run_full_pipeline

    orch = paused_orch
    events = [ev async for ev in run_full_pipeline(orch, ESTATE, "cobol", "go")]

    # It still finishes cleanly — a pause is a completion, not a hang or error.
    completed = [ev for ev in events if ev.kind == "pipeline_completed"]
    assert len(completed) == 1
    assert completed[0].payload["paused_after_planning"] is True

    # Everything up to and including the planning gate ran.
    resolved = {ev.payload["gate_id"] for ev in events if ev.kind == "gate_resolved"}
    assert resolved == {"gate_1", "gate_2", "gate_3", "gate_4", "gate_4_5"}

    # ...and nothing past it did.
    assert "gate_5" not in resolved
    reached = {ev.phase.value for ev in events}
    assert not (reached & _POST_PLANNING_PHASES), (
        f"pipeline entered post-planning phases: {sorted(reached & _POST_PLANNING_PHASES)}"
    )

    # No code translation happened.
    assert not (orch.run_dir / "seam_result.json").exists()

    # The UI is told which pills to strike out.
    assert set(completed[0].payload["skipped_phases"]) == _POST_PLANNING_PHASES


async def test_planning_artifacts_survive_the_pause(paused_orch):
    """The whole point of pausing is that the analysis output is still usable."""
    from micro_cosmos.orchestration.driver import run_full_pipeline

    orch = paused_orch
    async for _ in run_full_pipeline(orch, ESTATE, "cobol", "go"):
        pass

    # Every analysis/planning artifact the four gates produce. feature_specs.json
    # is deliberately not asserted: on this zero-seam fixture estate the Feature
    # Specifier writes feature_specs_result.json instead, which is a property of
    # the fixture, not of pausing.
    for artifact in (
        "ir_graph.json", "bounded_context_map.json", "tnas.json",
        "security_report.json", "seam.json", "work_streams.json",
    ):
        assert (orch.run_dir / artifact).exists(), f"{artifact} missing after pause"


async def test_pause_is_skipped_when_restarting_into_code_writer(monkeypatch, tmp_path):
    """A paused run isn't sealed: an explicit CODE_WRITER restart still runs the loop."""
    import micro_cosmos.settings as settings_mod
    s = settings_mod.Settings(skip_llm=True, runs_dir=str(tmp_path))
    monkeypatch.setattr(settings_mod, "_settings", s)

    from micro_cosmos.orchestration.pipeline import MicroCosmosOrchestrator, PipelinePhase
    from micro_cosmos.orchestration.driver import run_full_pipeline

    orch = MicroCosmosOrchestrator(
        run_id="pause-restart-test", skip_llm=True,
        auto_approve_gates=True, auto_approve_reviewer_name="Jane Reviewer",
        pause_after_planning=True,
    )
    events = [
        ev async for ev in run_full_pipeline(
            orch, ESTATE, "cobol", "go", start_phase=PipelinePhase.CODE_WRITER
        )
    ]
    completed = [ev for ev in events if ev.kind == "pipeline_completed"]
    assert len(completed) == 1
    assert not completed[0].payload.get("paused_after_planning")


async def test_default_run_is_unaffected(monkeypatch, tmp_path):
    """Without the flag the pipeline goes all the way through Gate 5 as before."""
    import micro_cosmos.settings as settings_mod
    s = settings_mod.Settings(skip_llm=True, runs_dir=str(tmp_path))
    monkeypatch.setattr(settings_mod, "_settings", s)

    from micro_cosmos.orchestration.pipeline import MicroCosmosOrchestrator
    from micro_cosmos.orchestration.driver import run_full_pipeline

    orch = MicroCosmosOrchestrator(
        run_id="no-pause-test", skip_llm=True,
        auto_approve_gates=True, auto_approve_reviewer_name="Jane Reviewer",
    )
    assert orch.pause_after_planning is False

    events = [ev async for ev in run_full_pipeline(orch, ESTATE, "cobol", "go")]
    resolved = {ev.payload["gate_id"] for ev in events if ev.kind == "gate_resolved"}
    assert "gate_5" in resolved
    completed = [ev for ev in events if ev.kind == "pipeline_completed"]
    assert not completed[0].payload.get("paused_after_planning")


# ── Persistence: POST /runs -> run_meta.json -> _restore_run -> restart ─────

def test_post_runs_persists_pause_after_planning(client):
    c, _app_module, tmp_path = client
    resp = c.post("/runs", data={
        "source_path": ESTATE,
        "source_lang": "cobol",
        "target_lang": "go",
        "skip_llm": "true",
        "pause_after_planning": "true",
    })
    assert resp.status_code == 200

    run_dirs = list(tmp_path.iterdir())
    assert len(run_dirs) == 1
    meta = json.loads((run_dirs[0] / "run_meta.json").read_text())
    assert meta["pause_after_planning"] is True


def test_post_runs_defaults_pause_after_planning_off(client):
    c, _app_module, tmp_path = client
    resp = c.post("/runs", data={
        "source_path": ESTATE,
        "source_lang": "cobol",
        "target_lang": "go",
        "skip_llm": "true",
    })
    assert resp.status_code == 200
    meta = json.loads((list(tmp_path.iterdir())[0] / "run_meta.json").read_text())
    assert meta["pause_after_planning"] is False


def test_restore_run_round_trips_pause_after_planning(monkeypatch, tmp_path):
    import micro_cosmos.settings as settings_mod
    s = settings_mod.Settings(skip_llm=True, runs_dir=str(tmp_path))
    monkeypatch.setattr(settings_mod, "_settings", s)

    import importlib
    app_module = importlib.import_module("micro_cosmos.web.app")

    run_id = "pause-restore-test"
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "run_meta.json").write_text(json.dumps({
        "source_path": ESTATE, "source_lang": "cobol", "target_lang": "go",
        "skip_llm": True,
        "pause_after_planning": True,
    }))

    app_module.RUNS.pop(run_id, None)
    run = app_module._restore_run(run_id)
    assert run is not None
    assert run.pause_after_planning is True
    assert run.orchestrator.pause_after_planning is True


def test_restore_run_tolerates_meta_without_the_field(monkeypatch, tmp_path):
    """Runs created before this feature existed must still restore."""
    import micro_cosmos.settings as settings_mod
    s = settings_mod.Settings(skip_llm=True, runs_dir=str(tmp_path))
    monkeypatch.setattr(settings_mod, "_settings", s)

    import importlib
    app_module = importlib.import_module("micro_cosmos.web.app")

    run_id = "pause-legacy-meta"
    run_dir = tmp_path / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "run_meta.json").write_text(json.dumps({
        "source_path": ESTATE, "source_lang": "cobol", "target_lang": "go",
    }))

    app_module.RUNS.pop(run_id, None)
    run = app_module._restore_run(run_id)
    assert run is not None
    assert run.pause_after_planning is False


async def test_run_restart_preserves_pause_after_planning(monkeypatch, tmp_path):
    import micro_cosmos.settings as settings_mod
    s = settings_mod.Settings(skip_llm=True, runs_dir=str(tmp_path))
    monkeypatch.setattr(settings_mod, "_settings", s)

    import importlib
    app_module = importlib.import_module("micro_cosmos.web.app")
    from micro_cosmos.orchestration.pipeline import PipelinePhase

    async def _noop_run_pipeline(self, start_phase=None):
        return None

    monkeypatch.setattr(app_module.Run, "_run_pipeline", _noop_run_pipeline)

    run = app_module.Run(
        "pause-restart-meta", ESTATE, "cobol", "go",
        skip_llm=True, pause_after_planning=True,
    )
    old_orch = run.orchestrator
    await run.restart(PipelinePhase.OBSERVER)

    assert run.orchestrator is not old_orch
    assert run.orchestrator.pause_after_planning is True


# ── Landing page moved from /demo to / ──────────────────────────────────────

def test_root_serves_the_example_chooser(client):
    c, _app_module, _tmp = client
    resp = c.get("/")
    assert resp.status_code == 200
    assert "Choose an example" in resp.text
    # The launch panel and its new toggle are on the landing page now.
    assert 'name="pause_after_planning"' in resp.text
    assert "Pause after planning" in resp.text


def test_demo_permanently_redirects_to_root(client):
    c, _app_module, _tmp = client
    resp = c.get("/demo", follow_redirects=False)
    assert resp.status_code == 308
    assert resp.headers["location"] == "/"


def test_demo_api_subroutes_keep_their_paths(client):
    c, _app_module, _tmp = client
    # Called directly by the page's own JS — these must not be redirected away.
    resp = c.get("/demo/detect-lang", params={"path": ESTATE})
    assert resp.status_code == 200
    assert "langs" in resp.json()


def test_login_redirects_to_root(monkeypatch, tmp_path):
    import micro_cosmos.settings as settings_mod
    s = settings_mod.Settings(skip_llm=True, runs_dir=str(tmp_path))
    monkeypatch.setattr(settings_mod, "_settings", s)

    import importlib
    from fastapi.testclient import TestClient
    app_module = importlib.import_module("micro_cosmos.web.app")

    c = TestClient(app_module.app)
    resp = c.post("/login", data={
        "username": settings_mod.get_settings().demo_username,
        "password": settings_mod.get_settings().demo_password,
    }, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
