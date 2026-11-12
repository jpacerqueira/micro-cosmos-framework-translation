-- =============================================================================
-- bronze / silver / gold — Generic ETL Pipeline Layers
-- =============================================================================
-- These schemas are created by the generic ETLPipeline class (etl_pipeline.py)
-- and configured via etl_config.json. They serve the 6 tables in the standard
-- medallion pattern for the non-BIS domain tables.
--
-- Tables:
--   bronze.*    ← ETLPipeline.extract_raw_data()  (CSV/Parquet ingest)
--   silver.*    ← ETLPipeline.process_data()      (type casts + quality checks)
--   gold.*      ← ETLPipeline.serve_data()        (aggregations)
--
-- Also includes BISPipeline gold output:
--   gold.fact_sales_orders_daily    ← BISPipeline.serve_fact_sales_orders()
--   gold.item_season_performance    ← BISAnalytics.py cell 7
--   gold.payment_provider_summary   ← PaymentDiagnostics.py cell 6
-- =============================================================================

-- =============================================================================
-- SCHEMA: bronze  (raw ingest from CSV extracts)
-- =============================================================================

USE bronze;

-- ---------------------------------------------------------------------------
-- customer_transactions  (bronze — raw CSV ingest)
-- Source: /mnt/raw/extracts/customer_transactions/*.csv
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bronze.customer_transactions (
    -- Source columns (schema inferred from CSV)
    transaction_id      STRING          COMMENT 'Source transaction identifier.',
    customer_id         STRING          COMMENT 'Customer identifier (pre-anonymisation).',
    transaction_date    STRING          COMMENT 'Raw date string — cast to TIMESTAMP in silver.',
    amount              STRING          COMMENT 'Raw amount string — cast to DECIMAL in silver.',
    transaction_type    STRING          COMMENT 'Transaction type code.',
    channel             STRING          COMMENT 'Sales channel.',
    store_id            STRING          COMMENT 'Store or site identifier.',
    product_id          STRING          COMMENT 'Product / item reference.',
    status              STRING          COMMENT 'Transaction status.',
    -- Ingest metadata
    _ingestion_timestamp TIMESTAMP      COMMENT 'UTC ingest timestamp.',
    _source_file        STRING          COMMENT 'Source file path from input_file_name().'
)
USING PARQUET
COMMENT 'Raw customer transactions landed from CSV extract. All columns are STRING — types are enforced in silver.customer_transactions. Written by ETLPipeline.extract_raw_data().'
LOCATION 'dbfs:/mnt/raw/customer_transactions'
TBLPROPERTIES (
    'quality.layer'   = 'bronze',
    'source.format'   = 'csv',
    'source.path'     = '/mnt/raw/extracts/customer_transactions/'
);

-- ---------------------------------------------------------------------------
-- product_inventory  (bronze — raw CSV ingest)
-- Source: /mnt/raw/extracts/product_inventory/*.csv
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bronze.product_inventory (
    product_id          STRING          COMMENT 'Product identifier.',
    product_name        STRING          COMMENT 'Product display name.',
    product_category    STRING          COMMENT 'Category.',
    price               STRING          COMMENT 'Raw price string — cast to DECIMAL in silver.',
    quantity            STRING          COMMENT 'Raw quantity string — cast to INT in silver.',
    last_updated        STRING          COMMENT 'Raw last-updated string — cast to TIMESTAMP in silver.',
    supplier_id         STRING          COMMENT 'Supplier identifier.',
    warehouse_location  STRING          COMMENT 'Warehouse or bin location.',
    -- Ingest metadata
    _ingestion_timestamp TIMESTAMP      COMMENT 'UTC ingest timestamp.',
    _source_file        STRING          COMMENT 'Source file path.'
)
USING PARQUET
COMMENT 'Raw product inventory from CSV extract. All columns STRING. Types enforced in silver. Written by ETLPipeline.extract_raw_data().'
LOCATION 'dbfs:/mnt/raw/product_inventory'
TBLPROPERTIES (
    'quality.layer'   = 'bronze',
    'source.format'   = 'csv',
    'source.path'     = '/mnt/raw/extracts/product_inventory/'
);

-- =============================================================================
-- SCHEMA: silver  (conformed, type-cast, quality-checked)
-- =============================================================================

USE silver;

-- ---------------------------------------------------------------------------
-- customer_transactions  (silver — conformed)
-- etl_config.json transformations: transaction_date → TIMESTAMP, amount → DECIMAL(10,2), customer_id → STRING
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.customer_transactions (
    transaction_id      STRING          NOT NULL  COMMENT 'Transaction identifier.',
    customer_id         STRING          NOT NULL  COMMENT 'Customer identifier (STRING cast applied).',
    transaction_date    TIMESTAMP       NOT NULL  COMMENT 'Transaction datetime (TIMESTAMP cast, format yyyy-MM-dd HH:mm:ss).',
    amount              DECIMAL(10, 2)  NOT NULL  COMMENT 'Transaction amount GBP (DECIMAL cast).',
    transaction_type    STRING          COMMENT 'Transaction type code.',
    channel             STRING          COMMENT 'Sales channel.',
    store_id            STRING          COMMENT 'Store or site identifier.',
    product_id          STRING          COMMENT 'Product / item reference.',
    status              STRING          COMMENT 'Transaction status.',
    -- Silver metadata
    _processing_timestamp TIMESTAMP     COMMENT 'UTC silver processing timestamp.'
)
USING DELTA
COMMENT 'Conformed customer transactions. Type casts applied per etl_config.json. Quality check DataQualityChecker.run_quality_checks() must pass before write. Written by ETLPipeline.process_data().'
LOCATION 'dbfs:/mnt/processing/customer_transactions'
TBLPROPERTIES (
    'delta.minReaderVersion'           = '1',
    'delta.minWriterVersion'           = '2',
    'delta.enableChangeDataFeed'       = 'true',
    'quality.layer'                    = 'silver',
    'quality.checker'                  = 'DataQualityChecker.run_quality_checks',
    'delta.autoOptimize.optimizeWrite' = 'true'
);

-- ---------------------------------------------------------------------------
-- product_inventory  (silver — conformed)
-- etl_config.json transformations: last_updated → TIMESTAMP, price → DECIMAL(10,2), quantity → INT
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.product_inventory (
    product_id          STRING          NOT NULL  COMMENT 'Product identifier.',
    product_name        STRING          COMMENT 'Product display name.',
    product_category    STRING          COMMENT 'Category.',
    price               DECIMAL(10, 2)  COMMENT 'Price GBP (DECIMAL cast).',
    quantity            INT             COMMENT 'Stock quantity (INT cast).',
    last_updated        TIMESTAMP       COMMENT 'Last update (TIMESTAMP cast, format yyyy-MM-dd HH:mm:ss).',
    supplier_id         STRING          COMMENT 'Supplier identifier.',
    warehouse_location  STRING          COMMENT 'Warehouse location.',
    -- Silver metadata
    _processing_timestamp TIMESTAMP     COMMENT 'UTC silver processing timestamp.'
)
USING DELTA
COMMENT 'Conformed product inventory. Type casts per etl_config.json. Written by ETLPipeline.process_data() with mergeSchema=true.'
LOCATION 'dbfs:/mnt/processing/product_inventory'
TBLPROPERTIES (
    'delta.minReaderVersion'  = '1',
    'delta.minWriterVersion'  = '2',
    'delta.enableChangeDataFeed' = 'true',
    'quality.layer'           = 'silver',
    'delta.autoOptimize.optimizeWrite' = 'true'
);

-- ---------------------------------------------------------------------------
-- nm_item_supplier  (silver — from etl_config.json + BISPipeline)
-- etl_config.json transformations: created_date → TIMESTAMP, supplier_id/item_number → STRING
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.nm_item_supplier (
    item_number         STRING          NOT NULL  COMMENT 'Item identifier (STRING cast). FK → trusted.dim_item.ItemNumber.',
    supplier_id         STRING          NOT NULL  COMMENT 'Supplier identifier (STRING cast).',
    supplier_name       STRING          COMMENT 'Supplier display name.',
    lead_time_days      INT,
    cost_price          DECIMAL(10, 2),
    status              STRING          COMMENT 'ACTIVE | INACTIVE | PENDING.',
    created_date        TIMESTAMP       COMMENT 'Created date (TIMESTAMP cast).',
    _processing_timestamp TIMESTAMP     COMMENT 'UTC silver processing timestamp.'
)
USING DELTA
COMMENT 'Conformed item-supplier mapping from etl_config.json. Mirrors product_systems.nm_item_supplier for the generic ETL path. Written by ETLPipeline.process_data().'
LOCATION 'dbfs:/mnt/processing/nm_item_supplier'
TBLPROPERTIES ('delta.minReaderVersion' = '1', 'delta.minWriterVersion' = '2', 'quality.layer' = 'silver');

-- ---------------------------------------------------------------------------
-- item_season  (silver — from etl_config.json)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.item_season (
    item_number         STRING          NOT NULL  COMMENT 'Item identifier (STRING cast).',
    season_code         STRING          NOT NULL  COMMENT 'Season code.',
    season_start_date   TIMESTAMP       COMMENT 'Season start (TIMESTAMP cast, format yyyy-MM-dd).',
    season_end_date     TIMESTAMP       COMMENT 'Season end (TIMESTAMP cast, format yyyy-MM-dd).',
    _processing_timestamp TIMESTAMP     COMMENT 'UTC silver processing timestamp.'
)
USING DELTA
COMMENT 'Conformed item-season mapping from etl_config.json path. Written by ETLPipeline.process_data().'
LOCATION 'dbfs:/mnt/processing/item_season'
TBLPROPERTIES ('delta.minReaderVersion' = '1', 'delta.minWriterVersion' = '2', 'quality.layer' = 'silver');

-- ---------------------------------------------------------------------------
-- fact_sales_orders  (silver — from etl_config.json)
-- etl_config.json: order_date → TIMESTAMP, order_amount → DECIMAL(12,2), item_number/customer_id → STRING
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.fact_sales_orders (
    order_id            STRING          COMMENT 'Order identifier.',
    item_number         STRING          NOT NULL  COMMENT 'Item identifier (STRING cast). FK → trusted.dim_item.ItemNumber.',
    customer_id         STRING          NOT NULL  COMMENT 'Customer identifier (STRING cast).',
    order_date          TIMESTAMP       NOT NULL  COMMENT 'Order datetime (TIMESTAMP cast).',
    order_amount        DECIMAL(12, 2)  NOT NULL  COMMENT 'Order amount GBP (DECIMAL cast).',
    quantity            INT,
    channel_code        STRING,
    _processing_timestamp TIMESTAMP     COMMENT 'UTC silver processing timestamp.'
)
USING DELTA
COMMENT 'Conformed fact_sales_orders from etl_config.json. Type casts applied. Written by ETLPipeline.process_data().'
LOCATION 'dbfs:/mnt/processing/fact_sales_orders'
TBLPROPERTIES ('delta.minReaderVersion' = '1', 'delta.minWriterVersion' = '2', 'quality.layer' = 'silver', 'delta.enableChangeDataFeed' = 'true');

-- ---------------------------------------------------------------------------
-- dim_item  (silver — from etl_config.json)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS silver.dim_item (
    item_number         STRING          NOT NULL  COMMENT 'Item identifier (STRING cast).',
    product_category    STRING,
    brand_code          STRING,
    retail_price        DECIMAL(10, 2),
    effective_date      TIMESTAMP       COMMENT 'SCD2 effective date (TIMESTAMP cast, format yyyy-MM-dd).',
    expiry_date         TIMESTAMP       COMMENT 'SCD2 expiry date (TIMESTAMP cast, format yyyy-MM-dd).',
    _processing_timestamp TIMESTAMP     COMMENT 'UTC silver processing timestamp.'
)
USING DELTA
COMMENT 'Conformed dim_item from etl_config.json. Note: for SCD2 gold, use trusted.dim_item. This silver is the generic ETL path output.'
LOCATION 'dbfs:/mnt/processing/dim_item'
TBLPROPERTIES ('delta.minReaderVersion' = '1', 'delta.minWriterVersion' = '2', 'quality.layer' = 'silver');

-- =============================================================================
-- SCHEMA: gold  (aggregated, served — includes BIS and generic ETL outputs)
-- =============================================================================

USE gold;

-- ---------------------------------------------------------------------------
-- customer_transactions__daily_transactions  (gold — etl_config.json agg)
-- etl_config.json: group_by [customer_id, transaction_date], agg: total_amount, count, avg
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gold.customer_transactions__daily_transactions (
    customer_id             STRING          NOT NULL  COMMENT 'Customer identifier.',
    transaction_date        TIMESTAMP       NOT NULL  COMMENT 'Transaction date (grain).',
    total_amount            DECIMAL(12, 2)  COMMENT 'Sum of transaction amounts in GBP.',
    transaction_count       BIGINT          COMMENT 'Number of transactions.',
    avg_amount              DECIMAL(10, 2)  COMMENT 'Average transaction amount.',
    _serving_timestamp      TIMESTAMP       COMMENT 'UTC serving timestamp.'
)
USING DELTA
COMMENT 'Daily customer transaction aggregation. From etl_config.json daily_transactions aggregation. Written by ETLPipeline.serve_data().'
LOCATION 'dbfs:/mnt/serving/customer_transactions'
TBLPROPERTIES ('delta.minReaderVersion' = '1', 'delta.minWriterVersion' = '2', 'quality.layer' = 'gold');

-- ---------------------------------------------------------------------------
-- product_inventory__inventory_summary  (gold — etl_config.json agg)
-- etl_config.json: group_by [product_category], agg: total_quantity, total_value, count
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gold.product_inventory__inventory_summary (
    product_category    STRING          NOT NULL  COMMENT 'Product category (grain).',
    total_quantity      BIGINT          COMMENT 'Sum of stock quantity across all items.',
    total_value         DECIMAL(16, 2)  COMMENT 'Sum of price * quantity.',
    product_count       BIGINT          COMMENT 'Count of distinct product_ids.',
    _serving_timestamp  TIMESTAMP       COMMENT 'UTC serving timestamp.'
)
USING DELTA
COMMENT 'Category-level inventory summary. From etl_config.json inventory_summary aggregation.'
LOCATION 'dbfs:/mnt/serving/product_inventory'
TBLPROPERTIES ('delta.minReaderVersion' = '1', 'delta.minWriterVersion' = '2', 'quality.layer' = 'gold');

-- ---------------------------------------------------------------------------
-- fact_sales_orders_daily  (gold — BISPipeline.serve_fact_sales_orders)
-- Written with saveAsTable — managed table
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gold.fact_sales_orders_daily (
    item_number         STRING          NOT NULL  COMMENT 'Item identifier. FK → trusted.dim_item.ItemNumber.',
    order_date          DATE            NOT NULL  COMMENT 'Order date grain.',
    product_category    STRING          COMMENT 'Denormalised from dim_item.',
    brand_code          STRING          COMMENT 'Denormalised from dim_item.',
    total_revenue       DECIMAL(14, 2)  COMMENT 'Sum of order_amount in GBP.',
    order_count         BIGINT          COMMENT 'Number of distinct orders.',
    _serving_timestamp  TIMESTAMP       COMMENT 'UTC gold serving timestamp.'
)
USING DELTA
COMMENT 'Daily sales aggregation from BISPipeline.serve_fact_sales_orders(). Managed table (saveAsTable). Joins dim_item for category/brand denormalisation.'
TBLPROPERTIES (
    'delta.minReaderVersion'  = '1',
    'delta.minWriterVersion'  = '2',
    'quality.layer'           = 'gold',
    'managed_table'           = 'true'
);

-- ---------------------------------------------------------------------------
-- item_season_performance  (gold — BISAnalytics.py cell 7)
-- Written to /mnt/serving/gold/item_season_performance
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gold.item_season_performance (
    item_number         STRING          COMMENT 'FK → trusted.dim_item.ItemNumber.',
    season_code         STRING          COMMENT 'Season code.',
    product_category    STRING          COMMENT 'Denormalised from dim_item.',
    brand_code          STRING          COMMENT 'Denormalised from dim_item.',
    retail_price        DECIMAL(10, 2)  COMMENT 'Full retail price from dim_item.',
    order_count         BIGINT          COMMENT 'Total orders for this item in the season.',
    total_revenue       DECIMAL(14, 2)  COMMENT 'Total revenue GBP.',
    avg_order_value     DECIMAL(10, 2)  COMMENT 'Average order value.',
    _serving_timestamp  TIMESTAMP       COMMENT 'UTC gold serving timestamp.'
)
USING DELTA
COMMENT 'Item × season performance summary. Written by BISAnalytics.py to /mnt/serving/gold/item_season_performance. Joins dim_item + item_season + fact_sales_orders.'
LOCATION 'dbfs:/mnt/serving/gold/item_season_performance'
TBLPROPERTIES ('delta.minReaderVersion' = '1', 'delta.minWriterVersion' = '2', 'quality.layer' = 'gold');

-- ---------------------------------------------------------------------------
-- payment_provider_summary  (gold — PaymentDiagnostics.py cell 6)
-- Cross-provider aggregation of payment events across all 5 diagnostic catalogs
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS gold.payment_provider_summary (
    provider            STRING          NOT NULL  COMMENT 'Payment provider name (WooPayments | AmazonPay | PayPal | GooglePay | Klarna).',
    event_count         BIGINT          COMMENT 'Total events in the analysis window.',
    total_amount        DECIMAL(16, 2)  COMMENT 'Total payment amount in GBP (extracted from JSON Payload).',
    _serving_timestamp  TIMESTAMP       COMMENT 'UTC gold serving timestamp.'
)
USING DELTA
COMMENT 'Cross-provider payment summary. Written by PaymentDiagnostics.py cross_provider_df.write. Source: UNION ALL of all 5 payment_events tables. Uses get_json_object(Payload, ...) — translated to JSON_VALUE() on BigQuery.'
LOCATION 'dbfs:/mnt/serving/gold/payment_provider_summary'
TBLPROPERTIES (
    'delta.minReaderVersion'  = '1',
    'delta.minWriterVersion'  = '2',
    'quality.layer'           = 'gold',
    'cross_catalog.sources'   = 'wp_diagnostic,ap_diagnostic,pp_diagnostic,gp_diagnostic,klarna_diagnostic'
);
