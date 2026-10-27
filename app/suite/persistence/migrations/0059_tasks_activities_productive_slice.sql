-- 0059_tasks_activities_productive_slice.sql
-- First productive Tasks & Activities slice with atomic task, activity, ACL and receipt writes.

CREATE SCHEMA IF NOT EXISTS tasks;

CREATE TABLE IF NOT EXISTS tasks.items (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    object_id text NOT NULL CHECK (object_id <> ''),
    object_type text NOT NULL DEFAULT 'task.task' CHECK (object_type = 'task.task'),
    owner_principal_id text NOT NULL CHECK (owner_principal_id <> ''),
    created_by text NOT NULL CHECK (created_by <> ''),
    created_at_utc timestamptz NOT NULL,
    updated_at_utc timestamptz NOT NULL,
    data_classification text NOT NULL DEFAULT 'personal' CHECK (data_classification = 'personal'),
    retention_policy_id text NOT NULL DEFAULT 'rp-standard' CHECK (
        retention_policy_id IN ('rp-standard', 'rp-restricted', 'rp-legal-hold')
    ),
    legal_hold_state text NOT NULL DEFAULT 'none' CHECK (legal_hold_state IN ('none', 'active')),
    lifecycle_state text NOT NULL DEFAULT 'assigned' CHECK (
        lifecycle_state IN (
            'draft',
            'open',
            'assigned',
            'in_progress',
            'blocked',
            'completed',
            'cancelled',
            'archived',
            'disposition_pending'
        )
    ),
    kms_key_ref text NOT NULL CHECK (kms_key_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    source_system text NOT NULL DEFAULT 'native' CHECK (source_system ~ '^[a-z][a-z0-9_+.-]*$'),
    schema_version text NOT NULL DEFAULT 'task_item.v1' CHECK (schema_version = 'task_item.v1'),
    task_number text NOT NULL CHECK (task_number <> ''),
    title text NOT NULL CHECK (title <> '' AND title !~ E'[\\r\\n]'),
    priority text NOT NULL DEFAULT 'normal' CHECK (priority IN ('low', 'normal', 'high', 'urgent')),
    assigned_principal_id text NOT NULL CHECK (assigned_principal_id <> ''),
    due_at_utc timestamptz,
    PRIMARY KEY (tenant_id, object_id),
    UNIQUE (tenant_id, task_number),
    CHECK (legal_hold_state <> 'active' OR retention_policy_id = 'rp-legal-hold')
);

CREATE TABLE IF NOT EXISTS tasks.activities (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    object_id text NOT NULL CHECK (object_id <> ''),
    object_type text NOT NULL DEFAULT 'task.activity' CHECK (object_type = 'task.activity'),
    owner_principal_id text NOT NULL CHECK (owner_principal_id <> ''),
    created_by text NOT NULL CHECK (created_by <> ''),
    created_at_utc timestamptz NOT NULL,
    updated_at_utc timestamptz NOT NULL,
    data_classification text NOT NULL DEFAULT 'personal' CHECK (data_classification = 'personal'),
    retention_policy_id text NOT NULL DEFAULT 'rp-standard' CHECK (
        retention_policy_id IN ('rp-standard', 'rp-restricted', 'rp-legal-hold')
    ),
    legal_hold_state text NOT NULL DEFAULT 'none' CHECK (legal_hold_state IN ('none', 'active')),
    lifecycle_state text NOT NULL DEFAULT 'open' CHECK (
        lifecycle_state IN ('open', 'in_progress', 'blocked', 'completed', 'cancelled', 'disposition_pending')
    ),
    kms_key_ref text NOT NULL CHECK (kms_key_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    source_system text NOT NULL DEFAULT 'native' CHECK (source_system ~ '^[a-z][a-z0-9_+.-]*$'),
    schema_version text NOT NULL DEFAULT 'task_activity.v1' CHECK (schema_version = 'task_activity.v1'),
    task_object_id text NOT NULL CHECK (task_object_id <> ''),
    activity_number text NOT NULL CHECK (activity_number <> ''),
    activity_type text NOT NULL DEFAULT 'created' CHECK (
        activity_type IN ('created', 'assigned', 'status_changed', 'due_date_changed', 'completed')
    ),
    summary text NOT NULL CHECK (summary <> '' AND summary !~ E'[\\r\\n]'),
    occurred_at_utc timestamptz NOT NULL,
    PRIMARY KEY (tenant_id, object_id),
    UNIQUE (tenant_id, activity_number),
    FOREIGN KEY (tenant_id, task_object_id)
        REFERENCES tasks.items (tenant_id, object_id),
    CHECK (legal_hold_state <> 'active' OR retention_policy_id = 'rp-legal-hold')
);

CREATE TABLE IF NOT EXISTS tasks.creation_receipts (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    mutation_reference text NOT NULL CHECK (mutation_reference ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    command_hash text NOT NULL CHECK (command_hash ~ '^sha256:[a-f0-9]{64}$'),
    created_by text NOT NULL CHECK (created_by <> ''),
    assigned_principal_id text NOT NULL CHECK (assigned_principal_id <> ''),
    task_object_id text NOT NULL CHECK (task_object_id <> ''),
    activity_object_id text NOT NULL CHECK (activity_object_id <> ''),
    acl_manifest jsonb NOT NULL CHECK (
        jsonb_typeof(acl_manifest) = 'array'
        AND jsonb_array_length(acl_manifest) BETWEEN 2 AND 4
    ),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    receipt_hash text NOT NULL CHECK (receipt_hash ~ '^sha256:[a-f0-9]{64}$'),
    created_at_utc timestamptz NOT NULL,
    schema_version text NOT NULL DEFAULT 'task_creation_receipt.v1'
        CHECK (schema_version = 'task_creation_receipt.v1'),
    PRIMARY KEY (tenant_id, mutation_reference),
    UNIQUE (tenant_id, receipt_hash),
    FOREIGN KEY (tenant_id, task_object_id)
        REFERENCES tasks.items (tenant_id, object_id),
    FOREIGN KEY (tenant_id, activity_object_id)
        REFERENCES tasks.activities (tenant_id, object_id)
);

COMMENT ON SCHEMA tasks IS
    'Tenant-scoped Tasks and Activities module schema.';
COMMENT ON TABLE tasks.items IS
    'Governed assigned-task metadata. Descriptions, comments, attachments and external effects are not stored here.';
COMMENT ON TABLE tasks.activities IS
    'Append-only governed task activity metadata.';
COMMENT ON TABLE tasks.creation_receipts IS
    'Append-only metadata receipt binding task, initial activity and authoritative ACL grants.';
COMMENT ON COLUMN tasks.creation_receipts.acl_manifest IS
    'ACL reference strings only. Task titles, activity summaries and other business field values are forbidden.';

CREATE INDEX IF NOT EXISTS tasks_items_assignee_due_idx
    ON tasks.items (tenant_id, assigned_principal_id, due_at_utc, lifecycle_state);
CREATE INDEX IF NOT EXISTS tasks_items_retention_hold_idx
    ON tasks.items (tenant_id, retention_policy_id, legal_hold_state, lifecycle_state);
CREATE INDEX IF NOT EXISTS tasks_activities_task_time_idx
    ON tasks.activities (tenant_id, task_object_id, occurred_at_utc DESC);
CREATE INDEX IF NOT EXISTS tasks_activities_retention_hold_idx
    ON tasks.activities (tenant_id, retention_policy_id, legal_hold_state, lifecycle_state);

ALTER TABLE tasks.items ENABLE ROW LEVEL SECURITY;
ALTER TABLE tasks.items FORCE ROW LEVEL SECURITY;
ALTER TABLE tasks.activities ENABLE ROW LEVEL SECURITY;
ALTER TABLE tasks.activities FORCE ROW LEVEL SECURITY;
ALTER TABLE tasks.creation_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE tasks.creation_receipts FORCE ROW LEVEL SECURITY;

CREATE POLICY tasks_items_tenant_select
    ON tasks.items FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());
CREATE POLICY tasks_items_tenant_insert
    ON tasks.items FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());
CREATE POLICY tasks_items_no_update
    ON tasks.items FOR UPDATE
    USING (false) WITH CHECK (false);
CREATE POLICY tasks_items_no_hard_delete
    ON tasks.items FOR DELETE
    USING (false);

CREATE POLICY tasks_activities_tenant_select
    ON tasks.activities FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());
CREATE POLICY tasks_activities_tenant_insert
    ON tasks.activities FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());
CREATE POLICY tasks_activities_no_update
    ON tasks.activities FOR UPDATE
    USING (false) WITH CHECK (false);
CREATE POLICY tasks_activities_no_hard_delete
    ON tasks.activities FOR DELETE
    USING (false);

CREATE POLICY tasks_creation_receipts_tenant_select
    ON tasks.creation_receipts FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());
CREATE POLICY tasks_creation_receipts_tenant_insert
    ON tasks.creation_receipts FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());
CREATE POLICY tasks_creation_receipts_no_update
    ON tasks.creation_receipts FOR UPDATE
    USING (false) WITH CHECK (false);
CREATE POLICY tasks_creation_receipts_no_hard_delete
    ON tasks.creation_receipts FOR DELETE
    USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_authz_admin') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA tasks TO collabio_authz_admin';
        EXECUTE 'GRANT SELECT, INSERT ON TABLE tasks.items TO collabio_authz_admin';
        EXECUTE 'GRANT SELECT, INSERT ON TABLE tasks.activities TO collabio_authz_admin';
        EXECUTE 'GRANT SELECT, INSERT ON TABLE tasks.creation_receipts TO collabio_authz_admin';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA tasks TO collabio_app';
        EXECUTE 'GRANT SELECT ON TABLE tasks.items TO collabio_app';
        EXECUTE 'GRANT SELECT ON TABLE tasks.activities TO collabio_app';
        EXECUTE 'GRANT SELECT ON TABLE tasks.creation_receipts TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA tasks TO collabio_worker';
        EXECUTE 'GRANT SELECT ON TABLE tasks.items TO collabio_worker';
        EXECUTE 'GRANT SELECT ON TABLE tasks.activities TO collabio_worker';
        EXECUTE 'GRANT SELECT ON TABLE tasks.creation_receipts TO collabio_worker';
    END IF;
END
$$;

UPDATE collabio.module_catalog
SET module_version = '0.2.0',
    status = 'installed',
    description = (
        'Optional governed Tasks and Activities module with a tenant-gated productive task and '
        'initial activity slice. Workflow transitions, notifications, integrations, RAG and AI remain separate gates.'
    ),
    installed_at_utc = COALESCE(installed_at_utc, now()),
    required_migration_versions = '["0050", "0059"]'::jsonb
WHERE module_id = 'tasks_activities';
