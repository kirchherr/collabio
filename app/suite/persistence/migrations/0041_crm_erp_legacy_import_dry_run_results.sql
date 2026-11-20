-- 0041_crm_erp_legacy_import_dry_run_results.sql
-- Tenant-scoped append-only metadata-only Legacy SQL import dry-run results.
-- This migration stores row-count/checksum evidence only; no raw legacy rows or import writes.

CREATE TABLE IF NOT EXISTS crm_erp_legacy.import_dry_run_results (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    module_id text NOT NULL DEFAULT 'crm_erp' CHECK (module_id = 'crm_erp'),
    source_system_ref text NOT NULL CHECK (source_system_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    dry_run_plan_hash text NOT NULL CHECK (dry_run_plan_hash ~ '^sha256:[a-f0-9]{64}$'),
    discovery_manifest_hash text NOT NULL CHECK (discovery_manifest_hash ~ '^sha256:[a-f0-9]{64}$'),
    mapping_manifest_hash text NOT NULL CHECK (mapping_manifest_hash ~ '^sha256:[a-f0-9]{64}$'),
    readiness_evidence_hash text NOT NULL CHECK (readiness_evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    staging_metadata_plan_hash text NOT NULL CHECK (staging_metadata_plan_hash ~ '^sha256:[a-f0-9]{64}$'),
    status text NOT NULL CHECK (status IN ('completed_metadata_only', 'blocked_by_plan')),
    table_result_count integer NOT NULL CHECK (table_result_count >= 0),
    expected_table_count integer NOT NULL CHECK (expected_table_count >= 1),
    table_results jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (
        jsonb_typeof(table_results) = 'array'
        AND jsonb_array_length(table_results) = table_result_count
    ),
    blocking_reasons jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (
        jsonb_typeof(blocking_reasons) = 'array'
    ),
    row_count_strategy text NOT NULL DEFAULT 'exact_read_only_count_query' CHECK (
        row_count_strategy = 'exact_read_only_count_query'
    ),
    checksum_strategy text NOT NULL DEFAULT 'sha256_canonical_row_hash_manifest' CHECK (
        checksum_strategy = 'sha256_canonical_row_hash_manifest'
    ),
    audit_event_types text[] NOT NULL CHECK (
        audit_event_types <@ ARRAY[
            'legacy_sql.import_dry_run.started',
            'legacy_sql.import_dry_run.table_validated',
            'legacy_sql.import_dry_run.completed',
            'legacy_sql.import_dry_run.blocked'
        ]::text[]
    ),
    metadata_only_ok boolean NOT NULL DEFAULT true CHECK (metadata_only_ok),
    dry_run_execution_attempted boolean NOT NULL,
    dry_run_execution_completed boolean NOT NULL,
    real_connection_used boolean NOT NULL DEFAULT false CHECK (real_connection_used = false),
    raw_data_import_allowed boolean NOT NULL DEFAULT false CHECK (raw_data_import_allowed = false),
    import_write_executed boolean NOT NULL DEFAULT false CHECK (import_write_executed = false),
    destructive_actions_executed boolean NOT NULL DEFAULT false CHECK (destructive_actions_executed = false),
    executed_by text NOT NULL CHECK (executed_by <> ''),
    executed_at_utc timestamptz NOT NULL,
    result_evidence jsonb NOT NULL CHECK (
        jsonb_typeof(result_evidence) = 'object'
        AND result_evidence ->> 'schema_version' = 'legacy_sql_import_dry_run_result.v1'
        AND NOT (result_evidence ? 'connection_secret_ref')
        AND NOT (result_evidence ? 'raw_payload')
        AND (result_evidence ->> 'metadata_only_ok')::boolean = true
        AND (result_evidence ->> 'real_connection_used')::boolean = false
        AND (result_evidence ->> 'raw_data_import_allowed')::boolean = false
        AND (result_evidence ->> 'import_write_executed')::boolean = false
        AND (result_evidence ->> 'destructive_actions_executed')::boolean = false
    ),
    result_hash text NOT NULL CHECK (result_hash ~ '^sha256:[a-f0-9]{64}$'),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    schema_version text NOT NULL DEFAULT 'legacy_sql_import_dry_run_result.v1' CHECK (
        schema_version = 'legacy_sql_import_dry_run_result.v1'
    ),
    PRIMARY KEY (tenant_id, result_hash),
    CHECK ((result_evidence ->> 'tenant_id') = tenant_id),
    CHECK ((result_evidence ->> 'module_id') = module_id),
    CHECK ((result_evidence ->> 'source_system_ref') = source_system_ref),
    CHECK ((result_evidence ->> 'dry_run_plan_hash') = dry_run_plan_hash),
    CHECK ((result_evidence ->> 'discovery_manifest_hash') = discovery_manifest_hash),
    CHECK ((result_evidence ->> 'mapping_manifest_hash') = mapping_manifest_hash),
    CHECK ((result_evidence ->> 'readiness_evidence_hash') = readiness_evidence_hash),
    CHECK ((result_evidence ->> 'staging_metadata_plan_hash') = staging_metadata_plan_hash),
    CHECK ((result_evidence ->> 'status') = status),
    CHECK ((result_evidence ->> 'result_hash') = result_hash),
    CHECK (
        (
            status = 'completed_metadata_only'
            AND dry_run_execution_attempted
            AND dry_run_execution_completed
            AND table_result_count = expected_table_count
            AND jsonb_array_length(blocking_reasons) = 0
        )
        OR (
            status = 'blocked_by_plan'
            AND dry_run_execution_completed = false
            AND table_result_count = 0
            AND jsonb_array_length(blocking_reasons) >= 1
        )
    )
);

COMMENT ON TABLE crm_erp_legacy.import_dry_run_results IS
    'Tenant-scoped append-only metadata-only Legacy SQL import dry-run results. Stores row-count observations, checksum manifest hashes, audit event references, and plan/result hashes without raw legacy rows, sample values, cell values, DSNs, Secret references, prompts, outputs, or import payloads.';

COMMENT ON COLUMN crm_erp_legacy.import_dry_run_results.result_evidence IS
    'legacy_sql_import_dry_run_result.v1 JSON. Raw SQL rows, table data, sample values, DSNs, Secret references, import write payloads, prompts, outputs, embeddings, transcripts, and destructive action payloads are excluded.';

CREATE INDEX IF NOT EXISTS crm_erp_legacy_import_dry_run_results_plan_idx
    ON crm_erp_legacy.import_dry_run_results (
        tenant_id,
        dry_run_plan_hash,
        status,
        executed_at_utc
    );

CREATE INDEX IF NOT EXISTS crm_erp_legacy_import_dry_run_results_chain_idx
    ON crm_erp_legacy.import_dry_run_results (
        tenant_id,
        discovery_manifest_hash,
        mapping_manifest_hash,
        readiness_evidence_hash,
        staging_metadata_plan_hash
    );

ALTER TABLE crm_erp_legacy.import_dry_run_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE crm_erp_legacy.import_dry_run_results FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS crm_erp_legacy_import_dry_run_results_tenant_select
    ON crm_erp_legacy.import_dry_run_results;
CREATE POLICY crm_erp_legacy_import_dry_run_results_tenant_select
    ON crm_erp_legacy.import_dry_run_results
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS crm_erp_legacy_import_dry_run_results_tenant_insert
    ON crm_erp_legacy.import_dry_run_results;
CREATE POLICY crm_erp_legacy_import_dry_run_results_tenant_insert
    ON crm_erp_legacy.import_dry_run_results
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS crm_erp_legacy_import_dry_run_results_no_update
    ON crm_erp_legacy.import_dry_run_results;
CREATE POLICY crm_erp_legacy_import_dry_run_results_no_update
    ON crm_erp_legacy.import_dry_run_results
    FOR UPDATE
    USING (false);

DROP POLICY IF EXISTS crm_erp_legacy_import_dry_run_results_no_hard_delete
    ON crm_erp_legacy.import_dry_run_results;
CREATE POLICY crm_erp_legacy_import_dry_run_results_no_hard_delete
    ON crm_erp_legacy.import_dry_run_results
    FOR DELETE
    USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE crm_erp_legacy.import_dry_run_results TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE crm_erp_legacy.import_dry_run_results TO collabio_worker';
    END IF;
END
$$;

UPDATE collabio.module_catalog
SET required_migration_versions = '["0007", "0008", "0009", "0010", "0011", "0016", "0017", "0018", "0019", "0020", "0034", "0035", "0036", "0037", "0038", "0039", "0040", "0041"]'::jsonb
WHERE module_id = 'crm_erp';
