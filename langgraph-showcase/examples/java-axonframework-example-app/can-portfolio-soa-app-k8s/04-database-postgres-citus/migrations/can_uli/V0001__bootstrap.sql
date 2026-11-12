-- =====================================================================
-- can_uli - Universal Layer of Interoperability persistence:
--   - Inbox/outbox pattern for at-least-once delivery semantics
--   - Dead letter queue for poison messages
--   - Replay manifest for re-processing event ranges
-- =====================================================================
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE SCHEMA IF NOT EXISTS uli;

CREATE TABLE uli.outbox (
    message_id      UUID        PRIMARY KEY,
    correlation_id  UUID        NOT NULL,
    causation_id    UUID,
    subject         TEXT        NOT NULL,
    type            TEXT        NOT NULL,
    source_service  TEXT        NOT NULL,
    payload         JSONB       NOT NULL,
    headers         JSONB,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at    TIMESTAMPTZ,
    publish_attempts INT        NOT NULL DEFAULT 0
);
CREATE INDEX outbox_pending_idx ON uli.outbox(occurred_at) WHERE published_at IS NULL;

CREATE TABLE uli.inbox (
    message_id      UUID        NOT NULL,
    consumer_group  TEXT        NOT NULL,
    received_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (message_id, consumer_group)
);

CREATE TABLE uli.dead_letter (
    dlq_id          BIGSERIAL PRIMARY KEY,
    message_id      UUID        NOT NULL,
    subject         TEXT        NOT NULL,
    payload         JSONB       NOT NULL,
    error           TEXT        NOT NULL,
    failed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    consumer_group  TEXT        NOT NULL
);
CREATE INDEX dlq_subject_idx ON uli.dead_letter(subject, failed_at DESC);
