"""Canonical fitness-function library.

The Architect Agent always emits these rules. They are committed to the client
CI pipeline on day one and gate every PR for the duration of the engagement."""

from __future__ import annotations

from micro_cosmos.schema.fitness import FitnessFunction, FitnessSeverity, FitnessSuite


CANONICAL_RULES: list[FitnessFunction] = [
    FitnessFunction(
        id="NO_FLOAT_ON_MONETARY",
        name="No float or double on monetary fields",
        description=(
            "Any field whose IR role is `monetary` must be represented as a "
            "decimal type in the target language (BigDecimal in Java, "
            "decimal.Decimal in Python, rust_decimal in Rust)."
        ),
        severity=FitnessSeverity.BLOCKING,
        rationale=(
            "Source fixed-point decimal arithmetic is not equivalent to "
            "IEEE-754 floating point. Subtle precision drift would surface in "
            "year-end or high-volume batch processing, not in unit tests."
        ),
        spec="no_primitive_type_on_field_role:monetary:float,double",
        derived_from="whitepaper:correctness-constraint",
    ),
    FitnessFunction(
        id="NO_INFRASTRUCTURE_IN_DOMAIN",
        name="No infrastructure dependencies in domain core",
        description=(
            "The domain core may not import database, queue, or network "
            "libraries directly. All such access goes through a port adapter."
        ),
        severity=FitnessSeverity.BLOCKING,
        rationale="Preserves hexagonal architecture and testability of the domain.",
        spec="no_direct_dependency:domain_core,infrastructure",
        derived_from="ddd:hexagonal-architecture",
    ),
    FitnessFunction(
        id="CQRS_COMMAND_RETURN",
        name="CQRS commands return void or DomainEvent",
        description="Commands must not return data; only queries do.",
        severity=FitnessSeverity.BLOCKING,
        rationale="Prevents read/write conflation that defeats the CQRS split.",
        spec="command_return_type_in:void,DomainEvent",
        derived_from="ddd:cqrs",
    ),
    FitnessFunction(
        id="FSM_TRANSITIONS_VIA_STATE_MACHINE",
        name="State transitions must pass through the state machine",
        description=(
            "Status-like fields must not be mutated directly. All mutations "
            "go through the explicit state-machine class derived from the "
            "level-88 (or equivalent) conditions in the source."
        ),
        severity=FitnessSeverity.BLOCKING,
        rationale="Loses business invariants if status is mutated ad hoc.",
        spec="state_transition_via:state_machine",
        derived_from="pattern-agent:fsm-extraction",
    ),
    FitnessFunction(
        id="NO_DB_ACCESS_OUTSIDE_REPOSITORY",
        name="No direct database access outside repository adapter",
        description=(
            "Database clients may only be imported inside the repository "
            "adapter for the relevant aggregate."
        ),
        severity=FitnessSeverity.BLOCKING,
        rationale="Keeps the persistence boundary explicit and swappable.",
        spec="no_database_access_outside:repository_adapter",
        derived_from="ddd:repository-pattern",
    ),
]


def build_canonical_suite(target_language: str) -> FitnessSuite:
    suite = FitnessSuite(
        functions=list(CANONICAL_RULES),
        target_language=target_language,
        intended_commit_path="architecture/fitness/",
    )
    suite.stamp(produced_by="architect.fitness-library")
    return suite
