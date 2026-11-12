-- ============================================================================
-- BankXYZ Fraud Detection — Oracle 10g DDL
-- ============================================================================

-- ----------------------------------------------------------------------------
-- SEQUENCES
-- FD_SEQ        → FRAUD_ALERTS.ALERT_ID
-- AUDIT_SEQ     → reserved for audit trail
-- WATCHLIST_SEQ, WL_HITS_SEQ, MQ_FAIL_SEQ, SLA_BREACH_SEQ → identity columns
-- ----------------------------------------------------------------------------

CREATE SEQUENCE FD_SEQ
    START WITH 1 INCREMENT BY 1 NOCYCLE CACHE 20;

CREATE SEQUENCE AUDIT_SEQ
    START WITH 1 INCREMENT BY 1 NOCYCLE CACHE 20;

CREATE SEQUENCE WATCHLIST_SEQ
    START WITH 1 INCREMENT BY 1 NOCYCLE CACHE 20;

CREATE SEQUENCE WL_HITS_SEQ
    START WITH 1 INCREMENT BY 1 NOCYCLE CACHE 20;

CREATE SEQUENCE MQ_FAIL_SEQ
    START WITH 1 INCREMENT BY 1 NOCYCLE CACHE 20;

CREATE SEQUENCE SLA_BREACH_SEQ
    START WITH 1 INCREMENT BY 1 NOCYCLE CACHE 20;

-- ----------------------------------------------------------------------------
-- ACCOUNT_MASTER
-- Source: core banking feed (nightly batch)
-- ACCT_STATUS values: 'A'=Active, 'F'=Frozen, 'C'=Closed (state machine)
-- ----------------------------------------------------------------------------

CREATE TABLE ACCOUNT_MASTER (
    ACCT_NO             CHAR(10)         NOT NULL,
    CUST_ID             CHAR(9)          NOT NULL,
    CUST_FULL_NAME      VARCHAR2(50)     NOT NULL,
    ACCT_STATUS         CHAR(1)          DEFAULT 'A' NOT NULL,
    ACCT_TYPE           CHAR(2)          NOT NULL,
    HOME_COUNTRY        CHAR(3)          DEFAULT 'GBR' NOT NULL,
    DAILY_TXN_COUNT     NUMBER(10)       DEFAULT 0 NOT NULL,
    LAST_VELOCITY_TS    TIMESTAMP,
    LAST_UPDATE_TS      TIMESTAMP        DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT PK_ACCT_MASTER PRIMARY KEY (ACCT_NO),
    CONSTRAINT CHK_ACCT_STATUS CHECK (ACCT_STATUS IN ('A','F','C'))
);

-- ----------------------------------------------------------------------------
-- TXN_QUEUE
-- Staging table for transactions awaiting fraud scoring.
-- TXN_STATUS: 'P'=Pending, 'S'=Scored, 'E'=Error
-- CHANNEL:    'ATM     ', 'ONLINE  ', 'BRANCH  ', 'CHIPPIN '
-- ----------------------------------------------------------------------------

CREATE TABLE TXN_QUEUE (
    TXN_ID              CHAR(16)         NOT NULL,
    ACCT_NO             CHAR(10)         NOT NULL,
    TXN_AMOUNT          NUMBER(15,2)     NOT NULL,
    MERCHANT_CODE       CHAR(8),
    CHANNEL             CHAR(8)          DEFAULT 'UNKNOWN' NOT NULL,
    TXN_COUNTRY         CHAR(3)          DEFAULT 'GBR' NOT NULL,
    CARD_LAST4          CHAR(4),
    CARD_TYPE           CHAR(2),
    CNP_FLAG            CHAR(1)          DEFAULT 'N' NOT NULL,
    TXN_STATUS          CHAR(1)          DEFAULT 'P' NOT NULL,
    TXN_TS              TIMESTAMP        DEFAULT CURRENT_TIMESTAMP NOT NULL,
    PROC_TS             TIMESTAMP,
    BATCH_DATE          CHAR(10),
    CONSTRAINT PK_TXN_QUEUE PRIMARY KEY (TXN_ID),
    CONSTRAINT FK_TXN_ACCT FOREIGN KEY (ACCT_NO)
        REFERENCES ACCOUNT_MASTER (ACCT_NO),
    CONSTRAINT CHK_TXN_STATUS CHECK (TXN_STATUS IN ('P','S','E')),
    CONSTRAINT CHK_CNP_FLAG CHECK (CNP_FLAG IN ('Y','N'))
);

CREATE INDEX IX_TXN_STATUS ON TXN_QUEUE (TXN_STATUS, TXN_TS);
CREATE INDEX IX_TXN_ACCT   ON TXN_QUEUE (ACCT_NO, TXN_TS);

-- ----------------------------------------------------------------------------
-- MERCHANT_RISK
-- Read by: FraudRulesService (SCORE-BY-MERCHANT signal)
-- RISK_BAND: 'HIGH', 'MED ', 'LOW '
-- ----------------------------------------------------------------------------

CREATE TABLE MERCHANT_RISK (
    MERCHANT_CODE       CHAR(8)          NOT NULL,
    MERCHANT_NAME       VARCHAR2(80),
    BLOCKED_FLAG        CHAR(1)          DEFAULT 'N' NOT NULL,
    RISK_BAND           CHAR(4)          DEFAULT 'LOW ' NOT NULL,
    BLOCK_REASON        VARCHAR2(80),
    EFFECTIVE_FROM      DATE             DEFAULT SYSDATE NOT NULL,
    EFFECTIVE_TO        DATE,
    LAST_UPDATE_TS      TIMESTAMP        DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT PK_MERCHANT_RISK PRIMARY KEY (MERCHANT_CODE),
    CONSTRAINT CHK_BLOCKED_FLAG CHECK (BLOCKED_FLAG IN ('Y','N')),
    CONSTRAINT CHK_RISK_BAND CHECK (RISK_BAND IN ('HIGH','MED ','LOW '))
);

-- ----------------------------------------------------------------------------
-- FRAUD_ALERTS
-- Written by: AlertWriterService
-- ALERT_STATUS state machine: PENDING → REVIEWED → CLOSED | ESCALATED
-- ----------------------------------------------------------------------------

CREATE TABLE FRAUD_ALERTS (
    ALERT_ID            NUMBER(10)       NOT NULL,
    TXN_ID              CHAR(16)         NOT NULL,
    ACCT_NO             CHAR(10)         NOT NULL,
    TXN_AMOUNT          NUMBER(15,2)     NOT NULL,
    FRAUD_SCORE         NUMBER(7,4)      NOT NULL,
    ALERT_STATUS        VARCHAR2(10)     DEFAULT 'PENDING' NOT NULL,
    ANALYST_ID          CHAR(8),
    RESOLUTION_NOTES    VARCHAR2(255),
    ARCHIVED_FLAG       CHAR(1)          DEFAULT 'N' NOT NULL,
    ARCHIVE_TS          TIMESTAMP,
    CREATED_TS          TIMESTAMP        DEFAULT CURRENT_TIMESTAMP NOT NULL,
    LAST_UPDATE_TS      TIMESTAMP        DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT PK_FRAUD_ALERTS PRIMARY KEY (ALERT_ID),
    CONSTRAINT FK_ALERT_TXN FOREIGN KEY (TXN_ID)
        REFERENCES TXN_QUEUE (TXN_ID),
    CONSTRAINT CHK_ALERT_STATUS
        CHECK (ALERT_STATUS IN ('PENDING','REVIEWED','CLOSED','ESCALATED'))
);

-- ----------------------------------------------------------------------------
-- CUST_PROFILE
-- Pre-computed customer behaviour profile (refreshed nightly).
-- ----------------------------------------------------------------------------

CREATE TABLE CUST_PROFILE (
    ACCT_NO             CHAR(10)         NOT NULL,
    AVG_TXN_AMOUNT      NUMBER(15,2)     DEFAULT 0 NOT NULL,
    MAX_TXN_AMOUNT      NUMBER(15,2)     DEFAULT 0 NOT NULL,
    USUAL_COUNTRY       CHAR(3)          DEFAULT 'GBR' NOT NULL,
    USUAL_CHANNEL       CHAR(8)          DEFAULT 'UNKNOWN ' NOT NULL,
    USUAL_HR_START      NUMBER(5)        DEFAULT 7 NOT NULL,
    USUAL_HR_END        NUMBER(5)        DEFAULT 22 NOT NULL,
    PROFILE_DATE        DATE             DEFAULT SYSDATE NOT NULL,
    LAST_UPDATE_TS      TIMESTAMP        DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT PK_CUST_PROFILE PRIMARY KEY (ACCT_NO)
);

-- ----------------------------------------------------------------------------
-- WATCHLIST
-- Sources: OFAC (daily), PEP (weekly), internal BankXYZ fraud operations.
-- LIST_TYPE: 'OFAC', 'PEP', 'INTERNAL'
-- ----------------------------------------------------------------------------

CREATE TABLE WATCHLIST (
    WATCHLIST_ID        NUMBER(10)       NOT NULL,
    LIST_TYPE           VARCHAR2(10)     NOT NULL,
    MATCH_NAME          VARCHAR2(100),
    MATCH_ACCT          CHAR(10),
    LIST_STATUS         VARCHAR2(6)      DEFAULT 'ACTIVE' NOT NULL,
    REF_NUMBER          CHAR(20),
    ADDED_BY            CHAR(8)          DEFAULT 'SYSTEM' NOT NULL,
    EFFECTIVE_FROM      DATE             DEFAULT SYSDATE NOT NULL,
    EFFECTIVE_TO        DATE,
    CONSTRAINT PK_WATCHLIST PRIMARY KEY (WATCHLIST_ID),
    CONSTRAINT CHK_LIST_TYPE CHECK (LIST_TYPE IN ('OFAC','PEP','INTERNAL')),
    CONSTRAINT CHK_LIST_STATUS CHECK (LIST_STATUS IN ('ACTIVE','EXPIRED'))
);

CREATE INDEX IX_WL_TYPE_NAME ON WATCHLIST (LIST_TYPE, MATCH_NAME, LIST_STATUS);
CREATE INDEX IX_WL_ACCT      ON WATCHLIST (MATCH_ACCT, LIST_TYPE, LIST_STATUS);

-- Trigger to auto-populate WATCHLIST_ID from sequence (Oracle 10g — no IDENTITY)
CREATE OR REPLACE TRIGGER TRG_WATCHLIST_ID
BEFORE INSERT ON WATCHLIST
FOR EACH ROW
WHEN (NEW.WATCHLIST_ID IS NULL)
BEGIN
    SELECT WATCHLIST_SEQ.NEXTVAL INTO :NEW.WATCHLIST_ID FROM DUAL;
END;
/

-- ----------------------------------------------------------------------------
-- WATCHLIST_HITS
-- Audit log of every watchlist match. Written by: WatchlistService.
-- ----------------------------------------------------------------------------

CREATE TABLE WATCHLIST_HITS (
    HIT_ID              NUMBER(10)       NOT NULL,
    ACCT_NO             CHAR(10)         NOT NULL,
    TXN_ID              CHAR(16)         NOT NULL,
    HIT_TYPE            VARCHAR2(40)     NOT NULL,
    HIT_REASON          VARCHAR2(80)     NOT NULL,
    HIT_TS              TIMESTAMP        DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT PK_WL_HITS PRIMARY KEY (HIT_ID)
);

CREATE OR REPLACE TRIGGER TRG_WL_HITS_ID
BEFORE INSERT ON WATCHLIST_HITS
FOR EACH ROW
WHEN (NEW.HIT_ID IS NULL)
BEGIN
    SELECT WL_HITS_SEQ.NEXTVAL INTO :NEW.HIT_ID FROM DUAL;
END;
/

-- ----------------------------------------------------------------------------
-- MQ_FAILURE_LOG
-- Written by: MqNotificationService on failed queue puts.
-- Operations team monitors daily.
-- ----------------------------------------------------------------------------

CREATE TABLE MQ_FAILURE_LOG (
    FAIL_ID             NUMBER(10)       NOT NULL,
    TXN_ID              CHAR(16)         NOT NULL,
    ACCT_NO             CHAR(10)         NOT NULL,
    REASON_CODE         NUMBER(10)       DEFAULT 0 NOT NULL,
    FAILED_TS           TIMESTAMP        DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT PK_MQ_FAIL PRIMARY KEY (FAIL_ID)
);

CREATE OR REPLACE TRIGGER TRG_MQ_FAIL_ID
BEFORE INSERT ON MQ_FAILURE_LOG
FOR EACH ROW
WHEN (NEW.FAIL_ID IS NULL)
BEGIN
    SELECT MQ_FAIL_SEQ.NEXTVAL INTO :NEW.FAIL_ID FROM DUAL;
END;
/

-- ----------------------------------------------------------------------------
-- SLA_BREACH_LOG
-- Written by: RealtimeCheckController when response > 180ms.
-- Reviewed during incident post-mortems and capacity planning.
-- ----------------------------------------------------------------------------

CREATE TABLE SLA_BREACH_LOG (
    BREACH_ID           NUMBER(10)       NOT NULL,
    TXN_ID              CHAR(16)         NOT NULL,
    ACCT_NO             CHAR(10)         NOT NULL,
    ELAPSED_MS          NUMBER(10)       NOT NULL,
    BREACH_TS           TIMESTAMP        DEFAULT CURRENT_TIMESTAMP NOT NULL,
    CONSTRAINT PK_SLA_BREACH PRIMARY KEY (BREACH_ID)
);

CREATE OR REPLACE TRIGGER TRG_SLA_BREACH_ID
BEFORE INSERT ON SLA_BREACH_LOG
FOR EACH ROW
WHEN (NEW.BREACH_ID IS NULL)
BEGIN
    SELECT SLA_BREACH_SEQ.NEXTVAL INTO :NEW.BREACH_ID FROM DUAL;
END;
/
