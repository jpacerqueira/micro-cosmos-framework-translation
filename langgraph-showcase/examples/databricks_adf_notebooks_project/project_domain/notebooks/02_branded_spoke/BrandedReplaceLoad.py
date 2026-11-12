# Databricks notebook source
# Branded Spoke — REPLACE write-back pattern.
# Reads from BIS hub (businessintelligencesystems_prod) and materialises into branded_prod.
# This is the dominant write pattern in the Next estate: 24 internal edges + 11 from BIS.
# Runs 30-60 times per table per month in March 2026 query history.
# GCP target: Dataform incremental models (NOT full table replace on every run).

# COMMAND ----------

import pyspark.sql.functions as F

# abfss:// URI reference
branded_output_path = "abfss://gold@nextdatalake.dfs.core.windows.net/branded_prod/attribution"

REPLACE_TARGETS = [
    "branded_attribution_summary",
    "branded_channel_mix",
    "branded_cohort_analysis",
    "branded_inventory_health",
    "branded_margin_by_sku",
]

# COMMAND ----------

# MAGIC %sql
-- REPLACE write-back: branded spoke reads from BIS hub, materialises locally.
-- Cross-catalog: branded_prod writes, businessintelligencesystems_prod reads.
CREATE OR REPLACE TABLE branded_prod.attribution.branded_attribution_summary AS
SELECT
    b.brand_id,
    b.brand_name,
    a.channel,
    SUM(a.attributed_revenue) AS total_attributed_revenue,
    SUM(a.margin) AS total_margin,
    COUNT(DISTINCT a.order_id) AS order_count
FROM businessintelligencesystems_prod.attribution.channel_mix a
JOIN businessintelligencesystems_prod.dimensions.brand b
    ON a.brand_id = b.brand_id
WHERE a.attribution_date >= DATEADD(day, -90, GETDATE())
GROUP BY b.brand_id, b.brand_name, a.channel

# COMMAND ----------

# Python cell: loop REPLACE across all targets
for target in REPLACE_TARGETS:
    spark.sql(f"""
        CREATE OR REPLACE TABLE branded_prod.attribution.{target} AS
        SELECT
            b.brand_id,
            get_json_object(m.metadata, '$.campaign_id') AS campaign_id,
            SUM(m.attributed_revenue) AS total_revenue
        FROM businessintelligencesystems_prod.attribution.channel_mix m
        JOIN businessintelligencesystems_prod.dimensions.brand b
            ON m.brand_id = b.brand_id
        WHERE m.attribution_date >= DATEADD(day, -30, GETDATE())
        GROUP BY b.brand_id, get_json_object(m.metadata, '$.campaign_id')
    """)

# COMMAND ----------

# MAGIC %sql
-- Cross-catalog: branded reads from marketing spoke too
CREATE OR REPLACE TABLE branded_prod.analytics.channel_roi AS
SELECT
    m.channel,
    m.brand_id,
    ISNULL(m.attributed_revenue, 0) AS attributed_revenue,
    ISNULL(m.spend, 0) AS spend,
    CASE WHEN ISNULL(m.spend, 0) = 0 THEN 0
         ELSE ISNULL(m.attributed_revenue, 0) / m.spend END AS roi
FROM marketingdata_prod.attribution.channel_mix m
JOIN businessintelligencesystems_prod.dimensions.brand b
    ON m.brand_id = b.brand_id
WHERE LEN(m.channel) > 0
