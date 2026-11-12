-- =============================================================================
-- NatWest Fraud Detection - Install All Scripts
-- Run this from the mssql/ directory using sqlcmd:
--   sqlcmd -S localhost -U fdadmin -P changeme -d FraudDetectionDb -i install_all.sql
-- =============================================================================

USE FraudDetectionDb;
GO

PRINT '=== Step 1: Creating ACCOUNT_MASTER ===';
:r 01_account_master.sql
GO

PRINT '=== Step 2: Creating TXN_QUEUE ===';
:r 02_txn_queue.sql
GO

PRINT '=== Step 3: Creating MERCHANT_RISK ===';
:r 03_merchant_risk.sql
GO

PRINT '=== Step 4: Creating CUST_PROFILE ===';
:r 04_cust_profile.sql
GO

PRINT '=== Step 5: Creating WATCHLIST ===';
:r 05_watchlist.sql
GO

PRINT '=== Step 6: Creating WATCHLIST_HITS ===';
:r 06_watchlist_hits.sql
GO

PRINT '=== Step 7: Creating FRAUD_ALERTS ===';
:r 07_fraud_alerts.sql
GO

PRINT '=== Step 8: Creating MQ_FAILURE_LOG ===';
:r 08_mq_failure_log.sql
GO

PRINT '=== Step 9: Creating SLA_BREACH_LOG ===';
:r 09_sla_breach_log.sql
GO

PRINT '=== Step 10: Loading Seed Data ===';
:r 10_seed_data.sql
GO

PRINT '=== All scripts completed successfully ===';
