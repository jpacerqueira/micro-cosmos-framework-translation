{{ config(materialized='view') }}

SELECT
  customer_id,
  full_name,
  NVL(segment, 'unassigned') AS segment,
  country
FROM {{ source('retail', 'customers') }}
WHERE customer_id IS NOT NULL
