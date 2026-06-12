import os
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import psycopg
import pytest

from suite.persistence.migrator import apply_migrations
from suite.platform.authz_admin import (
    AbacPolicyBindingUpsertCommand,
    GroupUpsertCommand,
    JwtReplayRetentionPurgeCommand,
    ObjectAclEntryUpsertCommand,
    PgAuthzAdminStore,
    PrincipalGroupMembershipUpsertCommand,
    PrincipalMembershipUpsertCommand,
    PrincipalRoleAssignmentUpsertCommand,
    PrincipalUpsertCommand,
    RoleUpsertCommand,
)
from suite.platform.context import DEFAULT_JWT_AUDIENCE, DEFAULT_JWT_ISSUER, VerifiedJwtClaims
from suite.platform.jwt_replay_store import PgJwtReplayStore
from suite.platform.principal_store import PgPrincipalDirectory


@dataclass(frozen=True)
class LiveAuthzAdminDatabase:
    migration_dsn: str
    app_dsn: str
    authz_admin_dsn: str


def env_or_skip(name: str) -> str:
    value = os.environ.get(name)
    if value is None:
        pytest.skip(f"{name} is not configured")
    return value


@pytest.fixture(scope="module")
def live_database() -> LiveAuthzAdminDatabase:
    migration_dsn = env_or_skip("SUITE_MIGRATION_DATABASE_DSN")
    app_dsn = env_or_skip("SUITE_DATABASE_DSN")
    authz_admin_dsn = env_or_skip("SUITE_AUTHZ_ADMIN_DATABASE_DSN")
    apply_migrations(migration_dsn)
    return LiveAuthzAdminDatabase(
        migration_dsn=migration_dsn,
        app_dsn=app_dsn,
        authz_admin_dsn=authz_admin_dsn,
    )


def claims(*, tenant_id: str, subject: str) -> VerifiedJwtClaims:
    return VerifiedJwtClaims(
        issuer=DEFAULT_JWT_ISSUER,
        subject=subject,
        audience={DEFAULT_JWT_AUDIENCE},
        tenant_id=tenant_id,
        expires_at_epoch=2_000,
        issued_at_epoch=1_000,
    )


def set_tenant(connection: psycopg.Connection[Any], tenant_id: str) -> None:
    connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))


def test_pg_authz_admin_store_upserts_authorization_graph_with_audit_refs(
    live_database: LiveAuthzAdminDatabase,
) -> None:
    suffix = uuid4().hex
    tenant_id = f"tenant-admin-authz-{suffix}"
    subject = f"subject-{suffix}"
    user_id = f"user-{suffix}"
    role_id = f"role-{suffix}"
    group_id = f"group-{suffix}"
    object_id = f"doc-{suffix}"
    policy_id = f"policy-{suffix}"
    store = PgAuthzAdminStore(database_dsn=live_database.authz_admin_dsn)

    principal = store.upsert_principal(
        tenant_id=tenant_id,
        command=PrincipalUpsertCommand(
            issuer=DEFAULT_JWT_ISSUER,
            subject=subject,
            user_id=user_id,
            display_name="Authz Test User",
            email="authz@example.test",
            approval_reference="approval:principal-upsert",
            reason="register principal for authz integration test",
        ),
        audit_chain_ref="audit:principal-upsert",
    )
    membership = store.upsert_membership(
        tenant_id=tenant_id,
        command=PrincipalMembershipUpsertCommand(
            issuer=DEFAULT_JWT_ISSUER,
            subject=subject,
            approval_reference="approval:membership-upsert",
            reason="activate tenant membership",
        ),
        audit_chain_ref="audit:membership-upsert",
    )
    role = store.upsert_role(
        tenant_id=tenant_id,
        command=RoleUpsertCommand(
            role_id=role_id,
            display_name="Knowledge Role",
            approval_reference="approval:role-upsert",
            reason="create tenant role",
        ),
        audit_chain_ref="audit:role-upsert",
    )
    group = store.upsert_group(
        tenant_id=tenant_id,
        command=GroupUpsertCommand(
            group_id=group_id,
            display_name="Knowledge Group",
            approval_reference="approval:group-upsert",
            reason="create tenant group",
        ),
        audit_chain_ref="audit:group-upsert",
    )
    role_assignment = store.upsert_role_assignment(
        tenant_id=tenant_id,
        command=PrincipalRoleAssignmentUpsertCommand(
            issuer=DEFAULT_JWT_ISSUER,
            subject=subject,
            role_id=role_id,
            approval_reference="approval:role-assignment-upsert",
            reason="assign tenant role",
        ),
        audit_chain_ref="audit:role-assignment-upsert",
    )
    group_membership = store.upsert_group_membership(
        tenant_id=tenant_id,
        command=PrincipalGroupMembershipUpsertCommand(
            issuer=DEFAULT_JWT_ISSUER,
            subject=subject,
            group_id=group_id,
            approval_reference="approval:group-membership-upsert",
            reason="assign tenant group",
        ),
        audit_chain_ref="audit:group-membership-upsert",
    )
    acl = store.upsert_object_acl_entry(
        tenant_id=tenant_id,
        command=ObjectAclEntryUpsertCommand(
            object_id=object_id,
            object_type="document",
            acl_subject_type="group",
            acl_subject_id=group_id,
            permission="read",
            acl_version=1,
            approval_reference="approval:acl-upsert",
            reason="grant object read access",
        ),
        audit_chain_ref="audit:acl-upsert",
    )
    abac = store.upsert_abac_policy_binding(
        tenant_id=tenant_id,
        command=AbacPolicyBindingUpsertCommand(
            policy_id=policy_id,
            effect="allow",
            principal_selector={"roles": [role_id]},
            resource_selector={"object_type": "document"},
            condition={"classification": {"not_in": ["confidential"]}},
            priority=20,
            approval_reference="approval:abac-upsert",
            reason="bind ABAC policy",
        ),
        audit_chain_ref="audit:abac-upsert",
    )

    directory = PgPrincipalDirectory(database_dsn=live_database.app_dsn)
    resolved = directory.principal_for_claims(claims(tenant_id=tenant_id, subject=subject))
    resolved_membership = directory.tenant_membership(resolved, tenant_id)

    assert principal.audit_chain_ref == "audit:principal-upsert"
    assert membership.audit_chain_ref == "audit:membership-upsert"
    assert role.resource_id == role_id
    assert group.resource_id == group_id
    assert role_assignment.status == "active"
    assert group_membership.status == "active"
    assert acl.audit_chain_ref == "audit:acl-upsert"
    assert abac.audit_chain_ref == "audit:abac-upsert"
    assert resolved.user_id == user_id
    assert resolved_membership.role_ids == {role_id}
    assert resolved_membership.group_ids == {group_id}
    assert directory.readable_object_ids(
        tenant_id=tenant_id,
        user_id=user_id,
        role_ids=resolved_membership.role_ids,
        group_ids=resolved_membership.group_ids,
    ) == {object_id}
    assert directory.active_abac_policy_ids(tenant_id=tenant_id) == (policy_id,)


def test_pg_authz_admin_store_purges_only_expired_replay_tokens_for_tenant(
    live_database: LiveAuthzAdminDatabase,
) -> None:
    suffix = uuid4().hex
    tenant_a = f"tenant-retention-a-{suffix}"
    tenant_b = f"tenant-retention-b-{suffix}"
    expired_a = f"jwt-expired-a-{suffix}"
    active_a = f"jwt-active-a-{suffix}"
    expired_b = f"jwt-expired-b-{suffix}"
    replay_store = PgJwtReplayStore(database_dsn=live_database.app_dsn)
    admin_store = PgAuthzAdminStore(database_dsn=live_database.authz_admin_dsn)

    replay_store.record(
        tenant_id=tenant_a,
        issuer=DEFAULT_JWT_ISSUER,
        subject=f"user-a-{suffix}",
        jwt_id=expired_a,
        expires_at_epoch=1_000,
        now_epoch=100,
    )
    replay_store.record(
        tenant_id=tenant_a,
        issuer=DEFAULT_JWT_ISSUER,
        subject=f"user-a-{suffix}",
        jwt_id=active_a,
        expires_at_epoch=3_000,
        now_epoch=100,
    )
    replay_store.record(
        tenant_id=tenant_b,
        issuer=DEFAULT_JWT_ISSUER,
        subject=f"user-b-{suffix}",
        jwt_id=expired_b,
        expires_at_epoch=1_000,
        now_epoch=100,
    )

    result = admin_store.purge_expired_jwt_replay_tokens(
        tenant_id=tenant_a,
        command=JwtReplayRetentionPurgeCommand(
            expires_before_epoch=2_000,
            approval_reference="approval:jwt-replay-retention",
            reason="purge expired replay tokens for tenant",
        ),
        audit_chain_ref="audit:jwt-replay-retention",
    )

    with psycopg.connect(live_database.migration_dsn) as owner_connection:
        rows = owner_connection.execute(
            """
            SELECT tenant_id, jwt_id
            FROM collabio.jwt_replay_tokens
            WHERE jwt_id IN (%s, %s, %s)
            ORDER BY jwt_id
            """,
            (expired_a, active_a, expired_b),
        ).fetchall()

    assert result.deleted_count == 1
    assert result.audit_chain_ref == "audit:jwt-replay-retention"
    assert rows == [(tenant_a, active_a), (tenant_b, expired_b)]


def test_authz_admin_role_cannot_bypass_tenant_rls(live_database: LiveAuthzAdminDatabase) -> None:
    suffix = uuid4().hex
    tenant_a = f"tenant-a-{suffix}"
    tenant_b = f"tenant-b-{suffix}"

    with psycopg.connect(live_database.authz_admin_dsn) as admin_connection:
        set_tenant(admin_connection, tenant_a)
        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="row-level security"):
            admin_connection.execute(
                """
                INSERT INTO collabio.tenant_roles (
                    tenant_id,
                    role_id,
                    display_name,
                    audit_chain_ref
                )
                VALUES (%s, 'cross-tenant-role', 'Cross Tenant Role', 'audit:blocked')
                """,
                (tenant_b,),
            )
