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
from suite.platform.legacy_sql_metadata_worker_lease_consumer import (
    LegacySqlMetadataWorkerLeaseConsumer,
    LegacySqlMetadataWorkerLeaseConsumerActivationEvidence,
)
from suite.platform.legacy_sql_metadata_worker_queue import (
    LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN,
    LegacySqlMetadataWorkerQueueBackend,
    build_default_legacy_sql_metadata_worker_queue_store,
    build_legacy_sql_metadata_worker_queue_job,
)
from suite.platform.legacy_sql_server_metadata import LegacySqlServerNetworkMode

LEGACY_SQL_CONNECTOR_SANDBOX_PROVIDER_ATTESTATION_SCHEMA_VERSION = (
    "legacy_sql_connector_sandbox_provider_attestation.v1"
)
LEGACY_SQL_CONNECTOR_SANDBOX_ENABLEMENT_GATE_SCHEMA_VERSION = "legacy_sql_connector_sandbox_enablement_gate.v1"
LEGACY_SQL_CONNECTOR_SANDBOX_ENABLEMENT_GATE_SMOKE_SCHEMA_VERSION = (
    "legacy_sql_connector_sandbox_enablement_gate_smoke_report.v1"
)
LEGACY_SQL_CONNECTOR_SANDBOX_ENABLEMENT_GATE_COMMAND_REF = (
    "docker-compose:legacy-sql-connector-sandbox-enablement-gate-smoke"
)
LEGACY_SQL_CONNECTOR_SANDBOX_PROVIDER_ATTESTATION_REF_PREFIX = "provider-attestation:legacy-sql-connector-sandbox"
ZERO_HASH = "sha256:" + "0" * 64
SHA256_REF_PATTERN = r"^sha256:[a-f0-9]{64}$"
FORBIDDEN_ENABLEMENT_GATE_FRAGMENTS = (
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


class LegacySqlConnectorSandboxEnablementGateStatus(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"


class LegacySqlConnectorSandboxProviderAttestation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_SANDBOX_PROVIDER_ATTESTATION_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    sandbox_profile_ref: str
    sandbox_profile_evidence_hash: str
    connector_network_profile_ref: str
    secret_resolver_profile_ref: str
    audit_profile_ref: str
    provider_attestation_ref: str
    network_profile_attestation_hash: str
    secret_resolver_attestation_hash: str
    audit_profile_attestation_hash: str
    provider_metadata_only_boundary_attested: bool
    network_profile_attested: bool
    secret_resolver_attested: bool
    audit_profile_attested: bool
    secret_material_available_to_gate: bool = False
    network_connection_materialized: bool = False
    raw_data_access_attested: bool = False
    import_dry_run_attested: bool = False
    import_write_attested: bool = False
    destructive_actions_attested: bool = False
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL connector sandbox provider attestation text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL connector sandbox provider attestation module_id must be lowercase snake_case")
        return value

    @field_validator(
        "source_system_ref",
        "sandbox_profile_ref",
        "connector_network_profile_ref",
        "secret_resolver_profile_ref",
        "audit_profile_ref",
        "provider_attestation_ref",
    )
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL connector sandbox provider attestation references must be namespaced")
        return value

    @field_validator(
        "sandbox_profile_evidence_hash",
        "network_profile_attestation_hash",
        "secret_resolver_attestation_hash",
        "audit_profile_attestation_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL connector sandbox provider attestation hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_metadata_only_provider_attestation(self) -> Self:
        if (
            self.secret_material_available_to_gate
            or self.network_connection_materialized
            or self.raw_data_access_attested
            or self.import_dry_run_attested
            or self.import_write_attested
            or self.destructive_actions_attested
        ):
            raise ValueError("legacy SQL connector sandbox provider attestation must stay metadata-only")
        _assert_enablement_gate_safe(self)
        return self


class LegacySqlConnectorSandboxEnablementCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    sandbox_profile_ref: str
    sandbox_profile_evidence_hash: str
    provider_attestation_ref: str
    provider_attestation_hash: str
    restore_evidence_hash: str
    requested_by: str
    human_confirmation_reference: str
    human_confirmation: bool
    connection_attempt_preparation_requested: bool = True
    raw_data_access_requested: bool = False
    import_dry_run_requested: bool = False
    import_write_requested: bool = False
    destructive_actions_requested: bool = False

    @field_validator("tenant_id", "requested_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL connector sandbox enablement command text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL connector sandbox enablement command module_id must be lowercase snake_case")
        return value

    @field_validator(
        "source_system_ref",
        "sandbox_profile_ref",
        "provider_attestation_ref",
        "human_confirmation_reference",
    )
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL connector sandbox enablement command references must be namespaced")
        return value

    @field_validator("sandbox_profile_evidence_hash", "provider_attestation_hash", "restore_evidence_hash")
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL connector sandbox enablement command hashes must be sha256 references")
        return value


class LegacySqlConnectorSandboxEnablementGateEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_SANDBOX_ENABLEMENT_GATE_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    continuity_domain: str = LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN
    command_ref: str = LEGACY_SQL_CONNECTOR_SANDBOX_ENABLEMENT_GATE_COMMAND_REF
    sandbox_profile_ref: str
    sandbox_profile_evidence_hash: str
    activation_evidence_hash: str
    queue_job_evidence_hash: str
    schedule_evidence_hash: str
    release_gate_evidence_hash: str
    host_profile_ref: str
    connector_network_profile_ref: str
    secret_resolver_profile_ref: str
    audit_profile_ref: str
    provider_attestation_ref: str
    provider_attestation_hash: str
    network_profile_attestation_hash: str
    secret_resolver_attestation_hash: str
    audit_profile_attestation_hash: str
    restore_evidence_hash: str
    requested_by: str
    human_confirmation_reference: str
    sandbox_profile_hash_valid: bool
    sandbox_profile_default_off: bool
    sandbox_profile_visible: bool
    sandbox_profile_enablement_allowed: bool
    provider_attestation_hash_valid: bool
    provider_attestation_bound: bool
    provider_metadata_only_boundary_attested: bool
    network_profile_attested: bool
    secret_resolver_attested: bool
    audit_profile_attested: bool
    restore_evidence_hash_valid: bool
    human_confirmation_verified: bool
    connection_attempt_preparation_requested: bool
    connection_attempt_preparation_allowed: bool
    future_real_connection_gate_required: bool = True
    connection_materialization_allowed: bool = False
    secret_material_resolution_allowed: bool = False
    egress_connection_materialized: bool = False
    default_compose_legacy_network_enabled: bool = False
    network_connection_opened: bool = False
    real_connection_opened: bool = False
    raw_data_access_requested: bool = False
    raw_data_access_allowed: bool = False
    import_dry_run_requested: bool = False
    import_dry_run_allowed: bool = False
    import_write_requested: bool = False
    import_write_allowed: bool = False
    destructive_actions_requested: bool = False
    destructive_actions_allowed: bool = False
    gate_status: LegacySqlConnectorSandboxEnablementGateStatus
    blocking_reasons: tuple[str, ...]
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "requested_by", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL connector sandbox enablement gate text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL connector sandbox enablement gate module_id must be lowercase snake_case")
        return value

    @field_validator(
        "source_system_ref",
        "sandbox_profile_ref",
        "host_profile_ref",
        "connector_network_profile_ref",
        "secret_resolver_profile_ref",
        "audit_profile_ref",
        "provider_attestation_ref",
        "human_confirmation_reference",
    )
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL connector sandbox enablement gate references must be namespaced")
        return value

    @field_validator(
        "sandbox_profile_evidence_hash",
        "activation_evidence_hash",
        "queue_job_evidence_hash",
        "schedule_evidence_hash",
        "release_gate_evidence_hash",
        "provider_attestation_hash",
        "network_profile_attestation_hash",
        "secret_resolver_attestation_hash",
        "audit_profile_attestation_hash",
        "restore_evidence_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL connector sandbox enablement gate hashes must be sha256 references")
        return value

    @field_validator("blocking_reasons")
    @classmethod
    def validate_blocking_reasons(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("legacy SQL connector sandbox enablement gate blocking reasons must be unique")
        for reason in value:
            if not reason.strip():
                raise ValueError("legacy SQL connector sandbox enablement gate blocking reasons must not be empty")
        return value

    @model_validator(mode="after")
    def require_safe_enablement_gate(self) -> Self:
        unsafe_allowed = (
            self.connection_materialization_allowed
            or self.secret_material_resolution_allowed
            or self.egress_connection_materialized
            or self.default_compose_legacy_network_enabled
            or self.network_connection_opened
            or self.real_connection_opened
            or self.raw_data_access_allowed
            or self.import_dry_run_allowed
            or self.import_write_allowed
            or self.destructive_actions_allowed
        )
        if unsafe_allowed:
            raise ValueError("legacy SQL connector sandbox enablement gate must not materialize connections or imports")
        if not self.future_real_connection_gate_required:
            raise ValueError("legacy SQL connector sandbox enablement gate must require a future real-connection gate")
        if self.gate_status == LegacySqlConnectorSandboxEnablementGateStatus.READY:
            required = (
                self.sandbox_profile_hash_valid,
                self.sandbox_profile_default_off,
                self.sandbox_profile_visible,
                self.sandbox_profile_enablement_allowed,
                self.provider_attestation_hash_valid,
                self.provider_attestation_bound,
                self.provider_metadata_only_boundary_attested,
                self.network_profile_attested,
                self.secret_resolver_attested,
                self.audit_profile_attested,
                self.restore_evidence_hash_valid,
                self.human_confirmation_verified,
                self.connection_attempt_preparation_requested,
                self.connection_attempt_preparation_allowed,
            )
            if not all(required) or self.blocking_reasons:
                raise ValueError("ready legacy SQL connector sandbox enablement gate requires complete evidence")
        if self.gate_status == LegacySqlConnectorSandboxEnablementGateStatus.BLOCKED:
            if not self.blocking_reasons:
                raise ValueError("blocked legacy SQL connector sandbox enablement gate requires blocking reasons")
            if self.connection_attempt_preparation_allowed or self.sandbox_profile_enablement_allowed:
                raise ValueError("blocked legacy SQL connector sandbox enablement gate cannot allow preparation")
        _assert_enablement_gate_safe(self)
        return self


class LegacySqlConnectorSandboxEnablementGateSmokeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_SANDBOX_ENABLEMENT_GATE_SMOKE_SCHEMA_VERSION
    tenant_id: str
    queue_backend: LegacySqlMetadataWorkerQueueBackend
    continuity_domain: str = LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN
    command_ref: str = LEGACY_SQL_CONNECTOR_SANDBOX_ENABLEMENT_GATE_COMMAND_REF
    sandbox_profile_ref: str
    sandbox_profile_evidence_hash: str
    provider_attestation_ref: str
    provider_attestation_hash: str
    enablement_gate_evidence_hash: str
    restore_evidence_hash: str
    ready_gate_created: bool
    explicit_human_confirmation_required: bool
    provider_attestation_required: bool
    restore_evidence_required: bool
    sandbox_profile_hash_required: bool
    missing_human_confirmation_blocked: bool
    unsafe_import_request_blocked: bool
    tampered_profile_hash_blocked: bool
    connection_attempt_preparation_allowed: bool
    sandbox_profile_enablement_allowed: bool
    future_real_connection_gate_required: bool
    connection_materialization_allowed: bool = False
    secret_material_resolution_allowed: bool = False
    egress_connection_materialized: bool = False
    default_compose_legacy_network_enabled: bool = False
    network_connection_opened: bool = False
    real_connection_opened: bool = False
    raw_data_access_allowed: bool = False
    import_dry_run_allowed: bool = False
    import_write_allowed: bool = False
    destructive_actions_allowed: bool = False
    enablement_gate_ready: bool
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str


def build_legacy_sql_connector_sandbox_provider_attestation(
    *,
    profile: LegacySqlConnectorSandboxProfileEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    provider_metadata_only_boundary_attested: bool = True,
    network_profile_attested: bool = True,
    secret_resolver_attested: bool = True,
    audit_profile_attested: bool = True,
) -> LegacySqlConnectorSandboxProviderAttestation:
    checked_at = checked_at_utc or datetime.now(UTC)
    provider_ref = legacy_sql_connector_sandbox_provider_attestation_ref(profile)
    draft = LegacySqlConnectorSandboxProviderAttestation(
        tenant_id=profile.tenant_id,
        module_id=profile.module_id,
        source_system_ref=profile.source_system_ref,
        connector_kind=profile.connector_kind,
        sandbox_profile_ref=profile.sandbox_profile_ref,
        sandbox_profile_evidence_hash=profile.evidence_hash,
        connector_network_profile_ref=profile.connector_network_profile_ref,
        secret_resolver_profile_ref=profile.secret_resolver_profile_ref,
        audit_profile_ref=profile.audit_profile_ref,
        provider_attestation_ref=provider_ref,
        network_profile_attestation_hash=_provider_component_attestation_hash(
            profile=profile,
            provider_attestation_ref=provider_ref,
            component_ref=profile.connector_network_profile_ref,
            component_kind="network_profile",
        ),
        secret_resolver_attestation_hash=_provider_component_attestation_hash(
            profile=profile,
            provider_attestation_ref=provider_ref,
            component_ref=profile.secret_resolver_profile_ref,
            component_kind="secret_resolver",
        ),
        audit_profile_attestation_hash=_provider_component_attestation_hash(
            profile=profile,
            provider_attestation_ref=provider_ref,
            component_ref=profile.audit_profile_ref,
            component_kind="audit_profile",
        ),
        provider_metadata_only_boundary_attested=provider_metadata_only_boundary_attested,
        network_profile_attested=network_profile_attested,
        secret_resolver_attested=secret_resolver_attested,
        audit_profile_attested=audit_profile_attested,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_sandbox_provider_attestation_hash(draft)}
    )


def build_legacy_sql_connector_sandbox_enablement_command(
    *,
    profile: LegacySqlConnectorSandboxProfileEvidence,
    provider_attestation: LegacySqlConnectorSandboxProviderAttestation,
    restore_evidence_hash: str,
    requested_by: str,
    human_confirmation_reference: str,
    human_confirmation: bool = True,
    connection_attempt_preparation_requested: bool = True,
    raw_data_access_requested: bool = False,
    import_dry_run_requested: bool = False,
    import_write_requested: bool = False,
    destructive_actions_requested: bool = False,
) -> LegacySqlConnectorSandboxEnablementCommand:
    return LegacySqlConnectorSandboxEnablementCommand(
        tenant_id=profile.tenant_id,
        module_id=profile.module_id,
        source_system_ref=profile.source_system_ref,
        connector_kind=profile.connector_kind,
        sandbox_profile_ref=profile.sandbox_profile_ref,
        sandbox_profile_evidence_hash=profile.evidence_hash,
        provider_attestation_ref=provider_attestation.provider_attestation_ref,
        provider_attestation_hash=provider_attestation.evidence_hash,
        restore_evidence_hash=restore_evidence_hash,
        requested_by=requested_by,
        human_confirmation_reference=human_confirmation_reference,
        human_confirmation=human_confirmation,
        connection_attempt_preparation_requested=connection_attempt_preparation_requested,
        raw_data_access_requested=raw_data_access_requested,
        import_dry_run_requested=import_dry_run_requested,
        import_write_requested=import_write_requested,
        destructive_actions_requested=destructive_actions_requested,
    )


def build_legacy_sql_connector_sandbox_enablement_gate(
    *,
    command: LegacySqlConnectorSandboxEnablementCommand,
    profile: LegacySqlConnectorSandboxProfileEvidence,
    provider_attestation: LegacySqlConnectorSandboxProviderAttestation,
    checked_by: str,
    checked_at_utc: datetime | None = None,
) -> LegacySqlConnectorSandboxEnablementGateEvidence:
    checked_at = checked_at_utc or datetime.now(UTC)
    sandbox_profile_hash_valid = (
        build_legacy_sql_connector_sandbox_profile_hash(profile)
        == profile.evidence_hash
        == command.sandbox_profile_evidence_hash
    )
    sandbox_profile_default_off = profile.profile_status == LegacySqlConnectorSandboxProfileStatus.DEFAULT_OFF
    sandbox_profile_visible = profile.sandbox_profile_visible and not profile.sandbox_profile_enabled
    provider_attestation_hash_valid = (
        build_legacy_sql_connector_sandbox_provider_attestation_hash(provider_attestation)
        == provider_attestation.evidence_hash
        == command.provider_attestation_hash
    )
    provider_attestation_bound = _provider_attestation_bound(
        command=command,
        profile=profile,
        provider_attestation=provider_attestation,
    )
    restore_evidence_hash_valid = bool(re.fullmatch(SHA256_REF_PATTERN, command.restore_evidence_hash))
    human_confirmation_verified = command.human_confirmation and bool(command.human_confirmation_reference.strip())
    metadata_only_attested = (
        provider_attestation.provider_metadata_only_boundary_attested
        and provider_attestation.network_profile_attested
        and provider_attestation.secret_resolver_attested
        and provider_attestation.audit_profile_attested
    )
    blocking_reasons = _enablement_gate_blocking_reasons(
        command=command,
        sandbox_profile_hash_valid=sandbox_profile_hash_valid,
        sandbox_profile_default_off=sandbox_profile_default_off,
        sandbox_profile_visible=sandbox_profile_visible,
        provider_attestation_hash_valid=provider_attestation_hash_valid,
        provider_attestation_bound=provider_attestation_bound,
        metadata_only_attested=metadata_only_attested,
        restore_evidence_hash_valid=restore_evidence_hash_valid,
        human_confirmation_verified=human_confirmation_verified,
    )
    ready = not blocking_reasons
    draft = LegacySqlConnectorSandboxEnablementGateEvidence(
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
        host_profile_ref=profile.host_profile_ref,
        connector_network_profile_ref=profile.connector_network_profile_ref,
        secret_resolver_profile_ref=profile.secret_resolver_profile_ref,
        audit_profile_ref=profile.audit_profile_ref,
        provider_attestation_ref=provider_attestation.provider_attestation_ref,
        provider_attestation_hash=provider_attestation.evidence_hash,
        network_profile_attestation_hash=provider_attestation.network_profile_attestation_hash,
        secret_resolver_attestation_hash=provider_attestation.secret_resolver_attestation_hash,
        audit_profile_attestation_hash=provider_attestation.audit_profile_attestation_hash,
        restore_evidence_hash=command.restore_evidence_hash,
        requested_by=command.requested_by,
        human_confirmation_reference=command.human_confirmation_reference,
        sandbox_profile_hash_valid=sandbox_profile_hash_valid,
        sandbox_profile_default_off=sandbox_profile_default_off,
        sandbox_profile_visible=sandbox_profile_visible,
        sandbox_profile_enablement_allowed=ready,
        provider_attestation_hash_valid=provider_attestation_hash_valid,
        provider_attestation_bound=provider_attestation_bound,
        provider_metadata_only_boundary_attested=provider_attestation.provider_metadata_only_boundary_attested,
        network_profile_attested=provider_attestation.network_profile_attested,
        secret_resolver_attested=provider_attestation.secret_resolver_attested,
        audit_profile_attested=provider_attestation.audit_profile_attested,
        restore_evidence_hash_valid=restore_evidence_hash_valid,
        human_confirmation_verified=human_confirmation_verified,
        connection_attempt_preparation_requested=command.connection_attempt_preparation_requested,
        connection_attempt_preparation_allowed=ready,
        raw_data_access_requested=command.raw_data_access_requested,
        import_dry_run_requested=command.import_dry_run_requested,
        import_write_requested=command.import_write_requested,
        destructive_actions_requested=command.destructive_actions_requested,
        gate_status=(
            LegacySqlConnectorSandboxEnablementGateStatus.READY
            if ready
            else LegacySqlConnectorSandboxEnablementGateStatus.BLOCKED
        ),
        blocking_reasons=blocking_reasons,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_connector_sandbox_enablement_gate_hash(draft)})


def legacy_sql_connector_sandbox_provider_attestation_ref(
    profile: LegacySqlConnectorSandboxProfileEvidence,
) -> str:
    return f"{LEGACY_SQL_CONNECTOR_SANDBOX_PROVIDER_ATTESTATION_REF_PREFIX}:{profile.evidence_hash}"


def build_legacy_sql_connector_sandbox_provider_attestation_hash(
    attestation: LegacySqlConnectorSandboxProviderAttestation,
) -> str:
    return stable_hash(canonical_json(attestation.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_sandbox_enablement_gate_hash(
    evidence: LegacySqlConnectorSandboxEnablementGateEvidence,
) -> str:
    return stable_hash(canonical_json(evidence.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_sandbox_enablement_gate_smoke_report_hash(
    report: LegacySqlConnectorSandboxEnablementGateSmokeReport,
) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def run_legacy_sql_connector_sandbox_enablement_gate_smoke_from_env(
    environ: Mapping[str, str] | None = None,
) -> LegacySqlConnectorSandboxEnablementGateSmokeReport:
    env = os.environ if environ is None else environ
    checked_by = env.get(
        "SUITE_LEGACY_SQL_CONNECTOR_SANDBOX_ENABLEMENT_GATE_CHECKED_BY",
        "legacy-sql-connector-sandbox-enablement-gate-smoke",
    )
    checked_at = datetime.now(UTC)
    queue_restore_hash = env.get("SUITE_LEGACY_SQL_METADATA_WORKER_QUEUE_RESTORE_HASH", "sha256:" + "b" * 64)
    enablement_restore_hash = env.get(
        "SUITE_LEGACY_SQL_CONNECTOR_SANDBOX_ENABLEMENT_RESTORE_HASH",
        "sha256:" + "c" * 64,
    )
    queue_backend = LegacySqlMetadataWorkerQueueBackend(
        env.get("SUITE_LEGACY_SQL_METADATA_WORKER_QUEUE_BACKEND", LegacySqlMetadataWorkerQueueBackend.JSONL.value)
    )
    activation = _activation_from_env(
        env=env,
        checked_by=checked_by,
        checked_at=checked_at,
        restore_hash=queue_restore_hash,
    )
    profile = build_legacy_sql_connector_sandbox_profile(
        activation=activation,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=3),
    )
    provider_attestation = build_legacy_sql_connector_sandbox_provider_attestation(
        profile=profile,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=4),
    )
    ready_command = build_legacy_sql_connector_sandbox_enablement_command(
        profile=profile,
        provider_attestation=provider_attestation,
        restore_evidence_hash=enablement_restore_hash,
        requested_by=checked_by,
        human_confirmation_reference=env.get(
            "SUITE_LEGACY_SQL_CONNECTOR_SANDBOX_ENABLEMENT_HUMAN_CONFIRMATION_REF",
            "human-confirmation:legacy-sql-connector-sandbox-enablement-gate-smoke",
        ),
    )
    ready_gate = build_legacy_sql_connector_sandbox_enablement_gate(
        command=ready_command,
        profile=profile,
        provider_attestation=provider_attestation,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=5),
    )
    missing_human_confirmation_gate = build_legacy_sql_connector_sandbox_enablement_gate(
        command=ready_command.model_copy(update={"human_confirmation": False}),
        profile=profile,
        provider_attestation=provider_attestation,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=6),
    )
    unsafe_import_gate = build_legacy_sql_connector_sandbox_enablement_gate(
        command=ready_command.model_copy(update={"import_dry_run_requested": True}),
        profile=profile,
        provider_attestation=provider_attestation,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=7),
    )
    tampered_profile = profile.model_copy(update={"evidence_hash": "sha256:" + "f" * 64})
    tampered_profile_gate = build_legacy_sql_connector_sandbox_enablement_gate(
        command=ready_command,
        profile=tampered_profile,
        provider_attestation=provider_attestation,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=8),
    )
    ready_gate_created = ready_gate.gate_status == LegacySqlConnectorSandboxEnablementGateStatus.READY
    missing_human_confirmation_blocked = (
        missing_human_confirmation_gate.gate_status == LegacySqlConnectorSandboxEnablementGateStatus.BLOCKED
        and "explicit_human_confirmation_missing" in missing_human_confirmation_gate.blocking_reasons
    )
    unsafe_import_request_blocked = (
        unsafe_import_gate.gate_status == LegacySqlConnectorSandboxEnablementGateStatus.BLOCKED
        and "import_dry_run_request_requires_separate_gate" in unsafe_import_gate.blocking_reasons
    )
    tampered_profile_hash_blocked = (
        tampered_profile_gate.gate_status == LegacySqlConnectorSandboxEnablementGateStatus.BLOCKED
        and "sandbox_profile_hash_invalid" in tampered_profile_gate.blocking_reasons
    )
    enablement_gate_ready = (
        ready_gate_created
        and missing_human_confirmation_blocked
        and unsafe_import_request_blocked
        and tampered_profile_hash_blocked
        and ready_gate.connection_attempt_preparation_allowed
        and ready_gate.sandbox_profile_enablement_allowed
        and ready_gate.future_real_connection_gate_required
        and not ready_gate.connection_materialization_allowed
        and not ready_gate.secret_material_resolution_allowed
        and not ready_gate.network_connection_opened
        and not ready_gate.real_connection_opened
        and not ready_gate.raw_data_access_allowed
        and not ready_gate.import_dry_run_allowed
        and not ready_gate.import_write_allowed
        and not ready_gate.destructive_actions_allowed
    )
    draft = LegacySqlConnectorSandboxEnablementGateSmokeReport(
        tenant_id=profile.tenant_id,
        queue_backend=queue_backend,
        sandbox_profile_ref=profile.sandbox_profile_ref,
        sandbox_profile_evidence_hash=profile.evidence_hash,
        provider_attestation_ref=provider_attestation.provider_attestation_ref,
        provider_attestation_hash=provider_attestation.evidence_hash,
        enablement_gate_evidence_hash=ready_gate.evidence_hash,
        restore_evidence_hash=enablement_restore_hash,
        ready_gate_created=ready_gate_created,
        explicit_human_confirmation_required=ready_gate.human_confirmation_verified,
        provider_attestation_required=(
            ready_gate.provider_attestation_hash_valid and ready_gate.provider_attestation_bound
        ),
        restore_evidence_required=ready_gate.restore_evidence_hash_valid,
        sandbox_profile_hash_required=ready_gate.sandbox_profile_hash_valid,
        missing_human_confirmation_blocked=missing_human_confirmation_blocked,
        unsafe_import_request_blocked=unsafe_import_request_blocked,
        tampered_profile_hash_blocked=tampered_profile_hash_blocked,
        connection_attempt_preparation_allowed=ready_gate.connection_attempt_preparation_allowed,
        sandbox_profile_enablement_allowed=ready_gate.sandbox_profile_enablement_allowed,
        future_real_connection_gate_required=ready_gate.future_real_connection_gate_required,
        enablement_gate_ready=enablement_gate_ready,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    _assert_enablement_gate_safe(draft)
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_sandbox_enablement_gate_smoke_report_hash(draft)}
    )


def exit_code_for_report(report: LegacySqlConnectorSandboxEnablementGateSmokeReport) -> int:
    return 0 if report.enablement_gate_ready else 1


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Legacy SQL connector sandbox enablement gate smoke.")
    parser.add_argument("--once", action="store_true", help="Run one metadata-only enablement gate smoke and exit.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the metadata-only enablement report.")
    args = parser.parse_args(argv)
    del args.once

    report = run_legacy_sql_connector_sandbox_enablement_gate_smoke_from_env()
    print(json.dumps(report.model_dump(mode="json"), indent=2 if args.pretty else None, sort_keys=True))
    raise SystemExit(exit_code_for_report(report))


def _activation_from_env(
    *,
    env: Mapping[str, str],
    checked_by: str,
    checked_at: datetime,
    restore_hash: str,
) -> LegacySqlMetadataWorkerLeaseConsumerActivationEvidence:
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
        raise RuntimeError("legacy SQL connector sandbox enablement gate smoke could not acquire a queue lease")
    return LegacySqlMetadataWorkerLeaseConsumer().validate_leased_job(
        job=leased,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=2),
    )


def _provider_component_attestation_hash(
    *,
    profile: LegacySqlConnectorSandboxProfileEvidence,
    provider_attestation_ref: str,
    component_ref: str,
    component_kind: str,
) -> str:
    return stable_hash(
        canonical_json(
            {
                "component_kind": component_kind,
                "component_ref": component_ref,
                "provider_attestation_ref": provider_attestation_ref,
                "sandbox_profile_evidence_hash": profile.evidence_hash,
                "sandbox_profile_ref": profile.sandbox_profile_ref,
                "tenant_id": profile.tenant_id,
            }
        )
    )


def _provider_attestation_bound(
    *,
    command: LegacySqlConnectorSandboxEnablementCommand,
    profile: LegacySqlConnectorSandboxProfileEvidence,
    provider_attestation: LegacySqlConnectorSandboxProviderAttestation,
) -> bool:
    return (
        command.tenant_id == profile.tenant_id == provider_attestation.tenant_id
        and command.module_id == profile.module_id == provider_attestation.module_id
        and command.source_system_ref == profile.source_system_ref == provider_attestation.source_system_ref
        and command.connector_kind == profile.connector_kind == provider_attestation.connector_kind
        and command.sandbox_profile_ref == profile.sandbox_profile_ref == provider_attestation.sandbox_profile_ref
        and command.sandbox_profile_evidence_hash
        == profile.evidence_hash
        == provider_attestation.sandbox_profile_evidence_hash
        and command.provider_attestation_ref == provider_attestation.provider_attestation_ref
        and profile.connector_network_profile_ref == provider_attestation.connector_network_profile_ref
        and profile.secret_resolver_profile_ref == provider_attestation.secret_resolver_profile_ref
        and profile.audit_profile_ref == provider_attestation.audit_profile_ref
        and profile.worker_network_mode == LegacySqlServerNetworkMode.APPROVED_LEGACY_HOST_ONLY
    )


def _enablement_gate_blocking_reasons(
    *,
    command: LegacySqlConnectorSandboxEnablementCommand,
    sandbox_profile_hash_valid: bool,
    sandbox_profile_default_off: bool,
    sandbox_profile_visible: bool,
    provider_attestation_hash_valid: bool,
    provider_attestation_bound: bool,
    metadata_only_attested: bool,
    restore_evidence_hash_valid: bool,
    human_confirmation_verified: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not sandbox_profile_hash_valid:
        reasons.append("sandbox_profile_hash_invalid")
    if not sandbox_profile_default_off:
        reasons.append("sandbox_profile_not_default_off")
    if not sandbox_profile_visible:
        reasons.append("sandbox_profile_not_visible")
    if not provider_attestation_hash_valid:
        reasons.append("provider_attestation_hash_invalid")
    if not provider_attestation_bound:
        reasons.append("provider_attestation_profile_hash_mismatch")
    if not metadata_only_attested:
        reasons.append("provider_metadata_only_boundary_not_attested")
    if not restore_evidence_hash_valid:
        reasons.append("restore_evidence_hash_invalid")
    if not human_confirmation_verified:
        reasons.append("explicit_human_confirmation_missing")
    if not command.connection_attempt_preparation_requested:
        reasons.append("connection_attempt_preparation_not_requested")
    if command.raw_data_access_requested:
        reasons.append("raw_data_access_request_requires_separate_gate")
    if command.import_dry_run_requested:
        reasons.append("import_dry_run_request_requires_separate_gate")
    if command.import_write_requested:
        reasons.append("import_write_request_requires_separate_gate")
    if command.destructive_actions_requested:
        reasons.append("destructive_action_request_requires_separate_gate")
    return tuple(sorted(set(reasons)))


def _assert_enablement_gate_safe(value: BaseModel) -> None:
    payload = value.model_dump_json().lower()
    for fragment in FORBIDDEN_ENABLEMENT_GATE_FRAGMENTS:
        if fragment in payload:
            raise ValueError(f"legacy SQL connector sandbox enablement gate leaked forbidden fragment: {fragment}")


if __name__ == "__main__":
    main()
