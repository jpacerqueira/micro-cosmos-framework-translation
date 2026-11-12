-- =============================================================================
-- warehouselogistics_prod — Warehouse / WMS Streaming Domain
-- =============================================================================
-- Isolated domain handling BPP (Business Process Platform) parcel events.
-- This is the only streaming domain in the estate — data arrives via
-- Eventarc (blob trigger equivalent) and is processed in near-real-time.
--
-- Architecture note: This domain has NO serving/gold layer in Phase 1.
-- It is flagged in lineage_warehouse.html as a Phase 5 target for Dataflow
-- migration (streaming Dataflow Flex Template replacing the Cloud Run handler).
--
-- UCX status: streaming tables are not Unity Catalog compatible with the
-- current DLT configuration — assess before promotion.
--
-- BPP event flow:
--   Warehouse WMS → Azure Event Grid → BlobToEventGridFunction (C#) →
--   blob storage → Delta table (parcel_events)
-- After migration:
--   Warehouse WMS → GCP Eventarc → Cloud Run (BlobToEventGridFunction skeleton) →
--   GCS → DataProc or Dataflow → Delta/BigQuery
-- =============================================================================

USE warehouselogistics_prod;

-- ---------------------------------------------------------------------------
-- bpp_parcel_events  (BPP Parcel Events — streaming landing)
-- Source: Azure Event Grid blob trigger → C# Function → Delta append
-- Grain: one row per parcel event (one parcel may have multiple events)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS warehouselogistics_prod.bpp_parcel_events (
    EventId             STRING          NOT NULL  COMMENT 'Unique event identifier from BPP.',
    ParcelId            STRING          NOT NULL  COMMENT 'Parcel / consignment identifier.',
    OrderId             STRING          COMMENT 'Associated order identifier. FK → trusted.fact_sales_orders.OrderID.',
    EventType           STRING          NOT NULL  COMMENT 'BPP event type: PARCEL_DESPATCHED | PARCEL_IN_TRANSIT | PARCEL_OUT_FOR_DELIVERY | PARCEL_DELIVERED | PARCEL_RETURNED | DELIVERY_FAILED | DELIVERY_EXCEPTION.',
    EventTimestamp      TIMESTAMP       NOT NULL  COMMENT 'UTC event occurrence time from BPP.',
    IngestionTimestamp  TIMESTAMP       COMMENT 'UTC time blob trigger fired (latency = EventTimestamp - IngestionTimestamp).',
    CarrierCode         STRING          COMMENT 'Carrier identifier (e.g. DPD, EVRI, ROYAL_MAIL, DHL).',
    TrackingNumber      STRING          COMMENT 'Carrier tracking reference.',
    WarehouseId         STRING          COMMENT 'Despatch warehouse identifier.',
    DestinationPostcode STRING          COMMENT 'Delivery postcode (truncated to sector for privacy).',
    DeliveryAttempt     INT             COMMENT 'Delivery attempt number (1 = first attempt).',
    FailureReason       STRING          COMMENT 'Reason code for failed delivery (NULL on success).',
    EstimatedDelivery   DATE            COMMENT 'Carrier-provided estimated delivery date.',
    ActualDelivery      TIMESTAMP       COMMENT 'Actual delivery timestamp (NULL until PARCEL_DELIVERED).',
    IsLateDelivery      BOOLEAN         COMMENT 'TRUE if ActualDelivery > EstimatedDelivery.',
    -- Ingest metadata
    _ingestion_timestamp TIMESTAMP      COMMENT 'UTC landing timestamp from blob trigger function.',
    _source_blob        STRING          COMMENT 'Azure Blob / GCS path of source event file.',
    _function_version   STRING          COMMENT 'Version of BlobToEventGridFunction that processed this event.'
)
USING DELTA
COMMENT 'BPP parcel tracking events. Streaming domain — appended in near-real-time via blob trigger. No serving layer in Phase 1. OrderId links to trusted.fact_sales_orders. Phase 5: replace blob trigger with Eventarc → Cloud Run → Dataflow Flex Template.'
LOCATION 'dbfs:/mnt/serving/warehouselogistics/bpp_parcel_events'
PARTITIONED BY (CarrierCode)
TBLPROPERTIES (
    'delta.minReaderVersion'           = '1',
    'delta.minWriterVersion'           = '2',
    'delta.enableChangeDataFeed'       = 'false',
    'delta.autoOptimize.optimizeWrite' = 'true',
    'delta.autoOptimize.autoCompact'   = 'true',
    'quality.layer'                    = 'streaming',
    'streaming.trigger'                = 'BlobToEventGridFunction',
    'streaming.runtime'                = 'dotnet',
    'streaming.gcp_replacement'        = 'Eventarc+CloudRun+Dataflow',
    'ucx.status'                       = 'assess:streaming_not_uc_compatible',
    'lineage.status'                   = 'isolated:no_serving_layer',
    'lineage.target_phase'             = 'Phase 5'
);

-- ---------------------------------------------------------------------------
-- bpp_delivery_status  (Current delivery status — silver aggregation)
-- Grain: one row per ParcelId (latest status snapshot)
-- Source: warehouselogistics_prod.bpp_parcel_events (latest event per parcel)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS warehouselogistics_prod.bpp_delivery_status (
    ParcelId            STRING          NOT NULL  COMMENT 'PK — parcel identifier.',
    OrderId             STRING          COMMENT 'FK → trusted.fact_sales_orders.OrderID.',
    LatestStatus        STRING          COMMENT 'Most recent EventType for this parcel.',
    LatestEventTime     TIMESTAMP       COMMENT 'Timestamp of the most recent event.',
    CarrierCode         STRING          COMMENT 'Carrier.',
    TrackingNumber      STRING,
    DeliveryAttempts    INT             COMMENT 'Total delivery attempts made.',
    IsDelivered         BOOLEAN         COMMENT 'TRUE if LatestStatus = PARCEL_DELIVERED.',
    IsReturned          BOOLEAN         COMMENT 'TRUE if LatestStatus = PARCEL_RETURNED.',
    EstimatedDelivery   DATE,
    ActualDelivery      TIMESTAMP,
    IsLate              BOOLEAN,
    -- Snapshot metadata
    _last_refreshed     TIMESTAMP       COMMENT 'UTC timestamp of last status refresh.'
)
USING DELTA
COMMENT 'Current delivery status snapshot — one row per ParcelId. Derived from bpp_parcel_events (latest event per parcel). Used for SVOC logistics signal in bismerged.svoc_customers (Phase 3+). Full overwrite on each refresh.'
LOCATION 'dbfs:/mnt/serving/warehouselogistics/bpp_delivery_status'
TBLPROPERTIES (
    'delta.minReaderVersion'  = '1',
    'delta.minWriterVersion'  = '2',
    'quality.layer'           = 'streaming-silver',
    'lineage.target_phase'    = 'Phase 3',
    'lineage.feeds'           = 'bismerged.svoc_customers.LastDeliveryDate,bismerged.svoc_customers.DeliverySuccessRate'
);
