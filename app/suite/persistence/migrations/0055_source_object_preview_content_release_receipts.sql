-- 0055_source_object_preview_content_release_receipts.sql
-- Tenant-scoped append-only metadata evidence for one-time sanitized plain-text preview releases.

CREATE TABLE IF NOT EXISTS collabio.source_object_preview_content_release_receipts (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    source_object_id text NOT NULL CHECK (source_object_id <> ''),
    source_version_id text NOT NULL CHECK (source_version_id <> ''),
    source_object_type text NOT NULL CHECK (source_object_type IN ('document', 'wiki', 'procedure_doc')),
    source_manifest_hash text NOT NULL CHECK (source_manifest_hash ~ '^sha256:[a-f0-9]{64}$'),
    source_content_hash text NOT NULL CHECK (source_content_hash ~ '^sha256:[a-f0-9]{64}$'),
    source_acl_version integer NOT NULL CHECK (source_acl_version >= 1),
    source_mime_type text NOT NULL CHECK (source_mime_type IN ('text/plain', 'text/markdown')),
    preview_decision_evidence_hash text NOT NULL CHECK (
        preview_decision_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    renderer_sandbox_evidence_hash text NOT NULL CHECK (
        renderer_sandbox_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    renderer_release_gate_evidence_hash text NOT NULL CHECK (
        renderer_release_gate_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    command_hash text NOT NULL CHECK (command_hash ~ '^sha256:[a-f0-9]{64}$'),
    sanitized_content_hash text NOT NULL CHECK (sanitized_content_hash ~ '^sha256:[a-f0-9]{64}$'),
    sanitized_content_byte_length integer NOT NULL CHECK (
        sanitized_content_byte_length >= 0 AND sanitized_content_byte_length <= 262144
    ),
    released_at_utc timestamptz NOT NULL,
    audit_event_id text NOT NULL CHECK (audit_event_id <> ''),
    receipt jsonb NOT NULL CHECK (
        jsonb_typeof(receipt) = 'object'
        AND receipt ->> 'schema_version' = 'source_object_preview_content_release_receipt.v1'
        AND receipt ->> 'continuity_domain' = 'source_object_preview_content_release_evidence'
        AND (receipt ->> 'access_checked')::boolean = true
        AND (receipt ->> 'tenant_policy_checked')::boolean = true
        AND (receipt ->> 'renderer_evidence_checked')::boolean = true
        AND (receipt ->> 'renderer_release_gate_checked')::boolean = true
        AND (receipt ->> 'source_integrity_checked')::boolean = true
        AND (receipt ->> 'content_included_in_receipt')::boolean = false
        AND (receipt ->> 'content_persisted')::boolean = false
        AND (receipt ->> 'external_fetch_allowed')::boolean = false
        AND (receipt ->> 'active_content_allowed')::boolean = false
        AND (receipt ->> 'attachment_open_allowed')::boolean = false
        AND (receipt ->> 'mail_body_release_allowed')::boolean = false
        AND (receipt ->> 'destructive_action_allowed')::boolean = false
        AND NOT (receipt ? 'content')
        AND NOT (receipt ? 'human_confirmation_statement')
        AND NOT (receipt ? 'reason')
        AND NOT (receipt ? 'raw_payload')
    ),
    evidence_hash text NOT NULL CHECK (evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    captured_at_utc timestamptz NOT NULL DEFAULT now(),
    schema_version text NOT NULL DEFAULT 'source_object_preview_content_release_receipt.v1' CHECK (
        schema_version = 'source_object_preview_content_release_receipt.v1'
    ),
    PRIMARY KEY (tenant_id, evidence_hash),
    CHECK ((receipt ->> 'tenant_id') = tenant_id),
    CHECK ((receipt ->> 'source_object_id') = source_object_id),
    CHECK ((receipt ->> 'source_version_id') = source_version_id),
    CHECK ((receipt ->> 'source_object_type') = source_object_type),
    CHECK ((receipt ->> 'source_manifest_hash') = source_manifest_hash),
    CHECK ((receipt ->> 'source_content_hash') = source_content_hash),
    CHECK ((receipt ->> 'source_acl_version')::integer = source_acl_version),
    CHECK ((receipt ->> 'source_mime_type') = source_mime_type),
    CHECK ((receipt ->> 'evidence_hash') = evidence_hash),
    CHECK (position('"human_confirmation_statement"' in lower(receipt::text)) = 0),
    CHECK (position('"content"' in lower(receipt::text)) = 0),
    CHECK (position('"reason"' in lower(receipt::text)) = 0),
    CHECK (position('"password"' in lower(receipt::text)) = 0)
);

COMMENT ON TABLE collabio.source_object_preview_content_release_receipts IS
    'Append-only tenant-scoped evidence for one-time ACL-checked sanitized plain-text preview releases. No source or rendered content.';

COMMENT ON COLUMN collabio.source_object_preview_content_release_receipts.receipt IS
    'Metadata-only source_object_preview_content_release_receipt.v1 JSON. Source text, mail bodies, attachment bytes, confirmation text, and reasons are excluded.';

CREATE INDEX IF NOT EXISTS source_object_preview_content_release_source_idx
    ON collabio.source_object_preview_content_release_receipts (
        tenant_id, source_object_id, source_version_id, released_at_utc
    );

CREATE INDEX IF NOT EXISTS source_object_preview_content_release_gate_idx
    ON collabio.source_object_preview_content_release_receipts (
        tenant_id, renderer_release_gate_evidence_hash, released_at_utc
    );

ALTER TABLE collabio.source_object_preview_content_release_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.source_object_preview_content_release_receipts FORCE ROW LEVEL SECURITY;

CREATE POLICY source_object_preview_content_release_tenant_select
    ON collabio.source_object_preview_content_release_receipts
    FOR SELECT USING (tenant_id = collabio.current_tenant_id());

CREATE POLICY source_object_preview_content_release_tenant_insert
    ON collabio.source_object_preview_content_release_receipts
    FOR INSERT WITH CHECK (tenant_id = collabio.current_tenant_id());

CREATE POLICY source_object_preview_content_release_no_update
    ON collabio.source_object_preview_content_release_receipts
    FOR UPDATE USING (false);

CREATE POLICY source_object_preview_content_release_no_hard_delete
    ON collabio.source_object_preview_content_release_receipts
    FOR DELETE USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.source_object_preview_content_release_receipts TO collabio_app';
    END IF;
END
$$;
