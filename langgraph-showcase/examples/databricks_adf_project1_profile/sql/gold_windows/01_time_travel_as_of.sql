-- Time travel query over Gold Delta table
-- Option A: query by path
SELECT *
FROM delta.`<GOLD_PATH>` VERSION AS OF 0
LIMIT 50;

-- Option B: query by timestamp
SELECT *
FROM delta.`<GOLD_PATH>` TIMESTAMP AS OF '2026-01-01 00:00:00'
LIMIT 50;

