# Databricks notebook source
"""BIS Hub Pipeline — class-based PySpark ETL for BIS analytics layer.

Representative of the Next BIS hub pattern:
- Multi-layer (bronze/silver/gold methods)
- 20 CTAS write-back targets (vs 15 in project1 — reflects real scale)
- Cross-catalog reads from spoke domains
"""

from pyspark.sql import SparkSession


class BISHubPipeline:
    CTAS_WRITEBACK_TARGETS = [
        "attribution_channel_mix",
        "attribution_campaign",
        "attribution_item_brand",
        "attribution_item_season",
        "attribution_item_team",
        "attribution_markdown_impact",
        "attribution_new_season_launch",
        "attribution_noclick_opportunity",
        "attribution_price_elasticity",
        "attribution_return_rate",
        "attribution_sales_monthly",
        "attribution_sales_weekly",
        "attribution_stock_cover",
        "attribution_supplier_lead_time",
        "attribution_svoc_segment",
        "attribution_brand_halo",
        "attribution_channel_roi",
        "attribution_cohort_ltv",
        "attribution_markdown_depth",
        "attribution_roas",
    ]

    HUB_CATALOG = "businessintelligencesystems_prod"
    SPOKE_CATALOGS = [
        "marketingdata_prod",
        "warehouselogistics_prod",
        "brandedretail_prod",
        "finance_prod",
        "product_prod",
        "hr_prod",
        "contactcentre_prod",
    ]

    def __init__(self, spark: SparkSession):
        self.spark = spark

    def extract_bronze_data(self, source_path: str, table_name: str):
        df = (
            self.spark.read
            .format("parquet")
            .load(source_path)
        )
        df.write.format("delta").mode("overwrite").saveAsTable(
            f"{self.HUB_CATALOG}.bronze.{table_name}"
        )
        return df

    def conform_silver_data(self, table_name: str):
        df = self.spark.table(f"{self.HUB_CATALOG}.bronze.{table_name}")
        df_clean = df.dropDuplicates().na.drop(subset=["id"])
        df_clean.write.format("delta").mode("overwrite").saveAsTable(
            f"{self.HUB_CATALOG}.silver.{table_name}_conformed"
        )
        return df_clean

    def serve_gold_analytics(self, target_table: str):
        self.spark.sql(f"""
            CREATE OR REPLACE TABLE {self.HUB_CATALOG}.gold.{target_table} AS
            SELECT * FROM {self.HUB_CATALOG}.silver.{target_table}_conformed
        """)

    def materialise_attribution_targets(self):
        for target in self.CTAS_WRITEBACK_TARGETS:
            self.spark.sql(f"""
                CREATE OR REPLACE TABLE {self.HUB_CATALOG}.attribution.{target} AS
                SELECT
                    brand_id,
                    channel,
                    SUM(revenue) AS total_revenue
                FROM marketingdata_prod.attribution.source_data
                JOIN {self.HUB_CATALOG}.dimensions.brand USING (brand_id)
                GROUP BY brand_id, channel
            """)

    def create_gold_view(self, table_name: str):
        self.spark.sql(f"""
            CREATE OR REPLACE VIEW {self.HUB_CATALOG}.gold.v_{table_name} AS
            SELECT * FROM {self.HUB_CATALOG}.gold.{table_name}
        """)
