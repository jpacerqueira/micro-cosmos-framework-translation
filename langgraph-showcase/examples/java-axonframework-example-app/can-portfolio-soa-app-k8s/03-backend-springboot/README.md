# 03-backend-springboot - Backend monorepo

Java 21, Spring Boot 3.2, AxonFramework 4.10. Multi-module Maven repo.

## Modules

| Module | Role |
|---|---|
| `common-domain` | Shared commands, events, ULI envelope |
| `webapp-bff` | GraphQL/REST BFF for the React UI |
| `user-auth` | User management, Azure AD B2B invitations via Microsoft Graph |
| `property-allocation` | Portfolio aggregate (CQRS/ES) and read-side projection |
| `vdr-ingestion` | Apache Tika/POI/PDFBox ingestion of Virtual Data Room documents |
| `workflow` | Axon Sagas / process managers |
| `search` | NATS-driven search index (Postgres full-text) |

## Cross-cutting concerns

- **Tracing & correlation**: every inbound HTTP request carries
  `X-Correlation-Id` (filter mints one if absent). The id is put in MDC,
  echoed on the response, propagated by the WebClient interceptor, and
  attached to every ULI envelope. This realises the SAD's "Correlate
  Requests with a unique Correlation_ID" pattern.
- **Logging**: JSON to stdout via Logstash Logback encoder. Azure Monitor
  ingests stdout of the pod and surfaces every JSON field as a column.
- **Auth**: OAuth2 resource server validates Azure AD JWTs.
  `@PreAuthorize("hasAuthority('SCOPE_<name>')")` enforces fine-grained
  access. The Istio ingress gateway double-checks the token before traffic
  ever hits a pod.
- **Secrets**: never in env vars or images. Pulled from Azure Key Vault
  via the CSI driver and mounted as a `Secret` in the pod's namespace.
- **Resilience**: Hikari pool, graceful shutdown, readiness/liveness split,
  Axon's tracking event processors with replay.

## Build

```bash
mvn -B -DskipTests clean package
mvn -DskipTests jib:build -Pbuild-images   # pushes to ACR
```

## Local dev

```bash
docker compose -f compose.dev.yml up -d   # nats, axonserver, postgres
mvn -pl property-allocation spring-boot:run
mvn -pl webapp-bff spring-boot:run
```
