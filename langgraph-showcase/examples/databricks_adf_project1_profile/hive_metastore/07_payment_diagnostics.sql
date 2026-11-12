-- =============================================================================
-- Payment Diagnostic Catalogs — 5 Providers
-- =============================================================================
-- Each of the 5 payment providers has its own diagnostic schema.
-- All 5 share an identical table structure: payment_events with a JSON Payload
-- column. The anti-pattern: all event data is stored as a raw JSON string, and
-- analysis queries use get_json_object() for field extraction.
--
-- Migration note: On BigQuery, get_json_object() must be replaced with
-- JSON_VALUE() (scalar) or JSON_QUERY() (object/array). db2bq translates this
-- automatically in SQL cells and in Python spark.sql() blocks.
--
-- Cross-catalog join: klarna_diagnostic queries against
-- businessintelligencesystems_prod.trusted.fact_sales_orders (ExternalOrderRef).
--
-- PII classification:
--   wp_diagnostic   — customer_email in Payload (HIGH)
--   ap_diagnostic   — order_reference in Payload (MEDIUM)
--   pp_diagnostic   — payer.email in Payload (HIGH)
--   gp_diagnostic   — no direct PII in extracted fields (LOW)
--   klarna_diagnostic — order_id correlation to BIS (MEDIUM)
-- =============================================================================

-- ---------------------------------------------------------------------------
-- COMMON PAYMENT_EVENTS SCHEMA (shared across all 5 providers)
--
-- Core columns (identical in all catalogs):
--   EventId          STRING   — Provider-specific event UUID.
--   EventType        STRING   — Event type code (varies by provider).
--   EventTimestamp   TIMESTAMP — UTC event time.
--   Payload          STRING   — Raw JSON webhook body (full provider payload).
--   ProcessedAt      TIMESTAMP — When the event was ingested.
--   _ingestion_ts    TIMESTAMP — DB2BQ ingest metadata.
--
-- Key JSON paths extracted per provider:
--   WooPayments:    $.transaction_id, $.amount, $.currency, $.status, $.customer_email, $.error_code
--   AmazonPay:      $.order_reference_id, $.dispute_id, $.amount.value, $.amount.currencyCode, $.reason_code, $.resolution_date
--   PayPal:         $.id, $.status, $.amount.value, $.payer.email, $.failure_reason
--   GooglePay:      $.result_code, $.decline_reason
--   Klarna:         $.order_id, $.capture_amount, $.settlement_date, $.event_type
-- ---------------------------------------------------------------------------

-- ============================================================================
-- wp_diagnostic  (WooPayments)
-- ============================================================================

CREATE TABLE IF NOT EXISTS wp_diagnostic.payment_events (
    EventId             STRING          NOT NULL  COMMENT 'WooPayments event UUID.',
    EventType           STRING          COMMENT 'Event type (payment.succeeded | payment.failed | payment.pending | refund.created | dispute.opened).',
    EventTimestamp      TIMESTAMP       NOT NULL  COMMENT 'UTC event occurrence time.',
    Payload             STRING          COMMENT 'Raw JSON webhook payload from WooPayments API. JSON paths: $.transaction_id, $.amount, $.currency, $.status, $.customer_email, $.error_code. get_json_object() anti-pattern → JSON_VALUE() on BigQuery.',
    GatewayReference    STRING          COMMENT 'WooPayments gateway transaction reference.',
    SiteId              STRING          COMMENT 'WooCommerce site identifier.',
    ProcessedAt         TIMESTAMP       COMMENT 'Ingestion processing timestamp.',
    RetryCount          INT             COMMENT 'Number of retry attempts for this event.',
    -- Ingest metadata
    _ingestion_timestamp TIMESTAMP      COMMENT 'UTC ingest timestamp.'
)
USING DELTA
COMMENT 'WooPayments webhook events. Payload column stores raw JSON string — use get_json_object(Payload, $.field) / JSON_VALUE(Payload, $.field on BQ) for extraction. PII: customer_email embedded in Payload. Partitioned by event date for query performance.'
LOCATION 'dbfs:/mnt/serving/diagnostics/wp/payment_events'
PARTITIONED BY (EventDate)
TBLPROPERTIES (
    'delta.minReaderVersion'    = '1',
    'delta.minWriterVersion'    = '2',
    'quality.layer'             = 'diagnostic',
    'pii.classification'        = 'high:customer_email_in_payload',
    'json.anti_pattern'         = 'get_json_object_in_queries',
    'migration.note'            = 'translate_get_json_object_to_JSON_VALUE',
    'provider'                  = 'WooPayments'
);

-- Partition column needed for Hive-partitioned table
ALTER TABLE wp_diagnostic.payment_events ADD COLUMN IF NOT EXISTS EventDate DATE
  GENERATED ALWAYS AS (CAST(EventTimestamp AS DATE))
  COMMENT 'Derived partition column from EventTimestamp.';

-- ============================================================================
-- ap_diagnostic  (AmazonPay)
-- ============================================================================

CREATE TABLE IF NOT EXISTS ap_diagnostic.payment_events (
    EventId             STRING          NOT NULL  COMMENT 'AmazonPay event UUID.',
    EventType           STRING          COMMENT 'Event type (DISPUTE_OPENED | REFUND_INITIATED | PAYMENT_CAPTURED | CHARGEBACK_RECEIVED).',
    EventTimestamp      TIMESTAMP       NOT NULL  COMMENT 'UTC event time.',
    Payload             STRING          COMMENT 'Raw JSON from AmazonPay IPN. JSON paths: $.order_reference_id, $.dispute_id, $.amount.value, $.amount.currencyCode, $.reason_code, $.resolution_date. Nested amount object requires JSON_QUERY on BigQuery.',
    MerchantId          STRING          COMMENT 'Amazon merchant identifier.',
    MarketplaceId       STRING          COMMENT 'Amazon marketplace (e.g. A1F83G8C2ARO7P = UK).',
    ProcessedAt         TIMESTAMP       COMMENT 'Ingestion processing timestamp.',
    EventDate           DATE            COMMENT 'Partition column (DATE cast of EventTimestamp).',
    -- Ingest metadata
    _ingestion_timestamp TIMESTAMP      COMMENT 'UTC ingest timestamp.'
)
USING DELTA
COMMENT 'AmazonPay IPN (Instant Payment Notification) events. Payload JSON has nested amount object ($.amount.value and $.amount.currencyCode) — requires JSON_QUERY for the object or double JSON_VALUE calls on BigQuery. PII: order_reference_id in Payload.'
LOCATION 'dbfs:/mnt/serving/diagnostics/ap/payment_events'
PARTITIONED BY (EventDate)
TBLPROPERTIES (
    'delta.minReaderVersion'  = '1',
    'delta.minWriterVersion'  = '2',
    'quality.layer'           = 'diagnostic',
    'pii.classification'      = 'medium:order_reference_in_payload',
    'json.anti_pattern'       = 'get_json_object_nested_object',
    'migration.note'          = 'use_JSON_QUERY_for_nested_amount_object',
    'provider'                = 'AmazonPay'
);

-- ============================================================================
-- pp_diagnostic  (PayPal)
-- ============================================================================

CREATE TABLE IF NOT EXISTS pp_diagnostic.payment_events (
    EventId             STRING          NOT NULL  COMMENT 'PayPal event UUID.',
    EventType           STRING          COMMENT 'Event type (PAYMENT.CAPTURE.COMPLETED | PAYMENT.CAPTURE.DECLINED | CUSTOMER.DISPUTE.CREATED | PAYMENT.CAPTURE.REFUNDED).',
    EventTimestamp      TIMESTAMP       NOT NULL  COMMENT 'UTC event time.',
    Payload             STRING          COMMENT 'Raw JSON from PayPal webhook. JSON paths: $.id, $.status, $.amount.value, $.payer.email, $.failure_reason. customer payer.email is PII — handle with masking on BigQuery.',
    PayPalAccountId     STRING          COMMENT 'PayPal business account identifier.',
    WebhookId           STRING          COMMENT 'PayPal webhook configuration ID.',
    ProcessedAt         TIMESTAMP       COMMENT 'Ingestion processing timestamp.',
    EventDate           DATE            COMMENT 'Partition column.',
    -- Ingest metadata
    _ingestion_timestamp TIMESTAMP      COMMENT 'UTC ingest timestamp.'
)
USING DELTA
COMMENT 'PayPal webhook events. Payload.payer.email is PII — HIGH classification. Queries filter on $.status = FAILED for diagnostics. Nested JSON paths require JSON_QUERY or multiple JSON_VALUE calls on BigQuery.'
LOCATION 'dbfs:/mnt/serving/diagnostics/pp/payment_events'
PARTITIONED BY (EventDate)
TBLPROPERTIES (
    'delta.minReaderVersion'  = '1',
    'delta.minWriterVersion'  = '2',
    'quality.layer'           = 'diagnostic',
    'pii.classification'      = 'high:payer_email_in_payload',
    'json.anti_pattern'       = 'get_json_object_deeply_nested',
    'migration.note'          = 'mask_payer_email_with_BQ_policy_tag',
    'provider'                = 'PayPal'
);

-- ============================================================================
-- gp_diagnostic  (GooglePay)
-- ============================================================================

CREATE TABLE IF NOT EXISTS gp_diagnostic.payment_events (
    EventId             STRING          NOT NULL  COMMENT 'GooglePay event UUID.',
    EventType           STRING          COMMENT 'Event type (AUTHORIZATION_RESULT | TRANSACTION_SETTLED | TRANSACTION_REFUNDED).',
    EventTimestamp      TIMESTAMP       NOT NULL  COMMENT 'UTC event time.',
    Payload             STRING          COMMENT 'Raw JSON from GooglePay notification. JSON paths: $.result_code (AUTH_SUCCESS | DECLINED), $.decline_reason. Used for authorization rate analysis.',
    MerchantId          STRING          COMMENT 'Google merchant center ID.',
    ProcessedAt         TIMESTAMP       COMMENT 'Ingestion processing timestamp.',
    EventDate           DATE            COMMENT 'Partition column.',
    -- Ingest metadata
    _ingestion_timestamp TIMESTAMP      COMMENT 'UTC ingest timestamp.'
)
USING DELTA
COMMENT 'GooglePay payment authorization events. Used for authorization rate (AUTH_SUCCESS / total) calculation. Queries use SELECT TOP 1000 in source — translated to LIMIT 1000 on BigQuery. PII risk: LOW.'
LOCATION 'dbfs:/mnt/serving/diagnostics/gp/payment_events'
PARTITIONED BY (EventDate)
TBLPROPERTIES (
    'delta.minReaderVersion'  = '1',
    'delta.minWriterVersion'  = '2',
    'quality.layer'           = 'diagnostic',
    'pii.classification'      = 'low',
    'migration.note'          = 'SELECT_TOP_translated_to_LIMIT',
    'provider'                = 'GooglePay'
);

-- ============================================================================
-- klarna_diagnostic  (Klarna BNPL)
-- Cross-catalog join: klarna_diagnostic.payment_events × businessintelligencesystems_prod.trusted.fact_sales_orders
-- Join key: get_json_object(Payload, '$.order_id') = fact_sales_orders.ExternalOrderRef
-- ============================================================================

CREATE TABLE IF NOT EXISTS klarna_diagnostic.payment_events (
    EventId             STRING          NOT NULL  COMMENT 'Klarna event UUID.',
    EventType           STRING          COMMENT 'Event type (SETTLEMENT_CREATED | CAPTURE_CREATED | REFUND_CREATED | DISPUTE_CREATED).',
    EventTimestamp      TIMESTAMP       NOT NULL  COMMENT 'UTC event time.',
    Payload             STRING          COMMENT 'Raw JSON from Klarna notification. JSON paths: $.order_id, $.capture_amount, $.settlement_date, $.event_type. $.order_id is used for cross-catalog reconciliation join with trusted.fact_sales_orders.ExternalOrderRef.',
    KlarnaOrderId       STRING          COMMENT 'Promoted from Payload for indexed join (denormalised for performance).',
    MerchantReference   STRING          COMMENT 'Merchant-side order reference.',
    ProcessedAt         TIMESTAMP       COMMENT 'Ingestion processing timestamp.',
    EventDate           DATE            COMMENT 'Partition column.',
    -- Ingest metadata
    _ingestion_timestamp TIMESTAMP      COMMENT 'UTC ingest timestamp.'
)
USING DELTA
COMMENT 'Klarna BNPL settlement events. Key cross-catalog query: joins klarna_diagnostic.payment_events ON get_json_object(Payload, $.order_id) = businessintelligencesystems_prod.trusted.fact_sales_orders.ExternalOrderRef for settlement reconciliation. KlarnaOrderId is denormalised for indexed join performance. On BigQuery: cross-project join via fully-qualified table references.'
LOCATION 'dbfs:/mnt/serving/diagnostics/klarna/payment_events'
PARTITIONED BY (EventDate)
TBLPROPERTIES (
    'delta.minReaderVersion'  = '1',
    'delta.minWriterVersion'  = '2',
    'quality.layer'           = 'diagnostic',
    'pii.classification'      = 'medium:order_id_links_to_customer',
    'cross_catalog.join_key'  = 'KlarnaOrderId',
    'cross_catalog.joins_to'  = 'businessintelligencesystems_prod.trusted.fact_sales_orders.ExternalOrderRef',
    'migration.note'          = 'cross_project_join_needs_IAM_roles_bigquery_dataViewer',
    'provider'                = 'Klarna',
    'bnpl.settlement_lag_check' = 'DATEDIFF_day_EventTimestamp_settlement_date'
);
