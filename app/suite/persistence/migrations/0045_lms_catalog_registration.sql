-- 0045_lms_catalog_registration.sql
-- Registers the LMS module package in the global catalog as not installed.
-- This creates no tenant state, LMS schema, LMS tables, content, worker queue, or API runtime.

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
VALUES (
    'lms',
    'Learning Management',
    '0.1.0',
    'business_domain',
    'not_installed',
    'Optional governed learning management module. Catalog-registered only; package installation, migrations, tenant provisioning, API routes, content runtime, RAG, and AI assist remain separate gates.',
    'sha256:lms-module-manifest',
    '[]'::jsonb,
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
