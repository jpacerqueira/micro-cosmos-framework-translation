"""Artifact → Chunk converters.

One Chunk per logical unit (IR node, seam, bounded context, work stream,
fitness function, or report section).  Each chunk carries a stable id used
for citations and enough plain-English text to be both embedded and read by
a stakeholder.

Node chunks are enriched with structural context derived from the edges (callers,
callees, member count) so even symbolically-parsed nodes that lack a summary are
meaningfully retrievable.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path


@dataclass
class Chunk:
    id: str                          # stable: "node:prog.Foo", "seam:seam_object_…", etc.
    kind: str                        # "node" | "seam" | "context" | "stream" | "fitness" | "report"
    text: str                        # embeddable + human-readable
    source_location: str = ""        # path:line or "report:<file>#<heading>"
    meta: dict = field(default_factory=dict)  # name, node_type, etc. — for citation display


# ── IR graph ──────────────────────────────────────────────────────────────────

def _build_structural_context(node_id: str, edges: list[dict]) -> tuple[list[str], list[str]]:
    """Return (callers, callees) display names from the edge list."""
    callers, callees = [], []
    for e in edges:
        etype = e.get("type", "")
        if e.get("target_id") == node_id and etype == "CALLS":
            callers.append(e["source_id"])
        elif e.get("source_id") == node_id and etype == "CALLS":
            callees.append(e["target_id"])
    return callers, callees


def _member_count(node_id: str, edges: list[dict]) -> int:
    """Count DEFINES edges where this node is the parent (i.e. member count)."""
    return sum(1 for e in edges if e.get("source_id") == node_id and e.get("type") == "DEFINES")


def chunks_from_ir_graph(ir_graph: dict) -> list[Chunk]:
    nodes = ir_graph.get("nodes", [])
    edges = ir_graph.get("edges", [])
    chunks: list[Chunk] = []

    for node in nodes:
        node_id = node.get("id", "")
        name = node.get("name", node_id)
        ntype = node.get("type", "")
        summary = (node.get("summary") or "").strip()
        source_loc = node.get("source_location", "")
        attributes = node.get("attributes") or {}
        inputs = node.get("inputs") or []
        output = (node.get("output") or "").strip()

        callers, callees = _build_structural_context(node_id, edges)
        members = _member_count(node_id, edges)

        parts = [f"Node: {name}", f"Type: {ntype}"]
        if source_loc:
            parts.append(f"File: {source_loc}")
        if summary:
            parts.append(f"Summary: {summary}")
        if inputs:
            sig = ", ".join(f"{p.get('name','?')}: {p.get('type','?')}" for p in inputs[:8])
            parts.append(f"Inputs: {sig}")
        if output:
            parts.append(f"Output: {output}")
        if attributes:
            attr_str = "; ".join(f"{k}={v}" for k, v in list(attributes.items())[:6])
            parts.append(f"Attributes: {attr_str}")
        if members:
            parts.append(f"Members: {members} (methods/fields defined inside)")
        if callers:
            parts.append(f"Called by ({len(callers)}): {', '.join(callers[:6])}")
        if callees:
            parts.append(f"Calls ({len(callees)}): {', '.join(callees[:6])}")

        chunks.append(
            Chunk(
                id=f"node:{node_id}",
                kind="node",
                text="\n".join(parts),
                source_location=source_loc,
                meta={
                    "name": name,
                    "node_type": ntype,
                    "fan_in": len(callers),
                    "fan_out": len(callees),
                    "members": members,
                },
            )
        )
    return chunks


# ── Seam report ───────────────────────────────────────────────────────────────

def chunks_from_seam(seam_data: dict) -> list[Chunk]:
    chunks: list[Chunk] = []
    for seam in seam_data.get("seams", []):
        seam_id = seam.get("id", "")
        stype = seam.get("type", "")
        location = seam.get("location", "")
        source_loc = seam.get("source_location", "")
        evidence = seam.get("evidence") or []
        note = (seam.get("substitution_note") or "").strip()
        work = seam.get("work") or {}

        parts = [
            f"Seam: {stype} at {location}",
            f"Evidence: {'; '.join(evidence)}" if evidence else "",
        ]
        if work:
            title = work.get("title", "")
            effort = work.get("effort", "")
            sp = work.get("story_points", "")
            risk = work.get("risk", "")
            phase = work.get("migration_phase", "")
            parts.append(f"Work: {title} (effort: {effort}, {sp} story points, risk: {risk})")
            if phase:
                parts.append(f"Migration phase: {phase}")
            steps = work.get("steps") or []
            if steps:
                parts.append("Steps:\n" + "\n".join(f"  {i+1}. {s}" for i, s in enumerate(steps)))
        if note:
            parts.append(f"Recommendation: {note}")

        chunks.append(
            Chunk(
                id=f"seam:{seam_id}",
                kind="seam",
                text="\n".join(p for p in parts if p),
                source_location=source_loc,
                meta={
                    "seam_type": stype,
                    "location": location,
                    "story_points": work.get("story_points"),
                    "effort": work.get("effort"),
                    "risk": work.get("risk"),
                },
            )
        )
    return chunks


# ── Bounded context map ───────────────────────────────────────────────────────

def chunks_from_bounded_context_map(bcm: dict) -> list[Chunk]:
    """Handle both the canonical schema (contexts[].name) and the run-67f0550e
    variant (bounded_contexts[].contexts[])."""
    chunks: list[Chunk] = []

    # Canonical shape: {"contexts": [{name, member_node_ids, confidence, …}, …]}
    contexts = bcm.get("contexts") or []
    for ctx in contexts:
        name = ctx.get("name", "unnamed")
        member_ids = ctx.get("member_node_ids") or ctx.get("node_ids") or []
        confidence = ctx.get("confidence", "")
        rationale = (ctx.get("rationale") or "").strip()
        leaky = ctx.get("leaky_abstractions") or []
        cross = ctx.get("cross_context_calls") or []

        parts = [
            f"Bounded context: {name}",
            f"Confidence: {confidence}",
            f"Member nodes: {len(member_ids)}",
        ]
        if rationale:
            parts.append(f"Rationale: {rationale}")
        if leaky:
            parts.append(f"Leaky abstractions: {', '.join(leaky[:6])}")
        if cross:
            calls_str = "; ".join(
                f"{c.get('src_ctx','?')} → {c.get('tgt_ctx','?')}" for c in cross[:6]
            )
            parts.append(f"Cross-context calls: {calls_str}")

        chunks.append(
            Chunk(
                id=f"context:{name}",
                kind="context",
                text="\n".join(parts),
                source_location="",
                meta={"name": name, "confidence": confidence, "member_count": len(member_ids)},
            )
        )

    # Alt shape from run 67f0550e: {"bounded_contexts": [{contexts: [name], node_ids, …}]}
    alt_contexts = bcm.get("bounded_contexts") or []
    for entry in alt_contexts:
        names = entry.get("contexts") or []
        name = names[0] if names else "unnamed"
        member_ids = entry.get("node_ids") or []
        confidence = entry.get("confidence", "")
        cross = entry.get("cross_context_calls") or []

        parts = [
            f"Bounded context: {name}",
            f"Confidence: {confidence}",
            f"Member nodes: {len(member_ids)}",
        ]
        if cross:
            calls_str = "; ".join(
                f"{c.get('src_ctx','?')} → {c.get('tgt_ctx','?')}" for c in cross[:6]
            )
            parts.append(f"Cross-context calls: {calls_str}")

        chunks.append(
            Chunk(
                id=f"context:{name}",
                kind="context",
                text="\n".join(parts),
                source_location="",
                meta={"name": name, "confidence": confidence, "member_count": len(member_ids)},
            )
        )

    return chunks


# ── Work streams ──────────────────────────────────────────────────────────────

def chunks_from_work_streams(ws: dict) -> list[Chunk]:
    chunks: list[Chunk] = []
    for stream in ws.get("work_streams", []):
        ws_id = stream.get("id", "")
        name = stream.get("name", "")
        rationale = (stream.get("rationale") or "").strip()
        depends_on = stream.get("depends_on") or []
        phase = stream.get("migration_phase", "")
        sp = stream.get("story_points", 0)
        risk = stream.get("risk", "")
        seam_ids = stream.get("seam_ids") or []

        parts = [f"Work stream: {name}"]
        if phase:
            parts.append(f"Migration phase: {phase}")
        if sp:
            parts.append(f"Story points: {sp}")
        if risk:
            parts.append(f"Risk: {risk}")
        if depends_on:
            parts.append(f"Depends on: {', '.join(depends_on)}")
        if seam_ids:
            parts.append(f"Seams: {', '.join(seam_ids)}")
        if rationale:
            parts.append(f"Rationale: {rationale}")

        chunks.append(
            Chunk(
                id=f"stream:{ws_id}",
                kind="stream",
                text="\n".join(parts),
                source_location="",
                meta={"name": name, "phase": phase, "story_points": sp, "risk": risk},
            )
        )
    return chunks


# ── TNAS / fitness suite ──────────────────────────────────────────────────────

def chunks_from_tnas(tnas: dict) -> list[Chunk]:
    chunks: list[Chunk] = []
    suite = tnas.get("fitness_suite") or {}
    # fitness_suite may be a list directly, or a dict with a "functions"/"rules"/"checks" key
    if isinstance(suite, list):
        fn_list = suite
    elif isinstance(suite, dict):
        fn_list = suite.get("functions") or suite.get("rules") or suite.get("checks") or []
    else:
        fn_list = []
    for fn in fn_list:
        if not isinstance(fn, dict):
            continue
        # LLM may use "function" or "name" for the human label
        fn_id = fn.get("id", "")
        name = fn.get("name") or fn.get("function") or fn_id
        description = (fn.get("description") or "").strip()
        rationale = (fn.get("rationale") or "").strip()
        spec = (fn.get("spec") or "").strip()
        severity = fn.get("severity", "")
        derived = fn.get("derived_from", "")

        parts = [
            f"Fitness function: {fn_id} — {name}",
            f"Severity: {severity}",
        ]
        if description:
            parts.append(f"Description: {description}")
        if rationale:
            parts.append(f"Rationale: {rationale}")
        if spec:
            parts.append(f"CI spec: {spec}")
        if derived:
            parts.append(f"Derived from: {derived}")

        chunks.append(
            Chunk(
                id=f"fitness:{fn_id}",
                kind="fitness",
                text="\n".join(parts),
                source_location="",
                meta={"name": name, "severity": severity},
            )
        )

    # Also emit a chunk for each per-context architecture decision
    for decision in tnas.get("context_decisions", []):
        ctx_name = decision.get("context_name", "")
        style = decision.get("architecture_style", "")
        rationale = (decision.get("rationale") or "").strip()
        risks = decision.get("risks") or []

        parts = [f"Architecture decision for context: {ctx_name}", f"Style: {style}"]
        if rationale:
            parts.append(f"Rationale: {rationale}")
        if risks:
            parts.append(f"Risks: {'; '.join(risks[:4])}")

        chunks.append(
            Chunk(
                id=f"decision:{ctx_name}",
                kind="fitness",
                text="\n".join(parts),
                source_location="",
                meta={"context": ctx_name, "style": style},
            )
        )

    return chunks


# ── Security report ───────────────────────────────────────────────────────────

def chunks_from_security_report(security_report: dict) -> list[Chunk]:
    """One chunk per security finding plus an overview chunk for risk summary."""
    chunks: list[Chunk] = []

    src_risk = security_report.get("source_architecture_risk", "")
    dst_risk = security_report.get("destination_architecture_risk", "")
    scope = (security_report.get("scope_summary") or "").strip()
    fixes = security_report.get("recommended_fixes") or []
    follow_ups = security_report.get("follow_up_checks") or []
    migration_notes = security_report.get("migration_security_notes") or []

    overview_parts = ["Security analysis overview"]
    if scope:
        overview_parts.append(f"Scope: {scope}")
    if src_risk:
        overview_parts.append(f"Source architecture risk: {src_risk}")
    if dst_risk:
        overview_parts.append(f"Destination architecture risk: {dst_risk}")
    if fixes:
        overview_parts.append("Recommended fixes: " + " | ".join(str(f) for f in fixes[:6]))
    if follow_ups:
        overview_parts.append("Follow-up checks: " + " | ".join(str(f) for f in follow_ups[:5]))
    if migration_notes:
        overview_parts.append(
            "Migration security notes: " + " | ".join(str(n) for n in migration_notes[:6])
        )

    chunks.append(
        Chunk(
            id="security:overview",
            kind="security",
            text="\n".join(overview_parts),
            source_location="security_report.json",
            meta={"source_risk": src_risk, "destination_risk": dst_risk},
        )
    )

    for finding in (security_report.get("findings") or []):
        fid = finding.get("id", "")
        if not fid:
            continue
        title = finding.get("title", "")
        severity = finding.get("severity", "")
        category = finding.get("category", "")
        location = finding.get("location", "")
        description = (finding.get("description") or "").strip()
        remediation = (finding.get("remediation") or "").strip()
        cwe_id = finding.get("cwe_id", "")
        confirmed = finding.get("confirmed", False)
        affects_migration = finding.get("affects_migration", False)

        parts = [f"Security finding {fid}: {title}"]
        parts.append(
            f"Severity: {severity} | Category: {category} | Confirmed: {confirmed}"
            + (" | Affects migration: yes" if affects_migration else "")
        )
        if location:
            parts.append(f"Location: {location}")
        if cwe_id:
            parts.append(f"CWE: {cwe_id}")
        if description:
            parts.append(f"Description: {description}")
        if remediation:
            parts.append(f"Remediation: {remediation}")

        chunks.append(
            Chunk(
                id=f"security:{fid}",
                kind="security",
                text="\n".join(parts),
                source_location=location or "security_report.json",
                meta={
                    "finding_id": fid,
                    "severity": severity,
                    "category": category,
                    "confirmed": confirmed,
                },
            )
        )

    return chunks


# ── Trivy CVE report ─────────────────────────────────────────────────────────

def chunks_from_trivy_report(trivy_data: dict) -> list[Chunk]:
    """One chunk per Trivy CVE vulnerability plus an overview chunk for counts."""
    chunks: list[Chunk] = []

    summary = trivy_data.get("summary", {})
    total = summary.get("total", 0)
    scan_target = trivy_data.get("scan_target", "")

    if trivy_data.get("error"):
        return []

    overview_parts = ["Trivy dependency CVE scan overview"]
    if scan_target:
        overview_parts.append(f"Scan target: {scan_target}")
    overview_parts.append(f"Total CVEs: {total}")
    for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        if summary.get(sev):
            overview_parts.append(f"{sev}: {summary[sev]}")

    chunks.append(
        Chunk(
            id="trivy:overview",
            kind="security",
            text="\n".join(overview_parts),
            source_location="trivy_report.json",
            meta={"source_risk": "TRIVY", "total_cves": total},
        )
    )

    for vuln in (trivy_data.get("vulnerabilities") or []):
        vid = vuln.get("id", "")
        cve_id = vuln.get("cve_id", "")
        pkg = vuln.get("pkg_name", "")
        installed = vuln.get("installed_version", "")
        fixed = vuln.get("fixed_version", "")
        sev = vuln.get("severity", "")
        title = vuln.get("title", "")
        desc = (vuln.get("description") or "").strip()
        location = vuln.get("location", "")
        remediation = (vuln.get("remediation") or "").strip()
        url = vuln.get("primary_url", "")

        parts = [f"Trivy CVE {vid} ({cve_id}): {title}"]
        parts.append(f"Severity: {sev} | Package: {pkg} {installed}" + (f" → fix: {fixed}" if fixed else ""))
        if location:
            parts.append(f"Location: {location}")
        if desc:
            parts.append(f"Description: {desc[:400]}")
        if remediation:
            parts.append(f"Remediation: {remediation}")
        if url:
            parts.append(f"Reference: {url}")

        chunks.append(
            Chunk(
                id=f"trivy:{vid}",
                kind="security",
                text="\n".join(parts),
                source_location=location or "trivy_report.json",
                meta={
                    "finding_id": vid,
                    "cve_id": cve_id,
                    "severity": sev,
                    "category": "SUPPLY_CHAIN",
                    "confirmed": True,
                },
            )
        )

    return chunks


# ── Gate decisions ────────────────────────────────────────────────────────────

_GATE_LABELS: dict[str, str] = {
    "gate_1": "Observer Gate",
    "gate_2": "Cartographer Gate",
    "gate_3": "Architect Gate",
    "gate_4": "Security Gate",
}


def chunks_from_gate_state(gate_id: str, gate_data: dict) -> list[Chunk]:
    """One chunk capturing the gate's decision, reviewer notes, and constraints."""
    gate_name = _GATE_LABELS.get(gate_id, gate_id)
    decision = gate_data.get("decision", "")

    parts = [f"{gate_name} ({gate_id}) — Decision: {decision}"]

    for rej in (gate_data.get("rejections") or []):
        constraint = rej.get("constraint") or {}
        reason = constraint.get("reason", rej.get("reason", ""))
        reviewer = rej.get("reviewer_name", "")
        if reason:
            prefix = f"{reviewer}: " if reviewer else ""
            parts.append(f"Rejection constraint: {prefix}{reason}")

    for appr in (gate_data.get("approvals") or []):
        reviewer = appr.get("reviewer_name", "")
        notes = (appr.get("notes") or "").strip()
        if reviewer:
            parts.append(
                f"Approved by: {reviewer}" + (f" — Notes: {notes}" if notes else "")
            )

    count = gate_data.get("rejection_count", 0)
    if count:
        parts.append(f"Rejection count before approval: {count}")

    if len(parts) < 2:
        return []

    return [
        Chunk(
            id=f"gate:{gate_id}",
            kind="gate",
            text="\n".join(parts),
            source_location=f"{gate_id}.json",
            meta={"gate_id": gate_id, "decision": decision},
        )
    ]


# ── Markdown / HTML reports ───────────────────────────────────────────────────

_HEADING_RE = re.compile(r"^(#{1,4})\s+(.+)$", re.MULTILINE)

# Narrative HTML reports produced by the Architect phase that contain prose worth
# indexing.  ir-graph.html is intentionally excluded — it is a pure D3 visualisation
# with no searchable prose.  seam-report-*.html is client-side generated and excluded
# via the allowlist (no glob).
_NARRATIVE_HTML_REPORTS: tuple[str, ...] = (
    "executive-summary.html",
    "migration-briefing.html",
    "project-synthesis.html",
    "architecture-decisions.html",
    "dead-code.html",
    "hotspots.html",
    "sprint-plan.html",
    "fitness-stubs.html",
    "security-report.html",
)


class _HtmlToText(HTMLParser):
    """Strip HTML to plain text, converting h1-h6 to Markdown headings.

    Drops the full content of <script>, <style>, and <svg> subtrees so that
    D3/Cytoscape JS bundles and inline SVG diagrams never appear in chunks.
    """

    _SKIP_TAGS = {"script", "style", "svg"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth: int = 0

    def handle_starttag(self, tag: str, _attrs: list) -> None:  # type: ignore[override]
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if re.match(r"h[1-6]", tag):
            self._parts.append("\n## ")

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        if tag in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if re.match(r"h[1-6]", tag):
            self._parts.append("\n")
        elif tag in ("p", "li", "tr", "div", "section", "article"):
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        self._parts.append(data)

    def get_text(self) -> str:
        raw = "".join(self._parts)
        # Collapse runs of blank lines to a single blank line
        return re.sub(r"\n{3,}", "\n\n", raw).strip()


def _html_to_text(html_source: str) -> str:
    """Convert HTML to plain text with headings as '## heading' markers."""
    parser = _HtmlToText()
    parser.feed(html_source)
    return parser.get_text()


def _chunks_from_text(text: str, fname: str) -> list[Chunk]:
    """Shared helper: split plain text on '## heading' markers into Chunk objects.

    Used by both chunks_from_report (Markdown) and chunks_from_html_report (HTML
    after stripping).  Heading detection relies on _HEADING_RE so both sources
    produce the same chunk shape.
    """
    chunks: list[Chunk] = []
    matches = list(_HEADING_RE.finditer(text))

    _MIN_BODY = 40  # skip header-only stubs (e.g. HTML title sections with no prose)

    for i, m in enumerate(matches):
        heading = m.group(2).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if len(body) < _MIN_BODY:
            continue

        if len(body) > 2000:
            body = body[:2000] + "\n… (truncated)"

        slug = re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")
        chunks.append(
            Chunk(
                id=f"report:{fname}#{slug}",
                kind="report",
                text=f"## {heading}\n{body}",
                source_location=f"report:{fname}#{heading}",
                meta={"file": fname, "heading": heading},
            )
        )

    if matches:
        intro = text[: matches[0].start()].strip()
        if intro:
            chunks.insert(
                0,
                Chunk(
                    id=f"report:{fname}#intro",
                    kind="report",
                    text=intro[:2000],
                    source_location=f"report:{fname}#intro",
                    meta={"file": fname, "heading": "intro"},
                ),
            )
    elif text.strip():
        chunks.append(
            Chunk(
                id=f"report:{fname}#full",
                kind="report",
                text=text[:4000],
                source_location=f"report:{fname}",
                meta={"file": fname, "heading": "full"},
            )
        )

    return chunks


def chunks_from_report(report_path: Path) -> list[Chunk]:
    """Split a Markdown report on headings; one chunk per section."""
    try:
        text = report_path.read_text(encoding="utf-8")
    except OSError:
        return []
    return _chunks_from_text(text, report_path.name)


def chunks_from_html_report(report_path: Path) -> list[Chunk]:
    """Strip an HTML report to plain text and split on headings; one chunk per section.

    <script>, <style>, and <svg> subtrees are dropped before chunking so that
    inline JS bundles and SVG diagrams never appear in retrieved context.
    """
    try:
        raw = report_path.read_text(encoding="utf-8")
    except OSError:
        return []
    text = _html_to_text(raw)
    return _chunks_from_text(text, report_path.name)


# ── Master builder ────────────────────────────────────────────────────────────

def build_chunks(run_dir: Path) -> list[Chunk]:
    """Build all chunks for a run from its on-disk artifacts.

    Covers all four pipeline phases: Observer (ir_graph, seam, work_streams),
    Cartographer (bounded_context_map), Architect (tnas, HTML reports),
    Security (security_report), plus gate decisions from gate_*.json.
    """
    run_dir = Path(run_dir)
    chunks: list[Chunk] = []

    def _load(filename: str) -> dict:
        p = run_dir / filename
        if not p.exists():
            return {}
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}

    # Phase 1 — Observer
    ir_graph = _load("ir_graph.json")
    if ir_graph.get("nodes"):
        chunks.extend(chunks_from_ir_graph(ir_graph))

    seam_data = _load("seam.json")
    if seam_data.get("seams"):
        chunks.extend(chunks_from_seam(seam_data))

    # Phase 2 — Cartographer
    bcm = _load("bounded_context_map.json")
    if bcm:
        chunks.extend(chunks_from_bounded_context_map(bcm))

    ws = _load("work_streams.json")
    if ws.get("work_streams"):
        chunks.extend(chunks_from_work_streams(ws))

    # Phase 3 — Architect
    tnas = _load("tnas.json")
    if tnas:
        try:
            chunks.extend(chunks_from_tnas(tnas))
        except Exception:
            pass

    # Phase 4 — Security
    sec = _load("security_report.json")
    if sec.get("findings") is not None:
        chunks.extend(chunks_from_security_report(sec))

    # Trivy CVE scan (run before Security phase)
    trivy = _load("trivy_report.json")
    if trivy.get("vulnerabilities") is not None:
        chunks.extend(chunks_from_trivy_report(trivy))

    # Gate decisions (all four gates)
    for gate_id in ("gate_1", "gate_2", "gate_3", "gate_4"):
        gate_data = _load(f"{gate_id}.json")
        if gate_data:
            chunks.extend(chunks_from_gate_state(gate_id, gate_data))

    # Markdown reports in reports/
    reports_dir = run_dir / "reports"
    if reports_dir.is_dir():
        for md in sorted(reports_dir.glob("*.md")):
            if md.name != "CONVERSATION-SUMMARY.md":
                chunks.extend(chunks_from_report(md))

    # Narrative HTML reports — look first in reports/, fall back to run root for
    # backward compatibility with runs generated before the reports/ subdirectory.
    for html_name in _NARRATIVE_HTML_REPORTS:
        html_path = reports_dir / html_name
        if not html_path.exists():
            html_path = run_dir / html_name
        if html_path.exists():
            chunks.extend(chunks_from_html_report(html_path))

    return chunks
