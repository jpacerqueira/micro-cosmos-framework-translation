---
name: crash-recovery-post-phase-hooks-and-gate-validity
description: run_phase()'s crash-recovery path returned before reaching a phase's own post-phase hooks, silently degrading LLM-mode below the deterministic-mode floor on 3 phases (#60/#61/#62); a companion fix makes open_gate() run the same _is_valid_artifact check and surface a real warning banner instead of letting a crash-cascade leftover reach a human reviewer looking like a normal result (#63) (2026-09-09)
metadata:
  type: project
---

## How this was found

Auditing a real run phase-by-phase (`java-axonframework-example-app` → Kotlin, a 317KB
`ir_graph.json`) surfaced the identical crash on 5 consecutive phases across two separate runs of
the same estate: `openai.BadRequestError: Context size has been exceeded` on Observer,
Cartographer, Architect, Security, and Feature Specifier. This is the same root cause already
fixed for Feature Specifier via batching (BUG-7/#56) — a single-LLM-call-per-phase design that
doesn't scale to real-sized estates on a context-limited local model — but auditing the crash
*recovery* path (not just the crash trigger) found something more consequential.

## The bug: crash recovery skipped every phase's own richer behaviour

`run_phase()`'s exception handler correctly called `_direct_tool_fallback()` to recover a valid
deterministic artifact — but then `return`ed immediately, before ever reaching that phase's
"happy path" post-phase hooks block. Confirmed 3/3 times:

- **Cartographer (#60):** every context in the crash-recovered `bounded_context_map` had
  `business_capability: None` — the seam/work-stream refresh hook never ran.
- **Observer (#61):** the crash-recovered `ir_graph` had 0/252 nodes with `summary` (matching
  deterministic mode's own <1% enrichment rate — expected there, not here) and **no
  `cqrs_framework_hints` key at all**, because `detect_cqrs_frameworks()` lives in Observer's
  post-phase hook, never reached.
- **Architect (#62), the most visible consequence:** `runs/<id>/reports/` didn't exist at all —
  `_run_architect_reports()` (all 9 HTML reports + the RAG index) never ran.

**Why this matters more than it first looks:** none of these hooks actually depend on the agent
having succeeded — every one operates on the artifact itself, which the fallback already produced
validly. A crash in LLM mode was silently degrading the pipeline *below* the deterministic-mode
floor (which runs these same hooks unconditionally), for a run that's supposedly using the *more*
capable mode. The pipeline never blocked on this — it's a silent quality regression, not a halt,
which is exactly why it went unnoticed until someone deliberately audited a real run phase by
phase instead of just checking "did it finish."

## The fix — one shared change, not three per-phase ones

Removed the early `return` in the crash handler. Falls through naturally to the same
artifact-validation block and post-phase-hooks section the happy path already runs:
`agent_events` stays `[]` (never reassigned since the `try` block raised, so the `for event in
agent_events` loop right after is a harmless no-op), and the artifact-validation block re-reads
`self.artifacts`, finds the fallback already valid, and skips calling `_direct_tool_fallback` a
second time. Every phase's post-phase hooks are written defensively already (each wrapped in its
own try/except, each guarding on `isinstance(artifact, dict)` before doing anything) — they were
built assuming a valid artifact might come from anywhere, they just were never given the chance to
run on a fallback one until now.

**Lesson for any future crash-recovery path in this codebase:** if a fallback produces a valid
artifact, ask explicitly whether the code that would normally enrich/report on that artifact
actually needs the agent to have succeeded, or just needs the artifact to exist and be valid. Two
different things — this bug conflated them for over a year of the codebase's history.

## The companion bug (#63) — a gate can present a crash's raw leftovers as reviewable content

The full cascade that surfaced this: Observer and Cartographer both crashed (steps above), so
`seam.json` never existed; Feature Specifier then also crashed on the same context-overflow
pattern, and its own crash-recovery fallback correctly detected it had no seams to read and
honestly returned `(None, None)` rather than fabricate something. But because the fallback
returned nothing, nothing overwrote the stale, confused LLM prose already sitting in session state
from the crashed turn — Gate 4.5 then opened with that prose as the "artifact," looking identical
to a normal review. No signal to a human reviewer that they were about to approve garbage — the
whole point of a human-approval gate is to catch what the pipeline can't catch itself, and a gate
that can silently present garbage as reviewable content undermines exactly the failure case where
a human's judgment matters most.

`_is_valid_artifact()` already existed and was already used to decide whether `run_phase()` needs
a deterministic fallback — reused as-is here, at `open_gate()`, the one place a human actually
sees the artifact. Emits a real `warning` PipelineEvent plus `artifact_valid: false` in the
`gate_opened` payload; `dashboard.js` renders a persistent, bold `.gate-invalid-banner` directly on
the gate card — deliberately not just a quiet trace-log line, since the whole point is that a
reviewer skimming the gate screen needs to see it without having to go looking for it.

**A real regression this found in 2 pre-existing tests:** `test_auto_approve_gates.py`'s
`test_open_gate_bypasses_wait_immediately`/`test_open_gate_without_auto_approve_still_blocks` both
called `open_gate(PipelinePhase.GATE_1)` on a bare orchestrator with zero artifacts ever set —
purely testing approve/reject mechanics, with no real precondition setup. The new validity check
correctly flags an empty `{}` as invalid (fails `ir_graph`'s `isinstance(v.get("nodes"), list)`
check), which broke their exact `[ev.kind for ev in events] == ["gate_opened", "gate_resolved"]`
assertions. Fixed by seeding a trivially-valid `orch.artifacts["ir_graph"] = {"nodes": []}` before
calling `open_gate` in both tests — preserves their actual intent (testing gate mechanics, not
artifact validity) without being a red herring from the new, unrelated check.

## Deliberately not built — flagged as a follow-up, not bundled in

The underlying trigger (context overflow itself) is still unaddressed for Observer, Cartographer,
and Architect — Feature Specifier is the only phase with batching today. Given this reproduces
100% of the time for a real, unremarkable-sized estate (317KB IR graph is not an edge case), it's
the common case for any real-sized codebase on a context-limited local model, not a corner case. A
bigger context window alone wouldn't help either — larger estates will eventually hit the same
ceiling regardless of how far it's raised. Each phase would need its own batching design (Observer
batches naturally by file/module; Cartographer's bounded-context classification is a single
graph-wide decision that doesn't obviously decompose the same way Feature Specifier's per-seam
specs did; Architect's TNAS spans the whole estate) — deliberately scoped out of this fix and
tracked as its own follow-up rather than attempted as one more thing bolted onto this PR.

## Files changed

| File | Change |
|---|---|
| `micro_cosmos/orchestration/pipeline.py` | Removed early `return` in the crash handler; `open_gate()` runs `_is_valid_artifact` and emits a `warning` + `artifact_valid` flag |
| `micro_cosmos/web/static/js/dashboard.js` | Renders `.gate-invalid-banner` on the gate card when `artifact_valid` is `false` |
| `micro_cosmos/web/static/css/app.css` | New `.gate-invalid-banner` style |
| `tests/test_pipeline.py` | 4 new tests (2 crash-recovery, 2 gate-validity) |
| `tests/test_auto_approve_gates.py` | 2 existing tests updated to seed a valid artifact |

## Follow-up: 4 real correctness gaps found in review, before merge (2026-09-10)

This PR was still open (not yet merged) when reviewed — 4 parallel review agents + manual
verification against the diff/source. All four confirmed real, fixed on the same branch before
merge, each independently re-verified against the code first (never trust a review finding at
face value, this session's own house rule).

1. **The Gate 4.5 backstop above was a complete no-op.** `feature_specifier_agent`'s real ADK
   `output_key` is `"feature_specs_result"`, not `"feature_specs"` — `_is_valid_artifact`'s
   `_checks` dict only had an entry for the latter, so `_checks.get("feature_specs_result")`
   returned `None` and fell through to the unconditional `True` default. This also meant BUG-7's
   own fallback-trigger check had never fired for a real LLM-mode run. Fixed by extracting
   `_is_valid_feature_specs()` and registering it under both keys.
2. **`auto_approve_gates` bypassed the new warning entirely** — approved right after warning about
   the same invalid artifact, defeating the backstop specifically for unattended runs. Fixed by
   skipping auto-approve for an invalid artifact — but a real hang was found and fixed *while
   verifying this fix*: scoping it mode-agnostically deadlocked
   `test_full_pipeline_auto_approves_all_six_gates`, because deterministic mode has no
   LLM-call-crash concept and `PR_REVIEWER` has zero deterministic fallback registered at all (a
   pre-existing, accepted gap — see the "skip_llm=true but no deterministic fallback for
   pr_reviewer" warning that already existed) — meaning `review_report` is *always* structurally
   invalid at Gate 5 in deterministic mode, permanently blocking auto-approve there for every
   deterministic run if the check weren't scoped. **Lesson**: when a review finding says "fix X,"
   verify the fix against the FULL test suite, not just the specific scenario the finding
   describes — the fix's own correct scope can be narrower than its first-pass implementation.
3. **A crashed phase's error pill silently flipped to green.** `dashboard.js`'s `markPhase()`
   unconditionally overwrites all status classes on every event; once the crash-recovery path
   above started reaching the final `phase_completed` event too, that event's handler
   unconditionally called `markPhase(phase, "done")`, erasing the exact "this degraded" signal the
   whole PR exists to surface. Fixed with a `recovered_from_crash` flag threaded from the crash
   handler through to the final event payload.
4. **A second, structurally identical early `return`** in the post-agent "state snapshot" except
   block was left unpatched — same bug class, different trigger (anything raising there, not just
   the LLM call itself). Fixed the same way; required moving `output_key = agent.output_key` to
   before that `try` block entirely, since it was previously assigned partway through and the old
   `return` had been silently protecting against a `NameError` for any exception that fired before
   that line.

**A real, separate correctness improvement found resolving #2's edge case**: Feature Specifier's
deterministic fallback returned `(None, None)` for a genuinely seam-free estate (not a failure) —
harmless before this PR (nothing consulted validity for auto-approve), but indistinguishable from
the confirmation-stub bug once #1's key fix made the check actually run. Now returns an explicit
`{"specs": [], ...}`, and `_is_valid_feature_specs` no longer requires a non-empty list (the real
bug shape has no `"specs"` key at all, so the list-type check alone already catches it).

**Not fixed, documented instead** (lower severity, flagged in the review itself as follow-up
material): `_run_architect_reports()`'s ~9 sequential blocking `subprocess.run` calls are
pre-existing tech debt, newly reachable via the crash path — a separate `asyncio.to_thread` fix,
same shape as [[test-agent-sandboxed-execution]]'s PR #74 fix, out of scope here. A double-fallback
double-execution edge case in the crash handler is accepted as low-likelihood, documented in
place. `open_gate()`'s new warning still duplicates `run_phase()`'s own validity-warning shape
instead of sharing a helper.

**Verification**: 6 new tests (including one that reproduces the deterministic-mode Gate 5 hang
directly, to lock in the LLM-mode-only scoping decision as a real regression test, not just a
one-off fix). Full suite: 302 passed (up from 296), same 8 known failures — zero regressions.
Verified in a real container build too.
