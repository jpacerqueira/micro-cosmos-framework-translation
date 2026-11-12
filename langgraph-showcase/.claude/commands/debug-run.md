# Debug a Micro-Cosmos run

Analyze the logs and state for a specific run to identify failures.

## Steps

1. Read `runs/$ARGUMENTS/` — check which JSON artifacts exist and which are missing
2. Read the run's diagnostics: `runs/$ARGUMENTS/diagnostics.json` if present
3. Check `runs/$ARGUMENTS/skeptical_review.json`, `test_review.json`, `functional_review.json` for review failures
4. Read `micro_cosmos/orchestration/pipeline.py` lines 260-280 to understand phase ordering
5. Cross-reference the phase that last completed against the artifact that is missing

Common failure patterns:
- `seam_result.json` missing: Code Writer crashed or LLM omitted `submit_seam_translation`
- `functional_review.json` missing / `run_dir=None`: reviewer received null run_dir — `set_run_dir` in `pipeline.py` only covers CODE_WRITER; reviewer phases have no fallback (known open issue, fix was reverted 2026-06-30)
- "Event from unknown agent" repeated: session history contamination — `reset_session()` is NOT currently called before reviewers in `driver.py` (known open issue, fix was reverted 2026-06-30)
- Tool not found on wrong agent: LLM cross-agent hallucination from shared session history — downstream of the session contamination above

ADK tool validation patterns:
- Trace shows `Invoking <tool>() failed as the following mandatory input parameters are not present` → ADK rejected the call because the LLM omitted a required param. Fix: add a Python default value (`= ""` / `= None`) to the function signature in the tool file. ADK treats any parameter without a default as mandatory and will refuse the call if missing.
- Affected tool: `submit_security_findings` in `micro_cosmos/tools/security_tools.py` — `scope_summary` and `source_architecture_risk` need defaults.

HTML report empty/blank patterns:
- `architecture-decisions.html` empty OR `fitness-stubs.html` empty: `tnas.fitness_suite` schema mismatch. LLM mode produces a named-dimension object (`{ "cohesion_within_context": "Medium. …" }`); deterministic mode produces `{ "functions": [{id, name, …}], "target_language": "…" }`. Generator scripts use `_FITNESS_META` exclusion to handle both. If the report is blank, check which format the run's `tnas.json` uses and whether the generator is reading the right path.
- `generate_synthesis.js` exits with `ERROR: TABLE 5 missing`: TABLE 5 (Mutual Call Pairs) was only emitted when circular deps exist. Now always emits — but only if running the patched version. If unpatched, all clean codebases will fail.

Trivy scan patterns:
- `trivy_report.json`/`trivy_output_report.json` looks empty or thin for a
  Gradle-based Java/Kotlin run: expected unless the image actually has a
  JDK + Gradle CLI installed — Trivy does not read `build.gradle`/`.kts`
  directly, only `*.gradle.lockfile`, and `_maybe_restore_jvm_lockfile()`
  in `micro_cosmos/tools/security_tools.py` needs `gradle`/`java` on PATH to
  generate one. Check the container has them (`gradle --version`,
  `java --version`) before assuming the Python logic is broken.
- Same pattern for C# output: thin `trivy_output_report.json` for a C#
  run means check `dotnet --version` in the container —
  `_maybe_restore_dotnet_lockfile()` needs the .NET SDK to generate
  `packages.lock.json`.
- Java/Maven (`pom.xml`) output looking incomplete is **not** a bug to
  chase — no active fix exists for Trivy's unresolved-version-property gap
  there, it's a documented limitation. See
  `transferable-skills/memory/trivy-security-scanning.md`.

Deterministic-mode `security_report.json` empty patterns:
- `security_report.json` shows "0 candidate findings across 0 file(s)" for
  a Deterministic-mode run: this is a **separate scanner** from Trivy —
  `scan_source_for_security()` in `micro_cosmos/tools/security_tools.py`, a
  regex-based CVE placeholder used when `skip_llm=true`. Don't confuse
  the two: Trivy's empty-scan causes above (missing lockfile artifacts)
  do not apply here; this scanner never shells out to Trivy at all.
- First check `_SOURCE_EXTENSIONS` actually includes the source language's
  extension — if it does, the real cause is usually pattern-coverage, not
  filtering: `_SECURITY_PATTERNS` (~22 tuples) is Java/Spring-, Python-,
  and JS/Node-biased. As of 2026-07-10, C#/.NET idioms were added to 5
  patterns (`SQL_CONCAT`, `WEAK_HASH_CRYPTO`, `MISSING_AUTH_ANNOTATION`,
  `DEBUG_EXPOSURE`, `SSRF_CANDIDATE` — see `changes-log.md` entry
  "Bug fix: deterministic security scanner... found 0 findings on real
  C# code"). Any other language/framework showing persistent zero
  findings likely has the same root cause: the regex vocabulary simply
  hasn't learned that language's idioms yet, not a bug in the scan loop.
- `MISSING_AUTH_ANNOTATION` on C# code is more false-positive-prone than
  on Java/Spring: ASP.NET Core commonly declares `[Authorize]` once at
  the controller **class** level, which a nearby-only lookahead can't
  see. Treat a C# finding here as a heads-up to verify manually, not an
  automatically confirmed gap.

Processing tab / seam-status patterns (2026-07-21):
- Processing tab shows every seam as "pending" with no other context: the
  seam TDD loop (`_run_all_seams()` in `driver.py`) hasn't started yet —
  `seam.json` has no `processing`/`processing_summary` fields until
  `init_seam_processing()` runs, which only happens once Gate 4.5 is
  approved. Not mode-specific — happens identically in LLM and
  Deterministic mode. The UI now shows an explicit "Seam processing hasn't
  started yet — waiting for Gate 4.5 approval" message for this state
  instead of an unexplained wall of pending rows.
- Processing tab shows 100% of seams "failed" (`processing.status`) for a
  Deterministic-mode run: **expected, not a regression** — Deterministic
  mode has no Code Writer/review LLM fallback
  (`_direct_tool_fallback()` in `pipeline.py` has no case for
  `CODE_WRITER`/`SKEPTICAL_REVIEW`/`TEST_REVIEW`/`FUNCTIONAL_REVIEW`), so
  every seam predictably exhausts `MAX_TDD_ITERATIONS_PER_SEAM` and the
  1-attempt retry pass. `failure_reason` reads "Code Writer produced no
  verifiable output and review phase(s) did not run — see trace for
  details." The UI now shows a banner explaining this whenever
  `run.skip_llm` is true (detected client-side via the existing
  `.run-mode-badge.mode-det` class) — the underlying attempts/status data
  is still real and worth reading, just needs this context. See
  `transferable-skills/memory/tdd-writer-hardening.md` and
  `transferable-skills/memory/processing-tab-deterministic-messaging.md`.

Test Agent / sandboxed test-execution patterns (2026-09-08, PR #73/#74):
- `test_execution.json` missing entirely for a seam that reached
  `TEST_REVIEW`: `_run_test_execution_prescan` (`pipeline.py`) failed before
  it could write the file — check `diagnostics.log` for
  "`_run_test_execution_prescan` failed for `<run_id>` — continuing"; the
  hook fails open (doesn't block the phase) so a missing file means the
  hook itself errored, not that tests didn't run.
- A seam's real tests pass locally (`mvn test`/`pytest` outside the
  container) but `test_execution.json` shows `passed: false` inside a run:
  check whether the failure is sandbox-environment-specific before assuming
  a translation bug — `_sandbox_env()` only forwards an explicit allowlist
  of env vars (`_SANDBOX_ENV_ALLOWLIST`) to the subprocess, not the full
  parent environment, so a test that implicitly depends on an unlisted env
  var will fail only inside the sandbox.
- Every Maven-based test execution fails with "Could not create local
  repository at `/home/sandboxrunner/.m2/repository`": the Dockerfile's
  `useradd --create-home` step is missing or the image predates PR #73 —
  Maven resolves `user.home` from the passwd database entry for the
  current UID, not from `$HOME`, so a real home directory has to exist on
  disk.
- Maven/Gradle dependency downloads happen on every single TDD iteration
  instead of caching: `_sandbox_env()`'s `HOME` only points at the
  persistent `_SANDBOX_HOME` (`/home/sandboxrunner`) when actually running
  as root inside the container (`os.getuid() == 0`, same gating
  `_sandbox_preexec` uses) — if this is running unprivileged (local dev/CI,
  or a container that didn't drop root the way the real image does), it
  intentionally falls back to the ephemeral per-call `tmp` dir instead, so
  caching not persisting there is expected, not a bug.
- A new pre-phase hook you're adding that calls into `fitness_runner.py`
  (or any other function that shells out via `subprocess.run`) appears to
  freeze the whole app — every concurrent run's SSE stream stalls, gate
  approvals stop responding: you're calling a blocking function directly
  from an `async def` hook. Wrap it in `asyncio.to_thread(...)`, the same
  fix applied to `_run_test_execution_prescan` in PR #74 — the pre-existing
  `_run_trivy_prescan` has the same latent gap but is lower-impact since it
  only fires once per pipeline run, not once per TDD iteration.
- Files in the accumulated project directory show up owned by `root` or
  with unexpectedly narrow permissions for the sandboxed UID: `fitness_
  runner.py`'s `_make_world_writable()` chowns the tree to `_SANDBOX_UID`
  (10001) specifically — it does not `chmod 0o777` (that was PR #73's
  original, overbroad approach, fixed in PR #74). Confirm `_SANDBOX_UID`
  here still matches the Dockerfile's `useradd --uid` value if either ever
  changes independently.
- See `transferable-skills/memory/test-agent-sandboxed-execution.md` for
  the full incident history (10 real bugs total across the two PRs).

Silently-degraded LLM-mode run patterns (2026-09-09, #60/#61/#62):
- A crash-recovered `ir_graph.json` missing `cqrs_framework_hints` entirely,
  a `bounded_context_map.json` where every context has
  `business_capability: None`, or a run whose `reports/` directory doesn't
  exist at all despite the run having "completed" through Architect: check
  `docker logs` / the Trace tab for an `openai.BadRequestError: Context size
  has been exceeded` (or any other agent-turn exception) on the relevant
  phase. Before 2026-09-09 this was expected — the crash-recovery path
  returned before reaching that phase's own post-phase hooks (CQRS
  detection, seam/work-stream production, HTML reports/RAG index). Fixed by
  falling through into the same hooks the happy path runs; if you see this
  gap reappear, check whether a *new* `return` was reintroduced into
  `run_phase()`'s crash-handling `except` block — that's the one place this
  regresses from.
- A gate that opened with `artifact_valid: false` in its `gate_opened` event
  payload (or a visible warning banner on the gate card in the UI): the
  artifact behind that gate failed `_is_valid_artifact()` — likely leftover
  LLM prose from a crashed turn whose own fallback also produced nothing
  (e.g. Feature Specifier crashing after `seam.json` never existed because
  an earlier phase's crash-recovery skipped the hook that creates it). Not
  a UI bug — it's the intended signal (#63) to look harder before approving,
  not a broken render.
- See `transferable-skills/memory/crash-recovery-post-phase-hooks-and-gate-validity.md`
  for the full incident history.

Artifact schema reference:
- `ir_graph.json` includes `security_hints` (pre-Security-phase scan): `{ finding_count, source_architecture_risk, top_findings[] }`
- `tnas.json` includes `architectural_notes[]` (`[{ concern, placement|seam_location }]`) and `migration_sequence_rationale` (free text)
- `security_report.json` includes `risk_ranking[]` (ordered finding IDs), `migration_security_notes[]`, `recommended_fixes[]`, `follow_up_checks[]`
- `seam.json` items have `side_a` / `side_b` strings describing the two sides of the boundary

Report: which phase failed, what artifact is missing, which of the known patterns applies.
