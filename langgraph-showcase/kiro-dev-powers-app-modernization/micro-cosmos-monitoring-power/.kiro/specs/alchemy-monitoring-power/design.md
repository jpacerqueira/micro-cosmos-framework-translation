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
A valid keyword set must cover: observability category (monitoring/otel/telemetry), Micro-Cosmos category (micro_cosmos/beyond/legacy), language category (java/csharp/typescript/nodejs), signal category (logging/metrics/tracing/health). Fast-check generates 100 keyword tuples.

## Key Design Decisions

- **0–100 scale with five 20-pt dimensions**: balances simplicity (single number) with diagnostic value (per-dimension breakdown).
- **BLOCKER at 0–19**: a microservice with no observability cannot be safely deployed; the BLOCKER finding prevents Gate 5 approval for the infrastructure side.
- **Language-specific code snippets**: embedded directly in POWER.md rather than separate reference files, because Kiro context windows are large and retrieval latency matters more for instrumentation tasks.
- **InMemorySpanExporter test pattern**: included for all three languages so OTel coverage can be asserted in the existing TDD test suite without a live OTel collector.
