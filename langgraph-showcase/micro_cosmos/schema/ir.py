"""Language-agnostic IR — the property graph the Observer produces."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from micro_cosmos.schema.artifact import Artifact


class Confidence(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class IRNodeType(str, Enum):
    PROGRAM = "PROGRAM"
    SECTION = "SECTION"
    PROCEDURE = "PROCEDURE"
    DATA_ITEM = "DATA_ITEM"
    DATA_STRUCTURE = "DATA_STRUCTURE"
    EXTERNAL_CALL = "EXTERNAL_CALL"
    STATE_FIELD = "STATE_FIELD"


class IREdgeType(str, Enum):
    CALLS = "CALLS"
    READS = "READS"
    WRITES = "WRITES"
    REFERENCES = "REFERENCES"
    DEFINES = "DEFINES"
    REDEFINES = "REDEFINES"
    CO_MUTATES_WITH = "CO_MUTATES_WITH"


class IRNode(Artifact):
    id: str = Field(description="Stable identifier, typically fully-qualified")
    type: IRNodeType
    name: str
    source_location: str = Field(description="path:line for traceability")
    attributes: dict[str, str] = Field(default_factory=dict)
    summary: str = Field(default="", description="Plain-English description of what this node does")
    inputs: list[dict[str, str]] = Field(
        default_factory=list,
        description="Input parameters — each entry has 'name', 'type', and optionally 'default'",
    )
    output: str = Field(default="", description="Return type or output description")


class IREdge(Artifact):
    source_id: str
    target_id: str
    type: IREdgeType
    attributes: dict[str, str] = Field(default_factory=dict)


class DeadCodeFinding(Artifact):
    node_id: str
    reason: str = Field(description="Why this node is considered unreachable")
    confidence: Confidence
    confirmed_by_telemetry: bool = Field(default=False)


class PerformanceFinding(Artifact):
    node_id: str
    pattern: str = Field(description="e.g. SQL_IN_LOOP, FILE_OPEN_IN_LOOP")
    severity: str = Field(description="CRITICAL | HIGH | MEDIUM | LOW")
    remediation: str = Field(description="Concrete remediation proposal")


class IRGraph(Artifact):
    """The complete IR. Output of the Observer Agent."""

    nodes: list[IRNode] = Field(default_factory=list)
    edges: list[IREdge] = Field(default_factory=list)
    dead_code: list[DeadCodeFinding] = Field(default_factory=list)
    performance_findings: list[PerformanceFinding] = Field(default_factory=list)
    documentation_bundle: dict[str, str] = Field(default_factory=dict)
    stale_documentation: list[str] = Field(default_factory=list)
    source_lang: str = Field(default="")
    source_snapshot_sha: str = Field(default="")

    def node_ids(self) -> set[str]:
        return {n.id for n in self.nodes}

    def edges_for(self, node_id: str) -> list[IREdge]:
        return [e for e in self.edges if e.source_id == node_id or e.target_id == node_id]


class IRGraphResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    nodes: list[dict] = Field(default_factory=list)
    edges: list[dict] = Field(default_factory=list)
    dead_code: list[dict] = Field(default_factory=list)
    performance_findings: list[dict] = Field(default_factory=list)
    documentation_bundle: dict[str, str] = Field(default_factory=dict)
    stale_documentation: list[str] = Field(default_factory=list)
    source_lang: str = ""
    source_snapshot_sha: str = ""
