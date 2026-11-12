# Micro-Cosmos Monitoring Power

Kiro.dev Power for scoring legacy application monitoring maturity, identifying OpenTelemetry gaps, and generating OTel instrumentation for Java, C#, and Node.js/TypeScript microservices translated by Micro-Cosmos.

## What it does

- Scores legacy application monitoring across five dimensions: Logging, Metrics, Tracing, Health, Alerting (0–100)
- Identifies monitoring gaps with severity (BLOCKER for 0-score microservice deployments)
- Generates production-ready OpenTelemetry instrumentation for Java, C#, TypeScript
- Reviews translated service code for OTel span coverage
- Provides test patterns for asserting OTel span emission

## Installation in Kiro

Install this power from the Kiro.dev marketplace or copy the `POWER.md` file into your Kiro powers directory.

## When to activate

- You want to score the legacy application's monitoring maturity before migration
- You need to generate OTel instrumentation for a translated microservice
- You are reviewing translated code and want to check telemetry coverage
- You are planning the observability gap remediation roadmap

## Score interpretation

| Score | Status |
|---|---|
| 80–100 | Production-ready |
| 60–79 | Adequate — close gaps before GA |
| 40–59 | Basic — tracing and structured logging missing |
| 20–39 | Insufficient — HIGH risk for distributed systems |
| 0–19 | None — **BLOCKER** for microservice deployment |

## Tests

```bash
npm install
npm test
```
