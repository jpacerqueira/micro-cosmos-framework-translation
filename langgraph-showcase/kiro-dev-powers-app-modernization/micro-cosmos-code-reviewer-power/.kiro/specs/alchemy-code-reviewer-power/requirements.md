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
