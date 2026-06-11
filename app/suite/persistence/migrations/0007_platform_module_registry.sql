-- 0007_platform_module_registry.sql
-- Core registry for optional platform modules and tenant module lifecycle state.

CREATE SCHEMA IF NOT EXISTS collabio;

CREATE TABLE IF NOT EXISTS collabio.module_catalog (
    module_id text PRIMARY KEY,
    display_name text NOT NULL CHECK (display_name <> ''),
    module_version text NOT NULL CHECK (module_version <> ''),
    module_kind text NOT NULL CHECK (
        module_kind IN ('business_domain', 'platform_extension', 'integration', 'ai_extension')
    ),
    status text NOT NULL CHECK (status IN ('not_installed', 'installed', 'available')),
    min_core_version text,
    description text NOT NULL CHECK (description <> ''),
    installed_at_utc timestamptz NOT NULL DEFAULT now(),
    manifest_hash text NOT NULL CHECK (manifest_hash ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    schema_version text NOT NULL DEFAULT 'module_catalog.v1',
    CHECK (module_id ~ '^[a-z][a-z0-9_]*$')
);

CREATE TABLE IF NOT EXISTS collabio.tenant_modules (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    module_id text NOT NULL REFERENCES collabio.module_catalog(module_id),
    status text NOT NULL CHECK (
        status IN (
            'available',
            'provisioning',
            'enabled',
            'disabled',
            'suspended',
            'decommission_requested',
            'decommission_blocked',
            'decommissioned'
        )
    ),
    enabled_features jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(enabled_features) = 'object'),
    policy_snapshot_hash text NOT NULL CHECK (policy_snapshot_hash ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    provisioned_at_utc timestamptz,
    enabled_at_utc timestamptz,
    disabled_at_utc timestamptz,
    decommission_requested_at_utc timestamptz,
    decommissioned_at_utc timestamptz,
    changed_by text NOT NULL CHECK (changed_by <> ''),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    updated_at_utc timestamptz NOT NULL DEFAULT now(),
    schema_version text NOT NULL DEFAULT 'tenant_module.v1',
    PRIMARY KEY (tenant_id, module_id),
    CHECK (status <> 'enabled' OR enabled_at_utc IS NOT NULL),
    CHECK (status <> 'disabled' OR disabled_at_utc IS NOT NULL),
    CHECK (status <> 'decommission_requested' OR decommission_requested_at_utc IS NOT NULL),
    CHECK (status <> 'decommissioned' OR decommissioned_at_utc IS NOT NULL)
);

COMMENT ON TABLE collabio.module_catalog IS
    'Deployment-level catalog for optional modules. Tenant authorization is stored in tenant_modules.';
COMMENT ON TABLE collabio.tenant_modules IS
    'Tenant module lifecycle state. Disabled modules still preserve compliance, retention, legal-hold, audit, backup, and export obligations.';
COMMENT ON COLUMN collabio.tenant_modules.enabled_features IS
    'Feature discovery only. Server-side policy and module gates remain authoritative.';

CREATE INDEX IF NOT EXISTS tenant_modules_tenant_status_idx
    ON collabio.tenant_modules (tenant_id, status);

CREATE INDEX IF NOT EXISTS tenant_modules_module_status_idx
    ON collabio.tenant_modules (module_id, status);

DROP TRIGGER IF EXISTS tenant_modules_touch_updated_at_utc
    ON collabio.tenant_modules;

CREATE TRIGGER tenant_modules_touch_updated_at_utc
    BEFORE UPDATE ON collabio.tenant_modules
    FOR EACH ROW
    EXECUTE FUNCTION collabio.touch_updated_at_utc();

ALTER TABLE collabio.tenant_modules ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.tenant_modules FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_modules_tenant_select ON collabio.tenant_modules;
CREATE POLICY tenant_modules_tenant_select
    ON collabio.tenant_modules
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS tenant_modules_tenant_insert ON collabio.tenant_modules;
CREATE POLICY tenant_modules_tenant_insert
    ON collabio.tenant_modules
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS tenant_modules_tenant_update ON collabio.tenant_modules;
CREATE POLICY tenant_modules_tenant_update
    ON collabio.tenant_modules
    FOR UPDATE
    USING (tenant_id = collabio.current_tenant_id())
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS tenant_modules_no_hard_delete ON collabio.tenant_modules;
CREATE POLICY tenant_modules_no_hard_delete
    ON collabio.tenant_modules
    FOR DELETE
    USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA collabio TO collabio_app';
        EXECUTE 'GRANT SELECT ON TABLE collabio.module_catalog TO collabio_app';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE collabio.tenant_modules TO collabio_app';
    END IF;
END
$$;
