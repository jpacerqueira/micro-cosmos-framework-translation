-- =============================================================================
-- NatWest Fraud Detection - Transaction Queue Table
-- SQL Server 2008 R2 Compatible DDL
-- =============================================================================

IF OBJECT_ID('dbo.TXN_QUEUE', 'U') IS NOT NULL
    DROP TABLE dbo.TXN_QUEUE;

CREATE TABLE dbo.TXN_QUEUE (
    TXN_ID        CHAR(16)      NOT NULL,
    ACCT_NO       CHAR(10)      NOT NULL,
    TXN_AMOUNT    DECIMAL(15,2) NOT NULL,
    MERCHANT_CODE CHAR(8)       NOT NULL,
    CHANNEL       VARCHAR(8)    NOT NULL,
    TXN_COUNTRY   CHAR(3)       NOT NULL,
    CARD_LAST4    CHAR(4)       NULL,
    CARD_TYPE     CHAR(2)       NULL,
    CNP_FLAG      CHAR(1)       NOT NULL CONSTRAINT DF_TXN_CNP_FLAG DEFAULT 'N',
    TXN_STATUS    CHAR(1)       NOT NULL CONSTRAINT DF_TXN_STATUS DEFAULT 'P'
        CONSTRAINT CHK_TXN_STATUS CHECK (TXN_STATUS IN ('P','S','E')),
    TXN_TS        DATETIME      NOT NULL CONSTRAINT DF_TXN_TS DEFAULT GETDATE(),
    PROC_TS       DATETIME      NULL,
    BATCH_DATE    DATETIME      NULL,
    CONSTRAINT PK_TXN_QUEUE PRIMARY KEY (TXN_ID),
    CONSTRAINT FK_TXN_ACCT FOREIGN KEY (ACCT_NO)
        REFERENCES dbo.ACCOUNT_MASTER (ACCT_NO)
);

CREATE INDEX IX_TXN_STATUS ON dbo.TXN_QUEUE (TXN_STATUS, TXN_TS);
CREATE INDEX IX_TXN_ACCT   ON dbo.TXN_QUEUE (ACCT_NO, TXN_TS);
