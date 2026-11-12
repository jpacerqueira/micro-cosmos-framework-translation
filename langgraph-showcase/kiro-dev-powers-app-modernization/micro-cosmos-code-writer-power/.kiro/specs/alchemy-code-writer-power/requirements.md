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
