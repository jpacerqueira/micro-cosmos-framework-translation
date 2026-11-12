---
name: trivy-security-scanning
description: Trivy dual-scan architecture (source + output) and the per-language dependency-resolution gaps each ecosystem needs to actually get scanned
metadata:
  type: project
---

**Scope note — do not confuse with the deterministic regex scanner:**
this file is about Trivy's dependency-CVE scan only. Deterministic-mode
runs also produce a `security_report.json`, but via a completely separate
mechanism — `scan_source_for_security()` in `micro_cosmos/tools/security_tools.py`,
a hand-written regex pattern list (`_SECURITY_PATTERNS`), used as the
Deterministic-mode CVE placeholder since Trivy's source-side scan is
architecturally unreachable when `skip_llm=true` (the deterministic
branch in `pipeline.py::run_phase()` returns before the LLM-mode-only
Trivy-prescan trigger). It had the same category of per-language gap as
Trivy — Java/Spring/Python/JS-biased patterns that matched nothing on
real C# code — fixed 2026-07-10 by extending 5 patterns with ADO.NET/.NET
idioms (`SQL_CONCAT`, `WEAK_HASH_CRYPTO`, `MISSING_AUTH_ANNOTATION`,
`DEBUG_EXPOSURE`, `SSRF_CANDIDATE`); see `changes-log.md` and
`.claude/commands/debug-run.md` for the full writeup. If asked why a
Deterministic-mode run's security findings look thin, check which
scanner actually ran (`run_meta.json`'s `skip_llm` flag) before assuming
it's the same Trivy gap described below.

Two identical `trivy fs --scanners vuln,secret` invocations:
`micro_cosmos/tools/security_tools.py::run_trivy_scan()` (source scan, before
the Security phase) and `micro_cosmos/orchestration/pipeline.py::_run_trivy_output_scan()`
(output scan, after Gate 5). Both read `source_lang`/`target_lang` from
session state and call two best-effort helpers before scanning — neither
helper ever raises or blocks the scan; a failure just means Trivy scans
with whatever it can already see.

**Per-ecosystem gaps, confirmed via Trivy's own docs, not assumed:**

| Ecosystem | Works out of the box? | Fix |
|---|---|---|
| Java (Maven, `pom.xml`) | Mostly — Trivy reads it directly, no build step | **None implemented.** Gap is unresolved version properties/variables (`${spring.version}`) and needs internet access to Maven Central unless `--offline-scan`. No clean fix exists — `mvn help:effective-pom` writes a file Trivy never reads, and overwriting the real `pom.xml` is too invasive. Documented limitation, not a workaround. |
| Java/Kotlin (Gradle, `build.gradle`/`.kts`) | **No** — Trivy does not read Gradle build scripts at all, only `*.gradle.lockfile` | `_maybe_restore_jvm_lockfile()` force-enables Gradle dependency locking via an `--init-script` (`allprojects { dependencyLocking { lockAllConfigurations() } }`) so it never touches the project's own `build.gradle`, then runs `dependencies --write-locks`. Uses `./gradlew` if present, else the image's system `gradle`. |
| C# (`.csproj`) | **No** — needs `packages.lock.json`/`.deps.json` for transitive resolution; a bare `.csproj` gives Trivy almost nothing | `_maybe_restore_dotnet_lockfile()` runs `dotnet restore --use-lock-file`, which generates `packages.lock.json` without touching the `.csproj`. |

**The bug that would have silently broken this if not caught:**
`target_lang`/`source_lang` are NOT single canonical strings per language.
The web form's dropdown and `observer_tools.py`'s `_LANG_EXTENSIONS` use
`java`/`java8`/`java11`/`java21` as four separate values for the same
ecosystem (Kotlin has no version suffix: just `kotlin`). C#'s `csharp` has
no such variants, so `lang == "csharp"` is safe — but the equivalent
`lang == "java"` check would silently never fire for the two values an
actual user is most likely to pick (`java8`/`java21`) from the dropdown.
Fixed with a set: `_JVM_LANGS = {"java", "java8", "java11", "java21", "kotlin"}`.
**If a new JVM-ish target/source language value is ever added to the
dropdown or `_LANG_EXTENSIONS`, it must be added to `_JVM_LANGS` too, or
this whole fix silently stops working for it.**

**Dockerfile cost, cumulative and permanent:** each language's fix
requires real tooling in the `micro-cosmos-web` image, added regardless of
whether any given run ever uses that language — the .NET SDK (~200-300MB)
and a JDK + Gradle CLI (~another meaningful chunk) are now both always
present. There is no way to make this conditional per-run since one image
serves every run. If a future language gets the same treatment, expect the
same tradeoff each time.

**Not yet verified against a live Docker build** — verified via
`ast.parse()` and a standalone dry-run (stubbed `micro_cosmos.diagnostics`,
loaded `security_tools.py` directly via `importlib` to dodge the
`google-adk` import chain) confirming the language-matching logic and
graceful missing-binary handling, not a real build. If Trivy's output for
a Gradle or C# run still looks empty after this ships, check first whether
the Dockerfile actually built with the new tooling present
(`dotnet --version`, `gradle --version`, `java --version` inside the
container) before assuming the Python logic is wrong.
