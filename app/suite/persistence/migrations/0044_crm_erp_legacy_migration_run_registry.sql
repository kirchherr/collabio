-- 0044_crm_erp_legacy_migration_run_registry.sql
-- Tenant-scoped append-only Legacy SQL migration run registry and metadata-only report skeleton.
-- This prepares future migration API state only; import write execution remains forbidden.

CREATE TABLE IF NOT EXISTS crm_erp_legacy.migration_runs (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    module_id text NOT NULL DEFAULT 'crm_erp' CHECK (module_id = 'crm_erp'),
    source_system_ref text NOT NULL CHECK (source_system_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    migration_run_ref text NOT NULL CHECK (migration_run_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    approval_record_hash text NOT NULL CHECK (approval_record_hash ~ '^sha256:[a-f0-9]{64}$'),
    approval_gate_evidence_hash text NOT NULL CHECK (approval_gate_evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    dry_run_result_hash text NOT NULL CHECK (dry_run_result_hash ~ '^sha256:[a-f0-9]{64}$'),
    idempotency_key_hash text NOT NULL CHECK (idempotency_key_hash ~ '^sha256:[a-f0-9]{64}$'),
    requested_by text NOT NULL CHECK (requested_by <> ''),
    requested_at_utc timestamptz NOT NULL,
    run_status text NOT NULL DEFAULT 'planned_metadata_only' CHECK (
        run_status IN ('planned_metadata_only', 'approval_pending', 'approval_granted', 'cancelled', 'blocked')
    ),
    future_import_write_execution_gate_required boolean NOT NULL DEFAULT true CHECK (
        future_import_write_execution_gate_required
    ),
    run_creation_enabled boolean NOT NULL DEFAULT false CHECK (run_creation_enabled = false),
    run_execution_allowed boolean NOT NULL DEFAULT false CHECK (run_execution_allowed = false),
    import_write_execution_allowed boolean NOT NULL DEFAULT false CHECK (
        import_write_execution_allowed = false
    ),
    raw_data_access_allowed boolean NOT NULL DEFAULT false CHECK (raw_data_access_allowed = false),
    import_write_payload_allowed boolean NOT NULL DEFAULT false CHECK (
        import_write_payload_allowed = false
    ),
    destructive_actions_allowed boolean NOT NULL DEFAULT false CHECK (
        destructive_actions_allowed = false
    ),
    external_side_effect_allowed boolean NOT NULL DEFAULT false CHECK (
        external_side_effect_allowed = false
    ),
    metadata_only_report_required boolean NOT NULL DEFAULT true CHECK (metadata_only_report_required),
    restore_evidence_hash text NOT NULL CHECK (restore_evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    audit_event_id text NOT NULL CHECK (audit_event_id <> ''),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    migration_run jsonb NOT NULL CHECK (
        jsonb_typeof(migration_run) = 'object'
        AND migration_run ?& ARRAY[
            'schema_version',
            'tenant_id',
            'module_id',
            'source_system_ref',
            'migration_run_ref',
            'approval_record_hash',
            'approval_gate_evidence_hash',
            'dry_run_result_hash',
            'idempotency_key_hash',
            'requested_by',
            'requested_at_utc',
            'run_status',
            'future_import_write_execution_gate_required',
            'run_creation_enabled',
            'run_execution_allowed',
            'import_write_execution_allowed',
            'raw_data_access_allowed',
            'import_write_payload_allowed',
            'destructive_actions_allowed',
            'external_side_effect_allowed',
            'metadata_only_report_required',
            'restore_evidence_hash',
            'audit_event_id',
            'audit_chain_ref',
            'evidence_hash'
        ]
        AND migration_run ->> 'schema_version' = 'legacy_sql_migration_run_registry_entry.v1'
        AND NOT (migration_run ? 'connection_secret_ref')
        AND NOT (migration_run ? 'raw_payload')
        AND NOT (migration_run ? 'sample_values')
        AND NOT (migration_run ? 'import_write_payload')
        AND (migration_run ->> 'future_import_write_execution_gate_required')::boolean = true
        AND (migration_run ->> 'run_creation_enabled')::boolean = false
        AND (migration_run ->> 'run_execution_allowed')::boolean = false
        AND (migration_run ->> 'import_write_execution_allowed')::boolean = false
        AND (migration_run ->> 'raw_data_access_allowed')::boolean = false
        AND (migration_run ->> 'import_write_payload_allowed')::boolean = false
        AND (migration_run ->> 'destructive_actions_allowed')::boolean = false
        AND (migration_run ->> 'external_side_effect_allowed')::boolean = false
        AND (migration_run ->> 'metadata_only_report_required')::boolean = true
    ),
    evidence_hash text NOT NULL CHECK (evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    schema_version text NOT NULL DEFAULT 'legacy_sql_migration_run_registry_entry.v1' CHECK (
        schema_version = 'legacy_sql_migration_run_registry_entry.v1'
    ),
    PRIMARY KEY (tenant_id, evidence_hash),
    UNIQUE (tenant_id, idempotency_key_hash),
    UNIQUE (tenant_id, migration_run_ref),
    CHECK ((migration_run ->> 'tenant_id') = tenant_id),
    CHECK ((migration_run ->> 'module_id') = module_id),
    CHECK ((migration_run ->> 'source_system_ref') = source_system_ref),
    CHECK ((migration_run ->> 'migration_run_ref') = migration_run_ref),
    CHECK ((migration_run ->> 'approval_record_hash') = approval_record_hash),
    CHECK ((migration_run ->> 'approval_gate_evidence_hash') = approval_gate_evidence_hash),
    CHECK ((migration_run ->> 'dry_run_result_hash') = dry_run_result_hash),
    CHECK ((migration_run ->> 'idempotency_key_hash') = idempotency_key_hash),
    CHECK ((migration_run ->> 'requested_by') = requested_by),
    CHECK ((migration_run ->> 'run_status') = run_status),
    CHECK ((migration_run ->> 'restore_evidence_hash') = restore_evidence_hash),
    CHECK ((migration_run ->> 'audit_event_id') = audit_event_id),
    CHECK ((migration_run ->> 'audit_chain_ref') = audit_chain_ref),
    CHECK ((migration_run ->> 'evidence_hash') = evidence_hash),
    CHECK (position('connection_secret_ref' in migration_run::text) = 0),
    CHECK (position('sqlserver://' in lower(migration_run::text)) = 0),
    CHECK (position('"password"' in lower(migration_run::text)) = 0),
    CHECK (position('"raw_payload"' in lower(migration_run::text)) = 0),
    CHECK (position('"sample_values"' in lower(migration_run::text)) = 0),
    CHECK (position('"import_write_payload"' in lower(migration_run::text)) = 0)
);

CREATE TABLE IF NOT EXISTS crm_erp_legacy.migration_reports (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    module_id text NOT NULL DEFAULT 'crm_erp' CHECK (module_id = 'crm_erp'),
    source_system_ref text NOT NULL CHECK (source_system_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    migration_run_hash text NOT NULL CHECK (migration_run_hash ~ '^sha256:[a-f0-9]{64}$'),
    migration_report_ref text NOT NULL CHECK (migration_report_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    idempotency_key_hash text NOT NULL CHECK (idempotency_key_hash ~ '^sha256:[a-f0-9]{64}$'),
    report_status text NOT NULL DEFAULT 'planned_metadata_only' CHECK (
        report_status IN ('planned_metadata_only', 'ready_for_review', 'blocked')
    ),
    planned_table_count integer NOT NULL DEFAULT 0 CHECK (planned_table_count >= 0),
    table_result_count integer NOT NULL DEFAULT 0 CHECK (table_result_count >= 0),
    row_count_manifest_hash text NOT NULL CHECK (row_count_manifest_hash ~ '^sha256:[a-f0-9]{64}$'),
    checksum_manifest_hash text NOT NULL CHECK (checksum_manifest_hash ~ '^sha256:[a-f0-9]{64}$'),
    restore_evidence_hash text NOT NULL CHECK (restore_evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    audit_event_id text NOT NULL CHECK (audit_event_id <> ''),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    metadata_only_ok boolean NOT NULL DEFAULT true CHECK (metadata_only_ok),
    future_import_write_execution_gate_required boolean NOT NULL DEFAULT true CHECK (
        future_import_write_execution_gate_required
    ),
    report_retrieval_enabled boolean NOT NULL DEFAULT false CHECK (report_retrieval_enabled = false),
    run_execution_completed boolean NOT NULL DEFAULT false CHECK (run_execution_completed = false),
    import_write_execution_allowed boolean NOT NULL DEFAULT false CHECK (
        import_write_execution_allowed = false
    ),
    raw_data_access_allowed boolean NOT NULL DEFAULT false CHECK (raw_data_access_allowed = false),
    import_write_payload_allowed boolean NOT NULL DEFAULT false CHECK (
        import_write_payload_allowed = false
    ),
    destructive_actions_allowed boolean NOT NULL DEFAULT false CHECK (
        destructive_actions_allowed = false
    ),
    external_side_effect_allowed boolean NOT NULL DEFAULT false CHECK (
        external_side_effect_allowed = false
    ),
    migration_report jsonb NOT NULL CHECK (
        jsonb_typeof(migration_report) = 'object'
        AND migration_report ?& ARRAY[
            'schema_version',
            'tenant_id',
            'module_id',
            'source_system_ref',
            'migration_run_hash',
            'migration_report_ref',
            'idempotency_key_hash',
            'report_status',
            'planned_table_count',
            'table_result_count',
            'row_count_manifest_hash',
            'checksum_manifest_hash',
            'restore_evidence_hash',
            'audit_event_id',
            'audit_chain_ref',
            'metadata_only_ok',
            'future_import_write_execution_gate_required',
            'report_retrieval_enabled',
            'run_execution_completed',
            'import_write_execution_allowed',
            'raw_data_access_allowed',
            'import_write_payload_allowed',
            'destructive_actions_allowed',
            'external_side_effect_allowed',
            'evidence_hash'
        ]
        AND migration_report ->> 'schema_version' = 'legacy_sql_migration_report_metadata.v1'
        AND NOT (migration_report ? 'connection_secret_ref')
        AND NOT (migration_report ? 'raw_payload')
        AND NOT (migration_report ? 'sample_values')
        AND NOT (migration_report ? 'import_write_payload')
        AND (migration_report ->> 'metadata_only_ok')::boolean = true
        AND (migration_report ->> 'future_import_write_execution_gate_required')::boolean = true
        AND (migration_report ->> 'report_retrieval_enabled')::boolean = false
        AND (migration_report ->> 'run_execution_completed')::boolean = false
        AND (migration_report ->> 'import_write_execution_allowed')::boolean = false
        AND (migration_report ->> 'raw_data_access_allowed')::boolean = false
        AND (migration_report ->> 'import_write_payload_allowed')::boolean = false
        AND (migration_report ->> 'destructive_actions_allowed')::boolean = false
        AND (migration_report ->> 'external_side_effect_allowed')::boolean = false
    ),
    evidence_hash text NOT NULL CHECK (evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    schema_version text NOT NULL DEFAULT 'legacy_sql_migration_report_metadata.v1' CHECK (
        schema_version = 'legacy_sql_migration_report_metadata.v1'
    ),
    PRIMARY KEY (tenant_id, evidence_hash),
    UNIQUE (tenant_id, idempotency_key_hash),
    UNIQUE (tenant_id, migration_report_ref),
    CHECK ((migration_report ->> 'tenant_id') = tenant_id),
    CHECK ((migration_report ->> 'module_id') = module_id),
    CHECK ((migration_report ->> 'source_system_ref') = source_system_ref),
    CHECK ((migration_report ->> 'migration_run_hash') = migration_run_hash),
    CHECK ((migration_report ->> 'migration_report_ref') = migration_report_ref),
    CHECK ((migration_report ->> 'idempotency_key_hash') = idempotency_key_hash),
    CHECK ((migration_report ->> 'report_status') = report_status),
    CHECK ((migration_report ->> 'row_count_manifest_hash') = row_count_manifest_hash),
    CHECK ((migration_report ->> 'checksum_manifest_hash') = checksum_manifest_hash),
    CHECK ((migration_report ->> 'restore_evidence_hash') = restore_evidence_hash),
    CHECK ((migration_report ->> 'audit_event_id') = audit_event_id),
    CHECK ((migration_report ->> 'audit_chain_ref') = audit_chain_ref),
    CHECK ((migration_report ->> 'evidence_hash') = evidence_hash),
    CHECK (position('connection_secret_ref' in migration_report::text) = 0),
    CHECK (position('sqlserver://' in lower(migration_report::text)) = 0),
    CHECK (position('"password"' in lower(migration_report::text)) = 0),
    CHECK (position('"raw_payload"' in lower(migration_report::text)) = 0),
    CHECK (position('"sample_values"' in lower(migration_report::text)) = 0),
    CHECK (position('"import_write_payload"' in lower(migration_report::text)) = 0)
);

COMMENT ON TABLE crm_erp_legacy.migration_runs IS
    'Tenant-scoped append-only Legacy SQL migration run registry skeleton. Stores only future run metadata, approval record hashes, idempotency keys, restore evidence and audit references; run creation, import write execution, raw legacy rows, sample values, Secret references, import write payloads, destructive actions and external side effects remain forbidden.';

COMMENT ON TABLE crm_erp_legacy.migration_reports IS
    'Tenant-scoped append-only Legacy SQL migration metadata-only report skeleton. Stores only report hashes, counts, restore evidence and audit references; report retrieval, run execution, raw legacy rows, sample values, import write payloads, destructive actions and external side effects remain forbidden.';

CREATE INDEX IF NOT EXISTS crm_erp_legacy_migration_runs_ref_idx
    ON crm_erp_legacy.migration_runs (
        tenant_id,
        source_system_ref,
        run_status,
        requested_at_utc
    );

CREATE INDEX IF NOT EXISTS crm_erp_legacy_migration_runs_approval_idx
    ON crm_erp_legacy.migration_runs (
        tenant_id,
        approval_record_hash,
        dry_run_result_hash,
        approval_gate_evidence_hash
    );

CREATE INDEX IF NOT EXISTS crm_erp_legacy_migration_reports_run_idx
    ON crm_erp_legacy.migration_reports (
        tenant_id,
        migration_run_hash,
        report_status,
        created_at_utc
    );

ALTER TABLE crm_erp_legacy.migration_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE crm_erp_legacy.migration_runs FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS crm_erp_legacy_migration_runs_tenant_select
    ON crm_erp_legacy.migration_runs;
CREATE POLICY crm_erp_legacy_migration_runs_tenant_select
    ON crm_erp_legacy.migration_runs
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS crm_erp_legacy_migration_runs_tenant_insert
    ON crm_erp_legacy.migration_runs;
CREATE POLICY crm_erp_legacy_migration_runs_tenant_insert
    ON crm_erp_legacy.migration_runs
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS crm_erp_legacy_migration_runs_no_update
    ON crm_erp_legacy.migration_runs;
CREATE POLICY crm_erp_legacy_migration_runs_no_update
    ON crm_erp_legacy.migration_runs
    FOR UPDATE
    USING (false);

DROP POLICY IF EXISTS crm_erp_legacy_migration_runs_no_hard_delete
    ON crm_erp_legacy.migration_runs;
CREATE POLICY crm_erp_legacy_migration_runs_no_hard_delete
    ON crm_erp_legacy.migration_runs
    FOR DELETE
    USING (false);

ALTER TABLE crm_erp_legacy.migration_reports ENABLE ROW LEVEL SECURITY;
ALTER TABLE crm_erp_legacy.migration_reports FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS crm_erp_legacy_migration_reports_tenant_select
    ON crm_erp_legacy.migration_reports;
CREATE POLICY crm_erp_legacy_migration_reports_tenant_select
    ON crm_erp_legacy.migration_reports
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS crm_erp_legacy_migration_reports_tenant_insert
    ON crm_erp_legacy.migration_reports;
CREATE POLICY crm_erp_legacy_migration_reports_tenant_insert
    ON crm_erp_legacy.migration_reports
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS crm_erp_legacy_migration_reports_no_update
    ON crm_erp_legacy.migration_reports;
CREATE POLICY crm_erp_legacy_migration_reports_no_update
    ON crm_erp_legacy.migration_reports
    FOR UPDATE
    USING (false);

DROP POLICY IF EXISTS crm_erp_legacy_migration_reports_no_hard_delete
    ON crm_erp_legacy.migration_reports;
CREATE POLICY crm_erp_legacy_migration_reports_no_hard_delete
    ON crm_erp_legacy.migration_reports
    FOR DELETE
    USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE crm_erp_legacy.migration_runs TO collabio_app';
        EXECUTE 'GRANT SELECT, INSERT ON TABLE crm_erp_legacy.migration_reports TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE crm_erp_legacy.migration_runs TO collabio_worker';
        EXECUTE 'GRANT SELECT, INSERT ON TABLE crm_erp_legacy.migration_reports TO collabio_worker';
    END IF;
END
$$;

UPDATE collabio.module_catalog
SET required_migration_versions = '["0007", "0008", "0009", "0010", "0011", "0016", "0017", "0018", "0019", "0020", "0034", "0035", "0036", "0037", "0038", "0039", "0040", "0041", "0042", "0043", "0044"]'::jsonb
WHERE module_id = 'crm_erp';
