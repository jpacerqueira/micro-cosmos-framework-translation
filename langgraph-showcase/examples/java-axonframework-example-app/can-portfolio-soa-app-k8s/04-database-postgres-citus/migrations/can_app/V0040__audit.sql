-- =====================================================================
-- V0040 -- Audit log: who did what, when, on which entity. Append-only;
-- INSERT only via stored procedure to prevent tampering.
-- =====================================================================
SET search_path TO audit, public;

CREATE TABLE event_log (
    event_id        BIGSERIAL PRIMARY KEY,
    correlation_id  UUID        NOT NULL,
    causation_id    UUID,
    actor_user_id   UUID,
    actor_email     TEXT,
    action          TEXT        NOT NULL,
    entity_type     TEXT        NOT NULL,
    entity_id       UUID,
    payload         JSONB,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_service  TEXT        NOT NULL
);
CREATE INDEX event_log_correlation_idx ON event_log(correlation_id);
CREATE INDEX event_log_entity_idx      ON event_log(entity_type, entity_id);
CREATE INDEX event_log_occurred_idx    ON event_log(occurred_at DESC);

-- Block UPDATE/DELETE on the audit log entirely - only inserts allowed.
CREATE OR REPLACE FUNCTION audit.deny_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit.event_log is append-only';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_no_update BEFORE UPDATE ON event_log
    FOR EACH ROW EXECUTE FUNCTION audit.deny_mutation();
CREATE TRIGGER audit_no_delete BEFORE DELETE ON event_log
    FOR EACH ROW EXECUTE FUNCTION audit.deny_mutation();
