-- =============================================================================
-- NatWest Fraud Detection - SLA Breach Log Table
-- SQL Server 2008 R2 Compatible DDL
-- =============================================================================

IF OBJECT_ID('dbo.SLA_BREACH_LOG', 'U') IS NOT NULL
    DROP TABLE dbo.SLA_BREACH_LOG;

CREATE TABLE dbo.SLA_BREACH_LOG (
    BREACH_ID  INT      NOT NULL IDENTITY(1,1),
    TXN_ID     CHAR(16) NOT NULL,
    ACCT_NO    CHAR(10) NOT NULL,
    ELAPSED_MS BIGINT   NOT NULL,
    BREACH_TS  DATETIME NOT NULL CONSTRAINT DF_SLA_BREACH_TS DEFAULT GETDATE(),
    CONSTRAINT PK_SLA_BREACH_LOG PRIMARY KEY (BREACH_ID)
);

CREATE INDEX IX_SLA_BREACH_TS   ON dbo.SLA_BREACH_LOG (BREACH_TS);
CREATE INDEX IX_SLA_BREACH_ACCT ON dbo.SLA_BREACH_LOG (ACCT_NO, BREACH_TS);
