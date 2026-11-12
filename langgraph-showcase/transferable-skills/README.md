# transferable-skills/

This folder contains the portable agent context for the Micro-Cosmos project. It lets any
developer, Cursor session, or Claude Code instance on a new machine pick up work without
needing the prior chat history.

The files under `memory/` are **project skills**: one markdown file per pattern, bug class,
or architectural decision. They are not Cursor `SKILL.md` packages (`~/.cursor/skills/`).
They travel with the git repo so GitHub clones get them too.

## How to use the skills in this folder

**You do not install them.** There is no `pip install`, no Cursor marketplace step, and no
copy into `~/.cursor/skills/`. They work because they are files in the repo that you (or
the agent) read.

### In a Cursor / Claude Code session on this repo

1. `CLAUDE.md` at the repo root is auto-loaded. That is the short, always-on map.
2. When the task matches a known topic, **read the matching file in `transferable-skills/memory/`**
   before editing. The table below is the index — filenames are the trigger terms
   (`pause-after-planning`, `docker-bind-mount-syspath`, `landing-page-example-chooser`, …).
3. At the start of a large or unfamiliar session, ask the agent:
   ```
   Read transferable-skills/README.md and the memory files relevant to this task,
   then apply them as working context.
   ```
   For a full dump (expensive; only when onboarding): `Read transferable-skills/memory/*.md`.
4. Claude Code slash commands live in `../.claude/commands/` (`/pipeline-context`,
   `/debug-run`, `/add-pipeline-phase`, …). Cursor does not auto-register those; treat
   them as prompt templates — open the `.md` and follow it.

### Which file to open

| If you are about to… | Read |
|---|---|
| Add a launch-time per-run flag (`skip_llm`-shaped) | `memory/pause-after-planning.md`, `memory/auto-approve-gates-and-full-report.md` |
| Add a live mid-run button | `memory/stop-tdd-loop-button.md` (cooperative flag, not `Task.cancel()`) |
| Touch `/`, `/demo`, or the launch form | `memory/landing-page-example-chooser.md` |
| Port a test from `beyond-alchemy` | `memory/cartographer-fixture-must-travel-with-test.md` |
| Probe code inside `docker compose run` with a `/tmp` script | `memory/docker-bind-mount-syspath.md` |
| Change the Claude directory plugin, its icon, or its license text | `memory/claude-pluggin-directory.md` |
| Change the Micro-Cosmos Claude plugin or its pipeline runner | `memory/micro-cosmos-claude-pluggin.md` |
| Diagnose a failed run's artifacts | `../.claude/commands/debug-run.md` |
| Add a pipeline phase or gate | `../.claude/commands/add-pipeline-phase.md` and `CLAUDE.md` |

### Adding a new skill

When a significant pattern, bug class, or decision is made:

1. Add `transferable-skills/memory/<kebab-name>.md` with YAML frontmatter:
   ```yaml
   ---
   name: kebab-name
   description: one sentence, including the date (YYYY-MM-DD)
   metadata:
     type: project
   ---
   ```
2. Add one row to the table in this README.
3. If it changes stable architecture, also update `../CLAUDE.md`.
4. Always append `../changes-log.md` — that file is the full history; `memory/` is the
   reusable lesson.

Keep one topic per file. Do not rewrite old memory files in place unless they are wrong;
supersede them with a pointer at the top (see `memory/nav-new-run-links-to-demo.md`).

## Contents

### Slash commands and project context

| File / Location | Purpose |
|---|---|
| `../CLAUDE.md` (repo root) | Auto-loaded by Claude Code on `claude` startup in this repo. Full project context: architecture, key files, ADK session model, known issues, phase-addition checklist, commit style. |
| `../.claude/commands/pipeline-context.md` | `/pipeline-context` slash command — reads the key architectural files and produces a fresh orientation summary. Run this at the start of any new session. |
| `../.claude/commands/debug-run.md` | `/debug-run <run-id>` slash command — analyses a specific run's artifact state and maps failures to known error patterns. |
| `../.claude/commands/add-pipeline-phase.md` | `/add-pipeline-phase <description>` slash command — 7-location checklist for adding a new phase or gate to the pipeline. |
| `../.claude/commands/regenerate-reports.md` | `/regenerate-reports <run-id>` slash command — regenerates all HTML reports for a run; documents per-script artifact prerequisites and the dual `fitness_suite` format. |
| `../.claude/commands/explain-run.md` | `/explain-run <run-id>` slash command — turns a run's technical artifacts into a plain-English narrative plus a 1-2-3 slide markdown summary, for a stakeholder who won't read HTML reports or JSON. Complements (doesn't duplicate) `scripts/generate_exec_summary.js`'s `executive-summary.html`. See `memory/run-explainability.md`. |
| `../.claude/commands/ci-images.md` | `/ci-images` — test and GHCR publish workflows. One showcase per deploy run. Cloud Run stays `/deploy-gcp`. |
| `../.claude/commands/deploy-gcp.md` | `/deploy-gcp` slash command — walks through deploying or redeploying the all-Cloud-Run GCP environment (GPU LLMGateway + web app). |
| `../.claude/commands/debug-gcp.md` | `/debug-gcp [web\|llmgateway\|connectivity]` slash command — diagnoses a *live* Cloud Run deployment by pulling ground truth via `gcloud`/`gcloud logging read` (service state, revision history, raw container logs, and the `run.googleapis.com/requests` per-request log). `connectivity` cross-checks whether micro-cosmos-web can actually reach micro-cosmos-llmgateway (ingress + VPC egress) — the check that found the 2026-07-14 VPC-egress incident. Complements `/debug-run`, which diagnoses a pipeline *run*'s artifacts, not GCP infra. |

### Memory files (`memory/`)

These are the Claude Code memory files from the original development session, committed here so they travel with the repo. On a new machine, load them manually by copying their content into your Claude Code memory system, or simply read them to orient yourself on the project's accumulated context.

| File | What it captures |
|---|---|
| `memory/project-owner-profile.md` | Project owner role, knowledge level, and working style — how to collaborate effectively on this codebase |
| `memory/claude-response-style.md` | How Claude Code should behave on this project: propose-before-implement, no trailing summaries, technical precision, commit message style |
| `memory/langgraph-runtime.md` | This folder: LangGraph tool loop replaces Google ADK. Read this before `memory/adk-session-architecture.md` |
| `memory/adk-session-architecture.md` | Shared `InMemorySessionService` session model (same API the LangGraph runner implements), the three TDD loop symptoms diagnosed in run `a23b8d06`, and the concurrent-run `run_dir` fix |
| `memory/run-isolation.md` | Per-run isolation boundaries (session service, file system, orchestrator) and the two cross-run shared globals that are not yet isolated |
| `memory/ask-tab-architecture.md` | ASK tab: FAISS RAG + client-side history + direct Anthropic API — zero coupling to the pipeline ADK session |
| `memory/github-actions-ci.md` | GitHub Actions: per-showcase pytest in the app image, and a manual GHCR publish of one showcase |
| `memory/ui-theme.md` | Lighter blue-slate LangGraph palette in this folder; do not copy it onto the ADK showcase |
| `memory/gcp-deployment.md` | All-Cloud-Run GCP deployment (GPU LLMGateway + web app, no Compute Engine VM) — architecture, file map, `$PROJECT` env var convention, known region/quota uncertainty to verify before a live deploy |
| `memory/trivy-security-scanning.md` | Trivy dual-scan architecture (source + output) and the per-language dependency-resolution gaps each ecosystem needs to actually get scanned (Maven/Gradle/C#) |
| `memory/run-explainability.md` | `/explain-run`'s design rationale — plain-English + 3-slide summaries, relationship to `generate_exec_summary.js`, and the jargon-translation rule new stakeholder-facing formats should follow |
| `memory/tdd-writer-hardening.md` | TDD Code Writer loop hardening — 3-attempt cap (was 5), per-seam status/attempts/failure_reason persisted into seam.json, the new "Processing" UI tab, the post-loop single-retry pass for failed seams, and the Gate-5-rejection reset behavior |
| `memory/input-trivy-scan-artifact-button.md` | Why the Artifacts-tab "Input Trivy scan" button needed zero backend/JS changes — the source-side artifact and its serving endpoint already existed, only the button was missing |
| `memory/deterministic-mode-trivy-scan.md` | Source-side Trivy scan now runs in Deterministic mode too — `run_phase()`'s `skip_llm` branch previously returned before ever reaching the Trivy prescan hook, so `trivy_report.json` was LLM-mode-only until this fix |
| `memory/model-reasoning-fast-env-typo.md` | `MODEL_REASONING`/`MODEL_FAST`'s `"gema4-e4b"` typo in `.env.example` silently deadlocked the LM Studio readiness wait for the full 25-minute timeout on every LLM-mode run — how it was diagnosed and fixed |
| `memory/cobol-seam-detection.md` | Why COBOL seam detection produced zero object/boundary seams — three compounding causes (a parser mainline-attribution bug plus two seam-detection assumptions tuned for Java), none of them a tree-sitter/parser-quality gap |
| `memory/processing-tab-deterministic-messaging.md` | PR #18 review fix — the Processing tab's unexplained "pending"/"100% failed" states, split into two distinct root causes (pre-loop-start vs. Deterministic-mode-has-no-fallback), fixed client-side with explicit messaging |
| `memory/databricks-cartographer-classification.md` | PR #23 fix — Cartographer/Architect failing on Databricks notebook estates: two path-classification bugs (an over-broad substring match, numeric-prefixed segments discarded outright) plus a missing generic drill-deeper layer classifier for non-JVM/COBOL estates |
| `memory/databricks-bundle-task-graph-seams.md` | PR #23 feature — seam-by-seam bounded contexts for Databricks Asset Bundles, derived from the bundle's own job/pipeline YAML task graph (task_key → context, depends_on → cross-context calls) instead of path heuristics |
| `memory/scheduler-registry-adf-support.md` | PR #23 feature — generalized the DAB-only task-graph integration into an extensible scheduler registry, added Azure Data Factory pipeline JSON support (two different notebookPath conventions), fixed a CamelCase label-mangling bug |
| `memory/llm-mode-confirm-toggle.md` | New-run form confirms before starting an LLM-mode run, rendered inline inside the run/launch panel (not a page-covering modal) via htmx's `htmx:confirm` event — includes a real `document.body`-in-`<head>` bug caught before shipping, and a design iteration (overlay → inline-in-box) driven by seeing it running live |
| `memory/run-dashboard-graph-resize-and-json-tree.md` | Two run-dashboard UX fixes — drag-to-resize the IR property graph panel (`.dashboard` grid→flex + a resizer handle, `localStorage`-persisted), and a collapsible JSON tree renderer in the Trace tab replacing raw `JSON.stringify` blobs that overflowed the panel instead of wrapping — plus ten follow-ups: a `margin:auto`-on-`<main>` overflow regression, a left/right panel-order swap, a stale-cache false alarm (real `Cache-Control` fix in the next entry), a tab-menu reorder, reusing the JSON tree for the Artifacts tab, Expand-all/Collapse-all buttons above it, detecting JSON embedded in Trace-tab prose text (fenced or raw/unfenced), a contrasting "active" highlight on the clicked Artifacts button, a third flexbox-shrink variant in the Seams tab (one shared scrollbar for all three sections), and a fourth variant (a long unbroken label overflowing into the next column) plus general gate-summary-row spacing |
| `memory/static-asset-cache-busting.md` | `/static/*` had no `Cache-Control` header at all, so browsers could heuristically cache a stale `app.css`/`dashboard.js` across this session's many rapid rebuilds — fixed with a `static_url()` cache-busting Jinja global (`?v=<mtime>`) plus a `Cache-Control: no-cache` override on the static mount |
| `memory/full-zip-generates-all-available-reports.md` | "Generate full.zip" previously just zipped whatever files already existed — now generates every report/artifact it can (13 HTML reports, OpenAPI/Jira, Kiro Powers/Skills) before zipping, skipping anything missing its prerequisite artifact rather than failing; "Translated code" is deliberately never synthesized |
| `memory/nav-new-run-links-to-demo.md` | **Superseded 2026-09-16** by `landing-page-example-chooser.md` — this was the 2026-08-06 one-line nav change that pointed "New run" at `/demo` while `/` still served `index.html` |
| `memory/stop-tdd-loop-button.md` | "Stop TDD loop" button for LLM-mode runs — a cooperative `stop_requested` flag (not `Task.cancel()`) checked at two loop-top checkpoints in `driver.py`, so PR Reviewer/Gate 5 still run with whatever seams completed; a real flag-leak bug (into the post-loop retry pass, and into a future Gate-5-rejection re-run) found and fixed during testing |
| `memory/effort-estimates-doubled.md` | Effort/story-point estimates doubled at their single source (`_work_for_seam` in `seam_tools.py`); two pre-existing enum-drift bugs fixed alongside it (deterministic mode always showing `effort: "MEDIUM"`, a report badge always defaulting to the blue "MEDIUM" style) |
| `memory/target-architecture-seams-panel.md` | New "Target architecture & features" section in the Seams tab — reuses `tnas.json`/`feature_specs.json` (already computed, never rendered as more than raw JSON before); two independent sub-sections since the artifacts land at different phases; a case-sensitivity gotcha caught before shipping, same shape as the same-day effort-badge bug |
| `memory/context-window-source-search.md` | Fixed a real `ContextWindowExceededError` incident in the TDD writer loop — five compounding root causes (a dead `seam_name` filter, a missing session reset, a redundant tool-response echo, no client-side size guard, and no source-code vector index) fixed together; new FAISS-backed `search_relevant_source` tool built on the existing (previously ASK-tab-only) retrieval infrastructure |
| `memory/review-submit-tool-defaults.md` | `/debug-run` diagnosis of a real run — all three TDD-loop reviewers failing every iteration, traced to `submit_code_review`/`submit_test_review`/`submit_functional_review` missing Python defaults on `run_dir`/boolean flags, causing ADK to silently reject the tool call whenever a model omitted one; same known-but-unfixed bug class as `submit_security_findings` |
| `memory/samuel-mbah-review-fixes.md` | Fixed 5 of 7 code-review findings — consolidated 3 copies of a known unresolved concurrency issue into one `ContextVar` (`run_context.py`), 2 more missing-tool-default instances, a seam-file-matching bug that turned out worse than reported (`side_a`/`side_b` mean different things per seam type), a defensive case-fix, and an in-memory index cache; 2 findings confirmed intentional, not bugs |
| `memory/debrand-generic-integration-categories.md` | Removed Slack/BambooHR references from generated reports and the Cartographer classifier — full-repo audit found exactly 4 lines across 2 files; broadened the underlying folder-name detection to generic HR/ERP/CRM/comms-alerting categories rather than just relabeling text |
| `memory/cqrs-framework-detection.md` | Broadened CQRS/event-sourcing framework detection to 6 named frameworks (Axon, Eventuate, Lagom, MediatR, NServiceBus, Wolverine) via a new manifest+annotation two-tier scan feeding `ir_graph.json`'s `cqrs_framework_hints`; found and fixed a silently-regressed Axon-specific parser (a merge had wiped it, `tests/test_java_axon.py` was failing against `HEAD`) plus two more real gaps (missed constructors, missed package-private methods) surfaced only by running the real Axon example fixture, not the synthetic unit test |
| `memory/openapi-rename-and-openspec-artifact.md` | Renamed the mislabeled OpenAPI export (was internally "openspec"); added a real Fission-AI/OpenSpec artifact alongside Skills/Kiro Powers with force-regenerate semantics (fixing a silent no-op "Regenerate" bug class found, but not fixed, in the existing two); aligned Security/Logging content across all three via shared content constants; two real bugs (a `fitness_suite` shape assumption, a fallback-return-value clobber) caught only by a live deterministic-mode run, not the unit tests |
| `memory/pr27-review-axon-dedup-and-readme.md` | Fixed 2 blocking PR #27 review findings — a real method-ID dedup-order bug where two sequential regex passes let source position lose to loop order, and 3 stale `/export/openspec` README references left over from the OpenAPI rename |
| `memory/ultra-review-pr26-pr27-29-findings.md` | `/code-review` at max effort across the full PR #26/#27 range — 29 findings fixed: wildcard Axon imports, nested-class ownership misattribution, regex backtracking, SQL DDL detection, markdown table injection, WHEN/THEN case/substring bugs, explicit-null handling, an async-off-the-event-loop fix, a CQRS registry de-hardcoding, an OpenSpec menu cleanup, and 6 real bugs in the Java Axon example app (an IDOR-style command-routing bug, an open GraphQL IDE + a bearer-token-propagation no-op, a null-unsafe UUID parse, a NATS ack/nak duplicate-publish risk, and a PII log-redaction gap) |
| `memory/env-setup-docs-and-skip-llm-fix.md` | New README Quickstart "step 0" documenting `.env` setup for new joiners; found and fixed a real bug along the way — `docker-compose.yml` hardcoded `SKIP_LLM`/4 other values as literal strings instead of `${VAR}` substitutions, so the documented `SKIP_LLM=false docker compose up` command never actually worked |
| `memory/auto-approve-gates-and-full-report.md` | Two features planned via EnterPlanMode/ExitPlanMode — an auto-approve-gates toggle (single `open_gate()` injection point, mirrors `skip_llm`'s data-flow pattern) and a 14th combined report `full-app-migration-report.html` (status table + iframe/`<pre>`-embedded content of every other report/artifact/Kiro-Power/OpenSpec/Skill); plus 6 pre-existing test failures actually fixed (not just documented), including a real `_direct_tool_fallback` gap that could let a crashed reviewer agent's stale prior-seam review silently pass the TDD loop |
| `memory/c-source-support-and-gnucobol-golden-master.md` | Real C source parsing (tree-sitter deep parser + call extractor) and GnuCOBOL added to the container for golden-master/differential testing; two bugs invisible until "c" existed as a source language (`_extensions_for` fuzzy-match, `.c`/`.h` id collision), plus BUG-3/BUG-6 container-toolchain bugs reproduced and fixed along the way |
| `memory/test-agent-sandboxed-execution.md` | Test Agent (#48/#52) — real per-language test execution now gates the TDD loop via a sandboxed subprocess and a Trivy-prescan-style pipeline hook; 5 sandboxing bugs found building it plus 5 more (event-loop blocking, dead validation branch, a HOME override defeating its own caching purpose, overbroad chmod, dead config entry) found in a follow-up review pass |
| `memory/real-signal-validation-and-fallback-gaps.md` | 4 real bugs (#53/#54/#57/#58) from running against a real local LLM — presence-only artifact validators miss schema drift, Code Writer crash-spirals on plain-text replies, dotted seam ids break scaffolding, copied retrieval excerpts pass as implementation; also a real GitHub gotcha — a comma-separated `Closes #a, #b, #c` only auto-links the first issue |
| `memory/semantic-equivalence-agent.md` | Semantic Equivalence Agent (#49) — target-side differential testing via a per-language (Python/Java/Kotlin/C#) CLI/JSON harness against Code-Writer-supplied test vectors; also completes BUG-10 (#59)'s Functional Review half, which an earlier premature issue-close had missed |
| `memory/crash-recovery-post-phase-hooks-and-gate-validity.md` | run_phase()'s crash-recovery path returned before reaching a phase's own post-phase hooks, silently degrading LLM-mode below the deterministic-mode floor on 3 phases (#60/#61/#62); open_gate() now runs the same artifact-validity check and shows a real warning banner instead of letting a crash-cascade leftover reach a human reviewer looking like a normal result (#63) |
| `memory/pause-after-planning.md` | Launch-time "Pause after planning" toggle — ends the run after Gate 4.5 instead of the seam TDD loop, still downloadable; copies `auto_approve_gates` persistence (five call sites), not `stop_requested`; reuses `pipeline_completed`; zero-seam fixture writes `feature_specs_result.json` not `feature_specs.json` (2026-09-16) |
| `memory/landing-page-example-chooser.md` | `demo.html` is now served at `/`; `index.html` deleted; `/demo` 308-redirects; `/demo/*` API sub-routes keep their paths; accepted trade-off is no free-text `source_path` field; copying an estate into `examples/` makes it a picker card (2026-09-16) |
| `memory/cartographer-fixture-must-travel-with-test.md` | Cartographer 40%-concentration regression was ported without `examples/AxonFramework_AxonBank`; `java-axonframework-example-app` is a different codebase and cannot stand in; beyond-alchemy ports must confirm the named estate exists in this repo (2026-09-16) |
| `memory/docker-bind-mount-syspath.md` | `python /tmp/p.py` inside the container imports the image's installed `micro_cosmos`, not the bind-mounted source — `sys.path[0]` is the script directory; use `PYTHONPATH=/app` or pytest (2026-09-16) |
| `memory/claude-pluggin-directory.md` | Micro-Focus Claude directory plugin in `claude-pluggin/`, submitted from its own public repo; square listing icon at `.claude-plugin/icon.png`; do not tell the plugin to read environment files or copy private values (2026-10-14) |
| `memory/micro-cosmos-claude-pluggin.md` | Micro-Cosmos Claude plugin in `micro-cosmos-claude-pluggin/`; runs the LangGraph pipeline; plan is pause-after-planning; translate stops when the seam tree exists and does not open the PR gate (2026-10-14) |

**To load on a new Claude Code session:**
```
Read transferable-skills/memory/*.md and apply their contents as working context for this project.
```

## How to use on a new machine

1. Clone the repo and open it in Claude Code (`claude` CLI or VS Code extension).
2. `CLAUDE.md` is loaded automatically. Claude Code already has full project context.
3. Run `/pipeline-context` to verify Claude Code has the current phase order and any recent changes in scope.
4. Run `/debug-run <run-id>` when diagnosing a failed run from Docker logs.
5. Run `/debug-gcp [web|llmgateway|connectivity]` when diagnosing a live Cloud Run deployment issue instead — e.g. a service that won't start, an LM Studio/vLLM readiness poll that never succeeds, or the web app not being able to reach the GPU service.

## How to hand off to a colleague

1. Share the repo (the files above are committed).
2. Tell them to run `/pipeline-context` first.
3. Point them to `changes-log.md` for the full decision history — it is the authoritative record of every change, bug analysis, and architectural decision made on this project.

## Keeping this current

When a significant new pattern, bug class, or architectural decision is made:
- Update `CLAUDE.md` (the "ADK session architecture" and "Adding a new pipeline phase" sections are the most likely to change)
- Add to `changes-log.md` (already maintained per every session)
- Update the relevant slash command if a new workflow emerges

The `changes-log.md` is more granular than `CLAUDE.md` — `CLAUDE.md` carries stable architecture facts, `changes-log.md` carries the full history.
