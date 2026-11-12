# Add a new pipeline phase to Micro-Cosmos

$ARGUMENTS should describe the new phase: name, what agent it runs, what artifact it produces, and where in the pipeline it fits.

## Checklist — 7 locations to update

1. **`micro_cosmos/orchestration/pipeline.py`**
   - Add `NEW_PHASE = "new_phase"` to `PipelinePhase` enum in the correct position
   - Add `PipelinePhase.NEW_PHASE: build_new_phase_agent` to `PHASE_AGENT_BUILDERS`
   - Add kickoff string to `_phase_kickoff_prompt()`
   - If this phase precedes a gate: add to `PHASE_AFTER_GATE` and `GATE_TO_AGENT_NAME`

2. **`micro_cosmos/orchestration/driver.py`**
   - Add `async for ev in orch.run_phase(PipelinePhase.NEW_PHASE): yield ev` at the correct position in `run_full_pipeline()` or `_run_all_seams()`
   - Update `start_phase` guard if needed

3. **`micro_cosmos/gates/__init__.py`** (if adding a gate)
   - Add gate dict to `GATE_DEFINITIONS` between the correct neighbours

4. **`micro_cosmos/web/app.py`** (if adding a gate)
   - Add `"new_gate": PipelinePhase.NEW_PHASE` to `_GATE_RESTART_PHASE`

5. **`micro_cosmos/web/templates/run.html`**
   - Add `"new_phase"` to the 17-pill phase strip array at the correct index

6. **`micro_cosmos/web/static/js/dashboard.js`** (if adding a gate)
   - Add entry to `GATE_ARTIFACT_KEY`
   - Add `case "new_gate":` block in `buildGateSummary()`

7. **Create the agent** in `micro_cosmos/agents/new_phase.py` and the tool in `micro_cosmos/tools/`

After all changes: update `changes-log.md` and `README.md` phase table.
