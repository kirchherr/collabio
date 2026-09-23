from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.ai_control_plane.models import UserContext
from suite.persistence.migration_catalog import MigrationManifestEntry
from suite.platform.lms_module import LMS_CONTINUITY_DOMAIN, LMS_MODULE_ID
from suite.platform.lms_tenant_admin_package_approval_gate import (
    build_lms_tenant_admin_package_approval_gate_response,
)
from suite.platform.modules import InMemoryModuleRegistry, PgModuleRegistry

LMS_TENANT_ADMIN_PACKAGE_APPROVAL_RECORD_SCHEMA_VERSION = "lms_tenant_admin_package_approval_record.v1"
LMS_TENANT_ADMIN_PACKAGE_APPROVAL_RECORD_RESULT_CONTRACT = (
    "metadata_only_lms_tenant_admin_package_approval_record_no_install"
)
LMS_TENANT_ADMIN_PACKAGE_APPROVAL_RECORD_ENDPOINT = (
    "/v1/platform/modules/families/lms/tenant-admin-package-approval-records"
)
LMS_TENANT_ADMIN_PACKAGE_APPROVAL_RECORD_CONFIRMATION_STATEMENT = (
    "I explicitly approve the LMS package installation readiness gate for this tenant without executing installation."
)
LMS_TENANT_ADMIN_PACKAGE_APPROVAL_RECORD_CREATED_NEXT_ACTION = "review_lms_package_installation_execution_boundary"
LMS_TENANT_ADMIN_PACKAGE_APPROVAL_RECORD_RETRY_NEXT_ACTION = (
    "record_tenant_admin_package_install_approval_with_explicit_human_confirmation"
)
LMS_TENANT_ADMIN_PACKAGE_APPROVAL_RECORD_STATUS_APPROVED = "approved_for_package_installation_execution_gate"
LMS_TENANT_ADMIN_PACKAGE_APPROVAL_RECORD_STATUS_BLOCKED = "blocked"

REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")
SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")


class LmsTenantAdminPackageApprovalRecordCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_gate_evidence_hash: str
    approval_record_ref: str
    approval_ticket_ref: str
    human_confirmation_reference: str
    human_confirmation_statement: str
    change_request_ref: str
    idempotency_key_ref: str
    approved_at_utc: datetime
    audit_chain_ref: str
    approval_record_requested: bool = True
    package_installation_execution_requested: bool = False
    tenant_module_state_creation_requested: bool = False
    migration_execution_requested: bool = False
    lms_business_api_activation_requested: bool = False
    content_payload_included: bool = False
    destructive_actions_requested: bool = False
    external_side_effect_requested: bool = False

    @field_validator("approval_gate_evidence_hash")
    @classmethod
    def require_sha256(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("LMS approval gate evidence hash must be a sha256 reference")
        return value

    @field_validator(
        "approval_record_ref",
        "approval_ticket_ref",
        "human_confirmation_reference",
        "change_request_ref",
        "idempotency_key_ref",
        "audit_chain_ref",
    )
    @classmethod
    def require_ref(cls, value: str) -> str:
        if not REF_PATTERN.fullmatch(value.strip()):
            raise ValueError("LMS approval record references must use a typed ref prefix")
        return value.strip()

    @field_validator("human_confirmation_statement")
    @classmethod
    def require_exact_confirmation_statement(cls, value: str) -> str:
        normalized = value.strip()
        if normalized != LMS_TENANT_ADMIN_PACKAGE_APPROVAL_RECORD_CONFIRMATION_STATEMENT:
            raise ValueError("LMS approval record requires the exact explicit human confirmation statement")
        return normalized

    @field_validator("approved_at_utc")
    @classmethod
    def require_timezone_aware_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("LMS approval record approved_at_utc must include a timezone")
        return value


class LmsTenantAdminPackageApprovalRecordSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    required_approval_evidence_count: int
    blocking_reason_count: int


class LmsTenantAdminPackageApprovalRecordResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LMS_TENANT_ADMIN_PACKAGE_APPROVAL_RECORD_SCHEMA_VERSION
    tenant_id: str
    module_id: str = LMS_MODULE_ID
    endpoint: str = LMS_TENANT_ADMIN_PACKAGE_APPROVAL_RECORD_ENDPOINT
    result_contract: str = LMS_TENANT_ADMIN_PACKAGE_APPROVAL_RECORD_RESULT_CONTRACT
    continuity_domain: str = LMS_CONTINUITY_DOMAIN
    approval_gate_ready: bool
    approval_gate_evidence_hash: str
    lms_restore_drill_evidence_hash: str
    command_hash: str
    idempotency_key_hash: str
    human_confirmation_statement_hash: str
    approval_record_ref: str
    approval_ticket_ref: str
    human_confirmation_reference: str
    change_request_ref: str
    audit_chain_ref: str
    approved_by: str
    approved_at_utc: datetime
    approver_role_allowed: bool
    record_status: str
    approval_record_created: bool
    human_confirmation_captured: bool
    human_confirmation_statement_matched: bool
    future_package_installation_execution_gate_required: bool = True
    package_installation_execution_allowed: bool = False
    tenant_provisioning_allowed: bool = False
    migration_execution_allowed: bool = False
    lms_business_api_allowed: bool = False
    package_installation_executed: bool = False
    module_activation_executed: bool = False
    tenant_module_state_created: bool = False
    persistent_task_created: bool = False
    content_included: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False
    required_approval_evidence: tuple[str, ...]
    blocking_reasons: tuple[str, ...]
    summary: LmsTenantAdminPackageApprovalRecordSummary
    evidence_refs: tuple[str, ...]
    evidence_hash: str
    next_action: str

    @field_validator(
        "tenant_id",
        "module_id",
        "endpoint",
        "result_contract",
        "continuity_domain",
        "approval_record_ref",
        "approval_ticket_ref",
        "human_confirmation_reference",
        "change_request_ref",
        "audit_chain_ref",
        "approved_by",
        "record_status",
        "next_action",
    )
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("LMS approval record text fields must not be empty")
        return value

    @field_validator(
        "approval_gate_evidence_hash",
        "lms_restore_drill_evidence_hash",
        "command_hash",
        "idempotency_key_hash",
        "human_confirmation_statement_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_hash_reference(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("LMS approval record hashes must be sha256 references")
        return value

    @field_validator(
        "required_approval_evidence",
        "blocking_reasons",
        "evidence_refs",
    )
    @classmethod
    def require_unique_lists(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("LMS approval record lists must not contain duplicates")
        for item in value:
            if not item.strip():
                raise ValueError("LMS approval record list items must not be empty")
        return value

    @model_validator(mode="after")
    def require_non_executing_record_contract(self) -> LmsTenantAdminPackageApprovalRecordResponse:
        if self.schema_version != LMS_TENANT_ADMIN_PACKAGE_APPROVAL_RECORD_SCHEMA_VERSION:
            raise ValueError("LMS approval record schema version is invalid")
        if self.endpoint != LMS_TENANT_ADMIN_PACKAGE_APPROVAL_RECORD_ENDPOINT:
            raise ValueError("LMS approval record endpoint is invalid")
        if self.result_contract != LMS_TENANT_ADMIN_PACKAGE_APPROVAL_RECORD_RESULT_CONTRACT:
            raise ValueError("LMS approval record result contract is invalid")
        if self.module_id != LMS_MODULE_ID:
            raise ValueError("LMS approval record only applies to lms")
        if self.continuity_domain != LMS_CONTINUITY_DOMAIN:
            raise ValueError("LMS approval record continuity domain is invalid")
        expected_created = (
            self.approval_gate_ready
            and self.approver_role_allowed
            and self.human_confirmation_captured
            and self.human_confirmation_statement_matched
            and not self.blocking_reasons
        )
        if self.approval_record_created != expected_created:
            raise ValueError("LMS approval record creation flag must match prerequisites")
        if (
            self.approval_record_created
            and self.record_status != LMS_TENANT_ADMIN_PACKAGE_APPROVAL_RECORD_STATUS_APPROVED
        ):
            raise ValueError("created LMS approval records must be approved for the next execution gate")
        if (
            not self.approval_record_created
            and self.record_status != LMS_TENANT_ADMIN_PACKAGE_APPROVAL_RECORD_STATUS_BLOCKED
        ):
            raise ValueError("blocked LMS approval record attempts must use blocked status")
        if not self.future_package_installation_execution_gate_required:
            raise ValueError("LMS approval record must require a future package-installation execution gate")
        if (
            self.package_installation_execution_allowed
            or self.tenant_provisioning_allowed
            or self.migration_execution_allowed
            or self.lms_business_api_allowed
            or self.package_installation_executed
            or self.module_activation_executed
            or self.tenant_module_state_created
            or self.persistent_task_created
            or self.content_included
            or self.destructive_actions_allowed
            or self.external_side_effect_allowed
        ):
            raise ValueError("LMS approval record must remain metadata-only and non-executing")
        if self.summary.required_approval_evidence_count != len(self.required_approval_evidence):
            raise ValueError("LMS approval record evidence count must match evidence list")
        if self.summary.blocking_reason_count != len(self.blocking_reasons):
            raise ValueError("LMS approval record blocking count must match blocking reasons")
        return self


class LmsTenantAdminPackageApprovalRecordStore(Protocol):
    def append(
        self,
        record: LmsTenantAdminPackageApprovalRecordResponse,
    ) -> LmsTenantAdminPackageApprovalRecordResponse: ...

    def latest_for_gate(
        self,
        *,
        tenant_id: str,
        approval_gate_evidence_hash: str,
    ) -> LmsTenantAdminPackageApprovalRecordResponse | None: ...


class InMemoryLmsTenantAdminPackageApprovalRecordStore:
    def __init__(self, records: Iterable[LmsTenantAdminPackageApprovalRecordResponse] = ()) -> None:
        self._by_tenant_gate: dict[tuple[str, str], LmsTenantAdminPackageApprovalRecordResponse] = {}
        self._by_tenant_idempotency: dict[tuple[str, str], LmsTenantAdminPackageApprovalRecordResponse] = {}
        for record in records:
            self.append(record)

    def append(
        self,
        record: LmsTenantAdminPackageApprovalRecordResponse,
    ) -> LmsTenantAdminPackageApprovalRecordResponse:
        if not record.approval_record_created:
            raise ValueError("blocked LMS approval record attempts must not be appended")
        gate_key = (record.tenant_id, record.approval_gate_evidence_hash)
        idempotency_key = (record.tenant_id, record.idempotency_key_hash)
        existing_for_idempotency = self._by_tenant_idempotency.get(idempotency_key)
        if existing_for_idempotency is not None:
            return existing_for_idempotency
        existing_for_gate = self._by_tenant_gate.get(gate_key)
        if existing_for_gate is not None:
            raise ValueError("LMS approval gate already has an approval record for this tenant")
        self._by_tenant_gate[gate_key] = record
        self._by_tenant_idempotency[idempotency_key] = record
        return record

    def latest_for_gate(
        self,
        *,
        tenant_id: str,
        approval_gate_evidence_hash: str,
    ) -> LmsTenantAdminPackageApprovalRecordResponse | None:
        return self._by_tenant_gate.get((tenant_id, approval_gate_evidence_hash))


def build_default_lms_tenant_admin_package_approval_record_store() -> InMemoryLmsTenantAdminPackageApprovalRecordStore:
    return InMemoryLmsTenantAdminPackageApprovalRecordStore()


def build_lms_tenant_admin_package_approval_record_response(
    *,
    command: LmsTenantAdminPackageApprovalRecordCommand,
    user_context: UserContext,
    module_registry: InMemoryModuleRegistry | PgModuleRegistry,
    migration_manifest_entries: Iterable[MigrationManifestEntry],
) -> LmsTenantAdminPackageApprovalRecordResponse:
    approval_gate = build_lms_tenant_admin_package_approval_gate_response(
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest_entries,
    )
    command_hash = build_lms_tenant_admin_package_approval_record_command_hash(command)
    idempotency_key_hash = stable_hash(
        canonical_json(
            {
                "schema_version": "lms_tenant_admin_package_approval_record_idempotency_key.v1",
                "tenant_id": user_context.tenant_id,
                "approval_gate_evidence_hash": command.approval_gate_evidence_hash,
                "idempotency_key_ref": command.idempotency_key_ref,
            }
        )
    )
    human_confirmation_statement_hash = stable_hash(command.human_confirmation_statement)
    approver_role_allowed = bool({"tenant-admin", "tenant_admin"} & user_context.role_ids)
    human_confirmation_statement_matched = (
        command.human_confirmation_statement == LMS_TENANT_ADMIN_PACKAGE_APPROVAL_RECORD_CONFIRMATION_STATEMENT
    )
    blocking_reasons = _approval_record_blocking_reasons(
        command=command,
        approval_gate_ready=approval_gate.approval_gate_ready,
        expected_approval_gate_evidence_hash=approval_gate.evidence_hash,
        approver_role_allowed=approver_role_allowed,
        human_confirmation_statement_matched=human_confirmation_statement_matched,
    )
    approval_record_created = not blocking_reasons
    required_approval_evidence = (
        "tenant_admin_role",
        "approval_gate_evidence_hash",
        "restore_drill_evidence_hash",
        "exact_human_confirmation_statement_hash",
        "approval_ticket_ref",
        "change_request_ref",
        "idempotency_key_hash",
        "audit_chain_ref",
        "future_package_installation_execution_gate_required",
        "no_lms_installation_execution_confirmation",
    )
    draft = LmsTenantAdminPackageApprovalRecordResponse(
        tenant_id=user_context.tenant_id,
        approval_gate_ready=approval_gate.approval_gate_ready,
        approval_gate_evidence_hash=command.approval_gate_evidence_hash,
        lms_restore_drill_evidence_hash=approval_gate.lms_restore_drill_evidence_hash
        or "sha256:0000000000000000000000000000000000000000000000000000000000000000",
        command_hash=command_hash,
        idempotency_key_hash=idempotency_key_hash,
        human_confirmation_statement_hash=human_confirmation_statement_hash,
        approval_record_ref=command.approval_record_ref,
        approval_ticket_ref=command.approval_ticket_ref,
        human_confirmation_reference=command.human_confirmation_reference,
        change_request_ref=command.change_request_ref,
        audit_chain_ref=command.audit_chain_ref,
        approved_by=user_context.user_id,
        approved_at_utc=command.approved_at_utc,
        approver_role_allowed=approver_role_allowed,
        record_status=(
            LMS_TENANT_ADMIN_PACKAGE_APPROVAL_RECORD_STATUS_APPROVED
            if approval_record_created
            else LMS_TENANT_ADMIN_PACKAGE_APPROVAL_RECORD_STATUS_BLOCKED
        ),
        approval_record_created=approval_record_created,
        human_confirmation_captured=True,
        human_confirmation_statement_matched=human_confirmation_statement_matched,
        required_approval_evidence=required_approval_evidence,
        blocking_reasons=blocking_reasons,
        summary=LmsTenantAdminPackageApprovalRecordSummary(
            required_approval_evidence_count=len(required_approval_evidence),
            blocking_reason_count=len(blocking_reasons),
        ),
        evidence_refs=(
            "docs/modules/LMS_MODULE_CHARTER.md",
            "docs/modules/MODULE_IMPLEMENTATION_CONTRACT.md",
            "app/suite/platform/lms_tenant_admin_package_approval_gate.py",
            "app/suite/platform/lms_tenant_admin_package_approval_record.py",
            "app/suite/platform/lms_package_installation_readiness.py",
            "app/suite/persistence/migrations/0047_lms_package_install_approval_records.sql",
            "tests/test_lms_tenant_admin_package_approval_record.py",
        ),
        evidence_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        next_action=(
            LMS_TENANT_ADMIN_PACKAGE_APPROVAL_RECORD_CREATED_NEXT_ACTION
            if approval_record_created
            else LMS_TENANT_ADMIN_PACKAGE_APPROVAL_RECORD_RETRY_NEXT_ACTION
        ),
    )
    return draft.model_copy(update={"evidence_hash": build_lms_tenant_admin_package_approval_record_hash(draft)})


def build_lms_tenant_admin_package_approval_record_command_hash(
    command: LmsTenantAdminPackageApprovalRecordCommand,
) -> str:
    payload = command.model_dump(mode="json", exclude={"human_confirmation_statement"})
    payload["human_confirmation_statement_hash"] = stable_hash(command.human_confirmation_statement)
    return stable_hash(canonical_json(payload))


def build_lms_tenant_admin_package_approval_record_hash(
    response: LmsTenantAdminPackageApprovalRecordResponse,
) -> str:
    return stable_hash(canonical_json(response.model_dump(mode="json", exclude={"evidence_hash"})))


def _approval_record_blocking_reasons(
    *,
    command: LmsTenantAdminPackageApprovalRecordCommand,
    approval_gate_ready: bool,
    expected_approval_gate_evidence_hash: str,
    approver_role_allowed: bool,
    human_confirmation_statement_matched: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not approval_gate_ready:
        reasons.append("lms_tenant_admin_approval_gate_not_ready")
    if command.approval_gate_evidence_hash != expected_approval_gate_evidence_hash:
        reasons.append("approval_gate_evidence_hash_mismatch")
    if not approver_role_allowed:
        reasons.append("tenant_admin_role_required")
    if not command.approval_record_requested:
        reasons.append("approval_record_not_requested")
    if not human_confirmation_statement_matched:
        reasons.append("human_confirmation_statement_mismatch")
    if command.package_installation_execution_requested:
        reasons.append("package_installation_execution_request_forbidden")
    if command.tenant_module_state_creation_requested:
        reasons.append("tenant_module_state_creation_request_forbidden")
    if command.migration_execution_requested:
        reasons.append("migration_execution_request_forbidden")
    if command.lms_business_api_activation_requested:
        reasons.append("lms_business_api_activation_request_forbidden")
    if command.content_payload_included:
        reasons.append("content_payload_forbidden")
    if command.destructive_actions_requested:
        reasons.append("destructive_action_request_forbidden")
    if command.external_side_effect_requested:
        reasons.append("external_side_effect_request_forbidden")
    return tuple(reasons)
