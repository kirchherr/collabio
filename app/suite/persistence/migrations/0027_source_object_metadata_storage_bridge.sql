-- 0027_source_object_metadata_storage_bridge.sql
-- PostgreSQL source-object metadata and storage-manifest bridge without content bodies.

CREATE TABLE IF NOT EXISTS collabio.source_object_storage_manifests (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    object_id text NOT NULL CHECK (object_id <> ''),
    object_type text NOT NULL CHECK (
        object_type IN ('document', 'mail', 'attachment', 'comment', 'wiki', 'procedure_doc')
    ),
    source_version_id text NOT NULL CHECK (source_version_id <> ''),
    bucket_id text NOT NULL CHECK (bucket_id <> ''),
    object_key text NOT NULL CHECK (object_key <> ''),
    object_version_id text NOT NULL CHECK (object_version_id <> ''),
    storage_provider text NOT NULL CHECK (storage_provider <> ''),
    stored_at_utc timestamptz NOT NULL,
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
    retention_policy_id text NOT NULL CHECK (retention_policy_id <> ''),
    legal_hold_state text NOT NULL DEFAULT 'none' CHECK (legal_hold_state IN ('none', 'active')),
    kms_key_ref text NOT NULL CHECK (kms_key_ref ~ '^[a-z][a-z0-9_+.-]*:.+'),
    source_manifest_hash text NOT NULL CHECK (source_manifest_hash ~ '^sha256:[a-f0-9]{64}$'),
    content_hash text NOT NULL CHECK (content_hash ~ '^[a-z][a-z0-9_+.-]*:.+'),
    content_byte_length integer NOT NULL CHECK (content_byte_length >= 0),
    retention_manifest_hash text NOT NULL CHECK (retention_manifest_hash ~ '^sha256:[a-f0-9]{64}$'),
    retention_policy_snapshot_hash text NOT NULL CHECK (retention_policy_snapshot_hash ~ '^sha256:[a-f0-9]{64}$'),
    object_lock_mode text NOT NULL DEFAULT 'none' CHECK (object_lock_mode IN ('none', 'governance', 'compliance')),
    object_lock_retain_until_utc timestamptz,
    object_lock_legal_hold boolean NOT NULL DEFAULT false,
    worm_required boolean NOT NULL DEFAULT false,
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z][a-z0-9_+.-]*:.+'),
    manifest_hash text NOT NULL CHECK (manifest_hash ~ '^sha256:[a-f0-9]{64}$'),
    schema_version text NOT NULL DEFAULT 'storage_object_manifest.v1',
    captured_at_utc timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, manifest_hash),
    UNIQUE (tenant_id, bucket_id, object_key, object_version_id),
    CHECK (object_lock_mode <> 'none' OR object_lock_retain_until_utc IS NULL),
    CHECK (object_lock_mode <> 'none' OR NOT object_lock_legal_hold),
    CHECK (NOT worm_required OR object_lock_mode <> 'none')
);

CREATE TABLE IF NOT EXISTS collabio.source_object_metadata (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
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
    source_schema_version text NOT NULL DEFAULT 'source_object.v1' CHECK (source_schema_version <> ''),
    mime_type text NOT NULL DEFAULT 'text/plain' CHECK (mime_type <> ''),
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
    retention_manifest_hash text NOT NULL CHECK (retention_manifest_hash ~ '^sha256:[a-f0-9]{64}$'),
    retention_policy_snapshot_hash text NOT NULL CHECK (retention_policy_snapshot_hash ~ '^sha256:[a-f0-9]{64}$'),
    storage_manifest_hash text NOT NULL CHECK (storage_manifest_hash ~ '^sha256:[a-f0-9]{64}$'),
    source_object_write_receipt_hash text CHECK (source_object_write_receipt_hash ~ '^sha256:[a-f0-9]{64}$'),
    persisted_at_utc timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, object_id, version_id),
    UNIQUE (tenant_id, manifest_hash),
    CHECK (object_type NOT IN ('attachment', 'comment') OR parent_object_id IS NOT NULL),
    CHECK (object_type <> 'mail' OR mime_type = 'message/rfc822'),
    CHECK (legal_hold_state <> 'active' OR lifecycle_state NOT IN ('deleted', 'cryptoshredded')),
    FOREIGN KEY (tenant_id, storage_manifest_hash)
        REFERENCES collabio.source_object_storage_manifests (tenant_id, manifest_hash),
    FOREIGN KEY (tenant_id, source_object_write_receipt_hash)
        REFERENCES collabio.source_object_write_receipts (tenant_id, receipt_hash)
);

COMMENT ON TABLE collabio.source_object_metadata IS
    'Authoritative source-object metadata. Object bodies and native bytes stay behind the content-store bridge.';

COMMENT ON TABLE collabio.source_object_storage_manifests IS
    'Metadata-only storage manifests binding source objects to content-store object versions and restore evidence.';

CREATE INDEX IF NOT EXISTS source_object_metadata_latest_idx
    ON collabio.source_object_metadata (tenant_id, object_id, persisted_at_utc DESC);

CREATE INDEX IF NOT EXISTS source_object_metadata_content_hash_idx
    ON collabio.source_object_metadata (tenant_id, content_hash);

CREATE INDEX IF NOT EXISTS source_object_metadata_storage_manifest_idx
    ON collabio.source_object_metadata (tenant_id, storage_manifest_hash);

CREATE INDEX IF NOT EXISTS source_object_storage_manifests_object_idx
    ON collabio.source_object_storage_manifests (tenant_id, object_id, source_version_id);

CREATE INDEX IF NOT EXISTS source_object_storage_manifests_content_hash_idx
    ON collabio.source_object_storage_manifests (tenant_id, content_hash);

ALTER TABLE collabio.source_object_storage_manifests ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.source_object_storage_manifests FORCE ROW LEVEL SECURITY;
ALTER TABLE collabio.source_object_metadata ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.source_object_metadata FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS source_object_storage_manifests_tenant_select ON collabio.source_object_storage_manifests;
CREATE POLICY source_object_storage_manifests_tenant_select
    ON collabio.source_object_storage_manifests
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS source_object_storage_manifests_tenant_insert ON collabio.source_object_storage_manifests;
CREATE POLICY source_object_storage_manifests_tenant_insert
    ON collabio.source_object_storage_manifests
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS source_object_storage_manifests_no_update ON collabio.source_object_storage_manifests;
CREATE POLICY source_object_storage_manifests_no_update
    ON collabio.source_object_storage_manifests
    FOR UPDATE
    USING (false);

DROP POLICY IF EXISTS source_object_storage_manifests_no_hard_delete ON collabio.source_object_storage_manifests;
CREATE POLICY source_object_storage_manifests_no_hard_delete
    ON collabio.source_object_storage_manifests
    FOR DELETE
    USING (false);

DROP POLICY IF EXISTS source_object_metadata_tenant_select ON collabio.source_object_metadata;
CREATE POLICY source_object_metadata_tenant_select
    ON collabio.source_object_metadata
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS source_object_metadata_tenant_insert ON collabio.source_object_metadata;
CREATE POLICY source_object_metadata_tenant_insert
    ON collabio.source_object_metadata
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS source_object_metadata_no_update ON collabio.source_object_metadata;
CREATE POLICY source_object_metadata_no_update
    ON collabio.source_object_metadata
    FOR UPDATE
    USING (false);

DROP POLICY IF EXISTS source_object_metadata_no_hard_delete ON collabio.source_object_metadata;
CREATE POLICY source_object_metadata_no_hard_delete
    ON collabio.source_object_metadata
    FOR DELETE
    USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA collabio TO collabio_app';
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.source_object_storage_manifests TO collabio_app';
        EXECUTE 'GRANT SELECT, INSERT ON TABLE collabio.source_object_metadata TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT SELECT ON TABLE collabio.source_object_storage_manifests TO collabio_worker';
        EXECUTE 'GRANT SELECT ON TABLE collabio.source_object_metadata TO collabio_worker';
    END IF;
END
$$;
