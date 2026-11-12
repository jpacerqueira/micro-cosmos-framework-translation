-- ============================================================================
-- 05_watchlist.sql
-- BankXYZ Fraud Detection — WATCHLIST table
--
-- Oracle 10g note:
--   WATCHLIST_ID uses sequence WATCHLIST_SEQ + trigger TRG_WATCHLIST_ID
--   because Oracle 10g does not support GENERATED ALWAYS AS IDENTITY.
--
-- Dependencies: sequence WATCHLIST_SEQ (00_sequences.sql)
-- Run after:    00_sequences.sql
-- ============================================================================

PROMPT ============================================================
PROMPT Creating table WATCHLIST
PROMPT ============================================================

BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE WATCHLIST CASCADE CONSTRAINTS PURGE';
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN RAISE; END IF;
END;
/

-- ----------------------------------------------------------------------------
-- WATCHLIST
-- Consolidated sanctions and fraud watchlist.
-- Sources: OFAC (daily feed), PEP (weekly feed), internal BankXYZ fraud ops.
--
-- WatchlistService screening order (returns on first hit):
--   1. LIST_TYPE = 'OFAC'     → score = 1.0, mandatory escalation (OFAC_FLAG = Y)
--   2. LIST_TYPE = 'PEP'      → score = 1.0, mandatory escalation (PEP_FLAG = Y)
--   3. LIST_TYPE = 'INTERNAL' → score = 0.9, logged; scoring continues
--
-- LIST_STATUS = 'EXPIRED' rows are ignored by WatchlistService.
-- MATCH_NAME screening uses LIKE with wildcards (case-insensitive in service).
-- MATCH_ACCT used for direct account-level blocking (INTERNAL list only).
-- ----------------------------------------------------------------------------
CREATE TABLE WATCHLIST
(
    WATCHLIST_ID        NUMBER(10)          NOT NULL,

    -- List source — drives WatchlistService screening logic
    LIST_TYPE           VARCHAR2(10)        NOT NULL,

    -- Name to match against ACCOUNT_MASTER.CUST_FULL_NAME
    MATCH_NAME          VARCHAR2(100),

    -- Account number for direct account-level blocking (INTERNAL list only)
    MATCH_ACCT          CHAR(10),

    -- 'ACTIVE' = in force, 'EXPIRED' = superseded or time-expired
    LIST_STATUS         VARCHAR2(6)         DEFAULT 'ACTIVE'  NOT NULL,

    -- External reference number (OFAC SDN ref, PEP source ref, internal case ID)
    REF_NUMBER          CHAR(20),

    -- Operator who added the entry
    ADDED_BY            CHAR(8)             DEFAULT 'SYSTEM'  NOT NULL,

    EFFECTIVE_FROM      DATE                DEFAULT SYSDATE   NOT NULL,

    -- NULL = currently active; set to past date to expire an entry
    EFFECTIVE_TO        DATE,

    -- ---- Constraints ----
    CONSTRAINT PK_WATCHLIST
        PRIMARY KEY (WATCHLIST_ID),

    CONSTRAINT CHK_LIST_TYPE
        CHECK (LIST_TYPE IN ('OFAC', 'PEP', 'INTERNAL')),

    CONSTRAINT CHK_LIST_STATUS
        CHECK (LIST_STATUS IN ('ACTIVE', 'EXPIRED')),

    CONSTRAINT CHK_WL_MATCH
        CHECK (MATCH_NAME IS NOT NULL OR MATCH_ACCT IS NOT NULL),

    CONSTRAINT CHK_WL_DATES
        CHECK (EFFECTIVE_TO IS NULL OR EFFECTIVE_TO >= EFFECTIVE_FROM)
);

-- ---- Indexes ----
-- Supports WatchlistService OFAC/PEP name screening query
CREATE INDEX IX_WL_TYPE_NAME
    ON WATCHLIST (LIST_TYPE, LIST_STATUS, MATCH_NAME);

-- Supports WatchlistService internal account-level screening query
CREATE INDEX IX_WL_ACCT
    ON WATCHLIST (MATCH_ACCT, LIST_TYPE, LIST_STATUS);

-- ---- Identity trigger (Oracle 10g — no IDENTITY column support) ----
-- Fires BEFORE INSERT; populates WATCHLIST_ID from WATCHLIST_SEQ when NULL.
CREATE OR REPLACE TRIGGER TRG_WATCHLIST_ID
    BEFORE INSERT ON WATCHLIST
    FOR EACH ROW
    WHEN (NEW.WATCHLIST_ID IS NULL)
BEGIN
    SELECT WATCHLIST_SEQ.NEXTVAL
    INTO   :NEW.WATCHLIST_ID
    FROM   DUAL;
END;
/

-- ---- Column documentation ----
COMMENT ON TABLE WATCHLIST IS
    'Consolidated sanctions and fraud watchlist. Sources: OFAC (daily), PEP (weekly), internal BankXYZ fraud ops. OFAC/PEP hits force score=1.0 and mandatory escalation.';

COMMENT ON COLUMN WATCHLIST.LIST_TYPE IS
    'OFAC=sanctions (mandatory escalation), PEP=politically exposed person (mandatory escalation), INTERNAL=BankXYZ internal fraud list (score=0.9).';
COMMENT ON COLUMN WATCHLIST.MATCH_NAME IS
    'Customer name for LIKE screening against ACCOUNT_MASTER.CUST_FULL_NAME. Use % wildcards for partial matches.';
COMMENT ON COLUMN WATCHLIST.MATCH_ACCT IS
    'Direct account block (INTERNAL list only). WatchlistService screens by MATCH_ACCT OR MATCH_NAME.';
COMMENT ON COLUMN WATCHLIST.LIST_STATUS IS
    'ACTIVE=currently enforced. EXPIRED=WatchlistService ignores this row.';
COMMENT ON COLUMN WATCHLIST.WATCHLIST_ID IS
    'Surrogate PK. Populated by TRG_WATCHLIST_ID from WATCHLIST_SEQ. Oracle 10g replacement for GENERATED ALWAYS AS IDENTITY.';

PROMPT Table WATCHLIST created.
PROMPT Indexes IX_WL_TYPE_NAME, IX_WL_ACCT created.
PROMPT Trigger TRG_WATCHLIST_ID created.
COMMIT;
