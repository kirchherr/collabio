-- 0012_principal_authz_store.sql
-- Tenant-scoped authoritative principal, membership, RBAC, ACL, and ABAC stores.

CREATE SCHEMA IF NOT EXISTS collabio;

CREATE TABLE IF NOT EXISTS collabio.tenant_principals (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    issuer text NOT NULL CHECK (issuer <> ''),
    subject text NOT NULL CHECK (subject <> ''),
    user_id text NOT NULL CHECK (user_id <> ''),
    display_name text,
    email text,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    updated_at_utc timestamptz NOT NULL DEFAULT now(),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    schema_version text NOT NULL DEFAULT 'tenant_principal.v1',
    PRIMARY KEY (tenant_id, issuer, subject),
    UNIQUE (tenant_id, user_id)
);

CREATE TABLE IF NOT EXISTS collabio.tenant_principal_memberships (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    issuer text NOT NULL CHECK (issuer <> ''),
    subject text NOT NULL CHECK (subject <> ''),
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled', 'suspended')),
    joined_at_utc timestamptz NOT NULL DEFAULT now(),
    disabled_at_utc timestamptz,
    updated_at_utc timestamptz NOT NULL DEFAULT now(),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    schema_version text NOT NULL DEFAULT 'tenant_principal_membership.v1',
    PRIMARY KEY (tenant_id, issuer, subject),
    FOREIGN KEY (tenant_id, issuer, subject)
        REFERENCES collabio.tenant_principals (tenant_id, issuer, subject),
    CHECK (status = 'active' OR disabled_at_utc IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS collabio.tenant_roles (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    role_id text NOT NULL CHECK (role_id <> ''),
    display_name text NOT NULL CHECK (display_name <> ''),
    description text,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled', 'deprecated')),
    system_role boolean NOT NULL DEFAULT false,
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    updated_at_utc timestamptz NOT NULL DEFAULT now(),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    schema_version text NOT NULL DEFAULT 'tenant_role.v1',
    PRIMARY KEY (tenant_id, role_id)
);

CREATE TABLE IF NOT EXISTS collabio.tenant_groups (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    group_id text NOT NULL CHECK (group_id <> ''),
    display_name text NOT NULL CHECK (display_name <> ''),
    description text,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    updated_at_utc timestamptz NOT NULL DEFAULT now(),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    schema_version text NOT NULL DEFAULT 'tenant_group.v1',
    PRIMARY KEY (tenant_id, group_id)
);

CREATE TABLE IF NOT EXISTS collabio.tenant_principal_role_assignments (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    issuer text NOT NULL CHECK (issuer <> ''),
    subject text NOT NULL CHECK (subject <> ''),
    role_id text NOT NULL CHECK (role_id <> ''),
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked')),
    assigned_at_utc timestamptz NOT NULL DEFAULT now(),
    revoked_at_utc timestamptz,
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    schema_version text NOT NULL DEFAULT 'tenant_principal_role_assignment.v1',
    PRIMARY KEY (tenant_id, issuer, subject, role_id),
    FOREIGN KEY (tenant_id, issuer, subject)
        REFERENCES collabio.tenant_principals (tenant_id, issuer, subject),
    FOREIGN KEY (tenant_id, role_id)
        REFERENCES collabio.tenant_roles (tenant_id, role_id),
    CHECK (status <> 'revoked' OR revoked_at_utc IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS collabio.tenant_principal_group_memberships (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    issuer text NOT NULL CHECK (issuer <> ''),
    subject text NOT NULL CHECK (subject <> ''),
    group_id text NOT NULL CHECK (group_id <> ''),
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked')),
    joined_at_utc timestamptz NOT NULL DEFAULT now(),
    revoked_at_utc timestamptz,
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    schema_version text NOT NULL DEFAULT 'tenant_principal_group_membership.v1',
    PRIMARY KEY (tenant_id, issuer, subject, group_id),
    FOREIGN KEY (tenant_id, issuer, subject)
        REFERENCES collabio.tenant_principals (tenant_id, issuer, subject),
    FOREIGN KEY (tenant_id, group_id)
        REFERENCES collabio.tenant_groups (tenant_id, group_id),
    CHECK (status <> 'revoked' OR revoked_at_utc IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS collabio.object_acl_entries (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    object_id text NOT NULL CHECK (object_id <> ''),
    object_type text NOT NULL CHECK (object_type <> ''),
    acl_subject_type text NOT NULL CHECK (acl_subject_type IN ('user', 'role', 'group')),
    acl_subject_id text NOT NULL CHECK (acl_subject_id <> ''),
    permission text NOT NULL CHECK (permission IN ('read', 'write', 'admin')),
    acl_version integer NOT NULL CHECK (acl_version >= 1),
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked')),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    revoked_at_utc timestamptz,
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    schema_version text NOT NULL DEFAULT 'object_acl_entry.v1',
    PRIMARY KEY (
        tenant_id,
        object_id,
        object_type,
        acl_subject_type,
        acl_subject_id,
        permission,
        acl_version
    ),
    CHECK (status <> 'revoked' OR revoked_at_utc IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS collabio.abac_policy_bindings (
    tenant_id text NOT NULL CHECK (tenant_id <> ''),
    policy_id text NOT NULL CHECK (policy_id <> ''),
    effect text NOT NULL CHECK (effect IN ('allow', 'deny')),
    principal_selector jsonb NOT NULL CHECK (jsonb_typeof(principal_selector) = 'object'),
    resource_selector jsonb NOT NULL CHECK (jsonb_typeof(resource_selector) = 'object'),
    condition jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(condition) = 'object'),
    priority integer NOT NULL DEFAULT 0,
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    created_at_utc timestamptz NOT NULL DEFAULT now(),
    updated_at_utc timestamptz NOT NULL DEFAULT now(),
    audit_chain_ref text NOT NULL CHECK (audit_chain_ref ~ '^[a-z0-9][a-z0-9_+.-]*:.+'),
    schema_version text NOT NULL DEFAULT 'abac_policy_binding.v1',
    PRIMARY KEY (tenant_id, policy_id)
);

COMMENT ON TABLE collabio.tenant_principals IS
    'Tenant-scoped authoritative principal records used by signed JWT and OIDC request context resolution.';
COMMENT ON TABLE collabio.tenant_principal_memberships IS
    'Tenant membership gate. A signed token is accepted only when this store has an active membership.';
COMMENT ON TABLE collabio.tenant_roles IS
    'Tenant-scoped role catalog. UI visibility is not authorization; server-side role assignments remain authoritative.';
COMMENT ON TABLE collabio.tenant_groups IS
    'Tenant-scoped group catalog used for ACL and ABAC decisions.';
COMMENT ON TABLE collabio.object_acl_entries IS
    'Authoritative object ACL entries. Search and RAG candidates must be checked against these grants before source fetch.';
COMMENT ON TABLE collabio.abac_policy_bindings IS
    'Tenant-scoped ABAC policy bindings. LLM output and client claims are never authoritative authorization inputs.';

CREATE INDEX IF NOT EXISTS tenant_principals_user_idx
    ON collabio.tenant_principals (tenant_id, user_id, status);

CREATE INDEX IF NOT EXISTS tenant_principal_memberships_status_idx
    ON collabio.tenant_principal_memberships (tenant_id, status);

CREATE INDEX IF NOT EXISTS tenant_roles_status_idx
    ON collabio.tenant_roles (tenant_id, status);

CREATE INDEX IF NOT EXISTS tenant_groups_status_idx
    ON collabio.tenant_groups (tenant_id, status);

CREATE INDEX IF NOT EXISTS tenant_principal_role_assignments_lookup_idx
    ON collabio.tenant_principal_role_assignments (tenant_id, issuer, subject, status);

CREATE INDEX IF NOT EXISTS tenant_principal_group_memberships_lookup_idx
    ON collabio.tenant_principal_group_memberships (tenant_id, issuer, subject, status);

CREATE INDEX IF NOT EXISTS object_acl_entries_lookup_idx
    ON collabio.object_acl_entries (tenant_id, object_id, object_type, permission, status);

CREATE INDEX IF NOT EXISTS object_acl_entries_subject_idx
    ON collabio.object_acl_entries (tenant_id, acl_subject_type, acl_subject_id, permission, status);

CREATE INDEX IF NOT EXISTS abac_policy_bindings_status_idx
    ON collabio.abac_policy_bindings (tenant_id, status, priority DESC);

DROP TRIGGER IF EXISTS tenant_principals_touch_updated_at_utc
    ON collabio.tenant_principals;
CREATE TRIGGER tenant_principals_touch_updated_at_utc
    BEFORE UPDATE ON collabio.tenant_principals
    FOR EACH ROW
    EXECUTE FUNCTION collabio.touch_updated_at_utc();

DROP TRIGGER IF EXISTS tenant_principal_memberships_touch_updated_at_utc
    ON collabio.tenant_principal_memberships;
CREATE TRIGGER tenant_principal_memberships_touch_updated_at_utc
    BEFORE UPDATE ON collabio.tenant_principal_memberships
    FOR EACH ROW
    EXECUTE FUNCTION collabio.touch_updated_at_utc();

DROP TRIGGER IF EXISTS tenant_roles_touch_updated_at_utc
    ON collabio.tenant_roles;
CREATE TRIGGER tenant_roles_touch_updated_at_utc
    BEFORE UPDATE ON collabio.tenant_roles
    FOR EACH ROW
    EXECUTE FUNCTION collabio.touch_updated_at_utc();

DROP TRIGGER IF EXISTS tenant_groups_touch_updated_at_utc
    ON collabio.tenant_groups;
CREATE TRIGGER tenant_groups_touch_updated_at_utc
    BEFORE UPDATE ON collabio.tenant_groups
    FOR EACH ROW
    EXECUTE FUNCTION collabio.touch_updated_at_utc();

DROP TRIGGER IF EXISTS abac_policy_bindings_touch_updated_at_utc
    ON collabio.abac_policy_bindings;
CREATE TRIGGER abac_policy_bindings_touch_updated_at_utc
    BEFORE UPDATE ON collabio.abac_policy_bindings
    FOR EACH ROW
    EXECUTE FUNCTION collabio.touch_updated_at_utc();

ALTER TABLE collabio.tenant_principals ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.tenant_principals FORCE ROW LEVEL SECURITY;
ALTER TABLE collabio.tenant_principal_memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.tenant_principal_memberships FORCE ROW LEVEL SECURITY;
ALTER TABLE collabio.tenant_roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.tenant_roles FORCE ROW LEVEL SECURITY;
ALTER TABLE collabio.tenant_groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.tenant_groups FORCE ROW LEVEL SECURITY;
ALTER TABLE collabio.tenant_principal_role_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.tenant_principal_role_assignments FORCE ROW LEVEL SECURITY;
ALTER TABLE collabio.tenant_principal_group_memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.tenant_principal_group_memberships FORCE ROW LEVEL SECURITY;
ALTER TABLE collabio.object_acl_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.object_acl_entries FORCE ROW LEVEL SECURITY;
ALTER TABLE collabio.abac_policy_bindings ENABLE ROW LEVEL SECURITY;
ALTER TABLE collabio.abac_policy_bindings FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_principals_tenant_select ON collabio.tenant_principals;
CREATE POLICY tenant_principals_tenant_select
    ON collabio.tenant_principals
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS tenant_principals_tenant_insert ON collabio.tenant_principals;
CREATE POLICY tenant_principals_tenant_insert
    ON collabio.tenant_principals
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS tenant_principals_tenant_update ON collabio.tenant_principals;
CREATE POLICY tenant_principals_tenant_update
    ON collabio.tenant_principals
    FOR UPDATE
    USING (tenant_id = collabio.current_tenant_id())
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS tenant_principals_no_hard_delete ON collabio.tenant_principals;
CREATE POLICY tenant_principals_no_hard_delete
    ON collabio.tenant_principals
    FOR DELETE
    USING (false);

DROP POLICY IF EXISTS tenant_principal_memberships_tenant_select ON collabio.tenant_principal_memberships;
CREATE POLICY tenant_principal_memberships_tenant_select
    ON collabio.tenant_principal_memberships
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS tenant_principal_memberships_tenant_insert ON collabio.tenant_principal_memberships;
CREATE POLICY tenant_principal_memberships_tenant_insert
    ON collabio.tenant_principal_memberships
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS tenant_principal_memberships_tenant_update ON collabio.tenant_principal_memberships;
CREATE POLICY tenant_principal_memberships_tenant_update
    ON collabio.tenant_principal_memberships
    FOR UPDATE
    USING (tenant_id = collabio.current_tenant_id())
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS tenant_principal_memberships_no_hard_delete ON collabio.tenant_principal_memberships;
CREATE POLICY tenant_principal_memberships_no_hard_delete
    ON collabio.tenant_principal_memberships
    FOR DELETE
    USING (false);

DROP POLICY IF EXISTS tenant_roles_tenant_select ON collabio.tenant_roles;
CREATE POLICY tenant_roles_tenant_select
    ON collabio.tenant_roles
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS tenant_roles_tenant_insert ON collabio.tenant_roles;
CREATE POLICY tenant_roles_tenant_insert
    ON collabio.tenant_roles
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS tenant_roles_tenant_update ON collabio.tenant_roles;
CREATE POLICY tenant_roles_tenant_update
    ON collabio.tenant_roles
    FOR UPDATE
    USING (tenant_id = collabio.current_tenant_id())
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS tenant_roles_no_hard_delete ON collabio.tenant_roles;
CREATE POLICY tenant_roles_no_hard_delete
    ON collabio.tenant_roles
    FOR DELETE
    USING (false);

DROP POLICY IF EXISTS tenant_groups_tenant_select ON collabio.tenant_groups;
CREATE POLICY tenant_groups_tenant_select
    ON collabio.tenant_groups
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS tenant_groups_tenant_insert ON collabio.tenant_groups;
CREATE POLICY tenant_groups_tenant_insert
    ON collabio.tenant_groups
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS tenant_groups_tenant_update ON collabio.tenant_groups;
CREATE POLICY tenant_groups_tenant_update
    ON collabio.tenant_groups
    FOR UPDATE
    USING (tenant_id = collabio.current_tenant_id())
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS tenant_groups_no_hard_delete ON collabio.tenant_groups;
CREATE POLICY tenant_groups_no_hard_delete
    ON collabio.tenant_groups
    FOR DELETE
    USING (false);

DROP POLICY IF EXISTS tenant_principal_role_assignments_tenant_select
    ON collabio.tenant_principal_role_assignments;
CREATE POLICY tenant_principal_role_assignments_tenant_select
    ON collabio.tenant_principal_role_assignments
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS tenant_principal_role_assignments_tenant_insert
    ON collabio.tenant_principal_role_assignments;
CREATE POLICY tenant_principal_role_assignments_tenant_insert
    ON collabio.tenant_principal_role_assignments
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS tenant_principal_role_assignments_tenant_update
    ON collabio.tenant_principal_role_assignments;
CREATE POLICY tenant_principal_role_assignments_tenant_update
    ON collabio.tenant_principal_role_assignments
    FOR UPDATE
    USING (tenant_id = collabio.current_tenant_id())
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS tenant_principal_role_assignments_no_hard_delete
    ON collabio.tenant_principal_role_assignments;
CREATE POLICY tenant_principal_role_assignments_no_hard_delete
    ON collabio.tenant_principal_role_assignments
    FOR DELETE
    USING (false);

DROP POLICY IF EXISTS tenant_principal_group_memberships_tenant_select
    ON collabio.tenant_principal_group_memberships;
CREATE POLICY tenant_principal_group_memberships_tenant_select
    ON collabio.tenant_principal_group_memberships
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS tenant_principal_group_memberships_tenant_insert
    ON collabio.tenant_principal_group_memberships;
CREATE POLICY tenant_principal_group_memberships_tenant_insert
    ON collabio.tenant_principal_group_memberships
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS tenant_principal_group_memberships_tenant_update
    ON collabio.tenant_principal_group_memberships;
CREATE POLICY tenant_principal_group_memberships_tenant_update
    ON collabio.tenant_principal_group_memberships
    FOR UPDATE
    USING (tenant_id = collabio.current_tenant_id())
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS tenant_principal_group_memberships_no_hard_delete
    ON collabio.tenant_principal_group_memberships;
CREATE POLICY tenant_principal_group_memberships_no_hard_delete
    ON collabio.tenant_principal_group_memberships
    FOR DELETE
    USING (false);

DROP POLICY IF EXISTS object_acl_entries_tenant_select ON collabio.object_acl_entries;
CREATE POLICY object_acl_entries_tenant_select
    ON collabio.object_acl_entries
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS object_acl_entries_tenant_insert ON collabio.object_acl_entries;
CREATE POLICY object_acl_entries_tenant_insert
    ON collabio.object_acl_entries
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS object_acl_entries_tenant_update ON collabio.object_acl_entries;
CREATE POLICY object_acl_entries_tenant_update
    ON collabio.object_acl_entries
    FOR UPDATE
    USING (tenant_id = collabio.current_tenant_id())
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS object_acl_entries_no_hard_delete ON collabio.object_acl_entries;
CREATE POLICY object_acl_entries_no_hard_delete
    ON collabio.object_acl_entries
    FOR DELETE
    USING (false);

DROP POLICY IF EXISTS abac_policy_bindings_tenant_select ON collabio.abac_policy_bindings;
CREATE POLICY abac_policy_bindings_tenant_select
    ON collabio.abac_policy_bindings
    FOR SELECT
    USING (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS abac_policy_bindings_tenant_insert ON collabio.abac_policy_bindings;
CREATE POLICY abac_policy_bindings_tenant_insert
    ON collabio.abac_policy_bindings
    FOR INSERT
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS abac_policy_bindings_tenant_update ON collabio.abac_policy_bindings;
CREATE POLICY abac_policy_bindings_tenant_update
    ON collabio.abac_policy_bindings
    FOR UPDATE
    USING (tenant_id = collabio.current_tenant_id())
    WITH CHECK (tenant_id = collabio.current_tenant_id());

DROP POLICY IF EXISTS abac_policy_bindings_no_hard_delete ON collabio.abac_policy_bindings;
CREATE POLICY abac_policy_bindings_no_hard_delete
    ON collabio.abac_policy_bindings
    FOR DELETE
    USING (false);

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
        EXECUTE 'GRANT USAGE ON SCHEMA collabio TO collabio_app';
        EXECUTE 'GRANT SELECT ON TABLE collabio.tenant_principals TO collabio_app';
        EXECUTE 'GRANT SELECT ON TABLE collabio.tenant_principal_memberships TO collabio_app';
        EXECUTE 'GRANT SELECT ON TABLE collabio.tenant_roles TO collabio_app';
        EXECUTE 'GRANT SELECT ON TABLE collabio.tenant_groups TO collabio_app';
        EXECUTE 'GRANT SELECT ON TABLE collabio.tenant_principal_role_assignments TO collabio_app';
        EXECUTE 'GRANT SELECT ON TABLE collabio.tenant_principal_group_memberships TO collabio_app';
        EXECUTE 'GRANT SELECT ON TABLE collabio.object_acl_entries TO collabio_app';
        EXECUTE 'GRANT SELECT ON TABLE collabio.abac_policy_bindings TO collabio_app';
    END IF;
END
$$;
