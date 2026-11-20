-- 0051_tickets_incidents_catalog_registration.sql
-- Registers the Tickets & Incidents module package in the global catalog as not installed.
-- This creates no tenant state, tickets schema, ticket/incident tables, content, worker queue, or business API runtime.

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
    'tickets_incidents',
    'Tickets and Incidents',
    '0.1.0',
    'business_domain',
    'not_installed',
    'Optional governed tickets and incidents module. Catalog-registered only; storage migrations, tenant provisioning, business API routes, workflow automation, notifications, RAG, and AI assist remain separate gates.',
    'sha256:tickets-incidents-module-manifest',
    '["0051"]'::jsonb,
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
