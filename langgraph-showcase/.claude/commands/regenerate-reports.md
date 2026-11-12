# Regenerate HTML reports for a Micro-Cosmos run

Regenerates all HTML reports for a completed or partial run. Use this after
report generator scripts are updated, or to backfill reports on an old run.

`$ARGUMENTS` = run ID (e.g. `1821ae7d`)

## Steps

1. Verify the run directory exists: `runs/$ARGUMENTS/`
2. List which JSON artifacts are present — this determines which reports can be built.
3. Run each generator script that has its required inputs available:

```bash
RUN=runs/$ARGUMENTS && OUT=$RUN/reports && mkdir -p $OUT

for pair in \
  "generate_security.js:security-report.html" \
  "generate_monitoring.js:monitoring.html" \
  "generate_briefing.js:migration-briefing.html" \
  "generate_synthesis.js:project-synthesis.html" \
  "generate_graph.js:ir-graph.html" \
  "generate_exec_summary.js:executive-summary.html" \
  "generate_hotspots.js:hotspots.html" \
  "generate_sprint_plan.js:sprint-plan.html" \
  "generate_adrs.js:architecture-decisions.html" \
  "generate_fitness_stubs.js:fitness-stubs.html" \
  "generate_deadcode.js:dead-code.html" \
  "generate_feature_specs.js:feature-specs.html" \
; do
  script="${pair%%:*}"; out="${pair##*:}"
  echo -n "=== $script → $out ... "
  node scripts/$script $RUN $OUT/$out 2>&1 | tail -1
done
```

4. Report which scripts succeeded, which were skipped (missing inputs), and which errored.

## Script prerequisites (skip if any missing)

| Script | Required JSON artifacts |
|---|---|
| `generate_briefing.js` | `run_meta.json`, `bounded_context_map.json`, `tnas.json`, `work_streams.json`, `seam.json` |
| `generate_synthesis.js` | + `ir_graph.json` |
| `generate_graph.js` | `run_meta.json`, `bounded_context_map.json`, `ir_graph.json` |
| `generate_exec_summary.js` | `run_meta.json` |
| `generate_hotspots.js` | `run_meta.json`, `ir_graph.json` |
| `generate_sprint_plan.js` | `run_meta.json`, `work_streams.json` |
| `generate_adrs.js` | `run_meta.json`, `tnas.json` |
| `generate_fitness_stubs.js` | `run_meta.json`, `tnas.json` |
| `generate_deadcode.js` | `run_meta.json`, `ir_graph.json` |
| `generate_monitoring.js` | `run_meta.json`, `ir_graph.json`, `tnas.json` |
| `generate_security.js` | `security_report.json` (reads `trivy_report.json` optionally) |
| `generate_feature_specs.js` | `feature_specs.json` |

## fitness_suite format note

`tnas.fitness_suite` has two valid shapes depending on run mode:
- **LLM mode**: plain object of named dimension strings `{ "cohesion_within_context": "High. …" }`
- **Deterministic mode**: FitnessSuite schema `{ "functions": [{...}], "target_language": "..." }`

All generator scripts handle both. The `_FITNESS_META` exclusion set prevents
canonical schema metadata keys (`sha`, `created_at`, `produced_by`, `functions`,
`target_language`, `intended_commit_path`) from being mistaken for dimension strings.
