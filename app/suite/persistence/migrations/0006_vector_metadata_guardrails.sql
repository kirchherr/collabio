-- 0006_vector_metadata_guardrails.sql
-- Tighten vector metadata schema guardrails for source object types and ACL versions.

ALTER TABLE collabio.vector_embedding_chunks
    DROP CONSTRAINT IF EXISTS vector_embedding_chunks_source_object_type_check;

ALTER TABLE collabio.vector_embedding_chunks
    ADD CONSTRAINT vector_embedding_chunks_source_object_type_check
    CHECK (
        source_object_type IN (
            'document',
            'mail',
            'attachment',
            'comment',
            'wiki',
            'procedure_doc'
        )
    );

ALTER TABLE collabio.vector_embedding_chunks
    DROP CONSTRAINT IF EXISTS vector_embedding_chunks_acl_metadata_check;

ALTER TABLE collabio.vector_embedding_chunks
    ADD CONSTRAINT vector_embedding_chunks_acl_metadata_check
    CHECK (
        acl_hash ~ '^[a-z][a-z0-9_+.-]*:.+'
        AND acl_version >= 1
    );

COMMENT ON COLUMN collabio.vector_embedding_chunks.acl_hash IS
    'Hash of the authoritative ACL snapshot used when the chunk was indexed.';

COMMENT ON COLUMN collabio.vector_embedding_chunks.acl_version IS
    'Monotonic ACL version copied from the authoritative source object metadata.';
