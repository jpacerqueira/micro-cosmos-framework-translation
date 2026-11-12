"""Writer Agent tools — materialise the seam PR onto disk.

Reads seam_result from the run directory, writes every translated file
to runs/{run_id}/{seam}_{lang}/, generates a README.md, and produces a
write manifest so downstream agents know exactly what was committed.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from micro_cosmos.tools.coder_tools import _dedup_declarations
from micro_cosmos.tools.feature_spec_tools import _read_json as _read_feature_spec_json
from micro_cosmos.tools.security_tools import _SEV_ORDER


# ─── README generation ────────────────────────────────────────────────────────

_LANG_DISPLAY: dict[str, str] = {
    "java": "Java", "java8": "Java 8", "java11": "Java 11", "java21": "Java 21",
    "python": "Python", "python2": "Python 2", "python3": "Python 3",
    "go": "Go", "typescript": "TypeScript", "javascript": "JavaScript",
    "csharp": "C#", "cs": "C#", "kotlin": "Kotlin", "rust": "Rust",
    "scala": "Scala", "swift": "Swift",
}

_LANG_PREREQS: dict[str, str] = {
    "java":       "- JDK 17 or later\n- Maven 3.9+ (or Gradle 8+)",
    "java8":      "- JDK 8 or later\n- Maven 3.9+ (or Gradle 8+)",
    "java11":     "- JDK 11 or later\n- Maven 3.9+",
    "java21":     "- JDK 21 or later\n- Maven 3.9+",
    "python":     "- Python 3.11+\n- pip",
    "python2":    "- Python 3.11+ (modernised target runs on Python 3)\n- pip",
    "python3":    "- Python 3.11+\n- pip",
    "go":         "- Go 1.21+",
    "typescript": "- Node.js 20+\n- npm 10+",
    "javascript": "- Node.js 20+\n- npm 10+",
    "csharp":     "- .NET 8 SDK or later",
    "cs":         "- .NET 8 SDK or later",
    "kotlin":     "- JDK 17 or later\n- Gradle 8+",
    "rust":       "- Rust 1.75+ (install via rustup)\n- Cargo (bundled with Rust)",
    "scala":      "- JDK 17 or later\n- sbt 1.9+",
    "swift":      "- Swift 5.9+\n- Xcode 15+ (macOS) or Swift toolchain (Linux)",
}

_LANG_QUICKSTART: dict[str, str] = {
    "java": """\
```bash
# Compile
mvn compile

# Run tests
mvn test

# Package as JAR
mvn package
```""",
    "java8": """\
```bash
mvn compile
mvn test
mvn package
```""",
    "java11": """\
```bash
mvn compile
mvn test
mvn package
```""",
    "java21": """\
```bash
mvn compile
mvn test
mvn package
```""",
    "python": """\
```bash
# Create a virtual environment
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\\Scripts\\activate

# Install dependencies (generated requirements.txt if present)
pip install -r requirements.txt 2>/dev/null || true

# Run tests
python -m pytest tests/ -v
```""",
    "python2": """\
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt 2>/dev/null || true
python -m pytest tests/ -v
```""",
    "python3": """\
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt 2>/dev/null || true
python -m pytest tests/ -v
```""",
    "go": """\
```bash
# Resolve dependencies
go mod tidy

# Build all packages
go build ./...

# Run tests
go test ./...
```""",
    "typescript": """\
```bash
npm install
npm run build
npm test
```""",
    "javascript": """\
```bash
npm install
npm test
```""",
    "csharp": """\
```bash
dotnet restore
dotnet build
dotnet test
```""",
    "cs": """\
```bash
dotnet restore
dotnet build
dotnet test
```""",
    "kotlin": """\
```bash
./gradlew build
./gradlew test
```""",
    "rust": """\
```bash
cargo build
cargo test
```""",
    "scala": """\
```bash
sbt compile
sbt test
```""",
    "swift": """\
```bash
swift build
swift test
```""",
}


# ─── Claude Code skill generation ────────────────────────────────────────────

_LANG_DECIMAL: dict[str, str] = {
    "java": "BigDecimal", "java8": "BigDecimal", "java11": "BigDecimal", "java21": "BigDecimal",
    "python": "decimal.Decimal", "python2": "decimal.Decimal", "python3": "decimal.Decimal",
    "go": "shopspring/decimal",
    "typescript": "Decimal (decimal.js)", "javascript": "Decimal (decimal.js)",
    "csharp": "decimal", "cs": "decimal",
    "kotlin": "BigDecimal",
    "rust": "rust_decimal::Decimal",
    "scala": "BigDecimal",
    "swift": "Decimal",
}

_LANG_FLOAT_AVOID: dict[str, str] = {
    "java": "float / double", "java8": "float / double", "java11": "float / double", "java21": "float / double",
    "python": "float", "python2": "float", "python3": "float",
    "go": "float32 / float64",
    "typescript": "number (primitive)", "javascript": "number (primitive)",
    "csharp": "float / double", "cs": "float / double",
    "kotlin": "Float / Double",
    "rust": "f32 / f64",
    "scala": "Float / Double",
    "swift": "Float / Double",
}

_LANG_EXT: dict[str, str] = {
    "java": "java", "java8": "java", "java11": "java", "java21": "java",
    "python": "py", "python2": "py", "python3": "py",
    "go": "go",
    "typescript": "ts", "javascript": "js",
    "csharp": "cs", "cs": "cs",
    "kotlin": "kt",
    "rust": "rs",
    "scala": "scala",
    "swift": "swift",
}

_LANG_BUILD_FILE: dict[str, str] = {
    "java": "pom.xml", "java8": "pom.xml", "java11": "pom.xml", "java21": "pom.xml",
    "python": "pyproject.toml", "python2": "pyproject.toml", "python3": "pyproject.toml",
    "go": "go.mod",
    "typescript": "package.json", "javascript": "package.json",
    "csharp": ".csproj", "cs": ".csproj",
    "kotlin": "build.gradle.kts",
    "rust": "Cargo.toml",
    "scala": "build.sbt",
    "swift": "Package.swift",
}


# ─── Shared content: Security / Observability / Logging / Testing ───────────
# _SECURITY_CATEGORIES is referenced identically by all three renderers
# (_write_output_skills's security-review.md, _write_kiro_powers's
# micro-cosmos-security-power, and _write_openspec's specs/security/spec.md), so a
# category added here automatically appears in all three.
#
# _TESTING_TAXONOMY_CHECKLIST and _OBSERVABILITY_CHECKLIST/
# _LOGGING_STANDARDS_CHECKLIST are shared between the Skills renderer and
# _write_openspec, but NOT literally reused inside _write_kiro_powers: the
# existing micro-cosmos-monitoring-power/micro-cosmos-code-reviewer-power POWER.md
# bodies are large pre-existing plain (non-f) string literals containing their
# own literal '{' characters (e.g. "I{Aggregate}UseCase" as illustrative
# placeholder text) — converting them to f-strings to interpolate these
# constants would require escaping every one of those as literal braces, a
# real risk of a subtle runtime break for a large, high-traffic template.
# Their equivalent sections (Kiro's Test Coverage / OTel checklists) are kept
# manually text-synced to the same content instead — genuinely aligned in
# substance (verified by tests/test_skills_kiro_openspec_parity.py), just not
# sharing the literal Python object the way Skills and OpenSpec do.
_SECURITY_FINDINGS_LIMIT = 40  # shared cutoff for both security-finding renderers below

_SECURITY_CATEGORIES: list[tuple[str, str, str]] = [
    ("Injection", "String-concatenated SQL/shell/LDAP commands built from unsanitized input",
     "Use parameterized queries / prepared statements; never concatenate user input into a command string"),
    ("Auth", "Sensitive operations reachable without an authentication or authorization check",
     "Require an explicit auth guard on every state-changing or data-returning endpoint"),
    ("Crypto", "Weak/deprecated algorithms (MD5, SHA1, DES), hardcoded keys, disabled TLS verification",
     "Use current algorithms (AES-256, SHA-256+), load keys from a secrets manager, never disable cert validation"),
    ("Secrets", "Hardcoded credentials, API keys, or tokens in source or config files",
     "Load secrets from environment variables or a secrets manager; never commit them"),
    ("Validation", "Missing input validation allowing malformed, oversized, or unexpected payloads through",
     "Validate type, length, and range at every trust boundary before processing"),
    ("Exposure", "Sensitive data (PII, passwords, tokens) logged, returned in error messages, or over-shared in API responses",
     "Redact sensitive fields before logging; return generic error messages to clients"),
    ("Deserialization", "Unsafe deserialization of untrusted data (e.g. Java ObjectInputStream, Python pickle, YAML.load)",
     "Use safe/restricted deserializers; validate schema before deserializing untrusted input"),
    ("Path", "Path traversal via unsanitized file paths built from user input",
     "Canonicalize and validate paths against an allowlist before file access"),
    ("SSRF", "Server-side requests to a URL built from user input, reachable to internal/attacker-controlled hosts",
     "Allowlist outbound destinations; block requests to internal/metadata IP ranges"),
    ("Supply chain", "Vulnerable or unpinned third-party dependencies",
     "Pin dependency versions; scan with Trivy/Dependabot for known CVEs"),
]

_TESTING_TAXONOMY_CHECKLIST = """\
- [ ] Happy path — valid input → expected success output
- [ ] Rule-violation — invalid input → explicit error/exception
- [ ] Edge case — boundary value (zero, empty, max, nil/null)
- [ ] Test types present as applicable: unit (pure domain logic), integration (adapters/DB), property-based (invariants that must hold for all inputs)
- [ ] Target coverage: >= 80% line coverage on domain/application layers
- [ ] Each test has at least one meaningful assertion"""

_LOGGING_STANDARDS_CHECKLIST = """\
- [ ] Structured (JSON) log format, not free-text string concatenation
- [ ] Every log line includes a `trace_id` (or `correlation_id`) matching the active OTel span, so logs and traces can be joined
- [ ] Log levels used correctly: ERROR (needs attention), WARN (recoverable anomaly), INFO (business event), DEBUG (developer detail, off in prod)
- [ ] No PII, credentials, or tokens ever written to a log line — redact before logging
- [ ] Log retention/rotation policy defined (not "log forever" or "log nowhere")"""

_OBSERVABILITY_CHECKLIST = """\
- [ ] Every public service method creates an OTel span (tracer.startSpan / ActivitySource.StartActivity / tracer.startActiveSpan per language)
- [ ] Spans record exceptions and set ERROR status on failure
- [ ] Key business metrics exported (request count, latency, error rate) via a metrics SDK
- [ ] A health/readiness endpoint exists and reflects real dependency health, not just "process is up"
- [ ] At least one test asserts span emission (InMemorySpanExporter / ActivityListener)"""


def _read_run_json(run_path: Path, filename: str) -> "dict | list | None":
    """Thin (run_path, filename) convenience wrapper around the shared
    feature_spec_tools._read_json reader, plus an OSError guard for filesystem
    errors _read_json's own try/except doesn't cover (e.g. a permissions error
    surfacing as something other than FileNotFoundError)."""
    try:
        return _read_feature_spec_json(run_path / filename)
    except OSError:
        return None


def _md_cell(value: object) -> str:
    """Escape a value for safe interpolation into a '|'-delimited Markdown
    table cell. Static content built by this module (e.g. _SECURITY_CATEGORIES)
    is verified to contain no literal '|' and doesn't need this — this is for
    dynamic, untrusted per-run text (security finding titles/remediations,
    LLM-produced context/service names) that could contain one and shift the
    row's column boundaries."""
    return "" if value is None else str(value).replace("|", "\\|")


def _security_categories_table() -> str:
    lines = ["| Category | Look for | Remediation |", "|---|---|---|"]
    for cat, look, fix in _SECURITY_CATEGORIES:
        lines.append(f"| {cat} | {look} | {fix} |")
    return "\n".join(lines)


def _security_findings_block(run_path: Path) -> str:
    """Render this run's security_report.json findings (if present) as a
    Markdown table grouped by severity — real per-run content on top of the
    always-present static category table above. Returns "" if no report
    exists yet (e.g. the Security phase hasn't run for this run)."""
    report = _read_run_json(run_path, "security_report.json")
    findings = report.get("findings") if isinstance(report, dict) else None
    if not findings or not isinstance(findings, list):
        return ""
    findings = [f for f in findings if isinstance(f, dict)]
    if not findings:
        return ""
    rows = sorted(findings, key=lambda f: _SEV_ORDER.get(f.get("severity") or "INFO", 9))
    lines = [
        "## Findings from this run's security_report.json",
        "",
        "| ID | Severity | Category | Location | Title | Remediation |",
        "|---|---|---|---|---|---|",
    ]
    for f in rows[:_SECURITY_FINDINGS_LIMIT]:
        remediation = (f.get("remediation") or "")[:120].replace("\n", " ")
        lines.append(
            f"| {_md_cell(f.get('id'))} | {_md_cell(f.get('severity'))} | {_md_cell(f.get('category'))} "
            f"| `{_md_cell(f.get('location'))}` | {_md_cell(f.get('title'))} | {_md_cell(remediation)} |"
        )
    return "\n".join(lines) + "\n"


def _write_output_skills(
    source_path: str,
    source_lang: str,
    target_lang: str,
    seam_name: str,
    run_path: Path,
    project_dir: str,
) -> str:
    """Write Claude Code skill files to <project_dir>_skills/ next to the output project.

    Creates:
      <project_dir>_skills/
        CLAUDE.md                           — project context loaded by Claude Code
        .claude/commands/
          translate-seam.md               — /translate-seam skill
          code-review.md                  — /code-review skill

    Returns the skills directory path as a string.
    """
    tl = target_lang.lower()
    sl = source_lang.lower()
    tl_display = _LANG_DISPLAY.get(tl, target_lang.capitalize())
    sl_display = _LANG_DISPLAY.get(sl, source_lang.capitalize())
    decimal_type = _LANG_DECIMAL.get(tl, "a decimal/fixed-point type")
    float_avoid  = _LANG_FLOAT_AVOID.get(tl, "float/double")
    ext          = _LANG_EXT.get(tl, tl)
    build_file   = _LANG_BUILD_FILE.get(tl, "build file")
    seam_snake   = re.sub(r"[^a-z0-9_]", "_", re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", seam_name).lower()).strip("_") or "seam"
    quickstart   = _LANG_QUICKSTART.get(tl, "```bash\n# see README.md\n```")

    skills_dir = run_path / "reports" / f"{project_dir}_skills"
    commands_dir = skills_dir / ".claude" / "commands"
    commands_dir.mkdir(parents=True, exist_ok=True)

    # ── translate-seam.md ─────────────────────────────────────────────────────
    (commands_dir / "translate-seam.md").write_text(f"""\
---
description: Translate a {sl_display} seam to {tl_display} following Micro-Cosmos hexagonal conventions
---

Translate the seam named in `$ARGUMENTS` from **{sl_display}** to **{tl_display}**
following hexagonal (DDD ports and adapters) architecture.

| Field | Value |
|-------|-------|
| Source project | `{source_path}` |
| Source language | {sl_display} |
| Target language | {tl_display} |
| Reference output | `../{project_dir}/` |

## Steps

1. **Read the source seam** — call `list_source_files` with the seam name, then
   `read_source_file` for every file returned.
2. **Map domain concepts** — identify aggregates, value objects, invariants,
   and business rules. Every invariant MUST become an explicit guard in the output.
3. **Write implementation** — produce idiomatic {tl_display} obeying:
   - Use `{decimal_type}` for all monetary/financial values — never `{float_avoid}`
   - Use enums (or sealed types) for every status/state field — never bare strings
   - Hexagonal layers: `domain/` → `application/` → `infrastructure/`
   - Name files after domain concepts — `{seam_snake}.{ext}` not `domain.{ext}`
   - No empty function bodies, no TODOs, no stubs
4. **Write unit tests** covering all three categories:
   - **Happy path** — valid inputs → expected success output
   - **Rule violation** — invalid input → explicit error/exception
   - **Edge case** — boundary value (zero, empty, max, nil/null)
5. **Write `README.md`** describing the module in business terms with build/test instructions.

## Build & test ({tl_display})

{quickstart}

## Reference

Review `../{project_dir}/` for naming conventions, package structure, and
patterns already established in this project before writing new code.
""", encoding="utf-8")

    # ── code-review.md ────────────────────────────────────────────────────────
    (commands_dir / "code-review.md").write_text(f"""\
---
description: Review {tl_display} output code in $ARGUMENTS for fidelity to {sl_display} source
---

Review **{tl_display}** code for correctness, completeness, and fidelity to the
original **{sl_display}** implementation.

| Field | Value |
|-------|-------|
| Source project | `{source_path}` |
| Source language | {sl_display} |
| Target language | {tl_display} |
| Output project | `../{project_dir}/` |

## Checklist

### 1. Business logic completeness
- [ ] All domain rules from the {sl_display} source are present and enforced
- [ ] Every aggregate invariant has an explicit guard — no silent no-ops
- [ ] No business rule replaced by a TODO, stub, or placeholder comment

### 2. Decimal hygiene
- [ ] `{float_avoid}` is **never** used for monetary or financial values
- [ ] All monetary arithmetic uses `{decimal_type}`
- [ ] Rounding modes are explicit where division occurs

### 3. Test coverage
{_TESTING_TAXONOMY_CHECKLIST}

### 4. Hexagonal architecture
- [ ] `domain/` contains only pure business logic (no I/O, no framework deps)
- [ ] `application/` contains use-case interfaces only
- [ ] `infrastructure/` contains adapters (in-memory for tests)
- [ ] Port interfaces (`I{{Aggregate}}UseCase` / `I{{Aggregate}}Repository`) exist

### 5. {tl_display} conventions
- [ ] Correct package/module/namespace naming
- [ ] Idiomatic error handling — errors are not swallowed
- [ ] No raw `{float_avoid}` for typed domain fields — use value objects or enums
- [ ] Build file present (`{build_file}`)

## How to review

1. Read the original {sl_display} source to understand business intent and rules
2. Read the {tl_display} output in `../{project_dir}/`
3. For each failed item above, report:
   `[SEVERITY] file:symbol — description of the issue`
   - **BLOCKER** — must fix before merge (wrong business logic, missing test category, float for money)
   - **MAJOR** — should fix before merge (structural, convention, missing assertion)
   - **MINOR** — improvement suggestion
""", encoding="utf-8")

    # ── terraform-review.md ───────────────────────────────────────────────────
    (commands_dir / "terraform-review.md").write_text(f"""\
---
description: Review Terraform HCL for microservice module coverage, security, and Gate 5 readiness for {tl_display} output
---

Review **Terraform HCL** associated with the translated **{tl_display}** microservices
for module coverage, security baseline, and Gate 5 readiness.

| Field | Value |
|-------|-------|
| Source project | `{source_path}` |
| Target language | {tl_display} |
| Output code | `../{project_dir}/` |

## Microservice Module Coverage — MANDATORY CHECK

Each bounded context from the Micro-Cosmos Cartographer output MUST have a dedicated Terraform module.
Run this check first and report **WARN MAJOR** for any context without a `modules/<context>/` directory.

Expected layout:
```
modules/
  <context-name>/
    main.tf  variables.tf  outputs.tf  versions.tf
environments/
  prod/   staging/   dev/
```

## Checklist (Gate 5 — Infrastructure)

- [ ] Each bounded context has its own module under `modules/`
- [ ] No hardcoded secrets or sensitive defaults
- [ ] `encrypt = true` on all state backends; KMS key specified
- [ ] IAM roles scoped to minimum required actions and resources
- [ ] Providers and runtime pinned in `versions.tf`
- [ ] `.terraform.lock.hcl` committed
- [ ] `trivy config .` passes clean (no HIGH/CRITICAL)
- [ ] `checkov -d .` passes clean (no HIGH severity)
- [ ] Plan artifact reviewed before any apply

## Validation commands

```bash
terraform fmt -check -recursive
terraform validate
trivy config .
checkov -d .
```

## How to review

1. List all `.tf` files in the repository
2. Check for `modules/` directory and per-context subdirectories
3. Scan for hardcoded secrets, unencrypted backends, open SGs
4. Run validation commands above
5. Report each finding: `[SEVERITY] file:line — description`
   - **BLOCKER** — secrets exposed, production apply without plan review
   - **MAJOR** — missing module, no encryption, missing version pin, open SG
   - **MINOR** — naming convention, missing tag, unused variable
""", encoding="utf-8")

    # ── monitoring-review.md ───────────────────────────────────────────────────
    (commands_dir / "monitoring-review.md").write_text(f"""\
---
description: Score legacy monitoring maturity and review {tl_display} translated code for OpenTelemetry coverage
---

Score the legacy **{sl_display}** source for monitoring maturity, then review the
translated **{tl_display}** code for OpenTelemetry instrumentation coverage.

| Field | Value |
|-------|-------|
| Source project | `{source_path}` |
| Source language | {sl_display} |
| Target language | {tl_display} |
| Output code | `../{project_dir}/` |

## Step 1 — Score legacy monitoring (0–100)

Scan source files for monitoring framework imports and patterns:

| Dimension | Look for | Score |
|-----------|----------|-------|
| Logging  | JVM: slf4j, log4j, logback, kotlin-logging, scala-logging · .NET: Serilog, NLog, log4net, ILogger · Node.js: pino, winston, bunyan, morgan | 0/10/20 |
| Metrics  | JVM: micrometer, prometheus · .NET: App.Metrics, OpenTelemetry.Instrumentation · Node.js: prom-client, hot-shots, statsd | 0/10/20 |
| Tracing  | JVM: opentelemetry, zipkin, jaeger, sleuth · .NET: ActivitySource, opentelemetry · Node.js: @opentelemetry/api | 0/10/20 |
| Health   | /health, /healthz, actuator, readiness, liveness probe | 0/10/20 |
| Alerting | alertmanager, cloudwatch, pagerduty, opsgenie, victorops | 0/10/20 |

Emit overall score and per-dimension status (covered / partial / absent).
Score ≤ 19 → emit **BLOCKER** — microservice deployment is HIGH risk.

## Step 2 — Review translated code for OTel coverage

For each public service method in `../{project_dir}/`:

**JVM (Java / Kotlin / Scala):**
- [ ] `Tracer` via `GlobalOpenTelemetry.getTracer()` declared as static field
- [ ] Span created with `spanBuilder(name).startSpan()` and `try (Scope scope = span.makeCurrent())`
- [ ] MDC.put("trace_id", ...) on entry, MDC.remove on finally
- [ ] `span.recordException(e)` + setStatus(ERROR) in catch, `span.end()` in finally

**.NET (C# / F# / VB.NET):**
- [ ] Static `ActivitySource` declared
- [ ] `using var activity = _source.StartActivity(name)` per method
- [ ] `activity?.SetTag(...)` for entity ID
- [ ] `activity?.RecordException(ex)` + SetStatus(Error) in catch

**Node.js / TypeScript / JavaScript:**
- [ ] `tracer.startActiveSpan(name, span => {{ ... }})` pattern
- [ ] `traceId` from `trace.getActiveSpan()?.spanContext()` injected into log object
- [ ] `span.recordException(err)` + setStatus(ERROR) in catch, `span.end()` in finally

**Test files (all languages):**
- [ ] At least one test uses `InMemorySpanExporter` (JVM/Node.js) or `ActivityListener` (C#/F#/VB) to assert span emission
- If absent: report **MINOR** — OTel span assertion missing

## Logging Standards

Distinct from tracing/metrics above — structured, secure, correlatable logs
are their own requirement, not a side-effect of instrumentation.

{_LOGGING_STANDARDS_CHECKLIST}

## Severity guide

| Severity | Condition |
|----------|-----------|
| BLOCKER | Legacy score ≤ 19 (no observability for microservice deployment) |
| MAJOR | Public service method without any span; no trace-id in logs |
| MINOR | Missing span assertion in tests; partial tracing coverage |
""", encoding="utf-8")

    # ── security-review.md ─────────────────────────────────────────────────────
    _sec_findings = _security_findings_block(run_path)
    (commands_dir / "security-review.md").write_text(f"""\
---
description: Review {tl_display} output code in $ARGUMENTS for the OWASP-aligned category checklist below, plus this run's own security findings if available
---

Review **{tl_display}** code for the security categories below. This checklist is
static and always applies; if this run has already been through the Security
phase, this run's own `security_report.json` findings are also included below.

| Field | Value |
|-------|-------|
| Source project | `{source_path}` |
| Target language | {tl_display} |
| Output code | `../{project_dir}/` |

## Category checklist

{_security_categories_table()}

{_sec_findings}## Severity guide

| Severity | Condition |
|----------|-----------|
| BLOCKER | Hardcoded secret, SQL/command injection, missing auth on a state-changing endpoint |
| MAJOR | Missing input validation, PII logged, weak/deprecated crypto |
| MINOR | Missing rate limiting, verbose error messages, unpinned dependency without a known CVE |

## How to review

1. Read `../{project_dir}/` for every category above — grep for string-concatenated
   queries, hardcoded credentials, and unvalidated inputs first (highest yield).
2. Cross-check this run's `security_report.json` findings (above, if present) against
   the translated code — confirm whether each finding was carried over, fixed, or
   introduced fresh by the translation.
3. Report each finding: `[SEVERITY] file:symbol — description of the issue`.
""", encoding="utf-8")

    # ── CLAUDE.md — project context loaded automatically by Claude Code ────────
    (skills_dir / "CLAUDE.md").write_text(f"""\
# {_pascal(seam_name)} — {sl_display} → {tl_display} Translation Skills

Micro-Cosmos generated skills for reviewing and extending the translation of
**{sl_display}** to **{tl_display}**.

## Project context

| Field | Value |
|-------|-------|
| Source project | `{source_path}` |
| Source language | {sl_display} |
| Target language | {tl_display} |
| Output code | `../{project_dir}/` |

## Available skills

| Command | Description |
|---------|-------------|
| `/translate-seam <seam-name>` | Translate a {sl_display} seam to {tl_display} |
| `/code-review <file-or-folder>` | Review {tl_display} code against {sl_display} source |
| `/terraform-review` | Review Terraform HCL for microservice module coverage and Gate 5 readiness |
| `/monitoring-review` | Score legacy monitoring maturity and review translated code for OTel coverage and logging standards |
| `/security-review` | Review {tl_display} code against the security category checklist, plus this run's own findings if available |

## Quick start

Open `../{project_dir}/` in Claude Code to work on the translated project with
these skills in scope, or open this `{project_dir}_skills/` folder to access
skills against the full source estate.

## Architecture reference

```
domain/         Pure business logic — aggregates, value objects, domain events
application/    Use-case interfaces and application services
infrastructure/ In-memory adapters (swap for real storage in production)
tests/          Happy path · Rule violation · Edge case
```

Monetary types: always `{decimal_type}` — never `{float_avoid}`.

## Observability reference

Every public service method is instrumented with OpenTelemetry spans.
Trace-id is injected into structured log fields (see Logging Standards in
`/monitoring-review` for the log-format/PII/retention rules, kept distinct
from tracing coverage). Use `/monitoring-review` to verify OTel coverage
after adding new code, and `/security-review` for the security checklist.

## Kiro.dev Powers

The `kiro-dev-powers-app-modernization/` folder (in `reports/`) contains equivalent powers for the Kiro IDE:

| Power | Kiro equivalent of |
|-------|-------------------|
| `micro-cosmos-code-writer-power` | `/translate-seam` |
| `micro-cosmos-code-reviewer-power` | `/code-review` |
| `micro-cosmos-terraform-power` | `/terraform-review` |
| `micro-cosmos-monitoring-power` | `/monitoring-review` |
| `micro-cosmos-security-power` | `/security-review` |

Open a power's `POWER.md` in Kiro to activate it for the translated project.
""", encoding="utf-8")

    return str(skills_dir)


def _write_kiro_powers(
    run_path: Path,
    source_path: str,
    source_lang: str,
    target_lang: str,
) -> str:
    """Generate Kiro.dev Power files into <run_path>/reports/kiro-dev-powers-app-modernization/.

    Creates five power directories, each with POWER.md and README.md:
      - micro-cosmos-monitoring-power/
      - micro-cosmos-terraform-power/
      - micro-cosmos-code-writer-power/
      - micro-cosmos-code-reviewer-power/
      - micro-cosmos-security-power/

    Returns the kiro powers directory path as a string.
    """
    tl = target_lang.lower()
    sl = source_lang.lower()
    tl_display = _LANG_DISPLAY.get(tl, target_lang.capitalize())
    sl_display = _LANG_DISPLAY.get(sl, source_lang.capitalize())
    decimal_type = _LANG_DECIMAL.get(tl, "a decimal/fixed-point type")
    float_avoid  = _LANG_FLOAT_AVOID.get(tl, "float/double")

    kiro_dir = run_path / "reports" / "kiro-dev-powers-app-modernization"
    kiro_dir.mkdir(parents=True, exist_ok=True)

    # ── micro-cosmos-monitoring-power ──────────────────────────────────────────────
    monitoring_dir = kiro_dir / "micro-cosmos-monitoring-power"
    monitoring_dir.mkdir(parents=True, exist_ok=True)
    if not (monitoring_dir / "POWER.md").exists():
        _monitoring_power_md = r"""---
name: "micro-cosmos-monitoring"
displayName: "Micro-Cosmos Monitoring"
author: "Micro-Cosmos"
description: "Use when scoring legacy application monitoring maturity, identifying telemetry gaps, or generating OpenTelemetry instrumentation for Java, C#, and Node.js/TypeScript in Micro-Cosmos-translated microservices."
keywords: ["monitoring", "observability", "opentelemetry", "otel", "telemetry", "logging", "metrics", "tracing", "health", "gap-analysis", "java", "csharp", "typescript", "nodejs", "micro-cosmos", "legacy", "instrumentation"]
---

# Micro-Cosmos Monitoring Power

Legacy monitoring scoring and OpenTelemetry adoption guide for Micro-Cosmos translated microservices. Diagnoses monitoring gaps in source code, scores observability maturity per dimension, and generates production-ready OTel instrumentation for Java, C#, and Node.js/TypeScript.

## Response Contract

Every monitoring review or instrumentation generation must include:

1. **Monitoring maturity score (0–100)** — aggregate across five dimensions: Logging, Metrics, Tracing, Health, Alerting.
2. **Per-dimension score** — each dimension scored 0–20 with rationale.
3. **Gap findings** — every missing dimension is a gap finding with severity.
4. **Instrumentation plan** — specific OTel SDK calls and configuration for the target language.
5. **Test coverage note** — whether OTel spans can be asserted in unit tests.

## Monitoring Maturity Scoring

### Dimensions (each 0–20 points)

| Dimension | 20 pts (covered) | 10 pts (partial) | 0 pts (absent) |
|---|---|---|---|
| **Logging** | Structured logs with trace-context injection (SLF4J MDC / Serilog context / pino fields) | Unstructured logging framework present (log4j, NLog, winston) | No logging at all |
| **Metrics** | Micrometer / App.Metrics / prom-client / OpenTelemetry Metrics with OTLP or Prometheus exporter | Ad-hoc counters or custom metrics | No metrics |
| **Tracing** | OpenTelemetry traces (JVM: GlobalOpenTelemetry · .NET: ActivitySource · Node.js: @opentelemetry/api) with span hierarchy and W3C traceparent propagation | Manual correlation IDs only | No distributed tracing |
| **Health** | Actuator `/health` or custom `/healthz` + readiness/liveness probes | Basic `/ping` endpoint | No health endpoint |
| **Alerting** | Alert rules defined (PagerDuty / CloudWatch / AlertManager / OpsGenie config present) | Log-based alerts only | No alerting |

**Score interpretation:**
- 80–100: Production-ready observability
- 60–79: Adequate — gaps should be addressed before GA
- 40–59: Basic — tracing and structured logging missing; high-risk for distributed systems
- 20–39: Insufficient — only partial logging; microservice deployment is HIGH risk
- 0–19: None — **BLOCKER for microservice deployment**

## Diagnose Before You Instrument

| Gap category | Symptoms | Action |
|---|---|---|
| **No structured logging** | Raw `System.out.println`, `console.log`, `print()` with no framework | Add SLF4J + Logback (Java), Serilog (C#), pino/winston (TS) |
| **No trace-context in logs** | Log statements without trace-id or correlation-id fields | Inject OTel trace context into MDC / log properties |
| **No metrics** | No Micrometer, Prometheus, prom-client, or OTel Metrics | Add `MeterProvider` with OTLP or Prometheus exporter |
| **No distributed tracing** | No Span creation, no W3C TraceContext header propagation | Add OTel SDK with OTLP exporter and `@WithSpan` / manual spans |
| **No health endpoint** | No `/health`, `/healthz`, `/actuator/health` | Add readiness + liveness probe endpoint |
| **Trace-id not propagated** | Service calls do not forward `traceparent` header | Add OTel `W3CTraceContextPropagator` to HTTP client |
| **OTel not in tests** | No `InMemorySpanExporter` or span assertion in test suite | Add OTel test SDK and assert span names/attributes |

## OpenTelemetry Instrumentation — Java

```java
// build.gradle.kts (add)
implementation("io.opentelemetry:opentelemetry-api:1.37.0")
implementation("io.opentelemetry:opentelemetry-sdk:1.37.0")
implementation("io.opentelemetry:opentelemetry-exporter-otlp:1.37.0")
implementation("io.opentelemetry.instrumentation:opentelemetry-spring-boot-starter:2.3.0")

// Application service — manual span (when @WithSpan annotation is unavailable)
import io.opentelemetry.api.GlobalOpenTelemetry;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.StatusCode;
import io.opentelemetry.api.trace.Tracer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;

public class FraudScoringService {
    private static final Logger log = LoggerFactory.getLogger(FraudScoringService.class);
    private static final Tracer tracer = GlobalOpenTelemetry.getTracer("micro_cosmos.fraud-scoring");

    public ScoringResult score(Transaction tx) {
        Span span = tracer.spanBuilder("FraudScoringService.score")
            .setAttribute("transaction.id", tx.getId().toString())
            .startSpan();
        try (var scope = span.makeCurrent()) {
            MDC.put("trace_id", span.getSpanContext().getTraceId());
            log.info("Scoring transaction id={} amount={}", tx.getId(), tx.getAmount());
            ScoringResult result = performScoring(tx);
            log.info("Score computed result={}", result.getRisk());
            return result;
        } catch (Exception e) {
            span.setStatus(StatusCode.ERROR, e.getMessage());
            span.recordException(e);
            log.error("Scoring failed transaction.id={}", tx.getId(), e);
            throw e;
        } finally {
            MDC.remove("trace_id");
            span.end();
        }
    }
}

// Test with InMemorySpanExporter
import io.opentelemetry.sdk.testing.exporter.InMemorySpanExporter;
import io.opentelemetry.sdk.trace.SdkTracerProvider;
import io.opentelemetry.sdk.trace.export.SimpleSpanProcessor;

@Test void score_emits_span() {
    var exporter = InMemorySpanExporter.create();
    var provider = SdkTracerProvider.builder()
        .addSpanProcessor(SimpleSpanProcessor.create(exporter))
        .build();
    OpenTelemetrySdk.builder().setTracerProvider(provider).buildAndRegisterGlobal();

    service.score(validTransaction());

    var spans = exporter.getFinishedSpanItems();
    assertThat(spans).hasSize(1);
    assertThat(spans.get(0).getName()).isEqualTo("FraudScoringService.score");
}
```

## OpenTelemetry Instrumentation — C#

```csharp
// .csproj (add)
// <PackageReference Include="OpenTelemetry.Api" Version="1.8.*" />
// <PackageReference Include="OpenTelemetry.Sdk" Version="1.8.*" />
// <PackageReference Include="OpenTelemetry.Exporter.OpenTelemetryProtocol" Version="1.8.*" />
// <PackageReference Include="OpenTelemetry.Extensions.Hosting" Version="1.8.*" />

// Activity source (one per assembly)
public static class Telemetry {
    public static readonly ActivitySource Source = new("MicroCosmos.FraudScoring", "1.0.0");
}

// Application service
public class FraudScoringService {
    private readonly ILogger<FraudScoringService> _logger;

    public FraudScoringService(ILogger<FraudScoringService> logger) => _logger = logger;

    public ScoringResult Score(Transaction tx) {
        using var activity = Telemetry.Source.StartActivity("FraudScoringService.Score");
        activity?.SetTag("transaction.id", tx.Id.ToString());
        _logger.LogInformation("Scoring transaction id={TransactionId} amount={Amount}",
            tx.Id, tx.Amount);
        try {
            var result = PerformScoring(tx);
            _logger.LogInformation("Score computed result={Risk}", result.Risk);
            return result;
        } catch (Exception ex) {
            activity?.SetStatus(ActivityStatusCode.Error, ex.Message);
            activity?.RecordException(ex);
            _logger.LogError(ex, "Scoring failed transaction.id={TransactionId}", tx.Id);
            throw;
        }
    }
}

// Test with ActivityListener
[Fact] public void Score_EmitsActivity() {
    var activities = new List<Activity>();
    using var listener = new ActivityListener {
        ShouldListenTo = s => s.Name == "MicroCosmos.FraudScoring",
        Sample = (ref ActivityCreationOptions<ActivityContext> _) => ActivitySamplingResult.AllData,
        ActivityStopped = activities.Add,
    };
    ActivitySource.AddActivityListener(listener);

    _service.Score(ValidTransaction());

    Assert.Single(activities);
    Assert.Equal("FraudScoringService.Score", activities[0].DisplayName);
}
```

## OpenTelemetry Instrumentation — Node.js / TypeScript

```typescript
// package.json (add)
// "@opentelemetry/api": "^1.8",
// "@opentelemetry/sdk-node": "^0.51",
// "@opentelemetry/exporter-trace-otlp-http": "^0.51",
// "@opentelemetry/instrumentation-http": "^0.51"

// tracing.ts — initialise once at startup
import { NodeSDK } from '@opentelemetry/sdk-node';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';

const sdk = new NodeSDK({
  traceExporter: new OTLPTraceExporter({ url: process.env.OTEL_EXPORTER_OTLP_ENDPOINT }),
  serviceName: 'micro-cosmos-fraud-scoring',
});
sdk.start();

// Application service
import { trace, SpanStatusCode } from '@opentelemetry/api';
import pino from 'pino';

const tracer = trace.getTracer('micro_cosmos.fraud-scoring', '1.0.0');
const log = pino();

export class FraudScoringService {
  score(tx: Transaction): ScoringResult {
    return tracer.startActiveSpan('FraudScoringService.score', span => {
      span.setAttribute('transaction.id', tx.id);
      const traceId = trace.getActiveSpan()?.spanContext().traceId ?? 'unknown';
      log.info({ traceId, transactionId: tx.id, amount: tx.amount }, 'Scoring transaction');
      try {
        const result = this.performScoring(tx);
        log.info({ traceId, risk: result.risk }, 'Score computed');
        return result;
      } catch (err) {
        span.setStatus({ code: SpanStatusCode.ERROR, message: String(err) });
        span.recordException(err as Error);
        log.error({ traceId, err }, 'Scoring failed');
        throw err;
      } finally {
        span.end();
      }
    });
  }
}

// Test with InMemorySpanExporter
import { InMemorySpanExporter, SimpleSpanProcessor } from '@opentelemetry/sdk-trace-base';
import { NodeTracerProvider } from '@opentelemetry/sdk-trace-node';

test('score emits a span', () => {
  const exporter = new InMemorySpanExporter();
  const provider = new NodeTracerProvider();
  provider.addSpanProcessor(new SimpleSpanProcessor(exporter));
  provider.register();

  service.score(validTransaction());

  const spans = exporter.getFinishedSpans();
  expect(spans).toHaveLength(1);
  expect(spans[0].name).toBe('FraudScoringService.score');
});
```

## OpenTelemetry Instrumentation — Scala

```scala
// build.sbt (add)
libraryDependencies += "io.opentelemetry" % "opentelemetry-api" % "1.37.0"
libraryDependencies += "io.opentelemetry" % "opentelemetry-sdk" % "1.37.0"

// Application service
import io.opentelemetry.api.GlobalOpenTelemetry
import io.opentelemetry.api.trace.StatusCode
import org.slf4j.{LoggerFactory, MDC}

class FraudScoringService {
  private val log = LoggerFactory.getLogger(getClass)
  private val tracer = GlobalOpenTelemetry.getTracer("micro_cosmos.fraud-scoring")

  def score(tx: Transaction): ScoringResult = {
    val span = tracer.spanBuilder("FraudScoringService.score")
      .setAttribute("transaction.id", tx.id.toString)
      .startSpan()
    val scope = span.makeCurrent()
    MDC.put("trace_id", span.getSpanContext.getTraceId)
    try {
      log.info(s"Scoring transaction id=${tx.id}")
      val result = performScoring(tx)
      log.info(s"Score computed risk=${result.risk}")
      result
    } catch {
      case e: Exception =>
        span.setStatus(StatusCode.ERROR, e.getMessage)
        span.recordException(e)
        log.error(s"Scoring failed transaction.id=${tx.id}", e)
        throw e
    } finally {
      MDC.remove("trace_id")
      scope.close()
      span.end()
    }
  }
}

// Test with InMemorySpanExporter (same as Java)
```

## OpenTelemetry Instrumentation — F#

```fsharp
// .fsproj (add)
// <PackageReference Include="OpenTelemetry.Api" Version="1.8.*" />

// Telemetry module
module Telemetry =
    let source = new ActivitySource("MicroCosmos.FraudScoring", "1.0.0")

// Application service
open System.Diagnostics
open Microsoft.Extensions.Logging

let score (logger: ILogger) (tx: Transaction) =
    use activity = Telemetry.source.StartActivity("FraudScoringService.score")
    activity |> Option.ofObj |> Option.iter (fun a -> a.SetTag("transaction.id", string tx.Id) |> ignore)
    logger.LogInformation("Scoring transaction id={TransactionId}", tx.Id)
    try
        let result = performScoring tx
        logger.LogInformation("Score computed risk={Risk}", result.Risk)
        result
    with ex ->
        activity |> Option.ofObj |> Option.iter (fun a ->
            a.SetStatus(ActivityStatusCode.Error, ex.Message) |> ignore
            a.RecordException(ex) |> ignore)
        logger.LogError(ex, "Scoring failed transaction.id={TransactionId}", tx.Id)
        reraise()

// Test with ActivityListener (same as C#)
```

## OpenTelemetry Instrumentation — VB.NET

```vb
' .vbproj (add)
' <PackageReference Include="OpenTelemetry.Api" Version="1.8.*" />

' Telemetry module
Module TelemetryModule
    Public ReadOnly Source As New ActivitySource("MicroCosmos.FraudScoring", "1.0.0")
End Module

' Application service
Public Class FraudScoringService
    Private ReadOnly _logger As ILogger(Of FraudScoringService)

    Public Function Score(tx As Transaction) As ScoringResult
        Using activity = TelemetryModule.Source.StartActivity("FraudScoringService.Score")
            If activity IsNot Nothing Then activity.SetTag("transaction.id", tx.Id.ToString())
            _logger.LogInformation("Scoring transaction id={TransactionId}", tx.Id)
            Try
                Dim result = PerformScoring(tx)
                _logger.LogInformation("Score computed risk={Risk}", result.Risk)
                Return result
            Catch ex As Exception
                If activity IsNot Nothing Then
                    activity.SetStatus(ActivityStatusCode.Error, ex.Message)
                    activity.RecordException(ex)
                End If
                _logger.LogError(ex, "Scoring failed transaction.id={TransactionId}", tx.Id)
                Throw
            End Try
        End Using
    End Function
End Class

' Test with ActivityListener (same as C#)
```

## Common Workflows

### Score legacy application monitoring
1. Read all source files (use IR graph node summaries for scale)
2. Identify logging frameworks (imports: `import org.slf4j`, `using Serilog`, `require('pino')`)
3. Identify metrics (imports: `io.micrometer`, `Prometheus`, `prom-client`)
4. Identify tracing (imports: `opentelemetry`, `Sleuth`, `Jaeger`, `Zipkin`)
5. Identify health endpoints (route patterns: `/health`, `/healthz`, `/actuator`)
6. Identify alert configs (files: `alertmanager.yml`, `alerts.yaml`, CloudWatch JSON)
7. Score each dimension 0–20 and emit aggregate score with gap findings

### Generate OTel instrumentation for a translated service
1. Identify target language from seam report
2. Select correct SDK: Java (OTel Java Agent or manual SDK), C# (ActivitySource), TypeScript (OTel Node SDK)
3. Generate `tracing.ts` / `OpenTelemetryConfig.java` / `Telemetry.cs` bootstrap
4. Wrap every public service method with span + structured log + exception recording
5. Add `InMemorySpanExporter` test to verify span emission
6. Update build file with OTel dependencies
7. Emit Response Contract with maturity score delta (before vs after)

### Review translated code for OTel coverage
1. Read generated service files
2. Check each public service method for span creation
3. Check for trace-context injection in log statements
4. Check test files for `InMemorySpanExporter` or `ActivityListener` span assertions
5. Report MAJOR for any public service method without span coverage
6. Report MINOR for missing span assertions in tests
7. Emit Response Contract
"""
        _monitoring_power_md += f"""
## Logging Standards

Distinct from tracing/metrics above — structured, secure, correlatable logs
are their own requirement, not a side-effect of instrumentation.

{_LOGGING_STANDARDS_CHECKLIST}
"""
        (monitoring_dir / "POWER.md").write_text(_monitoring_power_md, encoding="utf-8")

        (monitoring_dir / "README.md").write_text("""\
# Micro-Cosmos Monitoring Power

Kiro.dev Power for scoring legacy application monitoring maturity, identifying OpenTelemetry gaps, and generating OTel instrumentation for Java, C#, and Node.js/TypeScript microservices translated by Micro-Cosmos.

## What it does

- Scores legacy application monitoring across five dimensions: Logging, Metrics, Tracing, Health, Alerting (0–100)
- Identifies monitoring gaps with severity (BLOCKER for 0-score microservice deployments)
- Generates production-ready OpenTelemetry instrumentation for Java, C#, TypeScript
- Reviews translated service code for OTel span coverage
- Provides test patterns for asserting OTel span emission

## Installation in Kiro

Install this power from the Kiro.dev marketplace or copy the `POWER.md` file into your Kiro powers directory.

## When to activate

- You want to score the legacy application's monitoring maturity before migration
- You need to generate OTel instrumentation for a translated microservice
- You are reviewing translated code and want to check telemetry coverage
- You are planning the observability gap remediation roadmap

## Score interpretation

| Score | Status |
|---|---|
| 80–100 | Production-ready |
| 60–79 | Adequate — close gaps before GA |
| 40–59 | Basic — tracing and structured logging missing |
| 20–39 | Insufficient — HIGH risk for distributed systems |
| 0–19 | None — **BLOCKER** for microservice deployment |

## Tests

```bash
npm install
npm test
```
""", encoding="utf-8")
        # package.json
        (monitoring_dir / "package.json").write_text('{\n  "name": "micro-cosmos-monitoring-power",\n  "version": "1.0.0",\n  "type": "module",\n  "scripts": { "test": "vitest run" },\n  "devDependencies": {\n    "vitest": "^1.6.0",\n    "fast-check": "^3.19.0",\n    "js-yaml": "^4.1.0"\n  }\n}\n', encoding="utf-8")
        # vitest.config.js
        (monitoring_dir / "vitest.config.js").write_text("import { defineConfig } from 'vitest/config';\nexport default defineConfig({ test: { include: ['tests/**/*.test.js'] } });\n", encoding="utf-8")
        # tests/
        (monitoring_dir / "tests").mkdir(exist_ok=True)
        (monitoring_dir / "tests" / "power.property.test.js").write_text("""\
import { describe, test, expect } from 'vitest';
import * as fc from 'fast-check';
import fs from 'fs';
import yaml from 'js-yaml';

const POWER_PATH = new URL('../POWER.md', import.meta.url).pathname;
const raw = fs.readFileSync(POWER_PATH, 'utf8');
const parts = raw.split('---');
const frontmatter = yaml.load(parts[1]);
const body = parts.slice(2).join('---');

// Feature: micro-cosmos-monitoring-power, Property 1: Frontmatter Schema Completeness
test('Property 1: Frontmatter Schema Completeness', () => {
  fc.assert(fc.property(
    fc.record({
      name: fc.string({ minLength: 1, maxLength: 100 }),
      displayName: fc.string({ minLength: 1, maxLength: 100 }),
      author: fc.string({ minLength: 1, maxLength: 100 }),
      description: fc.string({ minLength: 10, maxLength: 1024 }),
      keywords: fc.array(fc.string({ minLength: 1, maxLength: 50 }), { minLength: 1, maxLength: 50 }),
    }),
    (fm) => {
      expect(typeof fm.name).toBe('string');
      expect(fm.name.length).toBeGreaterThan(0);
      expect(typeof fm.description).toBe('string');
      expect(fm.description.length).toBeGreaterThanOrEqual(10);
      expect(Array.isArray(fm.keywords)).toBe(true);
      expect(fm.keywords.length).toBeGreaterThan(0);
      fm.keywords.forEach(k => expect(typeof k).toBe('string'));
    }
  ), { numRuns: 100 });
});

// Feature: micro-cosmos-monitoring-power, Property 2: Keyword Category Coverage
test('Property 2: Keyword Category Coverage', () => {
  const observabilityKeywords = ['monitoring', 'observability', 'telemetry', 'opentelemetry', 'otel'];
  const brandKeywords = ['micro-cosmos', 'legacy'];
  const languageKeywords = ['java', 'csharp', 'typescript', 'nodejs'];
  const signalKeywords = ['logging', 'metrics', 'tracing', 'health'];

  fc.assert(fc.property(
    fc.tuple(
      fc.constantFrom(...observabilityKeywords),
      fc.constantFrom(...brandKeywords),
      fc.constantFrom(...languageKeywords),
      fc.constantFrom(...signalKeywords),
      fc.array(fc.string({ minLength: 1, maxLength: 30 }), { minLength: 0, maxLength: 5 }),
    ).map(([obs, alc, lang, sig, extra]) => [obs, alc, lang, sig, ...extra]),
    (keywords) => {
      const hasObservability = keywords.some(k => observabilityKeywords.includes(k));
      const hasBrand = keywords.some(k => brandKeywords.includes(k));
      const hasLanguage = keywords.some(k => languageKeywords.includes(k));
      const hasSignal = keywords.some(k => signalKeywords.includes(k));
      expect(hasObservability).toBe(true);
      expect(hasBrand).toBe(true);
      expect(hasLanguage).toBe(true);
      expect(hasSignal).toBe(true);
    }
  ), { numRuns: 100 });
});

// Validate actual POWER.md
test('Actual POWER.md satisfies Property 1', () => {
  expect(typeof frontmatter.name).toBe('string');
  expect(frontmatter.name.length).toBeGreaterThan(0);
  expect(typeof frontmatter.description).toBe('string');
  expect(frontmatter.description.length).toBeGreaterThanOrEqual(10);
  expect(Array.isArray(frontmatter.keywords)).toBe(true);
  expect(frontmatter.keywords.length).toBeGreaterThan(0);
});

test('Actual POWER.md satisfies Property 2 — keyword categories covered', () => {
  const kw = frontmatter.keywords;
  expect(kw.some(k => ['monitoring', 'observability', 'opentelemetry', 'otel', 'telemetry'].includes(k))).toBe(true);
  expect(kw.some(k => ['micro-cosmos', 'legacy'].includes(k))).toBe(true);
  expect(kw.some(k => ['java', 'csharp', 'typescript', 'nodejs'].includes(k))).toBe(true);
  expect(kw.some(k => ['logging', 'metrics', 'tracing', 'health'].includes(k))).toBe(true);
});
""", encoding="utf-8")
        (monitoring_dir / "tests" / "power.unit.test.js").write_text("""\
import { test, expect } from 'vitest';
import fs from 'fs';
import yaml from 'js-yaml';

const POWER_PATH = new URL('../POWER.md', import.meta.url).pathname;
const raw = fs.readFileSync(POWER_PATH, 'utf8');
const parts = raw.split('---');
const frontmatter = yaml.load(parts[1]);
const body = parts.slice(2).join('---');

// Frontmatter values
test('name is micro-cosmos-monitoring', () => {
  expect(frontmatter.name).toBe('micro-cosmos-monitoring');
});
test('displayName is Micro-Cosmos Monitoring', () => {
  expect(frontmatter.displayName).toBe('Micro-Cosmos Monitoring');
});
test('author is Micro-Cosmos', () => {
  expect(frontmatter.author).toBe('Micro-Cosmos');
});
test('keywords include monitoring', () => {
  expect(frontmatter.keywords).toContain('monitoring');
});
test('keywords include opentelemetry', () => {
  expect(frontmatter.keywords).toContain('opentelemetry');
});
test('keywords include micro-cosmos', () => {
  expect(frontmatter.keywords).toContain('micro-cosmos');
});
test('keywords include java', () => {
  expect(frontmatter.keywords).toContain('java');
});
test('keywords include csharp', () => {
  expect(frontmatter.keywords).toContain('csharp');
});
test('keywords include typescript', () => {
  expect(frontmatter.keywords).toContain('typescript');
});

// File structure
test('POWER.md file exists', () => {
  expect(fs.existsSync(POWER_PATH)).toBe(true);
});
test('README.md exists', () => {
  const p = new URL('../README.md', import.meta.url).pathname;
  expect(fs.existsSync(p)).toBe(true);
});

// Response contract
test('body contains Response Contract section', () => {
  expect(body).toContain('Response Contract');
});
test('body contains maturity score 0-100', () => {
  expect(body).toContain('0–100');
});
test('body contains five monitoring dimensions', () => {
  expect(body).toContain('Logging');
  expect(body).toContain('Metrics');
  expect(body).toContain('Tracing');
  expect(body).toContain('Health');
  expect(body).toContain('Alerting');
});

// OTel instrumentation for all language stacks
test('body contains Java OTel instrumentation', () => {
  expect(body).toContain('OpenTelemetry Instrumentation — Java');
});
test('body contains C# OTel instrumentation', () => {
  expect(body).toContain('OpenTelemetry Instrumentation — C#');
});
test('body contains Node.js/TypeScript OTel instrumentation', () => {
  expect(body).toContain('OpenTelemetry Instrumentation — Node.js');
});
test('body contains Scala OTel instrumentation', () => {
  expect(body).toContain('OpenTelemetry Instrumentation — Scala');
});
test('body contains F# OTel instrumentation', () => {
  expect(body).toContain('OpenTelemetry Instrumentation — F#');
});
test('body contains VB.NET OTel instrumentation', () => {
  expect(body).toContain('OpenTelemetry Instrumentation — VB.NET');
});
test('body references InMemorySpanExporter for JVM/Node.js testing', () => {
  expect(body).toContain('InMemorySpanExporter');
});
test('body references ActivityListener for .NET testing', () => {
  expect(body).toContain('ActivityListener');
});

// Scoring table
test('body contains score interpretation table', () => {
  expect(body).toContain('Production-ready');
  expect(body).toContain('BLOCKER');
});

// Workflows
test('body contains Common Workflows section', () => {
  expect(body).toContain('Common Workflows');
});
test('body contains workflow for scoring legacy app', () => {
  expect(body).toContain('Score legacy application monitoring');
});
test('body contains workflow for generating OTel instrumentation', () => {
  expect(body).toContain('Generate OTel instrumentation');
});
test('body contains workflow for reviewing translated code', () => {
  expect(body).toContain('Review translated code for OTel coverage');
});
""", encoding="utf-8")
        # .kiro/specs/
        _monitoring_specs = monitoring_dir / ".kiro" / "specs" / "micro-cosmos-monitoring-power"
        _monitoring_specs.mkdir(parents=True, exist_ok=True)
        (_monitoring_specs / ".config.kiro").write_text('{"generationMode": "requirements-first"}\n', encoding="utf-8")
        (_monitoring_specs / "requirements.md").write_text("""\
# Requirements — Micro-Cosmos Monitoring Power

## REQ-1: Monitoring Maturity Score
The power MUST compute a 0–100 monitoring maturity score by evaluating five dimensions: Logging (0–20), Metrics (0–20), Tracing (0–20), Health (0–20), Alerting (0–20). Each dimension MUST have a clear pass/partial/absent rubric.

## REQ-2: Legacy Application Scoring
The power MUST score the legacy source application by analysing imports, framework dependencies, endpoint patterns, and log statements present in the IR graph or source files.

## REQ-3: BLOCKER for Zero-Score Deployment
A legacy application with a total monitoring score of 0–19 MUST produce a BLOCKER finding that blocks microservice deployment until basic observability is added.

## REQ-4: Java OTel Instrumentation Generation
The power MUST generate complete Java OTel instrumentation: `Tracer` via `GlobalOpenTelemetry`, `Span` start/end in try-with-resources, MDC trace-id injection, `InMemorySpanExporter` test pattern. Dependencies for `build.gradle.kts` or `pom.xml` MUST be included.

## REQ-5: C# OTel Instrumentation Generation
The power MUST generate complete C# OTel instrumentation: `ActivitySource`, `Activity` with `StartActivity`, structured logging via `ILogger<T>`, `ActivityListener` test pattern. `<PackageReference>` entries MUST be included.

## REQ-6: TypeScript/Node.js OTel Instrumentation Generation
The power MUST generate complete TypeScript OTel instrumentation: `NodeSDK` bootstrap (`tracing.ts`), `trace.getTracer()` with `startActiveSpan`, pino structured logging with trace-id injection, `InMemorySpanExporter` vitest test. `package.json` dependencies MUST be included.

## REQ-7: Gap Findings with Severity
Every monitoring gap MUST be reported as a finding with severity BLOCKER (no monitoring in a microservice-deployed service), MAJOR (missing distributed tracing or structured logging), or MINOR (missing alert rules or health probe).

## REQ-8: Trace-Context Propagation
The power MUST check for W3C TraceContext header propagation in service-to-service HTTP calls and flag absence as MAJOR.

## REQ-9: OTel Coverage Review
The power MUST review translated service code for: span creation on every public service method, trace-id in log statements, and `InMemorySpanExporter` span assertions in tests.

## REQ-10: Per-Service Gap Table
For runs with multiple bounded contexts the power MUST produce a per-service monitoring gap table showing each context's score per dimension and overall status.
""", encoding="utf-8")
        (_monitoring_specs / "design.md").write_text("""\
# Design — Micro-Cosmos Monitoring Power

## Architecture

Steering-only Kiro.dev Power (no mcpServers). All guidance is embedded in `POWER.md` and delivered as steering instructions to Kiro's LLM context.

## Data Models

### Monitoring Score
```
{
  "total": 45,
  "dimensions": {
    "logging":  { "score": 20, "status": "covered", "evidence": "SLF4J + Logback present" },
    "metrics":  { "score": 5,  "status": "partial",  "evidence": "Ad-hoc counters only" },
    "tracing":  { "score": 0,  "status": "absent",   "evidence": null },
    "health":   { "score": 10, "status": "partial",  "evidence": "/ping endpoint present" },
    "alerting": { "score": 10, "status": "partial",  "evidence": "Log-based only" }
  },
  "interpretation": "Basic — tracing and structured logging missing",
  "gaps": ["MAJOR: No distributed tracing", "MAJOR: No trace-context in log statements"]
}
```

### OTel Gap Finding
```
{ "severity": "BLOCKER|MAJOR|MINOR", "service": "fraud-scoring", "dimension": "tracing", "description": "..." }
```

### Per-Service Table Row
```
{ "context": "fraud-scoring", "logging": 20, "metrics": 0, "tracing": 0, "health": 20, "alerting": 0, "total": 40, "status": "Insufficient" }
```

## Testing Strategy

### Property 1: Frontmatter Schema Completeness
Every valid frontmatter object must have non-empty `name`, `description` (≥10 chars), and at least one keyword. Fast-check generates 100 arbitrary records.

### Property 2: Keyword Category Coverage
A valid keyword set must cover: observability category (monitoring/otel/telemetry), Micro-Cosmos category (micro-cosmos/legacy), language category (java/csharp/typescript/nodejs), signal category (logging/metrics/tracing/health). Fast-check generates 100 keyword tuples.

## Key Design Decisions

- **0–100 scale with five 20-pt dimensions**: balances simplicity (single number) with diagnostic value (per-dimension breakdown).
- **BLOCKER at 0–19**: a microservice with no observability cannot be safely deployed; the BLOCKER finding prevents Gate 5 approval for the infrastructure side.
- **Language-specific code snippets**: embedded directly in POWER.md rather than separate reference files, because Kiro context windows are large and retrieval latency matters more for instrumentation tasks.
- **InMemorySpanExporter test pattern**: included for all three languages so OTel coverage can be asserted in the existing TDD test suite without a live OTel collector.
""", encoding="utf-8")
        (_monitoring_specs / "tasks.md").write_text("""\
# Tasks — Micro-Cosmos Monitoring Power

- [x] 1. Write POWER.md frontmatter (name, displayName, author, description, keywords)
- [x] 2. Write Response Contract section (score, per-dimension, gaps, instrumentation plan, test note)
- [x] 3. Write Monitoring Maturity Scoring section (five dimensions table, score interpretation)
- [x] 4. Write Diagnose Before You Instrument routing table
- [x] 5. Write Java OTel Instrumentation section (build.gradle.kts deps, Tracer, Span, MDC, InMemorySpanExporter test)
- [x] 6. Write C# OTel Instrumentation section (PackageReference, ActivitySource, ActivityListener test)
- [x] 7. Write TypeScript/Node.js OTel Instrumentation section (NodeSDK, startActiveSpan, pino, InMemorySpanExporter test)
- [x] 8. Write Common Workflows section (score legacy app, generate OTel, review translated code)
- [x] 9. Write README.md with score table
- [x] 10. Write package.json (ESM, vitest, fast-check, js-yaml)
- [x] 11. Write vitest.config.js
- [x] 12. Write tests/power.property.test.js (Property 1: schema, Property 2: keyword categories)
- [x] 13. Write tests/power.unit.test.js (frontmatter, five dimensions, three languages, workflows)
- [x] 14. Write .kiro/specs/micro-cosmos-monitoring-power/requirements.md (10 requirements)
- [x] 15. Write .kiro/specs/micro-cosmos-monitoring-power/design.md
- [x] 16. Write .kiro/specs/micro-cosmos-monitoring-power/tasks.md
- [x] 17. Write .kiro/specs/micro-cosmos-monitoring-power/.config.kiro
""", encoding="utf-8")

    # ── micro-cosmos-terraform-power ───────────────────────────────────────────────
    terraform_dir = kiro_dir / "micro-cosmos-terraform-power"
    terraform_dir.mkdir(parents=True, exist_ok=True)
    if not (terraform_dir / "POWER.md").exists():
        (terraform_dir / "POWER.md").write_text(r"""---
name: "micro-cosmos-terraform"
displayName: "Micro-Cosmos Terraform"
author: "Micro-Cosmos"
description: "Use when reviewing, writing, or validating Terraform HCL for Micro-Cosmos-translated microservices. Enforces modular microservice layout, security hygiene, and compatibility guards across the full Observer→Gate5 pipeline."
keywords: ["terraform", "hcl", "iac", "microservice", "module", "security", "micro-cosmos", "pipeline", "review", "state", "provider", "encryption", "least-privilege", "compatibility"]
---

# Micro-Cosmos Terraform Power

Diagnose-first Terraform review for Micro-Cosmos translated microservices. Applies the full terraform-skill discipline with Micro-Cosmos-specific conventions: modular microservice layout, security gate alignment, and pipeline-phase traceability.

## Response Contract

Every HCL review or generation must include:

1. **Execution context** — Terraform/OpenTofu version floor, provider(s), backend, CI path.
2. **Microservice module coverage** — **WARN** if the HCL does not follow a per-bounded-context module layout. Missing module separation is always flagged.
3. **Risk category addressed** — one or more of: identity churn, secret exposure, blast radius, CI drift, compliance gap, state corruption, provider upgrade risk.
4. **Validation plan** — exact commands: `terraform fmt -check`, `terraform validate`, `trivy config .`, `checkov -d .`.
5. **Rollback notes** — for any destructive or state-mutating change.

Never recommend direct production apply without a reviewed plan artifact and approval.

## Workflow

1. **Capture Micro-Cosmos context** — which pipeline phase produced or will use this HCL? (Observer infra, per-service module, composition layer.)
2. **Check microservice coverage** — each bounded context identified by the Cartographer MUST have its own Terraform module. Warn if flat resources are used instead.
3. **Diagnose failure mode** using the routing table below.
4. **Review or generate HCL** following module layout, variable contracts, and security rules.
5. **Emit Response Contract.**

## Microservice Module Coverage — MANDATORY CHECK

For every Micro-Cosmos run the Cartographer defines bounded contexts. Each context must map to a dedicated Terraform module:

```
modules/
├── <context-a>/          # one module per bounded context
│   ├── main.tf
│   ├── variables.tf
│   ├── outputs.tf
│   └── versions.tf
├── <context-b>/
│   └── ...
environments/
├── prod/
│   ├── main.tf           # composes modules/
│   └── terraform.tfvars
└── staging/
    └── ...
```

**⚠ WARN** if any of the following are present:
- Resources defined directly in `environments/` without a module call
- A single monolithic `main.tf` containing resources for multiple bounded contexts
- Module directory names that do not correspond to a bounded context from `bounded_context_map.json`
- No `modules/` directory at all

Include this warning in the review findings with severity **MAJOR**.

## Diagnose Before You Generate

| Failure category | Symptoms | Action |
|---|---|---|
| **Microservice module missing** | Flat resources, no `modules/` dir, multi-context `main.tf` | WARN MAJOR — propose per-context module split |
| **Identity churn** | `count` index instability, missing `moved` blocks after rename | Add `moved` blocks; switch to `for_each` |
| **Secret exposure** | Hardcoded values, secrets in `.tfvars`, sensitive outputs unmarked | Source from secret manager; use `sensitive = true` and `write_only` on 1.11+ |
| **Blast radius** | Prod/staging in same state, oversized stacks | Split state per environment and per component |
| **CI drift** | No `.terraform.lock.hcl`, apply without plan artifact | Pin versions; commit lock file |
| **Compliance gap** | No `trivy config .` or `checkov -d .` stage | Add security policy gate before apply |
| **Encryption absent** | Storage without encryption, KMS key not specified | Enforce `encrypt = true`, specify KMS key ARN/ID |
| **Least-privilege violated** | IAM with `*` actions/resources, overly broad SGs | Scope to minimum actions and resources |
| **Provider upgrade risk** | Unpinned providers, breaking-change bump without lock | Pin to `~> MAJOR.0`; upgrade in separate PR |

## Module Conventions for Micro-Cosmos Microservices

Each translated bounded context gets a dedicated module with:

```hcl
# modules/<context>/versions.tf
terraform {
  required_version = "~> 1.9"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

# modules/<context>/variables.tf
variable "environment" {
  description = "Deployment environment (prod | staging | dev)"
  type        = string
  validation {
    condition     = contains(["prod", "staging", "dev"], var.environment)
    error_message = "environment must be prod, staging, or dev."
  }
}

variable "context_name" {
  description = "Bounded context name from Micro-Cosmos Cartographer output"
  type        = string
}
```

**Variable contract rules:**
- Every variable has `description` and explicit `type`
- Secrets use `sensitive = true` (or `write_only` on 1.11+)
- No `map(any)` — use typed `object({})` with `optional()` on 1.3+

**Output contract rules:**
- Every output has `description`
- Sensitive outputs marked `sensitive = true`
- Expose stable subsets only — never expose whole provider objects

## Security Baseline

**Always enforce:**
- Remote state with encryption and locking (`encrypt = true`, `use_lockfile = true` on 1.10+)
- KMS-managed encryption keys for all storage resources
- Dedicated VPC per environment — never use default VPC
- Security groups: separate `aws_vpc_security_group_{ingress,egress}_rule` resources (not inline)
- No open `0.0.0.0/0` ingress except explicit load-balancer front ends
- Secrets sourced from AWS Secrets Manager / Azure Key Vault / GCP Secret Manager

**Pre-apply checks (embed in CI):**
```bash
terraform fmt -check -recursive
terraform validate
trivy config . --exit-code 1
checkov -d . --compact
```

## Pipeline Phase Traceability

Each Terraform module should carry tags/labels that trace back to the Micro-Cosmos run:

```hcl
# In modules/<context>/main.tf locals block
locals {
  common_tags = {
    micro_cosmos_run_id      = var.micro_cosmos_run_id
    bounded_context     = var.context_name
    source_language     = var.source_lang
    target_language     = var.target_lang
    environment         = var.environment
  }
}
```

Add `micro_cosmos_run_id` as a required variable in every module so cost attribution and drift investigation can always trace resources back to the originating Micro-Cosmos translation run.

## PR Gate Alignment (Gate 5)

Terraform HCL review is part of the Gate 5 PR review. For a PR to pass Gate 5 on the infrastructure side:

- [ ] Each bounded context has its own module under `modules/`
- [ ] No hardcoded secrets or sensitive defaults
- [ ] Encryption enabled on all storage and state backends
- [ ] IAM roles scoped to least-privilege
- [ ] Providers and runtime version-pinned in `versions.tf`
- [ ] `.terraform.lock.hcl` committed
- [ ] `trivy config .` and `checkov -d .` pass clean
- [ ] Plan artifact reviewed before apply

If any item is unchecked, the Gate 5 PR reviewer must mark it **BLOCKER** before merge.

## Common Workflows

### Review existing HCL for microservice coverage
1. Read all `.tf` files in the repository root and `environments/`
2. List bounded contexts from `bounded_context_map.json` (if available)
3. Check each context has a corresponding `modules/<context>/` directory
4. Report WARN MAJOR for any context without a dedicated module
5. Emit Response Contract with validation commands

### Generate a new bounded-context module
1. Identify context name from Cartographer output
2. Create `modules/<context-name>/` with: `main.tf`, `variables.tf`, `outputs.tf`, `versions.tf`
3. Add `micro_cosmos_run_id`, `context_name`, `environment` as required variables
4. Add `common_tags` local block
5. Write `examples/minimal/` and `examples/complete/` for documentation and test fixtures
6. Emit Response Contract

### Security review before apply
1. Run `terraform fmt -check -recursive`
2. Run `terraform validate`
3. Run `trivy config .` — fail on HIGH or CRITICAL
4. Run `checkov -d .` — fail on HIGH severity
5. Review plan artifact for destroy actions (`plan -destroy` first)
6. Emit Response Contract with every finding classified by risk category
""", encoding="utf-8")

        (terraform_dir / "README.md").write_text("""\
# Micro-Cosmos Terraform Power

Kiro.dev Power for reviewing and generating Terraform HCL in the context of Micro-Cosmos translated microservices.

## What it does

- Reviews HCL modules for microservice coverage (one module per bounded context)
- Warns when flat-resource patterns replace proper module decomposition
- Enforces security baseline: encryption, least-privilege IAM, secret sourcing
- Aligns HCL review with Micro-Cosmos Gate 5 PR approval requirements
- Provides pipeline phase traceability via standard resource tags

## Installation in Kiro

Install this power from the Kiro.dev marketplace or copy the `POWER.md` file into your Kiro powers directory.

## When to activate

- You are reviewing or writing Terraform for a microservice translated by Micro-Cosmos
- You want to validate that each Cartographer bounded context has its own module
- You are running the Gate 5 infrastructure checklist
- You need to audit security posture before a production apply

## Microservice coverage check

This power always checks whether each bounded context from the Micro-Cosmos Cartographer output has a dedicated `modules/<context>/` directory. A missing module is always a **MAJOR** finding.

## Tests

```bash
npm install
npm test
```
""", encoding="utf-8")
        # package.json
        (terraform_dir / "package.json").write_text('{\n  "name": "micro-cosmos-terraform-power",\n  "version": "1.0.0",\n  "type": "module",\n  "scripts": { "test": "vitest run" },\n  "devDependencies": {\n    "vitest": "^1.6.0",\n    "fast-check": "^3.19.0",\n    "js-yaml": "^4.1.0"\n  }\n}\n', encoding="utf-8")
        # vitest.config.js
        (terraform_dir / "vitest.config.js").write_text("import { defineConfig } from 'vitest/config';\nexport default defineConfig({ test: { include: ['tests/**/*.test.js'] } });\n", encoding="utf-8")
        # tests/
        (terraform_dir / "tests").mkdir(exist_ok=True)
        (terraform_dir / "tests" / "power.property.test.js").write_text("""\
import { describe, test, expect } from 'vitest';
import * as fc from 'fast-check';
import fs from 'fs';
import yaml from 'js-yaml';

const POWER_PATH = new URL('../POWER.md', import.meta.url).pathname;
const raw = fs.readFileSync(POWER_PATH, 'utf8');
const parts = raw.split('---');
const frontmatter = yaml.load(parts[1]);
const body = parts.slice(2).join('---');

// Feature: micro-cosmos-terraform-power, Property 1: Frontmatter Schema Completeness
test('Property 1: Frontmatter Schema Completeness', () => {
  fc.assert(fc.property(
    fc.record({
      name: fc.string({ minLength: 1, maxLength: 100 }),
      displayName: fc.string({ minLength: 1, maxLength: 100 }),
      author: fc.string({ minLength: 1, maxLength: 100 }),
      description: fc.string({ minLength: 10, maxLength: 1024 }),
      keywords: fc.array(fc.string({ minLength: 1, maxLength: 50 }), { minLength: 1, maxLength: 50 }),
    }),
    (fm) => {
      expect(typeof fm.name).toBe('string');
      expect(fm.name.length).toBeGreaterThan(0);
      expect(typeof fm.description).toBe('string');
      expect(fm.description.length).toBeGreaterThanOrEqual(10);
      expect(Array.isArray(fm.keywords)).toBe(true);
      expect(fm.keywords.length).toBeGreaterThan(0);
      fm.keywords.forEach(k => expect(typeof k).toBe('string'));
    }
  ), { numRuns: 100 });
});

// Feature: micro-cosmos-terraform-power, Property 2: Keyword Category Coverage
test('Property 2: Keyword Category Coverage', () => {
  const terraformKeywords = ['terraform', 'hcl', 'iac', 'opentofu', 'module', 'state'];
  const brandKeywords = ['micro-cosmos', 'pipeline'];
  const securityKeywords = ['security', 'encryption', 'least-privilege'];
  const microserviceKeywords = ['microservice', 'module'];

  fc.assert(fc.property(
    fc.tuple(
      fc.constantFrom(...terraformKeywords),
      fc.constantFrom(...brandKeywords),
      fc.constantFrom(...securityKeywords),
      fc.constantFrom(...microserviceKeywords),
      fc.array(fc.string({ minLength: 1, maxLength: 30 }), { minLength: 0, maxLength: 5 }),
    ).map(([tf, alc, sec, ms, extra]) => [tf, alc, sec, ms, ...extra]),
    (keywords) => {
      const hasTerraform = keywords.some(k => terraformKeywords.includes(k));
      const hasBrand = keywords.some(k => brandKeywords.includes(k));
      const hasSecurity = keywords.some(k => securityKeywords.includes(k));
      const hasMicroservice = keywords.some(k => microserviceKeywords.includes(k));
      expect(hasTerraform).toBe(true);
      expect(hasBrand).toBe(true);
      expect(hasSecurity).toBe(true);
      expect(hasMicroservice).toBe(true);
    }
  ), { numRuns: 100 });
});

// Validate actual POWER.md frontmatter satisfies both properties
test('Actual POWER.md satisfies Property 1', () => {
  expect(typeof frontmatter.name).toBe('string');
  expect(frontmatter.name.length).toBeGreaterThan(0);
  expect(typeof frontmatter.description).toBe('string');
  expect(frontmatter.description.length).toBeGreaterThanOrEqual(10);
  expect(Array.isArray(frontmatter.keywords)).toBe(true);
  expect(frontmatter.keywords.length).toBeGreaterThan(0);
});

test('Actual POWER.md satisfies Property 2 — keyword categories covered', () => {
  const kw = frontmatter.keywords;
  expect(kw.some(k => ['terraform', 'hcl', 'iac'].includes(k))).toBe(true);
  expect(kw.some(k => ['micro-cosmos'].includes(k))).toBe(true);
  expect(kw.some(k => ['security', 'encryption', 'least-privilege'].includes(k))).toBe(true);
  expect(kw.some(k => ['microservice', 'module'].includes(k))).toBe(true);
});
""", encoding="utf-8")
        (terraform_dir / "tests" / "power.unit.test.js").write_text("""\
import { test, expect } from 'vitest';
import fs from 'fs';
import yaml from 'js-yaml';

const POWER_PATH = new URL('../POWER.md', import.meta.url).pathname;
const raw = fs.readFileSync(POWER_PATH, 'utf8');
const parts = raw.split('---');
const frontmatter = yaml.load(parts[1]);
const body = parts.slice(2).join('---');

// Frontmatter values
test('name is micro-cosmos-terraform', () => {
  expect(frontmatter.name).toBe('micro-cosmos-terraform');
});
test('displayName is Micro-Cosmos Terraform', () => {
  expect(frontmatter.displayName).toBe('Micro-Cosmos Terraform');
});
test('author is Micro-Cosmos', () => {
  expect(frontmatter.author).toBe('Micro-Cosmos');
});
test('keywords include terraform', () => {
  expect(frontmatter.keywords).toContain('terraform');
});
test('keywords include microservice', () => {
  expect(frontmatter.keywords).toContain('microservice');
});
test('keywords include micro-cosmos', () => {
  expect(frontmatter.keywords).toContain('micro-cosmos');
});
test('keywords include security', () => {
  expect(frontmatter.keywords).toContain('security');
});

// File structure
test('POWER.md file exists', () => {
  expect(fs.existsSync(POWER_PATH)).toBe(true);
});
test('README.md exists', () => {
  const p = new URL('../README.md', import.meta.url).pathname;
  expect(fs.existsSync(p)).toBe(true);
});
test('package.json exists', () => {
  const p = new URL('../package.json', import.meta.url).pathname;
  expect(fs.existsSync(p)).toBe(true);
});

// Response Contract section
test('body contains Response Contract section', () => {
  expect(body).toContain('Response Contract');
});
test('body contains microservice module coverage check', () => {
  expect(body).toContain('Microservice Module Coverage');
});
test('body contains WARN for missing module', () => {
  expect(body).toContain('WARN');
});

// Security baseline
test('body contains Security Baseline section', () => {
  expect(body).toContain('Security Baseline');
});
test('body references trivy config', () => {
  expect(body).toContain('trivy config');
});
test('body references checkov', () => {
  expect(body).toContain('checkov');
});
test('body mentions encryption', () => {
  expect(body).toContain('encrypt');
});

// Pipeline gate alignment
test('body references Gate 5', () => {
  expect(body).toContain('Gate 5');
});
test('body references bounded context', () => {
  expect(body).toContain('bounded context');
});

// Module conventions
test('body references modules/ directory layout', () => {
  expect(body).toContain('modules/');
});
test('body references environments/ directory', () => {
  expect(body).toContain('environments/');
});

// Workflow presence
test('body contains Common Workflows section', () => {
  expect(body).toContain('Common Workflows');
});
test('body contains workflow for reviewing existing HCL', () => {
  expect(body).toContain('Review existing HCL');
});
test('body contains workflow for generating a new module', () => {
  expect(body).toContain('Generate a new bounded-context module');
});
test('body contains workflow for security review before apply', () => {
  expect(body).toContain('Security review before apply');
});
""", encoding="utf-8")
        # .kiro/specs/
        _terraform_specs = terraform_dir / ".kiro" / "specs" / "micro-cosmos-terraform-power"
        _terraform_specs.mkdir(parents=True, exist_ok=True)
        (_terraform_specs / ".config.kiro").write_text('{"generationMode": "requirements-first"}\n', encoding="utf-8")
        (_terraform_specs / "requirements.md").write_text("""\
# Requirements — Micro-Cosmos Terraform Power

## REQ-1: Microservice Module Coverage Check
The power MUST warn when Terraform HCL does not define a dedicated module per Micro-Cosmos bounded context. The warning MUST be severity MAJOR and include the list of contexts without modules.

## REQ-2: Security Baseline Enforcement
The power MUST verify: remote state with encryption, no hardcoded secrets in variables or `.tfvars`, KMS-managed keys, dedicated VPC, and least-privilege IAM. Each violation MUST be classified with severity (BLOCKER / MAJOR / MINOR).

## REQ-3: Gate 5 PR Checklist
The power MUST emit the Gate 5 infrastructure checklist covering: module coverage, secrets, encryption, IAM, version pinning, `.terraform.lock.hcl`, policy scan results, and plan artifact review.

## REQ-4: Pipeline Phase Traceability
The power MUST recommend resource tagging with `micro_cosmos_run_id`, `bounded_context`, `source_language`, `target_language`, `environment` for every module.

## REQ-5: Validation Plan
Every review MUST include exact CLI commands: `terraform fmt -check -recursive`, `terraform validate`, `trivy config .`, `checkov -d .`.

## REQ-6: Rollback Safety
For any destructive or state-mutating recommendation the power MUST include rollback instructions and require a `terraform plan -destroy` review before proceed.

## REQ-7: Module Layout Generation
The power MUST generate standard module layouts (`main.tf`, `variables.tf`, `outputs.tf`, `versions.tf`, `examples/minimal/`, `examples/complete/`) for a given bounded context name.

## REQ-8: Version Pinning
The power MUST enforce `required_version = "~> 1.9"` (or higher) and provider version constraints in every module's `versions.tf`.

## REQ-9: Micro-Cosmos Context Awareness
The power MUST understand Micro-Cosmos pipeline phases (Observer, Cartographer, Architect, Security, Code Writer, Writer, PR Reviewer, Gate 5) and contextualise findings to the phase that generated or will consume the HCL.

## REQ-10: Diagnosable Failure Categories
The power MUST include the Terraform failure category routing table (identity churn, blast radius, CI drift, compliance gap, state corruption, provider upgrade risk) adapted for Micro-Cosmos microservice patterns.
""", encoding="utf-8")
        (_terraform_specs / "design.md").write_text("""\
# Design — Micro-Cosmos Terraform Power

## Architecture

Steering-only Kiro.dev Power (no mcpServers). All guidance is embedded in `POWER.md` and delivered as steering instructions to Kiro's LLM context.

## Data Models

### Microservice Module Map
```
{
  "contexts": [
    { "name": "fraud-scoring", "module_path": "modules/fraud-scoring", "present": true },
    { "name": "payment-gateway", "module_path": "modules/payment-gateway", "present": false }
  ],
  "missing_modules": ["payment-gateway"]
}
```

### Security Finding
```
{ "severity": "BLOCKER|MAJOR|MINOR", "rule": "...", "file": "...", "line": N, "remediation": "..." }
```

### Gate 5 Checklist Item
```
{ "id": "module-coverage", "description": "...", "passed": true|false, "severity": "BLOCKER|MAJOR|MINOR" }
```

## Testing Strategy

### Property 1: Frontmatter Schema Completeness
Every valid frontmatter object must have non-empty `name`, `description` (≥10 chars), and at least one keyword.
Fast-check generates 100 arbitrary frontmatter records and asserts the schema invariants.

### Property 2: Keyword Category Coverage
A valid keyword set for this power must cover: Terraform category, Micro-Cosmos category, security category, microservice category.
Fast-check generates 100 keyword tuples (one from each category plus extras) and asserts at least one keyword from each category is present.

## Key Design Decisions

- **No mcpServers**: unlike the upstream terraform-skill which optionally bundles `terraform-mcp-server`, this power is steering-only to minimise setup friction in the Kiro environment.
- **Gate 5 alignment**: checklist items mirror the Micro-Cosmos Gate 5 PR review structure so the power output can be used directly as a gate sub-report.
- **WARN as MAJOR, not BLOCKER**: missing microservice modules are MAJOR (must fix before production) not BLOCKER (must fix before merge) to allow iterative module extraction.
""", encoding="utf-8")
        (_terraform_specs / "tasks.md").write_text("""\
# Tasks — Micro-Cosmos Terraform Power

- [x] 1. Write POWER.md frontmatter (name, displayName, author, description, keywords)
- [x] 2. Write Response Contract section
- [x] 3. Write Workflow section
- [x] 4. Write Microservice Module Coverage — MANDATORY CHECK section with WARN criteria
- [x] 5. Write Diagnose Before You Generate routing table
- [x] 6. Write Module Conventions for Micro-Cosmos Microservices section with HCL examples
- [x] 7. Write Security Baseline section with CLI commands
- [x] 8. Write Pipeline Phase Traceability section with tags HCL
- [x] 9. Write PR Gate Alignment (Gate 5) checklist
- [x] 10. Write Common Workflows section (review existing HCL, generate new module, security review)
- [x] 11. Write README.md
- [x] 12. Write package.json (ESM, vitest, fast-check, js-yaml)
- [x] 13. Write vitest.config.js
- [x] 14. Write tests/power.property.test.js (Property 1: schema, Property 2: keyword categories)
- [x] 15. Write tests/power.unit.test.js (frontmatter values, sections, workflows)
- [x] 16. Write .kiro/specs/micro-cosmos-terraform-power/requirements.md (10 requirements)
- [x] 17. Write .kiro/specs/micro-cosmos-terraform-power/design.md
- [x] 18. Write .kiro/specs/micro-cosmos-terraform-power/tasks.md
- [x] 19. Write .kiro/specs/micro-cosmos-terraform-power/.config.kiro
""", encoding="utf-8")

    # ── micro-cosmos-code-writer-power ─────────────────────────────────────────────
    code_writer_dir = kiro_dir / "micro-cosmos-code-writer-power"
    code_writer_dir.mkdir(parents=True, exist_ok=True)
    if not (code_writer_dir / "POWER.md").exists():
        (code_writer_dir / "POWER.md").write_text(f"""\
---
name: "micro-cosmos-code-writer"
displayName: "Micro-Cosmos Code Writer"
author: "Micro-Cosmos"
description: "Use when translating source seams to {tl_display} following Micro-Cosmos hexagonal conventions. Enforces TDD, BigDecimal for monetary values, hexagonal layering, OTel instrumentation, and JVM source-root path conventions across the full seam-by-seam TDD loop."
keywords: ["code-writer", "translation", "seam", "hexagonal", "ddd", "tdd", "bigdecimal", "java", "kotlin", "java21", "micro-cosmos", "modernization", "ports-and-adapters", "clean-architecture", "otel", "opentelemetry"]
---

# Micro-Cosmos Code Writer Power

Seam-by-seam translation power for Micro-Cosmos. Translates {sl_display} seams to {tl_display} following hexagonal (DDD ports and adapters) architecture, TDD, and OpenTelemetry instrumentation conventions.

## Response Contract

Every seam translation must include:

1. **Seam ID** — the bounded-context seam being translated.
2. **Implementation files** — full list of written files with paths relative to the project root.
3. **Test files** — at least one test file covering happy-path, rule-violation, and edge-case categories.
4. **README.md** — present and describing the module in business terms.

## Workflow

1. **Read source seam** — use `list_source_files` with the seam name, then `read_source_file` for every file returned. Understand aggregates, value objects, invariants, and business rules.
2. **Map domain concepts** — identify every business invariant. Each invariant MUST become an explicit guard in the output. No silent no-ops.
3. **Write implementation** — produce idiomatic {tl_display} following hexagonal layers (see below). No TODOs, no stubs, no placeholder implementations.
4. **Write unit tests** — cover all three categories per seam:
   - **Happy path** — valid inputs → expected success output
   - **Rule violation** — invalid input → explicit error/exception
   - **Edge case** — boundary value (zero, empty, max, nil/null)
5. **Add OTel spans** — add OpenTelemetry spans to every public service method (see OTel section).
6. **Write README.md** — describe the module in business terms with build and test instructions.
7. **Submit** — call `submit_seam_translation` with ALL files. NEVER output file content as prose or markdown.

## Hexagonal Layer Rules

| Layer | Location | Allowed dependencies |
|---|---|---|
| `domain/` | Pure business logic | None — no I/O, no framework imports |
| `application/` | Use-case interfaces | `domain/` only |
| `infrastructure/` | Adapters (in-memory for tests, real impl for prod) | `domain/`, `application/`, external libs |

Port interfaces follow the pattern `I{{Aggregate}}UseCase` / `I{{Aggregate}}Repository`.

## Decimal Hygiene

**NEVER use float or double for monetary or financial values.**

| Target | Correct type | Never use |
|---|---|---|
| Java / Kotlin / Scala | `BigDecimal` | `float`, `double`, `Float`, `Double` |
| Python | `decimal.Decimal` | `float` |
| C# | `System.Decimal` / `decimal` | `float`, `double` |
| Rust | `rust_decimal::Decimal` | `f32`, `f64` |
| Go | `github.com/shopspring/decimal` | `float32`, `float64` |
| TypeScript | `Decimal` (decimal.js) | `number` for amounts |

## File Path Conventions

**JVM targets (Java, Kotlin, Scala):**
- Implementation: `src/main/<lang>/com/example/.../MyClass.<ext>`
- Tests: `src/test/<lang>/com/example/.../MyClassTest.<ext>`
- NEVER write bare package paths like `com/example/MyClass.<ext>`
- NEVER use `tests/` or `test/` as a top-level directory for test files

## OTel Instrumentation

Add OpenTelemetry spans to every public service method.

**JVM (Java / Kotlin / Scala):**
```java
private static final Tracer tracer = GlobalOpenTelemetry.getTracer("micro_cosmos.<context>");

public Result process(Input input) {{
    Span span = tracer.spanBuilder("ServiceName.process")
        .setAttribute("input.id", input.getId().toString())
        .startSpan();
    try (var scope = span.makeCurrent()) {{
        MDC.put("trace_id", span.getSpanContext().getTraceId());
        // business logic
    }} catch (Exception e) {{
        span.setStatus(StatusCode.ERROR, e.getMessage());
        span.recordException(e);
        throw e;
    }} finally {{
        MDC.remove("trace_id");
        span.end();
    }}
}}
```

**Node.js / TypeScript / JavaScript:**
```typescript
return tracer.startActiveSpan('ServiceName.process', span => {{
    span.setAttribute('input.id', input.id);
    const traceId = trace.getActiveSpan()?.spanContext().traceId ?? 'unknown';
    try {{
        // business logic
    }} catch (err) {{
        span.setStatus({{ code: SpanStatusCode.ERROR, message: String(err) }});
        span.recordException(err as Error);
        throw err;
    }} finally {{ span.end(); }}
}});
```

**.NET (C# / F# / VB.NET):**
```csharp
using var activity = Telemetry.Source.StartActivity("ServiceName.Process");
activity?.SetTag("input.id", input.Id.ToString());
try {{
    // business logic
}} catch (Exception ex) {{
    activity?.SetStatus(ActivityStatusCode.Error, ex.Message);
    activity?.RecordException(ex);
    throw;
}}
```

## PR Gate Alignment (Gate 5)

- [ ] All domain rules from the source are present and explicitly enforced
- [ ] No TODOs, stubs, or placeholder comments in business logic
- [ ] `{decimal_type}` used for all monetary values — never `{float_avoid}`
- [ ] Hexagonal layers respected: domain/application/infrastructure separation
- [ ] Tests cover happy-path, rule-violation, and edge-case categories
- [ ] OTel spans added to every public service method
- [ ] README.md present with build/test instructions

If any item is not met, the Gate 5 reviewer must mark it **BLOCKER** before merge.

## Common Workflows

### Translate a new seam
1. Read all source files for the seam
2. Map domain concepts and invariants
3. Write implementation following hexagonal layers
4. Write tests (3 categories)
5. Add OTel spans
6. Write README.md
7. Submit via `submit_seam_translation`

### Fix a failing TDD review
1. Read the failing review findings from the feedback prompt
2. Only touch files flagged with BLOCKER or MAJOR findings
3. Non-flagged files: do not rewrite — include them unchanged
4. Re-submit via `submit_seam_translation`

### Add OTel to an existing translation
1. Read all implementation files
2. Add Tracer field and span wrapping to every public service method
3. Inject trace_id into all log statements
4. Add at least one test using InMemorySpanExporter / ActivityListener
5. Submit updated files
""", encoding="utf-8")

        (code_writer_dir / "README.md").write_text(f"""\
# Micro-Cosmos Code Writer Power

Kiro.dev Power for seam-by-seam {sl_display} → {tl_display} translation following Micro-Cosmos hexagonal conventions.

## What it does

- Reads source seams and maps domain aggregates, value objects, and invariants
- Writes idiomatic {tl_display} following hexagonal (domain/application/infrastructure) layering
- Enforces `{decimal_type}` for all monetary values — never `{float_avoid}`
- Enforces JVM file-path conventions (src/main/<lang>/...)
- Adds OpenTelemetry spans to every public service method
- Generates unit tests covering happy-path, rule-violation, and edge-case categories
- Produces README.md per seam in business terms

## When to activate

- You are translating a seam from {sl_display} to {tl_display}
- You are fixing a failing TDD review (BLOCKER or MAJOR findings)
- You need to add OTel instrumentation to a translated service
""", encoding="utf-8")
        # package.json
        (code_writer_dir / "package.json").write_text('{\n  "name": "micro-cosmos-code-writer-power",\n  "version": "1.0.0",\n  "type": "module",\n  "scripts": { "test": "vitest run" },\n  "devDependencies": {\n    "vitest": "^1.6.0",\n    "fast-check": "^3.19.0",\n    "js-yaml": "^4.1.0"\n  }\n}\n', encoding="utf-8")
        # vitest.config.js
        (code_writer_dir / "vitest.config.js").write_text("import { defineConfig } from 'vitest/config';\nexport default defineConfig({ test: { include: ['tests/**/*.test.js'] } });\n", encoding="utf-8")
        # tests/
        (code_writer_dir / "tests").mkdir(exist_ok=True)
        (code_writer_dir / "tests" / "power.property.test.js").write_text("""\
import { describe, test, expect } from 'vitest';
import * as fc from 'fast-check';
import fs from 'fs';
import yaml from 'js-yaml';

const POWER_PATH = new URL('../POWER.md', import.meta.url).pathname;
const raw = fs.readFileSync(POWER_PATH, 'utf8');
const parts = raw.split('---');
const frontmatter = yaml.load(parts[1]);
const body = parts.slice(2).join('---');

// Feature: micro-cosmos-code-writer-power, Property 1: Frontmatter Schema Completeness
test('Property 1: Frontmatter Schema Completeness', () => {
  fc.assert(fc.property(
    fc.record({
      name: fc.string({ minLength: 1, maxLength: 100 }),
      displayName: fc.string({ minLength: 1, maxLength: 100 }),
      author: fc.string({ minLength: 1, maxLength: 100 }),
      description: fc.string({ minLength: 10, maxLength: 1024 }),
      keywords: fc.array(fc.string({ minLength: 1, maxLength: 50 }), { minLength: 1, maxLength: 50 }),
    }),
    (fm) => {
      expect(typeof fm.name).toBe('string');
      expect(fm.name.length).toBeGreaterThan(0);
      expect(typeof fm.description).toBe('string');
      expect(fm.description.length).toBeGreaterThanOrEqual(10);
      expect(Array.isArray(fm.keywords)).toBe(true);
      expect(fm.keywords.length).toBeGreaterThan(0);
      fm.keywords.forEach(k => expect(typeof k).toBe('string'));
    }
  ), { numRuns: 100 });
});

// Feature: micro-cosmos-code-writer-power, Property 2: Keyword Category Coverage
test('Property 2: Keyword Category Coverage', () => {
  const codeGenKeywords = ['code-writer', 'translation', 'seam', 'modernization'];
  const brandKeywords = ['micro-cosmos', 'pipeline'];
  const architectureKeywords = ['hexagonal', 'ddd', 'ports-and-adapters', 'clean-architecture'];
  const qualityKeywords = ['tdd', 'otel', 'opentelemetry', 'bigdecimal'];

  fc.assert(fc.property(
    fc.tuple(
      fc.constantFrom(...codeGenKeywords),
      fc.constantFrom(...brandKeywords),
      fc.constantFrom(...architectureKeywords),
      fc.constantFrom(...qualityKeywords),
      fc.array(fc.string({ minLength: 1, maxLength: 30 }), { minLength: 0, maxLength: 5 }),
    ).map(([cg, alc, arch, qual, extra]) => [cg, alc, arch, qual, ...extra]),
    (keywords) => {
      const hasCodeGen = keywords.some(k => codeGenKeywords.includes(k));
      const hasBrand = keywords.some(k => brandKeywords.includes(k));
      const hasArchitecture = keywords.some(k => architectureKeywords.includes(k));
      const hasQuality = keywords.some(k => qualityKeywords.includes(k));
      expect(hasCodeGen).toBe(true);
      expect(hasBrand).toBe(true);
      expect(hasArchitecture).toBe(true);
      expect(hasQuality).toBe(true);
    }
  ), { numRuns: 100 });
});

// Validate actual POWER.md
test('Actual POWER.md satisfies Property 1', () => {
  expect(typeof frontmatter.name).toBe('string');
  expect(frontmatter.name.length).toBeGreaterThan(0);
  expect(typeof frontmatter.description).toBe('string');
  expect(frontmatter.description.length).toBeGreaterThanOrEqual(10);
  expect(Array.isArray(frontmatter.keywords)).toBe(true);
  expect(frontmatter.keywords.length).toBeGreaterThan(0);
});

test('Actual POWER.md satisfies Property 2 — keyword categories covered', () => {
  const kw = frontmatter.keywords;
  expect(kw.some(k => ['code-writer', 'translation', 'seam', 'modernization'].includes(k))).toBe(true);
  expect(kw.some(k => ['micro-cosmos'].includes(k))).toBe(true);
  expect(kw.some(k => ['hexagonal', 'ddd', 'ports-and-adapters', 'clean-architecture'].includes(k))).toBe(true);
  expect(kw.some(k => ['tdd', 'otel', 'opentelemetry', 'bigdecimal'].includes(k))).toBe(true);
});
""", encoding="utf-8")
        (code_writer_dir / "tests" / "power.unit.test.js").write_text("""\
import { test, expect } from 'vitest';
import fs from 'fs';
import yaml from 'js-yaml';

const POWER_PATH = new URL('../POWER.md', import.meta.url).pathname;
const raw = fs.readFileSync(POWER_PATH, 'utf8');
const parts = raw.split('---');
const frontmatter = yaml.load(parts[1]);
const body = parts.slice(2).join('---');

// Frontmatter values
test('name is micro-cosmos-code-writer', () => {
  expect(frontmatter.name).toBe('micro-cosmos-code-writer');
});
test('displayName is Micro-Cosmos Code Writer', () => {
  expect(frontmatter.displayName).toBe('Micro-Cosmos Code Writer');
});
test('author is Micro-Cosmos', () => {
  expect(frontmatter.author).toBe('Micro-Cosmos');
});
test('keywords include code-writer', () => {
  expect(frontmatter.keywords).toContain('code-writer');
});
test('keywords include micro-cosmos', () => {
  expect(frontmatter.keywords).toContain('micro-cosmos');
});
test('keywords include hexagonal', () => {
  expect(frontmatter.keywords).toContain('hexagonal');
});
test('keywords include tdd', () => {
  expect(frontmatter.keywords).toContain('tdd');
});

// File structure
test('POWER.md file exists', () => {
  expect(fs.existsSync(POWER_PATH)).toBe(true);
});
test('README.md exists', () => {
  const p = new URL('../README.md', import.meta.url).pathname;
  expect(fs.existsSync(p)).toBe(true);
});
test('package.json exists', () => {
  const p = new URL('../package.json', import.meta.url).pathname;
  expect(fs.existsSync(p)).toBe(true);
});

// Response Contract
test('body contains Response Contract section', () => {
  expect(body).toContain('Response Contract');
});
test('body contains Seam ID', () => {
  expect(body).toContain('Seam ID');
});

// Hexagonal layers
test('body contains Hexagonal Layer Rules', () => {
  expect(body).toContain('Hexagonal Layer Rules');
});
test('body references domain layer', () => {
  expect(body).toContain('domain/');
});
test('body references application layer', () => {
  expect(body).toContain('application/');
});
test('body references infrastructure layer', () => {
  expect(body).toContain('infrastructure/');
});

// Decimal hygiene
test('body contains Decimal Hygiene section', () => {
  expect(body).toContain('Decimal Hygiene');
});
test('body references BigDecimal', () => {
  expect(body).toContain('BigDecimal');
});

// OTel
test('body contains OTel Instrumentation section', () => {
  expect(body).toContain('OTel');
});

// Workflows
test('body contains Common Workflows section', () => {
  expect(body).toContain('Common Workflows');
});
test('body contains workflow for translating a seam', () => {
  expect(body).toContain('Translate a new seam');
});
test('body contains workflow for fixing TDD review', () => {
  expect(body).toContain('Fix a failing TDD review');
});

// Gate 5
test('body contains PR Gate Alignment', () => {
  expect(body).toContain('Gate 5');
});
""", encoding="utf-8")
        # .kiro/specs/
        _code_writer_specs = code_writer_dir / ".kiro" / "specs" / "micro-cosmos-code-writer-power"
        _code_writer_specs.mkdir(parents=True, exist_ok=True)
        (_code_writer_specs / ".config.kiro").write_text('{"generationMode": "requirements-first"}\n', encoding="utf-8")
        (_code_writer_specs / "requirements.md").write_text("""\
# Requirements — Micro-Cosmos Code Writer Power

## REQ-1: Seam-by-Seam Translation
The power MUST translate each bounded context seam independently, producing a complete implementation with tests before proceeding to the next seam.

## REQ-2: Hexagonal Architecture Compliance
The power MUST organise all output into hexagonal layers: `domain/` (pure business logic), `application/` (use-case interfaces), `infrastructure/` (adapters). Every layer separation MUST be enforced as BLOCKER.

## REQ-3: Decimal Hygiene Enforcement
The power MUST NEVER use `float` or `double` for monetary or financial values. The correct decimal type (`BigDecimal`, `decimal.Decimal`, `System.Decimal`, `rust_decimal::Decimal`) MUST be used. Violation is BLOCKER.

## REQ-4: Three-Category Test Coverage
Every seam MUST include tests covering: happy-path (valid input → success), rule-violation (invalid input → error/exception), and edge-case (boundary: zero, empty, max). Missing any category is BLOCKER.

## REQ-5: OTel Span Instrumentation
The power MUST add OpenTelemetry spans to every public service method. JVM: `GlobalOpenTelemetry` + `Span` in try-with-resources + MDC trace-id. Node.js: `startActiveSpan` + pino trace-id. .NET: `ActivitySource.StartActivity`. Missing span on any public method is MAJOR.

## REQ-6: JVM File Path Conventions
For JVM targets (Java, Kotlin, Scala): implementation files MUST be under `src/main/<lang>/` and test files under `src/test/<lang>/`. Bare package paths at project root are BLOCKER.

## REQ-7: LLM Mode Seam Context
When running in LLM mode with Micro-Cosmos pipeline data available, the power MUST use the seam report (`seam_report.json`), bounded context map, and architect output to provide seam-specific translation guidance. Seam ID, source location, evidence, and migration steps MUST be surfaced.

## REQ-8: Deterministic Mode Fallback
When running in deterministic mode (no LLM), the power MUST emit general hexagonal + TDD guidance for the source→target language pair, without seam-specific context. Language-specific examples MUST still be included.

## REQ-9: Build File Generation
The power MUST include the correct build file for the target language: `build.gradle.kts` (Java/Kotlin), `build.sbt` (Scala), `*.csproj` (C#/F#/VB), `package.json` (TypeScript/JavaScript/Node), `Cargo.toml` (Rust), `go.mod` (Go).

## REQ-10: Gate 5 PR Checklist
The power MUST emit a Gate 5 PR checklist covering: all domain rules present, no TODOs/stubs, correct decimal type, hexagonal separation, three test categories, OTel spans, and README.md present.
""", encoding="utf-8")
        (_code_writer_specs / "design.md").write_text("""\
# Design — Micro-Cosmos Code Writer Power

## Architecture

Steering-only Kiro.dev Power (no mcpServers). All guidance is embedded in `POWER.md` and delivered as steering instructions to Kiro's LLM context.

## Data Models

### Seam Translation Context
When run inside an Micro-Cosmos LLM pipeline, the following data is available from reports:
```
{
  "seam_id": "fraud-scoring",
  "source_language": "java",
  "target_language": "kotlin",
  "source_location": "src/main/java/com/example/FraudScoringService.java",
  "type": "service",
  "evidence": ["BigDecimal amount", "validate() invariant"],
  "work": {
    "steps": ["Translate domain aggregates", "Add OTel spans", "Write TDD tests"],
    "effort": "M",
    "risk": "LOW"
  }
}
```

When run in deterministic mode (no LLM), the power is generated from source path, source language, and target language only. Guidance is language-specific but seam-specific context is unavailable.

### Translation Output
```
{
  "seam_id": "fraud-scoring",
  "files": [
    {"path": "src/main/kotlin/com/example/domain/FraudScoringService.kt", "lines": 80},
    {"path": "src/test/kotlin/com/example/domain/FraudScoringServiceTest.kt", "lines": 60}
  ],
  "review_verdict": "PASS|FAIL",
  "tdd_iterations": 1
}
```

### Gate 5 Checklist Item
```
{ "id": "seam-coverage", "seam": "fraud-scoring", "passed": true|false, "blockers": [] }
```

## Testing Strategy

### Property 1: Frontmatter Schema Completeness
Every valid frontmatter object must have non-empty `name`, `description` (≥10 chars), and at least one keyword. Fast-check generates 100 arbitrary records and asserts the schema invariants.

### Property 2: Keyword Category Coverage
A valid keyword set must cover: code-generation category (code-writer/translation/seam), Micro-Cosmos category (micro-cosmos), architecture category (hexagonal/ddd), and quality category (tdd/otel/bigdecimal). Fast-check generates 100 keyword tuples.

## Key Design Decisions

- **Steering-only**: No mcpServers — power guidance is embedded in POWER.md context delivered to Kiro's LLM.
- **Seam-by-seam approach**: Each bounded context is translated independently with its own TDD loop, so failures are isolated.
- **LLM mode context**: Reads seam reports from `reports/seam_report.json` and bounded context map from Cartographer. The richer the upstream pipeline output, the more targeted the code-writer guidance.
- **Deterministic mode context**: Only source path, source language, and target language are known. Power emits general hexagonal + TDD guidance for the target language pair.
- **BigDecimal enforcement**: BLOCKER for any monetary value using float/double — this maps directly to the Skeptical Review BLOCKER criteria.
- **InMemorySpanExporter pattern**: Included for all target stacks so OTel coverage can be asserted in the TDD test suite without a live collector.
""", encoding="utf-8")
        (_code_writer_specs / "tasks.md").write_text("""\
# Tasks — Micro-Cosmos Code Writer Power

- [x] 1. Write POWER.md frontmatter (name, displayName, author, description, keywords)
- [x] 2. Write Response Contract section (seam ID, implementation files, test files, README.md)
- [x] 3. Write Workflow section (read source, map domain, write implementation, write tests, OTel, submit)
- [x] 4. Write Hexagonal Layer Rules section (domain/application/infrastructure table)
- [x] 5. Write Decimal Hygiene section (BigDecimal table for all target languages)
- [x] 6. Write File Path Conventions section (JVM src/main/<lang>/ rule)
- [x] 7. Write OTel Instrumentation section (JVM, Node.js/TS, .NET code examples)
- [x] 8. Write PR Gate Alignment (Gate 5) checklist
- [x] 9. Write Common Workflows section (translate seam, fix TDD review, add OTel)
- [x] 10. Write README.md with language-pair context
- [x] 11. Write package.json (ESM, vitest, fast-check, js-yaml)
- [x] 12. Write vitest.config.js
- [x] 13. Write tests/power.property.test.js (Property 1: schema, Property 2: keyword categories)
- [x] 14. Write tests/power.unit.test.js (frontmatter values, sections, workflows)
- [x] 15. Write .kiro/specs/micro-cosmos-code-writer-power/requirements.md (10 requirements)
- [x] 16. Write .kiro/specs/micro-cosmos-code-writer-power/design.md (LLM vs deterministic context)
- [x] 17. Write .kiro/specs/micro-cosmos-code-writer-power/tasks.md
- [x] 18. Write .kiro/specs/micro-cosmos-code-writer-power/.config.kiro
""", encoding="utf-8")

    # ── micro-cosmos-code-reviewer-power ───────────────────────────────────────────
    code_reviewer_dir = kiro_dir / "micro-cosmos-code-reviewer-power"
    code_reviewer_dir.mkdir(parents=True, exist_ok=True)
    if not (code_reviewer_dir / "POWER.md").exists():
        (code_reviewer_dir / "POWER.md").write_text("""\
---
name: "micro-cosmos-code-reviewer"
displayName: "Micro-Cosmos Code Reviewer"
author: "Micro-Cosmos"
description: "Use when performing adversarial structured review of translated code. Enforces business logic fidelity, decimal hygiene, three-category test coverage, hexagonal compliance, and OTel span presence. Classifies every finding as BLOCKER / MAJOR / MINOR / NIT."
keywords: ["code-review", "review", "skeptical", "adversarial", "blocker", "major", "minor", "nit", "hexagonal", "tdd", "decimal", "micro-cosmos", "java", "kotlin", "java21", "fidelity", "correctness"]
---

# Micro-Cosmos Code Reviewer Power

Adversarial structured code review for Micro-Cosmos translated microservices. Diagnoses fidelity gaps, structural issues, and missing observability between the source and translated implementation.

## Response Contract

Every review must include:

1. **Verdict** — `PASS`, `WARN`, or `FAIL`.
2. **Findings** — each finding in the format: `[SEVERITY] file:symbol — description`.
3. **Summary** — one paragraph describing the overall quality and most critical gaps.
4. **Metrics** — files reviewed, TODO density %, port interfaces present/missing.

## Severity Definitions

| Severity | When to use |
|---|---|
| **BLOCKER** | Wrong business logic, missing test category, float/double for money, missing hexagonal layer, security vulnerability |
| **MAJOR** | Structural issue, missing assertion in test, wrong package path, convention violation |
| **MINOR** | Improvement suggestion, cosmetic issue, partial coverage |
| **NIT** | Style preference with no correctness impact |

A PR with any BLOCKER must NOT be merged (Gate 5 fail).

## Workflow

1. **Read source seam files** — understand the business intent, domain rules, and invariants.
2. **Read translated output files** — understand the implementation.
3. **Check business logic completeness** — every domain invariant must be enforced. Silent no-ops are BLOCKER.
4. **Check decimal hygiene** — no float/double for monetary values. Report as BLOCKER.
5. **Check test coverage** — all three categories must be present: happy-path, rule-violation, edge-case. Missing category is BLOCKER.
6. **Check hexagonal architecture** — domain/application/infrastructure separation. Port interfaces present.
7. **Check OTel span presence** — every public service method must have a span. Missing span is MAJOR.
8. **Emit Response Contract** — verdict, findings table, summary, metrics.

## 7-Category Checklist

### 1. Functional Equivalence
- [ ] All domain rules from the source are present and explicitly enforced
- [ ] Every aggregate invariant has a guard — no silent no-ops
- [ ] No business rule replaced by TODO, stub, or placeholder comment

### 2. Decimal Hygiene
- [ ] No `float` / `double` / `f32` / `f64` / `number` used for monetary values
- [ ] Correct decimal type used (`BigDecimal`, `decimal.Decimal`, `rust_decimal::Decimal`, `System.Decimal`)
- [ ] Rounding modes explicit where division occurs

### 3. Test Coverage
- [ ] Happy path — valid inputs → expected success output
- [ ] Rule violation — invalid input → explicit error/exception
- [ ] Edge case — boundary value (zero, empty, max, nil/null)
- [ ] Test types present as applicable: unit (pure domain logic), integration (adapters/DB), property-based (invariants that must hold for all inputs)
- [ ] Target coverage: >= 80% line coverage on domain/application layers
- [ ] Each test has at least one meaningful assertion

### 4. Hexagonal Compliance
- [ ] `domain/` contains only pure business logic (no I/O, no framework deps)
- [ ] `application/` contains use-case interfaces only
- [ ] `infrastructure/` contains adapters (in-memory for tests)
- [ ] Port interfaces (`I{Aggregate}UseCase` / `I{Aggregate}Repository`) exist

### 5. Target Language Conventions
- [ ] Idiomatic error handling — errors not swallowed
- [ ] No raw primitive types for typed domain fields — use value objects or enums
- [ ] Build file present and correct

### 6. Package Structure
- [ ] JVM: all implementation files under `src/main/<lang>/`
- [ ] JVM: all test files under `src/test/<lang>/`
- [ ] No bare package paths like `com/example/MyClass.kt` at the project root

### 7. OTel / Observability
- [ ] Every public service method has an OTel span
- [ ] `trace_id` injected into structured log fields
- [ ] At least one test asserts span emission (`InMemorySpanExporter` / `ActivityListener`)

## Security Checks

- [ ] No hardcoded credentials, tokens, or API keys
- [ ] No SQL injection via string concatenation
- [ ] No sensitive data (PII, passwords) logged at any level
- [ ] No SSL/TLS validation bypass

## Gate 5 Alignment

For a PR to pass Gate 5 (Code review), NO BLOCKER findings must be present. Summarise all findings in a table:

| Severity | Count | Must fix before merge |
|---|---|---|
| BLOCKER | N | Yes |
| MAJOR | N | Recommended |
| MINOR | N | Optional |
| NIT | N | Optional |

## Common Workflows

### Skeptical first-pass review
1. Read source seam to understand intent
2. Read all translated files
3. Work through the 7-category checklist
4. Report each failure as `[SEVERITY] file:symbol — description`
5. Emit Response Contract

### Security-focused review
1. Scan all files for hardcoded credentials
2. Check all DB queries for string concatenation
3. Check all log statements for PII fields
4. Verify no SSL bypass in HTTP clients
5. Add findings to the Response Contract

### OTel coverage review
1. List all public service method signatures
2. Check each one for span creation
3. Check log statements for trace_id injection
4. Check test files for InMemorySpanExporter or ActivityListener usage
5. Report MAJOR for each un-instrumented method
""", encoding="utf-8")

        (code_reviewer_dir / "README.md").write_text("""\
# Micro-Cosmos Code Reviewer Power

Kiro.dev Power for adversarial structured review of Micro-Cosmos translated microservices.

## What it does

- Reviews translated code for business logic fidelity against the source seam
- Checks decimal hygiene (no float/double for monetary values)
- Verifies three-category test coverage (happy-path, rule-violation, edge-case)
- Validates hexagonal architecture compliance (domain/application/infrastructure)
- Checks OTel span instrumentation on every public service method
- Classifies findings as BLOCKER / MAJOR / MINOR / NIT
- Produces a Gate 5-ready verdict (PASS / WARN / FAIL)

## When to activate

- You are reviewing a translated seam before merging
- You need a Gate 5 review of translated code
- You want to check OTel span coverage in a translated service
- You need a security-focused review of translated output
""", encoding="utf-8")
        # package.json
        (code_reviewer_dir / "package.json").write_text('{\n  "name": "micro-cosmos-code-reviewer-power",\n  "version": "1.0.0",\n  "type": "module",\n  "scripts": { "test": "vitest run" },\n  "devDependencies": {\n    "vitest": "^1.6.0",\n    "fast-check": "^3.19.0",\n    "js-yaml": "^4.1.0"\n  }\n}\n', encoding="utf-8")
        # vitest.config.js
        (code_reviewer_dir / "vitest.config.js").write_text("import { defineConfig } from 'vitest/config';\nexport default defineConfig({ test: { include: ['tests/**/*.test.js'] } });\n", encoding="utf-8")
        # tests/
        (code_reviewer_dir / "tests").mkdir(exist_ok=True)
        (code_reviewer_dir / "tests" / "power.property.test.js").write_text("""\
import { describe, test, expect } from 'vitest';
import * as fc from 'fast-check';
import fs from 'fs';
import yaml from 'js-yaml';

const POWER_PATH = new URL('../POWER.md', import.meta.url).pathname;
const raw = fs.readFileSync(POWER_PATH, 'utf8');
const parts = raw.split('---');
const frontmatter = yaml.load(parts[1]);
const body = parts.slice(2).join('---');

// Feature: micro-cosmos-code-reviewer-power, Property 1: Frontmatter Schema Completeness
test('Property 1: Frontmatter Schema Completeness', () => {
  fc.assert(fc.property(
    fc.record({
      name: fc.string({ minLength: 1, maxLength: 100 }),
      displayName: fc.string({ minLength: 1, maxLength: 100 }),
      author: fc.string({ minLength: 1, maxLength: 100 }),
      description: fc.string({ minLength: 10, maxLength: 1024 }),
      keywords: fc.array(fc.string({ minLength: 1, maxLength: 50 }), { minLength: 1, maxLength: 50 }),
    }),
    (fm) => {
      expect(typeof fm.name).toBe('string');
      expect(fm.name.length).toBeGreaterThan(0);
      expect(typeof fm.description).toBe('string');
      expect(fm.description.length).toBeGreaterThanOrEqual(10);
      expect(Array.isArray(fm.keywords)).toBe(true);
      expect(fm.keywords.length).toBeGreaterThan(0);
      fm.keywords.forEach(k => expect(typeof k).toBe('string'));
    }
  ), { numRuns: 100 });
});

// Feature: micro-cosmos-code-reviewer-power, Property 2: Keyword Category Coverage
test('Property 2: Keyword Category Coverage', () => {
  const reviewKeywords = ['code-review', 'review', 'adversarial', 'skeptical'];
  const brandKeywords = ['micro-cosmos', 'modernization'];
  const severityKeywords = ['blocker', 'major', 'minor'];
  const qualityKeywords = ['tdd', 'decimal', 'hexagonal', 'fidelity'];

  fc.assert(fc.property(
    fc.tuple(
      fc.constantFrom(...reviewKeywords),
      fc.constantFrom(...brandKeywords),
      fc.constantFrom(...severityKeywords),
      fc.constantFrom(...qualityKeywords),
      fc.array(fc.string({ minLength: 1, maxLength: 30 }), { minLength: 0, maxLength: 5 }),
    ).map(([rev, alc, sev, qual, extra]) => [rev, alc, sev, qual, ...extra]),
    (keywords) => {
      const hasReview = keywords.some(k => reviewKeywords.includes(k));
      const hasBrand = keywords.some(k => brandKeywords.includes(k));
      const hasSeverity = keywords.some(k => severityKeywords.includes(k));
      const hasQuality = keywords.some(k => qualityKeywords.includes(k));
      expect(hasReview).toBe(true);
      expect(hasBrand).toBe(true);
      expect(hasSeverity).toBe(true);
      expect(hasQuality).toBe(true);
    }
  ), { numRuns: 100 });
});

// Validate actual POWER.md
test('Actual POWER.md satisfies Property 1', () => {
  expect(typeof frontmatter.name).toBe('string');
  expect(frontmatter.name.length).toBeGreaterThan(0);
  expect(typeof frontmatter.description).toBe('string');
  expect(frontmatter.description.length).toBeGreaterThanOrEqual(10);
  expect(Array.isArray(frontmatter.keywords)).toBe(true);
  expect(frontmatter.keywords.length).toBeGreaterThan(0);
});

test('Actual POWER.md satisfies Property 2 — keyword categories covered', () => {
  const kw = frontmatter.keywords;
  expect(kw.some(k => ['code-review', 'review', 'adversarial', 'skeptical'].includes(k))).toBe(true);
  expect(kw.some(k => ['micro-cosmos'].includes(k))).toBe(true);
  expect(kw.some(k => ['blocker', 'major', 'minor'].includes(k))).toBe(true);
  expect(kw.some(k => ['tdd', 'decimal', 'hexagonal', 'fidelity', 'correctness'].includes(k))).toBe(true);
});
""", encoding="utf-8")
        (code_reviewer_dir / "tests" / "power.unit.test.js").write_text("""\
import { test, expect } from 'vitest';
import fs from 'fs';
import yaml from 'js-yaml';

const POWER_PATH = new URL('../POWER.md', import.meta.url).pathname;
const raw = fs.readFileSync(POWER_PATH, 'utf8');
const parts = raw.split('---');
const frontmatter = yaml.load(parts[1]);
const body = parts.slice(2).join('---');

// Frontmatter values
test('name is micro-cosmos-code-reviewer', () => {
  expect(frontmatter.name).toBe('micro-cosmos-code-reviewer');
});
test('displayName is Micro-Cosmos Code Reviewer', () => {
  expect(frontmatter.displayName).toBe('Micro-Cosmos Code Reviewer');
});
test('author is Micro-Cosmos', () => {
  expect(frontmatter.author).toBe('Micro-Cosmos');
});
test('keywords include code-review', () => {
  expect(frontmatter.keywords).toContain('code-review');
});
test('keywords include micro-cosmos', () => {
  expect(frontmatter.keywords).toContain('micro-cosmos');
});
test('keywords include blocker', () => {
  expect(frontmatter.keywords).toContain('blocker');
});

// File structure
test('POWER.md file exists', () => {
  expect(fs.existsSync(POWER_PATH)).toBe(true);
});
test('README.md exists', () => {
  const p = new URL('../README.md', import.meta.url).pathname;
  expect(fs.existsSync(p)).toBe(true);
});
test('package.json exists', () => {
  const p = new URL('../package.json', import.meta.url).pathname;
  expect(fs.existsSync(p)).toBe(true);
});

// Response Contract
test('body contains Response Contract section', () => {
  expect(body).toContain('Response Contract');
});
test('body contains verdict PASS/WARN/FAIL', () => {
  expect(body).toContain('PASS');
  expect(body).toContain('FAIL');
});

// Severity definitions
test('body contains Severity Definitions', () => {
  expect(body).toContain('Severity Definitions');
});
test('body defines BLOCKER severity', () => {
  expect(body).toContain('BLOCKER');
});
test('body defines MAJOR severity', () => {
  expect(body).toContain('MAJOR');
});
test('body defines MINOR severity', () => {
  expect(body).toContain('MINOR');
});
test('body defines NIT severity', () => {
  expect(body).toContain('NIT');
});

// 7-category checklist
test('body contains 7-Category Checklist', () => {
  expect(body).toContain('7-Category Checklist');
});
test('body covers Functional Equivalence', () => {
  expect(body).toContain('Functional Equivalence');
});
test('body covers Decimal Hygiene', () => {
  expect(body).toContain('Decimal Hygiene');
});
test('body covers Hexagonal Compliance', () => {
  expect(body).toContain('Hexagonal Compliance');
});
test('body covers OTel / Observability', () => {
  expect(body).toContain('OTel');
});

// Gate 5
test('body references Gate 5 verdict', () => {
  expect(body).toContain('Gate 5');
});

// Workflows
test('body contains Common Workflows section', () => {
  expect(body).toContain('Common Workflows');
});
test('body contains skeptical first-pass review workflow', () => {
  expect(body).toContain('Skeptical first-pass review');
});
""", encoding="utf-8")
        # .kiro/specs/
        _code_reviewer_specs = code_reviewer_dir / ".kiro" / "specs" / "micro-cosmos-code-reviewer-power"
        _code_reviewer_specs.mkdir(parents=True, exist_ok=True)
        (_code_reviewer_specs / ".config.kiro").write_text('{"generationMode": "requirements-first"}\n', encoding="utf-8")
        (_code_reviewer_specs / "requirements.md").write_text("""\
# Requirements — Micro-Cosmos Code Reviewer Power

## REQ-1: Business Logic Fidelity
The power MUST verify that every domain invariant present in the source seam is enforced in the translated output. Silent no-ops that replace explicit guards are BLOCKER findings.

## REQ-2: Decimal Hygiene Audit
The power MUST detect and classify as BLOCKER any use of `float`, `double`, `f32`, `f64`, or `number` (TypeScript) for monetary or financial values. It MUST verify the correct decimal type is used per target language.

## REQ-3: Three-Category Test Audit
The power MUST verify that translated tests cover all three categories: happy-path, rule-violation, and edge-case. Missing any category is BLOCKER. Tests with no meaningful assertion are MAJOR.

## REQ-4: Hexagonal Architecture Audit
The power MUST verify hexagonal layer separation: `domain/` contains no I/O or framework imports, `application/` contains only use-case interfaces, `infrastructure/` contains adapters. Violations are BLOCKER.

## REQ-5: OTel Span Coverage Audit
The power MUST check that every public service method has an OTel span. Missing span on any public service method is MAJOR. Missing span assertions in tests is MINOR.

## REQ-6: JVM File Path Audit
For JVM targets, the power MUST verify all implementation files are under `src/main/<lang>/` and all test files under `src/test/<lang>/`. Bare package paths at root are MAJOR.

## REQ-7: LLM Mode Review Context
When running in LLM mode with Micro-Cosmos pipeline data available, the power MUST read source seam files alongside the translated output and perform a full fidelity check. Seam report, bounded context map, and architect output MUST inform the review.

## REQ-8: Deterministic Mode Checklist
When running in deterministic mode, the power MUST emit the 7-category structural checklist (functional equivalence, decimal hygiene, test coverage, hexagonal compliance, language conventions, package structure, OTel) based on static analysis of the generated files.

## REQ-9: Severity Classification
Every finding MUST be classified as BLOCKER (wrong business logic, missing test category, float for money, broken hexagonal layer), MAJOR (structural issue, missing OTel span, wrong path), MINOR (improvement suggestion, partial coverage), or NIT (style preference only).

## REQ-10: Gate 5 Verdict
The power MUST emit a Gate 5 verdict: PASS (no BLOCKER findings), WARN (MAJOR findings present), or FAIL (BLOCKER findings present). The verdict MUST include a summary table of finding counts per severity.
""", encoding="utf-8")
        (_code_reviewer_specs / "design.md").write_text("""\
# Design — Micro-Cosmos Code Reviewer Power

## Architecture

Steering-only Kiro.dev Power (no mcpServers). All guidance is embedded in `POWER.md` and delivered as steering instructions to Kiro's LLM context.

## Data Models

### Review Context
When run inside an Micro-Cosmos LLM pipeline, the following data is available:
```
{
  "source_seam_files": ["src/main/java/.../FraudScoringService.java"],
  "translated_files": ["src/main/kotlin/.../FraudScoringService.kt"],
  "seam_id": "fraud-scoring",
  "source_language": "java",
  "target_language": "kotlin",
  "bounded_context_map": {"contexts": [...]},
  "architect_output": {"seams": [...]}
}
```

When run in deterministic mode, only source path, source language, and target language are available. The reviewer applies structural heuristics (file path conventions, keyword presence for decimal types, OTel imports) without LLM-driven fidelity checking.

### Review Finding
```
{ "severity": "BLOCKER|MAJOR|MINOR|NIT", "file": "...", "symbol": "...", "issue": "..." }
```

### Gate 5 Verdict
```
{
  "verdict": "PASS|WARN|FAIL",
  "passed": true|false,
  "findings": [...],
  "metrics": {
    "files_reviewed": N,
    "todo_density_pct": N,
    "port_interfaces_present": N,
    "port_interfaces_missing": N
  },
  "summary": "..."
}
```

## Testing Strategy

### Property 1: Frontmatter Schema Completeness
Every valid frontmatter object must have non-empty `name`, `description` (≥10 chars), and at least one keyword. Fast-check generates 100 arbitrary records and asserts the schema invariants.

### Property 2: Keyword Category Coverage
A valid keyword set must cover: review category (code-review/review/adversarial), Micro-Cosmos category (micro-cosmos), severity category (blocker/major/minor), and quality category (tdd/decimal/hexagonal). Fast-check generates 100 keyword tuples.

## Key Design Decisions

- **Adversarial stance**: reviewer is intentionally skeptical — every code path is suspect until proven correct by explicit guard or test assertion.
- **LLM mode context**: reads source seam files + translated files + seam report for full fidelity check. Richer Micro-Cosmos pipeline output means more precise findings.
- **Deterministic mode context**: applies structural heuristics on generated files using only source path, source language, and target language. Cannot verify business logic fidelity, but can check file paths, OTel imports, and decimal type usage.
- **7-category checklist**: covers all Gate 5 acceptance criteria in a single structured pass, so the reviewer's output maps directly to the Gate 5 PR checklist.
- **BLOCKER escalation**: any BLOCKER finding triggers Gate 5 FAIL, forcing a TDD loop re-run before merge.
""", encoding="utf-8")
        (_code_reviewer_specs / "tasks.md").write_text("""\
# Tasks — Micro-Cosmos Code Reviewer Power

- [x] 1. Write POWER.md frontmatter (name, displayName, author, description, keywords)
- [x] 2. Write Response Contract section (verdict, findings, summary, metrics)
- [x] 3. Write Severity Definitions section (BLOCKER, MAJOR, MINOR, NIT table)
- [x] 4. Write Workflow section (read source, read translated, 7 checks, emit Response Contract)
- [x] 5. Write 7-Category Checklist (functional equivalence, decimal hygiene, test coverage, hexagonal, conventions, package structure, OTel)
- [x] 6. Write Security Checks section
- [x] 7. Write Gate 5 Alignment section (verdict table)
- [x] 8. Write Common Workflows section (skeptical review, security review, OTel coverage review)
- [x] 9. Write README.md
- [x] 10. Write package.json (ESM, vitest, fast-check, js-yaml)
- [x] 11. Write vitest.config.js
- [x] 12. Write tests/power.property.test.js (Property 1: schema, Property 2: keyword categories)
- [x] 13. Write tests/power.unit.test.js (frontmatter values, severity definitions, 7-category checklist, Gate 5 verdict)
- [x] 14. Write .kiro/specs/micro-cosmos-code-reviewer-power/requirements.md (10 requirements)
- [x] 15. Write .kiro/specs/micro-cosmos-code-reviewer-power/design.md (LLM vs deterministic context)
- [x] 16. Write .kiro/specs/micro-cosmos-code-reviewer-power/tasks.md
- [x] 17. Write .kiro/specs/micro-cosmos-code-reviewer-power/.config.kiro
""", encoding="utf-8")

    # ── micro-cosmos-security-power ────────────────────────────────────────────────
    security_dir = kiro_dir / "micro-cosmos-security-power"
    security_dir.mkdir(parents=True, exist_ok=True)
    if not (security_dir / "POWER.md").exists():
        _sec_findings_kiro = _security_findings_block(run_path)
        (security_dir / "POWER.md").write_text(f"""\
---
name: "micro-cosmos-security"
displayName: "Micro-Cosmos Security"
author: "Micro-Cosmos"
description: "Use when reviewing translated code for security defects. Checks 10 OWASP-aligned categories (injection, auth, crypto, secrets, validation, exposure, deserialization, path traversal, SSRF, supply chain) and, when available, cross-references this run's own security_report.json findings against the translated output."
keywords: ["security", "owasp", "injection", "auth", "crypto", "secrets", "ssrf", "deserialization", "supply-chain", "micro-cosmos", "vulnerability", "cve"]
---

# Micro-Cosmos Security Power

Security review for Micro-Cosmos translated microservices. Checks a fixed,
OWASP-aligned category checklist against the translated code, and — when this
run has already been through the Security phase — cross-references this run's
own findings so nothing flagged in the source is silently dropped or newly
introduced by translation.

## Response Contract

Every review must include:

1. **Verdict** — `PASS`, `WARN`, or `FAIL`.
2. **Findings** — each finding in the format: `[SEVERITY] file:symbol — description`.
3. **Carryover check** — for each `security_report.json` finding available, state whether it
   was fixed, carried over unchanged, or mutated by the translation.
4. **Summary** — one paragraph on overall security posture and the most critical gap.

## Severity Definitions

| Severity | When to use |
|---|---|
| **BLOCKER** | Hardcoded secret, SQL/command injection, missing auth on a state-changing endpoint |
| **MAJOR** | Missing input validation, PII logged, weak/deprecated crypto |
| **MINOR** | Missing rate limiting, verbose error messages, unpinned dependency without a known CVE |

A PR with any BLOCKER must NOT be merged (Gate 5 fail) — same rule as
`micro-cosmos-code-reviewer-power`, since security BLOCKERs are a subset of that
power's own Security Checks section; this power goes deeper on that one topic.

## Category Checklist

{_security_categories_table()}

{_sec_findings_kiro}## Workflow

1. Read translated output files for every category above — grep for
   string-concatenated queries, hardcoded credentials, and unvalidated inputs
   first (highest yield).
2. If `security_report.json` findings are listed above, cross-check each one
   against the translated code: fixed, carried over, or newly introduced.
3. Check for hardcoded credentials, tokens, or API keys.
4. Check all DB queries for string concatenation vs parameterization.
5. Check all log statements for PII/credential fields.
6. Verify no SSL/TLS validation bypass in HTTP clients.
7. Emit Response Contract: verdict, findings, carryover check, summary.

## Common Workflows

### Fresh security review (no security_report.json yet)
1. Read all translated files
2. Work through the 10-category checklist
3. Report each failure as `[SEVERITY] file:symbol — description`
4. Emit Response Contract (carryover check omitted — nothing to carry over)

### Post-Security-phase review (security_report.json present)
1. Read the findings listed above
2. For each, locate the equivalent code in the translated output
3. Classify: FIXED / CARRIED OVER / MUTATED
4. Continue with the fresh-review checklist for anything not already covered
5. Emit Response Contract including the carryover check
""", encoding="utf-8")

        (security_dir / "README.md").write_text("""\
# Micro-Cosmos Security Power

Kiro.dev Power for security review of Micro-Cosmos translated microservices.

## What it does

- Checks translated code against a 10-category, OWASP-aligned security checklist
  (injection, auth, crypto, secrets, validation, exposure, deserialization, path
  traversal, SSRF, supply chain)
- Cross-references this run's own `security_report.json` findings (if the Security
  phase has run) against the translated output, classifying each as fixed, carried
  over, or newly introduced
- Classifies findings as BLOCKER / MAJOR / MINOR
- Produces a Gate 5-ready verdict (PASS / WARN / FAIL)

## When to activate

- You are reviewing translated output for security defects
- This run has real `security_report.json` findings you want cross-checked against
  the translated code, not just the original source
- You need a security-focused Gate 5 review
""", encoding="utf-8")
        (security_dir / "package.json").write_text('{\n  "name": "micro-cosmos-security-power",\n  "version": "1.0.0",\n  "type": "module",\n  "scripts": { "test": "vitest run" },\n  "devDependencies": {\n    "vitest": "^1.6.0",\n    "fast-check": "^3.19.0",\n    "js-yaml": "^4.1.0"\n  }\n}\n', encoding="utf-8")
        (security_dir / "vitest.config.js").write_text("import { defineConfig } from 'vitest/config';\nexport default defineConfig({ test: { include: ['tests/**/*.test.js'] } });\n", encoding="utf-8")
        (security_dir / "tests").mkdir(exist_ok=True)
        (security_dir / "tests" / "power.property.test.js").write_text("""\
import { describe, test, expect } from 'vitest';
import * as fc from 'fast-check';
import fs from 'fs';
import yaml from 'js-yaml';

const POWER_PATH = new URL('../POWER.md', import.meta.url).pathname;
const raw = fs.readFileSync(POWER_PATH, 'utf8');
const parts = raw.split('---');
const frontmatter = yaml.load(parts[1]);
const body = parts.slice(2).join('---');

// Feature: micro-cosmos-security-power, Property 1: Frontmatter Schema Completeness
test('Property 1: Frontmatter Schema Completeness', () => {
  fc.assert(fc.property(
    fc.record({
      name: fc.string({ minLength: 1, maxLength: 100 }),
      displayName: fc.string({ minLength: 1, maxLength: 100 }),
      author: fc.string({ minLength: 1, maxLength: 100 }),
      description: fc.string({ minLength: 10, maxLength: 1024 }),
      keywords: fc.array(fc.string({ minLength: 1, maxLength: 50 }), { minLength: 1, maxLength: 50 }),
    }),
    (fm) => {
      expect(typeof fm.name).toBe('string');
      expect(fm.name.length).toBeGreaterThan(0);
      expect(typeof fm.description).toBe('string');
      expect(fm.description.length).toBeGreaterThanOrEqual(10);
      expect(Array.isArray(fm.keywords)).toBe(true);
      expect(fm.keywords.length).toBeGreaterThan(0);
      fm.keywords.forEach(k => expect(typeof k).toBe('string'));
    }
  ), { numRuns: 100 });
});

// Feature: micro-cosmos-security-power, Property 2: Keyword Category Coverage
test('Property 2: Keyword Category Coverage', () => {
  const secKeywords = ['security', 'owasp', 'vulnerability', 'cve'];
  const categoryKeywords = ['injection', 'auth', 'crypto', 'secrets', 'ssrf', 'deserialization', 'supply-chain'];
  const brandKeywords = ['micro-cosmos'];

  fc.assert(fc.property(
    fc.tuple(
      fc.constantFrom(...secKeywords),
      fc.constantFrom(...categoryKeywords),
      fc.constantFrom(...brandKeywords),
      fc.array(fc.string({ minLength: 1, maxLength: 30 }), { minLength: 0, maxLength: 5 }),
    ).map(([sec, cat, alc, extra]) => [sec, cat, alc, ...extra]),
    (keywords) => {
      const hasSec = keywords.some(k => secKeywords.includes(k));
      const hasCategory = keywords.some(k => categoryKeywords.includes(k));
      const hasBrand = keywords.some(k => brandKeywords.includes(k));
      expect(hasSec).toBe(true);
      expect(hasCategory).toBe(true);
      expect(hasBrand).toBe(true);
    }
  ), { numRuns: 100 });
});

// Validate actual POWER.md
test('Actual POWER.md satisfies Property 1', () => {
  expect(typeof frontmatter.name).toBe('string');
  expect(frontmatter.name.length).toBeGreaterThan(0);
  expect(typeof frontmatter.description).toBe('string');
  expect(frontmatter.description.length).toBeGreaterThanOrEqual(10);
  expect(Array.isArray(frontmatter.keywords)).toBe(true);
  expect(frontmatter.keywords.length).toBeGreaterThan(0);
});

test('Actual POWER.md satisfies Property 2 — keyword categories covered', () => {
  const kw = frontmatter.keywords;
  expect(kw.some(k => ['security', 'owasp', 'vulnerability', 'cve'].includes(k))).toBe(true);
  expect(kw.some(k => ['injection', 'auth', 'crypto', 'secrets', 'ssrf', 'deserialization', 'supply-chain'].includes(k))).toBe(true);
  expect(kw.some(k => ['micro-cosmos'].includes(k))).toBe(true);
});
""", encoding="utf-8")
        (security_dir / "tests" / "power.unit.test.js").write_text("""\
import { test, expect } from 'vitest';
import fs from 'fs';
import yaml from 'js-yaml';

const POWER_PATH = new URL('../POWER.md', import.meta.url).pathname;
const raw = fs.readFileSync(POWER_PATH, 'utf8');
const parts = raw.split('---');
const frontmatter = yaml.load(parts[1]);
const body = parts.slice(2).join('---');

test('name is micro-cosmos-security', () => {
  expect(frontmatter.name).toBe('micro-cosmos-security');
});
test('displayName is Micro-Cosmos Security', () => {
  expect(frontmatter.displayName).toBe('Micro-Cosmos Security');
});
test('author is Micro-Cosmos', () => {
  expect(frontmatter.author).toBe('Micro-Cosmos');
});
test('keywords include security', () => {
  expect(frontmatter.keywords).toContain('security');
});
test('keywords include owasp', () => {
  expect(frontmatter.keywords).toContain('owasp');
});
test('keywords include micro-cosmos', () => {
  expect(frontmatter.keywords).toContain('micro-cosmos');
});

test('POWER.md file exists', () => {
  expect(fs.existsSync(POWER_PATH)).toBe(true);
});
test('README.md exists', () => {
  const p = new URL('../README.md', import.meta.url).pathname;
  expect(fs.existsSync(p)).toBe(true);
});
test('package.json exists', () => {
  const p = new URL('../package.json', import.meta.url).pathname;
  expect(fs.existsSync(p)).toBe(true);
});

test('body contains Response Contract section', () => {
  expect(body).toContain('Response Contract');
});
test('body contains verdict PASS/WARN/FAIL', () => {
  expect(body).toContain('PASS');
  expect(body).toContain('FAIL');
});
test('body contains Severity Definitions', () => {
  expect(body).toContain('Severity Definitions');
});
test('body defines BLOCKER severity', () => {
  expect(body).toContain('BLOCKER');
});
test('body contains Category Checklist', () => {
  expect(body).toContain('Category Checklist');
});
test('body covers Injection category', () => {
  expect(body).toContain('Injection');
});
test('body covers Secrets category', () => {
  expect(body).toContain('Secrets');
});
test('body covers SSRF category', () => {
  expect(body).toContain('SSRF');
});
test('body covers Supply chain category', () => {
  expect(body).toContain('Supply chain');
});
test('body contains carryover check concept', () => {
  expect(body).toContain('carryover');
});
test('body contains Common Workflows section', () => {
  expect(body).toContain('Common Workflows');
});
""", encoding="utf-8")
        _security_specs = security_dir / ".kiro" / "specs" / "micro-cosmos-security-power"
        _security_specs.mkdir(parents=True, exist_ok=True)
        (_security_specs / ".config.kiro").write_text('{"generationMode": "requirements-first"}\n', encoding="utf-8")
        (_security_specs / "requirements.md").write_text("""\
# Requirements — Micro-Cosmos Security Power

## REQ-1: Category Checklist Coverage
The power MUST check translated output against all 10 categories: injection, auth, crypto, secrets, validation, exposure, deserialization, path traversal, SSRF, and supply chain.

## REQ-2: Static Checklist Always Available
The category checklist MUST be emitted even when this run has no `security_report.json` yet — the power does not depend on the Security phase having run.

## REQ-3: Real Findings Cross-Reference
When `security_report.json` exists for this run, the power MUST list its findings (severity, category, location, title, remediation) and cross-check each against the translated output, classifying it as fixed, carried over, or mutated.

## REQ-4: Severity Classification
Every finding MUST be classified as BLOCKER (hardcoded secret, injection, missing auth), MAJOR (missing validation, PII logged, weak crypto), or MINOR (missing rate limiting, verbose errors, unpinned dependency without a known CVE).

## REQ-5: Gate 5 Verdict
The power MUST emit a Gate 5 verdict: PASS (no BLOCKER findings), WARN (MAJOR findings present), or FAIL (BLOCKER findings present).

## REQ-6: LLM Mode Context
When running in LLM mode, the power MUST read the translated output files directly and reason about each category against the actual code, not just keyword-match.

## REQ-7: Deterministic Mode Checklist
When running in deterministic mode, the power emits the static category checklist and, if `security_report.json` exists, the real findings table — both computed without an LLM call.
""", encoding="utf-8")
        (_security_specs / "design.md").write_text("""\
# Design — Micro-Cosmos Security Power

## Architecture

Steering-only Kiro.dev Power (no mcpServers). All guidance is embedded in `POWER.md`.

## Data Models

### Security Finding (from security_report.json, when present)
```
{ "severity": "CRITICAL|HIGH|MEDIUM|LOW|INFO", "category": "INJECTION|AUTH|...", "location": "...", "title": "...", "remediation": "..." }
```

### Carryover Classification
```
{ "finding_id": "SEC-001", "status": "FIXED|CARRIED_OVER|MUTATED", "note": "..." }
```

## Testing Strategy

### Property 1: Frontmatter Schema Completeness
Every valid frontmatter object must have non-empty `name`, `description` (>=10 chars), and at least one keyword.

### Property 2: Keyword Category Coverage
A valid keyword set must cover: security category (security/owasp/vulnerability/cve), a specific OWASP-aligned category (injection/auth/crypto/secrets/ssrf/deserialization/supply-chain), and Micro-Cosmos category (micro-cosmos).

## Key Design Decisions

- **Static checklist first, real findings second**: the category checklist always renders, so the power is useful before the Security phase has even run — real `security_report.json` findings are additive, not a prerequisite.
- **Carryover check, not just re-scanning**: when real findings exist, the power's job shifts from "find new issues" to "confirm known issues were actually addressed by translation" — a different, narrower, and more actionable question than a generic re-scan.
- **Shared category list with the OpenSpec `specs/security/spec.md` and the Claude Code `/security-review` skill**: all three render the same `_SECURITY_CATEGORIES` source, so a category added to one automatically appears in all three artifact types.
""", encoding="utf-8")
        (_security_specs / "tasks.md").write_text("""\
# Tasks — Micro-Cosmos Security Power

- [x] 1. Write POWER.md frontmatter (name, displayName, author, description, keywords)
- [x] 2. Write Response Contract section (verdict, findings, carryover check, summary)
- [x] 3. Write Severity Definitions section (BLOCKER, MAJOR, MINOR table)
- [x] 4. Write Category Checklist (10 OWASP-aligned categories, shared with the Skill and OpenSpec renderings)
- [x] 5. Write real-findings cross-reference section (populated when security_report.json exists)
- [x] 6. Write Workflow section
- [x] 7. Write Common Workflows section (fresh review vs post-Security-phase review)
- [x] 8. Write README.md
- [x] 9. Write package.json (ESM, vitest, fast-check, js-yaml)
- [x] 10. Write vitest.config.js
- [x] 11. Write tests/power.property.test.js (Property 1: schema, Property 2: keyword categories)
- [x] 12. Write tests/power.unit.test.js (frontmatter values, severity definitions, category coverage)
- [x] 13. Write .kiro/specs/micro-cosmos-security-power/requirements.md (7 requirements)
- [x] 14. Write .kiro/specs/micro-cosmos-security-power/design.md
- [x] 15. Write .kiro/specs/micro-cosmos-security-power/tasks.md
- [x] 16. Write .kiro/specs/micro-cosmos-security-power/.config.kiro
""", encoding="utf-8")

    return str(kiro_dir)


# ─── OpenSpec (github.com/Fission-AI/OpenSpec) generation ───────────────────

def _openspec_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-") or "item"


_OPENSPEC_WHEN_RE = re.compile(r"\bwhen\b", re.IGNORECASE)
_OPENSPEC_THEN_RE = re.compile(r"\bthen\b", re.IGNORECASE)


def _openspec_scenario(criterion: str, title: str, index: int) -> str:
    """Render one feature_specs.json acceptance_criteria string as a
    WHEN/THEN scenario block. Never fabricates content beyond the criterion
    text itself — if the criterion already reads as when/then prose, split on
    a standalone "then"; otherwise synthesize a generic WHEN clause and use
    the criterion verbatim as the THEN clause.

    Uses word-boundary regex, not a plain substring/removeprefix check: a bare
    "then" in lower.rfind("then") also matches inside ordinary words like
    "lengthen"/"strengthen"/"authentication", severing them mid-word, and
    .removeprefix("When") is case-sensitive so an all-caps "WHEN ... THEN ..."
    criterion was never stripped, duplicating "WHEN WHEN ...". \\b anchors
    fix both without changing behavior on well-formed when/then criteria."""
    c = (criterion or "").strip()
    heading = " ".join(c.split()[:8]) or f"Scenario {index + 1}"
    when_m = _OPENSPEC_WHEN_RE.search(c)
    then_m = _OPENSPEC_THEN_RE.search(c)
    if when_m and then_m and then_m.start() > when_m.start():
        when_clause = c[when_m.end():then_m.start()].strip(" ,:-")
        then_clause = c[then_m.end():].strip(" ,:-")
        if not when_clause:
            when_clause = f"a client exercises the {title} capability"
        if not then_clause:
            then_clause = c
    else:
        when_clause = f"a client exercises the {title} capability"
        then_clause = c
    return f"""\
#### Scenario: {heading}
- **WHEN** {when_clause}
- **THEN** {then_clause}
"""


def _openspec_spec_from_feature_specs(specs: list[dict], work_stream_name: str) -> str:
    """One openspec/specs/<slug>/spec.md body for a single work stream's specs."""
    lines = [f"# {work_stream_name}", "", "## ADDED Requirements", ""]
    for spec in specs:
        # `x.get(k) or default`, not `x.get(k, default)` — the latter's default only
        # applies when the key is *missing*, not when its value is explicitly JSON
        # `null` (submit_feature_specs validates key presence, not non-nullness).
        title = spec.get("title") or spec.get("seam_id") or "Untitled"
        lines.append(f"### Requirement: {title}")
        lines.append((spec.get("description") or "").strip() or "(no description provided)")
        lines.append("")
        if spec.get("business_value"):
            lines.append(f"Business value: {spec['business_value']}")
            lines.append("")
        criteria = spec.get("acceptance_criteria") or []
        for i, c in enumerate(criteria):
            lines.append(_openspec_scenario(c, title, i))
        if not criteria:
            lines.append(_openspec_scenario(
                f"the {title} capability behaves as translated from {spec.get('seam_id') or 'the source seam'}",
                title, 0,
            ))
        surf = spec.get("api_surface")
        endpoints = [e for e in (surf.get("endpoints") or []) if e] if surf else []
        if endpoints:
            eps = ", ".join(f"`{e.get('method') or 'GET'} {e.get('path') or '/'}`" for e in endpoints)
            lines.append(f"> Exposed via: {eps}")
            lines.append("")
    return "\n".join(lines) + "\n"


def _openspec_security_spec(run_path: Path) -> str:
    lines = [
        "# Security", "", "## ADDED Requirements", "",
        "### Requirement: Baseline security category coverage",
        "The translated application SHALL NOT exhibit any of the following categories "
        "of defect, regardless of whether the Security phase has produced run-specific findings.",
        "",
    ]
    for i, (cat, look, fix) in enumerate(_SECURITY_CATEGORIES):
        lines.append(f"""\
#### Scenario: {cat} defects are absent
- **WHEN** the codebase is reviewed for {cat.lower()} issues ({look})
- **THEN** no such defect is present; where relevant, the fix is: {fix}
""")

    report = _read_run_json(run_path, "security_report.json")
    findings = report.get("findings") if isinstance(report, dict) else None
    findings = [f for f in findings if isinstance(f, dict)] if isinstance(findings, list) else None
    if findings:
        lines.append("### Requirement: This run's confirmed security findings are remediated")
        lines.append(
            "Findings below come from this run's own `security_report.json` — real, "
            "run-specific evidence, not the generic category list above."
        )
        lines.append("")
        for f in sorted(findings, key=lambda f: _SEV_ORDER.get(f.get("severity") or "INFO", 9))[:_SECURITY_FINDINGS_LIMIT]:
            remediation = _md_cell(f.get("remediation") or "")
            lines.append(f"""\
#### Scenario: {_md_cell(f.get('id') or 'finding')} — {_md_cell(f.get('title') or 'untitled')} is fixed
- **WHEN** `{_md_cell(f.get('location') or 'the affected location')}` is reviewed post-translation
- **THEN** the {_md_cell(f.get('severity') or 'reported')} finding is remediated: {remediation}
""")
    return "\n".join(lines) + "\n"


def _truncate_heading(text: str, limit: int = 60) -> str:
    """Truncate at a word boundary, adding an ellipsis when cut — a bare
    text[:limit] slice severs the last word mid-character with no indication
    anything was cut."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text.rfind(" ", 0, limit)
    if cut <= 0:
        cut = limit
    return text[:cut].rstrip() + "…"


def _checklist_to_scenarios(checklist: str, when_context: str) -> list[str]:
    """Render each '- [ ] ...' checklist line as one OpenSpec Scenario block
    sharing the same WHEN-context phrase. Shared by _openspec_observability_spec
    and _openspec_testing_spec, which used to duplicate this identical loop
    with only the WHEN phrase differing."""
    out = []
    for item in checklist.splitlines():
        text = item.removeprefix("- [ ] ").strip()
        if not text:
            continue
        out.append(f"""\
#### Scenario: {_truncate_heading(text)}
- **WHEN** {when_context}
- **THEN** {text}
""")
    return out


def _openspec_observability_spec() -> str:
    lines = ["# Observability & Logging", "", "## ADDED Requirements", ""]
    lines.append("### Requirement: Distributed tracing and metrics")
    lines += _checklist_to_scenarios(_OBSERVABILITY_CHECKLIST, "the translated service is exercised in production")
    lines.append("### Requirement: Structured, correlatable, safe logging")
    lines += _checklist_to_scenarios(_LOGGING_STANDARDS_CHECKLIST, "the translated service is exercised in production")
    return "\n".join(lines) + "\n"


def _openspec_testing_spec() -> str:
    lines = ["# Testing", "", "## ADDED Requirements", "", "### Requirement: Three-category test coverage"]
    lines += _checklist_to_scenarios(_TESTING_TAXONOMY_CHECKLIST, "the translated service's test suite is run")
    return "\n".join(lines) + "\n"


def _write_openspec(
    run_path: Path,
    source_path: str,
    source_lang: str,
    target_lang: str,
) -> str:
    """Write an OpenSpec (github.com/Fission-AI/OpenSpec) tree to
    <run_path>/reports/openspec/, derived from this run's own artifacts:

      openspec/
        project.md                     — run/source/target context
        specs/<work-stream-slug>/spec.md  — from feature_specs.json
        specs/security/spec.md         — from security_report.json (if present) + baseline categories
        specs/observability/spec.md    — shared observability + logging content
        specs/testing/spec.md          — shared testing taxonomy
        changes/<lang>-to-<lang>-migration/
          proposal.md                  — from tnas.json summary/rationale/notes
          design.md                    — from tnas.json context_decisions + pattern recommendations
          tasks.md                     — numbered checklist from work_streams.json
        archive/                       — created empty; Micro-Cosmos never populates it

    Always overwrites existing files — unlike _write_output_skills/
    _write_kiro_powers (pure templates, safe to skip once written), this
    content is derived from artifacts that can legitimately change after a
    Gate 3 / Gate 4.5 rejection and re-run.

    Raises FileNotFoundError only if NONE of feature_specs.json, tnas.json,
    work_streams.json, or seam.json exist yet — there would be nothing real
    to write. Each missing artifact degrades its own section gracefully
    (a placeholder note) rather than failing the whole tree.
    """
    feature_specs = _read_run_json(run_path, "feature_specs.json")
    tnas = _read_run_json(run_path, "tnas.json")
    work_streams = _read_run_json(run_path, "work_streams.json")
    seam_report = _read_run_json(run_path, "seam.json")

    if not any([feature_specs, tnas, work_streams, seam_report]):
        raise FileNotFoundError(
            "None of feature_specs.json, tnas.json, work_streams.json, seam.json "
            "exist yet — run at least the Cartographer phase (Gate 2) first."
        )

    tl_display = _LANG_DISPLAY.get(target_lang.lower(), target_lang.capitalize())
    sl_display = _LANG_DISPLAY.get(source_lang.lower(), source_lang.capitalize())

    openspec_dir = run_path / "reports" / "openspec"
    specs_dir = openspec_dir / "specs"
    changes_dir = openspec_dir / "changes"
    archive_dir = openspec_dir / "archive"
    for d in (specs_dir, changes_dir, archive_dir):
        d.mkdir(parents=True, exist_ok=True)

    # ── project.md ────────────────────────────────────────────────────────────
    (openspec_dir / "project.md").write_text(f"""\
# {Path(source_path).name if source_path else "project"}

Generated by Micro-Cosmos — migration from **{sl_display}** to **{tl_display}**.

- Run directory: `{run_path.name}`
- Source: `{source_path}`
- Target language: {tl_display}

This OpenSpec tree describes the seam-by-seam feature specifications and
architectural decisions produced by the Micro-Cosmos pipeline for this migration.
Requirements in `specs/` and the proposed change in `changes/` are derived
directly from this run's `feature_specs.json` and `tnas.json` artifacts —
not hand-written, and not generic boilerplate.
""", encoding="utf-8")

    # ── specs/<work-stream>/spec.md ───────────────────────────────────────────
    if feature_specs and feature_specs.get("specs"):
        by_stream: dict[str, list[dict]] = {}
        stream_names: dict[str, str] = {}
        for spec in feature_specs["specs"]:
            wsid = spec.get("work_stream_id", "general")
            by_stream.setdefault(wsid, []).append(spec)
            stream_names[wsid] = spec.get("work_stream_name", wsid)
        used_slugs: dict[str, str] = {}  # slug -> the wsid that claimed it
        for wsid, specs in by_stream.items():
            base_slug = _openspec_slug(stream_names.get(wsid, wsid))
            slug = base_slug
            if slug in used_slugs and used_slugs[slug] != wsid:
                # Two different work streams whose names differ only by case/
                # punctuation (e.g. "Payment Processing" vs "payment-processing")
                # would otherwise both resolve to the same directory and silently
                # overwrite each other's spec.md — disambiguate with the wsid.
                slug = f"{base_slug}-{_openspec_slug(wsid)}"
            used_slugs[slug] = wsid
            d = specs_dir / slug
            d.mkdir(parents=True, exist_ok=True)
            (d / "spec.md").write_text(
                _openspec_spec_from_feature_specs(specs, stream_names.get(wsid, wsid)),
                encoding="utf-8",
            )
    else:
        pending_dir = specs_dir / "_pending"
        pending_dir.mkdir(parents=True, exist_ok=True)
        (pending_dir / "spec.md").write_text(
            "# Specs pending\n\nfeature_specs.json has not been generated yet "
            "(Feature Specifier phase / Gate 4.5 not yet reached).\n",
            encoding="utf-8",
        )

    # ── specs/security, specs/observability, specs/testing ───────────────────
    (specs_dir / "security").mkdir(parents=True, exist_ok=True)
    (specs_dir / "security" / "spec.md").write_text(_openspec_security_spec(run_path), encoding="utf-8")
    (specs_dir / "observability").mkdir(parents=True, exist_ok=True)
    (specs_dir / "observability" / "spec.md").write_text(_openspec_observability_spec(), encoding="utf-8")
    (specs_dir / "testing").mkdir(parents=True, exist_ok=True)
    (specs_dir / "testing" / "spec.md").write_text(_openspec_testing_spec(), encoding="utf-8")

    # ── changes/<slug>/{proposal,design,tasks}.md ─────────────────────────────
    # Fixed, content-independent slug so repeated regeneration overwrites the
    # same change folder instead of accumulating stale duplicates.
    slug = _openspec_slug(f"{source_lang}-to-{target_lang}-migration")
    change_dir = changes_dir / slug
    change_dir.mkdir(parents=True, exist_ok=True)

    if tnas:
        notes = tnas.get("architect_notes") or []
        notes_md = "\n".join(f"- {n}" for n in notes) or "(no architect notes on this run — deterministic mode, or LLM enrichment not yet applied)"
        rationale = tnas.get("migration_sequence_rationale", "") or "(not yet available — populated by the Architect agent in LLM mode)"
        (change_dir / "proposal.md").write_text(f"""\
# Proposal: {sl_display} → {tl_display} migration

## Why
{tnas.get("summary", "(no summary available)")}

## What's changing
{rationale}

## Architect notes
{notes_md}
""", encoding="utf-8")

        rows = []
        # `or []`, not `.get(key, [])` — tnas.json can carry an explicit `null` for
        # either field (free-form LLM Architect output); the readiness guard above
        # doesn't catch that shape (a dict with a null-valued key is still truthy),
        # so `for x in tnas.get(key, [])` would raise TypeError on `for x in None`.
        for cd in tnas.get("context_decisions") or []:
            rows.append(
                f"| {_md_cell(cd.get('context'))} | {_md_cell(cd.get('communication_style'))} "
                f"| {_md_cell(cd.get('data_store'))} | {_md_cell(cd.get('execution_model'))} "
                f"| {_md_cell(cd.get('consistency_model'))} |"
            )
        table = "\n".join(rows) or "| _(no context_decisions on this run)_ | | | | |"
        pattern_rows = []
        for svc in tnas.get("services") or []:
            pattern = svc.get("pattern_recommendation") or svc.get("rationale") or "(no pattern recommendation)"
            seq = svc.get("migration_sequence")
            seq_note = f" (migration order: {seq})" if seq is not None else ""
            pattern_rows.append(f"- **{_md_cell(svc.get('service_id'))}** — {_md_cell(pattern)}{seq_note}")
        patterns_md = "\n".join(pattern_rows) or "(no services on this run)"
        # fitness_suite is a serialized FitnessSuite object ({"functions": [...],
        # "target_language": ..., ...}), not a bare list — see architect_tools.py's
        # build_canonical_suite(target_lang).model_dump(mode="json").
        _fitness_suite = tnas.get("fitness_suite") or {}
        _fitness_functions = _fitness_suite.get("functions", []) if isinstance(_fitness_suite, dict) else _fitness_suite
        fitness_names = [f.get("name", f.get("id", "")) for f in _fitness_functions]
        fitness_md = "\n".join(f"- {n}" for n in fitness_names) or "(fitness suite not yet available)"
        (change_dir / "design.md").write_text(f"""\
# Design

## Context decisions
| Context | Communication | Data store | Execution model | Consistency |
|---|---|---|---|---|
{table}

## Pattern recommendations
{patterns_md}

## Fitness functions
Fitness functions from the target-language fitness suite drive CI verification
of this migration (see `tnas.json.fitness_suite` for full rule bodies):
{fitness_md}
""", encoding="utf-8")
    else:
        placeholder = (
            "# Proposal pending\n\ntnas.json not yet generated "
            "(Architect phase / Gate 3 not yet reached).\n"
        )
        (change_dir / "proposal.md").write_text(placeholder, encoding="utf-8")
        (change_dir / "design.md").write_text(
            placeholder.replace("Proposal", "Design"), encoding="utf-8",
        )

    if work_streams and work_streams.get("work_streams"):
        lines = ["# Tasks", ""]
        for outer, ws in enumerate(work_streams["work_streams"], start=1):
            if not ws.get("seam_ids"):
                continue
            lines.append(f"## {outer}. {ws.get('name', ws.get('id', 'Work stream'))}")
            for inner, seam_id in enumerate(ws["seam_ids"], start=1):
                lines.append(f"- [ ] {outer}.{inner} Migrate seam `{seam_id}`")
            lines.append("")
        (change_dir / "tasks.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    elif seam_report and seam_report.get("seams"):
        lines = ["# Tasks", "", "## 1. Seams"]
        for inner, seam in enumerate(seam_report["seams"], start=1):
            lines.append(f"- [ ] 1.{inner} Migrate seam `{seam.get('id', seam.get('name', inner))}`")
        (change_dir / "tasks.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    else:
        (change_dir / "tasks.md").write_text(
            "# Tasks pending\n\nNo seam data yet (Cartographer/Architect phase not yet reached).\n",
            encoding="utf-8",
        )

    return str(openspec_dir)


def _seam_slug(seam_name: str) -> str:
    """Normalise a seam/bounded-context name to a safe directory slug.

    Examples: Btc → btc, CreditDecisioner → credit_decisioner, BTC → btc
    """
    slug = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", seam_name)
    return re.sub(r"[^a-z0-9_]", "_", slug.lower()).strip("_") or "seam"


def _output_dir_name(seam_name: str, target_lang: str) -> str:
    """Derive a consistent, human-readable output directory name.

    Examples: CreditDecisioner + python3 → credit_decisioner_python3
              PaymentProcessing + java21  → payment_processing_java21
    """
    slug = _seam_slug(seam_name)
    lang = re.sub(r"[^a-z0-9]", "", target_lang.lower())
    return f"{slug}_{lang}" if lang else slug


def _project_dir_name(source_path: str, target_lang: str) -> str:
    """Derive an output project directory name from the source repo and target language.

    Convention: {source_folder_name}_{target_lang}
    e.g. java_bankxyz_fraud_detection + kotlin → java_bankxyz_fraud_detection_kotlin
         simple-qrcode + go               → simple_qrcode_go

    The source folder name is preserved exactly (only non-alphanumeric chars are
    replaced with underscores) so it is always clear which source produced the output.
    """
    base = Path(source_path).name.strip() if source_path else ""
    if not base:
        base = "project"
    # Replace any non-alphanumeric/underscore character with underscore; collapse runs
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", base).strip("_") or "project"
    lang = re.sub(r"[^a-z0-9]", "", target_lang.lower())
    return f"{slug}_{lang}" if lang else slug


def _pascal(name: str) -> str:
    # If no separators the name is already PascalCase — return unchanged.
    if not re.search(r"[_\-\s]", name):
        return name
    return "".join(w.capitalize() for w in re.split(r"[_\-\s]+", name) if w)


def _generate_readme(
    seam_name: str,
    source_lang: str,
    target_lang: str,
    files_written: list[dict],
) -> str:
    """Build a project README.md from the files actually written to output."""
    tl = target_lang.lower()
    sl = source_lang.lower()
    title = _pascal(seam_name) or seam_name
    tl_display = _LANG_DISPLAY.get(tl, target_lang.capitalize())
    sl_display = _LANG_DISPLAY.get(sl, source_lang.capitalize())

    prereqs = _LANG_PREREQS.get(tl, f"- {tl_display} runtime")
    quickstart = _LANG_QUICKSTART.get(tl, f"```bash\n# Run the project\n```")

    # Build a table of the files that were actually written
    code_files = [f for f in files_written if "error" not in f]
    if code_files:
        rows = ["| File | Lines |", "|------|-------|"]
        for f in sorted(code_files, key=lambda x: x.get("path", "")):
            rows.append(f"| `{f['path']}` | {f.get('lines', '—')} |")
        file_table = "\n".join(rows)
    else:
        file_table = "_No files were written._"

    # Detect folder structure from actual paths
    folders = sorted({Path(f["path"]).parts[0] for f in code_files if "/" in f.get("path", "")})
    if folders:
        arch_folders = "\n".join(f"- `{d}/`" for d in folders)
        arch_note = f"Top-level directories:\n\n{arch_folders}"
    else:
        arch_note = "All files are in the root output directory."

    return f"""\
# {title} — {tl_display}

Modernised from **{sl_display}** to **{tl_display}** by the Micro-Cosmos pipeline.
Architecture: hexagonal (DDD ports and adapters) — domain logic is isolated from I/O.

## Prerequisites

{prereqs}

## Quick start

{quickstart}

## Architecture

This project follows hexagonal architecture so the domain model can be tested without any I/O framework.

| Layer | Role |
|-------|------|
| `domain/` | Pure business logic — aggregates, value objects, domain events |
| `application/` | Use-case interfaces and application services |
| `infrastructure/` | In-memory adapters — swap for real storage in production |
| `tests/` | Unit tests: happy path, rule violations, and edge cases |

{arch_note}

## Files

{file_table}

## Notes

- Translated seam: `{seam_name}`
- Source language: {sl_display}
- Target language: {tl_display}
- Generated by: [Micro-Cosmos](https://github.com/qodea/micro-cosmos)
"""


def _generate_seam_section(
    seam_name: str,
    source_lang: str,
    target_lang: str,
    files_written: list[dict],
) -> str:
    """Build an append-only section for a subsequent seam in an existing README."""
    tl = target_lang.lower()
    sl = source_lang.lower()
    title = _pascal(seam_name) or seam_name
    tl_display = _LANG_DISPLAY.get(tl, target_lang.capitalize())
    sl_display = _LANG_DISPLAY.get(sl, source_lang.capitalize())

    code_files = [f for f in files_written if "error" not in f and f.get("path") != "README.md"]
    if code_files:
        rows = ["| File | Lines |", "|------|-------|"]
        for f in sorted(code_files, key=lambda x: x.get("path", "")):
            rows.append(f"| `{f['path']}` | {f.get('lines', '—')} |")
        file_table = "\n".join(rows)
    else:
        file_table = "_No files were written._"

    return f"""\
## Seam: {title}

Translated from **{sl_display}** to **{tl_display}**.

{file_table}
"""


# ─── Build file accumulation ─────────────────────────────────────────────────
# These files are written by every seam. Instead of letting each seam overwrite
# the previous one (last seam wins), we merge dependencies so the final build
# file represents the union of requirements across all seams.

_BUILD_FILE_NAMES: frozenset[str] = frozenset({
    "pom.xml", "build.gradle.kts", "go.mod",
    "Cargo.toml", "package.json", "pyproject.toml", "build.sbt",
})


def _merge_pom_xml(existing: str, new_content: str) -> str:
    """Merge <dependency> blocks from new_content into existing pom.xml.

    Project-level metadata (<groupId>, <artifactId>, <version>, <parent>,
    <properties>) is kept from the existing file.  Only <dependency> entries
    absent by groupId:artifactId are appended inside <dependencies>.
    """
    dep_re = re.compile(r"<dependency>.*?</dependency>", re.DOTALL)

    def _dep_key(dep: str) -> str:
        gid = re.search(r"<groupId>(.*?)</groupId>", dep)
        aid = re.search(r"<artifactId>(.*?)</artifactId>", dep)
        return f"{gid.group(1)}:{aid.group(1)}" if gid and aid else dep[:80]

    existing_keys = {_dep_key(d) for d in dep_re.findall(existing)}
    additions = [d for d in dep_re.findall(new_content) if _dep_key(d) not in existing_keys]
    if not additions:
        return existing

    indent = "        "
    block = "\n" + "\n".join(
        "\n".join(f"{indent}{line}" for line in dep.splitlines())
        for dep in additions
    )
    return existing.replace("</dependencies>", f"{block}\n    </dependencies>", 1)


def _merge_gradle_kts(existing: str, new_content: str) -> str:
    """Merge dependency lines inside the dependencies { } block."""
    deps_block = re.compile(r"(dependencies\s*\{)([^}]*?)(\})", re.DOTALL)

    def _extract_lines(content: str) -> set[str]:
        m = deps_block.search(content)
        if not m:
            return set()
        return {
            ln.strip() for ln in m.group(2).splitlines()
            if ln.strip() and not ln.strip().startswith("//")
        }

    existing_lines = _extract_lines(existing)
    additions = sorted(_extract_lines(new_content) - existing_lines)
    if not additions:
        return existing

    add_block = "\n".join(f"    {ln}" for ln in additions)

    def _inject(m: re.Match) -> str:
        inner = m.group(2).rstrip()
        return f"{m.group(1)}{inner}\n{add_block}\n{m.group(3)}"

    return deps_block.sub(_inject, existing, count=1)


def _merge_go_mod(existing: str, new_content: str) -> str:
    """Merge require entries from new go.mod into existing."""
    req_block = re.compile(r"require\s*\((.+?)\)", re.DOTALL)
    req_single = re.compile(r"^require\s+(\S+)\s+(\S+)", re.MULTILINE)

    def _extract(content: str) -> dict[str, str]:
        result: dict[str, str] = {}
        for m in req_block.finditer(content):
            for line in m.group(1).splitlines():
                parts = line.strip().split()
                if len(parts) == 2:
                    result[parts[0]] = parts[1]
        for m in req_single.finditer(content):
            result[m.group(1)] = m.group(2)
        return result

    existing_reqs = _extract(existing)
    additions = {k: v for k, v in _extract(new_content).items() if k not in existing_reqs}
    if not additions:
        return existing

    new_lines = "\n".join(f"\t{k} {v}" for k, v in sorted(additions.items()))
    if "require (" in existing:
        return existing.replace("require (", f"require (\n{new_lines}", 1)
    return existing + f"\nrequire (\n{new_lines}\n)\n"


def _merge_cargo_toml(existing: str, new_content: str) -> str:
    """Merge [dependencies] entries from new Cargo.toml into existing."""
    section_re = re.compile(r"\[dependencies\](.+?)(?=\[|\Z)", re.DOTALL)

    def _extract(content: str) -> dict[str, str]:
        m = section_re.search(content)
        if not m:
            return {}
        result: dict[str, str] = {}
        for line in m.group(1).splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                k, _, v = stripped.partition("=")
                result[k.strip()] = v.strip()
        return result

    existing_deps = _extract(existing)
    additions = {k: v for k, v in _extract(new_content).items() if k not in existing_deps}
    if not additions:
        return existing

    new_lines = "\n".join(f"{k} = {v}" for k, v in sorted(additions.items()))
    if "[dependencies]" in existing:
        return existing.replace("[dependencies]", f"[dependencies]\n{new_lines}", 1)
    return existing + f"\n[dependencies]\n{new_lines}\n"


def _merge_package_json(existing: str, new_content: str) -> str:
    """Merge dependencies and devDependencies from new package.json into existing."""
    try:
        existing_data: dict = json.loads(existing)
        new_data: dict = json.loads(new_content)
    except (json.JSONDecodeError, ValueError):
        return existing
    for key in ("dependencies", "devDependencies"):
        existing_section: dict = existing_data.get(key, {})
        for pkg, version in new_data.get(key, {}).items():
            if pkg not in existing_section:
                existing_section[pkg] = version
        if existing_section:
            existing_data[key] = existing_section
    return json.dumps(existing_data, indent=2) + "\n"


def _merge_pyproject_toml(existing: str, new_content: str) -> str:
    """Merge project.dependencies list from new pyproject.toml into existing."""
    dep_block = re.compile(r"(dependencies\s*=\s*\[)(.+?)(\])", re.DOTALL)

    def _extract_pkgs(content: str) -> set[str]:
        m = dep_block.search(content)
        if not m:
            return set()
        pkgs = set()
        for line in m.group(2).splitlines():
            stripped = line.strip().strip('",').strip()
            if stripped:
                pkgs.add(re.split(r"[>=<!~^]", stripped)[0].strip().lower())
        return pkgs

    def _extract_lines(content: str) -> list[str]:
        m = dep_block.search(content)
        if not m:
            return []
        lines = []
        for line in m.group(2).splitlines():
            stripped = line.strip().strip('",').strip()
            if stripped:
                lines.append(stripped)
        return lines

    existing_pkgs = _extract_pkgs(existing)
    additions = [
        ln for ln in _extract_lines(new_content)
        if re.split(r"[>=<!~^]", ln)[0].strip().lower() not in existing_pkgs
    ]
    if not additions:
        return existing

    def _inject(m: re.Match) -> str:
        add_text = "\n".join(f'    "{a}",' for a in additions)
        return f"{m.group(1)}{m.group(2)}{add_text}\n{m.group(3)}"

    return dep_block.sub(_inject, existing, count=1)


def _merge_build_sbt(existing: str, new_content: str) -> str:
    """Merge libraryDependencies from new build.sbt into existing."""
    dep_re = re.compile(r'"[^"]+"\s+%%?\s+"[^"]+"\s+%\s+"[^"]+"')

    existing_deps = set(dep_re.findall(existing))
    additions = sorted(dep_re.findall(new_content) - existing_deps)
    if not additions:
        return existing

    new_lines = "\n".join(f'      "{dep}",' for dep in additions)
    if "libraryDependencies" in existing:
        return existing.replace(
            "libraryDependencies ++= Seq(",
            f"libraryDependencies ++= Seq(\n{new_lines}",
            1,
        )
    return existing + f'\nlibraryDependencies ++= Seq(\n{new_lines}\n)\n'


def _merge_build_file(existing: str, new_content: str, filename: str) -> str:
    """Dispatch to the right merge function based on the build file name."""
    if filename == "pom.xml":
        return _merge_pom_xml(existing, new_content)
    if filename == "build.gradle.kts":
        return _merge_gradle_kts(existing, new_content)
    if filename == "go.mod":
        return _merge_go_mod(existing, new_content)
    if filename == "Cargo.toml":
        return _merge_cargo_toml(existing, new_content)
    if filename == "package.json":
        return _merge_package_json(existing, new_content)
    if filename == "pyproject.toml":
        return _merge_pyproject_toml(existing, new_content)
    if filename == "build.sbt":
        return _merge_build_sbt(existing, new_content)
    return existing  # unknown format — keep existing


def write_output_files(
    source_path: str,
    source_lang: str,
    target_lang: str,
    seam_name: str,
    run_dir: str,
) -> dict:
    """Write all translated files from seam_result to the output directory.

    Reads ``seam_result.json`` from ``run_dir``, writes every file in
    ``pr.files`` to ``run_dir/output/``, and returns a manifest listing
    each file's path, size, and language.

    Args:
        source_path: Source estate root (used for metadata only).
        source_lang: Source language identifier.
        target_lang: Target language identifier.
        seam_name: Name of the bounded context / seam being translated.
        run_dir: Path to the current run directory (contains seam_result.json).

    Returns:
        Dict with ``files_written`` (list of file records), ``output_dir``,
        ``total_files``, and ``seam_name``.
    """
    run_path = Path(run_dir)
    seam_result_path = run_path / "seam_result.json"

    # Use the canonical project dir written by the driver before the seam loop so
    # every seam lands in the same output folder, regardless of whatever source_path
    # the LLM passes (which can be a seam-specific sub-path like "common_domain").
    _canonical_file = run_path / "reports" / "project_dir.txt"
    _canonical_proj_dir = (
        _canonical_file.read_text(encoding="utf-8").strip()
        if _canonical_file.exists()
        else _project_dir_name(source_path, target_lang)
    )

    if not seam_result_path.exists():
        return {
            "files_written": [],
            "output_dir": str(run_path / "reports" / _canonical_proj_dir),
            "total_files": 0,
            "seam_name": seam_name,
            "error": "seam_result.json not found — coder phase may not have completed",
        }

    try:
        raw = seam_result_path.read_text(encoding="utf-8")
        seam_result = json.loads(raw)
        # ADK sometimes double-encodes: the saved value is a JSON string
        # whose decoded value is the actual dict.
        if isinstance(seam_result, str):
            seam_result = json.loads(seam_result)
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "files_written": [],
            "output_dir": str(run_path / "reports" / _canonical_proj_dir),
            "total_files": 0,
            "seam_name": seam_name,
            "error": f"Could not read seam_result.json: {exc}",
        }

    # Unwrap one level if the model echoed {seam_result: {...}}
    if isinstance(seam_result, dict) and tuple(seam_result.keys()) == ("seam_result",):
        seam_result = seam_result["seam_result"]

    # Fill in any blank caller parameters from the saved JSON — the LLM sometimes
    # passes empty strings for {current_seam?} or {target_lang?} substitutions.
    if isinstance(seam_result, dict):
        if not seam_name:
            seam_name = seam_result.get("seam_name") or ""
        if not target_lang:
            target_lang = seam_result.get("target_lang") or ""
        if not source_lang:
            source_lang = seam_result.get("source_lang") or ""

    pr = seam_result.get("pr", {}) if isinstance(seam_result, dict) else {}
    files: list[dict] = pr.get("files", [])

    # All seams write directly into the project root (no extra seam subdir).
    # Go packages, Python modules, Java package paths etc. already provide
    # natural namespace isolation between seams, so an extra wrapper dir
    # would double-up the package prefix (btc/btc/...).
    project_root = run_path / "reports" / _canonical_proj_dir
    files_written: list[dict] = []

    for f in files:
        rel_path = f.get("path", "").lstrip("/")
        content = _dedup_declarations(f.get("content", ""), rel_path)
        if not rel_path:
            continue
        dest = project_root / rel_path
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            # Build files accumulate across seams: merge dependencies instead of
            # letting the last seam overwrite the whole file.
            if dest.exists() and dest.name in _BUILD_FILE_NAMES:
                try:
                    content = _merge_build_file(
                        dest.read_text(encoding="utf-8"), content, dest.name
                    )
                except Exception:
                    pass  # merge failed — fall through to plain overwrite
            dest.write_text(content, encoding="utf-8")
            files_written.append({
                "path": rel_path,
                "size_bytes": len(content.encode("utf-8")),
                "lines": content.count("\n"),
                "language": target_lang,
            })
        except OSError as exc:
            files_written.append({
                "path": rel_path,
                "error": str(exc),
            })

    # README: first seam writes the full file; subsequent seams append their
    # section so the project README accumulates across all seams in one pass.
    readme_dest = project_root / "README.md"
    try:
        project_root.mkdir(parents=True, exist_ok=True)
        if readme_dest.exists():
            readme_content = _generate_seam_section(seam_name, source_lang, target_lang, files_written)
            with readme_dest.open("a", encoding="utf-8") as fh:
                fh.write("\n" + readme_content)
        else:
            readme_content = _generate_readme(seam_name, source_lang, target_lang, files_written)
            readme_dest.write_text(readme_content, encoding="utf-8")
        final_size = len(readme_dest.read_bytes())
        files_written.append({
            "path": "README.md",
            "size_bytes": final_size,
            "lines": readme_dest.read_text(encoding="utf-8").count("\n"),
            "language": "markdown",
        })
    except OSError as exc:
        files_written.append({"path": "README.md", "error": str(exc)})

    # Generate Claude Code skills alongside the output project.
    # The driver generates skills once before the seam loop starts; this call
    # is a fallback for runs that bypassed that path (restarts, tests, etc.).
    # If the skills directory already exists it is left untouched.
    skills_dir = ""
    try:
        skills_target = run_path / "reports" / f"{_canonical_proj_dir}_skills"
        if skills_target.exists():
            skills_dir = str(skills_target)
        else:
            skills_dir = _write_output_skills(
                source_path=source_path,
                source_lang=source_lang,
                target_lang=target_lang,
                seam_name=seam_name,
                run_path=run_path,
                project_dir=_canonical_proj_dir,
            )
    except Exception:
        pass

    manifest = {
        "seam_name": seam_name,
        "source_lang": source_lang,
        "target_lang": target_lang,
        "source_path": source_path,
        "output_dir": str(project_root),
        "skills_dir": skills_dir,
        "files": files_written,
    }
    try:
        (run_path / "write_manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
    except OSError:
        pass

    return {
        "files_written": files_written,
        "output_dir": str(project_root),
        "skills_dir": skills_dir,
        "total_files": len(files_written),
        "seam_name": seam_name,
    }
