# Micro-Cosmos — Changelog

All notable changes to this project are recorded here.
Format: `[version] YYYY-MM-DD — summary`.

---

## [Unreleased] — 2026-05-21

### Added
- `audit_logs/` directory with CHANGELOG, MASTER_INSTRUCTIONS, and TASKS documents.
- Framework/dependency identification capability planned — see TASKS.md.
- Example-app selector for `legacy_estate` (Python 2 SOA) and `java-axonframework-modern-app` (Java K8s SOA) planned.
- Upgrade advisor agent and `UpgradeReport` schema planned.

---

## [0.1.0] — initial release (pre-audit baseline)

### Core pipeline

| Phase | Agent | Output artifact |
|---|---|---|
| 1 — Observe | `observer_agent` | `ir_graph` |
| 2 — Cartograph | `cartographer_agent` | `bounded_context_map` |
| 3a — Pattern | `pattern_agent` | `domain_model` |
| 3b — Architect | `architect_agent` | `tnas` |
| 4 — Code | `coder_judge_agent` + `code_reviewer_agent` + `writer_agent` | `seam_result`, `code_review`, `write_manifest` |
| 5 — Review | `pr_reviewer_agent` | `review_report` |

Each phase is guarded by a human gate (`gates/__init__.py`). A gate rejection prepends a `RejectionConstraint` to the responsible agent's next run. Three rejections escalate the pipeline to `ESCALATED` and halt it.

### Anti-hallucination
`verify_against_ir` in `micro_cosmos/tools/verifier.py` — every node ID an LLM references is checked against the IR. If the node does not exist the agent call is rejected. After Phase 1 no agent reads raw source files.

### Language support (Observer deep parsers)
- Python 2/3 — AST first, regex fallback for Python 2 `print` statements.
- Java 8/11/21 — annotation-aware class/method/field parser; detects `@Aggregate`, `@AggregateIdentifier`, `@CommandHandler`, `@EventSourcingHandler`, `@Transactional`.
- PHP — namespace, class, method, property.
- JavaScript/TypeScript — ES module imports and `require()`.
- COBOL — `CALL 'PROGRAM'` edges.
- Go, Rust, Kotlin, Scala, Swift, C# — extension matching only (no deep parser yet).

### Performance anti-pattern detectors (Observer)
- `SQL_IN_LOOP` — CRITICAL
- `FILE_OPEN_IN_LOOP` — HIGH
- `MISSING_AGGREGATE_IDENTIFIER` — CRITICAL (Axon/Spring)
- `BYPASS_COMMAND_GATEWAY` — HIGH (Axon/Spring)

### Fitness rules (blocking)
Five canonical blocking rules in `micro_cosmos/fitness/__init__.py`.
`NO_FLOAT_ON_MONETARY` is the only rule with a content scanner; the remaining four are schema-validated but the runner is stubbed.

### Equivalence harness
Stubbed — `run_equivalence_check` always returns `{"passed": True, "vectors_run": 12}`.

### Web UI
FastAPI + HTMX + Cytoscape.js. Routes: create run, stream events over WebSocket, approve/reject gates, browse artifacts, view IR graph, view diagnostics.

### CLI
`micro-cosmos serve | run | models | version` via Typer.

### LLM backends
- Vertex AI / Gemini (production) via `GOOGLE_GENAI_USE_VERTEXAI=TRUE`.
- LM Studio local server (dev default, OpenAI-compatible, `google/gemma-4-e4b`).
- `SKIP_LLM=true` — bypasses LLM entirely; calls deterministic tools directly.

### Completed example runs
| Run ID | Source | Target |
|---|---|---|
| `ab58f105` | `examples/legacy_estate` (Python 2) | Java (hexagonal) |
| `bcf410a1` | PHP QR code library | Go (with tests, `go.mod`, `Makefile`) |
| `ab1e4e6a` | PHP QR code library | Go (earlier iteration) |
| `0bbf57d2` | PHP QR code library | Go |
| `5e845dcc` | PHP QR code library | Go (per-method files) |
| `0542f6be` | Unknown | Go (ports stub only) |

### Known stubs / gaps (baseline)
1. No dependency-manifest parser — `pom.xml`, `requirements.txt`, `pyproject.toml`, `build.gradle` are not read.
2. No framework version identification.
3. No upgrade recommendation agent or schema.
4. No example-app quick-select in CLI or UI.
5. Fitness runner only evaluates `NO_FLOAT_ON_MONETARY`; four rules are inert.
6. Equivalence harness always returns passed.
7. Co-mutation and table-ownership analyses beyond call-graph clustering are stubs.
