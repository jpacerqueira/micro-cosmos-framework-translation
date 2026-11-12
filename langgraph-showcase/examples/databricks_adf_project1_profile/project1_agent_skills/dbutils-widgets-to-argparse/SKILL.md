---
name: dbutils-widgets-to-argparse
description: Translates Databricks dbutils.widgets calls (text, dropdown, combobox, multiselect, get, removeAll) to Python argparse in DataProc PySpark scripts. db2bq handles this automatically in notebook translation; this skill documents the exact transformation and edge cases.
disable-model-invocation: true
---

# dbutils.widgets → argparse

## What db2bq does automatically

When translating a Databricks notebook to a DataProc PySpark script,
db2bq's `_clean_python_cell()` function processes every Python cell:

| Source | Output |
|---|---|
| `dbutils.widgets.text("key", "default", "Label")` | `# (argparse) dbutils.widgets.text("key", "default", "Label")` |
| `dbutils.widgets.dropdown("mode", "full", ["full","extract"], "Label")` | `# (argparse) dbutils.widgets.dropdown(...)` |
| `dbutils.widgets.combobox(...)` | `# (argparse) dbutils.widgets.combobox(...)` |
| `dbutils.widgets.multiselect(...)` | `# (argparse) dbutils.widgets.multiselect(...)` |
| `dbutils.widgets.get("key")` | `key` (the Python identifier for the widget key) |
| `dbutils.widgets.removeAll()` | `# (db2bq) dbutils.widgets.removeAll() not needed on DataProc` |

The argparse block is generated at the **top of the script** from all widget declarations found.

## Generated argparse block

For this notebook (`RunETLPipeline.py`):
```python
dbutils.widgets.text("config_path", "/Workspace/...", "Config Path")
dbutils.widgets.text("table_name", "", "Table Name")
dbutils.widgets.dropdown("run_mode", "full", ["full", "extract", "process", "serve"], "Run Mode")
```

db2bq generates:
```python
import argparse

parser = argparse.ArgumentParser(description="RunETLPipeline")
parser.add_argument("--config-path", default="/Workspace/.../etl_config.json", help="Config Path")
parser.add_argument("--table-name", default="", help="Table Name")
parser.add_argument("--run-mode", default="full", choices=["full", "extract", "process", "serve"], help="Run Mode")
args = parser.parse_args()

config_path = args.config_path
table_name = args.table_name
run_mode = args.run_mode
```

## Key name to argparse flag conversion

Widget key `"table_name"` → flag `"--table-name"` → `args.table_name`:
- underscores → hyphens in the flag
- hyphens → underscores in `args.*`

## SQL cell parameter substitution

SQL cells use `${varname}` for Databricks parameter injection.
db2bq's `_render_sql_cell()` converts these to Python f-strings:

**Source SQL cell:**
```sql
SELECT * FROM ${table_name}_serving LIMIT 10
```

**Output:**
```python
spark.sql(f"""
SELECT * FROM {table_name}_serving LIMIT 10
""")
```

For complex expressions like `${etl.serving_path}`, db2bq emits a TODO:
```python
# TODO(db2bq): ${etl.serving_path} is a complex expression — replace manually
spark.sql("""
SELECT * FROM delta.`/mnt/serving/${table_name}`
""")
```

## Running the translated script on DataProc

```bash
gcloud dataproc jobs submit pyspark gs://retail-filestore-eu/scripts/notebook_RunETLPipeline.py \
  --cluster=retail-cluster \
  --region=europe-west2 \
  --project=my-gcp-project \
  -- \
  --table-name customer_transactions \
  --run-mode full \
  --config-path gs://retail-filestore-eu/config/etl_config.json
```

## Edge cases

| Pattern | Handling |
|---|---|
| `dbutils.widgets.get("key")` inside f-string | Replaced by identifier inline |
| Multi-line widget declaration | Commented out as single block |
| `%run ./other_notebook` magic | Emits a `# TODO(db2bq): %run` comment |
| `display(df)` | Replaced by `print(df.show())` |
| `dbutils.fs.ls(...)` | Commented with GCS equivalent TODO |
| `dbutils.notebook.run(...)` | Replaced by subprocess call to gcloud dataproc |

## Checklist

- [ ] Verify every argparse flag matches the widget key used in downstream cells
- [ ] Review `# TODO(db2bq): ${...}` comments for complex SQL parameters
- [ ] Update Cloud Workflows step `args` to pass the correct `--flag value` pairs
- [ ] Remove any surviving `dbutils.*` calls from the translated scripts
