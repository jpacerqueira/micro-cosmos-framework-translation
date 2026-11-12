"""Artifact base class — SHA-stamped, content-addressed."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, Field


class Artifact(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    sha: str = Field(default="", description="Content hash, 16 hex chars")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    produced_by: str = Field(default="", description="Name of the agent that produced this")

    def stamp(self, produced_by: str = "") -> "Artifact":
        if produced_by:
            self.produced_by = produced_by
        payload = self.model_dump_json(exclude={"sha", "created_at", "produced_by"})
        self.sha = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
        return self
