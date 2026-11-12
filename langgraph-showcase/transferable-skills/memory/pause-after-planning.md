---
name: pause-after-planning
description: Launch-time "Pause after planning" toggle — ends the run after Gate 4.5 instead of entering the seam TDD loop, still downloadable; copies auto_approve_gates persistence, not stop_requested (2026-09-16)
metadata:
  type: project
---

Joao asked for a yes/no toggle in the Launch-analysis panel, directly below Mode, that stops the
pipeline once Gate 4.5 is approved so the code-translation TDD loop never starts. Every artifact
produced up to that point must still be downloadable as a full zip.

## Persistence: `auto_approve_gates`, not `stop_requested`

`pause_after_planning: bool` is a **fixed-at-launch per-run setting**. It threads through the
exact same five call sites as `auto_approve_gates` / `skip_llm`:

1. `POST /runs` `Form` param (`pause_after_planning: str = Form("false")`, truthy on `"true"`)
2. `Run.__init__`
3. `create_run()`'s `run_meta.json` write
4. `_restore_run()`'s safe `.get("pause_after_planning", False)` — required, because the 20
   runs already on disk predate the key
5. `Run.restart()` re-supplies it to the freshly constructed `MicroCosmosOrchestrator`

`Run`, not the orchestrator (which is discarded and rebuilt on restart), is the durable source of
truth. This is **not** the `stop_requested` pattern (see [[stop-tdd-loop-button]]) — that models a
live mid-run mutation via a dedicated endpoint. Mixing the two is how a later Gate-5-rejection
re-run of `_run_all_seams()` previously leaked a stop flag.

## Placement of the check in `driver.py`

The early return sits in `run_full_pipeline()` **after Gate 4.5 has fully resolved** — after its
rejection/re-specify `while` loop and its ESCALATED early-return. Moving it earlier would break
Gate 4.5 rejection cycles. It is guarded by the same
`start_phase not in (CODE_WRITER, PR_REVIEWER)` condition as the surrounding blocks, so an
explicit restart into `CODE_WRITER` still bypasses the pause. A paused run is stopped, not sealed.

It emits the ordinary `pipeline_completed` event with `paused_after_planning: true` and a
`skipped_phases` list (code_writer, skeptical_review, test_review, functional_review, writer,
pr_reviewer, gate_5) rather than a new event kind. That is what keeps zip/report endpoints
untouched: `generate_zip` never gated on run completion, and `_REPORT_PREREQUISITES` already
skips reports whose input artifact is missing.

## UI

- Toggle in `demo.html` (served at `/`) reuses `.auto-approve-toggle` chrome; hint text
  "Stops the run once Gate 4.5 is approved — no code translation loop."
- `dashboard.js` rewords the completion card ("Stopped after planning") and marks the seven
  unreached pills `.phase-pill.skipped` (dashed + struck through). `markPhase()` must also
  *clear* `skipped`, or a later restart leaves pills struck through.
- A paused run's `full.zip` still contains every analysis/planning report. The two reports that
  stay absent are absent for correct reasons: `output-security-report.html` needs the post-Gate-5
  Trivy output scan, and `feature-specs.html` needs `feature_specs.json`.

## Fixture gotcha when asserting planning artifacts

On the zero-seam `examples/legacy_estate` estate the Feature Specifier writes
`feature_specs_result.json`, not `feature_specs.json`. Asserting the latter is a property of the
fixture, not of pausing. Tests that need "planning survived" should assert the six artifacts that
always exist: `ir_graph.json`, `bounded_context_map.json`, `tnas.json`, `security_report.json`,
`seam.json`, `work_streams.json`.

## Tests

`tests/test_pause_after_planning.py` — pipeline stops after Gate 4.5, planning artifacts survive,
`CODE_WRITER` restart bypasses the pause, a default run still reaches Gate 5, the flag round-trips
`run_meta.json` (including a legacy meta file without the key), `/` serves the chooser, `/demo`
308s, `/demo/*` APIs still work, login lands on `/`.
