---
name: medallion-3tier-gold-sql-windows
description: Implements a Medallion 3-tier architecture in a PySpark/Delta Lake repo where source data is CSV extracts from SQL DW. Converts CSV to Parquet in Bronze, uses Delta in Silver and Gold with time travel options, and adds a Gold SQL queries folder focused on window functions and Delta time travel. Extended for BIS product star schema (nm_item → dim_item → fact_sales_orders).
disable-model-invocation: true
---

# Medallion 3-tier (Bronze Parquet / Silver+Gold Delta) + Gold SQL Windows

## Quick start

When asked to "review/implement Medallion 3 tier architecture" with **CSV extracts** and add **Gold SQL window queries**, do the following in order:

1. Locate the ETL entrypoint (typically `src/etl_jobs/etl_pipeline.py`) and current config (often `src/etl_jobs/config/etl_config.json`).
2. Update **Bronze** ingestion to read CSV and write **Parquet**.
3. Update **Silver** to read Bronze Parquet and write **Delta**.
4. Update **Gold** to read Silver Delta and write **Delta**.
5. Add Delta **time travel** support and a helper that creates a SQL view over Gold for queryability.
6. Create `sql/gold_windows/` containing Spark SQL examples using **window functions** and **time travel** (`VERSION AS OF`, `TIMESTAMP AS OF`).
7. Align docs/tests/config paths from `*.json` to `*.csv` as needed.
8. Validate (at minimum: `python3 -m compileall -q src tests` and a lints pass if available).

## Implementation checklist

### A) Bronze: CSV extracts → Parquet

- Read CSV with:
  - `header=true`
  - `inferSchema=true` (or explicit schema if repo requires it)
- Add metadata columns:
  - `_ingestion_timestamp` (current timestamp)
  - `_source_file` (use `input_file_name()`)
- Write Bronze as:
  - `format("parquet")`
  - `mode("append")`

### B) Silver: Parquet → Delta

- Read Bronze with `format("parquet")`
- Apply transformations (cast/timestamp patterns already used in many repos)
- Add `_processing_timestamp`
- Run `DataQualityChecker.run_quality_checks()` and `BISQualityRules.check_item_number_integrity()` before writing
- Write Silver as:
  - `format("delta")`
  - `mode("overwrite")`
  - `option("mergeSchema","true")`

### C) Gold: Delta → Delta (serving)

- Read Silver with `format("delta")`
- Apply aggregations if configured
- Add `_serving_timestamp`
- Write Gold as Delta (same overwrite/mergeSchema defaults)
- For BIS domain: join dim_item on item_number before aggregating

### D) Delta time travel + SQL queryability

- Add a helper `read_delta_as_of(path, version=None, timestamp=None)` that enforces mutual exclusivity.
  - For version: `.option("versionAsOf", <int>)`
  - For timestamp: `.option("timestampAsOf", "<yyyy-MM-dd HH:mm:ss>")`
- Add `create_gold_view(table_name, view_name=None, version=None, timestamp=None)`:
  - loads Gold using time travel helper
  - registers a temp view for Spark SQL

### E) Add Gold SQL (Windows/window functions) folder

Create:

```
sql/gold_windows/
  README.md
  01_time_travel_as_of.sql
  02_latest_record_per_key.sql
  03_running_totals.sql
  04_change_detection_time_travel.sql
```

Rules for the SQL files:
- Use Spark SQL syntax.
- Prefer templates with placeholders (`<GOLD_PATH>`, `<GOLD_TABLE_OR_VIEW>`, `<KEY_COL>`, `<TS_COL>`).
- Include at least one query demonstrating:
  - `VERSION AS OF`
  - `TIMESTAMP AS OF`
- Include at least two window-function patterns:
  - `ROW_NUMBER() OVER (PARTITION BY ... ORDER BY ... DESC)`
  - running totals `SUM(...) OVER (...)`

## Notes / constraints

- Keep Bronze **Parquet** only (not Delta).
- Keep Silver/Gold **Delta** (to support time travel and ACID).
- Avoid introducing interactive steps; changes should be code/config driven.
- The BIS schema rename (`productsystems` → `product_systems`) is in-flight: always try `product_systems` first and fall back to `productsystems` with a warning log.

## Additional resources

- For file templates and suggested edits for common repos, see [reference.md](reference.md)
- For GCP translation patterns, see `../databricks-to-bigquery-migration/SKILL.md`
