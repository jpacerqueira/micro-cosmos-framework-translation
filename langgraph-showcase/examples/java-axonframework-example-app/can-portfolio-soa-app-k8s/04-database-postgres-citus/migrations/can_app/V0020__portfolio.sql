-- =====================================================================
-- V0020 -- portfolio schema: portfolio, property, allocations, valuations,
-- broker allocations, tenancy schedules, journal. Includes the Citus
-- distribution declarations - portfolio_id is the natural shard key.
-- =====================================================================
SET search_path TO portfolio, public;

-- Portfolio: the top-level aggregate root.
CREATE TABLE portfolio (
    portfolio_id            UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_name          TEXT        NOT NULL,
    portfolio_description   TEXT,
    cut_off_date            DATE        NOT NULL,
    final_bid_date          DATE        NOT NULL,
    project_phase           TEXT        NOT NULL,
    status                  TEXT        NOT NULL DEFAULT 'OPEN'
        CHECK (status IN ('DRAFT','OPEN','BIDDING','CLOSED','ARCHIVED')),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_dates CHECK (final_bid_date >= cut_off_date)
);
CREATE INDEX portfolio_status_idx       ON portfolio(status);
CREATE INDEX portfolio_name_trgm_idx    ON portfolio USING gin (portfolio_name gin_trgm_ops);

-- The view (read-side projection) the JPA entities map to.
CREATE TABLE portfolio_view (
    portfolio_id     UUID        PRIMARY KEY,
    name             TEXT        NOT NULL,
    description      TEXT,
    cut_off_date     DATE        NOT NULL,
    final_bid_date   DATE        NOT NULL,
    project_phase    TEXT        NOT NULL,
    status           TEXT        NOT NULL,
    last_event_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Connection: lender / counter-party metadata.
CREATE TABLE connection (
    connection_id          BIGSERIAL PRIMARY KEY,
    connection_id_name     TEXT,
    portfolio_id           UUID NOT NULL REFERENCES portfolio(portfolio_id) ON DELETE CASCADE,
    sector_of_connection   TEXT,
    operator_name          TEXT,
    type_of_operator       TEXT
);
CREATE INDEX connection_portfolio_idx ON connection(portfolio_id);

-- Loan facility under the portfolio.
CREATE TABLE loan_facility (
    loan_facility_id    BIGSERIAL PRIMARY KEY,
    facilities_id_list  TEXT,
    portfolio_id        UUID NOT NULL REFERENCES portfolio(portfolio_id) ON DELETE CASCADE,
    loan_id_list        TEXT,
    type_of_operator    TEXT,
    fcl_subborrower_id  TEXT
);
CREATE INDEX loan_facility_portfolio_idx ON loan_facility(portfolio_id);

-- Property: one property in a portfolio. Distributed by portfolio_id.
CREATE TABLE property (
    property_id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    portfolio_id                 UUID        NOT NULL REFERENCES portfolio(portfolio_id) ON DELETE CASCADE,
    property_external_id         TEXT,
    property_name                TEXT        NOT NULL,
    loan_facilities_id           BIGINT      REFERENCES loan_facility(loan_facility_id),
    connection_id                BIGINT      REFERENCES connection(connection_id),
    property_geolocation_lat     DOUBLE PRECISION,
    property_geolocation_long    DOUBLE PRECISION,
    property_map_url             TEXT,
    valuation_list_id_1          BIGINT,
    valuation_list_id_2          BIGINT,
    template_allocation_id       BIGINT,
    property_address_line_1      TEXT,
    property_address_line_2      TEXT,
    property_city                TEXT,
    property_state_region        TEXT,
    property_county              TEXT,
    property_address_postcode    TEXT,
    property_unit_list           TEXT,
    property_portfolio_onboarding_starts_at TIMESTAMPTZ,
    property_portfolio_onboarding_ends_at   TIMESTAMPTZ,
    created_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX property_portfolio_idx     ON property(portfolio_id);
CREATE INDEX property_postcode_idx      ON property(property_address_postcode);
CREATE INDEX property_name_trgm_idx     ON property USING gin (property_name gin_trgm_ops);
CREATE INDEX property_geo_idx           ON property(property_geolocation_lat, property_geolocation_long);

CREATE TABLE property_view (
    property_id        UUID PRIMARY KEY,
    portfolio_id       UUID NOT NULL,
    name               TEXT NOT NULL,
    address_line_1     TEXT,
    city               TEXT,
    postcode           TEXT,
    valuation          NUMERIC(18,2),
    broker_company_id  UUID,
    allocation_status  TEXT,
    last_event_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX property_view_portfolio_idx ON property_view(portfolio_id);
CREATE INDEX property_view_broker_idx    ON property_view(broker_company_id);

-- Unit under a property (lease unit).
CREATE TABLE unit (
    unit_id           BIGSERIAL PRIMARY KEY,
    property_id       UUID NOT NULL REFERENCES property(property_id) ON DELETE CASCADE,
    facilities_id     BIGINT,
    connection_id     BIGINT,
    unit_address      TEXT,
    unit_size         NUMERIC(14,2),
    unit_area         TEXT,
    unit_number       INT,
    unit_type         TEXT
);
CREATE INDEX unit_property_idx ON unit(property_id);

-- Valuation - latest valuation snapshot per property.
CREATE TABLE property_valuation (
    valuation_id                       BIGSERIAL PRIMARY KEY,
    property_id                        UUID NOT NULL REFERENCES property(property_id) ON DELETE CASCADE,
    portfolio_id                       UUID NOT NULL REFERENCES portfolio(portfolio_id) ON DELETE CASCADE,
    valuer_id                          UUID,
    valuation_date                     DATE NOT NULL,
    valuation_timestamp                TIMESTAMPTZ NOT NULL DEFAULT now(),
    valuation_type_fid                 TEXT,
    valuation_needed_fields            JSONB,
    valuation_size_id                  TEXT,
    capital_valuation                  NUMERIC(18,2) NOT NULL,
    bank_valuation                     NUMERIC(18,2),
    valuation_status                   TEXT,
    property_valuation_starts_at       TIMESTAMPTZ,
    property_valuation_ends_at         TIMESTAMPTZ
);
CREATE INDEX prop_val_property_idx     ON property_valuation(property_id);
CREATE INDEX prop_val_portfolio_idx    ON property_valuation(portfolio_id);

-- Tenancy schedule - one row per unit per review.
CREATE TABLE tenancy_schedule (
    tenancy_schedule_id                  BIGSERIAL PRIMARY KEY,
    valuation_id                         BIGINT NOT NULL REFERENCES property_valuation(valuation_id) ON DELETE CASCADE,
    unit_id                              BIGINT NOT NULL REFERENCES unit(unit_id),
    unit_number                          INT,
    term                                 TEXT,
    unit_size                            NUMERIC(14,2),
    unit_area                            TEXT,
    last_rent_review_date                DATE,
    next_rent_review_starts_at           DATE
);
CREATE INDEX ts_valuation_idx ON tenancy_schedule(valuation_id);

-- Template catalogue + allocation.
CREATE TABLE template_catalogue (
    template_id              BIGSERIAL PRIMARY KEY,
    template_name            TEXT NOT NULL,
    template_type            TEXT,
    property_sector          TEXT,
    template_needed_structure JSONB
);

CREATE TABLE template_allocation (
    allocation_id              BIGSERIAL PRIMARY KEY,
    template_id                BIGINT REFERENCES template_catalogue(template_id),
    template_name              TEXT,
    property_sector            TEXT,
    allocation_date            DATE NOT NULL DEFAULT CURRENT_DATE,
    template_needed_mapping_fields JSONB,
    template_list_id_1         BIGINT,
    template_list_id_2         BIGINT,
    template_allocation_status TEXT,
    template_allocation_starts_at TIMESTAMPTZ,
    template_allocation_ends_at   TIMESTAMPTZ
);

-- Broker allocation - which company markets which property.
CREATE TABLE broker_allocation (
    broker_allocation_id            BIGSERIAL PRIMARY KEY,
    property_id                     UUID NOT NULL REFERENCES property(property_id) ON DELETE CASCADE,
    portfolio_id                    UUID NOT NULL REFERENCES portfolio(portfolio_id) ON DELETE CASCADE,
    valuation_id                    BIGINT REFERENCES property_valuation(valuation_id),
    fcl_broker_company_name         TEXT,
    fcl_broker_user_id              UUID,
    fcl_valuer_user_id              UUID,
    user_id_1                       UUID,
    user_id_2                       UUID,
    user_id_3                       UUID,
    company_id_1                    UUID,
    company_id_2                    UUID,
    broker_allocation_starts_at     TIMESTAMPTZ,
    broker_allocation_ends_at       TIMESTAMPTZ,
    allocation_timestamp            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX broker_alloc_property_idx  ON broker_allocation(property_id);
CREATE INDEX broker_alloc_portfolio_idx ON broker_allocation(portfolio_id);

-- Valuation question / answer audit (for tenancy data quality).
CREATE TABLE valuation_question (
    question_id            BIGSERIAL PRIMARY KEY,
    broker_allocation_id   BIGINT REFERENCES broker_allocation(broker_allocation_id),
    valuation_id           BIGINT REFERENCES property_valuation(valuation_id),
    company_id             UUID,
    user_id                UUID,
    question               TEXT,
    answer                 TEXT,
    question_timestamp     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Property journal - immutable event log per portfolio.
CREATE TABLE property_journal (
    journal_id          BIGSERIAL PRIMARY KEY,
    portfolio_id        UUID NOT NULL REFERENCES portfolio(portfolio_id) ON DELETE CASCADE,
    property_id         UUID REFERENCES property(property_id),
    sequence_id         BIGINT NOT NULL,
    journal_timestamp   TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id             UUID,
    journal_log_message TEXT
);
CREATE INDEX prop_journal_portfolio_idx ON property_journal(portfolio_id, journal_timestamp DESC);
