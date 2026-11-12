"""Per-run vector index over SOURCE CODE (as opposed to micro_cosmos/retrieval/index.py,
which indexes pipeline JSON artifacts for the ASK tab).

Layout (runs/<id>/source_vectors/) — deliberately a separate sidecar from the
ASK-tab's runs/<id>/vectors/, since the two indexes have different lifecycles:
the source tree is immutable for the life of a run (build once, reuse
unconditionally, no staleness watcher needed), while the artifact index is
progressively rebuilt as the pipeline produces more JSON. Reuses RunIndex's
search/embed/persist machinery unchanged (micro_cosmos/retrieval/index.py).
"""

from __future__ import annotations

import logging
from pathlib import Path

from micro_cosmos.retrieval.index import RunIndex, embed_and_persist, load_from_sidecar
from micro_cosmos.retrieval.source_chunks import build_source_chunks

log = logging.getLogger(__name__)

_SOURCE_VECTORS_SUBDIR = "source_vectors"

# In-memory cache so repeated search_relevant_source() calls within the same
# run (there can be many, across every seam/iteration) don't re-read
# chunks.jsonl/embeddings.npy/meta.json from disk every time — the whole
# point of building this index once. Safe to keep for the process's lifetime
# since the source tree never changes during a run; bounded so a long-lived
# server doesn't accumulate one full index per run forever (mirrors app.py's
# _MAX_RUNS eviction convention).
_INDEX_CACHE: dict[str, RunIndex] = {}
_CACHE_MAX = 20


def _source_vectors_dir(run_dir: Path) -> Path:
    return Path(run_dir) / _SOURCE_VECTORS_SUBDIR


def build_source_index(run_dir: Path, source_path: str, source_lang: str, ir_graph: dict, embedder=None) -> RunIndex:
    """Chunk + embed + persist the source estate once. Call this a single time,
    right before the seam TDD loop starts (source_path is fixed by then)."""
    run_dir = Path(run_dir)
    chunks = build_source_chunks(source_path, source_lang, ir_graph)
    log.info("build_source_index: %d chunks from %s for run %s", len(chunks), source_path, run_dir.name)
    return embed_and_persist(chunks, _source_vectors_dir(run_dir), embedder=embedder, artifact_mtime=0.0)


def load_source_index(run_dir: Path, source_path: str, source_lang: str, ir_graph: dict, embedder=None) -> RunIndex:
    """Load the source sidecar if it exists; build it once if not. No
    staleness check — the source tree doesn't change during a run, so once
    built, always reused as-is. Cached in memory across calls for the same
    run_dir (see _INDEX_CACHE above) — only the first call in a run's
    lifetime touches disk at all."""
    key = str(run_dir)
    cached = _INDEX_CACHE.get(key)
    if cached is not None:
        return cached

    run_dir = Path(run_dir)
    idx = load_from_sidecar(_source_vectors_dir(run_dir))
    if idx is None:
        idx = build_source_index(run_dir, source_path, source_lang, ir_graph, embedder=embedder)

    if len(_INDEX_CACHE) >= _CACHE_MAX:
        _INDEX_CACHE.pop(next(iter(_INDEX_CACHE)))
    _INDEX_CACHE[key] = idx
    return idx
