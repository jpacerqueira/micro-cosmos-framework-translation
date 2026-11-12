-- ----------------------------------------------------------------
-- FDDB -- NatWest Fraud Detection Database Schema
-- IBM Db2 for z/OS  |  Bind plan: FDPLAN01
-- Schema owner: FDADMIN
-- Last updated: 2024-01-15  |  Change ref: CHG-2024-0003
-- ----------------------------------------------------------------

-- ----------------------------------------------------------------
-- SEQUENCES
-- ----------------------------------------------------------------

CREATE SEQUENCE FDDB.FD_SEQ
    AS INTEGER
    START WITH 1
    INCREMENT BY 1
    NO CYCLE
    CACHE 20;

CREATE SEQUENCE FDDB.AUDIT_SEQ
    AS INTEGER
    START WITH 1
    INCREMENT BY 1
    NO CYCLE
    CACHE 20;

-- ----------------------------------------------------------------
-- ACCOUNT_MASTER
-- Single source of truth for account status and limits.
-- Written by: core banking feed (nightly batch FDBATCH05)
-- Read by:    FDRULES, FDCUSTPF, FDWATCHL, FDRTCHK
-- ----------------------------------------------------------------

CREATE TABLE FDDB.ACCOUNT_MASTER (
    ACCT_NO             CHAR(10)         NOT NULL,
    CUST_ID             CHAR(9)          NOT NULL,
    CUST_FULL_NAME      VARCHAR(50)      NOT NULL,
    ACCT_STATUS         CHAR(1)          NOT NULL DEFAULT 'A',
        -- 'A' = Active  'F' = Frozen  'C' = Closed
    ACCT_TYPE           CHAR(2)          NOT NULL,
        -- 'CH' = Checking  'SV' = Savings  'CR' = Credit
    HOME_COUNTRY        CHAR(3)          NOT NULL DEFAULT 'GBR',
    DAILY_TXN_COUNT     INTEGER          NOT NULL DEFAULT 0,
    LAST_VELOCITY_TS    TIMESTAMP,
    LAST_UPDATE_TS      TIMESTAMP        NOT NULL WITH DEFAULT,
    CONSTRAINT PK_ACCT_MASTER PRIMARY KEY (ACCT_NO)
) IN FDDB.ACCTSP;

-- ----------------------------------------------------------------
-- TXN_QUEUE
-- Staging table for transactions awaiting fraud scoring.
-- Written by: authorisation feed and card scheme gateway
-- Read by:    FDTXNMON (batch), FDRTCHK (real-time), FDVELCHK
-- ----------------------------------------------------------------

CREATE TABLE FDDB.TXN_QUEUE (
    TXN_ID              CHAR(16)         NOT NULL,
    ACCT_NO             CHAR(10)         NOT NULL,
    TXN_AMOUNT          DECIMAL(15,2)    NOT NULL,
    MERCHANT_CODE       CHAR(8),
    CHANNEL             CHAR(8)          NOT NULL DEFAULT 'UNKNOWN',
        -- 'ATM     ' | 'ONLINE  ' | 'BRANCH  ' | 'CHIPPIN '
    TXN_COUNTRY         CHAR(3)          NOT NULL DEFAULT 'GBR',
    CARD_LAST4          CHAR(4),
    CARD_TYPE           CHAR(2),
        -- 'DB' = Debit  'CR' = Credit  'PP' = Prepaid
    CNP_FLAG            CHAR(1)          NOT NULL DEFAULT 'N',
        -- 'Y' = Card-not-present  'N' = Card-present
    TXN_STATUS          CHAR(1)          NOT NULL DEFAULT 'P',
        -- 'P' = Pending  'S' = Scored  'E' = Error
    TXN_TS              TIMESTAMP        NOT NULL WITH DEFAULT,
    PROC_TS             TIMESTAMP,
    BATCH_DATE          CHAR(10),
    CONSTRAINT PK_TXN_QUEUE PRIMARY KEY (TXN_ID)
) IN FDDB.TXNSP;

CREATE INDEX FDDB.IX_TXN_STATUS
    ON FDDB.TXN_QUEUE (TXN_STATUS, TXN_TS);

CREATE INDEX FDDB.IX_TXN_ACCT
    ON FDDB.TXN_QUEUE (ACCT_NO, TXN_TS);

-- ----------------------------------------------------------------
-- MERCHANT_RISK
-- Risk classification for merchant codes.
-- Maintained by the fraud operations team via FDMAINT (batch).
-- Read by:    FDRULES (SCORE-BY-MERCHANT)
-- ----------------------------------------------------------------

CREATE TABLE FDDB.MERCHANT_RISK (
    MERCHANT_CODE       CHAR(8)          NOT NULL,
    MERCHANT_NAME       VARCHAR(80),
    BLOCKED_FLAG        CHAR(1)          NOT NULL DEFAULT 'N',
    RISK_BAND           CHAR(4)          NOT NULL DEFAULT 'LOW ',
        -- 'HIGH' | 'MED ' | 'LOW '
    BLOCK_REASON        VARCHAR(80),
    EFFECTIVE_FROM      DATE             NOT NULL WITH DEFAULT,
    EFFECTIVE_TO        DATE,
    LAST_UPDATE_TS      TIMESTAMP        NOT NULL WITH DEFAULT,
    CONSTRAINT PK_MERCHANT_RISK PRIMARY KEY (MERCHANT_CODE)
) IN FDDB.MCHNTSP;

-- ----------------------------------------------------------------
-- FRAUD_ALERTS
-- Every transaction that scores above the fraud threshold.
-- Written by: FDALERT
-- Read by:    case management system (CASEDB feed), FDARCHIVE
-- ----------------------------------------------------------------

CREATE TABLE FDDB.FRAUD_ALERTS (
    ALERT_ID            INTEGER          NOT NULL,
    TXN_ID              CHAR(16)         NOT NULL,
    ACCT_NO             CHAR(10)         NOT NULL,
    TXN_AMOUNT          DECIMAL(15,2)    NOT NULL,
    FRAUD_SCORE         DECIMAL(7,4)     NOT NULL,
    ALERT_STATUS        CHAR(10)         NOT NULL DEFAULT 'PENDING   ',
        -- 'PENDING   ' | 'REVIEWED  ' | 'CLOSED    ' | 'ESCALATED '
    ANALYST_ID          CHAR(8),
    RESOLUTION_NOTES    VARCHAR(255),
    ARCHIVED_FLAG       CHAR(1)          NOT NULL DEFAULT 'N',
    ARCHIVE_TS          TIMESTAMP,
    CREATED_TS          TIMESTAMP        NOT NULL WITH DEFAULT,
    LAST_UPDATE_TS      TIMESTAMP        NOT NULL WITH DEFAULT,
    CONSTRAINT PK_FRAUD_ALERTS PRIMARY KEY (ALERT_ID),
    CONSTRAINT FK_ALERT_TXN FOREIGN KEY (TXN_ID)
        REFERENCES FDDB.TXN_QUEUE (TXN_ID)
) IN FDDB.ALERTSP;

-- ----------------------------------------------------------------
-- CUST_PROFILE
-- Pre-computed customer behaviour profile used by FDCUSTPF.
-- Refreshed nightly by FDBATCH06 from 90 days of transaction history.
-- Avoids the N+1 pattern in BUILD-PROFILE-FROM-HISTORY (FDCUSTPF).
-- ----------------------------------------------------------------

CREATE TABLE FDDB.CUST_PROFILE (
    ACCT_NO             CHAR(10)         NOT NULL,
    AVG_TXN_AMOUNT      DECIMAL(15,2)    NOT NULL DEFAULT 0,
    MAX_TXN_AMOUNT      DECIMAL(15,2)    NOT NULL DEFAULT 0,
    USUAL_COUNTRY       CHAR(3)          NOT NULL DEFAULT 'GBR',
    USUAL_CHANNEL       CHAR(8)          NOT NULL DEFAULT 'UNKNOWN ',
    USUAL_HR_START      SMALLINT         NOT NULL DEFAULT 7,
    USUAL_HR_END        SMALLINT         NOT NULL DEFAULT 22,
    PROFILE_DATE        DATE             NOT NULL WITH DEFAULT,
    LAST_UPDATE_TS      TIMESTAMP        NOT NULL WITH DEFAULT,
    CONSTRAINT PK_CUST_PROFILE PRIMARY KEY (ACCT_NO)
) IN FDDB.PROFSP;

-- ----------------------------------------------------------------
-- WATCHLIST
-- Consolidated sanctions and fraud watchlist.
-- Sources: OFAC (daily feed), PEP list (weekly feed),
--          internal NatWest fraud operations (ad hoc).
-- Replaced the VSAM KSDS file FDWTCHFL in 2020 (CHG-2020-0112).
-- ----------------------------------------------------------------

CREATE TABLE FDDB.WATCHLIST (
    WATCHLIST_ID        INTEGER          NOT NULL GENERATED ALWAYS AS IDENTITY,
    LIST_TYPE           CHAR(10)         NOT NULL,
        -- 'OFAC      ' | 'PEP       ' | 'INTERNAL  '
    MATCH_NAME          VARCHAR(100),
    MATCH_ACCT          CHAR(10),
    LIST_STATUS         CHAR(6)          NOT NULL DEFAULT 'ACTIVE',
    REF_NUMBER          CHAR(20),
    ADDED_BY            CHAR(8)          NOT NULL DEFAULT 'SYSTEM',
    EFFECTIVE_FROM      DATE             NOT NULL WITH DEFAULT,
    EFFECTIVE_TO        DATE,
    CONSTRAINT PK_WATCHLIST PRIMARY KEY (WATCHLIST_ID)
) IN FDDB.WATCHSP;

CREATE INDEX FDDB.IX_WL_TYPE_NAME
    ON FDDB.WATCHLIST (LIST_TYPE, MATCH_NAME, LIST_STATUS);

CREATE INDEX FDDB.IX_WL_ACCT
    ON FDDB.WATCHLIST (MATCH_ACCT, LIST_TYPE, LIST_STATUS);

-- ----------------------------------------------------------------
-- WATCHLIST_HITS
-- Audit log of every watchlist match, regardless of outcome.
-- Written by: FDWATCHL (LOG-WATCHLIST-HIT paragraph)
-- ----------------------------------------------------------------

CREATE TABLE FDDB.WATCHLIST_HITS (
    HIT_ID              INTEGER          NOT NULL GENERATED ALWAYS AS IDENTITY,
    ACCT_NO             CHAR(10)         NOT NULL,
    TXN_ID              CHAR(16)         NOT NULL,
    HIT_TYPE            VARCHAR(40)      NOT NULL,
    HIT_REASON          VARCHAR(80)      NOT NULL,
    HIT_TS              TIMESTAMP        NOT NULL WITH DEFAULT,
    CONSTRAINT PK_WL_HITS PRIMARY KEY (HIT_ID)
) IN FDDB.WATCHSP;

-- ----------------------------------------------------------------
-- MQ_FAILURE_LOG
-- Records failures when FDNOTIFY cannot put to FRAUD.ALERT.QUEUE.
-- Operations team monitors this daily for MQ infrastructure issues.
-- ----------------------------------------------------------------

CREATE TABLE FDDB.MQ_FAILURE_LOG (
    FAIL_ID             INTEGER          NOT NULL GENERATED ALWAYS AS IDENTITY,
    TXN_ID              CHAR(16)         NOT NULL,
    ACCT_NO             CHAR(10)         NOT NULL,
    REASON_CODE         INTEGER          NOT NULL DEFAULT 0,
    FAILED_TS           TIMESTAMP        NOT NULL WITH DEFAULT,
    CONSTRAINT PK_MQ_FAIL PRIMARY KEY (FAIL_ID)
) IN FDDB.LOGSP;

-- ----------------------------------------------------------------
-- SLA_BREACH_LOG
-- Records every real-time check (FDRTCHK) that exceeded 180ms.
-- Reviewed during incident post-mortems and capacity planning.
-- ----------------------------------------------------------------

CREATE TABLE FDDB.SLA_BREACH_LOG (
    BREACH_ID           INTEGER          NOT NULL GENERATED ALWAYS AS IDENTITY,
    TXN_ID              CHAR(16)         NOT NULL,
    ACCT_NO             CHAR(10)         NOT NULL,
    ELAPSED_MS          INTEGER          NOT NULL,
    BREACH_TS           TIMESTAMP        NOT NULL WITH DEFAULT,
    CONSTRAINT PK_SLA_BREACH PRIMARY KEY (BREACH_ID)
) IN FDDB.LOGSP;
