---
name: ask-tab-architecture
description: ASK tab (chat) architecture — FAISS RAG, client-side history, zero coupling to pipeline ADK session
metadata:
  type: project
---

The ASK tab (`POST /runs/{id}/chat`) is completely decoupled from the pipeline ADK session.

**Data sources:**
- FAISS vector index — built lazily from all run artifacts into `runs/<id>/vectors/` on first chat call
- Graph index — loaded from `runs/<id>/` artifact JSON files
- Both are disk-based; built by `micro_cosmos.retrieval.index` and `micro_cosmos.retrieval.graph_index`

**Conversation history:**
- Managed entirely **client-side** in `dashboard.js`
- Full `history` array (prior Q&A turns) sent with every request body
- Server is stateless for chat — no session stored server-side between requests
- History trimmed to last `2 * _MAX_HISTORY_TURNS` before sending to model

**Model calls:**
- Direct Anthropic API call inside `micro_cosmos.retrieval.chat.answer()`
- No ADK Runner, no `InMemorySessionService`, no Google ADK involvement

**Impact of `reset_session()` fix:** Zero. The pipeline session reset is entirely orthogonal. Multi-turn ASK conversations are unaffected regardless of what the TDD loop is doing to the pipeline session.
