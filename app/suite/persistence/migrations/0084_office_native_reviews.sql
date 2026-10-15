-- Review discussions are separate from immutable native document versions.
UPDATE collabio.module_catalog
SET required_migration_versions = '["0083", "0084"]'::jsonb,
    description = 'Native structured documents with explicit version saves, authoritative ACL and immutable source receipts, with version-bound review discussions.'
WHERE module_id = 'office_documents';

CREATE TABLE office.review_threads (
    tenant_id text NOT NULL,
    object_id text NOT NULL,
    thread_id text NOT NULL CHECK (thread_id ~ '^office-review-[a-f0-9]{32}$'),
    anchor_version_id text NOT NULL,
    anchor_content_hash text NOT NULL CHECK (anchor_content_hash ~ '^sha256:[a-f0-9]{64}$'),
    anchor_from integer,
    anchor_to integer,
    revision integer NOT NULL CHECK (revision >= 1),
    current_event_id text NOT NULL,
    status text NOT NULL CHECK (status IN ('open', 'resolved')),
    created_by text NOT NULL CHECK (created_by <> ''),
    created_at_utc timestamptz NOT NULL,
    updated_at_utc timestamptz NOT NULL,
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref LIKE 'audit:%'),
    PRIMARY KEY (tenant_id, thread_id),
    UNIQUE (tenant_id, object_id, thread_id),
    FOREIGN KEY (tenant_id, object_id, anchor_version_id)
        REFERENCES office.document_versions (tenant_id, object_id, version_id),
    CHECK ((anchor_from IS NULL AND anchor_to IS NULL) OR
           (anchor_from IS NOT NULL AND anchor_to IS NOT NULL AND anchor_from >= 1 AND anchor_to > anchor_from AND anchor_to <= 220000))
);

CREATE TABLE office.review_events (
    tenant_id text NOT NULL,
    object_id text NOT NULL,
    thread_id text NOT NULL,
    event_id text NOT NULL CHECK (event_id ~ '^office-review-event-[a-f0-9]{32}$'),
    revision integer NOT NULL CHECK (revision >= 1),
    previous_event_id text,
    operation text NOT NULL CHECK (operation IN ('create', 'reply', 'resolve', 'reopen')),
    status_after text NOT NULL CHECK (status_after IN ('open', 'resolved')),
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
    PRIMARY KEY (tenant_id, thread_id, event_id),
    UNIQUE (tenant_id, event_id),
    UNIQUE (tenant_id, thread_id, revision),
    UNIQUE (tenant_id, created_by, mutation_reference),
    UNIQUE (tenant_id, source_write_receipt_hash),
    FOREIGN KEY (tenant_id, object_id, thread_id)
        REFERENCES office.review_threads (tenant_id, object_id, thread_id),
    FOREIGN KEY (tenant_id, thread_id, previous_event_id)
        REFERENCES office.review_events (tenant_id, thread_id, event_id),
    FOREIGN KEY (tenant_id, thread_id, event_id)
        REFERENCES collabio.source_object_metadata (tenant_id, object_id, version_id),
    FOREIGN KEY (tenant_id, source_write_receipt_hash)
        REFERENCES collabio.source_object_write_receipts (tenant_id, receipt_hash),
    CHECK ((revision = 1 AND previous_event_id IS NULL AND operation = 'create') OR
           (revision > 1 AND previous_event_id IS NOT NULL AND previous_event_id <> event_id AND operation <> 'create')),
    CHECK ((operation = 'resolve' AND status_after = 'resolved') OR (operation <> 'resolve' AND status_after = 'open'))
);

ALTER TABLE office.review_threads ADD CONSTRAINT office_review_threads_current_event_fk
FOREIGN KEY (tenant_id, thread_id, current_event_id)
REFERENCES office.review_events (tenant_id, thread_id, event_id) DEFERRABLE INITIALLY DEFERRED;

CREATE FUNCTION office.guard_review_thread_insert()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    IF NEW.tenant_id IS DISTINCT FROM current_setting('app.tenant_id', true)
       OR NEW.revision <> 1 OR NEW.status <> 'open' OR NEW.created_at_utc <> NEW.updated_at_utc THEN
        RAISE EXCEPTION 'office review initial state is invalid';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM office.document_versions AS version
        JOIN office.documents AS document USING (tenant_id, object_id)
        WHERE version.tenant_id = NEW.tenant_id AND version.object_id = NEW.object_id
          AND version.version_id = NEW.anchor_version_id AND version.content_hash = NEW.anchor_content_hash
          AND document.current_version_id = NEW.anchor_version_id
    ) OR EXISTS (SELECT 1 FROM collabio.source_object_metadata
                 WHERE tenant_id = NEW.tenant_id AND object_id = NEW.thread_id)
      OR EXISTS (SELECT 1 FROM collabio.object_acl_entries
                 WHERE tenant_id = NEW.tenant_id AND object_id = NEW.thread_id) THEN
        RAISE EXCEPTION 'office review anchor or identity is invalid';
    END IF;
    RETURN NEW;
END
$$;
REVOKE ALL ON FUNCTION office.guard_review_thread_insert() FROM PUBLIC;
CREATE TRIGGER office_review_threads_guard_insert BEFORE INSERT ON office.review_threads
FOR EACH ROW EXECUTE FUNCTION office.guard_review_thread_insert();

CREATE FUNCTION office.enforce_review_event_source_binding()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
DECLARE
    thread office.review_threads%ROWTYPE;
    document office.documents%ROWTYPE;
BEGIN
    SELECT * INTO STRICT thread FROM office.review_threads
    WHERE tenant_id = NEW.tenant_id AND object_id = NEW.object_id AND thread_id = NEW.thread_id FOR UPDATE;
    SELECT * INTO STRICT document FROM office.documents
    WHERE tenant_id = NEW.tenant_id AND object_id = NEW.object_id;
    IF NEW.revision = 1 THEN
        IF thread.revision <> 1 OR thread.current_event_id <> NEW.event_id OR NEW.operation <> 'create'
           OR thread.created_by <> NEW.created_by OR thread.created_at_utc <> NEW.created_at_utc THEN
            RAISE EXCEPTION 'office review initial event is invalid';
        END IF;
    ELSE
        IF NEW.revision <> thread.revision + 1 OR NEW.previous_event_id <> thread.current_event_id
           OR (NEW.operation IN ('reply', 'resolve') AND thread.status <> 'open')
           OR (NEW.operation = 'reopen' AND thread.status <> 'resolved') THEN
            RAISE EXCEPTION 'office review event is stale';
        END IF;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM collabio.source_object_metadata AS source
        JOIN collabio.source_object_write_receipts AS receipt
          ON receipt.tenant_id = source.tenant_id AND receipt.receipt_hash = source.source_object_write_receipt_hash
        WHERE source.tenant_id = NEW.tenant_id AND source.object_id = NEW.thread_id AND source.version_id = NEW.event_id
          AND source.object_type = 'comment' AND source.source_system = 'collabio_office_native_review'
          AND source.source_schema_version = 'collabio_office_review_event.v1'
          AND source.mime_type = 'application/vnd.collabio.review-event+json'
          AND source.lifecycle_state = 'saved_version' AND source.classification = 'internal'
          AND source.retention_policy_id = 'rp-standard' AND source.legal_hold_state = 'none'
          AND source.kms_key_ref = 'kms://' || NEW.tenant_id || '/internal/v1'
          AND source.owner_principal_id = document.owner_principal_id AND source.created_by = NEW.created_by
          AND source.title = 'Office review event' AND source.created_at_utc = NEW.created_at_utc
          AND source.updated_at_utc = NEW.created_at_utc AND source.audit_chain_ref = NEW.audit_chain_ref
          AND source.manifest_hash = NEW.source_manifest_hash AND source.content_hash = NEW.content_hash
          AND source.content_byte_length = NEW.content_byte_length
          AND source.acl_hash = NEW.acl_hash AND source.acl_version = NEW.acl_version
          AND source.parent_object_id = NEW.object_id AND source.thread_id = NEW.thread_id AND source.parser_profile_id IS NULL
          AND receipt.receipt_hash = NEW.source_write_receipt_hash AND receipt.object_id = NEW.thread_id
          AND receipt.version_id = NEW.event_id AND receipt.object_type = 'comment'
          AND receipt.parent_object_id = NEW.object_id AND receipt.thread_id = NEW.thread_id
          AND receipt.manifest_hash = NEW.source_manifest_hash AND receipt.content_hash = NEW.content_hash
    ) THEN
        RAISE EXCEPTION 'office review source binding is invalid';
    END IF;
    RETURN NEW;
END
$$;
REVOKE ALL ON FUNCTION office.enforce_review_event_source_binding() FROM PUBLIC;
CREATE TRIGGER office_review_events_bind_source BEFORE INSERT ON office.review_events
FOR EACH ROW EXECUTE FUNCTION office.enforce_review_event_source_binding();

CREATE FUNCTION office.guard_review_thread_head()
RETURNS trigger LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    IF (to_jsonb(NEW) - ARRAY['revision', 'current_event_id', 'status', 'updated_at_utc'])
       IS DISTINCT FROM (to_jsonb(OLD) - ARRAY['revision', 'current_event_id', 'status', 'updated_at_utc'])
       OR NEW.revision <> OLD.revision + 1 THEN
        RAISE EXCEPTION 'office review identity is immutable';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM office.review_events WHERE tenant_id = NEW.tenant_id AND thread_id = NEW.thread_id
          AND event_id = NEW.current_event_id AND revision = NEW.revision AND previous_event_id = OLD.current_event_id
          AND status_after = NEW.status AND created_at_utc = NEW.updated_at_utc
    ) THEN
        RAISE EXCEPTION 'office review head must reference a saved successor';
    END IF;
    RETURN NEW;
END
$$;
REVOKE ALL ON FUNCTION office.guard_review_thread_head() FROM PUBLIC;
CREATE TRIGGER office_review_threads_guard_head BEFORE UPDATE ON office.review_threads
FOR EACH ROW EXECUTE FUNCTION office.guard_review_thread_head();

ALTER TABLE office.review_threads ENABLE ROW LEVEL SECURITY;
ALTER TABLE office.review_threads FORCE ROW LEVEL SECURITY;
ALTER TABLE office.review_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE office.review_events FORCE ROW LEVEL SECURITY;
CREATE POLICY office_review_threads_tenant_select ON office.review_threads FOR SELECT USING (tenant_id = collabio.current_tenant_id());
CREATE POLICY office_review_threads_tenant_insert ON office.review_threads FOR INSERT WITH CHECK (tenant_id = collabio.current_tenant_id());
CREATE POLICY office_review_threads_tenant_update ON office.review_threads FOR UPDATE
USING (tenant_id = collabio.current_tenant_id()) WITH CHECK (tenant_id = collabio.current_tenant_id());
CREATE POLICY office_review_threads_no_delete ON office.review_threads FOR DELETE USING (false);
CREATE POLICY office_review_events_tenant_select ON office.review_events FOR SELECT USING (tenant_id = collabio.current_tenant_id());
CREATE POLICY office_review_events_tenant_insert ON office.review_events FOR INSERT WITH CHECK (tenant_id = collabio.current_tenant_id());
CREATE POLICY office_review_events_no_update ON office.review_events FOR UPDATE USING (false);
CREATE POLICY office_review_events_no_delete ON office.review_events FOR DELETE USING (false);
CREATE INDEX office_review_threads_document_idx ON office.review_threads (tenant_id, object_id, thread_id);
CREATE INDEX office_review_threads_anchor_idx ON office.review_threads (tenant_id, object_id, anchor_version_id, thread_id);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        GRANT SELECT, INSERT ON office.review_threads, office.review_events TO collabio_app;
        GRANT UPDATE (revision, current_event_id, status, updated_at_utc) ON office.review_threads TO collabio_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        GRANT SELECT ON office.review_threads, office.review_events TO collabio_worker;
    END IF;
END
$$;
