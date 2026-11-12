"""Human review gates — approvals, rejections, and the RejectionConstraint."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import Field

from micro_cosmos.schema.artifact import Artifact


class GateDecision(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ESCALATED = "ESCALATED"


class RejectionConstraint(Artifact):
    gate_id: str
    reason: str = Field(description="Reviewer's free-text reason for rejection")
    applies_to_agent: str = Field(description="Name of the agent whose output was rejected")
    cannot_be_overridden_by_agent: bool = True


class GateApproval(Artifact):
    gate_id: str
    artifact_sha: str = Field(description="SHA of the proposal that was approved")
    reviewer_name: str
    reviewer_role: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    notes: str = Field(default="")


class GateRejection(Artifact):
    gate_id: str
    artifact_sha: str
    reviewer_name: str
    reviewer_role: str
    constraint: RejectionConstraint
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class GateState(Artifact):
    gate_id: str
    gate_name: str
    expected_reviewer_role: str
    decision: GateDecision = GateDecision.PENDING
    rejection_count: int = 0
    approvals: list[GateApproval] = Field(default_factory=list)
    rejections: list[GateRejection] = Field(default_factory=list)
    pending_artifact_sha: str = Field(default="")
