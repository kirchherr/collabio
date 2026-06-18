from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.platform.legacy_sql_discovery import (
    MODULE_ID_PATTERN,
    NAMESPACED_REF_PATTERN,
    LegacySqlConnectorKind,
    LegacySqlDiscoveryRequest,
)
from suite.platform.legacy_sql_server_metadata import (
    LegacySqlServerMetadataDiscoveryCommand,
    LegacySqlServerNetworkMode,
)


class LegacySqlDiscoveryIntakeStatus(StrEnum):
    READY_FOR_METADATA_WORKER = "ready_for_metadata_worker"
    BLOCKED = "blocked"


class LegacySqlApprovedHostProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host_profile_ref: str
    connector_kind: LegacySqlConnectorKind
    connector_policy_ref: str
    policy_snapshot_hash: str
    approved_egress_ref: str
    connection_secret_ref: str
    connection_fingerprint_hash: str
    worker_network_mode: LegacySqlServerNetworkMode = LegacySqlServerNetworkMode.APPROVED_LEGACY_HOST_ONLY
    approved_for_metadata_discovery: bool = True
    row_count_estimates_allowed: bool = True
    raw_data_access_allowed: bool = False
    sample_values_allowed: bool = False
    stored_procedure_body_reads_allowed: bool = False
    import_dry_run_allowed: bool = False
    import_write_allowed: bool = False
    destructive_actions_allowed: bool = False
    schema_version: str = "legacy_sql_approved_host_profile.v1"

    @field_validator(
        "host_profile_ref",
        "connector_policy_ref",
        "policy_snapshot_hash",
        "approved_egress_ref",
        "connection_secret_ref",
        "connection_fingerprint_hash",
    )
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL host profile references must be namespaced")
        return value

    @model_validator(mode="after")
    def require_safe_host_profile(self) -> Self:
        if self.connector_kind != LegacySqlConnectorKind.SQLSERVER:
            raise ValueError("initial legacy SQL discovery intake supports sqlserver only")
        if self.worker_network_mode != LegacySqlServerNetworkMode.APPROVED_LEGACY_HOST_ONLY:
            raise ValueError("legacy SQL host profile must require approved legacy host egress")
        if not self.approved_for_metadata_discovery:
            raise ValueError("legacy SQL host profile must be approved for metadata discovery")
        if (
            self.raw_data_access_allowed
            or self.sample_values_allowed
            or self.stored_procedure_body_reads_allowed
            or self.import_dry_run_allowed
            or self.import_write_allowed
            or self.destructive_actions_allowed
        ):
            raise ValueError("legacy SQL host profile must not allow raw data, import, or destructive actions")
        return self


class LegacySqlDiscoveryIntakeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    requested_by: str
    approval_reference: str
    audit_chain_ref: str
    host_profile_ref: str
    connector_policy_ref: str
    policy_snapshot_hash: str
    include_row_counts: bool = True
    dsn: str | None = None
    raw_data_requested: bool = False
    sample_values_requested: bool = False
    stored_procedure_body_requested: bool = False
    import_dry_run_requested: bool = False
    import_write_requested: bool = False
    destructive_actions_requested: bool = False

    @field_validator("tenant_id", "requested_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("field must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("module_id must be lowercase snake_case")
        return value

    @field_validator(
        "source_system_ref",
        "approval_reference",
        "audit_chain_ref",
        "host_profile_ref",
        "connector_policy_ref",
        "policy_snapshot_hash",
    )
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL discovery intake references must be namespaced")
        return value

    @model_validator(mode="after")
    def reject_unsafe_intake_requests(self) -> Self:
        if self.dsn is not None:
            raise ValueError("legacy SQL discovery intake must use secret references, not DSN values")
        if (
            self.raw_data_requested
            or self.sample_values_requested
            or self.stored_procedure_body_requested
            or self.import_dry_run_requested
            or self.import_write_requested
            or self.destructive_actions_requested
        ):
            raise ValueError("legacy SQL discovery intake only accepts metadata discovery requests")
        return self


class LegacySqlDiscoveryIntakeEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    requested_by: str
    approval_reference: str
    audit_chain_ref: str
    host_profile_ref: str
    connector_policy_ref: str
    policy_snapshot_hash: str
    approved_egress_ref: str
    connection_secret_ref_present: bool
    connection_fingerprint_hash: str
    worker_network_mode: LegacySqlServerNetworkMode
    include_row_counts: bool
    metadata_worker_command_ready: bool
    metadata_discovery_allowed: bool
    import_dry_run_allowed: bool = False
    import_write_allowed: bool = False
    raw_data_import_allowed: bool = False
    destructive_actions_allowed: bool = False
    blocking_reasons: tuple[str, ...]
    status: LegacySqlDiscoveryIntakeStatus
    evidence_hash: str
    schema_version: str = "legacy_sql_discovery_intake.v1"

    @field_validator("tenant_id", "requested_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("field must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("module_id must be lowercase snake_case")
        return value

    @field_validator(
        "source_system_ref",
        "approval_reference",
        "audit_chain_ref",
        "host_profile_ref",
        "connector_policy_ref",
        "policy_snapshot_hash",
        "approved_egress_ref",
        "connection_fingerprint_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL discovery intake evidence references must be namespaced")
        return value

    @field_validator("blocking_reasons")
    @classmethod
    def validate_blocking_reasons(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("blocking reasons must be unique")
        for reason in value:
            if not reason.strip():
                raise ValueError("blocking reasons must not be empty")
        return value

    @model_validator(mode="after")
    def require_intake_consistency(self) -> Self:
        if self.import_dry_run_allowed or self.import_write_allowed:
            raise ValueError("legacy SQL discovery intake must not allow import dry-run or import writes")
        if self.raw_data_import_allowed or self.destructive_actions_allowed:
            raise ValueError("legacy SQL discovery intake must not allow raw import or destructive actions")
        if self.metadata_discovery_allowed and self.blocking_reasons:
            raise ValueError("metadata discovery cannot be allowed while intake has blockers")
        if self.metadata_discovery_allowed != self.metadata_worker_command_ready:
            raise ValueError("metadata discovery and command readiness must match")
        if self.status == LegacySqlDiscoveryIntakeStatus.READY_FOR_METADATA_WORKER:
            if not self.metadata_discovery_allowed:
                raise ValueError("ready intake status requires metadata discovery allowance")
        elif not self.blocking_reasons:
            raise ValueError("blocked intake status requires blocking reasons")
        return self


@dataclass(frozen=True)
class LegacySqlDiscoveryIntakeResult:
    evidence: LegacySqlDiscoveryIntakeEvidence
    command: LegacySqlServerMetadataDiscoveryCommand | None


class LegacySqlDiscoveryIntakeGate:
    def evaluate(
        self,
        *,
        request: LegacySqlDiscoveryIntakeRequest,
        host_profile: LegacySqlApprovedHostProfile,
    ) -> LegacySqlDiscoveryIntakeResult:
        blocking_reasons = _blocking_reasons(request=request, host_profile=host_profile)
        allowed = not blocking_reasons
        command = _worker_command(request=request, host_profile=host_profile) if allowed else None
        status = (
            LegacySqlDiscoveryIntakeStatus.READY_FOR_METADATA_WORKER
            if allowed
            else LegacySqlDiscoveryIntakeStatus.BLOCKED
        )
        draft = LegacySqlDiscoveryIntakeEvidence(
            tenant_id=request.tenant_id,
            module_id=request.module_id,
            source_system_ref=request.source_system_ref,
            connector_kind=request.connector_kind,
            requested_by=request.requested_by,
            approval_reference=request.approval_reference,
            audit_chain_ref=request.audit_chain_ref,
            host_profile_ref=host_profile.host_profile_ref,
            connector_policy_ref=request.connector_policy_ref,
            policy_snapshot_hash=request.policy_snapshot_hash,
            approved_egress_ref=host_profile.approved_egress_ref,
            connection_secret_ref_present=bool(host_profile.connection_secret_ref.strip()),
            connection_fingerprint_hash=host_profile.connection_fingerprint_hash,
            worker_network_mode=host_profile.worker_network_mode,
            include_row_counts=request.include_row_counts,
            metadata_worker_command_ready=allowed,
            metadata_discovery_allowed=allowed,
            blocking_reasons=tuple(sorted(blocking_reasons)),
            status=status,
            evidence_hash="sha256:pending",
        )
        evidence = draft.model_copy(update={"evidence_hash": _hash_intake_evidence(draft)})
        return LegacySqlDiscoveryIntakeResult(evidence=evidence, command=command)


def _blocking_reasons(
    *,
    request: LegacySqlDiscoveryIntakeRequest,
    host_profile: LegacySqlApprovedHostProfile,
) -> list[str]:
    blocking_reasons: list[str] = []
    if request.host_profile_ref != host_profile.host_profile_ref:
        blocking_reasons.append("host_profile_ref_mismatch")
    if request.connector_kind != host_profile.connector_kind:
        blocking_reasons.append("connector_kind_mismatch")
    if request.connector_policy_ref != host_profile.connector_policy_ref:
        blocking_reasons.append("connector_policy_ref_mismatch")
    if request.policy_snapshot_hash != host_profile.policy_snapshot_hash:
        blocking_reasons.append("connector_policy_hash_mismatch")
    if request.include_row_counts and not host_profile.row_count_estimates_allowed:
        blocking_reasons.append("row_count_estimates_not_allowed")
    if host_profile.worker_network_mode != LegacySqlServerNetworkMode.APPROVED_LEGACY_HOST_ONLY:
        blocking_reasons.append("approved_legacy_host_egress_required")
    if not host_profile.approved_for_metadata_discovery:
        blocking_reasons.append("host_profile_not_approved_for_metadata_discovery")
    return blocking_reasons


def _worker_command(
    *,
    request: LegacySqlDiscoveryIntakeRequest,
    host_profile: LegacySqlApprovedHostProfile,
) -> LegacySqlServerMetadataDiscoveryCommand:
    return LegacySqlServerMetadataDiscoveryCommand(
        request=LegacySqlDiscoveryRequest(
            tenant_id=request.tenant_id,
            module_id=request.module_id,
            source_system_ref=request.source_system_ref,
            connector_kind=request.connector_kind,
            requested_by=request.requested_by,
            approval_reference=request.approval_reference,
            audit_chain_ref=request.audit_chain_ref,
            include_row_counts=request.include_row_counts,
        ),
        connection_secret_ref=host_profile.connection_secret_ref,
        connection_fingerprint_hash=host_profile.connection_fingerprint_hash,
        connector_policy_ref=host_profile.connector_policy_ref,
        policy_snapshot_hash=host_profile.policy_snapshot_hash,
    )


def _hash_intake_evidence(evidence: LegacySqlDiscoveryIntakeEvidence) -> str:
    payload = evidence.model_dump(mode="json", exclude={"evidence_hash"})
    return stable_hash(canonical_json(payload))
