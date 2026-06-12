-- 0022_knowledge_base_source_restore_evidence.sql
-- Evidence tables for Knowledge Base source-version integrity and restore readiness.

CREATE TABLE IF NOT EXISTS knowledge_base.source_version_evidence (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    article_object_id text NOT NULL CHECK (article_object_id <> ''),
    article_version_object_id text NOT NULL CHECK (article_version_object_id <> ''),
    source_object_id text NOT NULL CHECK (source_object_id <> ''),
    source_version_id text NOT NULL CHECK (source_version_id <> ''),
    source_object_type text NOT NULL DEFAULT 'wiki' CHECK (
        source_object_type IN ('document', 'mail', 'attachment', 'comment', 'wiki', 'procedure_doc')
    ),
    source_manifest_hash text NOT NULL CHECK (source_manifest_hash ~ '^sha256:[a-f0-9]{64}$'),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[a-f0-9]{64}$'),
    acl_version integer NOT NULL CHECK (acl_version >= 1),
    data_classification text NOT NULL DEFAULT 'internal' CHECK (data_classification = 'internal'),
    retention_policy_id text NOT NULL DEFAULT 'rp-standard' CHECK (retention_policy_id = 'rp-standard'),
    legal_hold_state text NOT NULL DEFAULT 'none' CHECK (legal_hold_state IN ('none', 'active')),
    evidence_hash text NOT NULL CHECK (evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    captured_at_utc timestamptz NOT NULL DEFAULT now(),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    schema_version text NOT NULL DEFAULT 'knowledge_base_source_version_evidence.v1',
    PRIMARY KEY (tenant_id, article_version_object_id, evidence_hash),
    FOREIGN KEY (tenant_id, article_object_id)
        REFERENCES knowledge_base.articles (tenant_id, object_id),
    FOREIGN KEY (tenant_id, article_version_object_id)
        REFERENCES knowledge_base.article_versions (tenant_id, object_id),
    CHECK (article_version_object_id = source_object_id)
);

CREATE TABLE IF NOT EXISTS knowledge_base.restore_evidence (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    module_id text NOT NULL DEFAULT 'knowledge_base' CHECK (module_id = 'knowledge_base'),
    continuity_domain text NOT NULL DEFAULT 'knowledge_base_content' CHECK (
        continuity_domain = 'knowledge_base_content'
    ),
    article_count integer NOT NULL CHECK (article_count >= 0),
    article_version_count integer NOT NULL CHECK (article_version_count >= 0),
    source_version_evidence_count integer NOT NULL CHECK (source_version_evidence_count >= 0),
    source_version_evidence_hashes text[] NOT NULL CHECK (array_length(source_version_evidence_hashes, 1) >= 0),
    restore_drill_report_hash text NOT NULL CHECK (restore_drill_report_hash ~ '^sha256:[a-f0-9]{64}$'),
    row_count_hash text NOT NULL CHECK (row_count_hash ~ '^sha256:[a-f0-9]{64}$'),
    checksum_manifest_hash text NOT NULL CHECK (checksum_manifest_hash ~ '^sha256:[a-f0-9]{64}$'),
    tenant_isolation_verified boolean NOT NULL CHECK (tenant_isolation_verified),
    disabled_state_restore_verified boolean NOT NULL CHECK (disabled_state_restore_verified),
    legal_hold_restore_verified boolean NOT NULL CHECK (legal_hold_restore_verified),
    evidence_hash text NOT NULL CHECK (evidence_hash ~ '^sha256:[a-f0-9]{64}$'),
    captured_at_utc timestamptz NOT NULL DEFAULT now(),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    schema_version text NOT NULL DEFAULT 'knowledge_base_restore_evidence.v1',
    PRIMARY KEY (tenant_id, evidence_hash),
    CHECK (article_version_count = source_version_evidence_count)
);

COMMENT ON TABLE knowledge_base.source_version_evidence IS
    'Tenant-scoped evidence that kb.article_version objects resolve to source object versions with manifest, content-hash, ACL-version, retention, and Legal Hold metadata.';
COMMENT ON TABLE knowledge_base.restore_evidence IS
    'Tenant-scoped restore evidence for the knowledge_base_content continuity domain before Knowledge Base write, edit, search, or RAG expansion.';

CREATE INDEX IF NOT EXISTS kb_source_version_evidence_article_idx
    ON knowledge_base.source_version_evidence (tenant_id, article_object_id, article_version_object_id);

CREATE INDEX IF NOT EXISTS kb_source_version_evidence_integrity_idx
    ON knowledge_base.source_version_evidence (tenant_id, source_manifest_hash, content_hash, acl_version);

CREATE INDEX IF NOT EXISTS kb_restore_evidence_domain_idx
    ON knowledge_base.restore_evidence (tenant_id, continuity_domain, captured_at_utc);

ALTER TABLE knowledge_base.source_version_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_base.source_version_evidence FORCE ROW LEVEL SECURITY;
ALTER TABLE knowledge_base.restore_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_base.restore_evidence FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS kb_source_version_evidence_tenant_select ON knowledge_base.source_version_evidence;
CREATE POLICY kb_source_version_evidence_tenant_select
    ON knowledge_base.source_version_evidence
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS kb_source_version_evidence_tenant_insert ON knowledge_base.source_version_evidence;
CREATE POLICY kb_source_version_evidence_tenant_insert
    ON knowledge_base.source_version_evidence
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS kb_source_version_evidence_no_update ON knowledge_base.source_version_evidence;
CREATE POLICY kb_source_version_evidence_no_update
    ON knowledge_base.source_version_evidence
    FOR UPDATE
    USING (false);

DROP POLICY IF EXISTS kb_source_version_evidence_no_hard_delete ON knowledge_base.source_version_evidence;
CREATE POLICY kb_source_version_evidence_no_hard_delete
    ON knowledge_base.source_version_evidence
    FOR DELETE
    USING (false);

DROP POLICY IF EXISTS kb_restore_evidence_tenant_select ON knowledge_base.restore_evidence;
CREATE POLICY kb_restore_evidence_tenant_select
    ON knowledge_base.restore_evidence
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS kb_restore_evidence_tenant_insert ON knowledge_base.restore_evidence;
CREATE POLICY kb_restore_evidence_tenant_insert
    ON knowledge_base.restore_evidence
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS kb_restore_evidence_no_update ON knowledge_base.restore_evidence;
CREATE POLICY kb_restore_evidence_no_update
    ON knowledge_base.restore_evidence
    FOR UPDATE
    USING (false);

DROP POLICY IF EXISTS kb_restore_evidence_no_hard_delete ON knowledge_base.restore_evidence;
CREATE POLICY kb_restore_evidence_no_hard_delete
    ON knowledge_base.restore_evidence
    FOR DELETE
    USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT SELECT, INSERT ON TABLE knowledge_base.source_version_evidence TO collabio_app';
        EXECUTE 'GRANT SELECT, INSERT ON TABLE knowledge_base.restore_evidence TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT SELECT ON TABLE knowledge_base.source_version_evidence TO collabio_worker';
        EXECUTE 'GRANT SELECT ON TABLE knowledge_base.restore_evidence TO collabio_worker';
    END IF;
END
$$;
