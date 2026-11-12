"""FAISS/vector-backed source-code search — the primary way Code Writer and
Functional Reviewer should read source code, instead of list_source_files
dumping (and read_source_file fully reading) the whole source estate every
TDD iteration. Returns small, relevant excerpts, never full files.
"""

from __future__ import annotations

import json
from pathlib import Path


def _as_int(value: object, default: int) -> int:
    """Models often send ``k`` as a string. Honor the requested count."""
    if isinstance(value, bool) or value is None:
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        try:
            return int(text)
        except ValueError:
            try:
                return int(float(text))
            except ValueError:
                return default
    return default


def search_relevant_source(
    seam_name: str = "",
    query: str = "",
    source_path: str = "",
    source_lang: str = "",
    run_dir: str = "",
    k: int = 5,
) -> dict:
    """Search the source estate for code relevant to `query`, scoped to the
    current seam when possible.

    Prefer this over list_source_files/read_source_file — it returns small,
    ranked excerpts of the source most relevant to what you're doing right
    now, not whole files. Only fall back to list_source_files if this returns
    fewer than 2 results, or to read_source_file if a specific excerpt is
    truncated and you need the surrounding code it references.

    Args:
        seam_name: The current seam id — narrows results to structurally
            related files when seam.json/ir_graph.json can resolve them.
        query: What you're looking for, e.g. "fraud score calculation logic"
            or "validation rules for AppUser". Natural language, not a
            filename.
        source_path: The source estate root (same value passed to
            list_source_files).
        source_lang: The source language (same value passed to
            list_source_files).
        run_dir: The current run directory — needed to load/build the index
            and resolve seam scoping.
        k: Number of excerpts to return (1-10, default 5).

    Returns:
        {"query", "seam_name", "mode": "faiss"|"vector"|"lexical", "scope":
         "seam"|"estate-wide", "results": [{"source_location", "text", "score"}]}
    """
    k = _as_int(k, 5)
    k = max(1, min(k, 10))
    if not run_dir or not source_path:
        return {
            "query": query, "seam_name": seam_name, "mode": "none",
            "scope": "estate-wide", "results": [],
            "note": "run_dir and source_path are required.",
        }

    rdir = Path(run_dir)
    ir_graph: dict = {}
    ir_path = rdir / "ir_graph.json"
    if ir_path.exists():
        try:
            ir_graph = json.loads(ir_path.read_text(encoding="utf-8"))
        except Exception:
            ir_graph = {}

    from micro_cosmos.retrieval.source_index import load_source_index
    idx = load_source_index(rdir, source_path, source_lang, ir_graph)

    results = idx.search(query, k=k * 3 if seam_name else k)  # over-fetch, then narrow by seam

    scope = "estate-wide"
    if seam_name:
        from micro_cosmos.tools.source_tools import _seam_relevant_files
        scoped_files = _seam_relevant_files(Path(source_path), run_dir, seam_name)
        if scoped_files:
            scope = "seam"
            scoped_strs = {str(p) for p in scoped_files}
            narrowed = [r for r in results if r.chunk.source_location.rsplit(":", 1)[0] in scoped_strs]
            results = (narrowed or results)[:k]
        else:
            results = results[:k]
    else:
        results = results[:k]

    return {
        "query": query,
        "seam_name": seam_name,
        "mode": idx.mode,
        "scope": scope,
        "results": [
            {"source_location": r.chunk.source_location, "text": r.chunk.text, "score": round(r.score, 4)}
            for r in results
        ],
    }
