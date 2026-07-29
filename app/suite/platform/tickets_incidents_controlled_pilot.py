from __future__ import annotations

import os
import re
from collections.abc import Iterable, Mapping
from datetime import datetime
from enum import StrEnum
from typing import Any, ClassVar, Protocol, Self

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.ai_control_plane.models import UserContext
from suite.persistence.migration_catalog import MigrationManifestEntry
from suite.platform.modules import InMemoryModuleRegistry, ModuleStatus, PgModuleRegistry, TenantModuleState
from suite.platform.tickets_incidents_activation_dry_run_execution_approval_record import (
    TicketsIncidentsActivationDryRunExecutionApprovalRecordResponse,
    TicketsIncidentsActivationDryRunExecutionApprovalRecordStore,
)
from suite.platform.tickets_incidents_module import (
    TICKETS_AI_ASSIST_FEATURE_ID,
    TICKETS_COMPLIANCE_EVIDENCE_FEATURE_ID,
    TICKETS_EVENTS_READ_FEATURE_ID,
    TICKETS_EVENTS_WRITE_FEATURE_ID,
    TICKETS_INCIDENTS_CONTINUITY_DOMAIN,
    TICKETS_INCIDENTS_MODULE_ID,
    TICKETS_ITEMS_READ_FEATURE_ID,
    TICKETS_ITEMS_WRITE_FEATURE_ID,
    TICKETS_RAG_INDEXING_FEATURE_ID,
    build_default_tickets_incidents_subfeature_registry,
)

SCHEMA_VERSION = "tickets_incidents_controlled_pilot_receipt.v1"
ADMISSION_ENDPOINT = "/v1/platform/modules/families/tickets-incidents/controlled-pilot/admission"
ENABLEMENT_ENDPOINT = "/v1/platform/modules/families/tickets-incidents/controlled-pilot/enablement"
ADMISSION_CONFIRMATION_STATEMENT = (
    "I explicitly approve installation and disabled tenant provisioning of the Tickets & Incidents "
    "controlled pilot. This does not enable business APIs, workers, AI, RAG, "
    "the compliance evidence feature, or external actions."
)
ENABLEMENT_CONFIRMATION_STATEMENT = (
    "I explicitly approve enabling exactly the four Tickets & Incidents item and event read/write features "
    "for this tenant. Workers, AI, RAG, the compliance evidence feature, destructive actions, "
    "and external actions remain disabled."
)
ZERO_HASH = "sha256:" + ("0" * 64)
SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")


class TicketsIncidentsPilotReceiptType(StrEnum):
    ADMISSION = "admission"
    ENABLEMENT_AUTHORIZATION = "enablement_authorization"
    ENABLEMENT_COMPLETED = "enablement_completed"


def controlled_pilot_enabled_features() -> dict[str, bool]:
    return {
        TICKETS_ITEMS_READ_FEATURE_ID: True,
        TICKETS_ITEMS_WRITE_FEATURE_ID: True,
        TICKETS_EVENTS_READ_FEATURE_ID: True,
        TICKETS_EVENTS_WRITE_FEATURE_ID: True,
        TICKETS_COMPLIANCE_EVIDENCE_FEATURE_ID: False,
        TICKETS_RAG_INDEXING_FEATURE_ID: False,
        TICKETS_AI_ASSIST_FEATURE_ID: False,
    }


def controlled_pilot_disabled_features() -> dict[str, bool]:
    return {feature_id: False for feature_id in controlled_pilot_enabled_features()}


class _TicketsIncidentsControlledPilotCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation_statement: ClassVar[str]

    approval_boundary_evidence_hash: str
    approval_record_evidence_hash: str
    tickets_restore_drill_evidence_hash: str
    policy_snapshot_hash: str
    feature_manifest_hash: str
    idempotency_key_ref: str
    change_request_ref: str
    human_confirmation_reference: str
    human_confirmation_statement: str
    audit_chain_ref: str
    changed_at_utc: datetime
    execution_requested: bool = True
    content_payload_included: bool = False
    destructive_actions_requested: bool = False
    external_side_effect_requested: bool = False
    worker_activation_requested: bool = False
    ai_or_rag_activation_requested: bool = False
    compliance_feature_activation_requested: bool = False

    @field_validator(
        "approval_boundary_evidence_hash",
        "approval_record_evidence_hash",
        "tickets_restore_drill_evidence_hash",
        "policy_snapshot_hash",
        "feature_manifest_hash",
    )
    @classmethod
    def require_hash(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("controlled pilot hashes must be sha256 references")
        return value

    @field_validator(
        "idempotency_key_ref",
        "change_request_ref",
        "human_confirmation_reference",
        "audit_chain_ref",
    )
    @classmethod
    def require_ref(cls, value: str) -> str:
        if not REF_PATTERN.fullmatch(value.strip()):
            raise ValueError("controlled pilot references must use typed prefixes")
        return value.strip()

    @field_validator("human_confirmation_statement")
    @classmethod
    def require_exact_confirmation(cls, value: str) -> str:
        if value.strip() != cls.confirmation_statement:
            raise ValueError("exact controlled pilot human confirmation statement required")
        return value.strip()

    @field_validator("changed_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("changed_at_utc must include a timezone")
        return value

    @model_validator(mode="after")
    def require_closed_high_risk_surfaces(self) -> Self:
        if not self.execution_requested:
            raise ValueError("controlled pilot execution must be explicitly requested")
        if (
            self.content_payload_included
            or self.destructive_actions_requested
            or self.external_side_effect_requested
            or self.worker_activation_requested
            or self.ai_or_rag_activation_requested
            or self.compliance_feature_activation_requested
        ):
            raise ValueError("controlled pilot command requests a forbidden high-risk surface")
        return self


class TicketsIncidentsControlledPilotAdmissionCommand(_TicketsIncidentsControlledPilotCommand):
    confirmation_statement: ClassVar[str] = ADMISSION_CONFIRMATION_STATEMENT
    admission_requested: bool = True
    tickets_business_api_activation_requested: bool = False

    @model_validator(mode="after")
    def require_admission_only(self) -> Self:
        if not self.admission_requested or self.tickets_business_api_activation_requested:
            raise ValueError("admission may only install and provision the module disabled")
        return self


class TicketsIncidentsControlledPilotEnablementCommand(_TicketsIncidentsControlledPilotCommand):
    confirmation_statement: ClassVar[str] = ENABLEMENT_CONFIRMATION_STATEMENT
    enablement_requested: bool = True
    tickets_business_api_activation_requested: bool = True

    @model_validator(mode="after")
    def require_explicit_business_enablement(self) -> Self:
        if not self.enablement_requested or not self.tickets_business_api_activation_requested:
            raise ValueError("enablement must explicitly request the Tickets business API")
        return self


class TicketsIncidentsControlledPilotReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    tenant_id: str
    module_id: str = TICKETS_INCIDENTS_MODULE_ID
    endpoint: str
    continuity_domain: str = TICKETS_INCIDENTS_CONTINUITY_DOMAIN
    receipt_type: TicketsIncidentsPilotReceiptType
    approval_boundary_evidence_hash: str
    approval_record_evidence_hash: str
    tickets_restore_drill_evidence_hash: str
    command_hash: str
    idempotency_key_hash: str
    confirmation_statement_hash: str
    policy_snapshot_hash: str
    feature_manifest_hash: str
    module_status: ModuleStatus
    enabled_features: dict[str, bool]
    changed_by: str
    changed_at_utc: datetime
    audit_chain_ref: str
    admission_receipt_evidence_hash: str = ZERO_HASH
    authorization_receipt_evidence_hash: str = ZERO_HASH
    explicit_human_confirmation_present: bool = True
    catalog_installed: bool = True
    tenant_provisioned: bool = True
    tickets_business_api_allowed: bool
    worker_activation_allowed: bool = False
    ai_or_rag_allowed: bool = False
    compliance_feature_allowed: bool = False
    content_included: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False
    evidence_hash: str
    next_action: str

    @field_validator(
        "approval_boundary_evidence_hash",
        "approval_record_evidence_hash",
        "tickets_restore_drill_evidence_hash",
        "command_hash",
        "idempotency_key_hash",
        "confirmation_statement_hash",
        "policy_snapshot_hash",
        "feature_manifest_hash",
        "admission_receipt_evidence_hash",
        "authorization_receipt_evidence_hash",
        "evidence_hash",
    )
    @classmethod
    def require_hash(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("controlled pilot receipt hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_fail_closed_receipt(self) -> Self:
        enabled = controlled_pilot_enabled_features()
        disabled = controlled_pilot_disabled_features()
        if self.receipt_type in {
            TicketsIncidentsPilotReceiptType.ADMISSION,
            TicketsIncidentsPilotReceiptType.ENABLEMENT_AUTHORIZATION,
        }:
            if self.module_status != ModuleStatus.DISABLED or self.enabled_features != disabled:
                raise ValueError("pre-enablement receipts must preserve a disabled tenant module")
            if self.tickets_business_api_allowed:
                raise ValueError("pre-enablement receipt cannot allow the Tickets business API")
        if self.receipt_type == TicketsIncidentsPilotReceiptType.ENABLEMENT_COMPLETED:
            if self.module_status != ModuleStatus.ENABLED or self.enabled_features != enabled:
                raise ValueError("completed enablement must open exactly four Tickets read/write features")
            if not self.tickets_business_api_allowed:
                raise ValueError("completed enablement must report the Tickets business API as allowed")
            if (
                self.admission_receipt_evidence_hash == ZERO_HASH
                or self.authorization_receipt_evidence_hash == ZERO_HASH
            ):
                raise ValueError("completed enablement requires admission and authorization receipts")
        if (
            not self.explicit_human_confirmation_present
            or not self.catalog_installed
            or not self.tenant_provisioned
            or self.worker_activation_allowed
            or self.ai_or_rag_allowed
            or self.compliance_feature_allowed
            or self.content_included
            or self.destructive_actions_allowed
            or self.external_side_effect_allowed
        ):
            raise ValueError("controlled pilot receipt violates the closed high-risk surface contract")
        return self


class TicketsIncidentsControlledPilotReceiptStore(Protocol):
    def append(self, receipt: TicketsIncidentsControlledPilotReceipt) -> TicketsIncidentsControlledPilotReceipt: ...

    def for_idempotency(
        self,
        *,
        tenant_id: str,
        receipt_type: TicketsIncidentsPilotReceiptType,
        idempotency_key_hash: str,
    ) -> TicketsIncidentsControlledPilotReceipt | None: ...

    def latest_for_type(
        self, *, tenant_id: str, receipt_type: TicketsIncidentsPilotReceiptType
    ) -> TicketsIncidentsControlledPilotReceipt | None: ...


class InMemoryTicketsIncidentsControlledPilotReceiptStore:
    def __init__(self, receipts: Iterable[TicketsIncidentsControlledPilotReceipt] = ()) -> None:
        self._receipts: list[TicketsIncidentsControlledPilotReceipt] = []
        for receipt in receipts:
            self.append(receipt)

    def append(self, receipt: TicketsIncidentsControlledPilotReceipt) -> TicketsIncidentsControlledPilotReceipt:
        existing = self.for_idempotency(
            tenant_id=receipt.tenant_id,
            receipt_type=receipt.receipt_type,
            idempotency_key_hash=receipt.idempotency_key_hash,
        )
        if existing is not None:
            return existing
        self._receipts.append(receipt)
        return receipt

    def for_idempotency(
        self,
        *,
        tenant_id: str,
        receipt_type: TicketsIncidentsPilotReceiptType,
        idempotency_key_hash: str,
    ) -> TicketsIncidentsControlledPilotReceipt | None:
        return next(
            (
                receipt
                for receipt in reversed(self._receipts)
                if receipt.tenant_id == tenant_id
                and receipt.receipt_type == receipt_type
                and receipt.idempotency_key_hash == idempotency_key_hash
            ),
            None,
        )

    def latest_for_type(
        self, *, tenant_id: str, receipt_type: TicketsIncidentsPilotReceiptType
    ) -> TicketsIncidentsControlledPilotReceipt | None:
        return next(
            (
                receipt
                for receipt in reversed(self._receipts)
                if receipt.tenant_id == tenant_id and receipt.receipt_type == receipt_type
            ),
            None,
        )


class PgTicketsIncidentsControlledPilotReceiptStore:
    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    @staticmethod
    def _set_tenant(connection: psycopg.Connection[Any], tenant_id: str) -> None:
        connection.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))

    def append(self, receipt: TicketsIncidentsControlledPilotReceipt) -> TicketsIncidentsControlledPilotReceipt:
        with psycopg.connect(self.database_dsn) as connection, connection.transaction():
            self._set_tenant(connection, receipt.tenant_id)
            existing = connection.execute(
                """
                SELECT receipt
                FROM tickets.controlled_pilot_receipts
                WHERE tenant_id = %s AND receipt_type = %s AND idempotency_key_hash = %s
                """,
                (receipt.tenant_id, receipt.receipt_type.value, receipt.idempotency_key_hash),
            ).fetchone()
            if existing is not None:
                return TicketsIncidentsControlledPilotReceipt.model_validate(existing[0])
            try:
                connection.execute(
                    """
                    INSERT INTO tickets.controlled_pilot_receipts (
                        tenant_id, receipt_type, approval_boundary_evidence_hash,
                        approval_record_evidence_hash, tickets_restore_drill_evidence_hash,
                        command_hash, idempotency_key_hash, policy_snapshot_hash,
                        feature_manifest_hash, module_status, enabled_features, changed_by,
                        changed_at_utc, audit_chain_ref, receipt, evidence_hash
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        receipt.tenant_id,
                        receipt.receipt_type.value,
                        receipt.approval_boundary_evidence_hash,
                        receipt.approval_record_evidence_hash,
                        receipt.tickets_restore_drill_evidence_hash,
                        receipt.command_hash,
                        receipt.idempotency_key_hash,
                        receipt.policy_snapshot_hash,
                        receipt.feature_manifest_hash,
                        receipt.module_status.value,
                        Jsonb(receipt.enabled_features),
                        receipt.changed_by,
                        receipt.changed_at_utc,
                        receipt.audit_chain_ref,
                        Jsonb(receipt.model_dump(mode="json")),
                        receipt.evidence_hash,
                    ),
                )
            except psycopg.errors.UniqueViolation as exc:
                raise ValueError("controlled pilot receipt already exists") from exc
        return receipt

    def for_idempotency(
        self,
        *,
        tenant_id: str,
        receipt_type: TicketsIncidentsPilotReceiptType,
        idempotency_key_hash: str,
    ) -> TicketsIncidentsControlledPilotReceipt | None:
        return self._one(
            tenant_id=tenant_id,
            where_sql="receipt_type = %s AND idempotency_key_hash = %s",
            parameters=(receipt_type.value, idempotency_key_hash),
        )

    def latest_for_type(
        self, *, tenant_id: str, receipt_type: TicketsIncidentsPilotReceiptType
    ) -> TicketsIncidentsControlledPilotReceipt | None:
        return self._one(
            tenant_id=tenant_id,
            where_sql="receipt_type = %s",
            parameters=(receipt_type.value,),
        )

    def _one(
        self, *, tenant_id: str, where_sql: str, parameters: tuple[str, ...]
    ) -> TicketsIncidentsControlledPilotReceipt | None:
        with psycopg.connect(self.database_dsn) as connection, connection.transaction():
            self._set_tenant(connection, tenant_id)
            row = connection.execute(
                f"""
                SELECT receipt
                FROM tickets.controlled_pilot_receipts
                WHERE tenant_id = %s AND {where_sql}
                ORDER BY created_at_utc DESC
                LIMIT 1
                """,  # nosec B608: where_sql is selected only by private callers above
                (tenant_id, *parameters),
            ).fetchone()
        if row is None:
            return None
        return TicketsIncidentsControlledPilotReceipt.model_validate(row[0])


def build_default_tickets_incidents_controlled_pilot_receipt_store(
    environ: Mapping[str, str] | None = None,
) -> TicketsIncidentsControlledPilotReceiptStore:
    env = os.environ if environ is None else environ
    backend = env.get("SUITE_TICKETS_PILOT_RECEIPT_BACKEND", "memory").strip().lower()
    if backend in {"memory", "inmemory", "in-memory"}:
        return InMemoryTicketsIncidentsControlledPilotReceiptStore()
    if backend in {"postgres", "postgresql", "pg"}:
        database_dsn = env.get("SUITE_TICKETS_PILOT_RECEIPT_DSN") or env.get("SUITE_DATABASE_DSN")
        if not database_dsn:
            raise ValueError(
                "PostgreSQL Tickets pilot receipt store requires SUITE_TICKETS_PILOT_RECEIPT_DSN or SUITE_DATABASE_DSN"
            )
        return PgTicketsIncidentsControlledPilotReceiptStore(database_dsn=database_dsn)
    raise ValueError(f"Unsupported SUITE_TICKETS_PILOT_RECEIPT_BACKEND: {backend}")


class TicketsIncidentsControlledPilotService:
    def __init__(
        self,
        *,
        module_registry: InMemoryModuleRegistry | PgModuleRegistry,
        migration_manifest_entries: Iterable[MigrationManifestEntry],
        approval_record_store: TicketsIncidentsActivationDryRunExecutionApprovalRecordStore,
        receipt_store: TicketsIncidentsControlledPilotReceiptStore,
    ) -> None:
        self.module_registry = module_registry
        self.migration_manifest_entries = tuple(migration_manifest_entries)
        self.approval_record_store = approval_record_store
        self.receipt_store = receipt_store

    def admit(
        self,
        *,
        user_context: UserContext,
        command: TicketsIncidentsControlledPilotAdmissionCommand,
    ) -> TicketsIncidentsControlledPilotReceipt:
        self._require_tenant_admin(user_context)
        approval = self._require_approval(user_context=user_context, command=command)
        command_hash, idempotency_hash = self._command_hashes(
            tenant_id=user_context.tenant_id,
            receipt_type=TicketsIncidentsPilotReceiptType.ADMISSION,
            command=command,
        )
        existing_receipt = self.receipt_store.for_idempotency(
            tenant_id=user_context.tenant_id,
            receipt_type=TicketsIncidentsPilotReceiptType.ADMISSION,
            idempotency_key_hash=idempotency_hash,
        )
        if existing_receipt is not None:
            return existing_receipt

        catalog = self.module_registry.get_catalog_entry(TICKETS_INCIDENTS_MODULE_ID)
        self.module_registry.install_catalog_module_for_controlled_pilot(
            tenant_id=user_context.tenant_id,
            module_id=TICKETS_INCIDENTS_MODULE_ID,
            expected_manifest_hash=catalog.manifest_hash,
            approval_evidence_hash=approval.evidence_hash,
            installed_at_utc=command.changed_at_utc,
        )
        state = self.module_registry.get_tenant_module_or_none(
            tenant_id=user_context.tenant_id,
            module_id=TICKETS_INCIDENTS_MODULE_ID,
        )
        if state is None:
            state = self.module_registry.provision_tenant_module(
                tenant_id=user_context.tenant_id,
                module_id=TICKETS_INCIDENTS_MODULE_ID,
                policy_snapshot_hash=command.policy_snapshot_hash,
                changed_by=user_context.user_id,
                audit_chain_ref=command.audit_chain_ref,
                enabled_features=controlled_pilot_disabled_features(),
                migration_manifest_entries=self.migration_manifest_entries,
                changed_at_utc=command.changed_at_utc,
            )
        else:
            self._require_recoverable_state(
                state=state,
                expected_status=ModuleStatus.DISABLED,
                enabled_features=controlled_pilot_disabled_features(),
                policy_snapshot_hash=command.policy_snapshot_hash,
                audit_chain_ref=command.audit_chain_ref,
            )
        receipt = self._receipt(
            user_context=user_context,
            command=command,
            approval=approval,
            receipt_type=TicketsIncidentsPilotReceiptType.ADMISSION,
            command_hash=command_hash,
            idempotency_hash=idempotency_hash,
            state=state,
            next_action="confirm_controlled_tickets_incidents_pilot_enablement_separately",
        )
        return self.receipt_store.append(receipt)

    def enable(
        self,
        *,
        user_context: UserContext,
        command: TicketsIncidentsControlledPilotEnablementCommand,
    ) -> TicketsIncidentsControlledPilotReceipt:
        self._require_tenant_admin(user_context)
        approval = self._require_approval(user_context=user_context, command=command)
        admission = self.receipt_store.latest_for_type(
            tenant_id=user_context.tenant_id,
            receipt_type=TicketsIncidentsPilotReceiptType.ADMISSION,
        )
        if admission is None or admission.approval_record_evidence_hash != approval.evidence_hash:
            raise ValueError("matching controlled pilot admission receipt is required")
        command_hash, idempotency_hash = self._command_hashes(
            tenant_id=user_context.tenant_id,
            receipt_type=TicketsIncidentsPilotReceiptType.ENABLEMENT_COMPLETED,
            command=command,
        )
        completed = self.receipt_store.for_idempotency(
            tenant_id=user_context.tenant_id,
            receipt_type=TicketsIncidentsPilotReceiptType.ENABLEMENT_COMPLETED,
            idempotency_key_hash=idempotency_hash,
        )
        if completed is not None:
            return completed

        state = self.module_registry.get_tenant_module(user_context.tenant_id, TICKETS_INCIDENTS_MODULE_ID)
        authorization = self.receipt_store.for_idempotency(
            tenant_id=user_context.tenant_id,
            receipt_type=TicketsIncidentsPilotReceiptType.ENABLEMENT_AUTHORIZATION,
            idempotency_key_hash=idempotency_hash,
        )
        if authorization is None:
            if state.status != ModuleStatus.DISABLED or state.enabled_features != controlled_pilot_disabled_features():
                raise ValueError("Tickets pilot must be disabled before enablement authorization")
            authorization = self.receipt_store.append(
                self._receipt(
                    user_context=user_context,
                    command=command,
                    approval=approval,
                    receipt_type=TicketsIncidentsPilotReceiptType.ENABLEMENT_AUTHORIZATION,
                    command_hash=command_hash,
                    idempotency_hash=idempotency_hash,
                    state=state,
                    admission_receipt_hash=admission.evidence_hash,
                    next_action="enable_exact_controlled_tickets_incidents_feature_set",
                )
            )

        if state.status == ModuleStatus.DISABLED:
            state = self.module_registry.enable_tenant_module(
                tenant_id=user_context.tenant_id,
                module_id=TICKETS_INCIDENTS_MODULE_ID,
                policy_snapshot_hash=command.policy_snapshot_hash,
                changed_by=user_context.user_id,
                audit_chain_ref=command.audit_chain_ref,
                enabled_features=controlled_pilot_enabled_features(),
                changed_at_utc=command.changed_at_utc,
            )
        else:
            self._require_recoverable_state(
                state=state,
                expected_status=ModuleStatus.ENABLED,
                enabled_features=controlled_pilot_enabled_features(),
                policy_snapshot_hash=command.policy_snapshot_hash,
                audit_chain_ref=command.audit_chain_ref,
            )
        receipt = self._receipt(
            user_context=user_context,
            command=command,
            approval=approval,
            receipt_type=TicketsIncidentsPilotReceiptType.ENABLEMENT_COMPLETED,
            command_hash=command_hash,
            idempotency_hash=idempotency_hash,
            state=state,
            admission_receipt_hash=admission.evidence_hash,
            authorization_receipt_hash=authorization.evidence_hash,
            next_action="run_tickets_incidents_productive_vertical_slice_pilot_evidence",
        )
        return self.receipt_store.append(receipt)

    @staticmethod
    def _require_tenant_admin(user_context: UserContext) -> None:
        if user_context.role_ids.isdisjoint({"tenant-admin", "tenant_admin"}):
            raise PermissionError("tenant_admin role required for controlled Tickets pilot")

    def _require_approval(
        self,
        *,
        user_context: UserContext,
        command: _TicketsIncidentsControlledPilotCommand,
    ) -> TicketsIncidentsActivationDryRunExecutionApprovalRecordResponse:
        approval = self.approval_record_store.latest_for_boundary(
            tenant_id=user_context.tenant_id,
            approval_boundary_evidence_hash=command.approval_boundary_evidence_hash,
        )
        if approval is None or not approval.explicit_human_execution_approval_present:
            raise ValueError("persisted explicit Tickets execution approval is required")
        if approval.evidence_hash != command.approval_record_evidence_hash:
            raise ValueError("Tickets approval record evidence hash mismatch")
        if approval.tickets_restore_drill_evidence_hash != command.tickets_restore_drill_evidence_hash:
            raise ValueError("Tickets restore drill evidence hash mismatch")
        manifest = build_default_tickets_incidents_subfeature_registry()
        if manifest.manifest_hash != command.feature_manifest_hash:
            raise ValueError("Tickets feature manifest hash mismatch")
        return approval

    @staticmethod
    def _command_hashes(
        *,
        tenant_id: str,
        receipt_type: TicketsIncidentsPilotReceiptType,
        command: _TicketsIncidentsControlledPilotCommand,
    ) -> tuple[str, str]:
        command_hash = stable_hash(
            canonical_json(
                {
                    **command.model_dump(mode="json", exclude={"human_confirmation_statement"}),
                    "confirmation_statement_hash": stable_hash(command.human_confirmation_statement),
                }
            )
        )
        idempotency_hash = stable_hash(
            canonical_json(
                {
                    "tenant_id": tenant_id,
                    "receipt_type": receipt_type.value,
                    "idempotency_key_ref": command.idempotency_key_ref,
                }
            )
        )
        return command_hash, idempotency_hash

    @staticmethod
    def _require_recoverable_state(
        *,
        state: TenantModuleState,
        expected_status: ModuleStatus,
        enabled_features: dict[str, bool],
        policy_snapshot_hash: str,
        audit_chain_ref: str,
    ) -> None:
        if (
            state.status != expected_status
            or state.enabled_features != enabled_features
            or state.policy_snapshot_hash != policy_snapshot_hash
            or state.audit_chain_ref != audit_chain_ref
        ):
            raise ValueError("existing Tickets tenant state is not recoverable by this pilot command")

    @staticmethod
    def _receipt(
        *,
        user_context: UserContext,
        command: _TicketsIncidentsControlledPilotCommand,
        approval: TicketsIncidentsActivationDryRunExecutionApprovalRecordResponse,
        receipt_type: TicketsIncidentsPilotReceiptType,
        command_hash: str,
        idempotency_hash: str,
        state: TenantModuleState,
        next_action: str,
        admission_receipt_hash: str = ZERO_HASH,
        authorization_receipt_hash: str = ZERO_HASH,
    ) -> TicketsIncidentsControlledPilotReceipt:
        endpoint = (
            ADMISSION_ENDPOINT if receipt_type == TicketsIncidentsPilotReceiptType.ADMISSION else ENABLEMENT_ENDPOINT
        )
        draft = TicketsIncidentsControlledPilotReceipt(
            tenant_id=user_context.tenant_id,
            endpoint=endpoint,
            receipt_type=receipt_type,
            approval_boundary_evidence_hash=approval.approval_boundary_evidence_hash,
            approval_record_evidence_hash=approval.evidence_hash,
            tickets_restore_drill_evidence_hash=approval.tickets_restore_drill_evidence_hash,
            command_hash=command_hash,
            idempotency_key_hash=idempotency_hash,
            confirmation_statement_hash=stable_hash(command.human_confirmation_statement),
            policy_snapshot_hash=command.policy_snapshot_hash,
            feature_manifest_hash=command.feature_manifest_hash,
            module_status=state.status,
            enabled_features=state.enabled_features,
            changed_by=user_context.user_id,
            changed_at_utc=command.changed_at_utc,
            audit_chain_ref=command.audit_chain_ref,
            admission_receipt_evidence_hash=admission_receipt_hash,
            authorization_receipt_evidence_hash=authorization_receipt_hash,
            tickets_business_api_allowed=receipt_type == TicketsIncidentsPilotReceiptType.ENABLEMENT_COMPLETED,
            evidence_hash=ZERO_HASH,
            next_action=next_action,
        )
        return draft.model_copy(
            update={
                "evidence_hash": stable_hash(canonical_json(draft.model_dump(mode="json", exclude={"evidence_hash"})))
            }
        )
