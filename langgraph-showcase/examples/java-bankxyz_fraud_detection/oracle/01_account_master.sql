-- ============================================================================
-- 01_account_master.sql
-- BankXYZ Fraud Detection — ACCOUNT_MASTER table
--
-- Dependencies: none (no foreign keys on this table)
-- Run after:    00_sequences.sql
-- ============================================================================

PROMPT ============================================================
PROMPT Creating table ACCOUNT_MASTER
PROMPT ============================================================

-- Drop existing table (idempotent)
-- ORA-00942 = table or view does not exist
BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE ACCOUNT_MASTER CASCADE CONSTRAINTS PURGE';
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN RAISE; END IF;
END;
/

-- ----------------------------------------------------------------------------
-- ACCOUNT_MASTER
-- Single source of truth for account status and daily transaction limits.
--
-- ACCT_STATUS state machine (mirrors AccountStatus enum in Java):
--   'A' = Active   — normal scoring applies
--   'F' = Frozen   — fraud score forced to 1.0
--   'C' = Closed   — fraud score forced to 1.0
-- ----------------------------------------------------------------------------
CREATE TABLE ACCOUNT_MASTER
(
    ACCT_NO             CHAR(10)            NOT NULL,
    CUST_ID             CHAR(9)             NOT NULL,
    CUST_FULL_NAME      VARCHAR2(50)        NOT NULL,

    -- State machine column: 'A'=Active, 'F'=Frozen, 'C'=Closed
    -- Business invariant: FROZEN or CLOSED forces composite score to 1.0
    ACCT_STATUS         CHAR(1)             DEFAULT 'A'   NOT NULL,

    -- 'CH'=Checking, 'SV'=Savings, 'CR'=Credit
    ACCT_TYPE           CHAR(2)             NOT NULL,

    -- ISO 3166-1 alpha-3 home country for geolocation scoring
    HOME_COUNTRY        CHAR(3)             DEFAULT 'GBR' NOT NULL,

    -- Pre-computed daily transaction count (updated by velocity batch)
    DAILY_TXN_COUNT     NUMBER(10)          DEFAULT 0     NOT NULL,

    -- Timestamp of last velocity calculation
    LAST_VELOCITY_TS    TIMESTAMP,

    -- Row last-modified timestamp
    LAST_UPDATE_TS      TIMESTAMP           DEFAULT CURRENT_TIMESTAMP NOT NULL,

    -- ---- Constraints ----
    CONSTRAINT PK_ACCT_MASTER
        PRIMARY KEY (ACCT_NO),

    CONSTRAINT CHK_ACCT_STATUS
        CHECK (ACCT_STATUS IN ('A', 'F', 'C')),

    CONSTRAINT CHK_ACCT_TYPE
        CHECK (ACCT_TYPE IN ('CH', 'SV', 'CR'))
);

-- ---- Column documentation ----
COMMENT ON TABLE ACCOUNT_MASTER IS
    'Single source of truth for account status and limits. Written by: core banking feed (nightly batch).';

COMMENT ON COLUMN ACCOUNT_MASTER.ACCT_NO IS
    'Account number — natural primary key. CHAR(10).';
COMMENT ON COLUMN ACCOUNT_MASTER.CUST_FULL_NAME IS
    'Customer full name — used by WatchlistService for OFAC/PEP name screening.';
COMMENT ON COLUMN ACCOUNT_MASTER.ACCT_STATUS IS
    'Account state machine: A=Active, F=Frozen, C=Closed. Frozen/Closed forces fraud score=1.0.';
COMMENT ON COLUMN ACCOUNT_MASTER.DAILY_TXN_COUNT IS
    'Pre-computed daily transaction count. Correct source for velocity (avoids N+1 anti-pattern).';

PROMPT Table ACCOUNT_MASTER created.
COMMIT;
