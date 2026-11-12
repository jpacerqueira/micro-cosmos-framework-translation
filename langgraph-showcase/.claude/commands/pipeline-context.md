# Load Micro-Cosmos pipeline context

Load the key architectural context for the Micro-Cosmos pipeline so you can work on it effectively.

## What to read

1. `CLAUDE.md` — full project context (auto-loaded, but re-read for freshness)
2. `changes-log.md` — last 5 entries in Bug Fixes section for recent decisions
3. `micro_cosmos/orchestration/pipeline.py` lines 50-130 — PipelinePhase enum + PHASE_AFTER_GATE + GATE_TO_AGENT_NAME
4. `micro_cosmos/orchestration/driver.py` lines 180-280 — run_full_pipeline structure

Then summarise: current phase count, gate count, any known issues from changes-log, and confirm the phase order is consistent across pipeline.py and driver.py.

## Key artifact schemas (do not grep for these — note here for reference)

### `tnas.json`
Two valid `fitness_suite` shapes depending on run mode:
- **LLM mode**: `{ "cohesion_within_context": "High. …", "migration_path_clarity": "Medium. …", … }` — named-dimension strings
- **Deterministic mode**: `{ "functions": [{ id, name, description, severity, rationale, spec, derived_from }], "target_language": "kotlin" }` — FitnessSuite Pydantic schema
- Also contains: `architectural_notes[]` (`[{ concern, placement|seam_location }]`), `migration_sequence_rationale` (free text), `services[]`, `summary`

### `ir_graph.json`
- Top-level `security_hints`: `{ finding_count, source_architecture_risk, top_findings[] }` — produced by pre-Architect security pre-scan, available before the Security agent runs
- Each node: `{ id, type, name, summary, inputs[], outputs[], signature, source_excerpt }`
- `documentation_bundle`: source README contents if present

### `security_report.json`
- `findings[]`: each has `{ id, title, category, severity, cwe_id, location, confirmed, affects_migration, description, matched_text, remediation, code_snippet }`
- `risk_ranking[]`: ordered list of finding IDs by combined severity
- `migration_security_notes[]`, `recommended_fixes[]`, `follow_up_checks[]`
- `scope_summary`, `source_architecture_risk`, `destination_architecture_risk`

### `seam.json`
Each seam: `{ id, type, location, source_location, side_a, side_b, evidence[], substitution_note, work: { title, steps[], effort, story_points, risk, migration_phase } }`

## Report generator → artifact mapping

| Generator | Reads |
|---|---|
| `generate_security.js` | `security_report.json`, `trivy_report.json` (optional) |
| `generate_monitoring.js` | `ir_graph.json`, `tnas.json`, `bounded_context_map.json`, `security_report.json` |
| `generate_adrs.js` | `tnas.json` (fitness_suite + architectural_notes) |
| `generate_fitness_stubs.js` | `tnas.json` (fitness_suite) |
| `generate_exec_summary.js` | `run_meta.json`, `ir_graph.json`, `tnas.json`, `bounded_context_map.json`, `seam.json`, `work_streams.json` |
| `generate_briefing.js` | `run_meta.json`, `bounded_context_map.json`, `tnas.json`, `work_streams.json`, `seam.json` |
| `generate_synthesis.js` | all of the above + `ir_graph.json` |

## Gate → artifact mapping

| Gate | Artifact key | JSON file |
|---|---|---|
| Gate 1 (Observer) | `ir_graph` | `ir_graph.json` |
| Gate 2 (Cartographer) | `bounded_context_map` | `bounded_context_map.json` |
| Gate 3 (Architect) | `tnas` | `tnas.json` |
| Gate 4 (Security) | `security_report` | `security_report.json` + `trivy_report.json` via extraData |
| Gate 4.5 (Planning) | `feature_specs` | `feature_specs.json` |
| Gate 5 (PR Review) | `review_report` | `review_report.json` + `trivy_output_report.json` via extraData |
