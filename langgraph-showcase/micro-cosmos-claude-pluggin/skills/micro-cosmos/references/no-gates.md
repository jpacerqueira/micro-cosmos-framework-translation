# No gate validation

Micro-Cosmos does not open a human gate and does not stop because an artifact failed a validity check. `run_pipeline.py` sets `skip_gate_validation`.

Do not pause, ask for approval, or re-run a phase for any of these:

- Gate 1, IR quality, after Observer
- Gate 2, bounded context map, after Cartographer
- Gate 3, TNAS, after Architect
- Gate 4, security analysis, after Security
- Gate 4.5, planning, after the framework translation planner
- Gate 5, PR approval, after code translation

Do not stop the run when an artifact is thin or missing a field. Write the artifact the pipeline produced, add a line to `gaps.md` naming the phase and the missing field, and start the next phase.

The plan command stops after the framework translation planner, before any code translation. The translate command stops when the translated tree exists. That stop is not a PR gate.
