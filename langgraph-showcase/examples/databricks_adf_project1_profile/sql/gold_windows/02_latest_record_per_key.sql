-- Latest record per business key using window functions
-- Replace:
-- - <GOLD_TABLE_OR_VIEW> with your Gold table/view
-- - <KEY_COL> with your business key column
-- - <TS_COL> with the timestamp/sequence column

WITH ranked AS (
  SELECT
    *,
    ROW_NUMBER() OVER (PARTITION BY <KEY_COL> ORDER BY <TS_COL> DESC) AS rn
  FROM <GOLD_TABLE_OR_VIEW>
)
SELECT *
FROM ranked
WHERE rn = 1;

