"""Gate-state-machine tests."""

from __future__ import annotations

from micro_cosmos.gates import approve, initial_gate_states, reject
from micro_cosmos.schema.gate import GateDecision


def test_initial_gate_states_pending() -> None:
    states = initial_gate_states()
    assert len(states) == 6  # gate_1, gate_2, gate_3, gate_4, gate_4_5, gate_5
    assert all(s.decision == GateDecision.PENDING for s in states.values())


def test_approve_records_approval() -> None:
    states = initial_gate_states()
    state = states["gate_1"]
    state.pending_artifact_sha = "abc123"
    approve(state, reviewer_name="Chris Jones", notes="LGTM")
    assert state.decision == GateDecision.APPROVED
    assert len(state.approvals) == 1
    assert state.approvals[0].reviewer_name == "Chris Jones"


def test_reject_produces_constraint() -> None:
    states = initial_gate_states()
    state = states["gate_2"]
    state.pending_artifact_sha = "def456"
    state, constraint = reject(
        state,
        reviewer_name="Domain expert",
        reason="Boundary between Credit and Customer is wrong",
        applies_to_agent="cartographer_agent",
    )
    assert state.decision == GateDecision.REJECTED
    assert state.rejection_count == 1
    assert constraint.applies_to_agent == "cartographer_agent"
    assert constraint.cannot_be_overridden_by_agent is True


def test_three_rejections_escalate() -> None:
    states = initial_gate_states()
    state = states["gate_3"]
    state.pending_artifact_sha = "x"
    for _ in range(3):
        state, _ = reject(state, "R", "bad", "pattern_agent")
    assert state.decision == GateDecision.ESCALATED
    assert state.rejection_count == 3
