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
from suite.platform.legacy_sql_connector_live_connection_gate import (
    LegacySqlConnectorLiveConnectionGateEvidence,
    LegacySqlConnectorLiveConnectionGateStatus,
    _build_live_connection_command_from_snapshots,
    _build_live_connection_gate_from_snapshots,
    _build_ready_live_connection_snapshots,
    _build_ready_runtime_activation_gate,
    build_legacy_sql_connector_live_connection_gate_hash,
)
from suite.platform.legacy_sql_connector_real_connection_executor import (
    LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    LegacySqlConnectorRealConnectionPolicyStoreBackend,
)
from suite.platform.legacy_sql_discovery import MODULE_ID_PATTERN, NAMESPACED_REF_PATTERN, LegacySqlConnectorKind
from suite.platform.legacy_sql_metadata_worker_queue import LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN

LEGACY_SQL_CONNECTOR_METADATA_CONNECTION_PROBE_PROVIDER_DRIVER_SNAPSHOT_SCHEMA_VERSION = (
    "legacy_sql_connector_metadata_connection_probe_provider_driver_snapshot.v1"
)
LEGACY_SQL_CONNECTOR_METADATA_CONNECTION_PROBE_SECRET_BROKER_READ_PATH_SNAPSHOT_SCHEMA_VERSION = (
    "legacy_sql_connector_metadata_connection_probe_secret_broker_read_path_snapshot.v1"
)
LEGACY_SQL_CONNECTOR_METADATA_CONNECTION_PROBE_QUERY_ALLOWLIST_SNAPSHOT_SCHEMA_VERSION = (
    "legacy_sql_connector_metadata_connection_probe_query_allowlist_snapshot.v1"
)
LEGACY_SQL_CONNECTOR_METADATA_CONNECTION_PROBE_TIMEOUT_CIRCUIT_BREAKER_EXECUTION_SNAPSHOT_SCHEMA_VERSION = (
    "legacy_sql_connector_metadata_connection_probe_timeout_circuit_breaker_execution_snapshot.v1"
)
LEGACY_SQL_CONNECTOR_METADATA_CONNECTION_PROBE_AUDIT_SINK_EXECUTION_SNAPSHOT_SCHEMA_VERSION = (
    "legacy_sql_connector_metadata_connection_probe_audit_sink_execution_snapshot.v1"
)
LEGACY_SQL_CONNECTOR_METADATA_CONNECTION_PROBE_EMERGENCY_DISABLE_EXECUTION_SNAPSHOT_SCHEMA_VERSION = (
    "legacy_sql_connector_metadata_connection_probe_emergency_disable_execution_snapshot.v1"
)
LEGACY_SQL_CONNECTOR_METADATA_CONNECTION_PROBE_GATE_SCHEMA_VERSION = (
    "legacy_sql_connector_metadata_connection_probe_gate.v1"
)
LEGACY_SQL_CONNECTOR_METADATA_CONNECTION_PROBE_GATE_SMOKE_SCHEMA_VERSION = (
    "legacy_sql_connector_metadata_connection_probe_gate_smoke_report.v1"
)
LEGACY_SQL_CONNECTOR_METADATA_CONNECTION_PROBE_GATE_COMMAND_REF = (
    "docker-compose:legacy-sql-connector-metadata-connection-probe-gate-smoke"
)
ZERO_HASH = "sha256:" + "0" * 64
SHA256_REF_PATTERN = r"^sha256:[a-f0-9]{64}$"
_ALLOWED_SNAPSHOT_SCHEMAS = {
    LEGACY_SQL_CONNECTOR_METADATA_CONNECTION_PROBE_PROVIDER_DRIVER_SNAPSHOT_SCHEMA_VERSION,
    LEGACY_SQL_CONNECTOR_METADATA_CONNECTION_PROBE_SECRET_BROKER_READ_PATH_SNAPSHOT_SCHEMA_VERSION,
    LEGACY_SQL_CONNECTOR_METADATA_CONNECTION_PROBE_QUERY_ALLOWLIST_SNAPSHOT_SCHEMA_VERSION,
    LEGACY_SQL_CONNECTOR_METADATA_CONNECTION_PROBE_TIMEOUT_CIRCUIT_BREAKER_EXECUTION_SNAPSHOT_SCHEMA_VERSION,
    LEGACY_SQL_CONNECTOR_METADATA_CONNECTION_PROBE_AUDIT_SINK_EXECUTION_SNAPSHOT_SCHEMA_VERSION,
    LEGACY_SQL_CONNECTOR_METADATA_CONNECTION_PROBE_EMERGENCY_DISABLE_EXECUTION_SNAPSHOT_SCHEMA_VERSION,
}
FORBIDDEN_METADATA_CONNECTION_PROBE_FRAGMENTS = (
    '"connection_secret_ref":',
    '"connection_secret_value":',
    '"secret_broker_read_result":',
    "secret:legacy-sql",
    "sqlserver://",
    "password",
    '"dsn":',
    "plain_secret",
    "connection_string",
    '"raw_payload":',
    '"sample_values":',
    '"import_write_payload":',
    "dbo.kunden",
    "kundenid",
    "email",
)


class LegacySqlConnectorMetadataConnectionProbeGateStatus(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"


class LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    snapshot_ref: str
    live_connection_gate_evidence_hash: str
    upstream_evidence_hashes: tuple[str, ...] = ()
    required_controls: tuple[str, ...]
    passed_controls: tuple[str, ...]
    failed_controls: tuple[str, ...] = ()
    provider_driver_load_allowed: bool = False
    secret_broker_read_allowed: bool = False
    metadata_connection_probe_allowed: bool = False
    metadata_connection_probe_executed: bool = False
    metadata_query_execution_allowed: bool = False
    socket_runtime_execution_allowed: bool = False
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

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: str) -> str:
        if value not in _ALLOWED_SNAPSHOT_SCHEMAS:
            raise ValueError("legacy SQL metadata connection probe snapshot schema is not allowed")
        return value

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL metadata connection probe snapshot text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL metadata connection probe snapshot module_id must be lowercase snake_case")
        return value

    @field_validator("source_system_ref", "snapshot_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL metadata connection probe snapshot references must be namespaced")
        return value

    @field_validator("live_connection_gate_evidence_hash", "evidence_hash")
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL metadata connection probe snapshot hashes must be sha256 references")
        return value

    @field_validator("upstream_evidence_hashes")
    @classmethod
    def validate_upstream_hashes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for item in value:
            if not re.fullmatch(SHA256_REF_PATTERN, item):
                raise ValueError("legacy SQL metadata connection probe snapshot upstream hashes must be sha256 refs")
        return value

    @field_validator("required_controls", "passed_controls", "failed_controls")
    @classmethod
    def validate_controls(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("legacy SQL metadata connection probe snapshot controls must be unique")
        for item in value:
            if not item.strip():
                raise ValueError("legacy SQL metadata connection probe snapshot controls must not be empty")
        return value

    @model_validator(mode="after")
    def require_safe_snapshot(self) -> Self:
        if (
            self.provider_driver_load_allowed
            or self.secret_broker_read_allowed
            or self.metadata_connection_probe_allowed
            or self.metadata_connection_probe_executed
            or self.metadata_query_execution_allowed
            or self.socket_runtime_execution_allowed
            or self.network_socket_opened
            or self.network_connection_opened
            or self.real_connection_opened
            or self.secret_material_resolved
            or self.raw_data_access_allowed
            or self.import_dry_run_allowed
            or self.import_write_allowed
            or self.destructive_actions_allowed
        ):
            raise ValueError("legacy SQL metadata connection probe snapshot must remain non-executing")
        missing_controls = set(self.required_controls) - set(self.passed_controls) - set(self.failed_controls)
        if missing_controls:
            raise ValueError("legacy SQL metadata connection probe snapshot must classify every required control")
        _assert_metadata_connection_probe_safe(self)
        return self


class LegacySqlConnectorMetadataConnectionProbeGateCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    live_connection_gate_evidence_hash: str
    provider_driver_snapshot_hash: str
    secret_broker_read_path_snapshot_hash: str
    metadata_query_allowlist_snapshot_hash: str
    timeout_circuit_breaker_execution_snapshot_hash: str
    audit_sink_execution_snapshot_hash: str
    emergency_disable_execution_snapshot_hash: str
    requested_by: str
    metadata_connection_probe_gate_requested: bool = True
    provider_driver_load_requested: bool = False
    secret_broker_read_requested: bool = False
    metadata_connection_probe_requested: bool = False
    metadata_query_execution_requested: bool = False
    socket_runtime_execution_requested: bool = False
    raw_data_access_requested: bool = False
    import_dry_run_requested: bool = False
    import_write_requested: bool = False
    destructive_actions_requested: bool = False

    @field_validator("tenant_id", "requested_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL metadata connection probe gate command text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL metadata connection probe gate command module_id must be lowercase snake_case")
        return value

    @field_validator("source_system_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL metadata connection probe gate command references must be namespaced")
        return value

    @field_validator(
        "live_connection_gate_evidence_hash",
        "provider_driver_snapshot_hash",
        "secret_broker_read_path_snapshot_hash",
        "metadata_query_allowlist_snapshot_hash",
        "timeout_circuit_breaker_execution_snapshot_hash",
        "audit_sink_execution_snapshot_hash",
        "emergency_disable_execution_snapshot_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL metadata connection probe gate command hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_safe_command(self) -> Self:
        _assert_metadata_connection_probe_safe(self)
        return self


class LegacySqlConnectorMetadataConnectionProbeGateEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_METADATA_CONNECTION_PROBE_GATE_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    continuity_domain: str = LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN
    command_ref: str = LEGACY_SQL_CONNECTOR_METADATA_CONNECTION_PROBE_GATE_COMMAND_REF
    live_connection_gate_evidence_hash: str
    provider_driver_snapshot_hash: str
    secret_broker_read_path_snapshot_hash: str
    metadata_query_allowlist_snapshot_hash: str
    timeout_circuit_breaker_execution_snapshot_hash: str
    audit_sink_execution_snapshot_hash: str
    emergency_disable_execution_snapshot_hash: str
    live_connection_gate_hash_valid: bool
    live_connection_gate_ready: bool
    live_connection_gate_bound: bool
    provider_driver_snapshot_hash_valid: bool
    provider_driver_snapshot_bound: bool
    provider_driver_passed: bool
    secret_broker_read_path_snapshot_hash_valid: bool
    secret_broker_read_path_snapshot_bound: bool
    secret_broker_read_path_passed: bool
    metadata_query_allowlist_snapshot_hash_valid: bool
    metadata_query_allowlist_snapshot_bound: bool
    metadata_query_allowlist_passed: bool
    timeout_circuit_breaker_execution_snapshot_hash_valid: bool
    timeout_circuit_breaker_execution_snapshot_bound: bool
    timeout_circuit_breaker_execution_passed: bool
    audit_sink_execution_snapshot_hash_valid: bool
    audit_sink_execution_snapshot_bound: bool
    audit_sink_execution_passed: bool
    emergency_disable_execution_snapshot_hash_valid: bool
    emergency_disable_execution_snapshot_bound: bool
    emergency_disable_execution_passed: bool
    metadata_connection_probe_gate_requested: bool
    metadata_connection_probe_gate_ready: bool
    future_metadata_probe_implementation_required: bool = True
    future_secret_materialization_gate_required: bool = True
    future_import_dry_run_gate_required: bool = True
    provider_driver_load_requested: bool = False
    provider_driver_load_allowed: bool = False
    secret_broker_read_requested: bool = False
    secret_broker_read_allowed: bool = False
    metadata_connection_probe_requested: bool = False
    metadata_connection_probe_allowed: bool = False
    metadata_connection_probe_executed: bool = False
    metadata_query_execution_requested: bool = False
    metadata_query_execution_allowed: bool = False
    socket_runtime_execution_requested: bool = False
    socket_runtime_execution_allowed: bool = False
    network_socket_opened: bool = False
    network_connection_opened: bool = False
    real_connection_opened: bool = False
    secret_material_resolved: bool = False
    raw_data_access_requested: bool = False
    raw_data_access_allowed: bool = False
    import_dry_run_requested: bool = False
    import_dry_run_allowed: bool = False
    import_write_requested: bool = False
    import_write_allowed: bool = False
    destructive_actions_requested: bool = False
    destructive_actions_allowed: bool = False
    gate_status: LegacySqlConnectorMetadataConnectionProbeGateStatus
    blocking_reasons: tuple[str, ...]
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL metadata connection probe gate text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL metadata connection probe gate module_id must be lowercase snake_case")
        return value

    @field_validator("source_system_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL metadata connection probe gate references must be namespaced")
        return value

    @field_validator(
        "live_connection_gate_evidence_hash",
        "provider_driver_snapshot_hash",
        "secret_broker_read_path_snapshot_hash",
        "metadata_query_allowlist_snapshot_hash",
        "timeout_circuit_breaker_execution_snapshot_hash",
        "audit_sink_execution_snapshot_hash",
        "emergency_disable_execution_snapshot_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL metadata connection probe gate hashes must be sha256 references")
        return value

    @field_validator("blocking_reasons")
    @classmethod
    def validate_blocking_reasons(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("legacy SQL metadata connection probe gate blocking reasons must be unique")
        for reason in value:
            if not reason.strip():
                raise ValueError("legacy SQL metadata connection probe gate blocking reasons must not be empty")
        return value

    @model_validator(mode="after")
    def require_safe_gate(self) -> Self:
        if (
            self.provider_driver_load_allowed
            or self.secret_broker_read_allowed
            or self.metadata_connection_probe_allowed
            or self.metadata_connection_probe_executed
            or self.metadata_query_execution_allowed
            or self.socket_runtime_execution_allowed
            or self.network_socket_opened
            or self.network_connection_opened
            or self.real_connection_opened
            or self.secret_material_resolved
            or self.raw_data_access_allowed
            or self.import_dry_run_allowed
            or self.import_write_allowed
            or self.destructive_actions_allowed
        ):
            raise ValueError("legacy SQL metadata connection probe gate must remain non-executing")
        if (
            not self.future_metadata_probe_implementation_required
            or not self.future_secret_materialization_gate_required
            or not self.future_import_dry_run_gate_required
        ):
            raise ValueError("legacy SQL metadata connection probe gate must require future implementation gates")
        if self.gate_status == LegacySqlConnectorMetadataConnectionProbeGateStatus.READY:
            required = (
                self.live_connection_gate_hash_valid,
                self.live_connection_gate_ready,
                self.live_connection_gate_bound,
                self.provider_driver_snapshot_hash_valid,
                self.provider_driver_snapshot_bound,
                self.provider_driver_passed,
                self.secret_broker_read_path_snapshot_hash_valid,
                self.secret_broker_read_path_snapshot_bound,
                self.secret_broker_read_path_passed,
                self.metadata_query_allowlist_snapshot_hash_valid,
                self.metadata_query_allowlist_snapshot_bound,
                self.metadata_query_allowlist_passed,
                self.timeout_circuit_breaker_execution_snapshot_hash_valid,
                self.timeout_circuit_breaker_execution_snapshot_bound,
                self.timeout_circuit_breaker_execution_passed,
                self.audit_sink_execution_snapshot_hash_valid,
                self.audit_sink_execution_snapshot_bound,
                self.audit_sink_execution_passed,
                self.emergency_disable_execution_snapshot_hash_valid,
                self.emergency_disable_execution_snapshot_bound,
                self.emergency_disable_execution_passed,
                self.metadata_connection_probe_gate_requested,
                self.metadata_connection_probe_gate_ready,
            )
            if not all(required) or self.blocking_reasons:
                raise ValueError("ready legacy SQL metadata connection probe gate requires complete evidence")
        if self.gate_status == LegacySqlConnectorMetadataConnectionProbeGateStatus.BLOCKED:
            if not self.blocking_reasons:
                raise ValueError("blocked legacy SQL metadata connection probe gate requires blocking reasons")
            if self.metadata_connection_probe_gate_ready:
                raise ValueError("blocked legacy SQL metadata connection probe gate cannot be ready")
        _assert_metadata_connection_probe_safe(self)
        return self


class LegacySqlConnectorMetadataConnectionProbeGateSmokeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_METADATA_CONNECTION_PROBE_GATE_SMOKE_SCHEMA_VERSION
    tenant_id: str
    store_backend: LegacySqlConnectorRealConnectionPolicyStoreBackend
    continuity_domain: str = LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN
    command_ref: str = LEGACY_SQL_CONNECTOR_METADATA_CONNECTION_PROBE_GATE_COMMAND_REF
    live_connection_gate_evidence_hash: str
    metadata_connection_probe_gate_evidence_hash: str
    metadata_connection_probe_gate_ready: bool
    live_connection_gate_required: bool
    provider_driver_snapshot_required: bool
    secret_broker_read_path_snapshot_required: bool
    metadata_query_allowlist_snapshot_required: bool
    timeout_circuit_breaker_execution_snapshot_required: bool
    audit_sink_execution_snapshot_required: bool
    emergency_disable_execution_snapshot_required: bool
    live_connection_gate_missing_blocked: bool
    provider_driver_missing_blocked: bool
    secret_broker_read_path_missing_blocked: bool
    metadata_query_allowlist_missing_blocked: bool
    timeout_circuit_breaker_execution_missing_blocked: bool
    audit_sink_execution_missing_blocked: bool
    emergency_disable_execution_missing_blocked: bool
    direct_probe_request_blocked: bool
    future_metadata_probe_implementation_required: bool
    future_secret_materialization_gate_required: bool
    future_import_dry_run_gate_required: bool
    provider_driver_load_allowed: bool = False
    secret_broker_read_allowed: bool = False
    metadata_connection_probe_allowed: bool = False
    metadata_connection_probe_executed: bool = False
    metadata_query_execution_allowed: bool = False
    socket_runtime_execution_allowed: bool = False
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

    @model_validator(mode="after")
    def require_smoke_safe(self) -> Self:
        if (
            self.provider_driver_load_allowed
            or self.secret_broker_read_allowed
            or self.metadata_connection_probe_allowed
            or self.metadata_connection_probe_executed
            or self.metadata_query_execution_allowed
            or self.socket_runtime_execution_allowed
            or self.network_socket_opened
            or self.network_connection_opened
            or self.real_connection_opened
            or self.secret_material_resolved
            or self.raw_data_access_allowed
            or self.import_dry_run_allowed
            or self.import_write_allowed
            or self.destructive_actions_allowed
        ):
            raise ValueError("legacy SQL metadata connection probe smoke must remain non-executing")
        _assert_metadata_connection_probe_safe(self)
        return self


def build_legacy_sql_connector_metadata_connection_probe_provider_driver_snapshot(
    *,
    live_connection_gate: LegacySqlConnectorLiveConnectionGateEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    passed: bool = True,
) -> LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot:
    return _build_snapshot(
        schema_version=LEGACY_SQL_CONNECTOR_METADATA_CONNECTION_PROBE_PROVIDER_DRIVER_SNAPSHOT_SCHEMA_VERSION,
        snapshot_ref="metadata-connection-probe-provider-driver:legacy-sql-metadata-probe",
        live_connection_gate=live_connection_gate,
        required_controls=(
            "provider_driver_package_pinned",
            "provider_driver_license_approved",
            "provider_driver_vulnerability_scan_passed",
            "provider_driver_adapter_boundary_defined",
            "provider_driver_not_loaded_by_gate",
        ),
        failed_controls=() if passed else ("provider_driver_package_pinned",),
        checked_by=checked_by,
        checked_at_utc=checked_at_utc,
    )


def build_legacy_sql_connector_metadata_connection_probe_secret_broker_read_path_snapshot(
    *,
    live_connection_gate: LegacySqlConnectorLiveConnectionGateEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    passed: bool = True,
) -> LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot:
    return _build_snapshot(
        schema_version=LEGACY_SQL_CONNECTOR_METADATA_CONNECTION_PROBE_SECRET_BROKER_READ_PATH_SNAPSHOT_SCHEMA_VERSION,
        snapshot_ref="metadata-connection-probe-secret-broker-read-path:legacy-sql-metadata-probe",
        live_connection_gate=live_connection_gate,
        upstream_evidence_hashes=(live_connection_gate.secret_broker_binding_snapshot_hash,),
        required_controls=(
            "secret_broker_read_path_bound",
            "sealed_secret_handle_metadata_bound",
            "secret_read_audit_event_ready",
            "secret_material_not_read_by_gate",
            "rotation_version_check_ready",
        ),
        failed_controls=() if passed else ("secret_broker_read_path_bound",),
        checked_by=checked_by,
        checked_at_utc=checked_at_utc,
    )


def build_legacy_sql_connector_metadata_connection_probe_query_allowlist_snapshot(
    *,
    live_connection_gate: LegacySqlConnectorLiveConnectionGateEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    passed: bool = True,
) -> LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot:
    return _build_snapshot(
        schema_version=LEGACY_SQL_CONNECTOR_METADATA_CONNECTION_PROBE_QUERY_ALLOWLIST_SNAPSHOT_SCHEMA_VERSION,
        snapshot_ref="metadata-connection-probe-query-allowlist:legacy-sql-metadata-probe",
        live_connection_gate=live_connection_gate,
        required_controls=(
            "metadata_catalog_queries_allowlisted",
            "row_data_queries_forbidden",
            "schema_introspection_only",
            "tenant_scope_required",
            "result_redaction_policy_bound",
        ),
        failed_controls=() if passed else ("metadata_catalog_queries_allowlisted",),
        checked_by=checked_by,
        checked_at_utc=checked_at_utc,
    )


def build_legacy_sql_connector_metadata_connection_probe_timeout_circuit_breaker_execution_snapshot(
    *,
    live_connection_gate: LegacySqlConnectorLiveConnectionGateEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    passed: bool = True,
) -> LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot:
    return _build_snapshot(
        schema_version=LEGACY_SQL_CONNECTOR_METADATA_CONNECTION_PROBE_TIMEOUT_CIRCUIT_BREAKER_EXECUTION_SNAPSHOT_SCHEMA_VERSION,
        snapshot_ref="metadata-connection-probe-timeout-circuit-breaker-execution:legacy-sql-metadata-probe",
        live_connection_gate=live_connection_gate,
        upstream_evidence_hashes=(live_connection_gate.timeout_circuit_breaker_snapshot_hash,),
        required_controls=(
            "connect_timeout_execution_bound",
            "metadata_query_timeout_execution_bound",
            "retry_budget_execution_bound",
            "circuit_breaker_trip_execution_bound",
            "pool_limit_execution_bound",
        ),
        failed_controls=() if passed else ("connect_timeout_execution_bound",),
        checked_by=checked_by,
        checked_at_utc=checked_at_utc,
    )


def build_legacy_sql_connector_metadata_connection_probe_audit_sink_execution_snapshot(
    *,
    live_connection_gate: LegacySqlConnectorLiveConnectionGateEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    passed: bool = True,
) -> LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot:
    return _build_snapshot(
        schema_version=LEGACY_SQL_CONNECTOR_METADATA_CONNECTION_PROBE_AUDIT_SINK_EXECUTION_SNAPSHOT_SCHEMA_VERSION,
        snapshot_ref="metadata-connection-probe-audit-sink-execution:legacy-sql-metadata-probe",
        live_connection_gate=live_connection_gate,
        upstream_evidence_hashes=(live_connection_gate.audit_sink_snapshot_hash,),
        required_controls=(
            "probe_attempt_audit_event_bound",
            "provider_driver_hash_logging_ready",
            "tool_call_hash_logging_ready",
            "redaction_policy_bound",
            "tenant_trace_context_required",
            "prompt_output_body_logging_forbidden",
        ),
        failed_controls=() if passed else ("probe_attempt_audit_event_bound",),
        checked_by=checked_by,
        checked_at_utc=checked_at_utc,
    )


def build_legacy_sql_connector_metadata_connection_probe_emergency_disable_execution_snapshot(
    *,
    live_connection_gate: LegacySqlConnectorLiveConnectionGateEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    passed: bool = True,
) -> LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot:
    return _build_snapshot(
        schema_version=LEGACY_SQL_CONNECTOR_METADATA_CONNECTION_PROBE_EMERGENCY_DISABLE_EXECUTION_SNAPSHOT_SCHEMA_VERSION,
        snapshot_ref="metadata-connection-probe-emergency-disable-execution:legacy-sql-metadata-probe",
        live_connection_gate=live_connection_gate,
        upstream_evidence_hashes=(live_connection_gate.emergency_disable_snapshot_hash,),
        required_controls=(
            "tenant_emergency_disable_execution_bound",
            "global_emergency_disable_execution_bound",
            "circuit_breaker_disable_execution_ready",
            "operator_abort_execution_ready",
            "post_probe_shutdown_execution_ready",
        ),
        failed_controls=() if passed else ("tenant_emergency_disable_execution_bound",),
        checked_by=checked_by,
        checked_at_utc=checked_at_utc,
    )


def build_legacy_sql_connector_metadata_connection_probe_gate_command(
    *,
    live_connection_gate: LegacySqlConnectorLiveConnectionGateEvidence,
    provider_driver_snapshot: LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot,
    secret_broker_read_path_snapshot: LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot,
    metadata_query_allowlist_snapshot: LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot,
    timeout_circuit_breaker_execution_snapshot: LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot,
    audit_sink_execution_snapshot: LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot,
    emergency_disable_execution_snapshot: LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot,
    requested_by: str,
    metadata_connection_probe_gate_requested: bool = True,
    provider_driver_load_requested: bool = False,
    secret_broker_read_requested: bool = False,
    metadata_connection_probe_requested: bool = False,
    metadata_query_execution_requested: bool = False,
    socket_runtime_execution_requested: bool = False,
    raw_data_access_requested: bool = False,
    import_dry_run_requested: bool = False,
    import_write_requested: bool = False,
    destructive_actions_requested: bool = False,
) -> LegacySqlConnectorMetadataConnectionProbeGateCommand:
    return LegacySqlConnectorMetadataConnectionProbeGateCommand(
        tenant_id=live_connection_gate.tenant_id,
        module_id=live_connection_gate.module_id,
        source_system_ref=live_connection_gate.source_system_ref,
        connector_kind=live_connection_gate.connector_kind,
        live_connection_gate_evidence_hash=live_connection_gate.evidence_hash,
        provider_driver_snapshot_hash=provider_driver_snapshot.evidence_hash,
        secret_broker_read_path_snapshot_hash=secret_broker_read_path_snapshot.evidence_hash,
        metadata_query_allowlist_snapshot_hash=metadata_query_allowlist_snapshot.evidence_hash,
        timeout_circuit_breaker_execution_snapshot_hash=timeout_circuit_breaker_execution_snapshot.evidence_hash,
        audit_sink_execution_snapshot_hash=audit_sink_execution_snapshot.evidence_hash,
        emergency_disable_execution_snapshot_hash=emergency_disable_execution_snapshot.evidence_hash,
        requested_by=requested_by,
        metadata_connection_probe_gate_requested=metadata_connection_probe_gate_requested,
        provider_driver_load_requested=provider_driver_load_requested,
        secret_broker_read_requested=secret_broker_read_requested,
        metadata_connection_probe_requested=metadata_connection_probe_requested,
        metadata_query_execution_requested=metadata_query_execution_requested,
        socket_runtime_execution_requested=socket_runtime_execution_requested,
        raw_data_access_requested=raw_data_access_requested,
        import_dry_run_requested=import_dry_run_requested,
        import_write_requested=import_write_requested,
        destructive_actions_requested=destructive_actions_requested,
    )


def build_legacy_sql_connector_metadata_connection_probe_gate(
    *,
    command: LegacySqlConnectorMetadataConnectionProbeGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    live_connection_gate: LegacySqlConnectorLiveConnectionGateEvidence,
    provider_driver_snapshot: LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot,
    secret_broker_read_path_snapshot: LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot,
    metadata_query_allowlist_snapshot: LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot,
    timeout_circuit_breaker_execution_snapshot: LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot,
    audit_sink_execution_snapshot: LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot,
    emergency_disable_execution_snapshot: LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot,
    checked_by: str,
    checked_at_utc: datetime | None = None,
) -> LegacySqlConnectorMetadataConnectionProbeGateEvidence:
    checked_at = checked_at_utc or datetime.now(UTC)
    live_connection_gate_hash_valid = (
        build_legacy_sql_connector_live_connection_gate_hash(live_connection_gate)
        == live_connection_gate.evidence_hash
        == command.live_connection_gate_evidence_hash
    )
    live_connection_gate_ready = (
        live_connection_gate.gate_status == LegacySqlConnectorLiveConnectionGateStatus.READY
        and live_connection_gate.live_connection_gate_ready
        and live_connection_gate.future_metadata_connection_probe_gate_required
    )
    live_connection_gate_bound = _live_connection_gate_bound(
        command=command, bundle=bundle, live_connection_gate=live_connection_gate
    )
    provider_hash_valid = _snapshot_hash_valid(provider_driver_snapshot, command.provider_driver_snapshot_hash)
    secret_hash_valid = _snapshot_hash_valid(
        secret_broker_read_path_snapshot, command.secret_broker_read_path_snapshot_hash
    )
    allowlist_hash_valid = _snapshot_hash_valid(
        metadata_query_allowlist_snapshot, command.metadata_query_allowlist_snapshot_hash
    )
    timeout_hash_valid = _snapshot_hash_valid(
        timeout_circuit_breaker_execution_snapshot, command.timeout_circuit_breaker_execution_snapshot_hash
    )
    audit_hash_valid = _snapshot_hash_valid(audit_sink_execution_snapshot, command.audit_sink_execution_snapshot_hash)
    emergency_hash_valid = _snapshot_hash_valid(
        emergency_disable_execution_snapshot, command.emergency_disable_execution_snapshot_hash
    )
    provider_bound = _snapshot_bound(
        command=command,
        live_connection_gate=live_connection_gate,
        snapshot=provider_driver_snapshot,
        expected_schema=LEGACY_SQL_CONNECTOR_METADATA_CONNECTION_PROBE_PROVIDER_DRIVER_SNAPSHOT_SCHEMA_VERSION,
    )
    secret_bound = _snapshot_bound(
        command=command,
        live_connection_gate=live_connection_gate,
        snapshot=secret_broker_read_path_snapshot,
        expected_schema=LEGACY_SQL_CONNECTOR_METADATA_CONNECTION_PROBE_SECRET_BROKER_READ_PATH_SNAPSHOT_SCHEMA_VERSION,
        required_upstream_hash=live_connection_gate.secret_broker_binding_snapshot_hash,
    )
    allowlist_bound = _snapshot_bound(
        command=command,
        live_connection_gate=live_connection_gate,
        snapshot=metadata_query_allowlist_snapshot,
        expected_schema=LEGACY_SQL_CONNECTOR_METADATA_CONNECTION_PROBE_QUERY_ALLOWLIST_SNAPSHOT_SCHEMA_VERSION,
    )
    timeout_bound = _snapshot_bound(
        command=command,
        live_connection_gate=live_connection_gate,
        snapshot=timeout_circuit_breaker_execution_snapshot,
        expected_schema=LEGACY_SQL_CONNECTOR_METADATA_CONNECTION_PROBE_TIMEOUT_CIRCUIT_BREAKER_EXECUTION_SNAPSHOT_SCHEMA_VERSION,
        required_upstream_hash=live_connection_gate.timeout_circuit_breaker_snapshot_hash,
    )
    audit_bound = _snapshot_bound(
        command=command,
        live_connection_gate=live_connection_gate,
        snapshot=audit_sink_execution_snapshot,
        expected_schema=LEGACY_SQL_CONNECTOR_METADATA_CONNECTION_PROBE_AUDIT_SINK_EXECUTION_SNAPSHOT_SCHEMA_VERSION,
        required_upstream_hash=live_connection_gate.audit_sink_snapshot_hash,
    )
    emergency_bound = _snapshot_bound(
        command=command,
        live_connection_gate=live_connection_gate,
        snapshot=emergency_disable_execution_snapshot,
        expected_schema=LEGACY_SQL_CONNECTOR_METADATA_CONNECTION_PROBE_EMERGENCY_DISABLE_EXECUTION_SNAPSHOT_SCHEMA_VERSION,
        required_upstream_hash=live_connection_gate.emergency_disable_snapshot_hash,
    )
    provider_passed = _snapshot_passed(provider_driver_snapshot)
    secret_passed = _snapshot_passed(secret_broker_read_path_snapshot)
    allowlist_passed = _snapshot_passed(metadata_query_allowlist_snapshot)
    timeout_passed = _snapshot_passed(timeout_circuit_breaker_execution_snapshot)
    audit_passed = _snapshot_passed(audit_sink_execution_snapshot)
    emergency_passed = _snapshot_passed(emergency_disable_execution_snapshot)
    blocking_reasons = _metadata_connection_probe_blocking_reasons(
        command=command,
        live_connection_gate_hash_valid=live_connection_gate_hash_valid,
        live_connection_gate_ready=live_connection_gate_ready,
        live_connection_gate_bound=live_connection_gate_bound,
        snapshot_checks=(
            ("provider_driver", provider_hash_valid, provider_bound, provider_passed, provider_driver_snapshot),
            (
                "secret_broker_read_path",
                secret_hash_valid,
                secret_bound,
                secret_passed,
                secret_broker_read_path_snapshot,
            ),
            (
                "metadata_query_allowlist",
                allowlist_hash_valid,
                allowlist_bound,
                allowlist_passed,
                metadata_query_allowlist_snapshot,
            ),
            (
                "timeout_circuit_breaker_execution",
                timeout_hash_valid,
                timeout_bound,
                timeout_passed,
                timeout_circuit_breaker_execution_snapshot,
            ),
            ("audit_sink_execution", audit_hash_valid, audit_bound, audit_passed, audit_sink_execution_snapshot),
            (
                "emergency_disable_execution",
                emergency_hash_valid,
                emergency_bound,
                emergency_passed,
                emergency_disable_execution_snapshot,
            ),
        ),
    )
    ready = not blocking_reasons
    draft = LegacySqlConnectorMetadataConnectionProbeGateEvidence(
        tenant_id=live_connection_gate.tenant_id,
        module_id=live_connection_gate.module_id,
        source_system_ref=live_connection_gate.source_system_ref,
        connector_kind=live_connection_gate.connector_kind,
        live_connection_gate_evidence_hash=live_connection_gate.evidence_hash,
        provider_driver_snapshot_hash=provider_driver_snapshot.evidence_hash,
        secret_broker_read_path_snapshot_hash=secret_broker_read_path_snapshot.evidence_hash,
        metadata_query_allowlist_snapshot_hash=metadata_query_allowlist_snapshot.evidence_hash,
        timeout_circuit_breaker_execution_snapshot_hash=timeout_circuit_breaker_execution_snapshot.evidence_hash,
        audit_sink_execution_snapshot_hash=audit_sink_execution_snapshot.evidence_hash,
        emergency_disable_execution_snapshot_hash=emergency_disable_execution_snapshot.evidence_hash,
        live_connection_gate_hash_valid=live_connection_gate_hash_valid,
        live_connection_gate_ready=live_connection_gate_ready,
        live_connection_gate_bound=live_connection_gate_bound,
        provider_driver_snapshot_hash_valid=provider_hash_valid,
        provider_driver_snapshot_bound=provider_bound,
        provider_driver_passed=provider_passed,
        secret_broker_read_path_snapshot_hash_valid=secret_hash_valid,
        secret_broker_read_path_snapshot_bound=secret_bound,
        secret_broker_read_path_passed=secret_passed,
        metadata_query_allowlist_snapshot_hash_valid=allowlist_hash_valid,
        metadata_query_allowlist_snapshot_bound=allowlist_bound,
        metadata_query_allowlist_passed=allowlist_passed,
        timeout_circuit_breaker_execution_snapshot_hash_valid=timeout_hash_valid,
        timeout_circuit_breaker_execution_snapshot_bound=timeout_bound,
        timeout_circuit_breaker_execution_passed=timeout_passed,
        audit_sink_execution_snapshot_hash_valid=audit_hash_valid,
        audit_sink_execution_snapshot_bound=audit_bound,
        audit_sink_execution_passed=audit_passed,
        emergency_disable_execution_snapshot_hash_valid=emergency_hash_valid,
        emergency_disable_execution_snapshot_bound=emergency_bound,
        emergency_disable_execution_passed=emergency_passed,
        metadata_connection_probe_gate_requested=command.metadata_connection_probe_gate_requested,
        metadata_connection_probe_gate_ready=ready,
        provider_driver_load_requested=command.provider_driver_load_requested,
        secret_broker_read_requested=command.secret_broker_read_requested,
        metadata_connection_probe_requested=command.metadata_connection_probe_requested,
        metadata_query_execution_requested=command.metadata_query_execution_requested,
        socket_runtime_execution_requested=command.socket_runtime_execution_requested,
        raw_data_access_requested=command.raw_data_access_requested,
        import_dry_run_requested=command.import_dry_run_requested,
        import_write_requested=command.import_write_requested,
        destructive_actions_requested=command.destructive_actions_requested,
        gate_status=LegacySqlConnectorMetadataConnectionProbeGateStatus.READY
        if ready
        else LegacySqlConnectorMetadataConnectionProbeGateStatus.BLOCKED,
        blocking_reasons=blocking_reasons,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_metadata_connection_probe_gate_hash(draft)}
    )


def build_legacy_sql_connector_metadata_connection_probe_snapshot_hash(
    snapshot: LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot,
) -> str:
    return stable_hash(canonical_json(snapshot.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_metadata_connection_probe_gate_hash(
    gate: LegacySqlConnectorMetadataConnectionProbeGateEvidence,
) -> str:
    return stable_hash(canonical_json(gate.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_metadata_connection_probe_gate_smoke_report_hash(
    report: LegacySqlConnectorMetadataConnectionProbeGateSmokeReport,
) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def run_legacy_sql_connector_metadata_connection_probe_gate_smoke_from_env(
    environ: Mapping[str, str] | None = None,
) -> LegacySqlConnectorMetadataConnectionProbeGateSmokeReport:
    env = os.environ if environ is None else environ
    checked_by = env.get(
        "SUITE_LEGACY_SQL_CONNECTOR_METADATA_CONNECTION_PROBE_GATE_CHECKED_BY",
        "legacy-sql-connector-metadata-connection-probe-gate-smoke",
    )
    checked_at = datetime.now(UTC)
    store_backend = LegacySqlConnectorRealConnectionPolicyStoreBackend(
        env.get(
            "SUITE_LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_POLICY_STORE_BACKEND",
            LegacySqlConnectorRealConnectionPolicyStoreBackend.JSONL.value,
        )
    )
    bundle, live_connection_gate = _build_ready_live_connection_gate(
        env=env, checked_by=checked_by, checked_at=checked_at
    )
    snapshots = _build_ready_metadata_connection_probe_snapshots(
        live_connection_gate=live_connection_gate,
        checked_by=checked_by,
        checked_at=checked_at,
    )
    command = _build_metadata_connection_probe_command_from_snapshots(
        live_connection_gate=live_connection_gate,
        snapshots=snapshots,
        requested_by=checked_by,
    )
    gate = _build_metadata_connection_probe_gate_from_snapshots(
        command=command,
        bundle=bundle,
        live_connection_gate=live_connection_gate,
        snapshots=snapshots,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=127),
    )
    live_connection_gate_missing_blocked = _live_connection_gate_missing_blocked(
        command, bundle, live_connection_gate, snapshots, checked_by, checked_at + timedelta(seconds=128)
    )
    provider_missing_blocked = _snapshot_missing_blocked(
        command,
        bundle,
        live_connection_gate,
        snapshots,
        "provider_driver_snapshot",
        "provider_driver_package_pinned",
        "provider_driver_snapshot_failed",
        checked_by,
        checked_at + timedelta(seconds=129),
    )
    secret_missing_blocked = _snapshot_missing_blocked(
        command,
        bundle,
        live_connection_gate,
        snapshots,
        "secret_broker_read_path_snapshot",
        "secret_broker_read_path_bound",
        "secret_broker_read_path_snapshot_failed",
        checked_by,
        checked_at + timedelta(seconds=130),
    )
    allowlist_missing_blocked = _snapshot_missing_blocked(
        command,
        bundle,
        live_connection_gate,
        snapshots,
        "metadata_query_allowlist_snapshot",
        "metadata_catalog_queries_allowlisted",
        "metadata_query_allowlist_snapshot_failed",
        checked_by,
        checked_at + timedelta(seconds=131),
    )
    timeout_missing_blocked = _snapshot_missing_blocked(
        command,
        bundle,
        live_connection_gate,
        snapshots,
        "timeout_circuit_breaker_execution_snapshot",
        "connect_timeout_execution_bound",
        "timeout_circuit_breaker_execution_snapshot_failed",
        checked_by,
        checked_at + timedelta(seconds=132),
    )
    audit_missing_blocked = _snapshot_missing_blocked(
        command,
        bundle,
        live_connection_gate,
        snapshots,
        "audit_sink_execution_snapshot",
        "probe_attempt_audit_event_bound",
        "audit_sink_execution_snapshot_failed",
        checked_by,
        checked_at + timedelta(seconds=133),
    )
    emergency_missing_blocked = _snapshot_missing_blocked(
        command,
        bundle,
        live_connection_gate,
        snapshots,
        "emergency_disable_execution_snapshot",
        "tenant_emergency_disable_execution_bound",
        "emergency_disable_execution_snapshot_failed",
        checked_by,
        checked_at + timedelta(seconds=134),
    )
    direct_probe_request_blocked = _direct_probe_request_blocked(
        command,
        bundle,
        live_connection_gate,
        snapshots,
        checked_by,
        checked_at + timedelta(seconds=135),
    )
    metadata_connection_probe_gate_ready = (
        gate.gate_status == LegacySqlConnectorMetadataConnectionProbeGateStatus.READY
        and gate.metadata_connection_probe_gate_ready
        and live_connection_gate_missing_blocked
        and provider_missing_blocked
        and secret_missing_blocked
        and allowlist_missing_blocked
        and timeout_missing_blocked
        and audit_missing_blocked
        and emergency_missing_blocked
        and direct_probe_request_blocked
        and not gate.provider_driver_load_allowed
        and not gate.secret_broker_read_allowed
        and not gate.metadata_connection_probe_executed
        and not gate.real_connection_opened
    )
    draft = LegacySqlConnectorMetadataConnectionProbeGateSmokeReport(
        tenant_id=bundle.tenant_id,
        store_backend=store_backend,
        live_connection_gate_evidence_hash=live_connection_gate.evidence_hash,
        metadata_connection_probe_gate_evidence_hash=gate.evidence_hash,
        metadata_connection_probe_gate_ready=metadata_connection_probe_gate_ready,
        live_connection_gate_required=gate.live_connection_gate_bound and gate.live_connection_gate_ready,
        provider_driver_snapshot_required=gate.provider_driver_snapshot_bound and gate.provider_driver_passed,
        secret_broker_read_path_snapshot_required=(
            gate.secret_broker_read_path_snapshot_bound and gate.secret_broker_read_path_passed
        ),
        metadata_query_allowlist_snapshot_required=(
            gate.metadata_query_allowlist_snapshot_bound and gate.metadata_query_allowlist_passed
        ),
        timeout_circuit_breaker_execution_snapshot_required=(
            gate.timeout_circuit_breaker_execution_snapshot_bound and gate.timeout_circuit_breaker_execution_passed
        ),
        audit_sink_execution_snapshot_required=gate.audit_sink_execution_snapshot_bound
        and gate.audit_sink_execution_passed,
        emergency_disable_execution_snapshot_required=(
            gate.emergency_disable_execution_snapshot_bound and gate.emergency_disable_execution_passed
        ),
        live_connection_gate_missing_blocked=live_connection_gate_missing_blocked,
        provider_driver_missing_blocked=provider_missing_blocked,
        secret_broker_read_path_missing_blocked=secret_missing_blocked,
        metadata_query_allowlist_missing_blocked=allowlist_missing_blocked,
        timeout_circuit_breaker_execution_missing_blocked=timeout_missing_blocked,
        audit_sink_execution_missing_blocked=audit_missing_blocked,
        emergency_disable_execution_missing_blocked=emergency_missing_blocked,
        direct_probe_request_blocked=direct_probe_request_blocked,
        future_metadata_probe_implementation_required=gate.future_metadata_probe_implementation_required,
        future_secret_materialization_gate_required=gate.future_secret_materialization_gate_required,
        future_import_dry_run_gate_required=gate.future_import_dry_run_gate_required,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    _assert_metadata_connection_probe_safe(draft)
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_metadata_connection_probe_gate_smoke_report_hash(draft)}
    )


def exit_code_for_report(report: LegacySqlConnectorMetadataConnectionProbeGateSmokeReport) -> int:
    return 0 if report.metadata_connection_probe_gate_ready else 1


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Legacy SQL metadata connection probe gate smoke.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one non-executing metadata connection probe gate smoke and exit.",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the metadata connection probe gate report.")
    args = parser.parse_args(argv)
    del args.once

    report = run_legacy_sql_connector_metadata_connection_probe_gate_smoke_from_env()
    print(json.dumps(report.model_dump(mode="json"), indent=2 if args.pretty else None, sort_keys=True))
    raise SystemExit(exit_code_for_report(report))


def _build_snapshot(
    *,
    schema_version: str,
    snapshot_ref: str,
    live_connection_gate: LegacySqlConnectorLiveConnectionGateEvidence,
    required_controls: tuple[str, ...],
    failed_controls: tuple[str, ...],
    checked_by: str,
    checked_at_utc: datetime | None,
    upstream_evidence_hashes: tuple[str, ...] = (),
) -> LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot:
    checked_at = checked_at_utc or datetime.now(UTC)
    passed_controls = tuple(control for control in required_controls if control not in failed_controls)
    draft = LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot(
        schema_version=schema_version,
        tenant_id=live_connection_gate.tenant_id,
        module_id=live_connection_gate.module_id,
        source_system_ref=live_connection_gate.source_system_ref,
        connector_kind=live_connection_gate.connector_kind,
        snapshot_ref=snapshot_ref,
        live_connection_gate_evidence_hash=live_connection_gate.evidence_hash,
        upstream_evidence_hashes=upstream_evidence_hashes,
        required_controls=required_controls,
        passed_controls=passed_controls,
        failed_controls=failed_controls,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_metadata_connection_probe_snapshot_hash(draft)}
    )


def _build_ready_live_connection_gate(
    *,
    env: Mapping[str, str],
    checked_by: str,
    checked_at: datetime,
) -> tuple[LegacySqlConnectorRealConnectionExecutorPolicyBundle, LegacySqlConnectorLiveConnectionGateEvidence]:
    bundle, runtime_activation_gate = _build_ready_runtime_activation_gate(
        env=env, checked_by=checked_by, checked_at=checked_at
    )
    live_snapshots = _build_ready_live_connection_snapshots(
        runtime_activation_gate=runtime_activation_gate,
        checked_by=checked_by,
        checked_at=checked_at,
    )
    live_command = _build_live_connection_command_from_snapshots(
        runtime_activation_gate=runtime_activation_gate,
        snapshots=live_snapshots,
        requested_by=checked_by,
    )
    live_connection_gate = _build_live_connection_gate_from_snapshots(
        command=live_command,
        bundle=bundle,
        runtime_activation_gate=runtime_activation_gate,
        snapshots=live_snapshots,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=110),
    )
    return bundle, live_connection_gate


def _build_ready_metadata_connection_probe_snapshots(
    *,
    live_connection_gate: LegacySqlConnectorLiveConnectionGateEvidence,
    checked_by: str,
    checked_at: datetime,
) -> dict[str, LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot]:
    return {
        "provider_driver_snapshot": build_legacy_sql_connector_metadata_connection_probe_provider_driver_snapshot(
            live_connection_gate=live_connection_gate,
            checked_by=checked_by,
            checked_at_utc=checked_at + timedelta(seconds=121),
        ),
        "secret_broker_read_path_snapshot": (
            build_legacy_sql_connector_metadata_connection_probe_secret_broker_read_path_snapshot(
                live_connection_gate=live_connection_gate,
                checked_by=checked_by,
                checked_at_utc=checked_at + timedelta(seconds=122),
            )
        ),
        "metadata_query_allowlist_snapshot": (
            build_legacy_sql_connector_metadata_connection_probe_query_allowlist_snapshot(
                live_connection_gate=live_connection_gate,
                checked_by=checked_by,
                checked_at_utc=checked_at + timedelta(seconds=123),
            )
        ),
        "timeout_circuit_breaker_execution_snapshot": (
            build_legacy_sql_connector_metadata_connection_probe_timeout_circuit_breaker_execution_snapshot(
                live_connection_gate=live_connection_gate,
                checked_by=checked_by,
                checked_at_utc=checked_at + timedelta(seconds=124),
            )
        ),
        "audit_sink_execution_snapshot": (
            build_legacy_sql_connector_metadata_connection_probe_audit_sink_execution_snapshot(
                live_connection_gate=live_connection_gate,
                checked_by=checked_by,
                checked_at_utc=checked_at + timedelta(seconds=125),
            )
        ),
        "emergency_disable_execution_snapshot": (
            build_legacy_sql_connector_metadata_connection_probe_emergency_disable_execution_snapshot(
                live_connection_gate=live_connection_gate,
                checked_by=checked_by,
                checked_at_utc=checked_at + timedelta(seconds=126),
            )
        ),
    }


def _snapshot_hash_valid(
    snapshot: LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot, expected_hash: str
) -> bool:
    return (
        build_legacy_sql_connector_metadata_connection_probe_snapshot_hash(snapshot)
        == snapshot.evidence_hash
        == expected_hash
    )


def _snapshot_passed(snapshot: LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot) -> bool:
    return not snapshot.failed_controls and set(snapshot.required_controls) == set(snapshot.passed_controls)


def _snapshot_bound(
    *,
    command: LegacySqlConnectorMetadataConnectionProbeGateCommand,
    live_connection_gate: LegacySqlConnectorLiveConnectionGateEvidence,
    snapshot: LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot,
    expected_schema: str,
    required_upstream_hash: str | None = None,
) -> bool:
    upstream_bound = required_upstream_hash is None or required_upstream_hash in snapshot.upstream_evidence_hashes
    return (
        command.tenant_id == live_connection_gate.tenant_id == snapshot.tenant_id
        and command.module_id == live_connection_gate.module_id == snapshot.module_id
        and command.source_system_ref == live_connection_gate.source_system_ref == snapshot.source_system_ref
        and command.connector_kind == live_connection_gate.connector_kind == snapshot.connector_kind
        and snapshot.schema_version == expected_schema
        and snapshot.live_connection_gate_evidence_hash == live_connection_gate.evidence_hash
        and upstream_bound
    )


def _live_connection_gate_bound(
    *,
    command: LegacySqlConnectorMetadataConnectionProbeGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    live_connection_gate: LegacySqlConnectorLiveConnectionGateEvidence,
) -> bool:
    return (
        command.tenant_id == bundle.tenant_id == live_connection_gate.tenant_id
        and command.module_id == bundle.module_id == live_connection_gate.module_id
        and command.source_system_ref == bundle.source_system_ref == live_connection_gate.source_system_ref
        and command.connector_kind == bundle.connector_kind == live_connection_gate.connector_kind
        and command.live_connection_gate_evidence_hash == live_connection_gate.evidence_hash
        and not live_connection_gate.metadata_connection_probe_allowed
        and not live_connection_gate.secret_broker_resolution_allowed
        and not live_connection_gate.socket_runtime_execution_allowed
        and not live_connection_gate.network_socket_opened
        and not live_connection_gate.real_connection_opened
        and not live_connection_gate.secret_material_resolved
    )


def _metadata_connection_probe_blocking_reasons(
    *,
    command: LegacySqlConnectorMetadataConnectionProbeGateCommand,
    live_connection_gate_hash_valid: bool,
    live_connection_gate_ready: bool,
    live_connection_gate_bound: bool,
    snapshot_checks: tuple[
        tuple[str, bool, bool, bool, LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot], ...
    ],
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not live_connection_gate_hash_valid:
        reasons.append("live_connection_gate_hash_invalid")
    if not live_connection_gate_ready:
        reasons.append("live_connection_gate_not_ready")
    if not live_connection_gate_bound:
        reasons.append("live_connection_gate_not_bound")
    for prefix, hash_valid, bound, passed, snapshot in snapshot_checks:
        if not hash_valid:
            reasons.append(f"{prefix}_snapshot_hash_invalid")
        if not bound:
            reasons.append(f"{prefix}_snapshot_not_bound")
        if not passed:
            reasons.append(f"{prefix}_snapshot_failed")
        for failed_control in snapshot.failed_controls:
            reasons.append(f"{prefix}_{failed_control}_failed")
    if not command.metadata_connection_probe_gate_requested:
        reasons.append("metadata_connection_probe_gate_not_requested")
    if command.provider_driver_load_requested:
        reasons.append("provider_driver_load_requires_future_probe_implementation")
    if command.secret_broker_read_requested:
        reasons.append("secret_broker_read_requires_future_secret_gate")
    if command.metadata_connection_probe_requested:
        reasons.append("metadata_connection_probe_requires_future_probe_implementation")
    if command.metadata_query_execution_requested:
        reasons.append("metadata_query_execution_requires_future_probe_implementation")
    if command.socket_runtime_execution_requested:
        reasons.append("socket_runtime_execution_requires_future_probe_implementation")
    if command.raw_data_access_requested:
        reasons.append("raw_data_access_requires_future_data_gate")
    if command.import_dry_run_requested:
        reasons.append("import_dry_run_requires_future_import_gate")
    if command.import_write_requested:
        reasons.append("import_write_requires_future_import_gate")
    if command.destructive_actions_requested:
        reasons.append("destructive_actions_require_human_confirmation_gate")
    return tuple(dict.fromkeys(reasons))


def _build_metadata_connection_probe_command_from_snapshots(
    *,
    live_connection_gate: LegacySqlConnectorLiveConnectionGateEvidence,
    snapshots: dict[str, LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot],
    requested_by: str,
) -> LegacySqlConnectorMetadataConnectionProbeGateCommand:
    return build_legacy_sql_connector_metadata_connection_probe_gate_command(
        live_connection_gate=live_connection_gate,
        provider_driver_snapshot=snapshots["provider_driver_snapshot"],
        secret_broker_read_path_snapshot=snapshots["secret_broker_read_path_snapshot"],
        metadata_query_allowlist_snapshot=snapshots["metadata_query_allowlist_snapshot"],
        timeout_circuit_breaker_execution_snapshot=snapshots["timeout_circuit_breaker_execution_snapshot"],
        audit_sink_execution_snapshot=snapshots["audit_sink_execution_snapshot"],
        emergency_disable_execution_snapshot=snapshots["emergency_disable_execution_snapshot"],
        requested_by=requested_by,
    )


def _build_metadata_connection_probe_gate_from_snapshots(
    *,
    command: LegacySqlConnectorMetadataConnectionProbeGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    live_connection_gate: LegacySqlConnectorLiveConnectionGateEvidence,
    snapshots: dict[str, LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot],
    checked_by: str,
    checked_at_utc: datetime,
) -> LegacySqlConnectorMetadataConnectionProbeGateEvidence:
    return build_legacy_sql_connector_metadata_connection_probe_gate(
        command=command,
        bundle=bundle,
        live_connection_gate=live_connection_gate,
        provider_driver_snapshot=snapshots["provider_driver_snapshot"],
        secret_broker_read_path_snapshot=snapshots["secret_broker_read_path_snapshot"],
        metadata_query_allowlist_snapshot=snapshots["metadata_query_allowlist_snapshot"],
        timeout_circuit_breaker_execution_snapshot=snapshots["timeout_circuit_breaker_execution_snapshot"],
        audit_sink_execution_snapshot=snapshots["audit_sink_execution_snapshot"],
        emergency_disable_execution_snapshot=snapshots["emergency_disable_execution_snapshot"],
        checked_by=checked_by,
        checked_at_utc=checked_at_utc,
    )


def _live_connection_gate_missing_blocked(
    command: LegacySqlConnectorMetadataConnectionProbeGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    live_connection_gate: LegacySqlConnectorLiveConnectionGateEvidence,
    snapshots: dict[str, LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot],
    checked_by: str,
    checked_at: datetime,
) -> bool:
    blocked_live_gate = live_connection_gate.model_copy(
        update={
            "gate_status": LegacySqlConnectorLiveConnectionGateStatus.BLOCKED,
            "live_connection_gate_ready": False,
            "blocking_reasons": ("metadata_connection_probe_test_live_gate_missing",),
            "checked_at_utc": checked_at,
            "evidence_hash": ZERO_HASH,
        }
    )
    blocked_live_gate = blocked_live_gate.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_live_connection_gate_hash(blocked_live_gate)}
    )
    blocked = _build_metadata_connection_probe_gate_from_snapshots(
        command=command.model_copy(update={"live_connection_gate_evidence_hash": blocked_live_gate.evidence_hash}),
        bundle=bundle,
        live_connection_gate=blocked_live_gate,
        snapshots=snapshots,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        blocked.gate_status == LegacySqlConnectorMetadataConnectionProbeGateStatus.BLOCKED
        and "live_connection_gate_not_ready" in blocked.blocking_reasons
    )


def _snapshot_missing_blocked(
    command: LegacySqlConnectorMetadataConnectionProbeGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    live_connection_gate: LegacySqlConnectorLiveConnectionGateEvidence,
    snapshots: dict[str, LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot],
    snapshot_key: str,
    failed_control: str,
    expected_reason: str,
    checked_by: str,
    checked_at: datetime,
) -> bool:
    updated_snapshots = dict(snapshots)
    snapshot = snapshots[snapshot_key]
    failed_controls = tuple(dict.fromkeys((*snapshot.failed_controls, failed_control)))
    blocked_snapshot = snapshot.model_copy(
        update={
            "passed_controls": tuple(
                control for control in snapshot.required_controls if control not in failed_controls
            ),
            "failed_controls": failed_controls,
            "checked_at_utc": checked_at,
            "evidence_hash": ZERO_HASH,
        }
    )
    blocked_snapshot = blocked_snapshot.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_metadata_connection_probe_snapshot_hash(blocked_snapshot)}
    )
    updated_snapshots[snapshot_key] = blocked_snapshot
    command_field = f"{snapshot_key}_hash"
    blocked = _build_metadata_connection_probe_gate_from_snapshots(
        command=command.model_copy(update={command_field: blocked_snapshot.evidence_hash}),
        bundle=bundle,
        live_connection_gate=live_connection_gate,
        snapshots=updated_snapshots,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        blocked.gate_status == LegacySqlConnectorMetadataConnectionProbeGateStatus.BLOCKED
        and expected_reason in blocked.blocking_reasons
    )


def _direct_probe_request_blocked(
    command: LegacySqlConnectorMetadataConnectionProbeGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    live_connection_gate: LegacySqlConnectorLiveConnectionGateEvidence,
    snapshots: dict[str, LegacySqlConnectorMetadataConnectionProbeEvidenceSnapshot],
    checked_by: str,
    checked_at: datetime,
) -> bool:
    blocked = _build_metadata_connection_probe_gate_from_snapshots(
        command=command.model_copy(
            update={
                "provider_driver_load_requested": True,
                "secret_broker_read_requested": True,
                "metadata_connection_probe_requested": True,
                "metadata_query_execution_requested": True,
                "socket_runtime_execution_requested": True,
                "raw_data_access_requested": True,
            }
        ),
        bundle=bundle,
        live_connection_gate=live_connection_gate,
        snapshots=snapshots,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        blocked.gate_status == LegacySqlConnectorMetadataConnectionProbeGateStatus.BLOCKED
        and "provider_driver_load_requires_future_probe_implementation" in blocked.blocking_reasons
        and "secret_broker_read_requires_future_secret_gate" in blocked.blocking_reasons
        and "metadata_connection_probe_requires_future_probe_implementation" in blocked.blocking_reasons
        and "metadata_query_execution_requires_future_probe_implementation" in blocked.blocking_reasons
        and "socket_runtime_execution_requires_future_probe_implementation" in blocked.blocking_reasons
        and "raw_data_access_requires_future_data_gate" in blocked.blocking_reasons
        and not blocked.provider_driver_load_allowed
        and not blocked.metadata_connection_probe_executed
        and not blocked.real_connection_opened
    )


def _assert_metadata_connection_probe_safe(value: BaseModel) -> None:
    payload = value.model_dump_json().lower()
    for fragment in FORBIDDEN_METADATA_CONNECTION_PROBE_FRAGMENTS:
        if fragment in payload:
            raise ValueError(f"legacy SQL metadata connection probe evidence contains forbidden fragment: {fragment}")


if __name__ == "__main__":
    main()
