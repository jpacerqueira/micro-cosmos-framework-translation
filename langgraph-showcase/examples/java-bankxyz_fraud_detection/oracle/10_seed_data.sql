-- ============================================================================
-- 10_seed_data.sql
-- BankXYZ Fraud Detection — Example seed data
--
-- Populates the five accounts, four merchants, one watchlist entry, and
-- velocity transaction history needed to exercise every example in
-- fraud_api/examples-api.txt.
--
-- Scoring notes (signal weights: amount=0.25, merchant=0.25, velocity=0.20,
--                                profile=0.20, watchlist=0.10):
--
--   Example 1a / 1f  (APPROVE  <0.75):
--     ACC0000001 active; TESCO001 LOW (0.10); 45.00 within profile range;
--     no geo/TOD deviation; CNP uplift 0.10 → composite ≈ 0.07
--
--   Example 1b  (REVIEW  0.75–0.90):
--     ACC0000002 active; FOREX999 HIGH (0.80); 6500.00 ≥ 5000 (amtScore=0.80);
--     USA vs usual GBR → geo deviation; amount >> profile max → AMT_HIGH_DEVIATION;
--     cnpFlag=true uplift; 5 pre-seeded velocity txns → velocityScore=1.0
--     → composite ≈ 0.76 (normal hours) – 0.80 (outside hours)  REVIEW ✓
--
--   Example 1c  (DECLINE ≥0.90):
--     ACC0000003 active; BLCKM001 BLOCKED (merchantScore=1.0); 9999.99 ≥ 5000;
--     INTERNAL watchlist hit → watchlistScore=0.9 (weight 0.10);
--     USUAL_HR_START=0 / USUAL_HR_END=0 confines "normal window" to midnight
--     only — any hour ≥ 1 adds TOD deviation (0.20); combined with geo
--     deviation (RUS≠GBR) and amount deviation → profileScore=0.90;
--     5 pre-seeded velocity txns → velocityScore=1.0
--     → composite ≈ 0.92 for 23/24 hours  DECLINE ✓
--
--   Example 1d  (APPROVE  <0.75, CHIPPIN):
--     CHIPPIN channel zeros profile weight and redistributes it equally to
--     the four remaining signals (BAU-2021-09). 12.50 < 200, CAFEBAR1 LOW,
--     no velocity → composite ≈ 0.05  APPROVE ✓
--
--   Example 1e  (DECLINE, forced):
--     FROZENACCT status='F' → FraudRulesService forces score=1.0 immediately,
--     no further signal evaluation  DECLINE ✓
--
-- Run after:    install_all.sql (all tables must exist)
-- Re-run safe:  yes — install_all.sql drops and recreates tables before this
--               script runs, so inserts always land in empty tables.
--
-- Velocity window caveat:
--   VelocityCheckService counts TXN_QUEUE rows WHERE TXN_TS > NOW()-24h.
--   The pre-seeded rows use TXN_TS = CURRENT_TIMESTAMP (container init time),
--   so velocityScore=1.0 holds for the first 24 hours after container start.
--   Examples 1b and 1c require the container to have been started within that
--   window; after 24 hours they will return APPROVE/REVIEW respectively due
--   to zero velocity.
-- ============================================================================

PROMPT
PROMPT ============================================================
PROMPT  Loading example seed data
PROMPT ============================================================
PROMPT

SET ECHO OFF
SET FEEDBACK ON
SET DEFINE OFF
WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK

-- ----------------------------------------------------------------------------
-- Step 1: MERCHANT_RISK
-- Four merchants referenced across examples 1a–1f.
-- ----------------------------------------------------------------------------
PROMPT [1/5] Inserting MERCHANT_RISK (4 rows)...

INSERT INTO MERCHANT_RISK (MERCHANT_CODE, MERCHANT_NAME, BLOCKED_FLAG, RISK_BAND, EFFECTIVE_FROM)
VALUES ('TESCO001', 'Tesco Stores Ltd', 'N', 'LOW ', SYSDATE);

INSERT INTO MERCHANT_RISK (MERCHANT_CODE, MERCHANT_NAME, BLOCKED_FLAG, RISK_BAND, EFFECTIVE_FROM)
VALUES ('FOREX999', 'International FX Services', 'N', 'HIGH', SYSDATE);

INSERT INTO MERCHANT_RISK (MERCHANT_CODE, MERCHANT_NAME, BLOCKED_FLAG, RISK_BAND, BLOCK_REASON, EFFECTIVE_FROM)
VALUES ('BLCKM001', 'Blocked Merchant Ltd', 'Y', 'LOW ',
        'Confirmed fraud nexus - FRD-2024-0042', SYSDATE);

INSERT INTO MERCHANT_RISK (MERCHANT_CODE, MERCHANT_NAME, BLOCKED_FLAG, RISK_BAND, EFFECTIVE_FROM)
VALUES ('CAFEBAR1', 'Cafe Bar One', 'N', 'LOW ', SYSDATE);

-- ----------------------------------------------------------------------------
-- Step 2: ACCOUNT_MASTER
-- Five accounts covering every documented example scenario.
--   ACC0000001  A (Active)  CH  Low-risk domestic customer (examples 1a, 1f)
--   ACC0000002  A (Active)  CR  High-risk international card holder (example 1b)
--   ACC0000003  A (Active)  CH  Watchlisted, fraud-profile customer (example 1c)
--   ACC0000004  A (Active)  CH  Chip+PIN exemption customer (example 1d)
--   FROZENACCT  F (Frozen)  CH  Frozen account — forced score=1.0 (example 1e)
-- ----------------------------------------------------------------------------
PROMPT [2/5] Inserting ACCOUNT_MASTER (5 rows)...

INSERT INTO ACCOUNT_MASTER (ACCT_NO, CUST_ID, CUST_FULL_NAME, ACCT_STATUS, ACCT_TYPE, HOME_COUNTRY, DAILY_TXN_COUNT)
VALUES ('ACC0000001', 'C00000001', 'Alice Parsons', 'A', 'CH', 'GBR', 0);

INSERT INTO ACCOUNT_MASTER (ACCT_NO, CUST_ID, CUST_FULL_NAME, ACCT_STATUS, ACCT_TYPE, HOME_COUNTRY, DAILY_TXN_COUNT)
VALUES ('ACC0000002', 'C00000002', 'Bob Henderson', 'A', 'CR', 'GBR', 0);

INSERT INTO ACCOUNT_MASTER (ACCT_NO, CUST_ID, CUST_FULL_NAME, ACCT_STATUS, ACCT_TYPE, HOME_COUNTRY, DAILY_TXN_COUNT)
VALUES ('ACC0000003', 'C00000003', 'Viktor Orlov', 'A', 'CH', 'GBR', 0);

INSERT INTO ACCOUNT_MASTER (ACCT_NO, CUST_ID, CUST_FULL_NAME, ACCT_STATUS, ACCT_TYPE, HOME_COUNTRY, DAILY_TXN_COUNT)
VALUES ('ACC0000004', 'C00000004', 'Carol Davies', 'A', 'CH', 'GBR', 0);

INSERT INTO ACCOUNT_MASTER (ACCT_NO, CUST_ID, CUST_FULL_NAME, ACCT_STATUS, ACCT_TYPE, HOME_COUNTRY, DAILY_TXN_COUNT)
VALUES ('FROZENACCT', 'C00000005', 'Frozen Account', 'F', 'CH', 'GBR', 0);

-- ----------------------------------------------------------------------------
-- Step 3: CUST_PROFILE
-- Pre-computed 90-day behaviour baselines for the four active accounts.
-- FROZENACCT is omitted — the scoring pipeline exits before CustomerProfileService
-- is reached when the account status is FROZEN.
--
-- ACC0000003 profile uses USUAL_HR_START=0 / USUAL_HR_END=0 so that the
-- "normal window" is midnight only (hour=0). Any transaction at hour >= 1 adds
-- the TOD deviation score (+0.20), which is needed to push example 1c into the
-- DECLINE band.  This setup is intentional — it models a customer whose only
-- known legitimate activity was at midnight and who is already on the internal
-- watchlist.
-- ----------------------------------------------------------------------------
PROMPT [3/5] Inserting CUST_PROFILE (4 rows)...

INSERT INTO CUST_PROFILE (ACCT_NO, AVG_TXN_AMOUNT, MAX_TXN_AMOUNT, USUAL_COUNTRY, USUAL_CHANNEL, USUAL_HR_START, USUAL_HR_END, PROFILE_DATE)
VALUES ('ACC0000001', 35.00, 100.00, 'GBR', 'ONLINE  ', 7, 22, SYSDATE);

INSERT INTO CUST_PROFILE (ACCT_NO, AVG_TXN_AMOUNT, MAX_TXN_AMOUNT, USUAL_COUNTRY, USUAL_CHANNEL, USUAL_HR_START, USUAL_HR_END, PROFILE_DATE)
VALUES ('ACC0000002', 50.00, 200.00, 'GBR', 'ONLINE  ', 7, 22, SYSDATE);

INSERT INTO CUST_PROFILE (ACCT_NO, AVG_TXN_AMOUNT, MAX_TXN_AMOUNT, USUAL_COUNTRY, USUAL_CHANNEL, USUAL_HR_START, USUAL_HR_END, PROFILE_DATE)
VALUES ('ACC0000003', 100.00, 500.00, 'GBR', 'ATM     ', 0, 0, SYSDATE);

INSERT INTO CUST_PROFILE (ACCT_NO, AVG_TXN_AMOUNT, MAX_TXN_AMOUNT, USUAL_COUNTRY, USUAL_CHANNEL, USUAL_HR_START, USUAL_HR_END, PROFILE_DATE)
VALUES ('ACC0000004', 15.00, 50.00, 'GBR', 'CHIPPIN ', 7, 22, SYSDATE);

-- ----------------------------------------------------------------------------
-- Step 4: WATCHLIST
-- One INTERNAL entry for ACC0000003.
-- WatchlistService.screenWatchlist() checks MATCH_ACCT for INTERNAL entries,
-- so this triggers watchlistScore=0.9 (weight=0.10) without OFAC/PEP escalation.
-- The TRG_WATCHLIST_ID trigger populates WATCHLIST_ID from WATCHLIST_SEQ.
-- ----------------------------------------------------------------------------
PROMPT [4/5] Inserting WATCHLIST (1 row)...

INSERT INTO WATCHLIST (LIST_TYPE, MATCH_ACCT, LIST_STATUS, REF_NUMBER, ADDED_BY, EFFECTIVE_FROM)
VALUES ('INTERNAL', 'ACC0000003', 'ACTIVE', 'INT-FRD-2024-0099', 'FDOPS', SYSDATE);

-- ----------------------------------------------------------------------------
-- Step 5: TXN_QUEUE velocity pre-seed
-- VelocityCheckService counts rows WHERE ACCT_NO = ? AND TXN_STATUS IN ('P','S')
-- AND TXN_TS > NOW()-24h.  Real-time velocity limit = 5 txns.
--
-- TXN_TS defaults to CURRENT_TIMESTAMP, so these rows are inside the 24-hour
-- window at container start time.  TXN_STATUS='S' (Scored) prevents the
-- nightly batch from re-processing them.
--
-- ACC0000002: 5 txns → velocityScore = 5/5 = 1.0  (needed for 1b → REVIEW)
-- ACC0000003: 5 txns → velocityScore = 5/5 = 1.0  (needed for 1c → DECLINE)
-- ----------------------------------------------------------------------------
PROMPT [5/5] Inserting TXN_QUEUE velocity seed (10 rows)...

-- ACC0000002 — 5 scored transactions (example 1b velocity)
INSERT INTO TXN_QUEUE (TXN_ID, ACCT_NO, TXN_AMOUNT, MERCHANT_CODE, CHANNEL, TXN_COUNTRY, CARD_TYPE, CNP_FLAG, TXN_STATUS)
VALUES ('VEL2ACC200200001', 'ACC0000002', 45.00, 'TESCO001', 'ONLINE', 'GBR', 'CR', 'Y', 'S');

INSERT INTO TXN_QUEUE (TXN_ID, ACCT_NO, TXN_AMOUNT, MERCHANT_CODE, CHANNEL, TXN_COUNTRY, CARD_TYPE, CNP_FLAG, TXN_STATUS)
VALUES ('VEL2ACC200200002', 'ACC0000002', 62.00, 'TESCO001', 'ONLINE', 'GBR', 'CR', 'N', 'S');

INSERT INTO TXN_QUEUE (TXN_ID, ACCT_NO, TXN_AMOUNT, MERCHANT_CODE, CHANNEL, TXN_COUNTRY, CARD_TYPE, CNP_FLAG, TXN_STATUS)
VALUES ('VEL2ACC200200003', 'ACC0000002', 38.50, 'TESCO001', 'ONLINE', 'GBR', 'CR', 'Y', 'S');

INSERT INTO TXN_QUEUE (TXN_ID, ACCT_NO, TXN_AMOUNT, MERCHANT_CODE, CHANNEL, TXN_COUNTRY, CARD_TYPE, CNP_FLAG, TXN_STATUS)
VALUES ('VEL2ACC200200004', 'ACC0000002', 55.00, 'CAFEBAR1', 'ONLINE', 'GBR', 'CR', 'N', 'S');

INSERT INTO TXN_QUEUE (TXN_ID, ACCT_NO, TXN_AMOUNT, MERCHANT_CODE, CHANNEL, TXN_COUNTRY, CARD_TYPE, CNP_FLAG, TXN_STATUS)
VALUES ('VEL2ACC200200005', 'ACC0000002', 29.99, 'TESCO001', 'ONLINE', 'GBR', 'CR', 'Y', 'S');

-- ACC0000003 — 5 scored transactions (example 1c velocity)
INSERT INTO TXN_QUEUE (TXN_ID, ACCT_NO, TXN_AMOUNT, MERCHANT_CODE, CHANNEL, TXN_COUNTRY, CARD_TYPE, CNP_FLAG, TXN_STATUS)
VALUES ('VEL3ACC200300001', 'ACC0000003', 120.00, 'TESCO001', 'ATM', 'GBR', 'CR', 'N', 'S');

INSERT INTO TXN_QUEUE (TXN_ID, ACCT_NO, TXN_AMOUNT, MERCHANT_CODE, CHANNEL, TXN_COUNTRY, CARD_TYPE, CNP_FLAG, TXN_STATUS)
VALUES ('VEL3ACC200300002', 'ACC0000003', 95.00, 'TESCO001', 'ATM', 'GBR', 'CR', 'N', 'S');

INSERT INTO TXN_QUEUE (TXN_ID, ACCT_NO, TXN_AMOUNT, MERCHANT_CODE, CHANNEL, TXN_COUNTRY, CARD_TYPE, CNP_FLAG, TXN_STATUS)
VALUES ('VEL3ACC200300003', 'ACC0000003', 250.00, 'CAFEBAR1', 'ATM', 'GBR', 'CR', 'N', 'S');

INSERT INTO TXN_QUEUE (TXN_ID, ACCT_NO, TXN_AMOUNT, MERCHANT_CODE, CHANNEL, TXN_COUNTRY, CARD_TYPE, CNP_FLAG, TXN_STATUS)
VALUES ('VEL3ACC200300004', 'ACC0000003', 175.00, 'TESCO001', 'ATM', 'RUS', 'CR', 'N', 'S');

INSERT INTO TXN_QUEUE (TXN_ID, ACCT_NO, TXN_AMOUNT, MERCHANT_CODE, CHANNEL, TXN_COUNTRY, CARD_TYPE, CNP_FLAG, TXN_STATUS)
VALUES ('VEL3ACC200300005', 'ACC0000003', 410.00, 'TESCO001', 'ATM', 'GBR', 'CR', 'N', 'S');

PROMPT
PROMPT ============================================================
PROMPT  Seed data loaded.
PROMPT    4 merchants  (MERCHANT_RISK)
PROMPT    5 accounts   (ACCOUNT_MASTER)
PROMPT    4 profiles   (CUST_PROFILE)
PROMPT    1 watchlist  (WATCHLIST)
PROMPT   10 velocity   (TXN_QUEUE — 5 per account, TXN_TS=now)
PROMPT ============================================================
PROMPT

COMMIT;
