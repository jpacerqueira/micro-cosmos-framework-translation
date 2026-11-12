# Micro-Cosmos — Claude Code Context

**Project:** Source-to-source application framework translation  
**Stack:** Python 3.12, LangGraph, LiteLLM gateway, FastAPI, HTMX, WebSocket, FAISS  
**Branch:** feat/security-analysis-tab  
**Entry point:** `micro-cosmos-run` CLI / `docker compose up`

---

## What this project does

Micro-Cosmos translates a source codebase (Java, Python, C#, COBOL, PHP, or C — Kotlin and Go are target-only, no source-side parser) into a target language through an 11-agent agentic pipeline with 6 human approval gates. Agents run sequentially; gates block until an engineering lead approves or rejects via the web UI.

---

## Commands

```bash
uv sync --extra dev                           # install deps (project uses uv, see uv.lock)
ruff check .                                  # lint (config in pyproject.toml: E,F,W,I,B,UP; line-length 100)
mypy micro_cosmos                             # type check

pytest                                        # full test suite (asyncio_mode=auto, testpaths=tests)
pytest tests/test_pipeline.py                 # single test file
pytest tests/test_pipeline.py::test_name -v   # single test case

micro-cosmos-run --help                       # CLI entry point (installed console script; also `micro-cosmos`)
```

No JS package manager/build step — `scripts/generate_*.js` are standalone Node scripts invoked by the pipeline itself (`(run_dir, out_path)` CLI convention), not part of a frontend build.

---

## Pipeline phases (in order)

```
Observer → Gate 1 → Cartographer → Gate 2 → Architect → Gate 3
→ Security → Gate 4 → Feature Specifier → Gate 4.5 "Planning"
→ [Skills + Kiro.dev Powers created once]
→ for each seam: Code Writer → TDD loop (Skeptical/Test/Functional Review) → Writer
→ PR Reviewer → Gate 5 → Trivy output scan → Done
```

| Phase | Agent | Key output |
|---|---|---|
| Observer | `observer_agent` | `ir_graph.json` |
| Cartographer | `cartographer_agent` | `bounded_context_map.json`, `seam.json`, `work_streams.json` |
| Architect | `architect_agent` | `tnas.json`, HTML reports |
| Security | `security_agent` | `security_report.json` |
| Feature Specifier | `feature_specifier_agent` | `feature_specs.json` |
| Code Writer | `code_writer_agent` | `seam_result.json` per seam |
| Skeptical/Test/Functional Review | reviewer agents | `*_review.json` per seam |
| Writer | `writer_agent` | `reports/<project>_<lang>/` |
| PR Reviewer | `pr_reviewer_agent` | `review_report.json` |

All artifacts land in `runs/<run-id>/`. HTML reports and translated code land in `runs/<run-id>/reports/`.

---

## Key files

| File | Role |
|---|---|
| `micro_cosmos/orchestration/pipeline.py` | `MicroCosmosOrchestrator`, `PipelinePhase` enum, `run_phase()`, `open_gate()`, `reset_session()` |
| `micro_cosmos/orchestration/driver.py` | `run_full_pipeline()` — top-level async generator; `_run_all_seams()`, `_run_tdd_loop_for_seam()`; `_wait_for_llm_ready()` gates a fresh LLM-mode run on the configured backend reporting the target model ready (LM Studio's native REST API when present, otherwise a plain `/v1/models` probe — the path Ollama takes); both seam-loop functions check `orch.stop_requested` cooperatively — see "Stop TDD loop" below |
| `micro_cosmos/web/app.py` | FastAPI app, `RUNS` dict, gate approval/rejection endpoints, SSE stream, chat endpoint; `static_url()` Jinja global + `CacheControlledStaticFiles` (cache-busting for `/static/*`); `POST /runs/{run_id}/stop-tdd-loop` sets the cooperative stop flag — see "Stop TDD loop" below |
| `micro_cosmos/gates/__init__.py` | `GATE_DEFINITIONS` list — all 6 gates |
| `micro_cosmos/tools/run_context.py` | `set_run_dir()`/`get_run_dir()` — `ContextVar`-backed, shared by `coder_tools.py`/`coding_loop_tools.py`/`source_tools.py` (each re-exports it) so concurrent runs don't race on a plain module global |
| `micro_cosmos/tools/coder_tools.py` | `submit_seam_translation` |
| `micro_cosmos/tools/coding_loop_tools.py` | `submit_code_review`, `submit_test_review`, `submit_functional_review` |
| `micro_cosmos/tools/writer_tools.py` | `write_output_files`, `_write_output_skills`, `_write_kiro_powers` |
| `micro_cosmos/retrieval/chat.py` | ASK tab: FAISS RAG + Anthropic API direct call, client-side history |
| `micro_cosmos/web/static/js/dashboard.js` | All UI logic: gate panels, seam feed, trace, ASK tab, phase strip |
| `micro_cosmos/web/static/js/run-confirm.js` | Confirms before starting an LLM-mode run (`htmx:confirm` handler, scoped per-form); loaded on every page via `base.html` |
| `micro_cosmos/web/templates/run.html` | 17-pill phase strip, Reports dropdown, tab panels; `.dashboard` = tab-pane-area (left) + `.dashboard-resizer` + `.graph-panel` (right, IR property graph) |
| `changes-log.md` | Authoritative record of every change, bug fix, and architectural decision |

---

## How to run

```bash
docker compose up --build           # full stack — Deterministic mode by default (SKIP_LLM=true)
SKIP_LLM=false docker compose up    # LLM mode (real model calls)
```

Web UI at http://localhost:8080. Start a run from the landing page `/` (the example chooser — `demo.html`; the old `/demo` URL 308-redirects here).

---

## Session architecture — important

All 11 agents share a single `InMemorySessionService` session (`"source-session"`) per `MicroCosmosOrchestrator` instance. Each agent runs through its own LangGraph `Runner` (`micro_cosmos/langgraph_runtime.py`) but reads/writes the same session. The runner is a tool-calling `StateGraph`: one `agent` node (LiteLLM completion against this folder’s gateway) and one `tools` node. `build_llm()` returns `GatewayModel` with the same `.model` / `._additional_args` shape the ADK `LiteLlm` object had, so engine tests stay valid. Deterministic mode never enters the graph.

**Known issue (partially fixed):** Session history accumulates across agents within a run. Fixed in TDD loop by calling `reset_session()` before each reviewer phase — this clears event history while preserving state keys (`source_path`, `source_lang`, `target_lang`, `run_dir`, `current_seam`) and all artifacts.

**Fixed (2026-08-10):** `_current_run_dir` used to be a separate process-wide module global in each of `coder_tools.py`, `coding_loop_tools.py`, and `source_tools.py` — concurrent CODE_WRITER phases from two simultaneous LLM runs would have raced. All three now share `micro_cosmos/tools/run_context.py`'s `contextvars.ContextVar`-backed `set_run_dir()`/`get_run_dir()`; since each `Run` gets its own `asyncio.Task`, two concurrent runs get independent values with no locking.

---

## Gate 4.5 — Planning gate

Added 2026-06-29. Feature Specifier runs after Gate 4, before the seam TDD loop. Gate 4.5 is the human checkpoint between analysis and code generation. On rejection: Feature Specifier re-runs with a `RejectionConstraint`. On approval: seam loop begins. Works identically in LLM and deterministic mode (gate is a human checkpoint, not an LLM call).

---

## Run modes

- **Deterministic mode** (default — `Settings.skip_llm: bool = True`): agents use symbolic fallbacks; Code Writer and Writer are skipped; Gate 4.5 opens normally; also governs the ASK tab (extractive-only answers) and embeddings (disabled, lexical fallback), not just the pipeline
- **LLM mode** (`SKIP_LLM=false`): all 11 agents make model calls. The web UI's new-run toggle follows this same global setting — Cloud Run's `deploy_cloudrun-micro-cosmos-app.py` deliberately keeps its own `SKIP_LLM=false` fallback (not the new default) to protect the production LLM pipeline; see `transferable-skills/memory/gcp-deployment.md`. A fresh run (not a gate-restart) in LLM mode waits up to `Settings.llm_ready_timeout_seconds` (default 1500s) for the backend to report the target model ready before sending real traffic — Compose **llm-gateway** via `GET /v1/models` only (`skip_native`, no LM Studio `/api/v0/models` probe on the proxy); direct LM Studio via its native REST API (`"loaded"` state); Ollama/vLLM via a `/v1/models` 200 — best-effort, never blocks indefinitely; see `_wait_for_llm_ready()` in `driver.py`
- **Compose `llm-gateway`** (added 2026-09-22): second service `ghcr.io/berriai/litellm:main-stable`. App `LLM_ENGINE=gateway`, `LLM_BASE_URL=http://llm-gateway:4000/v1`. Active profile **ollama** / `gemma4:latest`; dormant YAML `lmstudio` / `vllm` / `bedrock` / `vertex`. Switch `LLM_PROFILE` + restart gateway only. UTC JSON timeframes in `./logs/llm-gateway.log`. Cloud Run deploy scripts are unchanged (still talk to LM Studio/vLLM/Vertex directly).
- **`llm_engine=vertex`** (added 2026-09-08): routes `build_llm()` through Google Cloud Vertex AI (Gemini via Model Garden) **on the app process** instead of a self-hosted LM Studio/vLLM Cloud Run service — auth is ADC/IAM, not an API key, and no GPU-backed LLMGateway service is deployed for this option. `driver.py`'s `_wait_for_llm_ready()` is skipped entirely for this engine (no local GPU cold start to wait for). See `transferable-skills/memory/vertex-ai-engine-support.md`. For local Compose, prefer `LLM_PROFILE=vertex` on the proxy instead.

---

## Test Agent — real sandboxed test execution gates the TDD loop (2026-09-08)

Before PR #73, `fitness_runner.py` could run a seam's real tests but the result was written to `seam_result.json` and never consulted by the actual TDD gate — a seam could pass on LLM/static judgement alone while its real tests failed. Now: `_run_test_execution_prescan` (`pipeline.py`, modeled on `_run_trivy_prescan`) fires before `TEST_REVIEW` in both `skip_llm` and LLM-mode paths, calls `run_accumulated_test_execution()` (`fitness_runner.py`) via `asyncio.to_thread` (it shells out synchronously — calling it directly from an `async def` would block the whole app, every concurrent run, for the subprocess's full duration), and writes `test_execution.json`. `submit_test_review()` reads that file directly off disk (never as an LLM-supplied parameter — the usual ADK-footgun avoidance) and force-corrects its own `passed` field.

`assemble_accumulated_pr_files()` gives real execution the whole accumulated project (current seam's files merged onto every prior seam's materialized output), not just the current seam's diff — build-file collisions merge via the same logic `write_output_files()` uses.

The test subprocess runs sandboxed: dropped to an unprivileged `sandboxrunner` UID (`_SANDBOX_UID = 10001`, must match the Dockerfile's `useradd`) via `_sandbox_preexec`, with `HOME` pointed at `sandboxrunner`'s real persistent home directory (`_SANDBOX_HOME`) *only* when actually running as root inside the container — this is what lets Maven's `~/.m2/repository` cache persist across seams/TDD iterations instead of being wiped every call. Outside the container (local dev/CI, already unprivileged) `HOME` falls back to the per-call temp dir, the old behaviour. `_make_world_writable()` chowns the accumulated tree to `_SANDBOX_UID` specifically, not a blanket `chmod 0o777`.

This is the same body of work that closed BUG-3 (#52) and BUG-6 (#55) — see `transferable-skills/memory/test-agent-sandboxed-execution.md` for the full incident history (5 sandboxing bugs found building it, plus 5 more found in a subsequent review pass, PR #74).

The **Semantic Equivalence Agent** ("Verifier", #49) reuses this same sandboxing infrastructure directly (`assemble_accumulated_pr_files`, `_sandbox_env`/`_sandbox_preexec`) for target-side differential testing: given optional `test_vectors` on `submit_seam_translation`, `micro_cosmos/tools/equivalence_tools.py` invokes the seam's own generated code through a per-language (Python/Java/Kotlin/C#) CLI/JSON harness and compares real output against expected with a numeric-tolerant diff. Wired identically to Test Review — a `_run_equivalence_prescan` hook (same `asyncio.to_thread` pattern) writes `equivalence_result.json` before `FUNCTIONAL_REVIEW`, and `submit_functional_review` force-corrects `passed` from it (plus `test_execution.json`, completing BUG-10/#59's other half). True source-vs-target execution (running the *original* legacy code) is explicitly out of scope — see `transferable-skills/memory/semantic-equivalence-agent.md`.

---

## New-run confirmation (LLM mode)

`demo.html` (served at `/`) declares the `skip_llm` toggle markup and `hx-post="/runs"` declaratively via htmx — it has no custom JS submit handler. (Until 2026-09-16 `index.html` carried a duplicate of this form; that page was removed when the example chooser became the landing page, so there is now exactly one launch form.) `run-confirm.js` (loaded in `base.html`'s `<head>`) hooks htmx's `htmx:confirm` event to show an inline confirmation panel (`.llm-confirm-inline`, last child of each page's own `<form>`, right after the submit button — *inside* the existing run/launch box, not a page-covering modal) whenever the toggle is left in LLM mode. Deterministic-mode submits are unaffected. This is the app's first confirm/modal-style UI convention; if a future confirmation is needed elsewhere, extend this pattern (scoped per-form `.llm-confirm-inline` lookup) rather than introducing a second one.

**Gotcha for any future `<head>`-loaded script:** don't reference `document.body` at top-level scope — it's still `null` while a classic (non-`defer`) script in `<head>` executes, since `<body>` hasn't been parsed yet. Listen on `document` instead (always exists; custom events still bubble to it). See `transferable-skills/memory/llm-mode-confirm-toggle.md` for the full incident this was caught from.

---

## Stop TDD loop (LLM-mode runs)

`POST /runs/{run_id}/stop-tdd-loop` sets `MicroCosmosOrchestrator.stop_requested: bool` (plain bool, not an `asyncio.Event`), checked cooperatively at two points in `driver.py`: top of each TDD iteration (`_run_tdd_loop_for_seam`) and top of each seam (`_run_all_seams`). This is deliberately **not** `Task.cancel()` (what `restart()` uses) — cancelling the task aborts the whole `run_full_pipeline()` generator and never falls through to PR Reviewer/Gate 5, whereas the cooperative flag lets `_run_all_seams()` `return` early so the pipeline's existing post-loop code (PR Reviewer → Gate 5) still runs with whatever seams completed. **Both** checkpoints must reset the flag (not just one) — see `transferable-skills/memory/stop-tdd-loop-button.md` for a real bug where resetting it in only one place let it leak into a later Gate-5-rejection re-run of `_run_all_seams()`. The button itself is static markup in `run.html`, rendered only `{% if not run.skip_llm %}`, unlike the dynamically-injected `gate-restart` button.

---

## Pause after planning

`pause_after_planning: bool` (added 2026-09-16) is a launch-time toggle in the `/` Launch-analysis
panel. When set, `run_full_pipeline()` ends the run immediately after Gate 4.5 resolves instead of
entering the seam TDD loop — analysis and planning complete, no code translation.

It is threaded through the exact same five call sites as `auto_approve_gates` (`POST /runs` `Form`
param → `Run.__init__` → `run_meta.json`, `_restore_run()`'s safe `.get(..., False)`, and
`Run.restart()`), for the same reason: it is a fixed per-run setting that must survive a restart,
and `Run` — not the orchestrator, which is discarded and rebuilt — is the durable source of truth.
This is deliberately **not** the `stop_requested` pattern (see "Stop TDD loop"), which models a
live mid-run action.

**Three things to know before touching it:**
1. The check sits in `driver.py` *after* the Gate 4.5 block fully resolves — after its
   rejection/re-specify `while` loop and its ESCALATED check. Moving it earlier would break
   Gate 4.5 rejection cycles, which must keep working unchanged.
2. It is guarded by the same `start_phase not in (CODE_WRITER, PR_REVIEWER)` condition as the
   blocks around it, so an explicit restart into `CODE_WRITER` still bypasses the pause. A paused
   run is stopped, not sealed — a "continue into code generation" affordance can be added later
   with no redesign.
3. It emits the ordinary `pipeline_completed` event (with `paused_after_planning: true` and a
   `skipped_phases` list) rather than a new event kind. That is what keeps the zip/report
   endpoints working untouched: `generate_zip` never gated on run completion, and
   `_REPORT_PREREQUISITES` already skips reports whose input artifact is missing — so a paused run
   downloads fine, minus `output-security-report.html`, which legitimately needs the post-Gate-5
   Trivy scan. `dashboard.js` uses the flag only to reword the completion card and to mark the
   seven unreached pills `.skipped` (struck-through/dashed), so a deliberate pause doesn't read as
   a stalled run.

---

## Landing page: `/` is the example chooser

Changed 2026-09-16. `demo.html` is served at `/`; the former `index.html` landing page (a
manual free-text `source_path` form) was **deleted**, and `/demo` is now a 308 redirect to `/`.
Runs are launched only from example cards, the GitHub-URL box, or a zip upload — there is no
free-text path field any more (accepted trade-off; all three routes land content in `examples/`).

The `/demo/detect-lang`, `/demo/upload` and `/demo/fetch-github` **API sub-routes deliberately keep
their paths** — they are called by the page's own JS, and renaming them would churn the template
for no user-visible gain. Both login redirects and the single nav "New run" link point at `/`.

---

## Auto-approve gates (LLM-mode runs)

`auto_approve_gates: bool` + `auto_approve_reviewer_name: str` are plain per-run attributes threaded through the exact same three call sites as `skip_llm` — `POST /runs` (`Form` params → `Run.__init__` → `run_meta.json`), `_restore_run()` (reads them back with safe `.get(..., False/"")` defaults), and `Run.restart()` (re-supplies them to the freshly-constructed `MicroCosmosOrchestrator`) — because `Run`, not the orchestrator instance, is the durable source of truth across a restart (the orchestrator itself is discarded and rebuilt). This is the `skip_llm` pattern, not the `stop_requested` pattern (see "Stop TDD loop" above) — a fixed per-run setting, not a live mid-run mutation.

The single injection point is `MicroCosmosOrchestrator.open_gate()` (`pipeline.py`): right after emitting `gate_opened` and before `await self._gate_events[gate_id].wait()`, if `self.auto_approve_gates` is set it calls `self.approve_gate(gate_id, reviewer_name=self.auto_approve_reviewer_name, notes="auto-approved to next gate")` — which sets the gate's `asyncio.Event`, so the following `.wait()` returns immediately and every downstream branch of `open_gate()` (rejection/escalation handling, `gate_resolved` emission) runs completely unmodified. This applies uniformly to all 6 gates since they all funnel through this one method. The `gate_resolved` event payload also now carries `reviewer_name`/`notes` (sourced from `state.approvals[-1]`), which `dashboard.js`'s `markGateResolved()` uses to render "Approved by X: notes" for a gate that was never manually clicked (a manual approval gets this text from the approve endpoint's htmx-swapped response instead — the two paths are merged by only filling `.gate-result` when it's still empty).

Server-side validation (reject `auto_approve_gates=true` with a blank/whitespace reviewer name, 400) lives in `create_run()`, matching the `<div class='warn'>...</div>` 400-response convention already used by the gate approve/reject/restart endpoints — not the `.error-card`/500 convention `create_run` uses for actual runtime failures. The reviewer-name field appearing (and being required) only when the toggle is on is the deliberate confirmation step — no second modal/confirm dialog was added on top of it; `run-confirm.js` (the existing LLM-mode confirm) is untouched and unrelated to this flag.

---

## Start a demo run from a GitHub URL (download-as-zip)

`POST /demo/fetch-github` (`micro_cosmos/web/app.py`) lets the demo page fetch a public GitHub repo as
a zip via `codeload.github.com` — no `git` binary in the image — extract it into `examples/`, and
select it exactly like a manually-uploaded zip. `demo.html`'s GitHub-URL box occupies the top slot
(right below the hero); the pre-existing drag-and-drop zip-upload box moved to the bottom of the
page, below the full example grid, as a full-width `grid-column: 1 / -1` row inside `.demo-shell`.

**SSRF is closed off by construction, not by an allowlist check on user input**: the endpoint only
ever accepts a `github.com`/`www.github.com` URL, and the codeload/API URLs it fetches are built
server-side from the regex-parsed `(owner, repo, ref)` — the client never supplies the outbound
host directly, so there's no host string to smuggle a redirect through. Extraction logic is shared
with `/demo/upload` via `_extract_zip_to_examples()` (refactored out of `demo_upload_example()`,
same common-root-stripping + path-traversal guard as before), which also gained a new
uncompressed-size zip-bomb guard (500MB cap, checked via `ZipInfo.file_size` before any bytes are
written) that benefits both callers.

`github_url: str = ""` follows the exact `auto_approve_gates` persistence pattern (see above) —
threaded through `Run.__init__` → `create_run()`'s `run_meta.json` write → `_restore_run()`'s safe
`.get("github_url", "")` default. Purely descriptive (shown as a "GitHub source ↗" badge on
`run.html`); `source_path` is already a resolved local directory by the time `create_run()` runs,
so no pipeline code changes. See `transferable-skills/memory/github-url-demo-run.md` for the full
design, the mocked-network test strategy, and live verification.

---

## Run dashboard layout — resizable panel, JSON tree, two real bugs fixed (2026-08-06)

`run.html`'s `.dashboard` is a flex row (not grid) with three children in this order: `.tab-pane-area` (Gates/Seams/Trace/Processing/Artifacts/Ask/Diagnostics — **left**), `.dashboard-resizer` (a drag handle), `.graph-panel` (IR property graph, cytoscape `#cy` — **right**). Drag the resizer (mouse or arrow keys, focused) to resize; the chosen width persists to `localStorage` (`source:graph-panel-width`). The Trace tab renders tool-call args/responses via `jsonTreeHtml()` (`dashboard.js`) — nested collapsible `<details>`, not raw `JSON.stringify` — so large/deeply-nested payloads stay readable instead of overflowing. See `transferable-skills/memory/run-dashboard-graph-resize-and-json-tree.md`.

**Two real bugs found and fixed in this same area, both worth knowing before touching this layout again:**

1. **A stray `margin: 0 auto` on `<main>`.** The generic `main { margin: 0 auto; }` rule (for centering non-run pages) was never overridden by `body.run-page main`. `margin: auto` on a flex item **disables cross-axis stretch** — a different, less-known gotcha than `min-width: auto` (the one everyone reaches for first). This made `<main>` shrink-to-fit its content's preferred width (driven by the graph canvas several levels down) instead of stretching to the viewport, silently overflowing. Fixed with an explicit `margin: 0` on `body.run-page main`. `min-width: 0` was tried first (the textbook fix for the *other* gotcha) and measured to make zero difference — if a flex child overflows its parent despite `min-width: 0` everywhere, check for a stray `margin: auto` next.
2. **No `Cache-Control` on `/static/*`.** Plain `StaticFiles(...)` sends only `Last-Modified`/`ETag`, so browsers fall back to heuristic caching — a stale `app.css` can be served with zero server round-trip for a while. Fixed two ways: `static_url(path)` (a Jinja global in `app.py`) appends `?v=<mtime>` to every `/static/...` reference in `base.html`/`login.html`/`run.html`, so a changed file always gets a new URL; and `CacheControlledStaticFiles` (a `StaticFiles` subclass) forces `Cache-Control: no-cache` on every response as a second layer. If a UI change looks "applied on disk but not in the browser," hard-refresh before assuming the code is wrong.

---

## Full report (`full-app-migration-report.html`)

A 14th report, always last in the Reports menu (after "Translated code"), generated by
`scripts/generate_full_report.js` — a plain Node script following the same `(run_dir, out_path)`
CLI convention as every other `scripts/generate_*.js`. It's a status + content dump: a table at
the top listing every other HTML report, every `*.json` artifact under the run root, and the Kiro
Powers/OpenSpec/Claude Code Skills output — in the same top-to-bottom order the Reports menu lists
them — followed by the full content of everything that table lists.

The 13 other HTML reports are embedded via `<iframe src="{filename}">` (a relative path — resolves
correctly both live via `/runs/{id}/files/{filename}` and when `full-app-migration-report.html` is opened
directly from an extracted `full.zip`, since every report lands as a flat sibling file under
`reports/`), not by extracting and merging their inner markup — 4 of the 13 report scripts predate
`report_common.js`'s shared `htmlShell` and inline their own HTML, so a merge would need
per-script special-casing and could silently break for a future report script. Kiro/Skills/OpenSpec
markdown files render as raw text in a `<pre>` block (no Markdown-rendering dependency exists
anywhere in this codebase's report scripts). Every embedded report/file sits inside a collapsed
`<details>` so the page stays scannable.

`full-app-migration-report.html` is wired in three places in `app.py`: it's the **last** key in `_FILE_TO_SCRIPT`
(guarantees the other 12 reports are attempted first within `_generate_all_available_reports()`'s
loop); it has **no** entry in `_REPORT_PREREQUISITES` (tolerant/best-effort, like `monitoring.html`);
and `run_file()` special-cases it to **always regenerate**, bypassing the `if not out_path.exists()`
skip every other report uses — its only value is being an accurate live snapshot, so a stale cached
copy would defeat the point (same precedent as `_write_openspec()`'s always-regenerate behavior).
`_generate_all_available_reports()` also has a second, unconditional regeneration call for it at the
very end (after OpenAPI/Jira/Kiro/Skills/OpenSpec are generated) — its own turn inside the main loop
runs *before* those exist yet, so without this second call the copy bundled into `full.zip` would
show them as "not yet generated" on the very first "Generate full.zip" click.

---

## Seam types

`seam.json`'s seams carry one of five `type` values: `object`, `boundary`, `link`, `preprocessing`,
and `message`. `message` (added 2026-08-19) covers CQRS/event-driven coupling — an aggregate, a saga,
or a payload exchanged over a message bus between components with no `CALLS` edge between them.

Message seams are produced by a **gated, decoupled** pass in `_detect_seams()` that calls
`micro_cosmos/tools/message_flow_tools.py::discover_message_flows()`. That module is a registry of
`(detect_fn, parse_fn)` pairs (same convention as `scheduler_tools.py`) and returns an empty shape
for any estate with no message framework, so the pass is a no-op for ordinary codebases. Adding
Kafka/MediatR/NServiceBus support means appending one tuple there — `seam_tools.py` doesn't change.

**Three things to know before adding any further seam type:**
1. `_work_for_seam()`'s final `else` is an unguarded catch-all — a type without its own branch is
   silently scored as a config/Settings seam. Add an explicit branch.
2. Three hardcoded `("object","boundary","link","preprocessing","message")` tuples in `seam_tools.py`
   drive `seam_counts` and `work_summary.by_type`; a missing entry makes the type vanish from every
   breakdown while still counting toward `total`.
3. `dashboard.js`'s `byType[s.type]?.push(s)` silently drops an unregistered type — no error, just
   missing data. Register it in `SEAM_COLORS`/`SEAM_TYPE_COLOR`/`byType` and verify it renders live.

Unlike the other four types, `message` effort is scored by **role**, not by fan-in — an event-sourced
aggregate has no callers by construction, so fan-in is meaningless for it:

| Role | Effort | Points | Risk |
|---|---|---:|---|
| `external-integration` (broker/hub outside the process) | L | 16 | high |
| `saga` / process manager | L | 16 | high |
| `aggregate` (event-sourced) | M | 10 | high |
| `cross-context` flow | M | 10 | medium |
| `intra-context` flow | S | 6 | low |

### Adding a message-flow parser (the extension recipe)

Two are registered today: Axon (in-process bus) and NATS/JetStream + Azure Event Hubs (external
broker). To add a third, append one tuple to `_MESSAGE_FLOWS` in `message_flow_tools.py`:

```python
_MESSAGE_FLOWS = (
    ("AxonFramework",  detect_axon_flows,  parse_axon_flows),
    ("NATS/JetStream", detect_nats_flows,  parse_nats_flows),
    ("YourFramework",  detect_yours,       parse_yours),      # <- add here
)
```
- `detect(source_path, ir) -> bool` — cheap, **negative by default**, never raises. Gate at *estate*
  level, not per file: a per-file import check silently misses thin-wrapper producers.
- `parse(source_path, ir) -> {"aggregates": [...], "sagas": [...], "flows": [...]}` — `flows` entries
  need `payload`, `owners`, `consumers`, `handler_types`, `source_location`, and `external: True` for
  an out-of-process broker.
- The name must match what `detect_cqrs_frameworks()` reports, so `unparsed_frameworks()` can tell
  "detected but not parseable" from "fully covered" — that difference is surfaced to users via
  `seam.json`'s `coverage_notes`.

**Standing rule:** a parser is only added alongside a **real fixture** to verify it against. Inventing
heuristics for a framework with no example in the repo is unverifiable — the framework stays in the
detected-but-unparsed list (which is reported, not silent) until a fixture exists.

---

## Adding a new pipeline phase

1. Add enum value to `PipelinePhase` in `pipeline.py`
2. Add builder to `PHASE_AGENT_BUILDERS` in `pipeline.py`
3. Add kickoff prompt to `_phase_kickoff_prompt()` in `pipeline.py`
4. Add phase to the correct position in `driver.py` (`run_full_pipeline` or `_run_all_seams`)
5. Add pill to the 17-pill phase strip array in `run.html`
6. If it has a gate: add to `GATE_DEFINITIONS` in `gates/__init__.py`, `PHASE_AFTER_GATE`, `GATE_TO_AGENT_NAME`, `_GATE_RESTART_PHASE` in `app.py`, and `GATE_ARTIFACT_KEY` + `buildGateSummary` in `dashboard.js`

---

## ASK tab

`POST /runs/{id}/chat` — stateless server endpoint. Client sends full conversation history with each request. Server uses FAISS vector index from `runs/<id>/vectors/` and graph index from artifact JSON files. Calls Anthropic API directly. Zero coupling to the ADK pipeline session.

---

## Commit message style

`Type: short description (YYYY-MM-DD)` — e.g. `Feature:`, `Bug fix:`, `Fix + Feature:`, `Docs + Feature:`
