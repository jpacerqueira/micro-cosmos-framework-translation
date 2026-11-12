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
