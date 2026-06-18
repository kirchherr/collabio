from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.platform.legacy_sql_connector_provider_attestation_adapter import (
    LegacySqlConnectorProviderAttestationAdapter,
    LegacySqlConnectorProviderAttestationAdapterEvidence,
    LegacySqlConnectorProviderAttestationAdapterStatus,
    build_legacy_sql_connector_audit_deployment_profile,
    build_legacy_sql_connector_network_deployment_profile,
    build_legacy_sql_connector_provider_attestation_adapter_command,
    build_legacy_sql_connector_provider_attestation_adapter_hash,
    build_legacy_sql_connector_secret_resolver_deployment_profile,
)
from suite.platform.legacy_sql_connector_sandbox_enablement_gate import (
    LegacySqlConnectorSandboxEnablementGateEvidence,
    LegacySqlConnectorSandboxEnablementGateStatus,
    build_legacy_sql_connector_sandbox_enablement_command,
    build_legacy_sql_connector_sandbox_enablement_gate,
    build_legacy_sql_connector_sandbox_enablement_gate_hash,
)
from suite.platform.legacy_sql_connector_sandbox_profile import (
    LegacySqlConnectorSandboxProfileEvidence,
    LegacySqlConnectorSandboxProfileStatus,
    build_legacy_sql_connector_sandbox_profile,
    build_legacy_sql_connector_sandbox_profile_hash,
)
from suite.platform.legacy_sql_discovery import MODULE_ID_PATTERN, NAMESPACED_REF_PATTERN, LegacySqlConnectorKind
from suite.platform.legacy_sql_host_profile_adapter import (
    LegacySqlHostProfileAdapter,
    build_legacy_sql_host_profile_adapter_schedule_request_from_gate_smoke,
)
from suite.platform.legacy_sql_host_profile_release_gate import (
    build_default_legacy_sql_host_profile_release_gate_evidence_store,
)
from suite.platform.legacy_sql_host_profile_release_gate_smoke import (
    run_legacy_sql_host_profile_release_gate_smoke_from_env,
)
from suite.platform.legacy_sql_metadata_worker_lease_consumer import LegacySqlMetadataWorkerLeaseConsumer
from suite.platform.legacy_sql_metadata_worker_queue import (
    LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN,
    LegacySqlMetadataWorkerQueueBackend,
    build_default_legacy_sql_metadata_worker_queue_store,
    build_legacy_sql_metadata_worker_queue_job,
)

LEGACY_SQL_CONNECTOR_OPERATOR_CONTEXT_SCHEMA_VERSION = "legacy_sql_connector_operator_context.v1"
LEGACY_SQL_CONNECTOR_CONNECTION_PREFLIGHT_SCHEMA_VERSION = "legacy_sql_connector_connection_attempt_preflight_gate.v1"
LEGACY_SQL_CONNECTOR_CONNECTION_PREFLIGHT_SMOKE_SCHEMA_VERSION = (
    "legacy_sql_connector_connection_attempt_preflight_gate_smoke_report.v1"
)
LEGACY_SQL_CONNECTOR_CONNECTION_PREFLIGHT_COMMAND_REF = (
    "docker-compose:legacy-sql-connector-connection-preflight-gate-smoke"
)
ZERO_HASH = "sha256:" + "0" * 64
SHA256_REF_PATTERN = r"^sha256:[a-f0-9]{64}$"
FORBIDDEN_PREFLIGHT_FRAGMENTS = (
    '"connection_secret_ref":',
    "secret:legacy-sql",
    "sqlserver://",
    "password",
    "dsn",
    "raw_payload",
    "sample_values",
    "import_write_payload",
    "dbo.kunden",
    "kundenid",
    "email",
)


class LegacySqlConnectorConnectionPreflightStatus(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"


class LegacySqlConnectorOperatorContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_OPERATOR_CONTEXT_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    sandbox_profile_ref: str
    sandbox_profile_evidence_hash: str
    operator_principal_ref: str
    operator_role_ref: str = "role:legacy-sql-connection-operator"
    change_request_ref: str
    maintenance_window_ref: str
    approval_reference: str
    audit_chain_ref: str
    operator_authorized_for_legacy_sql: bool
    operator_mfa_verified: bool
    compliance_window_active: bool
    break_glass_requested: bool = False
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL connector operator context text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL connector operator context module_id must be lowercase snake_case")
        return value

    @field_validator(
        "source_system_ref",
        "sandbox_profile_ref",
        "operator_principal_ref",
        "operator_role_ref",
        "change_request_ref",
        "maintenance_window_ref",
        "approval_reference",
        "audit_chain_ref",
    )
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL connector operator context references must be namespaced")
        return value

    @field_validator("sandbox_profile_evidence_hash", "evidence_hash")
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL connector operator context hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_safe_operator_context(self) -> Self:
        _assert_preflight_safe(self)
        return self


class LegacySqlConnectorConnectionPreflightCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    sandbox_profile_ref: str
    sandbox_profile_evidence_hash: str
    enablement_gate_evidence_hash: str
    provider_attestation_adapter_evidence_hash: str
    operator_context_evidence_hash: str
    restore_evidence_hash: str
    requested_by: str
    connection_attempt_preflight_requested: bool = True
    network_socket_open_requested: bool = False
    secret_material_resolution_requested: bool = False
    raw_data_access_requested: bool = False
    import_dry_run_requested: bool = False
    import_write_requested: bool = False
    destructive_actions_requested: bool = False

    @field_validator("tenant_id", "requested_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL connector preflight command text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL connector preflight command module_id must be lowercase snake_case")
        return value

    @field_validator("source_system_ref", "sandbox_profile_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL connector preflight command references must be namespaced")
        return value

    @field_validator(
        "sandbox_profile_evidence_hash",
        "enablement_gate_evidence_hash",
        "provider_attestation_adapter_evidence_hash",
        "operator_context_evidence_hash",
        "restore_evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL connector preflight command hashes must be sha256 references")
        return value


class LegacySqlConnectorConnectionPreflightEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_CONNECTION_PREFLIGHT_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    continuity_domain: str = LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN
    command_ref: str = LEGACY_SQL_CONNECTOR_CONNECTION_PREFLIGHT_COMMAND_REF
    sandbox_profile_ref: str
    sandbox_profile_evidence_hash: str
    activation_evidence_hash: str
    queue_job_evidence_hash: str
    schedule_evidence_hash: str
    release_gate_evidence_hash: str
    enablement_gate_evidence_hash: str
    provider_attestation_adapter_evidence_hash: str
    provider_attestation_hash: str
    operator_context_evidence_hash: str
    restore_evidence_hash: str
    operator_principal_ref: str
    operator_role_ref: str
    change_request_ref: str
    maintenance_window_ref: str
    approval_reference: str
    sandbox_profile_hash_valid: bool
    sandbox_profile_default_off: bool
    sandbox_profile_visible: bool
    enablement_gate_hash_valid: bool
    enablement_gate_ready: bool
    enablement_gate_bound: bool
    provider_adapter_hash_valid: bool
    provider_adapter_ready: bool
    provider_adapter_bound: bool
    operator_context_hash_valid: bool
    operator_context_bound: bool
    operator_authorized_for_legacy_sql: bool
    operator_mfa_verified: bool
    compliance_window_active: bool
    break_glass_requested: bool
    restore_evidence_hash_valid: bool
    evidence_chain_bound: bool
    connection_attempt_preflight_requested: bool
    connection_attempt_preflight_ready: bool
    future_real_connection_executor_required: bool = True
    network_socket_open_requested: bool = False
    network_socket_opened: bool = False
    network_connection_opened: bool = False
    real_connection_opened: bool = False
    secret_material_resolution_requested: bool = False
    secret_material_resolved: bool = False
    raw_data_access_requested: bool = False
    raw_data_access_allowed: bool = False
    import_dry_run_requested: bool = False
    import_dry_run_allowed: bool = False
    import_write_requested: bool = False
    import_write_allowed: bool = False
    destructive_actions_requested: bool = False
    destructive_actions_allowed: bool = False
    gate_status: LegacySqlConnectorConnectionPreflightStatus
    blocking_reasons: tuple[str, ...]
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL connector preflight evidence text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL connector preflight evidence module_id must be lowercase snake_case")
        return value

    @field_validator(
        "source_system_ref",
        "sandbox_profile_ref",
        "operator_principal_ref",
        "operator_role_ref",
        "change_request_ref",
        "maintenance_window_ref",
        "approval_reference",
    )
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL connector preflight evidence references must be namespaced")
        return value

    @field_validator(
        "sandbox_profile_evidence_hash",
        "activation_evidence_hash",
        "queue_job_evidence_hash",
        "schedule_evidence_hash",
        "release_gate_evidence_hash",
        "enablement_gate_evidence_hash",
        "provider_attestation_adapter_evidence_hash",
        "provider_attestation_hash",
        "operator_context_evidence_hash",
        "restore_evidence_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL connector preflight evidence hashes must be sha256 references")
        return value

    @field_validator("blocking_reasons")
    @classmethod
    def validate_blocking_reasons(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("legacy SQL connector preflight blocking reasons must be unique")
        for reason in value:
            if not reason.strip():
                raise ValueError("legacy SQL connector preflight blocking reasons must not be empty")
        return value

    @model_validator(mode="after")
    def require_safe_preflight(self) -> Self:
        if (
            self.network_socket_opened
            or self.network_connection_opened
            or self.real_connection_opened
            or self.secret_material_resolved
            or self.raw_data_access_allowed
            or self.import_dry_run_allowed
            or self.import_write_allowed
            or self.destructive_actions_allowed
        ):
            raise ValueError("legacy SQL connector preflight must stay no-secret/no-socket")
        if not self.future_real_connection_executor_required:
            raise ValueError("legacy SQL connector preflight must require a future real-connection executor")
        if self.gate_status == LegacySqlConnectorConnectionPreflightStatus.READY:
            required = (
                self.sandbox_profile_hash_valid,
                self.sandbox_profile_default_off,
                self.sandbox_profile_visible,
                self.enablement_gate_hash_valid,
                self.enablement_gate_ready,
                self.enablement_gate_bound,
                self.provider_adapter_hash_valid,
                self.provider_adapter_ready,
                self.provider_adapter_bound,
                self.operator_context_hash_valid,
                self.operator_context_bound,
                self.operator_authorized_for_legacy_sql,
                self.operator_mfa_verified,
                self.compliance_window_active,
                not self.break_glass_requested,
                self.restore_evidence_hash_valid,
                self.evidence_chain_bound,
                self.connection_attempt_preflight_requested,
                self.connection_attempt_preflight_ready,
            )
            if not all(required) or self.blocking_reasons:
                raise ValueError("ready legacy SQL connector preflight requires complete evidence")
        if self.gate_status == LegacySqlConnectorConnectionPreflightStatus.BLOCKED:
            if not self.blocking_reasons:
                raise ValueError("blocked legacy SQL connector preflight requires blocking reasons")
            if self.connection_attempt_preflight_ready:
                raise ValueError("blocked legacy SQL connector preflight cannot be ready")
        _assert_preflight_safe(self)
        return self


class LegacySqlConnectorConnectionPreflightSmokeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_CONNECTION_PREFLIGHT_SMOKE_SCHEMA_VERSION
    tenant_id: str
    queue_backend: LegacySqlMetadataWorkerQueueBackend
    continuity_domain: str = LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN
    command_ref: str = LEGACY_SQL_CONNECTOR_CONNECTION_PREFLIGHT_COMMAND_REF
    sandbox_profile_ref: str
    sandbox_profile_evidence_hash: str
    enablement_gate_evidence_hash: str
    provider_attestation_adapter_evidence_hash: str
    operator_context_evidence_hash: str
    preflight_gate_evidence_hash: str
    restore_evidence_hash: str
    preflight_ready: bool
    enablement_gate_required: bool
    provider_adapter_required: bool
    operator_context_required: bool
    restore_evidence_required: bool
    operator_mfa_missing_blocked: bool
    secret_material_request_blocked: bool
    tampered_enablement_gate_blocked: bool
    future_real_connection_executor_required: bool
    network_socket_opened: bool = False
    network_connection_opened: bool = False
    real_connection_opened: bool = False
    secret_material_resolved: bool = False
    raw_data_access_allowed: bool = False
    import_dry_run_allowed: bool = False
    import_write_allowed: bool = False
    destructive_actions_allowed: bool = False
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str


def build_legacy_sql_connector_operator_context(
    *,
    profile: LegacySqlConnectorSandboxProfileEvidence,
    operator_principal_ref: str,
    change_request_ref: str,
    maintenance_window_ref: str,
    approval_reference: str,
    audit_chain_ref: str,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    operator_authorized_for_legacy_sql: bool = True,
    operator_mfa_verified: bool = True,
    compliance_window_active: bool = True,
    break_glass_requested: bool = False,
) -> LegacySqlConnectorOperatorContext:
    checked_at = checked_at_utc or datetime.now(UTC)
    draft = LegacySqlConnectorOperatorContext(
        tenant_id=profile.tenant_id,
        module_id=profile.module_id,
        source_system_ref=profile.source_system_ref,
        connector_kind=profile.connector_kind,
        sandbox_profile_ref=profile.sandbox_profile_ref,
        sandbox_profile_evidence_hash=profile.evidence_hash,
        operator_principal_ref=operator_principal_ref,
        change_request_ref=change_request_ref,
        maintenance_window_ref=maintenance_window_ref,
        approval_reference=approval_reference,
        audit_chain_ref=audit_chain_ref,
        operator_authorized_for_legacy_sql=operator_authorized_for_legacy_sql,
        operator_mfa_verified=operator_mfa_verified,
        compliance_window_active=compliance_window_active,
        break_glass_requested=break_glass_requested,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_connector_operator_context_hash(draft)})


def build_legacy_sql_connector_connection_preflight_command(
    *,
    profile: LegacySqlConnectorSandboxProfileEvidence,
    enablement_gate: LegacySqlConnectorSandboxEnablementGateEvidence,
    provider_adapter_evidence: LegacySqlConnectorProviderAttestationAdapterEvidence,
    operator_context: LegacySqlConnectorOperatorContext,
    restore_evidence_hash: str,
    requested_by: str,
    connection_attempt_preflight_requested: bool = True,
    network_socket_open_requested: bool = False,
    secret_material_resolution_requested: bool = False,
    raw_data_access_requested: bool = False,
    import_dry_run_requested: bool = False,
    import_write_requested: bool = False,
    destructive_actions_requested: bool = False,
) -> LegacySqlConnectorConnectionPreflightCommand:
    return LegacySqlConnectorConnectionPreflightCommand(
        tenant_id=profile.tenant_id,
        module_id=profile.module_id,
        source_system_ref=profile.source_system_ref,
        connector_kind=profile.connector_kind,
        sandbox_profile_ref=profile.sandbox_profile_ref,
        sandbox_profile_evidence_hash=profile.evidence_hash,
        enablement_gate_evidence_hash=enablement_gate.evidence_hash,
        provider_attestation_adapter_evidence_hash=provider_adapter_evidence.evidence_hash,
        operator_context_evidence_hash=operator_context.evidence_hash,
        restore_evidence_hash=restore_evidence_hash,
        requested_by=requested_by,
        connection_attempt_preflight_requested=connection_attempt_preflight_requested,
        network_socket_open_requested=network_socket_open_requested,
        secret_material_resolution_requested=secret_material_resolution_requested,
        raw_data_access_requested=raw_data_access_requested,
        import_dry_run_requested=import_dry_run_requested,
        import_write_requested=import_write_requested,
        destructive_actions_requested=destructive_actions_requested,
    )


def build_legacy_sql_connector_connection_preflight_gate(
    *,
    command: LegacySqlConnectorConnectionPreflightCommand,
    profile: LegacySqlConnectorSandboxProfileEvidence,
    enablement_gate: LegacySqlConnectorSandboxEnablementGateEvidence,
    provider_adapter_evidence: LegacySqlConnectorProviderAttestationAdapterEvidence,
    operator_context: LegacySqlConnectorOperatorContext,
    checked_by: str,
    checked_at_utc: datetime | None = None,
) -> LegacySqlConnectorConnectionPreflightEvidence:
    checked_at = checked_at_utc or datetime.now(UTC)
    sandbox_profile_hash_valid = (
        build_legacy_sql_connector_sandbox_profile_hash(profile)
        == profile.evidence_hash
        == command.sandbox_profile_evidence_hash
    )
    sandbox_profile_default_off = profile.profile_status == LegacySqlConnectorSandboxProfileStatus.DEFAULT_OFF
    sandbox_profile_visible = profile.sandbox_profile_visible and not profile.sandbox_profile_enabled
    enablement_gate_hash_valid = (
        build_legacy_sql_connector_sandbox_enablement_gate_hash(enablement_gate)
        == enablement_gate.evidence_hash
        == command.enablement_gate_evidence_hash
    )
    enablement_gate_ready = (
        enablement_gate.gate_status == LegacySqlConnectorSandboxEnablementGateStatus.READY
        and enablement_gate.connection_attempt_preparation_allowed
        and enablement_gate.future_real_connection_gate_required
    )
    provider_adapter_hash_valid = (
        build_legacy_sql_connector_provider_attestation_adapter_hash(provider_adapter_evidence)
        == provider_adapter_evidence.evidence_hash
        == command.provider_attestation_adapter_evidence_hash
    )
    provider_adapter_ready = (
        provider_adapter_evidence.adapter_status == LegacySqlConnectorProviderAttestationAdapterStatus.READY
        and provider_adapter_evidence.provider_attestation_ready
        and provider_adapter_evidence.provider_metadata_only_boundary_attested
    )
    operator_context_hash_valid = (
        build_legacy_sql_connector_operator_context_hash(operator_context)
        == operator_context.evidence_hash
        == command.operator_context_evidence_hash
    )
    enablement_gate_bound = _enablement_gate_bound(
        command=command,
        profile=profile,
        enablement_gate=enablement_gate,
        provider_adapter_evidence=provider_adapter_evidence,
    )
    provider_adapter_bound = _provider_adapter_bound(
        command=command,
        profile=profile,
        provider_adapter_evidence=provider_adapter_evidence,
        enablement_gate=enablement_gate,
    )
    operator_context_bound = _operator_context_bound(
        command=command,
        profile=profile,
        operator_context=operator_context,
    )
    restore_evidence_hash_valid = bool(re.fullmatch(SHA256_REF_PATTERN, command.restore_evidence_hash))
    evidence_chain_bound = (
        sandbox_profile_hash_valid
        and enablement_gate_hash_valid
        and provider_adapter_hash_valid
        and operator_context_hash_valid
        and enablement_gate_bound
        and provider_adapter_bound
        and operator_context_bound
    )
    blocking_reasons = _preflight_blocking_reasons(
        command=command,
        sandbox_profile_hash_valid=sandbox_profile_hash_valid,
        sandbox_profile_default_off=sandbox_profile_default_off,
        sandbox_profile_visible=sandbox_profile_visible,
        enablement_gate_hash_valid=enablement_gate_hash_valid,
        enablement_gate_ready=enablement_gate_ready,
        enablement_gate_bound=enablement_gate_bound,
        provider_adapter_hash_valid=provider_adapter_hash_valid,
        provider_adapter_ready=provider_adapter_ready,
        provider_adapter_bound=provider_adapter_bound,
        operator_context_hash_valid=operator_context_hash_valid,
        operator_context_bound=operator_context_bound,
        operator_context=operator_context,
        restore_evidence_hash_valid=restore_evidence_hash_valid,
        evidence_chain_bound=evidence_chain_bound,
    )
    ready = not blocking_reasons
    draft = LegacySqlConnectorConnectionPreflightEvidence(
        tenant_id=profile.tenant_id,
        module_id=profile.module_id,
        source_system_ref=profile.source_system_ref,
        connector_kind=profile.connector_kind,
        sandbox_profile_ref=profile.sandbox_profile_ref,
        sandbox_profile_evidence_hash=profile.evidence_hash,
        activation_evidence_hash=profile.activation_evidence_hash,
        queue_job_evidence_hash=profile.queue_job_evidence_hash,
        schedule_evidence_hash=profile.schedule_evidence_hash,
        release_gate_evidence_hash=profile.release_gate_evidence_hash,
        enablement_gate_evidence_hash=enablement_gate.evidence_hash,
        provider_attestation_adapter_evidence_hash=provider_adapter_evidence.evidence_hash,
        provider_attestation_hash=provider_adapter_evidence.provider_attestation_hash,
        operator_context_evidence_hash=operator_context.evidence_hash,
        restore_evidence_hash=command.restore_evidence_hash,
        operator_principal_ref=operator_context.operator_principal_ref,
        operator_role_ref=operator_context.operator_role_ref,
        change_request_ref=operator_context.change_request_ref,
        maintenance_window_ref=operator_context.maintenance_window_ref,
        approval_reference=operator_context.approval_reference,
        sandbox_profile_hash_valid=sandbox_profile_hash_valid,
        sandbox_profile_default_off=sandbox_profile_default_off,
        sandbox_profile_visible=sandbox_profile_visible,
        enablement_gate_hash_valid=enablement_gate_hash_valid,
        enablement_gate_ready=enablement_gate_ready,
        enablement_gate_bound=enablement_gate_bound,
        provider_adapter_hash_valid=provider_adapter_hash_valid,
        provider_adapter_ready=provider_adapter_ready,
        provider_adapter_bound=provider_adapter_bound,
        operator_context_hash_valid=operator_context_hash_valid,
        operator_context_bound=operator_context_bound,
        operator_authorized_for_legacy_sql=operator_context.operator_authorized_for_legacy_sql,
        operator_mfa_verified=operator_context.operator_mfa_verified,
        compliance_window_active=operator_context.compliance_window_active,
        break_glass_requested=operator_context.break_glass_requested,
        restore_evidence_hash_valid=restore_evidence_hash_valid,
        evidence_chain_bound=evidence_chain_bound,
        connection_attempt_preflight_requested=command.connection_attempt_preflight_requested,
        connection_attempt_preflight_ready=ready,
        network_socket_open_requested=command.network_socket_open_requested,
        secret_material_resolution_requested=command.secret_material_resolution_requested,
        raw_data_access_requested=command.raw_data_access_requested,
        import_dry_run_requested=command.import_dry_run_requested,
        import_write_requested=command.import_write_requested,
        destructive_actions_requested=command.destructive_actions_requested,
        gate_status=(
            LegacySqlConnectorConnectionPreflightStatus.READY
            if ready
            else LegacySqlConnectorConnectionPreflightStatus.BLOCKED
        ),
        blocking_reasons=blocking_reasons,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_connector_connection_preflight_hash(draft)})


def build_legacy_sql_connector_operator_context_hash(context: LegacySqlConnectorOperatorContext) -> str:
    return stable_hash(canonical_json(context.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_connection_preflight_hash(
    evidence: LegacySqlConnectorConnectionPreflightEvidence,
) -> str:
    return stable_hash(canonical_json(evidence.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_connection_preflight_smoke_report_hash(
    report: LegacySqlConnectorConnectionPreflightSmokeReport,
) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def run_legacy_sql_connector_connection_preflight_smoke_from_env(
    environ: Mapping[str, str] | None = None,
) -> LegacySqlConnectorConnectionPreflightSmokeReport:
    env = os.environ if environ is None else environ
    checked_by = env.get(
        "SUITE_LEGACY_SQL_CONNECTOR_CONNECTION_PREFLIGHT_CHECKED_BY",
        "legacy-sql-connector-connection-preflight-gate-smoke",
    )
    checked_at = datetime.now(UTC)
    queue_restore_hash = env.get("SUITE_LEGACY_SQL_METADATA_WORKER_QUEUE_RESTORE_HASH", "sha256:" + "1" * 64)
    enablement_restore_hash = env.get(
        "SUITE_LEGACY_SQL_CONNECTOR_CONNECTION_PREFLIGHT_ENABLEMENT_RESTORE_HASH",
        "sha256:" + "2" * 64,
    )
    preflight_restore_hash = env.get(
        "SUITE_LEGACY_SQL_CONNECTOR_CONNECTION_PREFLIGHT_RESTORE_HASH",
        "sha256:" + "3" * 64,
    )
    queue_backend = LegacySqlMetadataWorkerQueueBackend(
        env.get("SUITE_LEGACY_SQL_METADATA_WORKER_QUEUE_BACKEND", LegacySqlMetadataWorkerQueueBackend.JSONL.value)
    )
    profile = _sandbox_profile_from_env(
        env=env,
        checked_by=checked_by,
        checked_at=checked_at,
        restore_hash=queue_restore_hash,
    )
    provider_adapter = LegacySqlConnectorProviderAttestationAdapter()
    network_profile = build_legacy_sql_connector_network_deployment_profile(
        profile=profile,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=4),
    )
    secret_resolver_profile = build_legacy_sql_connector_secret_resolver_deployment_profile(
        profile=profile,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=5),
    )
    audit_profile = build_legacy_sql_connector_audit_deployment_profile(
        profile=profile,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=6),
    )
    provider_command = build_legacy_sql_connector_provider_attestation_adapter_command(
        profile=profile,
        network_profile=network_profile,
        secret_resolver_profile=secret_resolver_profile,
        audit_profile=audit_profile,
        requested_by=checked_by,
    )
    provider_result = provider_adapter.validate_provider_profiles(
        command=provider_command,
        profile=profile,
        network_profile=network_profile,
        secret_resolver_profile=secret_resolver_profile,
        audit_profile=audit_profile,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=7),
    )
    enablement_command = build_legacy_sql_connector_sandbox_enablement_command(
        profile=profile,
        provider_attestation=provider_result.provider_attestation,
        restore_evidence_hash=enablement_restore_hash,
        requested_by=checked_by,
        human_confirmation_reference=env.get(
            "SUITE_LEGACY_SQL_CONNECTOR_CONNECTION_PREFLIGHT_HUMAN_CONFIRMATION_REF",
            "human-confirmation:legacy-sql-connection-preflight-gate-smoke",
        ),
    )
    enablement_gate = build_legacy_sql_connector_sandbox_enablement_gate(
        command=enablement_command,
        profile=profile,
        provider_attestation=provider_result.provider_attestation,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=8),
    )
    operator_context = _operator_context_from_env(
        env=env,
        profile=profile,
        checked_by=checked_by,
        checked_at=checked_at + timedelta(seconds=9),
    )
    preflight_command = build_legacy_sql_connector_connection_preflight_command(
        profile=profile,
        enablement_gate=enablement_gate,
        provider_adapter_evidence=provider_result.adapter_evidence,
        operator_context=operator_context,
        restore_evidence_hash=preflight_restore_hash,
        requested_by=checked_by,
    )
    preflight_gate = build_legacy_sql_connector_connection_preflight_gate(
        command=preflight_command,
        profile=profile,
        enablement_gate=enablement_gate,
        provider_adapter_evidence=provider_result.adapter_evidence,
        operator_context=operator_context,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=10),
    )
    operator_mfa_missing_blocked = _operator_mfa_missing_blocked(
        command=preflight_command,
        profile=profile,
        enablement_gate=enablement_gate,
        provider_adapter_evidence=provider_result.adapter_evidence,
        operator_context=operator_context,
        checked_by=checked_by,
        checked_at=checked_at + timedelta(seconds=11),
    )
    secret_material_request_blocked = _secret_material_request_blocked(
        command=preflight_command,
        profile=profile,
        enablement_gate=enablement_gate,
        provider_adapter_evidence=provider_result.adapter_evidence,
        operator_context=operator_context,
        checked_by=checked_by,
        checked_at=checked_at + timedelta(seconds=12),
    )
    tampered_enablement_gate_blocked = _tampered_enablement_gate_blocked(
        command=preflight_command,
        profile=profile,
        enablement_gate=enablement_gate,
        provider_adapter_evidence=provider_result.adapter_evidence,
        operator_context=operator_context,
        checked_by=checked_by,
        checked_at=checked_at + timedelta(seconds=13),
    )
    preflight_ready = (
        preflight_gate.gate_status == LegacySqlConnectorConnectionPreflightStatus.READY
        and preflight_gate.connection_attempt_preflight_ready
        and operator_mfa_missing_blocked
        and secret_material_request_blocked
        and tampered_enablement_gate_blocked
        and not preflight_gate.network_socket_opened
        and not preflight_gate.secret_material_resolved
        and not preflight_gate.real_connection_opened
        and not preflight_gate.raw_data_access_allowed
        and not preflight_gate.import_dry_run_allowed
        and not preflight_gate.import_write_allowed
    )
    draft = LegacySqlConnectorConnectionPreflightSmokeReport(
        tenant_id=profile.tenant_id,
        queue_backend=queue_backend,
        sandbox_profile_ref=profile.sandbox_profile_ref,
        sandbox_profile_evidence_hash=profile.evidence_hash,
        enablement_gate_evidence_hash=enablement_gate.evidence_hash,
        provider_attestation_adapter_evidence_hash=provider_result.adapter_evidence.evidence_hash,
        operator_context_evidence_hash=operator_context.evidence_hash,
        preflight_gate_evidence_hash=preflight_gate.evidence_hash,
        restore_evidence_hash=preflight_restore_hash,
        preflight_ready=preflight_ready,
        enablement_gate_required=preflight_gate.enablement_gate_ready and preflight_gate.enablement_gate_bound,
        provider_adapter_required=preflight_gate.provider_adapter_ready and preflight_gate.provider_adapter_bound,
        operator_context_required=preflight_gate.operator_context_bound and preflight_gate.operator_mfa_verified,
        restore_evidence_required=preflight_gate.restore_evidence_hash_valid,
        operator_mfa_missing_blocked=operator_mfa_missing_blocked,
        secret_material_request_blocked=secret_material_request_blocked,
        tampered_enablement_gate_blocked=tampered_enablement_gate_blocked,
        future_real_connection_executor_required=preflight_gate.future_real_connection_executor_required,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    _assert_preflight_safe(draft)
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_connection_preflight_smoke_report_hash(draft)}
    )


def exit_code_for_report(report: LegacySqlConnectorConnectionPreflightSmokeReport) -> int:
    return 0 if report.preflight_ready else 1


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Legacy SQL connector connection preflight gate smoke.")
    parser.add_argument("--once", action="store_true", help="Run one no-secret/no-socket preflight smoke and exit.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the preflight report.")
    args = parser.parse_args(argv)
    del args.once

    report = run_legacy_sql_connector_connection_preflight_smoke_from_env()
    print(json.dumps(report.model_dump(mode="json"), indent=2 if args.pretty else None, sort_keys=True))
    raise SystemExit(exit_code_for_report(report))


def _sandbox_profile_from_env(
    *,
    env: Mapping[str, str],
    checked_by: str,
    checked_at: datetime,
    restore_hash: str,
) -> LegacySqlConnectorSandboxProfileEvidence:
    gate_smoke = run_legacy_sql_host_profile_release_gate_smoke_from_env(env)
    gate_store = build_default_legacy_sql_host_profile_release_gate_evidence_store(environ=env)
    adapter = LegacySqlHostProfileAdapter(gate_store=gate_store)
    schedule = adapter.prepare_metadata_worker_schedule(
        request=build_legacy_sql_host_profile_adapter_schedule_request_from_gate_smoke(
            env=env,
            gate_smoke=gate_smoke,
            release_gate_evidence_hash=gate_smoke.ready_gate_evidence_hash,
            checked_by=checked_by,
        ),
        checked_at_utc=checked_at,
    )
    store = build_default_legacy_sql_metadata_worker_queue_store(environ=env)
    queued = build_legacy_sql_metadata_worker_queue_job(
        schedule_evidence=schedule,
        restore_evidence_hash=restore_hash,
        enqueued_at_utc=checked_at,
    )
    store.enqueue(queued)
    leased = store.lease_next(
        tenant_id=schedule.tenant_id,
        lease_owner=checked_by,
        lease_duration_seconds=60,
        now=checked_at + timedelta(seconds=1),
    )
    if leased is None:
        raise RuntimeError("legacy SQL connection preflight smoke could not acquire a queue lease")
    activation = LegacySqlMetadataWorkerLeaseConsumer().validate_leased_job(
        job=leased,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=2),
    )
    return build_legacy_sql_connector_sandbox_profile(
        activation=activation,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=3),
    )


def _operator_context_from_env(
    *,
    env: Mapping[str, str],
    profile: LegacySqlConnectorSandboxProfileEvidence,
    checked_by: str,
    checked_at: datetime,
) -> LegacySqlConnectorOperatorContext:
    return build_legacy_sql_connector_operator_context(
        profile=profile,
        operator_principal_ref=env.get(
            "SUITE_LEGACY_SQL_CONNECTOR_CONNECTION_PREFLIGHT_OPERATOR_REF",
            "principal:legacy-sql-operator",
        ),
        change_request_ref=env.get(
            "SUITE_LEGACY_SQL_CONNECTOR_CONNECTION_PREFLIGHT_CHANGE_REQUEST_REF",
            "change-request:legacy-sql-connection-preflight",
        ),
        maintenance_window_ref=env.get(
            "SUITE_LEGACY_SQL_CONNECTOR_CONNECTION_PREFLIGHT_MAINTENANCE_WINDOW_REF",
            "maintenance-window:legacy-sql-connection-preflight",
        ),
        approval_reference=env.get(
            "SUITE_LEGACY_SQL_CONNECTOR_CONNECTION_PREFLIGHT_APPROVAL_REF",
            "approval:legacy-sql-connection-preflight",
        ),
        audit_chain_ref=env.get(
            "SUITE_LEGACY_SQL_CONNECTOR_CONNECTION_PREFLIGHT_AUDIT_REF",
            "audit:legacy-sql-connection-preflight",
        ),
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )


def _enablement_gate_bound(
    *,
    command: LegacySqlConnectorConnectionPreflightCommand,
    profile: LegacySqlConnectorSandboxProfileEvidence,
    enablement_gate: LegacySqlConnectorSandboxEnablementGateEvidence,
    provider_adapter_evidence: LegacySqlConnectorProviderAttestationAdapterEvidence,
) -> bool:
    return (
        command.tenant_id == profile.tenant_id == enablement_gate.tenant_id
        and command.module_id == profile.module_id == enablement_gate.module_id
        and command.source_system_ref == profile.source_system_ref == enablement_gate.source_system_ref
        and command.connector_kind == profile.connector_kind == enablement_gate.connector_kind
        and command.sandbox_profile_ref == profile.sandbox_profile_ref == enablement_gate.sandbox_profile_ref
        and command.sandbox_profile_evidence_hash
        == profile.evidence_hash
        == enablement_gate.sandbox_profile_evidence_hash
        and enablement_gate.provider_attestation_hash == provider_adapter_evidence.provider_attestation_hash
        and not enablement_gate.connection_materialization_allowed
        and not enablement_gate.secret_material_resolution_allowed
        and not enablement_gate.network_connection_opened
        and not enablement_gate.real_connection_opened
        and not enablement_gate.raw_data_access_allowed
        and not enablement_gate.import_dry_run_allowed
        and not enablement_gate.import_write_allowed
        and not enablement_gate.destructive_actions_allowed
    )


def _provider_adapter_bound(
    *,
    command: LegacySqlConnectorConnectionPreflightCommand,
    profile: LegacySqlConnectorSandboxProfileEvidence,
    provider_adapter_evidence: LegacySqlConnectorProviderAttestationAdapterEvidence,
    enablement_gate: LegacySqlConnectorSandboxEnablementGateEvidence,
) -> bool:
    return (
        command.tenant_id == profile.tenant_id == provider_adapter_evidence.tenant_id
        and command.module_id == profile.module_id == provider_adapter_evidence.module_id
        and command.source_system_ref == profile.source_system_ref == provider_adapter_evidence.source_system_ref
        and command.connector_kind == profile.connector_kind == provider_adapter_evidence.connector_kind
        and command.sandbox_profile_ref == profile.sandbox_profile_ref == provider_adapter_evidence.sandbox_profile_ref
        and command.sandbox_profile_evidence_hash
        == profile.evidence_hash
        == provider_adapter_evidence.sandbox_profile_evidence_hash
        and provider_adapter_evidence.provider_attestation_hash == enablement_gate.provider_attestation_hash
        and not provider_adapter_evidence.network_connection_opened
        and not provider_adapter_evidence.real_connection_opened
        and not provider_adapter_evidence.secret_material_resolved
        and not provider_adapter_evidence.raw_data_access_allowed
        and not provider_adapter_evidence.import_dry_run_allowed
        and not provider_adapter_evidence.import_write_allowed
        and not provider_adapter_evidence.destructive_actions_allowed
    )


def _operator_context_bound(
    *,
    command: LegacySqlConnectorConnectionPreflightCommand,
    profile: LegacySqlConnectorSandboxProfileEvidence,
    operator_context: LegacySqlConnectorOperatorContext,
) -> bool:
    return (
        command.tenant_id == profile.tenant_id == operator_context.tenant_id
        and command.module_id == profile.module_id == operator_context.module_id
        and command.source_system_ref == profile.source_system_ref == operator_context.source_system_ref
        and command.connector_kind == profile.connector_kind == operator_context.connector_kind
        and command.sandbox_profile_ref == profile.sandbox_profile_ref == operator_context.sandbox_profile_ref
        and command.sandbox_profile_evidence_hash
        == profile.evidence_hash
        == operator_context.sandbox_profile_evidence_hash
    )


def _preflight_blocking_reasons(
    *,
    command: LegacySqlConnectorConnectionPreflightCommand,
    sandbox_profile_hash_valid: bool,
    sandbox_profile_default_off: bool,
    sandbox_profile_visible: bool,
    enablement_gate_hash_valid: bool,
    enablement_gate_ready: bool,
    enablement_gate_bound: bool,
    provider_adapter_hash_valid: bool,
    provider_adapter_ready: bool,
    provider_adapter_bound: bool,
    operator_context_hash_valid: bool,
    operator_context_bound: bool,
    operator_context: LegacySqlConnectorOperatorContext,
    restore_evidence_hash_valid: bool,
    evidence_chain_bound: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not sandbox_profile_hash_valid:
        reasons.append("sandbox_profile_hash_invalid")
    if not sandbox_profile_default_off:
        reasons.append("sandbox_profile_not_default_off")
    if not sandbox_profile_visible:
        reasons.append("sandbox_profile_not_visible")
    if not enablement_gate_hash_valid:
        reasons.append("enablement_gate_hash_invalid")
    if not enablement_gate_ready:
        reasons.append("enablement_gate_not_ready")
    if not enablement_gate_bound:
        reasons.append("enablement_gate_not_bound")
    if not provider_adapter_hash_valid:
        reasons.append("provider_attestation_adapter_hash_invalid")
    if not provider_adapter_ready:
        reasons.append("provider_attestation_adapter_not_ready")
    if not provider_adapter_bound:
        reasons.append("provider_attestation_adapter_not_bound")
    if not operator_context_hash_valid:
        reasons.append("operator_context_hash_invalid")
    if not operator_context_bound:
        reasons.append("operator_context_not_bound")
    if not operator_context.operator_authorized_for_legacy_sql:
        reasons.append("operator_not_authorized_for_legacy_sql")
    if not operator_context.operator_mfa_verified:
        reasons.append("operator_mfa_not_verified")
    if not operator_context.compliance_window_active:
        reasons.append("operator_compliance_window_inactive")
    if operator_context.break_glass_requested:
        reasons.append("break_glass_requires_separate_incident_gate")
    if not restore_evidence_hash_valid:
        reasons.append("restore_evidence_hash_invalid")
    if not evidence_chain_bound:
        reasons.append("preflight_evidence_chain_not_bound")
    if not command.connection_attempt_preflight_requested:
        reasons.append("connection_attempt_preflight_not_requested")
    if command.network_socket_open_requested:
        reasons.append("network_socket_request_requires_future_executor")
    if command.secret_material_resolution_requested:
        reasons.append("secret_material_resolution_request_requires_future_executor")
    if command.raw_data_access_requested:
        reasons.append("raw_data_access_request_requires_separate_gate")
    if command.import_dry_run_requested:
        reasons.append("import_dry_run_request_requires_separate_gate")
    if command.import_write_requested:
        reasons.append("import_write_request_requires_separate_gate")
    if command.destructive_actions_requested:
        reasons.append("destructive_action_request_requires_separate_gate")
    return tuple(sorted(set(reasons)))


def _operator_mfa_missing_blocked(
    *,
    command: LegacySqlConnectorConnectionPreflightCommand,
    profile: LegacySqlConnectorSandboxProfileEvidence,
    enablement_gate: LegacySqlConnectorSandboxEnablementGateEvidence,
    provider_adapter_evidence: LegacySqlConnectorProviderAttestationAdapterEvidence,
    operator_context: LegacySqlConnectorOperatorContext,
    checked_by: str,
    checked_at: datetime,
) -> bool:
    blocked_context = operator_context.model_copy(
        update={"operator_mfa_verified": False, "checked_at_utc": checked_at, "evidence_hash": ZERO_HASH}
    )
    blocked_context = blocked_context.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_operator_context_hash(blocked_context)}
    )
    blocked_command = command.model_copy(update={"operator_context_evidence_hash": blocked_context.evidence_hash})
    blocked = build_legacy_sql_connector_connection_preflight_gate(
        command=blocked_command,
        profile=profile,
        enablement_gate=enablement_gate,
        provider_adapter_evidence=provider_adapter_evidence,
        operator_context=blocked_context,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        blocked.gate_status == LegacySqlConnectorConnectionPreflightStatus.BLOCKED
        and "operator_mfa_not_verified" in blocked.blocking_reasons
    )


def _secret_material_request_blocked(
    *,
    command: LegacySqlConnectorConnectionPreflightCommand,
    profile: LegacySqlConnectorSandboxProfileEvidence,
    enablement_gate: LegacySqlConnectorSandboxEnablementGateEvidence,
    provider_adapter_evidence: LegacySqlConnectorProviderAttestationAdapterEvidence,
    operator_context: LegacySqlConnectorOperatorContext,
    checked_by: str,
    checked_at: datetime,
) -> bool:
    blocked = build_legacy_sql_connector_connection_preflight_gate(
        command=command.model_copy(update={"secret_material_resolution_requested": True}),
        profile=profile,
        enablement_gate=enablement_gate,
        provider_adapter_evidence=provider_adapter_evidence,
        operator_context=operator_context,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        blocked.gate_status == LegacySqlConnectorConnectionPreflightStatus.BLOCKED
        and "secret_material_resolution_request_requires_future_executor" in blocked.blocking_reasons
    )


def _tampered_enablement_gate_blocked(
    *,
    command: LegacySqlConnectorConnectionPreflightCommand,
    profile: LegacySqlConnectorSandboxProfileEvidence,
    enablement_gate: LegacySqlConnectorSandboxEnablementGateEvidence,
    provider_adapter_evidence: LegacySqlConnectorProviderAttestationAdapterEvidence,
    operator_context: LegacySqlConnectorOperatorContext,
    checked_by: str,
    checked_at: datetime,
) -> bool:
    tampered_gate = enablement_gate.model_copy(update={"evidence_hash": "sha256:" + "f" * 64})
    blocked = build_legacy_sql_connector_connection_preflight_gate(
        command=command,
        profile=profile,
        enablement_gate=tampered_gate,
        provider_adapter_evidence=provider_adapter_evidence,
        operator_context=operator_context,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        blocked.gate_status == LegacySqlConnectorConnectionPreflightStatus.BLOCKED
        and "enablement_gate_hash_invalid" in blocked.blocking_reasons
    )


def _assert_preflight_safe(value: BaseModel) -> None:
    payload = value.model_dump_json().lower()
    for fragment in FORBIDDEN_PREFLIGHT_FRAGMENTS:
        if fragment in payload:
            raise ValueError(f"legacy SQL connector preflight leaked forbidden fragment: {fragment}")


if __name__ == "__main__":
    main()
