# Customer-Application-Name (CAN)

Reference implementation of the CAN solution architecture: an Azure-hosted,
event-driven microservices system for property portfolio allocation, valuation,
and disposal — built with Spring Boot 3.2, Axon Framework 4.10, NATS JetStream,
PostgreSQL, and GraphQL.

The accompanying architecture document is at
[`docs/CAN-Solution-Architecture-Design.docx`](docs/CAN-Solution-Architecture-Design.docx).

---

## Quick start

### Prerequisites

- Docker Desktop ≥ 4.x with **≥ 8 GB RAM** allocated to Docker
- ~20 GB free disk (Maven layer cache is large on first build)

### Start everything

```bash
cd examples/java-axonframework-modern-app/can-portfolio-soa-app-k8s

# First run: builds all images (10–15 min — Maven downloads Tika, PDFBox, Axon)
docker compose -f docker-compose.local.yml up --build

# Subsequent starts use the layer cache (< 1 min)
docker compose -f docker-compose.local.yml up
```

Once all containers are running, open **http://localhost:3000** in your browser to use the React webapp.

> The frontend starts almost instantly (Node/Vite). The backend services take ~60 s on
> first start while Axon Server, Flyway migrations, and Spring contexts initialise.
> If the UI shows a loading spinner or network error, wait a few seconds and refresh.

### Start only the webapp (frontend + BFF)

If you already have the backend running and just want to restart the frontend:

```bash
docker compose -f docker-compose.local.yml up --build frontend
```

Or to rebuild the BFF as well (e.g. after a Java code change):

```bash
docker compose -f docker-compose.local.yml up --build frontend webapp-bff
```

### Stop

```bash
# Keep volumes (database data, Axon event store survive)
docker compose -f docker-compose.local.yml stop

# Full teardown including all volumes
docker compose -f docker-compose.local.yml down -v
```

---

## Endpoints

| URL | What you get |
|-----|--------------|
| **http://localhost:3000** | **React UI — portfolio management webapp** |
| http://localhost:8080 | → redirects to GraphQL playground |
| http://localhost:8080/graphiql | GraphQL playground (BFF) |
| http://localhost:8080/graphql | GraphQL POST endpoint |
| http://localhost:8024 | Axon Server dashboard |
| http://localhost:8222 | NATS monitor |
| http://localhost:8002/api/v1/portfolios | property-allocation REST read API |
| http://localhost:8001/actuator/health | user-auth health |
| http://localhost:8002/actuator/health | property-allocation health |
| http://localhost:8003/actuator/health | vdr-ingestion health |
| http://localhost:8005/actuator/health | search health |

---

## Logs

### All containers at once

Stream live logs from every container in the stack:

```bash
docker compose -f docker-compose.local.yml logs -f
```

Show the last 100 lines from all containers then follow new output:

```bash
docker compose -f docker-compose.local.yml logs -f --tail 100
```

### Single service

```bash
docker compose -f docker-compose.local.yml logs -f webapp-bff
docker compose -f docker-compose.local.yml logs -f property-allocation
docker compose -f docker-compose.local.yml logs -f user-auth
docker compose -f docker-compose.local.yml logs -f vdr-ingestion
docker compose -f docker-compose.local.yml logs -f workflow
docker compose -f docker-compose.local.yml logs -f search
```

### Multiple services together

```bash
docker compose -f docker-compose.local.yml logs -f webapp-bff property-allocation
```

### Dump logs to a file (for sharing or offline analysis)

All services:

```bash
docker compose -f docker-compose.local.yml logs --no-color > can-all-$(date +%Y%m%d-%H%M%S).log
```

One service:

```bash
docker compose -f docker-compose.local.yml logs --no-color webapp-bff > bff-$(date +%Y%m%d-%H%M%S).log
```

### Filter for errors only

Scan all containers for ERROR lines:

```bash
docker compose -f docker-compose.local.yml logs --no-color 2>&1 | grep -i "error\|exception\|failed"
```

Check whether all six Spring Boot services started cleanly (no errors):

```bash
for svc in webapp-bff property-allocation user-auth search vdr-ingestion workflow; do
  echo "=== $svc ==="
  docker compose -f docker-compose.local.yml logs $svc 2>&1 \
    | grep -E "Started|ERROR|Exception|APPLICATION FAILED" \
    | grep -v "ContentTypeConverter"
done
```

### Infrastructure containers

```bash
docker compose -f docker-compose.local.yml logs -f postgres
docker compose -f docker-compose.local.yml logs -f axonserver
docker compose -f docker-compose.local.yml logs -f nats
docker compose -f docker-compose.local.yml logs -f flyway-can-app
docker compose -f docker-compose.local.yml logs -f flyway-axon-event
docker compose -f docker-compose.local.yml logs -f flyway-uli
```

### Check container health at a glance

```bash
docker compose -f docker-compose.local.yml ps
```

### Tail all logs since last restart

```bash
docker compose -f docker-compose.local.yml logs -f --since 1m
```

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  Browser  http://localhost:3000   (React + Vite dev server)          │
└─────────────────────────┬────────────────────────────────────────────┘
                          │  /graphql  (Vite proxy → webapp-bff:8080)
                          ▼
             ┌────────────────────────┐
             │    webapp-bff :8080    │  Spring for GraphQL BFF
             │  /graphiql playground  │  Axon CommandGateway (writes)
             └──────┬─────────────────┘  WebClient → property-allocation (reads)
                    │
        ┌───────────┼───────────────────┐
        │           │                   │
        ▼           ▼                   ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│property-alloc│  │  user-auth   │  │    search    │
│   :8002      │  │   :8001      │  │    :8005     │
│ CQRS agg.   │  │ MS Graph wrap│  │ projections  │
│ REST read API│  │              │  │              │
└──────┬───────┘  └──────────────┘  └──────────────┘
       │ Axon commands/events
       ▼
┌────────────────────────────────────────────────────┐
│  vdr-ingestion :8003  │  workflow :8004             │
│  Document upload      │  Allocation saga (Axon)    │
└────────────────────────────────────────────────────┘
       │                           │
       ▼                           ▼
┌──────────────┐    ┌─────────────────────────────────┐
│ Axon Server  │    │  NATS JetStream :4222           │
│ :8024 / 8124 │    │  ULI_EVENTS / ULI_COMMANDS /    │
│ Event store  │    │  ULI_DLQ streams                │
└──────────────┘    └─────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────┐  ┌───────────────────┐
│  PostgreSQL :5432               │  │  Azurite :10000   │
│  can_app (user_mgmt, portfolio, │  │  Azure Blob emu.  │
│           vdr, search, audit)   │  │  vdr-ingestion    │
│  can_axon_event  (Axon tables)  │  └───────────────────┘
│  can_uli         (ULI inbox)    │
└─────────────────────────────────┘
```

### Services

| Service | Port | Role |
|---------|------|------|
| `webapp-bff` | 8080 | GraphQL BFF — proxies reads to property-allocation, writes via Axon CommandGateway |
| `user-auth` | 8001 | User management, Azure AD B2B invitation flow |
| `property-allocation` | 8002 | Portfolio/property CQRS aggregate + JPA read-side REST API |
| `vdr-ingestion` | 8003 | Document upload to Azure Blob Storage, triggers processing events |
| `workflow` | 8004 | Allocation saga — orchestrates broker/valuer assignment flow |
| `search` | 8005 | Full-text search projections, NATS consumer |

### Infrastructure

| Service | Port(s) | Purpose |
|---------|---------|---------|
| PostgreSQL | 5432 | Application databases (3 logical DBs) |
| NATS | 4222 / 8222 | JetStream message bus + HTTP monitor |
| Axon Server | 8024 / 8124 | Event store + command routing + UI dashboard |
| Azurite | 10000–10002 | Azure Storage emulator (Blob, Queue, Table) |

---

## Pre-loaded seed data

The `V0060__seed_data.sql` migration runs on first start and loads:

**Companies**

| ID suffix | Name | Type |
|-----------|------|------|
| `...0001` | Beyond Capital | INTERNAL |
| `...0002` | Summit Brokers Ltd | BROKER |
| `...0003` | Apex Valuers Ltd | VALUER |
| `...0004` | First National Lender | LENDER |

**Users**

| Name | Email | Role |
|------|-------|------|
| Alice Admin | alice@beyondcapital.local | PORTFOLIO_ADMIN |
| Bob Broker | bob@summitbrokers.local | BROKER |
| Carol Valuer | carol@apexvaluers.local | VALUER |
| Dave Viewer | dave@beyondcapital.local | VIEWER |
| Eva SysAdmin | eva@beyondcapital.local | SYS_ADMIN |

**Portfolios**

| Portfolio | Status | Properties |
|-----------|--------|------------|
| London Commercial Portfolio 2025 (`...0001`) | OPEN | Canary Wharf Office Tower A, Covent Garden Retail Unit 12, Shoreditch Mixed-Use Block |
| Manchester Industrial Portfolio (`...0002`) | BIDDING | Trafford Park Warehouse Unit 7, Salford Industrial Estate Block B |

---

## Local-dev security model

All services start with `SPRING_PROFILES_ACTIVE=local`. This does three things:

1. **Disables OAuth2 / Azure AD** — `SecurityAutoConfiguration` and `OAuth2ResourceServerAutoConfiguration` are excluded via `SPRING_AUTOCONFIGURE_EXCLUDE`
2. **Injects a superuser** — a pre-auth filter populates `SecurityContextHolder` with `SCOPE_portfolio.read`, `SCOPE_portfolio.write`, and `SCOPE_actuator.read` on every request, so `@PreAuthorize` checks pass without a JWT
3. **Skips management security** — `ManagementWebSecurityAutoConfiguration` is also excluded so actuator starts without needing a security bean

To re-enable production security: remove `SPRING_PROFILES_ACTIVE=local` and provide:

```yaml
AAD_TENANT_ID: <your-azure-tenant-id>
AAD_CLIENT_ID: <your-app-registration-client-id>
```

---

## Project layout

```
can-portfolio-soa-app-k8s/
├── 00-frontend/                    React 18 + Vite 5 + Apollo Client webapp
│   ├── src/
│   │   ├── pages/                  PortfolioList, PortfolioDetail, CreatePortfolio
│   │   ├── components/             StatusBadge, Spinner, ErrorBanner
│   │   ├── graphql/queries.js      GraphQL queries and mutations
│   │   ├── App.jsx                 Router + nav shell
│   │   ├── main.jsx                ApolloProvider + BrowserRouter root
│   │   └── index.css               Global dark-theme stylesheet
│   ├── vite.config.js              Dev server on :3000, proxies /graphql → webapp-bff:8080
│   ├── Dockerfile                  Node 20 Alpine, runs `npm run dev`
│   └── package.json
├── 01-terraform/                   Azure infrastructure as code
├── 02-kubernetes-istio/            AKS manifests, Istio mesh, NATS, Axon Server
├── 03-backend-springboot/          Java 21 / Spring Boot / Axon microservices (Maven monorepo)
│   ├── common-domain/              Shared commands, events, ULI envelope
│   ├── webapp-bff/                 GraphQL BFF
│   ├── user-auth/                  User management
│   ├── property-allocation/        Portfolio CQRS aggregate + read-side REST
│   ├── vdr-ingestion/              Document ingestion
│   ├── workflow/                   Allocation saga
│   ├── search/                     Search projections
│   ├── Dockerfile                  Multi-stage Maven 3.9 → JRE 21 image
│   └── .dockerignore
├── 04-database-postgres-citus/     Flyway SQL migrations
│   └── migrations/
│       ├── can_app/                V0001–V0060 (bootstrap → seed data)
│       ├── can_axon_event/         Axon event store DB
│       └── can_uli/                ULI inbox schema
├── 05-uli-nats/                    Universal Layer of Interoperability spec
├── docker/
│   ├── nats/nats-local.conf        NATS JetStream config with local auth
│   ├── nats/bootstrap-streams.sh  Stream provisioning (ULI_EVENTS/COMMANDS/DLQ)
│   └── postgres/00-create-databases.sh  Creates can_axon_event + can_uli DBs
├── docs/                           Architecture document and diagrams
└── docker-compose.local.yml        ← Local dev entry point
```

---

## Development workflow

The repository ships with two skill agents that codify the standards in the
architecture document:

- `.claude/skills/can-coding-agent` — applied while writing new code; encodes the
  CQRS, ULI, security, observability, and infrastructure conventions.
- `.claude/skills/can-code-review-agent` — applied to pull requests; checks that
  the same conventions have been followed and produces a structured review.

## Deploying to Azure

```bash
# 1. Provision infrastructure
cd 01-terraform
terraform init -backend-config=envs/dev/backend.hcl
terraform apply -var-file=envs/dev/dev.tfvars

# 2. Push images (Jib builds + tags + signs in CI; locally:)
cd ../03-backend-springboot
mvn -DskipTests jib:build

# 3. Bootstrap NATS streams
cd ../05-uli-nats
./cli/uli-bootstrap.sh nats://nats.can-system.svc.cluster.local:4222

# 4. Apply k8s manifests
cd ../02-kubernetes-istio
kubectl apply -k .
```
