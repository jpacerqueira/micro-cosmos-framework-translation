-- =============================================================================
-- NatWest Fraud Detection - MQ Failure Log Table
-- SQL Server 2008 R2 Compatible DDL
-- =============================================================================

IF OBJECT_ID('dbo.MQ_FAILURE_LOG', 'U') IS NOT NULL
    DROP TABLE dbo.MQ_FAILURE_LOG;

CREATE TABLE dbo.MQ_FAILURE_LOG (
    FAIL_ID     INT      NOT NULL IDENTITY(1,1),
    TXN_ID      CHAR(16) NOT NULL,
    ACCT_NO     CHAR(10) NOT NULL,
    REASON_CODE INT      NULL,
    FAILED_TS   DATETIME NOT NULL CONSTRAINT DF_MQ_FAILED_TS DEFAULT GETDATE(),
    CONSTRAINT PK_MQ_FAILURE_LOG PRIMARY KEY (FAIL_ID)
);

CREATE INDEX IX_MQ_FAIL_TS   ON dbo.MQ_FAILURE_LOG (FAILED_TS);
CREATE INDEX IX_MQ_FAIL_ACCT ON dbo.MQ_FAILURE_LOG (ACCT_NO, FAILED_TS);
