-- 0050_tasks_activities_catalog_registration.sql
-- Registers the Tasks & Activities module package in the global catalog as not installed.
-- This creates no tenant state, tasks schema, task/activity tables, content, worker queue, or business API runtime.

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
    'tasks_activities',
    'Tasks and Activities',
    '0.1.0',
    'business_domain',
    'not_installed',
    'Optional governed tasks and activities module. Catalog-registered only; storage migrations, tenant provisioning, business API routes, workflow automation, notifications, RAG, and AI assist remain separate gates.',
    'sha256:tasks-activities-module-manifest',
    '["0050"]'::jsonb,
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
