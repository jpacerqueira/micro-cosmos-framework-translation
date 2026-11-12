"""ETL platform catalog and mechanical project translation.

Databricks, BigQuery + Dataform, and Snowflake + dbt form one family.
Web and Java application estates form another. A source only maps to
targets in its own family, and never to itself.
"""

from micro_cosmos.etl.catalog import (
    APPLICATION_TARGETS,
    ETL_PLATFORMS,
    allowed_targets,
    classify_example,
    detect_etl_platform,
    is_etl_target,
    pairing_error,
)
from micro_cosmos.etl.translate import build_translation_files, write_translation

__all__ = [
    "APPLICATION_TARGETS",
    "ETL_PLATFORMS",
    "allowed_targets",
    "build_translation_files",
    "classify_example",
    "detect_etl_platform",
    "is_etl_target",
    "pairing_error",
    "write_translation",
]
