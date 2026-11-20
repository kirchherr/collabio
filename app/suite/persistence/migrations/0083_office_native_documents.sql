-- Native structured documents. This does not admit any DOCX/WOPI engine.
CREATE SCHEMA office;

INSERT INTO collabio.module_catalog (
    module_id, display_name, module_version, module_kind, status, description,
    manifest_hash, required_migration_versions, min_core_version, installed_at_utc
) VALUES (
    'office_documents', 'Office Documents', '0.1.0', 'business_domain', 'installed',
    'Native structured documents with explicit version saves, authoritative ACL and immutable source receipts.',
    'sha256:office-native-documents-module-manifest', '["0083"]'::jsonb, NULL, now()
);

CREATE TABLE office.documents (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    object_id text NOT NULL CHECK (object_id ~ '^office-doc-[a-f0-9]{32}$'),
    title text NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
    current_version_id text NOT NULL,
    owner_principal_id text NOT NULL CHECK (owner_principal_id <> ''),
    created_by text NOT NULL CHECK (created_by <> ''),
    created_at_utc timestamptz NOT NULL,
    updated_at_utc timestamptz NOT NULL,
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref LIKE 'audit:%'),
    object_type text NOT NULL DEFAULT 'office.document' CHECK (object_type = 'office.document'),
    data_classification text NOT NULL DEFAULT 'internal' CHECK (data_classification = 'internal'),
    retention_policy_id text NOT NULL DEFAULT 'rp-standard' CHECK (retention_policy_id = 'rp-standard'),
    legal_hold_state text NOT NULL DEFAULT 'none' CHECK (legal_hold_state = 'none'),
    lifecycle_state text NOT NULL DEFAULT 'saved_version' CHECK (lifecycle_state = 'saved_version'),
    kms_key_ref text GENERATED ALWAYS AS ('kms://' || tenant_id || '/internal/v1') STORED,
    source_system text NOT NULL DEFAULT 'collabio_office_native' CHECK (source_system = 'collabio_office_native'),
    schema_version text NOT NULL DEFAULT 'collabio_document.v1' CHECK (schema_version = 'collabio_document.v1'),
    PRIMARY KEY (tenant_id, object_id),
    CHECK (owner_principal_id = created_by)
);

CREATE TABLE office.document_versions (
    tenant_id text NOT NULL,
    object_id text NOT NULL,
    version_id text NOT NULL CHECK (version_id ~ '^office-version-[a-f0-9]{32}$'),
    previous_version_id text,
    title text NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
    created_at_utc timestamptz NOT NULL,
    created_by text NOT NULL CHECK (created_by <> ''),
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[a-f0-9]{64}$'),
    source_manifest_hash text NOT NULL CHECK (source_manifest_hash ~ '^sha256:[a-f0-9]{64}$'),
    source_write_receipt_hash text NOT NULL CHECK (source_write_receipt_hash ~ '^sha256:[a-f0-9]{64}$'),
    content_byte_length integer NOT NULL CHECK (content_byte_length BETWEEN 1 AND 400000),
    acl_hash text NOT NULL CHECK (acl_hash ~ '^sha256:[a-f0-9]{64}$'),
    acl_version integer NOT NULL CHECK (acl_version >= 1),
    mutation_reference text NOT NULL CHECK (length(mutation_reference) BETWEEN 1 AND 128),
    command_hash text NOT NULL CHECK (command_hash ~ '^sha256:[a-f0-9]{64}$'),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref LIKE 'audit:%'),
    PRIMARY KEY (tenant_id, object_id, version_id),
    UNIQUE (tenant_id, created_by, mutation_reference),
    UNIQUE (tenant_id, source_write_receipt_hash),
    FOREIGN KEY (tenant_id, object_id) REFERENCES office.documents (tenant_id, object_id),
    FOREIGN KEY (tenant_id, object_id, previous_version_id)
        REFERENCES office.document_versions (tenant_id, object_id, version_id),
    FOREIGN KEY (tenant_id, object_id, version_id)
        REFERENCES collabio.source_object_metadata (tenant_id, object_id, version_id),
    FOREIGN KEY (tenant_id, source_write_receipt_hash)
        REFERENCES collabio.source_object_write_receipts (tenant_id, receipt_hash),
    CHECK (previous_version_id IS NULL OR previous_version_id <> version_id)
);

ALTER TABLE office.documents ADD CONSTRAINT office_documents_current_version_fk
FOREIGN KEY (tenant_id, object_id, current_version_id)
REFERENCES office.document_versions (tenant_id, object_id, version_id) DEFERRABLE INITIALLY DEFERRED;

CREATE FUNCTION office.bind_document_creator_acl()
RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
BEGIN
    IF NEW.tenant_id IS DISTINCT FROM current_setting('app.tenant_id', true) THEN
        RAISE EXCEPTION 'office document tenant mismatch';
    END IF;
    IF EXISTS (SELECT 1 FROM collabio.object_acl_entries
               WHERE tenant_id = NEW.tenant_id AND object_id = NEW.object_id)
       OR EXISTS (SELECT 1 FROM collabio.source_object_metadata
                  WHERE tenant_id = NEW.tenant_id AND object_id = NEW.object_id) THEN
        RAISE EXCEPTION 'office document identity already exists';
    END IF;
    INSERT INTO collabio.object_acl_entries (
        tenant_id, object_id, object_type, acl_subject_type, acl_subject_id,
        permission, acl_version, status, audit_chain_ref
    ) VALUES (
        NEW.tenant_id, NEW.object_id, 'office.document', 'user', NEW.created_by,
        'admin', 1, 'active', NEW.audit_chain_ref
    );
    RETURN NEW;
END
$$;
REVOKE ALL ON FUNCTION office.bind_document_creator_acl() FROM PUBLIC;
CREATE TRIGGER office_documents_bind_creator_acl AFTER INSERT ON office.documents
FOR EACH ROW EXECUTE FUNCTION office.bind_document_creator_acl();

CREATE FUNCTION office.enforce_version_source_binding()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
DECLARE
    document office.documents%ROWTYPE;
BEGIN
    SELECT * INTO STRICT document FROM office.documents
    WHERE tenant_id = NEW.tenant_id AND object_id = NEW.object_id FOR UPDATE;
    IF (NEW.previous_version_id IS NULL AND document.current_version_id <> NEW.version_id)
       OR (NEW.previous_version_id IS NOT NULL AND document.current_version_id <> NEW.previous_version_id) THEN
        RAISE EXCEPTION 'office document version is stale';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM collabio.source_object_metadata AS source
        JOIN collabio.source_object_write_receipts AS receipt
          ON receipt.tenant_id = source.tenant_id AND receipt.receipt_hash = source.source_object_write_receipt_hash
        WHERE source.tenant_id = NEW.tenant_id AND source.object_id = NEW.object_id
          AND source.version_id = NEW.version_id AND source.object_type = 'document'
          AND source.source_system = 'collabio_office_native'
          AND source.source_schema_version = 'collabio_document.v1'
          AND source.mime_type = 'application/vnd.collabio.document+json'
          AND source.lifecycle_state = 'saved_version' AND source.classification = 'internal'
          AND source.retention_policy_id = 'rp-standard' AND source.legal_hold_state = 'none'
          AND source.owner_principal_id = document.owner_principal_id AND source.created_by = NEW.created_by
          AND source.title = NEW.title AND source.created_at_utc = NEW.created_at_utc
          AND source.updated_at_utc = NEW.created_at_utc AND source.audit_chain_ref = NEW.audit_chain_ref
          AND source.manifest_hash = NEW.source_manifest_hash AND source.content_hash = NEW.content_hash
          AND source.content_byte_length = NEW.content_byte_length
          AND source.acl_hash = NEW.acl_hash AND source.acl_version = NEW.acl_version
          AND source.parent_object_id IS NULL AND source.thread_id IS NULL AND source.parser_profile_id IS NULL
          AND receipt.receipt_hash = NEW.source_write_receipt_hash
          AND receipt.object_id = NEW.object_id AND receipt.version_id = NEW.version_id
          AND receipt.manifest_hash = NEW.source_manifest_hash AND receipt.content_hash = NEW.content_hash
    ) THEN
        RAISE EXCEPTION 'office document source binding is invalid';
    END IF;
    RETURN NEW;
END
$$;
REVOKE ALL ON FUNCTION office.enforce_version_source_binding() FROM PUBLIC;
CREATE TRIGGER office_versions_bind_source BEFORE INSERT ON office.document_versions
FOR EACH ROW EXECUTE FUNCTION office.enforce_version_source_binding();

CREATE FUNCTION office.guard_document_head()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    IF (to_jsonb(NEW) - ARRAY['title', 'current_version_id', 'updated_at_utc', 'kms_key_ref'])
       IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['title', 'current_version_id', 'updated_at_utc', 'kms_key_ref']) THEN
        RAISE EXCEPTION 'office document identity is immutable';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM office.document_versions
        WHERE tenant_id = NEW.tenant_id AND object_id = NEW.object_id AND version_id = NEW.current_version_id
          AND title = NEW.title AND created_at_utc = NEW.updated_at_utc
          AND (version_id = OLD.current_version_id OR previous_version_id = OLD.current_version_id)
    ) THEN
        RAISE EXCEPTION 'office document head must reference a saved successor';
    END IF;
    RETURN NEW;
END
$$;
REVOKE ALL ON FUNCTION office.guard_document_head() FROM PUBLIC;
CREATE TRIGGER office_documents_guard_head BEFORE UPDATE ON office.documents
FOR EACH ROW EXECUTE FUNCTION office.guard_document_head();

ALTER TABLE office.documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE office.documents FORCE ROW LEVEL SECURITY;
ALTER TABLE office.document_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE office.document_versions FORCE ROW LEVEL SECURITY;

CREATE POLICY office_documents_tenant_select ON office.documents FOR SELECT
USING (tenant_id = collabio.current_tenant_id());
CREATE POLICY office_documents_tenant_insert ON office.documents FOR INSERT
WITH CHECK (tenant_id = collabio.current_tenant_id());
CREATE POLICY office_documents_tenant_update ON office.documents FOR UPDATE
USING (tenant_id = collabio.current_tenant_id()) WITH CHECK (tenant_id = collabio.current_tenant_id());
CREATE POLICY office_documents_no_delete ON office.documents FOR DELETE USING (false);
CREATE POLICY office_versions_tenant_select ON office.document_versions FOR SELECT
USING (tenant_id = collabio.current_tenant_id());
CREATE POLICY office_versions_tenant_insert ON office.document_versions FOR INSERT
WITH CHECK (tenant_id = collabio.current_tenant_id());
CREATE POLICY office_versions_no_update ON office.document_versions FOR UPDATE USING (false);
CREATE POLICY office_versions_no_delete ON office.document_versions FOR DELETE USING (false);

CREATE INDEX office_documents_recent_idx ON office.documents (tenant_id, updated_at_utc DESC, object_id);
CREATE INDEX office_versions_history_idx ON office.document_versions (tenant_id, object_id, created_at_utc DESC);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        GRANT USAGE ON SCHEMA office TO collabio_app;
        GRANT SELECT, INSERT ON office.documents, office.document_versions TO collabio_app;
        GRANT UPDATE (title, current_version_id, updated_at_utc) ON office.documents TO collabio_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        GRANT USAGE ON SCHEMA office TO collabio_worker;
        GRANT SELECT ON office.documents, office.document_versions TO collabio_worker;
    END IF;
END
$$;
