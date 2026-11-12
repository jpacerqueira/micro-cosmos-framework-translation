# CAN Portfolio — Legacy Java 8 Application

A property portfolio management system built with **Java 8 + Spring Boot 2.7** + **Oracle XE** + **Apache ActiveMQ**. This is the legacy counterpart to the modern Axon Framework application in `../java-axonframework-modern-app/`.

## Tech Stack Comparison

| Concern | Modern App | **This App (Legacy)** |
|---|---|---|
| Java | 21 | **8** |
| Spring Boot | 3.2 | **2.7.18** |
| Architecture | CQRS / Event Sourcing (Axon) | **Spring MVC + JPA + Audit Log** |
| Messaging | NATS JetStream | **Apache ActiveMQ 5.x (JMS)** |
| Database | PostgreSQL + Citus | **Oracle XE 21 (10g dialect)** |
| API style | GraphQL BFF | **REST + Springfox Swagger 2** |
| Auth | Azure AD OAuth2 | **Spring Security + JJWT 0.9.x** |
| Frontend | React 18 + Vite | **Plain HTML + Vanilla JS** |
| Logging | Logback JSON | **Log4j2 JsonLayout + MDC** |
| Service mesh | Istio | **nginx-ingress** |
| Dead-letter | NATS DLQ | **ActiveMQ.DLQ** |

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Tier 1 — Frontend                                          │
│  nginx (port 3000) → Plain HTML + Vanilla JS                │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP / REST
┌──────────────────────────▼──────────────────────────────────┐
│  Tier 2 — API / BFF                                         │
│  webapp-bff (port 8080) — Springfox Swagger UI              │
│  Routes to: user-auth (8001) · property-allocation (8002)   │
│             vdr-ingestion (8003) · workflow (8004)           │
│             search (8005)                                    │
└──────────────────────────┬──────────────────────────────────┘
                           │ JMS / Oracle JDBC
┌──────────────────────────▼──────────────────────────────────┐
│  Tier 3 — Data                                              │
│  Oracle XE 21 (port 1521) · Apache ActiveMQ (port 61616)    │
│  Elasticsearch (port 9200) · Kibana (port 5601)             │
└─────────────────────────────────────────────────────────────┘
```

## Quick Start (Docker Compose)

**Prerequisites:** Docker Desktop with at least 6 GB RAM allocated (Oracle XE needs ~2 GB).

```bash
cd examples/java-springboot-legacy-app

# 1. Build all services and start the stack
docker compose -f docker-compose.local.yml up --build

# First startup takes ~5 minutes (Oracle XE init + Flyway migrations)
# Watch for "DATABASE IS READY TO USE!" in oracle-db logs

# 2. Open the app
open http://localhost:3000          # Frontend
open http://localhost:8080/swagger-ui/  # BFF Swagger UI
open http://localhost:8161          # ActiveMQ Console (admin/admin)
open http://localhost:5601          # Kibana
```

## Demo Accounts

| Email | Password | Role |
|---|---|---|
| alice@beyondcapital.local | password123 | PORTFOLIO_ADMIN |
| bob@summitbrokers.local | password123 | BROKER |
| carol@apexvaluers.local | password123 | VALUER |
| dave@beyondcapital.local | password123 | VIEWER |
| eva@beyondcapital.local | password123 | SYS_ADMIN |

## API Endpoints (via BFF on :8080)

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/portfolios/auth/login` | Login, returns JWT |
| POST | `/api/v1/portfolios/auth/refresh` | Refresh token |
| GET | `/api/v1/portfolios` | List portfolios |
| POST | `/api/v1/portfolios` | Create portfolio |
| GET | `/api/v1/portfolios/{id}` | Get portfolio |
| PUT | `/api/v1/portfolios/{id}/close` | Close portfolio |
| GET | `/api/v1/portfolios/{id}/properties` | List properties |
| POST | `/api/v1/portfolios/{id}/properties` | Add property |
| GET | `/api/v1/search?q=...` | Global search |
| GET | `/api/v1/search/portfolios` | Search portfolios |
| GET | `/api/v1/search/properties` | Search properties |

Full Swagger docs: http://localhost:8080/swagger-ui/

## Service Ports

| Service | Port |
|---|---|
| Frontend (nginx) | 3000 |
| webapp-bff | 8080 |
| user-auth | 8001 |
| property-allocation | 8002 |
| vdr-ingestion | 8003 |
| workflow | 8004 |
| search | 8005 |
| Oracle XE | 1521 |
| ActiveMQ JMS | 61616 |
| ActiveMQ Console | 8161 |
| Elasticsearch | 9200 |
| Kibana | 5601 |

## Running on Kubernetes (AKS)

```bash
# 1. Provision infrastructure
cd terraform
terraform init
terraform apply -var="acr_name=yourUniqueAcrName"

# 2. Configure kubectl
az aks get-credentials --resource-group can-legacy-rg --name can-legacy-aks

# 3. Build and push images
ACR=$(terraform output -raw acr_login_server)
az acr login --name $ACR

for SERVICE in property-allocation user-auth vdr-ingestion workflow search webapp-bff; do
  docker build --build-arg SERVICE=$SERVICE -t $ACR/can-legacy/$SERVICE:latest ./can-portfolio-legacy-app
  docker push $ACR/can-legacy/$SERVICE:latest
done

docker build -t $ACR/can-legacy/frontend:latest ./00-frontend
docker push $ACR/can-legacy/frontend:latest

# 4. Deploy
kubectl apply -k kubernetes/
```

## Database Migrations (Flyway)

Migrations run automatically via the `db-migrate` container on first start. Scripts are in `can-portfolio-legacy-app/property-allocation/src/main/resources/db/migration/`:

| Script | Contents |
|---|---|
| V0001 | Bootstrap check |
| V0010 | `COMPANY`, `APP_USER` tables |
| V0020 | `PORTFOLIO`, `PROPERTY`, `PROPERTY_VALUATION`, `BROKER_ALLOCATION` |
| V0030 | `DOCUMENT`, `ALLOCATION_WORKFLOW` |
| V0040 | `PROPERTY_JOURNAL` (append-only audit log) |
| V0060 | Seed data (4 companies, 5 users, 2 portfolios, 5 properties) |

## Log Observability

All services emit structured JSON logs via Log4j2 with `correlationId`, `service`, and `environment` fields. In Docker Compose, Filebeat ships logs to Elasticsearch — view them in Kibana at http://localhost:5601 using index pattern `can-legacy-logs-*`.
