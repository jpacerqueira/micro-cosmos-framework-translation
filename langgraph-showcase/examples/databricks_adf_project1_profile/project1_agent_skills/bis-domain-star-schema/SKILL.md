---
name: bis-domain-star-schema
description: Implements and migrates the BIS (businessintelligencesystems_prod) product star schema — nm_item → dim_item → fact_sales_orders — across the 4-layer medallion (product_systems_raw → product_systems → trusted → refined). Covers the hub-and-spoke topology with branded_prod, schema rename guard, and CTAS write-back to 15 attribution targets.
disable-model-invocation: true
---

# BIS Domain — Product Star Schema

## Architecture overview

```
product_systems_raw     product_systems          trusted                  refined
  nm_item              → nm_item_supplier      → dim_item              → fact_sales_orders_season
  nm_item_detail         nm_item_option          dim_item_team            dim_item_attribute
  nm_item_text           productsystems          fact_sales_orders      bismerged
  nm_booking_report        item                  fact_return_rate_item    svoc_customers
  nm_supplier              item_season
                           item_text
```

**Hub–spoke pattern:**
- BIS is the hub (`businessintelligencesystems_prod`)
- Branded is the spoke (`branded_prod`) — receives runtime cross-catalog joins AND 15 CTAS write-backs
- Join key: `ItemNumber` (must be non-null, format `[A-Za-z0-9]{4,12}`)

## Schema rename — CRITICAL

The schema is being renamed **`productsystems` → `product_systems`** during UCX migration.
Both names may be live simultaneously. Always guard reads:

```python
try:
    df = spark.read.format("delta").load(f"{trusted_base}/product_systems/fact_sales_orders")
except Exception:
    logger.warning("product_systems not found — trying productsystems (rename in flight)")
    df = spark.read.format("delta").load(f"{trusted_base}/productsystems/fact_sales_orders")
```

## BISQualityRules checklist

Run `BISQualityRules` (in `src/data_quality/bis_quality_rules.py`) before every silver write:

| Method | What it checks |
|---|---|
| `check_item_number_integrity(df, table)` | ItemNumber non-null, non-empty, format `[A-Za-z0-9]{4,12}` |
| `check_schema_rename_consistency(df_new, df_old)` | Row count match between both schema names |
| `check_payment_json_completeness(df, provider, fields)` | JSON Payload field extraction null-rate < 5% |
| `check_cross_catalog_join_key_coverage(bis_df, branded_df)` | ItemNumber match rate ≥ 95% between catalogs |

## BISPipeline method order

For a full run:

```python
pipeline = BISPipeline()
pipeline.extract_nm_item_raw()          # wasb:// → bronze
pipeline.extract_nm_item_supplier()     # wasb:// → bronze
pipeline.extract_item_season()          # abfss:// ADLS Gen2 → silver
pipeline.conform_nm_item_supplier()     # quality check → silver Delta
pipeline.conform_fact_sales_orders()    # schema-rename guard → silver Delta
pipeline.serve_dim_item()               # nm_item JOIN supplier → gold dim
pipeline.serve_fact_sales_orders()      # fact JOIN dim → gold aggregate
pipeline.materialise_attribution_targets("AW24")  # 15 CTAS targets → branded_prod
```

## CTAS write-back targets (15)

All 15 `attribution_*` tables are materialised into `branded_prod`:

```
attribution_item_season           attribution_supplier_lead_time
attribution_item_team             attribution_noclick_opportunity
attribution_item_brand            attribution_svoc_segment
attribution_sales_weekly          attribution_price_elasticity
attribution_sales_monthly         attribution_channel_mix
attribution_return_rate           attribution_markdown_impact
attribution_stock_cover           attribution_new_season_launch
attribution_forecast_accuracy
```

On GCP: each becomes a Dataform SQLX table in the target BigQuery project with
cross-project IAM (`roles/bigquery.dataEditor` on branded GCP project).

## Cross-catalog join pattern

Runtime join between BIS and branded spoke:

```sql
SELECT di.ItemNumber, di.ProductCategory, ns.StockLevel
FROM businessintelligencesystems_prod.trusted.dim_item di
LEFT JOIN branded_prod.noclick_stock_levels ns
    ON di.ItemNumber = ns.ItemNumber
```

On BigQuery this becomes a cross-project join:

```sql
SELECT di.ItemNumber, di.ProductCategory, ns.StockLevel
FROM `bis-gcp-project.trusted.dim_item` di
LEFT JOIN `branded-gcp-project.branded_dataset.noclick_stock_levels` ns
    ON di.ItemNumber = ns.ItemNumber
```

Requires: `roles/bigquery.dataViewer` on `branded-gcp-project` for the Dataform SA.

## UCX blockers in this domain

| Issue | Source | Fix |
|---|---|---|
| `wasb://` URI | `BISPipeline.extract_nm_item_raw()` | Add `--mount-mapping` to db2bq; annotated with TODO |
| `abfss://` URI | `BISPipeline.extract_item_season()` | Add External Location mapping |
| Schema rename in-flight | `conform_fact_sales_orders()` | Schema rename guard (try/except) |
| Delta time travel | `_read_delta_as_of()` | Use db2bq daily snapshot workflow |

## Additional resources

- See `../databricks-to-bigquery-migration/SKILL.md` for the db2bq CLI invocation
- See `../cross-catalog-joins-bigquery/SKILL.md` for BigQuery cross-project patterns
- See `../delta-time-travel-to-bq-snapshots/SKILL.md` for snapshot workflow
