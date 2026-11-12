# Requirements — Micro-Cosmos Monitoring Power

## REQ-1: Monitoring Maturity Score
The power MUST compute a 0–100 monitoring maturity score by evaluating five dimensions: Logging (0–20), Metrics (0–20), Tracing (0–20), Health (0–20), Alerting (0–20). Each dimension MUST have a clear pass/partial/absent rubric.

## REQ-2: Legacy Application Scoring
The power MUST score the legacy source application by analysing imports, framework dependencies, endpoint patterns, and log statements present in the IR graph or source files.

## REQ-3: BLOCKER for Zero-Score Deployment
A legacy application with a total monitoring score of 0–19 MUST produce a BLOCKER finding that blocks microservice deployment until basic observability is added.

## REQ-4: Java OTel Instrumentation Generation
The power MUST generate complete Java OTel instrumentation: `Tracer` via `GlobalOpenTelemetry`, `Span` start/end in try-with-resources, MDC trace-id injection, `InMemorySpanExporter` test pattern. Dependencies for `build.gradle.kts` or `pom.xml` MUST be included.

## REQ-5: C# OTel Instrumentation Generation
The power MUST generate complete C# OTel instrumentation: `ActivitySource`, `Activity` with `StartActivity`, structured logging via `ILogger<T>`, `ActivityListener` test pattern. `<PackageReference>` entries MUST be included.

## REQ-6: TypeScript/Node.js OTel Instrumentation Generation
The power MUST generate complete TypeScript OTel instrumentation: `NodeSDK` bootstrap (`tracing.ts`), `trace.getTracer()` with `startActiveSpan`, pino structured logging with trace-id injection, `InMemorySpanExporter` vitest test. `package.json` dependencies MUST be included.

## REQ-7: Gap Findings with Severity
Every monitoring gap MUST be reported as a finding with severity BLOCKER (no monitoring in a microservice-deployed service), MAJOR (missing distributed tracing or structured logging), or MINOR (missing alert rules or health probe).

## REQ-8: Trace-Context Propagation
The power MUST check for W3C TraceContext header propagation in service-to-service HTTP calls and flag absence as MAJOR.

## REQ-9: OTel Coverage Review
The power MUST review translated service code for: span creation on every public service method, trace-id in log statements, and `InMemorySpanExporter` span assertions in tests.

## REQ-10: Per-Service Gap Table
For runs with multiple bounded contexts the power MUST produce a per-service monitoring gap table showing each context's score per dimension and overall status.
