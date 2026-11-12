"""Per-run vector index with disk sidecar.

Layout (runs/<id>/vectors/):
  chunks.jsonl    — one JSON line per Chunk (id, kind, text, source_location, meta)
  embeddings.npy  — float32 array of shape (n_chunks, dims); absent in lexical mode
  index.faiss     — FAISS IndexFlatIP (inner product = cosine on L2-normalised vecs);
                    present only when faiss-cpu is installed
  meta.json       — {mode, model, dims, built_at, artifact_mtime, chunk_count}

Modes (in preference order):
  faiss   — FAISS IndexFlatIP search (faiss-cpu installed + embeddings available)
  vector  — brute-force numpy cosine (embeddings available, no faiss-cpu)
  lexical — Jaccard token-overlap (no embedding server / SKIP_LLM=True)

All four pipeline phases (Observer, Cartographer, Architect, Security) and gate
decisions are indexed so the ASK tab can reason over the full analysis context.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from micro_cosmos.retrieval.chunks import _NARRATIVE_HTML_REPORTS, Chunk, build_chunks

log = logging.getLogger(__name__)

_VECTORS_SUBDIR = "vectors"
_BATCH_SIZE = 64

# Optional FAISS — graceful degradation to numpy when not installed
try:
    import faiss as _faiss
    _FAISS_AVAILABLE = True
except ImportError:
    _faiss = None  # type: ignore[assignment]
    _FAISS_AVAILABLE = False


@dataclass
class SearchResult:
    chunk: Chunk
    score: float


class RunIndex:
    """Loaded index for a single run."""

    def __init__(
        self,
        chunks: list[Chunk],
        embeddings,              # np.ndarray | None
        mode: str,               # "faiss" | "vector" | "lexical"
        faiss_index=None,        # faiss.IndexFlatIP | None
    ) -> None:
        self._chunks = chunks
        self._embeddings = embeddings
        self._mode = mode
        self._faiss_index = faiss_index
        self._token_cache: dict[str, set[str]] = {}

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    @property
    def mode(self) -> str:
        return self._mode

    # ── Search ────────────────────────────────────────────────────────────────

    def search(self, query: str, k: int = 8) -> list[SearchResult]:
        if not self._chunks:
            return []
        k = min(k, len(self._chunks))
        if self._mode in ("faiss", "vector") and self._embeddings is not None:
            return self._vector_search(query, k)
        return self._lexical_search(query, k)

    def _vector_search(self, query: str, k: int) -> list[SearchResult]:
        from micro_cosmos.retrieval.embedder import build_embedder

        embedder = build_embedder()
        if embedder is None:
            return self._lexical_search(query, k)

        q_vec = embedder.embed_one(query)
        if q_vec is None:
            return self._lexical_search(query, k)

        import numpy as np

        q = np.array(q_vec, dtype="float32")
        q_norm = q / (np.linalg.norm(q) + 1e-10)

        if self._faiss_index is not None:
            # FAISS inner-product search — equivalent to cosine on L2-normalised vecs
            scores_arr, indices_arr = self._faiss_index.search(
                q_norm.reshape(1, -1), k
            )
            results = []
            for idx, score in zip(indices_arr[0], scores_arr[0]):
                if 0 <= idx < len(self._chunks):
                    results.append(SearchResult(self._chunks[idx], float(score)))
            return results

        # Numpy fallback (no FAISS)
        scores = self._embeddings @ q_norm  # (n,)
        top_idx = np.argsort(scores)[::-1][:k]
        return [SearchResult(self._chunks[i], float(scores[i])) for i in top_idx]

    def _lexical_search(self, query: str, k: int) -> list[SearchResult]:
        q_tokens = _tokenise(query)
        if not q_tokens:
            return [SearchResult(c, 0.0) for c in self._chunks[:k]]

        scored = []
        for chunk in self._chunks:
            c_tokens = self._get_tokens(chunk)
            intersection = len(q_tokens & c_tokens)
            union = len(q_tokens | c_tokens)
            score = intersection / union if union else 0.0
            # Boost exact id/name matches
            if any(t in chunk.id.lower() for t in q_tokens if len(t) > 3):
                score += 0.2
            scored.append((score, chunk))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [SearchResult(c, s) for s, c in scored[:k]]

    def _get_tokens(self, chunk: Chunk) -> set[str]:
        if chunk.id not in self._token_cache:
            self._token_cache[chunk.id] = _tokenise(chunk.text)
        return self._token_cache[chunk.id]


def _tokenise(text: str) -> set[str]:
    return set(re.findall(r"[a-z][a-z0-9]{2,}", text.lower()))


# ── Build / load ──────────────────────────────────────────────────────────────

def _vectors_dir(run_dir: Path) -> Path:
    return run_dir / _VECTORS_SUBDIR


def _latest_artifact_mtime(run_dir: Path) -> float:
    """Return the latest mtime across all files that contribute to the index.

    Covers: root-level JSON artifacts (including gate_*.json and security_report.json),
    narrative HTML reports (in reports/ first, then run root), and reports/*.md.
    """
    mtimes: list[float] = []
    reports_dir = run_dir / "reports"

    # Root-level JSON artifacts (ir_graph, tnas, seam, bcm, gate_*, security_report, etc.)
    if run_dir.exists():
        mtimes.extend(p.stat().st_mtime for p in run_dir.iterdir() if p.suffix == ".json")

    # Narrative HTML reports — prefer reports/ subdirectory, fall back to run root
    for name in _NARRATIVE_HTML_REPORTS:
        for candidate in (reports_dir / name, run_dir / name):
            if candidate.exists():
                mtimes.append(candidate.stat().st_mtime)
                break

    # Markdown reports
    if reports_dir.is_dir():
        mtimes.extend(
            p.stat().st_mtime for p in reports_dir.glob("*.md")
            if p.name != "CONVERSATION-SUMMARY.md"
        )

    return max(mtimes, default=0.0)


def _is_stale(run_dir: Path) -> bool:
    """Return True if the sidecar is missing or older than any indexed artifact."""
    meta_path = _vectors_dir(run_dir) / "meta.json"
    if not meta_path.exists():
        return True
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        recorded_mtime = meta.get("artifact_mtime", 0)
        latest = _latest_artifact_mtime(run_dir)
        return latest > recorded_mtime + 1  # 1-second tolerance
    except Exception:
        return True


def embed_and_persist(chunks: list[Chunk], vdir: Path, embedder=None, artifact_mtime: float = 0.0) -> RunIndex:
    """Embed + persist a chunk list to a sidecar dir and return the resulting
    RunIndex — the shared machinery behind build_index() below, factored out so
    other chunk sources (e.g. micro_cosmos/retrieval/source_index.py's source-code
    index) can reuse the exact same embed/FAISS/lexical-fallback/meta.json
    logic without duplicating it or depending on build_chunks(run_dir)'s
    pipeline-artifact-specific chunking."""
    import numpy as np

    vdir.mkdir(parents=True, exist_ok=True)

    # Persist chunks
    chunks_path = vdir / "chunks.jsonl"
    with chunks_path.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(asdict(c), ensure_ascii=False) + "\n")

    # Attempt embeddings
    mode = "lexical"
    embeddings: np.ndarray | None = None
    faiss_index = None

    if embedder is None:
        from micro_cosmos.retrieval.embedder import build_embedder
        embedder = build_embedder()

    if embedder is not None:
        texts = [c.text for c in chunks]
        vecs: list[list[float]] = []
        for i in range(0, len(texts), _BATCH_SIZE):
            batch = embedder.embed(texts[i : i + _BATCH_SIZE])
            if batch is None:
                vecs = []
                break
            vecs.extend(batch)

        if vecs and len(vecs) == len(chunks):
            arr = np.array(vecs, dtype="float32")
            # L2-normalise for cosine similarity via dot / inner product
            norms = np.linalg.norm(arr, axis=1, keepdims=True)
            arr = arr / (norms + 1e-10)
            np.save(str(vdir / "embeddings.npy"), arr)
            embeddings = arr

            # Build FAISS index when available
            if _FAISS_AVAILABLE:
                try:
                    faiss_index = _faiss.IndexFlatIP(arr.shape[1])
                    faiss_index.add(arr)
                    _faiss.write_index(faiss_index, str(vdir / "index.faiss"))
                    mode = "faiss"
                    log.info(
                        "build_index: FAISS IndexFlatIP (%d vecs, dim %d)",
                        len(vecs), arr.shape[1],
                    )
                except Exception:
                    log.warning("build_index: FAISS build failed — using numpy vector mode")
                    faiss_index = None
                    mode = "vector"
            else:
                mode = "vector"
                log.info("build_index: %d embeddings (dim %d, numpy mode)", len(vecs), arr.shape[1])
        else:
            log.info("build_index: embeddings unavailable — lexical mode")

    meta = {
        "mode": mode,
        "model": embedder.model if embedder and mode != "lexical" else "",
        "dims": int(embeddings.shape[1]) if embeddings is not None else 0,
        "built_at": time.time(),
        "artifact_mtime": artifact_mtime,
        "chunk_count": len(chunks),
    }
    (vdir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    return RunIndex(chunks=chunks, embeddings=embeddings, mode=mode, faiss_index=faiss_index)


def build_index(run_dir: Path, embedder=None) -> RunIndex:
    """Build and persist a sidecar index for the given run directory.

    Indexes all four pipeline phases (Observer, Cartographer, Architect, Security)
    plus gate decisions.  Uses FAISS IndexFlatIP when faiss-cpu is installed;
    falls back to numpy brute-force cosine or lexical Jaccard.
    """
    run_dir = Path(run_dir)
    vdir = _vectors_dir(run_dir)

    chunks = build_chunks(run_dir)
    log.info("build_index: %d chunks for run %s", len(chunks), run_dir.name)

    try:
        latest_mtime = _latest_artifact_mtime(run_dir)
    except Exception:
        latest_mtime = time.time()

    return embed_and_persist(chunks, vdir, embedder=embedder, artifact_mtime=latest_mtime)


def load_from_sidecar(vdir: Path) -> RunIndex | None:
    """Load a RunIndex from an already-built sidecar dir (chunks.jsonl +
    meta.json [+ embeddings.npy] [+ index.faiss]), generic over any vdir —
    shared by load_index() below and micro_cosmos/retrieval/source_index.py.
    Returns None if the sidecar is missing or corrupt (caller decides whether
    to rebuild)."""
    import numpy as np

    chunks_path = vdir / "chunks.jsonl"
    meta_path = vdir / "meta.json"
    if not chunks_path.exists() or not meta_path.exists():
        return None

    try:
        chunks = []
        with chunks_path.open(encoding="utf-8") as f:
            for line in f:
                data = json.loads(line)
                chunks.append(
                    Chunk(
                        id=data["id"],
                        kind=data["kind"],
                        text=data["text"],
                        source_location=data.get("source_location", ""),
                        meta=data.get("meta", {}),
                    )
                )

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        mode = meta.get("mode", "lexical")

        embeddings = None
        emb_path = vdir / "embeddings.npy"
        if mode in ("faiss", "vector") and emb_path.exists():
            embeddings = np.load(str(emb_path))

        # Load FAISS index if available and present
        faiss_index = None
        faiss_path = vdir / "index.faiss"
        if _FAISS_AVAILABLE and faiss_path.exists():
            try:
                faiss_index = _faiss.read_index(str(faiss_path))
                mode = "faiss"
            except Exception:
                log.warning("load_from_sidecar: could not load FAISS index at %s — using numpy", vdir)

        log.info("load_from_sidecar: %d chunks (%s mode) from %s", len(chunks), mode, vdir)
        return RunIndex(chunks=chunks, embeddings=embeddings, mode=mode, faiss_index=faiss_index)

    except Exception as exc:
        log.warning("load_from_sidecar: corrupt sidecar at %s (%s)", vdir, exc)
        return None


def load_index(run_dir: Path, embedder=None, force_rebuild: bool = False) -> RunIndex:
    """Load the sidecar index; rebuild if stale or missing."""
    run_dir = Path(run_dir)

    if force_rebuild or _is_stale(run_dir):
        return build_index(run_dir, embedder=embedder)

    idx = load_from_sidecar(_vectors_dir(run_dir))
    if idx is None:
        return build_index(run_dir, embedder=embedder)
    return idx
