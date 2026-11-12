-- Compare two points-in-time of the Gold table (Delta time travel) and detect changes.
-- Replace <GOLD_PATH>, <KEY_COL> and list the columns you care about in the SELECTs.

WITH v0 AS (
  SELECT *
  FROM delta.`<GOLD_PATH>` VERSION AS OF 0
),
v1 AS (
  SELECT *
  FROM delta.`<GOLD_PATH>` VERSION AS OF 1
),
joined AS (
  SELECT
    COALESCE(v1.<KEY_COL>, v0.<KEY_COL>) AS <KEY_COL>,
    CASE
      WHEN v0.<KEY_COL> IS NULL THEN 'inserted'
      WHEN v1.<KEY_COL> IS NULL THEN 'deleted'
      ELSE 'potentially_updated'
    END AS change_type,
    v0 AS old_row,
    v1 AS new_row
  FROM v0
  FULL OUTER JOIN v1
    ON v0.<KEY_COL> = v1.<KEY_COL>
)
SELECT *
FROM joined;

