-- Bind article/version authorization to the same metadata transaction as KB writes.
-- Runtime roles receive no general ACL mutation privilege.
CREATE FUNCTION knowledge_base.bind_article_acl()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    IF NEW.tenant_id IS DISTINCT FROM current_setting('app.tenant_id', true) THEN
        RAISE EXCEPTION 'knowledge base ACL tenant mismatch';
    END IF;
    IF EXISTS (
        SELECT 1 FROM collabio.object_acl_entries
        WHERE tenant_id = NEW.tenant_id AND object_id = NEW.object_id
    ) OR EXISTS (
        SELECT 1 FROM collabio.source_object_metadata
        WHERE tenant_id = NEW.tenant_id AND object_id = NEW.object_id
    ) OR EXISTS (
        SELECT 1 FROM knowledge_base.article_versions
        WHERE tenant_id = NEW.tenant_id AND object_id = NEW.object_id
    ) THEN
        RAISE EXCEPTION 'knowledge base article identity already exists';
    END IF;
    INSERT INTO collabio.object_acl_entries (
        tenant_id, object_id, object_type, acl_subject_type, acl_subject_id,
        permission, acl_version, status, audit_chain_ref
    ) VALUES (
        NEW.tenant_id, NEW.object_id, 'kb.article', 'user', NEW.created_by,
        'admin', 1, 'active', NEW.audit_chain_ref
    );
    RETURN NEW;
END
$$;

CREATE FUNCTION knowledge_base.bind_version_acls()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    IF NEW.tenant_id IS DISTINCT FROM current_setting('app.tenant_id', true) THEN
        RAISE EXCEPTION 'knowledge base ACL tenant mismatch';
    END IF;
    PERFORM 1
    FROM knowledge_base.articles
    WHERE tenant_id = NEW.tenant_id AND object_id = NEW.article_object_id
    FOR UPDATE;
    IF NEW.object_id = NEW.article_object_id OR EXISTS (
        SELECT 1 FROM collabio.object_acl_entries
        WHERE tenant_id = NEW.tenant_id AND object_id = NEW.object_id
    ) OR EXISTS (
        SELECT 1 FROM knowledge_base.articles
        WHERE tenant_id = NEW.tenant_id AND object_id = NEW.object_id
    ) OR EXISTS (
        SELECT 1 FROM collabio.source_object_metadata
        WHERE tenant_id = NEW.tenant_id AND object_id = NEW.object_id
          AND (
              object_type <> 'wiki'
              OR xmin::text::numeric <> mod(pg_current_xact_id()::text::numeric, 4294967296)
          )
    ) THEN
        RAISE EXCEPTION 'knowledge base version identity already exists';
    END IF;

    INSERT INTO collabio.object_acl_entries (
        tenant_id, object_id, object_type, acl_subject_type, acl_subject_id,
        permission, acl_version, status, audit_chain_ref
    )
    SELECT NEW.tenant_id, NEW.object_id, 'kb.article_version', acl_subject_type, acl_subject_id,
           permission, acl_version, 'active', NEW.audit_chain_ref
    FROM collabio.object_acl_entries
    WHERE tenant_id = NEW.tenant_id AND object_id = NEW.article_object_id
      AND object_type = 'kb.article' AND status = 'active';
    IF NOT FOUND THEN
        RAISE EXCEPTION 'knowledge base article has no active ACL';
    END IF;
    RETURN NEW;
END
$$;

REVOKE ALL ON FUNCTION knowledge_base.bind_version_acls() FROM PUBLIC;
REVOKE ALL ON FUNCTION knowledge_base.bind_article_acl() FROM PUBLIC;
CREATE TRIGGER knowledge_base_articles_bind_acl
AFTER INSERT ON knowledge_base.articles
FOR EACH ROW EXECUTE FUNCTION knowledge_base.bind_article_acl();
CREATE TRIGGER knowledge_base_article_versions_bind_acls
AFTER INSERT ON knowledge_base.article_versions
FOR EACH ROW EXECUTE FUNCTION knowledge_base.bind_version_acls();

UPDATE collabio.module_catalog
SET module_version = '0.2.0',
    required_migration_versions = '["0007", "0008", "0009", "0010", "0011", "0021", "0022", "0023", "0024", "0025", "0026", "0027", "0028", "0029", "0082"]'::jsonb
WHERE module_id = 'knowledge_base';
