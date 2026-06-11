from __future__ import annotations

from typing import Any

import psycopg

from suite.platform.context import (
    PrincipalRecord,
    PrincipalResolutionError,
    TenantMembership,
    VerifiedJwtClaims,
)


class PgPrincipalDirectory:
    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise PrincipalResolutionError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    def principal_for_claims(self, claims: VerifiedJwtClaims) -> PrincipalRecord:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, claims.tenant_id)
            principal_row = connection.execute(
                """
                SELECT user_id
                FROM collabio.tenant_principals
                WHERE tenant_id = %s
                  AND issuer = %s
                  AND subject = %s
                  AND status = 'active'
                """,
                (claims.tenant_id, claims.issuer, claims.subject),
            ).fetchone()
            if principal_row is None:
                raise PrincipalResolutionError("Principal is not registered")

            membership = self._tenant_membership_for_subject(
                connection,
                tenant_id=claims.tenant_id,
                issuer=claims.issuer,
                subject=claims.subject,
            )
            role_ids = self._active_role_ids(
                connection,
                tenant_id=claims.tenant_id,
                issuer=claims.issuer,
                subject=claims.subject,
            )
            group_ids = self._active_group_ids(
                connection,
                tenant_id=claims.tenant_id,
                issuer=claims.issuer,
                subject=claims.subject,
            )

        return PrincipalRecord(
            issuer=claims.issuer,
            subject=claims.subject,
            user_id=str(principal_row[0]),
            memberships=[
                TenantMembership(
                    tenant_id=membership.tenant_id,
                    role_ids=role_ids,
                    group_ids=group_ids,
                    active=membership.active,
                )
            ],
        )

    def tenant_membership(self, principal: PrincipalRecord, tenant_id: str) -> TenantMembership:
        for membership in principal.memberships:
            if membership.tenant_id == tenant_id and membership.active:
                return membership
        raise PrincipalResolutionError("Principal is not an active member of the requested tenant")

    def readable_object_ids(self, *, tenant_id: str, user_id: str, role_ids: set[str], group_ids: set[str]) -> set[str]:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            rows = connection.execute(
                """
                SELECT DISTINCT object_id
                FROM collabio.object_acl_entries
                WHERE tenant_id = %s
                  AND status = 'active'
                  AND permission IN ('read', 'admin')
                  AND (
                    (acl_subject_type = 'user' AND acl_subject_id = %s)
                    OR (acl_subject_type = 'role' AND acl_subject_id = ANY(%s::text[]))
                    OR (acl_subject_type = 'group' AND acl_subject_id = ANY(%s::text[]))
                  )
                ORDER BY object_id
                """,
                (tenant_id, user_id, sorted(role_ids), sorted(group_ids)),
            ).fetchall()
        return {str(row[0]) for row in rows}

    def active_abac_policy_ids(self, *, tenant_id: str) -> tuple[str, ...]:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            rows = connection.execute(
                """
                SELECT policy_id
                FROM collabio.abac_policy_bindings
                WHERE tenant_id = %s
                  AND status = 'active'
                ORDER BY priority DESC, policy_id
                """,
                (tenant_id,),
            ).fetchall()
        return tuple(str(row[0]) for row in rows)

    def _tenant_membership_for_subject(
        self,
        connection: psycopg.Connection[Any],
        *,
        tenant_id: str,
        issuer: str,
        subject: str,
    ) -> TenantMembership:
        membership_row = connection.execute(
            """
            SELECT status
            FROM collabio.tenant_principal_memberships
            WHERE tenant_id = %s
              AND issuer = %s
              AND subject = %s
              AND status = 'active'
            """,
            (tenant_id, issuer, subject),
        ).fetchone()
        if membership_row is None:
            raise PrincipalResolutionError("Principal is not an active member of the requested tenant")
        return TenantMembership(tenant_id=tenant_id, active=True)

    def _active_role_ids(
        self,
        connection: psycopg.Connection[Any],
        *,
        tenant_id: str,
        issuer: str,
        subject: str,
    ) -> set[str]:
        rows = connection.execute(
            """
            SELECT assignment.role_id
            FROM collabio.tenant_principal_role_assignments AS assignment
            JOIN collabio.tenant_roles AS role
              ON role.tenant_id = assignment.tenant_id
             AND role.role_id = assignment.role_id
            WHERE assignment.tenant_id = %s
              AND assignment.issuer = %s
              AND assignment.subject = %s
              AND assignment.status = 'active'
              AND role.status = 'active'
            ORDER BY assignment.role_id
            """,
            (tenant_id, issuer, subject),
        ).fetchall()
        return {str(row[0]) for row in rows}

    def _active_group_ids(
        self,
        connection: psycopg.Connection[Any],
        *,
        tenant_id: str,
        issuer: str,
        subject: str,
    ) -> set[str]:
        rows = connection.execute(
            """
            SELECT membership.group_id
            FROM collabio.tenant_principal_group_memberships AS membership
            JOIN collabio.tenant_groups AS tenant_group
              ON tenant_group.tenant_id = membership.tenant_id
             AND tenant_group.group_id = membership.group_id
            WHERE membership.tenant_id = %s
              AND membership.issuer = %s
              AND membership.subject = %s
              AND membership.status = 'active'
              AND tenant_group.status = 'active'
            ORDER BY membership.group_id
            """,
            (tenant_id, issuer, subject),
        ).fetchall()
        return {str(row[0]) for row in rows}

    def _set_tenant(self, connection: psycopg.Connection[Any], tenant_id: str) -> None:
        connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))
