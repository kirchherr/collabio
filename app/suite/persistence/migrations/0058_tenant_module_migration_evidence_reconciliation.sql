-- 0058_tenant_module_migration_evidence_reconciliation.sql
-- Reconcile newly required CRM migration evidence for already provisioned tenants.

WITH migration_entry AS (
    SELECT jsonb_build_object(
        'version', version,
        'name', name,
        'module_id', module_id,
        'checksum', checksum,
        'evidence_refs', evidence_refs,
        'blocks_startup', blocks_startup
    ) AS evidence
    FROM collabio.schema_migrations
    WHERE version = '0057'
      AND module_id = 'crm_erp'
      AND blocks_startup = true
), stale_tenants AS (
    SELECT tenant_id, module_id
    FROM collabio.tenant_modules
    WHERE module_id = 'crm_erp'
      AND status NOT IN ('available', 'provisioning')
      AND NOT EXISTS (
          SELECT 1
          FROM jsonb_array_elements(migration_evidence) AS item
          WHERE item ->> 'version' = '0057'
      )
)
UPDATE collabio.tenant_modules AS tenant_module
SET migration_evidence = tenant_module.migration_evidence || jsonb_build_array(migration_entry.evidence),
    updated_at_utc = now()
FROM migration_entry, stale_tenants
WHERE tenant_module.tenant_id = stale_tenants.tenant_id
  AND tenant_module.module_id = stale_tenants.module_id;

COMMENT ON COLUMN collabio.tenant_modules.migration_evidence IS
    'Checksum-bound startup migration manifest entries; new required entries are reconciled during controlled upgrades.';
