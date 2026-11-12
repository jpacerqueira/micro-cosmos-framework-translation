# Micro-Cosmos — Task Backlog

> Goal: extend the pipeline to (1) let users select one of the two bundled example apps, (2) identify all frameworks and dependency versions in the selected app, and (3) produce a structured upgrade report before translation begins.

Status legend: `[ ]` todo · `[~]` in progress · `[x]` done

---

## Epic 1 — Example app selector

Allow users to pick one of the two bundled example apps from the CLI and web UI without having to know the directory paths.

### T-01 `[x]` Understand current CLI surface
`micro_cosmos/cli.py` exposes `serve`, `run`, `models`, `version`. The `run` command takes a free-form `source_path`. No example shortcuts exist.

### T-02 `[ ]` Add `micro-cosmos examples list` CLI command
**File:** `micro_cosmos/cli.py`

Add a `examples` Typer sub-group with a `list` sub-command that prints a table of available example apps:

```
ID              Language   Path
python-soa      Python 2   examples/legacy_estate
java-k8s-soa    Java 21    examples/java-axonframework-modern-app/solution-k8s/03-backend-springboot
```

Implementation notes:
- Define a `_EXAMPLE_REGISTRY: dict[str, dict]` constant at the top of `cli.py`:
  ```python
  _EXAMPLE_REGISTRY = {
      "python-soa": {
          "path": "examples/legacy_estate",
          "source_lang": "python2",
          "description": "Python 2 credit-decisioning SOA (anti-patterns: float monetary, SQL-in-loop, dead code)",
      },
      "java-k8s-soa": {
          "path": "examples/java-axonframework-modern-app/solution-k8s/03-backend-springboot",
          "source_lang": "java21",
          "description": "Java 21 / Spring Boot 3.2 / Axon 4.10 K8s SOA (Azure AKS, NATS, CQRS/ES)",
      },
  }
  ```
- Resolve paths relative to the package root (`Path(__file__).parent.parent`).

### T-03 `[ ]` Add `micro-cosmos analyse-example <id>` CLI command
**File:** `micro_cosmos/cli.py`

New command that runs only the Observer + framework identification + upgrade recommendation phases (Phases 1 + new framework phase). Does **not** run translation. Prints a human-readable upgrade report to stdout using `rich`.

Usage:
```bash
micro-cosmos analyse-example python-soa
micro-cosmos analyse-example java-k8s-soa
micro-cosmos analyse-example java-k8s-soa --output-json runs/upgrade_report.json
```

### T-04 `[ ]` Add example selector to web UI index page
**Files:** `micro_cosmos/web/templates/index.html`, `micro_cosmos/web/app.py`

Add a "Quick start — example apps" section above the free-form source path input with two cards:
- **Python 2 SOA** — click pre-fills source path + source lang fields.
- **Java K8s SOA** — click pre-fills fields.

Implement as HTMX `hx-vals` attribute so no extra route is needed.

---

## Epic 2 — Framework / dependency identification

### T-05 `[ ]` New schema: `micro_cosmos/schema/upgrade.py`

Define three Pydantic models:

```python
class DependencyInfo(BaseModel):
    name: str
    version: str                  # exact string from manifest; "unknown" if import-scan
    category: Literal[
        "web-framework", "orm", "messaging", "security",
        "testing", "serialisation", "build-tool", "infra",
        "observability", "other",
    ]
    manifest_file: str            # relative path e.g. "pom.xml"
    detected_via: Literal["manifest", "import-scan"]

class UpgradeRecommendation(BaseModel):
    framework: str
    current_version: str
    recommended_version: str
    migration_effort: Literal["LOW", "MEDIUM", "HIGH"]
    breaking_changes: list[str]
    migration_notes: str
    priority: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]

class UpgradeReport(Artifact):
    source_app: str
    source_lang: str
    dependencies: list[DependencyInfo]
    recommendations: list[UpgradeRecommendation]
```

`UpgradeReport` must subclass `Artifact` so it gets SHA-stamped and can be persisted to `runs/{run_id}/upgrade_report.json`.

### T-06 `[ ]` New tool: `scan_dependency_manifests()` in `micro_cosmos/tools/observer_tools.py`

Add to the existing observer tools file (do **not** create a new file — it is conceptually part of observation).

```python
def scan_dependency_manifests(source_path: str) -> dict:
    """Scan source_path for dependency manifest files and extract framework versions.

    Returns:
        {"dependencies": [DependencyInfo.model_dump(), ...]}
    """
```

Manifest parsing priority (implement in this order — each covers one of the two example apps):

**pom.xml** (covers `java-k8s-soa`):
- Use `re` to extract `<groupId>`, `<artifactId>`, `<version>` triples from `<dependency>` blocks.
- Also extract `<parent>` block for the Spring Boot starter parent version.
- Map known artifact IDs to categories:
  ```
  spring-boot-starter-web          → web-framework
  spring-boot-starter-data-jpa     → orm
  axon-spring-boot-starter         → messaging
  spring-boot-starter-security     → security
  spring-boot-starter-test         → testing
  jnats                            → messaging
  postgresql                       → orm
  logstash-logback-encoder         → observability
  spring-boot-starter-graphql      → web-framework
  tika-core                        → serialisation
  ```
- Resolve `${property}` references by reading `<properties>` block first.

**pyproject.toml / requirements.txt** (covers future Python targets; `legacy_estate` has no manifest):
- Use `re` to parse `[project.dependencies]` list in TOML or `name==version` lines in requirements.txt.
- When no manifest found, fall back to import scanning (see below).

**Import-scan fallback** (covers `legacy_estate` — bare Python 2 scripts):
- Walk all `.py` files, collect `import X` and `from X import` module names.
- Filter to known third-party names (not stdlib modules from a hardcoded set).
- Emit `DependencyInfo(version="unknown", detected_via="import-scan")`.
- Additionally, detect Python version from source heuristics:
  - `print "..."` → `python2`
  - `"rb"/"ab"` open modes with bytes operations → `python2`
  - Emit a synthetic `DependencyInfo(name="python", version="2.x", category="other", detected_via="import-scan")`.

**Update `observe_source_estate()`** to call `scan_dependency_manifests()` and include the result under key `"dependencies"` in the returned dict.

### T-07 `[ ]` Wire `scan_dependency_manifests` as an ADK FunctionTool
**File:** `micro_cosmos/tools/observer_tools.py` (add at the bottom)

Wrap with `FunctionTool(scan_dependency_manifests)` and export from `micro_cosmos/tools/__init__.py`.
Also register it in the Observer agent's tool list in `micro_cosmos/agents/observer.py`.

### T-08 `[ ]` Test: `tests/test_framework_scan.py`

Two test cases, no LLM required:

```python
def test_scan_java_k8s_soa():
    result = scan_dependency_manifests(
        "examples/java-axonframework-modern-app/solution-k8s/03-backend-springboot"
    )
    deps = {d["name"]: d for d in result["dependencies"]}
    assert deps["spring-boot"]["version"] == "3.2.5"
    assert deps["axon-spring-boot-starter"]["version"] == "4.10.0"
    assert deps["axon-spring-boot-starter"]["category"] == "messaging"

def test_scan_python_soa_no_manifest():
    result = scan_dependency_manifests("examples/legacy_estate")
    deps = {d["name"]: d for d in result["dependencies"]}
    assert deps["python"]["version"] == "2.x"
    assert deps["python"]["detected_via"] == "import-scan"
```

---

## Epic 3 — Upgrade advisor agent

### T-09 `[ ]` New agent: `micro_cosmos/agents/upgrade_advisor.py`

Create a new `LlmAgent` named `upgrade_advisor_agent`.

- **Input context:** `ir_graph` + `dependencies` list from the Observer output.
- **System prompt key rules** (encode directly in the agent's system prompt):
  1. Produce one `UpgradeRecommendation` per dependency where a newer stable version exists.
  2. Never recommend a pre-release unless the current version is also pre-release.
  3. For Python 2 → 3 upgrades, always classify effort as `HIGH` and list at minimum: print-statement syntax, byte-string literals, division operator semantics, `Decimal` for monetary fields.
  4. For Spring Boot 3.2 → 3.3+: mention AOT compilation and CDS improvements; effort `MEDIUM`.
  5. For Axon 4.10 → 4.11+: check for `@Aggregate` lifecycle changes; effort `MEDIUM`.
  6. For Java 21 virtual threads (Project Loom): if any service uses `@Async` or blocking I/O, suggest migrating to virtual thread executor; effort `LOW`.
  7. Always include a `migration_notes` string that references the project context (e.g. "This project already uses Java 21 — no JDK change needed for Spring Boot 3.3").
- **Fallback:** `_direct_upgrade_advisor_fallback` — calls a deterministic `generate_upgrade_report()` function in `micro_cosmos/tools/upgrade_advisor_tools.py` that generates known-good recommendations for the two example apps based on hardcoded version data. This ensures the pipeline works with `SKIP_LLM=true`.
- **Output artifact key:** `upgrade_report`

### T-10 `[ ]` New tools file: `micro_cosmos/tools/upgrade_advisor_tools.py`

```python
def generate_upgrade_report(
    source_app: str,
    source_lang: str,
    dependencies: list[dict],
) -> dict:
    """Deterministic fallback: produce an UpgradeReport for the two known example apps."""
```

Hardcode known recommendations for `python-soa` and `java-k8s-soa`.

**Python SOA known recommendations:**
| Framework | Current | Recommended | Effort | Priority |
|---|---|---|---|---|
| python | 2.x | 3.12 | HIGH | HIGH |
| (no ORM) | — | SQLAlchemy 2.x | LOW | MEDIUM |
| (no web FW) | — | FastAPI 0.115 | LOW | MEDIUM |
| (no validation) | — | Pydantic v2 | LOW | MEDIUM |
| (no testing) | — | pytest 8 | LOW | LOW |

**Java K8s SOA known recommendations:**
| Framework | Current | Recommended | Effort | Priority |
|---|---|---|---|---|
| Spring Boot | 3.2.5 | 3.3.x | MEDIUM | HIGH |
| Axon Framework | 4.10.0 | 4.11.x | MEDIUM | MEDIUM |
| jnats | 2.17.3 | 2.20.x | LOW | LOW |
| PostgreSQL JDBC | 42.7.3 | 42.7.5 | LOW | MEDIUM |
| Jib Maven Plugin | 3.4.2 | 3.4.4 | LOW | LOW |
| eclipse-temurin base image | 21-jre-alpine | 21-jre-alpine (latest patch) | LOW | MEDIUM |

### T-11 `[ ]` Add upgrade phase to orchestration
**File:** `micro_cosmos/orchestration/driver.py`

Insert the upgrade advisor as Phase 1b — after the Observer and before the Cartographer:

```
Phase 1  — Observer      → ir_graph
Phase 1b — Upgrade Advisor → upgrade_report   ← NEW
Phase 2  — Cartographer  → bounded_context_map
...
```

No new gate is needed. The upgrade report is informational — it does not block the pipeline. Emit it as an event so the web UI can display it.

### T-12 `[ ]` Expose upgrade report in web UI
**Files:** `micro_cosmos/web/app.py`, `micro_cosmos/web/templates/run.html`

Add a new tab "Upgrade Report" to the run detail page. Display the `UpgradeReport` as a sortable table:

Columns: Framework | Current version | Recommended | Effort | Priority | Breaking changes (expandable).

Use HTMX to load `GET /runs/{run_id}/artifacts/upgrade_report` inline.

---

## Epic 4 — Per-example upgrade analysis output

### T-13 `[ ]` Python SOA: complete anti-pattern findings

Extend `scan_performance_anti_patterns` in `micro_cosmos/tools/observer_tools.py` to detect:

1. **`FLOAT_MONETARY`** — scan for `float(` applied to variables with names containing `amount`, `rate`, `price`, `interest`, `principal`, `balance`. Currently only the fitness rule checks this post-generation; add it as an Observer finding so the Upgrade Advisor can reference it.
2. **`PYTHON2_PRINT_STATEMENT`** — detect `print "..."` (no parentheses). Mark as `CRITICAL` — indicates Python 2.
3. **`PYTHON2_BYTES_MODE`** — detect `open(..., "rb")` or `open(..., "ab")` combined with a `print` statement in the same file (strong Python 2 signal).
4. **`DEAD_IMPORT`** — detect commented-out imports `# from X import Y` or `# import X` as dead-code candidates (lower confidence than call-graph dead code).

### T-14 `[ ]` Java SOA: extend deep parser to flag version-sensitive patterns

Extend `_parse_java_file` in `micro_cosmos/tools/observer_tools.py`:

1. **`BLOCKING_IO_WITH_ASYNC`** — detect `@Async` annotated methods that contain `Thread.sleep`, `InputStream.read`, or JDBC calls. Flag as `HIGH` — candidate for Java 21 virtual thread migration.
2. **`DEPRECATED_AXON_LIFECYCLE`** — detect `@Saga` annotation (deprecated in Axon 4.7 in favour of `@SagaEventHandler`). Flag as `MEDIUM`.
3. **`SPRING_BOOT_32_DEPRECATION`** — detect `spring.datasource.*` properties in `application.properties`/`application.yml` that are renamed in Spring Boot 3.3. (Read `.properties`/`.yml` files in the observer's documentation scan and regex for deprecated keys.)

### T-15 `[ ]` Produce human-readable upgrade reports for both example apps

Run `micro-cosmos analyse-example python-soa` and `micro-cosmos analyse-example java-k8s-soa` and save the JSON output to:
- `examples/legacy_estate/upgrade_report.json`
- `examples/java-axonframework-modern-app/upgrade_report.json`

These files serve as reference outputs and regression baselines for the test suite.

---

## Epic 5 — Tests and quality

### T-16 `[ ]` Regression test: Python SOA upgrade report
`tests/test_upgrade_advisor.py`

```python
def test_python_soa_upgrade_report():
    deps = scan_dependency_manifests("examples/legacy_estate")["dependencies"]
    report = generate_upgrade_report("python-soa", "python2", deps)
    recs = {r["framework"]: r for r in report["recommendations"]}
    assert recs["python"]["recommended_version"] == "3.12"
    assert recs["python"]["migration_effort"] == "HIGH"
    assert any("Decimal" in c for c in recs["python"]["breaking_changes"])
```

### T-17 `[ ]` Regression test: Java SOA upgrade report
```python
def test_java_k8s_soa_upgrade_report():
    deps = scan_dependency_manifests(
        "examples/java-axonframework-modern-app/solution-k8s/03-backend-springboot"
    )["dependencies"]
    report = generate_upgrade_report("java-k8s-soa", "java21", deps)
    recs = {r["framework"]: r for r in report["recommendations"]}
    assert recs["Spring Boot"]["current_version"] == "3.2.5"
    assert recs["Spring Boot"]["migration_effort"] in ("LOW", "MEDIUM")
    assert recs["Axon Framework"]["current_version"] == "4.10.0"
```

### T-18 `[ ]` CI check: `micro-cosmos analyse-example` exits 0 for both examples
Add to CI (GitHub Actions or equivalent):
```bash
SKIP_LLM=true micro-cosmos analyse-example python-soa
SKIP_LLM=true micro-cosmos analyse-example java-k8s-soa
```

---

## Dependency map

```
T-02 → T-03 (CLI examples list needed before analyse-example)
T-05 → T-06 → T-07 → T-08 (schema → tool → FunctionTool → test)
T-05 → T-09 → T-10 → T-11 → T-12 (schema → agent → deterministic fallback → orchestration → UI)
T-06 → T-13 (observer tool extension — same file)
T-06 → T-14 (observer tool extension — same file)
T-09, T-10 → T-15 (generate reports after advisor is built)
T-10 → T-16, T-17 (regression tests after fallback is built)
T-03, T-16, T-17 → T-18 (CI gate after commands and tests exist)
```

---

## Effort estimate

| Task | Effort | Owner |
|---|---|---|
| T-02 CLI examples list | 0.5 h | — |
| T-03 analyse-example command | 1 h | — |
| T-04 web UI selector | 1 h | — |
| T-05 upgrade schema | 0.5 h | — |
| T-06 scan_dependency_manifests | 3 h | — |
| T-07 FunctionTool wiring | 0.5 h | — |
| T-08 framework scan tests | 1 h | — |
| T-09 upgrade advisor agent | 2 h | — |
| T-10 deterministic fallback tools | 2 h | — |
| T-11 orchestration phase 1b | 1 h | — |
| T-12 web UI upgrade report tab | 1.5 h | — |
| T-13 Python SOA anti-patterns | 1.5 h | — |
| T-14 Java SOA deep parser flags | 2 h | — |
| T-15 reference output files | 0.5 h | — |
| T-16 Python SOA regression test | 0.5 h | — |
| T-17 Java SOA regression test | 0.5 h | — |
| T-18 CI gate | 0.5 h | — |
| **Total** | **~20 h** | |
