-- =============================================================================
-- NatWest Fraud Detection - Customer Profile Table
-- SQL Server 2008 R2 Compatible DDL
-- =============================================================================

IF OBJECT_ID('dbo.CUST_PROFILE', 'U') IS NOT NULL
    DROP TABLE dbo.CUST_PROFILE;

CREATE TABLE dbo.CUST_PROFILE (
    ACCT_NO        CHAR(10)      NOT NULL,
    AVG_TXN_AMOUNT DECIMAL(15,2) NOT NULL CONSTRAINT DF_PROF_AVG DEFAULT 0,
    MAX_TXN_AMOUNT DECIMAL(15,2) NOT NULL CONSTRAINT DF_PROF_MAX DEFAULT 0,
    USUAL_COUNTRY  CHAR(3)       NULL,
    USUAL_CHANNEL  VARCHAR(8)    NULL,
    USUAL_HR_START INT           NULL,
    USUAL_HR_END   INT           NULL,
    PROFILE_DATE   DATETIME      NOT NULL CONSTRAINT DF_PROF_DATE DEFAULT GETDATE(),
    CONSTRAINT PK_CUST_PROFILE PRIMARY KEY (ACCT_NO)
);
