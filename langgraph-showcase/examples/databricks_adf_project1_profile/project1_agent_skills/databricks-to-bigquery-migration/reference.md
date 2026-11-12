## Reference: db2bq output shapes and manual porting guide

### Mount rewriting

db2bq replaces DBFS mount paths automatically when `--mount-mapping` is supplied:

| Source | Output |
|---|---|
| `/mnt/raw/customer_transactions` | `gs://retail-bronze-eu/raw/customer_transactions` |
| `/mnt/processing/trusted/dim_item` | `gs://retail-silver-eu/processing/trusted/dim_item` |
| `/mnt/serving/gold/item_season_performance` | `gs://retail-gold-eu/serving/gold/item_season_performance` |

Azure URIs that don't match a mount are annotated with a TODO:

```python
# TODO(db2bq): UCX hard-blocker: wasb:// is not UC-compatible — migrate to abfss:// first, then map to gs://
"wasb://branded-container@retailstorage.blob.core.windows.net/noclick_stock_levels"
```

### Dataform SQLX shape (gold table)

```sql
config {
  type: "table",
  tags: ["medallion:gold"],
  schema: "gold",
  description: "Auto-generated gold table for fact_sales_orders — daily_sales aggregation."
}

SELECT
  item_number,
  order_date,
  SUM(order_amount) AS total_revenue,
  COUNT(*) AS order_count,
  COUNT(DISTINCT customer_id) AS unique_customers
FROM ${ref('fact_sales_orders')}
GROUP BY item_number, order_date
```

### Dataform SQLX shape (view from create_gold_view)

```sql
config {
  type: "view",
  tags: ["medallion:gold", "view"]
}

-- Auto-generated Dataform view for the gold serving layer.
SELECT *
FROM ${ref('dim_item')}
```

### Cloud Workflows YAML (from ADF pipeline)

```yaml
main:
  steps:
    - IngestNmItemSupplier:
        call: http.post
        args:
          url: ${DATAPROC_JOBS_ENDPOINT}
          body:
            reference:
              projectId: my-gcp-project
            placement:
              clusterName: retail-cluster
            pysparkJob:
              mainPythonFileUri: gs://retail-filestore-eu/scripts/bronze_ingest_nm_item_supplier.py
    - RunBISAnalytics:
        call: http.post
        args:
          url: ${DATAPROC_JOBS_ENDPOINT}
          body:
            pysparkJob:
              mainPythonFileUri: gs://retail-filestore-eu/scripts/notebook_BISAnalytics.py
```

### Silver scaffold block (quality check placeholder)

Every generated silver script includes this comment block:

```python
# TODO(db2bq): quality + profiling — the source ETLPipeline.process_data()
# calls DataQualityChecker and DataProfiler here before writing silver.
# Port those classes to DataProc (see CLASSIC_ETL_TODO.md Phase 4).
# Example after porting:
#   from data_quality.quality_checker import DataQualityChecker
#   checker = DataQualityChecker()
#   quality_results = checker.run_quality_checks(df, "nm_item_supplier")
#   if not all(r.get('passed', False) for r in quality_results.values()):
#       raise ValueError(f"Quality checks failed for nm_item_supplier")
```

### SECRETS.md — secret rotation runbook (auto-generated)

db2bq produces `SECRETS.md` listing every Azure Key Vault reference with its GCP Secret Manager mapping. Example entry:

| Secret Manager id | Backend | Source vault | Source name | Referenced in |
|---|---|---|---|---|
| `akv__retailkv__event_grid_access_key` | AzureKeyVault | `retailkv` | `EVENT-GRID-ACCESS-KEY` | `azure_functions/local.settings.json` |

Operator steps:
1. `terraform apply` — provisions empty secrets
2. Mirror values: `az keyvault secret show ... | gcloud secrets versions add ...`
3. Update call sites to `secretmanager.SecretManagerServiceClient().access_secret_version(...)`
4. Grant `roles/secretmanager.secretAccessor` to the runtime SA

### CLASSIC_ETL_TODO.md — manual porting backlog

db2bq cannot auto-translate class-based ETL (no DLT lift point). It emits a layered TODO:

| Class | Layer | Methods | Writes Delta? |
|---|---|---|---|
| `ETLPipeline` | silver | `extract_raw_data`, `process_data`, `serve_data`, `create_gold_view` | yes |
| `BISPipeline` | silver | `extract_nm_item_raw`, `conform_nm_item_supplier`, `serve_dim_item`, ... | yes |

**Target shape per layer:**
- Bronze / Silver → `dataproc/<layer>_<name>.py`
- Gold SQL → `definitions/gold/<name>.sqlx`
