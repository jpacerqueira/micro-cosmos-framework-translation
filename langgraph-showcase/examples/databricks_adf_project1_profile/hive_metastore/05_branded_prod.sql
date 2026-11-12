-- =============================================================================
-- branded_prod — Branded / Lipsy Spoke
-- =============================================================================
-- The `branded_prod` schema is the write-back target for the 15 CTAS
-- materialisation jobs driven by BISPipeline.materialise_attribution_targets().
-- It also holds noclick_stock_levels sourced from the branded container on
-- Azure Blob Storage (wasb://).
--
-- CTAS pattern:
--   BIS trusted/refined → (cross-catalog join) → branded_prod.attribution_*
--   15 targets per season run. Each is a full overwrite per season.
--
-- Cross-catalog join:
--   BISAnalytics.py joins branded_prod.noclick_stock_levels
--   ON trusted.dim_item.ItemNumber = branded_prod.noclick_stock_levels.ItemNumber
--
-- UCX status: wasb:// source is a hard-blocker for the noclick feed.
-- =============================================================================

USE branded_prod;

-- ---------------------------------------------------------------------------
-- noclick_stock_levels  (Stock positions from Branded spoke)
-- Source: wasb://branded-container@retailstorage.blob.core.windows.net/noclick_stock_levels
-- This table is the hub-and-spoke join target referenced in BISAnalytics.py.
-- UCX BLOCKER: wasb:// source must be migrated to abfss:// before UC promotion.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS branded_prod.noclick_stock_levels (
    ItemNumber          STRING          NOT NULL  COMMENT 'Join key to trusted.dim_item.ItemNumber. Cross-catalog FK.',
    WarehouseLocation   STRING          COMMENT 'Warehouse location code (e.g. LDN-01, MCR-02).',
    StockLevel          INT             COMMENT 'Current on-hand stock units.',
    ReservedUnits       INT             COMMENT 'Units reserved for pending orders.',
    AvailableUnits      INT             COMMENT 'StockLevel minus ReservedUnits.',
    ReorderLevel        INT             COMMENT 'Reorder trigger threshold.',
    LastCountDate       DATE            COMMENT 'Date of last physical stock count.',
    StockStatus         STRING          COMMENT 'Derived: OUT_OF_STOCK | LOW_STOCK | IN_STOCK.',
    -- Metadata
    _ingestion_timestamp TIMESTAMP      COMMENT 'UTC ingest timestamp from wasb:// Parquet landing.'
)
USING DELTA
COMMENT 'Branded spoke stock positions. Sourced from wasb:// (UCX blocker). Join key: ItemNumber to trusted.dim_item. Read by BISAnalytics.py for cross-catalog stock-vs-sales analysis.'
LOCATION 'dbfs:/mnt/serving/branded_prod/noclick_stock_levels'
TBLPROPERTIES (
    'delta.minReaderVersion'  = '1',
    'delta.minWriterVersion'  = '2',
    'quality.layer'           = 'spoke',
    'source.uri.scheme'       = 'wasb',
    'ucx.blocker'             = 'wasb_uri_not_uc_compatible',
    'cross_catalog.join_key'  = 'ItemNumber',
    'cross_catalog.joins_to'  = 'trusted.dim_item'
);

-- ---------------------------------------------------------------------------
-- attribution_item_season  (Season-level item attribution)
-- CTAS write-back target #1 of 15
-- Source: refined.fact_sales_orders_season × trusted.dim_item × product_systems.item_season
-- Written by BISPipeline.materialise_attribution_targets(season_code)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS branded_prod.attribution_item_season (
    ItemNumber          STRING          NOT NULL  COMMENT 'FK → trusted.dim_item.ItemNumber.',
    SeasonCode          STRING          NOT NULL  COMMENT 'Season code. Partition key and grouping.',
    ProductCategory     STRING          COMMENT 'Denormalised from dim_item.',
    BrandCode           STRING          COMMENT 'Denormalised from dim_item.',
    SeasonRevenue       DECIMAL(14, 2)  COMMENT 'Total revenue within season window in GBP.',
    UniqueCustomers     INT             COMMENT 'Distinct customers who purchased in season.',
    PreSeasonCutoff     DATE            COMMENT 'Pre-season analysis cutoff date (7 days before SeasonEndDate).',
    -- Attribution metadata
    _generated_at       TIMESTAMP       COMMENT 'UTC timestamp of this materialisation run.',
    _season_run         STRING          COMMENT 'Season code that triggered this write-back.'
)
USING DELTA
COMMENT 'Season-level item attribution — CTAS write-back target 1/15. Materialised by BISPipeline.materialise_attribution_targets(). Full overwrite per season_code run.'
LOCATION 'dbfs:/mnt/serving/branded_prod/attribution_item_season'
PARTITIONED BY (SeasonCode)
TBLPROPERTIES (
    'delta.minReaderVersion'      = '1',
    'delta.minWriterVersion'      = '2',
    'quality.layer'               = 'spoke',
    'ctas.writeback_target'       = 'true',
    'ctas.writeback_number'       = '1',
    'ctas.source_class'           = 'BISPipeline.materialise_attribution_targets',
    'delta.autoOptimize.optimizeWrite' = 'true'
);

-- ---------------------------------------------------------------------------
-- Common column template for all 15 attribution_* tables:
--   ItemNumber STRING, SeasonCode STRING, ProductCategory STRING,
--   BrandCode STRING, [metric columns specific to each target],
--   _generated_at TIMESTAMP, _season_run STRING
-- The 14 tables below share this structure with domain-specific metric columns.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS branded_prod.attribution_item_team (
    ItemNumber          STRING          NOT NULL  COMMENT 'FK → trusted.dim_item.ItemNumber.',
    SeasonCode          STRING          NOT NULL  COMMENT 'Season code.',
    TeamCode            STRING          COMMENT 'FK → trusted.dim_item_team.TeamCode.',
    TeamName            STRING          COMMENT 'Buying team name.',
    TeamRevenue         DECIMAL(14, 2)  COMMENT 'Revenue attributable to this buying team.',
    TeamUnitsSold       INT             COMMENT 'Units sold attributable to this team.',
    TeamSeasonRank      INT             COMMENT 'Rank of item within team by revenue.',
    _generated_at       TIMESTAMP       COMMENT 'UTC materialisation timestamp.',
    _season_run         STRING          COMMENT 'Season trigger.'
)
USING DELTA
COMMENT 'Item attribution by buying team — CTAS write-back target 2/15.'
LOCATION 'dbfs:/mnt/serving/branded_prod/attribution_item_team'
PARTITIONED BY (SeasonCode)
TBLPROPERTIES ('quality.layer' = 'spoke', 'ctas.writeback_target' = 'true', 'ctas.writeback_number' = '2', 'delta.minReaderVersion' = '1', 'delta.minWriterVersion' = '2');

CREATE TABLE IF NOT EXISTS branded_prod.attribution_item_brand (
    ItemNumber          STRING          NOT NULL,
    SeasonCode          STRING          NOT NULL,
    BrandCode           STRING          COMMENT 'FK → trusted.dim_item.BrandCode.',
    BrandRevenue        DECIMAL(14, 2)  COMMENT 'Revenue attributable to brand.',
    BrandSharePct       DECIMAL(5, 2)   COMMENT 'Brand share of total season revenue.',
    _generated_at       TIMESTAMP,
    _season_run         STRING
)
USING DELTA
COMMENT 'Item attribution by brand — CTAS write-back target 3/15.'
LOCATION 'dbfs:/mnt/serving/branded_prod/attribution_item_brand'
PARTITIONED BY (SeasonCode)
TBLPROPERTIES ('quality.layer' = 'spoke', 'ctas.writeback_target' = 'true', 'ctas.writeback_number' = '3', 'delta.minReaderVersion' = '1', 'delta.minWriterVersion' = '2');

CREATE TABLE IF NOT EXISTS branded_prod.attribution_sales_weekly (
    ItemNumber          STRING          NOT NULL,
    SeasonCode          STRING          NOT NULL,
    WeekStartDate       DATE            NOT NULL  COMMENT 'ISO week start date.',
    WeekRevenue         DECIMAL(12, 2)  COMMENT 'Revenue for this week.',
    WeekUnitsSold       INT,
    WeekOnWeekGrowth    DECIMAL(6, 2)   COMMENT 'WoW revenue growth percentage.',
    _generated_at       TIMESTAMP,
    _season_run         STRING
)
USING DELTA
COMMENT 'Weekly sales attribution — CTAS write-back target 4/15.'
LOCATION 'dbfs:/mnt/serving/branded_prod/attribution_sales_weekly'
PARTITIONED BY (SeasonCode)
TBLPROPERTIES ('quality.layer' = 'spoke', 'ctas.writeback_target' = 'true', 'ctas.writeback_number' = '4', 'delta.minReaderVersion' = '1', 'delta.minWriterVersion' = '2');

CREATE TABLE IF NOT EXISTS branded_prod.attribution_sales_monthly (
    ItemNumber          STRING          NOT NULL,
    SeasonCode          STRING          NOT NULL,
    YearMonth           STRING          NOT NULL  COMMENT 'YYYY-MM period key.',
    MonthRevenue        DECIMAL(12, 2),
    MonthUnitsSold      INT,
    MonthOnMonthGrowth  DECIMAL(6, 2)   COMMENT 'MoM revenue growth percentage.',
    _generated_at       TIMESTAMP,
    _season_run         STRING
)
USING DELTA
COMMENT 'Monthly sales attribution — CTAS write-back target 5/15.'
LOCATION 'dbfs:/mnt/serving/branded_prod/attribution_sales_monthly'
PARTITIONED BY (SeasonCode)
TBLPROPERTIES ('quality.layer' = 'spoke', 'ctas.writeback_target' = 'true', 'ctas.writeback_number' = '5', 'delta.minReaderVersion' = '1', 'delta.minWriterVersion' = '2');

CREATE TABLE IF NOT EXISTS branded_prod.attribution_return_rate (
    ItemNumber          STRING          NOT NULL,
    SeasonCode          STRING          NOT NULL,
    ReturnRatePct       DECIMAL(5, 2)   COMMENT 'Season return rate. Source: trusted.fact_return_rate_item.',
    TopReturnReason     STRING          COMMENT 'Most frequent return reason code in the season.',
    ReturnCostGbp       DECIMAL(10, 2)  COMMENT 'Estimated cost of returns in GBP.',
    _generated_at       TIMESTAMP,
    _season_run         STRING
)
USING DELTA
COMMENT 'Item return rate attribution — CTAS write-back target 6/15.'
LOCATION 'dbfs:/mnt/serving/branded_prod/attribution_return_rate'
PARTITIONED BY (SeasonCode)
TBLPROPERTIES ('quality.layer' = 'spoke', 'ctas.writeback_target' = 'true', 'ctas.writeback_number' = '6', 'delta.minReaderVersion' = '1', 'delta.minWriterVersion' = '2');

CREATE TABLE IF NOT EXISTS branded_prod.attribution_stock_cover (
    ItemNumber          STRING          NOT NULL,
    SeasonCode          STRING          NOT NULL,
    AvgStockLevel       DECIMAL(10, 2)  COMMENT 'Average stock on-hand over the season. Source: noclick_stock_levels.',
    MinStockLevel       INT,
    MaxStockLevel       INT,
    StockCoverWeeks     DECIMAL(5, 2)   COMMENT 'Weeks of cover at average sell-through rate.',
    OutOfStockDays      INT             COMMENT 'Number of days item was out of stock.',
    _generated_at       TIMESTAMP,
    _season_run         STRING
)
USING DELTA
COMMENT 'Stock cover attribution — CTAS write-back target 7/15. Joins noclick_stock_levels.'
LOCATION 'dbfs:/mnt/serving/branded_prod/attribution_stock_cover'
PARTITIONED BY (SeasonCode)
TBLPROPERTIES ('quality.layer' = 'spoke', 'ctas.writeback_target' = 'true', 'ctas.writeback_number' = '7', 'delta.minReaderVersion' = '1', 'delta.minWriterVersion' = '2');

CREATE TABLE IF NOT EXISTS branded_prod.attribution_forecast_accuracy (
    ItemNumber          STRING          NOT NULL,
    SeasonCode          STRING          NOT NULL,
    ForecastedUnits     INT             COMMENT 'Buyer forecast from nm_booking_report.BuyQuantity.',
    ActualUnitsSold     INT,
    ForecastAccuracyPct DECIMAL(5, 2)   COMMENT '(ActualUnitsSold / ForecastedUnits) * 100.',
    ForecastBias        DECIMAL(8, 0)   COMMENT 'ActualUnitsSold - ForecastedUnits (+ = under-buy).',
    _generated_at       TIMESTAMP,
    _season_run         STRING
)
USING DELTA
COMMENT 'Forecast accuracy attribution — CTAS write-back target 8/15.'
LOCATION 'dbfs:/mnt/serving/branded_prod/attribution_forecast_accuracy'
PARTITIONED BY (SeasonCode)
TBLPROPERTIES ('quality.layer' = 'spoke', 'ctas.writeback_target' = 'true', 'ctas.writeback_number' = '8', 'delta.minReaderVersion' = '1', 'delta.minWriterVersion' = '2');

CREATE TABLE IF NOT EXISTS branded_prod.attribution_supplier_lead_time (
    ItemNumber          STRING          NOT NULL,
    SeasonCode          STRING          NOT NULL,
    SupplierID          STRING          COMMENT 'FK → product_systems_raw.nm_supplier.SupplierID.',
    AvgLeadTimeDays     DECIMAL(5, 1),
    MaxLeadTimeDays     INT,
    OnTimeDeliveryPct   DECIMAL(5, 2),
    _generated_at       TIMESTAMP,
    _season_run         STRING
)
USING DELTA
COMMENT 'Supplier lead time attribution — CTAS write-back target 9/15.'
LOCATION 'dbfs:/mnt/serving/branded_prod/attribution_supplier_lead_time'
PARTITIONED BY (SeasonCode)
TBLPROPERTIES ('quality.layer' = 'spoke', 'ctas.writeback_target' = 'true', 'ctas.writeback_number' = '9', 'delta.minReaderVersion' = '1', 'delta.minWriterVersion' = '2');

CREATE TABLE IF NOT EXISTS branded_prod.attribution_noclick_opportunity (
    ItemNumber          STRING          NOT NULL,
    SeasonCode          STRING          NOT NULL,
    NoclickStockUnits   INT             COMMENT 'Units available at noclick warehouse.',
    EstimatedRevLoss    DECIMAL(10, 2)  COMMENT 'Revenue lost due to out-of-stock days.',
    OpportunityScore    DECIMAL(5, 2)   COMMENT 'Composite score (0-100) for stock replenishment priority.',
    _generated_at       TIMESTAMP,
    _season_run         STRING
)
USING DELTA
COMMENT 'Noclick stock opportunity attribution — CTAS write-back target 10/15.'
LOCATION 'dbfs:/mnt/serving/branded_prod/attribution_noclick_opportunity'
PARTITIONED BY (SeasonCode)
TBLPROPERTIES ('quality.layer' = 'spoke', 'ctas.writeback_target' = 'true', 'ctas.writeback_number' = '10', 'delta.minReaderVersion' = '1', 'delta.minWriterVersion' = '2');

CREATE TABLE IF NOT EXISTS branded_prod.attribution_svoc_segment (
    ItemNumber          STRING          NOT NULL,
    SeasonCode          STRING          NOT NULL,
    CustomerSegment     STRING          COMMENT 'RFM segment (from bismerged.svoc_customers).',
    SegmentRevenue      DECIMAL(12, 2),
    SegmentOrderCount   INT,
    SegmentSharePct     DECIMAL(5, 2)   COMMENT 'Segment share of item total revenue.',
    _generated_at       TIMESTAMP,
    _season_run         STRING
)
USING DELTA
COMMENT 'SVOC customer segment attribution — CTAS write-back target 11/15. Source includes bismerged.svoc_customers.'
LOCATION 'dbfs:/mnt/serving/branded_prod/attribution_svoc_segment'
PARTITIONED BY (SeasonCode)
TBLPROPERTIES ('quality.layer' = 'spoke', 'ctas.writeback_target' = 'true', 'ctas.writeback_number' = '11', 'delta.minReaderVersion' = '1', 'delta.minWriterVersion' = '2');

CREATE TABLE IF NOT EXISTS branded_prod.attribution_price_elasticity (
    ItemNumber          STRING          NOT NULL,
    SeasonCode          STRING          NOT NULL,
    PricePoint          DECIMAL(8, 2),
    UnitsAtPrice        INT,
    RevenueAtPrice      DECIMAL(12, 2),
    ElasticityCoeff     DECIMAL(6, 4)   COMMENT 'Price elasticity coefficient (negative = elastic).',
    _generated_at       TIMESTAMP,
    _season_run         STRING
)
USING DELTA
COMMENT 'Price elasticity attribution — CTAS write-back target 12/15.'
LOCATION 'dbfs:/mnt/serving/branded_prod/attribution_price_elasticity'
PARTITIONED BY (SeasonCode)
TBLPROPERTIES ('quality.layer' = 'spoke', 'ctas.writeback_target' = 'true', 'ctas.writeback_number' = '12', 'delta.minReaderVersion' = '1', 'delta.minWriterVersion' = '2');

CREATE TABLE IF NOT EXISTS branded_prod.attribution_channel_mix (
    ItemNumber          STRING          NOT NULL,
    SeasonCode          STRING          NOT NULL,
    ChannelCode         STRING          COMMENT 'Sales channel (ONLINE | STORE | APP | MARKETPLACE).',
    ChannelRevenue      DECIMAL(12, 2),
    ChannelUnitsSold    INT,
    ChannelSharePct     DECIMAL(5, 2)   COMMENT 'Channel share of item total revenue in season.',
    _generated_at       TIMESTAMP,
    _season_run         STRING
)
USING DELTA
COMMENT 'Sales channel mix attribution — CTAS write-back target 13/15.'
LOCATION 'dbfs:/mnt/serving/branded_prod/attribution_channel_mix'
PARTITIONED BY (SeasonCode)
TBLPROPERTIES ('quality.layer' = 'spoke', 'ctas.writeback_target' = 'true', 'ctas.writeback_number' = '13', 'delta.minReaderVersion' = '1', 'delta.minWriterVersion' = '2');

CREATE TABLE IF NOT EXISTS branded_prod.attribution_markdown_impact (
    ItemNumber          STRING          NOT NULL,
    SeasonCode          STRING          NOT NULL,
    MarkdownDate        DATE            COMMENT 'Date first markdown was applied.',
    FullPriceRevenue    DECIMAL(12, 2)  COMMENT 'Revenue generated at full retail price.',
    MarkdownRevenue     DECIMAL(12, 2)  COMMENT 'Revenue generated after markdown.',
    AvgDiscountPct      DECIMAL(5, 2)   COMMENT 'Average discount depth applied.',
    LiftFromMarkdown    DECIMAL(5, 2)   COMMENT 'Volume uplift percentage due to markdown.',
    _generated_at       TIMESTAMP,
    _season_run         STRING
)
USING DELTA
COMMENT 'Markdown impact attribution — CTAS write-back target 14/15.'
LOCATION 'dbfs:/mnt/serving/branded_prod/attribution_markdown_impact'
PARTITIONED BY (SeasonCode)
TBLPROPERTIES ('quality.layer' = 'spoke', 'ctas.writeback_target' = 'true', 'ctas.writeback_number' = '14', 'delta.minReaderVersion' = '1', 'delta.minWriterVersion' = '2');

CREATE TABLE IF NOT EXISTS branded_prod.attribution_new_season_launch (
    ItemNumber          STRING          NOT NULL,
    SeasonCode          STRING          NOT NULL,
    LaunchWeekRevenue   DECIMAL(12, 2)  COMMENT 'Revenue in the first 7 days of season.',
    LaunchWeekUnits     INT,
    LaunchVsPriorSeason DECIMAL(6, 2)   COMMENT 'Launch week revenue vs same item prior season.',
    IsNewToRange        BOOLEAN         COMMENT 'TRUE if item did not exist in prior season.',
    _generated_at       TIMESTAMP,
    _season_run         STRING
)
USING DELTA
COMMENT 'New season launch attribution — CTAS write-back target 15/15.'
LOCATION 'dbfs:/mnt/serving/branded_prod/attribution_new_season_launch'
PARTITIONED BY (SeasonCode)
TBLPROPERTIES ('quality.layer' = 'spoke', 'ctas.writeback_target' = 'true', 'ctas.writeback_number' = '15', 'delta.minReaderVersion' = '1', 'delta.minWriterVersion' = '2');
