-- 0014_audit_event_store.sql
-- Tenant-scoped append-only audit events, HMAC checkpoints, and WORM export evidence.

CREATE SCHEMA IF NOT EXISTS collabio;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_audit_writer') THEN
        CREATE ROLE collabio_audit_writer LOGIN PASSWORD 'collabio_audit_writer';
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS collabio.audit_events (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    sequence_number bigint NOT NULL CHECK (sequence_number >= 1),
    event_id text NOT NULL CHECK (event_id <> ''),
    schema_version text NOT NULL DEFAULT 'audit_event.v1',
    user_id text NOT NULL CHECK (user_id <> ''),
    event_type text NOT NULL CHECK (event_type <> ''),
    model_id text,
    prompt_template_id text,
    source_object_ids text[] NOT NULL DEFAULT ARRAY[]::text[],
    input_hash text CHECK (input_hash IS NULL OR input_hash ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    output_hash text CHECK (output_hash IS NULL OR output_hash ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
    previous_event_hash text NOT NULL CHECK (previous_event_hash ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    event_hash text NOT NULL CHECK (event_hash ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    recorded_at_utc timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, sequence_number),
    UNIQUE (event_id),
    UNIQUE (tenant_id, event_hash)
);

CREATE TABLE IF NOT EXISTS collabio.audit_checkpoints (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    checkpoint_id text NOT NULL CHECK (checkpoint_id <> ''),
    through_sequence_number bigint NOT NULL CHECK (through_sequence_number >= 1),
    event_count bigint NOT NULL CHECK (event_count >= 1),
    first_event_hash text NOT NULL CHECK (first_event_hash ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    last_event_hash text NOT NULL CHECK (last_event_hash ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    checkpoint_hash text NOT NULL CHECK (checkpoint_hash ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    signature_algorithm text NOT NULL CHECK (signature_algorithm IN ('hmac-sha256')),
    signature_key_ref text NOT NULL CHECK (signature_key_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    created_by text NOT NULL CHECK (created_by <> ''),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    schema_version text NOT NULL DEFAULT 'audit_checkpoint.v1',
    PRIMARY KEY (tenant_id, checkpoint_id),
    UNIQUE (tenant_id, through_sequence_number)
);

CREATE TABLE IF NOT EXISTS collabio.audit_worm_exports (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    export_id text NOT NULL CHECK (export_id <> ''),
    checkpoint_id text NOT NULL,
    from_sequence_number bigint NOT NULL DEFAULT 1 CHECK (from_sequence_number = 1),
    through_sequence_number bigint NOT NULL CHECK (through_sequence_number >= 1),
    event_count bigint NOT NULL CHECK (event_count >= 1),
    first_event_hash text NOT NULL CHECK (first_event_hash ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    last_event_hash text NOT NULL CHECK (last_event_hash ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    checkpoint_hash text NOT NULL CHECK (checkpoint_hash ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    export_manifest_hash text NOT NULL CHECK (export_manifest_hash ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    storage_uri text NOT NULL CHECK (storage_uri <> ''),
    object_lock_mode text NOT NULL DEFAULT 'compliance' CHECK (object_lock_mode IN ('compliance')),
    created_by text NOT NULL CHECK (created_by <> ''),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    schema_version text NOT NULL DEFAULT 'audit_worm_export.v1',
    PRIMARY KEY (tenant_id, export_id),
    FOREIGN KEY (tenant_id, checkpoint_id)
        REFERENCES collabio.audit_checkpoints (tenant_id, checkpoint_id)
);

COMMENT ON TABLE collabio.audit_events IS
    'Append-only tenant-scoped audit chain. Prompt, output, document, mail, transcript, and token bodies are forbidden.';
COMMENT ON COLUMN collabio.audit_events.input_hash IS
    'Hash-only input evidence. Never store prompt or source bodies in audit_events.';
COMMENT ON COLUMN collabio.audit_events.output_hash IS
    'Hash-only output evidence. Never store generated output bodies in audit_events.';
COMMENT ON TABLE collabio.audit_checkpoints IS
    'HMAC checkpoint evidence over a tenant audit chain prefix.';
COMMENT ON TABLE collabio.audit_worm_exports IS
    'Evidence that an audit chain prefix was exported to WORM-capable storage.';

CREATE INDEX IF NOT EXISTS audit_events_tenant_event_type_idx
    ON collabio.audit_events (tenant_id, event_type, sequence_number);

CREATE INDEX IF NOT EXISTS audit_events_tenant_recorded_idx
    ON collabio.audit_events (tenant_id, recorded_at_utc);

CREATE INDEX IF NOT EXISTS audit_checkpoints_tenant_sequence_idx
    ON collabio.audit_checkpoints (tenant_id, through_sequence_number);

CREATE INDEX IF NOT EXISTS audit_worm_exports_tenant_checkpoint_idx
    ON collabio.audit_worm_exports (tenant_id, checkpoint_id);

ALTER TABLE collabio.audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.audit_events FORCE ROW LEVEL SECURITY;
ALTER TABLE collabio.audit_checkpoints ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.audit_checkpoints FORCE ROW LEVEL SECURITY;
ALTER TABLE collabio.audit_worm_exports ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.audit_worm_exports FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS audit_events_tenant_select ON collabio.audit_events;
CREATE POLICY audit_events_tenant_select
    ON collabio.audit_events
    FOR SELECT
    TO collabio_audit_writer
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS audit_events_tenant_insert ON collabio.audit_events;
CREATE POLICY audit_events_tenant_insert
    ON collabio.audit_events
    FOR INSERT
    TO collabio_audit_writer
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS audit_events_no_update ON collabio.audit_events;
CREATE POLICY audit_events_no_update
    ON collabio.audit_events
    FOR UPDATE
    TO collabio_audit_writer
    USING (false)
    WITH CHECK (false);

DROP POLICY IF EXISTS audit_events_no_hard_delete ON collabio.audit_events;
CREATE POLICY audit_events_no_hard_delete
    ON collabio.audit_events
    FOR DELETE
    TO collabio_audit_writer
    USING (false);

DROP POLICY IF EXISTS audit_checkpoints_tenant_select ON collabio.audit_checkpoints;
CREATE POLICY audit_checkpoints_tenant_select
    ON collabio.audit_checkpoints
    FOR SELECT
    TO collabio_audit_writer
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS audit_checkpoints_tenant_insert ON collabio.audit_checkpoints;
CREATE POLICY audit_checkpoints_tenant_insert
    ON collabio.audit_checkpoints
    FOR INSERT
    TO collabio_audit_writer
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS audit_checkpoints_no_update ON collabio.audit_checkpoints;
CREATE POLICY audit_checkpoints_no_update
    ON collabio.audit_checkpoints
    FOR UPDATE
    TO collabio_audit_writer
    USING (false)
    WITH CHECK (false);

DROP POLICY IF EXISTS audit_checkpoints_no_hard_delete ON collabio.audit_checkpoints;
CREATE POLICY audit_checkpoints_no_hard_delete
    ON collabio.audit_checkpoints
    FOR DELETE
    TO collabio_audit_writer
    USING (false);

DROP POLICY IF EXISTS audit_worm_exports_tenant_select ON collabio.audit_worm_exports;
CREATE POLICY audit_worm_exports_tenant_select
    ON collabio.audit_worm_exports
    FOR SELECT
    TO collabio_audit_writer
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS audit_worm_exports_tenant_insert ON collabio.audit_worm_exports;
CREATE POLICY audit_worm_exports_tenant_insert
    ON collabio.audit_worm_exports
    FOR INSERT
    TO collabio_audit_writer
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS audit_worm_exports_no_update ON collabio.audit_worm_exports;
CREATE POLICY audit_worm_exports_no_update
    ON collabio.audit_worm_exports
    FOR UPDATE
    TO collabio_audit_writer
    USING (false)
    WITH CHECK (false);

DROP POLICY IF EXISTS audit_worm_exports_no_hard_delete ON collabio.audit_worm_exports;
CREATE POLICY audit_worm_exports_no_hard_delete
    ON collabio.audit_worm_exports
    FOR DELETE
    TO collabio_audit_writer
    USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_audit_writer') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA collabio TO collabio_audit_writer';
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.audit_events TO collabio_audit_writer';
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.audit_checkpoints TO collabio_audit_writer';
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.audit_worm_exports TO collabio_audit_writer';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'REVOKE ALL ON TABLE collabio.audit_events FROM collabio_app';
        EXECUTE 'REVOKE ALL ON TABLE collabio.audit_checkpoints FROM collabio_app';
        EXECUTE 'REVOKE ALL ON TABLE collabio.audit_worm_exports FROM collabio_app';
    END IF;
END
$$;
