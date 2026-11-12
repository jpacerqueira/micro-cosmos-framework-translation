"""Branded Spoke — REPLACE write-back pipeline.

Reads from BIS hub (businessintelligencesystems_prod) and materialises into branded_prod.
This is the dominant write pattern in the Next estate for branded/spoke catalogs.

GCP mapping: Dataform incremental models with full_refresh=false. The REPLACE pattern
maps naturally to Dataform's incremental strategy — avoids full table scans on each run.
"""

from pyspark.sql import SparkSession


class BrandedReplacePipeline:
    REPLACE_TARGETS = [
        "branded_attribution_summary",
        "branded_channel_mix",
        "branded_cohort_analysis",
        "branded_inventory_health",
        "branded_margin_by_sku",
    ]

    BIS_CATALOG = "businessintelligencesystems_prod"
    BRANDED_CATALOG = "branded_prod"

    def __init__(self, spark: SparkSession):
        self.spark = spark

    def rebuild_branded_views(self, target_catalog: str = "branded_prod"):
        for target in self.REPLACE_TARGETS:
            self.spark.sql(f"""
                CREATE OR REPLACE TABLE {target_catalog}.attribution.{target} AS
                SELECT
                    b.brand_id,
                    b.brand_name,
                    a.channel,
                    a.campaign_id,
                    SUM(a.attributed_revenue) AS total_attributed_revenue,
                    SUM(a.margin) AS total_margin,
                    COUNT(DISTINCT a.order_id) AS order_count
                FROM {self.BIS_CATALOG}.attribution.channel_mix a
                JOIN {self.BIS_CATALOG}.dimensions.brand b
                    ON a.brand_id = b.brand_id
                WHERE a.attribution_date >= DATEADD(day, -90, GETDATE())
                GROUP BY b.brand_id, b.brand_name, a.channel, a.campaign_id
            """)

    def validate_replace_completeness(self) -> dict:
        results = {}
        for target in self.REPLACE_TARGETS:
            count = self.spark.sql(
                f"SELECT COUNT(*) AS n FROM {self.BRANDED_CATALOG}.attribution.{target}"
            ).collect()[0]["n"]
            results[target] = count
        return results
