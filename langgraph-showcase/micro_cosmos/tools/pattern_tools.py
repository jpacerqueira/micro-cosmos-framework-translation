"""Pattern extraction tools — domain model from IR and bounded contexts.

Used internally by derive_tnas; there is no standalone Pattern Agent in this pipeline."""

from __future__ import annotations


def extract_domain_model(source_path: str, source_lang: str) -> dict:
    """Return aggregates, domain events, ports, and FSMs for the source estate."""
    from micro_cosmos.tools.observer_tools import parse_source_estate
    from micro_cosmos.tools.cartographer_tools import analyse_bounded_contexts

    ir = parse_source_estate(source_path, source_lang)
    bc = analyse_bounded_contexts(source_path, source_lang)

    nodes_by_id = {n["id"]: n for n in ir.get("nodes", [])}
    edges = ir.get("edges", [])

    program_writers = {e["source_id"] for e in edges if e.get("type") == "CALLS"}
    program_readers = {e["target_id"] for e in edges if e.get("type") == "CALLS"}

    defines_count: dict[str, int] = {}
    for e in edges:
        if e.get("type") == "DEFINES":
            tgt = nodes_by_id.get(e.get("target_id", ""), {})
            if tgt.get("type") == "PROCEDURE":
                src = e["source_id"]
                defines_count[src] = defines_count.get(src, 0) + 1

    aggregates = []
    domain_events = []
    ports = []
    fsms = []
    value_objects = []

    _aggregate_seen: set[str] = set()

    _TEST_SUFFIXES = ("test", "tests", "spec", "specs", "mock", "stub", "fake")

    def _is_test_class(name: str) -> bool:
        low = name.lower()
        return any(low.endswith(s) for s in _TEST_SUFFIXES)

    def _agg_key(name: str) -> str:
        return name.lower()

    for context in bc.get("contexts", []):
        ctx_name = context["name"]
        program_ids = set(context["node_ids"])
        child_ids: set[str] = set()
        for e in edges:
            if e.get("type") == "DEFINES" and e["source_id"] in program_ids:
                child_ids.add(e["target_id"])
        all_ids = program_ids | child_ids

        for nid in all_ids:
            node = nodes_by_id.get(nid, {})
            node_name = node.get("name", nid)
            node_type = node.get("type", "")
            attrs = node.get("attributes", {})
            kind = attrs.get("kind", "")

            if node_type == "DATA_STRUCTURE":
                if kind == "interface":
                    direction = "IN" if any(
                        w in node_name for w in ("UseCase", "Service", "Handler", "Command")
                    ) else "OUT"
                    ports.append({
                        "name": node_name,
                        "direction": direction,
                        "context": ctx_name,
                        "node_id": nid,
                        "implements": attrs.get("implements", ""),
                    })
                elif kind in ("class", "trait"):
                    method_count = defines_count.get(nid, 0)
                    implements = attrs.get("implements", "")
                    extends = attrs.get("extends", "")
                    if method_count >= 2:
                        _key = _agg_key(node_name)
                        if not _is_test_class(node_name) and _key not in _aggregate_seen:
                            _aggregate_seen.add(_key)
                            aggregates.append({
                                "name": node_name,
                                "context": ctx_name,
                                "node_id": nid,
                                "value_objects": [],
                                "invariants": [],
                                "state_machine": None,
                                "method_count": method_count,
                                "implements": implements,
                                "extends": extends,
                            })
                    elif implements:
                        domain_events.append({
                            "name": f"{node_name}Executed",
                            "context": ctx_name,
                            "source_node_id": nid,
                        })

            elif node_type == "PROGRAM":
                if nid in program_writers and nid in program_readers:
                    _key = _agg_key(node_name)
                    if not _is_test_class(node_name) and _key not in _aggregate_seen:
                        _aggregate_seen.add(_key)
                        aggregates.append({
                            "name": node_name,
                            "context": ctx_name,
                            "node_id": nid,
                            "value_objects": [],
                            "invariants": [],
                            "state_machine": None,
                        })
                elif nid in program_writers and nid not in program_readers:
                    domain_events.append({
                        "name": f"{node_name}Completed",
                        "context": ctx_name,
                        "source_node_id": nid,
                    })
                elif "Reader" in node_name or "Loader" in node_name or "Interface" in node_name:
                    ports.append({
                        "name": f"I{node_name}Port",
                        "direction": "IN",
                        "context": ctx_name,
                        "node_id": nid,
                    })
                else:
                    _key = _agg_key(node_name)
                    if not _is_test_class(node_name) and _key not in _aggregate_seen:
                        _aggregate_seen.add(_key)
                        aggregates.append({
                            "name": node_name,
                            "context": ctx_name,
                            "node_id": nid,
                            "value_objects": [],
                            "invariants": [],
                            "state_machine": None,
                        })

        state_fields = [
            nodes_by_id[nid] for nid in all_ids
            if nodes_by_id.get(nid, {}).get("type") in ("DATA_ITEM", "STATE_FIELD")
            and (
                nodes_by_id.get(nid, {}).get("type") == "STATE_FIELD"
                or any(w in nodes_by_id.get(nid, {}).get("name", "").lower()
                       for w in ("status", "state", "decision", "phase", "stage"))
            )
        ]
        for sf in state_fields:
            fsms.append({
                "context": ctx_name,
                "state_field": sf["name"],
                "states": ["INITIAL", "PROCESSING", "COMPLETE", "FAILED"],
                "transitions": [
                    {"from": "INITIAL", "to": "PROCESSING", "trigger": f"start_{sf['name']}"},
                    {"from": "PROCESSING", "to": "COMPLETE", "trigger": f"complete_{sf['name']}"},
                    {"from": "PROCESSING", "to": "FAILED", "trigger": f"fail_{sf['name']}"},
                ],
            })

    _monetary_words = {"amount", "balance", "price", "rate", "cost", "fee", "total", "salary"}
    _date_words = {"date", "time", "timestamp", "at", "on"}
    seen_vo: set[str] = set()
    for n in ir.get("nodes", []):
        if n.get("type") != "DATA_ITEM":
            continue
        name_lower = n["name"].lower()
        type_hint = n.get("attributes", {}).get("type", "").lower()
        if any(w in name_lower for w in _monetary_words) and "float" not in type_hint:
            key = "MonetaryAmount"
            if key not in seen_vo:
                seen_vo.add(key)
                value_objects.append({"name": key, "fields": [n["name"]], "source_type": type_hint or "decimal"})
        elif any(w in name_lower for w in _date_words):
            key = "TemporalValue"
            if key not in seen_vo:
                seen_vo.add(key)
                value_objects.append({"name": key, "fields": [n["name"]], "source_type": type_hint or "datetime"})

    return {
        "aggregates": aggregates,
        "domain_events": domain_events,
        "ports": ports,
        "fsms": fsms,
        "value_objects": value_objects,
    }
