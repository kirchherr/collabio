-- 0034_legacy_sql_evidence_ledger.sql
-- Tenant-scoped append-only metadata ledger for Legacy SQL import evidence hashes.

CREATE TABLE IF NOT EXISTS collabio.legacy_sql_evidence_ledger (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    module_id text NOT NULL DEFAULT 'crm_erp' CHECK (module_id ~ '^[a-z][a-z0-9_]*$'),
    source_system_ref text NOT NULL CHECK (source_system_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    evidence_type text NOT NULL CHECK (
        evidence_type IN (
            'discovery_intake',
            'discovery_intake_operations_report',
            'metadata_discovery_manifest',
            'import_evidence_plan',
            'crm_erp_mapping_manifest',
            'import_readiness',
            'readiness_smoke_report'
        )
    ),
    evidence_ref text NOT NULL CHECK (evidence_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    evidence_hash text NOT NULL CHECK (evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    evidence_status text NOT NULL CHECK (evidence_status <> ''),
    related_evidence_hashes jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (
        jsonb_typeof(related_evidence_hashes) = 'array'
    ),
    restore_evidence_hash text NOT NULL CHECK (restore_evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    captured_by text NOT NULL CHECK (captured_by <> ''),
    captured_at_utc timestamptz NOT NULL,
    raw_payload_included boolean NOT NULL DEFAULT false CHECK (raw_payload_included = false),
    real_connection_used boolean NOT NULL DEFAULT false,
    import_dry_run_executed boolean NOT NULL DEFAULT false,
    import_write_executed boolean NOT NULL DEFAULT false CHECK (import_write_executed = false),
    destructive_actions_executed boolean NOT NULL DEFAULT false CHECK (destructive_actions_executed = false),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(metadata) = 'object'),
    ledger_entry jsonb NOT NULL CHECK (
        jsonb_typeof(ledger_entry) = 'object'
        AND ledger_entry ->> 'schema_version' = 'legacy_sql_evidence_ledger_entry.v1'
    ),
    ledger_entry_hash text NOT NULL CHECK (ledger_entry_hash ~ '^sha256:[a-f0-9]{64}$'),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    schema_version text NOT NULL DEFAULT 'legacy_sql_evidence_ledger_entry.v1' CHECK (
        schema_version = 'legacy_sql_evidence_ledger_entry.v1'
    ),
    PRIMARY KEY (tenant_id, ledger_entry_hash),
    CHECK ((ledger_entry ->> 'tenant_id') = tenant_id),
    CHECK ((ledger_entry ->> 'module_id') = module_id),
    CHECK ((ledger_entry ->> 'source_system_ref') = source_system_ref),
    CHECK ((ledger_entry ->> 'evidence_type') = evidence_type),
    CHECK ((ledger_entry ->> 'evidence_ref') = evidence_ref),
    CHECK ((ledger_entry ->> 'evidence_hash') = evidence_hash),
    CHECK ((ledger_entry ->> 'evidence_status') = evidence_status),
    CHECK ((ledger_entry ->> 'restore_evidence_hash') = restore_evidence_hash),
    CHECK ((ledger_entry ->> 'ledger_entry_hash') = ledger_entry_hash),
    CHECK ((ledger_entry ->> 'raw_payload_included')::boolean = false),
    CHECK ((ledger_entry ->> 'import_write_executed')::boolean = false),
    CHECK ((ledger_entry ->> 'destructive_actions_executed')::boolean = false)
);

COMMENT ON TABLE collabio.legacy_sql_evidence_ledger IS
    'Tenant-scoped append-only metadata ledger for Legacy SQL intake, discovery, mapping, readiness, and smoke-report hashes.';

COMMENT ON COLUMN collabio.legacy_sql_evidence_ledger.ledger_entry IS
    'legacy_sql_evidence_ledger_entry.v1 JSON. Raw SQL rows, table data, sample values, DSNs, secrets, report payloads, prompts, outputs, embeddings, transcripts, and destructive action payloads are excluded.';

CREATE INDEX IF NOT EXISTS legacy_sql_evidence_ledger_source_idx
    ON collabio.legacy_sql_evidence_ledger (tenant_id, source_system_ref, evidence_type, captured_at_utc);

CREATE INDEX IF NOT EXISTS legacy_sql_evidence_ledger_evidence_hash_idx
    ON collabio.legacy_sql_evidence_ledger (tenant_id, evidence_hash);

CREATE INDEX IF NOT EXISTS legacy_sql_evidence_ledger_restore_idx
    ON collabio.legacy_sql_evidence_ledger (tenant_id, restore_evidence_hash);

ALTER TABLE collabio.legacy_sql_evidence_ledger ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.legacy_sql_evidence_ledger FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS legacy_sql_evidence_ledger_tenant_select
    ON collabio.legacy_sql_evidence_ledger;
CREATE POLICY legacy_sql_evidence_ledger_tenant_select
    ON collabio.legacy_sql_evidence_ledger
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS legacy_sql_evidence_ledger_tenant_insert
    ON collabio.legacy_sql_evidence_ledger;
CREATE POLICY legacy_sql_evidence_ledger_tenant_insert
    ON collabio.legacy_sql_evidence_ledger
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS legacy_sql_evidence_ledger_no_update
    ON collabio.legacy_sql_evidence_ledger;
CREATE POLICY legacy_sql_evidence_ledger_no_update
    ON collabio.legacy_sql_evidence_ledger
    FOR UPDATE
    USING (false);

DROP POLICY IF EXISTS legacy_sql_evidence_ledger_no_hard_delete
    ON collabio.legacy_sql_evidence_ledger;
CREATE POLICY legacy_sql_evidence_ledger_no_hard_delete
    ON collabio.legacy_sql_evidence_ledger
    FOR DELETE
    USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.legacy_sql_evidence_ledger TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.legacy_sql_evidence_ledger TO collabio_worker';
    END IF;
END
$$;
