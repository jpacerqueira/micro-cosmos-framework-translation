-- =============================================================================
-- NatWest Fraud Detection - Watchlist Hits Table
-- SQL Server 2008 R2 Compatible DDL
-- =============================================================================

IF OBJECT_ID('dbo.WATCHLIST_HITS', 'U') IS NOT NULL
    DROP TABLE dbo.WATCHLIST_HITS;

CREATE TABLE dbo.WATCHLIST_HITS (
    HIT_ID     INT           NOT NULL IDENTITY(1,1),
    ACCT_NO    CHAR(10)      NOT NULL,
    TXN_ID     CHAR(16)      NOT NULL,
    HIT_TYPE   VARCHAR(10)   NOT NULL
        CONSTRAINT CHK_HIT_TYPE CHECK (HIT_TYPE IN ('OFAC','PEP','INTERNAL')),
    HIT_REASON NVARCHAR(200) NULL,
    HIT_TS     DATETIME      NOT NULL CONSTRAINT DF_HIT_TS DEFAULT GETDATE(),
    CONSTRAINT PK_WATCHLIST_HITS PRIMARY KEY (HIT_ID)
);

CREATE INDEX IX_WL_HITS_ACCT ON dbo.WATCHLIST_HITS (ACCT_NO, HIT_TS);
CREATE INDEX IX_WL_HITS_TXN  ON dbo.WATCHLIST_HITS (TXN_ID);
