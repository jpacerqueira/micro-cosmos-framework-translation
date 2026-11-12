"""Integration tests for the orchestration layer.

Uses skip_llm=True so every phase goes through _direct_tool_fallback —
no LM Studio connection required. The legacy COBOL estate provides real
source files so the deterministic tools produce non-trivial artifacts.
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
    return MicroCosmosOrchestrator(run_id="test-run")


# ── artifact validators ────────────────────────────────────────────────────────

def test_is_valid_artifact_rejects_bad_shapes():
    from micro_cosmos.orchestration.pipeline import _is_valid_artifact
    assert not _is_valid_artifact("ir_graph", {})
    assert not _is_valid_artifact("ir_graph", "not a dict")
    assert not _is_valid_artifact("bounded_context_map", {"wrong_key": []})
    assert not _is_valid_artifact("seam_result", {"no_pr": True})
    assert not _is_valid_artifact("review_report", {})


def test_is_valid_artifact_accepts_valid_shapes():
    from micro_cosmos.orchestration.pipeline import _is_valid_artifact
    assert _is_valid_artifact("ir_graph", {"nodes": []})
    # bounded_context_map requires >=2 real contexts + a real cross-context
    # call + no glob node_ids (tightened for the ProjectManagement
    # over-broad-context incident, 2026-08-04) — {"contexts": []} is not a
    # valid shape under that contract, unlike before the tightening.
    assert _is_valid_artifact("bounded_context_map", {
        "contexts": [
            {"name": "A", "node_ids": ["n1"]},
            {"name": "B", "node_ids": ["n2"]},
        ],
        "cross_context_calls": [["n1", "n2"]],
    })
    assert _is_valid_artifact("domain_model", {"aggregates": []})
    assert _is_valid_artifact("seam_result", {"pr": {}})
    assert _is_valid_artifact("review_report", {"review_passed": True})


def test_bounded_context_map_rejects_renamed_per_context_keys():
    """A real local model returned contexts shaped like
    {"context_name": ..., "nodes": [...]} instead of {"name": ...,
    "node_ids": [...]} — structurally plausible enough to fool a
    presence-only check, but useless to every downstream consumer keyed on
    the real field names."""
    from micro_cosmos.orchestration.pipeline import _is_valid_artifact
    renamed = {
        "contexts": [
            {"context_name": "Foo", "nodes": ["a", "b"]},
            {"context_name": "Bar", "nodes": ["c"]},
        ],
        "cross_context_calls": [["Foo", "Bar"]],
    }
    assert not _is_valid_artifact("bounded_context_map", renamed)


def test_bounded_context_map_rejects_empty_node_ids_per_context():
    from micro_cosmos.orchestration.pipeline import _is_valid_artifact
    empty_node_ids = {
        "contexts": [
            {"name": "Foo", "node_ids": ["a"]},
            {"name": "Bar", "node_ids": []},
        ],
        "cross_context_calls": [["Foo", "Bar"]],
    }
    assert not _is_valid_artifact("bounded_context_map", empty_node_ids)


def test_is_valid_fitness_suite_rejects_reinvented_shape():
    """A real local model returned a non-empty fitness_suite dict with keys
    like "read_heavy_services"/"write_heavy_services" instead of
    "functions" — truthy, so a bare presence check wrongly accepted it and
    every canonical fitness check went dark for that run."""
    from micro_cosmos.orchestration.pipeline import _is_valid_fitness_suite
    assert not _is_valid_fitness_suite({"read_heavy_services": ["Foo"], "write_heavy_services": ["Bar"]})
    assert not _is_valid_fitness_suite({"functions": []})
    assert not _is_valid_fitness_suite({"functions": [{"id": "X"}]})  # missing spec
    assert _is_valid_fitness_suite({"functions": [{"id": "X", "spec": "y", "severity": "BLOCKING"}]})


def test_bounded_context_map_rejects_incomplete_coverage():
    """A live LM Studio run classified only 33 of 902 real nodes (3.7%) into
    any context, while every context it DID produce was individually
    well-formed enough to pass every per-context check. Coverage is a
    coarser, estate-wide check the per-context validator cannot see."""
    from micro_cosmos.orchestration.pipeline import _is_valid_artifact
    ir = {"nodes": [{"id": f"prog.N{i}"} for i in range(100)]}
    barely_covered = {
        "contexts": [
            {"name": "Foo", "node_ids": ["prog.N0", "prog.N1"]},
            {"name": "Bar", "node_ids": ["prog.N2"]},
        ],
        "cross_context_calls": [["Foo", "Bar"]],
    }
    assert not _is_valid_artifact("bounded_context_map", barely_covered, ir=ir)


def test_bounded_context_map_accepts_high_coverage():
    from micro_cosmos.orchestration.pipeline import _is_valid_artifact
    ir = {"nodes": [{"id": f"prog.N{i}"} for i in range(10)]}
    well_covered = {
        "contexts": [
            {"name": "Foo", "node_ids": [f"prog.N{i}" for i in range(5)]},
            {"name": "Bar", "node_ids": [f"prog.N{i}" for i in range(5, 10)]},
        ],
        "cross_context_calls": [["Foo", "Bar"]],
    }
    assert _is_valid_artifact("bounded_context_map", well_covered, ir=ir)


def test_bounded_context_map_coverage_check_skipped_without_ir():
    """No ir_graph available yet (e.g. very first validation pass) must
    degrade to the structural-only check, not fail closed."""
    from micro_cosmos.orchestration.pipeline import _is_valid_artifact
    well_formed_but_unverifiable_coverage = {
        "contexts": [
            {"name": "Foo", "node_ids": ["a"]},
            {"name": "Bar", "node_ids": ["b"]},
        ],
        "cross_context_calls": [["Foo", "Bar"]],
    }
    assert _is_valid_artifact("bounded_context_map", well_formed_but_unverifiable_coverage)


def test_is_valid_context_decisions_rejects_reinterpreted_values():
    """A real local model returned entries keyed "name" (not "context") with
    communication_style set to free-form prose ("CQRS with event sourcing")
    instead of the real sync-http/async-event enum — nothing downstream
    would ever match against either."""
    from micro_cosmos.orchestration.pipeline import _is_valid_context_decisions
    assert not _is_valid_context_decisions([
        {"name": "Foo", "communication_style": "CQRS with event sourcing"},
    ])
    assert not _is_valid_context_decisions([])
    assert not _is_valid_context_decisions([{"context": "Foo", "communication_style": "sometimes-async"}])
    assert _is_valid_context_decisions([{"context": "Foo", "communication_style": "sync-http"}])


# ── phase execution ────────────────────────────────────────────────────────────

async def test_observer_phase_produces_ir_graph(skip_llm_orch):
    from micro_cosmos.orchestration.pipeline import PipelinePhase
    orch = skip_llm_orch
    await orch.initialise_session(ESTATE, "cobol", "go")

    events = []
    async for ev in orch.run_phase(PipelinePhase.OBSERVER):
        events.append(ev)

    kinds = {ev.kind for ev in events}
    assert "phase_started" in kinds
    assert "phase_completed" in kinds
    assert "error" not in kinds

    ir = orch.artifacts.get("ir_graph", {})
    assert "nodes" in ir
    assert len(ir["nodes"]) > 0


async def test_cartographer_phase_produces_bounded_context_map(skip_llm_orch):
    from micro_cosmos.orchestration.pipeline import PipelinePhase
    orch = skip_llm_orch
    await orch.initialise_session(ESTATE, "cobol", "go")

    async for _ in orch.run_phase(PipelinePhase.OBSERVER):
        pass
    async for _ in orch.run_phase(PipelinePhase.CARTOGRAPHER):
        pass

    bcm = orch.artifacts.get("bounded_context_map", {})
    assert "contexts" in bcm
    assert len(bcm["contexts"]) > 0


async def test_full_analysis_chain_produces_all_artifacts(skip_llm_orch):
    from micro_cosmos.orchestration.pipeline import PipelinePhase
    orch = skip_llm_orch
    await orch.initialise_session(ESTATE, "cobol", "go")

    # PipelinePhase.PATTERN / domain_model.json are not part of the real
    # pipeline — the Pattern agent (micro_cosmos/agents/pattern.py) is not wired
    # into driver.py or pipeline.py anywhere. Only the phases that actually
    # run are exercised here: Observer -> Cartographer -> Architect.
    for phase in [
        PipelinePhase.OBSERVER,
        PipelinePhase.CARTOGRAPHER,
        PipelinePhase.ARCHITECT,
    ]:
        async for _ in orch.run_phase(phase):
            pass

    assert "nodes" in orch.artifacts.get("ir_graph", {})
    assert "contexts" in orch.artifacts.get("bounded_context_map", {})
    assert any(k in orch.artifacts.get("tnas", {}) for k in ("services", "target_lang"))


async def test_phase_events_written_to_disk(skip_llm_orch, tmp_path):
    from micro_cosmos.orchestration.pipeline import PipelinePhase
    orch = skip_llm_orch
    await orch.initialise_session(ESTATE, "cobol", "go")

    async for _ in orch.run_phase(PipelinePhase.OBSERVER):
        pass

    assert (orch.run_dir / "ir_graph.json").exists()


def test_review_fallback_synthesises_failing_review_when_file_absent(skip_llm_orch, tmp_path):
    """_direct_tool_fallback must return a valid failing review, not None, when the
    agent crashed without calling submit_code_review. Without this, _passed() defaults
    to True and the TDD loop exits thinking the review passed."""
    from micro_cosmos.orchestration.pipeline import PipelinePhase, _direct_tool_fallback, _is_valid_artifact
    orch = skip_llm_orch
    run_dir = str(orch.run_dir)
    state = {"run_dir": run_dir, "source_path": ESTATE, "source_lang": "python", "target_lang": "go", "current_seam": ""}

    for phase in [PipelinePhase.SKEPTICAL_REVIEW, PipelinePhase.TEST_REVIEW, PipelinePhase.FUNCTIONAL_REVIEW]:
        result, _error = _direct_tool_fallback(phase, state)
        assert result is not None, f"{phase.value} fallback returned None"
        assert _is_valid_artifact(phase.value.replace("_review", "_review"), result), \
            f"{phase.value} fallback artifact failed shape check"
        assert result.get("passed") is False, f"{phase.value} fallback should be passed=False"
        assert result.get("findings"), f"{phase.value} fallback should include a warning finding"


def test_code_writer_fallback_synthesises_valid_seam_result_when_agent_did_not_submit(skip_llm_orch, tmp_path):
    """A Code Writer agent that crashes or replies with plain text instead of
    calling submit_seam_translation used to leave nothing behind for this
    phase — _direct_tool_fallback had no CODE_WRITER case at all, so ADK's
    own raw-text-into-output_key behavior could leave a plain string sitting
    in seam_result.json. That string passes the outer json.loads() (it's a
    valid JSON string literal) but poisons every downstream reader expecting
    a dict — confirmed live via a real LM Studio run, 2026-08-24, where the
    Test Agent and the skeptical checker both independently reported "could
    not parse seam_result.json", and that raw message then fed back into the
    next retry prompt and confused the model further. The fallback must now
    produce a valid, shaped, passed=False result — not None — the same way
    the three review phases already do."""
    from micro_cosmos.orchestration.pipeline import PipelinePhase, _direct_tool_fallback, _is_valid_artifact
    orch = skip_llm_orch
    run_dir = str(orch.run_dir)
    state = {
        "run_dir": run_dir, "source_path": ESTATE, "source_lang": "python", "target_lang": "go",
        "current_seam": "seam_object_prog.Probe",
    }

    result, error = _direct_tool_fallback(PipelinePhase.CODE_WRITER, state)

    assert result is not None, "CODE_WRITER fallback returned None"
    assert error is None
    assert _is_valid_artifact("seam_result", result)
    assert result.get("passed") is False
    assert result["pr"]["files"], "fallback should still emit real scaffolding files, not an empty PR"
    assert "did not submit" in result["pr"]["pr_body"].lower()


async def test_feature_specifier_fallback_does_not_clobber_its_own_output(skip_llm_orch):
    """BUG-7: submit_feature_specs() writes the full {specs, work_streams, ...}
    object straight to feature_specs.json but returns only a small
    {"ok": True, "specs_written": N} confirmation. _direct_tool_fallback used to
    return that confirmation verbatim, so the caller's self._save_artifact()
    call re-wrote feature_specs.json with just the stub, destroying the real
    specs the same call had just persisted a moment earlier — confirmed live
    as "feature_specs.json was not written at all" on a real estate."""
    from micro_cosmos.orchestration.pipeline import PipelinePhase, _direct_tool_fallback, _is_valid_artifact
    # The exact estate named in issue #56's own bug report (real seams, unlike
    # legacy_estate/cobol/go which produces zero).
    real_estate = "examples/java-bankxyz_fraud_detection"
    orch = skip_llm_orch
    await orch.initialise_session(real_estate, "java", "kotlin")

    # Real seam.json, needed for _direct_tool_fallback's FEATURE_SPECIFIER
    # case to have at least one seam to build a spec for.
    for phase in [PipelinePhase.OBSERVER, PipelinePhase.CARTOGRAPHER, PipelinePhase.ARCHITECT]:
        async for _ in orch.run_phase(phase):
            pass
    assert (orch.run_dir / "seam.json").exists()

    run_dir = str(orch.run_dir)
    state = {"run_dir": run_dir, "source_path": real_estate, "source_lang": "java", "target_lang": "kotlin", "current_seam": ""}
    result, _error = _direct_tool_fallback(PipelinePhase.FEATURE_SPECIFIER, state)

    assert result is not None
    # The bug: this used to be the bare {"ok": True, "specs_written": N} stub.
    assert isinstance(result.get("specs"), list) and len(result["specs"]) > 0, \
        "fallback should return the full feature_specs object, not submit_feature_specs()'s summary"
    assert _is_valid_artifact("feature_specs", result)

    # Reproduce exactly what run_phase() does with a fallback result, and
    # confirm it no longer clobbers the file feature_specs() already wrote.
    orch._save_artifact("feature_specs", result)
    import json
    on_disk = json.loads((orch.run_dir / "feature_specs.json").read_text(encoding="utf-8"))
    assert isinstance(on_disk.get("specs"), list) and len(on_disk["specs"]) > 0


# ── crash-recovery falls through to post-phase hooks (#60/#61/#62) ─────────────
#
# Confirmed live, 2026-09: run_phase()'s LLM-crash handler correctly saved a
# valid deterministic fallback artifact but then returned immediately, before
# ever reaching that phase's own "happy path" post-phase hooks — Observer's
# CQRS-hint detection and seam/work-stream production, Cartographer's
# seam/work-stream refresh, Architect's run_meta.json + HTML reports/RAG
# index. A crash in LLM mode was silently degrading the pipeline *below* the
# deterministic-mode floor, reproduced identically 3 phases in a row on the
# same real run and across two separate runs of the same estate.

@pytest.fixture
def llm_mode_orch(monkeypatch, tmp_path):
    import micro_cosmos.settings as settings_mod
    s = settings_mod.Settings(skip_llm=False, runs_dir=str(tmp_path))
    monkeypatch.setattr(settings_mod, "_settings", s)
    from micro_cosmos.orchestration.pipeline import MicroCosmosOrchestrator
    return MicroCosmosOrchestrator(run_id="test-run-crash", skip_llm=False)


async def _crash_run_phase(monkeypatch, orch, phase):
    import micro_cosmos.orchestration.pipeline as pipeline_mod

    async def _raise_context_overflow(*args, **kwargs):
        raise RuntimeError("Error code: 400 - {'error': 'Context size has been exceeded.'}")

    monkeypatch.setattr(pipeline_mod, "_drain_runner", _raise_context_overflow)
    events = []
    async for ev in orch.run_phase(phase):
        events.append(ev)
    return events


async def test_observer_crash_still_runs_post_phase_hooks(monkeypatch, llm_mode_orch):
    import json
    from micro_cosmos.orchestration.pipeline import PipelinePhase
    orch = llm_mode_orch
    await orch.initialise_session(ESTATE, "cobol", "go")

    events = await _crash_run_phase(monkeypatch, orch, PipelinePhase.OBSERVER)

    assert any(ev.kind == "error" for ev in events), "the crash itself must still surface as an error event"

    ir_path = orch.run_dir / "ir_graph.json"
    assert ir_path.exists(), "crash-recovery fallback must still produce a valid ir_graph.json"
    ir = json.loads(ir_path.read_text(encoding="utf-8"))
    assert ir.get("nodes"), "fallback ir_graph must have real nodes, not an empty shell"

    # The actual regression: before the fix, none of these ever ran because
    # the crash handler returned before reaching Observer's post-phase hooks.
    assert "cqrs_framework_hints" in ir, (
        "Observer's post-phase CQRS-framework-detection hook did not run after a crash"
    )
    assert (orch.run_dir / "seam.json").exists(), (
        "Observer's post-phase seam/work-stream production hook did not run after a crash"
    )


async def test_architect_crash_still_runs_post_phase_hooks(monkeypatch, llm_mode_orch):
    from micro_cosmos.orchestration.pipeline import PipelinePhase
    orch = llm_mode_orch
    await orch.initialise_session(ESTATE, "cobol", "go")

    # Architect's post-phase hooks read tnas.json and produce run_meta.json —
    # need a real (deterministic-fallback) tnas.json on disk first, exactly
    # as a real run would have by the time Architect's own turn starts.
    async for _ in orch.run_phase(PipelinePhase.OBSERVER):
        pass
    async for _ in orch.run_phase(PipelinePhase.CARTOGRAPHER):
        pass

    events = await _crash_run_phase(monkeypatch, orch, PipelinePhase.ARCHITECT)

    assert any(ev.kind == "error" for ev in events)
    assert (orch.run_dir / "tnas.json").exists(), "crash-recovery fallback must still produce a valid tnas.json"

    # The actual regression: before the fix, run_meta.json (and the HTML
    # reports / RAG index it enables) never got created because the crash
    # handler returned before reaching _run_architect_reports().
    assert (orch.run_dir / "run_meta.json").exists(), (
        "Architect's post-phase report-generation hook did not run after a crash"
    )


# ── gate-open artifact validity check (#63/BUG-14) ──────────────────────────
#
# Confirmed live: a cascade of upstream context-overflow crashes left
# feature_specs.json holding stale, confused LLM prose instead of real specs
# — and Gate 4.5 opened looking identical to a normal review, no signal to
# the human reviewer that they were about to approve garbage.

@pytest.fixture
def auto_approve_orch_for_gate_validity(monkeypatch, tmp_path):
    # skip_llm=False: the auto-approve-skips-an-invalid-artifact behavior
    # (review of PR #78, 2026-09-10) is deliberately scoped to LLM mode only
    # — deterministic mode has no LLM-call-crash concept, and at least one
    # phase (PR_REVIEWER) has no deterministic fallback at all, which would
    # otherwise permanently block auto-approve at Gate 5 for every
    # deterministic run. See open_gate()'s own comment for the full reasoning.
    import micro_cosmos.settings as settings_mod
    s = settings_mod.Settings(skip_llm=False, runs_dir=str(tmp_path))
    monkeypatch.setattr(settings_mod, "_settings", s)
    from micro_cosmos.orchestration.pipeline import MicroCosmosOrchestrator
    return MicroCosmosOrchestrator(
        run_id="gate-validity-unit-test",
        skip_llm=False,
        auto_approve_gates=True,
        auto_approve_reviewer_name="Jane Reviewer",
    )


async def test_open_gate_warns_when_artifact_fails_validity_check(auto_approve_orch_for_gate_validity):
    import asyncio
    from micro_cosmos.orchestration.pipeline import PipelinePhase
    orch = auto_approve_orch_for_gate_validity
    # Simulates BUG-14's exact real-world shape: an empty/malformed dict left
    # behind by a crashed agent turn whose fallback also produced nothing.
    orch.artifacts["ir_graph"] = {}

    # auto_approve_gates no longer bypasses an invalid artifact (review of
    # PR #78, 2026-09-10 — see test_open_gate_does_not_auto_approve_an_
    # invalid_artifact), so this now genuinely blocks until approved by hand,
    # same as a manual-review gate would.
    async def _drain():
        return [ev async for ev in orch.open_gate(PipelinePhase.GATE_1)]

    task = asyncio.ensure_future(_drain())
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(asyncio.shield(task), timeout=0.05)
    orch.approve_gate("gate_1", "human reviewer")
    events = await asyncio.wait_for(task, timeout=2)

    warnings = [ev for ev in events if ev.kind == "warning"]
    assert warnings, "an invalid artifact must produce a visible warning, not just open silently"
    assert "fails its own validity check" in warnings[0].payload["message"]

    gate_opened = next(ev for ev in events if ev.kind == "gate_opened")
    assert gate_opened.payload["artifact_valid"] is False


async def test_open_gate_no_warning_for_valid_artifact(auto_approve_orch_for_gate_validity):
    from micro_cosmos.orchestration.pipeline import PipelinePhase
    orch = auto_approve_orch_for_gate_validity
    orch.artifacts["ir_graph"] = {"nodes": [{"id": "prog.Foo"}]}

    events = [ev async for ev in orch.open_gate(PipelinePhase.GATE_1)]

    assert not any(ev.kind == "warning" for ev in events)
    gate_opened = next(ev for ev in events if ev.kind == "gate_opened")
    assert gate_opened.payload["artifact_valid"] is True


# ── review-of-PR-#78 fixes (2026-09-10) ──────────────────────────────────────
#
# Joao's review of PR #78 found the new Gate 4.5 backstop was a no-op (a real
# output_key mismatch meant _is_valid_artifact silently defaulted to True no
# matter what), auto_approve_gates bypassed the new warning entirely, and a
# crashed-then-recovered phase's error pill got silently overwritten to a
# green "done" one client-side. All three verified directly against the code
# before fixing, per this project's own house rule.

def test_is_valid_artifact_feature_specs_result_key_is_registered():
    """The real key used at runtime (feature_specifier_agent's ADK
    output_key) is "feature_specs_result", not "feature_specs" — confirmed
    via micro_cosmos/agents/feature_specifier.py. _checks previously only had a
    "feature_specs" entry, so every _is_valid_artifact(agent.output_key, ...)
    call for this phase fell through to the unconditional True default,
    silently no-op'ing both BUG-7's fallback-trigger check and #63's new
    Gate 4.5 validity banner for the exact scenario each was built for."""
    from micro_cosmos.orchestration.pipeline import _is_valid_artifact
    real_specs = {"specs": [{"seam_id": "seam1", "title": "x"}]}
    confirmation_stub = {"ok": True, "specs_written": 3}
    assert _is_valid_artifact("feature_specs_result", real_specs)
    assert not _is_valid_artifact("feature_specs_result", confirmation_stub)
    # The original key must still validate identically — existing callers
    # (e.g. this file's own BUG-7 regression test) use it directly.
    assert _is_valid_artifact("feature_specs", real_specs)
    assert not _is_valid_artifact("feature_specs", confirmation_stub)


def test_read_feature_specs_file_returns_merged_specs_not_the_stub(tmp_path):
    import json
    from micro_cosmos.orchestration.pipeline import _read_feature_specs_file

    (tmp_path / "feature_specs.json").write_text(json.dumps({
        "specs": [{"seam_id": "seam_a"}, {"seam_id": "seam_b"}],
    }))
    loaded = _read_feature_specs_file(tmp_path)
    assert [s["seam_id"] for s in loaded["specs"]] == ["seam_a", "seam_b"]

    (tmp_path / "feature_specs.json").write_text(json.dumps({"ok": True, "specs_written": 2}))
    assert _read_feature_specs_file(tmp_path) is None


async def test_open_gate_4_5_warns_on_stale_confirmation_stub(auto_approve_orch_for_gate_validity):
    """The actual GATE_4_5/feature_specs_result shape this bug hid — a
    regression test the original #63 PR should have had, per the review."""
    import asyncio
    from micro_cosmos.orchestration.pipeline import PipelinePhase
    orch = auto_approve_orch_for_gate_validity
    orch.artifacts["feature_specs_result"] = {"ok": True, "specs_written": 0}

    # See test_open_gate_warns_when_artifact_fails_validity_check — an
    # invalid artifact now blocks even with auto_approve_gates=True.
    async def _drain():
        return [ev async for ev in orch.open_gate(PipelinePhase.GATE_4_5)]

    task = asyncio.ensure_future(_drain())
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(asyncio.shield(task), timeout=0.05)
    orch.approve_gate("gate_4_5", "human reviewer")
    events = await asyncio.wait_for(task, timeout=2)

    warnings = [ev for ev in events if ev.kind == "warning"]
    assert warnings, "GATE_4_5 must warn on a confirmation-stub standing in for real specs"
    gate_opened = next(ev for ev in events if ev.kind == "gate_opened")
    assert gate_opened.payload["artifact_valid"] is False


async def test_open_gate_does_not_auto_approve_an_invalid_artifact(auto_approve_orch_for_gate_validity):
    """auto_approve_gates existed for the expected/common case, not the
    "something crashed upstream" case — an invalid artifact must still
    block on manual review even in an auto-approve run, since unattended
    runs are exactly the runs most exposed to the crash-recovery cascade
    the rest of this PR addresses."""
    import asyncio
    from micro_cosmos.orchestration.pipeline import PipelinePhase
    from micro_cosmos.schema.gate import GateDecision
    orch = auto_approve_orch_for_gate_validity
    orch.artifacts["ir_graph"] = {}  # invalid

    async def _drain():
        return [ev async for ev in orch.open_gate(PipelinePhase.GATE_1)]

    task = asyncio.ensure_future(_drain())
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(asyncio.shield(task), timeout=0.05)

    state = orch.gate_states["gate_1"]
    assert state.decision != GateDecision.APPROVED, "must not have auto-approved an invalid artifact"

    orch.approve_gate("gate_1", "human reviewer")
    events = await asyncio.wait_for(task, timeout=2)
    assert any(ev.kind == "warning" for ev in events)
    assert events[-1].payload["reviewer_name"] == "human reviewer"


async def test_phase_completed_flags_recovered_from_crash(monkeypatch, llm_mode_orch):
    """dashboard.js's markPhase() unconditionally overwrites the earlier
    "error" pill with "done" on phase_completed — without this flag, a
    crashed-then-recovered phase looked identical to a genuine success in
    the UI, silently erasing the exact signal #60/#61/#62 exist to surface."""
    from micro_cosmos.orchestration.pipeline import PipelinePhase
    orch = llm_mode_orch
    await orch.initialise_session(ESTATE, "cobol", "go")

    events = await _crash_run_phase(monkeypatch, orch, PipelinePhase.OBSERVER)
    completed = next(ev for ev in events if ev.kind == "phase_completed")
    assert completed.payload["recovered_from_crash"] is True


async def test_phase_completed_not_flagged_on_genuine_success(monkeypatch, llm_mode_orch):
    """skip_llm_orch can't exercise this — the skip_llm branch returns via
    its own separate phase_completed yield before ever reaching the
    LLM-mode code path this flag lives on. Mocks _drain_runner to succeed
    (return, not raise) instead of simulating a real model turn."""
    import micro_cosmos.orchestration.pipeline as pipeline_mod
    from micro_cosmos.orchestration.pipeline import PipelinePhase
    orch = llm_mode_orch
    await orch.initialise_session(ESTATE, "cobol", "go")

    async def _succeed(*args, **kwargs):
        return []

    monkeypatch.setattr(pipeline_mod, "_drain_runner", _succeed)
    events = [ev async for ev in orch.run_phase(PipelinePhase.OBSERVER)]
    assert not any(ev.kind == "error" for ev in events)
    completed = next(ev for ev in events if ev.kind == "phase_completed")
    assert completed.payload["recovered_from_crash"] is False


async def test_open_gate_auto_approves_invalid_artifact_in_deterministic_mode(monkeypatch, tmp_path):
    """Locks in the LLM-mode-only scope of the auto-approve-skip fix above.
    Found via a real hang while verifying that fix: deterministic mode has
    no LLM-call-crash concept, and PR_REVIEWER has no deterministic fallback
    registered at all (a pre-existing, already-warned-about, accepted gap —
    "skip_llm=true but no deterministic fallback for pr_reviewer") — so
    review_report is *always* structurally invalid at Gate 5 in this mode,
    not because of a crash. Gating auto-approve on validity mode-agnostically
    would have permanently blocked Gate 5 for every deterministic run."""
    import micro_cosmos.settings as settings_mod
    s = settings_mod.Settings(skip_llm=True, runs_dir=str(tmp_path))
    monkeypatch.setattr(settings_mod, "_settings", s)
    from micro_cosmos.orchestration.pipeline import MicroCosmosOrchestrator, PipelinePhase
    from micro_cosmos.schema.gate import GateDecision
    orch = MicroCosmosOrchestrator(
        run_id="det-mode-gate-validity-unit-test",
        skip_llm=True,
        auto_approve_gates=True,
        auto_approve_reviewer_name="Jane Reviewer",
    )
    orch.artifacts["ir_graph"] = {}  # invalid

    events = [ev async for ev in orch.open_gate(PipelinePhase.GATE_1)]

    assert any(ev.kind == "warning" for ev in events), "still warns even though it also auto-approves"
    state = orch.gate_states["gate_1"]
    assert state.decision == GateDecision.APPROVED
