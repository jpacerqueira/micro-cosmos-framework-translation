-- ============================================================================
-- 00_sequences.sql
-- BankXYZ Fraud Detection — Oracle 10g Sequences
--
-- Oracle 10g does not support IDENTITY columns (added in Oracle 12c).
-- Every surrogate primary key uses a sequence + BEFORE INSERT trigger.
--
-- Run order: this file MUST be executed before any table DDL that references
--            these sequences (i.e. before 05–09 and 07).
--
-- Usage:
--   sqlplus FDADMIN@//host:1521/SID @00_sequences.sql
-- ============================================================================

PROMPT ============================================================
PROMPT Creating sequences for BankXYZ Fraud Detection schema
PROMPT ============================================================

-- ----------------------------------------------------------------------------
-- Drop sequences if they already exist (idempotent re-run)
-- ORA-02289 = sequence does not exist (safe to ignore)
-- ----------------------------------------------------------------------------

BEGIN
    EXECUTE IMMEDIATE 'DROP SEQUENCE FD_SEQ';
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -2289 THEN RAISE; END IF;
END;
/

BEGIN
    EXECUTE IMMEDIATE 'DROP SEQUENCE AUDIT_SEQ';
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -2289 THEN RAISE; END IF;
END;
/

BEGIN
    EXECUTE IMMEDIATE 'DROP SEQUENCE WATCHLIST_SEQ';
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -2289 THEN RAISE; END IF;
END;
/

BEGIN
    EXECUTE IMMEDIATE 'DROP SEQUENCE WL_HITS_SEQ';
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -2289 THEN RAISE; END IF;
END;
/

BEGIN
    EXECUTE IMMEDIATE 'DROP SEQUENCE MQ_FAIL_SEQ';
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -2289 THEN RAISE; END IF;
END;
/

BEGIN
    EXECUTE IMMEDIATE 'DROP SEQUENCE SLA_BREACH_SEQ';
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -2289 THEN RAISE; END IF;
END;
/

-- ----------------------------------------------------------------------------
-- FD_SEQ
-- Used by: FRAUD_ALERTS.ALERT_ID
-- ----------------------------------------------------------------------------
CREATE SEQUENCE FD_SEQ
    START WITH 1
    INCREMENT BY 1
    NOCYCLE
    CACHE 20
    NOORDER;


-- ----------------------------------------------------------------------------
-- AUDIT_SEQ
-- Reserved for audit trail entries (not yet active in this migration phase).
-- ----------------------------------------------------------------------------
CREATE SEQUENCE AUDIT_SEQ
    START WITH 1
    INCREMENT BY 1
    NOCYCLE
    CACHE 20
    NOORDER;


-- ----------------------------------------------------------------------------
-- WATCHLIST_SEQ
-- Used by: trigger TRG_WATCHLIST_ID
-- ----------------------------------------------------------------------------
CREATE SEQUENCE WATCHLIST_SEQ
    START WITH 1
    INCREMENT BY 1
    NOCYCLE
    CACHE 20
    NOORDER;


-- ----------------------------------------------------------------------------
-- WL_HITS_SEQ
-- Used by: trigger TRG_WL_HITS_ID
-- ----------------------------------------------------------------------------
CREATE SEQUENCE WL_HITS_SEQ
    START WITH 1
    INCREMENT BY 1
    NOCYCLE
    CACHE 20
    NOORDER;


-- ----------------------------------------------------------------------------
-- MQ_FAIL_SEQ
-- Used by: trigger TRG_MQ_FAIL_ID
-- ----------------------------------------------------------------------------
CREATE SEQUENCE MQ_FAIL_SEQ
    START WITH 1
    INCREMENT BY 1
    NOCYCLE
    CACHE 20
    NOORDER;


-- ----------------------------------------------------------------------------
-- SLA_BREACH_SEQ
-- Used by: trigger TRG_SLA_BREACH_ID
-- ----------------------------------------------------------------------------
CREATE SEQUENCE SLA_BREACH_SEQ
    START WITH 1
    INCREMENT BY 1
    NOCYCLE
    CACHE 20
    NOORDER;


PROMPT Sequences created successfully.
COMMIT;
