-- =====================================================================
-- V0001 -- Bootstrap: extensions, schemas, roles, base settings.
-- =====================================================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;       -- trigram search for property names
CREATE EXTENSION IF NOT EXISTS btree_gin;     -- composite GIN indexes
-- Citus is enabled per the SAD's "Citus DB" decision; if running on plain PG
-- the CREATE EXTENSION below is a no-op-fail and the app still works.
DO $$ BEGIN
    PERFORM 1 FROM pg_available_extensions WHERE name = 'citus';
    IF FOUND THEN
        EXECUTE 'CREATE EXTENSION IF NOT EXISTS citus';
    END IF;
END $$;

-- One schema per bounded context. Keeps tables logically grouped and
-- makes per-service grants surgical.
CREATE SCHEMA IF NOT EXISTS user_mgmt;
CREATE SCHEMA IF NOT EXISTS portfolio;
CREATE SCHEMA IF NOT EXISTS vdr;
CREATE SCHEMA IF NOT EXISTS workflow;
CREATE SCHEMA IF NOT EXISTS search;
CREATE SCHEMA IF NOT EXISTS audit;

-- Application roles. Per-service users get the matching role; this is what
-- you grant in CREATE USER ... IN ROLE.
CREATE ROLE app_reader   NOLOGIN;
CREATE ROLE app_writer   NOLOGIN;
CREATE ROLE app_migrator NOLOGIN;

GRANT USAGE ON SCHEMA user_mgmt, portfolio, vdr, workflow, search, audit TO app_reader, app_writer, app_migrator;
ALTER DEFAULT PRIVILEGES IN SCHEMA user_mgmt, portfolio, vdr, workflow, search, audit
    GRANT SELECT ON TABLES TO app_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA user_mgmt, portfolio, vdr, workflow, search, audit
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_writer;

-- Helpful global setting: queries log when slower than 1 s.
ALTER DATABASE can_app SET log_min_duration_statement = '1s';
