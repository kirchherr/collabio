-- 0032_source_object_preview_renderer_evidence.sql
-- Append-only metadata-only renderer sandbox evidence store.

DO $$
DECLARE
    constraint_record record;
BEGIN
    FOR constraint_record IN
        SELECT conname
        FROM pg_constraint
        WHERE conrelid = 'collabio.source_object_preview_decision_evidence'::regclass
          AND contype = 'c'
          AND pg_get_constraintdef(oid) LIKE '%renderer_sandbox_evidence_verified%'
          AND pg_get_constraintdef(oid) LIKE '%renderer_sandbox_evidence_ref IS NOT NULL%'
    LOOP
        EXECUTE format(
            'ALTER TABLE collabio.source_object_preview_decision_evidence DROP CONSTRAINT %I',
            constraint_record.conname
        );
    END LOOP;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'collabio.source_object_preview_decision_evidence'::regclass
          AND conname = 'source_object_preview_decision_renderer_verified_requires_ref'
    ) THEN
        ALTER TABLE collabio.source_object_preview_decision_evidence
            ADD CONSTRAINT source_object_preview_decision_renderer_verified_requires_ref
            CHECK (
                renderer_sandbox_evidence_verified = false
                OR renderer_sandbox_evidence_ref IS NOT NULL
            );
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS collabio.source_object_preview_renderer_evidence (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    source_object_id text NOT NULL CHECK (source_object_id <> ''),
    source_version_id text NOT NULL CHECK (source_version_id <> ''),
    source_object_type text NOT NULL CHECK (
        source_object_type IN ('document', 'mail', 'attachment', 'comment', 'wiki', 'procedure_doc')
    ),
    source_manifest_hash text NOT NULL CHECK (source_manifest_hash ~ '^sha256:[a-f0-9]{64}$'),
    source_content_hash text NOT NULL CHECK (source_content_hash ~ '^sha256:[a-f0-9]{64}$'),
    source_acl_version integer NOT NULL CHECK (source_acl_version >= 1),
    preview_slot_id text NOT NULL CHECK (preview_slot_id <> ''),
    preview_policy_id text NOT NULL CHECK (preview_policy_id <> ''),
    gate_id text NOT NULL CHECK (gate_id <> ''),
    parser_profile_id text NOT NULL CHECK (parser_profile_id <> ''),
    sanitizer_profile_id text NOT NULL CHECK (sanitizer_profile_id <> ''),
    worker_profile_id text NOT NULL CHECK (worker_profile_id <> ''),
    worker_queue_id text NOT NULL CHECK (worker_queue_id = 'source-preview-renderer-runs'),
    worker_job_id text NOT NULL CHECK (worker_job_id ~ '^preview-renderer-job:sha256:[a-f0-9]{64}$'),
    worker_idempotency_key_hash text NOT NULL CHECK (worker_idempotency_key_hash ~ '^sha256:[a-f0-9]{64}$'),
    worker_queue_binding_ref text NOT NULL CHECK (
        worker_queue_binding_ref ~ '^worker-queue:source-preview-renderer-runs:sha256:[a-f0-9]{64}$'
    ),
    parser_sanitizer_evidence_ref text NOT NULL CHECK (
        parser_sanitizer_evidence_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'
    ),
    backup_coverage_evidence_ref text NOT NULL CHECK (
        backup_coverage_evidence_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'
    ),
    restore_evidence_ref text NOT NULL CHECK (
        restore_evidence_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'
    ),
    sandbox_boundaries jsonb NOT NULL CHECK (
        jsonb_typeof(sandbox_boundaries) = 'array'
        AND sandbox_boundaries ? 'network_access_allowed=false'
        AND sandbox_boundaries ? 'external_resource_loading=false'
        AND sandbox_boundaries ? 'rendered_content_included=false'
        AND sandbox_boundaries ? 'raw_source_content_returned=false'
        AND sandbox_boundaries ? 'temporary_workspace_destroyed=true'
    ),
    access_checked boolean NOT NULL DEFAULT true CHECK (access_checked = true),
    rendering_allowed boolean NOT NULL DEFAULT false CHECK (rendering_allowed = false),
    content_rendered boolean NOT NULL DEFAULT false CHECK (content_rendered = false),
    content_included boolean NOT NULL DEFAULT false CHECK (content_included = false),
    output_persisted boolean NOT NULL DEFAULT false CHECK (output_persisted = false),
    external_fetch_allowed boolean NOT NULL DEFAULT false CHECK (external_fetch_allowed = false),
    temporary_workspace_destroyed boolean NOT NULL DEFAULT true CHECK (temporary_workspace_destroyed = true),
    source_detail_audit_event_id text NOT NULL CHECK (source_detail_audit_event_id <> ''),
    audit_event_id text NOT NULL CHECK (audit_event_id <> ''),
    requested_by text NOT NULL CHECK (requested_by <> ''),
    reason_hash text NOT NULL CHECK (reason_hash ~ '^sha256:[a-f0-9]{64}$'),
    renderer_sandbox_evidence_hash text NOT NULL CHECK (
        renderer_sandbox_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    renderer_sandbox_evidence_ref text NOT NULL CHECK (
        renderer_sandbox_evidence_ref = 'renderer-sandbox:' || renderer_sandbox_evidence_hash
    ),
    captured_at_utc timestamptz NOT NULL DEFAULT now(),
    schema_version text NOT NULL DEFAULT 'source_object_preview_renderer_sandbox_evidence.v1' CHECK (
        schema_version = 'source_object_preview_renderer_sandbox_evidence.v1'
    ),
    PRIMARY KEY (tenant_id, renderer_sandbox_evidence_hash)
);

COMMENT ON TABLE collabio.source_object_preview_renderer_evidence IS
    'Tenant-scoped append-only metadata-only evidence for source-object preview renderer sandbox worker runs.';

COMMENT ON COLUMN collabio.source_object_preview_renderer_evidence.sandbox_boundaries IS
    'Sandbox controls only. Source text, rendered content, mail bodies, attachment bytes, prompts, outputs, embeddings, transcripts, and raw payloads are excluded.';

CREATE INDEX IF NOT EXISTS source_object_preview_renderer_source_idx
    ON collabio.source_object_preview_renderer_evidence (
        tenant_id,
        source_object_id,
        source_version_id,
        captured_at_utc
    );

CREATE INDEX IF NOT EXISTS source_object_preview_renderer_queue_idx
    ON collabio.source_object_preview_renderer_evidence (
        tenant_id,
        worker_queue_id,
        worker_idempotency_key_hash,
        captured_at_utc
    );

CREATE INDEX IF NOT EXISTS source_object_preview_renderer_policy_idx
    ON collabio.source_object_preview_renderer_evidence (tenant_id, preview_policy_id, worker_profile_id);

ALTER TABLE collabio.source_object_preview_renderer_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.source_object_preview_renderer_evidence FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS source_object_preview_renderer_tenant_select
    ON collabio.source_object_preview_renderer_evidence;
CREATE POLICY source_object_preview_renderer_tenant_select
    ON collabio.source_object_preview_renderer_evidence
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS source_object_preview_renderer_tenant_insert
    ON collabio.source_object_preview_renderer_evidence;
CREATE POLICY source_object_preview_renderer_tenant_insert
    ON collabio.source_object_preview_renderer_evidence
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS source_object_preview_renderer_no_update
    ON collabio.source_object_preview_renderer_evidence;
CREATE POLICY source_object_preview_renderer_no_update
    ON collabio.source_object_preview_renderer_evidence
    FOR UPDATE
    USING (false);

DROP POLICY IF EXISTS source_object_preview_renderer_no_hard_delete
    ON collabio.source_object_preview_renderer_evidence;
CREATE POLICY source_object_preview_renderer_no_hard_delete
    ON collabio.source_object_preview_renderer_evidence
    FOR DELETE
    USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.source_object_preview_renderer_evidence TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.source_object_preview_renderer_evidence TO collabio_worker';
    END IF;
END
$$;
