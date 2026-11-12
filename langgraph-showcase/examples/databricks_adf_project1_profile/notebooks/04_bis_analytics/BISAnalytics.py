# Databricks notebook source
# COMMAND ----------

# MAGIC %md
# MAGIC # BIS Analytics — Product Star Schema
# MAGIC
# MAGIC Queries across the BIS hub (`businessintelligencesystems_prod`) and branded spoke
# MAGIC (`branded_prod`) to produce item-level sales and stock analytics.
# MAGIC
# MAGIC **Catalogs referenced:** `businessintelligencesystems_prod`, `branded_prod`
# MAGIC
# MAGIC **Schema contract:** All column names use CamelCase aligned with hive_metastore DDL.
# MAGIC
# MAGIC **UCX note:** Cross-catalog joins use `spark.table("schema.table")` — on Unity Catalog
# MAGIC migration these become cross-project BigQuery joins via `<project>.<dataset>.<table>` FQNs.
# MAGIC Verify IAM roles/bigquery.dataViewer on both projects before enabling.

# COMMAND ----------

# MAGIC %md
# MAGIC ## Parameters

# COMMAND ----------

dbutils.widgets.text("report_date", "", "Report Date (yyyy-MM-dd)")
dbutils.widgets.text("season_code", "AW24", "Season Code")
dbutils.widgets.dropdown("output_mode", "overwrite", ["overwrite", "append"], "Output Mode")

# COMMAND ----------

# MAGIC %md
# MAGIC ## Imports

# COMMAND ----------

from pyspark.sql import SparkSession
from pyspark.sql.functions import col, current_timestamp, get_json_object
import logging

spark = SparkSession.builder.appName("BISAnalytics").getOrCreate()
logger = logging.getLogger(__name__)

report_date = dbutils.widgets.get("report_date")
season_code = dbutils.widgets.get("season_code")
output_mode = dbutils.widgets.get("output_mode")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 1. Load BIS Dimension Tables (via Hive Metastore schema-qualified reads)

# COMMAND ----------

# Read dim_item from trusted schema — spark.table() uses Hive metastore registration.
# On BigQuery: SELECT * FROM `my-gcp-project.gold.dim_item` WHERE IsCurrentRecord = TRUE
dim_item_df = spark.table("trusted.dim_item")
dim_item_df.createOrReplaceTempView("dim_item")

# Read item_season from product_systems silver schema
item_season_df = spark.table("product_systems.item_season")
item_season_df.createOrReplaceTempView("item_season")

# Read fact_sales_orders from trusted schema — Delta time travel for season window.
# TODO(db2bq): .option("timestampAsOf", ...) is Delta-specific — use BQ snapshot DAG instead.
fact_sales_df = spark.read.format("delta") \
    .option("timestampAsOf", report_date if report_date else "2024-10-01") \
    .load("/mnt/serving/trusted/fact_sales_orders")
fact_sales_df.createOrReplaceTempView("fact_sales_orders")

logger.info("BIS dimension and fact tables loaded from Hive metastore")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 2. Load Branded Spoke Data (cross-catalog join via Hive metastore)

# COMMAND ----------

# Read noclick_stock_levels from branded_prod schema via spark.table()
# Previously: wasb://branded-container@retailstorage.blob.core.windows.net/noclick_stock_levels
# Now: spark.table() resolves via Hive metastore LOCATION (UCX-safe path)
noclick_df = spark.table("branded_prod.noclick_stock_levels")
noclick_df.createOrReplaceTempView("noclick_stock_levels")

# Read attribution_item_season from branded_prod schema
# Previously: abfss://refined@retaildatalake.dfs.core.windows.net/branded_prod/attribution_item_season
# Now: spark.table() resolves via Hive metastore  # TODO(db2bq): map branded_prod to gs:// GCS bucket
attribution_df = spark.table("branded_prod.attribution_item_season")
attribution_df.createOrReplaceTempView("attribution_item_season")

logger.info("Branded spoke tables loaded from branded_prod schema")

# COMMAND ----------

# MAGIC %md
# MAGIC ## 3. Cross-Catalog Item Sales vs Stock Analysis
# MAGIC
# MAGIC Joins BIS trusted `dim_item` to `branded_prod.noclick_stock_levels` on `ItemNumber`.
# MAGIC This is the hub-and-spoke runtime join flagged in the PSO lineage report.
# MAGIC Column names aligned with hive_metastore DDL (CamelCase).

# COMMAND ----------

# MAGIC %sql
# MAGIC -- trusted.dim_item × branded_prod.noclick_stock_levels cross-catalog join
# MAGIC -- Join key: ItemNumber (maintained consistently across both schemas in DDL)
# MAGIC SELECT
# MAGIC     di.ItemNumber,
# MAGIC     di.ProductCategory,
# MAGIC     di.BrandCode,
# MAGIC     di.RetailPrice,
# MAGIC     ns.StockLevel,
# MAGIC     ns.AvailableUnits,
# MAGIC     ns.WarehouseLocation,
# MAGIC     fso.TotalRevenue,
# MAGIC     fso.OrderCount,
# MAGIC     CASE
# MAGIC         WHEN ns.StockLevel = 0 THEN 'Out of Stock'
# MAGIC         WHEN ns.StockLevel < 10 THEN 'Low Stock'
# MAGIC         ELSE 'In Stock'
# MAGIC     END AS StockStatus,
# MAGIC     current_timestamp() AS _report_generated
# MAGIC FROM dim_item di
# MAGIC LEFT JOIN noclick_stock_levels ns
# MAGIC     ON di.ItemNumber = ns.ItemNumber
# MAGIC    AND di.IsCurrentRecord = TRUE
# MAGIC LEFT JOIN (
# MAGIC     SELECT ItemNumber, SUM(OrderAmount) AS TotalRevenue, COUNT(OrderID) AS OrderCount
# MAGIC     FROM fact_sales_orders
# MAGIC     GROUP BY ItemNumber
# MAGIC ) fso ON di.ItemNumber = fso.ItemNumber
# MAGIC WHERE di.IsCurrentRecord = TRUE
# MAGIC   AND di.BrandCode IS NOT NULL

# COMMAND ----------

# MAGIC %md
# MAGIC ## 4. Season Attribution — CTAS Write-back Pattern
# MAGIC
# MAGIC Materialises a season-level attribution table into the branded spoke.
# MAGIC Column names aligned with branded_prod.attribution_item_season DDL.
# MAGIC On BigQuery: becomes a Dataform SQLX table with schema override `branded_prod`.

# COMMAND ----------

# MAGIC %sql
# MAGIC -- CTAS write-back: materialise season attribution into branded_prod schema
# MAGIC -- branded_prod.attribution_item_season is target 1 of 15 CTAS write-back targets
# MAGIC -- Column names match branded_prod DDL: ItemNumber, SeasonCode, SeasonStartDate, etc.
# MAGIC CREATE OR REPLACE TABLE ${season_code}_attribution_item_season AS
# MAGIC SELECT
# MAGIC     iss.ItemNumber,
# MAGIC     iss.SeasonCode,
# MAGIC     iss.SeasonStartDate,
# MAGIC     iss.SeasonEndDate,
# MAGIC     di.ProductCategory,
# MAGIC     di.BrandCode,
# MAGIC     SUM(fso.OrderAmount)             AS SeasonRevenue,
# MAGIC     COUNT(DISTINCT fso.CustomerID)   AS UniqueCustomers,
# MAGIC     DATE_SUB(iss.SeasonEndDate, 7)   AS PreSeasonCutoff,
# MAGIC     current_timestamp()              AS GeneratedAt
# MAGIC FROM item_season iss
# MAGIC JOIN dim_item di
# MAGIC     ON iss.ItemNumber = di.ItemNumber
# MAGIC    AND di.IsCurrentRecord = TRUE
# MAGIC LEFT JOIN fact_sales_orders fso
# MAGIC     ON iss.ItemNumber = fso.ItemNumber
# MAGIC     AND fso.OrderDate BETWEEN iss.SeasonStartDate AND iss.SeasonEndDate
# MAGIC WHERE iss.SeasonCode = '${season_code}'
# MAGIC GROUP BY
# MAGIC     iss.ItemNumber, iss.SeasonCode, iss.SeasonStartDate, iss.SeasonEndDate,
# MAGIC     di.ProductCategory, di.BrandCode

# COMMAND ----------

# MAGIC %md
# MAGIC ## 5. Schema Rename Dual-Read (productsystems → product_systems)
# MAGIC
# MAGIC During the UCX migration the `productsystems` schema is being renamed to
# MAGIC `product_systems`. Both names are live simultaneously — this cell reads both.
# MAGIC db2bq flags this as alias-schema diagnostic G1.

# COMMAND ----------

# MAGIC %sql
# MAGIC -- Schema rename monitoring: both names may be live during migration
# MAGIC -- product_systems is the post-rename target; productsystems is the legacy alias
# MAGIC -- db2bq G1: both will be detected as duplicate TableModel entries — deduplicate manually
# MAGIC SELECT 'product_systems' AS SchemaAlias, COUNT(*) AS RowCount
# MAGIC FROM product_systems.item_season
# MAGIC UNION ALL
# MAGIC SELECT 'productsystems' AS SchemaAlias, COUNT(*) AS RowCount
# MAGIC FROM productsystems.item_season

# COMMAND ----------

# MAGIC %md
# MAGIC ## 6. T-SQL Date Arithmetic (legacy pattern — translated by db2bq T-SQL rewriter)
# MAGIC
# MAGIC These T-SQL functions are automatically translated by db2bq:
# MAGIC   DATEADD(day, N, col) → DATE_ADD(col, INTERVAL N DAY)
# MAGIC   DATEDIFF(day, a, b)  → DATE_DIFF(b, a, DAY)
# MAGIC   GETDATE()            → CURRENT_TIMESTAMP()
# MAGIC   ISNULL(a, b)         → COALESCE(a, b)
# MAGIC   LEN(x)               → LENGTH(x)
# MAGIC   SELECT TOP N         → SELECT ... LIMIT N

# COMMAND ----------

# MAGIC %sql
# MAGIC -- T-SQL dialect — DATEADD / GETDATE / DATEDIFF / ISNULL / LEN / SELECT TOP
# MAGIC -- db2bq T-SQL rewriter translates these automatically to BigQuery-compatible SQL
# MAGIC SELECT TOP 100
# MAGIC     ItemNumber,
# MAGIC     OrderDate,
# MAGIC     DATEADD(day, 7, OrderDate)             AS DeliveryEstimate,
# MAGIC     DATEADD(month, -3, GETDATE())          AS ThreeMonthsAgo,
# MAGIC     DATEDIFF(day, OrderDate, GETDATE())    AS DaysSinceOrder,
# MAGIC     ISNULL(ReturnFlag, 0)                  AS EffectiveReturnFlag,
# MAGIC     LEN(ItemNumber)                        AS ItemNumberLength,
# MAGIC     ExternalOrderRef
# MAGIC FROM fact_sales_orders
# MAGIC WHERE DATEDIFF(day, OrderDate, GETDATE()) <= 90

# COMMAND ----------

# MAGIC %md
# MAGIC ## 7. Write Gold Layer — Item Season Performance

# COMMAND ----------

item_season_gold_df = spark.sql("""
    SELECT
        iss.ItemNumber,
        iss.SeasonCode,
        di.ProductCategory,
        di.BrandCode,
        di.RetailPrice,
        COUNT(fso.OrderID)       AS OrderCount,
        SUM(fso.OrderAmount)     AS TotalRevenue,
        AVG(fso.OrderAmount)     AS AvgOrderValue,
        current_timestamp()      AS _serving_timestamp
    FROM item_season iss
    JOIN dim_item di
        ON iss.ItemNumber = di.ItemNumber
       AND di.IsCurrentRecord = TRUE
    LEFT JOIN fact_sales_orders fso ON iss.ItemNumber = fso.ItemNumber
    GROUP BY iss.ItemNumber, iss.SeasonCode, di.ProductCategory, di.BrandCode, di.RetailPrice
""")

item_season_gold_df.write.format("delta") \
    .mode(output_mode) \
    .option("mergeSchema", "true") \
    .saveAsTable("gold.item_season_performance")

logger.info("Gold layer gold.item_season_performance written")

# COMMAND ----------

display(spark.table("gold.item_season_performance").limit(20))

# COMMAND ----------

dbutils.widgets.removeAll()
