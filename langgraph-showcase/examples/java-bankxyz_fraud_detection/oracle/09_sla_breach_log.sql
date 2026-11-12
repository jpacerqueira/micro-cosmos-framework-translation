-- ============================================================================
-- 09_sla_breach_log.sql
-- BankXYZ Fraud Detection — SLA_BREACH_LOG table
--
-- Oracle 10g note:
--   BREACH_ID uses sequence SLA_BREACH_SEQ + trigger TRG_SLA_BREACH_ID
--
-- Business invariant (BRD-2009-FD-004):
--   When the SLA is breached, the authorisation decision defaults to APPROVE.
--   The breach is logged here for monitoring but does NOT block the transaction.
--   This is an explicit accepted business risk (a sufficiently slow attack can
--   bypass real-time screening).
--
-- Dependencies: sequence SLA_BREACH_SEQ (00_sequences.sql)
-- Run after:    00_sequences.sql
-- ============================================================================

PROMPT ============================================================
PROMPT Creating table SLA_BREACH_LOG
PROMPT ============================================================

BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE SLA_BREACH_LOG CASCADE CONSTRAINTS PURGE';
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN RAISE; END IF;
END;
/

-- ----------------------------------------------------------------------------
-- SLA_BREACH_LOG
-- Records every real-time authorisation check that exceeded the 180ms SLA.
-- Reviewed during incident post-mortems (see INC-2023-4471) and during
-- capacity planning to identify peak-hour degradation patterns.
--
-- ELAPSED_MS: wall-clock time from RealtimeCheckController entry to
--             decision point, measured by System.currentTimeMillis().
--             Includes all DB and MQ I/O on the hot path.
-- ----------------------------------------------------------------------------
CREATE TABLE SLA_BREACH_LOG
(
    BREACH_ID           NUMBER(10)          NOT NULL,
    TXN_ID              CHAR(16)            NOT NULL,
    ACCT_NO             CHAR(10)            NOT NULL,

    -- Measured response time in milliseconds (SLA limit = 180ms)
    ELAPSED_MS          NUMBER(10)          NOT NULL,

    BREACH_TS           TIMESTAMP           DEFAULT CURRENT_TIMESTAMP NOT NULL,

    -- ---- Constraints ----
    CONSTRAINT PK_SLA_BREACH
        PRIMARY KEY (BREACH_ID),

    CONSTRAINT CHK_ELAPSED_MS
        CHECK (ELAPSED_MS > 0)
);

-- ---- Indexes ----
-- Supports time-range queries for SLA trend analysis
CREATE INDEX IX_SLA_BREACH_TS
    ON SLA_BREACH_LOG (BREACH_TS);

-- Supports per-account SLA analysis (identify accounts that repeatedly trigger
-- slow scoring paths, e.g. large watchlist scan)
CREATE INDEX IX_SLA_BREACH_ACCT
    ON SLA_BREACH_LOG (ACCT_NO, BREACH_TS);

-- ---- Identity trigger (Oracle 10g) ----
CREATE OR REPLACE TRIGGER TRG_SLA_BREACH_ID
    BEFORE INSERT ON SLA_BREACH_LOG
    FOR EACH ROW
    WHEN (NEW.BREACH_ID IS NULL)
BEGIN
    SELECT SLA_BREACH_SEQ.NEXTVAL
    INTO   :NEW.BREACH_ID
    FROM   DUAL;
END;
/

-- ---- Column documentation ----
COMMENT ON TABLE SLA_BREACH_LOG IS
    'Records every real-time check exceeding the 180ms SLA (BRD-2009-FD-004). Decision defaults to APPROVE on breach. Used for capacity planning and incident post-mortems.';

COMMENT ON COLUMN SLA_BREACH_LOG.BREACH_ID IS
    'Surrogate PK. Populated by TRG_SLA_BREACH_ID from SLA_BREACH_SEQ.';
COMMENT ON COLUMN SLA_BREACH_LOG.ELAPSED_MS IS
    'Wall-clock duration from RealtimeCheckController entry to decision. Includes all I/O. SLA limit is 180ms (configurable via fraud.scoring.sla-limit-ms).';
COMMENT ON COLUMN SLA_BREACH_LOG.TXN_ID IS
    'The transaction that triggered the breach. Decision was APPROVE regardless of fraud score (BRD-2009-FD-004).';

PROMPT Table SLA_BREACH_LOG created.
PROMPT Indexes IX_SLA_BREACH_TS, IX_SLA_BREACH_ACCT created.
PROMPT Trigger TRG_SLA_BREACH_ID created.
COMMIT;
