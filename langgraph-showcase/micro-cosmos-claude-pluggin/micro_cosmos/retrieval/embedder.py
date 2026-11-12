"""LiteLLM embedding wrapper with graceful fallback.

Returns None (not an exception) when the embedding server is unreachable or
SKIP_LLM is set.  Callers treat None as "build in lexical mode".

The embedder always targets the local LM Studio endpoint — embeddings of client
source code must never leave the local machine, even when the reasoning model
routes to Claude (which has no embeddings API anyway).
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)


class Embedder:
    """Thin wrapper around litellm.embedding()."""

    def __init__(self, model: str, base_url: str, api_key: str) -> None:
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def embed(self, texts: list[str]) -> list[list[float]] | None:
        """Embed a batch of texts.  Returns None on any failure."""
        if not texts:
            return []
        try:
            import litellm

            resp = litellm.embedding(
                model=f"openai/{self.model}",
                input=texts,
                api_base=self.base_url,
                api_key=self.api_key,
            )
            log.info("POST %s/embeddings -> 200 OK (%d text(s))", self.base_url, len(texts))
            return [item["embedding"] for item in resp.data]
        except Exception as exc:
            log.debug("Embedding failed (%s) — falling back to lexical mode", exc)
            return None

    def embed_one(self, text: str) -> list[float] | None:
        result = self.embed([text])
        if result is None:
            return None
        return result[0] if result else None


def build_embedder() -> Embedder | None:
    """Build an Embedder from the current settings.  Returns None when SKIP_LLM."""
    from micro_cosmos.settings import get_settings

    s = get_settings()
    if s.skip_llm:
        return None

    model = getattr(s, "embedding_model", "")
    base_url = getattr(s, "embedding_base_url", s.llm_base_url)
    api_key = s.llm_api_key

    if not model:
        return None

    log.info("build_embedder: model=%s api_base=%s api_key_configured=%s", model, base_url, bool(api_key))
    return Embedder(model=model, base_url=base_url, api_key=api_key)
