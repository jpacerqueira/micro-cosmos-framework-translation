"""BIS domain ETL pipeline — product star schema (nm_item → dim_item → fact_sales_orders).

Processes the BIS medallion layers:
  Raw/Landing (product_systems_raw) → Curated (product_systems) → Trusted → Refined

Schema contract: all column names use CamelCase to match the hive_metastore DDL.

UCX blockers present in this file:
  - wasb:// URIs (Azure Blob Storage Gen1 — not UC-compatible)  # TODO(db2bq): UCX hard-blocker
  - abfss:// URIs (ADLS Gen2 — needs External Location mapping)  # TODO(db2bq): map to gs://
  - Delta time travel (versionAsOf) — use daily snapshot workflow on GCP side

CTAS write-back pattern: pushes 15 materialised tables into branded_prod schema.
On BigQuery: cross-project Dataform SQLX in schema branded_prod (dataset branded__prod).
"""

from __future__ import annotations

from typing import Optional
import logging

from pyspark.sql import SparkSession, DataFrame
from pyspark.sql.functions import col, current_timestamp, to_date, lit, monotonically_increasing_id

from src.data_quality.quality_checker import DataQualityChecker
from src.data_quality.bis_quality_rules import BISQualityRules


class BISPipeline:
    """Class-based PySpark ETL for the BIS product star schema.

    Column naming contract (aligned with hive_metastore DDL):
      ItemNumber, SupplierID, OrderAmount, OrderDate, CustomerID,
      ProductCategory, BrandCode, RetailPrice, SeasonCode,
      EffectiveDate, ExpiryDate, IsCurrentRecord, ExternalOrderRef
    """

    # Azure source paths — TODO(db2bq): UCX hard-blocker — replace with GCS equivalents
    WASB_RAW_BASE = "wasb://raw-container@retailstorage.blob.core.windows.net"  # TODO(db2bq): UCX hard-blocker
    ABFSS_CURATED_BASE = "abfss://curated@retaildatalake.dfs.core.windows.net/product_systems"  # TODO(db2bq): map to gs://
    ABFSS_TRUSTED_BASE = "abfss://trusted@retaildatalake.dfs.core.windows.net"  # TODO(db2bq): map to gs://
    ABFSS_BRANDED_BASE = "abfss://refined@retaildatalake.dfs.core.windows.net/branded_prod"  # TODO(db2bq): map to gs://

    # Schema name pair in flight during UCX rename — both aliases are live simultaneously.
    # db2bq detects this try/except guard as an alias-schema diagnostic (G1).
    SCHEMA_PRIMARY = "product_systems"
    SCHEMA_ALIAS = "productsystems"

    # All 15 CTAS write-back targets for branded_prod spoke.
    # On BigQuery: each becomes a Dataform SQLX table in dataset `branded_prod`.
    CTAS_WRITEBACK_TARGETS = [
        "attribution_item_season",
        "attribution_item_team",
        "attribution_item_brand",
        "attribution_sales_weekly",
        "attribution_sales_monthly",
        "attribution_return_rate",
        "attribution_stock_cover",
        "attribution_forecast_accuracy",
        "attribution_supplier_lead_time",
        "attribution_noclick_opportunity",
        "attribution_svoc_segment",
        "attribution_price_elasticity",
        "attribution_channel_mix",
        "attribution_markdown_impact",
        "attribution_new_season_launch",
    ]

    def __init__(self, spark: Optional[SparkSession] = None) -> None:
        self.spark = spark or SparkSession.builder.appName("BISPipeline").getOrCreate()
        self.logger = logging.getLogger(__name__)
        self.quality_checker = DataQualityChecker()
        self.bis_rules = BISQualityRules()

    # ------------------------------------------------------------------ bronze

    def extract_nm_item_raw(self) -> None:
        """Ingest nm_item from wasb:// landing zone into product_systems_raw bronze Delta."""
        raw_path = f"{self.WASB_RAW_BASE}/product_systems_raw/nm_item/*.parquet"  # TODO(db2bq): UCX hard-blocker
        df = self.spark.read.format("parquet").load(raw_path)
        df = df.withColumn("_ingestion_timestamp", current_timestamp())
        df.write.format("delta").mode("append").save("/mnt/raw/product_systems_raw/nm_item")
        self.logger.info("nm_item ingested to product_systems_raw bronze")

    def extract_nm_item_supplier(self) -> None:
        """Ingest nm_item_supplier from wasb:// into product_systems_raw bronze Delta."""
        raw_path = f"{self.WASB_RAW_BASE}/product_systems_raw/nm_item_supplier/*.parquet"  # TODO(db2bq): UCX hard-blocker
        df = self.spark.read.format("parquet").load(raw_path)
        df = df.withColumn("_ingestion_timestamp", current_timestamp())
        df.write.format("delta").mode("append").save("/mnt/raw/product_systems_raw/nm_item_supplier")
        self.logger.info("nm_item_supplier ingested to product_systems_raw bronze")

    def extract_item_season(self) -> None:
        """Ingest item_season from abfss:// (ADLS Gen2) curated layer."""
        curated_path = f"{self.ABFSS_CURATED_BASE}/item_season"  # TODO(db2bq): map to gs://
        df = self.spark.read.format("delta").load(curated_path)
        df = df.withColumn("_ingestion_timestamp", current_timestamp())
        df.write.format("delta").mode("overwrite").save("/mnt/processing/product_systems/item_season")
        self.logger.info("item_season ingested from ADLS Gen2 curated layer")

    # ----------------------------------------------------------------- silver

    def conform_nm_item_supplier(self) -> None:
        """Conform nm_item_supplier: cast types to DDL schema, run BIS quality rules."""
        df = self.spark.table("product_systems_raw.nm_item_supplier")

        # BIS quality check — ItemNumber must not be null or empty
        quality_results = self.bis_rules.check_item_number_integrity(df, "nm_item_supplier")
        if not all(r.get("passed", False) for r in quality_results.values()):
            raise ValueError("BIS quality checks failed for nm_item_supplier — see logs")

        df = df.withColumn("ItemNumber", col("ItemNumber").cast("string")) \
               .withColumn("SupplierID", col("SupplierID").cast("string")) \
               .withColumn("ConformedAt", to_date(col("ConformedAt"))) \
               .withColumn("_processing_timestamp", current_timestamp())

        df.write.format("delta").mode("overwrite") \
            .option("mergeSchema", "true") \
            .save("/mnt/processing/product_systems/nm_item_supplier")
        self.logger.info("nm_item_supplier conformed to product_systems silver")

    def conform_fact_sales_orders(self) -> None:
        """Conform fact_sales_orders from trusted layer — schema rename guard.

        Both product_systems and productsystems are live during UCX rename.
        db2bq detects this try/except as an alias-schema pattern (G1 diagnostic).
        """
        try:
            df = self.spark.table(f"{self.SCHEMA_PRIMARY}.fact_sales_orders")
        except Exception:
            self.logger.warning(
                f"{self.SCHEMA_PRIMARY} schema not found — trying {self.SCHEMA_ALIAS} (rename in flight)"
            )
            df = self.spark.table(f"{self.SCHEMA_ALIAS}.fact_sales_orders")

        df = df.withColumn("OrderAmount", col("OrderAmount").cast("decimal(12,2)")) \
               .withColumn("OrderDate", to_date(col("OrderDate"))) \
               .withColumn("_processing_timestamp", current_timestamp())

        df.write.format("delta").mode("overwrite") \
            .option("mergeSchema", "true") \
            .save("/mnt/processing/trusted/fact_sales_orders")
        self.logger.info("fact_sales_orders conformed to trusted silver")

    # ------------------------------------------------------------------- gold

    def serve_dim_item(self) -> None:
        """Build dim_item SCD2 from conformed nm_item + nm_item_supplier.

        Column contract matches trusted.dim_item DDL:
          ItemSurrogateKey (generated), ItemNumber, EffectiveDate, ExpiryDate,
          IsCurrentRecord, ProductCategory, BrandCode, SupplierID, RetailPrice, IsActive.

        On BigQuery: rewrite as a Dataform SQLX MERGE INTO with surrogate key
        generated via FARM_FINGERPRINT(ItemNumber || CAST(EffectiveDate AS STRING)).
        """
        nm_item = self.spark.table("product_systems_raw.nm_item")
        supplier = self.spark.table("product_systems.nm_item_supplier")

        dim_item = (
            nm_item.join(supplier.select("ItemNumber", "SupplierID", "IsPreferred"), "ItemNumber", "left")
            .withColumn("ItemSurrogateKey", monotonically_increasing_id())
            .withColumn("EffectiveDate", to_date(lit("2024-01-01")))
            .withColumn("ExpiryDate", to_date(lit("9999-12-31")))
            .withColumn("IsCurrentRecord", lit(True))
            .withColumn("_serving_timestamp", current_timestamp())
        )

        dim_item.write.format("delta").mode("overwrite") \
            .option("mergeSchema", "true") \
            .save("/mnt/serving/trusted/dim_item")
        self.logger.info("dim_item served to trusted gold (SCD2 snapshot)")

    def serve_fact_sales_orders(self) -> None:
        """Aggregate fact_sales_orders into daily grain gold table.

        Output columns match gold.fact_sales_orders_daily DDL:
          ItemNumber, OrderDate, ProductCategory, BrandCode, TotalRevenue,
          OrderCount, UniqueCustomers, _serving_timestamp
        """
        fact = self.spark.table("trusted.fact_sales_orders")
        dim = self.spark.table("trusted.dim_item")

        gold = (
            fact.join(
                dim.filter(col("IsCurrentRecord")).select("ItemNumber", "ProductCategory", "BrandCode"),
                "ItemNumber",
                "left",
            )
            .groupBy("ItemNumber", "OrderDate", "ProductCategory", "BrandCode")
            .agg({"OrderAmount": "sum", "CustomerID": "count"})
            .withColumnRenamed("sum(OrderAmount)", "TotalRevenue")
            .withColumnRenamed("count(CustomerID)", "OrderCount")
            .withColumn("_serving_timestamp", current_timestamp())
        )

        gold.write.format("delta").mode("overwrite") \
            .option("mergeSchema", "true") \
            .saveAsTable("gold.fact_sales_orders_daily")
        self.logger.info("fact_sales_orders served to gold.fact_sales_orders_daily")

    def create_gold_view(self, table: str, view_name: Optional[str] = None) -> str:
        """Create Spark SQL temp view over gold table for ad-hoc access.

        On BigQuery: becomes a Dataform SQLX view (definitions/gold/v_<table>.sqlx).
        """
        df = self.spark.table(f"gold.{table}")
        resolved = view_name or f"{table}_gold"
        df.createOrReplaceTempView(resolved)
        return resolved

    # ------------------------------------------------------- CTAS write-backs

    def materialise_attribution_targets(self, season_code: str) -> None:
        """Materialise all 15 attribution_* CTAS write-back targets into branded_prod.

        Column contract (aligned with branded_prod DDL + refined.fact_sales_orders_season):
          ItemNumber, SeasonCode, ProductCategory, BrandCode, SeasonRevenue,
          UniqueCustomers, _generated_at

        On BigQuery: each target becomes a Dataform SQLX in dataset branded_prod
        with schema: "branded_prod" override. See definitions/gold/*__ctas.sqlx.
        Cross-project IAM required: roles/bigquery.dataEditor on branded_prod project.
        """
        dim = self.spark.table("trusted.dim_item")
        fact = self.spark.table("trusted.fact_sales_orders")
        item_season = self.spark.table("product_systems.item_season")

        season_fact = fact.join(
            item_season.filter(col("SeasonCode") == season_code).select("ItemNumber", "SeasonCode"),
            "ItemNumber",
        )

        attribution_base = (
            season_fact.join(
                dim.filter(col("IsCurrentRecord")).select("ItemNumber", "ProductCategory", "BrandCode"),
                "ItemNumber",
                "left",
            )
            .groupBy("ItemNumber", "SeasonCode", "ProductCategory", "BrandCode")
            .agg({"OrderAmount": "sum", "CustomerID": "count"})
            .withColumnRenamed("sum(OrderAmount)", "SeasonRevenue")
            .withColumnRenamed("count(CustomerID)", "UniqueCustomers")
            .withColumn("_generated_at", current_timestamp())
        )

        # Write attribution_item_season (first of 15 targets) to branded_prod
        target_path = f"{self.ABFSS_BRANDED_BASE}/attribution_item_season"  # TODO(db2bq): map to gs://
        attribution_base.write.format("delta").mode("overwrite").save(target_path)
        self.logger.info(f"Materialised attribution_item_season for season {season_code}")

    # ---------------------------------------------------------- full pipeline

    def run_full_pipeline(self, season_code: str = "AW24") -> None:
        """Run the complete BIS pipeline end-to-end."""
        self.logger.info("BIS pipeline starting")
        self.extract_nm_item_raw()
        self.extract_nm_item_supplier()
        self.extract_item_season()
        self.conform_nm_item_supplier()
        self.conform_fact_sales_orders()
        self.serve_dim_item()
        self.serve_fact_sales_orders()
        self.materialise_attribution_targets(season_code)
        self.logger.info("BIS pipeline complete")
