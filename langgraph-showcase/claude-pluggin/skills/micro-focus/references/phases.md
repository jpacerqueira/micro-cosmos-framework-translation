# Pipeline phases

Read `frameworks.md`, `modes.md`, and `no-gates.md` before the first phase. Work in order. The plan command stops after the framework translation planner. The translate command continues into code translation.

Create `<source>/.micro-focus/<run-id>/` only after the license check allows the run. `run-id` is a UTC timestamp `YYYYMMDDTHHMMSSZ`. Write `run.json` with `source_path`, `source_lang`, `target_lang`, `mode`, `depth` (`plan` or `translate`), `account_id`, and `frameworks_detected`.

Detect `source_lang` by the most common source extension. Ask for `target_lang` once if the user did not name it. An application estate uses an application language from `frameworks.md`. A data-engineering estate uses `databricks`, `bigquery_dataform`, or `snowflake_dbt`, and not the platform it already is.

## 1. Observer

Read the source files. Skip `.git`, `node_modules`, `target`, `build`, `.venv`, and `.micro-focus`.

Write `ir_graph.json`:

- `nodes`: a list. One node per source file, type, class, and function you can see. Each node has `id`, `name`, `kind`, and `path`.
- `edges`: a list of `CALLS`, `DEFINES`, `REFERENCES`, or `WRITES` links you can see from imports and calls.
- `cqrs_framework_hints`: `detected_frameworks` and `evidence`. Match manifests and imports against `frameworks.md` only.

Deterministic mode writes those three fields and stops. LLM mode adds up to 15 estate insights and up to 60 `function_summaries` with `name`, `summary`, `inputs`, and `output`. Omit getters, setters, and constructors.

`nodes` must be a list. If it is not, replace it with an empty list, note the gap, and continue.

## 2. Cartographer

Group the IR nodes into bounded contexts by folder and by framework role. Spring repositories, NestJS modules, React pages, Dataform schemas, dbt models, Databricks notebooks, and Data Factory activities are separate contexts when the files show that split.

Write:

- `bounded_context_map.json` with `contexts` (each has `name`, `node_ids`, `confidence`, `rationale`) and `cross_context_calls`.
- `seam.json` with one seam per migration unit. Each seam has `id`, `type`, `source_location`, `substitution_note`, `evidence`, and `work` (`steps`, `effort`, `risk`).
- `work_streams.json` with `id`, `seam_ids`, `rationale`, and `depends_on`.

Deterministic mode names contexts from the path and the framework file. LLM mode may rename a context to a domain name and add one sentence of rationale. If `contexts` is missing, write an empty list, note the gap, and continue.

## 3. Architect

Write `tnas.json` with `target_lang`, `services`, and `context_decisions`. One service per context. Each service has `service_id`, `node_ids`, `rationale`, `migration_risk`, and `risk_reason`. Each context decision has `context`, `confidence`, `service_granularity`, `communication_style` (`sync-http` or `async-event`), `data_store`, `execution_model`, and `consistency_model`.

For a data-engineering target, set `service_granularity` to `table`, `communication_style` to `async-event`, `data_store` to the target platform, and `consistency_model` to `EVENTUAL`.

Name a detected web or data-engineering framework in `pattern_recommendation` when `cqrs_framework_hints` or the source manifests found one. Deterministic mode copies context names and risks through. LLM mode adds the migration sequence. If both `services` and `target_lang` are missing, write `target_lang` from `run.json`, note the gap, and continue.

## 4. Security analysis

Write `security_report.json` with `source_lang`, `target_lang`, `scope_summary`, `findings`, `source_architecture_risk`, and `destination_architecture_risk`. `findings` is a list. Each finding has `id`, `title`, `description`, `severity` (`CRITICAL`, `HIGH`, `MEDIUM`, or `LOW`), `category`, `location`, `confirmed`, `remediation`, and `affects_migration`.

Read dependency manifest filenames that are part of the source tree. Note missing authorization checks and string-built SQL when the source line shows them. Do not install or run Trivy. Note that dependency CVEs were not scanned with Trivy. If `findings` is not a list, write `[]`, note the gap, and continue.

## 5. Framework translation planner

This is the last phase of a plan run. It is the showcase planning step after security and before any translated code.

Write `feature_specs.json` with one spec per seam: `seam_id`, `work_stream_id`, `title`, `description`, `business_value`, `acceptance_criteria`, `technical_notes`, `migration_phase`, `story_points`, `effort`, `risk`, `dependencies`, `api_surface`, `jira_issue_type`, and `jira_labels`.

Write `framework_translation_plan.md`. For each detected framework in `frameworks.md`, state the source framework, the evidence path, the target, and whether the target keeps that framework or replaces it. List seams that carry the framework's controllers, aggregates, jobs, notebooks, pipelines, or models.

Deterministic mode fills each spec from the seam's `substitution_note` and `work.steps`, and uses the seam id with underscores turned into spaces as the title. LLM mode writes the product-facing title, description, and acceptance criteria. Every seam still gets one spec. If the specs are empty, write one spec per seam from the seam file, note the gap, and continue.

A plan run stops here. Write `PLAN_COMPLETE.md` listing the artifact files and the sentence "Code translation did not start." Do not write files under `reports/`.

## 6. Code translation

Only a translate run enters this phase. For each seam, in order:

1. Code Writer. Read the seam source. Write target files for that seam only.
2. Skeptical review. Check stubs, wrong types, and missing logic. Write `passed` and `findings`.
3. Test review. The seam needs a happy path, a rule violation, and an edge case, or a finding that names the gap.
4. Functional review. The source business rules that appear in the seam must still be present.

Repeat that cycle up to 3 times for the seam. Then keep the latest files and start the next seam. A review that is missing `passed` or `findings` is a gap, not a stop.

Write the tree at `reports/<project>_<target>/`. `<project>` is the source folder name. Do not modify the source tree.

Deterministic mode transcribes each source declaration into the target language, keeps the original names, and puts source rules in comments. It still writes a test file that names those rules. LLM mode writes idiomatic code for the target and the framework mapping in `framework_translation_plan.md`. If a seam produces no files, write the deterministic transcription, note the gap, and continue.

When every seam has been attempted, stop. Do not open a PR gate.
