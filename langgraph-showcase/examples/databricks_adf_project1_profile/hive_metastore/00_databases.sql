-- =============================================================================
-- hive_metastore — Database / Schema Declarations
-- Retail BIS Platform  ·  project1_databricks_adf
-- =============================================================================
-- All schemas live in the legacy `hive_metastore` catalog (pre-Unity Catalog).
-- The UCX migration assessment (lineage_ucx.html) targets all of these for
-- promotion to Unity Catalog External Tables backed by ADLS Gen2 / GCS.
--
-- Schema layering:
--   product_systems_raw   → bronze / landing  (raw wasb:// + abfss:// ingests)
--   product_systems       → curated / silver  (conformed BIS product tables)
--   productsystems        → ALIAS (rename in flight → product_systems; dual-read)
--   trusted               → serving / gold    (dim_item, fact_sales_orders)
--   refined               → refined / gold+   (seasonal aggregates)
--   bismerged             → consolidated      (SVOC customer 360)
--   branded_prod          → spoke / write-back (15 CTAS attribution targets)
--   bronze                → generic ETL bronze (customer_transactions etc.)
--   silver                → generic ETL silver
--   gold                  → generic ETL gold
--   wp_diagnostic         → payment diagnostics · WooPayments
--   ap_diagnostic         → payment diagnostics · AmazonPay
--   pp_diagnostic         → payment diagnostics · PayPal
--   gp_diagnostic         → payment diagnostics · GooglePay
--   klarna_diagnostic     → payment diagnostics · Klarna
--   warehouselogistics_prod → BPP streaming events
-- =============================================================================

-- ---------------------------------------------------------------------------
-- BIS Hub — medallion layers
-- ---------------------------------------------------------------------------

CREATE DATABASE IF NOT EXISTS product_systems_raw
  COMMENT 'Bronze landing zone — raw ingests from ADLS Gen1 (wasb://) and Gen2 (abfss://). Contains nm_item_* and booking data as-landed with _ingestion_timestamp only.'
  LOCATION 'dbfs:/mnt/raw/product_systems_raw/'
  WITH DBPROPERTIES (
    'domain'     = 'BIS',
    'layer'      = 'bronze',
    'owner'      = 'data-engineering',
    'ucx_status' = 'blocker:wasb_uri'
  );

CREATE DATABASE IF NOT EXISTS product_systems
  COMMENT 'Curated / silver layer — conformed BIS product catalogue tables. Canonical post-rename schema (replacing productsystems).'
  LOCATION 'dbfs:/mnt/processing/product_systems/'
  WITH DBPROPERTIES (
    'domain'     = 'BIS',
    'layer'      = 'silver',
    'owner'      = 'data-engineering',
    'ucx_status' = 'assess:external_location_needed'
  );

CREATE DATABASE IF NOT EXISTS productsystems
  COMMENT 'LEGACY ALIAS — schema is being renamed to product_systems during UCX migration. Both schemas are live simultaneously; dual-read guard is in BISPipeline.conform_fact_sales_orders(). Do NOT write new pipelines to this schema.'
  LOCATION 'dbfs:/mnt/processing/productsystems/'
  WITH DBPROPERTIES (
    'domain'         = 'BIS',
    'layer'          = 'silver',
    'ucx_status'     = 'rename_in_flight',
    'rename_target'  = 'product_systems',
    'deprecated'     = 'true'
  );

CREATE DATABASE IF NOT EXISTS trusted
  COMMENT 'Trusted / gold serving layer — BIS star schema hub. dim_item (SCD2), fact_sales_orders, fact_return_rate_item. Downstream consumers and cross-catalog joins read from here.'
  LOCATION 'dbfs:/mnt/serving/trusted/'
  WITH DBPROPERTIES (
    'domain'     = 'BIS',
    'layer'      = 'gold',
    'owner'      = 'data-engineering',
    'ucx_status' = 'assess:external_location_needed'
  );

CREATE DATABASE IF NOT EXISTS refined
  COMMENT 'Refined / gold+ layer — seasonal aggregates and attribute denormalisation built on top of trusted.'
  LOCATION 'dbfs:/mnt/serving/refined/'
  WITH DBPROPERTIES (
    'domain'     = 'BIS',
    'layer'      = 'gold',
    'owner'      = 'data-engineering'
  );

CREATE DATABASE IF NOT EXISTS bismerged
  COMMENT 'BIS Merged — consolidated cross-domain views. Houses svoc_customers (Single View of Customer) joining BIS, payments, and logistics signals.'
  LOCATION 'dbfs:/mnt/serving/bismerged/'
  WITH DBPROPERTIES (
    'domain'     = 'BIS',
    'layer'      = 'gold',
    'owner'      = 'analytics-engineering'
  );

-- ---------------------------------------------------------------------------
-- Branded / Lipsy spoke
-- ---------------------------------------------------------------------------

CREATE DATABASE IF NOT EXISTS branded_prod
  COMMENT 'Branded / Lipsy spoke — receives 15 CTAS write-back materialised tables from BIS trusted/refined (attribution_* series). Also holds noclick_stock_levels sourced from wasb:// branded container.'
  LOCATION 'dbfs:/mnt/serving/branded_prod/'
  WITH DBPROPERTIES (
    'domain'     = 'Branded',
    'layer'      = 'spoke',
    'owner'      = 'branded-engineering',
    'ucx_status' = 'blocker:wasb_uri'
  );

-- ---------------------------------------------------------------------------
-- Generic ETL pipeline layers (from etl_config.json)
-- ---------------------------------------------------------------------------

CREATE DATABASE IF NOT EXISTS bronze
  COMMENT 'Generic ETL bronze layer — raw CSV extracts (customer_transactions, product_inventory) ingested via ETLPipeline.extract_raw_data().'
  LOCATION 'dbfs:/mnt/raw/'
  WITH DBPROPERTIES (
    'domain'  = 'Generic-ETL',
    'layer'   = 'bronze',
    'owner'   = 'data-engineering'
  );

CREATE DATABASE IF NOT EXISTS silver
  COMMENT 'Generic ETL silver layer — conformed tables from ETLPipeline.process_data() with quality checks and type casts applied.'
  LOCATION 'dbfs:/mnt/processing/'
  WITH DBPROPERTIES (
    'domain'  = 'Generic-ETL',
    'layer'   = 'silver',
    'owner'   = 'data-engineering'
  );

CREATE DATABASE IF NOT EXISTS gold
  COMMENT 'Generic ETL gold layer — aggregated serving tables from ETLPipeline.serve_data(). Also used for BIS gold saves (fact_sales_orders_daily).'
  LOCATION 'dbfs:/mnt/serving/'
  WITH DBPROPERTIES (
    'domain'  = 'Generic-ETL',
    'layer'   = 'gold',
    'owner'   = 'data-engineering'
  );

-- ---------------------------------------------------------------------------
-- Payment provider diagnostic catalogs (5 providers)
-- ---------------------------------------------------------------------------

CREATE DATABASE IF NOT EXISTS wp_diagnostic
  COMMENT 'WooPayments ad-hoc diagnostics — payment_events with raw JSON Payload column. Get_json_object() anti-pattern; scheduled for JSON_VALUE() migration in BigQuery.'
  LOCATION 'dbfs:/mnt/serving/diagnostics/wp/'
  WITH DBPROPERTIES (
    'domain'        = 'Payments',
    'provider'      = 'WooPayments',
    'layer'         = 'diagnostic',
    'owner'         = 'payments-engineering',
    'pii_risk'      = 'high:customer_email_in_payload',
    'ucx_status'    = 'assess'
  );

CREATE DATABASE IF NOT EXISTS ap_diagnostic
  COMMENT 'AmazonPay ad-hoc diagnostics — payment_events with raw JSON Payload column. Dispute and refund event types.'
  LOCATION 'dbfs:/mnt/serving/diagnostics/ap/'
  WITH DBPROPERTIES (
    'domain'   = 'Payments',
    'provider' = 'AmazonPay',
    'layer'    = 'diagnostic',
    'owner'    = 'payments-engineering',
    'pii_risk' = 'medium:order_reference_in_payload'
  );

CREATE DATABASE IF NOT EXISTS pp_diagnostic
  COMMENT 'PayPal ad-hoc diagnostics — payment_events with raw JSON Payload column. Failed transaction analysis.'
  LOCATION 'dbfs:/mnt/serving/diagnostics/pp/'
  WITH DBPROPERTIES (
    'domain'   = 'Payments',
    'provider' = 'PayPal',
    'layer'    = 'diagnostic',
    'owner'    = 'payments-engineering',
    'pii_risk' = 'high:payer_email_in_payload'
  );

CREATE DATABASE IF NOT EXISTS gp_diagnostic
  COMMENT 'GooglePay ad-hoc diagnostics — payment_events with raw JSON Payload column. Authorization rate analysis.'
  LOCATION 'dbfs:/mnt/serving/diagnostics/gp/'
  WITH DBPROPERTIES (
    'domain'   = 'Payments',
    'provider' = 'GooglePay',
    'layer'    = 'diagnostic',
    'owner'    = 'payments-engineering',
    'pii_risk' = 'low'
  );

CREATE DATABASE IF NOT EXISTS klarna_diagnostic
  COMMENT 'Klarna BNPL diagnostics — payment_events with raw JSON Payload column. Cross-domain settlement reconciliation against businessintelligencesystems_prod.trusted.fact_sales_orders.'
  LOCATION 'dbfs:/mnt/serving/diagnostics/klarna/'
  WITH DBPROPERTIES (
    'domain'         = 'Payments',
    'provider'       = 'Klarna',
    'layer'          = 'diagnostic',
    'owner'          = 'payments-engineering',
    'cross_catalog'  = 'businessintelligencesystems_prod.trusted.fact_sales_orders',
    'pii_risk'       = 'medium'
  );

-- ---------------------------------------------------------------------------
-- Warehouse Logistics (streaming domain)
-- ---------------------------------------------------------------------------

CREATE DATABASE IF NOT EXISTS warehouselogistics_prod
  COMMENT 'Warehouse / WMS domain — BPP parcel streaming events via Eventarc. Isolated domain; no downstream serving layer yet. Targeted for Dataflow migration in Phase 5.'
  LOCATION 'dbfs:/mnt/serving/warehouselogistics/'
  WITH DBPROPERTIES (
    'domain'     = 'WarehouseLogistics',
    'layer'      = 'streaming',
    'owner'      = 'logistics-engineering',
    'ucx_status' = 'assess:streaming_not_uc_compatible'
  );
