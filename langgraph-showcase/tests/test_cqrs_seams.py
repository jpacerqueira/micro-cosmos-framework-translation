"""Regression tests for CQRS / message-bus seam detection (BUG-2).

Background: seam detection only ever looked at CALLS fan-in, CALLS crossing a
bounded-context boundary, and ETL scheduler task graphs. An event-driven estate couples
over a message bus — an aggregate applies an event, the bus routes it, a handler in
another module reacts — so no CALLS edge exists and every pass was blind to it. Measured
on examples/java-axonframework-example-app: 11 CALLS edges across 251 nodes / 9 Maven
modules, yielding 8 seams of which none touched an aggregate, handler or saga, while the
IR already carried 20 Axon-annotated nodes that were simply discarded.

The two halves of this file matter equally:
  - message seams are actually produced for a real Axon estate, and
  - NOTHING changes for an estate with no message framework (the decoupling guarantee).
The second half is the regression guard that the new pass stays inert by default.
"""

from __future__ import annotations

import pytest

from micro_cosmos.tools.message_flow_tools import (
    detect_any_message_flow,
    discover_message_flows,
)
from micro_cosmos.tools.seam_tools import identify_seams

AXON_ESTATE = "examples/java-axonframework-example-app"
COBOL_ESTATE = "examples/cobol-bankxyz_fraud_detection"
JAVA_CRUD_ESTATE = "examples/java-springboot-legacy-app"


# ── The Axon estate now produces real message seams ──────────────────────────

def test_axon_estate_produces_message_seams() -> None:
    result = identify_seams(AXON_ESTATE, "java")
    message = [s for s in result["seams"] if s["type"] == "message"]
    assert message, "expected message-bus seams for an event-sourced Axon estate"
    assert result["seam_counts"]["message"] == len(message), (
        "seam_counts must include the new type — it is built from a hardcoded tuple "
        "that previously listed only object/boundary/link/preprocessing"
    )


def test_event_sourced_aggregate_is_a_seam() -> None:
    """Portfolio is an @Aggregate — the command-side consistency boundary and one of
    the hardest things in the estate to migrate. It produced no seam at all before."""
    result = identify_seams(AXON_ESTATE, "java")
    roles = {s.get("message_role") for s in result["seams"] if s["type"] == "message"}
    assert "aggregate" in roles
    agg = [s for s in result["seams"] if s.get("message_role") == "aggregate"]
    assert any("Portfolio" in s["side_a"] for s in agg)


def test_saga_is_a_seam() -> None:
    """AllocationSaga was wholly invisible to the parser before this change —
    @Saga/@SagaEventHandler were not in the recognised Axon annotation set."""
    result = identify_seams(AXON_ESTATE, "java")
    sagas = [s for s in result["seams"] if s.get("message_role") == "saga"]
    assert sagas, "expected a saga seam for AllocationSaga"
    assert any("AllocationSaga" in s["side_a"] for s in sagas)


def test_message_flow_between_distinct_components_is_a_seam() -> None:
    """A payload handled by two or more different classes is a real integration
    contract carried by the bus, with no CALLS edge anywhere between them."""
    result = identify_seams(AXON_ESTATE, "java")
    flows = [
        s for s in result["seams"]
        if s.get("message_role") in ("cross-context", "intra-context")
    ]
    assert flows, "expected at least one multi-consumer message flow seam"
    assert any("," in s["side_b"] for s in flows), (
        "a flow seam's side_b should list the multiple components sharing the payload"
    )


def test_message_seams_carry_real_story_points() -> None:
    """The whole point of BUG-2: the coupling must reach the estimate, not just the
    seam list. Also guards the _work_for_seam branch — without an explicit `message`
    branch these fall through to the config/Settings `else` at a flat S/6."""
    from micro_cosmos.tools.seam_tools import produce_seam_report
    from micro_cosmos.tools.observer_tools import observe_source_estate

    ir = observe_source_estate(AXON_ESTATE, "java")
    report = produce_seam_report(ir, source_path=AXON_ESTATE)
    msg = [s for s in report["seams"] if s["type"] == "message"]
    assert msg
    assert all(s["work"]["story_points"] > 0 for s in msg)
    # a saga must be scored the highest tier, never the flat preprocessing default
    saga = [s for s in msg if s.get("message_role") == "saga"]
    assert saga and saga[0]["work"]["effort"] == "L"
    assert saga[0]["work"]["story_points"] == 16
    assert "Settings" not in saga[0]["work"]["title"], (
        "a saga scored via the preprocessing fallback would be titled "
        "'Extract ... into a typed Settings interface'"
    )
    assert report["work_summary"]["by_type"]["message"]["story_points"] > 0


# ── Decoupling guarantee: inert for every non-CQRS estate ────────────────────

@pytest.mark.parametrize(
    "estate, lang",
    [(COBOL_ESTATE, "cobol"), (JAVA_CRUD_ESTATE, "java")],
)
def test_non_cqrs_estate_gets_no_message_seams(estate, lang) -> None:
    """The pass must never fire for an estate with no message framework. This is the
    explicit decoupling requirement — the BUG-1 lesson, where an unconditional detector
    broke an unrelated language's run."""
    assert detect_any_message_flow(estate, {}) is False
    result = identify_seams(estate, lang)
    assert [s for s in result["seams"] if s["type"] == "message"] == []
    assert result["seam_counts"]["message"] == 0


def test_discover_returns_empty_shape_for_non_cqrs_estate() -> None:
    got = discover_message_flows(COBOL_ESTATE, {})
    # "unparsed" was added by the BUG-2 follow-up so a detected-but-unparseable
    # framework can be surfaced; it is empty for an estate with no framework at all.
    assert got == {"aggregates": [], "sagas": [], "flows": [], "unparsed": []}


# ── Defensiveness (BUG-1 lesson: never raise, degrade to nothing) ────────────

@pytest.mark.parametrize(
    "ir",
    [
        {},
        {"nodes": None},
        {"nodes": []},
        {"nodes": [{"id": "class.X", "attributes": None}]},
        {"nodes": ["not-a-dict", 42, None]},
        {"nodes": [{"id": None, "attributes": {"handler_type": "event"}}]},
        [],
        None,
        "not-a-dict",
    ],
)
def test_malformed_ir_never_raises(ir) -> None:
    """A malformed or partial IR must degrade to 'no message seams', never break seam
    production for the entire run."""
    assert discover_message_flows("", ir) == {
        "aggregates": [], "sagas": [], "flows": [], "unparsed": [],
    }
    got = discover_message_flows(COBOL_ESTATE, ir)
    assert isinstance(got, dict)
    assert set(got) == {"aggregates", "sagas", "flows", "unparsed"}


# ── Coverage transparency: detected-but-unparsed frameworks (BUG-2 follow-up) ─
# detect_cqrs_frameworks() recognises six frameworks from manifest coordinates, but the
# registry only has flow parsers for the ones with a real fixture to verify against.
# The others must not silently contribute zero — the gap has to be visible, or a user
# reads an understated estimate with nothing indicating anything is missing.

def test_unparsed_frameworks_reported_when_no_parser_exists(tmp_path) -> None:
    from micro_cosmos.tools.message_flow_tools import parsed_frameworks, unparsed_frameworks

    # Minimal estate whose manifest names a framework we deliberately do not parse.
    (tmp_path / "pom.xml").write_text(
        "<project><dependencies><dependency>"
        "<groupId>com.example</groupId><artifactId>mediatr</artifactId>"
        "</dependency></dependencies></project>",
        encoding="utf-8",
    )
    unparsed = unparsed_frameworks(str(tmp_path), {})
    assert "MediatR" in unparsed
    assert "MediatR" not in parsed_frameworks()


def test_axon_is_reported_as_parsed_not_unparsed() -> None:
    from micro_cosmos.tools.message_flow_tools import parsed_frameworks, unparsed_frameworks

    assert "AxonFramework" in parsed_frameworks()
    assert "AxonFramework" not in unparsed_frameworks(AXON_ESTATE, {})


def test_discover_reports_unparsed_key(tmp_path) -> None:
    from micro_cosmos.tools.message_flow_tools import discover_message_flows

    (tmp_path / "pom.xml").write_text(
        "<project><dependencies><dependency><artifactId>nservicebus</artifactId>"
        "</dependency></dependencies></project>", encoding="utf-8",
    )
    got = discover_message_flows(str(tmp_path), {})
    assert "NServiceBus" in got["unparsed"]


def test_coverage_note_lands_in_the_seam_report(tmp_path) -> None:
    """The note must reach seam.json, not just a log line — that is what makes the
    understatement visible to whoever reads the estimate."""
    from micro_cosmos.tools.seam_tools import produce_seam_report

    (tmp_path / "pom.xml").write_text(
        "<project><dependencies><dependency><artifactId>wolverinefx</artifactId>"
        "</dependency></dependencies></project>", encoding="utf-8",
    )
    report = produce_seam_report({"nodes": [], "edges": []}, source_path=str(tmp_path))
    notes = report.get("coverage_notes")
    assert notes, "expected a coverage note for a detected-but-unparsed framework"
    assert any("Wolverine" in n for n in notes)
    assert any("understated" in n for n in notes)


def test_no_coverage_note_when_everything_is_parseable() -> None:
    """A fully-covered estate must not emit a spurious warning."""
    from micro_cosmos.tools.seam_tools import produce_seam_report
    from micro_cosmos.tools.observer_tools import observe_source_estate

    ir = observe_source_estate(AXON_ESTATE, "java")
    report = produce_seam_report(ir, source_path=AXON_ESTATE)
    assert report.get("coverage_notes") == []
