-- Tenant-scoped Office document grants for active users, roles and groups.
UPDATE collabio.module_catalog
SET module_version = '0.7.0',
    required_migration_versions = '["0083", "0084", "0085", "0086", "0087", "0088", "0089"]'::jsonb
WHERE module_id = 'office_documents';

ALTER TABLE collabio.object_acl_entries
    DROP CONSTRAINT object_acl_entries_office_expiration_check;

ALTER TABLE collabio.object_acl_entries
    ADD CONSTRAINT object_acl_entries_office_expiration_check CHECK (
        expires_at_utc IS NULL OR (
            object_type = 'office.document'
            AND acl_subject_type IN ('user', 'role', 'group')
            AND permission IN ('read', 'write')
            AND expires_at_utc > created_at_utc
        )
    );

ALTER TABLE office.document_share_decisions
    ADD COLUMN subject_type text NOT NULL DEFAULT 'user';

ALTER TABLE office.document_share_decisions
    ADD CONSTRAINT office_document_share_decisions_subject_type_check
    CHECK (subject_type IN ('user', 'role', 'group'));

DROP FUNCTION office.set_document_user_grant(text, text, text, text, text, timestamptz, integer, text);
DROP FUNCTION office.revoke_document_user_grant(text, text, text, text, integer, text);

CREATE FUNCTION office.set_document_subject_grant(
    p_tenant_id text, p_object_id text, p_actor_principal_id text, p_subject_type text,
    p_subject_principal_id text, p_permission text, p_expires_at_utc timestamptz,
    p_expected_acl_version integer, p_mutation_reference text
) RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    document office.documents%ROWTYPE;
    current_acl_version integer;
    next_acl_version integer;
BEGIN
    IF p_tenant_id IS DISTINCT FROM current_setting('app.tenant_id', true)
       OR p_subject_type NOT IN ('user', 'role', 'group')
       OR p_permission NOT IN ('read', 'write')
       OR p_subject_principal_id = '' OR p_actor_principal_id = ''
       OR p_mutation_reference !~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'
       OR (p_expires_at_utc IS NOT NULL AND (
           p_expires_at_utc <= now() OR p_expires_at_utc > now() + interval '366 days'
       )) THEN
        RAISE EXCEPTION 'invalid office document share' USING ERRCODE = '23514';
    END IF;
    SELECT * INTO STRICT document FROM office.documents
    WHERE tenant_id = p_tenant_id AND object_id = p_object_id FOR UPDATE;
    IF (p_subject_type = 'user' AND document.owner_principal_id = p_subject_principal_id)
       OR NOT EXISTS (
           SELECT 1 FROM collabio.object_acl_entries
           WHERE tenant_id = p_tenant_id AND object_id = p_object_id AND object_type = 'office.document'
             AND acl_subject_type = 'user' AND acl_subject_id = p_actor_principal_id
             AND permission = 'admin' AND status = 'active'
       ) OR NOT (
           (p_subject_type = 'user' AND EXISTS (
               SELECT 1 FROM collabio.tenant_principals AS principal
               JOIN collabio.tenant_principal_memberships AS membership
                 ON membership.tenant_id = principal.tenant_id
                AND membership.issuer = principal.issuer AND membership.subject = principal.subject
               WHERE principal.tenant_id = p_tenant_id AND principal.user_id = p_subject_principal_id
                 AND principal.status = 'active' AND membership.status = 'active'
           )) OR (p_subject_type = 'role' AND EXISTS (
               SELECT 1 FROM collabio.tenant_roles
               WHERE tenant_id = p_tenant_id AND role_id = p_subject_principal_id AND status = 'active'
           )) OR (p_subject_type = 'group' AND EXISTS (
               SELECT 1 FROM collabio.tenant_groups
               WHERE tenant_id = p_tenant_id AND group_id = p_subject_principal_id AND status = 'active'
           ))
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
        RETURNING tenant_id, object_id, object_type, acl_subject_type, acl_subject_id,
                  permission, expires_at_utc
    )
    INSERT INTO collabio.object_acl_entries (
        tenant_id, object_id, object_type, acl_subject_type, acl_subject_id,
        permission, expires_at_utc, acl_version, status, audit_chain_ref
    ) SELECT tenant_id, object_id, object_type, acl_subject_type, acl_subject_id,
             permission, expires_at_utc, next_acl_version, 'active',
             'audit:office-share-' || p_mutation_reference
      FROM revoked
      WHERE NOT (acl_subject_type = p_subject_type AND acl_subject_id = p_subject_principal_id);
    INSERT INTO collabio.object_acl_entries (
        tenant_id, object_id, object_type, acl_subject_type, acl_subject_id,
        permission, expires_at_utc, acl_version, status, audit_chain_ref
    ) VALUES (
        p_tenant_id, p_object_id, 'office.document', p_subject_type, p_subject_principal_id,
        p_permission, p_expires_at_utc, next_acl_version, 'active',
        'audit:office-share-' || p_mutation_reference
    );
    INSERT INTO office.document_share_decisions (
        tenant_id, object_id, mutation_reference, actor_principal_id, subject_type,
        subject_principal_id, action, permission, expires_at_utc, previous_acl_version,
        resulting_acl_version, audit_chain_ref
    ) VALUES (
        p_tenant_id, p_object_id, p_mutation_reference, p_actor_principal_id, p_subject_type,
        p_subject_principal_id, 'grant', p_permission, p_expires_at_utc, current_acl_version,
        next_acl_version, 'audit:office-share-' || p_mutation_reference
    );
    RETURN next_acl_version;
END
$$;

CREATE FUNCTION office.revoke_document_subject_grant(
    p_tenant_id text, p_object_id text, p_actor_principal_id text, p_subject_type text,
    p_subject_principal_id text, p_expected_acl_version integer, p_mutation_reference text
) RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $$
DECLARE
    document office.documents%ROWTYPE;
    current_acl_version integer;
    next_acl_version integer;
BEGIN
    IF p_tenant_id IS DISTINCT FROM current_setting('app.tenant_id', true)
       OR p_subject_type NOT IN ('user', 'role', 'group')
       OR p_subject_principal_id = '' OR p_actor_principal_id = ''
       OR p_mutation_reference !~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$' THEN
        RAISE EXCEPTION 'invalid office document share' USING ERRCODE = '23514';
    END IF;
    SELECT * INTO STRICT document FROM office.documents
    WHERE tenant_id = p_tenant_id AND object_id = p_object_id FOR UPDATE;
    IF (p_subject_type = 'user' AND document.owner_principal_id = p_subject_principal_id)
       OR NOT EXISTS (
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
          AND acl_subject_type = p_subject_type AND acl_subject_id = p_subject_principal_id
          AND status = 'active'
    ) THEN
        RAISE EXCEPTION 'invalid office document share' USING ERRCODE = '23514';
    END IF;
    next_acl_version := current_acl_version + 1;
    WITH revoked AS (
        UPDATE collabio.object_acl_entries SET status = 'revoked', revoked_at_utc = now()
        WHERE tenant_id = p_tenant_id AND object_id = p_object_id
          AND object_type = 'office.document' AND status = 'active'
        RETURNING tenant_id, object_id, object_type, acl_subject_type, acl_subject_id,
                  permission, expires_at_utc
    )
    INSERT INTO collabio.object_acl_entries (
        tenant_id, object_id, object_type, acl_subject_type, acl_subject_id,
        permission, expires_at_utc, acl_version, status, audit_chain_ref
    ) SELECT tenant_id, object_id, object_type, acl_subject_type, acl_subject_id,
             permission, expires_at_utc, next_acl_version, 'active',
             'audit:office-share-' || p_mutation_reference
      FROM revoked
      WHERE NOT (acl_subject_type = p_subject_type AND acl_subject_id = p_subject_principal_id);
    INSERT INTO office.document_share_decisions (
        tenant_id, object_id, mutation_reference, actor_principal_id, subject_type,
        subject_principal_id, action, permission, expires_at_utc, previous_acl_version,
        resulting_acl_version, audit_chain_ref
    ) VALUES (
        p_tenant_id, p_object_id, p_mutation_reference, p_actor_principal_id, p_subject_type,
        p_subject_principal_id, 'revoke', NULL, NULL, current_acl_version, next_acl_version,
        'audit:office-share-' || p_mutation_reference
    );
    RETURN next_acl_version;
END
$$;

REVOKE ALL ON FUNCTION office.set_document_subject_grant(
    text, text, text, text, text, text, timestamptz, integer, text
) FROM PUBLIC;
REVOKE ALL ON FUNCTION office.revoke_document_subject_grant(
    text, text, text, text, text, integer, text
) FROM PUBLIC;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        GRANT EXECUTE ON FUNCTION office.set_document_subject_grant(
            text, text, text, text, text, text, timestamptz, integer, text
        ) TO collabio_app;
        GRANT EXECUTE ON FUNCTION office.revoke_document_subject_grant(
            text, text, text, text, text, integer, text
        ) TO collabio_app;
    END IF;
END
$$;
