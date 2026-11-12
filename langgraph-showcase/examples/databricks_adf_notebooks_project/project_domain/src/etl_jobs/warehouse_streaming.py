"""Warehouse Streaming Pipeline — batch-INSERT staging landing zone.

Despite the class name and table name containing 'streaming', this is a BATCH job.
Runs hourly via ADF trigger. No Event Hub consumer, no Kafka, no continuous trigger.

GCP mapping: BigQuery Subscription (NOT Dataflow).
  - Source: Pub/Sub topic receiving warehouse order events
  - Target: BigQuery table (streaming_data_staging.order_events)
  - No stateful transforms needed → BQ Subscriptions sufficient

The streaming_detector.py parser will detect the INSERT INTO pattern in this file
and populate ir.streaming_landing_zones → ir.bq_subscriptions → terraform/bq_subscriptions.tf
"""

from pyspark.sql import SparkSession
from datetime import datetime


class WarehouseStreamingPipeline:
    STAGING_TABLE = "warehouselogistics_prod.streaming_data_staging.order_events"
    DOWNSTREAM_TABLE = "warehouseworkflow_prod.reports.order_summary"
    SOURCE_TABLE = "warehouselogistics_prod.events.raw_order_events"

    def __init__(self, spark: SparkSession):
        self.spark = spark

    def insert_staging_events(self, batch_timestamp: str = None):
        if batch_timestamp is None:
            batch_timestamp = datetime.utcnow().isoformat()
        self.spark.sql(f"""
            INSERT INTO {self.STAGING_TABLE}
            SELECT
                order_id,
                warehouse_id,
                event_type,
                event_payload,
                event_timestamp,
                '{batch_timestamp}' AS ingested_at
            FROM {self.SOURCE_TABLE}
            WHERE event_timestamp >= DATEADD(hour, -1, GETDATE())
              AND order_id IS NOT NULL
        """)

    def refresh_downstream_report(self):
        self.spark.sql(f"""
            INSERT INTO {self.DOWNSTREAM_TABLE}
            SELECT
                warehouse_id,
                event_type,
                COUNT(DISTINCT order_id) AS order_count,
                SUM(CAST(quantity AS BIGINT)) AS total_quantity,
                CAST(GETDATE() AS DATE) AS report_date
            FROM {self.STAGING_TABLE}
            WHERE ingested_at >= DATEADD(minute, -65, GETDATE())
            GROUP BY warehouse_id, event_type
        """)
