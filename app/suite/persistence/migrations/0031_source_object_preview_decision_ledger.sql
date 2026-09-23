-- 0031_source_object_preview_decision_ledger.sql
-- Append-only metadata-only source-object preview decision ledger.

CREATE TABLE IF NOT EXISTS collabio.source_object_preview_decision_evidence (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    source_object_id text NOT NULL CHECK (source_object_id <> ''),
    source_version_id text NOT NULL CHECK (source_version_id <> ''),
    source_object_type text NOT NULL CHECK (
        source_object_type IN ('document', 'mail', 'attachment', 'comment', 'wiki', 'procedure_doc')
    ),
    preview_slot_id text NOT NULL CHECK (preview_slot_id <> ''),
    preview_policy_id text NOT NULL CHECK (preview_policy_id <> ''),
    decision_status text NOT NULL DEFAULT 'blocked' CHECK (decision_status = 'blocked'),
    content_release_allowed boolean NOT NULL DEFAULT false CHECK (content_release_allowed = false),
    content_included boolean NOT NULL DEFAULT false CHECK (content_included = false),
    access_checked boolean NOT NULL DEFAULT true CHECK (access_checked = true),
    tenant_policy_checked boolean NOT NULL DEFAULT true CHECK (tenant_policy_checked = true),
    tenant_preview_policy_enabled boolean NOT NULL DEFAULT false,
    required_content_release_evidence jsonb NOT NULL CHECK (
        jsonb_typeof(required_content_release_evidence) = 'array'
        AND required_content_release_evidence ? 'tenant_preview_policy_enabled'
        AND required_content_release_evidence ? 'source_object_acl_checked'
        AND required_content_release_evidence ? 'source_detail_audit_event'
        AND required_content_release_evidence ? 'parser_sanitizer_evidence'
        AND required_content_release_evidence ? 'human_content_release_confirmation'
        AND required_content_release_evidence ? 'renderer_sandbox_worker_evidence'
        AND required_content_release_evidence ? 'backup_coverage_evidence'
        AND required_content_release_evidence ? 'restore_drill_evidence'
    ),
    provided_evidence jsonb NOT NULL CHECK (jsonb_typeof(provided_evidence) = 'array'),
    provided_evidence_refs jsonb NOT NULL CHECK (jsonb_typeof(provided_evidence_refs) = 'array'),
    missing_evidence jsonb NOT NULL CHECK (jsonb_typeof(missing_evidence) = 'array'),
    blocking_reasons jsonb NOT NULL CHECK (
        jsonb_typeof(blocking_reasons) = 'array'
        AND blocking_reasons ? 'content_preview_skeleton_blocks_release_until_renderer_operational'
    ),
    parser_profile_id text NOT NULL CHECK (parser_profile_id <> ''),
    sanitizer_profile_id text NOT NULL CHECK (sanitizer_profile_id <> ''),
    renderer_sandbox_required boolean NOT NULL DEFAULT true CHECK (renderer_sandbox_required = true),
    renderer_sandbox_evidence_ref text CHECK (
        renderer_sandbox_evidence_ref IS NULL
        OR renderer_sandbox_evidence_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'
    ),
    backup_coverage_required boolean NOT NULL DEFAULT true CHECK (backup_coverage_required = true),
    backup_coverage_evidence_ref text CHECK (
        backup_coverage_evidence_ref IS NULL
        OR backup_coverage_evidence_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'
    ),
    restore_evidence_required boolean NOT NULL DEFAULT true CHECK (restore_evidence_required = true),
    restore_evidence_ref text CHECK (
        restore_evidence_ref IS NULL
        OR restore_evidence_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'
    ),
    human_confirmation_reference text CHECK (
        human_confirmation_reference IS NULL
        OR human_confirmation_reference ~ '^[a-z0-9][a-z0-9_+.-]*:.+'
    ),
    renderer_sandbox_evidence_verified boolean NOT NULL DEFAULT false,
    backup_coverage_evidence_verified boolean NOT NULL DEFAULT false,
    restore_evidence_verified boolean NOT NULL DEFAULT false,
    human_confirmation_verified boolean NOT NULL DEFAULT false,
    content_release_evidence_complete boolean NOT NULL DEFAULT false,
    source_detail_audit_event_id text NOT NULL CHECK (source_detail_audit_event_id <> ''),
    audit_event_id text NOT NULL CHECK (audit_event_id <> ''),
    requested_by text NOT NULL CHECK (requested_by <> ''),
    reason_hash text NOT NULL CHECK (reason_hash ~ '^sha256:[a-f0-9]{64}$'),
    evidence_hash text NOT NULL CHECK (evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    captured_at_utc timestamptz NOT NULL DEFAULT now(),
    schema_version text NOT NULL DEFAULT 'source_object_preview_decision_evidence.v1' CHECK (
        schema_version = 'source_object_preview_decision_evidence.v1'
    ),
    PRIMARY KEY (tenant_id, evidence_hash),
    CHECK (renderer_sandbox_evidence_verified = (renderer_sandbox_evidence_ref IS NOT NULL)),
    CHECK (backup_coverage_evidence_verified = (backup_coverage_evidence_ref IS NOT NULL)),
    CHECK (restore_evidence_verified = (restore_evidence_ref IS NOT NULL)),
    CHECK (human_confirmation_verified = (human_confirmation_reference IS NOT NULL)),
    CHECK (content_release_evidence_complete = (jsonb_array_length(missing_evidence) = 0))
);

COMMENT ON TABLE collabio.source_object_preview_decision_evidence IS
    'Tenant-scoped append-only metadata-only evidence ledger for blocked source-object preview decisions.';

COMMENT ON COLUMN collabio.source_object_preview_decision_evidence.provided_evidence_refs IS
    'Namespaced evidence references only. Source text, mail bodies, attachment bytes, prompts, outputs, embeddings, transcripts, and raw payloads are excluded.';

CREATE INDEX IF NOT EXISTS source_object_preview_decision_source_idx
    ON collabio.source_object_preview_decision_evidence (
        tenant_id,
        source_object_id,
        source_version_id,
        captured_at_utc
    );

CREATE INDEX IF NOT EXISTS source_object_preview_decision_policy_idx
    ON collabio.source_object_preview_decision_evidence (tenant_id, preview_policy_id, decision_status);

ALTER TABLE collabio.source_object_preview_decision_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.source_object_preview_decision_evidence FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS source_object_preview_decision_tenant_select
    ON collabio.source_object_preview_decision_evidence;
CREATE POLICY source_object_preview_decision_tenant_select
    ON collabio.source_object_preview_decision_evidence
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS source_object_preview_decision_tenant_insert
    ON collabio.source_object_preview_decision_evidence;
CREATE POLICY source_object_preview_decision_tenant_insert
    ON collabio.source_object_preview_decision_evidence
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS source_object_preview_decision_no_update
    ON collabio.source_object_preview_decision_evidence;
CREATE POLICY source_object_preview_decision_no_update
    ON collabio.source_object_preview_decision_evidence
    FOR UPDATE
    USING (false);

DROP POLICY IF EXISTS source_object_preview_decision_no_hard_delete
    ON collabio.source_object_preview_decision_evidence;
CREATE POLICY source_object_preview_decision_no_hard_delete
    ON collabio.source_object_preview_decision_evidence
    FOR DELETE
    USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.source_object_preview_decision_evidence TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT SELECT ON TABLE collabio.source_object_preview_decision_evidence TO collabio_worker';
    END IF;
END
$$;
