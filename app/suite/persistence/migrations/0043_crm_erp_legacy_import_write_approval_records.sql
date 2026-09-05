-- 0043_crm_erp_legacy_import_write_approval_records.sql
-- Tenant-scoped append-only Legacy SQL import write approval record store.
-- This migration prepares human approval record persistence only; import write execution remains forbidden.

CREATE TABLE IF NOT EXISTS crm_erp_legacy.import_write_approval_records (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    module_id text NOT NULL DEFAULT 'crm_erp' CHECK (module_id = 'crm_erp'),
    source_system_ref text NOT NULL CHECK (source_system_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    dry_run_result_hash text NOT NULL CHECK (dry_run_result_hash ~ '^sha256:[a-f0-9]{64}$'),
    approval_request_boundary_evidence_hash text NOT NULL CHECK (
        approval_request_boundary_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    approval_gate_evidence_hash text NOT NULL CHECK (approval_gate_evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    approval_request_hash text NOT NULL CHECK (approval_request_hash ~ '^sha256:[a-f0-9]{64}$'),
    persistence_plan_evidence_hash text NOT NULL CHECK (persistence_plan_evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    approval_record_ref text NOT NULL CHECK (approval_record_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    approval_ticket_ref text NOT NULL CHECK (approval_ticket_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    human_confirmation_reference text NOT NULL CHECK (
        human_confirmation_reference ~ '^[a-z0-9][a-z0-9_+.-]*:.+'
    ),
    idempotency_key_hash text NOT NULL CHECK (idempotency_key_hash ~ '^sha256:[a-f0-9]{64}$'),
    approved_by text NOT NULL CHECK (approved_by <> ''),
    approved_at_utc timestamptz NOT NULL,
    record_status text NOT NULL DEFAULT 'approved_for_future_import_write_gate' CHECK (
        record_status IN ('approved_for_future_import_write_gate', 'rejected', 'expired')
    ),
    future_import_write_execution_gate_required boolean NOT NULL DEFAULT true CHECK (
        future_import_write_execution_gate_required
    ),
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
    restore_evidence_hash text NOT NULL CHECK (restore_evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    audit_event_id text NOT NULL CHECK (audit_event_id <> ''),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    approval_record jsonb NOT NULL CHECK (
        jsonb_typeof(approval_record) = 'object'
        AND approval_record ?& ARRAY[
            'schema_version',
            'tenant_id',
            'module_id',
            'source_system_ref',
            'dry_run_result_hash',
            'approval_request_boundary_evidence_hash',
            'approval_gate_evidence_hash',
            'approval_request_hash',
            'persistence_plan_evidence_hash',
            'approval_record_ref',
            'approval_ticket_ref',
            'human_confirmation_reference',
            'idempotency_key_hash',
            'approved_by',
            'approved_at_utc',
            'record_status',
            'future_import_write_execution_gate_required',
            'import_write_execution_allowed',
            'raw_data_access_allowed',
            'import_write_payload_allowed',
            'destructive_actions_allowed',
            'external_side_effect_allowed',
            'restore_evidence_hash',
            'audit_event_id',
            'audit_chain_ref',
            'evidence_hash'
        ]
        AND approval_record ->> 'schema_version' = 'legacy_sql_import_write_approval_record.v1'
        AND NOT (approval_record ? 'connection_secret_ref')
        AND NOT (approval_record ? 'raw_payload')
        AND NOT (approval_record ? 'sample_values')
        AND NOT (approval_record ? 'import_write_payload')
        AND (approval_record ->> 'future_import_write_execution_gate_required')::boolean = true
        AND (approval_record ->> 'import_write_execution_allowed')::boolean = false
        AND (approval_record ->> 'raw_data_access_allowed')::boolean = false
        AND (approval_record ->> 'import_write_payload_allowed')::boolean = false
        AND (approval_record ->> 'destructive_actions_allowed')::boolean = false
        AND (approval_record ->> 'external_side_effect_allowed')::boolean = false
    ),
    evidence_hash text NOT NULL CHECK (evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    schema_version text NOT NULL DEFAULT 'legacy_sql_import_write_approval_record.v1' CHECK (
        schema_version = 'legacy_sql_import_write_approval_record.v1'
    ),
    PRIMARY KEY (tenant_id, evidence_hash),
    UNIQUE (tenant_id, approval_request_boundary_evidence_hash),
    UNIQUE (tenant_id, idempotency_key_hash),
    UNIQUE (tenant_id, approval_record_ref),
    CHECK ((approval_record ->> 'tenant_id') = tenant_id),
    CHECK ((approval_record ->> 'module_id') = module_id),
    CHECK ((approval_record ->> 'source_system_ref') = source_system_ref),
    CHECK ((approval_record ->> 'dry_run_result_hash') = dry_run_result_hash),
    CHECK (
        (approval_record ->> 'approval_request_boundary_evidence_hash')
        = approval_request_boundary_evidence_hash
    ),
    CHECK ((approval_record ->> 'approval_gate_evidence_hash') = approval_gate_evidence_hash),
    CHECK ((approval_record ->> 'approval_request_hash') = approval_request_hash),
    CHECK ((approval_record ->> 'persistence_plan_evidence_hash') = persistence_plan_evidence_hash),
    CHECK ((approval_record ->> 'approval_record_ref') = approval_record_ref),
    CHECK ((approval_record ->> 'approval_ticket_ref') = approval_ticket_ref),
    CHECK ((approval_record ->> 'human_confirmation_reference') = human_confirmation_reference),
    CHECK ((approval_record ->> 'idempotency_key_hash') = idempotency_key_hash),
    CHECK ((approval_record ->> 'approved_by') = approved_by),
    CHECK ((approval_record ->> 'record_status') = record_status),
    CHECK ((approval_record ->> 'restore_evidence_hash') = restore_evidence_hash),
    CHECK ((approval_record ->> 'audit_event_id') = audit_event_id),
    CHECK ((approval_record ->> 'audit_chain_ref') = audit_chain_ref),
    CHECK ((approval_record ->> 'evidence_hash') = evidence_hash),
    CHECK (position('connection_secret_ref' in approval_record::text) = 0),
    CHECK (position('sqlserver://' in lower(approval_record::text)) = 0),
    CHECK (position('"password"' in lower(approval_record::text)) = 0),
    CHECK (position('"raw_payload"' in lower(approval_record::text)) = 0),
    CHECK (position('"sample_values"' in lower(approval_record::text)) = 0),
    CHECK (position('"import_write_payload"' in lower(approval_record::text)) = 0)
);

COMMENT ON TABLE crm_erp_legacy.import_write_approval_records IS
    'Tenant-scoped append-only Legacy SQL import write approval record store. Stores only human approval record metadata, hash links, idempotency keys, restore evidence and audit references; import write execution, raw legacy rows, sample values, Secret references, prompts, outputs, import write payloads, destructive actions and external side effects remain forbidden.';

COMMENT ON COLUMN crm_erp_legacy.import_write_approval_records.approval_record IS
    'legacy_sql_import_write_approval_record.v1 JSON. The record can authorize only a future import-write execution gate; it cannot execute imports or carry raw source data.';

CREATE INDEX IF NOT EXISTS crm_erp_legacy_import_write_approval_records_result_idx
    ON crm_erp_legacy.import_write_approval_records (
        tenant_id,
        dry_run_result_hash,
        record_status,
        approved_at_utc
    );

CREATE INDEX IF NOT EXISTS crm_erp_legacy_import_write_approval_records_chain_idx
    ON crm_erp_legacy.import_write_approval_records (
        tenant_id,
        approval_gate_evidence_hash,
        approval_request_boundary_evidence_hash,
        persistence_plan_evidence_hash
    );

ALTER TABLE crm_erp_legacy.import_write_approval_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE crm_erp_legacy.import_write_approval_records FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS crm_erp_legacy_import_write_approval_records_tenant_select
    ON crm_erp_legacy.import_write_approval_records;
CREATE POLICY crm_erp_legacy_import_write_approval_records_tenant_select
    ON crm_erp_legacy.import_write_approval_records
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS crm_erp_legacy_import_write_approval_records_tenant_insert
    ON crm_erp_legacy.import_write_approval_records;
CREATE POLICY crm_erp_legacy_import_write_approval_records_tenant_insert
    ON crm_erp_legacy.import_write_approval_records
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS crm_erp_legacy_import_write_approval_records_no_update
    ON crm_erp_legacy.import_write_approval_records;
CREATE POLICY crm_erp_legacy_import_write_approval_records_no_update
    ON crm_erp_legacy.import_write_approval_records
    FOR UPDATE
    USING (false);

DROP POLICY IF EXISTS crm_erp_legacy_import_write_approval_records_no_hard_delete
    ON crm_erp_legacy.import_write_approval_records;
CREATE POLICY crm_erp_legacy_import_write_approval_records_no_hard_delete
    ON crm_erp_legacy.import_write_approval_records
    FOR DELETE
    USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE crm_erp_legacy.import_write_approval_records TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE crm_erp_legacy.import_write_approval_records TO collabio_worker';
    END IF;
END
$$;

UPDATE collabio.module_catalog
SET required_migration_versions = '["0007", "0008", "0009", "0010", "0011", "0016", "0017", "0018", "0019", "0020", "0034", "0035", "0036", "0037", "0038", "0039", "0040", "0041", "0042", "0043"]'::jsonb
WHERE module_id = 'crm_erp';
