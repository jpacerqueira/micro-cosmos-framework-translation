-- =============================================================================
-- Views and Access Grants
-- =============================================================================
-- Logical views that abstract over the physical tables + read-only grants
-- matching the pre-UCX access patterns observed in the lineage.
--
-- In hive_metastore, views are stored as Spark SQL views.
-- On Unity Catalog / BigQuery, these become Dataform SQLX view definitions.
-- =============================================================================

-- ---------------------------------------------------------------------------
-- businessintelligencesystems_prod — Catalog alias views
--
-- The lineage report references tables as:
--   businessintelligencesystems_prod.trusted.dim_item
--   businessintelligencesystems_prod.trusted.fact_sales_orders
-- In hive_metastore (legacy catalog) these live in:
--   trusted.dim_item, trusted.fact_sales_orders
-- These views provide the three-part-name compatibility layer.
-- ---------------------------------------------------------------------------

CREATE DATABASE IF NOT EXISTS businessintelligencesystems_prod_trusted
  COMMENT 'Compatibility alias database for cross-catalog queries referencing businessintelligencesystems_prod.trusted.*. Views proxy to trusted.* Delta tables.'
  WITH DBPROPERTIES ('alias_for' = 'trusted', 'ucx_status' = 'resolve_with_external_location');

CREATE VIEW IF NOT EXISTS businessintelligencesystems_prod_trusted.dim_item
  COMMENT 'Alias view — proxies trusted.dim_item for cross-catalog queries using businessintelligencesystems_prod.trusted.dim_item notation.'
  AS SELECT * FROM trusted.dim_item;

CREATE VIEW IF NOT EXISTS businessintelligencesystems_prod_trusted.fact_sales_orders
  COMMENT 'Alias view — proxies trusted.fact_sales_orders for cross-catalog queries.'
  AS SELECT * FROM trusted.fact_sales_orders;

-- ---------------------------------------------------------------------------
-- Analytical views on top of the star schema
-- These are used by BISAnalytics notebook and ADF pipeline queries.
-- ---------------------------------------------------------------------------

-- v_item_stock_status — BISAnalytics cross-catalog join result
-- Materialised by the notebook; this view provides the same logic on-demand.
CREATE VIEW IF NOT EXISTS trusted.v_item_stock_status
  COMMENT 'Cross-catalog view joining trusted.dim_item × branded_prod.noclick_stock_levels × daily fact sales. Replaces the manual join in BISAnalytics.py cell 3.'
  AS
  SELECT
    di.ItemNumber,
    di.ProductCategory,
    di.BrandCode,
    di.RetailPrice,
    ns.StockLevel,
    ns.AvailableUnits,
    ns.WarehouseLocation,
    ns.StockStatus,
    COALESCE(fso.TotalRevenue, 0)  AS TotalRevenue,
    COALESCE(fso.OrderCount, 0)    AS OrderCount
  FROM trusted.dim_item di
  LEFT JOIN branded_prod.noclick_stock_levels ns
    ON di.ItemNumber = ns.ItemNumber
   AND di.IsCurrentRecord = TRUE
  LEFT JOIN (
    SELECT
      item_number,
      SUM(OrderAmount)   AS TotalRevenue,
      COUNT(OrderID)     AS OrderCount
    FROM trusted.fact_sales_orders
    GROUP BY item_number
  ) fso ON di.ItemNumber = fso.item_number
  WHERE di.IsCurrentRecord = TRUE;

-- v_season_attribution_base — common base for CTAS write-back targets
-- Used as the SELECT foundation by BISPipeline.materialise_attribution_targets()
CREATE VIEW IF NOT EXISTS refined.v_season_attribution_base
  COMMENT 'Season attribution base view joining fact_sales_orders_season × dim_item × item_season. Input for all 15 branded_prod CTAS write-back materialisation jobs.'
  AS
  SELECT
    fs.ItemNumber,
    fs.SeasonCode,
    fs.ProductCategory,
    fs.BrandCode,
    fs.TeamCode,
    fs.SeasonRevenue,
    fs.SeasonUnitsSold,
    fs.UniqueCustomers,
    fs.UniqueOrders,
    fs.AvgOrderValue,
    fs.ReturnRatePct,
    fs.PreSeasonRevenue,
    fs.SeasonRank,
    fs.IsTopPerformer,
    iss.SeasonStartDate,
    iss.SeasonEndDate,
    iss.IsCarryOver,
    dt.TeamName,
    di.SupplierID,
    di.RetailPrice,
    di.IsActive
  FROM refined.fact_sales_orders_season fs
  INNER JOIN product_systems.item_season iss
    ON fs.ItemNumber = iss.ItemNumber
   AND fs.SeasonCode = iss.SeasonCode
  LEFT JOIN trusted.dim_item_team dt
    ON fs.TeamCode = dt.TeamCode
  LEFT JOIN trusted.dim_item di
    ON fs.ItemNumber = di.ItemNumber
   AND di.IsCurrentRecord = TRUE;

-- v_payment_provider_daily — cross-provider diagnostic summary
-- Used by PaymentDiagnostics notebook for cross-provider comparison
CREATE VIEW IF NOT EXISTS gold.v_payment_provider_daily
  COMMENT 'Daily cross-provider payment summary. UNION ALL of all 5 diagnostic catalogs. Note: get_json_object() anti-pattern present in source queries — translated to JSON_VALUE() on BigQuery.'
  AS
  SELECT
    CAST(EventTimestamp AS DATE)  AS EventDate,
    'WooPayments'                  AS Provider,
    COUNT(*)                       AS EventCount,
    COUNT(CASE WHEN EventType LIKE '%fail%' OR EventType LIKE '%decline%' THEN 1 END) AS FailedCount
  FROM wp_diagnostic.payment_events
  GROUP BY CAST(EventTimestamp AS DATE)
  UNION ALL
  SELECT CAST(EventTimestamp AS DATE), 'AmazonPay', COUNT(*),
    COUNT(CASE WHEN EventType IN ('DISPUTE_OPENED','CHARGEBACK_RECEIVED') THEN 1 END)
  FROM ap_diagnostic.payment_events GROUP BY CAST(EventTimestamp AS DATE)
  UNION ALL
  SELECT CAST(EventTimestamp AS DATE), 'PayPal', COUNT(*),
    COUNT(CASE WHEN EventType LIKE 'PAYMENT.CAPTURE.DECLINED%' THEN 1 END)
  FROM pp_diagnostic.payment_events GROUP BY CAST(EventTimestamp AS DATE)
  UNION ALL
  SELECT CAST(EventTimestamp AS DATE), 'GooglePay', COUNT(*),
    COUNT(CASE WHEN EventType = 'AUTHORIZATION_RESULT' THEN 1 END)
  FROM gp_diagnostic.payment_events GROUP BY CAST(EventTimestamp AS DATE)
  UNION ALL
  SELECT CAST(EventTimestamp AS DATE), 'Klarna', COUNT(*),
    COUNT(CASE WHEN EventType = 'DISPUTE_CREATED' THEN 1 END)
  FROM klarna_diagnostic.payment_events GROUP BY CAST(EventTimestamp AS DATE);

-- ---------------------------------------------------------------------------
-- Access Grants (Hive metastore pre-UC permissions)
-- These represent the access patterns observed in lineage; translate to
-- IAM bindings (roles/bigquery.dataViewer, etc.) on GCP.
-- ---------------------------------------------------------------------------

-- BIS analytics team — read access to trusted and refined
GRANT SELECT ON DATABASE trusted    TO `analytics-engineering@retail.internal`;
GRANT SELECT ON DATABASE refined    TO `analytics-engineering@retail.internal`;
GRANT SELECT ON DATABASE bismerged  TO `analytics-engineering@retail.internal`;

-- Branded engineering — read from trusted (for join key), write to branded_prod
GRANT SELECT ON DATABASE trusted        TO `branded-engineering@retail.internal`;
GRANT SELECT, MODIFY ON DATABASE branded_prod TO `branded-engineering@retail.internal`;

-- Payments team — read/write their own diagnostic schemas
GRANT ALL PRIVILEGES ON DATABASE wp_diagnostic       TO `payments-engineering@retail.internal`;
GRANT ALL PRIVILEGES ON DATABASE ap_diagnostic       TO `payments-engineering@retail.internal`;
GRANT ALL PRIVILEGES ON DATABASE pp_diagnostic       TO `payments-engineering@retail.internal`;
GRANT ALL PRIVILEGES ON DATABASE gp_diagnostic       TO `payments-engineering@retail.internal`;
GRANT ALL PRIVILEGES ON DATABASE klarna_diagnostic   TO `payments-engineering@retail.internal`;
-- Klarna needs to read trusted for reconciliation
GRANT SELECT ON TABLE trusted.fact_sales_orders      TO `payments-engineering@retail.internal`;

-- Data engineering — full access to all raw/processing schemas
GRANT ALL PRIVILEGES ON DATABASE product_systems_raw TO `data-engineering@retail.internal`;
GRANT ALL PRIVILEGES ON DATABASE product_systems     TO `data-engineering@retail.internal`;
GRANT ALL PRIVILEGES ON DATABASE productsystems      TO `data-engineering@retail.internal`;
GRANT ALL PRIVILEGES ON DATABASE bronze              TO `data-engineering@retail.internal`;
GRANT ALL PRIVILEGES ON DATABASE silver              TO `data-engineering@retail.internal`;
GRANT ALL PRIVILEGES ON DATABASE gold                TO `data-engineering@retail.internal`;
GRANT ALL PRIVILEGES ON DATABASE trusted             TO `data-engineering@retail.internal`;

-- Logistics team — streaming domain
GRANT ALL PRIVILEGES ON DATABASE warehouselogistics_prod TO `logistics-engineering@retail.internal`;
GRANT SELECT ON TABLE trusted.fact_sales_orders          TO `logistics-engineering@retail.internal`;

-- Read-only group for BI tools / Tableau / Looker
GRANT SELECT ON DATABASE trusted    TO `bi-readers@retail.internal`;
GRANT SELECT ON DATABASE gold       TO `bi-readers@retail.internal`;
GRANT SELECT ON DATABASE refined    TO `bi-readers@retail.internal`;
GRANT SELECT ON DATABASE bismerged  TO `bi-readers@retail.internal`;
