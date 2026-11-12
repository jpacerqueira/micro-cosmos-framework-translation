-- =====================================================================
-- V0030 -- VDR (Virtual Data Room), workflow, search.
-- =====================================================================
SET search_path TO vdr, public;

CREATE TABLE vdr_raw (
    document_id        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id       UUID,
    property_id        UUID,
    blob_path          TEXT        NOT NULL,
    original_filename  TEXT        NOT NULL,
    mime_type          TEXT,
    size_bytes         BIGINT,
    sha256             TEXT,
    uploaded_by        UUID,
    uploaded_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    ingestion_status   TEXT        NOT NULL DEFAULT 'PENDING'
        CHECK (ingestion_status IN ('PENDING','EXTRACTING','CLEAN','FAILED','QUARANTINED'))
);
CREATE INDEX vdr_raw_status_idx       ON vdr_raw(ingestion_status);
CREATE INDEX vdr_raw_portfolio_idx    ON vdr_raw(portfolio_id);

CREATE TABLE template_catalogue (
    template_id    BIGSERIAL PRIMARY KEY,
    template_name  TEXT NOT NULL UNIQUE,
    template_type  TEXT,
    schema_json    JSONB NOT NULL
);

CREATE TABLE document_extracted (
    document_id    UUID PRIMARY KEY REFERENCES vdr_raw(document_id) ON DELETE CASCADE,
    extracted_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    text_content   TEXT,
    metadata_json  JSONB
);

-- Workflow state (denormalised process-instance projection).
CREATE SCHEMA IF NOT EXISTS workflow;
SET search_path TO workflow, public;

CREATE TABLE process_instance (
    instance_id     UUID PRIMARY KEY,
    portfolio_id    UUID,
    property_id     UUID,
    process_type    TEXT        NOT NULL,
    state           TEXT        NOT NULL,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ,
    last_event_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata        JSONB
);
CREATE INDEX pi_state_idx     ON process_instance(state);
CREATE INDEX pi_portfolio_idx ON process_instance(portfolio_id);

-- Search projection - one row per searchable thing across the domain.
SET search_path TO search, public;

CREATE TABLE search_index (
    entity_id     UUID NOT NULL,
    entity_type   TEXT NOT NULL,
    portfolio_id  UUID,
    title         TEXT NOT NULL,
    body          TEXT,
    tags          TEXT[],
    last_updated  TIMESTAMPTZ NOT NULL DEFAULT now(),
    tsv           TSVECTOR GENERATED ALWAYS AS
        (setweight(to_tsvector('english', coalesce(title,'')), 'A') ||
         setweight(to_tsvector('english', coalesce(body,'')),  'B'))
        STORED,
    PRIMARY KEY (entity_id, entity_type)
);
CREATE INDEX search_tsv_idx        ON search_index USING gin(tsv);
CREATE INDEX search_portfolio_idx  ON search_index(portfolio_id);
CREATE INDEX search_tags_idx       ON search_index USING gin(tags);
