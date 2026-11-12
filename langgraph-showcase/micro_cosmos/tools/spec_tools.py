"""Spec documentation RAG — fetches, indexes, and retrieves passages from
language specification pages and PDFs.

Index lifecycle
───────────────
The first call to query_spec_docs builds a persistent ChromaDB collection
under .rag_index/ at the project root.  The collection is keyed by a SHA-256
hash of the configured URL list; when SPEC_DOC_URLS changes the old collection
is dropped and rebuilt automatically.

Supported sources
─────────────────
• HTML web pages  — fetched with httpx, converted to Markdown via html2text.
• PDF documents   — fetched with httpx, extracted with pdfplumber.

Embeddings
──────────
sentence-transformers all-MiniLM-L6-v2 (384-d, ~80 MB, CPU-only).
The model is downloaded once by sentence-transformers to its cache dir.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_INDEX_DIR = Path(".rag_index")
_COLLECTION_NAME = "spec_docs"
_EMBED_MODEL = "all-MiniLM-L6-v2"
_CHUNK_SIZE = 800       # characters — comfortable for local context windows
_CHUNK_OVERLAP = 120
_BATCH = 400            # ChromaDB add() batch limit


# ─── text utilities ───────────────────────────────────────────────────────────

def _chunk(text: str) -> list[str]:
    """Split text into overlapping character chunks."""
    chunks: list[str] = []
    start = 0
    while start < len(text):
        chunk = text[start : start + _CHUNK_SIZE].strip()
        if chunk:
            chunks.append(chunk)
        start += _CHUNK_SIZE - _CHUNK_OVERLAP
    return chunks


def _url_hash(urls: list[str]) -> str:
    return hashlib.sha256(",".join(sorted(urls)).encode()).hexdigest()[:16]


# ─── fetchers ─────────────────────────────────────────────────────────────────

def _fetch_html(url: str, html: bytes) -> str:
    try:
        import html2text as _h2t
        h = _h2t.HTML2Text()
        h.ignore_links = True
        h.ignore_images = True
        h.body_width = 0
        return h.handle(html.decode("utf-8", errors="replace"))
    except ImportError:
        # Fallback: strip tags with stdlib
        import re
        text = html.decode("utf-8", errors="replace")
        return re.sub(r"<[^>]+>", " ", text)


def _fetch_pdf(content: bytes) -> str:
    import io
    import pdfplumber
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    return "\n\n".join(pages)


def _fetch_url(url: str) -> str:
    import httpx
    resp = httpx.get(
        url,
        follow_redirects=True,
        timeout=60,
        headers={"User-Agent": "MicroCosmos/1.0 (spec-indexer)"},
    )
    resp.raise_for_status()
    ct = resp.headers.get("content-type", "")
    if url.lower().endswith(".pdf") or "application/pdf" in ct:
        return _fetch_pdf(resp.content)
    return _fetch_html(url, resp.content)


# ─── ChromaDB collection ──────────────────────────────────────────────────────

def _open_collection(urls: list[str]):
    """Return a ChromaDB collection, rebuilding it if the URL set has changed."""
    import chromadb
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

    _INDEX_DIR.mkdir(exist_ok=True)
    client = chromadb.PersistentClient(path=str(_INDEX_DIR))
    ef = SentenceTransformerEmbeddingFunction(model_name=_EMBED_MODEL)
    current_hash = _url_hash(urls)

    # Try to reuse the existing collection
    try:
        col = client.get_collection(_COLLECTION_NAME, embedding_function=ef)
        if col.metadata.get("url_hash") == current_hash:
            logger.debug("RAG: reusing existing index (%d chunks)", col.count())
            return col
        logger.info("RAG: URL set changed — rebuilding index")
        client.delete_collection(_COLLECTION_NAME)
    except Exception:
        pass

    # Build a fresh collection
    col = client.create_collection(
        _COLLECTION_NAME,
        embedding_function=ef,
        metadata={"url_hash": current_hash},
    )

    ids: list[str] = []
    texts: list[str] = []
    metas: list[dict] = []

    for url in urls:
        try:
            logger.info("RAG: fetching %s", url)
            raw = _fetch_url(url)
            chunks = _chunk(raw)
            url_key = hashlib.md5(url.encode()).hexdigest()[:8]
            for i, chunk in enumerate(chunks):
                ids.append(f"{url_key}_{i}")
                texts.append(chunk)
                metas.append({"source": url})
            logger.info("RAG: indexed %d chunks from %s", len(chunks), url)
        except Exception as exc:
            logger.warning("RAG: failed to index %s: %s", url, exc)

    for start in range(0, len(texts), _BATCH):
        col.add(
            ids=ids[start : start + _BATCH],
            documents=texts[start : start + _BATCH],
            metadatas=metas[start : start + _BATCH],
        )

    logger.info("RAG: index built — %d total chunks from %d URL(s)", len(texts), len(urls))
    return col


# ─── public tool ─────────────────────────────────────────────────────────────

def _get_spec_urls() -> list[str]:
    import os
    raw = os.environ.get("SPEC_DOC_URLS", "")
    if not raw:
        try:
            from dotenv import dotenv_values
            raw = dotenv_values(".env").get("SPEC_DOC_URLS", "") or ""
        except ImportError:
            pass
    return [u.strip() for u in raw.split(",") if u.strip()]


def query_spec_docs(query: str, top_k: int = 5) -> dict:
    """Search indexed language specification documents for passages relevant to the query.

    Call this before writing or reviewing code to look up:
    - Idiomatic patterns and best practices for the target language
    - Standard library APIs (e.g. decimal handling, error wrapping)
    - Language specification rules (e.g. interface satisfaction, type constraints)
    - Style guide recommendations

    Args:
        query: Natural language question, e.g.
               "error handling idioms in Go",
               "decimal arithmetic precision in Java",
               "interface vs struct embedding Go".
        top_k: Number of passages to return (1–10, default 5).

    Returns:
        Dict with "passages" (list of {text, source, rank}) and the original
        "query".  Returns empty passages with a "note" if no URLs are configured.
    """
    urls = _get_spec_urls()
    if not urls:
        return {
            "query": query,
            "passages": [],
            "note": (
                "No spec docs configured. Add SPEC_DOC_URLS=url1,url2 to .env "
                "to enable spec retrieval."
            ),
        }

    top_k = min(max(1, top_k), 10)

    try:
        col = _open_collection(urls)
        n = col.count()
        if n == 0:
            return {"query": query, "passages": [], "note": "Spec index is empty."}

        results = col.query(query_texts=[query], n_results=min(top_k, n))
        docs = results.get("documents", [[]])[0]
        metas = results.get("metadatas", [[]])[0]

        passages = [
            {"text": doc, "source": meta.get("source", ""), "rank": i + 1}
            for i, (doc, meta) in enumerate(zip(docs, metas))
        ]
        return {"query": query, "passages": passages}

    except Exception as exc:
        logger.exception("RAG query failed: %s", exc)
        return {"query": query, "passages": [], "error": str(exc)}
