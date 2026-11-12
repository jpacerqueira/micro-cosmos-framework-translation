---
name: test-agent-sandboxed-execution
description: Test Agent (#48/#52, PR #73) wires real per-language test execution into the TDD gate for the first time via a sandboxed subprocess and a Trivy-prescan-style pipeline hook; plus 5 real bugs found in PR #74's follow-up review (event-loop blocking, dead validation branch, a HOME override that silently defeated its own caching purpose, an overbroad chmod, a dead config entry) (2026-09-08)
metadata:
  type: project
---

## The gap

`fitness_runner.py` could already run a seam's real tests (`_TEST_COMMANDS`, `_run_tests`), but
the result landed in `seam_result.json` and nothing downstream ever read it — `driver.py`'s actual
TDD pass/fail gate only reads the three reviewer JSONs. A seam could pass on LLM/static judgement
alone while its real tests failed. Deterministic mode's `TEST_REVIEW` fallback was also a
hardcoded, unconditional failure, so deterministic-mode runs could never pass the TDD loop at all.

## What PR #73 built

- **Sandboxed subprocess execution** — `_sandbox_env`/`_sandbox_preexec` drop the test-execution
  subprocess (only that subprocess — the app itself still runs as root) to an unprivileged
  `sandboxrunner` UID (`_SANDBOX_UID = 10001`, must match the Dockerfile's `useradd`).
- **`assemble_accumulated_pr_files(run_dir, current_pr_files)`** — resolves the canonical project
  dir the same way `write_output_files` does (`reports/project_dir.txt`), overlays the current
  seam's raw files onto every prior seam's already-materialized output, merging build-file
  collisions (`pom.xml`, `package.json`, etc.) via `writer_tools.py`'s existing
  `_merge_build_file`/`_BUILD_FILE_NAMES`. Real execution needs the whole accumulated project, not
  just the current seam's diff — static spec checks (`_check_spec`) deliberately stay scoped to
  the current seam only; this asymmetry is intentional, not an oversight.
- **`run_accumulated_test_execution(run_dir, target_lang)`** — detects the language and runs its
  real test command (pytest/mvn/gradle/dotnet) against the accumulated project inside the sandbox.
- **`_run_test_execution_prescan`** (`pipeline.py`) — a new pre-phase hook modeled exactly on the
  pre-existing `_run_trivy_prescan`: writes `test_execution.json`, emits `PipelineEvent`s under a
  distinct author, wired into both the `skip_llm` branch and the LLM-mode "pre-phase hooks" branch
  at `TEST_REVIEW`.
- **`submit_test_review()`** now reads `test_execution.json` directly off disk — never as an
  LLM-supplied parameter, the same ADK-footgun avoidance documented in
  [[review-submit-tool-defaults]] (a new *required* tool parameter with no Python default causes
  ADK to silently drop the whole tool call if the model omits it) — and force-corrects its own
  `passed` field, appending a synthetic BLOCKER finding when real execution failed.
- **`_test_execution_hard_failed(run_dir)`** — skips the Test Reviewer's own LLM turn entirely
  when a real compile/test failure already makes the outcome foregone, instead of paying for an
  LLM call whose opinion could never change the result.

`driver.py`'s `_run_tdd_loop_for_seam`/`_passed()` needed **zero changes** — it already derives
its pass/fail purely from the three reviewer JSONs, so a corrected `test_review.json` flows
through automatically. This "fold a real signal into the existing reviewer JSON, force-correct
`passed`, don't add a fourth gate" shape is the established house style for any future
deterministic-check-feeding-an-LLM-reviewer work in this pipeline.

## Same code closes BUG-3 (#52) — no separate "before" version exists

BUG-3's 5 sandboxing bugs were found and fixed *while building this exact code*, not against a
pre-existing implementation:
1. A virtual-memory `RLIMIT_AS` cap that reliably crashed every JVM test run on Linux (the JVM
   reserves large address space up front) while silently no-op'ing on macOS (`setrlimit` is
   effectively unenforced there) — invisible without a real Linux container test.
2. A missing home directory breaking every Maven-based test (`user.home` resolves from the passwd
   database entry for the UID, not `$HOME`) — needs the Dockerfile's `useradd --create-home`.
3. An env var that looked overridden but wasn't (see the HOME/caching bug in PR #74 below).
4. A second module needing its own world-writable temp-dir step.
5. A .NET runtime version drift (see [[c-source-support-and-gnucobol-golden-master]] — the
   `net8.0`-vs-SDK's-own-LTS mismatch was actually caught 4 days earlier, in the container
   toolchain fixes that preceded this).

Deliberately scoped **out** of PR #73: the **Semantic Equivalence Agent (#49)** — it has a hard
Python import dependency on `assemble_accumulated_pr_files` and the sandboxing helpers here, but
its own pipeline wiring on the roadmap branch is entangled with unrelated Documentation Agent
changes, so it needs its own careful extraction as a follow-up now that this sandboxing
infrastructure exists on `main`.

**Verification (PR #73):** real container build (this class of bug was invisible on macOS —
non-negotiable per BUG-3's own history): `sandboxrunner` user created with the correct UID and a
real home directory; full suite 265 passed (11 new) / 1 pre-existing unrelated failure / 1 skipped
— zero regressions.

## PR #74 — 5 real findings from Joao's review, fixed same day

Joao ran a max-effort, 8-agent review pass on #73 and surfaced 12 findings. Each was independently
re-verified against the diff before fixing (never trust a review finding at face value) —
addressed the 5 most severe/clear-cut:

1. **Event-loop blocking.** `_run_test_execution_prescan` (`async def`) called
   `run_accumulated_test_execution()` directly — that function shells out via a blocking
   `subprocess.run()`, so the call froze the *entire app* (every concurrent run's SSE stream, gate
   approvals, HTTP requests) for the subprocess's full duration. The pre-existing Trivy prescan
   has the identical blocking pattern but only fires once per pipeline run; this hook fires on
   every TDD iteration, so the cumulative impact is materially worse. Fixed by wrapping the call
   in `asyncio.to_thread`.
2. **Dead validation.** An `async_context_requires_messaging_evidence` branch in `_check_spec` was
   only reachable via a spec string injected by unrelated Architecture Compliance work on the
   roadmap branch — never actually part of #73's shipped scope, so the branch (and its regex) was
   silently unreachable dead code implying a check ran that never did. This slipped through the
   original "clean file" extraction check because that check only looked for new *function
   definitions*, not new branches added inside an *existing* function — worth remembering for any
   future partial-extraction from the roadmap branch. Removed the branch and the regex.
3. **HOME override defeated its own stated purpose.** `_sandbox_env` unconditionally set `HOME` to
   the same ephemeral per-call `tmp` directory also used for `TMPDIR` — so Maven's
   `~/.m2/repository` cache was wiped on every single call, directly contradicting #73's own PR
   description claim that the cache "persists across seams/TDD iterations." Fixed with a new
   `_SANDBOX_HOME = Path("/home/sandboxrunner")` constant: `HOME` now points there only when
   actually running as root inside the container (`os.getuid() == 0`, the same gating
   `_sandbox_preexec` itself uses) — sandboxrunner's real, persistent home per the Dockerfile's
   `--create-home`. Outside the container (local dev/CI, already unprivileged, no real
   `sandboxrunner` UID/home exists) `HOME` falls back to the old `tmp`-based behaviour rather than
   creating an unrelated real path on whoever's machine this runs on. `TMPDIR` always still uses
   the per-call `tmp` — genuine scratch space is correctly ephemeral, unlike a dependency cache.
4. **Overbroad chmod.** `_make_world_writable` did `os.chmod(path, 0o777)` on the entire
   accumulated tree — readable/writable by every user/process in the container, not just the
   sandbox UID that actually needs it. Changed to `os.chown(path, _SANDBOX_UID, _SANDBOX_UID)`.
5. **Dead `_TEST_COMMANDS["kotlin"]` entry** — `["gradle", "test", "-q"]` could never actually run
   because `_run_tests` always overwrites the Gradle command via `_gradle_cmd(tmp)` (which prefers
   `./gradlew` if present, else `gradle`) before use. Emptied to `[]` with a comment explaining it
   exists only so `.get("kotlin")` doesn't return `None` and hit the "no test command configured"
   skip path.

**Not fixed** (flagged, not silently dropped — lower severity than the five above):
- Duplicated hard-fail predicate between `_test_execution_hard_failed()` and
  `submit_test_review()`'s own inline check.
- `_gradle_cmd()` duplicates `security_tools.py`'s own inline Gradle resolution logic.
- `seam_result.json` double-decode/unwrap parsing duplicated a 3rd+ time across the codebase.
- `project_dir.txt` resolution duplicates `writer_tools.py`'s own, but silently drops its
  fallback.
- Two "plausible, worth a second look" items never investigated: `preexec_fn`-based privilege drop
  forking from a process with executor threads (CPython docs call this unsafe in general); no
  per-seam ownership check on `seam_result.json` (a stale prior seam's output could in principle
  pass real-execution gating). Kotlin's test branch is also missing the "build file doesn't exist
  yet" skip guard the Java branch has.

**Verification (PR #74):** real container build: full suite 265 passed / 1 pre-existing unrelated
failure / 1 skipped — zero regressions. Directly confirmed as root inside the container that
`_sandbox_env` now resolves `HOME` to `/home/sandboxrunner` while `TMPDIR` stays the ephemeral
per-call directory.

## Files changed

| File | Change |
|---|---|
| `Dockerfile` | `useradd --create-home --uid 10001 sandboxrunner` |
| `micro_cosmos/orchestration/pipeline.py` | `_test_execution_hard_failed`, `_run_test_execution_prescan` (wired via `asyncio.to_thread`) |
| `micro_cosmos/tools/coding_loop_tools.py` | `submit_test_review` reads `test_execution.json` off disk, force-corrects `passed` |
| `micro_cosmos/tools/fitness_runner.py` | `_sandbox_env`/`_sandbox_preexec`/`_make_world_writable`, `_SANDBOX_HOME`, `assemble_accumulated_pr_files`, `run_accumulated_test_execution`, dead-branch/dead-entry removal |
| `tests/test_review_submit_defaults.py`, `tests/test_tools.py` | New/extended coverage |
