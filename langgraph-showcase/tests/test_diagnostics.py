"""Diagnostics tests — severity tiers, traceback capture, payload shape."""

from __future__ import annotations

import json

from micro_cosmos import diagnostics
from micro_cosmos.diagnostics import Severity


def test_warning_event_shape() -> None:
    d = diagnostics.warning(
        phase="observer",
        source="observer_agent",
        message="Documentation stale",
        context={"file": "adr_007.md"},
    )
    assert d.severity == Severity.WARNING
    assert d.phase == "observer"
    assert d.traceback == ""
    payload = d.to_payload()
    assert payload["severity"] == "WARNING"
    assert payload["context"] == {"file": "adr_007.md"}
    assert payload["timestamp"]


def test_debug_event_shape() -> None:
    d = diagnostics.debug(phase="ws", source="dashboard", message="ping")
    assert d.severity == Severity.DEBUG
    assert d.to_event_kind() == "debug"


def test_exception_event_captures_traceback() -> None:
    try:
        raise ValueError("simulated agent failure")
    except ValueError as exc:
        d = diagnostics.from_exception(
            exc,
            phase="observer",
            source="observer_agent",
            message="Agent crashed",
        )
    assert d.severity == Severity.ERROR
    assert "ValueError" in d.traceback
    assert "simulated agent failure" in d.traceback
    assert d.to_event_kind() == "error"


def test_serialisation_matches_pipeline_event_envelope() -> None:
    d = diagnostics.warning(phase="cartographer", source="x", message="m")
    raw = diagnostics.to_pipeline_event_json(d)
    parsed = json.loads(raw)
    assert set(parsed.keys()) == {"kind", "phase", "payload"}
    assert parsed["kind"] == "warning"
    assert parsed["phase"] == "cartographer"
    assert parsed["payload"]["message"] == "m"


def test_default_message_uses_exception_type_when_omitted() -> None:
    try:
        raise RuntimeError("boom")
    except RuntimeError as exc:
        d = diagnostics.from_exception(exc, phase="x", source="y")
    assert d.message == "RuntimeError: boom"
