"""Human review gates — five gates spanning analysis and code generation phases."""

from __future__ import annotations

from micro_cosmos.schema.gate import (
    GateApproval,
    GateDecision,
    GateRejection,
    GateState,
    RejectionConstraint,
)


GATE_DEFINITIONS = [
    {
        "id": "gate_1",
        "name": "IR quality & dead-code review",
        "reviewer_role": "Client domain architect",
        "phase_after": "observer",
    },
    {
        "id": "gate_2",
        "name": "Bounded context map",
        "reviewer_role": "Business domain expert",
        "phase_after": "cartographer",
    },
    {
        "id": "gate_3",
        "name": "TNAS & migration plan",
        "reviewer_role": "Solution architect",
        "phase_after": "architect",
    },
    {
        "id": "gate_4",
        "name": "Security analysis review",
        "reviewer_role": "Security architect",
        "phase_after": "security",
    },
    {
        "id": "gate_4_5",
        "name": "Planning — translation scope &amp; feature specs review",
        "reviewer_role": "Engineering lead",
        "phase_after": "feature_specifier",
    },
    {
        "id": "gate_5",
        "name": "PR approval — generated code review",
        "reviewer_role": "Lead engineer",
        "phase_after": "pr_reviewer",
    },
]


def initial_gate_states() -> dict[str, GateState]:
    states = {}
    for g in GATE_DEFINITIONS:
        state = GateState(
            gate_id=g["id"],
            gate_name=g["name"],
            expected_reviewer_role=g["reviewer_role"],
        )
        state.stamp(produced_by="orchestrator")
        states[g["id"]] = state
    return states


def approve(state: GateState, reviewer_name: str, notes: str = "") -> GateState:
    approval = GateApproval(
        gate_id=state.gate_id,
        artifact_sha=state.pending_artifact_sha,
        reviewer_name=reviewer_name,
        reviewer_role=state.expected_reviewer_role,
        notes=notes,
    )
    approval.stamp(produced_by="gates.approve")
    state.approvals.append(approval)
    state.decision = GateDecision.APPROVED
    state.stamp(produced_by="gates.approve")
    return state


def reject(
    state: GateState,
    reviewer_name: str,
    reason: str,
    applies_to_agent: str,
) -> tuple[GateState, RejectionConstraint]:
    constraint = RejectionConstraint(
        gate_id=state.gate_id,
        reason=reason,
        applies_to_agent=applies_to_agent,
    )
    constraint.stamp(produced_by="gates.reject")
    rejection = GateRejection(
        gate_id=state.gate_id,
        artifact_sha=state.pending_artifact_sha,
        reviewer_name=reviewer_name,
        reviewer_role=state.expected_reviewer_role,
        constraint=constraint,
    )
    rejection.stamp(produced_by="gates.reject")
    state.rejections.append(rejection)
    state.rejection_count += 1
    state.decision = (
        GateDecision.ESCALATED if state.rejection_count >= 3 else GateDecision.REJECTED
    )
    state.stamp(produced_by="gates.reject")
    return state, constraint
