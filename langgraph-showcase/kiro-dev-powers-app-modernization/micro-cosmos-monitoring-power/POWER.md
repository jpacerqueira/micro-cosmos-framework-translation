---
name: "micro-cosmos-monitoring"
displayName: "Micro-Cosmos Monitoring"
author: "Micro-Cosmos"
description: "Use when scoring legacy application monitoring maturity, identifying telemetry gaps, or generating OpenTelemetry instrumentation for Java, C#, and Node.js/TypeScript in Micro-Cosmos-translated microservices."
keywords: ["monitoring", "observability", "opentelemetry", "otel", "telemetry", "logging", "metrics", "tracing", "health", "gap-analysis", "java", "csharp", "typescript", "nodejs", "micro-cosmos", "legacy", "instrumentation"]
---

# Micro-Cosmos Monitoring Power

Legacy monitoring scoring and OpenTelemetry adoption guide for Micro-Cosmos translated microservices. Diagnoses monitoring gaps in source code, scores observability maturity per dimension, and generates production-ready OTel instrumentation for Java, C#, and Node.js/TypeScript.

## Response Contract

Every monitoring review or instrumentation generation must include:

1. **Monitoring maturity score (0–100)** — aggregate across five dimensions: Logging, Metrics, Tracing, Health, Alerting.
2. **Per-dimension score** — each dimension scored 0–20 with rationale.
3. **Gap findings** — every missing dimension is a gap finding with severity.
4. **Instrumentation plan** — specific OTel SDK calls and configuration for the target language.
5. **Test coverage note** — whether OTel spans can be asserted in unit tests.

## Monitoring Maturity Scoring

### Dimensions (each 0–20 points)

| Dimension | 20 pts (covered) | 10 pts (partial) | 0 pts (absent) |
|---|---|---|---|
| **Logging** | Structured logs with trace-context injection (SLF4J MDC / Serilog context / pino fields) | Unstructured logging framework present (log4j, NLog, winston) | No logging at all |
| **Metrics** | Micrometer / App.Metrics / prom-client / OpenTelemetry Metrics with OTLP or Prometheus exporter | Ad-hoc counters or custom metrics | No metrics |
| **Tracing** | OpenTelemetry traces (JVM: GlobalOpenTelemetry · .NET: ActivitySource · Node.js: @opentelemetry/api) with span hierarchy and W3C traceparent propagation | Manual correlation IDs only | No distributed tracing |
| **Health** | Actuator `/health` or custom `/healthz` + readiness/liveness probes | Basic `/ping` endpoint | No health endpoint |
| **Alerting** | Alert rules defined (PagerDuty / CloudWatch / AlertManager / OpsGenie config present) | Log-based alerts only | No alerting |

**Score interpretation:**
- 80–100: Production-ready observability
- 60–79: Adequate — gaps should be addressed before GA
- 40–59: Basic — tracing and structured logging missing; high-risk for distributed systems
- 20–39: Insufficient — only partial logging; microservice deployment is HIGH risk
- 0–19: None — **BLOCKER for microservice deployment**

## Diagnose Before You Instrument

| Gap category | Symptoms | Action |
|---|---|---|
| **No structured logging** | Raw `System.out.println`, `console.log`, `print()` with no framework | Add SLF4J + Logback (Java), Serilog (C#), pino/winston (TS) |
| **No trace-context in logs** | Log statements without trace-id or correlation-id fields | Inject OTel trace context into MDC / log properties |
| **No metrics** | No Micrometer, Prometheus, prom-client, or OTel Metrics | Add `MeterProvider` with OTLP or Prometheus exporter |
| **No distributed tracing** | No Span creation, no W3C TraceContext header propagation | Add OTel SDK with OTLP exporter and `@WithSpan` / manual spans |
| **No health endpoint** | No `/health`, `/healthz`, `/actuator/health` | Add readiness + liveness probe endpoint |
| **Trace-id not propagated** | Service calls do not forward `traceparent` header | Add OTel `W3CTraceContextPropagator` to HTTP client |
| **OTel not in tests** | No `InMemorySpanExporter` or span assertion in test suite | Add OTel test SDK and assert span names/attributes |

## OpenTelemetry Instrumentation — Java

```java
// build.gradle.kts (add)
implementation("io.opentelemetry:opentelemetry-api:1.37.0")
implementation("io.opentelemetry:opentelemetry-sdk:1.37.0")
implementation("io.opentelemetry:opentelemetry-exporter-otlp:1.37.0")
implementation("io.opentelemetry.instrumentation:opentelemetry-spring-boot-starter:2.3.0")

// Application service — manual span (when @WithSpan annotation is unavailable)
import io.opentelemetry.api.GlobalOpenTelemetry;
import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.StatusCode;
import io.opentelemetry.api.trace.Tracer;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;

public class FraudScoringService {
    private static final Logger log = LoggerFactory.getLogger(FraudScoringService.class);
    private static final Tracer tracer = GlobalOpenTelemetry.getTracer("micro_cosmos.fraud-scoring");

    public ScoringResult score(Transaction tx) {
        Span span = tracer.spanBuilder("FraudScoringService.score")
            .setAttribute("transaction.id", tx.getId().toString())
            .startSpan();
        try (var scope = span.makeCurrent()) {
            MDC.put("trace_id", span.getSpanContext().getTraceId());
            log.info("Scoring transaction id={} amount={}", tx.getId(), tx.getAmount());
            ScoringResult result = performScoring(tx);
            log.info("Score computed result={}", result.getRisk());
            return result;
        } catch (Exception e) {
            span.setStatus(StatusCode.ERROR, e.getMessage());
            span.recordException(e);
            log.error("Scoring failed transaction.id={}", tx.getId(), e);
            throw e;
        } finally {
            MDC.remove("trace_id");
            span.end();
        }
    }
}

// Test with InMemorySpanExporter
import io.opentelemetry.sdk.testing.exporter.InMemorySpanExporter;
import io.opentelemetry.sdk.trace.SdkTracerProvider;
import io.opentelemetry.sdk.trace.export.SimpleSpanProcessor;

@Test void score_emits_span() {
    var exporter = InMemorySpanExporter.create();
    var provider = SdkTracerProvider.builder()
        .addSpanProcessor(SimpleSpanProcessor.create(exporter))
        .build();
    OpenTelemetrySdk.builder().setTracerProvider(provider).buildAndRegisterGlobal();

    service.score(validTransaction());

    var spans = exporter.getFinishedSpanItems();
    assertThat(spans).hasSize(1);
    assertThat(spans.get(0).getName()).isEqualTo("FraudScoringService.score");
}
```

## OpenTelemetry Instrumentation — C#

```csharp
// .csproj (add)
// <PackageReference Include="OpenTelemetry.Api" Version="1.8.*" />
// <PackageReference Include="OpenTelemetry.Sdk" Version="1.8.*" />
// <PackageReference Include="OpenTelemetry.Exporter.OpenTelemetryProtocol" Version="1.8.*" />
// <PackageReference Include="OpenTelemetry.Extensions.Hosting" Version="1.8.*" />

// Activity source (one per assembly)
public static class Telemetry {
    public static readonly ActivitySource Source = new("MicroCosmos.FraudScoring", "1.0.0");
}

// Application service
public class FraudScoringService {
    private readonly ILogger<FraudScoringService> _logger;

    public FraudScoringService(ILogger<FraudScoringService> logger) => _logger = logger;

    public ScoringResult Score(Transaction tx) {
        using var activity = Telemetry.Source.StartActivity("FraudScoringService.Score");
        activity?.SetTag("transaction.id", tx.Id.ToString());
        _logger.LogInformation("Scoring transaction id={TransactionId} amount={Amount}",
            tx.Id, tx.Amount);
        try {
            var result = PerformScoring(tx);
            _logger.LogInformation("Score computed result={Risk}", result.Risk);
            return result;
        } catch (Exception ex) {
            activity?.SetStatus(ActivityStatusCode.Error, ex.Message);
            activity?.RecordException(ex);
            _logger.LogError(ex, "Scoring failed transaction.id={TransactionId}", tx.Id);
            throw;
        }
    }
}

// Test with ActivityListener
[Fact] public void Score_EmitsActivity() {
    var activities = new List<Activity>();
    using var listener = new ActivityListener {
        ShouldListenTo = s => s.Name == "MicroCosmos.FraudScoring",
        Sample = (ref ActivityCreationOptions<ActivityContext> _) => ActivitySamplingResult.AllData,
        ActivityStopped = activities.Add,
    };
    ActivitySource.AddActivityListener(listener);

    _service.Score(ValidTransaction());

    Assert.Single(activities);
    Assert.Equal("FraudScoringService.Score", activities[0].DisplayName);
}
```

## OpenTelemetry Instrumentation — Node.js / TypeScript

```typescript
// package.json (add)
// "@opentelemetry/api": "^1.8",
// "@opentelemetry/sdk-node": "^0.51",
// "@opentelemetry/exporter-trace-otlp-http": "^0.51",
// "@opentelemetry/instrumentation-http": "^0.51"

// tracing.ts — initialise once at startup
import { NodeSDK } from '@opentelemetry/sdk-node';
import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http';

const sdk = new NodeSDK({
  traceExporter: new OTLPTraceExporter({ url: process.env.OTEL_EXPORTER_OTLP_ENDPOINT }),
  serviceName: 'micro-cosmos-fraud-scoring',
});
sdk.start();

// Application service
import { trace, SpanStatusCode } from '@opentelemetry/api';
import pino from 'pino';

const tracer = trace.getTracer('micro_cosmos.fraud-scoring', '1.0.0');
const log = pino();

export class FraudScoringService {
  score(tx: Transaction): ScoringResult {
    return tracer.startActiveSpan('FraudScoringService.score', span => {
      span.setAttribute('transaction.id', tx.id);
      const traceId = trace.getActiveSpan()?.spanContext().traceId ?? 'unknown';
      log.info({ traceId, transactionId: tx.id, amount: tx.amount }, 'Scoring transaction');
      try {
        const result = this.performScoring(tx);
        log.info({ traceId, risk: result.risk }, 'Score computed');
        return result;
      } catch (err) {
        span.setStatus({ code: SpanStatusCode.ERROR, message: String(err) });
        span.recordException(err as Error);
        log.error({ traceId, err }, 'Scoring failed');
        throw err;
      } finally {
        span.end();
      }
    });
  }
}

// Test with InMemorySpanExporter
import { InMemorySpanExporter, SimpleSpanProcessor } from '@opentelemetry/sdk-trace-base';
import { NodeTracerProvider } from '@opentelemetry/sdk-trace-node';

test('score emits a span', () => {
  const exporter = new InMemorySpanExporter();
  const provider = new NodeTracerProvider();
  provider.addSpanProcessor(new SimpleSpanProcessor(exporter));
  provider.register();

  service.score(validTransaction());

  const spans = exporter.getFinishedSpans();
  expect(spans).toHaveLength(1);
  expect(spans[0].name).toBe('FraudScoringService.score');
});
```

## OpenTelemetry Instrumentation — Scala

```scala
// build.sbt (add)
libraryDependencies += "io.opentelemetry" % "opentelemetry-api" % "1.37.0"
libraryDependencies += "io.opentelemetry" % "opentelemetry-sdk" % "1.37.0"

// Application service
import io.opentelemetry.api.GlobalOpenTelemetry
import io.opentelemetry.api.trace.StatusCode
import org.slf4j.{LoggerFactory, MDC}

class FraudScoringService {
  private val log = LoggerFactory.getLogger(getClass)
  private val tracer = GlobalOpenTelemetry.getTracer("micro_cosmos.fraud-scoring")

  def score(tx: Transaction): ScoringResult = {
    val span = tracer.spanBuilder("FraudScoringService.score")
      .setAttribute("transaction.id", tx.id.toString)
      .startSpan()
    val scope = span.makeCurrent()
    MDC.put("trace_id", span.getSpanContext.getTraceId)
    try {
      log.info(s"Scoring transaction id=${tx.id}")
      val result = performScoring(tx)
      log.info(s"Score computed risk=${result.risk}")
      result
    } catch {
      case e: Exception =>
        span.setStatus(StatusCode.ERROR, e.getMessage)
        span.recordException(e)
        log.error(s"Scoring failed transaction.id=${tx.id}", e)
        throw e
    } finally {
      MDC.remove("trace_id")
      scope.close()
      span.end()
    }
  }
}

// Test with InMemorySpanExporter (same as Java)
```

## OpenTelemetry Instrumentation — F#

```fsharp
// .fsproj (add)
// <PackageReference Include="OpenTelemetry.Api" Version="1.8.*" />

// Telemetry module
module Telemetry =
    let source = new ActivitySource("MicroCosmos.FraudScoring", "1.0.0")

// Application service
open System.Diagnostics
open Microsoft.Extensions.Logging

let score (logger: ILogger) (tx: Transaction) =
    use activity = Telemetry.source.StartActivity("FraudScoringService.score")
    activity |> Option.ofObj |> Option.iter (fun a -> a.SetTag("transaction.id", string tx.Id) |> ignore)
    logger.LogInformation("Scoring transaction id={TransactionId}", tx.Id)
    try
        let result = performScoring tx
        logger.LogInformation("Score computed risk={Risk}", result.Risk)
        result
    with ex ->
        activity |> Option.ofObj |> Option.iter (fun a ->
            a.SetStatus(ActivityStatusCode.Error, ex.Message) |> ignore
            a.RecordException(ex) |> ignore)
        logger.LogError(ex, "Scoring failed transaction.id={TransactionId}", tx.Id)
        reraise()

// Test with ActivityListener (same as C#)
```

## OpenTelemetry Instrumentation — VB.NET

```vb
' .vbproj (add)
' <PackageReference Include="OpenTelemetry.Api" Version="1.8.*" />

' Telemetry module
Module TelemetryModule
    Public ReadOnly Source As New ActivitySource("MicroCosmos.FraudScoring", "1.0.0")
End Module

' Application service
Public Class FraudScoringService
    Private ReadOnly _logger As ILogger(Of FraudScoringService)

    Public Function Score(tx As Transaction) As ScoringResult
        Using activity = TelemetryModule.Source.StartActivity("FraudScoringService.Score")
            If activity IsNot Nothing Then activity.SetTag("transaction.id", tx.Id.ToString())
            _logger.LogInformation("Scoring transaction id={TransactionId}", tx.Id)
            Try
                Dim result = PerformScoring(tx)
                _logger.LogInformation("Score computed risk={Risk}", result.Risk)
                Return result
            Catch ex As Exception
                If activity IsNot Nothing Then
                    activity.SetStatus(ActivityStatusCode.Error, ex.Message)
                    activity.RecordException(ex)
                End If
                _logger.LogError(ex, "Scoring failed transaction.id={TransactionId}", tx.Id)
                Throw
            End Try
        End Using
    End Function
End Class

' Test with ActivityListener (same as C#)
```

## Common Workflows

### Score legacy application monitoring
1. Read all source files (use IR graph node summaries for scale)
2. Identify logging frameworks (imports: `import org.slf4j`, `using Serilog`, `require('pino')`)
3. Identify metrics (imports: `io.micrometer`, `Prometheus`, `prom-client`)
4. Identify tracing (imports: `opentelemetry`, `Sleuth`, `Jaeger`, `Zipkin`)
5. Identify health endpoints (route patterns: `/health`, `/healthz`, `/actuator`)
6. Identify alert configs (files: `alertmanager.yml`, `alerts.yaml`, CloudWatch JSON)
7. Score each dimension 0–20 and emit aggregate score with gap findings

### Generate OTel instrumentation for a translated service
1. Identify target language from seam report
2. Select correct SDK: Java (OTel Java Agent or manual SDK), C# (ActivitySource), TypeScript (OTel Node SDK)
3. Generate `tracing.ts` / `OpenTelemetryConfig.java` / `Telemetry.cs` bootstrap
4. Wrap every public service method with span + structured log + exception recording
5. Add `InMemorySpanExporter` test to verify span emission
6. Update build file with OTel dependencies
7. Emit Response Contract with maturity score delta (before vs after)

### Review translated code for OTel coverage
1. Read generated service files
2. Check each public service method for span creation
3. Check for trace-context injection in log statements
4. Check test files for `InMemorySpanExporter` or `ActivityListener` span assertions
5. Report MAJOR for any public service method without span coverage
6. Report MINOR for missing span assertions in tests
7. Emit Response Contract
