from __future__ import annotations

import os
import re
from typing import Any, Literal, Protocol

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, field_validator

NAMESPACED_REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")

PrincipalStatus = Literal["active", "disabled"]
MembershipStatus = Literal["active", "disabled", "suspended"]
RoleStatus = Literal["active", "disabled", "deprecated"]
GroupStatus = Literal["active", "disabled"]
AssignmentStatus = Literal["active", "revoked"]
AclSubjectType = Literal["user", "role", "group"]
AclPermission = Literal["read", "write", "admin"]
AbacEffect = Literal["allow", "deny"]
AbacStatus = Literal["active", "disabled"]


class ApprovedAuthzAdminCommand(BaseModel):
    approval_reference: str
    reason: str

    @field_validator("approval_reference")
    @classmethod
    def require_namespaced_approval_reference(cls, value: str) -> str:
        normalized = value.strip()
        if not NAMESPACED_REF_PATTERN.fullmatch(normalized):
            raise ValueError("approval_reference must be a namespaced reference")
        return normalized

    @field_validator("reason")
    @classmethod
    def require_reason(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("reason must not be empty")
        return normalized


class PrincipalUpsertCommand(ApprovedAuthzAdminCommand):
    issuer: str
    subject: str
    user_id: str
    display_name: str | None = None
    email: str | None = None
    status: PrincipalStatus = "active"

    @field_validator("issuer", "subject", "user_id")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized


class PrincipalMembershipUpsertCommand(ApprovedAuthzAdminCommand):
    issuer: str
    subject: str
    status: MembershipStatus = "active"

    @field_validator("issuer", "subject")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized


class RoleUpsertCommand(ApprovedAuthzAdminCommand):
    role_id: str
    display_name: str
    description: str | None = None
    status: RoleStatus = "active"
    system_role: bool = False

    @field_validator("role_id", "display_name")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized


class GroupUpsertCommand(ApprovedAuthzAdminCommand):
    group_id: str
    display_name: str
    description: str | None = None
    status: GroupStatus = "active"

    @field_validator("group_id", "display_name")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized


class PrincipalRoleAssignmentUpsertCommand(ApprovedAuthzAdminCommand):
    issuer: str
    subject: str
    role_id: str
    status: AssignmentStatus = "active"

    @field_validator("issuer", "subject", "role_id")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized


class PrincipalGroupMembershipUpsertCommand(ApprovedAuthzAdminCommand):
    issuer: str
    subject: str
    group_id: str
    status: AssignmentStatus = "active"

    @field_validator("issuer", "subject", "group_id")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized


class ObjectAclEntryUpsertCommand(ApprovedAuthzAdminCommand):
    object_id: str
    object_type: str
    acl_subject_type: AclSubjectType
    acl_subject_id: str
    permission: AclPermission
    acl_version: int = Field(ge=1)
    status: AssignmentStatus = "active"

    @field_validator("object_id", "object_type", "acl_subject_id")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized


class AbacPolicyBindingUpsertCommand(ApprovedAuthzAdminCommand):
    policy_id: str
    effect: AbacEffect
    principal_selector: dict[str, Any]
    resource_selector: dict[str, Any]
    condition: dict[str, Any] = Field(default_factory=dict)
    priority: int = 0
    status: AbacStatus = "active"

    @field_validator("policy_id")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("policy_id must not be empty")
        return normalized


class JwtReplayRetentionPurgeCommand(ApprovedAuthzAdminCommand):
    expires_before_epoch: int = Field(gt=0)


class AuthzMutationView(BaseModel):
    tenant_id: str
    resource_type: str
    resource_id: str
    status: str
    audit_chain_ref: str


class JwtReplayRetentionPurgeView(BaseModel):
    tenant_id: str
    deleted_count: int
    expires_before_epoch: int
    audit_chain_ref: str


class AuthzAdminStore(Protocol):
    def upsert_principal(
        self, *, tenant_id: str, command: PrincipalUpsertCommand, audit_chain_ref: str
    ) -> AuthzMutationView: ...

    def upsert_membership(
        self, *, tenant_id: str, command: PrincipalMembershipUpsertCommand, audit_chain_ref: str
    ) -> AuthzMutationView: ...

    def upsert_role(self, *, tenant_id: str, command: RoleUpsertCommand, audit_chain_ref: str) -> AuthzMutationView: ...

    def upsert_group(
        self, *, tenant_id: str, command: GroupUpsertCommand, audit_chain_ref: str
    ) -> AuthzMutationView: ...

    def upsert_role_assignment(
        self, *, tenant_id: str, command: PrincipalRoleAssignmentUpsertCommand, audit_chain_ref: str
    ) -> AuthzMutationView: ...

    def upsert_group_membership(
        self, *, tenant_id: str, command: PrincipalGroupMembershipUpsertCommand, audit_chain_ref: str
    ) -> AuthzMutationView: ...

    def upsert_object_acl_entry(
        self, *, tenant_id: str, command: ObjectAclEntryUpsertCommand, audit_chain_ref: str
    ) -> AuthzMutationView: ...

    def upsert_abac_policy_binding(
        self, *, tenant_id: str, command: AbacPolicyBindingUpsertCommand, audit_chain_ref: str
    ) -> AuthzMutationView: ...

    def purge_expired_jwt_replay_tokens(
        self, *, tenant_id: str, command: JwtReplayRetentionPurgeCommand, audit_chain_ref: str
    ) -> JwtReplayRetentionPurgeView: ...


class InMemoryAuthzAdminStore:
    def __init__(self) -> None:
        self.mutations: list[AuthzMutationView | JwtReplayRetentionPurgeView] = []

    def upsert_principal(
        self, *, tenant_id: str, command: PrincipalUpsertCommand, audit_chain_ref: str
    ) -> AuthzMutationView:
        return self._record(
            tenant_id=tenant_id,
            resource_type="tenant_principal",
            resource_id=f"{command.issuer}:{command.subject}",
            status=command.status,
            audit_chain_ref=audit_chain_ref,
        )

    def upsert_membership(
        self, *, tenant_id: str, command: PrincipalMembershipUpsertCommand, audit_chain_ref: str
    ) -> AuthzMutationView:
        return self._record(
            tenant_id=tenant_id,
            resource_type="tenant_principal_membership",
            resource_id=f"{command.issuer}:{command.subject}",
            status=command.status,
            audit_chain_ref=audit_chain_ref,
        )

    def upsert_role(self, *, tenant_id: str, command: RoleUpsertCommand, audit_chain_ref: str) -> AuthzMutationView:
        return self._record(
            tenant_id=tenant_id,
            resource_type="tenant_role",
            resource_id=command.role_id,
            status=command.status,
            audit_chain_ref=audit_chain_ref,
        )

    def upsert_group(self, *, tenant_id: str, command: GroupUpsertCommand, audit_chain_ref: str) -> AuthzMutationView:
        return self._record(
            tenant_id=tenant_id,
            resource_type="tenant_group",
            resource_id=command.group_id,
            status=command.status,
            audit_chain_ref=audit_chain_ref,
        )

    def upsert_role_assignment(
        self, *, tenant_id: str, command: PrincipalRoleAssignmentUpsertCommand, audit_chain_ref: str
    ) -> AuthzMutationView:
        return self._record(
            tenant_id=tenant_id,
            resource_type="tenant_principal_role_assignment",
            resource_id=f"{command.issuer}:{command.subject}:{command.role_id}",
            status=command.status,
            audit_chain_ref=audit_chain_ref,
        )

    def upsert_group_membership(
        self, *, tenant_id: str, command: PrincipalGroupMembershipUpsertCommand, audit_chain_ref: str
    ) -> AuthzMutationView:
        return self._record(
            tenant_id=tenant_id,
            resource_type="tenant_principal_group_membership",
            resource_id=f"{command.issuer}:{command.subject}:{command.group_id}",
            status=command.status,
            audit_chain_ref=audit_chain_ref,
        )

    def upsert_object_acl_entry(
        self, *, tenant_id: str, command: ObjectAclEntryUpsertCommand, audit_chain_ref: str
    ) -> AuthzMutationView:
        return self._record(
            tenant_id=tenant_id,
            resource_type="object_acl_entry",
            resource_id=(
                f"{command.object_type}:{command.object_id}:"
                f"{command.acl_subject_type}:{command.acl_subject_id}:{command.permission}:{command.acl_version}"
            ),
            status=command.status,
            audit_chain_ref=audit_chain_ref,
        )

    def upsert_abac_policy_binding(
        self, *, tenant_id: str, command: AbacPolicyBindingUpsertCommand, audit_chain_ref: str
    ) -> AuthzMutationView:
        return self._record(
            tenant_id=tenant_id,
            resource_type="abac_policy_binding",
            resource_id=command.policy_id,
            status=command.status,
            audit_chain_ref=audit_chain_ref,
        )

    def purge_expired_jwt_replay_tokens(
        self, *, tenant_id: str, command: JwtReplayRetentionPurgeCommand, audit_chain_ref: str
    ) -> JwtReplayRetentionPurgeView:
        view = JwtReplayRetentionPurgeView(
            tenant_id=tenant_id,
            deleted_count=0,
            expires_before_epoch=command.expires_before_epoch,
            audit_chain_ref=audit_chain_ref,
        )
        self.mutations.append(view)
        return view

    def _record(
        self,
        *,
        tenant_id: str,
        resource_type: str,
        resource_id: str,
        status: str,
        audit_chain_ref: str,
    ) -> AuthzMutationView:
        view = AuthzMutationView(
            tenant_id=tenant_id,
            resource_type=resource_type,
            resource_id=resource_id,
            status=status,
            audit_chain_ref=audit_chain_ref,
        )
        self.mutations.append(view)
        return view


class PgAuthzAdminStore:
    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    def upsert_principal(
        self, *, tenant_id: str, command: PrincipalUpsertCommand, audit_chain_ref: str
    ) -> AuthzMutationView:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            connection.execute(
                """
                INSERT INTO collabio.tenant_principals (
                    tenant_id,
                    issuer,
                    subject,
                    user_id,
                    display_name,
                    email,
                    status,
                    audit_chain_ref
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, issuer, subject)
                DO UPDATE SET
                    user_id = EXCLUDED.user_id,
                    display_name = EXCLUDED.display_name,
                    email = EXCLUDED.email,
                    status = EXCLUDED.status,
                    audit_chain_ref = EXCLUDED.audit_chain_ref
                """,
                (
                    tenant_id,
                    command.issuer,
                    command.subject,
                    command.user_id,
                    command.display_name,
                    command.email,
                    command.status,
                    audit_chain_ref,
                ),
            )
            connection.commit()
        return AuthzMutationView(
            tenant_id=tenant_id,
            resource_type="tenant_principal",
            resource_id=f"{command.issuer}:{command.subject}",
            status=command.status,
            audit_chain_ref=audit_chain_ref,
        )

    def upsert_membership(
        self, *, tenant_id: str, command: PrincipalMembershipUpsertCommand, audit_chain_ref: str
    ) -> AuthzMutationView:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            connection.execute(
                """
                INSERT INTO collabio.tenant_principal_memberships (
                    tenant_id,
                    issuer,
                    subject,
                    status,
                    disabled_at_utc,
                    audit_chain_ref
                )
                VALUES (
                    %s, %s, %s, %s,
                    CASE WHEN %s = 'active' THEN NULL ELSE now() END,
                    %s
                )
                ON CONFLICT (tenant_id, issuer, subject)
                DO UPDATE SET
                    status = EXCLUDED.status,
                    disabled_at_utc = EXCLUDED.disabled_at_utc,
                    audit_chain_ref = EXCLUDED.audit_chain_ref
                """,
                (
                    tenant_id,
                    command.issuer,
                    command.subject,
                    command.status,
                    command.status,
                    audit_chain_ref,
                ),
            )
            connection.commit()
        return AuthzMutationView(
            tenant_id=tenant_id,
            resource_type="tenant_principal_membership",
            resource_id=f"{command.issuer}:{command.subject}",
            status=command.status,
            audit_chain_ref=audit_chain_ref,
        )

    def upsert_role(self, *, tenant_id: str, command: RoleUpsertCommand, audit_chain_ref: str) -> AuthzMutationView:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            connection.execute(
                """
                INSERT INTO collabio.tenant_roles (
                    tenant_id,
                    role_id,
                    display_name,
                    description,
                    status,
                    system_role,
                    audit_chain_ref
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, role_id)
                DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    description = EXCLUDED.description,
                    status = EXCLUDED.status,
                    system_role = EXCLUDED.system_role,
                    audit_chain_ref = EXCLUDED.audit_chain_ref
                """,
                (
                    tenant_id,
                    command.role_id,
                    command.display_name,
                    command.description,
                    command.status,
                    command.system_role,
                    audit_chain_ref,
                ),
            )
            connection.commit()
        return AuthzMutationView(
            tenant_id=tenant_id,
            resource_type="tenant_role",
            resource_id=command.role_id,
            status=command.status,
            audit_chain_ref=audit_chain_ref,
        )

    def upsert_group(self, *, tenant_id: str, command: GroupUpsertCommand, audit_chain_ref: str) -> AuthzMutationView:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            connection.execute(
                """
                INSERT INTO collabio.tenant_groups (
                    tenant_id,
                    group_id,
                    display_name,
                    description,
                    status,
                    audit_chain_ref
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, group_id)
                DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    description = EXCLUDED.description,
                    status = EXCLUDED.status,
                    audit_chain_ref = EXCLUDED.audit_chain_ref
                """,
                (
                    tenant_id,
                    command.group_id,
                    command.display_name,
                    command.description,
                    command.status,
                    audit_chain_ref,
                ),
            )
            connection.commit()
        return AuthzMutationView(
            tenant_id=tenant_id,
            resource_type="tenant_group",
            resource_id=command.group_id,
            status=command.status,
            audit_chain_ref=audit_chain_ref,
        )

    def upsert_role_assignment(
        self, *, tenant_id: str, command: PrincipalRoleAssignmentUpsertCommand, audit_chain_ref: str
    ) -> AuthzMutationView:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            connection.execute(
                """
                INSERT INTO collabio.tenant_principal_role_assignments (
                    tenant_id,
                    issuer,
                    subject,
                    role_id,
                    status,
                    revoked_at_utc,
                    audit_chain_ref
                )
                VALUES (
                    %s, %s, %s, %s, %s,
                    CASE WHEN %s = 'revoked' THEN now() ELSE NULL END,
                    %s
                )
                ON CONFLICT (tenant_id, issuer, subject, role_id)
                DO UPDATE SET
                    status = EXCLUDED.status,
                    revoked_at_utc = EXCLUDED.revoked_at_utc,
                    audit_chain_ref = EXCLUDED.audit_chain_ref
                """,
                (
                    tenant_id,
                    command.issuer,
                    command.subject,
                    command.role_id,
                    command.status,
                    command.status,
                    audit_chain_ref,
                ),
            )
            connection.commit()
        return AuthzMutationView(
            tenant_id=tenant_id,
            resource_type="tenant_principal_role_assignment",
            resource_id=f"{command.issuer}:{command.subject}:{command.role_id}",
            status=command.status,
            audit_chain_ref=audit_chain_ref,
        )

    def upsert_group_membership(
        self, *, tenant_id: str, command: PrincipalGroupMembershipUpsertCommand, audit_chain_ref: str
    ) -> AuthzMutationView:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            connection.execute(
                """
                INSERT INTO collabio.tenant_principal_group_memberships (
                    tenant_id,
                    issuer,
                    subject,
                    group_id,
                    status,
                    revoked_at_utc,
                    audit_chain_ref
                )
                VALUES (
                    %s, %s, %s, %s, %s,
                    CASE WHEN %s = 'revoked' THEN now() ELSE NULL END,
                    %s
                )
                ON CONFLICT (tenant_id, issuer, subject, group_id)
                DO UPDATE SET
                    status = EXCLUDED.status,
                    revoked_at_utc = EXCLUDED.revoked_at_utc,
                    audit_chain_ref = EXCLUDED.audit_chain_ref
                """,
                (
                    tenant_id,
                    command.issuer,
                    command.subject,
                    command.group_id,
                    command.status,
                    command.status,
                    audit_chain_ref,
                ),
            )
            connection.commit()
        return AuthzMutationView(
            tenant_id=tenant_id,
            resource_type="tenant_principal_group_membership",
            resource_id=f"{command.issuer}:{command.subject}:{command.group_id}",
            status=command.status,
            audit_chain_ref=audit_chain_ref,
        )

    def upsert_object_acl_entry(
        self, *, tenant_id: str, command: ObjectAclEntryUpsertCommand, audit_chain_ref: str
    ) -> AuthzMutationView:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
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
                    status,
                    revoked_at_utc,
                    audit_chain_ref
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s,
                    CASE WHEN %s = 'revoked' THEN now() ELSE NULL END,
                    %s
                )
                ON CONFLICT (
                    tenant_id,
                    object_id,
                    object_type,
                    acl_subject_type,
                    acl_subject_id,
                    permission,
                    acl_version
                )
                DO UPDATE SET
                    status = EXCLUDED.status,
                    revoked_at_utc = EXCLUDED.revoked_at_utc,
                    audit_chain_ref = EXCLUDED.audit_chain_ref
                """,
                (
                    tenant_id,
                    command.object_id,
                    command.object_type,
                    command.acl_subject_type,
                    command.acl_subject_id,
                    command.permission,
                    command.acl_version,
                    command.status,
                    command.status,
                    audit_chain_ref,
                ),
            )
            connection.commit()
        return AuthzMutationView(
            tenant_id=tenant_id,
            resource_type="object_acl_entry",
            resource_id=(
                f"{command.object_type}:{command.object_id}:"
                f"{command.acl_subject_type}:{command.acl_subject_id}:{command.permission}:{command.acl_version}"
            ),
            status=command.status,
            audit_chain_ref=audit_chain_ref,
        )

    def upsert_abac_policy_binding(
        self, *, tenant_id: str, command: AbacPolicyBindingUpsertCommand, audit_chain_ref: str
    ) -> AuthzMutationView:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
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
                    status,
                    audit_chain_ref
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, policy_id)
                DO UPDATE SET
                    effect = EXCLUDED.effect,
                    principal_selector = EXCLUDED.principal_selector,
                    resource_selector = EXCLUDED.resource_selector,
                    condition = EXCLUDED.condition,
                    priority = EXCLUDED.priority,
                    status = EXCLUDED.status,
                    audit_chain_ref = EXCLUDED.audit_chain_ref
                """,
                (
                    tenant_id,
                    command.policy_id,
                    command.effect,
                    Jsonb(command.principal_selector),
                    Jsonb(command.resource_selector),
                    Jsonb(command.condition),
                    command.priority,
                    command.status,
                    audit_chain_ref,
                ),
            )
            connection.commit()
        return AuthzMutationView(
            tenant_id=tenant_id,
            resource_type="abac_policy_binding",
            resource_id=command.policy_id,
            status=command.status,
            audit_chain_ref=audit_chain_ref,
        )

    def purge_expired_jwt_replay_tokens(
        self, *, tenant_id: str, command: JwtReplayRetentionPurgeCommand, audit_chain_ref: str
    ) -> JwtReplayRetentionPurgeView:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            connection.execute(
                "SELECT set_config('app.retention_now_epoch', %s, true)",
                (str(command.expires_before_epoch),),
            )
            cursor = connection.execute(
                """
                DELETE FROM collabio.jwt_replay_tokens
                WHERE tenant_id = %s
                  AND expires_at_epoch <= %s
                """,
                (tenant_id, command.expires_before_epoch),
            )
            deleted_count = cursor.rowcount
            connection.commit()
        return JwtReplayRetentionPurgeView(
            tenant_id=tenant_id,
            deleted_count=deleted_count,
            expires_before_epoch=command.expires_before_epoch,
            audit_chain_ref=audit_chain_ref,
        )

    def _set_tenant(self, connection: psycopg.Connection[Any], tenant_id: str) -> None:
        connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))


def build_default_authz_admin_store() -> AuthzAdminStore:
    backend = os.getenv("SUITE_AUTHZ_ADMIN_STORE_BACKEND", "memory").strip().lower()
    if backend in {"memory", "in-memory", "in_memory"}:
        return InMemoryAuthzAdminStore()
    if backend in {"postgres", "postgresql", "pg"}:
        database_dsn = os.getenv("SUITE_AUTHZ_ADMIN_DATABASE_DSN")
        if not database_dsn:
            raise ValueError("PostgreSQL authz admin store requires SUITE_AUTHZ_ADMIN_DATABASE_DSN")
        return PgAuthzAdminStore(database_dsn=database_dsn)
    raise ValueError(f"Unsupported SUITE_AUTHZ_ADMIN_STORE_BACKEND: {backend}")
