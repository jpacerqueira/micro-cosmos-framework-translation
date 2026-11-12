# No gate validation

Micro-Focus does not open a human gate and does not stop because an artifact failed a validity check.

Do not pause, ask for approval, or re-run a phase for any of these:

- Gate 1, IR quality, after Observer
- Gate 2, bounded context map, after Cartographer
- Gate 3, TNAS, after Architect
- Gate 4, security analysis, after Security
- Gate 4.5, planning, after the framework translation planner
- Gate 5, PR approval, after code translation

Do not stop the run when an artifact is thin or missing a field. The showcase pipeline can refuse to continue when `ir_graph.nodes` is not a list, the context map is empty, `tnas` has neither `services` nor `target_lang`, `security_report.findings` is not a list, a seam result has no `pr`, a review has no boolean `passed` and no `findings` list, or feature specs are empty. Micro-Focus does the opposite. Write the artifact you have, add a line to `gaps.md` naming the phase and the missing field, and start the next phase.

Do not invent a rejection, an escalation, or a reviewer name. The only time a run stops early is when the command is the plan command, and that stop is after the framework translation planner, before any code translation.
