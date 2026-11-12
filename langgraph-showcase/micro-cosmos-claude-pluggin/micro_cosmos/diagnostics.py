"""Diagnostics — structured error, warning, and debug event emission.

Single source of truth for how the pipeline reports things going wrong, things
that almost went wrong, and verbose internals. All emit via the same async
broadcast channel so the UI can subscribe to a single stream and filter
client-side.

Three severity tiers:

- ERROR: pipeline-halting. Agent failed, verifier rejected a hallucinated
  reference, missing Vertex credentials, malformed agent output.
- WARNING: non-fatal. Gate retry, fitness function in WARNING severity,
  stale documentation flag, tool retry after transient failure.
- DEBUG: verbose internals. Each tool call's full payload, session state
  snapshots, async-event metadata. Off by default; UI toggle enables.

Every event carries: severity, phase, source, message, timestamp, optional
traceback, optional structured context dict. Traceback is captured at the
catch site, never reconstructed."""

from __future__ import annotations

import json
import logging
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

log = logging.getLogger("micro_cosmos.diagnostics")


class Severity(str, Enum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    DEBUG = "DEBUG"


@dataclass
class DiagnosticEvent:
    """One unit of diagnostic information."""

    severity: Severity
    phase: str
    source: str            # e.g. "orchestrator", "observer_agent", "verifier"
    message: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    traceback: str = ""    # populated for ERROR; empty otherwise
    context: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "severity": self.severity.value,
            "phase": self.phase,
            "source": self.source,
            "message": self.message,
            "timestamp": self.timestamp,
            "traceback": self.traceback,
            "context": self.context,
        }

    def to_event_kind(self) -> str:
        """Map severity → orchestrator event kind so the UI can route it."""
        return {
            Severity.ERROR: "error",
            Severity.WARNING: "warning",
            Severity.DEBUG: "debug",
        }[self.severity]


def from_exception(
    exc: BaseException,
    *,
    phase: str,
    source: str,
    message: str | None = None,
    context: dict[str, Any] | None = None,
) -> DiagnosticEvent:
    """Construct an ERROR event from a caught exception. Captures the
    traceback at the call site so it reflects where it was caught, not
    where it was rebuilt."""
    tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    msg = message or f"{type(exc).__name__}: {exc}"
    return DiagnosticEvent(
        severity=Severity.ERROR,
        phase=phase,
        source=source,
        message=msg,
        traceback=tb,
        context=context or {},
    )


def warning(
    *, phase: str, source: str, message: str, context: dict[str, Any] | None = None
) -> DiagnosticEvent:
    return DiagnosticEvent(
        severity=Severity.WARNING,
        phase=phase,
        source=source,
        message=message,
        context=context or {},
    )


def debug(
    *, phase: str, source: str, message: str, context: dict[str, Any] | None = None
) -> DiagnosticEvent:
    return DiagnosticEvent(
        severity=Severity.DEBUG,
        phase=phase,
        source=source,
        message=message,
        context=context or {},
    )


def to_pipeline_event_json(diag: DiagnosticEvent) -> str:
    """Serialise a diagnostic event in the same envelope shape as
    PipelineEvent so the UI can consume them through one WebSocket."""
    return json.dumps({
        "kind": diag.to_event_kind(),
        "phase": diag.phase,
        "payload": diag.to_payload(),
    })
