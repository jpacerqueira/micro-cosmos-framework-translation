-- =============================================================================
-- refined + bismerged — Refined Gold+ and Consolidated Layers
-- =============================================================================
-- refined:   Seasonal aggregates and attribute denormalisation on top of trusted.
--            Built for campaign and attribution analytics — feeds the branded_prod
--            CTAS write-back pipeline.
--
-- bismerged: Consolidated cross-domain layer. Houses svoc_customers — the Single
--            View of Customer joining BIS, payment, and logistics signals.
--            Currently an orphan (no active downstream); flagged in lineage as
--            needing cross-domain wiring before Phase 3 go-live.
-- =============================================================================

-- =============================================================================
-- SCHEMA: refined
-- =============================================================================

USE refined;

-- ---------------------------------------------------------------------------
-- fact_sales_orders_season  (Seasonal Sales Aggregation)
-- Source: trusted.fact_sales_orders × product_systems.item_season (seasonal join)
-- Grain: one row per ItemNumber × SeasonCode
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS refined.fact_sales_orders_season (
    ItemNumber          STRING          NOT NULL  COMMENT 'FK → trusted.dim_item.ItemNumber.',
    SeasonCode          STRING          NOT NULL  COMMENT 'FK → product_systems.item_season.SeasonCode (partition key).',
    ProductCategory     STRING          COMMENT 'Denormalised from dim_item for performance.',
    BrandCode           STRING          COMMENT 'Denormalised from dim_item.',
    TeamCode            STRING          COMMENT 'Denormalised from dim_item_team.',
    SeasonRevenue       DECIMAL(14, 2)  COMMENT 'Total order revenue within the season window in GBP.',
    SeasonUnitsSold     INT             COMMENT 'Total units sold within the season window.',
    UniqueCustomers     INT             COMMENT 'Count of distinct CustomerIDs in the season.',
    UniqueOrders        INT             COMMENT 'Count of distinct OrderIDs in the season.',
    AvgOrderValue       DECIMAL(10, 2)  COMMENT 'Average order line value in the season.',
    ReturnRatePct       DECIMAL(5, 2)   COMMENT 'Season-level return rate percentage.',
    PreSeasonRevenue    DECIMAL(14, 2)  COMMENT 'Revenue in the 7-day pre-season window (DATEADD equivalent).',
    -- Attribution base columns (populated for CTAS write-back to branded_prod)
    SeasonRank          INT             COMMENT 'Rank of this item by SeasonRevenue within BrandCode.',
    IsTopPerformer      BOOLEAN         COMMENT 'TRUE if SeasonRank <= 10 within category.',
    -- Gold metadata
    _generated_at       TIMESTAMP       COMMENT 'UTC timestamp of this aggregation run.'
)
USING DELTA
COMMENT 'Seasonal sales aggregation. One row per ItemNumber-SeasonCode. Primary input for BISPipeline.materialise_attribution_targets() and the 15 CTAS write-back tables in branded_prod.'
LOCATION 'dbfs:/mnt/serving/refined/fact_sales_orders_season'
PARTITIONED BY (SeasonCode)
TBLPROPERTIES (
    'delta.minReaderVersion'           = '1',
    'delta.minWriterVersion'           = '2',
    'delta.enableChangeDataFeed'       = 'true',
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'quality.layer'                    = 'refined',
    'feeds'                            = 'branded_prod.attribution_item_season,branded_prod.attribution_sales_weekly,branded_prod.attribution_sales_monthly'
);

-- ---------------------------------------------------------------------------
-- dim_item_attribute  (Item Attribute Denormalised)
-- Source: product_systems.item + nm_item_detail options merged
-- Used for campaign targeting and stock analysis
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS refined.dim_item_attribute (
    ItemNumber          STRING          NOT NULL  COMMENT 'FK → trusted.dim_item.ItemNumber.',
    OptionCode          STRING          NOT NULL  COMMENT 'FK → product_systems.nm_item_option.OptionCode.',
    ColourCode          STRING          COMMENT 'Colour code.',
    ColourFamily        STRING          COMMENT 'Colour family grouping (e.g. Blues, Neutrals) — derived from ColourCode.',
    SizeCode            STRING          COMMENT 'Size.',
    SizeGroup           STRING          COMMENT 'Size group (e.g. 6-10 = XS-S range).',
    FabricContent       STRING          COMMENT 'Fabric composition.',
    IsVegan             BOOLEAN         COMMENT 'Inferred from fabric content — no animal products.',
    IsSustainable       BOOLEAN         COMMENT 'Marked sustainable by sustainability team.',
    CareType            STRING          COMMENT 'Derived care type (MACHINE_WASH | HAND_WASH | DRY_CLEAN).',
    -- Gold metadata
    _serving_timestamp  TIMESTAMP       COMMENT 'UTC gold serving timestamp.'
)
USING DELTA
COMMENT 'Denormalised item attribute table — one row per ItemNumber-OptionCode. Supports faceted filtering in stock analysis and campaign targeting. Joins: trusted.dim_item on ItemNumber.'
LOCATION 'dbfs:/mnt/serving/refined/dim_item_attribute'
TBLPROPERTIES (
    'delta.minReaderVersion'  = '1',
    'delta.minWriterVersion'  = '2',
    'quality.layer'           = 'refined'
);

-- =============================================================================
-- SCHEMA: bismerged
-- =============================================================================

USE bismerged;

-- ---------------------------------------------------------------------------
-- svoc_customers  (Single View of Customer — Customer 360)
-- Source: trusted.fact_sales_orders + payment catalogs + warehouselogistics_prod
-- Grain: one row per CustomerID (current snapshot)
-- Status: ORPHAN — feeds no active downstream pipeline in Phase 1.
--         Flagged in lineage_ucx.html — cross-domain wiring needed in Phase 3.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS bismerged.svoc_customers (
    CustomerID              STRING          NOT NULL  COMMENT 'Anonymised customer identifier. Join key across all domains.',
    -- BIS signals (from trusted.fact_sales_orders)
    FirstOrderDate          DATE            COMMENT 'Date of customer first purchase.',
    LastOrderDate           DATE            COMMENT 'Date of most recent purchase.',
    TotalLifetimeRevenue    DECIMAL(14, 2)  COMMENT 'Sum of all order amounts in GBP.',
    TotalLifetimeOrders     INT             COMMENT 'Total number of orders placed.',
    TotalLifetimeReturns    INT             COMMENT 'Total units returned.',
    FavouriteCategory       STRING          COMMENT 'Category with highest spend.',
    FavouriteBrand          STRING          COMMENT 'Brand with highest spend.',
    AvgOrderValue           DECIMAL(10, 2)  COMMENT 'Mean order line value.',
    ReturnRatePct           DECIMAL(5, 2)   COMMENT 'Lifetime return rate percentage.',
    -- Payment signals (cross-catalog — from wp/ap/pp/gp/klarna diagnostic catalogs)
    LastPaymentProvider     STRING          COMMENT 'Most recently used payment provider.',
    HasOpenDispute          BOOLEAN         COMMENT 'TRUE if any unresolved dispute in payment catalogs.',
    KlarnaCustomer          BOOLEAN         COMMENT 'TRUE if customer has used Klarna BNPL.',
    -- Logistics signals (from warehouselogistics_prod — currently unmapped)
    LastDeliveryDate        DATE            COMMENT 'Most recent parcel delivery date from WMS.',
    DeliverySuccessRate     DECIMAL(5, 2)   COMMENT 'Percentage of deliveries that succeeded first-time.',
    -- Segmentation (derived)
    CustomerSegment         STRING          COMMENT 'RFM-derived segment: VIP | LOYAL | AT_RISK | LAPSED | NEW.',
    IsActiveCustomer        BOOLEAN         COMMENT 'TRUE if LastOrderDate within 12 months.',
    -- Snapshot metadata
    SnapshotDate            DATE            NOT NULL  COMMENT 'Date of this SVOC snapshot (partition key).',
    _generated_at           TIMESTAMP       COMMENT 'UTC generation timestamp.'
)
USING DELTA
COMMENT 'Single View of Customer — consolidated 360 profile. One row per CustomerID per snapshot date. ORPHAN: currently has no active downstream consumer pipeline (Phase 3 target). Cross-domain join from BIS + 5 payment catalogs + WMS. Ensure cross-project IAM is set before enabling on GCP.'
LOCATION 'dbfs:/mnt/serving/bismerged/svoc_customers'
PARTITIONED BY (SnapshotDate)
TBLPROPERTIES (
    'delta.minReaderVersion'           = '1',
    'delta.minWriterVersion'           = '2',
    'delta.enableChangeDataFeed'       = 'true',
    'quality.layer'                    = 'merged',
    'pii.classification'               = 'restricted:customer_data',
    'lineage.status'                   = 'orphan:no_active_downstream',
    'lineage.target_phase'             = 'Phase 3',
    'cross_catalog.sources'            = 'trusted.fact_sales_orders,wp_diagnostic,ap_diagnostic,pp_diagnostic,gp_diagnostic,klarna_diagnostic,warehouselogistics_prod'
);
