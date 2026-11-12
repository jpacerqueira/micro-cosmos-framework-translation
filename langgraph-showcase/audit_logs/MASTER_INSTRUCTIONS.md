# Micro-Cosmos — Master Instructions

> This document is the authoritative guide for contributors working on the Micro-Cosmos codebase. Read it before writing any code.

---

## 1. What this project is

Micro-Cosmos is a **neurosymbolic code modernisation pipeline**. It translates a legacy source estate to a modern target language and architecture without hallucination.

The neurosymbolic contract: a deterministic symbolic parser builds an Intermediate Representation (IR) property graph in Phase 1. All subsequent LLM agents may only reference IR node IDs that already exist. Any node ID the LLM fabricates is caught by `verify_against_ir` and rejected.

---

## 2. Repository layout

```
micro-cosmos/
├── micro_cosmos/
│   ├── agents/          Eight LlmAgent builders (observer, cartographer, pattern,
│   │                    architect, coder_judge, code_reviewer, writer, pr_reviewer)
│   ├── fitness/         Five blocking fitness rules
│   ├── gates/           Gate state machine (approve / reject / escalate)
│   ├── orchestration/   MicroCosmosOrchestrator + async pipeline driver
│   ├── schema/          Pydantic schemas: ir, tnas, gate, fitness, artifact, upgrade (new)
│   ├── tools/           FunctionTool wrappers — one file per agent phase
│   └── web/             FastAPI app, Jinja2 templates, static JS/CSS
├── examples/
│   ├── legacy_estate/               Python 2 SOA (credit-decisioning)
│   └── java-axonframework-modern-app/solution-k8s/   Java 21 / Spring Boot / Axon 4.10 K8s SOA
├── audit_logs/          This directory — changelog, instructions, tasks
├── runs/                Persisted run artifacts (JSON + output files)
├── tests/
├── pyproject.toml
└── Dockerfile
```

---

## 3. Architecture rules

### 3.1 The IR is the single source of truth
- The Observer (`micro_cosmos/agents/observer.py` + `micro_cosmos/tools/observer_tools.py`) is the **only** agent that reads raw source files.
- Every other agent must receive data from the IR or a downstream artifact derived from the IR.
- Never pass raw source content to any agent after Phase 1.

### 3.2 Schema discipline
- Every artifact must subclass `Artifact` from `micro_cosmos/schema/artifact.py`.
- Artifacts are SHA-stamped on creation via `artifact.stamp(produced_by=...)`.
- Schemas live in `micro_cosmos/schema/`. Add a new `<feature>.py` file for new schemas; do not extend unrelated schemas.

### 3.3 Tools are deterministic
- Tools in `micro_cosmos/tools/` must be pure functions over their inputs. No side effects except writing to `runs/{run_id}/`.
- Every tool must have a matching `_direct_tool_fallback` in the agent that calls it. The fallback calls the tool directly when the LLM times out or emits an invalid artifact.
- Raise `ValueError` with a user-readable message; the orchestrator will route it to diagnostics.

### 3.4 Gate discipline
- There are exactly five human gates. Do not add more without a compelling reason documented in this file.
- Gate rejections generate `RejectionConstraint` objects that are prepended to the responsible agent's system prompt on retry.
- Three rejections on the same gate → `ESCALATED`. The orchestrator halts the pipeline.

### 3.5 LLM agnosticism
- All agents are wired through LiteLLM. Never import `anthropic`, `openai`, or any provider SDK directly.
- Model selection is via `settings.py` (Pydantic settings). Respect `SKIP_LLM=true` in all agent paths.

---

## 4. Adding a new capability

Follow this checklist in order:

1. **Schema first** — define the output Pydantic model in `micro_cosmos/schema/<feature>.py`.
2. **Tool second** — implement the deterministic tool function in `micro_cosmos/tools/<feature>_tools.py`. Write it so it can be called directly (no LLM) and returns the schema as a dict.
3. **Agent third** — create `micro_cosmos/agents/<feature>.py` returning an `LlmAgent`. Wire the tool via `FunctionTool`.
4. **Orchestrator last** — add the new phase to `micro_cosmos/orchestration/driver.py` and register the gate (if applicable) in `micro_cosmos/orchestration/pipeline.py`.
5. **Tests** — add at least one unit test in `tests/test_<feature>.py` using `SKIP_LLM=true` so CI does not require a live model.

---

## 5. Example applications

Two example codebases live under `examples/`. They serve as canonical inputs for development, demos, and framework upgrade analysis.

### 5.1 Python 2 SOA — `examples/legacy_estate/`

| File | Role |
|---|---|
| `credit_decisioner.py` | Entry point. Uses Python 2 `print` statement; `float()` for monetary arithmetic. |
| `customer_reader.py` | Reads CSV customer data. Contains deliberate SQL-in-loop anti-pattern. |
| `decision_writer.py` | Appends decisions to CSV. Opens file in Python 2 `"ab"` mode. |
| `legacy_archiver.py` | Dead code — the import is commented out in `credit_decisioner.py`. |

**Detected anti-patterns (Observer):** `SQL_IN_LOOP`, `NO_FLOAT_ON_MONETARY`, Python 2 print statement, dead code (`LegacyArchiver`), stale/absent docs.

**Upgrade path (target):** Python 3.12, `decimal.Decimal` for monetary values, FastAPI 0.115+, Pydantic v2, SQLAlchemy 2.x, pytest 8, async I/O, hexagonal port architecture.

**CLI quickstart:**
```bash
micro-cosmos run examples/legacy_estate --target-lang python3
micro-cosmos run examples/legacy_estate --target-lang java21 --auto-approve
```

### 5.2 Java K8s SOA — `examples/java-axonframework-modern-app/solution-k8s/`

A cloud-native Azure/AKS portfolio management system (CAN — Customer-Application-Name).

| Module | Role |
|---|---|
| `common-domain` | Shared commands, events, ULI envelope (Java records) |
| `webapp-bff` | GraphQL BFF (Spring GraphQL) |
| `user-auth` | Azure AD B2B invitation via Microsoft Graph |
| `property-allocation` | Portfolio CQRS/ES aggregate (Axon 4.10, core domain) |
| `vdr-ingestion` | Virtual Data Room: Apache Tika/POI/PDFBox |
| `workflow` | Axon Sagas (AllocationSaga process manager) |
| `search` | NATS-driven Postgres full-text search |

**Current versions (pom.xml baseline):**

| Dependency | Current version |
|---|---|
| Java | 21 |
| Spring Boot | 3.2.5 |
| Axon Framework | 4.10.0 |
| jnats | 2.17.3 |
| PostgreSQL JDBC | 42.7.3 |
| Jib Maven Plugin | 3.4.2 |
| Base image | eclipse-temurin:21-jre-alpine |

**Infrastructure:** Azure AKS + Istio mTLS, NATS JetStream, Azure Event Hubs (Kafka), PostgreSQL Flexible Server (Citus-ready), Azure Key Vault (secrets via CSI driver), OTel Collector.

**CLI quickstart:**
```bash
micro-cosmos run examples/java-axonframework-modern-app/solution-k8s/03-backend-springboot \
  --source-lang java21 --target-lang java21
```

---

## 6. Framework identification rules

When scanning a source estate for framework/dependency information, the tool (`scan_dependency_manifests`) must:

1. Walk the source tree looking for these manifest files in priority order:

   | Manifest | Language | Parser |
   |---|---|---|
   | `pyproject.toml` | Python | TOML `[project.dependencies]` |
   | `requirements.txt` | Python | `name==version` per line |
   | `setup.py` / `setup.cfg` | Python | `install_requires` |
   | `pom.xml` | Java/Maven | `<dependency>` blocks |
   | `build.gradle` / `build.gradle.kts` | Java/Kotlin/Gradle | `implementation '...'` |
   | `package.json` | JS/TS | `dependencies` + `devDependencies` |
   | `go.mod` | Go | `require` blocks |
   | `Cargo.toml` | Rust | `[dependencies]` |
   | `Gemfile` | Ruby | `gem 'name', 'version'` |

2. Emit a `DependencyInfo` record per detected dependency:
   - `name` — package/artifact name
   - `version` — exact version string as declared (may be a range)
   - `category` — one of: `web-framework`, `orm`, `messaging`, `security`, `testing`, `serialisation`, `build-tool`, `infra`, `observability`, `other`
   - `manifest_file` — relative path of the file it was read from
   - `detected_via` — `"manifest"` (from file) or `"import-scan"` (inferred from source imports when no manifest exists)

3. When no manifest exists (e.g. bare Python 2 scripts), fall back to import scanning:
   - Scan all source files for `import X` / `from X import` statements
   - Emit `DependencyInfo` with `detected_via="import-scan"` and `version="unknown"`

---

## 7. Upgrade recommendation rules

The `UpgradeAdvisorAgent` must produce an `UpgradeReport` following these rules:

1. For each `DependencyInfo` with a known version, compare against the latest stable release known to the model's training data.
2. Classify migration effort: `LOW` (patch/minor, no API changes), `MEDIUM` (minor with deprecations), `HIGH` (major version with breaking changes).
3. List breaking changes as bullet strings.
4. Provide migration notes specific to the project context (e.g. "Spring Boot 3.3 requires Java 17 minimum; this project already uses Java 21 — no JDK change needed").
5. Assign priority: `CRITICAL` (security CVE), `HIGH` (major version EOL), `MEDIUM` (significant new features), `LOW` (minor patch).
6. Never recommend downgrading a dependency.
7. Never recommend a pre-release / RC version unless the current version is also a pre-release.

---

## 8. Running locally

```bash
# Install (editable)
pip install -e ".[dev]"

# Dev server (LM Studio required unless SKIP_LLM=true)
micro-cosmos serve

# Run on Python 2 SOA, skip LLM (deterministic tools only)
SKIP_LLM=true micro-cosmos run examples/legacy_estate --target-lang python3 --auto-approve

# Run tests
pytest

# Lint
ruff check micro_cosmos tests
mypy micro_cosmos
```

Environment variables (see `.env.example`):

| Variable | Purpose |
|---|---|
| `SKIP_LLM` | `true` → bypass LLM, call tools directly |
| `GOOGLE_GENAI_USE_VERTEXAI` | `TRUE` → use Vertex AI / Gemini |
| `GOOGLE_CLOUD_PROJECT` | GCP project ID for Vertex AI |
| `LMSTUDIO_BASE_URL` | LM Studio API base (default `http://localhost:1234/v1`) |
| `LMSTUDIO_MODEL` | Model identifier for LM Studio |

---

## 9. Coding conventions

- Python 3.9+ syntax. `from __future__ import annotations` in all tool files.
- Type annotations on every public function.
- No comments unless the WHY is non-obvious.
- Ruff line length 100. `ruff check --fix` before committing.
- Tests in `tests/` use `pytest-asyncio` with `asyncio_mode = "auto"`.
- Never import a provider SDK directly — use LiteLLM or ADK abstractions.
- Never store secrets in source — use `.env` / Key Vault / environment variables.
