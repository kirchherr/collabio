-- 0026_source_object_write_receipts.sql
-- Durable metadata-only receipt boundary for source object writes.

CREATE TABLE IF NOT EXISTS collabio.source_object_write_receipts (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    receipt_reference text NOT NULL CHECK (receipt_reference ~ '^[a-z][a-z0-9_+.-]*:.+'),
    object_id text NOT NULL CHECK (object_id <> ''),
    object_type text NOT NULL CHECK (
        object_type IN ('document', 'mail', 'attachment', 'comment', 'wiki', 'procedure_doc')
    ),
    version_id text NOT NULL CHECK (version_id <> ''),
    title text NOT NULL CHECK (title <> ''),
    owner_principal_id text NOT NULL CHECK (owner_principal_id <> ''),
    created_by text NOT NULL CHECK (created_by <> ''),
    created_at_utc timestamptz NOT NULL,
    updated_at_utc timestamptz NOT NULL,
    classification text NOT NULL CHECK (
        classification IN (
            'public',
            'internal',
            'personal',
            'confidential',
            'gobd',
            'legal_hold',
            'ai_prompt',
            'ai_output',
            'rag_chunk',
            'embedding',
            'voice_transcript'
        )
    ),
    retention_policy_id text NOT NULL CHECK (retention_policy_id <> ''),
    legal_hold_state text NOT NULL DEFAULT 'none' CHECK (legal_hold_state IN ('none', 'active')),
    kms_key_ref text NOT NULL CHECK (kms_key_ref ~ '^[a-z][a-z0-9_+.-]*:.+'),
    manifest_hash text NOT NULL CHECK (manifest_hash ~ '^sha256:[a-f0-9]{64}$'),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z][a-z0-9_+.-]*:.+'),
    source_system text NOT NULL CHECK (source_system ~ '^[a-z][a-z0-9_+.-]*$'),
    source_schema_version text NOT NULL CHECK (source_schema_version <> ''),
    mime_type text NOT NULL CHECK (mime_type <> ''),
    acl_hash text NOT NULL CHECK (acl_hash ~ '^[a-z][a-z0-9_+.-]*:.+'),
    acl_version integer NOT NULL CHECK (acl_version >= 1),
    content_hash text NOT NULL CHECK (content_hash ~ '^[a-z][a-z0-9_+.-]*:.+'),
    content_byte_length integer NOT NULL CHECK (content_byte_length >= 0),
    lifecycle_state text NOT NULL CHECK (
        lifecycle_state IN (
            'working',
            'saved_version',
            'business_record',
            'worm_evidence',
            'restricted',
            'deleted',
            'cryptoshredded'
        )
    ),
    parent_object_id text,
    thread_id text,
    parser_profile_id text,
    captured_at_utc timestamptz NOT NULL DEFAULT now(),
    receipt_hash text NOT NULL CHECK (receipt_hash ~ '^sha256:[a-f0-9]{64}$'),
    receipt_schema_version text NOT NULL DEFAULT 'source_object_write_receipt.v1',
    PRIMARY KEY (tenant_id, receipt_hash),
    UNIQUE (tenant_id, object_id, version_id),
    CHECK (object_type NOT IN ('attachment', 'comment') OR parent_object_id IS NOT NULL),
    CHECK (object_type <> 'mail' OR mime_type = 'message/rfc822'),
    CHECK (legal_hold_state <> 'active' OR lifecycle_state NOT IN ('deleted', 'cryptoshredded'))
);

COMMENT ON TABLE collabio.source_object_write_receipts IS
    'Tenant-scoped append-only metadata receipts proving source object write boundaries before dependent module writes.';

COMMENT ON COLUMN collabio.source_object_write_receipts.receipt_hash IS
    'Canonical hash over receipt metadata. Object content, prompts, outputs, transcripts, embeddings, and raw payloads are excluded.';

CREATE INDEX IF NOT EXISTS source_object_write_receipts_object_version_idx
    ON collabio.source_object_write_receipts (tenant_id, object_id, version_id);

CREATE INDEX IF NOT EXISTS source_object_write_receipts_content_hash_idx
    ON collabio.source_object_write_receipts (tenant_id, content_hash);

CREATE INDEX IF NOT EXISTS source_object_write_receipts_audit_chain_idx
    ON collabio.source_object_write_receipts (tenant_id, audit_chain_ref);

ALTER TABLE collabio.source_object_write_receipts ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.source_object_write_receipts FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS source_object_write_receipts_tenant_select ON collabio.source_object_write_receipts;
CREATE POLICY source_object_write_receipts_tenant_select
    ON collabio.source_object_write_receipts
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS source_object_write_receipts_tenant_insert ON collabio.source_object_write_receipts;
CREATE POLICY source_object_write_receipts_tenant_insert
    ON collabio.source_object_write_receipts
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS source_object_write_receipts_no_update ON collabio.source_object_write_receipts;
CREATE POLICY source_object_write_receipts_no_update
    ON collabio.source_object_write_receipts
    FOR UPDATE
    USING (false);

DROP POLICY IF EXISTS source_object_write_receipts_no_hard_delete ON collabio.source_object_write_receipts;
CREATE POLICY source_object_write_receipts_no_hard_delete
    ON collabio.source_object_write_receipts
    FOR DELETE
    USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.source_object_write_receipts TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT SELECT ON TABLE collabio.source_object_write_receipts TO collabio_worker';
    END IF;
END
$$;
