-- Tenant-safe, owner-controlled Office document sharing with immutable decision receipts.
CREATE TABLE office.document_share_decisions (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    object_id text NOT NULL,
    mutation_reference text NOT NULL CHECK (length(mutation_reference) BETWEEN 1 AND 128),
    actor_principal_id text NOT NULL CHECK (actor_principal_id <> ''),
    subject_principal_id text NOT NULL CHECK (subject_principal_id <> ''),
    action text NOT NULL CHECK (action IN ('grant', 'revoke')),
    permission text CHECK (permission IN ('read', 'write')),
    previous_acl_version integer NOT NULL CHECK (previous_acl_version >= 1),
    resulting_acl_version integer NOT NULL CHECK (resulting_acl_version = previous_acl_version + 1),
    decided_at_utc timestamptz NOT NULL DEFAULT now(),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref LIKE 'audit:%'),
    PRIMARY KEY (tenant_id, object_id, mutation_reference),
    FOREIGN KEY (tenant_id, object_id) REFERENCES office.documents (tenant_id, object_id),
    CHECK ((action = 'grant') = (permission IS NOT NULL))
);

ALTER TABLE office.document_share_decisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE office.document_share_decisions FORCE ROW LEVEL SECURITY;
CREATE POLICY office_document_share_decisions_tenant_select ON office.document_share_decisions FOR SELECT
USING (tenant_id = collabio.current_tenant_id());
CREATE POLICY office_document_share_decisions_no_insert ON office.document_share_decisions FOR INSERT WITH CHECK (false);
CREATE POLICY office_document_share_decisions_no_update ON office.document_share_decisions FOR UPDATE USING (false);
CREATE POLICY office_document_share_decisions_no_delete ON office.document_share_decisions FOR DELETE USING (false);

CREATE FUNCTION office.set_document_user_grant(
    p_tenant_id text, p_object_id text, p_actor_principal_id text, p_subject_principal_id text,
    p_permission text, p_expected_acl_version integer, p_mutation_reference text
) RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    document office.documents%ROWTYPE;
    current_acl_version integer;
    next_acl_version integer;
BEGIN
    IF p_tenant_id IS DISTINCT FROM current_setting('app.tenant_id', true)
       OR p_permission NOT IN ('read', 'write')
       OR p_subject_principal_id = '' OR p_actor_principal_id = ''
       OR p_mutation_reference !~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$' THEN
        RAISE EXCEPTION 'invalid office document share' USING ERRCODE = '23514';
    END IF;
    SELECT * INTO STRICT document FROM office.documents
    WHERE tenant_id = p_tenant_id AND object_id = p_object_id FOR UPDATE;
    IF document.owner_principal_id = p_subject_principal_id OR NOT EXISTS (
        SELECT 1 FROM collabio.object_acl_entries
        WHERE tenant_id = p_tenant_id AND object_id = p_object_id AND object_type = 'office.document'
          AND acl_subject_type = 'user' AND acl_subject_id = p_actor_principal_id
          AND permission = 'admin' AND status = 'active'
    ) OR NOT EXISTS (
        SELECT 1 FROM collabio.tenant_principals AS principal
        JOIN collabio.tenant_principal_memberships AS membership
          ON membership.tenant_id = principal.tenant_id
         AND membership.issuer = principal.issuer AND membership.subject = principal.subject
        WHERE principal.tenant_id = p_tenant_id AND principal.user_id = p_subject_principal_id
          AND principal.status = 'active' AND membership.status = 'active'
    ) THEN
        RAISE EXCEPTION 'invalid office document share' USING ERRCODE = '23514';
    END IF;
    SELECT COALESCE(MAX(acl_version), 1) INTO current_acl_version
    FROM collabio.object_acl_entries
    WHERE tenant_id = p_tenant_id AND object_id = p_object_id AND object_type = 'office.document';
    IF current_acl_version <> p_expected_acl_version THEN
        RAISE EXCEPTION 'stale office document ACL' USING ERRCODE = '40001';
    END IF;
    IF EXISTS (SELECT 1 FROM office.document_share_decisions
               WHERE tenant_id = p_tenant_id AND object_id = p_object_id
                 AND mutation_reference = p_mutation_reference) THEN
        RAISE EXCEPTION 'duplicate office share mutation' USING ERRCODE = '40001';
    END IF;
    next_acl_version := current_acl_version + 1;
    WITH revoked AS (
        UPDATE collabio.object_acl_entries SET status = 'revoked', revoked_at_utc = now()
        WHERE tenant_id = p_tenant_id AND object_id = p_object_id
          AND object_type = 'office.document' AND status = 'active'
        RETURNING tenant_id, object_id, object_type, acl_subject_type, acl_subject_id, permission
    )
    INSERT INTO collabio.object_acl_entries (
        tenant_id, object_id, object_type, acl_subject_type, acl_subject_id,
        permission, acl_version, status, audit_chain_ref
    ) SELECT tenant_id, object_id, object_type, acl_subject_type, acl_subject_id,
             permission, next_acl_version, 'active', 'audit:office-share-' || p_mutation_reference
      FROM revoked
      WHERE NOT (acl_subject_type = 'user' AND acl_subject_id = p_subject_principal_id);
    INSERT INTO collabio.object_acl_entries (
        tenant_id, object_id, object_type, acl_subject_type, acl_subject_id,
        permission, acl_version, status, audit_chain_ref
    ) VALUES (
        p_tenant_id, p_object_id, 'office.document', 'user', p_subject_principal_id,
        p_permission, next_acl_version, 'active', 'audit:office-share-' || p_mutation_reference
    );
    INSERT INTO office.document_share_decisions (
        tenant_id, object_id, mutation_reference, actor_principal_id, subject_principal_id,
        action, permission, previous_acl_version, resulting_acl_version, audit_chain_ref
    ) VALUES (
        p_tenant_id, p_object_id, p_mutation_reference, p_actor_principal_id, p_subject_principal_id,
        'grant', p_permission, current_acl_version, next_acl_version, 'audit:office-share-' || p_mutation_reference
    );
    RETURN next_acl_version;
END
$$;

CREATE FUNCTION office.revoke_document_user_grant(
    p_tenant_id text, p_object_id text, p_actor_principal_id text, p_subject_principal_id text,
    p_expected_acl_version integer, p_mutation_reference text
) RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    document office.documents%ROWTYPE;
    current_acl_version integer;
    next_acl_version integer;
BEGIN
    IF p_tenant_id IS DISTINCT FROM current_setting('app.tenant_id', true)
       OR p_subject_principal_id = '' OR p_actor_principal_id = ''
       OR p_mutation_reference !~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$' THEN
        RAISE EXCEPTION 'invalid office document share' USING ERRCODE = '23514';
    END IF;
    SELECT * INTO STRICT document FROM office.documents
    WHERE tenant_id = p_tenant_id AND object_id = p_object_id FOR UPDATE;
    IF document.owner_principal_id = p_subject_principal_id OR NOT EXISTS (
        SELECT 1 FROM collabio.object_acl_entries
        WHERE tenant_id = p_tenant_id AND object_id = p_object_id AND object_type = 'office.document'
          AND acl_subject_type = 'user' AND acl_subject_id = p_actor_principal_id
          AND permission = 'admin' AND status = 'active'
    ) THEN
        RAISE EXCEPTION 'invalid office document share' USING ERRCODE = '23514';
    END IF;
    SELECT COALESCE(MAX(acl_version), 1) INTO current_acl_version
    FROM collabio.object_acl_entries
    WHERE tenant_id = p_tenant_id AND object_id = p_object_id AND object_type = 'office.document';
    IF current_acl_version <> p_expected_acl_version THEN
        RAISE EXCEPTION 'stale office document ACL' USING ERRCODE = '40001';
    END IF;
    IF EXISTS (SELECT 1 FROM office.document_share_decisions
               WHERE tenant_id = p_tenant_id AND object_id = p_object_id
                 AND mutation_reference = p_mutation_reference) THEN
        RAISE EXCEPTION 'duplicate office share mutation' USING ERRCODE = '40001';
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM collabio.object_acl_entries
        WHERE tenant_id = p_tenant_id AND object_id = p_object_id AND object_type = 'office.document'
          AND acl_subject_type = 'user' AND acl_subject_id = p_subject_principal_id AND status = 'active'
    ) THEN
        RAISE EXCEPTION 'invalid office document share' USING ERRCODE = '23514';
    END IF;
    next_acl_version := current_acl_version + 1;
    WITH revoked AS (
        UPDATE collabio.object_acl_entries SET status = 'revoked', revoked_at_utc = now()
        WHERE tenant_id = p_tenant_id AND object_id = p_object_id
          AND object_type = 'office.document' AND status = 'active'
        RETURNING tenant_id, object_id, object_type, acl_subject_type, acl_subject_id, permission
    )
    INSERT INTO collabio.object_acl_entries (
        tenant_id, object_id, object_type, acl_subject_type, acl_subject_id,
        permission, acl_version, status, audit_chain_ref
    ) SELECT tenant_id, object_id, object_type, acl_subject_type, acl_subject_id,
             permission, next_acl_version, 'active', 'audit:office-share-' || p_mutation_reference
      FROM revoked
      WHERE NOT (acl_subject_type = 'user' AND acl_subject_id = p_subject_principal_id);
    INSERT INTO office.document_share_decisions (
        tenant_id, object_id, mutation_reference, actor_principal_id, subject_principal_id,
        action, permission, previous_acl_version, resulting_acl_version, audit_chain_ref
    ) VALUES (
        p_tenant_id, p_object_id, p_mutation_reference, p_actor_principal_id, p_subject_principal_id,
        'revoke', NULL, current_acl_version, next_acl_version, 'audit:office-share-' || p_mutation_reference
    );
    RETURN next_acl_version;
END
$$;

REVOKE ALL ON FUNCTION office.set_document_user_grant(text, text, text, text, text, integer, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION office.revoke_document_user_grant(text, text, text, text, integer, text) FROM PUBLIC;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        GRANT SELECT ON office.document_share_decisions TO collabio_app;
        GRANT EXECUTE ON FUNCTION office.set_document_user_grant(text, text, text, text, text, integer, text)
            TO collabio_app;
        GRANT EXECUTE ON FUNCTION office.revoke_document_user_grant(text, text, text, text, integer, text)
            TO collabio_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
        GRANT SELECT ON office.document_share_decisions TO collabio_worker;
    END IF;
END
$$;
