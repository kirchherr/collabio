-- 0019_crm_activities_notes.sql
-- Persistent CRM activities and metadata-only notes for the gated crm_erp.crm.activities slice.

CREATE TABLE IF NOT EXISTS crm.activities (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    object_id text NOT NULL CHECK (object_id <> ''),
    object_type text NOT NULL DEFAULT 'crm.activity' CHECK (object_type = 'crm.activity'),
    owner_principal_id text NOT NULL CHECK (owner_principal_id <> ''),
    created_by text NOT NULL CHECK (created_by <> ''),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    updated_at_utc timestamptz NOT NULL DEFAULT now(),
    data_classification text NOT NULL DEFAULT 'personal' CHECK (data_classification = 'personal'),
    retention_policy_id text NOT NULL DEFAULT 'rp-standard' CHECK (retention_policy_id = 'rp-standard'),
    legal_hold_state text NOT NULL DEFAULT 'none' CHECK (legal_hold_state IN ('none', 'active')),
    lifecycle_state text NOT NULL DEFAULT 'active' CHECK (
        lifecycle_state IN ('working', 'active', 'restricted', 'disposition_pending')
    ),
    kms_key_ref text NOT NULL CHECK (kms_key_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    source_system text NOT NULL CHECK (source_system ~ '^[a-z][a-z0-9_+.-]*$'),
    schema_version text NOT NULL DEFAULT 'crm_activity.v1' CHECK (schema_version = 'crm_activity.v1'),
    account_object_id text CHECK (account_object_id IS NULL OR account_object_id <> ''),
    contact_object_id text CHECK (contact_object_id IS NULL OR contact_object_id <> ''),
    activity_number text CHECK (activity_number IS NULL OR activity_number <> ''),
    activity_type text NOT NULL CHECK (activity_type IN ('task', 'call', 'meeting', 'email', 'follow_up')),
    subject text NOT NULL CHECK (subject <> ''),
    due_at_utc timestamptz,
    completed_at_utc timestamptz,
    status text NOT NULL DEFAULT 'planned' CHECK (
        status IN ('planned', 'done', 'cancelled', 'restricted', 'archived')
    ),
    PRIMARY KEY (tenant_id, object_id),
    FOREIGN KEY (tenant_id, account_object_id)
        REFERENCES crm.accounts (tenant_id, object_id),
    FOREIGN KEY (tenant_id, contact_object_id)
        REFERENCES crm.contacts (tenant_id, object_id),
    CHECK (status <> 'restricted' OR lifecycle_state = 'restricted'),
    CHECK (status <> 'done' OR completed_at_utc IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS crm.notes (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    object_id text NOT NULL CHECK (object_id <> ''),
    object_type text NOT NULL DEFAULT 'crm.note' CHECK (object_type = 'crm.note'),
    owner_principal_id text NOT NULL CHECK (owner_principal_id <> ''),
    created_by text NOT NULL CHECK (created_by <> ''),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    updated_at_utc timestamptz NOT NULL DEFAULT now(),
    data_classification text NOT NULL DEFAULT 'personal' CHECK (data_classification = 'personal'),
    retention_policy_id text NOT NULL DEFAULT 'rp-standard' CHECK (retention_policy_id = 'rp-standard'),
    legal_hold_state text NOT NULL DEFAULT 'none' CHECK (legal_hold_state IN ('none', 'active')),
    lifecycle_state text NOT NULL DEFAULT 'active' CHECK (
        lifecycle_state IN ('working', 'active', 'restricted', 'disposition_pending')
    ),
    kms_key_ref text NOT NULL CHECK (kms_key_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    source_system text NOT NULL CHECK (source_system ~ '^[a-z][a-z0-9_+.-]*$'),
    schema_version text NOT NULL DEFAULT 'crm_note.v1' CHECK (schema_version = 'crm_note.v1'),
    account_object_id text CHECK (account_object_id IS NULL OR account_object_id <> ''),
    contact_object_id text CHECK (contact_object_id IS NULL OR contact_object_id <> ''),
    activity_object_id text CHECK (activity_object_id IS NULL OR activity_object_id <> ''),
    note_number text CHECK (note_number IS NULL OR note_number <> ''),
    title text NOT NULL CHECK (title <> ''),
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'restricted', 'archived')),
    PRIMARY KEY (tenant_id, object_id),
    FOREIGN KEY (tenant_id, account_object_id)
        REFERENCES crm.accounts (tenant_id, object_id),
    FOREIGN KEY (tenant_id, contact_object_id)
        REFERENCES crm.contacts (tenant_id, object_id),
    FOREIGN KEY (tenant_id, activity_object_id)
        REFERENCES crm.activities (tenant_id, object_id),
    CHECK (status <> 'restricted' OR lifecycle_state = 'restricted')
);

COMMENT ON TABLE crm.activities IS
    'Tenant-scoped CRM activity records for crm_erp.crm.activities. Normal API access requires the module gate.';
COMMENT ON TABLE crm.notes IS
    'Tenant-scoped CRM note metadata for crm_erp.crm.activities. Note body storage is intentionally outside this initial slice.';
COMMENT ON COLUMN crm.activities.account_object_id IS
    'Optional CRM account relation. API responses must redact the relation unless the account object is readable.';
COMMENT ON COLUMN crm.activities.contact_object_id IS
    'Optional CRM contact relation. API responses must redact the relation unless the contact object is readable.';
COMMENT ON COLUMN crm.notes.title IS
    'Metadata-only note title. Full note bodies require a later source-object/content-resolver slice.';
COMMENT ON COLUMN crm.notes.activity_object_id IS
    'Optional CRM activity relation. API responses must redact the relation unless the activity object is readable.';

CREATE UNIQUE INDEX IF NOT EXISTS crm_activities_activity_number_unique_idx
    ON crm.activities (tenant_id, activity_number)
    WHERE activity_number IS NOT NULL;

CREATE INDEX IF NOT EXISTS crm_activities_tenant_account_idx
    ON crm.activities (tenant_id, account_object_id)
    WHERE account_object_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS crm_activities_tenant_contact_idx
    ON crm.activities (tenant_id, contact_object_id)
    WHERE contact_object_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS crm_activities_tenant_status_idx
    ON crm.activities (tenant_id, status, lifecycle_state);

CREATE INDEX IF NOT EXISTS crm_activities_retention_legal_hold_idx
    ON crm.activities (tenant_id, retention_policy_id, legal_hold_state, lifecycle_state);

CREATE UNIQUE INDEX IF NOT EXISTS crm_notes_note_number_unique_idx
    ON crm.notes (tenant_id, note_number)
    WHERE note_number IS NOT NULL;

CREATE INDEX IF NOT EXISTS crm_notes_tenant_account_idx
    ON crm.notes (tenant_id, account_object_id)
    WHERE account_object_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS crm_notes_tenant_contact_idx
    ON crm.notes (tenant_id, contact_object_id)
    WHERE contact_object_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS crm_notes_tenant_activity_idx
    ON crm.notes (tenant_id, activity_object_id)
    WHERE activity_object_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS crm_notes_tenant_status_idx
    ON crm.notes (tenant_id, status, lifecycle_state);

CREATE INDEX IF NOT EXISTS crm_notes_retention_legal_hold_idx
    ON crm.notes (tenant_id, retention_policy_id, legal_hold_state, lifecycle_state);

CREATE OR REPLACE FUNCTION crm.touch_updated_at_utc()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at_utc = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS crm_activities_touch_updated_at_utc ON crm.activities;
CREATE TRIGGER crm_activities_touch_updated_at_utc
    BEFORE UPDATE ON crm.activities
    FOR EACH ROW
    EXECUTE FUNCTION crm.touch_updated_at_utc();

DROP TRIGGER IF EXISTS crm_notes_touch_updated_at_utc ON crm.notes;
CREATE TRIGGER crm_notes_touch_updated_at_utc
    BEFORE UPDATE ON crm.notes
    FOR EACH ROW
    EXECUTE FUNCTION crm.touch_updated_at_utc();

ALTER TABLE crm.activities ENABLE ROW LEVEL SECURITY;
ALTER TABLE crm.activities FORCE ROW LEVEL SECURITY;
ALTER TABLE crm.notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE crm.notes FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS crm_activities_tenant_select ON crm.activities;
CREATE POLICY crm_activities_tenant_select
    ON crm.activities
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS crm_activities_tenant_insert ON crm.activities;
CREATE POLICY crm_activities_tenant_insert
    ON crm.activities
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS crm_activities_tenant_update ON crm.activities;
CREATE POLICY crm_activities_tenant_update
    ON crm.activities
    FOR UPDATE
    USING (tenant_id = collabio.current_tenant_id())
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS crm_activities_no_hard_delete ON crm.activities;
CREATE POLICY crm_activities_no_hard_delete
    ON crm.activities
    FOR DELETE
    USING (false);

DROP POLICY IF EXISTS crm_notes_tenant_select ON crm.notes;
CREATE POLICY crm_notes_tenant_select
    ON crm.notes
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS crm_notes_tenant_insert ON crm.notes;
CREATE POLICY crm_notes_tenant_insert
    ON crm.notes
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS crm_notes_tenant_update ON crm.notes;
CREATE POLICY crm_notes_tenant_update
    ON crm.notes
    FOR UPDATE
    USING (tenant_id = collabio.current_tenant_id())
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS crm_notes_no_hard_delete ON crm.notes;
CREATE POLICY crm_notes_no_hard_delete
    ON crm.notes
    FOR DELETE
    USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA crm TO collabio_app';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE ON TABLE crm.activities TO collabio_app';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE ON TABLE crm.notes TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA crm TO collabio_worker';
        EXECUTE 'GRANT SELECT ON TABLE crm.activities TO collabio_worker';
        EXECUTE 'GRANT SELECT ON TABLE crm.notes TO collabio_worker';
    END IF;
END
$$;
