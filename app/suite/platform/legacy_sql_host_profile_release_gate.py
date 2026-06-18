from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.platform.legacy_sql_discovery import (
    MODULE_ID_PATTERN,
    NAMESPACED_REF_PATTERN,
    LegacySqlConnectorKind,
)
from suite.platform.legacy_sql_discovery_intake import LegacySqlApprovedHostProfile
from suite.platform.legacy_sql_evidence_ledger_operations import (
    LEGACY_SQL_EVIDENCE_LEDGER_CONTINUITY_DOMAIN,
    LegacySqlEvidenceLedgerBackend,
    LegacySqlEvidenceLedgerOperationsReport,
    build_legacy_sql_evidence_ledger_operations_report_hash,
)
from suite.platform.legacy_sql_server_metadata import (
    LegacySqlServerConnectorPolicy,
    LegacySqlServerNetworkMode,
    build_legacy_sql_connector_policy_hash,
)

LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_SCHEMA_VERSION = "legacy_sql_host_profile_release_gate.v1"
LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_REF_PREFIX = "legacy-sql-host-profile-release-gate"
LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_FRESHNESS_HOURS = 24
LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_REQUIRED_INPUTS = (
    "legacy_sql_evidence_ledger_operations_report_hash",
    "legacy_sql_connector_policy_hash",
    "legacy_sql_host_profile_ref",
    "approved_egress_ref",
    "connection_secret_ref_hash",
    "explicit_human_confirmation_reference",
)
SHA256_REF_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
ZERO_HASH = "sha256:" + "0" * 64


class LegacySqlHostProfileReleaseGateStatus(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"


class LegacySqlHostProfileReleaseGateCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    host_profile_ref: str
    connector_policy_ref: str
    policy_snapshot_hash: str
    approved_egress_ref: str
    connection_secret_ref: str
    connection_fingerprint_hash: str
    ledger_operations_report_hash: str
    requested_by: str
    human_confirmation_reference: str
    human_confirmation: bool
    dsn: str | None = None
    raw_data_access_requested: bool = False
    import_dry_run_requested: bool = False
    import_write_requested: bool = False
    destructive_actions_requested: bool = False

    @field_validator("tenant_id", "requested_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL host profile release gate text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL host profile release gate module_id must be lowercase snake_case")
        return value

    @field_validator(
        "source_system_ref",
        "host_profile_ref",
        "connector_policy_ref",
        "approved_egress_ref",
        "connection_secret_ref",
        "connection_fingerprint_hash",
        "human_confirmation_reference",
    )
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL host profile release gate references must be namespaced")
        return value

    @field_validator("policy_snapshot_hash", "ledger_operations_report_hash")
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL host profile release gate hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def reject_unsafe_release_requests(self) -> Self:
        if self.dsn is not None:
            raise ValueError("legacy SQL host profile release gate must use secret references, not DSN values")
        if (
            self.raw_data_access_requested
            or self.import_dry_run_requested
            or self.import_write_requested
            or self.destructive_actions_requested
        ):
            raise ValueError("legacy SQL host profile release gate only releases metadata discovery host profiles")
        return self


class LegacySqlHostProfileReleaseGateEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    continuity_domain: str = LEGACY_SQL_EVIDENCE_LEDGER_CONTINUITY_DOMAIN
    required_evidence_inputs: tuple[str, ...] = LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_REQUIRED_INPUTS
    host_profile_ref: str
    connector_kind: LegacySqlConnectorKind
    connector_policy_ref: str
    policy_snapshot_hash: str
    approved_egress_ref: str
    connection_secret_ref_hash: str
    connection_fingerprint_hash: str
    ledger_operations_report_hash: str
    ledger_operations_checked_at_utc: datetime
    evaluated_at_utc: datetime
    freshness_window_hours: int = Field(gt=0, le=720)
    requested_by: str
    human_confirmation_reference: str
    ledger_operations_report_hash_valid: bool
    ledger_operations_report_fresh: bool
    ledger_operations_gate_passed: bool
    postgres_ledger_backend_ready: bool
    connector_policy_hash_valid: bool
    host_profile_policy_bound: bool
    host_profile_egress_bound: bool
    host_profile_secret_bound: bool
    host_profile_fingerprint_bound: bool
    host_profile_metadata_only: bool
    human_confirmation_verified: bool
    metadata_only_boundary_verified: bool
    host_profile_activation_allowed: bool
    metadata_worker_scheduling_allowed: bool
    real_connection_used: bool = False
    raw_data_access_allowed: bool = False
    import_dry_run_allowed: bool = False
    import_write_allowed: bool = False
    destructive_actions_allowed: bool = False
    blocking_reasons: tuple[str, ...]
    gate_status: LegacySqlHostProfileReleaseGateStatus
    evidence_hash: str

    @field_validator("tenant_id", "requested_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL host profile release gate evidence text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL host profile release gate evidence module_id must be lowercase snake_case")
        return value

    @field_validator(
        "source_system_ref",
        "host_profile_ref",
        "connector_policy_ref",
        "approved_egress_ref",
        "connection_fingerprint_hash",
        "human_confirmation_reference",
    )
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL host profile release gate evidence references must be namespaced")
        return value

    @field_validator(
        "policy_snapshot_hash",
        "connection_secret_ref_hash",
        "ledger_operations_report_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL host profile release gate evidence hashes must be sha256 references")
        return value

    @field_validator("required_evidence_inputs")
    @classmethod
    def require_expected_inputs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_REQUIRED_INPUTS:
            raise ValueError("legacy SQL host profile release gate evidence inputs are incomplete")
        return value

    @field_validator("blocking_reasons")
    @classmethod
    def validate_blocking_reasons(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("legacy SQL host profile release gate blocking reasons must be unique")
        for reason in value:
            if not reason.strip():
                raise ValueError("legacy SQL host profile release gate blocking reasons must not be empty")
        return value

    @model_validator(mode="after")
    def require_gate_consistency(self) -> LegacySqlHostProfileReleaseGateEvidence:
        allowed = self.host_profile_activation_allowed and self.metadata_worker_scheduling_allowed
        if self.continuity_domain != LEGACY_SQL_EVIDENCE_LEDGER_CONTINUITY_DOMAIN:
            raise ValueError("legacy SQL host profile release gate must use the CRM/ERP continuity domain")
        if (
            self.real_connection_used
            or self.raw_data_access_allowed
            or self.import_dry_run_allowed
            or self.import_write_allowed
            or self.destructive_actions_allowed
        ):
            raise ValueError("legacy SQL host profile release gate must not execute or allow import/write actions")
        if allowed and self.blocking_reasons:
            raise ValueError("legacy SQL host profile release gate cannot allow activation with blocking reasons")
        if allowed and self.gate_status != LegacySqlHostProfileReleaseGateStatus.READY:
            raise ValueError("legacy SQL host profile release gate allowed state must be ready")
        if not allowed and self.gate_status != LegacySqlHostProfileReleaseGateStatus.BLOCKED:
            raise ValueError("legacy SQL host profile release gate blocked state must be blocked")
        return self


def build_legacy_sql_host_profile_release_gate(
    *,
    command: LegacySqlHostProfileReleaseGateCommand,
    host_profile: LegacySqlApprovedHostProfile,
    connector_policy: LegacySqlServerConnectorPolicy,
    ledger_operations_report: LegacySqlEvidenceLedgerOperationsReport,
    evaluated_at_utc: datetime | None = None,
    freshness_window_hours: int = LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_FRESHNESS_HOURS,
) -> LegacySqlHostProfileReleaseGateEvidence:
    evaluated_at = _aware(evaluated_at_utc or datetime.now(UTC))
    ledger_checked_at = _aware(ledger_operations_report.checked_at_utc)
    freshness_window = timedelta(hours=freshness_window_hours)
    policy_hash = build_legacy_sql_connector_policy_hash(connector_policy)
    ledger_operations_report_hash_valid = (
        build_legacy_sql_evidence_ledger_operations_report_hash(ledger_operations_report)
        == ledger_operations_report.evidence_hash
        == command.ledger_operations_report_hash
    )
    ledger_operations_report_fresh = _fresh(
        checked_at=ledger_checked_at,
        evaluated_at=evaluated_at,
        window=freshness_window,
    )
    ledger_operations_gate_passed = (
        ledger_operations_report.legacy_host_profile_release_gate_passed
        and not ledger_operations_report.alert_required
        and ledger_operations_report.failed_count == 0
        and not ledger_operations_report.real_connection_used
        and not ledger_operations_report.import_dry_run_executed
        and not ledger_operations_report.import_write_executed
        and not ledger_operations_report.destructive_actions_executed
    )
    postgres_ledger_backend_ready = any(
        result.backend == LegacySqlEvidenceLedgerBackend.POSTGRES and result.host_profile_release_precondition_ok
        for result in ledger_operations_report.backend_results
    )
    connector_policy_hash_valid = (
        policy_hash == command.policy_snapshot_hash == host_profile.policy_snapshot_hash
        and command.connector_policy_ref == host_profile.connector_policy_ref
        and command.connector_kind == connector_policy.connector_kind
    )
    host_profile_policy_bound = (
        command.host_profile_ref == host_profile.host_profile_ref
        and command.connector_kind == host_profile.connector_kind
        and command.connector_policy_ref == host_profile.connector_policy_ref
        and command.policy_snapshot_hash == host_profile.policy_snapshot_hash
    )
    host_profile_egress_bound = (
        command.approved_egress_ref == host_profile.approved_egress_ref
        and host_profile.worker_network_mode == LegacySqlServerNetworkMode.APPROVED_LEGACY_HOST_ONLY
    )
    host_profile_secret_bound = (
        bool(command.connection_secret_ref.strip())
        and command.connection_secret_ref == host_profile.connection_secret_ref
    )
    host_profile_fingerprint_bound = command.connection_fingerprint_hash == host_profile.connection_fingerprint_hash
    host_profile_metadata_only = _host_profile_metadata_only(host_profile)
    human_confirmation_verified = command.human_confirmation and bool(command.human_confirmation_reference.strip())
    metadata_only_boundary_verified = (
        host_profile_metadata_only
        and ledger_operations_gate_passed
        and not command.raw_data_access_requested
        and not command.import_dry_run_requested
        and not command.import_write_requested
        and not command.destructive_actions_requested
    )
    blocking_reasons = _release_gate_blocking_reasons(
        command=command,
        host_profile=host_profile,
        ledger_operations_report=ledger_operations_report,
        ledger_operations_report_hash_valid=ledger_operations_report_hash_valid,
        ledger_operations_report_fresh=ledger_operations_report_fresh,
        ledger_operations_gate_passed=ledger_operations_gate_passed,
        postgres_ledger_backend_ready=postgres_ledger_backend_ready,
        connector_policy_hash_valid=connector_policy_hash_valid,
        host_profile_policy_bound=host_profile_policy_bound,
        host_profile_egress_bound=host_profile_egress_bound,
        host_profile_secret_bound=host_profile_secret_bound,
        host_profile_fingerprint_bound=host_profile_fingerprint_bound,
        host_profile_metadata_only=host_profile_metadata_only,
        human_confirmation_verified=human_confirmation_verified,
        metadata_only_boundary_verified=metadata_only_boundary_verified,
    )
    release_allowed = not blocking_reasons
    draft = LegacySqlHostProfileReleaseGateEvidence(
        tenant_id=command.tenant_id,
        module_id=command.module_id,
        source_system_ref=command.source_system_ref,
        host_profile_ref=host_profile.host_profile_ref,
        connector_kind=command.connector_kind,
        connector_policy_ref=command.connector_policy_ref,
        policy_snapshot_hash=command.policy_snapshot_hash,
        approved_egress_ref=host_profile.approved_egress_ref,
        connection_secret_ref_hash=_connection_secret_ref_hash(command.connection_secret_ref),
        connection_fingerprint_hash=host_profile.connection_fingerprint_hash,
        ledger_operations_report_hash=ledger_operations_report.evidence_hash,
        ledger_operations_checked_at_utc=ledger_checked_at,
        evaluated_at_utc=evaluated_at,
        freshness_window_hours=freshness_window_hours,
        requested_by=command.requested_by,
        human_confirmation_reference=command.human_confirmation_reference,
        ledger_operations_report_hash_valid=ledger_operations_report_hash_valid,
        ledger_operations_report_fresh=ledger_operations_report_fresh,
        ledger_operations_gate_passed=ledger_operations_gate_passed,
        postgres_ledger_backend_ready=postgres_ledger_backend_ready,
        connector_policy_hash_valid=connector_policy_hash_valid,
        host_profile_policy_bound=host_profile_policy_bound,
        host_profile_egress_bound=host_profile_egress_bound,
        host_profile_secret_bound=host_profile_secret_bound,
        host_profile_fingerprint_bound=host_profile_fingerprint_bound,
        host_profile_metadata_only=host_profile_metadata_only,
        human_confirmation_verified=human_confirmation_verified,
        metadata_only_boundary_verified=metadata_only_boundary_verified,
        host_profile_activation_allowed=release_allowed,
        metadata_worker_scheduling_allowed=release_allowed,
        blocking_reasons=blocking_reasons,
        gate_status=(
            LegacySqlHostProfileReleaseGateStatus.READY
            if release_allowed
            else LegacySqlHostProfileReleaseGateStatus.BLOCKED
        ),
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_host_profile_release_gate_hash(draft)})


def require_legacy_sql_host_profile_release_gate_ready(
    gate: LegacySqlHostProfileReleaseGateEvidence,
) -> LegacySqlHostProfileReleaseGateEvidence:
    if (
        gate.gate_status != LegacySqlHostProfileReleaseGateStatus.READY
        or not gate.host_profile_activation_allowed
        or not gate.metadata_worker_scheduling_allowed
    ):
        reasons = ", ".join(gate.blocking_reasons) or "unknown"
        raise ValueError(f"legacy SQL host profile release gate is blocked: {reasons}")
    return gate


def require_legacy_sql_host_profile_release_gate_for_wiring(
    *,
    gate: LegacySqlHostProfileReleaseGateEvidence,
    tenant_id: str,
    host_profile_ref: str,
    evidence_hash: str,
) -> LegacySqlHostProfileReleaseGateEvidence:
    if gate.tenant_id != tenant_id:
        raise ValueError("legacy SQL host profile release gate tenant does not match wiring tenant")
    if gate.host_profile_ref != host_profile_ref:
        raise ValueError("legacy SQL host profile release gate profile does not match wiring profile")
    if gate.evidence_hash != evidence_hash:
        raise ValueError("legacy SQL host profile release gate evidence hash does not match wiring hash")
    _require_valid_release_gate_hash(gate)
    return require_legacy_sql_host_profile_release_gate_ready(gate)


def build_legacy_sql_host_profile_release_gate_hash(
    evidence: LegacySqlHostProfileReleaseGateEvidence,
) -> str:
    return stable_hash(canonical_json(evidence.model_dump(mode="json", exclude={"evidence_hash"})))


def legacy_sql_host_profile_release_gate_ref(evidence: LegacySqlHostProfileReleaseGateEvidence) -> str:
    return f"{LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_REF_PREFIX}:{evidence.evidence_hash}"


def _release_gate_blocking_reasons(
    *,
    command: LegacySqlHostProfileReleaseGateCommand,
    host_profile: LegacySqlApprovedHostProfile,
    ledger_operations_report: LegacySqlEvidenceLedgerOperationsReport,
    ledger_operations_report_hash_valid: bool,
    ledger_operations_report_fresh: bool,
    ledger_operations_gate_passed: bool,
    postgres_ledger_backend_ready: bool,
    connector_policy_hash_valid: bool,
    host_profile_policy_bound: bool,
    host_profile_egress_bound: bool,
    host_profile_secret_bound: bool,
    host_profile_fingerprint_bound: bool,
    host_profile_metadata_only: bool,
    human_confirmation_verified: bool,
    metadata_only_boundary_verified: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if ledger_operations_report.continuity_domain != LEGACY_SQL_EVIDENCE_LEDGER_CONTINUITY_DOMAIN:
        reasons.append("ledger_operations_continuity_domain_mismatch")
    if command.tenant_id not in {result.tenant_id for result in ledger_operations_report.backend_results}:
        reasons.append("ledger_operations_tenant_missing")
    if not ledger_operations_report_hash_valid:
        reasons.append("ledger_operations_report_hash_invalid")
    if not ledger_operations_report_fresh:
        reasons.append("ledger_operations_report_stale")
    if not ledger_operations_gate_passed:
        reasons.append("ledger_operations_gate_not_passed")
    if not postgres_ledger_backend_ready:
        reasons.append("postgres_ledger_backend_not_ready")
    if not connector_policy_hash_valid:
        reasons.append("connector_policy_hash_invalid")
    if not host_profile_policy_bound:
        reasons.append("host_profile_policy_not_bound")
    if not host_profile_egress_bound:
        reasons.append("host_profile_egress_not_bound")
    if not host_profile_secret_bound:
        reasons.append("host_profile_secret_not_bound")
    if not host_profile_fingerprint_bound:
        reasons.append("host_profile_fingerprint_not_bound")
    if host_profile.connector_kind != LegacySqlConnectorKind.SQLSERVER:
        reasons.append("unsupported_connector_kind")
    if not host_profile_metadata_only:
        reasons.append("host_profile_not_metadata_only")
    if not human_confirmation_verified:
        reasons.append("explicit_human_confirmation_missing")
    if not metadata_only_boundary_verified:
        reasons.append("metadata_only_boundary_not_verified")
    return tuple(sorted(set(reasons)))


def _host_profile_metadata_only(host_profile: LegacySqlApprovedHostProfile) -> bool:
    return (
        host_profile.approved_for_metadata_discovery
        and host_profile.worker_network_mode == LegacySqlServerNetworkMode.APPROVED_LEGACY_HOST_ONLY
        and not host_profile.raw_data_access_allowed
        and not host_profile.sample_values_allowed
        and not host_profile.stored_procedure_body_reads_allowed
        and not host_profile.import_dry_run_allowed
        and not host_profile.import_write_allowed
        and not host_profile.destructive_actions_allowed
    )


def _connection_secret_ref_hash(connection_secret_ref: str) -> str:
    return stable_hash(canonical_json({"connection_secret_ref": connection_secret_ref}))


def _fresh(*, checked_at: datetime, evaluated_at: datetime, window: timedelta) -> bool:
    if checked_at > evaluated_at:
        return False
    return evaluated_at - checked_at <= window


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _require_valid_release_gate_hash(evidence: LegacySqlHostProfileReleaseGateEvidence) -> None:
    if build_legacy_sql_host_profile_release_gate_hash(evidence) != evidence.evidence_hash:
        raise ValueError("legacy SQL host profile release gate evidence hash is invalid")
