# AppsFlow — TypeScript rebuild with Micro-Cosmos: run findings + improvement plan

**Context**: `examples/appsflow` is a real TypeScript codebase being run through Micro-Cosmos
for an in-place modernisation (source language = target language = TypeScript/Node). Run
`1212e54b` (2026-08-14, Deterministic mode, auto-approve-gates on) was inspected via `/explain-run`
and directly against its on-disk artifacts. This file combines what that run revealed with a
concrete plan for improving Observer/Cartographer/Architect's TypeScript support, since AppsFlow
is exactly the kind of TypeScript-source, TypeScript/Node-target project this plan targets.

Plain-English versions of the run explanation also live at
`runs/1212e54b/reports/plain-english-summary.md` and
`runs/1212e54b/reports/three-slide-summary.md`.

---

## Part 1 — What run `1212e54b` revealed

### Run shape
- Source: `examples/appsflow`, TypeScript → TypeScript, Deterministic mode, `auto_approve_gates`
  on (reviewer: Joao Cerqueira).
- Observer produced a large IR graph: 2,577 nodes / 2,817 edges.
- Security scan: 80 findings, all `MEDIUM` severity, `source_architecture_risk: MEDIUM`.
- Missing from disk: `bounded_context_map.json`, `seam.json`, `work_streams.json`, `tnas.json`,
  `feature_specs.json` — Cartographer/Architect/Feature-Specifier outputs never landed.
- Present but unexpected: `skeptical_review.json`, `test_review.json`, `functional_review.json` —
  files that normally only appear deep in the per-seam TDD loop, well after the missing files
  above would need to already exist.

### Finding 1 (confirmed, real, worth fixing) — macOS zip artifacts pollute the IR graph
535 of the 2,577 IR-graph nodes (~21%) come from `examples/appsflow/__MACOSX/` — the hidden
bookkeeping folder macOS's Finder "Compress" feature adds to a zip automatically. Observer parsed
these `._*` AppleDouble sidecar files as if they were real TypeScript source
(`source_location: examples/appsflow/__MACOSX/appsflow/._diverse-sample-e2e.test.ts:1`), producing
meaningless graph nodes like `.Next.config` and `.Drizzle.config`. This isn't TypeScript-specific
in principle, but it's the most visible on a project zipped on a Mac — exactly AppsFlow's case, and
plausibly common for any externally-sourced TypeScript/Node project sent in as a zip.

**Fix**: skip `__MACOSX/` directories and any file whose basename starts with `._` during source
file discovery (wherever Observer enumerates files, before language-extension filtering). Small,
safe, high-value — this should be prioritized ahead of the deeper TypeScript-parsing work below
since it silently inflates node counts and pollutes downstream Cartographer/Architect input for
*any* zip-uploaded project, not just AppsFlow.

### Finding 2 (confirmed, real, a regression from earlier this session) — misleading review-failure wording in Deterministic mode
`run_phase()` (`pipeline.py`) calls `_direct_tool_fallback(phase, state)` unconditionally whenever
`skip_llm=True`, for *every* phase including `SKEPTICAL_REVIEW`/`TEST_REVIEW`/`FUNCTIONAL_REVIEW`.
Earlier this session, `_direct_tool_fallback` gained real fallback cases for those three phases
(fixing a genuine LLM-mode bug: a crashed reviewer agent could let a stale prior-seam review
silently pass the TDD loop). The fallback text says *"agent did not submit a review (crashed or
returned no tool call)"* — accurate for the LLM-mode crash case it was built for, but now also
fires unconditionally in Deterministic mode, where there was never an agent or a crash — the
review simply doesn't run in that mode by design. The `passed: false` outcome is still correct
either way; only the wording is misleading. This run's `skeptical_review.json`/`test_review.json`/
`functional_review.json` show exactly this: the "crashed" framing, in a run that never made an LLM
call at all.

**Fix (not yet made — flagging for a decision, not applying unprompted)**: give
`_direct_tool_fallback`'s three review branches Deterministic-mode-aware wording (e.g. "Deterministic
mode does not run a code review for this phase" instead of "did not submit a review (crashed...)"),
or gate the fallback differently for `skip_llm=True` vs. a genuine LLM-crash recovery path.

### Finding 3 (observed, not fully explained) — missing mid-pipeline artifacts alongside present review files
Cartographer/Architect/Feature-Specifier's JSON outputs are absent, yet files that should only be
produced *after* those succeed are present. This is internally inconsistent and wasn't fully
root-caused within the time available here. **Recommended next step**: run the `/debug-run 1212e54b`
diagnostic (built exactly for this kind of artifact-inconsistency triage) before treating this
run's TDD-loop-stage outputs as meaningful, or start a fresh run against a `__MACOSX`-cleaned copy
of `examples/appsflow` and compare.

---

## Part 2 — Effort estimate: improving Observer/Cartographer/Architect for TypeScript (source) → TypeScript/Node (target)

Scope: TypeScript as the *source* language specifically, where the target is always
TypeScript/Node (in-place modernisation) rather than translation into a different language.
Yardstick: this session's comparably-scoped features (CQRS-framework-detection ≈ 556 lines
incl. tests/docs ≈ 1 day; the DAB→ADF scheduler-registry generalization, similarly sized, ≈ 1 day).

### Current-state summary

| Phase | File(s) | Current TypeScript depth |
|---|---|---|
| **Observer** | `observer_tools.py` (`_parse_typescript_file`, line ~858) | Regex/brace-depth parser shared with plain JS — no tree-sitter grammar (Java has one, gated on `_TS_AVAILABLE`). Captures classes, interfaces, functions/methods, JSDoc summaries reasonably well. **No decorator parsing** (`@Controller`/`@Injectable`/`@Module` explicitly skipped, not extracted — blocks NestJS route/DI detection). Import/require extraction is a naive filename-stem match — no relative-path resolution, no `package.json` awareness, nothing like Java's import-map used for Axon detection. No Node-framework-detection module (Express/NestJS/Fastify) analogous to `framework_tools.py`'s CQRS registry. |
| **Cartographer** | `cartographer_tools.py` | ~13 hardcoded path-substring rules (`/nestjs/`, `vite.config`, `timesheet`, `phase-assignment`, etc.) — bespoke to one past client codebase, not a generalized TS/Node heuristic. No `package.json` workspaces/monorepo boundary detection. No generic TS layer-classifier fallback (analogous to `_classify_java_layer`/`_classify_csharp_layer`/`_classify_cobol_layer`) — an unmatched TS project falls straight to the fully generic classifier. |
| **Architect** | `architect_tools.py`, `micro_cosmos/fitness/__init__.py` | `_MIGRATION_RISK` reasons are hardcoded for a TS→Java narrative ("Java HTTP client semantics") — nonsensical when target is also TypeScript. `build_canonical_suite()` returns the same 5 language-agnostic fitness rules regardless of target language; no TS-specific rule (no `any`-usage ban, no strict-null-check gate, no discriminated-union/exhaustiveness check). |

`scheduler_tools.py`/`framework_tools.py` have zero Node/TS signatures today — both are
Databricks/ADF and JVM/.NET-CQRS oriented; nothing reusable there yet.

### Prioritized gaps

0. **(New, from this run)** Skip `__MACOSX/`/`._*` zip artifacts during file discovery — cheap,
   affects every zip-uploaded project, not TS-specific, do this first.
1. **Observer** — no decorator-aware extraction (blocks NestJS controller/route/DI detection); no
   Node framework registry; naive import resolution (no real module graph, no monorepo package
   boundaries).
2. **Cartographer** — path rules are one-client bespoke, not generic; no `package.json`
   workspaces/monorepo detection; no generic TS layer-classifier fallback.
3. **Architect** — risk table assumes a non-TS target; no TS-specific fitness functions.

### Effort estimate

| Item | Size | Estimate |
|---|---|---|
| Finding 0 — skip zip junk during file discovery | XS | a few hours |
| Finding 2 — Deterministic-mode-aware review-fallback wording | XS | under an hour |
| **Observer**: generic decorator regex + route/DI extraction, Node framework registry (mirroring `framework_tools.py`'s pattern), `package.json`-aware import resolution | M | 2–3 days |
| **Observer, stretch**: a *real* tree-sitter TypeScript parser (parity with Java's) — new grammar dependency, type-vs-value disambiguation, JSX handling | L/XL | 1–2 weeks — biggest unknown/risk in this whole plan |
| **Cartographer**: generalize path rules + monorepo/workspace detection + generic TS layer-classifier fallback | M | 1–2 days |
| **Architect**: target-language-conditional risk reasons + 3–5 TS-specific fitness rules | S | 0.5–1 day |

**Total: roughly 1 week for regex-based parity with Java's current depth (Findings 0/2 included);
add 1–2 weeks on top only if a real AST-based TypeScript parser is required** rather than extending
the existing regex approach.

---

## Part 3 — Recommended order of work

1. Fix Finding 0 (zip junk filtering) — immediate, cheap, benefits every project type.
2. Decide on Finding 2's wording fix and apply it — cheap, avoids future confusion reading
   Deterministic-mode runs.
3. Re-run AppsFlow (or a `__MACOSX`-cleaned copy) and use `/debug-run 1212e54b`-style diagnosis on
   the new run to confirm Cartographer/Architect/Feature-Specifier actually complete end-to-end
   before investing in deeper TypeScript-specific parsing improvements.
4. Observer decorator/framework-detection work (M, 2–3 days) — highest leverage of the three phase
   improvements, since NestJS/Express detection unlocks better Cartographer boundaries too.
5. Cartographer generalization (M, 1–2 days).
6. Architect TS-specific fitness rules + risk-reason fix (S, 0.5–1 day).
7. Only after the above: evaluate whether a real tree-sitter TypeScript parser is actually needed,
   or whether the regex approach (once decorator-aware) is good enough in practice.
