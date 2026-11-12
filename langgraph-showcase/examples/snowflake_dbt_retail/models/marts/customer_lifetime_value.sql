{{ config(materialized='table') }}

SELECT
  c.customer_id,
  c.segment,
  COUNT(o.order_id) AS order_count,
  SUM(o.amount) AS lifetime_value
FROM {{ ref('stg_customers') }} c
JOIN {{ ref('stg_orders') }} o
  ON c.customer_id = o.customer_id
GROUP BY c.customer_id, c.segment
