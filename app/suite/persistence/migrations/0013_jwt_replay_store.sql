-- 0013_jwt_replay_store.sql
-- Tenant-aware durable replay protection for signed OIDC/JWT token IDs.

CREATE SCHEMA IF NOT EXISTS collabio;

CREATE TABLE IF NOT EXISTS collabio.jwt_replay_tokens (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    issuer text NOT NULL CHECK (issuer <> ''),
    subject text NOT NULL CHECK (subject <> ''),
    jwt_id text NOT NULL CHECK (jwt_id <> ''),
    expires_at_epoch bigint NOT NULL CHECK (expires_at_epoch > 0),
    expires_at_utc timestamptz NOT NULL,
    first_seen_at_utc timestamptz NOT NULL DEFAULT now(),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    schema_version text NOT NULL DEFAULT 'jwt_replay_token.v1',
    PRIMARY KEY (issuer, jwt_id)
);

CREATE TABLE IF NOT EXISTS collabio.jwt_replay_events (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    event_id text PRIMARY KEY CHECK (event_id <> ''),
    event_type text NOT NULL CHECK (event_type IN ('accepted', 'replayed')),
    issuer text NOT NULL CHECK (issuer <> ''),
    subject text NOT NULL CHECK (subject <> ''),
    jwt_id text NOT NULL CHECK (jwt_id <> ''),
    expires_at_epoch bigint NOT NULL CHECK (expires_at_epoch > 0),
    expires_at_utc timestamptz NOT NULL,
    observed_at_epoch bigint NOT NULL CHECK (observed_at_epoch > 0),
    observed_at_utc timestamptz NOT NULL DEFAULT now(),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    schema_version text NOT NULL DEFAULT 'jwt_replay_event.v1'
);

COMMENT ON TABLE collabio.jwt_replay_tokens IS
    'Durable replay guard for signed JWT jti values. Token bodies are never stored.';
COMMENT ON COLUMN collabio.jwt_replay_tokens.jwt_id IS
    'Opaque token identifier only; never store the compact JWT or claims body in this table.';
COMMENT ON TABLE collabio.jwt_replay_events IS
    'Append-only tenant-aware replay audit events for accepted and rejected token IDs.';

CREATE INDEX IF NOT EXISTS jwt_replay_tokens_tenant_expiry_idx
    ON collabio.jwt_replay_tokens (tenant_id, expires_at_epoch);

CREATE INDEX IF NOT EXISTS jwt_replay_tokens_subject_idx
    ON collabio.jwt_replay_tokens (tenant_id, issuer, subject);

CREATE INDEX IF NOT EXISTS jwt_replay_events_tenant_type_idx
    ON collabio.jwt_replay_events (tenant_id, event_type, observed_at_utc);

CREATE INDEX IF NOT EXISTS jwt_replay_events_jti_idx
    ON collabio.jwt_replay_events (issuer, jwt_id, observed_at_utc);

ALTER TABLE collabio.jwt_replay_tokens ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.jwt_replay_tokens FORCE ROW LEVEL SECURITY;
ALTER TABLE collabio.jwt_replay_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.jwt_replay_events FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS jwt_replay_tokens_tenant_select ON collabio.jwt_replay_tokens;
CREATE POLICY jwt_replay_tokens_tenant_select
    ON collabio.jwt_replay_tokens
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS jwt_replay_tokens_tenant_insert ON collabio.jwt_replay_tokens;
CREATE POLICY jwt_replay_tokens_tenant_insert
    ON collabio.jwt_replay_tokens
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS jwt_replay_tokens_no_hard_delete ON collabio.jwt_replay_tokens;
CREATE POLICY jwt_replay_tokens_no_hard_delete
    ON collabio.jwt_replay_tokens
    FOR DELETE
    USING (false);

DROP POLICY IF EXISTS jwt_replay_events_tenant_select ON collabio.jwt_replay_events;
CREATE POLICY jwt_replay_events_tenant_select
    ON collabio.jwt_replay_events
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS jwt_replay_events_tenant_insert ON collabio.jwt_replay_events;
CREATE POLICY jwt_replay_events_tenant_insert
    ON collabio.jwt_replay_events
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS jwt_replay_events_no_hard_delete ON collabio.jwt_replay_events;
CREATE POLICY jwt_replay_events_no_hard_delete
    ON collabio.jwt_replay_events
    FOR DELETE
    USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA collabio TO collabio_app';
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.jwt_replay_tokens TO collabio_app';
        EXECUTE 'GRANT INSERT ON TABLE collabio.jwt_replay_events TO collabio_app';
    END IF;
END
$$;
