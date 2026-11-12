---
name: "micro-cosmos-code-writer"
displayName: "Micro-Cosmos Code Writer"
author: "Micro-Cosmos"
description: "Use when translating source seams to Kotlin following Micro-Cosmos hexagonal conventions. Enforces TDD, BigDecimal for monetary values, hexagonal layering, OTel instrumentation, and JVM source-root path conventions across the full seam-by-seam TDD loop."
keywords: ["code-writer", "translation", "seam", "hexagonal", "ddd", "tdd", "bigdecimal", "java", "kotlin", "java21", "micro-cosmos", "modernization", "ports-and-adapters", "clean-architecture", "otel", "opentelemetry"]
---

# Micro-Cosmos Code Writer Power

Seam-by-seam translation power for Micro-Cosmos. Translates Java seams to Kotlin following hexagonal (DDD ports and adapters) architecture, TDD, and OpenTelemetry instrumentation conventions.

## Response Contract

Every seam translation must include:

1. **Seam ID** — the bounded-context seam being translated.
2. **Implementation files** — full list of written files with paths relative to the project root.
3. **Test files** — at least one test file covering happy-path, rule-violation, and edge-case categories.
4. **README.md** — present and describing the module in business terms.

## Workflow

1. **Read source seam** — use `list_source_files` with the seam name, then `read_source_file` for every file returned. Understand aggregates, value objects, invariants, and business rules.
2. **Map domain concepts** — identify every business invariant. Each invariant MUST become an explicit guard in the output. No silent no-ops.
3. **Write implementation** — produce idiomatic Kotlin following hexagonal layers (see below). No TODOs, no stubs, no placeholder implementations.
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

Port interfaces follow the pattern `I{Aggregate}UseCase` / `I{Aggregate}Repository`.

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

public Result process(Input input) {
    Span span = tracer.spanBuilder("ServiceName.process")
        .setAttribute("input.id", input.getId().toString())
        .startSpan();
    try (var scope = span.makeCurrent()) {
        MDC.put("trace_id", span.getSpanContext().getTraceId());
        // business logic
    } catch (Exception e) {
        span.setStatus(StatusCode.ERROR, e.getMessage());
        span.recordException(e);
        throw e;
    } finally {
        MDC.remove("trace_id");
        span.end();
    }
}
```

**Node.js / TypeScript / JavaScript:**
```typescript
return tracer.startActiveSpan('ServiceName.process', span => {
    span.setAttribute('input.id', input.id);
    const traceId = trace.getActiveSpan()?.spanContext().traceId ?? 'unknown';
    try {
        // business logic
    } catch (err) {
        span.setStatus({ code: SpanStatusCode.ERROR, message: String(err) });
        span.recordException(err as Error);
        throw err;
    } finally { span.end(); }
});
```

**.NET (C# / F# / VB.NET):**
```csharp
using var activity = Telemetry.Source.StartActivity("ServiceName.Process");
activity?.SetTag("input.id", input.Id.ToString());
try {
    // business logic
} catch (Exception ex) {
    activity?.SetStatus(ActivityStatusCode.Error, ex.Message);
    activity?.RecordException(ex);
    throw;
}
```

## PR Gate Alignment (Gate 5)

- [ ] All domain rules from the source are present and explicitly enforced
- [ ] No TODOs, stubs, or placeholder comments in business logic
- [ ] `BigDecimal` used for all monetary values — never `float/double`
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
