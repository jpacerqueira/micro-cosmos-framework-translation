# Micro-Cosmos Code Writer Power

Kiro.dev Power for seam-by-seam Java → Kotlin translation following Micro-Cosmos hexagonal conventions.

## What it does

- Reads source seams and maps domain aggregates, value objects, and invariants
- Writes idiomatic Kotlin following hexagonal (domain/application/infrastructure) layering
- Enforces `BigDecimal` for all monetary values — never `float/double`
- Enforces JVM file-path conventions (src/main/<lang>/...)
- Adds OpenTelemetry spans to every public service method
- Generates unit tests covering happy-path, rule-violation, and edge-case categories
- Produces README.md per seam in business terms

## When to activate

- You are translating a seam from Java to Kotlin
- You are fixing a failing TDD review (BLOCKER or MAJOR findings)
- You need to add OTel instrumentation to a translated service
