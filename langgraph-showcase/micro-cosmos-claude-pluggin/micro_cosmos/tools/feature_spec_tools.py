"""Feature Specifier tools — read seam analysis artifacts and write feature_specs.json."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


# ─── helpers ──────────────────────────────────────────────────────────────────

def _read_json(path: Path) -> dict | list | None:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


# ─── read_seam_data ───────────────────────────────────────────────────────────

def read_seam_data(run_dir: str, seam_ids: list[str] | None = None) -> dict:
    """Read seam.json, work_streams.json, tnas.json, and bounded_context_map.json.

    Returns a merged summary dict the agent uses to compose feature specs.
    Seam content is truncated to key fields only — the agent does not need
    full source evidence arrays to generate feature specs.

    seam_ids, when given, restricts the returned "seams" list to just those
    IDs — used by driver.py's per-batch Feature Specifier loop so a single
    LLM call only has to ingest (and then produce specs for) a small slice
    of a large estate instead of every seam at once. Optional, defaulting
    to None — omitting it (or passing an empty list) means "no filter,
    return everything," matching every existing caller's behaviour
    unchanged. A non-empty list with IDs that don't match anything
    correctly returns zero seams rather than silently falling back to
    "everything" — that's a real, honest signal the caller asked for the
    wrong IDs, not something to paper over.
    """
    root = Path(run_dir)

    # ── seams ──────────────────────────────────────────────────────────────
    _seam_file = _read_json(root / "seam.json") or []
    seams_raw: list = _seam_file.get("seams", []) if isinstance(_seam_file, dict) else _seam_file
    wanted = set(seam_ids) if seam_ids else None
    seams: list[dict] = []
    for s in seams_raw:
        if wanted is not None and s.get("id") not in wanted:
            continue
        work = s.get("work", {})
        seams.append({
            "id":                s.get("id", ""),
            "type":              s.get("type", ""),
            "location":          s.get("location", ""),
            "source_location":   s.get("source_location", ""),
            "substitution_note": s.get("substitution_note", ""),
            "side_a":            s.get("side_a", ""),
            "side_b":            s.get("side_b", ""),
            "work": {
                "title":          work.get("title", ""),
                "effort":         work.get("effort", ""),
                "story_points":   work.get("story_points", 0),
                "risk":           work.get("risk", ""),
                "migration_phase": work.get("migration_phase", ""),
                "steps":          work.get("steps", []),
            },
        })

    # ── work streams ───────────────────────────────────────────────────────
    ws_raw = _read_json(root / "work_streams.json") or {}
    work_streams: list[dict] = []
    for ws in ws_raw.get("work_streams", []):
        work_streams.append({
            "id":             ws.get("id", ""),
            "seq":            ws.get("seq", 0),
            "name":           ws.get("name", ""),
            "rationale":      ws.get("rationale", ""),
            "depends_on":     ws.get("depends_on", []),
            "migration_phase": ws.get("migration_phase", ""),
            "story_points":   ws.get("story_points", 0),
            "seam_ids":       ws.get("seam_ids", []),
            "risk":           ws.get("risk", "LOW"),
        })

    # ── tnas summary ───────────────────────────────────────────────────────
    tnas_raw = _read_json(root / "tnas.json") or {}
    tnas_summary = {
        "target_lang": tnas_raw.get("target_lang", ""),
        "services":    tnas_raw.get("services", []),
        "summary":     tnas_raw.get("summary", ""),
    }

    # ── bounded context map (context names only — no full node lists) ──────
    bcm_raw = _read_json(root / "bounded_context_map.json") or {}
    contexts = [
        {"name": c.get("name", ""), "description": c.get("description", "")}
        for c in bcm_raw.get("contexts", [])
    ]

    # ── run meta ───────────────────────────────────────────────────────────
    meta = _read_json(root / "run_meta.json") or {}

    return {
        "run_dir":       run_dir,
        "source_path":   meta.get("source_path", ""),
        "source_lang":   meta.get("source_lang", ""),
        "target_lang":   meta.get("target_lang", tnas_summary["target_lang"]),
        "seams":         seams,
        "work_streams":  work_streams,
        "tnas":          tnas_summary,
        "contexts":      contexts,
    }


# ─── submit_feature_specs ─────────────────────────────────────────────────────

def _loads_json_text(value: str):
    """Parse a model-supplied JSON string, including one wrapped in a fence.

    Returns the original string when it is not JSON, so the caller can tell
    a real object from prose.
    """
    text = value.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    if not text or text[0] not in "[{":
        return value
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return value


def _coerce_specs(specs):
    """Turn the payload the model actually sends into a list of spec dicts.

    LiteLLM/Gemma often delivers ``specs`` as one JSON string, or as a list
    of JSON strings, instead of a parsed list of objects. Iterating that
    string and calling ``.keys()`` on each character is what raised
    ``'str' object has no attribute 'keys'`` and dropped the whole batch.
    """
    if isinstance(specs, str):
        parsed = _loads_json_text(specs)
        if isinstance(parsed, str):
            parsed = _loads_json_text(parsed)
        specs = parsed
    if isinstance(specs, dict):
        inner = specs.get("specs")
        specs = inner if isinstance(inner, (list, str)) else [specs]
        if isinstance(specs, str):
            specs = _loads_json_text(specs)
    if not isinstance(specs, list):
        return None
    out: list[dict] = []
    for item in specs:
        if isinstance(item, str):
            item = _loads_json_text(item)
        if not isinstance(item, dict):
            return None
        criteria = item.get("acceptance_criteria")
        if isinstance(criteria, str):
            parsed = _loads_json_text(criteria)
            item["acceptance_criteria"] = parsed if isinstance(parsed, list) else [criteria]
        points = item.get("story_points")
        if isinstance(points, str):
            text = points.strip()
            try:
                item["story_points"] = int(text)
            except ValueError:
                try:
                    item["story_points"] = int(float(text))
                except ValueError:
                    pass
        elif isinstance(points, float):
            item["story_points"] = int(points)
        out.append(item)
    return out


def submit_feature_specs(specs: list[dict], run_dir: str) -> dict:
    """Validate and persist feature_specs.json to run_dir root.

    Each spec must contain at minimum:
      seam_id, title, description, business_value,
      acceptance_criteria (list), technical_notes,
      migration_phase, story_points, effort, risk,
      work_stream_id, jira_issue_type.

    Merges with any specs already on disk (keyed by seam_id — this batch's
    entries win on overlap) rather than overwriting the whole file. Large
    estates go through driver.py's per-batch Feature Specifier loop, one
    call per slice of seams, so a later batch's call must not erase an
    earlier batch's already-valid work. A single-call, all-seams-at-once
    submission (deterministic mode, or a small estate processed in one
    batch) merges against an empty/absent prior file, which is a no-op —
    identical output to before this existed.

    Returns a summary dict confirming write success.
    """
    specs = _coerce_specs(specs)
    if specs is None:
        return {"ok": False, "error": "specs must be a list of objects"}
    if not specs:
        return {"ok": False, "error": "specs list is empty"}

    root = Path(run_dir)
    meta = _read_json(root / "run_meta.json") or {}
    ws_raw = _read_json(root / "work_streams.json") or {}

    # Build work_stream index for summary enrichment
    ws_index: dict[str, dict] = {}
    for ws in ws_raw.get("work_streams", []):
        ws_index[ws["id"]] = ws

    # Validate required fields and normalise — only this batch's incoming
    # specs; a prior batch's specs already on disk were validated when
    # THEY were submitted, no need to re-check them here.
    required = {
        "seam_id", "title", "description", "business_value",
        "acceptance_criteria", "technical_notes",
        "migration_phase", "story_points", "effort", "risk",
        "work_stream_id", "jira_issue_type",
    }
    errors: list[str] = []
    for i, spec in enumerate(specs):
        missing = required - set(spec.keys())
        if missing:
            errors.append(f"spec[{i}] ({spec.get('seam_id', '?')}) missing: {sorted(missing)}")
        if not isinstance(spec.get("acceptance_criteria"), list):
            errors.append(f"spec[{i}] acceptance_criteria must be a list")

    if errors:
        return {"ok": False, "errors": errors}

    # Merge this batch's (now-validated) specs on top of whatever prior
    # batches already wrote, keyed by seam_id so a re-submitted seam (e.g.
    # a Gate 4.5 rejection retry re-running every batch) correctly replaces
    # its own earlier entry instead of duplicating it.
    prior = _read_json(root / "feature_specs.json") or {}
    prior_specs: list[dict] = prior.get("specs", []) if isinstance(prior, dict) else []
    merged_by_id: dict[str, dict] = {s.get("seam_id"): s for s in prior_specs if s.get("seam_id")}
    for spec in specs:
        merged_by_id[spec["seam_id"]] = spec
    specs = list(merged_by_id.values())

    # Enrich each spec with work stream name
    for spec in specs:
        ws = ws_index.get(spec["work_stream_id"], {})
        spec.setdefault("work_stream_name", ws.get("name", spec["work_stream_id"]))
        spec.setdefault("dependencies", [])
        spec.setdefault("api_surface", None)
        spec.setdefault("jira_labels", _default_labels(spec, meta))
        spec.setdefault("translated_files", [])

    # Build summary
    total_sp = sum(s.get("story_points", 0) for s in specs)
    by_phase: dict[str, int] = {}
    by_effort: dict[str, int] = {}
    api_seams = 0
    for s in specs:
        ph = s.get("migration_phase", "UNKNOWN")
        by_phase[ph] = by_phase.get(ph, 0) + s.get("story_points", 0)
        ef = s.get("effort", "UNKNOWN")
        by_effort[ef] = by_effort.get(ef, 0) + 1
        if s.get("api_surface"):
            api_seams += 1

    # Build work stream summaries for the report
    ws_specs: list[dict] = []
    for ws in ws_raw.get("work_streams", []):
        ws_seam_specs = [s for s in specs if s.get("work_stream_id") == ws["id"]]
        ws_specs.append({
            "id":             ws["id"],
            "name":           ws.get("name", ""),
            "rationale":      ws.get("rationale", ""),
            "migration_phase": ws.get("migration_phase", ""),
            "story_points":   sum(s.get("story_points", 0) for s in ws_seam_specs),
            "seam_count":     len(ws_seam_specs),
            "jira_issue_type": "Epic",
            "jira_labels":    _default_ws_labels(ws, meta),
        })

    run_id = root.name
    output: dict = {
        "schema_version": "1.0",
        "run_id":         run_id,
        "generated_at":   datetime.now(timezone.utc).isoformat(),
        "source_path":    meta.get("source_path", ""),
        "target_lang":    meta.get("target_lang", ""),
        "work_streams":   ws_specs,
        "specs":          specs,
        "summary": {
            "total_seams":        len(specs),
            "total_story_points": total_sp,
            "by_phase":           by_phase,
            "by_effort":          by_effort,
            "api_seams":          api_seams,
        },
    }

    out_path = root / "feature_specs.json"
    out_path.write_text(json.dumps(output, indent=2))

    return {
        "ok":           True,
        "path":         str(out_path),
        "specs_written": len(specs),
        "total_story_points": total_sp,
        "summary":      output["summary"],
    }


# ─── export helpers (called from app.py, not ADK tools) ───────────────────────

def export_openapi(run_dir: str) -> str:
    """Generate OpenAPI 3.1 YAML from feature_specs.json. Returns YAML string."""
    import yaml  # type: ignore[import]  # PyYAML

    root = Path(run_dir)
    data = _read_json(root / "feature_specs.json")
    if not data:
        raise FileNotFoundError("feature_specs.json not found — run FEATURE_SPECIFIER phase first")

    source_path = data.get("source_path", "unknown")
    project_name = Path(source_path).name if source_path else "project"
    target_lang = data.get("target_lang", "")

    # Collect API-bearing specs
    api_specs = [s for s in data.get("specs", []) if s.get("api_surface")]

    paths: dict = {}
    for spec in api_specs:
        surf = spec["api_surface"]
        for ep in surf.get("endpoints", []):
            method  = ep.get("method", "GET").lower()
            path    = ep.get("path", "/")
            summary = ep.get("summary", spec["title"])
            tag     = _slug(spec.get("work_stream_name", "general"))

            if path not in paths:
                paths[path] = {}
            paths[path][method] = {
                "summary":     summary,
                "description": spec.get("description", ""),
                "operationId": _camel_id(spec["seam_id"], method),
                "tags":        [tag],
                "responses": {
                    "200": {"description": "Success"},
                    "400": {"description": "Invalid request"},
                    "500": {"description": "Internal error"},
                },
            }

    doc = {
        "openapi": "3.1.0",
        "info": {
            "title":       f"{project_name} — Feature Specifications",
            "version":     "1.0.0",
            "description": (
                f"Generated by Micro-Cosmos from seam analysis of {source_path}. "
                f"Target language: {target_lang}."
            ),
        },
        "paths": paths or {},
    }

    # Add non-API seams as schema components
    schemas: dict = {}
    for spec in data.get("specs", []):
        schema_name = _pascal_id(spec["seam_id"])
        schemas[schema_name] = {
            "type":        "object",
            "description": spec.get("description", ""),
            "properties":  {},
        }

    if schemas:
        doc["components"] = {"schemas": schemas}

    return yaml.dump(doc, sort_keys=False, allow_unicode=True, default_flow_style=False)


def export_jira(run_dir: str, project_key: str = "ALX") -> dict:
    """Generate Jira bulk-import JSON from feature_specs.json.

    Compatible with POST /rest/api/3/issue/bulk (Jira Server 8+ and Cloud).
    Work streams → Epics. Seams → Stories linked to their work stream Epic.
    """
    root = Path(run_dir)
    data = _read_json(root / "feature_specs.json")
    if not data:
        raise FileNotFoundError("feature_specs.json not found — run FEATURE_SPECIFIER phase first")

    issue_updates: list[dict] = []

    # Map work_stream_id → Epic summary for story linking
    epic_summary: dict[str, str] = {}

    # 1. Create Epics for each work stream
    for ws in data.get("work_streams", []):
        summary = f"[{ws['migration_phase']}] {ws['name']}"
        epic_summary[ws["id"]] = summary
        issue_updates.append({
            "fields": {
                "project":       {"key": project_key},
                "issuetype":     {"name": "Epic"},
                "summary":       summary,
                "description":   _jira_doc(ws.get("rationale", "")),
                "labels":        ws.get("jira_labels", ["migration"]),
                "customfield_10016": ws.get("story_points", 0),  # story points
            }
        })

    # 2. Create Stories for each seam
    for spec in data.get("specs", []):
        ws_id   = spec.get("work_stream_id", "")
        phase   = spec.get("migration_phase", "")
        risk    = spec.get("risk", "MEDIUM")
        summary = f"[{phase}] {spec['title']}"

        criteria_text = "\n".join(
            f"• {c}" for c in spec.get("acceptance_criteria", [])
        )
        body = (
            f"{spec.get('description', '')}\n\n"
            f"**Business Value:**\n{spec.get('business_value', '')}\n\n"
            f"**Acceptance Criteria:**\n{criteria_text}\n\n"
            f"**Technical Notes:**\n{spec.get('technical_notes', '')}"
        )

        fields: dict = {
            "project":       {"key": project_key},
            "issuetype":     {"name": spec.get("jira_issue_type", "Story")},
            "summary":       summary,
            "description":   _jira_doc(body),
            "priority":      {"name": _risk_to_priority(risk)},
            "labels":        spec.get("jira_labels", ["migration"]),
            "customfield_10016": spec.get("story_points", 0),
        }

        # Link story to its epic (Jira Cloud uses customfield_10014 for epic link)
        parent_summary = epic_summary.get(ws_id)
        if parent_summary:
            fields["customfield_10014"] = parent_summary

        issue_updates.append({"fields": fields})

    return {"issueUpdates": issue_updates}


# ─── private helpers ──────────────────────────────────────────────────────────

def _default_labels(spec: dict, meta: dict) -> list[str]:
    labels = ["migration"]
    tl = meta.get("target_lang", "")
    if tl:
        labels.append(tl)
    ph = spec.get("migration_phase", "")
    if ph:
        labels.append(ph.lower().replace("_", "-"))
    return labels


def _default_ws_labels(ws: dict, meta: dict) -> list[str]:
    labels = ["migration"]
    tl = meta.get("target_lang", "")
    if tl:
        labels.append(tl)
    ph = ws.get("migration_phase", "")
    if ph:
        labels.append(ph.lower().replace("_", "-"))
    return labels


def _slug(name: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _camel_id(seam_id: str, method: str) -> str:
    import re
    parts = [p for p in re.split(r"[_\-\s]+", seam_id.lower()) if p and p not in ("seam", "context")]
    if parts:
        return method.lower() + "".join(p.capitalize() for p in parts)
    return method.lower() + seam_id.replace("_", "").capitalize()


def _pascal_id(seam_id: str) -> str:
    import re
    parts = [p for p in re.split(r"[_\-\s]+", seam_id) if p and p.lower() not in ("seam", "context")]
    return "".join(p.capitalize() for p in parts) or seam_id


def _risk_to_priority(risk: str) -> str:
    return {"HIGH": "High", "CRITICAL": "Highest", "LOW": "Low"}.get(risk.upper(), "Medium")


def _jira_doc(text: str) -> dict:
    """Wrap plain text in Atlassian Document Format (ADF) for Jira Cloud."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    content = []
    for para in paragraphs:
        content.append({
            "type": "paragraph",
            "content": [{"type": "text", "text": para}],
        })
    if not content:
        content = [{"type": "paragraph", "content": [{"type": "text", "text": ""}]}]
    return {"type": "doc", "version": 1, "content": content}
