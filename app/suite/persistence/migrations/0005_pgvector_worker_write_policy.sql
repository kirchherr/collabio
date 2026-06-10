-- 0005_pgvector_worker_write_policy.sql
-- Restrict runtime app role to candidate reads; reserve vector writes for workers.

REVOKE INSERT, UPDATE, DELETE ON TABLE collabio.vector_embedding_chunks FROM collabio_app;
GRANT SELECT, INSERT, UPDATE ON TABLE collabio.vector_embedding_chunks TO collabio_worker;

DROP POLICY IF EXISTS vector_embedding_chunks_tenant_insert ON collabio.vector_embedding_chunks;
DROP POLICY IF EXISTS vector_embedding_chunks_tenant_update ON collabio.vector_embedding_chunks;

DROP POLICY IF EXISTS vector_embedding_chunks_worker_insert ON collabio.vector_embedding_chunks;
CREATE POLICY vector_embedding_chunks_worker_insert
    ON collabio.vector_embedding_chunks
    FOR INSERT
    TO collabio_worker
    WITH CHECK (
        tenant_id = collabio.current_tenant_id()
        AND lifecycle_state IN ('active', 'reindex_pending')
    );

DROP POLICY IF EXISTS vector_embedding_chunks_worker_update ON collabio.vector_embedding_chunks;
CREATE POLICY vector_embedding_chunks_worker_update
    ON collabio.vector_embedding_chunks
    FOR UPDATE
    TO collabio_worker
    USING (tenant_id = collabio.current_tenant_id())
    WITH CHECK (tenant_id = collabio.current_tenant_id());
