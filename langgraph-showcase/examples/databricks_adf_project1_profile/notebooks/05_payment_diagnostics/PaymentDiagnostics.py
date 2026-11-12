# Databricks notebook source
# COMMAND ----------

# MAGIC %md
# MAGIC # Payment Diagnostics — 5-Provider Analysis
# MAGIC
# MAGIC Ad-hoc diagnostic notebook across the 5 payment provider diagnostic catalogs:
# MAGIC - WooPayments (`wp_diagnostic`)
# MAGIC - AmazonPay (`ap_diagnostic`)
# MAGIC - PayPal (`pp_diagnostic`)
# MAGIC - GooglePay (`gp_diagnostic`)
# MAGIC - Klarna (`klarna_diagnostic`)
# MAGIC
# MAGIC **Anti-pattern note:** All 5 providers store raw webhook events in a `Payload` column
# MAGIC as a JSON string. `get_json_object()` is used for extraction — db2bq automatically
# MAGIC rewrites these to BigQuery `JSON_VALUE()` / `JSON_QUERY()`.
# MAGIC
# MAGIC **Column contract:** EventId, EventType, EventTimestamp, Payload, EventDate
# MAGIC are identical across all 5 schemas per hive_metastore DDL.
# MAGIC
# MAGIC **Cross-catalog join:** Klarna joins `klarna_diagnostic.payment_events` to
# MAGIC `trusted.fact_sales_orders` via `KlarnaOrderId = ExternalOrderRef`.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Parameters

# COMMAND ----------

dbutils.widgets.text("start_date", "2024-01-01", "Start Date (yyyy-MM-dd)")
dbutils.widgets.text("end_date", "2024-12-31", "End Date (yyyy-MM-dd)")
dbutils.widgets.dropdown("provider", "all", ["all", "wp", "ap", "pp", "gp", "klarna"], "Provider Filter")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Imports

# COMMAND ----------

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, get_json_object, current_timestamp, to_date
import logging

spark = SparkSession.builder.appName("PaymentDiagnostics").getOrCreate()
logger = logging.getLogger(__name__)

start_date = dbutils.widgets.get("start_date")
end_date = dbutils.widgets.get("end_date")
provider_filter = dbutils.widgets.get("provider")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. WooPayments — JSON Payload Extraction
# MAGIC
# MAGIC PII HIGH: Payload contains customer_email — apply BQ column-level policy tag
# MAGIC before querying in production. db2bq emits a masking note in MIGRATION_REPORT.md.

# COMMAND ----------

# MAGIC %sql
# MAGIC -- WooPayments: extract key fields from JSON Payload
# MAGIC -- get_json_object() → JSON_VALUE() on BigQuery (auto-translated by db2bq)
# MAGIC -- PII: $.customer_email requires policy tag roles/datacatalog.maskedReader
# MAGIC SELECT
# MAGIC     EventId,
# MAGIC     EventType,
# MAGIC     EventTimestamp,
# MAGIC     EventDate,
# MAGIC     get_json_object(Payload, '$.transaction_id')   AS TransactionId,
# MAGIC     get_json_object(Payload, '$.amount')           AS Amount,
# MAGIC     get_json_object(Payload, '$.currency')         AS Currency,
# MAGIC     get_json_object(Payload, '$.status')           AS PaymentStatus,
# MAGIC     get_json_object(Payload, '$.customer_email')   AS CustomerEmail,
# MAGIC     get_json_object(Payload, '$.error_code')       AS ErrorCode,
# MAGIC     DATEADD(day, 1, EventTimestamp)                AS NextRetryDate,
# MAGIC     DATEDIFF(day, EventTimestamp, GETDATE())       AS DaysSinceEvent
# MAGIC FROM wp_diagnostic.payment_events
# MAGIC WHERE EventDate BETWEEN '${start_date}' AND '${end_date}'
# MAGIC   AND get_json_object(Payload, '$.status') IN ('failed', 'pending')

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. AmazonPay — Dispute and Refund Events
# MAGIC
# MAGIC Nested JSON: `$.amount` is a JSON object containing `value` and `currencyCode`.
# MAGIC On BigQuery: use JSON_QUERY(Payload, '$.amount') for the object,
# MAGIC or two JSON_VALUE calls for scalar sub-fields.

# COMMAND ----------

# MAGIC %sql
# MAGIC -- AmazonPay: nested $.amount object — JSON_QUERY needed on BigQuery
# MAGIC SELECT
# MAGIC     EventId,
# MAGIC     EventType,
# MAGIC     EventTimestamp,
# MAGIC     EventDate,
# MAGIC     MerchantId,
# MAGIC     get_json_object(Payload, '$.order_reference_id') AS OrderReferenceId,
# MAGIC     get_json_object(Payload, '$.dispute_id')         AS DisputeId,
# MAGIC     get_json_object(Payload, '$.amount.value')       AS RefundAmount,
# MAGIC     get_json_object(Payload, '$.amount.currencyCode') AS Currency,
# MAGIC     get_json_object(Payload, '$.reason_code')        AS ReasonCode,
# MAGIC     ISNULL(get_json_object(Payload, '$.resolution_date'), GETDATE()) AS EffectiveResolution,
# MAGIC     LEN(get_json_object(Payload, '$.order_reference_id')) AS RefIdLength
# MAGIC FROM ap_diagnostic.payment_events
# MAGIC WHERE EventType IN ('DISPUTE_OPENED', 'REFUND_INITIATED')
# MAGIC   AND EventDate >= DATEADD(month, -3, GETDATE())

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. PayPal — Failed Transaction Summary
# MAGIC
# MAGIC PII HIGH: Payload contains payer.email — mask with BQ policy tag.

# COMMAND ----------

pp_events_df = spark.sql(f"""
    SELECT
        EventId,
        EventType,
        EventTimestamp,
        EventDate,
        get_json_object(Payload, '$.id')             AS TransactionId,
        get_json_object(Payload, '$.status')         AS Status,
        get_json_object(Payload, '$.amount.value')   AS Amount,
        get_json_object(Payload, '$.payer.email')    AS PayerEmail,
        get_json_object(Payload, '$.failure_reason') AS FailureReason
    FROM pp_diagnostic.payment_events
    WHERE EventDate BETWEEN '{start_date}' AND '{end_date}'
      AND get_json_object(Payload, '$.status') = 'FAILED'
""")

pp_events_df.createOrReplaceTempView("pp_failed_events")
logger.info(f"PayPal failed events: {pp_events_df.count()}")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. GooglePay — Authorization Rate
# MAGIC
# MAGIC PII LOW. Uses SELECT TOP — db2bq rewrites to LIMIT.

# COMMAND ----------

# MAGIC %sql
# MAGIC -- GooglePay: authorization rate analysis
# MAGIC -- SELECT TOP 1000 → SELECT ... LIMIT 1000 on BigQuery (db2bq T-SQL rewriter)
# MAGIC SELECT
# MAGIC     EventDate,
# MAGIC     COUNT(*)                                                                      AS TotalEvents,
# MAGIC     SUM(CASE WHEN get_json_object(Payload, '$.result_code') = 'AUTH_SUCCESS' THEN 1 ELSE 0 END) AS Authorized,
# MAGIC     SUM(CASE WHEN get_json_object(Payload, '$.result_code') != 'AUTH_SUCCESS' THEN 1 ELSE 0 END) AS Declined,
# MAGIC     ROUND(
# MAGIC         100.0 * SUM(CASE WHEN get_json_object(Payload, '$.result_code') = 'AUTH_SUCCESS' THEN 1 ELSE 0 END) / COUNT(*),
# MAGIC         2
# MAGIC     )                                                                             AS AuthRate_Pct
# MAGIC FROM gp_diagnostic.payment_events
# MAGIC WHERE EventDate BETWEEN '${start_date}' AND '${end_date}'
# MAGIC GROUP BY EventDate
# MAGIC ORDER BY EventDate DESC
# MAGIC LIMIT 1000

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Klarna — BNPL Settlement Reconciliation
# MAGIC
# MAGIC Cross-catalog join: `klarna_diagnostic.payment_events` × `trusted.fact_sales_orders`
# MAGIC Join key: `KlarnaOrderId = ExternalOrderRef` (both columns defined in DDL).
# MAGIC On BigQuery: becomes a cross-project join using fully-qualified table references.
# MAGIC IAM required: roles/bigquery.dataViewer on trusted project for Klarna SA.

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Klarna settlement reconciliation — cross-catalog join
# MAGIC -- trusted.fact_sales_orders.ExternalOrderRef ↔ klarna_diagnostic.payment_events.KlarnaOrderId
# MAGIC -- db2bq detects this as a cross-catalog join (G8) and emits NOTE(db2bq) annotation
# MAGIC SELECT
# MAGIC     ke.EventId,
# MAGIC     ke.KlarnaOrderId,
# MAGIC     ke.EventDate,
# MAGIC     get_json_object(ke.Payload, '$.capture_amount')  AS CapturedAmount,
# MAGIC     get_json_object(ke.Payload, '$.settlement_date') AS SettlementDate,
# MAGIC     fso.OrderAmount                                   AS BISOrderAmount,
# MAGIC     fso.ItemNumber                                    AS ItemNumber,
# MAGIC     fso.ExternalOrderRef,
# MAGIC     DATEDIFF(
# MAGIC         day,
# MAGIC         ke.EventTimestamp,
# MAGIC         CAST(get_json_object(ke.Payload, '$.settlement_date') AS TIMESTAMP)
# MAGIC     )                                                 AS SettlementDays,
# MAGIC     CASE
# MAGIC         WHEN ABS(
# MAGIC             CAST(get_json_object(ke.Payload, '$.capture_amount') AS DECIMAL(10,2))
# MAGIC             - fso.OrderAmount
# MAGIC         ) > 0.01 THEN 'MISMATCH'
# MAGIC         ELSE 'OK'
# MAGIC     END                                               AS ReconciliationStatus
# MAGIC FROM klarna_diagnostic.payment_events ke
# MAGIC LEFT JOIN trusted.fact_sales_orders fso
# MAGIC     ON ke.KlarnaOrderId = fso.ExternalOrderRef
# MAGIC WHERE ke.EventDate BETWEEN '${start_date}' AND '${end_date}'
# MAGIC   AND get_json_object(ke.Payload, '$.event_type') = 'SETTLEMENT_CREATED'

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. Cross-Provider Summary

# COMMAND ----------

cross_provider_df = spark.sql(f"""
    SELECT 'WooPayments' AS Provider,
           COUNT(*) AS EventCount,
           SUM(CAST(get_json_object(Payload, '$.amount') AS DOUBLE)) AS TotalAmount
    FROM wp_diagnostic.payment_events
    WHERE EventDate BETWEEN '{start_date}' AND '{end_date}'
    UNION ALL
    SELECT 'AmazonPay' AS Provider,
           COUNT(*) AS EventCount,
           SUM(CAST(get_json_object(Payload, '$.amount.value') AS DOUBLE)) AS TotalAmount
    FROM ap_diagnostic.payment_events
    WHERE EventDate BETWEEN '{start_date}' AND '{end_date}'
    UNION ALL
    SELECT 'PayPal' AS Provider,
           COUNT(*) AS EventCount,
           SUM(CAST(get_json_object(Payload, '$.amount.value') AS DOUBLE)) AS TotalAmount
    FROM pp_diagnostic.payment_events
    WHERE EventDate BETWEEN '{start_date}' AND '{end_date}'
    UNION ALL
    SELECT 'GooglePay' AS Provider,
           COUNT(*) AS EventCount,
           SUM(CAST(get_json_object(Payload, '$.amount') AS DOUBLE)) AS TotalAmount
    FROM gp_diagnostic.payment_events
    WHERE EventDate BETWEEN '{start_date}' AND '{end_date}'
    UNION ALL
    SELECT 'Klarna' AS Provider,
           COUNT(*) AS EventCount,
           SUM(CAST(get_json_object(Payload, '$.capture_amount') AS DOUBLE)) AS TotalAmount
    FROM klarna_diagnostic.payment_events
    WHERE EventDate BETWEEN '{start_date}' AND '{end_date}'
""")

display(cross_provider_df)

# COMMAND ----------

cross_provider_df.write.format("delta") \
    .mode("overwrite") \
    .saveAsTable("gold.payment_provider_summary")

logger.info("Payment provider summary written to gold.payment_provider_summary")

# COMMAND ----------

dbutils.widgets.removeAll()
