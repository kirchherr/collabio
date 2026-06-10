-- 0003_pgvector_role_scoped_insert_policy.sql
-- Keep app-role upserts strict without constraining lifecycle-worker updates.

DROP POLICY IF EXISTS vector_embedding_chunks_tenant_insert ON collabio.vector_embedding_chunks;
CREATE POLICY vector_embedding_chunks_tenant_insert
    ON collabio.vector_embedding_chunks
    FOR INSERT
    TO collabio_app
    WITH CHECK (
        tenant_id = collabio.current_tenant_id()
        AND lifecycle_state IN ('active', 'reindex_pending')
    );
