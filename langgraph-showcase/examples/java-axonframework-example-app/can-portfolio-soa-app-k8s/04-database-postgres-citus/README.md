# 04-database-postgres-citus

PostgreSQL 15 + Citus 12 schemas for the Customer-Application-Name system.
Run with **Flyway** from each Spring Boot service (each service owns the
migration of its own schema) or in CI before the first pod starts.

## Databases

| Database | Owner service(s) | Purpose |
|---|---|---|
| `can_app` | property-allocation, user-auth, search, vdr-ingestion | Domain reads + writes |
| `can_axon_event` | property-allocation, workflow | Axon event store |
| `can_uli` | every service that publishes/consumes ULI | Outbox / inbox / DLQ |

## Schemas inside `can_app`

| Schema | Purpose |
|---|---|
| `user_mgmt` | Users, roles, companies, notifications |
| `portfolio` | Portfolios, properties, valuations, allocations, journal |
| `vdr` | VDR raw + extracted documents |
| `workflow` | Process-instance projection from sagas |
| `search` | Full-text search index (tsvector) |
| `audit` | Append-only event log |

## Citus distribution

`portfolio_id` is the **co-location key** for the entire portfolio bounded
context: `portfolio`, `property`, `property_view`, `property_valuation`,
`broker_allocation`, `property_journal`, `vdr_raw`, `process_instance`,
`search_index` are all distributed on `portfolio_id`. Joins inside one
portfolio are local to a single worker.

Reference tables (replicated to every worker):
- `user_mgmt.company`, `user_mgmt.role`, `user_mgmt.app_user`,
  `user_mgmt.user_role`
- `portfolio.unit`, `portfolio.tenancy_schedule`,
  `portfolio.template_catalogue`, `portfolio.template_allocation`,
  `portfolio.valuation_question`

The audit log is distributed on `correlation_id` so that every event of a
logical request lands on the same shard, making correlated audit retrieval
a single-shard query.

## Migration order

```
V0001__bootstrap.sql            # extensions, schemas, roles
V0010__user_mgmt.sql            # users, roles, companies
V0020__portfolio.sql            # portfolio + property + valuations + journal
V0030__vdr_workflow_search.sql  # vdr, workflow, search
V0040__audit.sql                # append-only event log
V0050__citus_distribution.sql   # distribute / reference (no-op on plain PG)
```
