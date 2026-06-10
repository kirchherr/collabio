-- 0001_pgvector_embeddings.sql
-- pgvector-backed embedding metadata schema.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE SCHEMA IF NOT EXISTS collabio;

DO $$
BEGIN
    CREATE TYPE collabio.vector_lifecycle_state AS ENUM (
        'active',
        'reindex_pending',
        'restricted',
        'deleted',
        'cryptoshredded'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE OR REPLACE FUNCTION collabio.current_tenant_id()
RETURNS text
LANGUAGE sql
STABLE
AS $$
    SELECT nullif(current_setting('app.tenant_id', true), '')
$$;

CREATE OR REPLACE FUNCTION collabio.touch_updated_at_utc()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at_utc = now();
    RETURN NEW;
END
$$;

CREATE TABLE IF NOT EXISTS collabio.embedding_models (
    embedding_model_id text NOT NULL,
    embedding_model_version text NOT NULL,
    provider text NOT NULL,
    deployment text NOT NULL,
    dimensions integer NOT NULL CHECK (dimensions > 0 AND dimensions <= 16000),
    distance_metric text NOT NULL DEFAULT 'cosine' CHECK (distance_metric IN ('cosine', 'l2', 'inner_product')),
    checksum text NOT NULL CHECK (checksum ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    approved_for_data_classes text[] NOT NULL DEFAULT ARRAY[]::text[],
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    approved_at_utc timestamptz,
    retired_at_utc timestamptz,
    PRIMARY KEY (embedding_model_id, embedding_model_version)
);

CREATE TABLE IF NOT EXISTS collabio.vector_embedding_chunks (
    tenant_id text NOT NULL,
    source_object_id text NOT NULL,
    source_object_type text NOT NULL,
    source_version_id text NOT NULL,
    chunk_id text NOT NULL,
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
    retention_policy_id text NOT NULL,
    legal_hold_state text NOT NULL DEFAULT 'none' CHECK (legal_hold_state IN ('none', 'active')),
    acl_hash text NOT NULL CHECK (acl_hash ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    acl_version integer NOT NULL CHECK (acl_version >= 1),
    embedding_model_id text NOT NULL,
    embedding_model_version text NOT NULL,
    embedding_dimensions integer NOT NULL CHECK (embedding_dimensions > 0 AND embedding_dimensions <= 16000),
    embedding vector NOT NULL,
    content_hash text NOT NULL CHECK (content_hash ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    content_byte_length integer NOT NULL CHECK (content_byte_length >= 0),
    lifecycle_state collabio.vector_lifecycle_state NOT NULL DEFAULT 'active',
    indexed_at_utc timestamptz NOT NULL DEFAULT now(),
    source_created_at_utc timestamptz,
    source_updated_at_utc timestamptz,
    restricted_at_utc timestamptz,
    deletion_requested_at_utc timestamptz,
    deleted_at_utc timestamptz,
    cryptoshredded_at_utc timestamptz,
    expires_at_utc timestamptz,
    last_reindexed_at_utc timestamptz,
    audit_event_id text,
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    updated_at_utc timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (
        tenant_id,
        source_object_id,
        source_version_id,
        chunk_id,
        embedding_model_id,
        embedding_model_version
    ),
    FOREIGN KEY (embedding_model_id, embedding_model_version)
        REFERENCES collabio.embedding_models (embedding_model_id, embedding_model_version),
    CHECK (tenant_id <> ''),
    CHECK (source_object_id <> ''),
    CHECK (source_object_type <> ''),
    CHECK (source_version_id <> ''),
    CHECK (chunk_id <> ''),
    CHECK (retention_policy_id <> ''),
    CHECK (embedding_dimensions = vector_dims(embedding)),
    CHECK (
        (lifecycle_state <> 'restricted' OR restricted_at_utc IS NOT NULL)
        AND (lifecycle_state <> 'deleted' OR deleted_at_utc IS NOT NULL)
        AND (lifecycle_state <> 'cryptoshredded' OR cryptoshredded_at_utc IS NOT NULL)
    )
);

COMMENT ON TABLE collabio.vector_embedding_chunks IS
    'Candidate-only embedding chunks. Source text must be fetched only after authoritative ACL validation.';
COMMENT ON COLUMN collabio.vector_embedding_chunks.embedding IS
    'Classified tenant data. Never log raw embeddings or use vector search as authorization.';
COMMENT ON COLUMN collabio.vector_embedding_chunks.lifecycle_state IS
    'Soft-delete lifecycle state used by deletion, restriction, reindex, legal hold, and cryptoshred workflows.';

CREATE INDEX IF NOT EXISTS vector_embedding_chunks_tenant_lifecycle_idx
    ON collabio.vector_embedding_chunks (
        tenant_id,
        lifecycle_state,
        embedding_model_id,
        embedding_model_version
    );

CREATE INDEX IF NOT EXISTS vector_embedding_chunks_source_idx
    ON collabio.vector_embedding_chunks (tenant_id, source_object_id, source_version_id);

CREATE INDEX IF NOT EXISTS vector_embedding_chunks_retention_idx
    ON collabio.vector_embedding_chunks (
        tenant_id,
        retention_policy_id,
        legal_hold_state,
        lifecycle_state,
        expires_at_utc
    );

CREATE INDEX IF NOT EXISTS vector_embedding_chunks_acl_idx
    ON collabio.vector_embedding_chunks (tenant_id, acl_hash, acl_version);

CREATE INDEX IF NOT EXISTS vector_embedding_chunks_content_hash_idx
    ON collabio.vector_embedding_chunks (tenant_id, content_hash);

DROP TRIGGER IF EXISTS vector_embedding_chunks_touch_updated_at_utc
    ON collabio.vector_embedding_chunks;

CREATE TRIGGER vector_embedding_chunks_touch_updated_at_utc
    BEFORE UPDATE ON collabio.vector_embedding_chunks
    FOR EACH ROW
    EXECUTE FUNCTION collabio.touch_updated_at_utc();

ALTER TABLE collabio.vector_embedding_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.vector_embedding_chunks FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS vector_embedding_chunks_tenant_select ON collabio.vector_embedding_chunks;
CREATE POLICY vector_embedding_chunks_tenant_select
    ON collabio.vector_embedding_chunks
    FOR SELECT
    USING (
        tenant_id = collabio.current_tenant_id()
        AND lifecycle_state = 'active'
    );

DROP POLICY IF EXISTS vector_embedding_chunks_tenant_insert ON collabio.vector_embedding_chunks;
CREATE POLICY vector_embedding_chunks_tenant_insert
    ON collabio.vector_embedding_chunks
    FOR INSERT
    WITH CHECK (
        tenant_id = collabio.current_tenant_id()
        AND lifecycle_state IN ('active', 'reindex_pending')
    );

DROP POLICY IF EXISTS vector_embedding_chunks_tenant_update ON collabio.vector_embedding_chunks;
CREATE POLICY vector_embedding_chunks_tenant_update
    ON collabio.vector_embedding_chunks
    FOR UPDATE
    USING (tenant_id = collabio.current_tenant_id())
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS vector_embedding_chunks_no_hard_delete ON collabio.vector_embedding_chunks;
CREATE POLICY vector_embedding_chunks_no_hard_delete
    ON collabio.vector_embedding_chunks
    FOR DELETE
    USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA collabio TO collabio_app';
        EXECUTE 'GRANT SELECT, REFERENCES ON TABLE collabio.embedding_models TO collabio_app';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE collabio.vector_embedding_chunks TO collabio_app';
    END IF;
END
$$;

-- ANN indexes are intentionally model- and dimension-specific. Add partial HNSW/IVFFlat
-- indexes only after benchmarking a concrete embedding model and tenant distribution.
