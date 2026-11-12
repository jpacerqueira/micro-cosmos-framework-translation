---
name: payment-json-payload-bigquery
description: Translates the 5-provider payment diagnostic JSON Payload anti-pattern from Spark SQL get_json_object() to BigQuery JSON_VALUE/JSON_EXTRACT functions. Covers WooPayments, AmazonPay, PayPal, GooglePay, and Klarna — including the cross-catalog join with BIS fact_sales_orders for Klarna reconciliation.
disable-model-invocation: true
---

# Payment JSON Payload → BigQuery

## Anti-pattern context

All 5 payment provider diagnostic catalogs store raw webhook events as a JSON
string in a `Payload` column. The notebooks use `get_json_object()` to extract
fields — this is Spark SQL and does not work in BigQuery SQL.

## Provider → required JSON fields

| Provider | Key fields in `$.` | Notes |
|---|---|---|
| WooPayments | `transaction_id`, `amount`, `currency`, `status`, `customer_email`, `error_code` | |
| AmazonPay | `order_reference_id`, `dispute_id`, `amount.value`, `amount.currencyCode`, `reason_code`, `resolution_date` | Nested `amount` object |
| PayPal | `id`, `status`, `amount.value`, `payer.email`, `failure_reason` | Nested objects |
| GooglePay | `result_code`, `decline_reason`, `amount` | |
| Klarna | `order_id`, `capture_amount`, `settlement_date`, `event_type` | Cross-catalog join with BIS |

## Translation

### Simple field extraction

**Spark SQL:**
```sql
get_json_object(Payload, '$.transaction_id') AS transaction_id
```

**BigQuery SQL:**
```sql
JSON_VALUE(Payload, '$.transaction_id') AS transaction_id
```

### Nested field extraction

**Spark SQL:**
```sql
get_json_object(Payload, '$.amount.value') AS amount
```

**BigQuery SQL:**
```sql
JSON_VALUE(Payload, '$.amount.value') AS amount
```

### Nested object (returns JSON)

**Spark SQL:**
```sql
get_json_object(Payload, '$.amount') AS amount_json
```

**BigQuery SQL:**
```sql
JSON_QUERY(Payload, '$.amount') AS amount_json
```

## Full WooPayments query rewrite

**Source:**
```sql
SELECT
    EventId,
    get_json_object(Payload, '$.transaction_id')   AS transaction_id,
    get_json_object(Payload, '$.amount')           AS amount,
    get_json_object(Payload, '$.status')           AS payment_status,
    DATEADD(day, 1, EventTimestamp)                AS NextRetryDate
FROM wp_diagnostic.payment_events
WHERE get_json_object(Payload, '$.status') IN ('failed', 'pending')
```

**Target (BigQuery):**
```sql
SELECT
    EventId,
    JSON_VALUE(Payload, '$.transaction_id')        AS transaction_id,
    JSON_VALUE(Payload, '$.amount')                AS amount,
    JSON_VALUE(Payload, '$.status')                AS payment_status,
    DATE_ADD(EventTimestamp, INTERVAL 1 DAY)       AS NextRetryDate
FROM `payment-project.wp_diagnostic.payment_events`
WHERE JSON_VALUE(Payload, '$.status') IN ('failed', 'pending')
```

## Klarna reconciliation — cross-catalog rewrite

**Source:**
```sql
FROM klarna_diagnostic.payment_events ke
LEFT JOIN businessintelligencesystems_prod.trusted.fact_sales_orders fso
    ON get_json_object(ke.Payload, '$.order_id') = fso.external_order_ref
```

**Target:**
```sql
FROM `payment-project.klarna_diagnostic.payment_events` ke
LEFT JOIN `bis-project.trusted.fact_sales_orders` fso
    ON JSON_VALUE(ke.Payload, '$.order_id') = fso.external_order_ref
```

## BigQuery JSON column type (preferred)

If re-designing the table schema, prefer the native `JSON` type over `STRING`:

```sql
-- Parse stored JSON string to native JSON type on ingest
SELECT
    EventId,
    PARSE_JSON(Payload) AS payload_json,
    JSON_VALUE(PARSE_JSON(Payload), '$.transaction_id') AS transaction_id
FROM raw_payment_events
```

With native JSON type, use `payload_json.transaction_id` (dot notation, no JSON_VALUE needed).

## BISQualityRules.check_payment_json_completeness

Before translating, validate JSON field completeness (in `src/data_quality/bis_quality_rules.py`):

```python
results = bis_rules.check_payment_json_completeness(
    df=wp_events_df,
    provider="WooPayments",
    required_fields=["transaction_id", "amount", "currency", "status"]
)
# Fails if null rate > 5% for any required field
```

## DataProc → BigQuery translation scope

db2bq does **not** automatically translate `get_json_object()` to `JSON_VALUE()`.
This is a **Phase 6** manual step. The T-SQL translator handles DATEADD/GETDATE
automatically, but JSON function names are Spark-specific.

After db2bq translation, search for remaining `get_json_object` calls:

```bash
grep -r "get_json_object" translated_2bq_project1_databricks_adf/
```

Each hit needs manual replacement with `JSON_VALUE(...)` or `JSON_QUERY(...)`.

## Checklist

- [ ] Replace all `get_json_object(col, '$.field')` with `JSON_VALUE(col, '$.field')`
- [ ] Replace all `get_json_object(col, '$.obj')` returning objects with `JSON_QUERY`
- [ ] Rewrite five-provider cross-catalog queries with BigQuery FQNs
- [ ] Run `BISQualityRules.check_payment_json_completeness()` for each provider before cutover
- [ ] Consider migrating Payload column to native BigQuery `JSON` type in the new schema
- [ ] Update Klarna reconciliation to use `bis-project` FQN for `fact_sales_orders`
