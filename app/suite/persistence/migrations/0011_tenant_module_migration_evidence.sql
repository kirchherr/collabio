-- 0011_tenant_module_migration_evidence.sql
-- Migration manifest evidence captured when tenant modules are provisioned.

ALTER TABLE collabio.tenant_modules
    ADD COLUMN IF NOT EXISTS migration_evidence jsonb NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE collabio.tenant_modules
    DROP CONSTRAINT IF EXISTS tenant_modules_migration_evidence_json_check;

ALTER TABLE collabio.tenant_modules
    ADD CONSTRAINT tenant_modules_migration_evidence_json_check
    CHECK (jsonb_typeof(migration_evidence) = 'array');

ALTER TABLE collabio.tenant_modules
    DROP CONSTRAINT IF EXISTS tenant_modules_provisioned_migration_evidence_check;

ALTER TABLE collabio.tenant_modules
    ADD CONSTRAINT tenant_modules_provisioned_migration_evidence_check
    CHECK (
        status IN ('available', 'provisioning')
        OR jsonb_array_length(migration_evidence) > 0
    );

COMMENT ON COLUMN collabio.tenant_modules.migration_evidence IS
    'Startup-blocking migration manifest entries captured at module provisioning time, including versions, checksums, and evidence references.';
