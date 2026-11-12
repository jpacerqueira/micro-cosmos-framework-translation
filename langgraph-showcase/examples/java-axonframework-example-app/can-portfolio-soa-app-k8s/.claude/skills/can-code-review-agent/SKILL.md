---
name: can-code-review-agent
description: >
  Apply this skill whenever you review a pull request or diff in the CAN
  (Customer-Application-Name) repository. Triggers on any review of code
  inside 01-terraform, 02-kubernetes-istio, 03-backend-springboot,
  04-database-postgres-citus, or 05-uli-nats. Mechanically checks the
  conventions encoded in `can-coding-agent`, plus security, operability,
  and resilience checks. Produces a structured review with severity
  labels (BLOCKER, MAJOR, MINOR, NIT) and a final verdict
  (APPROVE / REQUEST CHANGES / COMMENT).
---

# CAN Code Review Agent

This skill reviews diffs against the CAN architecture and coding
standards. The companion skill, `can-coding-agent`, is the source of
truth for the standards themselves; this skill is the checklist applied
on the way out.

## How to review

1. Read the PR description and any linked ADR.
2. Identify the affected modules from the diff.
3. Walk the appropriate checklist below for each affected module.
4. Group findings by severity. Output the review in the format at the
   bottom of this file.
5. If any BLOCKER findings exist, the verdict is REQUEST CHANGES. Else
   if MAJOR findings exist, the verdict is REQUEST CHANGES unless the
   reviewer judges them addressable in a follow-up. Otherwise APPROVE
   or COMMENT as appropriate.

## Severity definitions

- **BLOCKER** - merging this risks production incident, data loss,
  security breach, or violates a hard architecture rule. Always REQUEST
  CHANGES.
- **MAJOR** - violates a documented standard, will cause operational
  pain, or noticeably degrades quality. Usually REQUEST CHANGES.
- **MINOR** - style, structure, or readability improvements. Suggest
  rather than block.
- **NIT** - subjective preferences. Always optional.

## Java / Spring Boot - what to check

### Security and authorisation

- [ ] **BLOCKER** every public endpoint carries `@PreAuthorize` with a
      non-empty expression.
- [ ] **BLOCKER** no secrets in code, configuration, or fixtures (regex
      check `(?i)(password|secret|token|key)\s*=\s*[A-Za-z0-9]{8,}`).
- [ ] **MAJOR** no `permitAll()` outside `/actuator/health` and
      `/actuator/info`.
- [ ] **MAJOR** OAuth issuer and audience read from configuration, not
      hard-coded.
- [ ] **MAJOR** any new external HTTP client uses the central
      `WebClient.Builder` so correlation id propagates.

### CQRS / Axon

- [ ] **BLOCKER** any `@Aggregate` has exactly one `@AggregateIdentifier`.
- [ ] **BLOCKER** `@CommandHandler` methods do not mutate state -
      mutation only inside `@EventSourcingHandler`.
- [ ] **MAJOR** invariants enforced inside command handlers, not in
      event handlers.
- [ ] **MAJOR** new domain events are records in `common-domain`.
- [ ] **MAJOR** new sagas have exactly one `@StartSaga` and one
      `@EndSaga`; deadlines are scheduled, not implicit.

### Logging and observability

- [ ] **BLOCKER** no `System.out.println` or `e.printStackTrace()`.
- [ ] **MAJOR** new code paths log at the appropriate level with
      parameterised SLF4J calls.
- [ ] **MAJOR** correlation id is propagated to outbound calls and to
      the ULI envelope.
- [ ] **MINOR** new classes use `private static final Logger` not field
      injection.

### ULI

- [ ] **BLOCKER** new cross-service messages use `UliEnvelope`.
- [ ] **BLOCKER** new consumers ack explicitly and dedupe via
      `uli.inbox`.
- [ ] **MAJOR** subject follows the `uli.<kind>.<context>.<Type>`
      pattern.
- [ ] **MAJOR** producer fills `correlationId` from MDC or makes the
      omission explicit.

### Tests

- [ ] **BLOCKER** new aggregate behaviour has a matching
      `AggregateTestFixture` test.
- [ ] **MAJOR** new public endpoints have an API-level test that
      asserts the response shape.
- [ ] **MAJOR** new SQL has a Testcontainers-based integration test.
- [ ] **MINOR** new tests use AssertJ chained assertions, not
      `assertEquals` ladders.

## Kubernetes manifests - what to check

For every new or modified `Deployment`/`StatefulSet`:

- [ ] **BLOCKER** `securityContext.runAsNonRoot: true`,
      `readOnlyRootFilesystem: true`,
      `allowPrivilegeEscalation: false`,
      `capabilities.drop: [ALL]`.
- [ ] **BLOCKER** both `resources.requests` AND `resources.limits` set
      for CPU and memory.
- [ ] **BLOCKER** `livenessProbe` AND `readinessProbe` configured.
- [ ] **MAJOR** `startupProbe` configured for slow-starting services.
- [ ] **MAJOR** matching `HorizontalPodAutoscaler` and
      `PodDisruptionBudget`.
- [ ] **MAJOR** Istio `DestinationRule` (`tls.mode: ISTIO_MUTUAL`) and
      `AuthorizationPolicy` (no wildcard sources) present.
- [ ] **MAJOR** `NetworkPolicy` with a default-deny posture and
      explicit ingress allows.
- [ ] **MAJOR** `ServiceAccount` annotated for Workload Identity if the
      pod accesses Azure.
- [ ] **MINOR** image tag is a digest or a versioned tag, not `latest`.

## Terraform - what to check

- [ ] **BLOCKER** no plaintext secrets, no `provider` blocks with
      hard-coded credentials.
- [ ] **MAJOR** every PaaS data resource has a `private_endpoint` and
      `public_network_access_enabled = false` (or equivalent).
- [ ] **MAJOR** every resource carries the standard tags
      (`environment`, `project`, `cost-center`, `owner`).
- [ ] **MAJOR** new modules expose `variables.tf` and `outputs.tf`,
      both documented.
- [ ] **MINOR** `terraform fmt` clean, no spurious whitespace diff.
- [ ] **MINOR** sensitive outputs marked `sensitive = true`.

## SQL / Citus - what to check

- [ ] **BLOCKER** no `DROP TABLE` / `DROP COLUMN` without an explicit
      data-loss notice in the PR description.
- [ ] **BLOCKER** distribution declarations are inside a
      `DO $$ ... has_citus ... $$` guard so plain PG installs survive.
- [ ] **MAJOR** new distributed tables co-locate on `portfolio_id` (or
      the documented exception applies).
- [ ] **MAJOR** money columns are `NUMERIC(18,2)`.
- [ ] **MAJOR** new indexes are justified with EXPLAIN evidence in the
      PR body.
- [ ] **MAJOR** audit tables carry the `deny_mutation` triggers.
- [ ] **MINOR** migration filename follows `V0xxx__snake_case.sql`.

## Performance and resilience

- [ ] **MAJOR** new outbound HTTP calls have a configured timeout (no
      infinite waits).
- [ ] **MAJOR** new retry logic uses exponential backoff and a budget,
      not unbounded retries.
- [ ] **MAJOR** new caches have an eviction policy.
- [ ] **MINOR** loops over result sets use streaming reads when N could
      grow without bound.

## Documentation

- [ ] **MAJOR** README updated for any new run command, env var, or
      port.
- [ ] **MAJOR** ADR added under `docs/adr/` for any new pattern,
      framework, or significant deviation.
- [ ] **MINOR** Javadoc on public types in `common-domain` and on any
      `@RestController` method.

## Output format

Produce the review as Markdown:

```
## Code review - <PR title>

**Verdict**: APPROVE | COMMENT | REQUEST CHANGES

**Summary**: <one sentence>

### Findings

#### BLOCKER (n)
- <file:line> — <finding> — <suggested fix>

#### MAJOR (n)
- <file:line> — <finding> — <suggested fix>

#### MINOR (n)
- <file:line> — <finding>

#### NIT (n)
- <file:line> — <finding>

### Strengths
- <what is done well>
```

Findings without a fix recommendation are incomplete - always include
the suggested change so the author can address it without a round-trip.

## Reviewer self-check

Before posting, verify:

1. Every BLOCKER is genuinely a production risk, not a stylistic
   preference disguised as one.
2. Every finding cites a specific file and line.
3. Every finding suggests a fix.
4. The Strengths section is not empty - reviewers must call out what
   the author did well, not only what to change.
