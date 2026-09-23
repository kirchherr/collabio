-- 0047_lms_package_install_approval_records.sql
-- Tenant-scoped append-only LMS package-install approval record store.
-- This migration stores approval metadata only; package installation and runtime activation remain forbidden.

CREATE TABLE IF NOT EXISTS lms.package_install_approval_records (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    module_id text NOT NULL DEFAULT 'lms' CHECK (module_id = 'lms'),
    approval_gate_evidence_hash text NOT NULL CHECK (approval_gate_evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    lms_restore_drill_evidence_hash text NOT NULL CHECK (
        lms_restore_drill_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    command_hash text NOT NULL CHECK (command_hash ~ '^sha256:[a-f0-9]{64}$'),
    idempotency_key_hash text NOT NULL CHECK (idempotency_key_hash ~ '^sha256:[a-f0-9]{64}$'),
    human_confirmation_statement_hash text NOT NULL CHECK (
        human_confirmation_statement_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    approval_record_ref text NOT NULL CHECK (approval_record_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    approval_ticket_ref text NOT NULL CHECK (approval_ticket_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    human_confirmation_reference text NOT NULL CHECK (
        human_confirmation_reference ~ '^[a-z0-9][a-z0-9_+.-]*:.+'
    ),
    change_request_ref text NOT NULL CHECK (change_request_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    approved_by text NOT NULL CHECK (approved_by <> ''),
    approved_at_utc timestamptz NOT NULL,
    record_status text NOT NULL DEFAULT 'approved_for_package_installation_execution_gate' CHECK (
        record_status IN ('approved_for_package_installation_execution_gate', 'blocked', 'expired', 'revoked')
    ),
    future_package_installation_execution_gate_required boolean NOT NULL DEFAULT true CHECK (
        future_package_installation_execution_gate_required
    ),
    package_installation_execution_allowed boolean NOT NULL DEFAULT false CHECK (
        package_installation_execution_allowed = false
    ),
    tenant_provisioning_allowed boolean NOT NULL DEFAULT false CHECK (tenant_provisioning_allowed = false),
    migration_execution_allowed boolean NOT NULL DEFAULT false CHECK (migration_execution_allowed = false),
    lms_business_api_allowed boolean NOT NULL DEFAULT false CHECK (lms_business_api_allowed = false),
    package_installation_executed boolean NOT NULL DEFAULT false CHECK (package_installation_executed = false),
    module_activation_executed boolean NOT NULL DEFAULT false CHECK (module_activation_executed = false),
    tenant_module_state_created boolean NOT NULL DEFAULT false CHECK (tenant_module_state_created = false),
    content_included boolean NOT NULL DEFAULT false CHECK (content_included = false),
    destructive_actions_allowed boolean NOT NULL DEFAULT false CHECK (destructive_actions_allowed = false),
    external_side_effect_allowed boolean NOT NULL DEFAULT false CHECK (external_side_effect_allowed = false),
    approval_record jsonb NOT NULL CHECK (
        jsonb_typeof(approval_record) = 'object'
        AND approval_record ?& ARRAY[
            'schema_version',
            'tenant_id',
            'module_id',
            'approval_gate_evidence_hash',
            'lms_restore_drill_evidence_hash',
            'command_hash',
            'idempotency_key_hash',
            'human_confirmation_statement_hash',
            'approval_record_ref',
            'approval_ticket_ref',
            'human_confirmation_reference',
            'change_request_ref',
            'audit_chain_ref',
            'approved_by',
            'approved_at_utc',
            'record_status',
            'future_package_installation_execution_gate_required',
            'package_installation_execution_allowed',
            'tenant_provisioning_allowed',
            'migration_execution_allowed',
            'lms_business_api_allowed',
            'package_installation_executed',
            'module_activation_executed',
            'tenant_module_state_created',
            'content_included',
            'destructive_actions_allowed',
            'external_side_effect_allowed',
            'evidence_hash'
        ]
        AND approval_record ->> 'schema_version' = 'lms_tenant_admin_package_approval_record.v1'
        AND NOT (approval_record ? 'human_confirmation_statement')
        AND NOT (approval_record ? 'course_content')
        AND NOT (approval_record ? 'training_content')
        AND NOT (approval_record ? 'raw_payload')
        AND (approval_record ->> 'future_package_installation_execution_gate_required')::boolean = true
        AND (approval_record ->> 'package_installation_execution_allowed')::boolean = false
        AND (approval_record ->> 'tenant_provisioning_allowed')::boolean = false
        AND (approval_record ->> 'migration_execution_allowed')::boolean = false
        AND (approval_record ->> 'lms_business_api_allowed')::boolean = false
        AND (approval_record ->> 'package_installation_executed')::boolean = false
        AND (approval_record ->> 'module_activation_executed')::boolean = false
        AND (approval_record ->> 'tenant_module_state_created')::boolean = false
        AND (approval_record ->> 'content_included')::boolean = false
        AND (approval_record ->> 'destructive_actions_allowed')::boolean = false
        AND (approval_record ->> 'external_side_effect_allowed')::boolean = false
    ),
    evidence_hash text NOT NULL CHECK (evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    schema_version text NOT NULL DEFAULT 'lms_tenant_admin_package_approval_record.v1' CHECK (
        schema_version = 'lms_tenant_admin_package_approval_record.v1'
    ),
    PRIMARY KEY (tenant_id, evidence_hash),
    UNIQUE (tenant_id, approval_gate_evidence_hash),
    UNIQUE (tenant_id, idempotency_key_hash),
    UNIQUE (tenant_id, approval_record_ref),
    CHECK ((approval_record ->> 'tenant_id') = tenant_id),
    CHECK ((approval_record ->> 'module_id') = module_id),
    CHECK ((approval_record ->> 'approval_gate_evidence_hash') = approval_gate_evidence_hash),
    CHECK ((approval_record ->> 'lms_restore_drill_evidence_hash') = lms_restore_drill_evidence_hash),
    CHECK ((approval_record ->> 'command_hash') = command_hash),
    CHECK ((approval_record ->> 'idempotency_key_hash') = idempotency_key_hash),
    CHECK ((approval_record ->> 'human_confirmation_statement_hash') = human_confirmation_statement_hash),
    CHECK ((approval_record ->> 'approval_record_ref') = approval_record_ref),
    CHECK ((approval_record ->> 'approval_ticket_ref') = approval_ticket_ref),
    CHECK ((approval_record ->> 'human_confirmation_reference') = human_confirmation_reference),
    CHECK ((approval_record ->> 'change_request_ref') = change_request_ref),
    CHECK ((approval_record ->> 'audit_chain_ref') = audit_chain_ref),
    CHECK ((approval_record ->> 'approved_by') = approved_by),
    CHECK ((approval_record ->> 'record_status') = record_status),
    CHECK ((approval_record ->> 'evidence_hash') = evidence_hash),
    CHECK (position('"human_confirmation_statement"' in lower(approval_record::text)) = 0),
    CHECK (position('"course_content"' in lower(approval_record::text)) = 0),
    CHECK (position('"training_content"' in lower(approval_record::text)) = 0),
    CHECK (position('"raw_payload"' in lower(approval_record::text)) = 0),
    CHECK (position('"password"' in lower(approval_record::text)) = 0)
);

COMMENT ON TABLE lms.package_install_approval_records IS
    'Tenant-scoped append-only LMS package-install approval records. Stores only refs, hashes, approver metadata, restore evidence and audit-chain references; package installation, tenant module state creation, LMS runtime activation, content payloads, destructive actions and external side effects remain forbidden.';

COMMENT ON COLUMN lms.package_install_approval_records.approval_record IS
    'lms_tenant_admin_package_approval_record.v1 JSON without cleartext human confirmation statement or LMS content. The record authorizes only a future package-installation execution gate.';

CREATE INDEX IF NOT EXISTS lms_package_install_approval_records_gate_idx
    ON lms.package_install_approval_records (
        tenant_id,
        approval_gate_evidence_hash,
        record_status,
        approved_at_utc
    );

CREATE INDEX IF NOT EXISTS lms_package_install_approval_records_chain_idx
    ON lms.package_install_approval_records (
        tenant_id,
        lms_restore_drill_evidence_hash,
        command_hash,
        idempotency_key_hash
    );

ALTER TABLE lms.package_install_approval_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE lms.package_install_approval_records FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS lms_package_install_approval_records_tenant_select
    ON lms.package_install_approval_records;
CREATE POLICY lms_package_install_approval_records_tenant_select
    ON lms.package_install_approval_records
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS lms_package_install_approval_records_tenant_insert
    ON lms.package_install_approval_records;
CREATE POLICY lms_package_install_approval_records_tenant_insert
    ON lms.package_install_approval_records
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS lms_package_install_approval_records_no_update
    ON lms.package_install_approval_records;
CREATE POLICY lms_package_install_approval_records_no_update
    ON lms.package_install_approval_records
    FOR UPDATE
    USING (false);

DROP POLICY IF EXISTS lms_package_install_approval_records_no_hard_delete
    ON lms.package_install_approval_records;
CREATE POLICY lms_package_install_approval_records_no_hard_delete
    ON lms.package_install_approval_records
    FOR DELETE
    USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE lms.package_install_approval_records TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE lms.package_install_approval_records TO collabio_worker';
    END IF;
END
$$;

UPDATE collabio.module_catalog
SET required_migration_versions = '["0045", "0046", "0047"]'::jsonb
WHERE module_id = 'lms';
