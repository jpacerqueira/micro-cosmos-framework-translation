---
name: full-zip-generates-all-available-reports
description: "Generate {run_id}_full.zip" now generates every report/artifact that can be built before zipping — previously it only zipped whatever files happened to already exist on disk, silently omitting anything nobody had clicked yet (2026-08-06)
metadata:
  type: project
---

## The ask

Joao wanted clicking "⚡ Generate `<run_id>_full.zip`" in the "Reports Skills and Code" menu to
act as if every individual item in that menu (Executive summary, Migration briefing, ... down to
Kiro.dev Powers / Claude Code skills / Translated code) had been clicked first — generating
whatever's missing, skipping (not failing) whatever genuinely can't be built yet, and only then
zipping. Explicitly: "if not available a report tries next one" — one report's absence must
never block the others.

## What the full-zip button actually did before this

Researched via a dedicated Explore pass before writing any code (this touches enough files —
`app.py`, `scripts/generate_*.js`, `writer_tools.py`, `pipeline.py`/`driver.py` — that guessing
would have been expensive to get wrong). `generate_zip()`'s `_build_and_save()` in
`micro_cosmos/web/app.py` was **purely** `zipfile.ZipFile` + `run_dir.rglob("*")` — it never invoked
any report generation at all. Reports only ever landed on disk two other ways: eagerly, via
pipeline-phase hooks in `pipeline.py`/`driver.py` (for whichever reports had their artifact
ready at that phase boundary); or lazily, the first time someone opened a report's own
`/runs/{id}/files/{filename}` link (`run_file()`, which runs `node <script> <run_dir> <out_path>`
via `_FILE_TO_SCRIPT`). So a full-zip click before every report link had been opened (or before
every relevant phase had run) produced a zip **silently missing** whichever reports weren't
generated yet — no error, no indication of what was left out.

## What generates each item, and which ones can be produced on demand

Confirmed by reading every `scripts/generate_*.js` and the relevant Python:

- **13 HTML reports** (`_FILE_TO_SCRIPT` map, `app.py`) — Executive summary, Migration briefing,
  Project synthesis, Hotspots & coupling, Dead code & waste, Architecture decisions, Fitness test
  stubs, Telemetry gap analysis (Monitoring), Source security analysis, Output security scan, IR
  graph, Migration sprint plan, Build output features (feature-specs.html). Each needs specific
  artifact JSON(s); 5 of them have an explicit prerequisite in `_REPORT_PREREQUISITES`
  (`feature_specs.json`, `trivy_output_report.json`, or `work_streams.json`) — the rest tolerate
  missing inputs (`tryRead`/`readOpt` with empty-object fallbacks in the Node scripts) and render
  a thinner report rather than failing outright.
- **OpenAPI 3.1 spec / Jira bulk import** — `export_openspec()`/`export_jira()` in
  `micro_cosmos/tools/feature_spec_tools.py`, gated on `feature_specs.json`. These routes only ever
  streamed a response **in memory** — no file was ever persisted under `reports/`, so even if
  someone had already downloaded both, the full zip still wouldn't have contained them. Fixed by
  writing their output to `reports/openspec.yaml`/`reports/jira_bulk_import.json` too.
- **Kiro.dev Powers / Claude Code skills** — `_write_kiro_powers()`/`_write_output_skills()` in
  `micro_cosmos/tools/writer_tools.py` are **pure templates** (embedded Python strings), confirmed to
  read no code artifacts at all — only `source_path`/`source_lang`/`target_lang` (+ a cosmetic
  `seam_name` for skills, used only for naming a skill file, defaulting to `"project"` if none
  exists). `driver.py`'s own `_run_all_seams()` already calls both unconditionally in *both* LLM
  and deterministic modes, before the seam loop even starts — confirming they have zero real
  dependency on translated output existing. Producible on demand regardless of pipeline stage.
- **Translated code** (`write_output_files()`, keyed on `seam_result.json`) — genuinely requires
  real Code Writer/Writer-phase output for at least one seam. No template/placeholder path
  exists for it, unlike Kiro/Skills. **Deliberately not attempted** — synthesizing fake
  "translated code" would be actively wrong, not just incomplete. If it doesn't exist, the zip
  simply won't include it, exactly per "if not available, tries next one."

## Implementation

`micro_cosmos/web/app.py`:
- Extracted the subprocess-invoking logic already inside `run_file()` into `_generate_report_file(script, run_dir, out_path)` — reused by both `run_file()` (unchanged behavior) and the new bulk generator, instead of duplicating the `node <script> <run_dir> <out_path>` call.
- New `_generate_all_available_reports(run, run_dir, reports_dir)`: loops `_FILE_TO_SCRIPT`, skips any file already on disk, skips any whose `_REPORT_PREREQUISITES` artifact is missing, generates the rest — each attempt wrapped in `try/except` that logs via `diagnostics.log.warning(...)` and continues rather than raising, so one script failing/timing out can never abort the others. Then the same skip-if-exists/wrap-in-try-except treatment for OpenAPI/Jira (persisting to `reports/` for the first time) and Kiro Powers/Skills. Translated code is not attempted at all (see above).
- Wired in at the top of `generate_zip()`, gated on `folder_type == "full"` only — the narrower Kiro/Skills/Output-only zip buttons are already scoped to a single folder and don't need the "generate everything" treatment.

No changes to `run.html`/`dashboard.js` — same button, same request/response contract; only the server-side work behind it changed.

## Verified live, against a real run with a genuinely partial artifact set

Used `runs/b2a6cf1f/` (an existing run with `ir_graph.json`/`bounded_context_map.json`/
`seam.json`/`work_streams.json`/`tnas.json` present, but **no** `feature_specs.json`,
`security_report.json`, or `trivy_output_report.json`) — a real partial state, not a contrived
one. `reports/` already had 9 of the 13 HTML reports from earlier eager generation, but no
`monitoring.html`, `security-report.html`, `output-security-report.html`, `feature-specs.html`,
no Kiro Powers dir, no skills dir. `POST /runs/b2a6cf1f/zip/full` (via `curl`, logged in with the
real session cookie) returned `200` in well under a second:

- **Generated, confirmed via mtime and zip contents**: `monitoring.html`, `security-report.html`
  (both succeeded despite `security_report.json` being absent — the scripts' own `tryRead`
  fallbacks render a thinner report rather than failing, exactly as the research predicted),
  `kiro-dev-powers-app-modernization/` (4 full power directories), and a freshly-named
  `<project>_skills/` directory (project name correctly derived from `source_path` via the same
  `_project_dir_name()` the real pipeline uses).
- **Correctly skipped, never even attempted**: `feature-specs.html`, `openspec.yaml`,
  `jira_bulk_import.json` (all gated on the absent `feature_specs.json`), and
  `output-security-report.html` (gated on the absent `trivy_output_report.json` per the app-level
  `_REPORT_PREREQUISITES` table — a deliberately stricter gate than the script's own internal
  tolerance). None of these four appear anywhere in the resulting zip.
- **Left untouched**: all 9 pre-existing HTML reports kept their original mtime (12:41, vs. the
  newly-generated files' 18:37) — confirming "regenerated if not there" only touches what's
  actually missing, never re-does existing work.
- **Zero warnings logged** (`docker logs | grep full-zip`) — every attempted generation
  succeeded; the skip path is a silent `continue`, not a warning, since a missing prerequisite is
  routine, not an error.
- Confirmed via `unzip -l` that the final zip contains every one of the newly-generated
  files/directories, and none of the four correctly-skipped ones.

## Lesson

Researching the exact current mechanism first (a dedicated Explore pass, not assumptions) is
what made the fix minimal and safe: it revealed that OpenAPI/Jira had no persisted file at all
(a separate real gap the original ask wouldn't have surfaced), and that Kiro/Skills were
*already* known to be seam-independent per `driver.py`'s own comments — so generating them
"early" on a full-zip click isn't a hack, it's exercising the exact same call the pipeline
itself already considers safe to make before any seam has translated.
