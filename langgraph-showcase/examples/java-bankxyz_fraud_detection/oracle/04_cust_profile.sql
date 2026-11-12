-- ============================================================================
-- 04_cust_profile.sql
-- BankXYZ Fraud Detection — CUST_PROFILE table
--
-- Purpose:
--   Pre-aggregated customer behaviour profile computed from 90 days of
--   transaction history. Refreshed nightly to avoid the N+1 anti-pattern
--   of recalculating from raw history on every scoring call.
--
-- Dependencies: none (ACCT_NO is not FK-constrained here — profile may
--               exist before ACCOUNT_MASTER row in some feed sequences)
-- Run after:    00_sequences.sql
-- ============================================================================

PROMPT ============================================================
PROMPT Creating table CUST_PROFILE
PROMPT ============================================================

BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE CUST_PROFILE CASCADE CONSTRAINTS PURGE';
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN RAISE; END IF;
END;
/

-- ----------------------------------------------------------------------------
-- CUST_PROFILE
-- Pre-computed customer behaviour profile.
--
-- CustomerProfileService uses this table to run three deviation checks:
--   1. Amount deviation  — TXN_AMOUNT vs AVG_TXN_AMOUNT / MAX_TXN_AMOUNT
--   2. Geolocation       — TXN_COUNTRY vs USUAL_COUNTRY
--   3. Time-of-day       — current hour vs USUAL_HR_START / USUAL_HR_END
--
-- If no profile row exists for ACCT_NO, the service defaults score = 0.3000.
--
-- USUAL_HR_START / USUAL_HR_END are in 24-hour local time (0–23).
-- Default window 07:00–22:00 covers typical UK retail banking hours.
-- ----------------------------------------------------------------------------
CREATE TABLE CUST_PROFILE
(
    ACCT_NO             CHAR(10)            NOT NULL,

    -- Statistical baseline computed from 90-day history
    AVG_TXN_AMOUNT      NUMBER(15, 2)       DEFAULT 0     NOT NULL,
    MAX_TXN_AMOUNT      NUMBER(15, 2)       DEFAULT 0     NOT NULL,

    -- Most frequent transaction country (ISO 3166-1 alpha-3)
    USUAL_COUNTRY       CHAR(3)             DEFAULT 'GBR' NOT NULL,

    -- Most frequent channel (space-padded to 8 chars)
    USUAL_CHANNEL       CHAR(8)             DEFAULT 'UNKNOWN ' NOT NULL,

    -- Usual activity window (24-hour clock, inclusive bounds)
    -- Transactions outside this window add 0.20 to profile deviation score
    USUAL_HR_START      NUMBER(2)           DEFAULT 7     NOT NULL,
    USUAL_HR_END        NUMBER(2)           DEFAULT 22    NOT NULL,

    -- Date the profile was last computed (nightly batch)
    PROFILE_DATE        DATE                DEFAULT SYSDATE NOT NULL,

    LAST_UPDATE_TS      TIMESTAMP           DEFAULT CURRENT_TIMESTAMP NOT NULL,

    -- ---- Constraints ----
    CONSTRAINT PK_CUST_PROFILE
        PRIMARY KEY (ACCT_NO),

    CONSTRAINT CHK_PROFILE_HOURS
        CHECK (USUAL_HR_START BETWEEN 0 AND 23
           AND USUAL_HR_END   BETWEEN 0 AND 23
           AND USUAL_HR_END   >= USUAL_HR_START),

    CONSTRAINT CHK_PROFILE_AMOUNTS
        CHECK (AVG_TXN_AMOUNT >= 0 AND MAX_TXN_AMOUNT >= 0)
);

-- ---- Column documentation ----
COMMENT ON TABLE CUST_PROFILE IS
    'Pre-computed customer behaviour profile (90-day window). Refreshed nightly. Read by CustomerProfileService for signal 4 (weight=0.20). If absent, score defaults to 0.30.';

COMMENT ON COLUMN CUST_PROFILE.AVG_TXN_AMOUNT IS
    'Average transaction amount over 90-day window. NUMBER(15,2).';
COMMENT ON COLUMN CUST_PROFILE.MAX_TXN_AMOUNT IS
    'Maximum transaction amount over 90-day window. Threshold for amount deviation check.';
COMMENT ON COLUMN CUST_PROFILE.USUAL_COUNTRY IS
    'Most frequent transaction country. Cross-border deviation adds 0.30 to profile score.';
COMMENT ON COLUMN CUST_PROFILE.USUAL_HR_START IS
    'Start of typical active hours (0-23). Transactions before this hour add 0.20 to profile score.';
COMMENT ON COLUMN CUST_PROFILE.USUAL_HR_END IS
    'End of typical active hours (0-23). Transactions after this hour add 0.20 to profile score.';

PROMPT Table CUST_PROFILE created.
COMMIT;
