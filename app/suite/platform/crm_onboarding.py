from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Protocol

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import UserContext
from suite.platform.crm_accounts import CRM_ACCOUNT_OBJECT_TYPE
from suite.platform.crm_activities import (
    CRM_ACTIVITY_OBJECT_TYPE,
    CRM_NOTE_OBJECT_TYPE,
    CrmActivityType,
)
from suite.platform.crm_contacts import CRM_CONTACT_OBJECT_TYPE

CRM_ONBOARDING_SCHEMA_VERSION = "crm_account_onboarding_receipt.v1"
CRM_ONBOARDING_ROLE_IDS = frozenset({"tenant-admin", "crm-manager", "crm-operator"})
NAMESPACED_REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")
SOURCE_SYSTEM_PATTERN = re.compile(r"^[a-z][a-z0-9_+.-]*$")


class CrmOnboardingConflict(ValueError):
    pass


class CrmAccountCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str = Field(min_length=1, max_length=200)
    account_number: str | None = Field(default=None, min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=300)


class CrmContactCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str = Field(min_length=1, max_length=200)
    contact_number: str | None = Field(default=None, min_length=1, max_length=100)
    display_name: str = Field(min_length=1, max_length=300)
    given_name: str | None = Field(default=None, min_length=1, max_length=150)
    family_name: str | None = Field(default=None, min_length=1, max_length=150)
    primary_email: str | None = Field(default=None, min_length=3, max_length=320)
    role_label: str | None = Field(default=None, min_length=1, max_length=200)


class CrmActivityCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str = Field(min_length=1, max_length=200)
    activity_number: str | None = Field(default=None, min_length=1, max_length=100)
    activity_type: CrmActivityType = CrmActivityType.FOLLOW_UP
    subject: str = Field(min_length=1, max_length=500)
    due_at_utc: datetime | None = None


class CrmNoteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str = Field(min_length=1, max_length=200)
    note_number: str | None = Field(default=None, min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=500)


class CrmAccountOnboardingCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mutation_reference: str = Field(min_length=3, max_length=300)
    account: CrmAccountCreate
    contact: CrmContactCreate
    activity: CrmActivityCreate
    note: CrmNoteCreate
    source_system: str = "native"

    @field_validator("mutation_reference")
    @classmethod
    def require_namespaced_mutation_reference(cls, value: str) -> str:
        normalized = value.strip()
        if not NAMESPACED_REF_PATTERN.fullmatch(normalized):
            raise ValueError("mutation_reference must be a namespaced reference")
        return normalized

    @field_validator("source_system")
    @classmethod
    def require_source_system(cls, value: str) -> str:
        normalized = value.strip()
        if not SOURCE_SYSTEM_PATTERN.fullmatch(normalized):
            raise ValueError("source_system must be lowercase and non-empty")
        return normalized

    @model_validator(mode="after")
    def require_unique_object_ids(self) -> CrmAccountOnboardingCommand:
        object_ids = {
            self.account.object_id,
            self.contact.object_id,
            self.activity.object_id,
            self.note.object_id,
        }
        if len(object_ids) != 4:
            raise ValueError("CRM onboarding object IDs must be unique")
        return self


class CrmAccountOnboardingReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    mutation_reference: str
    command_hash: str
    created_by: str
    acl_subject_id: str
    object_manifest: dict[str, str]
    acl_manifest: tuple[str, ...]
    audit_chain_ref: str
    receipt_hash: str
    created_at_utc: str
    schema_version: str = CRM_ONBOARDING_SCHEMA_VERSION


class CrmAccountOnboardingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = "crm_erp"
    required_feature_ids: tuple[str, ...] = (
        "crm_erp.crm.accounts",
        "crm_erp.crm.contacts",
        "crm_erp.crm.activities",
    )
    receipt: CrmAccountOnboardingReceipt
    acl_grant_count: int = 4
    idempotent_replay: bool
    atomic_transaction_committed: bool = True
    content_included: bool = False
    audit_event_id: str


class CrmAccountOnboardingStore(Protocol):
    def create(
        self,
        *,
        tenant_id: str,
        user_id: str,
        command: CrmAccountOnboardingCommand,
    ) -> tuple[CrmAccountOnboardingReceipt, bool]: ...


def stable_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def command_hash(command: CrmAccountOnboardingCommand, *, user_id: str) -> str:
    return stable_hash({"command": command.model_dump(mode="json"), "created_by": user_id})


def object_manifest(command: CrmAccountOnboardingCommand) -> dict[str, str]:
    return {
        CRM_ACCOUNT_OBJECT_TYPE: command.account.object_id,
        CRM_CONTACT_OBJECT_TYPE: command.contact.object_id,
        CRM_ACTIVITY_OBJECT_TYPE: command.activity.object_id,
        CRM_NOTE_OBJECT_TYPE: command.note.object_id,
    }


def acl_manifest(command: CrmAccountOnboardingCommand, user_id: str) -> tuple[str, ...]:
    return tuple(
        f"{object_type}:{object_id}:user:{user_id}:admin:1"
        for object_type, object_id in object_manifest(command).items()
    )


def build_receipt(
    *,
    tenant_id: str,
    user_id: str,
    command: CrmAccountOnboardingCommand,
    created_at_utc: str,
) -> CrmAccountOnboardingReceipt:
    digest = command_hash(command, user_id=user_id)
    objects = object_manifest(command)
    acls = acl_manifest(command, user_id)
    audit_chain_ref = f"audit:crm-onboarding:{digest.removeprefix('sha256:')}"
    receipt_hash = stable_hash(
        {
            "tenant_id": tenant_id,
            "mutation_reference": command.mutation_reference,
            "command_hash": digest,
            "created_by": user_id,
            "acl_subject_id": user_id,
            "object_manifest": objects,
            "acl_manifest": acls,
            "audit_chain_ref": audit_chain_ref,
            "schema_version": CRM_ONBOARDING_SCHEMA_VERSION,
        }
    )
    return CrmAccountOnboardingReceipt(
        tenant_id=tenant_id,
        mutation_reference=command.mutation_reference,
        command_hash=digest,
        created_by=user_id,
        acl_subject_id=user_id,
        object_manifest=objects,
        acl_manifest=acls,
        audit_chain_ref=audit_chain_ref,
        receipt_hash=receipt_hash,
        created_at_utc=created_at_utc,
    )


class InMemoryCrmAccountOnboardingStore:
    def __init__(self) -> None:
        self._receipts: dict[tuple[str, str], CrmAccountOnboardingReceipt] = {}

    def create(
        self,
        *,
        tenant_id: str,
        user_id: str,
        command: CrmAccountOnboardingCommand,
    ) -> tuple[CrmAccountOnboardingReceipt, bool]:
        key = (tenant_id, command.mutation_reference)
        existing = self._receipts.get(key)
        if existing is not None:
            if existing.command_hash != command_hash(command, user_id=user_id):
                raise CrmOnboardingConflict("mutation_reference already belongs to a different command")
            return existing, True
        receipt = build_receipt(
            tenant_id=tenant_id,
            user_id=user_id,
            command=command,
            created_at_utc=datetime.now().astimezone().isoformat(),
        )
        self._receipts[key] = receipt
        return receipt, False


class PgCrmAccountOnboardingStore:
    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    def create(
        self,
        *,
        tenant_id: str,
        user_id: str,
        command: CrmAccountOnboardingCommand,
    ) -> tuple[CrmAccountOnboardingReceipt, bool]:
        digest = command_hash(command, user_id=user_id)
        try:
            with psycopg.connect(self.database_dsn, row_factory=dict_row) as connection:
                connection.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"{tenant_id}:{command.mutation_reference}",),
                )
                existing = connection.execute(
                    """
                    SELECT tenant_id, mutation_reference, command_hash, created_by,
                           acl_subject_id, object_manifest, acl_manifest, audit_chain_ref,
                           receipt_hash, created_at_utc, schema_version
                    FROM crm.account_onboarding_receipts
                    WHERE tenant_id = %s AND mutation_reference = %s
                    """,
                    (tenant_id, command.mutation_reference),
                ).fetchone()
                if existing is not None:
                    if existing["command_hash"] != digest:
                        raise CrmOnboardingConflict("mutation_reference already belongs to a different command")
                    return self._receipt_from_row(existing), True

                provisional = build_receipt(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    command=command,
                    created_at_utc="pending",
                )
                self._insert_business_records(
                    connection=connection,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    command=command,
                    audit_chain_ref=provisional.audit_chain_ref,
                )
                self._insert_acls(
                    connection=connection,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    command=command,
                    audit_chain_ref=provisional.audit_chain_ref,
                )
                row = connection.execute(
                    """
                    INSERT INTO crm.account_onboarding_receipts (
                        tenant_id, mutation_reference, command_hash, created_by,
                        acl_subject_id, object_manifest, acl_manifest, audit_chain_ref, receipt_hash
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING tenant_id, mutation_reference, command_hash, created_by,
                              acl_subject_id, object_manifest, acl_manifest, audit_chain_ref,
                              receipt_hash, created_at_utc, schema_version
                    """,
                    (
                        tenant_id,
                        command.mutation_reference,
                        digest,
                        user_id,
                        user_id,
                        Jsonb(provisional.object_manifest),
                        Jsonb(list(provisional.acl_manifest)),
                        provisional.audit_chain_ref,
                        provisional.receipt_hash,
                    ),
                ).fetchone()
                if row is None:
                    raise RuntimeError("CRM onboarding receipt was not returned")
                return self._receipt_from_row(row), False
        except psycopg.errors.UniqueViolation as exc:
            raise CrmOnboardingConflict("one or more CRM object IDs or numbers already exist") from exc

    @staticmethod
    def _insert_business_records(
        *,
        connection: psycopg.Connection[dict[str, Any]],
        tenant_id: str,
        user_id: str,
        command: CrmAccountOnboardingCommand,
        audit_chain_ref: str,
    ) -> None:
        kms_key_ref = f"kms:{tenant_id}:crm"
        common = (tenant_id, user_id, user_id, kms_key_ref, audit_chain_ref, command.source_system)
        connection.execute(
            """
            INSERT INTO crm.accounts (
                tenant_id, object_id, owner_principal_id, created_by, kms_key_ref,
                audit_chain_ref, source_system, account_number, display_name
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                common[0],
                command.account.object_id,
                *common[1:],
                command.account.account_number,
                command.account.display_name,
            ),
        )
        connection.execute(
            """
            INSERT INTO crm.contacts (
                tenant_id, object_id, owner_principal_id, created_by, kms_key_ref,
                audit_chain_ref, source_system, account_object_id, contact_number,
                display_name, given_name, family_name, primary_email, role_label
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                common[0],
                command.contact.object_id,
                *common[1:],
                command.account.object_id,
                command.contact.contact_number,
                command.contact.display_name,
                command.contact.given_name,
                command.contact.family_name,
                command.contact.primary_email,
                command.contact.role_label,
            ),
        )
        connection.execute(
            """
            INSERT INTO crm.activities (
                tenant_id, object_id, owner_principal_id, created_by, kms_key_ref,
                audit_chain_ref, source_system, account_object_id, contact_object_id,
                activity_number, activity_type, subject, due_at_utc
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                common[0],
                command.activity.object_id,
                *common[1:],
                command.account.object_id,
                command.contact.object_id,
                command.activity.activity_number,
                command.activity.activity_type.value,
                command.activity.subject,
                command.activity.due_at_utc,
            ),
        )
        connection.execute(
            """
            INSERT INTO crm.notes (
                tenant_id, object_id, owner_principal_id, created_by, kms_key_ref,
                audit_chain_ref, source_system, account_object_id, contact_object_id,
                activity_object_id, note_number, title
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                common[0],
                command.note.object_id,
                *common[1:],
                command.account.object_id,
                command.contact.object_id,
                command.activity.object_id,
                command.note.note_number,
                command.note.title,
            ),
        )

    @staticmethod
    def _insert_acls(
        *,
        connection: psycopg.Connection[dict[str, Any]],
        tenant_id: str,
        user_id: str,
        command: CrmAccountOnboardingCommand,
        audit_chain_ref: str,
    ) -> None:
        for object_type, object_id in object_manifest(command).items():
            connection.execute(
                """
                INSERT INTO collabio.object_acl_entries (
                    tenant_id, object_id, object_type, acl_subject_type, acl_subject_id,
                    permission, acl_version, status, audit_chain_ref
                ) VALUES (%s, %s, %s, 'user', %s, 'admin', 1, 'active', %s)
                """,
                (tenant_id, object_id, object_type, user_id, audit_chain_ref),
            )

    @staticmethod
    def _receipt_from_row(row: Mapping[str, Any]) -> CrmAccountOnboardingReceipt:
        created_at = row["created_at_utc"]
        return CrmAccountOnboardingReceipt(
            tenant_id=str(row["tenant_id"]),
            mutation_reference=str(row["mutation_reference"]),
            command_hash=str(row["command_hash"]),
            created_by=str(row["created_by"]),
            acl_subject_id=str(row["acl_subject_id"]),
            object_manifest={str(key): str(value) for key, value in row["object_manifest"].items()},
            acl_manifest=tuple(str(value) for value in row["acl_manifest"]),
            audit_chain_ref=str(row["audit_chain_ref"]),
            receipt_hash=str(row["receipt_hash"]),
            created_at_utc=(created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at)),
            schema_version=str(row["schema_version"]),
        )


class CrmAccountOnboardingService:
    def __init__(self, *, store: CrmAccountOnboardingStore, audit_logger: InMemoryAuditLogger) -> None:
        self.store = store
        self.audit_logger = audit_logger

    def create(
        self,
        *,
        user_context: UserContext,
        command: CrmAccountOnboardingCommand,
    ) -> CrmAccountOnboardingResponse:
        if user_context.role_ids.isdisjoint(CRM_ONBOARDING_ROLE_IDS):
            raise PermissionError("CRM operator role required")
        receipt, replay = self.store.create(
            tenant_id=user_context.tenant_id,
            user_id=user_context.user_id,
            command=command,
        )
        event = self.audit_logger.record(
            user_context=user_context,
            event_type="crm.account.onboarding.replayed" if replay else "crm.account.onboarding.committed",
            source_object_ids=list(receipt.object_manifest.values()),
            metadata={
                "module_id": "crm_erp",
                "mutation_reference": receipt.mutation_reference,
                "command_hash": receipt.command_hash,
                "receipt_hash": receipt.receipt_hash,
                "acl_grant_count": len(receipt.acl_manifest),
                "atomic_transaction_committed": True,
                "idempotent_replay": replay,
                "result_contract": "metadata_only_crm_account_onboarding_receipt",
                "content_included": False,
            },
        )
        return CrmAccountOnboardingResponse(
            tenant_id=user_context.tenant_id,
            receipt=receipt,
            idempotent_replay=replay,
            audit_event_id=event.event_id,
        )


def build_default_crm_account_onboarding_store(
    environ: Mapping[str, str] | None = None,
) -> CrmAccountOnboardingStore:
    env = os.environ if environ is None else environ
    backend = env.get("SUITE_CRM_ONBOARDING_BACKEND", "memory").strip().lower()
    if backend in {"memory", "inmemory", "in-memory"}:
        return InMemoryCrmAccountOnboardingStore()
    if backend in {"postgres", "postgresql", "pg"}:
        database_dsn = env.get("SUITE_CRM_ONBOARDING_DSN") or env.get("SUITE_AUTHZ_ADMIN_DATABASE_DSN")
        if not database_dsn:
            raise ValueError(
                "PostgreSQL CRM onboarding requires SUITE_CRM_ONBOARDING_DSN or SUITE_AUTHZ_ADMIN_DATABASE_DSN"
            )
        return PgCrmAccountOnboardingStore(database_dsn=database_dsn)
    raise ValueError(f"Unsupported SUITE_CRM_ONBOARDING_BACKEND: {backend}")
