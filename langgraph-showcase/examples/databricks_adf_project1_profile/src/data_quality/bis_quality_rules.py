"""BIS-specific data quality rules.

Extends the generic DataQualityChecker with domain rules derived from the
PSO lineage report:
  - ItemNumber join integrity (BIS.trusted.dim_item ↔ branded_prod.*)
  - Schema rename monitoring (productsystems → product_systems both live)
  - Payment JSON column completeness (get_json_object() extractions)
  - Warehouse streaming completeness (parcel event arrival rate)
"""

from __future__ import annotations

from typing import Any
import logging

from pyspark.sql import DataFrame
from pyspark.sql.functions import col, count, when, isnan, isnull, get_json_object


class BISQualityRules:
    """Domain-specific quality rules for the BIS product star schema."""

    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)

    def check_item_number_integrity(
        self, df: DataFrame, table_name: str
    ) -> dict[str, dict[str, Any]]:
        """Check ItemNumber is non-null, non-empty, and matches expected format.

        The lineage report identifies ItemNumber as the cross-catalog join key
        between BIS.trusted.dim_item and branded_prod.noclick_stock_levels.
        Null or malformed ItemNumbers cause silent join misses.
        """
        results: dict[str, dict[str, Any]] = {}

        total = df.count()
        if total == 0:
            results["item_number_not_empty_table"] = {
                "passed": False,
                "message": f"{table_name}: table has no rows",
                "count": 0,
            }
            return results

        null_count = df.filter(isnull(col("ItemNumber")) | (col("ItemNumber") == "")).count()
        results["item_number_not_null"] = {
            "passed": null_count == 0,
            "message": f"{null_count}/{total} rows have null or empty ItemNumber",
            "null_count": null_count,
            "total": total,
        }

        # ItemNumber format: alphanumeric, 4-12 chars — specific to BIS schema contract
        invalid_format = df.filter(
            ~col("ItemNumber").rlike("^[A-Za-z0-9]{4,12}$")
        ).count()
        results["item_number_format"] = {
            "passed": invalid_format == 0,
            "message": f"{invalid_format}/{total} rows have non-standard ItemNumber format",
            "invalid_count": invalid_format,
        }

        self.logger.info(f"ItemNumber integrity check for {table_name}: {results}")
        return results

    def check_schema_rename_consistency(
        self, df_product_systems: DataFrame, df_productsystems: DataFrame
    ) -> dict[str, dict[str, Any]]:
        """Verify both schema names return same row count during rename migration.

        During the UCX migration, product_systems and productsystems are both
        live simultaneously. Row count mismatch indicates replication lag.
        """
        count_new = df_product_systems.count()
        count_old = df_productsystems.count()
        match = count_new == count_old

        result = {
            "schema_rename_row_count_match": {
                "passed": match,
                "message": (
                    f"product_systems={count_new} rows, productsystems={count_old} rows — "
                    + ("MATCH" if match else "MISMATCH — replication lag suspected")
                ),
                "product_systems_count": count_new,
                "productsystems_count": count_old,
            }
        }
        self.logger.info(f"Schema rename consistency: {result}")
        return result

    def check_payment_json_completeness(
        self, df: DataFrame, provider: str, required_fields: list[str]
    ) -> dict[str, dict[str, Any]]:
        """Check that JSON Payload column contains all required fields for a provider.

        The lineage report identifies a JSON anti-pattern across all 5 payment
        providers: raw webhook events stored as a JSON string in `Payload`.
        This check validates that extraction via get_json_object() succeeds for
        all required fields and that the null rate stays below 5%.
        """
        results: dict[str, dict[str, Any]] = {}
        total = df.count()

        if total == 0:
            results[f"{provider}_payload_not_empty"] = {
                "passed": False,
                "message": f"{provider}: no payment events found",
            }
            return results

        for field in required_fields:
            null_count = df.filter(
                isnull(get_json_object(col("Payload"), f"$.{field}"))
            ).count()
            null_pct = null_count / total * 100
            results[f"{provider}_{field}_completeness"] = {
                "passed": null_pct < 5.0,
                "message": f"{null_count}/{total} ({null_pct:.1f}%) events missing $.{field}",
                "null_count": null_count,
                "null_pct": null_pct,
            }

        return results

    def check_warehouse_streaming_arrival_rate(
        self, df: DataFrame, expected_events_per_hour: int = 100
    ) -> dict[str, dict[str, Any]]:
        """Check that parcel event arrival rate meets the expected threshold.

        Warehouse Logistics uses BPP streaming events. Late-arrival detection:
        if hourly event count drops below expected_events_per_hour, flag it.
        This is a placeholder — full implementation requires windowed aggregation
        over a streaming sink or hourly materialized view.
        """
        from pyspark.sql.functions import window, hour

        total = df.count()
        result = {
            "warehouse_streaming_arrival": {
                "passed": total >= expected_events_per_hour,
                "message": (
                    f"Event count={total}, threshold={expected_events_per_hour} — "
                    + ("OK" if total >= expected_events_per_hour else "LOW — possible streaming lag")
                ),
                "event_count": total,
                "threshold": expected_events_per_hour,
            }
        }
        self.logger.info(f"Warehouse streaming arrival rate: {result}")
        return result

    def check_cross_catalog_join_key_coverage(
        self,
        bis_df: DataFrame,
        branded_df: DataFrame,
        join_key: str = "ItemNumber",
    ) -> dict[str, dict[str, Any]]:
        """Check how many BIS items have a match in the branded spoke.

        A low match rate indicates the branded spoke is missing items that
        BIS has — which will produce silent join misses in analytics.
        """
        bis_keys = set(row[0] for row in bis_df.select(join_key).distinct().collect())
        branded_keys = set(row[0] for row in branded_df.select(join_key).distinct().collect())

        matched = len(bis_keys & branded_keys)
        unmatched_bis = len(bis_keys - branded_keys)
        match_pct = matched / len(bis_keys) * 100 if bis_keys else 0.0

        result = {
            "cross_catalog_join_coverage": {
                "passed": match_pct >= 95.0,
                "message": (
                    f"{matched}/{len(bis_keys)} BIS items matched in branded spoke "
                    f"({match_pct:.1f}%) — {unmatched_bis} BIS items have no branded counterpart"
                ),
                "matched": matched,
                "unmatched_in_bis": unmatched_bis,
                "match_pct": match_pct,
            }
        }
        self.logger.info(f"Cross-catalog join key coverage: {result}")
        return result
