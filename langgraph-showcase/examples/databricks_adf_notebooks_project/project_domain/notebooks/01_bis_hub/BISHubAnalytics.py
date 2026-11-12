# Databricks notebook source
# BIS Hub Analytics — representative of the Next BIS hub catalog notebook patterns.
# Patterns covered:
#   - abfss:// storage URIs (UCX note annotation)
#   - Three-part cross-catalog SQL references (3 different catalogs in one query)
#   - T-SQL dialect: DATEADD, DATEDIFF, SELECT TOP, ISNULL, LEN
#   - CREATE OR REPLACE TABLE (CTAS annotation)
#   - get_json_object in SQL cell
#   - get_json_object in spark.sql() Python block

# COMMAND ----------

import json
from pyspark.sql import functions as F

# abfss:// URI — UCX note: needs External Location → map to gs://
raw_path = "abfss://bronze@nextdatalake.dfs.core.windows.net/crm/customer_360"
processing_path = "abfss://silver@nextdatalake.dfs.core.windows.net/analytics"

# COMMAND ----------

# MAGIC %sql
-- Cross-catalog analytical query: BIS hub reads from marketing and warehouse spokes.
-- Three catalogs in one query → cross-catalog migration concern.
SELECT
    c.customer_id,
    c.segment,
    o.order_date,
    DATEADD(day, -7, GETDATE()) AS week_ago,
    DATEDIFF(day, o.order_date, GETDATE()) AS days_since_order,
    ISNULL(m.attributed_revenue, 0) AS attributed_revenue,
    LEN(c.sku_code) AS sku_code_length,
    w.stock_units
FROM businessintelligencesystems_prod.analytics.customer_orders c
JOIN marketingdata_prod.attribution.channel_mix m
    ON c.customer_id = m.customer_id
JOIN warehouselogistics_prod.inventory.stock_cover w
    ON c.sku_code = w.sku_code
WHERE c.order_date >= DATEADD(day, -90, GETDATE())

# COMMAND ----------

# MAGIC %sql
SELECT TOP 1000
    brand_id,
    SUM(revenue) AS total_revenue,
    COUNT(DISTINCT order_id) AS order_count
FROM businessintelligencesystems_prod.analytics.customer_orders
WHERE order_date >= DATEADD(day, -30, GETDATE())
GROUP BY brand_id
ORDER BY total_revenue DESC

# COMMAND ----------

# MAGIC %sql
-- CTAS write-back: materialise BIS-derived summary into branded_prod
-- Runs 30-60 times per table in March query history.
CREATE OR REPLACE TABLE branded_prod.analytics.customer_summary AS
SELECT
    c.customer_id,
    c.segment,
    SUM(o.revenue) AS total_revenue,
    COUNT(DISTINCT o.order_id) AS order_count
FROM businessintelligencesystems_prod.analytics.customer_orders o
JOIN businessintelligencesystems_prod.dimensions.customer c
    ON o.customer_id = c.customer_id
GROUP BY c.customer_id, c.segment

# COMMAND ----------

# MAGIC %sql
-- JSON payload from warehouse event log — get_json_object in SQL cell
SELECT
    event_id,
    get_json_object(event_payload, '$.event_type') AS event_type,
    get_json_object(event_payload, '$.warehouse_id') AS warehouse_id,
    get_json_object(event_payload, '$.quantity') AS quantity,
    event_timestamp
FROM warehouselogistics_prod.events.warehouse_event_log
WHERE event_timestamp >= DATEADD(hour, -24, GETDATE())

# COMMAND ----------

# Python cell: spark.sql with get_json_object in embedded SQL string
result_df = spark.sql(f"""
    SELECT
        order_id,
        get_json_object(order_metadata, '$.channel') AS channel,
        get_json_object(order_metadata, '$.promo_code') AS promo_code,
        get_json_object(order_metadata, '$.fulfilment_type') AS fulfilment_type
    FROM businessintelligencesystems_prod.analytics.customer_orders
    WHERE order_date >= DATEADD(day, -7, GETDATE())
""")

result_df.write.format("delta").mode("overwrite").saveAsTable(
    "businessintelligencesystems_prod.analytics.channel_attribution_staging"
)
