-- 0023_knowledge_base_write_approval_evidence.sql
-- Append-only Knowledge Base write-approval evidence ledger.

CREATE TABLE IF NOT EXISTS knowledge_base.write_approval_evidence (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    approval_reference text NOT NULL CHECK (approval_reference ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    operation text NOT NULL CHECK (operation IN ('create', 'edit')),
    approval_state text NOT NULL DEFAULT 'dry_run' CHECK (
        approval_state IN ('dry_run', 'approved_for_write', 'rejected', 'expired')
    ),
    article_object_id text NOT NULL CHECK (article_object_id <> ''),
    expected_current_version_object_id text,
    proposed_version_object_id text NOT NULL CHECK (proposed_version_object_id <> ''),
    proposed_source_object_id text NOT NULL CHECK (proposed_source_object_id <> ''),
    proposed_source_version_id text NOT NULL CHECK (proposed_source_version_id <> ''),
    proposed_source_object_type text NOT NULL DEFAULT 'wiki' CHECK (
        proposed_source_object_type IN ('document', 'mail', 'attachment', 'comment', 'wiki', 'procedure_doc')
    ),
    proposed_source_manifest_hash text NOT NULL CHECK (proposed_source_manifest_hash ~ '^sha256:[a-f0-9]{64}$'),
    proposed_content_hash text NOT NULL CHECK (proposed_content_hash ~ '^sha256:[a-f0-9]{64}$'),
    proposed_acl_version integer NOT NULL CHECK (proposed_acl_version >= 1),
    command_hash text NOT NULL CHECK (command_hash ~ '^sha256:[a-f0-9]{64}$'),
    proposed_source_version_evidence_hash text NOT NULL CHECK (
        proposed_source_version_evidence_hash ~ '^sha256:[a-f0-9]{64}$'
    ),
    current_restore_evidence_hash text NOT NULL CHECK (current_restore_evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    source_object_write_guard_ref text NOT NULL CHECK (
        source_object_write_guard_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'
    ),
    requested_by text NOT NULL CHECK (requested_by <> ''),
    persistence_allowed boolean NOT NULL DEFAULT false,
    rag_indexing_allowed boolean NOT NULL DEFAULT false,
    source_authority_verified boolean NOT NULL DEFAULT false,
    audit_event_id text NOT NULL CHECK (audit_event_id <> ''),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    evidence_hash text NOT NULL CHECK (evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    captured_at_utc timestamptz NOT NULL DEFAULT now(),
    schema_version text NOT NULL DEFAULT 'knowledge_base_write_approval_evidence.v1',
    PRIMARY KEY (tenant_id, evidence_hash),
    CHECK (proposed_version_object_id = proposed_source_object_id),
    CHECK (operation <> 'edit' OR expected_current_version_object_id IS NOT NULL),
    CHECK (operation <> 'create' OR expected_current_version_object_id IS NULL),
    CHECK (approval_state = 'approved_for_write' OR NOT persistence_allowed),
    CHECK (approval_state = 'approved_for_write' OR NOT rag_indexing_allowed),
    CHECK (approval_state = 'approved_for_write' OR NOT source_authority_verified)
);

COMMENT ON TABLE knowledge_base.write_approval_evidence IS
    'Tenant-scoped append-only evidence ledger for Knowledge Base create/edit approvals before article metadata, source objects, search indexes, embeddings, or RAG state may change.';

CREATE INDEX IF NOT EXISTS kb_write_approval_evidence_article_idx
    ON knowledge_base.write_approval_evidence (tenant_id, article_object_id, captured_at_utc);

CREATE INDEX IF NOT EXISTS kb_write_approval_evidence_command_idx
    ON knowledge_base.write_approval_evidence (tenant_id, command_hash, approval_state);

CREATE INDEX IF NOT EXISTS kb_write_approval_evidence_proposed_source_idx
    ON knowledge_base.write_approval_evidence (
        tenant_id,
        proposed_source_object_id,
        proposed_source_version_id,
        proposed_source_version_evidence_hash
    );

ALTER TABLE knowledge_base.write_approval_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_base.write_approval_evidence FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS kb_write_approval_evidence_tenant_select ON knowledge_base.write_approval_evidence;
CREATE POLICY kb_write_approval_evidence_tenant_select
    ON knowledge_base.write_approval_evidence
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS kb_write_approval_evidence_tenant_insert ON knowledge_base.write_approval_evidence;
CREATE POLICY kb_write_approval_evidence_tenant_insert
    ON knowledge_base.write_approval_evidence
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS kb_write_approval_evidence_no_update ON knowledge_base.write_approval_evidence;
CREATE POLICY kb_write_approval_evidence_no_update
    ON knowledge_base.write_approval_evidence
    FOR UPDATE
    USING (false);

DROP POLICY IF EXISTS kb_write_approval_evidence_no_hard_delete ON knowledge_base.write_approval_evidence;
CREATE POLICY kb_write_approval_evidence_no_hard_delete
    ON knowledge_base.write_approval_evidence
    FOR DELETE
    USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE knowledge_base.write_approval_evidence TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT SELECT ON TABLE knowledge_base.write_approval_evidence TO collabio_worker';
    END IF;
END
$$;
