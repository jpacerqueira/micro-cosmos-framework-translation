-- ============================================================================
-- 08_mq_failure_log.sql
-- BankXYZ Fraud Detection — MQ_FAILURE_LOG table
--
-- Oracle 10g note:
--   FAIL_ID uses sequence MQ_FAIL_SEQ + trigger TRG_MQ_FAIL_ID
--
-- Dependencies: sequence MQ_FAIL_SEQ (00_sequences.sql)
-- Run after:    00_sequences.sql
-- ============================================================================

PROMPT ============================================================
PROMPT Creating table MQ_FAILURE_LOG
PROMPT ============================================================

BEGIN
    EXECUTE IMMEDIATE 'DROP TABLE MQ_FAILURE_LOG CASCADE CONSTRAINTS PURGE';
EXCEPTION
    WHEN OTHERS THEN
        IF SQLCODE != -942 THEN RAISE; END IF;
END;
/

-- ----------------------------------------------------------------------------
-- MQ_FAILURE_LOG
-- Records failures when MqNotificationService cannot put a message to
-- FRAUD.ALERT.QUEUE. A failed put is non-fatal — the DB alert is already
-- committed, but the case management system will not be notified in real time.
-- Operations team must replay failed messages manually.
--
-- REASON_CODE: JMSException error code from the broker.
--   0 = unknown / default (used when no numeric code is available)
--   Other codes are broker-specific (ActiveMQ reason codes).
-- ----------------------------------------------------------------------------
CREATE TABLE MQ_FAILURE_LOG
(
    FAIL_ID             NUMBER(10)          NOT NULL,
    TXN_ID              CHAR(16)            NOT NULL,
    ACCT_NO             CHAR(10)            NOT NULL,

    -- JMS error code (broker-specific; 0 = unknown)
    REASON_CODE         NUMBER(10)          DEFAULT 0     NOT NULL,

    FAILED_TS           TIMESTAMP           DEFAULT CURRENT_TIMESTAMP NOT NULL,

    -- ---- Constraints ----
    CONSTRAINT PK_MQ_FAIL
        PRIMARY KEY (FAIL_ID)
);

-- ---- Index: operations queries — recent failures ----
CREATE INDEX IX_MQ_FAIL_TS
    ON MQ_FAILURE_LOG (FAILED_TS);

-- ---- Identity trigger (Oracle 10g) ----
CREATE OR REPLACE TRIGGER TRG_MQ_FAIL_ID
    BEFORE INSERT ON MQ_FAILURE_LOG
    FOR EACH ROW
    WHEN (NEW.FAIL_ID IS NULL)
BEGIN
    SELECT MQ_FAIL_SEQ.NEXTVAL
    INTO   :NEW.FAIL_ID
    FROM   DUAL;
END;
/

-- ---- Column documentation ----
COMMENT ON TABLE MQ_FAILURE_LOG IS
    'Records failed JMS puts to FRAUD.ALERT.QUEUE. Written by MqNotificationService — non-fatal; DB alert is already committed. Operations team monitors daily.';

COMMENT ON COLUMN MQ_FAILURE_LOG.FAIL_ID IS
    'Surrogate PK. Populated by TRG_MQ_FAIL_ID from MQ_FAIL_SEQ.';
COMMENT ON COLUMN MQ_FAILURE_LOG.REASON_CODE IS
    'Broker error code. For ActiveMQ: see JMSException.getErrorCode(). 0 = no code available.';
COMMENT ON COLUMN MQ_FAILURE_LOG.TXN_ID IS
    'Transaction whose alert notification failed. Used to replay the message manually if needed.';

PROMPT Table MQ_FAILURE_LOG created.
PROMPT Index IX_MQ_FAIL_TS created.
PROMPT Trigger TRG_MQ_FAIL_ID created.
COMMIT;
