-- ============================================================================
-- install_all.sql
-- BankXYZ Fraud Detection — Master install script for Oracle 10g
--
-- Runs all DDL files in dependency order:
--   sequences first → tables with no FKs → tables with FKs
--
-- Usage (SQL*Plus):
--   sqlplus FDADMIN/password@//host:1521/SID @install_all.sql
--
-- Usage (SQLcl):
--   sql FDADMIN/password@//host:1521/SID @install_all.sql
--
-- Prerequisites:
--   - Schema owner FDADMIN must exist with CREATE TABLE, CREATE SEQUENCE,
--     CREATE INDEX, CREATE TRIGGER privileges
--   - All .sql files must be in the same directory as this script
--
-- Re-run safety:
--   Each individual file drops its objects before recreating them using
--   PL/SQL blocks that swallow ORA-00942 (table not found) and
--   ORA-02289 (sequence not found). Safe to re-run on an existing schema.
-- ============================================================================

PROMPT
PROMPT ============================================================
PROMPT  BankXYZ Fraud Detection — Oracle 10g schema install
PROMPT ============================================================
PROMPT

SET ECHO OFF
SET FEEDBACK ON
SET DEFINE OFF
SET SQLBLANKLINES ON
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK

-- ----------------------------------------------------------------------------
-- Step 1: Sequences
-- Must run before any table that uses a sequence for its PK.
-- ----------------------------------------------------------------------------
PROMPT [1/10] Creating sequences...
@00_sequences.sql

-- ----------------------------------------------------------------------------
-- Step 2: Foundation tables (no foreign key dependencies)
-- ----------------------------------------------------------------------------
PROMPT [2/10] Creating ACCOUNT_MASTER...
@01_account_master.sql

PROMPT [3/10] Creating MERCHANT_RISK...
@03_merchant_risk.sql

PROMPT [4/10] Creating CUST_PROFILE...
@04_cust_profile.sql

PROMPT [5/10] Creating WATCHLIST...
@05_watchlist.sql

PROMPT [6/10] Creating WATCHLIST_HITS...
@06_watchlist_hits.sql

PROMPT [7/10] Creating MQ_FAILURE_LOG...
@08_mq_failure_log.sql

PROMPT [8/10] Creating SLA_BREACH_LOG...
@09_sla_breach_log.sql

-- ----------------------------------------------------------------------------
-- Step 3: Tables with foreign key dependencies
-- TXN_QUEUE  → ACCOUNT_MASTER
-- FRAUD_ALERTS → TXN_QUEUE
-- ----------------------------------------------------------------------------
PROMPT [9/10] Creating TXN_QUEUE (FK: ACCOUNT_MASTER)...
@02_txn_queue.sql

PROMPT [10/10] Creating FRAUD_ALERTS (FK: TXN_QUEUE)...
@07_fraud_alerts.sql

-- ----------------------------------------------------------------------------
-- Step 11: Example seed data
-- Inserts the five accounts, four merchants, customer profiles, watchlist
-- entry, and pre-seeded velocity transactions required by examples-api.txt.
-- Run last so all FK targets (ACCOUNT_MASTER, TXN_QUEUE) already exist.
-- ----------------------------------------------------------------------------
PROMPT [11/11] Loading example seed data...
@10_seed_data.sql

-- ----------------------------------------------------------------------------
-- Summary
-- ----------------------------------------------------------------------------
PROMPT
PROMPT ============================================================
PROMPT  Schema install complete. Objects created:
PROMPT
PROMPT  Sequences (6):
PROMPT    FD_SEQ, AUDIT_SEQ, WATCHLIST_SEQ,
PROMPT    WL_HITS_SEQ, MQ_FAIL_SEQ, SLA_BREACH_SEQ
PROMPT
PROMPT  Tables (9):
PROMPT    ACCOUNT_MASTER, TXN_QUEUE, MERCHANT_RISK,
PROMPT    CUST_PROFILE, WATCHLIST, WATCHLIST_HITS,
PROMPT    FRAUD_ALERTS, MQ_FAILURE_LOG, SLA_BREACH_LOG
PROMPT
PROMPT  Triggers (4):
PROMPT    TRG_WATCHLIST_ID, TRG_WL_HITS_ID,
PROMPT    TRG_MQ_FAIL_ID,   TRG_SLA_BREACH_ID
PROMPT
PROMPT  Indexes (8):
PROMPT    IX_TXN_STATUS, IX_TXN_ACCT,
PROMPT    IX_WL_TYPE_NAME, IX_WL_ACCT,
PROMPT    IX_WL_HITS_ACCT, IX_WL_HITS_TXN,
PROMPT    IX_ALERT_ACCT_STATUS, IX_ALERT_STATUS_TS,
PROMPT    IX_MQ_FAIL_TS, IX_SLA_BREACH_TS, IX_SLA_BREACH_ACCT
PROMPT ============================================================
PROMPT

COMMIT;
