"""Grounded Q&A over a single run's artifacts with CoT reasoning and multi-turn history.

answer(run_dir, question, history) -> {answer, citations, mode, steps}

Pipeline:
1. Load (or lazily rebuild) the RunIndex — covers all four pipeline phases:
   Observer (ir_graph, seam, work_streams), Cartographer (bounded_context_map),
   Architect (tnas, HTML reports), Security (security_report), plus gate decisions.
2. Query expansion — extract named entities and key terms to generate sub-queries.
3. Multi-pass retrieval — search on the original question and each sub-query;
   deduplicate by chunk id so diverse artifact kinds are represented.
4. Structural enrichment — inject graph facts for IR nodes mentioned in the question.
5. CoT-prompted LLM call — system prompt instructs step-by-step evidence reasoning;
   multi-turn history is threaded as prior messages so the model stays in context.
6. Return {answer, citations, mode, steps} — steps expose the retrieval trace and
   reasoning for display in the ASK tab.

Under SKIP_LLM: skip step 5, return top chunks verbatim (extractive).

Data residency: if MODEL_REASONING routes to Claude (ANTHROPIC_API_KEY set), the
question, history, and retrieved chunk excerpts will be sent to Anthropic.
Keep MODEL_REASONING pointing at a local model for sensitive client source.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_DEFAULT_K = 12                  # primary retrieval pass
_SUB_QUERY_K = 5                 # secondary passes per sub-query
_MAX_HISTORY_TURNS = 6           # prior Q&A pairs included in context (12 messages)
_MAX_CONTEXT_CHARS = 20_000      # hard cap on retrieval context fed to the LLM
_MAX_TOKENS = 2048               # LLM response budget

# Stopwords to strip when building sub-queries from the user question
_STOPWORDS = frozenset(
    "a an the is are was were be been being have has had do does did will would "
    "could should may might shall can what who how why when where which that this "
    "these those and or but if of in on at to for with about from by into as it its "
    "me my we our you your they their them there then than any all some no not i am".split()
)

_SYSTEM_PROMPT = """\
You are an expert software architect reviewing a migration analysis produced by the \
Micro-Cosmos & Security pipeline. The pipeline ran four phases:

  Phase 1 — Observer     → ir_graph.json  (nodes, edges, dead code, security hints)
  Phase 2 — Cartographer → bounded_context_map.json, work_streams.json
  Phase 3 — Architect    → tnas.json (services, fitness functions, architecture decisions,
                            migration sequence, architect_notes), HTML reports
  Phase 4 — Security     → security_report.json (findings, severity, CWE, remediation,
                            source/destination risk, migration_security_notes)

Each phase was reviewed through a human gate (Gate 1–4). Reviewer constraints and \
decisions are in gate_*.json.

Your task: answer the user's question by reasoning through the evidence step by step.

Reasoning approach:
  1. Identify which artifact(s) are most relevant to the question.
  2. State what you found in those artifacts — name specific context names, finding IDs,
     risk levels, and locations; do not paraphrase vaguely.
  3. Draw a grounded conclusion. Call out any gaps if the context is insufficient.
  4. Cite every chunk you used with [chunk_id] in square brackets.

Rules:
  - Answer ONLY from the provided context. Do not invent details not in the context.
  - If the context does not contain enough information, say exactly what is missing.
  - Be specific: name contexts, services, finding IDs, and artifact keys.
  - For risk questions: reference severity, confirmed status, and migration impact.
  - For architecture questions: reference node_ids, migration_risk, pattern_recommendation,
    and architect_notes from the TNAS.
  - Keep the answer concise; avoid generic migration advice that is not evidence-based.
"""


def _expand_queries(question: str) -> list[str]:
    """Extract sub-queries from the question for multi-pass retrieval.

    Returns up to 2 focused sub-queries derived from named entities (CamelCase /
    ALL_CAPS tokens) and key domain terms in the question.  Returns [] when the
    question is already atomic enough that a second pass would be redundant.
    """
    sub: list[str] = []

    # Named entities: CamelCase, PascalCase, ALL_CAPS, dotted identifiers
    entities = re.findall(r"\b(?:[A-Z][a-z]+){2,}\b|\b[A-Z]{2,}\b|\b\w+\.\w+\b", question)
    entities = [e for e in entities if len(e) > 3]
    if entities:
        sub.append(" ".join(entities[:4]))

    # Domain keywords: extract meaningful non-stopword tokens
    tokens = [
        t.lower() for t in re.findall(r"[a-zA-Z][a-zA-Z0-9]{3,}", question)
        if t.lower() not in _STOPWORDS
    ]
    # Focus sub-query on security/risk if those terms appear
    security_terms = {"security", "vulnerability", "finding", "risk", "cwe", "severity",
                      "injection", "xss", "csrf", "authentication", "authorization"}
    arch_terms = {"architecture", "service", "context", "seam", "migration", "fitness",
                  "boundary", "coupling", "dependency", "pattern", "stream"}

    if any(t in security_terms for t in tokens) and len(sub) < 2:
        sub.append("security findings risk vulnerability remediation " + " ".join(
            t for t in tokens if t not in security_terms
        )[:60])
    elif any(t in arch_terms for t in tokens) and len(sub) < 2:
        sub.append("architecture migration service context " + " ".join(
            t for t in tokens if t not in arch_terms
        )[:60])

    return sub[:2]


def answer(
    run_dir: str | Path,
    question: str,
    k: int = _DEFAULT_K,
    history: list[dict] | None = None,
) -> dict[str, Any]:
    """Return {answer, citations, mode, steps} for a question about a run.

    history: list of prior {role, content} messages (newest last).  The last
    _MAX_HISTORY_TURNS pairs are included as context for multi-turn coherence.

    steps: list of dicts describing the retrieval trace and reasoning context,
    rendered in the ASK tab as a collapsible CoT panel.
    """
    from micro_cosmos.retrieval.graph_index import load_graph_index
    from micro_cosmos.retrieval.index import load_index
    from micro_cosmos.settings import get_settings

    run_dir = Path(run_dir)
    settings = get_settings()
    steps: list[dict[str, Any]] = []

    # ── 1. Load index ──────────────────────────────────────────────────────────
    idx = load_index(run_dir)
    index_mode = idx.mode

    # ── 2. Query expansion ─────────────────────────────────────────────────────
    sub_queries = _expand_queries(question)

    # ── 3. Multi-pass retrieval ────────────────────────────────────────────────
    seen_ids: set[str] = set()
    unique_results: list = []
    retrieval_passes: list[dict] = []

    def _add_results(results: list, query: str) -> None:
        added = 0
        for r in results:
            if r.chunk.id not in seen_ids:
                seen_ids.add(r.chunk.id)
                unique_results.append(r)
                added += 1
        retrieval_passes.append({"query": query[:120], "returned": len(results), "new": added})

    primary = idx.search(question, k=k)
    _add_results(primary, question)

    for sq in sub_queries:
        if sq.strip():
            sub_results = idx.search(sq, k=_SUB_QUERY_K)
            _add_results(sub_results, sq)

    if not unique_results:
        return {
            "answer": "No index data available for this run. The artifacts may not have been generated yet.",
            "citations": [],
            "mode": "none",
            "steps": [],
        }

    artifact_kinds = sorted({r.chunk.kind for r in unique_results})
    steps.append({
        "type": "retrieval",
        "index_mode": index_mode,
        "passes": retrieval_passes,
        "total_chunks": len(unique_results),
        "artifact_kinds": artifact_kinds,
    })

    # ── 4. Build citation list ─────────────────────────────────────────────────
    citations: list[dict] = []
    for r in unique_results:
        excerpt = r.chunk.text[:300].replace("\n", " ")
        citations.append({
            "chunk_id": r.chunk.id,
            "kind": r.chunk.kind,
            "source_location": r.chunk.source_location,
            "excerpt": excerpt,
            "score": round(r.score, 4),
        })

    # ── 5. Structural enrichment ───────────────────────────────────────────────
    structural_blocks: list[str] = []
    gi = load_graph_index(run_dir)
    if gi is not None:
        mentioned = gi.resolve_node_mentions(question)
        top_text = " ".join(r.chunk.text for r in unique_results[:3])
        mentioned_in_ctx = gi.resolve_node_mentions(top_text)
        node_ids = list(dict.fromkeys(mentioned + mentioned_in_ctx))[:4]

        for nid in node_ids:
            facts = gi.structural_facts(nid)
            if not facts.get("is_unknown"):
                block = (
                    f"Structural facts for {facts['name']} ({nid}):\n"
                    f"  Type: {facts['type']}\n"
                    f"  Fan-in (callers): {facts['fan_in']}\n"
                    f"  Fan-out (callees): {facts['fan_out']}\n"
                    f"  Member count: {facts['member_count']}\n"
                    f"  In a dependency cycle: {facts['in_cycle']}\n"
                )
                if facts["callers"]:
                    block += f"  Called by: {', '.join(facts['callers'][:6])}\n"
                if facts["in_cycle"] and facts["cycle_peers"]:
                    block += f"  Cycle peers: {', '.join(facts['cycle_peers'][:4])}\n"
                structural_blocks.append(block.strip())

    # ── 6. SKIP_LLM — extractive answer ───────────────────────────────────────
    if settings.skip_llm:
        top_texts = "\n\n---\n\n".join(r.chunk.text for r in unique_results[:3])
        structural = "\n\n".join(structural_blocks) if structural_blocks else ""
        extractive = (structural + "\n\n" + top_texts) if structural else top_texts
        return {
            "answer": f"[Extractive — top chunks]\n\n{extractive}",
            "citations": citations,
            "mode": "extractive",
            "steps": steps,
        }

    # ── 7. Build grounded context string ──────────────────────────────────────
    context_parts: list[str] = []
    total_chars = 0
    for r in unique_results:
        snippet = f"[{r.chunk.id}]\n{r.chunk.text}"
        if r.chunk.source_location:
            snippet += f"\n(location: {r.chunk.source_location})"
        if total_chars + len(snippet) > _MAX_CONTEXT_CHARS:
            break
        context_parts.append(snippet)
        total_chars += len(snippet)

    context_str = "\n\n---\n\n".join(context_parts)
    structural_str = (
        "\n\nStructural graph facts:\n\n" + "\n\n".join(structural_blocks)
        if structural_blocks else ""
    )

    steps.append({
        "type": "context",
        "chars_used": total_chars,
        "chunks_included": len(context_parts),
        "structural_nodes": len(structural_blocks),
        "description": (
            f"Reasoning over {len(context_parts)} chunks "
            f"({', '.join(artifact_kinds)}) "
            + (f"+ {len(structural_blocks)} graph node(s)" if structural_blocks else "")
        ),
    })

    # ── 8. Assemble messages with history ─────────────────────────────────────
    prior_messages: list[dict] = []
    if history:
        # Cap at last N turns (each turn = user + assistant message)
        trimmed = history[-(2 * _MAX_HISTORY_TURNS):]
        for msg in trimmed:
            role = msg.get("role", "")
            content = (msg.get("content") or "").strip()
            if role in ("user", "assistant") and content:
                prior_messages.append({"role": role, "content": content})

    user_prompt = (
        f"Context:\n\n{context_str}{structural_str}\n\n"
        "---\n\n"
        f"Question: {question}\n\n"
        "Answer (reason step by step through the evidence, then give your grounded answer "
        "with [chunk_id] citations):"
    )

    messages: list[dict] = (
        [{"role": "system", "content": _SYSTEM_PROMPT}]
        + prior_messages
        + [{"role": "user", "content": user_prompt}]
    )

    # ── 9. LLM call ───────────────────────────────────────────────────────────
    try:
        import litellm

        model_name = settings.model_reasoning
        call_kwargs: dict[str, Any] = {"messages": messages, "max_tokens": _MAX_TOKENS}

        if settings.anthropic_api_key and model_name.startswith("claude-"):
            call_kwargs["model"] = f"anthropic/{model_name}"
            call_kwargs["api_key"] = settings.anthropic_api_key
        else:
            call_kwargs["model"] = f"openai/{model_name}"
            call_kwargs["api_base"] = settings.llm_base_url
            call_kwargs["api_key"] = settings.llm_api_key
            log.info(
                "chat.answer: model=%s api_base=%s api_key_configured=%s",
                model_name, settings.llm_base_url, bool(settings.llm_api_key),
            )

        resp = litellm.completion(**call_kwargs)
        log.info(
            "chat.answer: POST %s -> 200 OK",
            call_kwargs.get("api_base", "https://api.anthropic.com"),
        )
        answer_text = (resp.choices[0].message.content or "").strip()

        steps.append({"type": "answer", "tokens": _MAX_TOKENS})
        return {"answer": answer_text, "citations": citations, "mode": "generative", "steps": steps}

    except Exception as exc:
        log.warning("chat.answer: LLM call failed (%s) — extractive fallback", exc)
        top_texts = "\n\n---\n\n".join(r.chunk.text for r in unique_results[:3])
        structural = "\n\n".join(structural_blocks) if structural_blocks else ""
        extractive = (structural + "\n\n" + top_texts) if structural else top_texts
        return {
            "answer": f"[LLM unavailable — top relevant chunks]\n\n{extractive}",
            "citations": citations,
            "mode": "extractive",
            "steps": steps,
            "error": str(exc),
        }
