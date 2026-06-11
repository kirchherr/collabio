-- 0009_tenant_module_decommission_completion.sql
-- Blocked and completed decommission workflow evidence.

ALTER TABLE collabio.tenant_modules
    ADD COLUMN IF NOT EXISTS decommission_blocked_at_utc timestamptz;

ALTER TABLE collabio.tenant_modules
    DROP CONSTRAINT IF EXISTS tenant_modules_decommission_blocked_timestamp_check;

ALTER TABLE collabio.tenant_modules
    ADD CONSTRAINT tenant_modules_decommission_blocked_timestamp_check
    CHECK (status <> 'decommission_blocked' OR decommission_blocked_at_utc IS NOT NULL);

ALTER TABLE collabio.tenant_modules
    DROP CONSTRAINT IF EXISTS tenant_modules_decommission_after_request_check;

ALTER TABLE collabio.tenant_modules
    ADD CONSTRAINT tenant_modules_decommission_after_request_check
    CHECK (
        status NOT IN ('decommission_blocked', 'decommissioned')
        OR decommission_requested_at_utc IS NOT NULL
    );

ALTER TABLE collabio.tenant_modules
    DROP CONSTRAINT IF EXISTS tenant_modules_decommission_blocked_evidence_check;

ALTER TABLE collabio.tenant_modules
    ADD CONSTRAINT tenant_modules_decommission_blocked_evidence_check
    CHECK (
        status <> 'decommission_blocked'
        OR (
            decommission_evidence_refs ? 'retention_evaluation_ref'
            AND decommission_evidence_refs ? 'legal_hold_check_ref'
            AND decommission_evidence_refs ? 'export_archive_decision_ref'
            AND decommission_evidence_refs ? 'audit_evidence_ref'
            AND decommission_evidence_refs ? 'backup_restore_evidence_ref'
            AND decommission_evidence_refs ? 'blocker_report_ref'
            AND decommission_evidence_refs ? 'remediation_plan_ref'
        )
    );

ALTER TABLE collabio.tenant_modules
    DROP CONSTRAINT IF EXISTS tenant_modules_decommission_completed_evidence_check;

ALTER TABLE collabio.tenant_modules
    ADD CONSTRAINT tenant_modules_decommission_completed_evidence_check
    CHECK (
        status <> 'decommissioned'
        OR (
            decommission_evidence_refs ? 'retention_evaluation_ref'
            AND decommission_evidence_refs ? 'legal_hold_check_ref'
            AND decommission_evidence_refs ? 'export_archive_decision_ref'
            AND decommission_evidence_refs ? 'audit_evidence_ref'
            AND decommission_evidence_refs ? 'backup_restore_evidence_ref'
            AND decommission_evidence_refs ? 'final_retention_disposition_ref'
            AND decommission_evidence_refs ? 'final_legal_hold_clearance_ref'
            AND decommission_evidence_refs ? 'final_export_archive_manifest_ref'
            AND decommission_evidence_refs ? 'final_audit_closure_ref'
            AND decommission_evidence_refs ? 'final_backup_disposition_ref'
            AND decommission_evidence_refs ? 'final_data_disposition_ref'
        )
    );

ALTER TABLE collabio.tenant_modules
    DROP CONSTRAINT IF EXISTS tenant_modules_decommission_request_features_check;

ALTER TABLE collabio.tenant_modules
    ADD CONSTRAINT tenant_modules_decommission_request_features_check
    CHECK (
        status NOT IN ('decommission_requested', 'decommission_blocked', 'decommissioned')
        OR NOT (enabled_features @? '$.* ? (@ == true)')
    );

COMMENT ON COLUMN collabio.tenant_modules.decommission_blocked_at_utc IS
    'Timestamp for a blocked tenant module decommission workflow while compliance access remains available.';
