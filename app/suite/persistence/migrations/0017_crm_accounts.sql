-- 0017_crm_accounts.sql
-- First persistent CRM business table for the gated crm_erp.crm.accounts slice.

CREATE TABLE IF NOT EXISTS crm.accounts (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    object_id text NOT NULL CHECK (object_id <> ''),
    object_type text NOT NULL DEFAULT 'crm.account' CHECK (object_type = 'crm.account'),
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
    schema_version text NOT NULL DEFAULT 'crm_account.v1' CHECK (schema_version = 'crm_account.v1'),
    account_number text CHECK (account_number IS NULL OR account_number <> ''),
    display_name text NOT NULL CHECK (display_name <> ''),
    account_kind text NOT NULL DEFAULT 'organization' CHECK (account_kind IN ('organization', 'person')),
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'restricted', 'archived')),
    PRIMARY KEY (tenant_id, object_id),
    CHECK (status <> 'restricted' OR lifecycle_state = 'restricted')
);

COMMENT ON TABLE crm.accounts IS
    'Tenant-scoped CRM account records for crm_erp.crm.accounts. Normal API access requires the module gate.';
COMMENT ON COLUMN crm.accounts.data_classification IS
    'CRM accounts start as personal data until a narrower tenant policy is approved.';
COMMENT ON COLUMN crm.accounts.retention_policy_id IS
    'Retention policy reference. Initial CRM account records use rp-standard.';
COMMENT ON COLUMN crm.accounts.legal_hold_state IS
    'Legal Hold state blocks destructive lifecycle transitions outside approved compliance workflows.';

CREATE UNIQUE INDEX IF NOT EXISTS crm_accounts_account_number_unique_idx
    ON crm.accounts (tenant_id, account_number)
    WHERE account_number IS NOT NULL;

CREATE INDEX IF NOT EXISTS crm_accounts_tenant_status_idx
    ON crm.accounts (tenant_id, status, lifecycle_state);

CREATE INDEX IF NOT EXISTS crm_accounts_retention_legal_hold_idx
    ON crm.accounts (tenant_id, retention_policy_id, legal_hold_state, lifecycle_state);

CREATE OR REPLACE FUNCTION crm.touch_updated_at_utc()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at_utc = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS crm_accounts_touch_updated_at_utc ON crm.accounts;
CREATE TRIGGER crm_accounts_touch_updated_at_utc
    BEFORE UPDATE ON crm.accounts
    FOR EACH ROW
    EXECUTE FUNCTION crm.touch_updated_at_utc();

ALTER TABLE crm.accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE crm.accounts FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS crm_accounts_tenant_select ON crm.accounts;
CREATE POLICY crm_accounts_tenant_select
    ON crm.accounts
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS crm_accounts_tenant_insert ON crm.accounts;
CREATE POLICY crm_accounts_tenant_insert
    ON crm.accounts
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS crm_accounts_tenant_update ON crm.accounts;
CREATE POLICY crm_accounts_tenant_update
    ON crm.accounts
    FOR UPDATE
    USING (tenant_id = collabio.current_tenant_id())
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS crm_accounts_no_hard_delete ON crm.accounts;
CREATE POLICY crm_accounts_no_hard_delete
    ON crm.accounts
    FOR DELETE
    USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA crm TO collabio_app';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE ON TABLE crm.accounts TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA crm TO collabio_worker';
        EXECUTE 'GRANT SELECT ON TABLE crm.accounts TO collabio_worker';
    END IF;
END
$$;
