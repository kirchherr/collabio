-- 0057_crm_atomic_account_onboarding.sql
-- Atomic CRM onboarding: business metadata, owner ACLs and an immutable receipt.

CREATE TABLE IF NOT EXISTS crm.account_onboarding_receipts (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    mutation_reference text NOT NULL CHECK (mutation_reference ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    command_hash text NOT NULL CHECK (command_hash ~ '^sha256:[a-f0-9]{64}$'),
    created_by text NOT NULL CHECK (created_by <> ''),
    acl_subject_id text NOT NULL CHECK (acl_subject_id <> ''),
    object_manifest jsonb NOT NULL CHECK (jsonb_typeof(object_manifest) = 'object'),
    acl_manifest jsonb NOT NULL CHECK (jsonb_typeof(acl_manifest) = 'array'),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    receipt_hash text NOT NULL CHECK (receipt_hash ~ '^sha256:[a-f0-9]{64}$'),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    schema_version text NOT NULL DEFAULT 'crm_account_onboarding_receipt.v1'
        CHECK (schema_version = 'crm_account_onboarding_receipt.v1'),
    PRIMARY KEY (tenant_id, mutation_reference),
    UNIQUE (tenant_id, receipt_hash),
    CHECK (object_manifest ?& ARRAY['crm.account', 'crm.contact', 'crm.activity', 'crm.note']),
    CHECK (jsonb_array_length(acl_manifest) = 4)
);

COMMENT ON TABLE crm.account_onboarding_receipts IS
    'Append-only metadata receipt binding one CRM account, contact, activity, note and their owner ACL grants.';
COMMENT ON COLUMN crm.account_onboarding_receipts.object_manifest IS
    'Object type to object ID mapping only. Business field values and note bodies are forbidden.';
COMMENT ON COLUMN crm.account_onboarding_receipts.acl_manifest IS
    'Metadata-only ACL references created in the same PostgreSQL transaction.';

ALTER TABLE crm.account_onboarding_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE crm.account_onboarding_receipts FORCE ROW LEVEL SECURITY;

CREATE POLICY crm_account_onboarding_receipts_tenant_select
    ON crm.account_onboarding_receipts
    FOR SELECT USING (tenant_id = collabio.current_tenant_id());

CREATE POLICY crm_account_onboarding_receipts_tenant_insert
    ON crm.account_onboarding_receipts
    FOR INSERT WITH CHECK (tenant_id = collabio.current_tenant_id());

CREATE POLICY crm_account_onboarding_receipts_no_update
    ON crm.account_onboarding_receipts
    FOR UPDATE USING (false);

CREATE POLICY crm_account_onboarding_receipts_no_hard_delete
    ON crm.account_onboarding_receipts
    FOR DELETE USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_authz_admin') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA crm TO collabio_authz_admin';
        EXECUTE 'GRANT SELECT, INSERT ON TABLE crm.accounts TO collabio_authz_admin';
        EXECUTE 'GRANT SELECT, INSERT ON TABLE crm.contacts TO collabio_authz_admin';
        EXECUTE 'GRANT SELECT, INSERT ON TABLE crm.activities TO collabio_authz_admin';
        EXECUTE 'GRANT SELECT, INSERT ON TABLE crm.notes TO collabio_authz_admin';
        EXECUTE 'GRANT SELECT, INSERT ON TABLE crm.account_onboarding_receipts TO collabio_authz_admin';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT SELECT ON TABLE crm.account_onboarding_receipts TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT SELECT ON TABLE crm.account_onboarding_receipts TO collabio_worker';
    END IF;
END
$$;

UPDATE collabio.module_catalog
SET required_migration_versions = '["0007", "0008", "0009", "0010", "0011", "0016", "0017", "0018", "0019", "0020", "0034", "0035", "0036", "0037", "0038", "0039", "0040", "0041", "0042", "0043", "0044", "0057"]'::jsonb
WHERE module_id = 'crm_erp';
