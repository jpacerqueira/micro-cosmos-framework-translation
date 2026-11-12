"""Regression tests for NATS/JetStream + Azure Event Hubs message seams (BUG-2 follow-up).

This is the second parser registered in message_flow_tools._MESSAGE_FLOWS, and adding it
required no change to seam_tools.py — which is the actual proof that the registry
decoupling built for BUG-2 works as intended.

Real fixture, not synthetic: examples/java-axonframework-example-app/.../05-uli-nats
declares io.nats:jnats:2.17.3 and com.azure:azure-messaging-eventhubs in its pom.xml,
pull-subscribes on "uli.events.>" with an explicit-ack durable consumer, and ships a
streams.yaml declaring three streams and three durable consumers. Per the standing rule
in cqrs-framework-detection.md, a parser is only written where a real fixture exists to
verify it against.
"""

from __future__ import annotations

import pytest

from micro_cosmos.tools.message_flow_tools import (
    _subject_matches,
    detect_nats_flows,
    discover_message_flows,
    parse_nats_flows,
)
from micro_cosmos.tools.seam_tools import identify_seams, produce_seam_report
from micro_cosmos.tools.observer_tools import observe_source_estate

NATS_ESTATE = "examples/java-axonframework-example-app"
COBOL_ESTATE = "examples/cobol-bankxyz_fraud_detection"
JAVA_CRUD_ESTATE = "examples/java-springboot-legacy-app"


def test_detects_nats_via_manifest_coordinates() -> None:
    assert detect_nats_flows(NATS_ESTATE, {}) is True


def test_subjects_are_extracted_from_real_source() -> None:
    flows = parse_nats_flows(NATS_ESTATE, {})["flows"]
    subjects = {f["payload"] for f in flows}
    # the wildcard the bridge pull-subscribes on, and a concrete published subject
    assert "uli.events.>" in subjects
    assert "uli.events.portfolio.PortfolioCreated" in subjects


def test_producer_and_consumer_pair_on_subject() -> None:
    """Producer and consumer share no call edge — only the subject string. A concrete
    published subject must resolve to the wildcard consumer that receives it."""
    flows = {f["payload"]: f for f in parse_nats_flows(NATS_ESTATE, {})["flows"]}
    created = flows["uli.events.portfolio.PortfolioCreated"]
    assert "UliEventBridge" in created["owners"], "expected the publishing class"
    assert created["consumers"], "expected the wildcard subscriber to be paired in"
    assert created["external"] is True


def test_declared_durable_consumers_are_read_from_streams_yaml() -> None:
    """streams.yaml declares the topology explicitly — the same 'the estate declares its
    own structure' precedent as a Databricks Asset Bundle YAML."""
    flows = {f["payload"]: f for f in parse_nats_flows(NATS_ESTATE, {})["flows"]}
    wildcard = flows["uli.events.>"]
    owners = set(wildcard["owners"])
    assert {"eventhub-bridge", "search-index-builder"} <= owners


def test_external_integration_seams_produced_for_the_estate() -> None:
    result = identify_seams(NATS_ESTATE, "java")
    ext = [s for s in result["seams"] if s.get("message_role") == "external-integration"]
    assert ext, "expected external-integration seams from the NATS bridge module"
    assert any("uli.events" in s["side_a"] for s in ext)


def test_external_integration_scored_highest_tier() -> None:
    """Crossing to external infrastructure carries subject contract + durable-consumer
    redelivery semantics — scored L/16/high, not as an ordinary in-process flow."""
    ir = observe_source_estate(NATS_ESTATE, "java")
    report = produce_seam_report(ir, source_path=NATS_ESTATE)
    ext = [s for s in report["seams"] if s.get("message_role") == "external-integration"]
    assert ext
    assert all(s["work"]["effort"] == "L" for s in ext)
    assert all(s["work"]["story_points"] == 16 for s in ext)
    assert all(s["work"]["risk"] == "high" for s in ext)


# ── Decoupling guarantee ─────────────────────────────────────────────────────

@pytest.mark.parametrize("estate, lang", [(COBOL_ESTATE, "cobol"), (JAVA_CRUD_ESTATE, "java")])
def test_non_nats_estates_are_untouched(estate, lang) -> None:
    assert detect_nats_flows(estate, {}) is False
    assert parse_nats_flows(estate, {})["flows"] == []
    result = identify_seams(estate, lang)
    assert [s for s in result["seams"] if s.get("message_role") == "external-integration"] == []


# ── Defensiveness ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad", ["", "/nonexistent/path/xyz", "."])
def test_bad_source_paths_never_raise(bad) -> None:
    assert detect_nats_flows(bad, {}) in (True, False)
    got = parse_nats_flows(bad, {})
    assert set(got) == {"aggregates", "sagas", "flows"}


@pytest.mark.parametrize("ir", [{}, None, [], {"nodes": None}, "str"])
def test_malformed_ir_never_raises(ir) -> None:
    got = discover_message_flows(NATS_ESTATE, ir)
    assert isinstance(got, dict)
    assert "flows" in got


# ── Precision fixes from Samuel Mbah's PR #45 review ─────────────────────────
# Both were reproduced before fixing. Neither crashed anything, which is exactly why
# they mattered: they produced a confident wrong number rather than an obvious failure.

def _nats_estate(tmp_path):
    (tmp_path / "pom.xml").write_text(
        "<project><dependency><groupId>io.nats</groupId></dependency></project>",
        encoding="utf-8",
    )
    (tmp_path / "RealNats.java").write_text(
        'import io.nats.client.JetStream;\n'
        'class RealNats { void g(JetStream j){ j.subscribe("uli.events.>"); } }',
        encoding="utf-8",
    )
    return tmp_path


def test_unrelated_broker_in_a_nats_estate_is_not_scored_as_nats(tmp_path):
    """An MQTT client on its own topic namespace, inside an estate that genuinely uses
    NATS elsewhere, was being scored as a full external-integration seam (L/16) with
    NATS-specific migration guidance attached to code with nothing to do with NATS."""
    p = _nats_estate(tmp_path)
    (p / "MqttThing.java").write_text(
        'import org.eclipse.paho.client.mqttv3.MqttClient;\n'
        'class MqttThing { void g(MqttClient c) throws Exception {\n'
        '  c.subscribe("sensors.factory.temperature");\n'
        '  c.publish("sensors.factory.humidity", null); } }',
        encoding="utf-8",
    )
    subjects = {f["payload"] for f in parse_nats_flows(str(p), {})["flows"]}
    assert not any(s.startswith("sensors.") for s in subjects), (
        f"unrelated MQTT topics leaked into NATS flows: {sorted(subjects)}"
    )
    assert "uli.events.>" in subjects, "the genuine NATS subject must still be found"


def test_thin_wrapper_producer_is_still_detected(tmp_path):
    """The reason the per-file import check was originally removed: the publishing class
    holds the subject literals but imports only its own wrapper, not io.nats. The
    namespace-based gate must still admit it — otherwise fixing the false positive
    would silently reintroduce the false negative."""
    p = _nats_estate(tmp_path)
    (p / "PortfolioPub.java").write_text(
        'class PortfolioPub { void g(Object uli){ publish("uli.events.portfolio.Created", null); } }',
        encoding="utf-8",
    )
    subjects = {f["payload"] for f in parse_nats_flows(str(p), {})["flows"]}
    assert "uli.events.portfolio.Created" in subjects


def test_wildcard_pairing_respects_subtree_boundaries(tmp_path):
    """_root() compared only the first two dot-segments, so a producer on
    uli.events.portfolio.X was paired with a subscriber on uli.events.billing.> —
    same prefix, unrelated subtree."""
    p = _nats_estate(tmp_path)
    (p / "BillingSub.java").write_text(
        'import io.nats.client.JetStream;\n'
        'class BillingSub { void g(JetStream j){ j.subscribe("uli.events.billing.>"); } }',
        encoding="utf-8",
    )
    (p / "PortfolioPub.java").write_text(
        'class PortfolioPub { void g(Object uli){ publish("uli.events.portfolio.Created", null); } }',
        encoding="utf-8",
    )
    flows = {f["payload"]: f for f in parse_nats_flows(str(p), {})["flows"]}
    cons = flows["uli.events.portfolio.Created"]["consumers"]
    assert "BillingSub" not in cons, f"paired across unrelated subtrees: {cons}"
    assert "RealNats" in cons, "the genuinely-covering uli.events.> subscriber must pair"


@pytest.mark.parametrize(
    "pattern, subject, expected",
    [
        ("uli.events.>", "uli.events.portfolio.Created", True),
        ("uli.events.>", "uli.events.x", True),
        ("uli.events.billing.>", "uli.events.portfolio.Created", False),
        ("uli.events.*", "uli.events.portfolio", True),
        ("uli.events.*", "uli.events.portfolio.Created", False),   # '*' is exactly one token
        ("a.b", "a.b", True),
        ("a.b", "a.b.c", False),
        ("a.b.c", "a.b", False),
        ("uli.events.>", "uli.events", False),                      # '>' needs >=1 token
    ],
)
def test_subject_matching_follows_nats_wildcard_semantics(pattern, subject, expected):
    assert _subject_matches(pattern, subject) is expected
