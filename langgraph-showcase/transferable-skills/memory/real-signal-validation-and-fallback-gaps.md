---
name: real-signal-validation-and-fallback-gaps
description: 4 real bugs (#53, #54, #57, #58) found running the real pipeline against a real local LLM — presence-only artifact validators miss LLM schema drift, Code Writer crash spirals on plain-text replies, dotted seam identifiers break scaffolding, copied retrieval excerpts pass as implementation (PR #76, 2026-09-09)
metadata:
  type: project
---

All four surfaced from the same source: running the real pipeline against an actual local model
(qwen2.5-coder-7b-instruct-mlx / Granite 3.1 8B via LM Studio) on real estates, not synthetic
fixtures. All four fixes already existed as real, tested code sitting uncommitted on the local
`roadmap/enterprise-modernisation-platform-vision` checkout — extracted and hand-transplanted
onto `main`, same methodology as [[test-agent-sandboxed-execution]]'s Test Agent extraction,
carefully separated from that branch's other entangled work (Semantic Equivalence Agent #49 —
see [[semantic-equivalence-agent]] — and Architecture Compliance tightening #51, neither touched
in this PR).

## BUG-4 (#53) — presence-only artifact validators miss LLM schema drift

`_is_valid_artifact`'s checks verified outer presence/absence-of-bad-values, never that an
LLM-touched artifact still has the *right field names and enum values* everything downstream
depends on. A real run surfaced three cases where a non-empty-but-reinvented shape passed a bare
truthiness check: `fitness_suite` (`{"read_heavy_services": [...]}` instead of
`{"functions": [...]}`), `context_decisions` (keyed `"name"` instead of `"context"`, free-form
prose like "CQRS with event sourcing" instead of the `sync-http`/`async-event` enum), and
`bounded_context_map` (renamed to `context_name`/`nodes`). A 4th, separate gap in the same
investigation: Cartographer classified only 33 of 902 real nodes (3.7%) into any context —
individually well-formed but estate-wide incomplete, which no per-context check catches.

Fixed: `_is_valid_fitness_suite`, `_is_valid_context_decisions`, `_is_valid_bounded_context_map`
(with an 85%-coverage floor via `_bounded_context_map_coverage`) replace the old presence-only
checks, wired into `_is_valid_artifact` plus two new post-Architect merge-back hooks that
re-derive from the deterministic tool when the LLM's output fails validation — the same pattern
already used for `fitness_suite`'s pre-existing (now-tightened) merge-back.

**How to apply going forward:** for anything an LLM-mode agent is expected to preserve/pass
through from a deterministic tool's output, a presence/truthiness check is not enough — verify
actual field names and value domains, and test against a real local model's actual behaviour, not
just a hand-built "correct" fixture.

## BUG-5 (#54) — Code Writer crash spiral

A model replying in plain text instead of calling `submit_seam_translation` left ADK's raw text
sitting in `seam_result.json` (passes `json.loads`, poisons every downstream dict reader), and
that raw parse error fed back into the next retry prompt as if it were a review finding — an
unbounded, confusing loop with no code ever produced. Fixed: a new `CODE_WRITER` case in
`_direct_tool_fallback` reuses `generate_and_verify_seam()` — already documented as existing for
exactly this case, never actually wired in — producing real DDD scaffolding, `passed: False`, and
a plain-English "did not submit" PR body instead of a bare parse error.

## BUG-8 (#57) — dotted seam identifiers break scaffolding

`_pascal()` only split on `"_"`/`"-"`/whitespace; seam ids routinely carry a literal `.`
(`seam_object_prog.PortfolioReadRepository`, mirroring the IR's own dotted node-id convention),
producing invalid identifiers like `ISeamObjectProg.FooUseCase` — confirmed against a real Kotlin
compile error (`Redeclaration: interface ISeamObjectProg`). Since this is the deterministic
`generate_and_verify_seam()` fallback path, it regenerated the identical broken code on every TDD
retry, guaranteeing the seam could never pass. Fixed: split on `.` too.

## BUG-9 (#58) — copied retrieval excerpts pass as implementation

`search_relevant_source`'s own chunk format (`"File: <path>\nFunction/class: <name>\n<code>"`)
was long enough to pass the old `has_impl` check (>100 chars) even when it was a raw, uncompiled
excerpt copied verbatim rather than a real translation. Fixed: `_has_retrieval_artifact()`
detects the exact chunk shape and excludes it from `impl_files`, with a specific warning naming
the affected files; Code Writer's own instructions now explicitly warn against this at the point
`search_relevant_source` is introduced, and RULE 1/2's examples show the target-language-
appropriate extension instead of hardcoded `.java`.

## Verification

12 new tests (7 for the artifact validators, 1 for the `CODE_WRITER` fallback, 3 for the
retrieval-artifact detection, 1 for the dotted-identifier fix). Pure Python logic, no
OS/sandboxing/toolchain surface — verified via local pytest only (271 passed, up from 259, same 6
pre-existing unrelated failures), no container rebuild needed (unlike Test Agent, nothing here is
container-specific).

## A real gap in the extraction process this caught

The three-comma-separated `Closes #53, #54, #57, #58` in the PR body only auto-linked the first
issue (#53) — GitHub does not reliably multi-close from one comma list. The other three (#54,
#57, #58) stayed open despite being merged until closed manually. For any future multi-issue PR:
repeat the keyword (`Closes #53, Closes #54, ...`) or one per line, don't rely on a comma list.

## Files changed

| File | Change |
|---|---|
| `micro_cosmos/orchestration/pipeline.py` | `_is_valid_fitness_suite`, `_is_valid_context_decisions`, `_is_valid_bounded_context_map`, `_bounded_context_map_coverage`, 2 new post-Architect merge-back hooks, `CODE_WRITER` case in `_direct_tool_fallback` |
| `micro_cosmos/tools/coder_tools.py` | `_pascal` splits on `.`, `_has_retrieval_artifact` + `impl_files` exclusion |
| `micro_cosmos/agents/code_writer.py` | Explicit anti-copy-paste instruction, RULE 1/2 target-language-aware examples |
| `tests/test_pipeline.py`, `tests/test_coder_tools.py` (new) | 12 new tests |
