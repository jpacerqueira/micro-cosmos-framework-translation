-- ============================================================================
-- 02_txn_queue.sql
-- BankXYZ Fraud Detection — TXN_QUEUE table
--
-- Dependencies: ACCOUNT_MASTER (FK constraint)
-- Run after:    01_account_master.sql
-- ============================================================================

PROMPT ============================================================
PROMPT Creating table TXN_QUEUE
PROMPT ============================================================

BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE TXN_QUEUE CASCADE CONSTRAINTS PURGE';
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN RAISE; END IF;
END;
/

-- ----------------------------------------------------------------------------
-- TXN_QUEUE
-- Staging table for transactions awaiting fraud scoring.
--
-- TXN_STATUS lifecycle:
--   'P' = Pending — awaiting fraud scoring (picked up by batch / real-time)
--   'S' = Scored  — fraud score has been computed; stamped with PROC_TS
--   'E' = Error   — scoring failed; requires manual investigation
--
-- CHANNEL values (fixed-length, space-padded):
--   'ATM     '   ATM withdrawal or deposit
--   'ONLINE  '   Internet banking or mobile
--   'BRANCH  '   Over-the-counter
--   'CHIPPIN '   Chip and PIN card-present — profile check skipped (BAU-2021-09)
--
-- CNP_FLAG: 'Y' = card-not-present (adds 0.10 uplift on profile score)
-- ----------------------------------------------------------------------------
CREATE TABLE TXN_QUEUE
(
    TXN_ID              CHAR(16)            NOT NULL,
    ACCT_NO             CHAR(10)            NOT NULL,

    -- All monetary amounts stored as NUMBER(15,2). Never use FLOAT or BINARY_FLOAT.
    TXN_AMOUNT          NUMBER(15, 2)       NOT NULL,

    MERCHANT_CODE       CHAR(8),
    CHANNEL             CHAR(8)             DEFAULT 'UNKNOWN' NOT NULL,
    TXN_COUNTRY         CHAR(3)             DEFAULT 'GBR'     NOT NULL,
    CARD_LAST4          CHAR(4),

    -- 'DB'=Debit, 'CR'=Credit, 'PP'=Prepaid
    CARD_TYPE           CHAR(2),

    -- Card-not-present flag
    CNP_FLAG            CHAR(1)             DEFAULT 'N'       NOT NULL,

    -- Row status — drives batch and real-time processing
    TXN_STATUS          CHAR(1)             DEFAULT 'P'       NOT NULL,

    -- Transaction creation timestamp
    TXN_TS              TIMESTAMP           DEFAULT CURRENT_TIMESTAMP NOT NULL,

    -- Populated by TransactionMonitorService.stampProcessed() after scoring
    PROC_TS             TIMESTAMP,

    -- Batch run date (YYYY-MM-DD) populated by nightly batch
    BATCH_DATE          CHAR(10),

    -- ---- Constraints ----
    CONSTRAINT PK_TXN_QUEUE
        PRIMARY KEY (TXN_ID),

    CONSTRAINT FK_TXN_ACCT
        FOREIGN KEY (ACCT_NO)
        REFERENCES ACCOUNT_MASTER (ACCT_NO),

    CONSTRAINT CHK_TXN_STATUS
        CHECK (TXN_STATUS IN ('P', 'S', 'E')),

    CONSTRAINT CHK_CNP_FLAG
        CHECK (CNP_FLAG IN ('Y', 'N')),

    CONSTRAINT CHK_CARD_TYPE
        CHECK (CARD_TYPE IN ('DB', 'CR', 'PP') OR CARD_TYPE IS NULL),

    CONSTRAINT CHK_TXN_AMOUNT
        CHECK (TXN_AMOUNT > 0)
);

-- ---- Indexes ----
-- IX_TXN_STATUS: used by TransactionMonitorService to fetch pending transactions
-- (SELECT ... WHERE TXN_STATUS = 'P' ORDER BY TXN_TS)
CREATE INDEX IX_TXN_STATUS
    ON TXN_QUEUE (TXN_STATUS, TXN_TS);

-- IX_TXN_ACCT: used by VelocityCheckService 24-hour window query
-- (SELECT COUNT(*) ... WHERE ACCT_NO = ? AND TXN_TS > ?)
CREATE INDEX IX_TXN_ACCT
    ON TXN_QUEUE (ACCT_NO, TXN_TS);

-- ---- Column documentation ----
COMMENT ON TABLE TXN_QUEUE IS
    'Staging table for transactions awaiting fraud scoring. TXN_STATUS=P picked up by batch (nightly) and real-time (per authorisation).';

COMMENT ON COLUMN TXN_QUEUE.TXN_AMOUNT IS
    'Transaction amount. NUMBER(15,2). Never store as FLOAT.';
COMMENT ON COLUMN TXN_QUEUE.CHANNEL IS
    'Fixed-length channel code. CHIPPIN causes profile weight=0 in FraudRulesService (BAU-2021-09).';
COMMENT ON COLUMN TXN_QUEUE.CNP_FLAG IS
    'Card-not-present flag. Y adds 0.10 uplift on CustomerProfileService score.';
COMMENT ON COLUMN TXN_QUEUE.TXN_STATUS IS
    'Lifecycle state: P=Pending (unscored), S=Scored, E=Error. Batch reads P rows only.';
COMMENT ON COLUMN TXN_QUEUE.PROC_TS IS
    'Stamped by TransactionMonitorService.stampProcessed() after successful scoring.';

PROMPT Table TXN_QUEUE created.
PROMPT Indexes IX_TXN_STATUS, IX_TXN_ACCT created.
COMMIT;
