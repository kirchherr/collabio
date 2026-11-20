-- 0030_platform_module_registry_runtime_store.sql
-- Persistent module registry runtime store, canonical seed/backfill, and worker-safe discovery grants.

ALTER TABLE collabio.module_catalog
    ADD COLUMN IF NOT EXISTS required_migration_versions jsonb NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE collabio.module_catalog
    DROP CONSTRAINT IF EXISTS module_catalog_required_migration_versions_json_check;

ALTER TABLE collabio.module_catalog
    ADD CONSTRAINT module_catalog_required_migration_versions_json_check
    CHECK (
        jsonb_typeof(required_migration_versions) = 'array'
        AND NOT required_migration_versions @? '$[*] ? (!(@ like_regex "^[0-9]{4}$"))'
    );

COMMENT ON COLUMN collabio.module_catalog.required_migration_versions IS
    'Startup-blocking migration versions required before a tenant module can be provisioned or enabled.';

INSERT INTO collabio.module_catalog (
    module_id,
    display_name,
    module_version,
    module_kind,
    status,
    description,
    manifest_hash,
    required_migration_versions,
    schema_version
)
VALUES
    (
        'crm_erp',
        'CRM/ERP',
        '0.1.0',
        'business_domain',
        'installed',
        'Optional CRM/ERP business module.',
        'sha256:crm-erp-module-manifest',
        '["0007", "0008", "0009", "0010", "0011", "0016", "0017", "0018", "0019", "0020"]'::jsonb,
        'module_catalog.v1'
    ),
    (
        'knowledge_base',
        'Knowledge Base',
        '0.1.0',
        'business_domain',
        'installed',
        'Optional governed knowledge base module.',
        'sha256:knowledge-base-module-manifest',
        '["0007", "0008", "0009", "0010", "0011", "0021", "0022", "0023", "0024", "0025", "0026", "0027", "0028", "0029"]'::jsonb,
        'module_catalog.v1'
    )
ON CONFLICT (module_id) DO UPDATE
SET display_name = EXCLUDED.display_name,
    module_version = EXCLUDED.module_version,
    module_kind = EXCLUDED.module_kind,
    status = EXCLUDED.status,
    description = EXCLUDED.description,
    manifest_hash = EXCLUDED.manifest_hash,
    required_migration_versions = EXCLUDED.required_migration_versions,
    schema_version = EXCLUDED.schema_version;

INSERT INTO collabio.tenant_modules (
    tenant_id,
    module_id,
    status,
    enabled_features,
    policy_snapshot_hash,
    changed_by,
    audit_chain_ref,
    schema_version
)
VALUES
    (
        'tenant-demo',
        'crm_erp',
        'available',
        '{
            "crm_erp.crm.accounts": true,
            "crm_erp.crm.contacts": true,
            "crm_erp.crm.activities": true,
            "crm_erp.erp.products": true,
            "crm_erp.erp.suppliers": true,
            "crm_erp.erp.orders": true,
            "crm_erp.erp.invoices": true,
            "crm_erp.legacy_import.sqlserver": false,
            "crm_erp.legal_hold": true,
            "crm_erp.rag_indexing": false,
            "crm_erp.ai_assist": false
        }'::jsonb,
        'sha256:demo-module-policy',
        'system',
        'audit:module-seed',
        'tenant_module.v1'
    ),
    (
        'tenant-demo',
        'knowledge_base',
        'available',
        '{
            "knowledge_base.articles.read": true,
            "knowledge_base.articles.write": false,
            "knowledge_base.evidence.read": true,
            "knowledge_base.rag.index": false,
            "knowledge_base.ai_assist": false
        }'::jsonb,
        'sha256:demo-module-policy',
        'system',
        'audit:module-seed',
        'tenant_module.v1'
    )
ON CONFLICT (tenant_id, module_id) DO NOTHING;

DROP POLICY IF EXISTS tenant_modules_worker_module_select ON collabio.tenant_modules;
CREATE POLICY tenant_modules_worker_module_select
    ON collabio.tenant_modules
    FOR SELECT
    TO collabio_worker
    USING (true);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT SELECT ON TABLE collabio.module_catalog TO collabio_app';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE collabio.tenant_modules TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA collabio TO collabio_worker';
        EXECUTE 'GRANT SELECT ON TABLE collabio.module_catalog TO collabio_worker';
        EXECUTE 'GRANT SELECT ON TABLE collabio.tenant_modules TO collabio_worker';
    END IF;
END
$$;
