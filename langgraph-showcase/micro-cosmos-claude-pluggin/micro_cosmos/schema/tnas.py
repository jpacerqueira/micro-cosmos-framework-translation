"""TNAS, bounded contexts, and the domain model — Phase 2–3 artifacts."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from micro_cosmos.schema.artifact import Artifact
from micro_cosmos.schema.ir import Confidence


class BoundedContext(Artifact):
    name: str = Field(description="Human-readable context name, sentence-case")
    node_ids: list[str] = Field(description="IR node IDs that belong to this context")
    confidence: Confidence = Field(
        description="HIGH if all 3 analyses agree, MEDIUM if 2, LOW if 1",
    )
    rationale: str = Field(description="Why the Cartographer drew this boundary")
    leaky_abstractions: list[str] = Field(
        default_factory=list,
        description="Shared data structures used across this context boundary",
    )


class BoundedContextMap(Artifact):
    contexts: list[BoundedContext] = Field(default_factory=list)
    cross_context_calls: list[tuple[str, str]] = Field(default_factory=list)


class StateMachine(Artifact):
    state_field: str = Field(description="Name of the IR STATE_FIELD this FSM derives from")
    states: list[str]
    transitions: list[tuple[str, str, str]] = Field(default_factory=list)


class DomainEvent(Artifact):
    name: str = Field(description="PastTenseVerb, e.g. LoanApproved")
    payload_fields: list[str] = Field(description="Field names in the event payload")
    emitted_by_node_id: str = Field(description="IR node that emits this event")


class DomainAggregate(Artifact):
    name: str
    root_node_id: str = Field(description="IR node ID of the aggregate root")
    value_object_fields: list[str] = Field(default_factory=list)
    invariants: list[str] = Field(default_factory=list)
    state_machine: StateMachine | None = None
    bounded_context: str = Field(description="Name of the owning bounded context")


class PortKind(str, Enum):
    QUERY = "QUERY"
    COMMAND = "COMMAND"
    EVENT_PUBLISHER = "EVENT_PUBLISHER"
    EVENT_SUBSCRIBER = "EVENT_SUBSCRIBER"
    REPOSITORY = "REPOSITORY"


class Port(Artifact):
    name: str
    kind: PortKind
    interface_signature: str = Field(description="Language-agnostic interface description")
    adapter_technology: str = Field(description="Target adapter, e.g. AlloyDB, Pub/Sub, REST")
    source_node_id: str = Field(description="IR node this port replaces")


class DomainModel(Artifact):
    aggregates: list[DomainAggregate] = Field(default_factory=list)
    events: list[DomainEvent] = Field(default_factory=list)
    ports: list[Port] = Field(default_factory=list)


class ServiceGranularity(str, Enum):
    MONOLITH = "MONOLITH"
    COARSE_SERVICE = "COARSE_SERVICE"
    MICROSERVICE = "MICROSERVICE"


class DataStore(str, Enum):
    ALLOYDB = "ALLOYDB"
    SPANNER = "SPANNER"
    BIGTABLE = "BIGTABLE"
    GCS_BIGQUERY = "GCS_BIGQUERY"
    FIRESTORE = "FIRESTORE"


class ConsistencyModel(str, Enum):
    STRONG = "STRONG"
    SAGA = "SAGA"
    EVENTUAL = "EVENTUAL"


class ExecutionModel(str, Enum):
    GKE_AUTOPILOT = "GKE_AUTOPILOT"
    CLOUD_RUN = "CLOUD_RUN"
    CLOUD_RUN_JOBS = "CLOUD_RUN_JOBS"
    DATAFLOW = "DATAFLOW"


class CommunicationStyle(str, Enum):
    REST = "REST"
    GRPC = "GRPC"
    PUBSUB = "PUBSUB"
    MQ = "MQ"


class ContextArchitecture(Artifact):
    bounded_context: str
    service_granularity: ServiceGranularity
    data_store: DataStore
    consistency_model: ConsistencyModel
    execution_model: ExecutionModel
    communication_style: CommunicationStyle
    rationale: str = Field(description="Which source signals drove each decision")


class TNAS(Artifact):
    """Technology-Neutral Architecture Specification — the Architect's output."""

    context_architectures: list[ContextArchitecture] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    target_language: str = Field(default="")
    target_runtime_notes: str = Field(default="")


class BoundedContextMapResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    contexts: list[dict] = Field(default_factory=list)
    cross_context_calls: list[list[str]] = Field(default_factory=list)


class DomainModelResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    aggregates: list[dict] = Field(default_factory=list)
    events: list[dict] = Field(default_factory=list)
    ports: list[dict] = Field(default_factory=list)


class TNASResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    context_architectures: list[dict] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    target_language: str = ""
    fitness_suite: dict = Field(default_factory=dict)
