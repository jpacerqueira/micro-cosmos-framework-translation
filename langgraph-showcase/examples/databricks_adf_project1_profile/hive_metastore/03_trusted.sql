-- =============================================================================
-- trusted — BIS Gold / Serving Layer (Star Schema Hub)
-- =============================================================================
-- The `trusted` schema is the primary read layer for analytics consumers and
-- cross-catalog joins. It contains the BIS product star schema:
--
--   dim_item           — Item dimension (SCD Type 2)
--   dim_item_team      — Buying team dimension
--   fact_sales_orders  — Sales order fact (daily grain)
--   fact_return_rate_item — Item-level return rate fact
--
-- Written by:
--   BISPipeline.serve_dim_item()          → trusted.dim_item
--   BISPipeline.serve_fact_sales_orders() → gold.fact_sales_orders_daily (see 07_gold.sql)
--   (legacy notebooks write directly to Delta path at /mnt/serving/trusted/)
--
-- Cross-catalog join point: branded_prod notebooks join ON dim_item.ItemNumber.
-- Payment cross-catalog: klarna_diagnostic joins ON fact_sales_orders.external_order_ref.
-- Delta time travel: BISAnalytics.py reads fact_sales_orders with timestampAsOf.
-- =============================================================================

USE trusted;

-- ---------------------------------------------------------------------------
-- dim_item  (Item Dimension — SCD Type 2)
-- Source: BISPipeline.serve_dim_item() — joins product_systems.item + nm_item_supplier
-- PK: ItemNumber (current record where IsCurrentRecord = TRUE)
-- Used by: fact_sales_orders, fact_return_rate_item, branded_prod.attribution_*
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trusted.dim_item (
    ItemSurrogateKey    BIGINT          NOT NULL  COMMENT 'SCD2 surrogate key — auto-incremented. Use for joins in fact tables.',
    ItemNumber          STRING          NOT NULL  COMMENT 'Natural item identifier from ERP. Current-record join key for cross-catalog queries.',
    ItemName            STRING          COMMENT 'Short display name.',
    ProductCategory     STRING          COMMENT 'Top-level product category (e.g. Womenswear).',
    SubCategory         STRING          COMMENT 'Sub-category (e.g. Dresses).',
    BrandCode           STRING          COMMENT 'Brand code (e.g. NM, LIPSY). Used in branded_prod CTAS write-backs.',
    BrandName           STRING          COMMENT 'Brand display name.',
    Department          STRING          COMMENT 'Buying department code.',
    ClassCode           STRING          COMMENT 'Merchandising class code.',
    TeamCode            STRING          COMMENT 'Buying team code. FK → trusted.dim_item_team.TeamCode.',
    SupplierID          STRING          COMMENT 'Primary supplier. FK → product_systems_raw.nm_supplier.SupplierID.',
    RetailPrice         DECIMAL(10, 2)  COMMENT 'Full retail price GBP at time of this SCD2 record.',
    CostPrice           DECIMAL(10, 2)  COMMENT 'Standard cost price GBP at time of this SCD2 record.',
    CountryOfOrigin     STRING          COMMENT 'ISO-3166 country of manufacturing origin.',
    IsActive            BOOLEAN         COMMENT 'Whether item was active at EffectiveDate.',
    -- SCD2 temporal columns
    EffectiveDate       DATE            NOT NULL  COMMENT 'Date from which this version of the item record is valid.',
    ExpiryDate          DATE            COMMENT 'Date on which this version expired (NULL = current record).',
    IsCurrentRecord     BOOLEAN         NOT NULL  COMMENT 'TRUE for the current active version of each ItemNumber.',
    -- Gold metadata
    _serving_timestamp  TIMESTAMP       COMMENT 'UTC timestamp when this record was written to gold.'
)
USING DELTA
COMMENT 'Item dimension SCD Type 2. One current row per ItemNumber (IsCurrentRecord=TRUE) plus historical rows. Primary lookup for all BIS fact tables and branded_prod write-backs. Join key: ItemNumber for cross-catalog queries.'
LOCATION 'dbfs:/mnt/serving/trusted/dim_item'
TBLPROPERTIES (
    'delta.minReaderVersion'           = '1',
    'delta.minWriterVersion'           = '2',
    'delta.enableChangeDataFeed'       = 'true',
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'quality.layer'                    = 'gold',
    'scd.type'                         = '2',
    'cross_catalog.join_key'           = 'ItemNumber',
    'cross_catalog.referenced_by'      = 'branded_prod,klarna_diagnostic'
);

-- ---------------------------------------------------------------------------
-- dim_item_team  (Buying Team Dimension)
-- Source: buying team master from ERP
-- PK: TeamCode
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trusted.dim_item_team (
    TeamCode            STRING          NOT NULL  COMMENT 'Primary key. Buying team identifier (e.g. BT001).',
    TeamName            STRING          COMMENT 'Team display name (e.g. Womenswear Dresses).',
    DivisionCode        STRING          COMMENT 'Division above team (e.g. Womenswear).',
    DivisionName        STRING          COMMENT 'Division display name.',
    DirectorName        STRING          COMMENT 'Buying director for this team.',
    IsActive            BOOLEAN         COMMENT 'Whether this team is currently active.',
    EffectiveDate       DATE            COMMENT 'Date team structure became effective.',
    -- Gold metadata
    _serving_timestamp  TIMESTAMP       COMMENT 'UTC serving timestamp.'
)
USING DELTA
COMMENT 'Buying team dimension — organisational hierarchy above dim_item. TeamCode is used in item_season for team-level season attribution.'
LOCATION 'dbfs:/mnt/serving/trusted/dim_item_team'
TBLPROPERTIES (
    'delta.minReaderVersion'  = '1',
    'delta.minWriterVersion'  = '2',
    'quality.layer'           = 'gold'
);

-- ---------------------------------------------------------------------------
-- fact_sales_orders  (Sales Orders Fact — daily grain)
-- Source: BISPipeline.conform_fact_sales_orders() + serve_fact_sales_orders()
-- Grain: one row per order line (OrderID, ItemNumber)
-- PK: OrderID + ItemNumber + OrderDate
-- FK: ItemNumber → dim_item.ItemNumber (or dim_item.ItemSurrogateKey for SCD2)
-- Delta time travel: BISAnalytics.py reads this with timestampAsOf (report_date)
-- Cross-catalog: klarna_diagnostic.payment_events joins ON external_order_ref
-- =============================================================================
-- NOTE: BISPipeline.conform_fact_sales_orders() includes a dual-read guard for
-- the schema rename: tries `product_systems` first, falls back to `productsystems`.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trusted.fact_sales_orders (
    OrderID             STRING          NOT NULL  COMMENT 'Order identifier from OMS.',
    OrderLineID         STRING          COMMENT 'Order line sub-identifier (for multi-item orders).',
    ItemNumber          STRING          NOT NULL  COMMENT 'FK → dim_item.ItemNumber (current-record join).',
    ItemSurrogateKey    BIGINT          COMMENT 'FK → dim_item.ItemSurrogateKey (SCD2 point-in-time join — preferred for historical analysis).',
    CustomerID          STRING          COMMENT 'Anonymised customer identifier.',
    OrderDate           DATE            NOT NULL  COMMENT 'Date of order placement (partition key).',
    OrderAmount         DECIMAL(12, 2)  NOT NULL  COMMENT 'Order line amount in GBP.',
    Quantity            INT             COMMENT 'Units ordered.',
    ChannelCode         STRING          COMMENT 'Sales channel (ONLINE | STORE | APP | MARKETPLACE).',
    PromoCode           STRING          COMMENT 'Applied promotional code (NULL if none).',
    DiscountAmount      DECIMAL(10, 2)  COMMENT 'Discount applied in GBP.',
    DeliveryMethodCode  STRING          COMMENT 'Delivery method (STANDARD | EXPRESS | CLICK_COLLECT).',
    ExternalOrderRef    STRING          COMMENT 'External payment provider order reference. Used for cross-catalog join: klarna_diagnostic.payment_events.Payload->order_id.',
    ReturnFlag          BOOLEAN         COMMENT 'TRUE if this order line was subsequently returned.',
    ReturnDate          DATE            COMMENT 'Return date (NULL if not returned).',
    -- Gold metadata
    _processing_timestamp TIMESTAMP     COMMENT 'UTC silver processing timestamp.',
    _serving_timestamp    TIMESTAMP     COMMENT 'UTC gold serving timestamp.'
)
USING DELTA
COMMENT 'Sales orders fact table. Daily grain — one row per order line. Supports Delta time travel (timestampAsOf) for season-window analysis. Partition on OrderDate for performance. ExternalOrderRef links to payment provider catalogs.'
LOCATION 'dbfs:/mnt/serving/trusted/fact_sales_orders'
PARTITIONED BY (OrderDate)
TBLPROPERTIES (
    'delta.minReaderVersion'             = '1',
    'delta.minWriterVersion'             = '2',
    'delta.enableChangeDataFeed'         = 'true',
    'delta.autoOptimize.optimizeWrite'   = 'true',
    'delta.autoOptimize.autoCompact'     = 'true',
    'delta.logRetentionDuration'         = 'interval 90 days',
    'delta.deletedFileRetentionDuration' = 'interval 7 days',
    'quality.layer'                      = 'gold',
    'cross_catalog.join_key'             = 'ExternalOrderRef',
    'cross_catalog.referenced_by'        = 'klarna_diagnostic.payment_events'
);

-- ---------------------------------------------------------------------------
-- fact_return_rate_item  (Item Return Rate Fact)
-- Source: derived from fact_sales_orders + return events
-- Grain: one row per item per week
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trusted.fact_return_rate_item (
    ItemNumber          STRING          NOT NULL  COMMENT 'FK → dim_item.ItemNumber.',
    WeekStartDate       DATE            NOT NULL  COMMENT 'ISO week start date (partition key).',
    TotalUnitsSold      INT             COMMENT 'Total units sold in the week.',
    TotalUnitsReturned  INT             COMMENT 'Total units returned in the week.',
    ReturnRatePct       DECIMAL(5, 2)   COMMENT 'Return rate percentage (TotalUnitsReturned / TotalUnitsSold * 100).',
    ReturnReasonTop     STRING          COMMENT 'Most frequent return reason code for this item-week.',
    -- Gold metadata
    _serving_timestamp  TIMESTAMP       COMMENT 'UTC gold serving timestamp.'
)
USING DELTA
COMMENT 'Weekly item return rate fact. Grain: ItemNumber × WeekStartDate. Input for attribution_return_rate CTAS write-back to branded_prod.'
LOCATION 'dbfs:/mnt/serving/trusted/fact_return_rate_item'
PARTITIONED BY (WeekStartDate)
TBLPROPERTIES (
    'delta.minReaderVersion'  = '1',
    'delta.minWriterVersion'  = '2',
    'quality.layer'           = 'gold',
    'delta.autoOptimize.optimizeWrite' = 'true'
);
