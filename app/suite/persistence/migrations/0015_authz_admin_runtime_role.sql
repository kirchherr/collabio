-- 0015_authz_admin_runtime_role.sql
-- Dedicated runtime role for audited authorization administration.

CREATE SCHEMA IF NOT EXISTS collabio;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_authz_admin') THEN
        CREATE ROLE collabio_authz_admin LOGIN PASSWORD 'collabio_authz_admin';
    END IF;
END
$$;

DROP POLICY IF EXISTS jwt_replay_tokens_retention_delete ON collabio.jwt_replay_tokens;
CREATE POLICY jwt_replay_tokens_retention_delete
    ON collabio.jwt_replay_tokens
    FOR DELETE
    TO collabio_authz_admin
    USING (
        tenant_id = collabio.current_tenant_id()
        AND expires_at_epoch <= COALESCE(
            NULLIF(current_setting('app.retention_now_epoch', true), '')::bigint,
            0
        )
    );

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_authz_admin') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA collabio TO collabio_authz_admin';

        EXECUTE 'GRANT SELECT, INSERT, UPDATE ON TABLE collabio.tenant_principals TO collabio_authz_admin';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE ON TABLE collabio.tenant_principal_memberships TO collabio_authz_admin';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE ON TABLE collabio.tenant_roles TO collabio_authz_admin';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE ON TABLE collabio.tenant_groups TO collabio_authz_admin';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE ON TABLE collabio.tenant_principal_role_assignments TO collabio_authz_admin';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE ON TABLE collabio.tenant_principal_group_memberships TO collabio_authz_admin';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE ON TABLE collabio.object_acl_entries TO collabio_authz_admin';
        EXECUTE 'GRANT SELECT, INSERT, UPDATE ON TABLE collabio.abac_policy_bindings TO collabio_authz_admin';

        EXECUTE 'GRANT SELECT, DELETE ON TABLE collabio.jwt_replay_tokens TO collabio_authz_admin';
        EXECUTE 'GRANT SELECT ON TABLE collabio.jwt_replay_events TO collabio_authz_admin';
    END IF;
END
$$;
