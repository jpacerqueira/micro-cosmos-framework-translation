-- ============================================================================
-- 06_watchlist_hits.sql
-- BankXYZ Fraud Detection — WATCHLIST_HITS table
--
-- Oracle 10g note:
--   HIT_ID uses sequence WL_HITS_SEQ + trigger TRG_WL_HITS_ID
--
-- Dependencies: sequence WL_HITS_SEQ (00_sequences.sql)
-- Run after:    00_sequences.sql
-- ============================================================================

PROMPT ============================================================
PROMPT Creating table WATCHLIST_HITS
PROMPT ============================================================

BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE WATCHLIST_HITS CASCADE CONSTRAINTS PURGE';
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN RAISE; END IF;
END;
/

-- ----------------------------------------------------------------------------
-- WATCHLIST_HITS
-- Immutable audit log of every watchlist match regardless of outcome.
-- Written by WatchlistService before returning to caller — a hit must be
-- logged even if the transaction is subsequently approved or reviewed.
--
-- HIT_TYPE values: 'OFAC', 'PEP', 'INTERNAL'
-- HIT_REASON: human-readable description, e.g.
--   'OFAC SANCTIONS HIT - MANDATORY ESCALATION'
--   'PEP LIST HIT - MANDATORY ESCALATION'
--   'INTERNAL WATCHLIST HIT'
-- ----------------------------------------------------------------------------
CREATE TABLE WATCHLIST_HITS
(
    HIT_ID              NUMBER(10)          NOT NULL,
    ACCT_NO             CHAR(10)            NOT NULL,
    TXN_ID              CHAR(16)            NOT NULL,

    -- List type that generated this hit
    HIT_TYPE            VARCHAR2(40)        NOT NULL,

    -- Human-readable match reason (passed to fraud operations team)
    HIT_REASON          VARCHAR2(80)        NOT NULL,

    HIT_TS              TIMESTAMP           DEFAULT CURRENT_TIMESTAMP NOT NULL,

    -- ---- Constraints ----
    CONSTRAINT PK_WL_HITS
        PRIMARY KEY (HIT_ID),

    CONSTRAINT CHK_WL_HIT_TYPE
        CHECK (HIT_TYPE IN ('OFAC', 'PEP', 'INTERNAL'))
);

-- ---- Index: common query pattern — hits per account or per transaction ----
CREATE INDEX IX_WL_HITS_ACCT
    ON WATCHLIST_HITS (ACCT_NO, HIT_TS);

CREATE INDEX IX_WL_HITS_TXN
    ON WATCHLIST_HITS (TXN_ID);

-- ---- Identity trigger (Oracle 10g) ----
CREATE OR REPLACE TRIGGER TRG_WL_HITS_ID
    BEFORE INSERT ON WATCHLIST_HITS
    FOR EACH ROW
    WHEN (NEW.HIT_ID IS NULL)
BEGIN
    SELECT WL_HITS_SEQ.NEXTVAL
    INTO   :NEW.HIT_ID
    FROM   DUAL;
END;
/

-- ---- Column documentation ----
COMMENT ON TABLE WATCHLIST_HITS IS
    'Immutable audit log of every watchlist match. Written by WatchlistService. Read by compliance and incident investigation.';

COMMENT ON COLUMN WATCHLIST_HITS.HIT_ID IS
    'Surrogate PK. Populated by TRG_WL_HITS_ID from WL_HITS_SEQ.';
COMMENT ON COLUMN WATCHLIST_HITS.HIT_TYPE IS
    'OFAC, PEP, or INTERNAL — identifies which list generated the match.';
COMMENT ON COLUMN WATCHLIST_HITS.HIT_REASON IS
    'Human-readable reason logged by WatchlistService. Consumed by fraud operations.';

PROMPT Table WATCHLIST_HITS created.
PROMPT Indexes IX_WL_HITS_ACCT, IX_WL_HITS_TXN created.
PROMPT Trigger TRG_WL_HITS_ID created.
COMMIT;
