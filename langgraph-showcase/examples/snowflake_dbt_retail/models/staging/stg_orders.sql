{{ config(materialized='view') }}

SELECT
  order_id,
  customer_id,
  order_date,
  amount,
  NVL(channel, 'unknown') AS channel
FROM {{ source('retail', 'orders') }}
WHERE order_date >= DATEADD(day, -90, CURRENT_DATE())
  AND amount IS NOT NULL
