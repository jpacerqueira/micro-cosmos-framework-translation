# Auto-approve gates + combined full-app-migration-report.html

Two independent features, planned together via `EnterPlanMode`/`ExitPlanMode` (plan file:
`vivid-strolling-stearns.md`) given the combined scope — orchestrator, `app.py`, templates, JS, and
a brand-new Node report script.

## Feature 1 — Auto-approve gates

**The ask**: LLM-mode runs can take hours across 6 human-approval gates. Joao wanted a toggle on the
run-creation form so a run can proceed unattended end-to-end, opt-in. This had been mentioned once
before earlier in the session and explicitly deferred with a fuller spec ("request name and forces
comment as 'auto-approved to next gate'"); when raised again more simply, three points were
re-confirmed via `AskUserQuestion` rather than assumed: (1) enabling the toggle requires an approver
name — a text input appears next to it, required only when checked, stamped as `reviewer_name` on
every auto-approval with `notes` always forced to `"auto-approved to next gate"`; (2) all 6 gates
auto-approve uniformly, including Gate 5 (the automated PR-reviewer checks still run — only the
human click is skipped); (3) run-start-only, no mid-run toggle (unlike "Stop TDD loop").

**Data flow — copies `skip_llm`, not `stop_requested`.** `skip_llm` is a per-run value fixed at
`Run`/`MicroCosmosOrchestrator` construction, re-supplied on every `Run.restart()`, persisted to
`run_meta.json`. `stop_requested` is a live mid-run mutation via a dedicated endpoint. Auto-approve
needed the former shape (a fixed, run-start setting), not the latter — `auto_approve_gates: bool` +
`auto_approve_reviewer_name: str` thread through the exact same 3 call sites `skip_llm` already
uses: `POST /runs` Form params → `Run.__init__` → `run_meta.json`; `_restore_run()`'s
`.get(..., False/"")` reads; `Run.restart()`'s re-supply to the freshly-built orchestrator (`Run`,
not the orchestrator instance, is the durable source of truth across a restart — the orchestrator
itself is discarded and rebuilt).

**The single injection point**: `MicroCosmosOrchestrator.open_gate()` (`pipeline.py`) — immediately
before `await self._gate_events[gate_id].wait()`:
```python
if self.auto_approve_gates:
    self.approve_gate(gate_id, reviewer_name=self.auto_approve_reviewer_name,
                       notes="auto-approved to next gate")
```
`approve_gate()` is synchronous (no `await`), so it sets the gate's `asyncio.Event` before `.wait()`
runs on the next line — single-threaded asyncio guarantees no interleaving within one coroutine, so
`.wait()` returns immediately and every downstream branch of `open_gate()` (rejection/escalation
handling, `gate_resolved` emission) runs completely unmodified, uniformly for all 6 gates.

**A necessary extension found during design, not assumed**: the `gate_resolved` event payload only
carried `gate_id`/`decision`/`rejection_count` — no `reviewer_name`/`notes`. Without extending it,
`dashboard.js` would have no way to show "Approved by X: notes" for a gate that was never manually
clicked (a manual approval gets that text from the approve endpoint's htmx-swapped HTTP response,
which auto-approval never makes). Extended the payload with `reviewer_name`/`notes` sourced from
`state.approvals[-1]`, and `markGateResolved()` fills `.gate-result` only when it's still empty — so
a normal manual approval's already-swapped text is never overwritten, but an auto-approved gate gets
the same rendering treatment for free.

**Deliberately no second confirmation modal.** The required-name field appearing only when the
toggle is checked already serves as the "are you sure" gate. `run-confirm.js` (the existing
LLM-mode confirmation, see [[llm-mode-confirm-toggle]]) is untouched and unrelated.

**Verified live**: a full deterministic-mode pipeline run against `examples/legacy_estate`
(cobol→go) with `auto_approve_gates=True` and **zero** manual `approve_gate()` calls resolved all 6
gates `APPROVED` with the correct reviewer name and notes, reaching `pipeline_completed`.

## Feature 2 — Combined `full-app-migration-report.html`

**The ask**: a 14th report, last in the Reports menu, combining a status table (every other HTML
report, every `*.json` artifact, Kiro/OpenSpec/Skills output — in Reports-menu order) with the full
content of everything that table lists, below it.

**Key design decision, stated up front rather than discovered by trial and error**: embed the 13
other HTML reports via `<iframe src="{filename}">`, not by extracting and merging their inner
markup into one continuous document. 9 of the 13 report scripts share `report_common.js`'s
`htmlShell`, but 4 (`briefing`, `synthesis`, `graph`, `monitoring`) predate it and inline their own
HTML — a merge-by-extraction approach would need per-script special-casing today and could silently
break for any future report script that doesn't conform. A relative iframe `src` resolves correctly
both live (`/runs/{id}/files/{filename}`) and when the combined report is opened directly from an
extracted `full.zip`, since every report lands as a flat sibling file under `reports/`. Trade-off:
each embedded report keeps its own nav/cover header rather than flowing as one seamless document —
accepted, not fixed.

Kiro/Skills/OpenSpec markdown files render as raw text in a `<pre>` block — no Markdown-rendering
dependency exists anywhere in this codebase's report scripts, and adding one for this alone would be
disproportionate surface area. Every embedded report/file sits inside a collapsed `<details>` (same
convention as the Trace tab's JSON tree, see [[run-dashboard-graph-resize-and-json-tree]]) so the
page stays scannable. JSON artifact rows are status-only per the literal ask ("status of all output
generated artifacts"), with an inline note that `seam_result.json`/`skeptical_review.json`/
`test_review.json`/`functional_review.json` reflect only the most recently processed seam (these
files are overwritten per-seam as the TDD loop iterates), not full history.

**A real gap found during implementation, fixed rather than left in place**: `full-app-migration-report.html`
is the last key in `_FILE_TO_SCRIPT`, so `_generate_all_available_reports()`'s main loop (plain dict
insertion order) generates it after the other 12 reports — but steps 2-5 of that same function
(OpenAPI/Jira export, Kiro Powers, Claude Code Skills, OpenSpec) run *after* the whole loop, meaning
the very first "Generate full.zip" click would produce a combined report showing those as "not yet
generated" even though they're created moments later in that same request. Fixed with a second,
unconditional regeneration call at the very end of `_generate_all_available_reports()`, so the copy
bundled into `full.zip` is accurate on the first click, not just a subsequent "Regenerate."

`run_file()` special-cases this one filename to always regenerate (bypassing the
`if not out_path.exists()` skip every other report uses) — same "always regenerate" precedent as
`_write_openspec()` (see [[openapi-rename-and-openspec-artifact]]), since the whole point is being
an accurate live snapshot; a cached stale copy would defeat it.

**Renamed mid-implementation**: shipped first as `full-report.html`, then renamed to
`full-app-migration-report.html` per explicit request. Mechanical rename across the generator
script, `app.py`'s 3 wiring points, the `run.html` menu link, `CLAUDE.md`, and the test file —
verified via a repo-wide grep that zero references to the old name survived.

**Verified live**: a real pipeline run generated 2 real HTML reports + Kiro Powers + Claude Code
skills, then the combined report (90KB) rendered correctly — accurate status table, working
`<iframe>` embeds for generated reports, real Kiro Power markdown content inline via `<pre>`.

## 6 pre-existing test failures fixed (not just documented) along the way

Running the full suite after both features surfaced 6 failures unrelated to either feature. Per an
explicit request this time for a genuinely clean report (not "pre-existing, documented, left as-is"
— the pattern used earlier in this same session), all 6 were investigated and fixed:

1. `test_gates.py::test_initial_gate_states_pending` asserted `len(states) == 5`; `GATE_DEFINITIONS`
   has had 6 entries (including `gate_4_5`) for a while — stale assertion, fixed to `6`.
2. `_is_valid_artifact` had no shape check for `"seam_result"`/`"review_report"` — any shape
   (including one missing the expected `"pr"`/`"review_passed"` key) was silently accepted as
   valid. Added real checks, matching the pattern already used for `ir_graph`/`bounded_context_map`.
3. A pre-existing test's "valid `bounded_context_map`" example (`{"contexts": []}`) predated a real,
   deliberate, already-shipped tightening of that check (≥2 real contexts, a real cross-context
   call, no glob node_ids — the documented "ProjectManagement over-broad-context incident,
   2026-08-04" fix). The check was correct; the test's example was stale. Fixed the test, left the
   check untouched — the opposite call from the two `_is_valid_artifact` gaps above, worth noting
   since both "test is stale" and "implementation has a real gap" can look identical (a failing
   assertion) until you trace *why* the check exists.
4. A test referenced `PipelinePhase.PATTERN`, which doesn't exist — the Pattern agent
   (`micro_cosmos/agents/pattern.py`) was confirmed (via grep, during this same session's earlier
   research) to not be wired into `driver.py`/`pipeline.py` anywhere. Removed the phase and its
   `domain_model` assertion from the test.
5. **The most consequential fix**: `_direct_tool_fallback` had no case at all for
   `SKEPTICAL_REVIEW`/`TEST_REVIEW`/`FUNCTIONAL_REVIEW`. A pre-existing test's own docstring named
   the exact real-world consequence: "`_direct_tool_fallback` must return a valid failing review,
   not `None`, when the agent crashed without calling `submit_code_review`. Without this, `_passed()`
   defaults to True" — meaning a reviewer agent that crashes without submitting could let a stale
   prior-seam's `<review>.json` (these files are overwritten per-seam) stand in for the current
   seam's review in `orch.artifacts`, silently passing the TDD loop on a seam that was never
   actually reviewed. Added 3 fallback branches synthesizing a failing review (`passed=False`, one
   `BLOCKER` finding) via the real `submit_code_review`/`submit_test_review`/`submit_functional_review`
   tool functions (not hand-built dicts), so the written JSON is shape-identical to a real
   submission. Also added `_is_valid_artifact` shape checks for these three review types as
   defense-in-depth against the same staleness class of bug.
6. `test_fitness_suite_passes_clean_code` — `run_fitness_suite`'s exec check runs
   `pytest --tb=short -q` against a PR fragment with no test files of its own; pytest's convention
   is exit code `5` ("no tests collected"), but every OTHER language's test command in this file
   (`go test`, `cargo test`, `mvn test`) exits `0` with zero tests — pytest is the outlier, and the
   code treated `5` as a real failure. Fixed by special-casing `lang == "python" and
   proc.returncode == 5` as a pass, scoped narrowly to pytest's specific convention rather than
   changing behavior for any other language.

Full suite: 150 passed (up from 133 at the start of this batch), 1 skipped, zero failures.
