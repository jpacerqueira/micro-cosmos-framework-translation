# CAN — Java Axon Framework Modern App

A reference implementation of a CQRS / Event Sourcing microservices platform built with
Spring Boot 3.2, Axon Framework 4.10, NATS JetStream, PostgreSQL, and GraphQL.

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
# rebuild and restart only the frontend container
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
| http://localhost:800X/actuator/health | Health check (X = 1–5, management port 8081 inside container) |

---

## Try the API (GraphQL playground)

Open **http://localhost:8080** — it redirects to the GraphiQL playground. Paste any of these queries:

```graphql
# List all portfolios (two pre-loaded by seed data)
{
  portfolios {
    portfolioId
    name
    status
  }
}
```

```graphql
# Get a single portfolio with its properties
{
  portfolio(id: "20000000-0000-0000-0000-000000000001") {
    name
    status
    cutOffDate
    properties {
      name
      city
      postcode
      valuation
    }
  }
}
```

```graphql
# Mutation: create a new portfolio
mutation {
  createPortfolio(input: {
    name: "Bristol Retail Portfolio"
    description: "City-centre retail units in Bristol"
    cutOffDate: "2025-08-31"
    finalBidDate: "2025-11-30"
    projectPhase: "PHASE_1"
  })
}
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

**Portfolios and properties**

| Portfolio | Status | Properties |
|-----------|--------|------------|
| London Commercial Portfolio 2025 (`...0001`) | OPEN | Canary Wharf Office Tower A, Covent Garden Retail Unit 12, Shoreditch Mixed-Use Block |
| Manchester Industrial Portfolio (`...0002`) | BIDDING | Trafford Park Warehouse Unit 7, Salford Industrial Estate Block B |

---

## Local-dev security model

All services start with `SPRING_PROFILES_ACTIVE=local`. This does three things:

1. **Disables OAuth2 / Azure AD** — `SecurityAutoConfiguration` and `OAuth2ResourceServerAutoConfiguration` are excluded via `SPRING_AUTOCONFIGURE_EXCLUDE`
2. **Injects a superuser** — a pre-auth filter populates `SecurityContextHolder` with `SCOPE_portfolio.read`, `SCOPE_portfolio.write`, and `SCOPE_actuator.read` on every request, so `@PreAuthorize` checks pass without a JWT
3. **Skips management security** — `ManagementWebSecurityAutoConfiguration` is also excluded so actuator starts without needing an `HttpSecurity` bean

To re-enable production security: remove `SPRING_PROFILES_ACTIVE=local` from the compose file and provide:

```yaml
AAD_TENANT_ID: <your-azure-tenant-id>
AAD_CLIENT_ID: <your-app-registration-client-id>
```

---

## Database migrations

Flyway runs once at startup via dedicated one-shot containers. Migrations are in:

```
solution-k8s/04-database-postgres-citus/migrations/
├── can_app/
│   ├── V0001__bootstrap.sql       # Extensions, schemas, roles
│   ├── V0010__user_mgmt.sql       # company, app_user, user_role tables
│   ├── V0020__portfolio.sql       # portfolio, property, valuation tables
│   ├── V0030__vdr_workflow_search.sql
│   ├── V0040__audit.sql
│   ├── V0050__citus_distribution.sql  # No-op on plain PG
│   └── V0060__seed_data.sql       # Dev seed: companies, users, portfolios
├── can_axon_event/
│   └── V0001__bootstrap.sql       # DB + schema (Axon tables auto-created by framework)
└── can_uli/
    └── V0001__bootstrap.sql       # ULI inbox schema
```

---

## NATS streams

| Stream | Subjects | Retention | Purpose |
|--------|----------|-----------|---------|
| `ULI_EVENTS` | `uli.events.>` | limits / 7 days | Domain event log |
| `ULI_COMMANDS` | `uli.commands.>` | work-queue / 24 h | Async command delivery |
| `ULI_DLQ` | `uli.dlq.>` | limits / 30 days | Failed message parking |

---

## Project layout

```
solution-k8s/
├── 00-frontend/                    React 18 + Vite 5 + Apollo Client webapp
│   ├── src/
│   │   ├── pages/                  PortfolioList, PortfolioDetail, CreatePortfolio
│   │   ├── components/             StatusBadge, Spinner, ErrorBanner
│   │   ├── graphql/queries.js      All GraphQL queries and mutations
│   │   ├── App.jsx                 Router + nav shell
│   │   ├── main.jsx                ApolloProvider + BrowserRouter root
│   │   └── index.css               Global dark-theme stylesheet
│   ├── vite.config.js              Dev server on :3000, proxies /graphql → webapp-bff:8080
│   ├── Dockerfile                  Node 20 Alpine, runs `npm run dev`
│   └── package.json
├── 01-terraform/                   Azure infrastructure (AKS, ACR, PG Citus, Key Vault)
├── 02-kubernetes-istio/            K8s manifests + Istio AuthorizationPolicies
├── 03-backend-springboot/          Maven multi-module — all 6 microservices
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
│       ├── can_app/
│       ├── can_axon_event/
│       └── can_uli/
├── 05-uli-nats/                    ULI envelope specification and schemas
├── docker/
│   ├── nats/nats-local.conf        NATS JetStream config with local auth
│   ├── nats/bootstrap-streams.sh  Stream provisioning (ULI_EVENTS/COMMANDS/DLQ)
│   └── postgres/00-create-databases.sh  Init: creates can_axon_event + can_uli
└── docker-compose.local.yml        ← Local dev entry point
```

---

## Key versions

| Technology | Version |
|------------|---------|
| Java | 21 |
| Spring Boot | 3.2.5 |
| Axon Framework | 4.10.0 |
| Axon Server | latest |
| PostgreSQL | 16-alpine |
| NATS | 2.10-alpine |
| graphql-java | 21.4 |
| graphql-java-extended-scalars | 22.0 |
| Flyway | 10-alpine |
