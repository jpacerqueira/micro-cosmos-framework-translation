"""Seam analysis tools — identifies substitution boundaries in a source estate.

A seam (Feathers, Working Effectively with Legacy Code) is a point where you can
alter behaviour without editing the code at that point.  The four types detected
here are:

  object       — a node called by many callers; an interface or injection point
                 would let callers be decoupled from the concrete implementation.
  boundary     — an object seam whose name/summary suggests an external system
                 (HTTP, database, queue, cloud storage).  Warrants a port/adapter.
  link         — a directory boundary with significant cross-cutting CALLS traffic;
                 making the contract explicit reduces coupling between modules.
  preprocessing — a node whose name/summary suggests it controls behaviour via
                  configuration, feature flags, or environment variables.
"""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

_log = logging.getLogger(__name__)

# ── Pattern matchers ──────────────────────────────────────────────────────────

_OBJECT_PATTERNS = re.compile(
    r"\b(service|repository|repo|client|adapter|gateway|store|manager|"
    r"handler|provider|factory|registry|dispatcher|broker|connector)\b",
    re.IGNORECASE,
)

_BOUNDARY_PATTERNS = re.compile(
    r"\b(http|https|api|rest|graphql|grpc|database|db|sql|postgres|mysql|"
    r"mongo|redis|queue|message|event|pubsub|kafka|s3|gcs|blob|storage|"
    r"filesystem|file|socket|smtp|email)\b",
    re.IGNORECASE,
)

_PREPROCESSING_PATTERNS = re.compile(
    r"\b(config|configuration|settings?|feature.?flags?|env(?:ironment)?|"
    r"toggle|switch|properties)\b",
    re.IGNORECASE,
)

# Nodes whose IDs contain these suffixes are test artefacts, not real seams
_TEST_PATTERN = re.compile(r"\.(spec|test|e2e|mock|stub|fixture|fake)\b", re.IGNORECASE)

# Minimum callers for a node to qualify as an object/boundary seam on fan-in alone
_FAN_IN_THRESHOLD = 3
# Minimum CALLS edges crossing a directory pair to report a link seam
_LINK_EDGE_THRESHOLD = 2


# ── Public tool function ──────────────────────────────────────────────────────

def identify_seams(source_path: str, source_lang: str) -> dict:
    """Identify substitution seams in the source estate.

    Locates the IR (ir_graph.json in the run directory, in-memory cache, or by
    re-parsing the source estate) and returns a categorised list of seam candidates.
    Each seam names the two sides of the boundary, the evidence, and a concrete
    substitution note for the migration plan.
    """
    from pathlib import Path as _Path

    # 1. Try the on-disk IR from the same run directory
    ir: dict | None = None
    candidate = _Path(source_path).parent / "ir_graph.json"
    if candidate.exists():
        try:
            ir = json.loads(candidate.read_text(encoding="utf-8"))
        except Exception:
            pass

    # 2. Try the in-memory observer cache
    if ir is None:
        try:
            from micro_cosmos.tools.observer_tools import _ir_cache
            ir = _ir_cache.get(f"{source_path}:{source_lang}")
        except Exception:
            pass

    # 3. Re-run the observer to generate the IR
    if ir is None:
        from micro_cosmos.tools.observer_tools import parse_source_estate
        ir = parse_source_estate(source_path, source_lang)

    return _detect_seams(ir, source_path=source_path)


# ── Internal analysis (accepts an already-loaded IR dict) ────────────────────

def _adaptive_fan_in_threshold(callers_of: dict[str, list[str]], absolute: int, floor: int = 2) -> int:
    """Fall back to the estate's own max fan-in when it never reaches the
    absolute threshold — e.g. a small/sparse COBOL estate where the busiest
    real hub program has only 2 callers, below a threshold tuned for
    Java-scale codebases (where individual classes commonly have higher
    fan-in). Never drops below `floor`: a single caller isn't meaningfully
    a hub. No-op for estates that already clear `absolute` on their own.
    """
    if not callers_of:
        return absolute
    observed_max = max(len(c) for c in callers_of.values())
    return min(absolute, max(floor, observed_max))


def _detect_seams(ir: dict, bcm: dict | None = None, source_path: str | None = None) -> dict:
    """Analyse an IR dict and return seam candidates."""
    nodes = ir.get("nodes", [])
    edges = ir.get("edges", [])

    prog_nodes: dict[str, dict] = {
        n["id"]: n for n in nodes if n.get("type") == "PROGRAM"
    }
    # PROCEDURE-level nodes (e.g. COBOL paragraphs, methods) — see the fan-in
    # pass below for why these need their own analysis, separate from
    # prog_nodes: languages organised around a single top-level unit per file
    # (COBOL: one PROGRAM per file, with all real internal structure living
    # in its paragraphs) never surface fan-in at the PROGRAM level at all.
    proc_nodes: dict[str, dict] = {
        n["id"]: n for n in nodes if n.get("type") == "PROCEDURE"
    }

    # Build call-graph indices
    callers_of: dict[str, list[str]] = defaultdict(list)
    proc_callers_of: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        if e.get("type") == "CALLS":
            src, tgt = e["source_id"], e["target_id"]
            if src in prog_nodes and tgt in prog_nodes:
                callers_of[tgt].append(src)
            elif src in proc_nodes and tgt in proc_nodes:
                proc_callers_of[tgt].append(src)

    seams: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    _coverage_notes: list[str] = []

    def _add(seam: dict) -> None:
        if seam["id"] not in seen_ids:
            seen_ids.add(seam["id"])
            seams.append(seam)

    # ── Object / boundary seams: fan-in ──────────────────────────────────────
    _fan_in_threshold = _adaptive_fan_in_threshold(callers_of, _FAN_IN_THRESHOLD)
    for nid, callers in callers_of.items():
        if len(callers) < _fan_in_threshold:
            continue
        if _TEST_PATTERN.search(nid):
            continue
        n = prog_nodes[nid]
        if (n.get("attributes") or {}).get("etl_platform") == "bigquery_dataform":
            continue
        if (n.get("attributes") or {}).get("etl_activity"):
            continue
        label = f"{nid} {n.get('summary', '')}"
        seam_type = "boundary" if _BOUNDARY_PATTERNS.search(label) else "object"
        note = (
            "Wrap behind a port/adapter interface; the external system becomes "
            "replaceable without touching any of the callers."
            if seam_type == "boundary"
            else "Introduce a protocol or interface at this node; inject the "
            "concrete implementation at each construction site."
        )
        _add({
            "id": f"seam_{seam_type}_{nid}",
            "type": seam_type,
            "location": nid,
            "source_location": n.get("source_location", ""),
            "side_a": f"{len(callers)} caller(s)",
            "side_b": "concrete implementation",
            "evidence": [
                f"fan-in: {len(callers)}",
                f"callers include: {', '.join(sorted(callers)[:3])}",
            ],
            "substitution_note": note,
        })

    # ── Object/boundary seams: PROCEDURE-level fan-in ─────────────────────────
    # Mirrors the PROGRAM-level pass above, but over intra-program calls
    # (e.g. COBOL PERFORM between paragraphs). For a codebase whose real
    # internal structure lives below the PROGRAM level, this is often the
    # *only* signal that finds real substitution points at all — a COBOL
    # program with a busy shared paragraph (error handling, a scoring
    # routine called from several places) never shows up in the PROGRAM-level
    # pass, since that only sees cross-program CALL/EXEC CICS LINK traffic.
    _proc_fan_in_threshold = _adaptive_fan_in_threshold(proc_callers_of, _FAN_IN_THRESHOLD)
    for nid, callers in proc_callers_of.items():
        if len(callers) < _proc_fan_in_threshold:
            continue
        if _TEST_PATTERN.search(nid):
            continue
        n = proc_nodes[nid]
        label = f"{nid} {n.get('summary', '')}"
        seam_type = "boundary" if _BOUNDARY_PATTERNS.search(label) else "object"
        note = (
            "Wrap behind a port/adapter interface; the external system becomes "
            "replaceable without touching any of the callers."
            if seam_type == "boundary"
            else "Extract this into its own callable unit (function/interface); "
            "inject or parameterise it at each call site so it can be replaced "
            "or tested independently of its callers."
        )
        _add({
            "id": f"seam_{seam_type}_{nid}",
            "type": seam_type,
            "location": nid,
            "source_location": n.get("source_location", ""),
            "side_a": f"{len(callers)} caller(s)",
            "side_b": "concrete implementation",
            "evidence": [
                f"fan-in: {len(callers)} (intra-program/procedure-level)",
                f"callers include: {', '.join(sorted(callers)[:3])}",
            ],
            "substitution_note": note,
        })

    # ── Object seams: named patterns with any callers ─────────────────────────
    for nid, n in prog_nodes.items():
        if _TEST_PATTERN.search(nid):
            continue
        label = f"{nid} {n.get('summary', '')}"
        match = _OBJECT_PATTERNS.search(label)
        if match and callers_of.get(nid):
            _add({
                "id": f"seam_object_{nid}",
                "type": "object",
                "location": nid,
                "source_location": n.get("source_location", ""),
                "side_a": f"{len(callers_of[nid])} caller(s)",
                "side_b": "concrete implementation",
                "evidence": [
                    f"architectural pattern: '{match.group(0)}'",
                    f"fan-in: {len(callers_of[nid])}",
                ],
                "substitution_note": (
                    f"Named as a {match.group(0).lower()} — intended substitution point. "
                    "Extract an explicit interface if one does not already exist."
                ),
            })

    # ── Preprocessing seams: config/settings/feature-flag nodes ──────────────
    # Match the camelCase-split node-ID suffix OR high-confidence summary terms.
    # Full summary is excluded — too noisy (e.g. "tests feature X" would fire).
    for nid, n in prog_nodes.items():
        if _TEST_PATTERN.search(nid):
            continue
        if (n.get("attributes") or {}).get("etl_platform") == "bigquery_dataform":
            continue
        if "/etl_jobs/" in (n.get("source_location") or "").replace("\\", "/"):
            continue
        # Split camelCase ("AppSettings" → "App Settings") for \b matching.
        # Also insert a space before known keyword suffixes in lowercase-concatenated
        # Java-style IDs ("Fraudbatchjobconfig" → "Fraud batch job config").
        raw_suffix = nid.split(".")[-1]
        id_readable = re.sub(r"([a-z])([A-Z])", r"\1 \2", raw_suffix)
        id_readable = re.sub(
            r"(?i)(config(?:uration)?|settings?|properties|env(?:ironment)?)$",
            r" \1", id_readable,
        )
        summary = n.get("summary", "")
        # Summary only checked for compound terms unlikely to appear accidentally
        summary_match = re.search(
            r"\b(feature.?flag|feature.?toggle|env(?:ironment)?\s+variable)\b",
            summary, re.IGNORECASE,
        )
        domain_match = n.get("attributes", {}).get("domain", "") in (
            "configuration", "config", "settings", "properties",
        )
        match = _PREPROCESSING_PATTERNS.search(id_readable) or summary_match or domain_match
        if match:
            _add({
                "id": f"seam_preprocessing_{nid}",
                "type": "preprocessing",
                "location": nid,
                "source_location": n.get("source_location", ""),
                "side_a": "code that reads this configuration",
                "side_b": "configuration values / environment",
                "evidence": [f"pattern: '{match.group(0)}'"],
                "substitution_note": (
                    "Surface configuration through an explicit settings interface rather "
                    "than reading environment variables directly; this enables per-test "
                    "overrides and environment-agnostic deployments."
                ),
            })

    # ── Link seams: significant cross-directory call traffic ──────────────────
    cross_dir: dict[tuple[str, str], int] = defaultdict(int)
    for e in edges:
        if e.get("type") != "CALLS":
            continue
        src_n = prog_nodes.get(e["source_id"])
        tgt_n = prog_nodes.get(e["target_id"])
        if not src_n or not tgt_n:
            continue
        src_dir = _top_dir(src_n.get("source_location", ""))
        tgt_dir = _top_dir(tgt_n.get("source_location", ""))
        if src_dir and tgt_dir and src_dir != tgt_dir:
            key = (min(src_dir, tgt_dir), max(src_dir, tgt_dir))
            cross_dir[key] += 1

    for (dir_a, dir_b), count in cross_dir.items():
        if count < _LINK_EDGE_THRESHOLD:
            continue
        _add({
            "id": f"seam_link_{dir_a}__{dir_b}",
            "type": "link",
            "location": f"{dir_a}/ ↔ {dir_b}/",
            "source_location": "",
            "side_a": f"{dir_a}/",
            "side_b": f"{dir_b}/",
            "evidence": [f"{count} CALLS edges cross this directory boundary"],
            "substitution_note": (
                f"The {dir_a}/{dir_b} boundary carries significant call traffic. "
                "Define explicit contracts (interfaces or protocols) at the crossing "
                "points to allow either side to be migrated or replaced independently."
            ),
        })

    # ── Context boundary seams: CALLS crossing bounded context boundaries ────────
    # Supplements directory-based link seams for codebases where all files share
    # a single flat directory (e.g. COBOL mainframe programs).
    if bcm:
        ctx_of: dict[str, str] = {}
        for ctx in bcm.get("contexts", []):
            for nid in ctx.get("node_ids", []):
                ctx_of[nid] = ctx["name"]
        cross_ctx: dict[tuple[str, str], list[tuple[str, str]]] = defaultdict(list)
        for e in edges:
            if e.get("type") != "CALLS":
                continue
            src, tgt = e["source_id"], e["target_id"]
            if src not in prog_nodes or tgt not in prog_nodes:
                continue
            src_ctx = ctx_of.get(src, "")
            tgt_ctx = ctx_of.get(tgt, "")
            if src_ctx and tgt_ctx and src_ctx != tgt_ctx and "DeadCode" not in (src_ctx, tgt_ctx):
                src_platform = (prog_nodes[src].get("attributes") or {}).get("etl_platform")
                tgt_platform = (prog_nodes[tgt].get("attributes") or {}).get("etl_platform")
                if src_platform == "bigquery_dataform" and tgt_platform == "bigquery_dataform":
                    continue
                key = (min(src_ctx, tgt_ctx), max(src_ctx, tgt_ctx))
                cross_ctx[key].append((src, tgt))
        for (ctx_a, ctx_b), ctx_calls in cross_ctx.items():
            seam_id = f"seam_context_{ctx_a}__{ctx_b}"
            if seam_id in seen_ids:
                continue
            _add({
                "id": seam_id,
                "type": "link",
                "location": f"{ctx_a} ↔ {ctx_b}",
                "source_location": "",
                "side_a": ctx_a,
                "side_b": ctx_b,
                "evidence": [
                    f"{len(ctx_calls)} CALLS edge{'s' if len(ctx_calls) != 1 else ''} cross this context boundary",
                    *[f"{s} → {t}" for s, t in ctx_calls[:3]],
                ],
                "substitution_note": (
                    f"The {ctx_a}/{ctx_b} boundary has {len(ctx_calls)} inter-context "
                    "call(s). Define an explicit interface or service contract at this "
                    "boundary so either side can be migrated or replaced independently."
                ),
            })

    # ── Dataform SQLX models ────────────────────────────────────────────────
    # Each BigQuery table or view is a migration unit. ${ref()} fan-in on a
    # retail model is usually 1, below the hub threshold, and every file sits
    # in definitions/, so the passes above never see these boundaries.
    for nid, n in prog_nodes.items():
        attrs = n.get("attributes") or {}
        if attrs.get("etl_platform") != "bigquery_dataform":
            continue
        model = attrs.get("model_name") or n.get("name", nid)
        schema = attrs.get("schema") or ""
        materialization = attrs.get("materialization") or "table"
        relation = f"{schema}.{model}" if schema else model
        dep_ids = [
            e["target_id"] for e in edges
            if e.get("type") == "CALLS" and e.get("source_id") == nid and e.get("target_id") in prog_nodes
        ]
        _add({
            "id": f"seam_object_{nid}",
            "type": "object",
            "location": nid,
            "source_location": n.get("source_location", ""),
            "side_a": relation,
            "side_b": materialization,
            "target": {
                "model": model,
                "schema": schema,
                "relation": relation,
                "materialization": materialization,
                "platform": "",
                "platform_label": "",
            },
            "evidence": [
                f"dataform model: {materialization}",
                f"schema: {schema or 'default'}",
                f"columns: {attrs.get('column_count', '0')}",
                f"aggregation: {attrs.get('has_aggregation', 'false')}",
                f"dependencies: {len(dep_ids)}",
            ],
            "substitution_note": (
                f"Translate BigQuery Dataform {materialization} {relation} "
                "into the destination warehouse, keeping its columns and upstream refs."
            ),
        })
        for dep_id in dep_ids:
            dep = prog_nodes[dep_id]
            dep_attrs = dep.get("attributes") or {}
            dep_name = dep_attrs.get("model_name") or dep.get("name", dep_id)
            _add({
                "id": f"seam_link_{nid}__{dep_id}",
                "type": "link",
                "location": f"{model} → {dep_name}",
                "source_location": n.get("source_location", ""),
                "side_a": model,
                "side_b": dep_name,
                "target": {
                    "model": dep_name,
                    "schema": dep_attrs.get("schema") or "",
                    "relation": f"{model} → {dep_name}",
                    "materialization": "ref",
                    "platform": "",
                    "platform_label": "",
                },
                "evidence": [
                    f"1 Dataform ref: {model} depends on {dep_name}",
                ],
                "substitution_note": (
                    f"Keep {model} scheduled after {dep_name}. "
                    "The destination job or dbt ref must preserve this dependency."
                ),
            })

    # ── ETL scheduler seams: scheduler-declared task dependencies ───────────
    # A scheduler's tasks (Databricks Asset Bundle job tasks, ADF pipeline
    # activities, or any other format registered in scheduler_tools.py) are
    # chained by the *scheduler itself*, not by any source-code CALLS
    # relationship — a notebook task and the task that runs after it
    # typically share no actual function call at all, so neither the fan-in
    # passes above nor the CALLS-derived context-boundary pass above can
    # ever find these boundaries. The scheduler's own task graph is used
    # directly instead of inferring anything from code.
    if source_path:
        from micro_cosmos.tools.databricks_bundle_tools import task_context_label
        from micro_cosmos.tools.scheduler_tools import discover_task_graph

        _scheduler_tasks = discover_task_graph(source_path)["tasks"]
        for tk, tdef in _scheduler_tasks.items():
            tgt_label = task_context_label(tk)
            notebooks = [Path(path).name for path in tdef["owns_files"]]
            notebook = notebooks[0] if notebooks else ""
            _add({
                "id": f"seam_object_act.{tgt_label}",
                "type": "object",
                "location": f"act.{tgt_label}",
                "source_location": "",
                "side_a": tgt_label,
                "side_b": notebook or tdef["kind"],
                "target": {
                    "model": tgt_label,
                    "schema": tdef["job"],
                    "relation": f"{tdef['job']}.{tgt_label}",
                    "materialization": tdef["kind"],
                    "platform": "",
                    "platform_label": "",
                },
                "evidence": [
                    f"scheduler activity: {tdef['kind']}",
                    f"job: {tdef['job']}",
                    f"notebook: {notebook or 'unresolved'}",
                    f"dependencies: {len(tdef['depends_on'])}",
                ],
                "substitution_note": (
                    f"Migrate scheduler activity {tgt_label} from {tdef['job']} "
                    f"with the notebook it runs ({notebook or 'unresolved path'})."
                ),
            })
            for dep_tk in tdef["depends_on"]:
                if dep_tk not in _scheduler_tasks:
                    continue
                src_label = task_context_label(dep_tk)
                seam_id = f"seam_dab_task_{src_label}__{tgt_label}"
                if seam_id in seen_ids:
                    continue
                _add({
                    "id": seam_id,
                    "type": "link",
                    "location": f"{src_label} ↔ {tgt_label}",
                    "source_location": "",
                    "side_a": src_label,
                    "side_b": tgt_label,
                    "evidence": [
                        f"1 declared task dependency (job/pipeline "
                        f"'{tdef['job']}': task '{tk}' depends_on '{dep_tk}')",
                    ],
                    "substitution_note": (
                        f"'{tk}' runs only after '{dep_tk}' completes, per the estate's "
                        "own scheduler — not a source-code call. Define an explicit "
                        f"handoff contract (the data/state '{dep_tk}' produces and '{tk}' "
                        "consumes) so either task can be migrated or replaced "
                        "independently of the other."
                    ),
                })

    # ── Message-bus seams: CQRS / event-driven coupling ─────────────────────
    # Same reasoning as the ETL-scheduler pass above, different declaration
    # mechanism. In an event-sourced estate an aggregate applies an event, the
    # message bus routes it, and a handler in another module reacts — there is
    # no CALLS edge between them, so the fan-in and context-boundary passes
    # above can never see the coupling. discover_message_flows() is gated on
    # its own per-framework detection and returns empty for any estate with no
    # message framework, so this whole block is a no-op for ordinary codebases.
    if source_path:
        from micro_cosmos.tools.message_flow_tools import discover_message_flows

        _mf = discover_message_flows(source_path, ir)
        _unparsed = _mf.get("unparsed") or []
        if _unparsed:
            # Loud, not silent: detection can name a framework the registry has no
            # parser for, in which case its message coupling contributes nothing and
            # the estimate is understated. Surfacing it beats a silent zero.
            _log.warning(
                "message-flow coverage gap: %s detected but not parseable — "
                "message-bus coupling for %s is not counted, seam estimate is understated",
                ", ".join(_unparsed), "it" if len(_unparsed) == 1 else "them",
            )
            _coverage_notes.append(
                f"{', '.join(_unparsed)} detected but not parseable — message-bus "
                "coupling for it is not counted; this seam estimate is understated."
            )
        _ctx_of_msg: dict[str, str] = {}
        if bcm:
            for _c in bcm.get("contexts", []):
                for _nid in _c.get("node_ids", []):
                    _ctx_of_msg[_nid] = _c["name"]

        def _ctx_for_class(cls: str) -> str:
            return _ctx_of_msg.get(f"class.{cls}", "")

        for _agg in _mf["aggregates"]:
            _name = _agg["name"]
            _add({
                "id": f"seam_msg_aggregate_{_name}",
                "type": "message",
                "message_role": "aggregate",
                "location": _agg["node_id"] or f"class.{_name}",
                "source_location": _agg["source_location"],
                "side_a": _name,
                "side_b": "command bus",
                "evidence": [
                    f"event-sourced aggregate handling {len(_agg['payloads'])} message type(s)",
                ],
                "substitution_note": (
                    f"{_name} is an event-sourced aggregate: its state is derived by replaying "
                    "its own event stream, not read from a table. Migrating it means preserving "
                    "the event schema and replay semantics, not just porting the class — treat "
                    "the command API and the emitted event contract as the substitution boundary."
                ),
            })

        for _saga in _mf["sagas"]:
            _name = _saga["name"]
            _add({
                "id": f"seam_msg_saga_{_name}",
                "type": "message",
                "message_role": "saga",
                "location": _saga["node_id"] or f"class.{_name}",
                "source_location": _saga["source_location"],
                "side_a": _name,
                "side_b": "event bus",
                "evidence": [
                    f"saga / process manager orchestrating {len(_saga['payloads'])} event type(s)",
                ],
                "substitution_note": (
                    f"{_name} is a long-running process manager coordinating several aggregates "
                    "via events. It holds workflow state across messages, so it cannot be "
                    "migrated piecemeal with either side — port it together with the event "
                    "contracts it starts and ends on, and re-verify timeout/compensation paths."
                ),
            })

        for _flow in _mf["flows"]:
            _owners = _flow["owners"]
            if len(_owners) < 2:
                continue  # single-owner payload: no coupling between components
            _ctxs = {c for c in (_ctx_for_class(o) for o in _owners) if c}
            _cross = len(_ctxs) > 1
            _payload = _flow["payload"]
            if _flow.get("external"):
                # Crosses the process boundary to external infrastructure (a broker,
                # a hub). The subject/topic is the contract and the durable-consumer
                # config carries redelivery semantics — materially harder to migrate
                # than an in-process handler, hence its own role and tier.
                _durables = _flow.get("durables") or []
                _add({
                    "id": f"seam_msg_external_{_payload}",
                    "type": "message",
                    "message_role": "external-integration",
                    "location": f"{_payload} ({', '.join(_owners)})",
                    "source_location": _flow.get("source_location", ""),
                    "side_a": _payload,
                    "side_b": ", ".join(_owners),
                    "evidence": [
                        f"{len(_owners)} component(s) bound to external subject/topic "
                        f"'{_payload}'"
                        + (f"; durable consumer(s): {', '.join(_durables)}" if _durables else ""),
                    ],
                    "substitution_note": (
                        f"'{_payload}' crosses the process boundary to external messaging "
                        "infrastructure. The subject/topic name, message schema and the "
                        "durable-consumer settings (ack policy, max deliveries, ack wait) "
                        "together form the contract — at-least-once delivery means consumers "
                        "must stay idempotent, and a dead-letter path must exist before either "
                        "side is migrated."
                    ),
                })
                continue
            _add({
                "id": f"seam_msg_flow_{_payload}",
                "type": "message",
                "message_role": "cross-context" if _cross else "intra-context",
                "location": f"{_payload} → {', '.join(_owners)}",
                "source_location": _flow["source_location"],
                "side_a": _payload,
                "side_b": ", ".join(_owners),
                "evidence": [
                    f"{len(_owners)} component(s) handle '{_payload}' "
                    f"({', '.join(_flow['handler_types'])})"
                    + (f" across bounded contexts {', '.join(sorted(_ctxs))}" if _cross else ""),
                ],
                "substitution_note": (
                    f"'{_payload}' is exchanged over the message bus between "
                    f"{', '.join(_owners)} — no source-code call connects them, so this "
                    "coupling is invisible to a call-graph reading of the codebase. The "
                    "message's schema IS the contract: version it explicitly and add a "
                    "consumer-driven contract test before either side is migrated."
                ),
            })

    counts = {
        t: sum(1 for s in seams if s["type"] == t)
        for t in ("object", "boundary", "link", "preprocessing", "message")
    }
    total = len(seams)
    _log.debug("seam analysis: %d seams (%s)", total, counts)

    return {
        "seams": seams,
        "seam_counts": counts,
        "total": total,
        "coverage_notes": _coverage_notes,
        "summary": (
            f"{total} seam(s) identified: "
            f"{counts['object']} object, "
            f"{counts['boundary']} boundary, "
            f"{counts['link']} link, "
            f"{counts['preprocessing']} preprocessing."
        ),
    }


# ── Seam report (seam.json) ───────────────────────────────────────────────────

def _parse_fan_in(evidence: list[str]) -> int:
    """Extract the numeric count from evidence strings like 'fan-in: 42'."""
    for ev in evidence:
        m = re.search(r"(\d+)", ev)
        if m:
            return int(m.group(1))
    return 0


def _short_name(location: str) -> str:
    """Return the final dotted segment of a node id, camelCase-split."""
    leaf = location.split(".")[-1]
    return re.sub(r"([a-z])([A-Z])", r"\1 \2", leaf)


def _evidence_value(seam: dict, prefix: str) -> str:
    for item in seam.get("evidence") or []:
        if item.startswith(prefix):
            return item.split(":", 1)[1].strip()
    return ""


def _is_dataform_model_seam(seam: dict) -> bool:
    return any(item.startswith("dataform model:") for item in seam.get("evidence") or [])


def _is_dataform_ref_seam(seam: dict) -> bool:
    return any(item.startswith("1 Dataform ref:") for item in seam.get("evidence") or [])


def _is_scheduler_activity_seam(seam: dict) -> bool:
    return any(item.startswith("scheduler activity:") for item in seam.get("evidence") or [])


def _is_scheduler_dep_seam(seam: dict) -> bool:
    return any("declared task dependency" in item for item in seam.get("evidence") or [])


def _destination_label(target_lang: str) -> str:
    return {
        "databricks": "Databricks SQL",
        "snowflake_dbt": "Snowflake dbt",
        "bigquery_dataform": "BigQuery Dataform",
    }.get(target_lang, "the destination warehouse")


def _work_for_dataform_model(seam: dict) -> dict:
    materialization = _evidence_value(seam, "dataform model:") or "table"
    relation = (seam.get("target") or {}).get("relation") or _short_name(seam.get("location", ""))
    dest = (seam.get("target") or {}).get("platform_label") or "the destination warehouse"
    aggregated = _evidence_value(seam, "aggregation:") == "true"
    try:
        columns = int(_evidence_value(seam, "columns:") or "0")
    except ValueError:
        columns = 0
    if aggregated or columns >= 8:
        effort, pts, risk = "M", 8, "medium"
    elif materialization == "view":
        effort, pts, risk = "S", 3, "low"
    else:
        effort, pts, risk = "S", 5, "low"
    return {
        "title": f"Migrate {relation} to {dest}",
        "effort": effort,
        "story_points": pts,
        "risk": risk,
        "migration_phase": "extraction",
        "steps": [
            f"Create {materialization} {relation} in {dest}",
            "Rewrite BigQuery types and functions (NUMERIC, IFNULL, DATE_SUB) to the destination dialect",
            "Replace ${ref()} with the destination reference and keep the column names",
            "Schedule this model after the upstream models it reads",
            "Check the grain and keep monetary columns decimal, not float",
        ],
    }


def _work_for_dataform_ref(seam: dict) -> dict:
    dest = (seam.get("target") or {}).get("platform_label") or "the destination warehouse"
    relation = (seam.get("target") or {}).get("relation") or seam.get("location", "")
    upstream = seam.get("side_b") or "the upstream model"
    downstream = seam.get("side_a") or "the downstream model"
    return {
        "title": f"Preserve {relation} in {dest}",
        "effort": "S",
        "story_points": 3,
        "risk": "low",
        "migration_phase": "isolation",
        "steps": [
            f"Declare that {downstream} runs only after {upstream} in {dest}",
            f"Point {downstream} at the migrated {upstream} relation, not the BigQuery source",
            "Fail the pipeline when the upstream model is missing",
        ],
    }


def _work_for_scheduler_activity(seam: dict) -> dict:
    relation = (seam.get("target") or {}).get("relation") or seam.get("side_a") or "activity"
    dest = (seam.get("target") or {}).get("platform_label") or "the destination warehouse"
    notebook = _evidence_value(seam, "notebook:") or "its notebook"
    try:
        deps = int(_evidence_value(seam, "dependencies:") or "0")
    except ValueError:
        deps = 0
    if deps >= 2:
        effort, pts, risk = "M", 8, "medium"
    else:
        effort, pts, risk = "S", 5, "low"
    return {
        "title": f"Migrate {relation} to {dest}",
        "effort": effort,
        "story_points": pts,
        "risk": risk,
        "migration_phase": "extraction",
        "steps": [
            f"Create the {dest} task for {relation}",
            f"Point it at the migrated notebook {notebook}",
            "Keep the activity parameters and the warehouse it writes",
            "Run it only after the upstream activities listed on the pipeline",
        ],
    }


def _work_for_scheduler_dep(seam: dict) -> dict:
    dest = (seam.get("target") or {}).get("platform_label") or "the destination warehouse"
    upstream = seam.get("side_a") or "the upstream activity"
    downstream = seam.get("side_b") or "the downstream activity"
    return {
        "title": f"Keep {downstream} after {upstream} in {dest}",
        "effort": "S",
        "story_points": 3,
        "risk": "low",
        "migration_phase": "isolation",
        "steps": [
            f"Declare that {downstream} runs only after {upstream} succeeds",
            f"Point {downstream} at the notebook migrated for {upstream}'s output",
            "Fail the job when the upstream activity is missing",
        ],
    }


def _work_for_seam(seam: dict) -> dict:
    """Derive concrete work metadata from a single seam."""
    if _is_dataform_model_seam(seam):
        return _work_for_dataform_model(seam)
    if _is_dataform_ref_seam(seam):
        return _work_for_dataform_ref(seam)
    if _is_scheduler_activity_seam(seam):
        return _work_for_scheduler_activity(seam)
    if _is_scheduler_dep_seam(seam):
        return _work_for_scheduler_dep(seam)
    location = (seam.get("source_location") or "").replace("\\", "/")
    if seam.get("type") == "object" and any(
        part in location for part in ("/etl_jobs/", "/notebooks/", "/data_quality/", "/data_profiling/")
    ):
        name = _short_name(seam.get("location", ""))
        return {
            "title": f"Keep {name} available to the notebooks that import it",
            "effort": "S",
            "story_points": 5,
            "risk": "low",
            "migration_phase": "extraction",
            "steps": [
                f"Translate {name} into the destination project",
                "Preserve the functions and classes the notebooks import",
                "Keep callers pointing at this module after the move",
            ],
        }
    stype = seam["type"]
    fan_in = _parse_fan_in(seam["evidence"])
    loc = seam["location"]
    name = _short_name(loc)

    if stype == "boundary":
        if fan_in >= 30:
            effort, pts, risk = "L", 16, "high"
        elif fan_in >= 10:
            effort, pts, risk = "M", 10, "high"
        else:
            effort, pts, risk = "S", 6, "medium"
        steps = [
            f"Define I{name}Port interface exposing only the methods callers require",
            f"Wrap the existing {name} implementation as {name}Adapter : I{name}Port",
            f"Update {fan_in} caller(s) to depend on I{name}Port via constructor injection",
            f"Register {name}Adapter in the DI container (swap at a single wiring site)",
            f"Implement a Fake{name}Port in-memory double for use in unit tests",
        ]
        title = f"Introduce I{name}Port and {name}Adapter (port/adapter)"
        phase = "adaptation"

    elif stype == "object":
        if fan_in >= 50:
            effort, pts, risk = "L", 16, "medium"
        elif fan_in >= 16:
            effort, pts, risk = "M", 10, "medium"
        elif fan_in >= 6:
            effort, pts, risk = "S", 6, "low"
        else:
            effort, pts, risk = "XS", 4, "low"
        steps = [
            f"Extract I{name} interface from the concrete {name} class",
            f"Update {fan_in} caller(s) to accept I{name} in their constructors",
            "Update DI registrations to bind the concrete class to the interface",
            f"Create a Stub{name} test double implementing I{name} for unit tests",
        ]
        title = f"Extract I{name} interface and inject at {fan_in} call site(s)"
        phase = "extraction"

    elif stype == "link":
        # fan_in is the edge count for link seams
        edges = fan_in
        if edges >= 16:
            effort, pts, risk = "L", 16, "medium"
        elif edges >= 6:
            effort, pts, risk = "M", 10, "medium"
        else:
            effort, pts, risk = "S", 6, "low"
        side_a = seam.get("side_a", "").rstrip("/")
        side_b = seam.get("side_b", "").rstrip("/")
        steps = [
            f"Audit the {edges} CALLS edges crossing the {side_a}/{side_b} boundary",
            f"Define an explicit public API for {side_a}/ (barrel export, facade, or interface module)",
            "Restrict direct cross-boundary imports with an ESLint / ArchUnit rule",
            "Migrate all crossing callers to reference only the public API",
            "Add a boundary-crossing test that fails if any new direct import bypasses the API",
        ]
        title = f"Define explicit contract at the {side_a}/↔{side_b}/ boundary"
        phase = "isolation"

    elif stype == "message":
        # Message-bus coupling is not scored by fan-in: an event-sourced aggregate with a
        # single handler is still among the hardest things in an estate to migrate, and an
        # async contract's difficulty is driven by its role and whether it crosses a
        # bounded context — not by how many callers a call-graph shows (there are none).
        # NOTE this branch is mandatory, not an optimisation: without it these seams fall
        # through to the `else` below and are silently labelled config/Settings seams with
        # os.environ migration steps.
        role = seam.get("message_role", "intra-context")
        side_a = seam.get("side_a", name)
        side_b = seam.get("side_b", "")
        if role == "external-integration":
            effort, pts, risk = "L", 16, "high"
            steps = [
                f"Pin the subject/topic contract for '{side_a}' and version its message schema",
                "Recreate durable consumer settings exactly (ack policy, ack wait, max deliveries)",
                "Prove consumer idempotency — external brokers redeliver on at-least-once",
                "Stand up a dead-letter/parking path and alert on it before cutover",
                f"Run old and new consumers side by side on '{side_a}' and diff outcomes",
            ]
            title = f"Migrate external messaging integration on '{side_a}'"
            phase = "isolation"
        elif role == "saga":
            effort, pts, risk = "L", 16, "high"
            steps = [
                f"Map every event {side_a} starts, continues and ends on, with its association property",
                "Model the saga's persisted workflow state explicitly as a first-class schema",
                "Port timeout/deadline handling and compensating actions before the happy path",
                "Replay a real historical event sequence against the migrated saga and diff the outcome",
                "Add a contract test per participating event so a schema change fails loudly",
            ]
            title = f"Migrate {side_a} process manager with its event choreography"
            phase = "isolation"
        elif role == "aggregate":
            effort, pts, risk = "M", 10, "high"
            steps = [
                f"Freeze and version the event schema {side_a} emits (this is the real contract)",
                f"Port {side_a}'s command handlers, preserving the command-to-event mapping exactly",
                "Reimplement event-sourcing handlers so state is rebuilt by replay, not by direct assignment",
                f"Replay the existing {side_a} event stream and assert the rebuilt state matches",
                "Keep the aggregate identifier and routing key stable across the migration",
            ]
            title = f"Migrate event-sourced aggregate {side_a} (preserve replay semantics)"
            phase = "extraction"
        elif role == "cross-context":
            effort, pts, risk = "M", 10, "medium"
            steps = [
                f"Publish an explicit versioned schema for '{side_a}' as a shared contract artefact",
                f"Add a consumer-driven contract test for each consumer ({side_b})",
                "Introduce a translation/anti-corruption layer at the receiving context boundary",
                "Support both old and new message versions during the migration window",
                "Add monitoring for unroutable / dead-letter messages across the boundary",
            ]
            title = f"Version the '{side_a}' contract crossing bounded contexts"
            phase = "isolation"
        else:  # intra-context message flow
            effort, pts, risk = "S", 6, "low"
            steps = [
                f"Document '{side_a}' as an internal message contract between {side_b}",
                "Add a schema assertion so a field change breaks a test rather than a consumer",
                "Confirm handler idempotency — the bus may redeliver the same message",
                "Migrate producer and consumers together while the contract stays internal",
            ]
            title = f"Define the internal '{side_a}' message contract"
            phase = "adaptation"

    else:
        # Explicit guard, not a catch-all. This branch used to be a bare `else`
        # meaning "preprocessing", so any unrecognised type — a future seam type
        # added without its own branch, or a rename of "preprocessing" — was
        # silently scored as a config/Settings extraction with os.environ steps.
        # A wrong type must still return safe defaults (never raise mid-run), but
        # it must not do so silently.
        if stype != "preprocessing":
            _log.warning(
                "unrecognised seam type %r — scoring it as 'preprocessing'; add an "
                "explicit branch to _work_for_seam() for this type",
                stype,
            )
        effort, pts, risk = "S", 6, "low"
        steps = [
            f"Centralise all reads of the {name} configuration into a typed Settings class",
            "Inject the Settings instance via constructor (or a DI token) into each consumer",
            "Replace any direct process.env / os.environ reads with Settings accessors",
            "In tests, supply a TestSettings override instead of mutating environment variables",
            "Add a startup validation that fails fast if required settings are missing",
        ]
        title = f"Extract {name} into a typed Settings interface"
        phase = "extraction"

    return {
        "title": title,
        "effort": effort,
        "story_points": pts,
        "risk": risk,
        "migration_phase": phase,
        "steps": steps,
    }


def produce_seam_report(
    ir: dict,
    run_id: str | None = None,
    bcm: dict | None = None,
    source_path: str | None = None,
    target_lang: str | None = None,
) -> dict:
    """Run seam detection and enrich each seam with concrete work metadata.

    Returns a dict suitable for writing to seam.json.  Optionally writes to
    runs/{run_id}/seam.json when run_id is provided.
    """
    base = _detect_seams(ir, bcm=bcm, source_path=source_path)
    label = _destination_label(target_lang or "")
    for seam in base["seams"]:
        if not (
            _is_dataform_model_seam(seam)
            or _is_dataform_ref_seam(seam)
            or _is_scheduler_activity_seam(seam)
            or _is_scheduler_dep_seam(seam)
        ):
            continue
        target = seam.get("target")
        if not isinstance(target, dict):
            target = {}
            seam["target"] = target
        target["platform"] = target_lang or ""
        target["platform_label"] = label
    seams_with_work = []
    total_pts = 0
    pts_by_type: dict[str, int] = defaultdict(int)
    effort_dist: dict[str, int] = defaultdict(int)

    for seam in base["seams"]:
        work = _work_for_seam(seam)
        seams_with_work.append({**seam, "work": work})
        total_pts += work["story_points"]
        pts_by_type[seam["type"]] += work["story_points"]
        effort_dist[work["effort"]] += 1

    report = {
        "schema_version": "1.0",
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_seams": base["total"],
        "seam_counts": base["seam_counts"],
        "summary": base["summary"],
        "coverage_notes": base.get("coverage_notes", []),
        "work_summary": {
            "total_story_points": total_pts,
            "by_type": {
                t: {
                    "count": base["seam_counts"].get(t, 0),
                    "story_points": pts_by_type.get(t, 0),
                }
                for t in ("boundary", "object", "link", "preprocessing", "message")
            },
            "effort_distribution": dict(effort_dist),
        },
        "seams": seams_with_work,
    }

    if run_id:
        from micro_cosmos.settings import get_settings
        out = Path(get_settings().runs_dir) / run_id / "seam.json"
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        _log.info("seam report written to %s (%d seams, %d pts)", out, base["total"], total_pts)

    return report


# ── Seam processing status (runtime TDD-loop tracking, written in place ──────
# into seam.json — the same "tree" the Seams UI tab already renders from,
# rather than a separate artifact) ────────────────────────────────────────────

ProcessingStatus = Literal["pending", "success", "failed"]

_REVIEW_FILES = ("skeptical_review.json", "test_review.json", "functional_review.json")


def _seam_processing_defaults() -> dict:
    return {
        "status": "pending",
        "attempts": 0,
        "retry_attempts": 0,
        "failure_reason": None,
        "updated_at": None,
    }


def _recompute_processing_summary(report: dict) -> None:
    counts = {"pending": 0, "success": 0, "failed": 0}
    seams = report.get("seams", [])
    for seam in seams:
        status = seam.get("processing", {}).get("status", "pending")
        counts[status] = counts.get(status, 0) + 1
    report["processing_summary"] = {"total": len(seams), **counts}


def _seam_json_path(run_dir: Path) -> Path:
    return Path(run_dir) / "seam.json"


def init_seam_processing(run_dir: Path, *, force: bool = False) -> dict | None:
    """Pre-seed every seam entry in seam.json with a `processing` sub-object
    (status="pending") and a run-level `processing_summary`.

    Idempotent: a no-op if every seam already carries a `processing` key,
    unless force=True — used to reset the whole tree back to pending ahead
    of a full seam re-run (e.g. a Gate 5 rejection), so the status table
    only ever reflects the current pass, not an accumulation across it.

    Returns the updated report dict, or None if seam.json doesn't exist yet.
    """
    path = _seam_json_path(run_dir)
    if not path.exists():
        return None
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        _log.exception("Failed to read seam.json at %s", path)
        return None

    seams = report.get("seams", [])
    if not force and seams and all("processing" in s for s in seams):
        return report

    for seam in seams:
        seam["processing"] = _seam_processing_defaults()
    _recompute_processing_summary(report)

    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    _log.info(
        "seam processing %s for %d seam(s) in %s",
        "reset" if force else "initialised", len(seams), path,
    )
    return report


def update_seam_processing(
    run_dir: Path,
    seam_id: str,
    *,
    status: ProcessingStatus,
    attempts: int | None = None,
    retry_attempts: int | None = None,
    failure_reason: str | None = None,
) -> dict | None:
    """Update one seam's `processing` sub-object in seam.json in place.

    Re-reads seam.json fresh from disk on every call (never passed a cached
    report), so repeated calls across the seam loop can't go stale.
    `status` and `failure_reason` are always written to the given value
    (pass failure_reason=None to clear it, e.g. on success). `attempts`/
    `retry_attempts` are only overwritten when explicitly passed (None
    means "leave unchanged") — e.g. the retry-pass call sets
    retry_attempts without touching the attempts count from the main pass.

    Best-effort, matching this module's existing I/O style: never raises —
    logs a warning and returns None if seam.json or seam_id isn't found.
    """
    path = _seam_json_path(run_dir)
    if not path.exists():
        _log.warning("update_seam_processing: seam.json not found at %s", path)
        return None
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        _log.exception("Failed to read seam.json at %s", path)
        return None

    seam = next((s for s in report.get("seams", []) if s.get("id") == seam_id), None)
    if seam is None:
        _log.warning("update_seam_processing: seam id %r not found in %s", seam_id, path)
        return None

    processing = seam.setdefault("processing", _seam_processing_defaults())
    processing["status"] = status
    if attempts is not None:
        processing["attempts"] = attempts
    if retry_attempts is not None:
        processing["retry_attempts"] = retry_attempts
    processing["failure_reason"] = failure_reason
    processing["updated_at"] = datetime.now(timezone.utc).isoformat()

    _recompute_processing_summary(report)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def summarize_seam_failure(run_dir: Path) -> str | None:
    """Read skeptical/test/functional review JSON files from run_dir and
    return a bullet-point, human-readable summary of every failing/blocking
    finding across the three reviews.

    This is the finding-collection logic shared with
    micro_cosmos/orchestration/driver.py's _build_feedback_prompt (which builds
    the in-loop "FIX THESE ISSUES" Code Writer prompt) — factored out here
    so both that prompt and the persisted `failure_reason` use one
    implementation.

    Returns None only when all three reviews are present and all passed.
    If none of the three review files exist at all (the reviewer phase(s)
    never ran or crashed — e.g. the generate_and_verify_seam fallback path
    in coder_tools.py produced nothing verifiable for Code Writer to hand
    off), returns a fallback string rather than None, so a real failure is
    never silently reported as a pass.
    """
    run_dir = Path(run_dir)

    def _load(fname: str) -> dict:
        p = run_dir / fname
        if not p.exists():
            return {}
        try:
            v = json.loads(p.read_text(encoding="utf-8"))
            # ADK sometimes double-encodes: the file contains a JSON string
            # whose value is itself a JSON object string.
            if isinstance(v, str):
                v = json.loads(v)
            return v if isinstance(v, dict) else {}
        except Exception:
            return {}

    skeptical = _load("skeptical_review.json")
    test_rev = _load("test_review.json")
    functional = _load("functional_review.json")

    if not skeptical and not test_rev and not functional:
        return (
            "Code Writer produced no verifiable output and review phase(s) "
            "did not run — see trace for details."
        )

    findings: list[str] = []
    any_failed = False

    if not skeptical.get("passed", True):
        any_failed = True
    for f in skeptical.get("findings", []):
        sev = f.get("severity", "MINOR").upper()
        loc = f.get("file", "<unknown>")
        if f.get("symbol"):
            loc += f":{f['symbol']}"
        findings.append(f"[SKEPTICAL/{sev}] {loc} — {f.get('issue', '')}")

    if not test_rev.get("passed", True):
        any_failed = True
    for f in test_rev.get("findings", []):
        sev = f.get("severity", "MINOR").upper()
        loc = f.get("test_file", "<unknown>")
        if f.get("test_name"):
            loc += f":{f['test_name']}"
        findings.append(f"[TEST/{sev}] {loc} — {f.get('issue', '')}")
    if test_rev and not test_rev.get("passed", True):
        if not test_rev.get("has_happy_path"):
            findings.append("[TEST/BLOCKER] test suite — add a happy-path test (valid input → expected success)")
        if not test_rev.get("has_rule_violation"):
            findings.append("[TEST/BLOCKER] test suite — add a rule-violation test (invalid input → expected error/exception)")
        if not test_rev.get("has_edge_case"):
            findings.append("[TEST/BLOCKER] test suite — add an edge-case test (boundary: zero, empty, or max value)")

    if not functional.get("passed", True):
        any_failed = True
    for f in functional.get("findings", []):
        sev = f.get("severity", "MINOR").upper()
        findings.append(f"[FUNCTIONAL/{sev}] {f.get('source_behavior', '<unknown>')} — {f.get('issue', '')}")

    if not any_failed:
        return None

    return "\n".join(f"• {fn}" for fn in findings)


# ── Work-stream grouping (work_streams.json) ─────────────────────────────────

_ETL_STREAM_CATALOGUE: list[dict[str, Any]] = [
    {
        "id": "ws_etl_raw",
        "seq": 1,
        "name": "Raw warehouse sources",
        "rationale": (
            "Land the BigQuery raw views first. Staging and marts read them, so the "
            "destination raw relations have to exist before any downstream model is built."
        ),
        "depends_on": [],
        "migration_phase": "extraction",
    },
    {
        "id": "ws_etl_staging",
        "seq": 2,
        "name": "Staging tables",
        "rationale": (
            "Cleansed staging tables sit on the raw sources. Translate their filters, "
            "casts, and null handling into the destination dialect before the marts."
        ),
        "depends_on": ["ws_etl_raw"],
        "migration_phase": "extraction",
    },
    {
        "id": "ws_etl_marts",
        "seq": 3,
        "name": "Mart tables",
        "rationale": (
            "Mart tables aggregate the staging layer. They are the published warehouse "
            "surface and run only after staging is in place."
        ),
        "depends_on": ["ws_etl_staging"],
        "migration_phase": "extraction",
    },
    {
        "id": "ws_etl_dependencies",
        "seq": 2,
        "name": "Model dependencies",
        "rationale": (
            "Each Dataform ref is a schedule edge. The destination job or dbt graph "
            "must keep the same upstream before downstream order."
        ),
        "depends_on": ["ws_etl_raw"],
        "migration_phase": "isolation",
    },
]


_JOB_STREAM_CATALOGUE: list[dict[str, Any]] = [
    {
        "id": "ws_etl_activities",
        "seq": 1,
        "name": "Scheduler activities",
        "rationale": (
            "Each ADF or job activity is a migration unit. It runs one notebook "
            "and must exist in the destination before its downstream activities."
        ),
        "depends_on": [],
        "migration_phase": "extraction",
    },
    {
        "id": "ws_etl_dependencies",
        "seq": 2,
        "name": "Activity dependencies",
        "rationale": (
            "dependsOn edges are the pipeline order. The destination job keeps "
            "the same upstream-before-downstream sequence."
        ),
        "depends_on": ["ws_etl_activities"],
        "migration_phase": "isolation",
    },
]


_STREAM_CATALOGUE: list[dict[str, Any]] = [
    {
        "id": "ws_01_config",
        "seq": 1,
        "name": "Configuration & Environment",
        "rationale": (
            "Extract all configuration, feature-flag, and environment-variable reads into "
            "typed Settings interfaces. This is the prerequisite for every other stream: "
            "once settings are injected rather than read directly, any downstream refactoring "
            "can supply test doubles without touching environment variables."
        ),
        "depends_on": [],
        "migration_phase": "extraction",
    },
    {
        "id": "ws_02_test_infra",
        "seq": 1,
        "name": "Test Infrastructure Boundaries",
        "rationale": (
            "Define explicit contracts at the boundaries between test helpers, e2e fixtures, "
            "and the modules they exercise. Isolating test utilities behind stable interfaces "
            "prevents test code from leaking into production modules and reduces the blast "
            "radius of test refactors. Independent of all other domain work."
        ),
        "depends_on": [],
        "migration_phase": "isolation",
    },
    {
        "id": "ws_03_messaging",
        "seq": 2,
        "name": "Messaging & Event Bus",
        "rationale": (
            "Wrap all event publishers, PubSub clients, and notification services behind "
            "port interfaces. Because every domain stream produces or consumes events, "
            "having stable messaging ports in place first lets domain teams write tests "
            "with fake event buses rather than real infrastructure."
        ),
        "depends_on": ["ws_01_config"],
        "migration_phase": "adaptation",
    },
    {
        "id": "ws_04_ext_integrations",
        "seq": 2,
        "name": "External Client Adapters",
        "rationale": (
            "Isolate all third-party integrations (HR/payroll systems, "
            "communications/alerting tools, GraphQL, storage) behind port/adapter "
            "interfaces and define explicit contracts at the external-api/ and "
            "comms-api/ directory boundaries. Owned by an integrations team; no "
            "dependency on any domain feature stream."
        ),
        "depends_on": ["ws_01_config"],
        "migration_phase": "adaptation",
    },
    {
        "id": "ws_05_api_boundary",
        "seq": 2,
        "name": "API Module Contracts",
        "rationale": (
            "Define the explicit public surface of the api/ module by formalising "
            "the api/↔features/ contract (594 CALLS edges) and wrapping database "
            "error handling behind a port. This is the highest-traffic boundary in "
            "the codebase and the prerequisite for all domain-feature streams: once "
            "the API surface is explicit, domain teams can work behind it independently."
        ),
        "depends_on": ["ws_01_config"],
        "migration_phase": "isolation",
    },
    {
        "id": "ws_06_auth",
        "seq": 3,
        "name": "Authentication & Access Control",
        "rationale": (
            "Extract interfaces for authentication services, route guards, and access-control "
            "primitives. The Authentication and RouteGuard contexts account for the largest "
            "single slice of object seams (149 nodes). Work can be parallelised within the "
            "stream: high-fan-in services first, guards and DTOs in a follow-on pass."
        ),
        "depends_on": ["ws_01_config", "ws_05_api_boundary"],
        "migration_phase": "extraction",
    },
    {
        "id": "ws_07_admin",
        "seq": 3,
        "name": "Admin Feature Module",
        "rationale": (
            "Introduce interfaces for the admin client-management feature area (49 nodes). "
            "This is a self-contained feature module with no dependency on the project-"
            "management or people domains; it can be undertaken by the admin squad in "
            "parallel with other domain streams."
        ),
        "depends_on": ["ws_01_config", "ws_05_api_boundary"],
        "migration_phase": "extraction",
    },
    {
        "id": "ws_08_data_transfer",
        "seq": 3,
        "name": "Data Transfer & Shared DTOs",
        "rationale": (
            "Formalise the data-transfer layer: extract interfaces for the FeaturesData* "
            "and Decorator contexts (43 nodes) that carry shared data structures across "
            "domain boundaries. Stable DTO interfaces reduce merge conflicts when multiple "
            "domain teams modify overlapping data shapes."
        ),
        "depends_on": ["ws_01_config", "ws_05_api_boundary"],
        "migration_phase": "extraction",
    },
    {
        "id": "ws_09_project_mgmt",
        "seq": 3,
        "name": "Project Management Domain",
        "rationale": (
            "Introduce interfaces for project-management and allocation services (36 nodes "
            "across FeaturesProjectsProjectManagement, ProjectManagement, and "
            "FeaturesAllocationsResourceAllocation contexts). Self-contained domain with "
            "no coupling to admin or people feature streams."
        ),
        "depends_on": ["ws_01_config", "ws_05_api_boundary"],
        "migration_phase": "extraction",
    },
    {
        "id": "ws_10_frontend",
        "seq": 3,
        "name": "Frontend Hooks & UI Components",
        "rationale": (
            "Extract interfaces for React hooks, page-level components, and people-feature "
            "hooks (ReactHook, FeaturesPeopleReactHook, PagesAdmin contexts). Also covers "
            "UI-layer link seams (components/↔pages/, hooks/↔pages/, etc.). Owned by the "
            "frontend team and parallelisable with all other seq-3 streams."
        ),
        "depends_on": ["ws_01_config"],
        "migration_phase": "extraction",
    },
    {
        "id": "ws_11_features_contracts",
        "seq": 4,
        "name": "Features Module Internal Contracts",
        "rationale": (
            "Define stable sub-module contracts within the features/ directory tree — "
            "the busiest internal boundary (features/↔utils/ alone has 212 CALLS edges). "
            "This stream is intentionally last: the earlier domain streams will have "
            "already clarified which parts of features/ are stable APIs vs. implementation "
            "details, making the contract boundaries easier to draw correctly."
        ),
        "depends_on": [
            "ws_06_auth", "ws_07_admin", "ws_08_data_transfer",
            "ws_09_project_mgmt", "ws_10_frontend",
        ],
        "migration_phase": "isolation",
    },
]


# Exact mapping from BCM context name → work stream ID.
# Any context not in this table, or any seam whose node_id is not in BCM,
# falls to ws_11_features_contracts.
_CTX_TO_STREAM: dict[str, str] = {
    "Configuration":        "ws_01_config",
    "TestUnit":             "ws_02_test_infra",
    "TestE2E":              "ws_02_test_infra",
    "Messaging":            "ws_03_messaging",
    "ExternalIntegrations": "ws_04_ext_integrations",
    "BackendCore":          "ws_05_api_boundary",
    "Authentication":       "ws_06_auth",
    "Admin":                "ws_07_admin",
    "DataTransfer":         "ws_08_data_transfer",
    "ProjectManagement":    "ws_09_project_mgmt",
    "People":               "ws_09_project_mgmt",
    "Frontend":             "ws_10_frontend",
    "Shared":               "ws_11_features_contracts",
}


def _dataform_stream_id(seam: dict) -> str:
    if _is_dataform_ref_seam(seam):
        return "ws_etl_dependencies"
    schema = _evidence_value(seam, "schema:").lower()
    if schema in ("raw", "staging", "marts"):
        return f"ws_etl_{schema}"
    return "ws_etl_staging"


def _job_stream_id(seam: dict) -> str:
    if _is_scheduler_dep_seam(seam):
        return "ws_etl_dependencies"
    return "ws_etl_activities"


def _assign_stream_id(seam: dict, node_to_ctx: dict[str, str]) -> str:
    """Assign a seam to a work stream via BCM context routing.

    Routing algorithm:
    1. Extract the source node ID from the seam ID: seam_<type>_<node_id>
       → split on '_' with maxsplit=2, take parts[2].
    2. Look up node_id in node_to_ctx (keyed by real IR node IDs from BCM).
    3. Map the BCM context name to a stream ID via _CTX_TO_STREAM.
    4. If the node_id is not found in BCM (e.g. link seams with directory
       boundary IDs), assign to ws_11_features_contracts.
    """
    if _is_dataform_model_seam(seam) or _is_dataform_ref_seam(seam):
        return _dataform_stream_id(seam)
    if _is_scheduler_activity_seam(seam) or _is_scheduler_dep_seam(seam):
        return _job_stream_id(seam)
    location = (seam.get("source_location") or "").replace("\\", "/")
    if any(part in location for part in ("/etl_jobs/", "/notebooks/", "/data_quality/", "/data_profiling/")):
        return "ws_etl_activities"
    parts = seam.get("id", "").split("_", 2)
    node_id = parts[2] if len(parts) >= 3 else ""
    ctx = node_to_ctx.get(node_id, "")
    return _CTX_TO_STREAM.get(ctx, "ws_11_features_contracts")


def produce_work_streams(
    seam_report: dict,
    bcm: dict | None = None,
    run_id: str | None = None,
) -> dict:
    """Group seams from a seam report into independently-deliverable work streams.

    bcm is the bounded_context_map dict; when omitted context-based assignment
    falls back to the 'features contracts' stream.
    """
    node_to_ctx: dict[str, str] = {}
    if bcm:
        for ctx in bcm.get("contexts", []):
            for nid in ctx.get("node_ids", []):
                node_to_ctx[nid] = ctx["name"]

    # Assign every seam to a stream
    stream_seams: dict[str, list[dict]] = defaultdict(list)
    seams = seam_report.get("seams", [])
    dataform_estate = any(
        _is_dataform_model_seam(seam) or _is_dataform_ref_seam(seam) for seam in seams
    )
    job_estate = any(
        _is_scheduler_activity_seam(seam) or _is_scheduler_dep_seam(seam) for seam in seams
    )
    for seam in seams:
        sid = _assign_stream_id(seam, node_to_ctx)
        stream_seams[sid].append(seam)

    # A Dataform or scheduler estate does not use the application catalogue
    # (auth, React, admin). Effort sits on the warehouse layers or the job
    # activities.
    work_streams: list[dict[str, Any]] = []
    if dataform_estate:
        catalogue = _ETL_STREAM_CATALOGUE
    elif job_estate:
        catalogue = _JOB_STREAM_CATALOGUE
    else:
        catalogue = _STREAM_CATALOGUE
    for meta in catalogue:
        sid = meta["id"]
        seams = stream_seams.get(sid, [])
        pts = sum(s["work"]["story_points"] for s in seams)
        by_type = {
            t: sum(1 for s in seams if s["type"] == t)
            for t in ("boundary", "object", "link", "preprocessing", "message")
        }
        by_type_filtered = {k: v for k, v in by_type.items() if v}
        max_risk = (
            "high" if any(s["work"]["risk"] == "high" for s in seams) else
            "medium" if any(s["work"]["risk"] == "medium" for s in seams) else
            "low"
        )
        efforts = [s["work"]["effort"] for s in seams]
        dominant_effort = max(set(efforts), key=efforts.count) if efforts else "—"
        work_streams.append({
            **meta,
            "seam_count": len(seams),
            "story_points": pts,
            "seam_types_present": by_type_filtered,
            "dominant_effort": dominant_effort,
            "risk": max_risk,
            "seam_ids": [s["id"] for s in seams],
        })

    total_pts = sum(w["story_points"] for w in work_streams)
    total_seams = seam_report.get("total_seams", seam_report.get("total", 0))
    result = {
        "schema_version": "1.0",
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_seams": total_seams,
        "total_story_points": total_pts,
        "stream_count": len([w for w in work_streams if w["seam_count"] > 0]),
        "work_streams": work_streams,
    }

    if run_id:
        from micro_cosmos.settings import get_settings
        out = Path(get_settings().runs_dir) / run_id / "work_streams.json"
        out.write_text(json.dumps(result, indent=2), encoding="utf-8")
        _log.info(
            "work_streams written to %s (%d streams, %d pts)",
            out, result["stream_count"], total_pts,
        )

    return result


_ANCHOR_RE = re.compile(r'^.*(?:src|app|lib|functions|packages|services)/')


def _top_dir(source_location: str) -> str:
    """Return the first meaningful directory segment after stripping repo/anchor prefix.

    Strips everything up to and including the last anchor directory (src/, app/,
    lib/, etc.) then returns the first remaining path segment, matching the
    approach used by the cluster preprocessor. Falls back to the last two
    non-root parts of the absolute path if no anchor is found.
    """
    path = source_location.split(":")[0] if ":" in source_location else source_location
    stripped = _ANCHOR_RE.sub("", path)
    if stripped == path:
        # No anchor — use the second-to-last directory (skip filename)
        parts = [p for p in Path(path).parts if p not in (".", "/")]
        return parts[-2] if len(parts) >= 2 else (parts[0] if parts else "")
    parts = [p for p in Path(stripped).parts[:-1] if p]
    return parts[0] if parts else ""
