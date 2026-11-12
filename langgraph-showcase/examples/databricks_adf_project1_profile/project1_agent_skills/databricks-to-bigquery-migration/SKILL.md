---
name: databricks-to-bigquery-migration
description: Run the db2bq CLI to translate a Databricks / ADF project (classic mode, no databricks.yml) into a GCP-native output — DataProc PySpark files, Dataform SQLX, Eventarc Cloud Run handlers, Terraform for Secret Manager and Eventarc, and Cloud Workflows YAML. Covers the full db2bq pipeline for project1_databricks_adf.
disable-model-invocation: true
---

# Databricks → BigQuery / GCP Migration with db2bq

## When to use this skill

Use this skill when asked to:
- "Translate the project to GCP"
- "Run db2bq on this project"
- "Generate the BigQuery output"
- "Rebuild translated_2bq_project1_databricks_adf"

## Prerequisites

```bash
cd databricks-to-bigquery/db2bq
pip install -e ".[dev]"
```

## Standard invocation for this project

```bash
cd /path/to/next-investigation
python -m db2bq.cli \
  --source-path project1_databricks_adf \
  --target-path translated_2bq_project1_databricks_adf \
  --gcp-project my-gcp-project \
  --bq-location EU \
  --bronze-mirror-bucket retail-bronze-mirror-eu \
  --dbfs-filestore-bucket retail-filestore-eu \
  --mount-mapping "/mnt/raw=gs://retail-bronze-eu/raw" \
  --mount-mapping "/mnt/processing=gs://retail-silver-eu/processing" \
  --mount-mapping "/mnt/serving=gs://retail-gold-eu/serving" \
  --mount-mapping "/mnt/raw/trusted=gs://retail-bronze-eu/trusted" \
  --mount-mapping "/mnt/raw/product_systems_raw=gs://retail-bronze-eu/product_systems_raw"
```

Or via the Python API (used in tests):

```python
from db2bq.config import MigrationConfig
from db2bq.pipeline import migrate

cfg = MigrationConfig(
    source_path=Path("project1_databricks_adf"),
    target_path=Path("translated_2bq_project1_databricks_adf"),
    gcp_project="my-gcp-project",
    bq_location="EU",
    bronze_mirror_bucket="retail-bronze-mirror-eu",
    mount_mappings=[
        "/mnt/raw=gs://retail-bronze-eu/raw",
        "/mnt/processing=gs://retail-silver-eu/processing",
        "/mnt/serving=gs://retail-gold-eu/serving",
    ],
    dbfs_filestore_bucket="retail-filestore-eu",
    work_dir=Path("/tmp/db2bq_wd"),
)
target_dir, pr_url, ir = migrate(cfg)
```

## What db2bq produces (classic mode)

| Source artefact | Output artefact | Location |
|---|---|---|
| Databricks `.py` notebook | DataProc PySpark script | `dataproc/notebook_<name>.py` |
| `etl_config.json` bronze step | DataProc bronze ingest script | `dataproc/bronze_ingest_<table>.py` |
| `etl_config.json` silver step | DataProc silver conform script | `dataproc/silver_conform_<table>.py` |
| `etl_config.json` gold step | Dataform SQLX | `definitions/gold/<table>__<agg>.sqlx` |
| Class with `create_gold_view()` | Dataform view SQLX | `definitions/gold/v_<table>.sqlx` |
| ADF pipeline JSON | Cloud Workflows YAML | `workflows/<pipeline_name>.yaml` |
| ADF trigger JSON | Cloud Workflows schedule | `workflows/<trigger_name>.yaml` |
| Azure Function | Eventarc Cloud Run handler | `eventarc/<trigger>/main.py` + `Dockerfile` |
| Azure Key Vault refs | Secret Manager Terraform | `terraform/secret_manager.tf` |
| All triggers | Eventarc Terraform | `terraform/eventarc.tf` |
| Quality/profiling comments | Silver scaffold block | Inside silver `.py` files |

## Key flags explained

| Flag | Purpose |
|---|---|
| `--mount-mapping` | Maps `/mnt/xxx` DBFS paths to `gs://` GCS URIs. Repeat for each mount. |
| `--bronze-mirror-bucket` | Bucket where raw data is mirrored to; referenced in bronze ingest scripts. |
| `--dbfs-filestore-bucket` | Bucket for DBFS filestore items (JARs, scripts). |
| `--bq-location` | BigQuery dataset location (`EU`, `US`, `europe-west2`, etc.). |

## Classic mode detection

db2bq detects **classic mode** (vs DAB/DLT mode) by the absence of `databricks.yml`:
- Scans `**/*.py` for `class.*ETL` with PySpark write calls
- Scans `notebooks/**/*.py` for Databricks notebook marker (`# Databricks notebook source`)
- Reads `azure_functions/**/*.json` for event trigger functions
- Reads `adf/pipeline_*.json` and `adf/trigger_*.json` for ADF pipelines
- Reads `src/**/config/etl_config.json` for medallion layer jobs

## Output validation

After running db2bq, validate with:

```bash
# All Python files must parse
find translated_2bq_project1_databricks_adf -name "*.py" | xargs python3 -m py_compile

# Expected file counts (approximate)
find translated_2bq_project1_databricks_adf -name "*.py" | wc -l   # ≥12
find translated_2bq_project1_databricks_adf -name "*.sqlx" | wc -l # ≥8
find translated_2bq_project1_databricks_adf -name "*.tf" | wc -l   # ≥2
find translated_2bq_project1_databricks_adf -name "*.yaml" | wc -l # ≥3
```

## Known gaps (manual work after translation)

See [reference.md](reference.md) for the per-gap porting guide.

- `wasb://` and `adl://` URIs → add `--mount-mapping` or manually rewrite to `gs://`
- T-SQL DATEADD/GETDATE → translated automatically but verify complex expressions
- Cross-catalog joins → flagged with WARN; manually convert to BigQuery cross-project FQNs
- `get_json_object()` → replace with `JSON_VALUE()` / `JSON_EXTRACT()` in BigQuery SQL
- Delta time travel → no native equivalent; use the daily `CREATE SNAPSHOT TABLE` workflow db2bq emits
- CTAS write-backs (15 targets) → Dataform `SQLX` with `INSERT OVERWRITE` + IAM grant
