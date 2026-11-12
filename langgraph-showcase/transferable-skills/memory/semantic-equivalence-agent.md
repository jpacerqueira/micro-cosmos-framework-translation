---
name: semantic-equivalence-agent
description: Semantic Equivalence Agent / "Verifier" (#49) — target-side differential testing against Code-Writer-supplied test vectors via a per-language CLI/JSON harness; also completes BUG-10 (#59)'s Functional Review half, which PR #73 never actually shipped despite the issue text implying it did (2026-09-09)
metadata:
  type: project
---

## The gap

`run_equivalence_check` (`coder_tools.py`) was an explicit stub — always returned
`passed: False` regardless of input, called with `test_vectors=[]` always. This made
`submit_seam_translation`'s own internal `passed` field unconditionally `False` for every seam
ever submitted. Harmless in practice — `driver.py`'s real TDD gate reads only the three reviewer
JSONs, never this field (confirmed by tracing the call chain before touching anything) — but
misleading data sitting in every `seam_result.json`, and more importantly: nothing proved a
translated seam actually *behaves* like the source beyond an LLM reviewer's own self-report.

## What was built — Phase 1 scope, deliberately: target-side only

New `micro_cosmos/tools/equivalence_tools.py`. Given optional test vectors
(`{"description", "input", "expected_output"}`, authored by the Code Writer alongside its
implementation and tests — the `test_vectors` param on `submit_seam_translation`), invokes the
seam's own generated code through a small, per-language CLI/JSON harness convention and compares
real output against expected with a numeric-tolerant diff (`_values_match` — bool is not treated
as numeric despite being an `int` subclass in Python; dicts require identical key sets; lists are
deliberately order-*sensitive*, not a multiset match, since an order-insensitive comparison over
lists of dicts is ambiguous about which element corresponds to which and risks masking a real
ordering bug).

Harness convention, one file per target language, each reading one JSON value from stdin and
writing exactly one JSON value to stdout:
- Python → `equivalence_harness.py` (run directly, no build step)
- Java → `src/main/java/EquivalenceHarness.java` (no package declaration, may still `import` the
  seam's own named-package classes; compiled via `mvn`/`gradle compileJava`, invoked as a plain
  class)
- Kotlin → `src/main/kotlin/EquivalenceHarness.kt` (top-level `fun main()` — Kotlin's compiler
  names the facade class `EquivalenceHarnessKt`); invoked via a Gradle **init script**
  (`_KOTLIN_INIT_SCRIPT`, same "inject behavior without touching the project's own build file"
  idiom as `security_tools.py`'s JVM-lockfile restoration) registering a throwaway `JavaExec`
  task that reuses Gradle's own dependency resolution (`sourceSets.main.runtimeClasspath`) so
  `kotlin-stdlib` is on the classpath without the harness code needing to locate it itself.
  `--no-daemon` is used unconditionally — a real local run found Gradle's daemon mode happened to
  forward stdin correctly via `standardInput = System.in`, but that's undocumented daemon-protocol
  behavior that has differed across Gradle versions historically, not something to depend on.
- C# → `EquivalenceHarness.cs` at the project root (a class with `static void Main`). The
  accumulated multi-seam project directory routinely has several `.csproj` files side by side
  (C#'s scaffold names each seam's `.csproj` after the seam, no cross-seam merge like Kotlin's
  single always-merged `build.gradle.kts`) — a bare `dotnet build` in that directory is ambiguous.
  Sidestepped by copying every `.cs` file into an isolated `_equivalence_harness_build/`
  subdirectory alongside one freshly generated Exe-typed `.csproj` that globs them all up.

Other target languages are an honest no-op (`_INVOKERS` has no entry) — vectors present but not
evaluated is reported as `ran: false` with an explicit message, never silently claimed as a pass
or forced to a fail. Same degradation philosophy as `fitness_runner._run_tests` for a missing
toolchain.

True source-vs-target differential execution (running the *original* legacy code on the same
input) is explicitly **not** built — needs a runnable toolchain per source language (e.g.
GnuCOBOL for COBOL, see [[c-source-support-and-gnucobol-golden-master]]), a separate, materially
larger workstream.

## Wiring — mirrors Test Review's established pattern exactly

- `_run_equivalence_prescan` (`pipeline.py`), modeled on `_run_test_execution_prescan`, wired at
  `FUNCTIONAL_REVIEW` in both `skip_llm` and LLM-mode paths, writes `equivalence_result.json`.
- `submit_functional_review` (`coding_loop_tools.py`) reads that file off disk (never as an
  LLM-supplied parameter) and force-corrects `passed` on a real vector mismatch.
- A caught-before-shipping bug: the roadmap branch's own `_run_equivalence_prescan` called
  `run_accumulated_equivalence_check` directly from its `async def`, the exact event-loop-blocking
  pattern found (via review, after the fact) and fixed for `_run_test_execution_prescan` in PR #74
  — `run_accumulated_equivalence_check` also shells out via blocking `subprocess.run` to compile
  and run harnesses. Wrapped in `asyncio.to_thread` proactively this time, before it ever shipped.

## Also completes BUG-10 (#59) — a real gap in my own earlier issue-closing

I had closed #59 based on `_test_execution_hard_failed` existing on `main`, without checking
every item in the issue's own "Fixed" write-up. Item 3 — "`submit_functional_review` now also
folds in `test_execution.json`, independent of the skip-optimization" — was never actually
shipped; PR #73 only wired the `TEST_REVIEW` half. Reopened #59 and shipped the missing half here,
in the same function, same PR, since it's the natural place: `submit_functional_review` now folds
in `test_execution.json` *and* `equivalence_result.json` (severity_counts computed after both
blocks — same ordering lesson as [[review-submit-tool-defaults]]), and a matching
`FUNCTIONAL_REVIEW` hard-fail-skip (reusing `_test_execution_hard_failed`) now also avoids the
Functional Reviewer's LLM turn when a real compile failure already makes the outcome foregone.

**Lesson**: closing an issue on the strength of one matching symbol/function existing is not the
same as verifying every claim in its own fix description. Check each item.

## Verification

24 new tests (`tests/test_equivalence_tools.py`), including real compile-and-run checks against
genuinely buggy and genuinely correct Python/Java/Kotlin/C# implementations — not mocks. 2 of
these (Java, Kotlin) cannot run on a machine with `mvn`/`gradle` binaries present but no linked
JDK (confirmed locally: "Unable to locate a Java Runtime" — a real, distinct environment gap from
the container's `openjdk-21-jdk-headless`), so verified in a real container build instead: all 24
pass there. Full suite inside the container: 301 passed, 1 pre-existing unrelated failure (the
documented `test_adf_scheduler.py` container-vs-host discrepancy), 1 skipped — zero regressions.

## Files changed

| File | Change |
|---|---|
| `micro_cosmos/tools/equivalence_tools.py` | New — harness invocation (Python/Java/Kotlin/C#), tolerant comparison, `run_accumulated_equivalence_check` |
| `micro_cosmos/orchestration/pipeline.py` | `_run_equivalence_prescan` (via `asyncio.to_thread`), `FUNCTIONAL_REVIEW` wiring, hard-fail-skip |
| `micro_cosmos/tools/coding_loop_tools.py` | `submit_functional_review` folds in `test_execution.json` and `equivalence_result.json` |
| `micro_cosmos/tools/coder_tools.py` | `test_vectors` param, `run_equivalence_check` de-stubbed to informational-only |
| `micro_cosmos/agents/code_writer.py` | Optional "EQUIVALENCE HARNESS AND TEST VECTORS" instruction section |
| `tests/test_equivalence_tools.py` | New — 24 tests |
