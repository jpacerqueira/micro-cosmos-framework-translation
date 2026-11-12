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
A valid keyword set must cover: code-generation category (code-writer/translation/seam), Micro-Cosmos category (micro_cosmos/beyond), architecture category (hexagonal/ddd), and quality category (tdd/otel/bigdecimal). Fast-check generates 100 keyword tuples.

## Key Design Decisions

- **Steering-only**: No mcpServers — power guidance is embedded in POWER.md context delivered to Kiro's LLM.
- **Seam-by-seam approach**: Each bounded context is translated independently with its own TDD loop, so failures are isolated.
- **LLM mode context**: Reads seam reports from `reports/seam_report.json` and bounded context map from Cartographer. The richer the upstream pipeline output, the more targeted the code-writer guidance.
- **Deterministic mode context**: Only source path, source language, and target language are known. Power emits general hexagonal + TDD guidance for the target language pair.
- **BigDecimal enforcement**: BLOCKER for any monetary value using float/double — this maps directly to the Skeptical Review BLOCKER criteria.
- **InMemorySpanExporter pattern**: Included for all target stacks so OTel coverage can be asserted in the TDD test suite without a live collector.
