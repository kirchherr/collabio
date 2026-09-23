-- Saved text suggestions and one immutable terminal decision; no tenant activation.
UPDATE collabio.module_catalog
SET required_migration_versions = '["0083", "0084", "0085"]'::jsonb
WHERE module_id = 'office_documents';

CREATE TABLE office.text_suggestions (
    tenant_id text NOT NULL,
    object_id text NOT NULL,
    suggestion_id text NOT NULL CHECK (suggestion_id ~ '^office-suggestion-[a-f0-9]{32}$'),
    source_version_id text NOT NULL CHECK (source_version_id ~ '^office-suggestion-event-[a-f0-9]{32}$'),
    created_by text NOT NULL CHECK (created_by <> ''),
    created_at_utc timestamptz NOT NULL,
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[a-f0-9]{64}$'),
    source_manifest_hash text NOT NULL CHECK (source_manifest_hash ~ '^sha256:[a-f0-9]{64}$'),
    source_write_receipt_hash text NOT NULL CHECK (source_write_receipt_hash ~ '^sha256:[a-f0-9]{64}$'),
    content_byte_length integer NOT NULL CHECK (content_byte_length BETWEEN 1 AND 80000),
    acl_hash text NOT NULL CHECK (acl_hash ~ '^sha256:[a-f0-9]{64}$'),
    acl_version integer NOT NULL CHECK (acl_version >= 1),
    mutation_reference text NOT NULL CHECK (length(mutation_reference) BETWEEN 1 AND 128),
    command_hash text NOT NULL CHECK (command_hash ~ '^sha256:[a-f0-9]{64}$'),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref LIKE 'audit:%'),
    anchor_version_id text NOT NULL,
    anchor_content_hash text NOT NULL CHECK (anchor_content_hash ~ '^sha256:[a-f0-9]{64}$'),
    anchor_from integer NOT NULL CHECK (anchor_from >= 1),
    anchor_to integer NOT NULL CHECK (anchor_to > anchor_from AND anchor_to <= 220000),
    PRIMARY KEY (tenant_id, suggestion_id),
    UNIQUE (tenant_id, object_id, suggestion_id),
    UNIQUE (tenant_id, created_by, mutation_reference),
    UNIQUE (tenant_id, source_write_receipt_hash),
    FOREIGN KEY (tenant_id, object_id, anchor_version_id)
        REFERENCES office.document_versions (tenant_id, object_id, version_id),
    FOREIGN KEY (tenant_id, suggestion_id, source_version_id)
        REFERENCES collabio.source_object_metadata (tenant_id, object_id, version_id),
    FOREIGN KEY (tenant_id, source_write_receipt_hash)
        REFERENCES collabio.source_object_write_receipts (tenant_id, receipt_hash)
);

CREATE TABLE office.text_suggestion_decisions (
    tenant_id text NOT NULL,
    object_id text NOT NULL,
    suggestion_id text NOT NULL,
    source_version_id text NOT NULL,
    created_by text NOT NULL CHECK (created_by <> ''),
    created_at_utc timestamptz NOT NULL,
    content_hash text NOT NULL CHECK (content_hash ~ '^sha256:[a-f0-9]{64}$'),
    source_manifest_hash text NOT NULL CHECK (source_manifest_hash ~ '^sha256:[a-f0-9]{64}$'),
    source_write_receipt_hash text NOT NULL CHECK (source_write_receipt_hash ~ '^sha256:[a-f0-9]{64}$'),
    content_byte_length integer NOT NULL CHECK (content_byte_length BETWEEN 1 AND 80000),
    acl_hash text NOT NULL CHECK (acl_hash ~ '^sha256:[a-f0-9]{64}$'),
    acl_version integer NOT NULL CHECK (acl_version >= 1),
    mutation_reference text NOT NULL CHECK (length(mutation_reference) BETWEEN 1 AND 128),
    command_hash text NOT NULL CHECK (command_hash ~ '^sha256:[a-f0-9]{64}$'),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref LIKE 'audit:%'),
    decision_id text NOT NULL CHECK (decision_id ~ '^office-suggestion-decision-[a-f0-9]{32}$'),
    operation text NOT NULL CHECK (operation IN ('accept', 'reject')),
    result_version_id text,
    result_content_hash text CHECK (result_content_hash ~ '^sha256:[a-f0-9]{64}$'),
    PRIMARY KEY (tenant_id, suggestion_id),
    UNIQUE (tenant_id, decision_id),
    UNIQUE (tenant_id, created_by, mutation_reference),
    UNIQUE (tenant_id, source_write_receipt_hash),
    UNIQUE (tenant_id, result_version_id),
    FOREIGN KEY (tenant_id, object_id, suggestion_id)
        REFERENCES office.text_suggestions (tenant_id, object_id, suggestion_id),
    FOREIGN KEY (tenant_id, object_id, result_version_id)
        REFERENCES office.document_versions (tenant_id, object_id, version_id),
    FOREIGN KEY (tenant_id, suggestion_id, source_version_id)
        REFERENCES collabio.source_object_metadata (tenant_id, object_id, version_id),
    FOREIGN KEY (tenant_id, source_write_receipt_hash)
        REFERENCES collabio.source_object_write_receipts (tenant_id, receipt_hash),
    CHECK (source_version_id = decision_id),
    CHECK ((operation = 'accept' AND result_version_id IS NOT NULL AND result_content_hash IS NOT NULL) OR
           (operation = 'reject' AND result_version_id IS NULL AND result_content_hash IS NULL))
);

CREATE FUNCTION office.enforce_text_suggestion_source()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
DECLARE
    document office.documents%ROWTYPE;
    proposal office.text_suggestions%ROWTYPE;
BEGIN
    IF NEW.tenant_id IS DISTINCT FROM current_setting('app.tenant_id', true) THEN
        RAISE EXCEPTION 'office suggestion tenant is invalid';
    END IF;
    SELECT * INTO STRICT document FROM office.documents
    WHERE tenant_id = NEW.tenant_id AND object_id = NEW.object_id;
    IF TG_TABLE_NAME = 'text_suggestions' THEN
        IF NOT EXISTS (
            SELECT 1 FROM office.document_versions WHERE tenant_id = NEW.tenant_id AND object_id = NEW.object_id
              AND version_id = NEW.anchor_version_id AND version_id = document.current_version_id
              AND content_hash = NEW.anchor_content_hash
        ) OR (SELECT count(*) FROM collabio.source_object_metadata
              WHERE tenant_id = NEW.tenant_id AND object_id = NEW.suggestion_id) <> 1
          OR EXISTS (SELECT 1 FROM collabio.object_acl_entries
                     WHERE tenant_id = NEW.tenant_id AND object_id = NEW.suggestion_id) THEN
            RAISE EXCEPTION 'office suggestion anchor or identity is invalid';
        END IF;
    ELSE
        SELECT * INTO STRICT proposal FROM office.text_suggestions
        WHERE tenant_id = NEW.tenant_id AND object_id = NEW.object_id AND suggestion_id = NEW.suggestion_id;
        IF NEW.operation = 'accept' AND NOT EXISTS (
            SELECT 1 FROM office.document_versions WHERE tenant_id = NEW.tenant_id AND object_id = NEW.object_id
              AND version_id = NEW.result_version_id AND version_id = document.current_version_id
              AND previous_version_id = proposal.anchor_version_id AND content_hash = NEW.result_content_hash
              AND created_by = NEW.created_by AND mutation_reference = 'office-suggestion-accept:' || NEW.decision_id
        ) THEN
            RAISE EXCEPTION 'office suggestion accepted version is invalid';
        END IF;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM collabio.source_object_metadata AS source
        JOIN collabio.source_object_write_receipts AS receipt
          ON receipt.tenant_id = source.tenant_id AND receipt.receipt_hash = source.source_object_write_receipt_hash
        WHERE source.tenant_id = NEW.tenant_id AND source.object_id = NEW.suggestion_id AND source.version_id = NEW.source_version_id
          AND source.object_type = 'comment' AND source.source_system = 'collabio_office_native_suggestion'
          AND source.source_schema_version = 'collabio_office_suggestion_event.v1'
          AND source.mime_type = 'application/vnd.collabio.suggestion-event+json'
          AND source.lifecycle_state = 'saved_version' AND source.classification = 'internal'
          AND source.retention_policy_id = 'rp-standard' AND source.legal_hold_state = 'none'
          AND source.kms_key_ref = 'kms://' || NEW.tenant_id || '/internal/v1'
          AND source.owner_principal_id = document.owner_principal_id AND source.created_by = NEW.created_by
          AND source.title = 'Office text suggestion' AND source.created_at_utc = NEW.created_at_utc
          AND source.updated_at_utc = NEW.created_at_utc AND source.audit_chain_ref = NEW.audit_chain_ref
          AND source.manifest_hash = NEW.source_manifest_hash AND source.content_hash = NEW.content_hash
          AND source.content_byte_length = NEW.content_byte_length
          AND source.acl_hash = NEW.acl_hash AND source.acl_version = NEW.acl_version
          AND source.parent_object_id = NEW.object_id AND source.thread_id = NEW.suggestion_id AND source.parser_profile_id IS NULL
          AND receipt.receipt_hash = NEW.source_write_receipt_hash AND receipt.object_id = NEW.suggestion_id
          AND receipt.version_id = NEW.source_version_id AND receipt.object_type = 'comment'
          AND receipt.parent_object_id = NEW.object_id AND receipt.thread_id = NEW.suggestion_id
          AND receipt.manifest_hash = NEW.source_manifest_hash AND receipt.content_hash = NEW.content_hash
    ) THEN
        RAISE EXCEPTION 'office suggestion source binding is invalid';
    END IF;
    RETURN NEW;
END
$$;
REVOKE ALL ON FUNCTION office.enforce_text_suggestion_source() FROM PUBLIC;
CREATE TRIGGER office_text_suggestions_bind_source BEFORE INSERT ON office.text_suggestions
FOR EACH ROW EXECUTE FUNCTION office.enforce_text_suggestion_source();
CREATE TRIGGER office_text_suggestion_decisions_bind_source BEFORE INSERT ON office.text_suggestion_decisions
FOR EACH ROW EXECUTE FUNCTION office.enforce_text_suggestion_source();

CREATE FUNCTION office.require_text_suggestion_decision()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    IF NEW.mutation_reference LIKE 'office-suggestion-accept:%' AND NOT EXISTS (
        SELECT 1 FROM office.text_suggestion_decisions
        WHERE tenant_id = NEW.tenant_id AND object_id = NEW.object_id AND result_version_id = NEW.version_id
          AND result_content_hash = NEW.content_hash AND created_by = NEW.created_by AND operation = 'accept'
          AND 'office-suggestion-accept:' || decision_id = NEW.mutation_reference
    ) THEN
        RAISE EXCEPTION 'office accepted version requires its suggestion decision';
    END IF;
    RETURN NEW;
END
$$;
REVOKE ALL ON FUNCTION office.require_text_suggestion_decision() FROM PUBLIC;
CREATE CONSTRAINT TRIGGER office_versions_require_suggestion_decision AFTER INSERT ON office.document_versions
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION office.require_text_suggestion_decision();

ALTER TABLE office.text_suggestions ENABLE ROW LEVEL SECURITY;
ALTER TABLE office.text_suggestions FORCE ROW LEVEL SECURITY;
ALTER TABLE office.text_suggestion_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE office.text_suggestion_decisions FORCE ROW LEVEL SECURITY;
CREATE POLICY office_text_suggestions_tenant_select ON office.text_suggestions FOR SELECT USING (tenant_id = collabio.current_tenant_id());
CREATE POLICY office_text_suggestions_tenant_insert ON office.text_suggestions FOR INSERT WITH CHECK (tenant_id = collabio.current_tenant_id());
CREATE POLICY office_text_suggestions_no_update ON office.text_suggestions FOR UPDATE USING (false);
CREATE POLICY office_text_suggestions_no_delete ON office.text_suggestions FOR DELETE USING (false);
CREATE POLICY office_text_suggestion_decisions_tenant_select ON office.text_suggestion_decisions FOR SELECT USING (tenant_id = collabio.current_tenant_id());
CREATE POLICY office_text_suggestion_decisions_tenant_insert ON office.text_suggestion_decisions FOR INSERT WITH CHECK (tenant_id = collabio.current_tenant_id());
CREATE POLICY office_text_suggestion_decisions_no_update ON office.text_suggestion_decisions FOR UPDATE USING (false);
CREATE POLICY office_text_suggestion_decisions_no_delete ON office.text_suggestion_decisions FOR DELETE USING (false);
REVOKE ALL ON office.text_suggestions, office.text_suggestion_decisions FROM PUBLIC, collabio_app, collabio_worker, collabio_audit_writer, collabio_authz_admin;
GRANT SELECT, INSERT ON office.text_suggestions, office.text_suggestion_decisions TO collabio_app;
GRANT SELECT ON office.text_suggestions, office.text_suggestion_decisions TO collabio_worker;
