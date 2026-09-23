-- 0060_time_tracking_productive_slice.sql
-- First productive Time Tracking slice with atomic entry, initial approval, ACL and receipt writes.

INSERT INTO collabio.module_catalog (
    module_id, display_name, module_version, module_kind, status, description,
    manifest_hash, required_migration_versions, min_core_version, installed_at_utc
)
VALUES (
    'time_tracking', 'Time Tracking', '0.1.0', 'business_domain', 'installed',
    (
        'Optional governed Time Tracking module with tenant-gated time-entry creation, '
        'initial approval state and authoritative ACL reads. Corrections, approval decisions, '
        'payroll exports and automation remain separate gates.'
    ),
    'sha256:time-tracking-module-manifest', '["0060"]'::jsonb, NULL, now()
)
ON CONFLICT (module_id) DO UPDATE
SET display_name = EXCLUDED.display_name,
    module_version = EXCLUDED.module_version,
    module_kind = EXCLUDED.module_kind,
    status = EXCLUDED.status,
    description = EXCLUDED.description,
    manifest_hash = EXCLUDED.manifest_hash,
    required_migration_versions = EXCLUDED.required_migration_versions,
    installed_at_utc = COALESCE(collabio.module_catalog.installed_at_utc, EXCLUDED.installed_at_utc);

CREATE SCHEMA IF NOT EXISTS time_tracking;

CREATE TABLE IF NOT EXISTS time_tracking.entries (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    object_id text NOT NULL CHECK (object_id <> ''),
    object_type text NOT NULL DEFAULT 'time.entry' CHECK (object_type = 'time.entry'),
    owner_principal_id text NOT NULL CHECK (owner_principal_id <> ''),
    created_by text NOT NULL CHECK (created_by <> ''),
    created_at_utc timestamptz NOT NULL,
    updated_at_utc timestamptz NOT NULL,
    data_classification text NOT NULL DEFAULT 'personal' CHECK (data_classification = 'personal'),
    retention_policy_id text NOT NULL DEFAULT 'rp-standard' CHECK (
        retention_policy_id IN ('rp-standard', 'rp-restricted', 'rp-legal-hold')
    ),
    legal_hold_state text NOT NULL DEFAULT 'none' CHECK (legal_hold_state IN ('none', 'active')),
    lifecycle_state text NOT NULL DEFAULT 'recorded' CHECK (lifecycle_state = 'recorded'),
    kms_key_ref text NOT NULL CHECK (kms_key_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    source_system text NOT NULL DEFAULT 'native' CHECK (source_system ~ '^[a-z][a-z0-9_+.-]*$'),
    schema_version text NOT NULL DEFAULT 'time_entry.v1' CHECK (schema_version = 'time_entry.v1'),
    entry_number text NOT NULL CHECK (entry_number <> ''),
    worker_principal_id text NOT NULL CHECK (worker_principal_id <> ''),
    work_date date NOT NULL,
    started_at_utc timestamptz NOT NULL,
    ended_at_utc timestamptz NOT NULL,
    duration_minutes integer NOT NULL CHECK (duration_minutes BETWEEN 1 AND 1440),
    project_reference text CHECK (
        project_reference IS NULL OR project_reference ~ '^[a-z0-9][a-z0-9_+.-]*:.+'
    ),
    cost_center_reference text CHECK (
        cost_center_reference IS NULL OR cost_center_reference ~ '^[a-z0-9][a-z0-9_+.-]*:.+'
    ),
    PRIMARY KEY (tenant_id, object_id),
    UNIQUE (tenant_id, entry_number),
    CHECK (ended_at_utc > started_at_utc),
    CHECK (EXTRACT(EPOCH FROM (ended_at_utc - started_at_utc)) = duration_minutes * 60),
    CHECK (legal_hold_state <> 'active' OR retention_policy_id = 'rp-legal-hold')
);

CREATE TABLE IF NOT EXISTS time_tracking.approvals (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    object_id text NOT NULL CHECK (object_id <> ''),
    object_type text NOT NULL DEFAULT 'time.approval' CHECK (object_type = 'time.approval'),
    owner_principal_id text NOT NULL CHECK (owner_principal_id <> ''),
    created_by text NOT NULL CHECK (created_by <> ''),
    created_at_utc timestamptz NOT NULL,
    updated_at_utc timestamptz NOT NULL,
    data_classification text NOT NULL DEFAULT 'personal' CHECK (data_classification = 'personal'),
    retention_policy_id text NOT NULL DEFAULT 'rp-standard' CHECK (
        retention_policy_id IN ('rp-standard', 'rp-restricted', 'rp-legal-hold')
    ),
    legal_hold_state text NOT NULL DEFAULT 'none' CHECK (legal_hold_state IN ('none', 'active')),
    lifecycle_state text NOT NULL DEFAULT 'not_submitted' CHECK (lifecycle_state = 'not_submitted'),
    kms_key_ref text NOT NULL CHECK (kms_key_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    source_system text NOT NULL DEFAULT 'native' CHECK (source_system ~ '^[a-z][a-z0-9_+.-]*$'),
    schema_version text NOT NULL DEFAULT 'time_approval.v1' CHECK (schema_version = 'time_approval.v1'),
    entry_object_id text NOT NULL CHECK (entry_object_id <> ''),
    approval_number text NOT NULL CHECK (approval_number <> ''),
    approval_state text NOT NULL DEFAULT 'not_submitted' CHECK (approval_state = 'not_submitted'),
    worker_principal_id text NOT NULL CHECK (worker_principal_id <> ''),
    approver_principal_id text,
    decided_at_utc timestamptz,
    PRIMARY KEY (tenant_id, object_id),
    UNIQUE (tenant_id, approval_number),
    UNIQUE (tenant_id, entry_object_id),
    FOREIGN KEY (tenant_id, entry_object_id) REFERENCES time_tracking.entries (tenant_id, object_id),
    CHECK (approver_principal_id IS NULL AND decided_at_utc IS NULL),
    CHECK (legal_hold_state <> 'active' OR retention_policy_id = 'rp-legal-hold')
);

CREATE TABLE IF NOT EXISTS time_tracking.entry_creation_receipts (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    mutation_reference text NOT NULL CHECK (mutation_reference ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    command_hash text NOT NULL CHECK (command_hash ~ '^sha256:[a-f0-9]{64}$'),
    created_by text NOT NULL CHECK (created_by <> ''),
    worker_principal_id text NOT NULL CHECK (worker_principal_id <> ''),
    entry_object_id text NOT NULL CHECK (entry_object_id <> ''),
    approval_object_id text NOT NULL CHECK (approval_object_id <> ''),
    duration_minutes integer NOT NULL CHECK (duration_minutes BETWEEN 1 AND 1440),
    acl_manifest jsonb NOT NULL CHECK (
        jsonb_typeof(acl_manifest) = 'array' AND jsonb_array_length(acl_manifest) BETWEEN 2 AND 4
    ),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    receipt_hash text NOT NULL CHECK (receipt_hash ~ '^sha256:[a-f0-9]{64}$'),
    created_at_utc timestamptz NOT NULL,
    schema_version text NOT NULL DEFAULT 'time_entry_creation_receipt.v1'
        CHECK (schema_version = 'time_entry_creation_receipt.v1'),
    PRIMARY KEY (tenant_id, mutation_reference),
    UNIQUE (tenant_id, receipt_hash),
    FOREIGN KEY (tenant_id, entry_object_id) REFERENCES time_tracking.entries (tenant_id, object_id),
    FOREIGN KEY (tenant_id, approval_object_id) REFERENCES time_tracking.approvals (tenant_id, object_id)
);

COMMENT ON SCHEMA time_tracking IS 'Tenant-scoped governed Time Tracking module schema.';
COMMENT ON TABLE time_tracking.entries IS
    'Governed time-entry metadata. Free-text work descriptions and payroll payloads are outside this slice.';
COMMENT ON TABLE time_tracking.approvals IS
    'Append-only initial approval state linked one-to-one with a governed time entry.';
COMMENT ON TABLE time_tracking.entry_creation_receipts IS
    'Append-only metadata receipt binding time entry, initial approval and authoritative ACL grants.';
COMMENT ON COLUMN time_tracking.entry_creation_receipts.acl_manifest IS
    'ACL reference strings only. Work descriptions, payroll values and other business content are forbidden.';

CREATE INDEX IF NOT EXISTS time_entries_worker_date_idx
    ON time_tracking.entries (tenant_id, worker_principal_id, work_date DESC, started_at_utc DESC);
CREATE INDEX IF NOT EXISTS time_entries_retention_hold_idx
    ON time_tracking.entries (tenant_id, retention_policy_id, legal_hold_state, lifecycle_state);
CREATE INDEX IF NOT EXISTS time_approvals_worker_state_idx
    ON time_tracking.approvals (tenant_id, worker_principal_id, approval_state, created_at_utc DESC);
CREATE INDEX IF NOT EXISTS time_approvals_retention_hold_idx
    ON time_tracking.approvals (tenant_id, retention_policy_id, legal_hold_state, lifecycle_state);

ALTER TABLE time_tracking.entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE time_tracking.entries FORCE ROW LEVEL SECURITY;
ALTER TABLE time_tracking.approvals ENABLE ROW LEVEL SECURITY;
ALTER TABLE time_tracking.approvals FORCE ROW LEVEL SECURITY;
ALTER TABLE time_tracking.entry_creation_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE time_tracking.entry_creation_receipts FORCE ROW LEVEL SECURITY;

CREATE POLICY time_entries_tenant_select ON time_tracking.entries FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());
CREATE POLICY time_entries_tenant_insert ON time_tracking.entries FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());
CREATE POLICY time_entries_no_update ON time_tracking.entries FOR UPDATE USING (false) WITH CHECK (false);
CREATE POLICY time_entries_no_hard_delete ON time_tracking.entries FOR DELETE USING (false);

CREATE POLICY time_approvals_tenant_select ON time_tracking.approvals FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());
CREATE POLICY time_approvals_tenant_insert ON time_tracking.approvals FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());
CREATE POLICY time_approvals_no_update ON time_tracking.approvals FOR UPDATE USING (false) WITH CHECK (false);
CREATE POLICY time_approvals_no_hard_delete ON time_tracking.approvals FOR DELETE USING (false);

CREATE POLICY time_entry_receipts_tenant_select ON time_tracking.entry_creation_receipts FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());
CREATE POLICY time_entry_receipts_tenant_insert ON time_tracking.entry_creation_receipts FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());
CREATE POLICY time_entry_receipts_no_update ON time_tracking.entry_creation_receipts FOR UPDATE
    USING (false) WITH CHECK (false);
CREATE POLICY time_entry_receipts_no_hard_delete ON time_tracking.entry_creation_receipts FOR DELETE USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_authz_admin') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA time_tracking TO collabio_authz_admin';
        EXECUTE 'GRANT SELECT, INSERT ON TABLE time_tracking.entries TO collabio_authz_admin';
        EXECUTE 'GRANT SELECT, INSERT ON TABLE time_tracking.approvals TO collabio_authz_admin';
        EXECUTE 'GRANT SELECT, INSERT ON TABLE time_tracking.entry_creation_receipts TO collabio_authz_admin';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA time_tracking TO collabio_app';
        EXECUTE 'GRANT SELECT ON TABLE time_tracking.entries TO collabio_app';
        EXECUTE 'GRANT SELECT ON TABLE time_tracking.approvals TO collabio_app';
        EXECUTE 'GRANT SELECT ON TABLE time_tracking.entry_creation_receipts TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA time_tracking TO collabio_worker';
        EXECUTE 'GRANT SELECT ON TABLE time_tracking.entries TO collabio_worker';
        EXECUTE 'GRANT SELECT ON TABLE time_tracking.approvals TO collabio_worker';
        EXECUTE 'GRANT SELECT ON TABLE time_tracking.entry_creation_receipts TO collabio_worker';
    END IF;
END
$$;
