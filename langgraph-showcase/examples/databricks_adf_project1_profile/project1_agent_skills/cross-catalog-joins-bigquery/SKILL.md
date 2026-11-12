---
name: cross-catalog-joins-bigquery
description: Translates Databricks Unity Catalog cross-catalog joins (catalog.schema.table three-part names) to BigQuery cross-project fully qualified names (project.dataset.table). Covers IAM requirements, Dataform cross-project refs, and the BIS→branded_prod runtime join pattern.
disable-model-invocation: true
---

# Cross-Catalog Joins → BigQuery Cross-Project

## Detection

db2bq's cross-catalog detector fires when a SQL cell references tables from
more than one catalog prefix. It emits a `WARN` diagnostic:

```
Notebook SQL cells reference tables from 2 distinct catalogs
(businessintelligencesystems_prod, branded_prod).
On BigQuery these become cross-project joins — verify IAM and billing before enabling.
```

## Translation pattern

| Databricks (Unity Catalog) | BigQuery |
|---|---|
| `catalog.schema.table` | `` `project-id.dataset.table` `` |
| `businessintelligencesystems_prod.trusted.dim_item` | `` `bis-project.trusted.dim_item` `` |
| `branded_prod.noclick_stock_levels` | `` `branded-project.branded_dataset.noclick_stock_levels` `` |

## SQL rewrite example

**Source (Databricks):**
```sql
SELECT di.ItemNumber, ns.StockLevel
FROM businessintelligencesystems_prod.trusted.dim_item di
LEFT JOIN branded_prod.noclick_stock_levels ns
    ON di.ItemNumber = ns.ItemNumber
```

**Target (BigQuery):**
```sql
SELECT di.ItemNumber, ns.StockLevel
FROM `bis-gcp-project.trusted.dim_item` di
LEFT JOIN `branded-gcp-project.branded_dataset.noclick_stock_levels` ns
    ON di.ItemNumber = ns.ItemNumber
```

## Dataform cross-project ref

In Dataform SQLX, cross-project references use the `ref()` function with a
project override in `dataform.json`:

```json
{
  "defaultDatabase": "bis-gcp-project",
  "defaultSchema": "trusted",
  "vars": {
    "branded_project": "branded-gcp-project",
    "branded_dataset": "branded_dataset"
  }
}
```

In SQLX:
```sql
SELECT di.ItemNumber, ns.StockLevel
FROM ${ref("dim_item")} di
LEFT JOIN `${dataform.projectConfig.vars.branded_project}.${dataform.projectConfig.vars.branded_dataset}.noclick_stock_levels` ns
    ON di.ItemNumber = ns.ItemNumber
```

## IAM requirements

For each cross-project join, the Dataform / DataProc service account needs:

```bash
# Grant on the source BIS project
gcloud projects add-iam-policy-binding bis-gcp-project \
  --member="serviceAccount:dataform-sa@bis-gcp-project.iam.gserviceaccount.com" \
  --role="roles/bigquery.dataViewer"

# Grant on the branded spoke project
gcloud projects add-iam-policy-binding branded-gcp-project \
  --member="serviceAccount:dataform-sa@bis-gcp-project.iam.gserviceaccount.com" \
  --role="roles/bigquery.dataViewer"
```

## CTAS write-back IAM

For the 15 CTAS attribution write-backs (BIS → branded_prod), the SA also needs:

```bash
gcloud projects add-iam-policy-binding branded-gcp-project \
  --member="serviceAccount:dataform-sa@bis-gcp-project.iam.gserviceaccount.com" \
  --role="roles/bigquery.dataEditor"
```

## Billing note

Cross-project queries in BigQuery are billed to the **project running the query**,
not the project that owns the data. Confirm billing allocation with the client
before enabling cross-project joins at scale.

## Checklist

- [ ] Map each Databricks catalog to a GCP project ID
- [ ] Rewrite all three-part names to `` `project.dataset.table` `` FQNs in BigQuery SQL
- [ ] Grant `roles/bigquery.dataViewer` on each referenced project to the runtime SA
- [ ] For write-backs: grant `roles/bigquery.dataEditor`
- [ ] Update `dataform.json` with project vars for all spoke projects
- [ ] Verify billing allocation
