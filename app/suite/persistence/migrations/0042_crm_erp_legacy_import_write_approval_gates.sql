-- 0042_crm_erp_legacy_import_write_approval_gates.sql
-- Tenant-scoped append-only Legacy SQL import write approval gate evidence.
-- This migration stores review/change/restore evidence only; it never enables import write execution.

CREATE TABLE IF NOT EXISTS crm_erp_legacy.import_write_approval_gates (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    module_id text NOT NULL DEFAULT 'crm_erp' CHECK (module_id = 'crm_erp'),
    source_system_ref text NOT NULL CHECK (source_system_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    dry_run_plan_hash text NOT NULL CHECK (dry_run_plan_hash ~ '^sha256:[a-f0-9]{64}$'),
    dry_run_result_hash text NOT NULL CHECK (dry_run_result_hash ~ '^sha256:[a-f0-9]{64}$'),
    dry_run_worker_report_hash text NOT NULL CHECK (dry_run_worker_report_hash ~ '^sha256:[a-f0-9]{64}$'),
    approval_review_evidence_hash text NOT NULL CHECK (
        approval_review_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    change_control_evidence_hash text NOT NULL CHECK (
        change_control_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    restore_drill_evidence_hash text NOT NULL CHECK (
        restore_drill_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    gate_status text NOT NULL CHECK (gate_status IN ('ready_for_human_approval_record', 'blocked')),
    human_approval_record_allowed boolean NOT NULL,
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
    blocking_reasons jsonb NOT NULL DEFAULT '[]'::jsonb CHECK (
        jsonb_typeof(blocking_reasons) = 'array'
    ),
    checked_by text NOT NULL CHECK (checked_by <> ''),
    checked_at_utc timestamptz NOT NULL,
    gate_evidence jsonb NOT NULL CHECK (
        jsonb_typeof(gate_evidence) = 'object'
        AND gate_evidence ->> 'schema_version' = 'legacy_sql_import_write_approval_gate.v1'
        AND NOT (gate_evidence ? 'connection_secret_ref')
        AND NOT (gate_evidence ? 'raw_payload')
        AND NOT (gate_evidence ? 'import_write_payload')
        AND (gate_evidence ->> 'future_import_write_execution_gate_required')::boolean = true
        AND (gate_evidence ->> 'import_write_execution_allowed')::boolean = false
        AND (gate_evidence ->> 'raw_data_access_allowed')::boolean = false
        AND (gate_evidence ->> 'import_write_payload_allowed')::boolean = false
        AND (gate_evidence ->> 'destructive_actions_allowed')::boolean = false
        AND (gate_evidence ->> 'external_side_effect_allowed')::boolean = false
    ),
    evidence_hash text NOT NULL CHECK (evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    schema_version text NOT NULL DEFAULT 'legacy_sql_import_write_approval_gate.v1' CHECK (
        schema_version = 'legacy_sql_import_write_approval_gate.v1'
    ),
    PRIMARY KEY (tenant_id, evidence_hash),
    CHECK ((gate_evidence ->> 'tenant_id') = tenant_id),
    CHECK ((gate_evidence ->> 'module_id') = module_id),
    CHECK ((gate_evidence ->> 'source_system_ref') = source_system_ref),
    CHECK ((gate_evidence ->> 'dry_run_plan_hash') = dry_run_plan_hash),
    CHECK ((gate_evidence ->> 'dry_run_result_hash') = dry_run_result_hash),
    CHECK ((gate_evidence ->> 'dry_run_worker_report_hash') = dry_run_worker_report_hash),
    CHECK ((gate_evidence ->> 'approval_review_evidence_hash') = approval_review_evidence_hash),
    CHECK ((gate_evidence ->> 'change_control_evidence_hash') = change_control_evidence_hash),
    CHECK ((gate_evidence ->> 'restore_drill_evidence_hash') = restore_drill_evidence_hash),
    CHECK ((gate_evidence ->> 'gate_status') = gate_status),
    CHECK ((gate_evidence ->> 'evidence_hash') = evidence_hash),
    CHECK (jsonb_array_length(blocking_reasons) = jsonb_array_length(gate_evidence -> 'blocking_reasons')),
    CHECK (
        (
            gate_status = 'ready_for_human_approval_record'
            AND human_approval_record_allowed
            AND jsonb_array_length(blocking_reasons) = 0
        )
        OR (
            gate_status = 'blocked'
            AND human_approval_record_allowed = false
            AND jsonb_array_length(blocking_reasons) >= 1
        )
    )
);

COMMENT ON TABLE crm_erp_legacy.import_write_approval_gates IS
    'Tenant-scoped append-only Legacy SQL import write approval gate evidence. Stores dry-run result hashes, dry-run worker report hashes, human review, change-control, rollback, and restore drill evidence without raw legacy rows, sample values, cell values, DSNs, Secret references, prompts, outputs, import write payloads, external side effects, or import write execution.';

COMMENT ON COLUMN crm_erp_legacy.import_write_approval_gates.gate_evidence IS
    'legacy_sql_import_write_approval_gate.v1 JSON. This may allow only a future human approval record; import write execution, raw data access, destructive actions, external side effects, prompts, outputs, embeddings, transcripts, and import write payloads remain excluded.';

CREATE INDEX IF NOT EXISTS crm_erp_legacy_import_write_approval_gates_result_idx
    ON crm_erp_legacy.import_write_approval_gates (
        tenant_id,
        dry_run_result_hash,
        gate_status,
        checked_at_utc
    );

CREATE INDEX IF NOT EXISTS crm_erp_legacy_import_write_approval_gates_chain_idx
    ON crm_erp_legacy.import_write_approval_gates (
        tenant_id,
        dry_run_plan_hash,
        dry_run_worker_report_hash,
        approval_review_evidence_hash,
        change_control_evidence_hash,
        restore_drill_evidence_hash
    );

ALTER TABLE crm_erp_legacy.import_write_approval_gates ENABLE ROW LEVEL SECURITY;
ALTER TABLE crm_erp_legacy.import_write_approval_gates FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS crm_erp_legacy_import_write_approval_gates_tenant_select
    ON crm_erp_legacy.import_write_approval_gates;
CREATE POLICY crm_erp_legacy_import_write_approval_gates_tenant_select
    ON crm_erp_legacy.import_write_approval_gates
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS crm_erp_legacy_import_write_approval_gates_tenant_insert
    ON crm_erp_legacy.import_write_approval_gates;
CREATE POLICY crm_erp_legacy_import_write_approval_gates_tenant_insert
    ON crm_erp_legacy.import_write_approval_gates
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS crm_erp_legacy_import_write_approval_gates_no_update
    ON crm_erp_legacy.import_write_approval_gates;
CREATE POLICY crm_erp_legacy_import_write_approval_gates_no_update
    ON crm_erp_legacy.import_write_approval_gates
    FOR UPDATE
    USING (false);

DROP POLICY IF EXISTS crm_erp_legacy_import_write_approval_gates_no_hard_delete
    ON crm_erp_legacy.import_write_approval_gates;
CREATE POLICY crm_erp_legacy_import_write_approval_gates_no_hard_delete
    ON crm_erp_legacy.import_write_approval_gates
    FOR DELETE
    USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE crm_erp_legacy.import_write_approval_gates TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE crm_erp_legacy.import_write_approval_gates TO collabio_worker';
    END IF;
END
$$;

UPDATE collabio.module_catalog
SET required_migration_versions = '["0007", "0008", "0009", "0010", "0011", "0016", "0017", "0018", "0019", "0020", "0034", "0035", "0036", "0037", "0038", "0039", "0040", "0041", "0042"]'::jsonb
WHERE module_id = 'crm_erp';
