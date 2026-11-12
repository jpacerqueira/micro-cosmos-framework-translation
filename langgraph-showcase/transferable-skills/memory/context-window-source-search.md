---
name: context-window-source-search
description: Fixed a real ContextWindowExceededError incident in the TDD writer loop — five compounding root causes, only one of which a FAISS vector store actually fixes; new source-code search tool built on the existing (previously ASK-tab-only) retrieval infrastructure (2026-08-10)
metadata:
  type: project
---

Real production incident: `test_reviewer_agent` crashed with `litellm.
ContextWindowExceededError` (230,513+ input tokens against a 230,512-token model context
window, per `gcloud-run-setup-vllm.txt`'s deployed vLLM config) mid-way through the TDD writer
loop (Code Writer → Skeptical/Test/Functional Review, per seam, up to `MAX_TDD_ITERATIONS`
times). Joao asked for a strategy using the app's existing FAISS/vector-store infrastructure
(previously powering only the ASK tab) so this class of error is structurally avoided going
forward — not a band-aid.

## Five compounding root causes, only fixing all of them was "effective"

Two rounds of research (tracing exactly what accumulates into the TDD loop's prompts, then
inventorying the existing `micro_cosmos/retrieval/` FAISS infrastructure) found the vector store alone
would NOT have been enough — four other leaks needed closing too:

1. **`micro_cosmos/tools/source_tools.py::list_source_files`'s `seam_name` parameter was dead code.**
   Every agent instruction (`code_writer.py`, `functional_reviewer.py`) claimed "the seam_name
   filter returns only files related to the current seam" — the function body never referenced
   the parameter at all. It unconditionally dumped every source file matching the target
   language, truncated per-file at 10,000 chars, up to a 120,000-char total budget, **every
   single TDD iteration**. This was the single biggest token source, and a real, independently
   fixable bug regardless of any vector-store work.
2. **`_run_tdd_loop_for_seam()` (`driver.py`) never reset the ADK session between a Functional
   Review finishing and the next Code Writer iteration.** Each iteration already reset before
   its 3 review phases (confirmed correct), but the wraparound from iteration N's Functional
   Review back to iteration N+1's Code Writer had no reset — so Code Writer inherited the full
   leftover tool-call history from the previous iteration's reviewer, compounding every
   iteration. One `await orch.reset_session()` call, guarded to skip only iteration 1.
3. **`submit_seam_translation`'s tool response re-embedded the entire merged file list** (full
   content, LLM-generated + scaffolding) back into context right as Code Writer finished its
   turn. Verified nothing downstream reads this in-context copy before trimming it — `pipeline.py`
   prefers the disk-written `seam_result.json` over session state, and `read_generated_files`
   (the actual re-read mechanism) reads from disk too. Kept `_write_seam_result` writing the full
   dict to disk unchanged; the LLM-facing return value is now a small manifest.
4. **No client-side token/size guard existed anywhere.** `Settings.model_context_length` was only
   ever passed to the inference engine as a KV-cache allocation hint (`extra_body={"num_ctx":
   ...}`), never used to warn or cap client-side. Added a best-effort pre-flight warning in
   `run_phase()` — deliberately just a diagnostic (it can only see `session.state`'s size, not the
   in-flight turn's own tool-call growth), not a hard cap.
5. **The FAISS work** — see below.

## What the existing FAISS infrastructure could and couldn't do

`micro_cosmos/retrieval/index.py`'s `RunIndex` (three-tier fallback: FAISS → numpy vector → lexical
Jaccard token-overlap), `embedder.py`, and `graph_index.py` were fully generic and reusable
as-is — but `micro_cosmos/retrieval/chunks.py` **only ever chunked pipeline JSON artifacts and
generated reports** (IR nodes' semantic summaries, seams, bounded contexts, security findings,
etc.) for the ASK tab's Q&A use case. Nothing chunked the actual source code being translated.
Building a source-code index was genuinely new work, not a rewire of something that already did
this.

**New `micro_cosmos/retrieval/source_chunks.py`** — chunks source files by reusing Observer's
already-computed IR node boundaries (`ir_graph.json`'s per-node `source_location: "file:line"`)
rather than adding a tree-sitter/AST dependency — one chunk per IR node, spanning to the next
node's start line or EOF, with a sliding-window fallback for files with zero IR nodes (config
files, unparsed languages).

**New `micro_cosmos/retrieval/source_index.py`** — builds/persists this once per run to a **separate**
sidecar, `runs/<id>/source_vectors/` (not the ASK tab's `runs/<id>/vectors/`), since the source
tree is immutable for the run's lifetime — no staleness watcher needed at all, deliberately
simpler than extending the ASK-tab index's mtime-based staleness check to cover a source tree.
Reuses `RunIndex`'s embed/search/persist machinery unchanged: `index.py` was lightly refactored
to extract `embed_and_persist()`/`load_from_sidecar()` as shared, chunk-list-generic helpers, with
`build_index()`/`load_index()` (the ASK tab's real API) becoming thin wrappers around them — the
full test suite confirmed zero behavior change to the ASK tab from this refactor.

**New `micro_cosmos/tools/source_search_tools.py::search_relevant_source(seam_name, query, ...)`** —
modeled on the existing `query_spec_docs` tool's calling convention. Searches the source index,
then narrows results to the seam's structurally-relevant files (reusing fix #1's resolution
logic) when that resolves. Registered on **Code Writer and Functional Reviewer only** — verified
Skeptical/Test Reviewer don't read source today and shouldn't gain a new capability as a side
effect of this fix. Their instructions now prefer `search_relevant_source` first, falling back to
`list_source_files`/`read_source_file` (kept, not removed) only if fewer than 2 results come back
or a specific full file is genuinely needed.

## Operational reality, designed for explicitly, not glossed over

`Settings.embedding_model`/`embedding_base_url` default to empty and `docker-compose.yml` never
sets them — so `build_embedder()` returns `None` and the whole system runs in `RunIndex`'s
lexical (Jaccard token-overlap) fallback mode **out of the box, even in LLM mode**. This is
exactly what got verified in this session (no local embedding model configured here), and it's a
reasonable retriever for this use case regardless — queries are things like "fraud score
calculation logic," and token overlap on code identifiers works fine for that. Real FAISS/
embedding-mode quality should be checked on the GCP deployment where an embedding model is
actually available; this was an explicit, confirmed-with-Joao scope decision, not an oversight.

## Verification

New `tests/test_source_search.py` (7 tests, no LLM/embedding server needed): seam-scoped vs.
estate-wide `list_source_files` filtering including graceful fallback when a seam can't be
resolved; IR-node-boundary chunking including the sliding-window fallback; `search_relevant_source`
lexical-mode search confirming results are small capped excerpts, never uncapped full files. All
pass. Full suite: 30 passed (up from 23 earlier this session), 1 skipped, same 5 pre-existing
unrelated failures.

Live, via direct `run_full_pipeline()` calls (deterministic mode, `examples/
java-springboot-legacy-app`, the same technique used repeatedly this session): confirmed the
source index builds exactly once right before the seam loop (637 chunks, lexical mode) and is
reused — not rebuilt — on a subsequent `search_relevant_source` call (`meta.json`'s `built_at`
unchanged); confirmed a real seam search returns `scope="seam"` (structural filtering engaged)
with excerpts of a few hundred characters, nothing close to a full file. One debugging dead end
along the way: an early, more elaborate verification script hit an unreproducible
`ModuleNotFoundError` that a simpler script didn't — treated as a quirk of that one script (never
explained, not worth chasing further since the simpler, more targeted scripts all worked
correctly and consistently).

Since reproducing the actual incident (a 230K-token-context model) isn't possible in this dev
environment, full LLM-mode confirmation should happen on the next real GCP deployment run —
watch for `search_relevant_source` result counts/`scope` values in the trace, absence of
`ContextWindowExceededError` in the logs, and a `Source index ready` info event appearing exactly
once per run before the first `seam_started` event.

## Complementary deployment change

Joao separately raised `gcloud-run-setup-vllm.txt`'s `MODEL_CONTEXT_LENGTH` from `230512` to
`256000` — more headroom on top of the code fixes, not instead of them. The fixes address why the
prompt reached that size in the first place; the larger window is margin for whatever
legitimately large content remains (e.g. `search_relevant_source` still falls through to
`read_source_file` for a genuinely large file an agent needs in full).

## Files changed

| File | Change |
|---|---|
| `gcloud-run-setup-vllm.txt` | `MODEL_CONTEXT_LENGTH` raised from `230512` to `256000` |
| `micro_cosmos/orchestration/driver.py` | Session reset between TDD iterations; builds the source index once before the seam loop |
| `micro_cosmos/tools/source_tools.py` | `seam_name` now actually filters `list_source_files` |
| `micro_cosmos/orchestration/pipeline.py` | Wires `source_tools.set_run_dir()`; pre-flight context-size warning |
| `micro_cosmos/tools/coder_tools.py` | `submit_seam_translation` returns a manifest, not full file bodies |
| `micro_cosmos/retrieval/index.py` | Extracted `embed_and_persist()`/`load_from_sidecar()` as reusable helpers |
| `micro_cosmos/retrieval/source_chunks.py` | New — IR-node-boundary source-code chunking |
| `micro_cosmos/retrieval/source_index.py` | New — once-per-run source vector index |
| `micro_cosmos/tools/source_search_tools.py` | New — `search_relevant_source` FunctionTool |
| `micro_cosmos/agents/code_writer.py`, `micro_cosmos/agents/functional_reviewer.py` | Register the new tool; instructions prefer it |
| `tests/test_source_search.py` | New automated regression test |
