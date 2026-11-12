---
name: can-coding-agent
description: >
  Apply this skill whenever you write, modify, or scaffold code in the CAN
  (Customer-Application-Name) repository. Triggers on any change inside
  01-terraform, 02-kubernetes-istio, 03-backend-springboot,
  04-database-postgres-citus, or 05-uli-nats. Encodes the CQRS / event
  sourcing patterns, ULI envelope usage, OAuth2 + correlation-id
  conventions, JSON logging, JPA conventions, Kubernetes manifest
  structure, Terraform module conventions, and PostgreSQL/Citus rules.
  Layer on top of standard Java/Spring/Terraform/Kubernetes idioms - this
  skill is project-specific.
---

# CAN Coding Agent

This skill captures the coding conventions of the CAN reference
implementation. Apply every rule below to every change. Where rules
conflict, follow the order they appear in.

## Overarching rules

1. **Read the architecture document first.** `docs/CAN-Solution-Architecture-Design.docx`
   is authoritative; this skill is a faithful condensation. If the document
   and this skill ever disagree, the document wins and this skill must be
   updated.
2. **Conform before extending.** When adding to an existing module, copy
   the structure of the closest sibling. New patterns require an
   architecture decision record (ADR) under `docs/adr/`.
3. **Tests are part of the change.** No production code lands without
   matching tests. Aggregates require Axon `AggregateTestFixture` tests;
   APIs require `@SpringBootTest` slice tests; SQL changes require an
   integration test against Testcontainers PostgreSQL.

## Java / Spring Boot conventions

### Project layout per service

```
<service>/
├── pom.xml
├── src/main/java/com/customer/can/<service>/
│   ├── <Service>Application.java       # @SpringBootApplication
│   ├── api/                            # @RestController / @Controller
│   ├── application/                    # use-cases, sagas, projections
│   ├── domain/                         # aggregates, value objects (no Spring)
│   ├── infrastructure/                 # JPA entities, repositories, NATS, Graph
│   └── config/                         # @Configuration beans, security
├── src/main/resources/
│   ├── application.yml
│   ├── logback-spring.xml
│   └── db/migration/                   # Flyway scripts
└── src/test/java/...
```

### Domain layer

- Aggregates carry `@Aggregate`. The identifier field carries
  `@AggregateIdentifier`. Constructors annotated with `@CommandHandler`
  must call `AggregateLifecycle.apply(...)` instead of mutating state directly.
- Domain events are `record`s, declared in `common-domain` so producers
  and consumers share the type. Field names match the SQL column names
  they ultimately project to - this keeps projections trivial.
- Value objects are `record`s. Validation lives in compact constructors,
  never in setters; aggregates and value objects are immutable.

```java
@Aggregate
public class Portfolio {
    @AggregateIdentifier
    private UUID portfolioId;

    @CommandHandler
    public Portfolio(CreatePortfolio cmd) {
        if (cmd.finalBidDate().isBefore(cmd.cutOffDate()))
            throw new IllegalArgumentException("finalBidDate before cutOffDate");
        AggregateLifecycle.apply(new PortfolioCreated(...));
    }
    @EventSourcingHandler
    void on(PortfolioCreated e) { this.portfolioId = e.portfolioId(); }
}
```

### Application layer

- Projections live in `application/` with `@ProcessingGroup("<group>")`.
  One projection class per read model. Avoid combining unrelated entities.
- Sagas (`@Saga`) live in `application/saga/`. Use `@StartSaga` exactly
  once and `@EndSaga` exactly once per saga lifecycle.
- The ULI bridge is its own `@ProcessingGroup("uli-publisher")` so
  back-pressure on NATS does not block the JPA projection.

### API layer

- Every public endpoint carries `@PreAuthorize("hasAuthority('SCOPE_<name>')")`.
  Empty `@PreAuthorize` or class-level annotations only is forbidden.
- REST: `/api/v1/<plural>` for collections, `/api/v1/<plural>/{id}` for
  items. PUT replaces, PATCH merges, POST creates.
- GraphQL: schema-first. `@QueryMapping`/`@MutationMapping` with
  `@PreAuthorize`. No business logic in resolvers - delegate to a service.

### Cross-cutting filters

- `CorrelationIdFilter` on every service. Reads `X-Correlation-Id`,
  generates a UUID if missing, puts it in MDC, echoes on response.
- Outbound calls use the central `WebClient.Builder` bean from
  `BffConfig`/`AppConfig` so headers propagate without per-call code.

### Logging

- JSON only via `logstash-logback-encoder`. Pattern in
  `logback-spring.xml`. Never `System.out.println`. Never log secrets,
  full tokens, or any column from a personally identifiable column.
- Use SLF4J parameterised messages: `log.info("created portfolio {}", id)`.
  Do not concatenate strings.
- Use `log.atDebug()` (or `log.atInfo()`) for high-rate paths so the cost
  is paid only when the level is enabled.

### Configuration and secrets

- All connection strings, issuer URIs, and audiences live in
  `application.yml` with `${ENV_VAR:default}` fallbacks. Never hard-code.
- Secrets land via the Key Vault CSI driver and arrive as files mounted
  under `/mnt/secrets-store`. Map them to env vars in the `Deployment`,
  not in code.

## Kubernetes manifests

A canonical service manifest contains every one of:

1. `Deployment` with `securityContext`: `runAsNonRoot: true`,
   `readOnlyRootFilesystem: true`, `allowPrivilegeEscalation: false`,
   `capabilities.drop: [ALL]`.
2. CPU and memory `resources.requests` AND `resources.limits`.
3. `livenessProbe`, `readinessProbe`, `startupProbe`.
4. `HorizontalPodAutoscaler`.
5. `PodDisruptionBudget` with `minAvailable: 1`.
6. `Service` of type `ClusterIP`.
7. Istio `DestinationRule` with `trafficPolicy.tls.mode: ISTIO_MUTUAL`.
8. Istio `AuthorizationPolicy` enumerating allowed source service accounts.
9. `NetworkPolicy` with default-deny except the explicit ingress sources
   needed.
10. `ServiceAccount` annotated for Workload Identity if Azure access is needed.

A manifest missing any of the above is a code-review block.

## Terraform conventions

- Each Azure resource family is a module under `modules/<name>/`. Modules
  expose a small, intentional input surface in `variables.tf` and a
  documented output set in `outputs.tf`.
- Common tags are applied via the `default_tags` provider feature. Every
  resource has at least `environment`, `project`, `cost-center`, `owner`.
- Private endpoints for every PaaS data service. Public endpoints
  forbidden in non-development environments.
- State is in Azure Storage with versioning enabled. The state file is
  encrypted with a customer-managed key.
- `terraform fmt`, `terraform validate`, and `tflint` run in CI; any
  diff fails the build.

## PostgreSQL / Citus

- One schema per bounded context. Per-service Flyway migrations under
  `src/main/resources/db/migration/`. Migration filenames sort
  lexicographically: `V0001__short_description.sql`.
- `portfolio_id` is the co-location key for distributed tables. Reference
  tables only for small lookup data; never for tables that grow with the
  business.
- Money is always `NUMERIC(18,2)`, never `float`/`double`. Identifiers
  are `UUID` populated by `gen_random_uuid()` (pgcrypto extension).
- Audit tables are append-only - install the `deny_mutation` trigger on
  every audit table.
- New indexes require a migration showing `EXPLAIN (ANALYZE, BUFFERS)`
  output before and after, attached to the PR.

## ULI / NATS

- Every cross-service message uses the `UliEnvelope` record from
  `common-domain`. Hand-rolled envelopes are forbidden.
- Subjects follow `uli.<kind>.<context>.<Type>` with kind in
  `{commands, events, queries, dlq}`. The third segment is the bounded
  context name. The last segment is PascalCase.
- Producers fill `correlationId` from the MDC. If the MDC is empty, the
  producer is being called outside a request scope and must explicitly
  decide a correlation id - the library will not silently invent one.
- Consumers are durable, `ackPolicy: explicit`, and dedup via the
  `uli.inbox` table before applying side effects. Auto-ack is forbidden.
- After `max_deliver`, NAK to `uli.dlq.<context>.<kind>` with the
  exception class name in `headers.error`.

## Tests

- Unit tests use JUnit 5, AssertJ, and the Axon test fixture for aggregates.
- Integration tests use Testcontainers (`citusdata/citus:12.1`,
  `nats:2.10-alpine`) and start the full Spring context.
- API tests use `WebTestClient` (reactive) or `MockMvc` (servlet).
  Always assert the JSON shape, not just the status code.
- Saga tests use `SagaTestFixture<TheSaga>` and exercise both happy path
  and the timeout path explicitly.

## Pull request hygiene

- Title format: `<scope>: <imperative summary>` where `<scope>` is the
  module (e.g. `property-allocation: enforce final bid date order`).
- The body links the ADR or the architecture-document section affected,
  if any.
- Every PR adds or updates the unit/integration tests it requires; PRs
  that only "fix" tests without changing behaviour need an explicit
  reason.
- Squash on merge. Commit history on `main` is one commit per PR.

## Self-check before requesting review

1. All public endpoints carry `@PreAuthorize`.
2. Any new domain event is also published as a ULI envelope.
3. Any new SQL change has a Flyway migration; no manual SQL is run on a
   running environment.
4. Logs are JSON; correlation id is in the MDC; no secrets are logged.
5. Kubernetes manifests are complete (the ten-point list above).
6. Terraform formatted, validated, tagged, with a private endpoint where
   relevant.
7. README updated if the change introduces a new run command, env var,
   or service.
