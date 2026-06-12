-- 0021_knowledge_base_articles.sql
-- Initial knowledge base article metadata/read slice with source-version references only.

CREATE SCHEMA IF NOT EXISTS knowledge_base;

CREATE TABLE IF NOT EXISTS knowledge_base.articles (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    object_id text NOT NULL CHECK (object_id <> ''),
    object_type text NOT NULL DEFAULT 'kb.article' CHECK (object_type = 'kb.article'),
    owner_principal_id text NOT NULL CHECK (owner_principal_id <> ''),
    created_by text NOT NULL CHECK (created_by <> ''),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    updated_at_utc timestamptz NOT NULL DEFAULT now(),
    data_classification text NOT NULL DEFAULT 'internal' CHECK (data_classification = 'internal'),
    retention_policy_id text NOT NULL DEFAULT 'rp-standard' CHECK (retention_policy_id = 'rp-standard'),
    legal_hold_state text NOT NULL DEFAULT 'none' CHECK (legal_hold_state IN ('none', 'active')),
    lifecycle_state text NOT NULL DEFAULT 'published' CHECK (
        lifecycle_state IN ('working', 'published', 'restricted', 'disposition_pending')
    ),
    kms_key_ref text NOT NULL CHECK (kms_key_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    source_system text NOT NULL CHECK (source_system ~ '^[a-z][a-z0-9_+.-]*$'),
    schema_version text NOT NULL DEFAULT 'kb_article.v1' CHECK (schema_version = 'kb_article.v1'),
    article_key text NOT NULL CHECK (article_key <> ''),
    title text NOT NULL CHECK (title <> ''),
    current_version_object_id text NOT NULL CHECK (current_version_object_id <> ''),
    current_version_label text NOT NULL CHECK (current_version_label <> ''),
    published_at_utc timestamptz,
    status text NOT NULL DEFAULT 'published' CHECK (status IN ('draft', 'published', 'restricted', 'archived')),
    PRIMARY KEY (tenant_id, object_id),
    UNIQUE (tenant_id, article_key),
    CHECK (status <> 'published' OR published_at_utc IS NOT NULL),
    CHECK (status <> 'restricted' OR lifecycle_state = 'restricted')
);

CREATE TABLE IF NOT EXISTS knowledge_base.article_versions (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    object_id text NOT NULL CHECK (object_id <> ''),
    object_type text NOT NULL DEFAULT 'kb.article_version' CHECK (object_type = 'kb.article_version'),
    owner_principal_id text NOT NULL CHECK (owner_principal_id <> ''),
    created_by text NOT NULL CHECK (created_by <> ''),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    updated_at_utc timestamptz NOT NULL DEFAULT now(),
    data_classification text NOT NULL DEFAULT 'internal' CHECK (data_classification = 'internal'),
    retention_policy_id text NOT NULL DEFAULT 'rp-standard' CHECK (retention_policy_id = 'rp-standard'),
    legal_hold_state text NOT NULL DEFAULT 'none' CHECK (legal_hold_state IN ('none', 'active')),
    lifecycle_state text NOT NULL DEFAULT 'published' CHECK (
        lifecycle_state IN ('working', 'published', 'restricted', 'disposition_pending')
    ),
    kms_key_ref text NOT NULL CHECK (kms_key_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    source_system text NOT NULL CHECK (source_system ~ '^[a-z][a-z0-9_+.-]*$'),
    schema_version text NOT NULL DEFAULT 'kb_article_version.v1' CHECK (schema_version = 'kb_article_version.v1'),
    article_object_id text NOT NULL CHECK (article_object_id <> ''),
    version_label text NOT NULL CHECK (version_label <> ''),
    version_state text NOT NULL DEFAULT 'published' CHECK (
        version_state IN ('draft', 'published', 'restricted', 'superseded')
    ),
    source_object_version_ref text NOT NULL CHECK (source_object_version_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[a-f0-9]{64}$'),
    published_at_utc timestamptz,
    PRIMARY KEY (tenant_id, object_id),
    UNIQUE (tenant_id, article_object_id, version_label),
    FOREIGN KEY (tenant_id, article_object_id)
        REFERENCES knowledge_base.articles (tenant_id, object_id),
    CHECK (version_state <> 'published' OR published_at_utc IS NOT NULL),
    CHECK (version_state <> 'restricted' OR lifecycle_state = 'restricted')
);

COMMENT ON SCHEMA knowledge_base IS
    'Knowledge base module schema. Article bodies are not stored by the initial metadata/read slice.';
COMMENT ON TABLE knowledge_base.articles IS
    'Tenant-scoped knowledge base article metadata for knowledge_base.articles.read.';
COMMENT ON TABLE knowledge_base.article_versions IS
    'Tenant-scoped knowledge base source-version metadata. Body text remains behind source-object retrieval.';
COMMENT ON COLUMN knowledge_base.articles.current_version_object_id IS
    'Current kb.article_version object ID used by later RAG citations after authoritative ACL validation.';
COMMENT ON COLUMN knowledge_base.article_versions.source_object_version_ref IS
    'Namespaced source version reference; no article body, raw source text, prompt, or AI output is stored here.';

CREATE UNIQUE INDEX IF NOT EXISTS kb_articles_article_key_unique_idx
    ON knowledge_base.articles (tenant_id, article_key);

CREATE INDEX IF NOT EXISTS kb_articles_tenant_status_idx
    ON knowledge_base.articles (tenant_id, status, lifecycle_state);

CREATE INDEX IF NOT EXISTS kb_articles_retention_legal_hold_idx
    ON knowledge_base.articles (tenant_id, retention_policy_id, legal_hold_state, lifecycle_state);

CREATE INDEX IF NOT EXISTS kb_article_versions_article_idx
    ON knowledge_base.article_versions (tenant_id, article_object_id, version_state);

CREATE INDEX IF NOT EXISTS kb_article_versions_retention_legal_hold_idx
    ON knowledge_base.article_versions (tenant_id, retention_policy_id, legal_hold_state, lifecycle_state);

CREATE OR REPLACE FUNCTION knowledge_base.touch_updated_at_utc()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at_utc = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS kb_articles_touch_updated_at_utc ON knowledge_base.articles;
CREATE TRIGGER kb_articles_touch_updated_at_utc
    BEFORE UPDATE ON knowledge_base.articles
    FOR EACH ROW
    EXECUTE FUNCTION knowledge_base.touch_updated_at_utc();

DROP TRIGGER IF EXISTS kb_article_versions_touch_updated_at_utc ON knowledge_base.article_versions;
CREATE TRIGGER kb_article_versions_touch_updated_at_utc
    BEFORE UPDATE ON knowledge_base.article_versions
    FOR EACH ROW
    EXECUTE FUNCTION knowledge_base.touch_updated_at_utc();

ALTER TABLE knowledge_base.articles ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_base.articles FORCE ROW LEVEL SECURITY;
ALTER TABLE knowledge_base.article_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_base.article_versions FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS kb_articles_tenant_select ON knowledge_base.articles;
CREATE POLICY kb_articles_tenant_select
    ON knowledge_base.articles
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS kb_articles_tenant_insert ON knowledge_base.articles;
CREATE POLICY kb_articles_tenant_insert
    ON knowledge_base.articles
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS kb_articles_tenant_update ON knowledge_base.articles;
CREATE POLICY kb_articles_tenant_update
    ON knowledge_base.articles
    FOR UPDATE
    USING (tenant_id = collabio.current_tenant_id())
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS kb_articles_no_hard_delete ON knowledge_base.articles;
CREATE POLICY kb_articles_no_hard_delete
    ON knowledge_base.articles
    FOR DELETE
    USING (false);

DROP POLICY IF EXISTS kb_article_versions_tenant_select ON knowledge_base.article_versions;
CREATE POLICY kb_article_versions_tenant_select
    ON knowledge_base.article_versions
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS kb_article_versions_tenant_insert ON knowledge_base.article_versions;
CREATE POLICY kb_article_versions_tenant_insert
    ON knowledge_base.article_versions
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS kb_article_versions_tenant_update ON knowledge_base.article_versions;
CREATE POLICY kb_article_versions_tenant_update
    ON knowledge_base.article_versions
    FOR UPDATE
    USING (tenant_id = collabio.current_tenant_id())
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS kb_article_versions_no_hard_delete ON knowledge_base.article_versions;
CREATE POLICY kb_article_versions_no_hard_delete
    ON knowledge_base.article_versions
    FOR DELETE
    USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA knowledge_base TO collabio_app';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE ON TABLE knowledge_base.articles TO collabio_app';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE ON TABLE knowledge_base.article_versions TO collabio_app';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA knowledge_base TO collabio_worker';
        EXECUTE 'GRANT SELECT ON TABLE knowledge_base.articles TO collabio_worker';
        EXECUTE 'GRANT SELECT ON TABLE knowledge_base.article_versions TO collabio_worker';
    END IF;
END
$$;
