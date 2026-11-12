-- =============================================================================
-- product_systems — Curated / Silver Layer (canonical post-rename schema)
-- =============================================================================
-- Conformed tables built from product_systems_raw by BISPipeline silver methods.
-- Types are cast, nulls are enforced, quality rules are applied (BISQualityRules).
-- The legacy alias schema `productsystems` points to the same data during the
-- UCX rename window; see productsystems.sql for the redirect stubs.
--
-- BISPipeline methods that write here:
--   conform_nm_item_supplier() → product_systems.nm_item_supplier
--   extract_item_season()      → product_systems.item_season
--
-- IMPORTANT: The schema is also referenced as `productsystems` by some legacy
-- notebooks during the rename migration. BISPipeline.conform_fact_sales_orders()
-- includes a dual-read guard for this. The canonical name is `product_systems`.
-- =============================================================================

USE product_systems;

-- ---------------------------------------------------------------------------
-- nm_item_supplier  (conformed · silver)
-- Source: product_systems_raw.nm_item_supplier via BISPipeline.conform_nm_item_supplier()
-- Quality rule: BISQualityRules.check_item_number_integrity() must pass before write.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS product_systems.nm_item_supplier (
    ItemNumber          STRING          NOT NULL  COMMENT 'Conformed item identifier (STRING cast applied). FK → trusted.dim_item.ItemNumber.',
    SupplierID          STRING          NOT NULL  COMMENT 'Conformed supplier identifier (STRING cast applied). FK → product_systems_raw.nm_supplier.SupplierID.',
    SupplierName        STRING          COMMENT 'Supplier display name.',
    SupplierRef         STRING          COMMENT 'Supplier-side product reference.',
    LeadTimeDays        INT             COMMENT 'Procurement lead time in days.',
    MinOrderQty         INT             COMMENT 'Minimum order quantity.',
    CostPrice           DECIMAL(10, 2)  COMMENT 'Agreed cost price in GBP.',
    CurrencyCode        STRING          COMMENT 'Purchase currency (default GBP).',
    Status              STRING          COMMENT 'ACTIVE | INACTIVE | PENDING.',
    CreatedDate         DATE            COMMENT 'Date cast applied (yyyy-MM-dd).',
    ModifiedDate        DATE            COMMENT 'Last modification date.',
    IsPreferred         BOOLEAN         COMMENT 'TRUE = preferred supplier for this item.',
    -- Silver metadata
    _processing_timestamp TIMESTAMP     COMMENT 'UTC timestamp when silver transform was applied.',
    _source_version       BIGINT        COMMENT 'Delta version of source bronze table at read time.'
)
USING DELTA
COMMENT 'Conformed item-supplier mapping. Passes BIS quality rule check_item_number_integrity(). Written by BISPipeline.conform_nm_item_supplier() with mergeSchema=true.'
LOCATION 'dbfs:/mnt/processing/product_systems/nm_item_supplier'
TBLPROPERTIES (
    'delta.minReaderVersion'      = '1',
    'delta.minWriterVersion'      = '2',
    'delta.enableChangeDataFeed'  = 'true',
    'quality.layer'               = 'silver',
    'quality.rule'                = 'BISQualityRules.check_item_number_integrity',
    'delta.autoOptimize.optimizeWrite' = 'true'
);

-- ---------------------------------------------------------------------------
-- item_season  (conformed · silver)
-- Source: abfss://curated@retaildatalake.dfs.core.windows.net/product_systems/item_season
--         via BISPipeline.extract_item_season() (overwrite mode)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS product_systems.item_season (
    ItemNumber          STRING          NOT NULL  COMMENT 'Item identifier (STRING cast). FK → trusted.dim_item.ItemNumber.',
    SeasonCode          STRING          NOT NULL  COMMENT 'Season code (e.g. AW24). Used as partition key and join key to attribution_item_season.',
    SeasonStartDate     DATE            COMMENT 'Season open date (DATE cast from TIMESTAMP).',
    SeasonEndDate       DATE            COMMENT 'Season close date (DATE cast from TIMESTAMP).',
    RangeStatus         STRING          COMMENT 'PLANNED | ACTIVE | CLOSED.',
    OptionCount         INT             COMMENT 'Number of active options for this season.',
    BuyerCode           STRING          COMMENT 'Responsible buyer.',
    TeamCode            STRING          COMMENT 'Buying team. FK → trusted.dim_item_team.TeamCode.',
    IsCarryOver         BOOLEAN         COMMENT 'Carry-over from prior season.',
    -- Silver metadata
    _ingestion_timestamp  TIMESTAMP     COMMENT 'Preserved from bronze landing timestamp.',
    _processing_timestamp TIMESTAMP     COMMENT 'UTC silver processing timestamp.'
)
USING DELTA
COMMENT 'Conformed item-season mapping. Written in overwrite mode by BISPipeline.extract_item_season(). Season-scoped queries: filter on SeasonCode.'
LOCATION 'dbfs:/mnt/processing/product_systems/item_season'
PARTITIONED BY (SeasonCode)
TBLPROPERTIES (
    'delta.minReaderVersion'      = '1',
    'delta.minWriterVersion'      = '2',
    'delta.enableChangeDataFeed'  = 'true',
    'quality.layer'               = 'silver',
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true'
);

-- ---------------------------------------------------------------------------
-- nm_item_option  (item SKU options · silver)
-- Source: product_systems_raw.nm_item_detail after conformance
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS product_systems.nm_item_option (
    ItemNumber          STRING          NOT NULL  COMMENT 'FK → nm_item.ItemNumber.',
    OptionCode          STRING          NOT NULL  COMMENT 'Colour-size option identifier.',
    ColourCode          STRING          COMMENT 'Colour code.',
    ColourDescription   STRING          COMMENT 'Colour display name.',
    SizeCode            STRING          COMMENT 'Size (e.g. 8, S, M, ONE SIZE).',
    BarCode             STRING          COMMENT 'EAN-13 barcode.',
    Weight              DECIMAL(8, 3)   COMMENT 'Weight in kg.',
    IsActive            BOOLEAN         COMMENT 'Option currently in range.',
    -- Silver metadata
    _processing_timestamp TIMESTAMP     COMMENT 'UTC silver processing timestamp.'
)
USING DELTA
COMMENT 'Conformed item colour-size options (SKU level). One row per ItemNumber-OptionCode. Source: product_systems_raw.nm_item_detail.'
LOCATION 'dbfs:/mnt/processing/product_systems/nm_item_option'
TBLPROPERTIES (
    'delta.minReaderVersion'  = '1',
    'delta.minWriterVersion'  = '2',
    'quality.layer'           = 'silver'
);

-- ---------------------------------------------------------------------------
-- item  (curated item master · silver)
-- Source: product_systems_raw.nm_item + nm_item_text merged
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS product_systems.item (
    ItemNumber          STRING          NOT NULL  COMMENT 'Primary item identifier.',
    ItemName            STRING          COMMENT 'Short display name.',
    ItemDescription     STRING          COMMENT 'Long marketing description.',
    ProductCategory     STRING          COMMENT 'Top-level category.',
    SubCategory         STRING          COMMENT 'Sub-category.',
    BrandCode           STRING          COMMENT 'Brand identifier. FK → trusted.dim_item.BrandCode.',
    BrandName           STRING          COMMENT 'Brand display name.',
    ColourCode          STRING          COMMENT 'Primary colour code.',
    RetailPrice         DECIMAL(10, 2)  COMMENT 'Full retail price GBP.',
    CostPrice           DECIMAL(10, 2)  COMMENT 'Standard cost price GBP.',
    Department          STRING          COMMENT 'Buying department.',
    ClassCode           STRING          COMMENT 'Merchandising class.',
    IsActive            BOOLEAN         COMMENT 'Item currently active.',
    LaunchDate          DATE            COMMENT 'First sale date.',
    EndDate             DATE            COMMENT 'Last sale date.',
    -- Silver metadata
    _processing_timestamp TIMESTAMP     COMMENT 'UTC silver processing timestamp.'
)
USING DELTA
COMMENT 'Curated item master — merged from nm_item + nm_item_text. Used as the source for trusted.dim_item SCD2 build.'
LOCATION 'dbfs:/mnt/processing/product_systems/item'
TBLPROPERTIES (
    'delta.minReaderVersion'  = '1',
    'delta.minWriterVersion'  = '2',
    'quality.layer'           = 'silver',
    'delta.autoOptimize.optimizeWrite' = 'true'
);

-- ---------------------------------------------------------------------------
-- item_text  (conformed item copy · silver)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS product_systems.item_text (
    ItemNumber          STRING          NOT NULL  COMMENT 'FK → product_systems.item.ItemNumber.',
    LanguageCode        STRING          NOT NULL  COMMENT 'ISO-639 language code.',
    Title               STRING          COMMENT 'SEO title.',
    LongDescription     STRING          COMMENT 'Full PDP copy.',
    BulletPoints        STRING          COMMENT 'Pipe-separated bullet points.',
    SizeGuideText       STRING          COMMENT 'Size and fit guidance.',
    LastUpdated         TIMESTAMP       COMMENT 'Last copy update timestamp.',
    -- Silver metadata
    _processing_timestamp TIMESTAMP     COMMENT 'UTC silver processing timestamp.'
)
USING DELTA
COMMENT 'Conformed item text / localised marketing copy. One row per ItemNumber-LanguageCode.'
LOCATION 'dbfs:/mnt/processing/product_systems/item_text'
TBLPROPERTIES (
    'delta.minReaderVersion'  = '1',
    'delta.minWriterVersion'  = '2',
    'quality.layer'           = 'silver'
);

-- ---------------------------------------------------------------------------
-- LEGACY ALIAS: productsystems database stubs
-- These CREATE TABLE statements point to the SAME LOCATIONS as above.
-- Purpose: allow legacy notebooks that reference `productsystems.item_season`
-- to continue working during the UCX schema rename migration.
-- Once all notebooks are updated, drop productsystems.* and this alias.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS productsystems.item_season
    USING DELTA
    COMMENT '[LEGACY ALIAS] Points to same Delta location as product_systems.item_season. Do not write to this alias — use product_systems.item_season.'
    LOCATION 'dbfs:/mnt/processing/product_systems/item_season';

CREATE TABLE IF NOT EXISTS productsystems.item
    USING DELTA
    COMMENT '[LEGACY ALIAS] Points to same Delta location as product_systems.item.'
    LOCATION 'dbfs:/mnt/processing/product_systems/item';
