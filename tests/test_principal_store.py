import os
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from psycopg.types.json import Jsonb

from suite.persistence.migrator import apply_migrations
from suite.platform.context import DEFAULT_JWT_AUDIENCE, DEFAULT_JWT_ISSUER, VerifiedJwtClaims
from suite.platform.principal_store import PgPrincipalDirectory


@dataclass(frozen=True)
class LiveDatabase:
    migration_dsn: str
    app_dsn: str


def env_or_skip(name: str) -> str:
    value = os.environ.get(name)
    if value is None:
        pytest.skip(f"{name} is not configured")
    return value


@pytest.fixture(scope="module")
def live_database() -> LiveDatabase:
    migration_dsn = env_or_skip("SUITE_MIGRATION_DATABASE_DSN")
    app_dsn = env_or_skip("SUITE_DATABASE_DSN")
    apply_migrations(migration_dsn)
    return LiveDatabase(migration_dsn=migration_dsn, app_dsn=app_dsn)


def set_tenant(connection: psycopg.Connection[Any], tenant_id: str) -> None:
    connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))


def seed_principal_authz(
    connection: psycopg.Connection[Any],
    *,
    tenant_id: str,
    subject: str,
    user_id: str,
    readable_object_id: str,
    policy_id: str,
) -> None:
    connection.execute(
        """
        INSERT INTO collabio.tenant_principals (
            tenant_id,
            issuer,
            subject,
            user_id,
            display_name,
            audit_chain_ref
        )
        VALUES (%s, %s, %s, %s, 'Test User', 'audit:tenant-principal')
        """,
        (tenant_id, DEFAULT_JWT_ISSUER, subject, user_id),
    )
    connection.execute(
        """
        INSERT INTO collabio.tenant_principal_memberships (
            tenant_id,
            issuer,
            subject,
            audit_chain_ref
        )
        VALUES (%s, %s, %s, 'audit:tenant-membership')
        """,
        (tenant_id, DEFAULT_JWT_ISSUER, subject),
    )
    connection.execute(
        """
        INSERT INTO collabio.tenant_roles (
            tenant_id,
            role_id,
            display_name,
            audit_chain_ref
        )
        VALUES
            (%s, 'knowledge-worker', 'Knowledge Worker', 'audit:tenant-role'),
            (%s, 'security-admin', 'Security Admin', 'audit:tenant-role')
        """,
        (tenant_id, tenant_id),
    )
    connection.execute(
        """
        INSERT INTO collabio.tenant_groups (
            tenant_id,
            group_id,
            display_name,
            audit_chain_ref
        )
        VALUES
            (%s, 'team-demo', 'Demo Team', 'audit:tenant-group'),
            (%s, 'payroll', 'Payroll', 'audit:tenant-group')
        """,
        (tenant_id, tenant_id),
    )
    connection.execute(
        """
        INSERT INTO collabio.tenant_principal_role_assignments (
            tenant_id,
            issuer,
            subject,
            role_id,
            audit_chain_ref
        )
        VALUES (%s, %s, %s, 'knowledge-worker', 'audit:role-assignment')
        """,
        (tenant_id, DEFAULT_JWT_ISSUER, subject),
    )
    connection.execute(
        """
        INSERT INTO collabio.tenant_principal_group_memberships (
            tenant_id,
            issuer,
            subject,
            group_id,
            audit_chain_ref
        )
        VALUES (%s, %s, %s, 'team-demo', 'audit:group-membership')
        """,
        (tenant_id, DEFAULT_JWT_ISSUER, subject),
    )
    connection.execute(
        """
        INSERT INTO collabio.object_acl_entries (
            tenant_id,
            object_id,
            object_type,
            acl_subject_type,
            acl_subject_id,
            permission,
            acl_version,
            audit_chain_ref
        )
        VALUES
            (%s, %s, 'document', 'group', 'team-demo', 'read', 1, 'audit:acl-readable'),
            (%s, %s, 'document', 'group', 'payroll', 'read', 1, 'audit:acl-secret'),
            (%s, %s, 'document', 'role', 'security-admin', 'admin', 1, 'audit:acl-admin')
        """,
        (
            tenant_id,
            readable_object_id,
            tenant_id,
            f"secret-{readable_object_id}",
            tenant_id,
            f"admin-{readable_object_id}",
        ),
    )
    connection.execute(
        """
        INSERT INTO collabio.abac_policy_bindings (
            tenant_id,
            policy_id,
            effect,
            principal_selector,
            resource_selector,
            condition,
            priority,
            audit_chain_ref
        )
        VALUES (%s, %s, 'allow', %s, %s, %s, 10, 'audit:abac-policy')
        """,
        (
            tenant_id,
            policy_id,
            Jsonb({"roles": ["knowledge-worker"]}),
            Jsonb({"object_type": "document"}),
            Jsonb({"classification": {"not_in": ["confidential"]}}),
        ),
    )


def verified_claims(*, tenant_id: str, subject: str) -> VerifiedJwtClaims:
    return VerifiedJwtClaims(
        issuer=DEFAULT_JWT_ISSUER,
        subject=subject,
        audience={DEFAULT_JWT_AUDIENCE},
        tenant_id=tenant_id,
        expires_at_epoch=2_000,
        issued_at_epoch=1_000,
    )


def test_pg_principal_directory_resolves_membership_roles_groups_acl_and_abac(
    live_database: LiveDatabase,
) -> None:
    suffix = uuid4().hex
    tenant_id = f"tenant-authz-{suffix}"
    subject = f"user-{suffix}"
    user_id = f"user-{suffix}"
    readable_object_id = f"doc-{suffix}"
    policy_id = f"policy-{suffix}"

    with psycopg.connect(live_database.migration_dsn) as owner_connection:
        seed_principal_authz(
            owner_connection,
            tenant_id=tenant_id,
            subject=subject,
            user_id=user_id,
            readable_object_id=readable_object_id,
            policy_id=policy_id,
        )
        owner_connection.commit()

    directory = PgPrincipalDirectory(database_dsn=live_database.app_dsn)
    principal = directory.principal_for_claims(verified_claims(tenant_id=tenant_id, subject=subject))
    membership = directory.tenant_membership(principal, tenant_id)

    assert principal.user_id == user_id
    assert membership.role_ids == {"knowledge-worker"}
    assert membership.group_ids == {"team-demo"}
    assert directory.readable_object_ids(
        tenant_id=tenant_id,
        user_id=principal.user_id,
        role_ids=membership.role_ids,
        group_ids=membership.group_ids,
    ) == {readable_object_id}
    assert directory.active_abac_policy_ids(tenant_id=tenant_id) == (policy_id,)


def test_principal_authz_store_enforces_rls_and_read_only_app_role(live_database: LiveDatabase) -> None:
    suffix = uuid4().hex
    tenant_a = f"tenant-a-{suffix}"
    tenant_b = f"tenant-b-{suffix}"
    user_a = f"user-a-{suffix}"
    user_b = f"user-b-{suffix}"

    with psycopg.connect(live_database.migration_dsn) as owner_connection:
        seed_principal_authz(
            owner_connection,
            tenant_id=tenant_a,
            subject=user_a,
            user_id=user_a,
            readable_object_id=f"doc-a-{suffix}",
            policy_id=f"policy-a-{suffix}",
        )
        seed_principal_authz(
            owner_connection,
            tenant_id=tenant_b,
            subject=user_b,
            user_id=user_b,
            readable_object_id=f"doc-b-{suffix}",
            policy_id=f"policy-b-{suffix}",
        )
        owner_connection.commit()

    with psycopg.connect(live_database.app_dsn) as app_connection:
        set_tenant(app_connection, tenant_a)
        rows = app_connection.execute(
            """
            SELECT tenant_id, user_id
            FROM collabio.tenant_principals
            WHERE user_id IN (%s, %s)
            ORDER BY user_id
            """,
            (user_a, user_b),
        ).fetchall()

        assert rows == [(tenant_a, user_a)]

        with pytest.raises(psycopg.errors.InsufficientPrivilege, match="permission denied"):
            app_connection.execute(
                """
                INSERT INTO collabio.tenant_principals (
                    tenant_id,
                    issuer,
                    subject,
                    user_id,
                    audit_chain_ref
                )
                VALUES (%s, %s, 'app-write', 'app-write', 'audit:app-write')
                """,
                (tenant_a, DEFAULT_JWT_ISSUER),
            )
