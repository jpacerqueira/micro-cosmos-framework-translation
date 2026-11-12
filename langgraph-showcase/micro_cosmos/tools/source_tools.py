"""Source file reading tools — give the LLM direct access to source code."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from micro_cosmos.langgraph_runtime import ToolContext

from micro_cosmos.tools.run_context import get_run_dir, set_run_dir  # noqa: F401 — re-exported


def _resolve_path(loc: str, root: Path) -> Path | None:
    """A seam/node source_location's file part may be absolute or relative to
    the source root, depending on how Observer recorded it — try both."""
    if not loc:
        return None
    file_part = loc.rsplit(":", 1)[0] if ":" in loc else loc
    p = Path(file_part)
    if p.is_absolute() and p.exists():
        return p
    cand = root / file_part
    return cand if cand.exists() else None


def _seam_relevant_files(root: Path, run_dir: str, seam_name: str) -> set[Path] | None:
    """Return files structurally related to seam_name (its own source file plus
    its 1-hop callers/callees via the IR graph, or both sides of a link-type
    seam's directory boundary), or None if resolution wasn't possible — the
    caller falls back to the unfiltered (today's) behavior in that case."""
    if not run_dir or not seam_name:
        return None
    rdir = Path(run_dir)
    seam_path = rdir / "seam.json"
    if not seam_path.exists():
        return None
    try:
        seams = json.loads(seam_path.read_text(encoding="utf-8")).get("seams", [])
    except Exception:
        return None
    seam = next((s for s in seams if s.get("id") == seam_name), None)
    if seam is None:
        return None

    files: set[Path] = set()

    loc = _resolve_path(seam.get("source_location", ""), root)
    if loc:
        files.add(loc)

    # side_a/side_b mean different things depending on seam type (seam_tools.py): for
    # directory-based link seams they're real top-level directory names; for context-
    # boundary/scheduler-task link seams they're bounded-context/task labels; for other
    # seam types they're human-readable prose ("3 caller(s)"). Only treat a side as a
    # directory filter when it actually resolves to a real directory — walking inside a
    # confirmed directory (rather than string-prefix-matching every file) also closes the
    # "Payment" vs "PaymentGateway" false-positive class for real directory-based seams.
    for side in (seam.get("side_a", ""), seam.get("side_b", "")):
        if not side.strip():
            continue
        side_dir = root / side.rstrip("/")
        if side_dir.is_dir():
            files.update(p for p in side_dir.rglob("*") if p.is_file())

    node_id = seam.get("location", "")
    try:
        from micro_cosmos.retrieval.graph_index import load_graph_index
        gidx = load_graph_index(rdir)
    except Exception:
        gidx = None
    if gidx is not None and node_id:
        facts = gidx.structural_facts(node_id)
        if not facts.get("is_unknown"):
            for nid in gidx.neighbourhood(node_id, hops=1):
                neighbour_loc = _resolve_path(gidx.structural_facts(nid).get("source_location", ""), root)
                if neighbour_loc:
                    files.add(neighbour_loc)

    return files or None


def list_source_files(
    source_path: str,
    source_lang: str,
    seam_name: str = "",
    tool_context: Optional[ToolContext] = None,
) -> dict:
    """Return source files for source_lang under source_path, scoped to the
    current seam when seam_name resolves to a known seam.

    Large files are truncated; call read_source_file to get the rest.
    """
    from micro_cosmos.tools.observer_tools import _source_files, _extensions_for

    if not source_path:
        return {
            "files": [],
            "count": 0,
            "source_path": source_path,
            "source_lang": source_lang,
            "extensions": _extensions_for(source_lang),
            "error": "source_path is empty.",
        }

    root = Path(source_path)
    if not root.exists():
        return {
            "files": [],
            "count": 0,
            "source_path": source_path,
            "source_lang": source_lang,
            "extensions": _extensions_for(source_lang),
            "error": f"source_path does not exist: {source_path}",
        }

    paths = _source_files(root, source_lang)
    scope = "estate-wide"
    if seam_name:
        scoped = _seam_relevant_files(root, get_run_dir(), seam_name)
        if scoped:
            paths = [p for p in paths if p in scoped]
            scope = "seam"

    _MAX_CHARS = 10_000
    _TOTAL_BUDGET = 120_000

    files = []
    total_chars = 0
    for p in paths:
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            content = f"[could not read: {exc}]"
        size = len(content)
        if total_chars >= _TOTAL_BUDGET:
            files.append({
                "path": str(p),
                "relative_path": str(p.relative_to(root)),
                "size": size,
                "content": "[budget exhausted — call read_source_file to read this file]",
                "truncated": True,
            })
            continue
        truncated = size > _MAX_CHARS
        excerpt = content[:_MAX_CHARS]
        total_chars += len(excerpt)
        files.append({
            "path": str(p),
            "relative_path": str(p.relative_to(root)),
            "size": size,
            "content": excerpt + ("\n\n[... truncated — call read_source_file for the rest ...]" if truncated else ""),
            "truncated": truncated,
        })

    return {
        "files": files,
        "count": len(files),
        "source_path": source_path,
        "source_lang": source_lang,
        "extensions": _extensions_for(source_lang),
        "scope": scope,
    }


def read_source_file(file_path: str) -> dict:
    """Return the full content of a single source file."""
    p = Path(file_path)
    if not p.exists():
        return {"path": file_path, "content": "", "lines": 0, "error": "File not found"}
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        return {"path": file_path, "content": content, "lines": len(content.splitlines())}
    except OSError as exc:
        return {"path": file_path, "content": "", "lines": 0, "error": str(exc)}
