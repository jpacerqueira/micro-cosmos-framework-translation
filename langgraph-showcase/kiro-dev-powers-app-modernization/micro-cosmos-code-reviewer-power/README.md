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
