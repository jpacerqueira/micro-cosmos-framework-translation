# Databricks notebook source
# Warehouse Streaming Staging — INSERT-into-staging landing zone pattern.
# Despite the name 'streaming', this is a scheduled BATCH notebook.
# No Event Hub / Kafka consumer. Runs hourly via ADF trigger.
# GCP target: BigQuery Subscription (NOT Dataflow).
# Dataflow would only be warranted for stateful transforms (dedup windows, SCD joins at
# ingestion, windowed aggregations) — none of which are present here.

# COMMAND ----------

import pyspark.sql.functions as F
from datetime import datetime

STAGING_TABLE = "warehouselogistics_prod.streaming_data_staging.order_events"
DOWNSTREAM_TABLE = "warehouseworkflow_prod.reports.order_summary"
SOURCE_TABLE = "warehouselogistics_prod.events.raw_order_events"

batch_timestamp = datetime.utcnow().isoformat()

# COMMAND ----------

# MAGIC %sql
-- INSERT INTO staging landing zone from raw events table.
-- This is a batch INSERT (hourly schedule), not a real streaming operation.
-- The schema name 'streaming_data_staging' is a legacy label from Databricks — not Event Hub.
INSERT INTO warehouselogistics_prod.streaming_data_staging.order_events
SELECT
    order_id,
    warehouse_id,
    event_type,
    get_json_object(event_payload, '$.quantity') AS quantity,
    get_json_object(event_payload, '$.sku_code') AS sku_code,
    event_timestamp,
    CURRENT_TIMESTAMP() AS ingested_at
FROM warehouselogistics_prod.events.raw_order_events
WHERE event_timestamp >= DATEADD(hour, -1, GETDATE())
  AND order_id IS NOT NULL

# COMMAND ----------

# MAGIC %sql
-- Downstream report: reads from staging, aggregates into report table.
INSERT INTO warehouseworkflow_prod.reports.order_summary
SELECT
    warehouse_id,
    event_type,
    SUM(CAST(quantity AS BIGINT)) AS total_quantity,
    COUNT(DISTINCT order_id) AS order_count,
    CAST(DATEADD(hour, 0, GETDATE()) AS DATE) AS report_date
FROM warehouselogistics_prod.streaming_data_staging.order_events
WHERE ingested_at >= DATEADD(minute, -65, GETDATE())
GROUP BY warehouse_id, event_type

# COMMAND ----------

# Python: refresh materialised downstream view
spark.sql(f"""
    CREATE OR REPLACE VIEW warehouseworkflow_prod.reports.v_order_summary_latest AS
    SELECT
        warehouse_id,
        event_type,
        total_quantity,
        order_count,
        report_date,
        get_json_object(metadata, '$.region') AS region
    FROM warehouseworkflow_prod.reports.order_summary
    WHERE report_date = CURRENT_DATE()
""")
