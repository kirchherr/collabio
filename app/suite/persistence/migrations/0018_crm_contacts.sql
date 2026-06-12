-- 0018_crm_contacts.sql
-- First persistent CRM contact table for the gated crm_erp.crm.contacts slice.

CREATE TABLE IF NOT EXISTS crm.contacts (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    object_id text NOT NULL CHECK (object_id <> ''),
    object_type text NOT NULL DEFAULT 'crm.contact' CHECK (object_type = 'crm.contact'),
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
    schema_version text NOT NULL DEFAULT 'crm_contact.v1' CHECK (schema_version = 'crm_contact.v1'),
    account_object_id text CHECK (account_object_id IS NULL OR account_object_id <> ''),
    contact_number text CHECK (contact_number IS NULL OR contact_number <> ''),
    display_name text NOT NULL CHECK (display_name <> ''),
    given_name text CHECK (given_name IS NULL OR given_name <> ''),
    family_name text CHECK (family_name IS NULL OR family_name <> ''),
    primary_email text CHECK (primary_email IS NULL OR primary_email <> ''),
    primary_phone text CHECK (primary_phone IS NULL OR primary_phone <> ''),
    role_label text CHECK (role_label IS NULL OR role_label <> ''),
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'restricted', 'archived')),
    PRIMARY KEY (tenant_id, object_id),
    FOREIGN KEY (tenant_id, account_object_id)
        REFERENCES crm.accounts (tenant_id, object_id),
    CHECK (status <> 'restricted' OR lifecycle_state = 'restricted')
);

COMMENT ON TABLE crm.contacts IS
    'Tenant-scoped CRM contact records for crm_erp.crm.contacts. Normal API access requires the module gate.';
COMMENT ON COLUMN crm.contacts.account_object_id IS
    'Optional CRM account relation. API responses must redact the relation unless the account object is readable.';
COMMENT ON COLUMN crm.contacts.data_classification IS
    'CRM contacts start as personal data until a narrower tenant policy is approved.';
COMMENT ON COLUMN crm.contacts.retention_policy_id IS
    'Retention policy reference. Initial CRM contact records use rp-standard.';
COMMENT ON COLUMN crm.contacts.legal_hold_state IS
    'Legal Hold state blocks destructive lifecycle transitions outside approved compliance workflows.';

CREATE UNIQUE INDEX IF NOT EXISTS crm_contacts_contact_number_unique_idx
    ON crm.contacts (tenant_id, contact_number)
    WHERE contact_number IS NOT NULL;

CREATE INDEX IF NOT EXISTS crm_contacts_tenant_account_idx
    ON crm.contacts (tenant_id, account_object_id)
    WHERE account_object_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS crm_contacts_tenant_status_idx
    ON crm.contacts (tenant_id, status, lifecycle_state);

CREATE INDEX IF NOT EXISTS crm_contacts_retention_legal_hold_idx
    ON crm.contacts (tenant_id, retention_policy_id, legal_hold_state, lifecycle_state);

CREATE OR REPLACE FUNCTION crm.touch_updated_at_utc()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at_utc = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS crm_contacts_touch_updated_at_utc ON crm.contacts;
CREATE TRIGGER crm_contacts_touch_updated_at_utc
    BEFORE UPDATE ON crm.contacts
    FOR EACH ROW
    EXECUTE FUNCTION crm.touch_updated_at_utc();

ALTER TABLE crm.contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE crm.contacts FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS crm_contacts_tenant_select ON crm.contacts;
CREATE POLICY crm_contacts_tenant_select
    ON crm.contacts
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS crm_contacts_tenant_insert ON crm.contacts;
CREATE POLICY crm_contacts_tenant_insert
    ON crm.contacts
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS crm_contacts_tenant_update ON crm.contacts;
CREATE POLICY crm_contacts_tenant_update
    ON crm.contacts
    FOR UPDATE
    USING (tenant_id = collabio.current_tenant_id())
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS crm_contacts_no_hard_delete ON crm.contacts;
CREATE POLICY crm_contacts_no_hard_delete
    ON crm.contacts
    FOR DELETE
    USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA crm TO collabio_app';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE ON TABLE crm.contacts TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA crm TO collabio_worker';
        EXECUTE 'GRANT SELECT ON TABLE crm.contacts TO collabio_worker';
    END IF;
END
$$;
