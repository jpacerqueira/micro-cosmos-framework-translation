-- =====================================================================
-- V0010 -- user_mgmt schema: companies, users, roles, notifications.
-- Mirrors the SAD's Conceptual Data Model, expressed for PostgreSQL with
-- referential integrity and indexing for the BFF's typical access paths.
-- =====================================================================
SET search_path TO user_mgmt, public;

CREATE TABLE company (
    company_id    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    company_name  TEXT        NOT NULL,
    company_type  TEXT        NOT NULL CHECK (company_type IN ('INTERNAL','BROKER','VALUER','LENDER','OTHER')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX company_name_trgm_idx ON company USING gin (company_name gin_trgm_ops);

CREATE TABLE role (
    role_id     SERIAL PRIMARY KEY,
    role_name   TEXT NOT NULL UNIQUE
);
INSERT INTO role (role_name) VALUES
    ('PORTFOLIO_ADMIN'), ('BROKER'), ('VALUER'), ('VIEWER'), ('SYS_ADMIN');

CREATE TABLE app_user (
    user_id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_oid         TEXT        UNIQUE,                 -- Azure AD object id
    user_name        TEXT        NOT NULL,
    user_email       TEXT        NOT NULL UNIQUE,
    user_mobile      TEXT,
    company_id       UUID        REFERENCES company(company_id),
    is_external      BOOLEAN     NOT NULL DEFAULT FALSE,
    last_login_at    TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX app_user_company_idx ON app_user(company_id);
CREATE INDEX app_user_email_idx ON app_user(lower(user_email));

CREATE TABLE user_role (
    user_id   UUID NOT NULL REFERENCES app_user(user_id) ON DELETE CASCADE,
    role_id   INT  NOT NULL REFERENCES role(role_id),
    granted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, role_id)
);

CREATE TABLE user_notification (
    notification_id          BIGSERIAL PRIMARY KEY,
    user_id                  UUID        NOT NULL REFERENCES app_user(user_id),
    channel                  TEXT        NOT NULL CHECK (channel IN ('EMAIL','TEAMS','SMS','IN_APP')),
    subject                  TEXT,
    message                  TEXT,
    outbound_destination     TEXT,
    notification_status      TEXT        NOT NULL DEFAULT 'PENDING'
        CHECK (notification_status IN ('PENDING','SENT','FAILED')),
    notification_timestamp   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX notif_user_idx    ON user_notification(user_id);
CREATE INDEX notif_pending_idx ON user_notification(notification_status) WHERE notification_status = 'PENDING';
