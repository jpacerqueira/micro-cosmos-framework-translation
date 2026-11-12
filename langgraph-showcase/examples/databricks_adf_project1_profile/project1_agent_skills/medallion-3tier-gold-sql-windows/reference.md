## Reference: concrete templates for this repo shape

This reference is intentionally short: it gives copy/paste snippets the agent can adapt.

### ETL pipeline updates (typical)

#### Bronze extract (CSV → Parquet)

Use:

```python
from pyspark.sql.functions import current_timestamp, input_file_name

df = (
    spark.read
    .option("header", "true")
    .option("inferSchema", "true")
    .csv(source_path)
)

df = (
    df.withColumn("_ingestion_timestamp", current_timestamp())
      .withColumn("_source_file", input_file_name())
)

df.write.format("parquet").mode("append").save(bronze_path)
```

#### Silver process (Parquet → Delta)

```python
df = spark.read.format("parquet").load(bronze_path)
# transformations...
df = df.withColumn("_processing_timestamp", current_timestamp())
df.write.format("delta").mode("overwrite").option("mergeSchema","true").save(silver_path)
```

#### Gold serve (Delta → Delta)

```python
df = spark.read.format("delta").load(silver_path)
# aggregations...
df = df.withColumn("_serving_timestamp", current_timestamp())
df.write.format("delta").mode("overwrite").option("mergeSchema","true").save(gold_path)
```

### Delta time travel helper

```python
def read_delta_as_of(path: str, version: int | None = None, timestamp: str | None = None):
    if version is not None and timestamp is not None:
        raise ValueError("Provide only one of version or timestamp")

    r = spark.read.format("delta")
    if version is not None:
        r = r.option("versionAsOf", int(version))
    if timestamp is not None:
        r = r.option("timestampAsOf", timestamp)
    return r.load(path)
```

### SQL: create a view over Gold

```sql
CREATE OR REPLACE TEMP VIEW customer_transactions_gold AS
SELECT *
FROM delta.`/data/serving/customer_transactions`;
```

### SQL: time travel patterns

```sql
SELECT *
FROM delta.`/data/serving/customer_transactions` VERSION AS OF 0;

SELECT *
FROM delta.`/data/serving/customer_transactions` TIMESTAMP AS OF '2026-01-01 00:00:00';
```

### SQL: window function patterns

Latest per key:

```sql
WITH ranked AS (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY transaction_date DESC) AS rn
  FROM customer_transactions_gold
)
SELECT * FROM ranked WHERE rn = 1;
```

Running totals:

```sql
SELECT
  *,
  SUM(total_amount) OVER (
    PARTITION BY customer_id
    ORDER BY transaction_date
    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
  ) AS running_total
FROM customer_transactions_gold;
```

