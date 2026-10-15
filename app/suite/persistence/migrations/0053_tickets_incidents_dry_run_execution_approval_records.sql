-- 0053_tickets_incidents_dry_run_execution_approval_records.sql
-- Tenant-scoped append-only approval evidence. This table never queues or executes work.

CREATE TABLE IF NOT EXISTS tickets.activation_dry_run_execution_approval_records (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    module_id text NOT NULL DEFAULT 'tickets_incidents' CHECK (module_id = 'tickets_incidents'),
    approval_boundary_evidence_hash text NOT NULL CHECK (
        approval_boundary_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    tenant_admin_approval_record_hash text NOT NULL CHECK (
        tenant_admin_approval_record_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    tickets_restore_drill_evidence_hash text NOT NULL CHECK (
        tickets_restore_drill_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    command_hash text NOT NULL CHECK (command_hash ~ '^sha256:[a-f0-9]{64}$'),
    idempotency_key_hash text NOT NULL CHECK (idempotency_key_hash ~ '^sha256:[a-f0-9]{64}$'),
    confirmation_statement_hash text NOT NULL CHECK (
        confirmation_statement_hash ~ '^sha256:[a-f0-9]{64}$'
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
    approval_record jsonb NOT NULL CHECK (
        jsonb_typeof(approval_record) = 'object'
        AND approval_record ->> 'schema_version'
            = 'tickets_incidents_activation_dry_run_execution_approval_record.v1'
        AND NOT (approval_record ? 'human_confirmation_statement')
        AND NOT (approval_record ? 'ticket_content')
        AND NOT (approval_record ? 'raw_payload')
        AND (approval_record ->> 'explicit_human_execution_approval_present')::boolean = true
        AND (approval_record ->> 'worker_execution_allowed')::boolean = false
        AND (approval_record ->> 'activation_dry_run_execution_allowed')::boolean = false
        AND (approval_record ->> 'tickets_business_api_allowed')::boolean = false
    ),
    evidence_hash text NOT NULL CHECK (evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    schema_version text NOT NULL DEFAULT
        'tickets_incidents_activation_dry_run_execution_approval_record.v1' CHECK (
            schema_version = 'tickets_incidents_activation_dry_run_execution_approval_record.v1'
        ),
    PRIMARY KEY (tenant_id, evidence_hash),
    UNIQUE (tenant_id, approval_boundary_evidence_hash),
    UNIQUE (tenant_id, idempotency_key_hash),
    UNIQUE (tenant_id, approval_record_ref),
    CHECK ((approval_record ->> 'tenant_id') = tenant_id),
    CHECK ((approval_record ->> 'module_id') = module_id),
    CHECK ((approval_record ->> 'evidence_hash') = evidence_hash),
    CHECK (position('"human_confirmation_statement"' in lower(approval_record::text)) = 0),
    CHECK (position('"ticket_content"' in lower(approval_record::text)) = 0),
    CHECK (position('"password"' in lower(approval_record::text)) = 0)
);

COMMENT ON TABLE tickets.activation_dry_run_execution_approval_records IS
    'Append-only human approval metadata for a future Tickets activation dry-run. No content, job, worker or activation state.';

ALTER TABLE tickets.activation_dry_run_execution_approval_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE tickets.activation_dry_run_execution_approval_records FORCE ROW LEVEL SECURITY;

CREATE POLICY tickets_activation_dry_run_approval_records_tenant_select
    ON tickets.activation_dry_run_execution_approval_records
    FOR SELECT USING (tenant_id = collabio.current_tenant_id());

CREATE POLICY tickets_activation_dry_run_approval_records_tenant_insert
    ON tickets.activation_dry_run_execution_approval_records
    FOR INSERT WITH CHECK (tenant_id = collabio.current_tenant_id());

CREATE POLICY tickets_activation_dry_run_approval_records_no_update
    ON tickets.activation_dry_run_execution_approval_records
    FOR UPDATE USING (false);

CREATE POLICY tickets_activation_dry_run_approval_records_no_hard_delete
    ON tickets.activation_dry_run_execution_approval_records
    FOR DELETE USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE tickets.activation_dry_run_execution_approval_records TO collabio_app';
    END IF;
END
$$;

UPDATE collabio.module_catalog
SET required_migration_versions = '["0051", "0052", "0053"]'::jsonb
WHERE module_id = 'tickets_incidents';
