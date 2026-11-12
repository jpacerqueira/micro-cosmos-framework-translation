# Design — Micro-Cosmos Code Reviewer Power

## Architecture

Steering-only Kiro.dev Power (no mcpServers). All guidance is embedded in `POWER.md` and delivered as steering instructions to Kiro's LLM context.

## Data Models

### Review Context
When run inside an Micro-Cosmos LLM pipeline, the following data is available:
```
{
  "source_seam_files": ["src/main/java/.../FraudScoringService.java"],
  "translated_files": ["src/main/kotlin/.../FraudScoringService.kt"],
  "seam_id": "fraud-scoring",
  "source_language": "java",
  "target_language": "kotlin",
  "bounded_context_map": {"contexts": [...]},
  "architect_output": {"seams": [...]}
}
```

When run in deterministic mode, only source path, source language, and target language are available. The reviewer applies structural heuristics (file path conventions, keyword presence for decimal types, OTel imports) without LLM-driven fidelity checking.

### Review Finding
```
{ "severity": "BLOCKER|MAJOR|MINOR|NIT", "file": "...", "symbol": "...", "issue": "..." }
```

### Gate 5 Verdict
```
{
  "verdict": "PASS|WARN|FAIL",
  "passed": true|false,
  "findings": [...],
  "metrics": {
    "files_reviewed": N,
    "todo_density_pct": N,
    "port_interfaces_present": N,
    "port_interfaces_missing": N
  },
  "summary": "..."
}
```

## Testing Strategy

### Property 1: Frontmatter Schema Completeness
Every valid frontmatter object must have non-empty `name`, `description` (≥10 chars), and at least one keyword. Fast-check generates 100 arbitrary records and asserts the schema invariants.

### Property 2: Keyword Category Coverage
A valid keyword set must cover: review category (code-review/review/adversarial), Micro-Cosmos category (micro_cosmos/beyond), severity category (blocker/major/minor), and quality category (tdd/decimal/hexagonal). Fast-check generates 100 keyword tuples.

## Key Design Decisions

- **Adversarial stance**: reviewer is intentionally skeptical — every code path is suspect until proven correct by explicit guard or test assertion.
- **LLM mode context**: reads source seam files + translated files + seam report for full fidelity check. Richer Micro-Cosmos pipeline output means more precise findings.
- **Deterministic mode context**: applies structural heuristics on generated files using only source path, source language, and target language. Cannot verify business logic fidelity, but can check file paths, OTel imports, and decimal type usage.
- **7-category checklist**: covers all Gate 5 acceptance criteria in a single structured pass, so the reviewer's output maps directly to the Gate 5 PR checklist.
- **BLOCKER escalation**: any BLOCKER finding triggers Gate 5 FAIL, forcing a TDD loop re-run before merge.
