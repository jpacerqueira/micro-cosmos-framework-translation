"""seam_enrichment.py — enriches seam.json with source context for downstream code generation.

Adds five fields to each seam record:
  source_snippet, caller_snippets, di_pattern, interface_shape, test_double_pattern

Adds one field to each work-stream record:
  context_files

Writes seam.enriched.json and work_streams.enriched.json alongside the originals.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


# ── File helpers ───────────────────────────────────────────────────────────────

def _strip_loc(source_location: str) -> str | None:
    """Strip ':N' line-number suffix — '/path/to/file.ts:1' → '/path/to/file.ts'."""
    if not source_location:
        return None
    path = source_location.rsplit(":", 1)[0]
    p = Path(path)
    return str(p) if p.suffix else None


def _read_lines(path: str | None, n: int) -> str | None:
    if not path:
        return None
    try:
        p = Path(path)
        if not p.is_file():
            return None
        content = p.read_text(encoding="utf-8", errors="replace")
        return "\n".join(content.splitlines()[:n])
    except OSError as exc:
        print(f"[enrich] cannot read {path}: {exc}", file=sys.stderr)
        return None


# ── DI pattern detection ───────────────────────────────────────────────────────

_DI_CHECKS = [
    ("nestjs_injectable", re.compile(
        r'@Injectable\(\)|@Module\s*\(\s*\{|from\s+["\']@nestjs/',
        re.MULTILINE,
    )),
    ("inversify", re.compile(
        r'@injectable\(\)|@inject\(|from\s+["\']inversify',
        re.MULTILINE,
    )),
    ("angular", re.compile(
        r'from\s+["\']@angular/|@Component\s*\(|@NgModule\s*\(',
        re.MULTILINE,
    )),
    ("manual", re.compile(
        r'this\.\w+\s*=\s*new\s+\w+|=\s*new\s+\w+\s*\(',
        re.MULTILINE,
    )),
]


def _detect_di(source_snippet: str | None, caller_snippets: list[dict]) -> str:
    if source_snippet is None:
        return "unknown"
    corpus = source_snippet + "\n" + "\n".join(
        cs.get("snippet") or "" for cs in caller_snippets
    )
    for name, pat in _DI_CHECKS:
        if pat.search(corpus):
            return name
    return "unknown"


# ── Interface shape extraction ─────────────────────────────────────────────────

_CLASS_RE    = re.compile(r'^\s*(export\s+)?(abstract\s+)?class\s+\w+')
_METHOD_RE   = re.compile(
    r'^\s*(?!private\b|protected\b|#|constructor\b|static\b)'
    r'(?:public\s+)?(?:async\s+)?(?:readonly\s+)?'
    r'(\w+)\s*[(<].*',
)
_PROP_RE     = re.compile(
    r'^\s*(?:public\s+|readonly\s+)(\w+)\s*[?!]?\s*:'
)
_EXPORT_FN_RE = re.compile(
    r'^\s*export\s+(?:async\s+)?function\s+\w+\s*\('
)
_PROPS_TYPE_RE = re.compile(
    r'^\s*(type|interface)\s+\w*[Pp]rops\b'
)


def _extract_interface_shape(
    source_snippet: str | None,
    seam_type: str,
    source_path: str | None,
) -> dict | None:
    if seam_type not in ("object", "boundary"):
        return None
    if not source_snippet:
        return None

    lines = source_snippet.splitlines()
    is_react = bool(source_path and (
        source_path.endswith(".tsx")
        or re.search(r'/use[A-Z]', source_path)
    ))

    # React: prefer props type
    if is_react:
        for line in lines:
            if _PROPS_TYPE_RE.match(line):
                return {"signatures": [line.strip()], "confidence": "high"}
        return {"signatures": [], "confidence": "low"}

    in_class = False
    confidence = "low"
    sigs: list[str] = []

    for line in lines:
        if _CLASS_RE.match(line):
            in_class = True
            confidence = "high"
            continue

        # Exported function (file exports functions rather than a class)
        if not in_class and _EXPORT_FN_RE.match(line):
            sig = re.split(r'\{', line)[0].strip().rstrip(';')
            if sig:
                sigs.append(sig)
            continue

        if not in_class:
            continue

        stripped = line.strip()
        if not stripped or stripped.startswith("//") or stripped.startswith("*"):
            continue

        # Property
        if _PROP_RE.match(line):
            sig = re.split(r'[=;{]', stripped)[0].strip().rstrip(';')
            if sig:
                sigs.append(sig)
            continue

        # Method
        if _METHOD_RE.match(line):
            sig = re.split(r'\{', stripped)[0].strip().rstrip(';')
            if sig and "(" in sig:
                sigs.append(sig)

    return {"signatures": sigs[:12], "confidence": confidence}


# ── Caller parsing ─────────────────────────────────────────────────────────────

_CALLERS_RE = re.compile(r'callers include[:\s]+(.+)', re.IGNORECASE)


def _parse_caller_ids(evidence: list[str]) -> list[str]:
    for ev in evidence:
        m = _CALLERS_RE.match(ev)
        if m:
            return [c.strip() for c in m.group(1).split(",") if c.strip()]
    return []


# ── Test-double pattern ────────────────────────────────────────────────────────

def _run_level_test_double(seams: list[dict]) -> str:
    """Derive once from preprocessing seam IDs — vitest > jest > playwright > unknown."""
    ids = {s.get("id", "") for s in seams}
    if any("vitest" in sid.lower() for sid in ids):
        return "vitest_mock"
    if any("jest" in sid.lower() for sid in ids):
        return "jest_mock"
    locs = {s.get("source_location", "") for s in seams}
    if any("/e2e/" in loc or "/fixtures/" in loc for loc in locs if loc):
        return "playwright_fixture"
    return "unknown"


def _seam_test_double(base: str, src_path: str | None, di: str) -> str:
    if src_path and ("/e2e/" in src_path or "/fixtures/" in src_path):
        return "playwright_fixture"
    if di == "manual":
        return "manual_stub"
    return base


# ── Context files for work streams ────────────────────────────────────────────

_CTX_RE = re.compile(
    r'(\.module\.ts|index\.tsx?|\.di\.ts|container\.ts|'
    r'inversify\.config\.ts|app\.module\.ts|bootstrap\.ts)$',
    re.IGNORECASE,
)


def _find_context_files(seam_source_paths: list[str]) -> list[str]:
    candidates: set[str] = set()
    for src in seam_source_paths:
        p = Path(src)
        if _CTX_RE.search(p.name) and p.is_file():
            candidates.add(str(p))
        if p.parent.is_dir():
            for sibling in p.parent.iterdir():
                if _CTX_RE.search(sibling.name) and sibling.is_file():
                    candidates.add(str(sibling))
    return sorted(candidates)[:4]


# ── Main enrichment pass ───────────────────────────────────────────────────────

def enrich_run(run_dir: str | Path) -> None:
    run_dir = Path(run_dir)

    seam_data  = json.loads((run_dir / "seam.json").read_text(encoding="utf-8"))
    ws_data    = json.loads((run_dir / "work_streams.json").read_text(encoding="utf-8"))
    ir_path    = run_dir / "ir_graph.json"
    ir         = json.loads(ir_path.read_text(encoding="utf-8")) if ir_path.exists() else {}

    # Node-id → source_location from IR (authoritative for caller resolution)
    node_loc: dict[str, str] = {}
    for n in ir.get("nodes", []):
        nid = n.get("id", "")
        loc = _strip_loc(n.get("source_location", "")) or ""
        if nid and loc:
            node_loc[nid] = loc

    seams = seam_data.get("seams", [])

    # Seam location → source_path for caller resolution fallback
    seam_src: dict[str, str] = {}
    for s in seams:
        loc = s.get("location", "")
        src = _strip_loc(s.get("source_location", "")) or ""
        if loc and src:
            seam_src[loc] = src

    base_test_double = _run_level_test_double(seams)

    errors: list[dict] = []
    stats: dict[str, Any] = {
        "source_snippet":        0,
        "caller_snippets":       0,
        "di_pattern":            {},
        "interface_shape_high":  0,
        "interface_shape_low":   0,
    }

    enriched_seams: list[dict] = []
    for seam in seams:
        try:
            enriched = dict(seam)

            # ── source_snippet ────────────────────────────────────────────────
            src_path = _strip_loc(seam.get("source_location", ""))
            snippet  = _read_lines(src_path, 60)
            enriched["source_snippet"] = snippet
            if snippet:
                stats["source_snippet"] += 1

            # ── caller_snippets ───────────────────────────────────────────────
            caller_ids      = _parse_caller_ids(seam.get("evidence", []))[:3]
            caller_snippets: list[dict] = []
            for cid in caller_ids:
                file_path = node_loc.get(cid) or seam_src.get(cid)
                if not file_path:
                    continue
                cs = _read_lines(file_path, 30)
                if cs is not None:
                    caller_snippets.append({
                        "caller_id":  cid,
                        "file_path":  file_path,
                        "snippet":    cs,
                    })
            enriched["caller_snippets"] = caller_snippets
            if caller_snippets:
                stats["caller_snippets"] += 1

            # ── di_pattern ────────────────────────────────────────────────────
            di = _detect_di(snippet, caller_snippets)
            enriched["di_pattern"] = di
            stats["di_pattern"][di] = stats["di_pattern"].get(di, 0) + 1

            # ── interface_shape ───────────────────────────────────────────────
            shape = _extract_interface_shape(snippet, seam.get("type", ""), src_path)
            enriched["interface_shape"] = shape
            if shape is None:
                pass
            elif shape["confidence"] == "high":
                stats["interface_shape_high"] += 1
            else:
                stats["interface_shape_low"] += 1

            # ── test_double_pattern ───────────────────────────────────────────
            enriched["test_double_pattern"] = _seam_test_double(base_test_double, src_path, di)

            enriched_seams.append(enriched)

        except Exception as exc:
            errors.append({"seam_id": seam.get("id"), "error": str(exc)})
            enriched_seams.append(seam)

    # ── Work-stream context_files ──────────────────────────────────────────────
    seam_map = {s["id"]: s for s in enriched_seams if "id" in s}
    context_files_count = 0
    enriched_streams: list[dict] = []

    for ws in ws_data.get("work_streams", []):
        enriched_ws = dict(ws)
        src_paths = [
            _strip_loc(seam_map[sid].get("source_location", ""))
            for sid in ws.get("seam_ids", [])
            if sid in seam_map
        ]
        src_paths = [p for p in src_paths if p]
        ctx = _find_context_files(src_paths)
        enriched_ws["context_files"] = ctx
        if ctx:
            context_files_count += 1
        enriched_streams.append(enriched_ws)

    # ── Write outputs ──────────────────────────────────────────────────────────
    seam_out = dict(seam_data)
    seam_out["seams"] = enriched_seams
    seam_out["enrichment_errors"] = errors

    ws_out = dict(ws_data)
    ws_out["work_streams"] = enriched_streams
    ws_out["enrichment_errors"] = errors

    (run_dir / "seam.enriched.json").write_text(
        json.dumps(seam_out, indent=2, default=str), encoding="utf-8"
    )
    (run_dir / "work_streams.enriched.json").write_text(
        json.dumps(ws_out, indent=2, default=str), encoding="utf-8"
    )

    # ── Summary ───────────────────────────────────────────────────────────────
    n_seams  = len(enriched_seams)
    n_shape  = stats["interface_shape_high"] + stats["interface_shape_low"]
    print(f"Enriched: {n_seams} seams")
    print(f"source_snippet populated: {stats['source_snippet']}")
    print(f"caller_snippets populated: {stats['caller_snippets']}")
    print(f"di_pattern breakdown: {stats['di_pattern']}")
    print(
        f"interface_shape populated: {n_shape} "
        f"(high confidence: {stats['interface_shape_high']}, "
        f"low: {stats['interface_shape_low']})"
    )
    print(f"context_files populated: {context_files_count} streams")
    print(f"Errors: {len(errors)} (see enrichment_errors)")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Enrich seam.json with source context")
    ap.add_argument("run_dir", help="Path to the run directory (e.g. runs/1792a195)")
    args = ap.parse_args()
    enrich_run(args.run_dir)
