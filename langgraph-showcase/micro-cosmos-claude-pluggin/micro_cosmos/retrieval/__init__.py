"""Per-run retrieval layer — hybrid vector + graph index for the chat endpoint.

Architecture:
- chunks.py   — Chunk dataclass + builders from every artifact type
- embedder.py — LiteLLM embedding wrapper with lexical fallback
- index.py    — brute-force numpy cosine index + disk sidecar (runs/<id>/vectors/)
- graph_index.py — networkx structural facts (fan-in/out, cycles, neighbourhood)
- chat.py     — fuses vector retrieval + structural facts into a grounded LLM answer

Data residency: embeddings are computed locally (LM Studio endpoint).  At answer
time, the question + retrieved chunks go to the reasoning model — if that model is
a Claude route (ANTHROPIC_API_KEY set), excerpts from client source code will leave
the local machine.  For sensitive estates, keep MODEL_REASONING local too (the
default already does this).
"""

from micro_cosmos.retrieval.chat import answer
from micro_cosmos.retrieval.chunks import Chunk, build_chunks
from micro_cosmos.retrieval.graph_index import GraphIndex, build_graph_index
from micro_cosmos.retrieval.index import RunIndex, build_index, load_index

__all__ = [
    "Chunk",
    "build_chunks",
    "GraphIndex",
    "build_graph_index",
    "RunIndex",
    "build_index",
    "load_index",
    "answer",
]
