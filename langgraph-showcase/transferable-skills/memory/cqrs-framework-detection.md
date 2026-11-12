---
name: cqrs-framework-detection
description: Broadened CQRS/event-sourcing framework detection to 6 named frameworks (Axon, Eventuate, Lagom, MediatR, NServiceBus, Wolverine); found and fixed a silently-regressed Axon-specific parser along the way (2026-08-13)
metadata:
  type: project
---

Joao asked to broaden CQRS-pattern detection to explicitly recognize named CQRS/event-sourcing
frameworks — AxonFramework and Ballerina were his examples, plus "other CQRS Java or .NET
frameworks." Confirmed via `AskUserQuestion` before implementing: a real deterministic
manifest+annotation scan, not just LLM-prompt text; and the exact framework list — Java: Axon,
Eventuate, Lagom; .NET: MediatR, NServiceBus, Wolverine. Ballerina and Brighter were considered
and explicitly dropped (Ballerina isn't itself a CQRS framework and has zero footprint anywhere in
this repo; Brighter wasn't part of the confirmed scope).

## "Expand it there" was literally true — a real regression, not a vague request

Before designing anything new, `git log -S is_axon_aggregate -- micro_cosmos/tools/observer_tools.py`
showed `_parse_java_file` and `scan_performance_anti_patterns` *used to* have real Axon-specific
detection (`is_axon_aggregate`, `handler_type`, `handles_payload`, plus two derived findings
`MISSING_AGGREGATE_IDENTIFIER`/`BYPASS_COMMAND_GATEWAY`) — added in one commit, then silently
deleted by a later merge that replaced large parts of the file with an older version that never
had it. `tests/test_java_axon.py` (added alongside the original feature) was never updated and
still asserted the old behavior — confirmed live by copying it into the running container and
running it against `HEAD` before touching anything: all 3 tests failed. Restoring it became part
of this change, not a separate ticket, since it was the exact mechanism the user's "expand it
there" phrasing pointed at.

**Lesson for future "extend X to also cover Y" requests**: if the user's phrasing implies an
existing location that a grep doesn't find, check git history before assuming the phrasing is just
imprecise — `git log -S <distinctive_attribute_name>` on the file you'd expect to hold it. A
silently-regressed merge is a real, recurring failure mode in this codebase (this is the second
time in this session's memory it's mattered structurally — see [[project_debrand_generic_integration_categories]]
for a different kind of "hidden in a default template" gap found the same way, via audit-before-plan).

## Two-tier detection design, matched to actual evidence

1. **Manifest coordinates (all 6 frameworks)** — reliable, unambiguous: a declared dependency on
   `org.axonframework`/`io.eventuate`/`com.lightbend.lagom` (Java) or a `PackageReference` for
   `MediatR`/`NServiceBus.Core`/`WolverineFx` (.NET) means the codebase uses that framework, full
   stop. New `micro_cosmos/tools/framework_tools.py::detect_cqrs_frameworks()` reuses the existing
   `micro_cosmos/tools/security_tools.py::read_manifest_files()` — already discovers
   `pom.xml`/`build.gradle`/`*.csproj` etc. and returns raw content; no need to duplicate manifest
   discovery.
2. **Source annotations (Axon only)** — the only framework with a real fixture
   (`examples/java-axonframework-modern-app`), so it's the only one where annotation-level
   heuristics are actually verifiable rather than speculative guesses. Speculatively inventing
   annotation regexes for Eventuate/Lagom/MediatR/NServiceBus/Wolverine (frameworks with zero
   fixtures in this repo) would have been unverifiable — the manifest tier alone correctly answers
   "does this codebase use framework X" for those without guessing at code-shape.

Both tiers feed one new compact field on `ir_graph.json` — `cqrs_framework_hints` — via a new
post-OBSERVER hook in `micro_cosmos/orchestration/pipeline.py`, deliberately mirroring the existing
`security_hints` precedent exactly: same phase, same artifact, same isolated try/except block.
Wired into the Architect LLM prompt (`micro_cosmos/agents/architect.py`) the same way
`security_hints` is: `{ir_graph.security_hints?}` → `{ir_graph.cqrs_framework_hints.detected_frameworks?}`.

**Reusable pattern**: any new deterministic pre-scan that should inform the Architect (or any
later-phase agent) without adding a new pipeline phase should follow this exact shape — a
post-OBSERVER hook writing a compact field onto `ir_graph.json`, consumed via Jinja-style
`{ir_graph.<field>?}` interpolation in the consuming agent's prompt. Don't invent a new mechanism
per feature.

## Three real bugs found and fixed while restoring `_parse_java_file` — all surfaced by the live check, not by unit tests alone

The unit test (`tests/test_java_axon.py`, synthetic inline Java) passed after the first round of
fixes, but running the *real* fixture (`examples/java-axonframework-modern-app/.../property-allocation`)
through `observe_source_estate` surfaced three more gaps the synthetic test didn't exercise:

1. **False-positive risk in the original historical design**: the old code matched bare annotation
   names (`"CommandHandler" in current_annotations`) with no check that the annotation actually
   resolved to `org.axonframework.*` — a same-named annotation from an unrelated library would have
   been mistaken for Axon. Fixed by building a per-file import map (`_java_import_map()`) and
   gating detection on the annotation's import actually starting with `org.axonframework.`.
2. **Constructors were never matched at all** by the current regex-based `_parse_java_file`
   (`_JAVA_METHOD_RE` requires a return-type token before the method name; constructors have none).
   This matters for Axon specifically because the aggregate-creation command handler is
   conventionally the constructor (`@CommandHandler public Portfolio(CreatePortfolio cmd) {...}`).
   Fixed with a dedicated `_JAVA_CTOR_RE`, filtered to only fire when the declared name equals the
   enclosing class name (reusing the existing `_owner_class()` helper) — this specifically avoids
   turning every `Word(args) {` control-flow-shaped line into a false constructor match.
3. **Package-private methods (no access modifier) were never matched either** — Axon's conventional
   style for `@EventSourcingHandler` methods (`void on(PortfolioCreated e) { ... }`, no `public`/
   `private`). The obvious fix (making `_JAVA_METHOD_RE`'s modifier requirement `*` instead of `+`)
   would have introduced a real false-positive: an anonymous inner class instantiation like
   `new Runnable() {` would then parse as a method named "Runnable" with return type "new" — Java's
   `new` keyword isn't itself in the modifier list, so with modifiers optional the type-capture
   group happily consumes it instead. **Fix**: a separate `_JAVA_PKG_METHOD_RE` that requires *at
   least one* annotation line (not optional — `_JAVA_ANN_REQUIRED`, one-or-more, vs. the normal
   `_JAVA_ANN` zero-or-more) plus a negative lookahead against the modifier keywords, so it only
   ever matches "annotated, no access modifier" — never bare unannotated code, and never overlaps
   with `_JAVA_METHOD_RE`'s matches.

**Lesson**: a synthetic unit-test fixture (hand-written, matching exactly what the historical
assertions expected) can pass while missing real gaps that only show up against an actual,
organically-written codebase. Always run the live check against the real example directory before
calling a parser restoration complete — it's what caught both #2 and #3 here; the unit test alone
would have shipped a parser that silently dropped every constructor and every package-private
handler in the real fixture.

## Explicitly descoped: `derive_tnas()`'s deterministic fallback

`micro_cosmos/tools/architect_tools.py::derive_tnas()` was *not* made framework-aware. It's a plain
function called from a module-level `_direct_tool_fallback(phase, state)` in `pipeline.py` with no
artifact-loading access, and every `context_decisions` field it sets today
(`data_store`, `execution_model`, `consistency_model`, `service_granularity`) is a hardcoded
literal regardless of context — there's no established convention for what a framework-aware
version should change output-shape-wise, and inventing one would have been a speculative addition
beyond what was asked. Flagged as a known limitation rather than silently skipped.

## Files changed

| File | Change |
|---|---|
| `micro_cosmos/tools/observer_tools.py` | Restored + hardened Axon annotation detection; restored `scan_performance_anti_patterns`'s Axon block; restored SQL `CREATE TABLE` parsing; new `_JAVA_CTOR_RE`/`_JAVA_PKG_METHOD_RE` |
| `micro_cosmos/tools/framework_tools.py` | New file — `detect_cqrs_frameworks()` |
| `micro_cosmos/orchestration/pipeline.py` | New post-OBSERVER hook for `cqrs_framework_hints` |
| `micro_cosmos/agents/architect.py` | New prompt interpolation + guidance |
| `tests/test_java_axon.py` | Fixed; added false-positive regression test |
| `tests/test_cqrs_framework_detection.py` | New file — 8 tests |

## Follow-up (2026-08-19): detection existed, but nothing consumed it for seams

`cqrs_framework_hints` fed only the Architect prompt — seam detection never looked at the Axon
attributes this work restored, so an event-sourced estate scored lowest per LOC of three Java apps.
Fixed by a decoupled message-flow registry plus saga-annotation parsing. See
[[cqrs-message-flow-seams]].
