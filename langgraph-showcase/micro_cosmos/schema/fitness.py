"""Fitness functions — executable architecture rules."""

from __future__ import annotations

from enum import Enum

from pydantic import Field

from micro_cosmos.schema.artifact import Artifact


class FitnessSeverity(str, Enum):
    BLOCKING = "BLOCKING"
    WARNING = "WARNING"
    INFO = "INFO"


class FitnessFunction(Artifact):
    id: str = Field(description="Stable identifier, e.g. NO_FLOAT_ON_MONETARY")
    name: str
    description: str
    severity: FitnessSeverity = FitnessSeverity.BLOCKING
    rationale: str = Field(description="Why this rule exists")
    spec: str
    derived_from: str = Field(default="")


class FitnessFunctionResult(Artifact):
    function_id: str
    passed: bool
    offending_locations: list[str] = Field(default_factory=list)
    message: str = Field(default="")


class FitnessSuite(Artifact):
    functions: list[FitnessFunction] = Field(default_factory=list)
    target_language: str = Field(default="")
    intended_commit_path: str = Field(default="architecture/fitness/")
