-- 0040_crm_erp_legacy_import_dry_run_plans.sql
-- Tenant-scoped metadata-only Legacy SQL import dry-run plans for CRM/ERP.
-- This migration stores no raw legacy rows and does not allow import writes.

CREATE TABLE IF NOT EXISTS crm_erp_legacy.import_dry_run_plans (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    module_id text NOT NULL DEFAULT 'crm_erp' CHECK (module_id = 'crm_erp'),
    source_system_ref text NOT NULL CHECK (source_system_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    discovery_manifest_hash text NOT NULL CHECK (discovery_manifest_hash ~ '^sha256:[a-f0-9]{64}$'),
    mapping_manifest_hash text NOT NULL CHECK (mapping_manifest_hash ~ '^sha256:[a-f0-9]{64}$'),
    readiness_evidence_hash text NOT NULL CHECK (readiness_evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    staging_metadata_plan_hash text NOT NULL CHECK (staging_metadata_plan_hash ~ '^sha256:[a-f0-9]{64}$'),
    table_count integer NOT NULL CHECK (table_count >= 1),
    planned_table_count integer NOT NULL CHECK (planned_table_count >= 1),
    estimated_row_count_total bigint CHECK (estimated_row_count_total IS NULL OR estimated_row_count_total >= 0),
    status text NOT NULL CHECK (
        status IN ('ready_for_metadata_dry_run', 'blocked_by_readiness')
    ),
    dry_run_execution_allowed boolean NOT NULL,
    blocking_reasons jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (
        jsonb_typeof(blocking_reasons) = 'array'
    ),
    row_count_strategy text NOT NULL DEFAULT 'exact_read_only_count_query' CHECK (
        row_count_strategy = 'exact_read_only_count_query'
    ),
    checksum_strategy text NOT NULL DEFAULT 'sha256_canonical_row_hash_manifest' CHECK (
        checksum_strategy = 'sha256_canonical_row_hash_manifest'
    ),
    table_plans jsonb NOT NULL CHECK (
        jsonb_typeof(table_plans) = 'array'
        AND jsonb_array_length(table_plans) = planned_table_count
    ),
    required_audit_event_types text[] NOT NULL CHECK (
        required_audit_event_types @> ARRAY[
            'legacy_sql.import_dry_run.started',
            'legacy_sql.import_dry_run.table_validated',
            'legacy_sql.import_dry_run.completed',
            'legacy_sql.import_dry_run.blocked'
        ]::text[]
    ),
    dry_run_required boolean NOT NULL DEFAULT true CHECK (dry_run_required),
    import_write_allowed boolean NOT NULL DEFAULT false CHECK (import_write_allowed = false),
    raw_data_import_allowed boolean NOT NULL DEFAULT false CHECK (raw_data_import_allowed = false),
    destructive_actions_allowed boolean NOT NULL DEFAULT false CHECK (destructive_actions_allowed = false),
    manifest_hash text NOT NULL CHECK (manifest_hash ~ '^sha256:[a-f0-9]{64}$'),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    schema_version text NOT NULL DEFAULT 'crm_erp_legacy_import_dry_run_plan.v1' CHECK (
        schema_version = 'crm_erp_legacy_import_dry_run_plan.v1'
    ),
    PRIMARY KEY (tenant_id, manifest_hash),
    CHECK (
        (
            status = 'ready_for_metadata_dry_run'
            AND dry_run_execution_allowed
            AND jsonb_array_length(blocking_reasons) = 0
        )
        OR (
            status = 'blocked_by_readiness'
            AND dry_run_execution_allowed = false
            AND jsonb_array_length(blocking_reasons) >= 1
        )
    )
);

COMMENT ON TABLE crm_erp_legacy.import_dry_run_plans IS
    'Tenant-scoped metadata-only Legacy SQL import dry-run plans. Row counts, checksum manifest strategy, audit event requirements, and staging metadata profile bindings are stored without raw legacy rows, sample values, cell values, DSNs, Secret references, prompts, outputs, or import payloads.';

COMMENT ON COLUMN crm_erp_legacy.import_dry_run_plans.table_plans IS
    'Per source table metadata-only dry-run contracts binding staging metadata profile object IDs to row-count, checksum, manifest hash, and audit requirements.';

CREATE INDEX IF NOT EXISTS crm_erp_legacy_import_dry_run_plans_source_idx
    ON crm_erp_legacy.import_dry_run_plans (
        tenant_id,
        source_system_ref,
        status,
        created_at_utc DESC
    );

CREATE INDEX IF NOT EXISTS crm_erp_legacy_import_dry_run_plans_evidence_idx
    ON crm_erp_legacy.import_dry_run_plans (
        tenant_id,
        discovery_manifest_hash,
        mapping_manifest_hash,
        readiness_evidence_hash,
        staging_metadata_plan_hash
    );

ALTER TABLE crm_erp_legacy.import_dry_run_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE crm_erp_legacy.import_dry_run_plans FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS crm_erp_legacy_import_dry_run_plans_tenant_select
    ON crm_erp_legacy.import_dry_run_plans;
CREATE POLICY crm_erp_legacy_import_dry_run_plans_tenant_select
    ON crm_erp_legacy.import_dry_run_plans
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS crm_erp_legacy_import_dry_run_plans_tenant_insert
    ON crm_erp_legacy.import_dry_run_plans;
CREATE POLICY crm_erp_legacy_import_dry_run_plans_tenant_insert
    ON crm_erp_legacy.import_dry_run_plans
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS crm_erp_legacy_import_dry_run_plans_no_update
    ON crm_erp_legacy.import_dry_run_plans;
CREATE POLICY crm_erp_legacy_import_dry_run_plans_no_update
    ON crm_erp_legacy.import_dry_run_plans
    FOR UPDATE
    USING (false);

DROP POLICY IF EXISTS crm_erp_legacy_import_dry_run_plans_no_hard_delete
    ON crm_erp_legacy.import_dry_run_plans;
CREATE POLICY crm_erp_legacy_import_dry_run_plans_no_hard_delete
    ON crm_erp_legacy.import_dry_run_plans
    FOR DELETE
    USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE crm_erp_legacy.import_dry_run_plans TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE crm_erp_legacy.import_dry_run_plans TO collabio_worker';
    END IF;
END
$$;

UPDATE collabio.module_catalog
SET required_migration_versions = '["0007", "0008", "0009", "0010", "0011", "0016", "0017", "0018", "0019", "0020", "0034", "0035", "0036", "0037", "0038", "0039", "0040"]'::jsonb
WHERE module_id = 'crm_erp';
