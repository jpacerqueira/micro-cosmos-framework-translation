---
name: tsql-to-bigquery-sql
description: Translates T-SQL dialect (SQL Server syntax carried over from legacy ETLs) present in Databricks SQL cells to BigQuery-compatible SQL. Covers DATEADD, GETDATE, DATEDIFF, ISNULL, LEN, SELECT TOP, and get_json_object patterns. db2bq applies these automatically; this skill documents what was translated and what remains manual.
disable-model-invocation: true
---

# T-SQL → BigQuery SQL Translation

## Context

Several notebooks in this project carry T-SQL dialect from SQL Server ETLs:
- `BISAnalytics.py` — DATEADD/GETDATE/DATEDIFF/ISNULL/LEN/SELECT TOP in SQL cells
- `PaymentDiagnostics.py` — DATEADD/GETDATE/DATEDIFF/ISNULL in payment query cells

db2bq's `_translate_tsql()` function applies regex-based translations automatically.
This skill documents the full mapping for cases that need manual review.

## Automatic translations (applied by db2bq)

| T-SQL | BigQuery SQL | Notes |
|---|---|---|
| `GETDATE()` | `CURRENT_TIMESTAMP()` | |
| `DATEADD(day, N, col)` | `DATE_ADD(col, INTERVAL N DAY)` | unit mapped: day→DAY, month→MONTH, year→YEAR, week→WEEK |
| `DATEADD(day, -N, col)` | `DATE_SUB(col, INTERVAL N DAY)` | negative N → `DATE_SUB` |
| `DATEDIFF(day, start, end)` | `DATE_DIFF(end, start, DAY)` | argument order flips |
| `ISNULL(expr, default)` | `IFNULL(expr, default)` | |
| `LEN(expr)` | `LENGTH(expr)` | |
| `SELECT TOP N ...` | `SELECT ...` + `LIMIT N` appended | |

## Manual translations (not handled by db2bq)

| T-SQL | BigQuery SQL | Why manual |
|---|---|---|
| `GETDATE()` inside `DATEADD` complex nesting | `DATE_ADD(CURRENT_TIMESTAMP(), ...)` | Nested regex doesn't resolve reliably |
| `CONVERT(DATE, col, 103)` | `PARSE_DATE('%d/%m/%Y', col)` | format codes vary |
| `FORMAT(col, 'yyyy-MM-dd')` | `FORMAT_DATE('%Y-%m-%d', col)` | |
| `CAST(col AS NVARCHAR(50))` | `CAST(col AS STRING)` | NVARCHAR → STRING |
| `CHARINDEX(substr, str)` | `STRPOS(str, substr)` | argument order flips |
| `SUBSTRING(str, start, len)` | `SUBSTR(str, start, len)` | |
| `LTRIM/RTRIM` | `LTRIM/RTRIM` | same name, works in BQ |
| `@@ROWCOUNT` | Not supported — use `SELECT COUNT(*) ...` | |
| `NOLOCK` hint | Remove — BigQuery is ACID, no hints needed | |

## get_json_object → BigQuery JSON functions

`get_json_object(col, '$.field')` is Spark SQL — BigQuery uses different functions:

| Spark SQL | BigQuery SQL | Notes |
|---|---|---|
| `get_json_object(col, '$.field')` | `JSON_VALUE(col, '$.field')` | returns STRING |
| `get_json_object(col, '$.nested.field')` | `JSON_VALUE(col, '$.nested.field')` | |
| `get_json_object(col, '$.amount.value')` | `JSON_VALUE(col, '$.amount.value')` | |

For structured access (returns JSON not string):
- `JSON_QUERY(col, '$.object')` — returns a JSON object or array

## Full example rewrite

**Source (Databricks SQL cell):**
```sql
SELECT
    ItemNumber,
    DATEADD(day, 7, OrderDate) AS DeliveryEstimate,
    DATEADD(month, -3, GETDATE()) AS ThreeMonthsAgo,
    DATEDIFF(day, OrderDate, GETDATE()) AS DaysSinceOrder,
    ISNULL(ReturnDate, GETDATE()) AS EffectiveReturnDate,
    LEN(ItemNumber) AS ItemNumberLength
FROM fact_sales_orders
WHERE DATEDIFF(day, OrderDate, GETDATE()) <= 90
```

**After db2bq automatic translation:**
```sql
SELECT
    ItemNumber,
    DATE_ADD(OrderDate, INTERVAL 7 DAY) AS DeliveryEstimate,
    DATE_SUB(CURRENT_TIMESTAMP(), INTERVAL 3 MONTH) AS ThreeMonthsAgo,
    DATE_DIFF(CURRENT_TIMESTAMP(), OrderDate, DAY) AS DaysSinceOrder,
    IFNULL(ReturnDate, CURRENT_TIMESTAMP()) AS EffectiveReturnDate,
    LENGTH(ItemNumber) AS ItemNumberLength
FROM fact_sales_orders
WHERE DATE_DIFF(CURRENT_TIMESTAMP(), OrderDate, DAY) <= 90
```

## SELECT TOP rewrite

**Source:**
```sql
SELECT TOP 100 * FROM fact_sales_orders ORDER BY OrderDate DESC
```

**Target:**
```sql
SELECT * FROM fact_sales_orders ORDER BY OrderDate DESC
LIMIT 100
```

Note: BigQuery requires `ORDER BY` before `LIMIT` for deterministic results — always verify.

## Checklist

- [ ] Review all `.py` files in `dataproc/` for `# TODO(db2bq): T-SQL` comments
- [ ] Replace `get_json_object()` with `JSON_VALUE()` in all BigQuery SQL files
- [ ] Review `CONVERT(...)` and `FORMAT(...)` patterns manually
- [ ] Test date arithmetic with actual BQ dates (timezone assumptions may differ)
- [ ] Remove SQL Server query hints (`NOLOCK`, `UPDLOCK`)
