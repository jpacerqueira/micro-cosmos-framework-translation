# Refactor plan — `pyspark_dataprofiling_quality` to GCP

This is a **concrete, file-level** plan to migrate the project to GCP using
db2bq's classic-mode pipeline (no rewrite of the source repo into a DAB —
db2bq-classic-mode handles the shape we already have).

Target topology:

- **Bronze + silver** → DataProc Serverless PySpark batches.
- **Gold** → BigQuery via Dataform SQLX.
- **Orchestration** → Cloud Scheduler → Cloud Workflows.
- **Event-driven ingestion** → Eventarc → Cloud Run (replacing the .NET Azure Function blob trigger).
- **Secrets** → Google Secret Manager (replacing Azure Key Vault).
- **Bronze data system-of-record** → stays in ADLS for the cutover window; mirrored to GCS over the Equinix Cloud Interconnect by Storage Transfer Service (sts_event mode).

Estimated effort: **~12 working days** end-to-end, of which db2bq scaffolds ~5 days of code for free. The remaining 7 days are the items below marked **manual**.

---

## Phase 0 — Provision targets (½ day)

| # | Task | Owner |
|---|---|---|
| 0.1 | Create GCP project, enable APIs (BigQuery, Dataform, DataProc, Workflows, Scheduler, Eventarc, Cloud Run, Secret Manager, Dataplex, Storage Transfer Service). | Platform |
| 0.2 | Create GCS buckets: `retail-bronze-eu`, `retail-silver-eu`, `retail-gold-eu`, `retail-filestore-eu`, `retail-dataproc-code-eu`. | Platform |
| 0.3 | Provision the Equinix Cloud Interconnect circuit (network team owns this; db2bq emits a TF stub only). | Network |
| 0.4 | Create the runtime SAs: `db2bq-orchestrator@`, `db2bq-dataproc@`, `db2bq-eventarc@`, `db2bq-secret-rotator@`. Grant the minimum roles listed in `db2bq-user-guide.docx`. | Platform |
| 0.5 | Mirror Azure Key Vault secret names into Secret Manager **empty resources** (`terraform apply` from `terraform/secret_manager.tf` once db2bq has emitted it — see Phase 2). | Platform |

---

## Phase 1 — Run db2bq classic mode (1 day)

```bash
cd databricks-to-bigquery/db2bq

db2bq \
  --source-path ../../pyspark_dataprofiling_quality \
  --target-path  ../../pyspark_dataprofiling_quality_gcp \
  --gcp-project  retail-data-prod \
  --bq-location  EU \
  --bronze-mirror-bucket retail-bronze-mirror-eu \
  --adls-account omvmcnp1stradinge2edev \
  --interconnect-region-pair "northeurope/europe-west2" \
  --equinix-circuit-id "eqx-prod-01" \
  --dataproc-region europe-west2 \
  --dataproc-service-account db2bq-dataproc@retail-data-prod.iam.gserviceaccount.com \
  --cloud-workflows-region europe-west2 \
  --scheduler-region europe-west2 \
  --orchestrator-service-account db2bq-orchestrator@retail-data-prod.iam.gserviceaccount.com \
  --mount-mapping "/mnt/raw=gs://retail-bronze-eu/raw" \
  --mount-mapping "/mnt/processing=gs://retail-silver-eu/processing" \
  --mount-mapping "/mnt/serving=gs://retail-gold-eu/serving" \
  --dbfs-filestore-bucket retail-filestore-eu
```

What you get:

| Source artefact | Generated target artefact | Action |
|---|---|---|
| `etl_config.json` | `dataproc/bronze_ingest_customer_transactions.py`, `silver_conform_*.py`, `definitions/gold/customer_transactions__daily_transactions.sqlx` (and the same for `product_inventory`) | Review, then **(see Phase 3)** wire the silver casts and gold metrics against the real columns. |
| `notebooks/01_data_quality/DataQualityChecks.py` | `dataproc/notebook_DataQualityChecks.py` | Review TODOs; lift the `DataQualityChecker` calls into argparse-driven main. |
| `notebooks/02_data_profiling/DataProfiling.py` | `dataproc/notebook_DataProfiling.py` | Replace `display()`/seaborn with a "write profile JSON to GCS" block; Looker Studio reads the JSON. |
| `notebooks/03_etl_jobs/RunETLPipeline.py` | `dataproc/notebook_RunETLPipeline.py` | This becomes a **driver script**; rewire it to call the bronze/silver/gold workflow directly via Cloud Workflows. |
| `src/etl_pipeline.py` (`ETLPipeline` class) | Entry in `CLASSIC_ETL_TODO.md` (heuristic layer = "silver") | **(Phase 3)** Port `extract_raw_data` → bronze pyspark, `process_data` → silver pyspark, `serve_data` → gold SQLX. |
| `src/data_quality/quality_checker.py` | (no auto-translation) | **(Phase 4)** Port to a DataProc PySpark job that writes a `quality_check_results` table. Or migrate to Dataplex Data Quality rules. |
| `src/data_profiling/profiler.py` | (no auto-translation) | **(Phase 4)** Port to DataProc job; write profile JSON to `gs://retail-filestore-eu/profiles/`. Or migrate to Dataplex auto-profiling. |
| `src/etl_jobs/get_secrets.py` (Azure KV `get_secret("EVENT-GRID-ACCESS-KEY")`) | `SECRETS.md` row + `terraform/secret_manager.tf` resource `akv__omvmcnp1kvtradinge2edev__event_grid_access_key` | Mirror the value during cutover; then update the call site (Phase 2). |
| `azure_functions/BlobToEventGridFunction/function.json` (.NET blob trigger) | `eventarc/BlobToEventGridFunction/{main.py,Dockerfile}` + `terraform/eventarc.tf` | **(Phase 5)** Build the container; replace the placeholder Cloud Run image. |
| `sql/gold_windows/01–04.sql` (Spark window + Delta time travel) | (not auto-translated by classic mode — Spark SQL with Delta semantics) | **(Phase 6)** Port four queries to Dataform SQLX, replacing `VERSION AS OF` with the snapshot pattern db2bq emits. |
| (no `databricks.yml` / `medallion.yml`) | `workflows/medallion_daily.yaml`, `workflows/snapshots_daily.yaml`, `terraform/scheduler.tf` | Review the daily cron and snapshot retention. |

---

## Phase 2 — Secrets and IAM (½ day)

1. `cd pyspark_dataprofiling_quality_gcp/terraform && terraform apply -target=google_secret_manager_secret.akv__omvmcnp1kvtradinge2edev__event_grid_access_key`.
2. Mirror the value:
   ```bash
   az keyvault secret show --vault-name omvmcnp1kvtradinge2edev \
     --name EVENT-GRID-ACCESS-KEY --query value -o tsv \
     | gcloud secrets versions add akv__omvmcnp1kvtradinge2edev__event_grid_access_key \
         --project=retail-data-prod --data-file=-
   ```
3. Replace the call site in `src/etl_jobs/get_secrets.py` with:
   ```python
   from google.cloud import secretmanager
   def get_event_grid_key(project: str = "retail-data-prod") -> str:
       client = secretmanager.SecretManagerServiceClient()
       name = f"projects/{project}/secrets/akv__omvmcnp1kvtradinge2edev__event_grid_access_key/versions/latest"
       return client.access_secret_version(request={"name": name}).payload.data.decode()
   ```
4. Delete `azure_auth_config.py` (Azure-specific) once nothing imports it.

---

## Phase 3 — Port the class-based ETL (3 days, **manual**)

`src/etl_pipeline.py:ETLPipeline` doesn't auto-translate. The structure of the
ported code lines up cleanly with what db2bq scaffolds from `etl_config.json`,
so use those scaffolds as the target:

| Source method | Target file (already scaffolded) | What to lift in |
|---|---|---|
| `extract_raw_data(table)` | `dataproc/bronze_ingest_<table>.py` | Add `_ingestion_timestamp` / `_source_file` columns; honour CSV/parquet auto-detection from `etl_config.json`. |
| `process_data(table)` | `dataproc/silver_conform_<table>.py` | Apply `transformations` (cast/format) — already templated by db2bq; add the `_processing_timestamp` column. |
| `serve_data(table)` | `definitions/gold/<table>__<agg>.sqlx` | Translate the aggregations block into the Dataform SQLX; the file already has the GROUP BY skeleton. |
| `_read_delta_as_of(...)` | (rewrite) | Use `gs://retail-gold-eu/snapshots/<table>__YYYYMMDD/` instead of Delta versions. The snapshot workflow at `workflows/snapshots_daily.yaml` writes these. |
| `create_gold_view(...)` | `definitions/gold/v_<table>.sqlx` | Standard Dataform view. |

Validation: run `pytest tests/` against the ported PySpark using DataProc Serverless local mode (`--local`) — fix until the assertions in `tests/test_etl_pipeline.py` pass against fixture CSVs in GCS.

---

## Phase 4 — Port quality + profiling (2 days, **manual**)

Two paths. **Pick one before starting:**

### Path A — Keep custom quality / profiling

- Port `DataQualityChecker` and `DataProfiler` verbatim into `dataproc/quality_checks.py` and `dataproc/profiler.py`.
- Add two steps to `workflows/medallion_daily.yaml` (between silver and gold):
  - `dataproc.batches.create` for `quality_checks.py` writing `retail-data-prod.silver.quality_check_results`.
  - `dataproc.batches.create` for `profiler.py` writing JSON profiles to `gs://retail-filestore-eu/profiles/<table>/<run_ts>.json`.
- Surface results to Looker Studio (read the BQ table) and Vertex AI Workbench (read the JSON).

### Path B — Switch to Dataplex

- Define each rule from `quality_checker.py` in **Dataplex Data Quality** (UI or `gcloud dataplex tasks create`).
- Enable Dataplex auto-profiling on the silver dataset.
- Delete `src/data_quality/` and `src/data_profiling/`.

Path B is the "GCP-native" choice; Path A keeps a closer 1:1 with the source. Default to **Path A** for the first cutover; migrate to Path B in a follow-up.

---

## Phase 5 — Replace the Azure Function blob trigger (1 day, **manual**)

db2bq emits `eventarc/BlobToEventGridFunction/{main.py,Dockerfile}` already.

1. The blob trigger logic in the .NET function was "publish a CloudEvent to the orchestration topic". The generated handler does the same thing by calling Cloud Workflows directly. **Replace** the placeholder image:
   ```bash
   cd pyspark_dataprofiling_quality_gcp/eventarc/BlobToEventGridFunction
   gcloud builds submit --tag europe-west2-docker.pkg.dev/retail-data-prod/eventarc/blob-to-workflow:v1
   ```
2. Update `terraform/eventarc.tf` to use the built image (replace `gcr.io/cloudrun/placeholder`).
3. `terraform apply` — verify the trigger fires by uploading a file to `gs://retail-bronze-eu/raw/customer_transactions/test.csv`.

---

## Phase 6 — Port `sql/gold_windows/*.sql` (½ day, **manual**)

| Source file | Target | Notes |
|---|---|---|
| `01_time_travel_as_of.sql` | `definitions/gold/v_<table>_as_of.sqlx` | Replace `VERSION AS OF / TIMESTAMP AS OF` with `${ref(table + '__' + snapshot_date)}` — the daily snapshots workflow writes one snapshot per day. |
| `02_latest_record_per_key.sql` | `definitions/gold/<table>_latest.sqlx` | Direct port — sqlglot syntax is identical for `ROW_NUMBER() OVER (...)`. |
| `03_running_totals.sql` | `definitions/gold/<table>_running_totals.sqlx` | Direct port — `SUM() OVER (... ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)` works as-is. |
| `04_change_detection_time_travel.sql` | `definitions/gold/<table>_changes.sqlx` | The trickiest one — rewrite the two-version JOIN as a JOIN between `<table>__YYYYMMDD` and `<table>__YYYY(MM-1)DD`. Add a parameter to the workflow for the comparison date. |

---

## Phase 7 — Cutover and decommission (1 day)

1. Run a full pipeline end-to-end against a single test table; compare row counts and aggregates against the Databricks output.
2. Schedule a parallel-run window (1 week minimum) where both Databricks and GCP run on the same source data; reconcile daily.
3. Once green: cut over the Azure Function trigger to point at the GCP Eventarc handler (or leave the Azure side alone and have the function call the Cloud Workflow webhook — see `MIGRATION_REPORT.md` for the trade-off).
4. Decommission Databricks workspace + Delta Lake storage (after retention window expires).
5. Decommission the Azure Function once GCP Eventarc has run for two weeks without incident.
6. Decommission the Azure Key Vault (or keep it as the master and continue mirroring) — depends on org rotation policy.

---

## Out of scope for this plan

- **MLflow** — the source has none today; if added later, plan a separate Vertex AI migration.
- **Streaming** — the source is batch-only. If true streaming is added, replace the daily Cloud Workflow with a Dataflow pipeline.
- **Multi-region failover** — single-region deployment to start; multi-region is a follow-on.
- **Unity Catalog masks** — the source has no masks. If added later, db2bq's existing Dataplex policy-tag pipeline picks them up automatically.
