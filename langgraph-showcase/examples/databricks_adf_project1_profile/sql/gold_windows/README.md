## Gold tier SQL queries (Windows / Window functions)

This folder contains **ready-to-run Spark SQL** examples targeted at querying the **Gold tier** stored in **Delta Lake** (time travel enabled).

### How to use

- **Direct path queries**:
  - Replace `<GOLD_PATH>` with your Gold Delta path (example: `/data/serving/customer_transactions`).
- **Or create a view** (recommended):
  - Create a temp view in your Spark session:
    - `CREATE OR REPLACE TEMP VIEW customer_transactions_gold AS SELECT * FROM delta.\`/data/serving/customer_transactions\`;`
  - Then run the queries by replacing `<GOLD_TABLE_OR_VIEW>` with `customer_transactions_gold`.

### Time travel

Delta supports time travel using:

- `VERSION AS OF <n>`
- `TIMESTAMP AS OF '<yyyy-MM-dd HH:mm:ss>'`

You’ll see both patterns in the `.sql` examples.

