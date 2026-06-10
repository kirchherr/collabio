-- 0002_pgvector_lifecycle_worker_role.sql
-- Dedicated runtime role and RLS policy for vector lifecycle transitions.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        CREATE ROLE collabio_worker LOGIN PASSWORD 'collabio_worker';
    END IF;
END
$$;

GRANT USAGE ON SCHEMA collabio TO collabio_worker;
GRANT SELECT, REFERENCES ON TABLE collabio.embedding_models TO collabio_worker;
GRANT SELECT, UPDATE ON TABLE collabio.vector_embedding_chunks TO collabio_worker;

DROP POLICY IF EXISTS vector_embedding_chunks_worker_select ON collabio.vector_embedding_chunks;
CREATE POLICY vector_embedding_chunks_worker_select
    ON collabio.vector_embedding_chunks
    FOR SELECT
    TO collabio_worker
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS vector_embedding_chunks_worker_update ON collabio.vector_embedding_chunks;
CREATE POLICY vector_embedding_chunks_worker_update
    ON collabio.vector_embedding_chunks
    FOR UPDATE
    TO collabio_worker
    USING (tenant_id = collabio.current_tenant_id())
    WITH CHECK (tenant_id = collabio.current_tenant_id());
