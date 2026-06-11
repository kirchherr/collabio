-- 0008_tenant_module_decommission_evidence.sql
-- Evidence references for tenant module decommission requests.

ALTER TABLE collabio.tenant_modules
    ADD COLUMN IF NOT EXISTS decommission_evidence_refs jsonb NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE collabio.tenant_modules
    DROP CONSTRAINT IF EXISTS tenant_modules_decommission_evidence_json_check;

ALTER TABLE collabio.tenant_modules
    ADD CONSTRAINT tenant_modules_decommission_evidence_json_check
    CHECK (jsonb_typeof(decommission_evidence_refs) = 'object');

ALTER TABLE collabio.tenant_modules
    DROP CONSTRAINT IF EXISTS tenant_modules_decommission_request_evidence_check;

ALTER TABLE collabio.tenant_modules
    ADD CONSTRAINT tenant_modules_decommission_request_evidence_check
    CHECK (
        status <> 'decommission_requested'
        OR (
            decommission_evidence_refs ? 'retention_evaluation_ref'
            AND decommission_evidence_refs ? 'legal_hold_check_ref'
            AND decommission_evidence_refs ? 'export_archive_decision_ref'
            AND decommission_evidence_refs ? 'audit_evidence_ref'
            AND decommission_evidence_refs ? 'backup_restore_evidence_ref'
        )
    );

ALTER TABLE collabio.tenant_modules
    DROP CONSTRAINT IF EXISTS tenant_modules_decommission_request_features_check;

ALTER TABLE collabio.tenant_modules
    ADD CONSTRAINT tenant_modules_decommission_request_features_check
    CHECK (
        status <> 'decommission_requested'
        OR NOT (enabled_features @? '$.* ? (@ == true)')
    );

COMMENT ON COLUMN collabio.tenant_modules.decommission_evidence_refs IS
    'Namespaced references to retention, legal-hold, export/archive, audit, and backup/restore evidence required before a module can be decommission requested.';
