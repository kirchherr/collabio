-- 0004_pgvector_role_scoped_update_policy.sql
-- Prevent app-role upserts from reactivating restricted or deleted chunks.

DROP POLICY IF EXISTS vector_embedding_chunks_tenant_update ON collabio.vector_embedding_chunks;
CREATE POLICY vector_embedding_chunks_tenant_update
    ON collabio.vector_embedding_chunks
    FOR UPDATE
    TO collabio_app
    USING (
        tenant_id = collabio.current_tenant_id()
        AND lifecycle_state IN ('active', 'reindex_pending')
    )
    WITH CHECK (
        tenant_id = collabio.current_tenant_id()
        AND lifecycle_state IN ('active', 'reindex_pending')
    );
