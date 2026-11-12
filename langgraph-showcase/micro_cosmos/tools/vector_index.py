"""FAISS-backed vector index for IR nodes.

Provides semantic nearest-neighbour lookup over the IR node set.  Used by
submit_observer_output to fuzzy-match LLM function_summaries to parsed nodes
when exact name matching fails — the primary cause of "broken" AST results.

Embedding strategy (priority order):
  1. sentence-transformers all-MiniLM-L6-v2 — already a project dependency;
     384-d semantic vectors, CPU-only, loaded lazily on first call.
  2. Character-trigram TF-IDF — deterministic fallback when sentence-transformers
     cannot be imported; effective for code identifier names and short prose.

FAISS IndexFlatIP (exact flat inner-product) is used when faiss-cpu is
installed.  A pure-numpy fallback is active otherwise so the module is always
importable regardless of optional-dep install state.
"""

from __future__ import annotations

import math
import re
from collections import Counter

import numpy as np

try:
    import faiss  # type: ignore[import-untyped]

    _FAISS_OK = True
except ModuleNotFoundError:
    _FAISS_OK = False


# ── text representation ────────────────────────────────────────────────────────

def _node_text(node: dict) -> str:
    """Build a searchable string from an IR node or a function-summary entry."""
    parts = [
        node.get("type", ""),
        node.get("name", ""),
        node.get("summary", ""),
    ]
    attrs = node.get("attributes") or {}
    for k in ("kind", "package", "namespace", "handler_type", "handles_payload"):
        v = attrs.get(k)
        if v:
            parts.append(v)
    return " ".join(p for p in parts if p)


# ── char-trigram TF-IDF encoder ───────────────────────────────────────────────

def _trigrams(text: str) -> list[str]:
    s = re.sub(r"\s+", " ", text.lower()).strip()
    padded = f"  {s}  "
    return [padded[i : i + 3] for i in range(len(padded) - 2)]


class _TrigramTFIDF:
    """Encode text as a unit-norm char-trigram TF-IDF float32 vector."""

    def __init__(self, corpus: list[str]) -> None:
        vocab: dict[str, int] = {}
        df: dict[str, int] = {}
        N = max(len(corpus), 1)
        for text in corpus:
            for tg in set(_trigrams(text)):
                if tg not in vocab:
                    vocab[tg] = len(vocab)
                df[tg] = df.get(tg, 0) + 1
        self._vocab = vocab
        self._idf = {tg: math.log((N + 1) / (df.get(tg, 0) + 1)) + 1.0 for tg in vocab}
        self.dim = max(len(vocab), 1)

    def encode(self, text: str) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        for tg, cnt in Counter(_trigrams(text)).items():
            idx = self._vocab.get(tg)
            if idx is not None:
                v[idx] = cnt * self._idf[tg]
        norm = np.linalg.norm(v)
        return v / norm if norm > 0 else v


# ── sentence-transformers embeddings ─────────────────────────────────────────

_ST_MODEL_NAME = "all-MiniLM-L6-v2"
_st_model = None  # lazy singleton


def _st_embed(texts: list[str]) -> np.ndarray | None:
    """Encode *texts* with sentence-transformers.  Returns a float32 matrix
    of shape ``(len(texts), dim)`` with unit-norm rows, or ``None`` on error."""
    global _st_model
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]

        if _st_model is None:
            _st_model = SentenceTransformer(_ST_MODEL_NAME)
        mat = _st_model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
        return mat.astype(np.float32)
    except Exception:
        return None


# ── pure-numpy fallback index ─────────────────────────────────────────────────

class _NumpyFlatIP:
    """Exact flat inner-product search without FAISS."""

    def __init__(self, mat: np.ndarray) -> None:
        self._mat = mat

    def add(self, mat: np.ndarray) -> None:  # noqa: ARG002
        pass

    def search(
        self, query: np.ndarray, k: int
    ) -> tuple[np.ndarray, np.ndarray]:
        if self._mat.shape[0] == 0:
            return np.zeros((1, 0), np.float32), np.full((1, 0), -1, np.int64)
        scores = (self._mat @ query.T).flatten()
        k = min(k, len(scores))
        top = np.argsort(scores)[::-1][:k]
        return scores[top].reshape(1, -1).astype(np.float32), top.reshape(1, -1).astype(np.int64)


# ── public API ────────────────────────────────────────────────────────────────

class NodeVectorIndex:
    """FAISS flat cosine index (IndexFlatIP on unit-normed vectors) over
    a list of IR node dicts or function-summary dicts.

    Usage::

        index = NodeVectorIndex.build(ir_nodes)
        hits  = index.search("calculateInterest", k=3)
        # → [(0.91, {node_dict}), (0.72, {node_dict}), ...]
    """

    # Cosine-similarity threshold above which a fuzzy match is accepted.
    MATCH_THRESHOLD: float = 0.60

    def __init__(
        self,
        nodes: list[dict],
        mat: np.ndarray,
        raw_index: object,
        encoder: _TrigramTFIDF | None,
        use_st: bool,
    ) -> None:
        self._nodes = nodes
        self._mat = mat
        self._raw = raw_index
        self._encoder = encoder
        self._use_st = use_st

    # ── construction ─────────────────────────────────────────────────────────

    @classmethod
    def build(cls, nodes: list[dict]) -> "NodeVectorIndex":
        """Build a cosine index from *nodes* (IR node dicts or summary dicts)."""
        if not nodes:
            empty = np.zeros((0, 1), np.float32)
            raw = faiss.IndexFlatIP(1) if _FAISS_OK else _NumpyFlatIP(empty)
            return cls(nodes, empty, raw, None, False)

        texts = [_node_text(n) for n in nodes]
        encoder: _TrigramTFIDF | None = None
        use_st = False

        st_mat = _st_embed(texts)
        if st_mat is not None and st_mat.shape[0] == len(texts):
            mat = st_mat
            use_st = True
        else:
            encoder = _TrigramTFIDF(texts)
            mat = np.stack([encoder.encode(t) for t in texts])

        dim = mat.shape[1]
        if _FAISS_OK:
            raw: object = faiss.IndexFlatIP(dim)
            raw.add(mat)  # type: ignore[attr-defined]
        else:
            raw = _NumpyFlatIP(mat)

        return cls(nodes, mat, raw, encoder, use_st)

    # ── search ────────────────────────────────────────────────────────────────

    def search(self, query: str, k: int = 5) -> list[tuple[float, dict]]:
        """Return up to *k* ``(score, node_dict)`` pairs sorted by cosine
        similarity descending.  Scores are in ``[-1, 1]``; ``≥ MATCH_THRESHOLD``
        indicates a reliable match."""
        if not self._nodes:
            return []
        vec = self._embed(query).reshape(1, -1)
        k = min(k, len(self._nodes))
        scores, indices = self._raw.search(vec, k)  # type: ignore[attr-defined]
        results = []
        for score, idx in zip(scores[0], indices[0]):
            if int(idx) >= 0:
                results.append((float(score), self._nodes[int(idx)]))
        return results

    # ── internals ────────────────────────────────────────────────────────────

    def _embed(self, text: str) -> np.ndarray:
        if self._use_st:
            vec = _st_embed([text])
            if vec is not None:
                return vec[0]
            # sentence-transformers unexpectedly failed — fall through to trigram
            self._use_st = False
            self._encoder = _TrigramTFIDF([_node_text(n) for n in self._nodes])
        assert self._encoder is not None
        return self._encoder.encode(text)
