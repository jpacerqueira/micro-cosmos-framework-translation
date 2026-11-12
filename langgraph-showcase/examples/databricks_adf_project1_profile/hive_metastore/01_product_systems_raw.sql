-- =============================================================================
-- product_systems_raw — Bronze / Landing Layer
-- =============================================================================
-- Source: ADLS Gen1 (wasb://) raw container + ADLS Gen2 (abfss://) curated zone.
-- Ingested by BISPipeline.extract_nm_item_raw() and extract_nm_item_supplier().
-- All tables are Delta format (append mode). Single metadata column added at
-- ingest time: _ingestion_timestamp. No transformation applied at this layer.
--
-- UCX status: BLOCKER — wasb:// source URIs are not Unity Catalog compatible.
--   All tables require External Location mapping before UC promotion.
-- =============================================================================

USE product_systems_raw;

-- ---------------------------------------------------------------------------
-- nm_item  (Item Master — raw landing)
-- Source: wasb://raw-container@retailstorage.blob.core.windows.net/product_systems_raw/nm_item/
-- Primary key: ItemNumber (natural key from ERP system)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS product_systems_raw.nm_item (
    ItemNumber          STRING          NOT NULL  COMMENT 'Natural item identifier from ERP (e.g. NM-12345). Join key to nm_item_supplier, item_season, dim_item.',
    ItemName            STRING          COMMENT 'Short display name of the item.',
    ItemDescription     STRING          COMMENT 'Long-form description from content team.',
    ProductCategory     STRING          COMMENT 'Top-level category (e.g. Womenswear, Menswear, Beauty).',
    SubCategory         STRING          COMMENT 'Second-level category (e.g. Dresses, Trousers).',
    BrandCode           STRING          COMMENT 'Brand identifier (e.g. NM, LIPSY, LABELLEDITION).',
    BrandName           STRING          COMMENT 'Display brand name.',
    ColourCode          STRING          COMMENT 'Colour code from product catalogue.',
    ColourDescription   STRING          COMMENT 'Human-readable colour name.',
    SizeCode            STRING          COMMENT 'Size code (e.g. 8, 10, S, M, L).',
    RetailPrice         DECIMAL(10, 2)  COMMENT 'Current full retail price in GBP.',
    CostPrice           DECIMAL(10, 2)  COMMENT 'Cost price / buy price in GBP.',
    Department          STRING          COMMENT 'Buying department code.',
    ClassCode           STRING          COMMENT 'Merchandising class code.',
    IsActive            BOOLEAN         COMMENT 'Whether item is currently active in the range.',
    LaunchDate          DATE            COMMENT 'First available-for-sale date.',
    EndDate             DATE            COMMENT 'Last available-for-sale date (NULL = ongoing).',
    SupplierRef         STRING          COMMENT 'Supplier-side reference code.',
    CountryOfOrigin     STRING          COMMENT 'ISO-3166 country code for manufacturing origin.',
    -- Metadata
    _ingestion_timestamp  TIMESTAMP     COMMENT 'UTC timestamp when row was ingested into bronze.',
    _source_file          STRING        COMMENT 'DBFS/ADLS source file path (from input_file_name()).'
)
USING DELTA
COMMENT 'Raw item master data as-landed from ERP via wasb:// ADLS Gen1. No transformations applied. Delta append mode.'
LOCATION 'dbfs:/mnt/raw/product_systems_raw/nm_item'
TBLPROPERTIES (
    'delta.minReaderVersion'      = '1',
    'delta.minWriterVersion'      = '2',
    'delta.enableChangeDataFeed'  = 'false',
    'quality.layer'               = 'bronze',
    'source.format'               = 'parquet',
    'source.uri.scheme'           = 'wasb',
    'ucx.blocker'                 = 'wasb_uri_not_uc_compatible'
);

-- ---------------------------------------------------------------------------
-- nm_item_supplier  (Item–Supplier Link — raw landing)
-- Source: wasb://raw-container@retailstorage.blob.core.windows.net/product_systems_raw/nm_item_supplier/
-- Primary key: (ItemNumber, SupplierID)
-- FK: ItemNumber → nm_item.ItemNumber
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS product_systems_raw.nm_item_supplier (
    ItemNumber          STRING          NOT NULL  COMMENT 'Item identifier. FK → nm_item.ItemNumber.',
    SupplierID          STRING          NOT NULL  COMMENT 'Supplier identifier from supplier master.',
    SupplierName        STRING          COMMENT 'Supplier display name.',
    SupplierRef         STRING          COMMENT 'Supplier-side product reference code.',
    LeadTimeDays        INT             COMMENT 'Procurement lead time in days.',
    MinOrderQty         INT             COMMENT 'Minimum order quantity for this supplier-item.',
    CostPrice           DECIMAL(10, 2)  COMMENT 'Agreed cost price in GBP for this supplier.',
    CurrencyCode        STRING          COMMENT 'Purchase currency (default GBP).',
    Status              STRING          COMMENT 'Relationship status: ACTIVE | INACTIVE | PENDING.',
    CreatedDate         DATE            COMMENT 'Date this supplier-item link was created.',
    ModifiedDate        DATE            COMMENT 'Date this record was last modified.',
    IsPreferred         BOOLEAN         COMMENT 'TRUE if this is the preferred supplier for the item.',
    -- Metadata
    _ingestion_timestamp  TIMESTAMP     COMMENT 'UTC ingestion timestamp.',
    _source_file          STRING        COMMENT 'Source file path.'
)
USING DELTA
COMMENT 'Raw item-to-supplier mapping as-landed from ERP. Links nm_item to supplier master. Conformed version in product_systems.nm_item_supplier.'
LOCATION 'dbfs:/mnt/raw/product_systems_raw/nm_item_supplier'
TBLPROPERTIES (
    'delta.minReaderVersion'  = '1',
    'delta.minWriterVersion'  = '2',
    'quality.layer'           = 'bronze',
    'source.format'           = 'parquet',
    'source.uri.scheme'       = 'wasb',
    'ucx.blocker'             = 'wasb_uri_not_uc_compatible'
);

-- ---------------------------------------------------------------------------
-- nm_item_detail  (Item Detail / Options)
-- Source: wasb://raw-container@retailstorage.blob.core.windows.net/product_systems_raw/nm_item_detail/
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS product_systems_raw.nm_item_detail (
    ItemNumber          STRING          NOT NULL  COMMENT 'FK → nm_item.ItemNumber.',
    OptionCode          STRING          NOT NULL  COMMENT 'Option / SKU code (colour-size combination).',
    BarCode             STRING          COMMENT 'EAN-13 barcode.',
    StockKeepingUnit    STRING          COMMENT 'Internal SKU reference.',
    Weight              DECIMAL(8, 3)   COMMENT 'Item weight in kg (for shipping cost calculation).',
    Height              DECIMAL(8, 2)   COMMENT 'Packaged height in cm.',
    Width               DECIMAL(8, 2)   COMMENT 'Packaged width in cm.',
    Depth               DECIMAL(8, 2)   COMMENT 'Packaged depth in cm.',
    HsCode              STRING          COMMENT 'Harmonised System tariff code for customs.',
    FabricContent       STRING          COMMENT 'Fabric composition text (e.g. 100% Cotton).',
    CareInstructions    STRING          COMMENT 'Care label instructions.',
    IsActive            BOOLEAN         COMMENT 'Whether this option is active.',
    -- Metadata
    _ingestion_timestamp  TIMESTAMP     COMMENT 'UTC ingestion timestamp.',
    _source_file          STRING        COMMENT 'Source file path.'
)
USING DELTA
COMMENT 'Raw item detail / SKU-level attributes per colour-size option. One row per ItemNumber-OptionCode combination.'
LOCATION 'dbfs:/mnt/raw/product_systems_raw/nm_item_detail'
TBLPROPERTIES (
    'delta.minReaderVersion'  = '1',
    'delta.minWriterVersion'  = '2',
    'quality.layer'           = 'bronze',
    'source.format'           = 'parquet',
    'ucx.blocker'             = 'wasb_uri_not_uc_compatible'
);

-- ---------------------------------------------------------------------------
-- nm_item_text  (Item Copy / Marketing Text)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS product_systems_raw.nm_item_text (
    ItemNumber          STRING          NOT NULL  COMMENT 'FK → nm_item.ItemNumber.',
    LanguageCode        STRING          NOT NULL  COMMENT 'ISO-639 language (e.g. en-GB).',
    Title               STRING          COMMENT 'SEO product title.',
    LongDescription     STRING          COMMENT 'Full marketing copy for PDP.',
    BulletPoints        STRING          COMMENT 'Pipe-separated bullet points for listing.',
    SizeGuideText       STRING          COMMENT 'Size and fit guidance copy.',
    LastUpdated         TIMESTAMP       COMMENT 'Timestamp of last copy update.',
    UpdatedBy           STRING          COMMENT 'Editor username who last updated.',
    -- Metadata
    _ingestion_timestamp  TIMESTAMP     COMMENT 'UTC ingestion timestamp.',
    _source_file          STRING        COMMENT 'Source file path.'
)
USING DELTA
COMMENT 'Item marketing copy and localised text. One row per ItemNumber-LanguageCode combination.'
LOCATION 'dbfs:/mnt/raw/product_systems_raw/nm_item_text'
TBLPROPERTIES (
    'delta.minReaderVersion'  = '1',
    'delta.minWriterVersion'  = '2',
    'quality.layer'           = 'bronze',
    'source.format'           = 'parquet'
);

-- ---------------------------------------------------------------------------
-- nm_supplier  (Supplier Master — raw landing)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS product_systems_raw.nm_supplier (
    SupplierID          STRING          NOT NULL  COMMENT 'Primary supplier identifier.',
    SupplierName        STRING          COMMENT 'Legal entity / trading name.',
    SupplierGroup       STRING          COMMENT 'Group / parent supplier (for consolidated reporting).',
    CountryCode         STRING          COMMENT 'ISO-3166 country of registration.',
    CurrencyCode        STRING          COMMENT 'Default trading currency.',
    PaymentTermsDays    INT             COMMENT 'Standard payment terms (days).',
    VatNumber           STRING          COMMENT 'VAT registration number.',
    ContactEmail        STRING          COMMENT 'Primary contact email.',
    AccountManager      STRING          COMMENT 'Internal NM account manager name.',
    Status              STRING          COMMENT 'ACTIVE | INACTIVE | SUSPENDED.',
    OnboardedDate       DATE            COMMENT 'Date supplier was activated in the system.',
    -- Metadata
    _ingestion_timestamp  TIMESTAMP     COMMENT 'UTC ingestion timestamp.',
    _source_file          STRING        COMMENT 'Source file path.'
)
USING DELTA
COMMENT 'Supplier master data landed from ERP. Join key for nm_item_supplier.SupplierID.'
LOCATION 'dbfs:/mnt/raw/product_systems_raw/nm_supplier'
TBLPROPERTIES (
    'delta.minReaderVersion'  = '1',
    'delta.minWriterVersion'  = '2',
    'quality.layer'           = 'bronze',
    'source.format'           = 'parquet'
);

-- ---------------------------------------------------------------------------
-- nm_booking_report  (Buying / Booking Report)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS product_systems_raw.nm_booking_report (
    BookingID           STRING          NOT NULL  COMMENT 'Booking / purchase order reference.',
    ItemNumber          STRING          COMMENT 'FK → nm_item.ItemNumber.',
    SupplierID          STRING          COMMENT 'FK → nm_supplier.SupplierID.',
    SeasonCode          STRING          COMMENT 'Season identifier (e.g. AW24, SS25).',
    BuyQuantity         INT             COMMENT 'Units ordered.',
    ConfirmedQuantity   INT             COMMENT 'Units confirmed by supplier.',
    UnitCostPrice       DECIMAL(10, 2)  COMMENT 'Agreed unit cost price in GBP.',
    DeliveryWindowStart DATE            COMMENT 'Earliest expected delivery date.',
    DeliveryWindowEnd   DATE            COMMENT 'Latest expected delivery date.',
    BookingStatus       STRING          COMMENT 'DRAFT | CONFIRMED | RECEIVED | CANCELLED.',
    CreatedDate         DATE            COMMENT 'Booking creation date.',
    -- Metadata
    _ingestion_timestamp  TIMESTAMP     COMMENT 'UTC ingestion timestamp.',
    _source_file          STRING        COMMENT 'Source file path.'
)
USING DELTA
COMMENT 'Buying / purchase order booking data. One row per booking line (ItemNumber × SupplierID × Season).'
LOCATION 'dbfs:/mnt/raw/product_systems_raw/nm_booking_report'
TBLPROPERTIES (
    'delta.minReaderVersion'  = '1',
    'delta.minWriterVersion'  = '2',
    'quality.layer'           = 'bronze',
    'source.format'           = 'parquet'
);

-- ---------------------------------------------------------------------------
-- item_season  (from etl_config.json / BISPipeline.extract_item_season)
-- Source: abfss://curated@retaildatalake.dfs.core.windows.net/product_systems/item_season
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS product_systems_raw.item_season (
    ItemNumber          STRING          NOT NULL  COMMENT 'FK → nm_item.ItemNumber.',
    SeasonCode          STRING          NOT NULL  COMMENT 'Season code (e.g. AW24, SS25, AW25).',
    SeasonStartDate     DATE            COMMENT 'Season open-to-buy start date.',
    SeasonEndDate       DATE            COMMENT 'Season close-to-buy end date.',
    RangeStatus         STRING          COMMENT 'PLANNED | ACTIVE | CLOSED.',
    OptionCount         INT             COMMENT 'Number of colour-size options in season range.',
    BuyerCode           STRING          COMMENT 'Responsible buyer identifier.',
    TeamCode            STRING          COMMENT 'Buying team code. FK → dim_item_team.',
    IsCarryOver         BOOLEAN         COMMENT 'Whether item carries over from previous season.',
    -- Metadata
    _ingestion_timestamp  TIMESTAMP     COMMENT 'UTC ingestion timestamp.',
    _source_file          STRING        COMMENT 'Source file path.'
)
USING DELTA
COMMENT 'Item-to-season mapping. Records which items are in which buying season. One row per ItemNumber-SeasonCode. Conformed version in product_systems.item_season.'
LOCATION 'dbfs:/mnt/raw/product_systems_raw/item_season'
TBLPROPERTIES (
    'delta.minReaderVersion'  = '1',
    'delta.minWriterVersion'  = '2',
    'quality.layer'           = 'bronze',
    'source.format'           = 'parquet',
    'source.uri.scheme'       = 'abfss',
    'ucx.note'                = 'abfss_needs_external_location'
);
