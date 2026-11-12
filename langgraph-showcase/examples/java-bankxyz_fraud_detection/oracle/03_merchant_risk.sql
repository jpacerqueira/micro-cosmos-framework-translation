-- ============================================================================
-- 03_merchant_risk.sql
-- BankXYZ Fraud Detection — MERCHANT_RISK table
--
-- Dependencies: none
-- Run after:    00_sequences.sql
-- ============================================================================

PROMPT ============================================================
PROMPT Creating table MERCHANT_RISK
PROMPT ============================================================

BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE MERCHANT_RISK CASCADE CONSTRAINTS PURGE';
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN RAISE; END IF;
END;
/

-- ----------------------------------------------------------------------------
-- MERCHANT_RISK
-- Risk classification for merchant codes.
-- Read by FraudRulesService to compute signal 2 (merchant risk band).
--
-- BLOCKED_FLAG scoring (FraudRulesService.scoreByMerchant):
--   BLOCKED_FLAG = 'Y'  →  merchant score = 1.0000 (immediate high risk)
--   RISK_BAND = 'HIGH'  →  merchant score = 0.8000
--   RISK_BAND = 'MED '  →  merchant score = 0.4000
--   RISK_BAND = 'LOW '  →  merchant score = 0.1000
--   Not found in table  →  merchant score = 0.0000 (no signal)
--
-- EFFECTIVE_FROM / EFFECTIVE_TO allow time-bounded risk classifications.
-- A row with EFFECTIVE_TO < SYSDATE should be ignored by the application
-- (application-level filter, not enforced by a DB constraint here).
-- ----------------------------------------------------------------------------
CREATE TABLE MERCHANT_RISK
(
    MERCHANT_CODE       CHAR(8)             NOT NULL,
    MERCHANT_NAME       VARCHAR2(80),

    -- 'Y' = entirely blocked; score = 1.0 regardless of risk band
    BLOCKED_FLAG        CHAR(1)             DEFAULT 'N'    NOT NULL,

    -- Space-padded to 4 chars: 'HIGH' | 'MED ' | 'LOW '
    RISK_BAND           CHAR(4)             DEFAULT 'LOW ' NOT NULL,

    BLOCK_REASON        VARCHAR2(80),
    EFFECTIVE_FROM      DATE                DEFAULT SYSDATE NOT NULL,
    EFFECTIVE_TO        DATE,
    LAST_UPDATE_TS      TIMESTAMP           DEFAULT CURRENT_TIMESTAMP NOT NULL,

    -- ---- Constraints ----
    CONSTRAINT PK_MERCHANT_RISK
        PRIMARY KEY (MERCHANT_CODE),

    CONSTRAINT CHK_BLOCKED_FLAG
        CHECK (BLOCKED_FLAG IN ('Y', 'N')),

    CONSTRAINT CHK_RISK_BAND
        CHECK (RISK_BAND IN ('HIGH', 'MED ', 'LOW ')),

    CONSTRAINT CHK_EFFECTIVE_DATES
        CHECK (EFFECTIVE_TO IS NULL OR EFFECTIVE_TO >= EFFECTIVE_FROM)
);

-- ---- Column documentation ----
COMMENT ON TABLE MERCHANT_RISK IS
    'Risk classification for merchant codes. Read by FraudRulesService (signal 2, weight=0.25). Maintained by fraud operations team.';

COMMENT ON COLUMN MERCHANT_RISK.BLOCKED_FLAG IS
    'Y = merchant entirely blocked; FraudRulesService returns score=1.0 immediately.';
COMMENT ON COLUMN MERCHANT_RISK.RISK_BAND IS
    'Risk band: HIGH=0.80, MED =0.40, LOW =0.10. Fixed 4-char space-padded.';
COMMENT ON COLUMN MERCHANT_RISK.EFFECTIVE_TO IS
    'NULL = still active. Application filters out expired rows (EFFECTIVE_TO < SYSDATE).';

PROMPT Table MERCHANT_RISK created.
COMMIT;
