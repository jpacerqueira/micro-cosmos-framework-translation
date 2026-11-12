"""Source-code -> Chunk converters.

Unlike micro_cosmos/retrieval/chunks.py (which chunks pipeline JSON artifacts and
generated reports for the ASK tab), this module chunks the actual SOURCE CODE
being translated — the estate at `source_path`, not anything under `run_dir`.

Chunking strategy: reuse Observer's already-computed IR node boundaries
(ir_graph.json's per-node `source_location: "file:line"`) rather than adding a
new parser — one chunk per IR node, spanning from its start line to the next
node's start line in the same file (or EOF). Files with zero IR nodes (config
files, languages Observer doesn't parse, symbolic-fallback misses) fall back
to a simple sliding window so they're still searchable.
"""

from __future__ import annotations

from pathlib import Path

from micro_cosmos.retrieval.chunks import Chunk

_MAX_CHUNK_CHARS = 4_000       # defensive ceiling — a single huge paragraph/class
_WINDOW_LINES = 150            # sliding-window fallback chunk size
_WINDOW_OVERLAP = 20


def _loc_parts(source_location: str) -> tuple[str, int]:
    """Split "path/to/File.java:42" into ("path/to/File.java", 42). Returns
    (source_location, 0) if there's no trailing :line."""
    if ":" not in source_location:
        return source_location, 0
    file_part, _, line_part = source_location.rpartition(":")
    try:
        return file_part, int(line_part)
    except ValueError:
        return source_location, 0


def _cap(text: str) -> str:
    if len(text) <= _MAX_CHUNK_CHARS:
        return text
    return text[:_MAX_CHUNK_CHARS] + "\n\n[... chunk truncated ...]"


def _sliding_window_chunks(file_path: Path, rel_path: str) -> list[Chunk]:
    try:
        lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    if not lines:
        return []
    chunks = []
    step = _WINDOW_LINES - _WINDOW_OVERLAP
    for start in range(0, len(lines), step):
        end = min(start + _WINDOW_LINES, len(lines))
        text = "\n".join(lines[start:end])
        if not text.strip():
            continue
        chunks.append(Chunk(
            id=f"src:{rel_path}:{start + 1}",
            kind="source",
            text=_cap(f"File: {rel_path}\n{text}"),
            source_location=f"{file_path}:{start + 1}",
            meta={"name": "", "end_line": end},
        ))
        if end == len(lines):
            break
    return chunks


def chunk_source_file(file_path: Path, root: Path, nodes_in_file: list[dict]) -> list[Chunk]:
    """One chunk per IR node located in this file, ordered by start line.
    Falls back to a sliding window when nodes_in_file is empty."""
    rel_path = str(file_path.relative_to(root))
    if not nodes_in_file:
        return _sliding_window_chunks(file_path, rel_path)

    try:
        lines = file_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    if not lines:
        return []

    ordered = sorted(nodes_in_file, key=lambda n: _loc_parts(n.get("source_location", ""))[1])
    chunks = []
    for i, node in enumerate(ordered):
        start = max(_loc_parts(node.get("source_location", ""))[1], 1)
        end = (
            max(_loc_parts(ordered[i + 1].get("source_location", ""))[1] - 1, start)
            if i + 1 < len(ordered)
            else len(lines)
        )
        text = "\n".join(lines[start - 1:end])
        if not text.strip():
            continue
        chunks.append(Chunk(
            id=f"src:{rel_path}:{start}",
            kind="source",
            text=_cap(f"File: {rel_path}\nFunction/class: {node.get('name', '')}\n{text}"),
            source_location=f"{file_path}:{start}",
            meta={"node_id": node.get("id", ""), "name": node.get("name", ""), "end_line": end},
        ))
    return chunks or _sliding_window_chunks(file_path, rel_path)


def build_source_chunks(source_path: str, source_lang: str, ir_graph: dict) -> list[Chunk]:
    """Chunk every source file under source_path matching source_lang,
    scoped by whatever IR nodes ir_graph already resolved to that file."""
    from micro_cosmos.tools.observer_tools import _source_files

    root = Path(source_path)
    if not root.exists():
        return []

    nodes_by_file: dict[str, list[dict]] = {}
    for node in ir_graph.get("nodes", []):
        file_part, _ = _loc_parts(node.get("source_location", ""))
        if file_part:
            nodes_by_file.setdefault(file_part, []).append(node)

    def _resolve_nodes_for(file_path: Path) -> list[dict]:
        rel = str(file_path.relative_to(root))
        abs_str = str(file_path)
        return nodes_by_file.get(abs_str, []) or nodes_by_file.get(rel, [])

    chunks: list[Chunk] = []
    for file_path in _source_files(root, source_lang):
        chunks.extend(chunk_source_file(file_path, root, _resolve_nodes_for(file_path)))
    return chunks
