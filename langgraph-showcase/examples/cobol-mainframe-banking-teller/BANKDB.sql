-- BANKDB.sql  -  Db2 for z/OS DDL for the COBOL mainframe banking estate
-- Bind plan: BKPLAN01
-- Schema:    BANKDB
-- Tablespace names follow the BANKDB01..BANKDB04 convention.

-- --------------------------------------------------------------------
-- Account Master
-- Primary store for all account balances and daily withdrawal state.
-- BALANCE uses DECIMAL(15,2); the COBOL COMP-3 field HV-BALANCE maps
-- to this column directly via the static bind plan.
-- --------------------------------------------------------------------
CREATE TABLESPACE BANKDB01
    IN BANKDB
    SEGSIZE 4
    BUFFERPOOL BP0
    LOCKSIZE ROW;

CREATE TABLE BANKDB.ACCOUNT_MASTER (
    ACCT_NO          CHAR(10)        NOT NULL,
    ACCT_TYPE        CHAR(2)         NOT NULL,
    CUSTOMER_ID      CHAR(9)         NOT NULL,
    ACCT_STATUS      CHAR(1)         NOT NULL DEFAULT 'A',
    BALANCE          DECIMAL(15, 2)  NOT NULL DEFAULT 0.00,
    OVERDRAFT_LIMIT  DECIMAL(9, 2)   NOT NULL DEFAULT 0.00,
    DAILY_WD_LIMIT   DECIMAL(9, 2)   NOT NULL DEFAULT 5000.00,
    DAILY_WD_USED    DECIMAL(9, 2)   NOT NULL DEFAULT 0.00,
    LAST_UPDATE_TS   TIMESTAMP       NOT NULL WITH DEFAULT,
    CONSTRAINT PK_ACCOUNT PRIMARY KEY (ACCT_NO),
    CONSTRAINT CK_ACCT_TYPE
        CHECK (ACCT_TYPE IN ('CH', 'SV', 'LN')),
    CONSTRAINT CK_ACCT_STATUS
        CHECK (ACCT_STATUS IN ('A', 'F', 'C')),
    CONSTRAINT CK_BALANCE_GTE_OD
        CHECK (BALANCE >= (OVERDRAFT_LIMIT * -1))
) IN BANKDB.BANKDB01;

CREATE UNIQUE INDEX BANKDB.IX_ACCT_PK
    ON BANKDB.ACCOUNT_MASTER (ACCT_NO)
    CLUSTER;

CREATE INDEX BANKDB.IX_ACCT_CUST
    ON BANKDB.ACCOUNT_MASTER (CUSTOMER_ID);

-- --------------------------------------------------------------------
-- Transaction Register
-- Immutable ledger of every committed transaction.
-- Partitioned by TXN_DATE for archival efficiency.
-- --------------------------------------------------------------------
CREATE TABLESPACE BANKDB02
    IN BANKDB
    SEGSIZE 4
    BUFFERPOOL BP0
    LOCKSIZE ROW;

CREATE TABLE BANKDB.TRANSACTION_REGISTER (
    TXN_ID           INTEGER         NOT NULL GENERATED ALWAYS AS IDENTITY,
    TXN_DATE         DATE            NOT NULL,
    TXN_TIME         TIME            NOT NULL,
    TXN_TYPE         CHAR(4)         NOT NULL,
    ACCT_FROM        CHAR(10)        NOT NULL,
    ACCT_TO          CHAR(10),
    TXN_AMOUNT       DECIMAL(15, 2)  NOT NULL,
    TXN_REF          CHAR(16)        NOT NULL,
    TELLER_ID        CHAR(8)         NOT NULL,
    BRANCH_ID        CHAR(6)         NOT NULL,
    CHANNEL          CHAR(10)        NOT NULL DEFAULT 'TELLER',
    TXN_STATUS       CHAR(1)         NOT NULL DEFAULT 'C',
    REVERSAL_REF     CHAR(16),
    TXN_TIMESTAMP    TIMESTAMP       NOT NULL WITH DEFAULT,
    CONSTRAINT PK_TXN PRIMARY KEY (TXN_ID),
    CONSTRAINT CK_TXN_TYPE
        CHECK (TXN_TYPE IN ('DEPO', 'WITH', 'XFER', 'INQU')),
    CONSTRAINT CK_TXN_STATUS
        CHECK (TXN_STATUS IN ('C', 'F', 'R')),
    CONSTRAINT CK_TXN_AMOUNT_POS
        CHECK (TXN_AMOUNT > 0)
) IN BANKDB.BANKDB02;

CREATE INDEX BANKDB.IX_TXN_ACCT_DATE
    ON BANKDB.TRANSACTION_REGISTER (ACCT_FROM, TXN_DATE);

CREATE INDEX BANKDB.IX_TXN_REF
    ON BANKDB.TRANSACTION_REGISTER (TXN_REF);

-- Sequence used by BKTRXN to generate unique transaction references
CREATE SEQUENCE BANKDB.TXN_SEQ
    AS INTEGER
    START WITH 1
    INCREMENT BY 1
    NO CYCLE
    CACHE 20;

-- --------------------------------------------------------------------
-- Teller Session
-- Tracks active teller sessions for audit and concurrent-logon control.
-- --------------------------------------------------------------------
CREATE TABLESPACE BANKDB03
    IN BANKDB
    SEGSIZE 4
    BUFFERPOOL BP0
    LOCKSIZE ROW;

CREATE TABLE BANKDB.TELLER_SESSION (
    SESSION_ID       CHAR(16)        NOT NULL,
    TELLER_ID        CHAR(8)         NOT NULL,
    BRANCH_ID        CHAR(6)         NOT NULL,
    TERMINAL_ID      CHAR(4)         NOT NULL,
    SIGNON_TS        TIMESTAMP       NOT NULL WITH DEFAULT,
    SIGNOFF_TS       TIMESTAMP,
    SESSION_STATUS   CHAR(1)         NOT NULL DEFAULT 'A',
    CONSTRAINT PK_SESSION PRIMARY KEY (SESSION_ID),
    CONSTRAINT CK_SESSION_STATUS
        CHECK (SESSION_STATUS IN ('A', 'E'))
) IN BANKDB.BANKDB03;

CREATE INDEX BANKDB.IX_SESSION_TELLER
    ON BANKDB.TELLER_SESSION (TELLER_ID, SESSION_STATUS);

-- --------------------------------------------------------------------
-- Audit Log
-- Append-only table. Every committed transaction writes one row here
-- via BKAUDIT. The legacy VSAM KSDS (BKAUDFL) wrote the same data
-- until Q3-2019; that path is now dead code in BKAUDIT.cbl.
-- --------------------------------------------------------------------
CREATE TABLESPACE BANKDB04
    IN BANKDB
    SEGSIZE 4
    BUFFERPOOL BP0
    LOCKSIZE ROW;

CREATE TABLE BANKDB.AUDIT_LOG (
    AUD_ID           INTEGER         NOT NULL GENERATED ALWAYS AS IDENTITY,
    AUD_TXN_REF      CHAR(16)        NOT NULL,
    EVENT_TYPE       CHAR(20)        NOT NULL,
    EVENT_TS         TIMESTAMP       NOT NULL WITH DEFAULT,
    TELLER_ID        CHAR(8)         NOT NULL,
    BEFORE_BAL       DECIMAL(15, 2)  NOT NULL,
    AFTER_BAL        DECIMAL(15, 2)  NOT NULL,
    DETAILS          VARCHAR(255),
    CONSTRAINT PK_AUDIT PRIMARY KEY (AUD_ID)
) IN BANKDB.BANKDB04;

CREATE INDEX BANKDB.IX_AUDIT_TXN_REF
    ON BANKDB.AUDIT_LOG (AUD_TXN_REF);

CREATE INDEX BANKDB.IX_AUDIT_TS
    ON BANKDB.AUDIT_LOG (EVENT_TS);

-- Sequence used by BKAUDIT for audit record identity
CREATE SEQUENCE BANKDB.AUDIT_SEQ
    AS INTEGER
    START WITH 1
    INCREMENT BY 1
    NO CYCLE
    CACHE 20;

-- --------------------------------------------------------------------
-- Seed data
-- --------------------------------------------------------------------
INSERT INTO BANKDB.ACCOUNT_MASTER
    (ACCT_NO, ACCT_TYPE, CUSTOMER_ID, ACCT_STATUS,
     BALANCE, OVERDRAFT_LIMIT, DAILY_WD_LIMIT, DAILY_WD_USED)
VALUES
    ('ACC0000001', 'CH', '100000001', 'A', 12500.00, 0.00,   5000.00, 0.00),
    ('ACC0000002', 'SV', '100000001', 'A', 43200.75, 0.00,   2000.00, 0.00),
    ('ACC0000003', 'CH', '100000002', 'A',  8900.00, 500.00, 5000.00, 0.00),
    ('ACC0000004', 'LN', '100000002', 'A', -15000.00, 0.00,     0.00, 0.00),
    ('ACC0000005', 'CH', '100000003', 'F',  3200.00, 0.00,   1000.00, 0.00),
    ('ACC0000006', 'SV', '100000003', 'C',     0.00, 0.00,      0.00, 0.00);
