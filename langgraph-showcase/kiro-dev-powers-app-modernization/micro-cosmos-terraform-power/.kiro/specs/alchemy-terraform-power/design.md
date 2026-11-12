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
