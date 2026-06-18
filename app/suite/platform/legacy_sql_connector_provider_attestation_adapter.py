from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.platform.legacy_sql_connector_sandbox_enablement_gate import (
    LegacySqlConnectorSandboxProviderAttestation,
    build_legacy_sql_connector_sandbox_enablement_command,
    build_legacy_sql_connector_sandbox_enablement_gate,
    build_legacy_sql_connector_sandbox_provider_attestation,
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
from suite.platform.legacy_sql_metadata_worker_lease_consumer import (
    LegacySqlMetadataWorkerLeaseConsumer,
)
from suite.platform.legacy_sql_metadata_worker_queue import (
    LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN,
    LegacySqlMetadataWorkerQueueBackend,
    build_default_legacy_sql_metadata_worker_queue_store,
    build_legacy_sql_metadata_worker_queue_job,
)
from suite.platform.legacy_sql_server_metadata import LegacySqlServerNetworkMode

LEGACY_SQL_CONNECTOR_PROVIDER_NETWORK_PROFILE_SCHEMA_VERSION = "legacy_sql_connector_provider_network_profile.v1"
LEGACY_SQL_CONNECTOR_PROVIDER_SECRET_RESOLVER_PROFILE_SCHEMA_VERSION = (
    "legacy_sql_connector_provider_secret_resolver_profile.v1"
)
LEGACY_SQL_CONNECTOR_PROVIDER_AUDIT_PROFILE_SCHEMA_VERSION = "legacy_sql_connector_provider_audit_profile.v1"
LEGACY_SQL_CONNECTOR_PROVIDER_ATTESTATION_ADAPTER_SCHEMA_VERSION = (
    "legacy_sql_connector_provider_attestation_adapter.v1"
)
LEGACY_SQL_CONNECTOR_PROVIDER_ATTESTATION_ADAPTER_SMOKE_SCHEMA_VERSION = (
    "legacy_sql_connector_provider_attestation_adapter_smoke_report.v1"
)
LEGACY_SQL_CONNECTOR_PROVIDER_ATTESTATION_ADAPTER_COMMAND_REF = (
    "docker-compose:legacy-sql-connector-provider-attestation-adapter-smoke"
)
ZERO_HASH = "sha256:" + "0" * 64
SHA256_REF_PATTERN = r"^sha256:[a-f0-9]{64}$"
FORBIDDEN_PROVIDER_ADAPTER_FRAGMENTS = (
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


class LegacySqlConnectorProviderAttestationAdapterStatus(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"


class LegacySqlConnectorNetworkDeploymentProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_PROVIDER_NETWORK_PROFILE_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    sandbox_profile_ref: str
    sandbox_profile_evidence_hash: str
    host_profile_ref: str
    connector_network_profile_ref: str
    approved_egress_ref: str
    deployment_environment_ref: str = "deployment:legacy-sql-provider-attestation"
    network_policy_ref: str = "network-policy:legacy-sql-approved-host-metadata"
    worker_network_mode: LegacySqlServerNetworkMode
    outbound_policy_attested: bool = True
    host_allowlist_attested: bool = True
    connection_materialization_allowed: bool = False
    default_compose_legacy_network_enabled: bool = False
    network_connection_opened: bool = False
    real_connection_opened: bool = False
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL provider network profile text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL provider network profile module_id must be lowercase snake_case")
        return value

    @field_validator(
        "source_system_ref",
        "sandbox_profile_ref",
        "host_profile_ref",
        "connector_network_profile_ref",
        "approved_egress_ref",
        "deployment_environment_ref",
        "network_policy_ref",
    )
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL provider network profile references must be namespaced")
        return value

    @field_validator("sandbox_profile_evidence_hash", "evidence_hash")
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL provider network profile hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_metadata_only_network_profile(self) -> Self:
        if self.worker_network_mode != LegacySqlServerNetworkMode.APPROVED_LEGACY_HOST_ONLY:
            raise ValueError("legacy SQL provider network profile requires approved legacy-host-only network mode")
        if (
            self.connection_materialization_allowed
            or self.default_compose_legacy_network_enabled
            or self.network_connection_opened
            or self.real_connection_opened
        ):
            raise ValueError("legacy SQL provider network profile must not materialize network connections")
        _assert_provider_adapter_safe(self)
        return self


class LegacySqlConnectorSecretResolverDeploymentProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_PROVIDER_SECRET_RESOLVER_PROFILE_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    sandbox_profile_ref: str
    sandbox_profile_evidence_hash: str
    secret_resolver_profile_ref: str
    connection_secret_ref_hash: str
    secret_manager_profile_ref: str = "secret-manager-profile:legacy-sql-handle-attestation"
    secret_access_policy_ref: str = "secret-policy:legacy-sql-handle-only"
    secret_handle_hash_attested: bool = True
    secret_material_lookup_allowed_for_attestation: bool = False
    secret_material_resolved: bool = False
    plaintext_secret_export_allowed: bool = False
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL provider secret resolver profile text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL provider secret resolver profile module_id must be lowercase snake_case")
        return value

    @field_validator(
        "source_system_ref",
        "sandbox_profile_ref",
        "secret_resolver_profile_ref",
        "secret_manager_profile_ref",
        "secret_access_policy_ref",
    )
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL provider secret resolver profile references must be namespaced")
        return value

    @field_validator("sandbox_profile_evidence_hash", "connection_secret_ref_hash", "evidence_hash")
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL provider secret resolver profile hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_metadata_only_secret_profile(self) -> Self:
        if (
            self.secret_material_lookup_allowed_for_attestation
            or self.secret_material_resolved
            or self.plaintext_secret_export_allowed
        ):
            raise ValueError("legacy SQL provider secret resolver profile must not resolve secret material")
        _assert_provider_adapter_safe(self)
        return self


class LegacySqlConnectorAuditDeploymentProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_PROVIDER_AUDIT_PROFILE_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    sandbox_profile_ref: str
    sandbox_profile_evidence_hash: str
    audit_profile_ref: str
    audit_sink_ref: str = "audit-sink:legacy-sql-provider-attestation"
    audit_event_schema_ref: str = "audit-schema:legacy-sql-provider-attestation"
    redaction_policy_ref: str = "redaction-policy:legacy-sql-provider-attestation"
    audit_sink_attested: bool = True
    redaction_required: bool = True
    prompt_or_output_body_logging_allowed: bool = False
    raw_data_logging_allowed: bool = False
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL provider audit profile text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL provider audit profile module_id must be lowercase snake_case")
        return value

    @field_validator(
        "source_system_ref",
        "sandbox_profile_ref",
        "audit_profile_ref",
        "audit_sink_ref",
        "audit_event_schema_ref",
        "redaction_policy_ref",
    )
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL provider audit profile references must be namespaced")
        return value

    @field_validator("sandbox_profile_evidence_hash", "evidence_hash")
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL provider audit profile hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_metadata_only_audit_profile(self) -> Self:
        if self.prompt_or_output_body_logging_allowed or self.raw_data_logging_allowed:
            raise ValueError("legacy SQL provider audit profile must not allow raw or body logging")
        _assert_provider_adapter_safe(self)
        return self


class LegacySqlConnectorProviderAttestationAdapterCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    sandbox_profile_ref: str
    sandbox_profile_evidence_hash: str
    network_profile_evidence_hash: str
    secret_resolver_profile_evidence_hash: str
    audit_profile_evidence_hash: str
    requested_by: str
    network_connection_requested: bool = False
    secret_material_resolution_requested: bool = False
    raw_data_access_requested: bool = False
    import_dry_run_requested: bool = False
    import_write_requested: bool = False
    destructive_actions_requested: bool = False

    @field_validator("tenant_id", "requested_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL provider attestation adapter command text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL provider attestation adapter command module_id must be lowercase snake_case")
        return value

    @field_validator("source_system_ref", "sandbox_profile_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL provider attestation adapter command references must be namespaced")
        return value

    @field_validator(
        "sandbox_profile_evidence_hash",
        "network_profile_evidence_hash",
        "secret_resolver_profile_evidence_hash",
        "audit_profile_evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL provider attestation adapter command hashes must be sha256 references")
        return value


class LegacySqlConnectorProviderAttestationAdapterEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_PROVIDER_ATTESTATION_ADAPTER_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    continuity_domain: str = LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN
    command_ref: str = LEGACY_SQL_CONNECTOR_PROVIDER_ATTESTATION_ADAPTER_COMMAND_REF
    sandbox_profile_ref: str
    sandbox_profile_evidence_hash: str
    activation_evidence_hash: str
    queue_job_evidence_hash: str
    schedule_evidence_hash: str
    release_gate_evidence_hash: str
    network_profile_ref: str
    network_profile_evidence_hash: str
    secret_resolver_profile_ref: str
    secret_resolver_profile_evidence_hash: str
    audit_profile_ref: str
    audit_profile_evidence_hash: str
    provider_attestation_ref: str
    provider_attestation_hash: str
    sandbox_profile_hash_valid: bool
    sandbox_profile_default_off: bool
    sandbox_profile_visible: bool
    network_profile_hash_valid: bool
    secret_resolver_profile_hash_valid: bool
    audit_profile_hash_valid: bool
    network_profile_bound: bool
    secret_resolver_profile_bound: bool
    audit_profile_bound: bool
    provider_metadata_only_boundary_attested: bool
    provider_attestation_ready: bool
    network_connection_requested: bool = False
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
    adapter_status: LegacySqlConnectorProviderAttestationAdapterStatus
    blocking_reasons: tuple[str, ...]
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL provider attestation adapter evidence text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL provider attestation adapter evidence module_id must be lowercase snake_case")
        return value

    @field_validator(
        "source_system_ref",
        "sandbox_profile_ref",
        "network_profile_ref",
        "secret_resolver_profile_ref",
        "audit_profile_ref",
        "provider_attestation_ref",
    )
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL provider attestation adapter evidence references must be namespaced")
        return value

    @field_validator(
        "sandbox_profile_evidence_hash",
        "activation_evidence_hash",
        "queue_job_evidence_hash",
        "schedule_evidence_hash",
        "release_gate_evidence_hash",
        "network_profile_evidence_hash",
        "secret_resolver_profile_evidence_hash",
        "audit_profile_evidence_hash",
        "provider_attestation_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL provider attestation adapter evidence hashes must be sha256 references")
        return value

    @field_validator("blocking_reasons")
    @classmethod
    def validate_blocking_reasons(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("legacy SQL provider attestation adapter blocking reasons must be unique")
        for reason in value:
            if not reason.strip():
                raise ValueError("legacy SQL provider attestation adapter blocking reasons must not be empty")
        return value

    @model_validator(mode="after")
    def require_safe_adapter_evidence(self) -> Self:
        if (
            self.network_connection_opened
            or self.real_connection_opened
            or self.secret_material_resolved
            or self.raw_data_access_allowed
            or self.import_dry_run_allowed
            or self.import_write_allowed
            or self.destructive_actions_allowed
        ):
            raise ValueError(
                "legacy SQL provider attestation adapter must not materialize secrets, connections, or imports"
            )
        if self.adapter_status == LegacySqlConnectorProviderAttestationAdapterStatus.READY:
            required = (
                self.sandbox_profile_hash_valid,
                self.sandbox_profile_default_off,
                self.sandbox_profile_visible,
                self.network_profile_hash_valid,
                self.secret_resolver_profile_hash_valid,
                self.audit_profile_hash_valid,
                self.network_profile_bound,
                self.secret_resolver_profile_bound,
                self.audit_profile_bound,
                self.provider_metadata_only_boundary_attested,
                self.provider_attestation_ready,
            )
            if not all(required) or self.blocking_reasons:
                raise ValueError("ready legacy SQL provider attestation adapter requires complete evidence")
        if self.adapter_status == LegacySqlConnectorProviderAttestationAdapterStatus.BLOCKED:
            if not self.blocking_reasons:
                raise ValueError("blocked legacy SQL provider attestation adapter requires blocking reasons")
            if self.provider_attestation_ready:
                raise ValueError("blocked legacy SQL provider attestation adapter cannot produce a ready attestation")
        _assert_provider_adapter_safe(self)
        return self


class LegacySqlConnectorProviderAttestationAdapterSmokeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_PROVIDER_ATTESTATION_ADAPTER_SMOKE_SCHEMA_VERSION
    tenant_id: str
    queue_backend: LegacySqlMetadataWorkerQueueBackend
    continuity_domain: str = LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN
    command_ref: str = LEGACY_SQL_CONNECTOR_PROVIDER_ATTESTATION_ADAPTER_COMMAND_REF
    sandbox_profile_ref: str
    sandbox_profile_evidence_hash: str
    network_profile_evidence_hash: str
    secret_resolver_profile_evidence_hash: str
    audit_profile_evidence_hash: str
    adapter_evidence_hash: str
    provider_attestation_hash: str
    enablement_gate_evidence_hash: str
    adapter_ready: bool
    downstream_enablement_gate_ready: bool
    network_profile_mismatch_blocked: bool
    secret_material_request_blocked: bool
    tampered_sandbox_profile_blocked: bool
    provider_metadata_only_boundary_attested: bool
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


@dataclass(frozen=True)
class LegacySqlConnectorProviderAttestationAdapterResult:
    adapter_evidence: LegacySqlConnectorProviderAttestationAdapterEvidence
    provider_attestation: LegacySqlConnectorSandboxProviderAttestation


class LegacySqlConnectorProviderAttestationAdapter:
    def validate_provider_profiles(
        self,
        *,
        command: LegacySqlConnectorProviderAttestationAdapterCommand,
        profile: LegacySqlConnectorSandboxProfileEvidence,
        network_profile: LegacySqlConnectorNetworkDeploymentProfile,
        secret_resolver_profile: LegacySqlConnectorSecretResolverDeploymentProfile,
        audit_profile: LegacySqlConnectorAuditDeploymentProfile,
        checked_by: str,
        checked_at_utc: datetime | None = None,
    ) -> LegacySqlConnectorProviderAttestationAdapterResult:
        checked_at = checked_at_utc or datetime.now(UTC)
        sandbox_profile_hash_valid = (
            build_legacy_sql_connector_sandbox_profile_hash(profile)
            == profile.evidence_hash
            == command.sandbox_profile_evidence_hash
        )
        sandbox_profile_default_off = profile.profile_status == LegacySqlConnectorSandboxProfileStatus.DEFAULT_OFF
        sandbox_profile_visible = profile.sandbox_profile_visible and not profile.sandbox_profile_enabled
        network_profile_hash_valid = (
            build_legacy_sql_connector_network_deployment_profile_hash(network_profile)
            == network_profile.evidence_hash
            == command.network_profile_evidence_hash
        )
        secret_resolver_profile_hash_valid = (
            build_legacy_sql_connector_secret_resolver_deployment_profile_hash(secret_resolver_profile)
            == secret_resolver_profile.evidence_hash
            == command.secret_resolver_profile_evidence_hash
        )
        audit_profile_hash_valid = (
            build_legacy_sql_connector_audit_deployment_profile_hash(audit_profile)
            == audit_profile.evidence_hash
            == command.audit_profile_evidence_hash
        )
        network_profile_bound = _network_profile_bound(
            command=command,
            profile=profile,
            network_profile=network_profile,
        )
        secret_resolver_profile_bound = _secret_resolver_profile_bound(
            command=command,
            profile=profile,
            secret_resolver_profile=secret_resolver_profile,
        )
        audit_profile_bound = _audit_profile_bound(command=command, profile=profile, audit_profile=audit_profile)
        provider_metadata_only_boundary_attested = _provider_metadata_only_boundary_attested(
            command=command,
            network_profile=network_profile,
            secret_resolver_profile=secret_resolver_profile,
            audit_profile=audit_profile,
        )
        blocking_reasons = _adapter_blocking_reasons(
            command=command,
            sandbox_profile_hash_valid=sandbox_profile_hash_valid,
            sandbox_profile_default_off=sandbox_profile_default_off,
            sandbox_profile_visible=sandbox_profile_visible,
            network_profile_hash_valid=network_profile_hash_valid,
            secret_resolver_profile_hash_valid=secret_resolver_profile_hash_valid,
            audit_profile_hash_valid=audit_profile_hash_valid,
            network_profile_bound=network_profile_bound,
            secret_resolver_profile_bound=secret_resolver_profile_bound,
            audit_profile_bound=audit_profile_bound,
            provider_metadata_only_boundary_attested=provider_metadata_only_boundary_attested,
        )
        ready = not blocking_reasons
        provider_attestation = build_legacy_sql_connector_sandbox_provider_attestation(
            profile=profile,
            checked_by=checked_by,
            checked_at_utc=checked_at,
            provider_metadata_only_boundary_attested=provider_metadata_only_boundary_attested,
            network_profile_attested=network_profile_hash_valid and network_profile_bound,
            secret_resolver_attested=secret_resolver_profile_hash_valid and secret_resolver_profile_bound,
            audit_profile_attested=audit_profile_hash_valid and audit_profile_bound,
        )
        draft = LegacySqlConnectorProviderAttestationAdapterEvidence(
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
            network_profile_ref=network_profile.connector_network_profile_ref,
            network_profile_evidence_hash=network_profile.evidence_hash,
            secret_resolver_profile_ref=secret_resolver_profile.secret_resolver_profile_ref,
            secret_resolver_profile_evidence_hash=secret_resolver_profile.evidence_hash,
            audit_profile_ref=audit_profile.audit_profile_ref,
            audit_profile_evidence_hash=audit_profile.evidence_hash,
            provider_attestation_ref=provider_attestation.provider_attestation_ref,
            provider_attestation_hash=provider_attestation.evidence_hash,
            sandbox_profile_hash_valid=sandbox_profile_hash_valid,
            sandbox_profile_default_off=sandbox_profile_default_off,
            sandbox_profile_visible=sandbox_profile_visible,
            network_profile_hash_valid=network_profile_hash_valid,
            secret_resolver_profile_hash_valid=secret_resolver_profile_hash_valid,
            audit_profile_hash_valid=audit_profile_hash_valid,
            network_profile_bound=network_profile_bound,
            secret_resolver_profile_bound=secret_resolver_profile_bound,
            audit_profile_bound=audit_profile_bound,
            provider_metadata_only_boundary_attested=provider_metadata_only_boundary_attested,
            provider_attestation_ready=ready,
            network_connection_requested=command.network_connection_requested,
            secret_material_resolution_requested=command.secret_material_resolution_requested,
            raw_data_access_requested=command.raw_data_access_requested,
            import_dry_run_requested=command.import_dry_run_requested,
            import_write_requested=command.import_write_requested,
            destructive_actions_requested=command.destructive_actions_requested,
            adapter_status=(
                LegacySqlConnectorProviderAttestationAdapterStatus.READY
                if ready
                else LegacySqlConnectorProviderAttestationAdapterStatus.BLOCKED
            ),
            blocking_reasons=blocking_reasons,
            checked_by=checked_by,
            checked_at_utc=checked_at,
            evidence_hash=ZERO_HASH,
        )
        return LegacySqlConnectorProviderAttestationAdapterResult(
            adapter_evidence=draft.model_copy(
                update={"evidence_hash": build_legacy_sql_connector_provider_attestation_adapter_hash(draft)}
            ),
            provider_attestation=provider_attestation,
        )


def build_legacy_sql_connector_network_deployment_profile(
    *,
    profile: LegacySqlConnectorSandboxProfileEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
) -> LegacySqlConnectorNetworkDeploymentProfile:
    checked_at = checked_at_utc or datetime.now(UTC)
    draft = LegacySqlConnectorNetworkDeploymentProfile(
        tenant_id=profile.tenant_id,
        module_id=profile.module_id,
        source_system_ref=profile.source_system_ref,
        connector_kind=profile.connector_kind,
        sandbox_profile_ref=profile.sandbox_profile_ref,
        sandbox_profile_evidence_hash=profile.evidence_hash,
        host_profile_ref=profile.host_profile_ref,
        connector_network_profile_ref=profile.connector_network_profile_ref,
        approved_egress_ref=profile.approved_egress_ref,
        worker_network_mode=profile.worker_network_mode,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_connector_network_deployment_profile_hash(draft)})


def build_legacy_sql_connector_secret_resolver_deployment_profile(
    *,
    profile: LegacySqlConnectorSandboxProfileEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
) -> LegacySqlConnectorSecretResolverDeploymentProfile:
    checked_at = checked_at_utc or datetime.now(UTC)
    draft = LegacySqlConnectorSecretResolverDeploymentProfile(
        tenant_id=profile.tenant_id,
        module_id=profile.module_id,
        source_system_ref=profile.source_system_ref,
        connector_kind=profile.connector_kind,
        sandbox_profile_ref=profile.sandbox_profile_ref,
        sandbox_profile_evidence_hash=profile.evidence_hash,
        secret_resolver_profile_ref=profile.secret_resolver_profile_ref,
        connection_secret_ref_hash=profile.connection_secret_ref_hash,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_secret_resolver_deployment_profile_hash(draft)}
    )


def build_legacy_sql_connector_audit_deployment_profile(
    *,
    profile: LegacySqlConnectorSandboxProfileEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
) -> LegacySqlConnectorAuditDeploymentProfile:
    checked_at = checked_at_utc or datetime.now(UTC)
    draft = LegacySqlConnectorAuditDeploymentProfile(
        tenant_id=profile.tenant_id,
        module_id=profile.module_id,
        source_system_ref=profile.source_system_ref,
        connector_kind=profile.connector_kind,
        sandbox_profile_ref=profile.sandbox_profile_ref,
        sandbox_profile_evidence_hash=profile.evidence_hash,
        audit_profile_ref=profile.audit_profile_ref,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_connector_audit_deployment_profile_hash(draft)})


def build_legacy_sql_connector_provider_attestation_adapter_command(
    *,
    profile: LegacySqlConnectorSandboxProfileEvidence,
    network_profile: LegacySqlConnectorNetworkDeploymentProfile,
    secret_resolver_profile: LegacySqlConnectorSecretResolverDeploymentProfile,
    audit_profile: LegacySqlConnectorAuditDeploymentProfile,
    requested_by: str,
) -> LegacySqlConnectorProviderAttestationAdapterCommand:
    return LegacySqlConnectorProviderAttestationAdapterCommand(
        tenant_id=profile.tenant_id,
        module_id=profile.module_id,
        source_system_ref=profile.source_system_ref,
        connector_kind=profile.connector_kind,
        sandbox_profile_ref=profile.sandbox_profile_ref,
        sandbox_profile_evidence_hash=profile.evidence_hash,
        network_profile_evidence_hash=network_profile.evidence_hash,
        secret_resolver_profile_evidence_hash=secret_resolver_profile.evidence_hash,
        audit_profile_evidence_hash=audit_profile.evidence_hash,
        requested_by=requested_by,
    )


def build_legacy_sql_connector_network_deployment_profile_hash(
    profile: LegacySqlConnectorNetworkDeploymentProfile,
) -> str:
    return stable_hash(canonical_json(profile.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_secret_resolver_deployment_profile_hash(
    profile: LegacySqlConnectorSecretResolverDeploymentProfile,
) -> str:
    return stable_hash(canonical_json(profile.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_audit_deployment_profile_hash(
    profile: LegacySqlConnectorAuditDeploymentProfile,
) -> str:
    return stable_hash(canonical_json(profile.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_provider_attestation_adapter_hash(
    evidence: LegacySqlConnectorProviderAttestationAdapterEvidence,
) -> str:
    return stable_hash(canonical_json(evidence.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_provider_attestation_adapter_smoke_report_hash(
    report: LegacySqlConnectorProviderAttestationAdapterSmokeReport,
) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def run_legacy_sql_connector_provider_attestation_adapter_smoke_from_env(
    environ: Mapping[str, str] | None = None,
) -> LegacySqlConnectorProviderAttestationAdapterSmokeReport:
    env = os.environ if environ is None else environ
    checked_by = env.get(
        "SUITE_LEGACY_SQL_CONNECTOR_PROVIDER_ATTESTATION_ADAPTER_CHECKED_BY",
        "legacy-sql-connector-provider-attestation-adapter-smoke",
    )
    checked_at = datetime.now(UTC)
    queue_restore_hash = env.get("SUITE_LEGACY_SQL_METADATA_WORKER_QUEUE_RESTORE_HASH", "sha256:" + "d" * 64)
    enablement_restore_hash = env.get(
        "SUITE_LEGACY_SQL_CONNECTOR_PROVIDER_ATTESTATION_RESTORE_HASH",
        "sha256:" + "e" * 64,
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
    adapter = LegacySqlConnectorProviderAttestationAdapter()
    command = build_legacy_sql_connector_provider_attestation_adapter_command(
        profile=profile,
        network_profile=network_profile,
        secret_resolver_profile=secret_resolver_profile,
        audit_profile=audit_profile,
        requested_by=checked_by,
    )
    ready_result = adapter.validate_provider_profiles(
        command=command,
        profile=profile,
        network_profile=network_profile,
        secret_resolver_profile=secret_resolver_profile,
        audit_profile=audit_profile,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=7),
    )
    enablement_command = build_legacy_sql_connector_sandbox_enablement_command(
        profile=profile,
        provider_attestation=ready_result.provider_attestation,
        restore_evidence_hash=enablement_restore_hash,
        requested_by=checked_by,
        human_confirmation_reference=env.get(
            "SUITE_LEGACY_SQL_CONNECTOR_PROVIDER_ATTESTATION_HUMAN_CONFIRMATION_REF",
            "human-confirmation:legacy-sql-provider-attestation-adapter-smoke",
        ),
    )
    enablement_gate = build_legacy_sql_connector_sandbox_enablement_gate(
        command=enablement_command,
        profile=profile,
        provider_attestation=ready_result.provider_attestation,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=8),
    )
    network_profile_mismatch_blocked = _network_profile_mismatch_blocked(
        adapter=adapter,
        command=command,
        profile=profile,
        network_profile=network_profile,
        secret_resolver_profile=secret_resolver_profile,
        audit_profile=audit_profile,
        checked_by=checked_by,
        checked_at=checked_at + timedelta(seconds=9),
    )
    secret_material_request_blocked = _secret_material_request_blocked(
        adapter=adapter,
        command=command,
        profile=profile,
        network_profile=network_profile,
        secret_resolver_profile=secret_resolver_profile,
        audit_profile=audit_profile,
        checked_by=checked_by,
        checked_at=checked_at + timedelta(seconds=10),
    )
    tampered_sandbox_profile_blocked = _tampered_sandbox_profile_blocked(
        adapter=adapter,
        command=command,
        profile=profile,
        network_profile=network_profile,
        secret_resolver_profile=secret_resolver_profile,
        audit_profile=audit_profile,
        checked_by=checked_by,
        checked_at=checked_at + timedelta(seconds=11),
    )
    adapter_ready = (
        ready_result.adapter_evidence.adapter_status == LegacySqlConnectorProviderAttestationAdapterStatus.READY
        and ready_result.adapter_evidence.provider_attestation_ready
        and ready_result.adapter_evidence.provider_metadata_only_boundary_attested
    )
    downstream_enablement_gate_ready = enablement_gate.connection_attempt_preparation_allowed and not any(
        (
            enablement_gate.connection_materialization_allowed,
            enablement_gate.secret_material_resolution_allowed,
            enablement_gate.network_connection_opened,
            enablement_gate.real_connection_opened,
            enablement_gate.raw_data_access_allowed,
            enablement_gate.import_dry_run_allowed,
            enablement_gate.import_write_allowed,
            enablement_gate.destructive_actions_allowed,
        )
    )
    draft = LegacySqlConnectorProviderAttestationAdapterSmokeReport(
        tenant_id=profile.tenant_id,
        queue_backend=queue_backend,
        sandbox_profile_ref=profile.sandbox_profile_ref,
        sandbox_profile_evidence_hash=profile.evidence_hash,
        network_profile_evidence_hash=network_profile.evidence_hash,
        secret_resolver_profile_evidence_hash=secret_resolver_profile.evidence_hash,
        audit_profile_evidence_hash=audit_profile.evidence_hash,
        adapter_evidence_hash=ready_result.adapter_evidence.evidence_hash,
        provider_attestation_hash=ready_result.provider_attestation.evidence_hash,
        enablement_gate_evidence_hash=enablement_gate.evidence_hash,
        adapter_ready=adapter_ready,
        downstream_enablement_gate_ready=downstream_enablement_gate_ready,
        network_profile_mismatch_blocked=network_profile_mismatch_blocked,
        secret_material_request_blocked=secret_material_request_blocked,
        tampered_sandbox_profile_blocked=tampered_sandbox_profile_blocked,
        provider_metadata_only_boundary_attested=ready_result.adapter_evidence.provider_metadata_only_boundary_attested,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    _assert_provider_adapter_safe(draft)
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_provider_attestation_adapter_smoke_report_hash(draft)}
    )


def exit_code_for_report(report: LegacySqlConnectorProviderAttestationAdapterSmokeReport) -> int:
    return 0 if report.adapter_ready and report.downstream_enablement_gate_ready else 1


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Legacy SQL connector provider attestation adapter smoke.")
    parser.add_argument("--once", action="store_true", help="Run one metadata-only provider adapter smoke and exit.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the provider adapter smoke report.")
    args = parser.parse_args(argv)
    del args.once

    report = run_legacy_sql_connector_provider_attestation_adapter_smoke_from_env()
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
        raise RuntimeError("legacy SQL provider attestation adapter smoke could not acquire a queue lease")
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


def _network_profile_bound(
    *,
    command: LegacySqlConnectorProviderAttestationAdapterCommand,
    profile: LegacySqlConnectorSandboxProfileEvidence,
    network_profile: LegacySqlConnectorNetworkDeploymentProfile,
) -> bool:
    return (
        command.tenant_id == profile.tenant_id == network_profile.tenant_id
        and command.module_id == profile.module_id == network_profile.module_id
        and command.source_system_ref == profile.source_system_ref == network_profile.source_system_ref
        and command.connector_kind == profile.connector_kind == network_profile.connector_kind
        and command.sandbox_profile_ref == profile.sandbox_profile_ref == network_profile.sandbox_profile_ref
        and command.sandbox_profile_evidence_hash
        == profile.evidence_hash
        == network_profile.sandbox_profile_evidence_hash
        and profile.host_profile_ref == network_profile.host_profile_ref
        and profile.connector_network_profile_ref == network_profile.connector_network_profile_ref
        and profile.approved_egress_ref == network_profile.approved_egress_ref
        and network_profile.worker_network_mode == LegacySqlServerNetworkMode.APPROVED_LEGACY_HOST_ONLY
        and network_profile.outbound_policy_attested
        and network_profile.host_allowlist_attested
    )


def _secret_resolver_profile_bound(
    *,
    command: LegacySqlConnectorProviderAttestationAdapterCommand,
    profile: LegacySqlConnectorSandboxProfileEvidence,
    secret_resolver_profile: LegacySqlConnectorSecretResolverDeploymentProfile,
) -> bool:
    return (
        command.tenant_id == profile.tenant_id == secret_resolver_profile.tenant_id
        and command.module_id == profile.module_id == secret_resolver_profile.module_id
        and command.source_system_ref == profile.source_system_ref == secret_resolver_profile.source_system_ref
        and command.connector_kind == profile.connector_kind == secret_resolver_profile.connector_kind
        and command.sandbox_profile_ref == profile.sandbox_profile_ref == secret_resolver_profile.sandbox_profile_ref
        and command.sandbox_profile_evidence_hash
        == profile.evidence_hash
        == secret_resolver_profile.sandbox_profile_evidence_hash
        and profile.secret_resolver_profile_ref == secret_resolver_profile.secret_resolver_profile_ref
        and profile.connection_secret_ref_hash == secret_resolver_profile.connection_secret_ref_hash
        and secret_resolver_profile.secret_handle_hash_attested
    )


def _audit_profile_bound(
    *,
    command: LegacySqlConnectorProviderAttestationAdapterCommand,
    profile: LegacySqlConnectorSandboxProfileEvidence,
    audit_profile: LegacySqlConnectorAuditDeploymentProfile,
) -> bool:
    return (
        command.tenant_id == profile.tenant_id == audit_profile.tenant_id
        and command.module_id == profile.module_id == audit_profile.module_id
        and command.source_system_ref == profile.source_system_ref == audit_profile.source_system_ref
        and command.connector_kind == profile.connector_kind == audit_profile.connector_kind
        and command.sandbox_profile_ref == profile.sandbox_profile_ref == audit_profile.sandbox_profile_ref
        and command.sandbox_profile_evidence_hash
        == profile.evidence_hash
        == audit_profile.sandbox_profile_evidence_hash
        and profile.audit_profile_ref == audit_profile.audit_profile_ref
        and audit_profile.audit_sink_attested
        and audit_profile.redaction_required
    )


def _provider_metadata_only_boundary_attested(
    *,
    command: LegacySqlConnectorProviderAttestationAdapterCommand,
    network_profile: LegacySqlConnectorNetworkDeploymentProfile,
    secret_resolver_profile: LegacySqlConnectorSecretResolverDeploymentProfile,
    audit_profile: LegacySqlConnectorAuditDeploymentProfile,
) -> bool:
    return not any(
        (
            command.network_connection_requested,
            command.secret_material_resolution_requested,
            command.raw_data_access_requested,
            command.import_dry_run_requested,
            command.import_write_requested,
            command.destructive_actions_requested,
            network_profile.connection_materialization_allowed,
            network_profile.default_compose_legacy_network_enabled,
            network_profile.network_connection_opened,
            network_profile.real_connection_opened,
            secret_resolver_profile.secret_material_lookup_allowed_for_attestation,
            secret_resolver_profile.secret_material_resolved,
            secret_resolver_profile.plaintext_secret_export_allowed,
            audit_profile.prompt_or_output_body_logging_allowed,
            audit_profile.raw_data_logging_allowed,
        )
    )


def _adapter_blocking_reasons(
    *,
    command: LegacySqlConnectorProviderAttestationAdapterCommand,
    sandbox_profile_hash_valid: bool,
    sandbox_profile_default_off: bool,
    sandbox_profile_visible: bool,
    network_profile_hash_valid: bool,
    secret_resolver_profile_hash_valid: bool,
    audit_profile_hash_valid: bool,
    network_profile_bound: bool,
    secret_resolver_profile_bound: bool,
    audit_profile_bound: bool,
    provider_metadata_only_boundary_attested: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not sandbox_profile_hash_valid:
        reasons.append("sandbox_profile_hash_invalid")
    if not sandbox_profile_default_off:
        reasons.append("sandbox_profile_not_default_off")
    if not sandbox_profile_visible:
        reasons.append("sandbox_profile_not_visible")
    if not network_profile_hash_valid:
        reasons.append("network_profile_hash_invalid")
    if not secret_resolver_profile_hash_valid:
        reasons.append("secret_resolver_profile_hash_invalid")
    if not audit_profile_hash_valid:
        reasons.append("audit_profile_hash_invalid")
    if not network_profile_bound:
        reasons.append("network_profile_not_bound")
    if not secret_resolver_profile_bound:
        reasons.append("secret_resolver_profile_not_bound")
    if not audit_profile_bound:
        reasons.append("audit_profile_not_bound")
    if not provider_metadata_only_boundary_attested:
        reasons.append("provider_metadata_only_boundary_not_attested")
    if command.network_connection_requested:
        reasons.append("network_connection_request_requires_real_connection_gate")
    if command.secret_material_resolution_requested:
        reasons.append("secret_material_resolution_request_requires_real_connection_gate")
    if command.raw_data_access_requested:
        reasons.append("raw_data_access_request_requires_separate_gate")
    if command.import_dry_run_requested:
        reasons.append("import_dry_run_request_requires_separate_gate")
    if command.import_write_requested:
        reasons.append("import_write_request_requires_separate_gate")
    if command.destructive_actions_requested:
        reasons.append("destructive_action_request_requires_separate_gate")
    return tuple(sorted(set(reasons)))


def _network_profile_mismatch_blocked(
    *,
    adapter: LegacySqlConnectorProviderAttestationAdapter,
    command: LegacySqlConnectorProviderAttestationAdapterCommand,
    profile: LegacySqlConnectorSandboxProfileEvidence,
    network_profile: LegacySqlConnectorNetworkDeploymentProfile,
    secret_resolver_profile: LegacySqlConnectorSecretResolverDeploymentProfile,
    audit_profile: LegacySqlConnectorAuditDeploymentProfile,
    checked_by: str,
    checked_at: datetime,
) -> bool:
    mismatched = network_profile.model_copy(
        update={"connector_network_profile_ref": "network-profile:legacy-sql-wrong", "evidence_hash": ZERO_HASH}
    )
    mismatched = mismatched.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_network_deployment_profile_hash(mismatched)}
    )
    mismatched_command = command.model_copy(update={"network_profile_evidence_hash": mismatched.evidence_hash})
    result = adapter.validate_provider_profiles(
        command=mismatched_command,
        profile=profile,
        network_profile=mismatched,
        secret_resolver_profile=secret_resolver_profile,
        audit_profile=audit_profile,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        result.adapter_evidence.adapter_status == LegacySqlConnectorProviderAttestationAdapterStatus.BLOCKED
        and "network_profile_not_bound" in result.adapter_evidence.blocking_reasons
    )


def _secret_material_request_blocked(
    *,
    adapter: LegacySqlConnectorProviderAttestationAdapter,
    command: LegacySqlConnectorProviderAttestationAdapterCommand,
    profile: LegacySqlConnectorSandboxProfileEvidence,
    network_profile: LegacySqlConnectorNetworkDeploymentProfile,
    secret_resolver_profile: LegacySqlConnectorSecretResolverDeploymentProfile,
    audit_profile: LegacySqlConnectorAuditDeploymentProfile,
    checked_by: str,
    checked_at: datetime,
) -> bool:
    result = adapter.validate_provider_profiles(
        command=command.model_copy(update={"secret_material_resolution_requested": True}),
        profile=profile,
        network_profile=network_profile,
        secret_resolver_profile=secret_resolver_profile,
        audit_profile=audit_profile,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        result.adapter_evidence.adapter_status == LegacySqlConnectorProviderAttestationAdapterStatus.BLOCKED
        and "secret_material_resolution_request_requires_real_connection_gate"
        in result.adapter_evidence.blocking_reasons
    )


def _tampered_sandbox_profile_blocked(
    *,
    adapter: LegacySqlConnectorProviderAttestationAdapter,
    command: LegacySqlConnectorProviderAttestationAdapterCommand,
    profile: LegacySqlConnectorSandboxProfileEvidence,
    network_profile: LegacySqlConnectorNetworkDeploymentProfile,
    secret_resolver_profile: LegacySqlConnectorSecretResolverDeploymentProfile,
    audit_profile: LegacySqlConnectorAuditDeploymentProfile,
    checked_by: str,
    checked_at: datetime,
) -> bool:
    tampered_profile = profile.model_copy(update={"evidence_hash": "sha256:" + "f" * 64})
    result = adapter.validate_provider_profiles(
        command=command,
        profile=tampered_profile,
        network_profile=network_profile,
        secret_resolver_profile=secret_resolver_profile,
        audit_profile=audit_profile,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        result.adapter_evidence.adapter_status == LegacySqlConnectorProviderAttestationAdapterStatus.BLOCKED
        and "sandbox_profile_hash_invalid" in result.adapter_evidence.blocking_reasons
    )


def _assert_provider_adapter_safe(value: BaseModel) -> None:
    payload = value.model_dump_json().lower()
    for fragment in FORBIDDEN_PROVIDER_ADAPTER_FRAGMENTS:
        if fragment in payload:
            raise ValueError(f"legacy SQL provider attestation adapter leaked forbidden fragment: {fragment}")


if __name__ == "__main__":
    main()
