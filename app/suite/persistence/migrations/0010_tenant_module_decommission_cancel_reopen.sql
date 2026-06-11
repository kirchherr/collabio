-- 0010_tenant_module_decommission_cancel_reopen.sql
-- Explicit cancel and reopen evidence for tenant module decommission workflows.

ALTER TABLE collabio.tenant_modules
    ADD COLUMN IF NOT EXISTS decommission_cancelled_at_utc timestamptz;

ALTER TABLE collabio.tenant_modules
    ADD COLUMN IF NOT EXISTS decommission_reopened_at_utc timestamptz;

ALTER TABLE collabio.tenant_modules
    DROP CONSTRAINT IF EXISTS tenant_modules_decommission_cancel_evidence_check;

ALTER TABLE collabio.tenant_modules
    ADD CONSTRAINT tenant_modules_decommission_cancel_evidence_check
    CHECK (
        decommission_cancelled_at_utc IS NULL
        OR (
            decommission_requested_at_utc IS NOT NULL
            AND decommission_evidence_refs ? 'cancel_approval_ref'
            AND decommission_evidence_refs ? 'cancel_audit_evidence_ref'
        )
    );

ALTER TABLE collabio.tenant_modules
    DROP CONSTRAINT IF EXISTS tenant_modules_decommission_cancel_disabled_features_check;

ALTER TABLE collabio.tenant_modules
    ADD CONSTRAINT tenant_modules_decommission_cancel_disabled_features_check
    CHECK (
        decommission_cancelled_at_utc IS NULL
        OR status <> 'disabled'
        OR NOT (enabled_features @? '$.* ? (@ == true)')
    );

ALTER TABLE collabio.tenant_modules
    DROP CONSTRAINT IF EXISTS tenant_modules_decommission_reopen_evidence_check;

ALTER TABLE collabio.tenant_modules
    ADD CONSTRAINT tenant_modules_decommission_reopen_evidence_check
    CHECK (
        decommission_reopened_at_utc IS NULL
        OR (
            decommission_requested_at_utc IS NOT NULL
            AND decommission_blocked_at_utc IS NOT NULL
            AND decommission_evidence_refs ? 'retention_evaluation_ref'
            AND decommission_evidence_refs ? 'legal_hold_check_ref'
            AND decommission_evidence_refs ? 'export_archive_decision_ref'
            AND decommission_evidence_refs ? 'audit_evidence_ref'
            AND decommission_evidence_refs ? 'backup_restore_evidence_ref'
            AND decommission_evidence_refs ? 'blocker_report_ref'
            AND decommission_evidence_refs ? 'remediation_plan_ref'
            AND decommission_evidence_refs ? 'reopen_approval_ref'
            AND decommission_evidence_refs ? 'blocker_remediation_evidence_ref'
            AND decommission_evidence_refs ? 'reopen_audit_evidence_ref'
        )
    );

COMMENT ON COLUMN collabio.tenant_modules.decommission_cancelled_at_utc IS
    'Timestamp for an explicitly approved decommission cancellation that returns the tenant module to disabled lifecycle state.';

COMMENT ON COLUMN collabio.tenant_modules.decommission_reopened_at_utc IS
    'Timestamp for an explicitly approved reopen after a blocked decommission workflow has remediation evidence.';
