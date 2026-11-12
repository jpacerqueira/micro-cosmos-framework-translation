-- Running totals over time using window functions
-- Replace:
-- - <GOLD_TABLE_OR_VIEW> with your Gold table/view
-- - <PARTITION_COL> with an entity id (optional; remove PARTITION BY if not needed)
-- - <ORDER_COL> with a date/timestamp column
-- - <VALUE_COL> with the measure column

SELECT
  *,
  SUM(<VALUE_COL>) OVER (
    PARTITION BY <PARTITION_COL>
    ORDER BY <ORDER_COL>
    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
  ) AS running_total
FROM <GOLD_TABLE_OR_VIEW>;

