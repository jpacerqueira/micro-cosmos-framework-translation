# Hive Metastore — project1_databricks_adf

Speculative but accurate DDL representation of the full Hive metastore for the retail BIS platform. Derived from source analysis of all notebooks, ETL classes, etl_config.json, ADF pipelines, and the PSO lineage discovery report (925 queries across 6 domains).

All DDL uses Databricks Hive metastore syntax with `USING DELTA`, `LOCATION`, `TBLPROPERTIES`, and `PARTITIONED BY` clauses. Every table includes per-column `COMMENT` annotations, UCX migration notes, and cross-catalog join relationships.

---

## File Index

| File | Schema(s) | Tables | Description |
|---|---|---|---|
| [00_databases.sql](00_databases.sql) | All | — | `CREATE DATABASE` statements for all 15+ schemas with DBPROPERTIES |
| [01_product_systems_raw.sql](01_product_systems_raw.sql) | `product_systems_raw` | nm_item, nm_item_supplier, nm_item_detail, nm_item_text, nm_supplier, nm_booking_report, item_season | Bronze landing zone — raw ADLS ingest |
| [02_product_systems.sql](02_product_systems.sql) | `product_systems`, `productsystems` | nm_item_supplier, item_season, nm_item_option, item, item_text | Curated silver + legacy alias stubs |
| [03_trusted.sql](03_trusted.sql) | `trusted` | dim_item (SCD2), dim_item_team, fact_sales_orders, fact_return_rate_item | BIS star schema gold hub |
| [04_refined_bismerged.sql](04_refined_bismerged.sql) | `refined`, `bismerged` | fact_sales_orders_season, dim_item_attribute, svoc_customers | Seasonal aggregates + Customer 360 |
| [05_branded_prod.sql](05_branded_prod.sql) | `branded_prod` | noclick_stock_levels + 15 × attribution_* | Branded spoke + all 15 CTAS write-back targets |
| [06_bronze_silver_gold.sql](06_bronze_silver_gold.sql) | `bronze`, `silver`, `gold` | customer_transactions, product_inventory, nm_item_supplier, item_season, fact_sales_orders, dim_item (+ gold aggs) | Generic ETL pipeline layers from etl_config.json |
| [07_payment_diagnostics.sql](07_payment_diagnostics.sql) | `wp_diagnostic`, `ap_diagnostic`, `pp_diagnostic`, `gp_diagnostic`, `klarna_diagnostic` | 5 × payment_events | 5 payment provider diagnostic catalogs (JSON Payload anti-pattern) |
| [08_warehouselogistics_prod.sql](08_warehouselogistics_prod.sql) | `warehouselogistics_prod` | bpp_parcel_events, bpp_delivery_status | Streaming BPP parcel events |
| [09_views_and_grants.sql](09_views_and_grants.sql) | All | Views + GRANT statements | Analytical views, catalog alias compatibility views, access grants |

---

## Domain Map

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      HIVE METASTORE (legacy catalog)                    │
├──────────────────────────────┬──────────────────────────────────────────┤
│   BIS HUB (medallion)        │   BRANDED SPOKE                         │
│                              │                                          │
│  product_systems_raw         │   branded_prod                          │
│    nm_item          ─────────┼──► noclick_stock_levels                 │
│    nm_item_supplier          │   attribution_item_season  (1/15)       │
│    nm_item_detail            │   attribution_item_team    (2/15)       │
│    nm_item_text              │   attribution_item_brand   (3/15)       │
│    nm_supplier               │   attribution_sales_weekly (4/15)       │
│    nm_booking_report         │   attribution_sales_monthly(5/15)       │
│    item_season               │   attribution_return_rate  (6/15)       │
│         │                    │   attribution_stock_cover  (7/15)       │
│         ▼                    │   attribution_forecast_acc (8/15)       │
│  product_systems             │   attribution_supplier_lt  (9/15)       │
│    nm_item_supplier          │   attribution_noclick_opp  (10/15)      │
│    item_season ◄─────────────┼── attribution_svoc_segment (11/15)      │
│    nm_item_option            │   attribution_price_elast  (12/15)      │
│    item                      │   attribution_channel_mix  (13/15)      │
│    item_text                 │   attribution_markdown_imp (14/15)      │
│         │  ╔═══════╗         │   attribution_new_season   (15/15)      │
│         │  ║ CTAS  ║ ────────┤         ▲                               │
│         ▼  ╚═══════╝         │         │ BISPipeline.materialise_      │
│  trusted                     │         │ attribution_targets()          │
│    dim_item (SCD2) ──────────┼─────────┘                               │
│    dim_item_team             │                                          │
│    fact_sales_orders ────────┼──────────────────────────────────────── │
│    fact_return_rate_item     │         ▲ ExternalOrderRef join          │
│         │                    │         │                                │
│         ▼                    ├──────────────────────────────────────── │
│  refined                     │   PAYMENTS (5 providers)                │
│    fact_sales_orders_season  │   wp_diagnostic.payment_events          │
│    dim_item_attribute        │   ap_diagnostic.payment_events          │
│         │                    │   pp_diagnostic.payment_events          │
│         ▼                    │   gp_diagnostic.payment_events          │
│  bismerged                   │   klarna_diagnostic.payment_events ─────┤
│    svoc_customers ◄──────────┤         (cross-catalog join to trusted) │
│    (ORPHAN - Phase 3)        ├──────────────────────────────────────── │
│                              │   WAREHOUSE LOGISTICS                   │
│  bronze / silver / gold      │   warehouselogistics_prod               │
│  (generic ETL pipeline)      │     bpp_parcel_events (streaming)       │
│                              │     bpp_delivery_status                 │
└──────────────────────────────┴──────────────────────────────────────────┘
```

---

## Key Relationships

| From | Join Key | To | Type |
|---|---|---|---|
| `product_systems.nm_item_supplier` | ItemNumber | `product_systems_raw.nm_item` | N:1 |
| `product_systems.item_season` | ItemNumber | `product_systems_raw.nm_item` | N:1 |
| `trusted.dim_item` | ItemNumber | `product_systems.item` | SCD2 merge |
| `trusted.dim_item` | TeamCode | `trusted.dim_item_team` | N:1 |
| `trusted.fact_sales_orders` | ItemNumber | `trusted.dim_item` | N:1 |
| `trusted.fact_sales_orders` | ExternalOrderRef | `klarna_diagnostic.payment_events` Payload→order_id | cross-catalog |
| `trusted.dim_item` | ItemNumber | `branded_prod.noclick_stock_levels` | cross-catalog N:1 |
| `refined.fact_sales_orders_season` | ItemNumber, SeasonCode | `product_systems.item_season` | N:1 |
| `branded_prod.attribution_*` | ItemNumber, SeasonCode | `refined.fact_sales_orders_season` | CTAS write-back |
| `bismerged.svoc_customers` | CustomerID | `trusted.fact_sales_orders` | 1:1 snapshot |
| `warehouselogistics_prod.bpp_delivery_status` | OrderId | `trusted.fact_sales_orders` | N:1 |

---

## UCX Migration Status Summary

| Schema | Status | Blocker |
|---|---|---|
| `product_systems_raw` | BLOCKER | `wasb://` source URIs not UC-compatible |
| `product_systems` | ASSESS | External Location needed for `abfss://` paths |
| `productsystems` | RENAME IN FLIGHT | Alias for `product_systems` — dual-read during rename |
| `trusted` | ASSESS | External Location needed |
| `refined` | ASSESS | External Location needed |
| `bismerged` | ASSESS | External Location needed |
| `branded_prod` | BLOCKER | `wasb://` source for noclick_stock_levels |
| `bronze` / `silver` / `gold` | ASSESS | External Location needed |
| `wp_diagnostic` | ASSESS | PII (customer_email in Payload) needs masking |
| `ap_diagnostic` | ASSESS | PII (order_reference) |
| `pp_diagnostic` | ASSESS | PII (payer.email in Payload) needs masking |
| `gp_diagnostic` | LOW | No direct PII in extracted fields |
| `klarna_diagnostic` | ASSESS | Cross-catalog join needs IAM on both projects |
| `warehouselogistics_prod` | ASSESS | Streaming tables not UC-compatible with current DLT config |

---

## GCP Mapping (after db2bq translation)

| Hive Schema | GCP equivalent |
|---|---|
| `product_systems_raw` | `my-gcp-project.bronze` dataset (BigQuery) + `gs://retail-bronze-eu/` |
| `product_systems` | `my-gcp-project.silver` dataset |
| `trusted` | `my-gcp-project.gold` dataset (Dataform-managed) |
| `branded_prod.attribution_*` | `my-gcp-project.gold.attribution_*__ctas.sqlx` (15 Dataform SQLX skeletons) |
| `[provider]_diagnostic.payment_events` | `my-gcp-project.[provider]_diagnostic.payment_events` (BigQuery native) |
| `warehouselogistics_prod` | `my-gcp-project.warehouselogistics` + Eventarc Cloud Run handler |

---

## How to apply this metastore

Run in order inside a Databricks workspace:

```bash
# 1. Create all databases
%run /hive_metastore/00_databases.sql

# 2. Bronze landing
%run /hive_metastore/01_product_systems_raw.sql

# 3. Silver curated
%run /hive_metastore/02_product_systems.sql

# 4. Gold hub
%run /hive_metastore/03_trusted.sql

# 5. Refined + SVOC
%run /hive_metastore/04_refined_bismerged.sql

# 6. Branded spoke (CTAS targets)
%run /hive_metastore/05_branded_prod.sql

# 7. Generic ETL layers
%run /hive_metastore/06_bronze_silver_gold.sql

# 8. Payment diagnostics
%run /hive_metastore/07_payment_diagnostics.sql

# 9. Warehouse logistics
%run /hive_metastore/08_warehouselogistics_prod.sql

# 10. Views and grants
%run /hive_metastore/09_views_and_grants.sql
```

Or run the whole set at once from a Databricks Job with a single-task notebook that `%run`s each file in sequence.
