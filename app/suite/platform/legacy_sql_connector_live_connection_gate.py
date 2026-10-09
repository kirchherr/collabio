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
from suite.platform.legacy_sql_connector_real_connection_executor import (
    LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    LegacySqlConnectorRealConnectionPolicyStoreBackend,
)
from suite.platform.legacy_sql_connector_runtime_activation_gate import (
    LegacySqlConnectorRuntimeActivationGateEvidence,
    LegacySqlConnectorRuntimeActivationGateStatus,
    _build_ready_runtime_activation_snapshots,
    _build_ready_runtime_merge_gate,
    _build_runtime_activation_command_from_snapshots,
    _build_runtime_activation_gate_from_snapshots,
    build_legacy_sql_connector_runtime_activation_gate_hash,
)
from suite.platform.legacy_sql_discovery import MODULE_ID_PATTERN, NAMESPACED_REF_PATTERN, LegacySqlConnectorKind
from suite.platform.legacy_sql_metadata_worker_queue import LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN

LEGACY_SQL_CONNECTOR_LIVE_CONNECTION_SECRET_BROKER_BINDING_SNAPSHOT_SCHEMA_VERSION = (
    "legacy_sql_connector_live_connection_secret_broker_binding_snapshot.v1"
)
LEGACY_SQL_CONNECTOR_LIVE_CONNECTION_NETWORK_EGRESS_POLICY_SNAPSHOT_SCHEMA_VERSION = (
    "legacy_sql_connector_live_connection_network_egress_policy_snapshot.v1"
)
LEGACY_SQL_CONNECTOR_LIVE_CONNECTION_LEAST_PRIVILEGE_DB_ROLE_SNAPSHOT_SCHEMA_VERSION = (
    "legacy_sql_connector_live_connection_least_privilege_db_role_snapshot.v1"
)
LEGACY_SQL_CONNECTOR_LIVE_CONNECTION_TIMEOUT_CIRCUIT_BREAKER_SNAPSHOT_SCHEMA_VERSION = (
    "legacy_sql_connector_live_connection_timeout_circuit_breaker_snapshot.v1"
)
LEGACY_SQL_CONNECTOR_LIVE_CONNECTION_AUDIT_SINK_SNAPSHOT_SCHEMA_VERSION = (
    "legacy_sql_connector_live_connection_audit_sink_snapshot.v1"
)
LEGACY_SQL_CONNECTOR_LIVE_CONNECTION_EMERGENCY_DISABLE_SNAPSHOT_SCHEMA_VERSION = (
    "legacy_sql_connector_live_connection_emergency_disable_snapshot.v1"
)
LEGACY_SQL_CONNECTOR_LIVE_CONNECTION_GATE_SCHEMA_VERSION = "legacy_sql_connector_live_connection_gate.v1"
LEGACY_SQL_CONNECTOR_LIVE_CONNECTION_GATE_SMOKE_SCHEMA_VERSION = (
    "legacy_sql_connector_live_connection_gate_smoke_report.v1"
)
LEGACY_SQL_CONNECTOR_LIVE_CONNECTION_GATE_COMMAND_REF = "docker-compose:legacy-sql-connector-live-connection-gate-smoke"
ZERO_HASH = "sha256:" + "0" * 64
SHA256_REF_PATTERN = r"^sha256:[a-f0-9]{64}$"
_ALLOWED_SNAPSHOT_SCHEMAS = {
    LEGACY_SQL_CONNECTOR_LIVE_CONNECTION_SECRET_BROKER_BINDING_SNAPSHOT_SCHEMA_VERSION,
    LEGACY_SQL_CONNECTOR_LIVE_CONNECTION_NETWORK_EGRESS_POLICY_SNAPSHOT_SCHEMA_VERSION,
    LEGACY_SQL_CONNECTOR_LIVE_CONNECTION_LEAST_PRIVILEGE_DB_ROLE_SNAPSHOT_SCHEMA_VERSION,
    LEGACY_SQL_CONNECTOR_LIVE_CONNECTION_TIMEOUT_CIRCUIT_BREAKER_SNAPSHOT_SCHEMA_VERSION,
    LEGACY_SQL_CONNECTOR_LIVE_CONNECTION_AUDIT_SINK_SNAPSHOT_SCHEMA_VERSION,
    LEGACY_SQL_CONNECTOR_LIVE_CONNECTION_EMERGENCY_DISABLE_SNAPSHOT_SCHEMA_VERSION,
}
FORBIDDEN_LIVE_CONNECTION_FRAGMENTS = (
    '"connection_secret_ref":',
    '"connection_secret_value":',
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


class LegacySqlConnectorLiveConnectionGateStatus(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"


class LegacySqlConnectorLiveConnectionEvidenceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    snapshot_ref: str
    runtime_activation_gate_evidence_hash: str
    upstream_evidence_hashes: tuple[str, ...] = ()
    required_controls: tuple[str, ...]
    passed_controls: tuple[str, ...]
    failed_controls: tuple[str, ...] = ()
    metadata_connection_probe_allowed: bool = False
    live_connection_probe_allowed: bool = False
    secret_broker_resolution_allowed: bool = False
    socket_runtime_execution_allowed: bool = False
    secret_materialization_allowed: bool = False
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
            raise ValueError("legacy SQL live connection snapshot schema is not allowed")
        return value

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL live connection snapshot text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL live connection snapshot module_id must be lowercase snake_case")
        return value

    @field_validator("source_system_ref", "snapshot_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL live connection snapshot references must be namespaced")
        return value

    @field_validator("runtime_activation_gate_evidence_hash", "evidence_hash")
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL live connection snapshot hashes must be sha256 references")
        return value

    @field_validator("upstream_evidence_hashes")
    @classmethod
    def validate_upstream_hashes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for item in value:
            if not re.fullmatch(SHA256_REF_PATTERN, item):
                raise ValueError("legacy SQL live connection snapshot upstream hashes must be sha256 references")
        return value

    @field_validator("required_controls", "passed_controls", "failed_controls")
    @classmethod
    def validate_controls(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("legacy SQL live connection snapshot controls must be unique")
        for item in value:
            if not item.strip():
                raise ValueError("legacy SQL live connection snapshot controls must not be empty")
        return value

    @model_validator(mode="after")
    def require_safe_snapshot(self) -> Self:
        if (
            self.metadata_connection_probe_allowed
            or self.live_connection_probe_allowed
            or self.secret_broker_resolution_allowed
            or self.socket_runtime_execution_allowed
            or self.secret_materialization_allowed
            or self.network_socket_opened
            or self.network_connection_opened
            or self.real_connection_opened
            or self.secret_material_resolved
            or self.raw_data_access_allowed
            or self.import_dry_run_allowed
            or self.import_write_allowed
            or self.destructive_actions_allowed
        ):
            raise ValueError("legacy SQL live connection snapshot must remain non-executing")
        missing_controls = set(self.required_controls) - set(self.passed_controls) - set(self.failed_controls)
        if missing_controls:
            raise ValueError("legacy SQL live connection snapshot must classify every required control")
        _assert_live_connection_safe(self)
        return self


class LegacySqlConnectorLiveConnectionGateCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    runtime_activation_gate_evidence_hash: str
    secret_broker_binding_snapshot_hash: str
    network_egress_policy_snapshot_hash: str
    least_privilege_db_role_snapshot_hash: str
    timeout_circuit_breaker_snapshot_hash: str
    audit_sink_snapshot_hash: str
    emergency_disable_snapshot_hash: str
    requested_by: str
    live_connection_gate_requested: bool = True
    metadata_connection_probe_requested: bool = False
    live_connection_probe_requested: bool = False
    secret_broker_resolution_requested: bool = False
    socket_runtime_execution_requested: bool = False
    secret_materialization_requested: bool = False
    raw_data_access_requested: bool = False
    import_dry_run_requested: bool = False
    import_write_requested: bool = False
    destructive_actions_requested: bool = False

    @field_validator("tenant_id", "requested_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL live connection gate command text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL live connection gate command module_id must be lowercase snake_case")
        return value

    @field_validator("source_system_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL live connection gate command references must be namespaced")
        return value

    @field_validator(
        "runtime_activation_gate_evidence_hash",
        "secret_broker_binding_snapshot_hash",
        "network_egress_policy_snapshot_hash",
        "least_privilege_db_role_snapshot_hash",
        "timeout_circuit_breaker_snapshot_hash",
        "audit_sink_snapshot_hash",
        "emergency_disable_snapshot_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL live connection gate command hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_safe_command(self) -> Self:
        _assert_live_connection_safe(self)
        return self


class LegacySqlConnectorLiveConnectionGateEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_LIVE_CONNECTION_GATE_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    continuity_domain: str = LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN
    command_ref: str = LEGACY_SQL_CONNECTOR_LIVE_CONNECTION_GATE_COMMAND_REF
    runtime_activation_gate_evidence_hash: str
    secret_broker_binding_snapshot_hash: str
    network_egress_policy_snapshot_hash: str
    least_privilege_db_role_snapshot_hash: str
    timeout_circuit_breaker_snapshot_hash: str
    audit_sink_snapshot_hash: str
    emergency_disable_snapshot_hash: str
    runtime_activation_gate_hash_valid: bool
    runtime_activation_gate_ready: bool
    runtime_activation_gate_bound: bool
    secret_broker_binding_snapshot_hash_valid: bool
    secret_broker_binding_snapshot_bound: bool
    secret_broker_binding_passed: bool
    network_egress_policy_snapshot_hash_valid: bool
    network_egress_policy_snapshot_bound: bool
    network_egress_policy_passed: bool
    least_privilege_db_role_snapshot_hash_valid: bool
    least_privilege_db_role_snapshot_bound: bool
    least_privilege_db_role_passed: bool
    timeout_circuit_breaker_snapshot_hash_valid: bool
    timeout_circuit_breaker_snapshot_bound: bool
    timeout_circuit_breaker_passed: bool
    audit_sink_snapshot_hash_valid: bool
    audit_sink_snapshot_bound: bool
    audit_sink_passed: bool
    emergency_disable_snapshot_hash_valid: bool
    emergency_disable_snapshot_bound: bool
    emergency_disable_passed: bool
    live_connection_gate_requested: bool
    live_connection_gate_ready: bool
    future_metadata_connection_probe_gate_required: bool = True
    future_secret_materialization_gate_required: bool = True
    future_import_dry_run_gate_required: bool = True
    metadata_connection_probe_requested: bool = False
    metadata_connection_probe_allowed: bool = False
    live_connection_probe_requested: bool = False
    live_connection_probe_allowed: bool = False
    secret_broker_resolution_requested: bool = False
    secret_broker_resolution_allowed: bool = False
    socket_runtime_execution_requested: bool = False
    socket_runtime_execution_allowed: bool = False
    secret_materialization_requested: bool = False
    secret_materialization_allowed: bool = False
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
    gate_status: LegacySqlConnectorLiveConnectionGateStatus
    blocking_reasons: tuple[str, ...]
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL live connection gate text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL live connection gate module_id must be lowercase snake_case")
        return value

    @field_validator("source_system_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL live connection gate references must be namespaced")
        return value

    @field_validator(
        "runtime_activation_gate_evidence_hash",
        "secret_broker_binding_snapshot_hash",
        "network_egress_policy_snapshot_hash",
        "least_privilege_db_role_snapshot_hash",
        "timeout_circuit_breaker_snapshot_hash",
        "audit_sink_snapshot_hash",
        "emergency_disable_snapshot_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL live connection gate hashes must be sha256 references")
        return value

    @field_validator("blocking_reasons")
    @classmethod
    def validate_blocking_reasons(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("legacy SQL live connection gate blocking reasons must be unique")
        for reason in value:
            if not reason.strip():
                raise ValueError("legacy SQL live connection gate blocking reasons must not be empty")
        return value

    @model_validator(mode="after")
    def require_safe_gate(self) -> Self:
        if (
            self.metadata_connection_probe_allowed
            or self.live_connection_probe_allowed
            or self.secret_broker_resolution_allowed
            or self.socket_runtime_execution_allowed
            or self.secret_materialization_allowed
            or self.network_socket_opened
            or self.network_connection_opened
            or self.real_connection_opened
            or self.secret_material_resolved
            or self.raw_data_access_allowed
            or self.import_dry_run_allowed
            or self.import_write_allowed
            or self.destructive_actions_allowed
        ):
            raise ValueError("legacy SQL live connection gate must remain non-executing")
        if (
            not self.future_metadata_connection_probe_gate_required
            or not self.future_secret_materialization_gate_required
            or not self.future_import_dry_run_gate_required
        ):
            raise ValueError("legacy SQL live connection gate must require future execution gates")
        if self.gate_status == LegacySqlConnectorLiveConnectionGateStatus.READY:
            required = (
                self.runtime_activation_gate_hash_valid,
                self.runtime_activation_gate_ready,
                self.runtime_activation_gate_bound,
                self.secret_broker_binding_snapshot_hash_valid,
                self.secret_broker_binding_snapshot_bound,
                self.secret_broker_binding_passed,
                self.network_egress_policy_snapshot_hash_valid,
                self.network_egress_policy_snapshot_bound,
                self.network_egress_policy_passed,
                self.least_privilege_db_role_snapshot_hash_valid,
                self.least_privilege_db_role_snapshot_bound,
                self.least_privilege_db_role_passed,
                self.timeout_circuit_breaker_snapshot_hash_valid,
                self.timeout_circuit_breaker_snapshot_bound,
                self.timeout_circuit_breaker_passed,
                self.audit_sink_snapshot_hash_valid,
                self.audit_sink_snapshot_bound,
                self.audit_sink_passed,
                self.emergency_disable_snapshot_hash_valid,
                self.emergency_disable_snapshot_bound,
                self.emergency_disable_passed,
                self.live_connection_gate_requested,
                self.live_connection_gate_ready,
            )
            if not all(required) or self.blocking_reasons:
                raise ValueError("ready legacy SQL live connection gate requires complete evidence")
        if self.gate_status == LegacySqlConnectorLiveConnectionGateStatus.BLOCKED:
            if not self.blocking_reasons:
                raise ValueError("blocked legacy SQL live connection gate requires blocking reasons")
            if self.live_connection_gate_ready:
                raise ValueError("blocked legacy SQL live connection gate cannot be ready")
        _assert_live_connection_safe(self)
        return self


class LegacySqlConnectorLiveConnectionGateSmokeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_LIVE_CONNECTION_GATE_SMOKE_SCHEMA_VERSION
    tenant_id: str
    store_backend: LegacySqlConnectorRealConnectionPolicyStoreBackend
    continuity_domain: str = LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN
    command_ref: str = LEGACY_SQL_CONNECTOR_LIVE_CONNECTION_GATE_COMMAND_REF
    runtime_activation_gate_evidence_hash: str
    live_connection_gate_evidence_hash: str
    live_connection_gate_ready: bool
    runtime_activation_gate_required: bool
    secret_broker_binding_snapshot_required: bool
    network_egress_policy_snapshot_required: bool
    least_privilege_db_role_snapshot_required: bool
    timeout_circuit_breaker_snapshot_required: bool
    audit_sink_snapshot_required: bool
    emergency_disable_snapshot_required: bool
    runtime_activation_gate_missing_blocked: bool
    secret_broker_binding_missing_blocked: bool
    network_egress_policy_missing_blocked: bool
    least_privilege_db_role_missing_blocked: bool
    timeout_circuit_breaker_missing_blocked: bool
    audit_sink_missing_blocked: bool
    emergency_disable_missing_blocked: bool
    metadata_probe_request_blocked: bool
    future_metadata_connection_probe_gate_required: bool
    future_secret_materialization_gate_required: bool
    future_import_dry_run_gate_required: bool
    metadata_connection_probe_allowed: bool = False
    live_connection_probe_allowed: bool = False
    secret_broker_resolution_allowed: bool = False
    socket_runtime_execution_allowed: bool = False
    secret_materialization_allowed: bool = False
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
            self.metadata_connection_probe_allowed
            or self.live_connection_probe_allowed
            or self.secret_broker_resolution_allowed
            or self.socket_runtime_execution_allowed
            or self.secret_materialization_allowed
            or self.network_socket_opened
            or self.network_connection_opened
            or self.real_connection_opened
            or self.secret_material_resolved
            or self.raw_data_access_allowed
            or self.import_dry_run_allowed
            or self.import_write_allowed
            or self.destructive_actions_allowed
        ):
            raise ValueError("legacy SQL live connection smoke must remain non-executing")
        _assert_live_connection_safe(self)
        return self


def build_legacy_sql_connector_live_connection_secret_broker_binding_snapshot(
    *,
    runtime_activation_gate: LegacySqlConnectorRuntimeActivationGateEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    passed: bool = True,
) -> LegacySqlConnectorLiveConnectionEvidenceSnapshot:
    return _build_snapshot(
        schema_version=LEGACY_SQL_CONNECTOR_LIVE_CONNECTION_SECRET_BROKER_BINDING_SNAPSHOT_SCHEMA_VERSION,
        snapshot_ref="live-connection-secret-broker-binding:legacy-sql-live-connection",
        runtime_activation_gate=runtime_activation_gate,
        upstream_evidence_hashes=(runtime_activation_gate.secret_rotation_confirmation_snapshot_hash,),
        required_controls=(
            "secret_broker_binding_metadata_ready",
            "sealed_secret_handle_metadata_present",
            "broker_access_policy_reviewed",
            "no_secret_material_resolved",
            "rotation_confirmation_bound",
        ),
        failed_controls=() if passed else ("secret_broker_binding_metadata_ready",),
        checked_by=checked_by,
        checked_at_utc=checked_at_utc,
    )


def build_legacy_sql_connector_live_connection_network_egress_policy_snapshot(
    *,
    runtime_activation_gate: LegacySqlConnectorRuntimeActivationGateEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    passed: bool = True,
) -> LegacySqlConnectorLiveConnectionEvidenceSnapshot:
    return _build_snapshot(
        schema_version=LEGACY_SQL_CONNECTOR_LIVE_CONNECTION_NETWORK_EGRESS_POLICY_SNAPSHOT_SCHEMA_VERSION,
        snapshot_ref="live-connection-network-egress-policy:legacy-sql-live-connection",
        runtime_activation_gate=runtime_activation_gate,
        upstream_evidence_hashes=(runtime_activation_gate.network_authorization_snapshot_hash,),
        required_controls=(
            "egress_policy_bound",
            "target_host_allowlist_metadata_ready",
            "deny_by_default_confirmed",
            "no_socket_probe_performed",
            "change_ticket_bound",
        ),
        failed_controls=() if passed else ("egress_policy_bound",),
        checked_by=checked_by,
        checked_at_utc=checked_at_utc,
    )


def build_legacy_sql_connector_live_connection_least_privilege_db_role_snapshot(
    *,
    runtime_activation_gate: LegacySqlConnectorRuntimeActivationGateEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    passed: bool = True,
) -> LegacySqlConnectorLiveConnectionEvidenceSnapshot:
    return _build_snapshot(
        schema_version=LEGACY_SQL_CONNECTOR_LIVE_CONNECTION_LEAST_PRIVILEGE_DB_ROLE_SNAPSHOT_SCHEMA_VERSION,
        snapshot_ref="live-connection-least-privilege-db-role:legacy-sql-live-connection",
        runtime_activation_gate=runtime_activation_gate,
        required_controls=(
            "least_privilege_db_role_defined",
            "read_metadata_only_role_confirmed",
            "no_write_permission",
            "no_cross_database_privilege",
            "credential_scope_tenant_bound",
        ),
        failed_controls=() if passed else ("least_privilege_db_role_defined",),
        checked_by=checked_by,
        checked_at_utc=checked_at_utc,
    )


def build_legacy_sql_connector_live_connection_timeout_circuit_breaker_snapshot(
    *,
    runtime_activation_gate: LegacySqlConnectorRuntimeActivationGateEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    passed: bool = True,
) -> LegacySqlConnectorLiveConnectionEvidenceSnapshot:
    return _build_snapshot(
        schema_version=LEGACY_SQL_CONNECTOR_LIVE_CONNECTION_TIMEOUT_CIRCUIT_BREAKER_SNAPSHOT_SCHEMA_VERSION,
        snapshot_ref="live-connection-timeout-circuit-breaker:legacy-sql-live-connection",
        runtime_activation_gate=runtime_activation_gate,
        required_controls=(
            "connect_timeout_defined",
            "metadata_query_timeout_defined",
            "retry_budget_defined",
            "circuit_breaker_defined",
            "connection_pool_limits_defined",
        ),
        failed_controls=() if passed else ("connect_timeout_defined",),
        checked_by=checked_by,
        checked_at_utc=checked_at_utc,
    )


def build_legacy_sql_connector_live_connection_audit_sink_snapshot(
    *,
    runtime_activation_gate: LegacySqlConnectorRuntimeActivationGateEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    passed: bool = True,
) -> LegacySqlConnectorLiveConnectionEvidenceSnapshot:
    return _build_snapshot(
        schema_version=LEGACY_SQL_CONNECTOR_LIVE_CONNECTION_AUDIT_SINK_SNAPSHOT_SCHEMA_VERSION,
        snapshot_ref="live-connection-audit-sink:legacy-sql-live-connection",
        runtime_activation_gate=runtime_activation_gate,
        required_controls=(
            "audit_sink_bound",
            "probe_attempt_audit_schema_ready",
            "tool_call_hash_logging_ready",
            "redaction_policy_bound",
            "tenant_trace_context_required",
        ),
        failed_controls=() if passed else ("audit_sink_bound",),
        checked_by=checked_by,
        checked_at_utc=checked_at_utc,
    )


def build_legacy_sql_connector_live_connection_emergency_disable_snapshot(
    *,
    runtime_activation_gate: LegacySqlConnectorRuntimeActivationGateEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    passed: bool = True,
) -> LegacySqlConnectorLiveConnectionEvidenceSnapshot:
    return _build_snapshot(
        schema_version=LEGACY_SQL_CONNECTOR_LIVE_CONNECTION_EMERGENCY_DISABLE_SNAPSHOT_SCHEMA_VERSION,
        snapshot_ref="live-connection-emergency-disable:legacy-sql-live-connection",
        runtime_activation_gate=runtime_activation_gate,
        upstream_evidence_hashes=(runtime_activation_gate.kill_switch_arming_snapshot_hash,),
        required_controls=(
            "tenant_emergency_disable_armed",
            "global_emergency_disable_armed",
            "circuit_breaker_trip_path_verified",
            "operator_abort_path_confirmed",
            "post_probe_shutdown_runbook_ready",
        ),
        failed_controls=() if passed else ("tenant_emergency_disable_armed",),
        checked_by=checked_by,
        checked_at_utc=checked_at_utc,
    )


def build_legacy_sql_connector_live_connection_gate_command(
    *,
    runtime_activation_gate: LegacySqlConnectorRuntimeActivationGateEvidence,
    secret_broker_binding_snapshot: LegacySqlConnectorLiveConnectionEvidenceSnapshot,
    network_egress_policy_snapshot: LegacySqlConnectorLiveConnectionEvidenceSnapshot,
    least_privilege_db_role_snapshot: LegacySqlConnectorLiveConnectionEvidenceSnapshot,
    timeout_circuit_breaker_snapshot: LegacySqlConnectorLiveConnectionEvidenceSnapshot,
    audit_sink_snapshot: LegacySqlConnectorLiveConnectionEvidenceSnapshot,
    emergency_disable_snapshot: LegacySqlConnectorLiveConnectionEvidenceSnapshot,
    requested_by: str,
    live_connection_gate_requested: bool = True,
    metadata_connection_probe_requested: bool = False,
    live_connection_probe_requested: bool = False,
    secret_broker_resolution_requested: bool = False,
    socket_runtime_execution_requested: bool = False,
    secret_materialization_requested: bool = False,
    raw_data_access_requested: bool = False,
    import_dry_run_requested: bool = False,
    import_write_requested: bool = False,
    destructive_actions_requested: bool = False,
) -> LegacySqlConnectorLiveConnectionGateCommand:
    return LegacySqlConnectorLiveConnectionGateCommand(
        tenant_id=runtime_activation_gate.tenant_id,
        module_id=runtime_activation_gate.module_id,
        source_system_ref=runtime_activation_gate.source_system_ref,
        connector_kind=runtime_activation_gate.connector_kind,
        runtime_activation_gate_evidence_hash=runtime_activation_gate.evidence_hash,
        secret_broker_binding_snapshot_hash=secret_broker_binding_snapshot.evidence_hash,
        network_egress_policy_snapshot_hash=network_egress_policy_snapshot.evidence_hash,
        least_privilege_db_role_snapshot_hash=least_privilege_db_role_snapshot.evidence_hash,
        timeout_circuit_breaker_snapshot_hash=timeout_circuit_breaker_snapshot.evidence_hash,
        audit_sink_snapshot_hash=audit_sink_snapshot.evidence_hash,
        emergency_disable_snapshot_hash=emergency_disable_snapshot.evidence_hash,
        requested_by=requested_by,
        live_connection_gate_requested=live_connection_gate_requested,
        metadata_connection_probe_requested=metadata_connection_probe_requested,
        live_connection_probe_requested=live_connection_probe_requested,
        secret_broker_resolution_requested=secret_broker_resolution_requested,
        socket_runtime_execution_requested=socket_runtime_execution_requested,
        secret_materialization_requested=secret_materialization_requested,
        raw_data_access_requested=raw_data_access_requested,
        import_dry_run_requested=import_dry_run_requested,
        import_write_requested=import_write_requested,
        destructive_actions_requested=destructive_actions_requested,
    )


def build_legacy_sql_connector_live_connection_gate(
    *,
    command: LegacySqlConnectorLiveConnectionGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    runtime_activation_gate: LegacySqlConnectorRuntimeActivationGateEvidence,
    secret_broker_binding_snapshot: LegacySqlConnectorLiveConnectionEvidenceSnapshot,
    network_egress_policy_snapshot: LegacySqlConnectorLiveConnectionEvidenceSnapshot,
    least_privilege_db_role_snapshot: LegacySqlConnectorLiveConnectionEvidenceSnapshot,
    timeout_circuit_breaker_snapshot: LegacySqlConnectorLiveConnectionEvidenceSnapshot,
    audit_sink_snapshot: LegacySqlConnectorLiveConnectionEvidenceSnapshot,
    emergency_disable_snapshot: LegacySqlConnectorLiveConnectionEvidenceSnapshot,
    checked_by: str,
    checked_at_utc: datetime | None = None,
) -> LegacySqlConnectorLiveConnectionGateEvidence:
    checked_at = checked_at_utc or datetime.now(UTC)
    runtime_activation_gate_hash_valid = (
        build_legacy_sql_connector_runtime_activation_gate_hash(runtime_activation_gate)
        == runtime_activation_gate.evidence_hash
        == command.runtime_activation_gate_evidence_hash
    )
    runtime_activation_gate_ready = (
        runtime_activation_gate.gate_status == LegacySqlConnectorRuntimeActivationGateStatus.READY
        and runtime_activation_gate.runtime_activation_gate_ready
        and runtime_activation_gate.future_live_connection_gate_required
    )
    runtime_activation_gate_bound = _runtime_activation_gate_bound(
        command=command, bundle=bundle, runtime_activation_gate=runtime_activation_gate
    )
    secret_broker_hash_valid = _snapshot_hash_valid(
        secret_broker_binding_snapshot, command.secret_broker_binding_snapshot_hash
    )
    network_hash_valid = _snapshot_hash_valid(
        network_egress_policy_snapshot, command.network_egress_policy_snapshot_hash
    )
    db_role_hash_valid = _snapshot_hash_valid(
        least_privilege_db_role_snapshot, command.least_privilege_db_role_snapshot_hash
    )
    timeout_hash_valid = _snapshot_hash_valid(
        timeout_circuit_breaker_snapshot, command.timeout_circuit_breaker_snapshot_hash
    )
    audit_hash_valid = _snapshot_hash_valid(audit_sink_snapshot, command.audit_sink_snapshot_hash)
    emergency_hash_valid = _snapshot_hash_valid(emergency_disable_snapshot, command.emergency_disable_snapshot_hash)
    secret_broker_bound = _snapshot_bound(
        command=command,
        runtime_activation_gate=runtime_activation_gate,
        snapshot=secret_broker_binding_snapshot,
        expected_schema=LEGACY_SQL_CONNECTOR_LIVE_CONNECTION_SECRET_BROKER_BINDING_SNAPSHOT_SCHEMA_VERSION,
        required_upstream_hash=runtime_activation_gate.secret_rotation_confirmation_snapshot_hash,
    )
    network_bound = _snapshot_bound(
        command=command,
        runtime_activation_gate=runtime_activation_gate,
        snapshot=network_egress_policy_snapshot,
        expected_schema=LEGACY_SQL_CONNECTOR_LIVE_CONNECTION_NETWORK_EGRESS_POLICY_SNAPSHOT_SCHEMA_VERSION,
        required_upstream_hash=runtime_activation_gate.network_authorization_snapshot_hash,
    )
    db_role_bound = _snapshot_bound(
        command=command,
        runtime_activation_gate=runtime_activation_gate,
        snapshot=least_privilege_db_role_snapshot,
        expected_schema=LEGACY_SQL_CONNECTOR_LIVE_CONNECTION_LEAST_PRIVILEGE_DB_ROLE_SNAPSHOT_SCHEMA_VERSION,
    )
    timeout_bound = _snapshot_bound(
        command=command,
        runtime_activation_gate=runtime_activation_gate,
        snapshot=timeout_circuit_breaker_snapshot,
        expected_schema=LEGACY_SQL_CONNECTOR_LIVE_CONNECTION_TIMEOUT_CIRCUIT_BREAKER_SNAPSHOT_SCHEMA_VERSION,
    )
    audit_bound = _snapshot_bound(
        command=command,
        runtime_activation_gate=runtime_activation_gate,
        snapshot=audit_sink_snapshot,
        expected_schema=LEGACY_SQL_CONNECTOR_LIVE_CONNECTION_AUDIT_SINK_SNAPSHOT_SCHEMA_VERSION,
    )
    emergency_bound = _snapshot_bound(
        command=command,
        runtime_activation_gate=runtime_activation_gate,
        snapshot=emergency_disable_snapshot,
        expected_schema=LEGACY_SQL_CONNECTOR_LIVE_CONNECTION_EMERGENCY_DISABLE_SNAPSHOT_SCHEMA_VERSION,
        required_upstream_hash=runtime_activation_gate.kill_switch_arming_snapshot_hash,
    )
    secret_broker_passed = _snapshot_passed(secret_broker_binding_snapshot)
    network_passed = _snapshot_passed(network_egress_policy_snapshot)
    db_role_passed = _snapshot_passed(least_privilege_db_role_snapshot)
    timeout_passed = _snapshot_passed(timeout_circuit_breaker_snapshot)
    audit_passed = _snapshot_passed(audit_sink_snapshot)
    emergency_passed = _snapshot_passed(emergency_disable_snapshot)
    blocking_reasons = _live_connection_blocking_reasons(
        command=command,
        runtime_activation_gate_hash_valid=runtime_activation_gate_hash_valid,
        runtime_activation_gate_ready=runtime_activation_gate_ready,
        runtime_activation_gate_bound=runtime_activation_gate_bound,
        snapshot_checks=(
            (
                "secret_broker_binding",
                secret_broker_hash_valid,
                secret_broker_bound,
                secret_broker_passed,
                secret_broker_binding_snapshot,
            ),
            (
                "network_egress_policy",
                network_hash_valid,
                network_bound,
                network_passed,
                network_egress_policy_snapshot,
            ),
            (
                "least_privilege_db_role",
                db_role_hash_valid,
                db_role_bound,
                db_role_passed,
                least_privilege_db_role_snapshot,
            ),
            (
                "timeout_circuit_breaker",
                timeout_hash_valid,
                timeout_bound,
                timeout_passed,
                timeout_circuit_breaker_snapshot,
            ),
            ("audit_sink", audit_hash_valid, audit_bound, audit_passed, audit_sink_snapshot),
            (
                "emergency_disable",
                emergency_hash_valid,
                emergency_bound,
                emergency_passed,
                emergency_disable_snapshot,
            ),
        ),
    )
    ready = not blocking_reasons
    draft = LegacySqlConnectorLiveConnectionGateEvidence(
        tenant_id=runtime_activation_gate.tenant_id,
        module_id=runtime_activation_gate.module_id,
        source_system_ref=runtime_activation_gate.source_system_ref,
        connector_kind=runtime_activation_gate.connector_kind,
        runtime_activation_gate_evidence_hash=runtime_activation_gate.evidence_hash,
        secret_broker_binding_snapshot_hash=secret_broker_binding_snapshot.evidence_hash,
        network_egress_policy_snapshot_hash=network_egress_policy_snapshot.evidence_hash,
        least_privilege_db_role_snapshot_hash=least_privilege_db_role_snapshot.evidence_hash,
        timeout_circuit_breaker_snapshot_hash=timeout_circuit_breaker_snapshot.evidence_hash,
        audit_sink_snapshot_hash=audit_sink_snapshot.evidence_hash,
        emergency_disable_snapshot_hash=emergency_disable_snapshot.evidence_hash,
        runtime_activation_gate_hash_valid=runtime_activation_gate_hash_valid,
        runtime_activation_gate_ready=runtime_activation_gate_ready,
        runtime_activation_gate_bound=runtime_activation_gate_bound,
        secret_broker_binding_snapshot_hash_valid=secret_broker_hash_valid,
        secret_broker_binding_snapshot_bound=secret_broker_bound,
        secret_broker_binding_passed=secret_broker_passed,
        network_egress_policy_snapshot_hash_valid=network_hash_valid,
        network_egress_policy_snapshot_bound=network_bound,
        network_egress_policy_passed=network_passed,
        least_privilege_db_role_snapshot_hash_valid=db_role_hash_valid,
        least_privilege_db_role_snapshot_bound=db_role_bound,
        least_privilege_db_role_passed=db_role_passed,
        timeout_circuit_breaker_snapshot_hash_valid=timeout_hash_valid,
        timeout_circuit_breaker_snapshot_bound=timeout_bound,
        timeout_circuit_breaker_passed=timeout_passed,
        audit_sink_snapshot_hash_valid=audit_hash_valid,
        audit_sink_snapshot_bound=audit_bound,
        audit_sink_passed=audit_passed,
        emergency_disable_snapshot_hash_valid=emergency_hash_valid,
        emergency_disable_snapshot_bound=emergency_bound,
        emergency_disable_passed=emergency_passed,
        live_connection_gate_requested=command.live_connection_gate_requested,
        live_connection_gate_ready=ready,
        metadata_connection_probe_requested=command.metadata_connection_probe_requested,
        live_connection_probe_requested=command.live_connection_probe_requested,
        secret_broker_resolution_requested=command.secret_broker_resolution_requested,
        socket_runtime_execution_requested=command.socket_runtime_execution_requested,
        secret_materialization_requested=command.secret_materialization_requested,
        raw_data_access_requested=command.raw_data_access_requested,
        import_dry_run_requested=command.import_dry_run_requested,
        import_write_requested=command.import_write_requested,
        destructive_actions_requested=command.destructive_actions_requested,
        gate_status=LegacySqlConnectorLiveConnectionGateStatus.READY
        if ready
        else LegacySqlConnectorLiveConnectionGateStatus.BLOCKED,
        blocking_reasons=blocking_reasons,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_connector_live_connection_gate_hash(draft)})


def build_legacy_sql_connector_live_connection_snapshot_hash(
    snapshot: LegacySqlConnectorLiveConnectionEvidenceSnapshot,
) -> str:
    return stable_hash(canonical_json(snapshot.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_live_connection_gate_hash(gate: LegacySqlConnectorLiveConnectionGateEvidence) -> str:
    return stable_hash(canonical_json(gate.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_live_connection_gate_smoke_report_hash(
    report: LegacySqlConnectorLiveConnectionGateSmokeReport,
) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def run_legacy_sql_connector_live_connection_gate_smoke_from_env(
    environ: Mapping[str, str] | None = None,
) -> LegacySqlConnectorLiveConnectionGateSmokeReport:
    env = os.environ if environ is None else environ
    checked_by = env.get(
        "SUITE_LEGACY_SQL_CONNECTOR_LIVE_CONNECTION_GATE_CHECKED_BY",
        "legacy-sql-connector-live-connection-gate-smoke",
    )
    checked_at = datetime.now(UTC)
    store_backend = LegacySqlConnectorRealConnectionPolicyStoreBackend(
        env.get(
            "SUITE_LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_POLICY_STORE_BACKEND",
            LegacySqlConnectorRealConnectionPolicyStoreBackend.JSONL.value,
        )
    )
    bundle, runtime_activation_gate = _build_ready_runtime_activation_gate(
        env=env, checked_by=checked_by, checked_at=checked_at
    )
    snapshots = _build_ready_live_connection_snapshots(
        runtime_activation_gate=runtime_activation_gate,
        checked_by=checked_by,
        checked_at=checked_at,
    )
    command = _build_live_connection_command_from_snapshots(
        runtime_activation_gate=runtime_activation_gate,
        snapshots=snapshots,
        requested_by=checked_by,
    )
    gate = _build_live_connection_gate_from_snapshots(
        command=command,
        bundle=bundle,
        runtime_activation_gate=runtime_activation_gate,
        snapshots=snapshots,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=107),
    )
    runtime_activation_gate_missing_blocked = _runtime_activation_gate_missing_blocked(
        command, bundle, runtime_activation_gate, snapshots, checked_by, checked_at + timedelta(seconds=108)
    )
    secret_broker_missing_blocked = _snapshot_missing_blocked(
        command,
        bundle,
        runtime_activation_gate,
        snapshots,
        "secret_broker_binding_snapshot",
        "secret_broker_binding_metadata_ready",
        "secret_broker_binding_snapshot_failed",
        checked_by,
        checked_at + timedelta(seconds=109),
    )
    network_missing_blocked = _snapshot_missing_blocked(
        command,
        bundle,
        runtime_activation_gate,
        snapshots,
        "network_egress_policy_snapshot",
        "egress_policy_bound",
        "network_egress_policy_snapshot_failed",
        checked_by,
        checked_at + timedelta(seconds=110),
    )
    db_role_missing_blocked = _snapshot_missing_blocked(
        command,
        bundle,
        runtime_activation_gate,
        snapshots,
        "least_privilege_db_role_snapshot",
        "least_privilege_db_role_defined",
        "least_privilege_db_role_snapshot_failed",
        checked_by,
        checked_at + timedelta(seconds=111),
    )
    timeout_missing_blocked = _snapshot_missing_blocked(
        command,
        bundle,
        runtime_activation_gate,
        snapshots,
        "timeout_circuit_breaker_snapshot",
        "connect_timeout_defined",
        "timeout_circuit_breaker_snapshot_failed",
        checked_by,
        checked_at + timedelta(seconds=112),
    )
    audit_missing_blocked = _snapshot_missing_blocked(
        command,
        bundle,
        runtime_activation_gate,
        snapshots,
        "audit_sink_snapshot",
        "audit_sink_bound",
        "audit_sink_snapshot_failed",
        checked_by,
        checked_at + timedelta(seconds=113),
    )
    emergency_missing_blocked = _snapshot_missing_blocked(
        command,
        bundle,
        runtime_activation_gate,
        snapshots,
        "emergency_disable_snapshot",
        "tenant_emergency_disable_armed",
        "emergency_disable_snapshot_failed",
        checked_by,
        checked_at + timedelta(seconds=114),
    )
    metadata_probe_request_blocked = _metadata_probe_request_blocked(
        command,
        bundle,
        runtime_activation_gate,
        snapshots,
        checked_by,
        checked_at + timedelta(seconds=115),
    )
    live_connection_gate_ready = (
        gate.gate_status == LegacySqlConnectorLiveConnectionGateStatus.READY
        and gate.live_connection_gate_ready
        and runtime_activation_gate_missing_blocked
        and secret_broker_missing_blocked
        and network_missing_blocked
        and db_role_missing_blocked
        and timeout_missing_blocked
        and audit_missing_blocked
        and emergency_missing_blocked
        and metadata_probe_request_blocked
        and not gate.metadata_connection_probe_allowed
        and not gate.secret_broker_resolution_allowed
        and not gate.real_connection_opened
    )
    draft = LegacySqlConnectorLiveConnectionGateSmokeReport(
        tenant_id=bundle.tenant_id,
        store_backend=store_backend,
        runtime_activation_gate_evidence_hash=runtime_activation_gate.evidence_hash,
        live_connection_gate_evidence_hash=gate.evidence_hash,
        live_connection_gate_ready=live_connection_gate_ready,
        runtime_activation_gate_required=gate.runtime_activation_gate_bound and gate.runtime_activation_gate_ready,
        secret_broker_binding_snapshot_required=(
            gate.secret_broker_binding_snapshot_bound and gate.secret_broker_binding_passed
        ),
        network_egress_policy_snapshot_required=(
            gate.network_egress_policy_snapshot_bound and gate.network_egress_policy_passed
        ),
        least_privilege_db_role_snapshot_required=(
            gate.least_privilege_db_role_snapshot_bound and gate.least_privilege_db_role_passed
        ),
        timeout_circuit_breaker_snapshot_required=(
            gate.timeout_circuit_breaker_snapshot_bound and gate.timeout_circuit_breaker_passed
        ),
        audit_sink_snapshot_required=gate.audit_sink_snapshot_bound and gate.audit_sink_passed,
        emergency_disable_snapshot_required=gate.emergency_disable_snapshot_bound and gate.emergency_disable_passed,
        runtime_activation_gate_missing_blocked=runtime_activation_gate_missing_blocked,
        secret_broker_binding_missing_blocked=secret_broker_missing_blocked,
        network_egress_policy_missing_blocked=network_missing_blocked,
        least_privilege_db_role_missing_blocked=db_role_missing_blocked,
        timeout_circuit_breaker_missing_blocked=timeout_missing_blocked,
        audit_sink_missing_blocked=audit_missing_blocked,
        emergency_disable_missing_blocked=emergency_missing_blocked,
        metadata_probe_request_blocked=metadata_probe_request_blocked,
        future_metadata_connection_probe_gate_required=gate.future_metadata_connection_probe_gate_required,
        future_secret_materialization_gate_required=gate.future_secret_materialization_gate_required,
        future_import_dry_run_gate_required=gate.future_import_dry_run_gate_required,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    _assert_live_connection_safe(draft)
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_live_connection_gate_smoke_report_hash(draft)}
    )


def exit_code_for_report(report: LegacySqlConnectorLiveConnectionGateSmokeReport) -> int:
    return 0 if report.live_connection_gate_ready else 1


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Legacy SQL live connection gate smoke.")
    parser.add_argument(
        "--once", action="store_true", help="Run one non-executing live connection gate smoke and exit."
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the live connection gate report.")
    args = parser.parse_args(argv)
    del args.once

    report = run_legacy_sql_connector_live_connection_gate_smoke_from_env()
    print(json.dumps(report.model_dump(mode="json"), indent=2 if args.pretty else None, sort_keys=True))
    raise SystemExit(exit_code_for_report(report))


def _build_snapshot(
    *,
    schema_version: str,
    snapshot_ref: str,
    runtime_activation_gate: LegacySqlConnectorRuntimeActivationGateEvidence,
    required_controls: tuple[str, ...],
    failed_controls: tuple[str, ...],
    checked_by: str,
    checked_at_utc: datetime | None,
    upstream_evidence_hashes: tuple[str, ...] = (),
) -> LegacySqlConnectorLiveConnectionEvidenceSnapshot:
    checked_at = checked_at_utc or datetime.now(UTC)
    passed_controls = tuple(control for control in required_controls if control not in failed_controls)
    draft = LegacySqlConnectorLiveConnectionEvidenceSnapshot(
        schema_version=schema_version,
        tenant_id=runtime_activation_gate.tenant_id,
        module_id=runtime_activation_gate.module_id,
        source_system_ref=runtime_activation_gate.source_system_ref,
        connector_kind=runtime_activation_gate.connector_kind,
        snapshot_ref=snapshot_ref,
        runtime_activation_gate_evidence_hash=runtime_activation_gate.evidence_hash,
        upstream_evidence_hashes=upstream_evidence_hashes,
        required_controls=required_controls,
        passed_controls=passed_controls,
        failed_controls=failed_controls,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_connector_live_connection_snapshot_hash(draft)})


def _build_ready_runtime_activation_gate(
    *,
    env: Mapping[str, str],
    checked_by: str,
    checked_at: datetime,
) -> tuple[LegacySqlConnectorRealConnectionExecutorPolicyBundle, LegacySqlConnectorRuntimeActivationGateEvidence]:
    bundle, runtime_merge_gate = _build_ready_runtime_merge_gate(env=env, checked_by=checked_by, checked_at=checked_at)
    activation_snapshots = _build_ready_runtime_activation_snapshots(
        runtime_merge_gate=runtime_merge_gate,
        checked_by=checked_by,
        checked_at=checked_at,
    )
    activation_command = _build_runtime_activation_command_from_snapshots(
        runtime_merge_gate=runtime_merge_gate,
        snapshots=activation_snapshots,
        requested_by=checked_by,
    )
    runtime_activation_gate = _build_runtime_activation_gate_from_snapshots(
        command=activation_command,
        bundle=bundle,
        runtime_merge_gate=runtime_merge_gate,
        snapshots=activation_snapshots,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=90),
    )
    return bundle, runtime_activation_gate


def _build_ready_live_connection_snapshots(
    *,
    runtime_activation_gate: LegacySqlConnectorRuntimeActivationGateEvidence,
    checked_by: str,
    checked_at: datetime,
) -> dict[str, LegacySqlConnectorLiveConnectionEvidenceSnapshot]:
    return {
        "secret_broker_binding_snapshot": build_legacy_sql_connector_live_connection_secret_broker_binding_snapshot(
            runtime_activation_gate=runtime_activation_gate,
            checked_by=checked_by,
            checked_at_utc=checked_at + timedelta(seconds=101),
        ),
        "network_egress_policy_snapshot": build_legacy_sql_connector_live_connection_network_egress_policy_snapshot(
            runtime_activation_gate=runtime_activation_gate,
            checked_by=checked_by,
            checked_at_utc=checked_at + timedelta(seconds=102),
        ),
        "least_privilege_db_role_snapshot": build_legacy_sql_connector_live_connection_least_privilege_db_role_snapshot(
            runtime_activation_gate=runtime_activation_gate,
            checked_by=checked_by,
            checked_at_utc=checked_at + timedelta(seconds=103),
        ),
        "timeout_circuit_breaker_snapshot": (
            build_legacy_sql_connector_live_connection_timeout_circuit_breaker_snapshot(
                runtime_activation_gate=runtime_activation_gate,
                checked_by=checked_by,
                checked_at_utc=checked_at + timedelta(seconds=104),
            )
        ),
        "audit_sink_snapshot": build_legacy_sql_connector_live_connection_audit_sink_snapshot(
            runtime_activation_gate=runtime_activation_gate,
            checked_by=checked_by,
            checked_at_utc=checked_at + timedelta(seconds=105),
        ),
        "emergency_disable_snapshot": build_legacy_sql_connector_live_connection_emergency_disable_snapshot(
            runtime_activation_gate=runtime_activation_gate,
            checked_by=checked_by,
            checked_at_utc=checked_at + timedelta(seconds=106),
        ),
    }


def _snapshot_hash_valid(snapshot: LegacySqlConnectorLiveConnectionEvidenceSnapshot, expected_hash: str) -> bool:
    return build_legacy_sql_connector_live_connection_snapshot_hash(snapshot) == snapshot.evidence_hash == expected_hash


def _snapshot_passed(snapshot: LegacySqlConnectorLiveConnectionEvidenceSnapshot) -> bool:
    return not snapshot.failed_controls and set(snapshot.required_controls) == set(snapshot.passed_controls)


def _snapshot_bound(
    *,
    command: LegacySqlConnectorLiveConnectionGateCommand,
    runtime_activation_gate: LegacySqlConnectorRuntimeActivationGateEvidence,
    snapshot: LegacySqlConnectorLiveConnectionEvidenceSnapshot,
    expected_schema: str,
    required_upstream_hash: str | None = None,
) -> bool:
    upstream_bound = required_upstream_hash is None or required_upstream_hash in snapshot.upstream_evidence_hashes
    return (
        command.tenant_id == runtime_activation_gate.tenant_id == snapshot.tenant_id
        and command.module_id == runtime_activation_gate.module_id == snapshot.module_id
        and command.source_system_ref == runtime_activation_gate.source_system_ref == snapshot.source_system_ref
        and command.connector_kind == runtime_activation_gate.connector_kind == snapshot.connector_kind
        and snapshot.schema_version == expected_schema
        and snapshot.runtime_activation_gate_evidence_hash == runtime_activation_gate.evidence_hash
        and upstream_bound
    )


def _runtime_activation_gate_bound(
    *,
    command: LegacySqlConnectorLiveConnectionGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    runtime_activation_gate: LegacySqlConnectorRuntimeActivationGateEvidence,
) -> bool:
    return (
        command.tenant_id == bundle.tenant_id == runtime_activation_gate.tenant_id
        and command.module_id == bundle.module_id == runtime_activation_gate.module_id
        and command.source_system_ref == bundle.source_system_ref == runtime_activation_gate.source_system_ref
        and command.connector_kind == bundle.connector_kind == runtime_activation_gate.connector_kind
        and command.runtime_activation_gate_evidence_hash == runtime_activation_gate.evidence_hash
        and not runtime_activation_gate.runtime_activation_allowed
        and not runtime_activation_gate.activatable_runtime_allowed
        and not runtime_activation_gate.socket_runtime_execution_allowed
        and not runtime_activation_gate.secret_materialization_allowed
        and not runtime_activation_gate.network_socket_opened
        and not runtime_activation_gate.secret_material_resolved
    )


def _live_connection_blocking_reasons(
    *,
    command: LegacySqlConnectorLiveConnectionGateCommand,
    runtime_activation_gate_hash_valid: bool,
    runtime_activation_gate_ready: bool,
    runtime_activation_gate_bound: bool,
    snapshot_checks: tuple[tuple[str, bool, bool, bool, LegacySqlConnectorLiveConnectionEvidenceSnapshot], ...],
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not runtime_activation_gate_hash_valid:
        reasons.append("runtime_activation_gate_hash_invalid")
    if not runtime_activation_gate_ready:
        reasons.append("runtime_activation_gate_not_ready")
    if not runtime_activation_gate_bound:
        reasons.append("runtime_activation_gate_not_bound")
    for prefix, hash_valid, bound, passed, snapshot in snapshot_checks:
        if not hash_valid:
            reasons.append(f"{prefix}_snapshot_hash_invalid")
        if not bound:
            reasons.append(f"{prefix}_snapshot_not_bound")
        if not passed:
            reasons.append(f"{prefix}_snapshot_failed")
        for failed_control in snapshot.failed_controls:
            reasons.append(f"{prefix}_{failed_control}_failed")
    if not command.live_connection_gate_requested:
        reasons.append("live_connection_gate_not_requested")
    if command.metadata_connection_probe_requested:
        reasons.append("metadata_connection_probe_requires_future_probe_execution_gate")
    if command.live_connection_probe_requested:
        reasons.append("live_connection_probe_requires_future_probe_execution_gate")
    if command.secret_broker_resolution_requested:
        reasons.append("secret_broker_resolution_requires_future_secret_gate")
    if command.socket_runtime_execution_requested:
        reasons.append("socket_runtime_execution_requires_future_probe_execution_gate")
    if command.secret_materialization_requested:
        reasons.append("secret_materialization_requires_future_secret_gate")
    if command.raw_data_access_requested:
        reasons.append("raw_data_access_requires_future_data_gate")
    if command.import_dry_run_requested:
        reasons.append("import_dry_run_requires_future_import_gate")
    if command.import_write_requested:
        reasons.append("import_write_requires_future_import_gate")
    if command.destructive_actions_requested:
        reasons.append("destructive_actions_require_human_confirmation_gate")
    return tuple(dict.fromkeys(reasons))


def _build_live_connection_command_from_snapshots(
    *,
    runtime_activation_gate: LegacySqlConnectorRuntimeActivationGateEvidence,
    snapshots: dict[str, LegacySqlConnectorLiveConnectionEvidenceSnapshot],
    requested_by: str,
) -> LegacySqlConnectorLiveConnectionGateCommand:
    return build_legacy_sql_connector_live_connection_gate_command(
        runtime_activation_gate=runtime_activation_gate,
        secret_broker_binding_snapshot=snapshots["secret_broker_binding_snapshot"],
        network_egress_policy_snapshot=snapshots["network_egress_policy_snapshot"],
        least_privilege_db_role_snapshot=snapshots["least_privilege_db_role_snapshot"],
        timeout_circuit_breaker_snapshot=snapshots["timeout_circuit_breaker_snapshot"],
        audit_sink_snapshot=snapshots["audit_sink_snapshot"],
        emergency_disable_snapshot=snapshots["emergency_disable_snapshot"],
        requested_by=requested_by,
    )


def _build_live_connection_gate_from_snapshots(
    *,
    command: LegacySqlConnectorLiveConnectionGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    runtime_activation_gate: LegacySqlConnectorRuntimeActivationGateEvidence,
    snapshots: dict[str, LegacySqlConnectorLiveConnectionEvidenceSnapshot],
    checked_by: str,
    checked_at_utc: datetime,
) -> LegacySqlConnectorLiveConnectionGateEvidence:
    return build_legacy_sql_connector_live_connection_gate(
        command=command,
        bundle=bundle,
        runtime_activation_gate=runtime_activation_gate,
        secret_broker_binding_snapshot=snapshots["secret_broker_binding_snapshot"],
        network_egress_policy_snapshot=snapshots["network_egress_policy_snapshot"],
        least_privilege_db_role_snapshot=snapshots["least_privilege_db_role_snapshot"],
        timeout_circuit_breaker_snapshot=snapshots["timeout_circuit_breaker_snapshot"],
        audit_sink_snapshot=snapshots["audit_sink_snapshot"],
        emergency_disable_snapshot=snapshots["emergency_disable_snapshot"],
        checked_by=checked_by,
        checked_at_utc=checked_at_utc,
    )


def _runtime_activation_gate_missing_blocked(
    command: LegacySqlConnectorLiveConnectionGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    runtime_activation_gate: LegacySqlConnectorRuntimeActivationGateEvidence,
    snapshots: dict[str, LegacySqlConnectorLiveConnectionEvidenceSnapshot],
    checked_by: str,
    checked_at: datetime,
) -> bool:
    blocked_activation_gate = runtime_activation_gate.model_copy(
        update={
            "gate_status": LegacySqlConnectorRuntimeActivationGateStatus.BLOCKED,
            "runtime_activation_gate_ready": False,
            "blocking_reasons": ("live_connection_test_activation_gate_missing",),
            "checked_at_utc": checked_at,
            "evidence_hash": ZERO_HASH,
        }
    )
    blocked_activation_gate = blocked_activation_gate.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_runtime_activation_gate_hash(blocked_activation_gate)}
    )
    blocked = _build_live_connection_gate_from_snapshots(
        command=command.model_copy(
            update={"runtime_activation_gate_evidence_hash": blocked_activation_gate.evidence_hash}
        ),
        bundle=bundle,
        runtime_activation_gate=blocked_activation_gate,
        snapshots=snapshots,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        blocked.gate_status == LegacySqlConnectorLiveConnectionGateStatus.BLOCKED
        and "runtime_activation_gate_not_ready" in blocked.blocking_reasons
    )


def _snapshot_missing_blocked(
    command: LegacySqlConnectorLiveConnectionGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    runtime_activation_gate: LegacySqlConnectorRuntimeActivationGateEvidence,
    snapshots: dict[str, LegacySqlConnectorLiveConnectionEvidenceSnapshot],
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
        update={"evidence_hash": build_legacy_sql_connector_live_connection_snapshot_hash(blocked_snapshot)}
    )
    updated_snapshots[snapshot_key] = blocked_snapshot
    command_field = f"{snapshot_key}_hash"
    blocked = _build_live_connection_gate_from_snapshots(
        command=command.model_copy(update={command_field: blocked_snapshot.evidence_hash}),
        bundle=bundle,
        runtime_activation_gate=runtime_activation_gate,
        snapshots=updated_snapshots,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        blocked.gate_status == LegacySqlConnectorLiveConnectionGateStatus.BLOCKED
        and expected_reason in blocked.blocking_reasons
    )


def _metadata_probe_request_blocked(
    command: LegacySqlConnectorLiveConnectionGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    runtime_activation_gate: LegacySqlConnectorRuntimeActivationGateEvidence,
    snapshots: dict[str, LegacySqlConnectorLiveConnectionEvidenceSnapshot],
    checked_by: str,
    checked_at: datetime,
) -> bool:
    blocked = _build_live_connection_gate_from_snapshots(
        command=command.model_copy(
            update={
                "metadata_connection_probe_requested": True,
                "live_connection_probe_requested": True,
                "secret_broker_resolution_requested": True,
                "socket_runtime_execution_requested": True,
                "secret_materialization_requested": True,
                "raw_data_access_requested": True,
            }
        ),
        bundle=bundle,
        runtime_activation_gate=runtime_activation_gate,
        snapshots=snapshots,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        blocked.gate_status == LegacySqlConnectorLiveConnectionGateStatus.BLOCKED
        and "metadata_connection_probe_requires_future_probe_execution_gate" in blocked.blocking_reasons
        and "live_connection_probe_requires_future_probe_execution_gate" in blocked.blocking_reasons
        and "secret_broker_resolution_requires_future_secret_gate" in blocked.blocking_reasons
        and "socket_runtime_execution_requires_future_probe_execution_gate" in blocked.blocking_reasons
        and "secret_materialization_requires_future_secret_gate" in blocked.blocking_reasons
        and "raw_data_access_requires_future_data_gate" in blocked.blocking_reasons
        and not blocked.metadata_connection_probe_allowed
        and not blocked.real_connection_opened
    )


def _assert_live_connection_safe(value: BaseModel) -> None:
    payload = value.model_dump_json().lower()
    for fragment in FORBIDDEN_LIVE_CONNECTION_FRAGMENTS:
        if fragment in payload:
            raise ValueError(f"legacy SQL live connection evidence contains forbidden fragment: {fragment}")


if __name__ == "__main__":
    main()
