"""Extensible registry of message-bus / CQRS coupling parsers.

Why this exists: seam detection finds seams from `CALLS` fan-in, `CALLS` crossing a
bounded-context boundary, and ETL scheduler task graphs. An event-driven estate couples
over a *message bus* — an aggregate applies an event, the bus routes it, an
`@EventHandler` in a different module reacts — so no `CALLS` edge is ever emitted
between the two sides and every existing pass is blind to the coupling. Measured on
`examples/java-axonframework-example-app`: 11 CALLS edges across 251 nodes and 9 Maven
modules (0.39 per file, vs 2.17 for a CRUD estate), producing 8 seams none of which
touched an aggregate, handler or saga.

This is the same shape of problem `scheduler_tools.py` already solves for ETL
schedulers: the coupling is declared somewhere other than the call graph. The registry
convention is deliberately identical — a tuple of `(detect_fn, parse_fn)` pairs, each
individually gated on its own `detect_fn`, so adding Kafka/NServiceBus/MediatR support
later means appending one entry here and changing nothing in `seam_tools.py`.

**Decoupling guarantee.** `discover_message_flows()` returns the empty shape for any
estate where no registered framework is detected, so the seam pass's loops are simply
empty and a non-CQRS estate's output is byte-for-byte unchanged. Nothing in this module
runs its body for an ordinary codebase.

Every parser returns the same shape:
    {"aggregates": [entry, ...], "sagas": [entry, ...], "flows": [flow, ...]}
where entry = {"name", "node_id", "source_location", "payloads": [str, ...]}
and   flow  = {"payload", "owners": [class name, ...], "handler_types": [str, ...],
               "source_location"}
"""

from __future__ import annotations

import re
from pathlib import Path

from micro_cosmos.tools.framework_tools import detect_cqrs_frameworks

# Handler roles that mean "this class consumes a message someone else emitted", i.e. the
# read/integration/orchestration side. "event-sourcing" is deliberately excluded: an
# @EventSourcingHandler replays an aggregate's own events onto itself, which is internal
# state reconstruction, not a coupling between two components.
_CONSUMER_ROLES = frozenset({"event", "saga-event", "query"})


def _nodes(ir: object) -> list[dict]:
    """Defensively extract the node list from an IR dict.

    Guards every shape: a non-dict ir, a missing/None "nodes" key, and non-dict entries
    inside the list. Returns [] rather than raising — a malformed IR must degrade to
    "no message seams", never break seam production for the whole run (the failure mode
    that caused BUG-1).
    """
    if not isinstance(ir, dict):
        return []
    nodes = ir.get("nodes")
    if not isinstance(nodes, list):
        return []
    return [n for n in nodes if isinstance(n, dict)]


def _attrs(node: dict) -> dict:
    # `or {}` rather than .get(key, {}) — the default only applies when the key is
    # missing, not when its value is explicitly null.
    a = node.get("attributes") or {}
    return a if isinstance(a, dict) else {}


def _owner_of(node_id: str) -> str:
    """method.PortfolioProjection.on_53 -> PortfolioProjection."""
    if not isinstance(node_id, str):
        return ""
    parts = node_id.split(".")
    return parts[1] if len(parts) >= 3 and parts[0] == "method" else ""


def detect_axon_flows(source_path: str, ir: object) -> bool:
    """Cheap gate: is AxonFramework actually in use in this estate?

    Reuses the existing manifest+annotation detector rather than re-implementing
    detection. Negative by default — any estate without Axon short-circuits here and
    parse_axon_flows() is never called.
    """
    try:
        hints = detect_cqrs_frameworks(source_path, ir if isinstance(ir, dict) else {})
        return "AxonFramework" in (hints.get("detected_frameworks") or [])
    except Exception:
        return False


def parse_axon_flows(source_path: str, ir: object) -> dict:
    """Correlate Axon handlers into message flows, aggregates and sagas.

    There is no handler-to-handler edge in the IR — the only join key is the payload
    type, captured per handler as attributes["handles_payload"] (the handler method's
    first parameter type). Two handlers naming the same payload in different classes
    are, by construction, the two ends of one message flow.
    """
    aggregates: list[dict] = []
    sagas: list[dict] = []
    by_payload: dict[str, dict] = {}
    payloads_by_owner: dict[str, set[str]] = {}

    for node in _nodes(ir):
        a = _attrs(node)
        nid = node.get("id") or ""
        loc = node.get("source_location") or ""
        name = node.get("name") or ""

        if a.get("is_axon_aggregate") == "true":
            aggregates.append({"name": name or nid, "node_id": nid,
                               "source_location": loc, "payloads": []})
        if a.get("is_axon_saga") == "true":
            sagas.append({"name": name or nid, "node_id": nid,
                          "source_location": loc, "payloads": []})

        role = a.get("handler_type") or ""
        payload = a.get("handles_payload") or ""
        if not role or not payload:
            continue
        owner = _owner_of(nid)
        if owner:
            payloads_by_owner.setdefault(owner, set()).add(payload)
        entry = by_payload.setdefault(
            payload, {"payload": payload, "owners": set(), "handler_types": set(),
                      "consumers": set(), "source_location": loc},
        )
        entry["owners"].add(owner or nid)
        entry["handler_types"].add(role)
        if role in _CONSUMER_ROLES and owner:
            entry["consumers"].add(owner)

    # Attach each aggregate's/saga's own payloads for evidence text.
    for coll in (aggregates, sagas):
        for e in coll:
            cls = (e["name"] or "").split(".")[-1]
            e["payloads"] = sorted(payloads_by_owner.get(cls, set()))

    flows = []
    for payload, e in by_payload.items():
        flows.append({
            "payload": payload,
            "owners": sorted(o for o in e["owners"] if o),
            "consumers": sorted(e["consumers"]),
            "handler_types": sorted(e["handler_types"]),
            "source_location": e["source_location"],
        })
    flows.sort(key=lambda f: f["payload"])
    return {"aggregates": aggregates, "sagas": sagas, "flows": flows}


# ── NATS / JetStream (+ Azure Event Hubs) ────────────────────────────────────
# The second parser in this registry, and the reason the registry exists: adding it
# required no change to seam_tools.py at all.
#
# Unlike Axon's in-process bus, NATS coupling crosses the process boundary to external
# infrastructure. The subject IS the contract, and the durable-consumer configuration
# (ack policy, max_deliver, ack_wait) carries redelivery semantics that must survive a
# migration — which is why these score as `external-integration` rather than as an
# ordinary cross-context flow.

_NATS_MANIFEST_SIGNATURES = ("io.nats", "azure-messaging-eventhubs")
_NATS_IMPORT_PREFIXES = ("io.nats.", "com.azure.messaging.eventhubs")

# Subject literals: jetStream.subscribe("uli.events.>"), .filterSubject("uli.events.>"),
# uli.publish("uli.events.portfolio.PortfolioCreated", ...). A NATS subject is
# dot-delimited and may end in a > or * wildcard.
_NATS_SUBJECT_RE = re.compile(r'"([a-z0-9_-]+(?:\.[a-z0-9_*-]+)*(?:\.[>*])?)"', re.IGNORECASE)
_NATS_SUBJECT_CALL_RE = re.compile(
    r'\b(?:subscribe|publish|filterSubject)\s*\(\s*"([^"]+)"', re.IGNORECASE
)
_NATS_DURABLE_RE = re.compile(r'\bdurable\s*\(\s*"([^"]+)"')


def _read_manifests_text(source_path: str) -> str:
    try:
        from micro_cosmos.tools.security_tools import read_manifest_files
        files = read_manifest_files(source_path).get("files", []) or []
    except Exception:
        return ""
    return "\n".join((f.get("content") or "") for f in files if isinstance(f, dict)).lower()


def detect_nats_flows(source_path: str, ir: object) -> bool:
    """Cheap, negative-by-default gate for NATS/JetStream or Azure Event Hubs usage."""
    try:
        text = _read_manifests_text(source_path)
        if any(sig in text for sig in _NATS_MANIFEST_SIGNATURES):
            return True
        # Manifest may be unreadable/absent — fall back to import evidence on the IR.
        for n in _nodes(ir):
            loc = n.get("source_location") or ""
            attrs = _attrs(n)
            blob = f"{loc} {attrs.get('imports', '')}"
            if any(p in blob for p in _NATS_IMPORT_PREFIXES):
                return True
    except Exception:
        return False
    return False


def _iter_source_files(source_path: str):
    root = Path(source_path)
    if not root.is_dir():
        return
    for f in root.rglob("*.java"):
        # target/ is build output — the same "don't scan generated trees" lesson as BUG-1.
        if "/target/" in f.as_posix():
            continue
        try:
            yield f, f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue


def _parse_streams_yaml(source_path: str) -> list[dict]:
    """JetStream stream/consumer topology, when the estate declares it.

    Same precedent as a Databricks Asset Bundle YAML: where an estate declares its own
    topology, that declaration beats inferring one from code. Parsed with a small line
    reader rather than adding a YAML dependency for one optional file.
    """
    root = Path(source_path)
    if not root.is_dir():
        return []
    consumers: list[dict] = []
    for y in root.rglob("streams.yaml"):
        if "/target/" in y.as_posix():
            continue
        try:
            lines = y.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        cur: dict = {}
        in_consumers = False
        for raw in lines:
            line = raw.split("#", 1)[0].rstrip()
            if not line.strip():
                continue
            if line.strip() == "consumers:":
                in_consumers = True
                continue
            if line.strip() == "streams:":
                in_consumers = False
                continue
            if not in_consumers:
                continue
            stripped = line.strip()
            if stripped.startswith("- "):
                if cur.get("durable") or cur.get("name"):
                    consumers.append(cur)
                cur = {"source_location": y.as_posix()}
                stripped = stripped[2:]
            if ":" in stripped:
                k, _, v = stripped.partition(":")
                cur[k.strip()] = v.strip().strip('"')
        if cur.get("durable") or cur.get("name"):
            consumers.append(cur)
    return consumers


def _subject_matches(pattern: str, subject: str) -> bool:
    """NATS subject matching, token-wise, per NATS wildcard semantics.

    '*' matches exactly one token; '>' matches one or more trailing tokens and is only
    valid as the final token. A previous version compared only the first two
    dot-separated segments, which wrongly paired a producer on
    "uli.events.portfolio.X" with a subscriber on "uli.events.billing.>" — same first
    two segments, entirely different subtree.
    """
    if pattern == subject:
        return True
    p_tokens = pattern.split(".")
    s_tokens = subject.split(".")
    for i, tok in enumerate(p_tokens):
        if tok == ">":
            # '>' must be final and needs at least one token to consume.
            return i == len(p_tokens) - 1 and len(s_tokens) > i
        if i >= len(s_tokens):
            return False
        if tok == "*":
            continue
        if tok != s_tokens[i]:
            return False
    return len(s_tokens) == len(p_tokens)


def parse_nats_flows(source_path: str, ir: object) -> dict:
    """Pair NATS producers and consumers on their subject.

    Producers and consumers share no call edge — they only ever agree on a subject
    string, so the subject is the join key exactly as the payload type is for Axon.
    """
    producers: dict[str, set[str]] = {}
    consumers: dict[str, set[str]] = {}
    durables: dict[str, str] = {}
    locations: dict[str, str] = {}

    declared = _parse_streams_yaml(source_path)

    # Two-pass, because neither a per-file import check nor no check at all is correct.
    #
    # A per-file `io.nats` import check misses the producer side: UliEventBridge.java
    # holds the literal subject strings but imports only UliPublisher, which is the
    # class that imports io.nats. But dropping the check entirely means ANY
    # publish/subscribe/filterSubject call with a dotted string literal is treated as
    # NATS — an unrelated MQTT client on "sensors.factory.temperature" in the same
    # estate was being scored as a full external-integration seam with NATS-specific
    # migration guidance attached (found in review by Samuel Mbah, PR #45).
    #
    # So: pass 1 establishes the estate's real NATS subject namespaces from files that
    # genuinely import NATS/Event Hubs, plus whatever streams.yaml declares. Pass 2
    # accepts a subject from a non-importing file only when it falls inside one of
    # those namespaces — which admits the thin-wrapper publisher and rejects the
    # unrelated broker.
    _namespaces: set[str] = set()
    _files: list = []
    for path, content in _iter_source_files(source_path):
        is_nats_file = any(pref in content for pref in _NATS_IMPORT_PREFIXES)
        _files.append((path, content, is_nats_file))
        if not is_nats_file:
            continue
        for m in _NATS_SUBJECT_CALL_RE.finditer(content):
            subj = m.group(1)
            if "." in subj:
                _namespaces.add(subj)
    for c in declared:
        for key in ("filter_subject", "subjects"):
            v = c.get(key)
            if v:
                _namespaces.add(v.strip().strip('[]"'))

    def _in_known_namespace(subject: str) -> bool:
        return any(
            _subject_matches(ns, subject) or _subject_matches(subject, ns)
            for ns in _namespaces
        )

    for path, content, is_nats_file in _files:
        cls = path.stem
        for m in _NATS_SUBJECT_CALL_RE.finditer(content):
            verb = m.group(0).split("(")[0].strip().lower()
            subject = m.group(1)
            if "." not in subject:
                continue  # not a NATS subject, just some other string arg
            if not is_nats_file and not _in_known_namespace(subject):
                continue  # unrelated broker/library in a NATS-using estate
            bucket = producers if "publish" in verb else consumers
            bucket.setdefault(subject, set()).add(cls)
            locations.setdefault(subject, path.as_posix())
        for m in _NATS_DURABLE_RE.finditer(content):
            durables[m.group(1)] = cls

    for c in declared:
        subj = c.get("filter_subject") or ""
        name = c.get("durable") or c.get("name") or ""
        if subj and name:
            consumers.setdefault(subj, set()).add(name)
            locations.setdefault(subj, c.get("source_location", ""))


    flows = []
    for subject in sorted(set(producers) | set(consumers)):
        prods = sorted(producers.get(subject, set()))
        cons = sorted(consumers.get(subject, set()))
        # Pair across the wildcard boundary too: a producer on
        # "uli.events.portfolio.X" is consumed by a subscriber on "uli.events.>".
        if not cons:
            # Pair a concrete published subject with any wildcard subscriber whose
            # pattern genuinely covers it, using real NATS matching — not a shared
            # two-segment prefix.
            for other, who in consumers.items():
                if ("*" in other or ">" in other) and _subject_matches(other, subject):
                    cons.extend(sorted(who))
            cons = sorted(set(cons))
        if not (prods or cons):
            continue
        flows.append({
            "payload": subject,
            "owners": sorted(set(prods) | set(cons)),
            "consumers": cons,
            "producers": prods,
            "handler_types": ["nats-subject"],
            "durables": sorted({d for d, _c in durables.items()}),
            "source_location": locations.get(subject, ""),
            "external": True,
        })
    return {"aggregates": [], "sagas": [], "flows": flows}


# (framework_name, detect_fn, parse_fn). The name must match what
# framework_tools.detect_cqrs_frameworks() reports, so "detected but not parseable"
# can be computed by comparing the two — see unparsed_frameworks().
_MESSAGE_FLOWS = (
    ("AxonFramework", detect_axon_flows, parse_axon_flows),
    ("NATS/JetStream", detect_nats_flows, parse_nats_flows),
)

_EMPTY: dict = {"aggregates": [], "sagas": [], "flows": [], "unparsed": []}


def parsed_frameworks() -> set[str]:
    """Framework names this registry can actually build a message graph for."""
    return {name for name, _d, _p in _MESSAGE_FLOWS}


def unparsed_frameworks(source_path: str, ir: object) -> list[str]:
    """Frameworks detection can NAME but the registry cannot PARSE.

    Without this, an estate using e.g. MediatR gets zero message seams and nothing
    anywhere says why — the estimate is silently understated. Surfacing the gap is the
    point: a parser is only added alongside a real fixture to verify it against (the
    standing rule from cqrs-framework-detection.md), so this list is expected to be
    non-empty for real-world estates and must be visible rather than swallowed.
    """
    try:
        hints = detect_cqrs_frameworks(source_path, ir if isinstance(ir, dict) else {})
        detected = set(hints.get("detected_frameworks") or [])
    except Exception:
        return []
    return sorted(detected - parsed_frameworks())


def discover_message_flows(source_path: str, ir: object) -> dict:
    """Merge message-flow graphs from every framework detected in source_path.

    Returns the empty shape when nothing is detected — callers can iterate the result
    unconditionally and get a no-op for ordinary estates.
    """
    if not source_path:
        return {"aggregates": [], "sagas": [], "flows": [], "unparsed": []}
    merged: dict = {"aggregates": [], "sagas": [], "flows": []}
    for _name, detect, parse in _MESSAGE_FLOWS:
        try:
            if not detect(source_path, ir):
                continue
            got = parse(source_path, ir)
        except Exception:
            # Never let a parser take down seam production — the BUG-1 lesson.
            continue
        if not isinstance(got, dict):
            continue
        for key in merged:
            vals = got.get(key)
            if isinstance(vals, list):
                merged[key].extend(vals)
    merged["unparsed"] = unparsed_frameworks(source_path, ir)
    return merged


def detect_any_message_flow(source_path: str, ir: object) -> bool:
    return any(detect(source_path, ir) for _n, detect, _p in _MESSAGE_FLOWS)
