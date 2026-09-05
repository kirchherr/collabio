from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.platform.legacy_sql_connector_metadata_connection_probe_gate import (
    LegacySqlConnectorMetadataConnectionProbeGateEvidence,
    LegacySqlConnectorMetadataConnectionProbeGateStatus,
    _build_metadata_connection_probe_command_from_snapshots,
    _build_metadata_connection_probe_gate_from_snapshots,
    _build_ready_live_connection_gate,
    _build_ready_metadata_connection_probe_snapshots,
    build_legacy_sql_connector_metadata_connection_probe_gate_hash,
)
from suite.platform.legacy_sql_connector_real_connection_executor import (
    LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    LegacySqlConnectorRealConnectionPolicyStoreBackend,
)
from suite.platform.legacy_sql_discovery import MODULE_ID_PATTERN, NAMESPACED_REF_PATTERN, LegacySqlConnectorKind
from suite.platform.legacy_sql_metadata_worker_queue import LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN

COMMAND_SCHEMA_VERSION = "legacy_sql_connector_metadata_connection_probe_skeleton_command.v1"
PLAN_SCHEMA_VERSION = "legacy_sql_connector_metadata_connection_probe_execution_plan.v1"
EVIDENCE_SCHEMA_VERSION = "legacy_sql_connector_metadata_connection_probe_execution_evidence.v1"
SMOKE_SCHEMA_VERSION = "legacy_sql_connector_metadata_connection_probe_skeleton_smoke_report.v1"
COMMAND_REF = "docker-compose:legacy-sql-connector-metadata-connection-probe-skeleton-smoke"
DEFAULT_PROVIDER_DRIVER_ADAPTER_REF = "provider-driver-adapter:legacy-sql-metadata-only-offline-fixture"
DEFAULT_SEALED_SECRET_HANDLE_REF = "sealed-handle:legacy-sql-metadata-probe"
DEFAULT_METADATA_QUERY_ALLOWLIST_REF = "metadata-query-allowlist:legacy-sql-catalog-v1"
DEFAULT_ALLOWED_QUERY_NAMES = ("tables", "columns", "primary_keys")
REQUIRED_AUDIT_EVENT_TYPES = (
    "legacy_sql.metadata_connection_probe.requested",
    "legacy_sql.metadata_connection_probe.started",
    "legacy_sql.metadata_connection_probe.completed",
    "legacy_sql.metadata_connection_probe.blocked",
)
ZERO_HASH = "sha256:" + "0" * 64
SHA256_REF_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
QUERY_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
FORBIDDEN_FRAGMENTS = (
    '"connection_secret_ref":',
    '"connection_secret_value":',
    '"secret_material_value":',
    '"secret_broker_read_result":',
    "secret:legacy-sql",
    "sqlserver://",
    "password",
    '"dsn":',
    "plain_secret",
    "connection_string",
    '"raw_payload":',
    '"sample_values":',
    '"row_values":',
    '"record_values":',
    '"import_write_payload":',
    "dbo.",
    "kunden",
    "email",
)


class LegacySqlConnectorMetadataConnectionProbeSkeletonStatus(StrEnum):
    BLOCKED = "blocked"
    READY = "ready"
    EXECUTED = "executed"


class LegacySqlConnectorMetadataConnectionProbeSkeletonCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = COMMAND_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    metadata_connection_probe_gate_evidence_hash: str
    provider_driver_snapshot_hash: str
    secret_broker_read_path_snapshot_hash: str
    metadata_query_allowlist_snapshot_hash: str
    timeout_circuit_breaker_execution_snapshot_hash: str
    audit_sink_execution_snapshot_hash: str
    emergency_disable_execution_snapshot_hash: str
    provider_driver_adapter_ref: str = DEFAULT_PROVIDER_DRIVER_ADAPTER_REF
    sealed_secret_handle_ref: str = DEFAULT_SEALED_SECRET_HANDLE_REF
    metadata_query_allowlist_ref: str = DEFAULT_METADATA_QUERY_ALLOWLIST_REF
    allowed_query_names: tuple[str, ...] = DEFAULT_ALLOWED_QUERY_NAMES
    connect_timeout_seconds: int = Field(default=5, ge=1, le=30)
    metadata_query_timeout_seconds: int = Field(default=10, ge=1, le=60)
    total_budget_seconds: int = Field(default=20, ge=1, le=120)
    metadata_probe_runtime_enabled: bool = False
    tenant_kill_switch_armed: bool = True
    tenant_kill_switch_disabled: bool = False
    global_emergency_disable_active: bool = False
    metadata_connection_probe_requested: bool = True
    provider_driver_adapter_requested: bool = True
    secret_broker_read_requested: bool = True
    metadata_query_execution_requested: bool = True
    socket_runtime_execution_requested: bool = True
    raw_data_access_requested: bool = False
    import_dry_run_requested: bool = False
    import_write_requested: bool = False
    destructive_actions_requested: bool = False
    requested_by: str

    @model_validator(mode="after")
    def validate_command(self) -> Self:
        if self.schema_version != COMMAND_SCHEMA_VERSION:
            raise ValueError("metadata connection probe skeleton command schema mismatch")
        _validate_common_refs(
            tenant_id=self.tenant_id,
            module_id=self.module_id,
            namespaced_refs=(
                self.source_system_ref,
                self.provider_driver_adapter_ref,
                self.sealed_secret_handle_ref,
                self.metadata_query_allowlist_ref,
            ),
            hashes=(
                self.metadata_connection_probe_gate_evidence_hash,
                self.provider_driver_snapshot_hash,
                self.secret_broker_read_path_snapshot_hash,
                self.metadata_query_allowlist_snapshot_hash,
                self.timeout_circuit_breaker_execution_snapshot_hash,
                self.audit_sink_execution_snapshot_hash,
                self.emergency_disable_execution_snapshot_hash,
            ),
        )
        if not self.requested_by.strip():
            raise ValueError("metadata connection probe skeleton requested_by is required")
        if self.total_budget_seconds < self.connect_timeout_seconds + self.metadata_query_timeout_seconds:
            raise ValueError("metadata connection probe skeleton time budget is too small")
        _validate_query_names(self.allowed_query_names)
        _assert_safe_model(self)
        return self


class LegacySqlConnectorMetadataConnectionProbeExecutionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = PLAN_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    command_hash: str
    metadata_connection_probe_gate_evidence_hash: str
    provider_driver_snapshot_hash: str
    secret_broker_read_path_snapshot_hash: str
    metadata_query_allowlist_snapshot_hash: str
    timeout_circuit_breaker_execution_snapshot_hash: str
    audit_sink_execution_snapshot_hash: str
    emergency_disable_execution_snapshot_hash: str
    provider_driver_adapter_ref: str
    sealed_secret_handle_ref: str
    metadata_query_allowlist_ref: str
    allowed_query_names: tuple[str, ...]
    connect_timeout_seconds: int
    metadata_query_timeout_seconds: int
    total_budget_seconds: int
    metadata_probe_runtime_enabled: bool
    tenant_kill_switch_armed: bool
    tenant_kill_switch_disabled: bool
    global_emergency_disable_active: bool
    metadata_connection_probe_gate_hash_valid: bool
    metadata_connection_probe_gate_ready: bool
    metadata_connection_probe_gate_bound: bool
    provider_driver_adapter_invocation_allowed: bool
    secret_broker_handle_metadata_read_allowed: bool
    metadata_query_execution_allowed: bool
    socket_runtime_execution_allowed: bool
    raw_data_access_allowed: bool = False
    import_dry_run_allowed: bool = False
    import_write_allowed: bool = False
    destructive_actions_allowed: bool = False
    execution_plan_ready: bool
    plan_status: LegacySqlConnectorMetadataConnectionProbeSkeletonStatus
    blocking_reasons: tuple[str, ...]
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @model_validator(mode="after")
    def validate_plan(self) -> Self:
        if self.schema_version != PLAN_SCHEMA_VERSION:
            raise ValueError("metadata connection probe execution plan schema mismatch")
        _validate_common_refs(
            tenant_id=self.tenant_id,
            module_id=self.module_id,
            namespaced_refs=(
                self.source_system_ref,
                self.provider_driver_adapter_ref,
                self.sealed_secret_handle_ref,
                self.metadata_query_allowlist_ref,
            ),
            hashes=(
                self.command_hash,
                self.metadata_connection_probe_gate_evidence_hash,
                self.provider_driver_snapshot_hash,
                self.secret_broker_read_path_snapshot_hash,
                self.metadata_query_allowlist_snapshot_hash,
                self.timeout_circuit_breaker_execution_snapshot_hash,
                self.audit_sink_execution_snapshot_hash,
                self.emergency_disable_execution_snapshot_hash,
                self.evidence_hash,
            ),
        )
        _validate_query_names(self.allowed_query_names)
        if self.plan_status == LegacySqlConnectorMetadataConnectionProbeSkeletonStatus.READY:
            if not self.execution_plan_ready or self.blocking_reasons:
                raise ValueError("ready metadata connection probe execution plan cannot have blockers")
            if not (
                self.metadata_connection_probe_gate_hash_valid
                and self.metadata_connection_probe_gate_ready
                and self.metadata_connection_probe_gate_bound
                and self.provider_driver_adapter_invocation_allowed
                and self.secret_broker_handle_metadata_read_allowed
                and self.metadata_query_execution_allowed
                and self.socket_runtime_execution_allowed
            ):
                raise ValueError("ready metadata connection probe execution plan is missing guard evidence")
        if self.plan_status == LegacySqlConnectorMetadataConnectionProbeSkeletonStatus.BLOCKED and (
            self.execution_plan_ready or not self.blocking_reasons
        ):
            raise ValueError("blocked metadata connection probe execution plan requires blockers")
        _assert_no_raw_import_or_destructive(
            self.raw_data_access_allowed,
            self.import_dry_run_allowed,
            self.import_write_allowed,
            self.destructive_actions_allowed,
        )
        _assert_safe_model(self)
        return self


class LegacySqlConnectorMetadataConnectionProbeExecutionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = EVIDENCE_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    command_ref: str = COMMAND_REF
    command_hash: str
    execution_plan_hash: str
    metadata_connection_probe_gate_evidence_hash: str
    metadata_connection_probe_result_hash: str | None = None
    secret_handle_metadata_hash: str | None = None
    audit_event_refs: tuple[str, ...]
    executed_query_names: tuple[str, ...] = ()
    metadata_result_set_hashes: tuple[str, ...] = ()
    metadata_relation_count: int = Field(default=0, ge=0)
    metadata_column_count: int = Field(default=0, ge=0)
    metadata_connection_probe_executed: bool = False
    provider_driver_adapter_invoked: bool = False
    provider_driver_loaded_by_adapter: bool = False
    secret_broker_handle_metadata_read: bool = False
    secret_material_resolved: bool = False
    metadata_query_execution_allowed: bool = False
    socket_runtime_execution_allowed: bool = False
    network_socket_opened: bool = False
    network_connection_opened: bool = False
    real_connection_opened: bool = False
    raw_data_access_allowed: bool = False
    raw_rows_returned: bool = False
    sample_values_returned: bool = False
    stored_procedure_body_returned: bool = False
    import_dry_run_allowed: bool = False
    import_write_allowed: bool = False
    destructive_actions_allowed: bool = False
    future_raw_data_gate_required: bool = True
    future_import_dry_run_gate_required: bool = True
    evidence_status: LegacySqlConnectorMetadataConnectionProbeSkeletonStatus
    blocking_reasons: tuple[str, ...]
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        if self.schema_version != EVIDENCE_SCHEMA_VERSION:
            raise ValueError("metadata connection probe execution evidence schema mismatch")
        hashes = [
            self.command_hash,
            self.execution_plan_hash,
            self.metadata_connection_probe_gate_evidence_hash,
            self.evidence_hash,
        ]
        if self.metadata_connection_probe_result_hash is not None:
            hashes.append(self.metadata_connection_probe_result_hash)
        if self.secret_handle_metadata_hash is not None:
            hashes.append(self.secret_handle_metadata_hash)
        _validate_common_refs(
            tenant_id=self.tenant_id,
            module_id=self.module_id,
            namespaced_refs=(self.source_system_ref, self.command_ref, *self.audit_event_refs),
            hashes=tuple(hashes),
        )
        _validate_query_names(self.executed_query_names, allow_empty=True)
        for result_hash in self.metadata_result_set_hashes:
            _validate_hash(result_hash)
        unsafe = (
            self.secret_material_resolved
            or self.raw_data_access_allowed
            or self.raw_rows_returned
            or self.sample_values_returned
            or self.stored_procedure_body_returned
            or self.import_dry_run_allowed
            or self.import_write_allowed
            or self.destructive_actions_allowed
        )
        if unsafe:
            raise ValueError("metadata connection probe execution evidence must remain metadata-only")
        if self.evidence_status == LegacySqlConnectorMetadataConnectionProbeSkeletonStatus.EXECUTED:
            required = (
                self.metadata_connection_probe_executed,
                self.provider_driver_adapter_invoked,
                self.secret_broker_handle_metadata_read,
                self.metadata_query_execution_allowed,
                self.socket_runtime_execution_allowed,
                self.metadata_connection_probe_result_hash is not None,
                self.secret_handle_metadata_hash is not None,
                self.future_raw_data_gate_required,
                self.future_import_dry_run_gate_required,
            )
            if self.blocking_reasons or not all(required):
                raise ValueError("executed metadata connection probe evidence is incomplete")
        if self.evidence_status == LegacySqlConnectorMetadataConnectionProbeSkeletonStatus.BLOCKED and (
            self.metadata_connection_probe_executed or not self.blocking_reasons
        ):
            raise ValueError("blocked metadata connection probe evidence must not execute")
        _assert_safe_model(self)
        return self


class LegacySqlConnectorMetadataConnectionProbeSkeletonSmokeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SMOKE_SCHEMA_VERSION
    tenant_id: str
    store_backend: LegacySqlConnectorRealConnectionPolicyStoreBackend
    continuity_domain: str = LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN
    command_ref: str = COMMAND_REF
    metadata_connection_probe_gate_evidence_hash: str
    default_off_execution_evidence_hash: str
    kill_switch_execution_evidence_hash: str
    raw_data_request_execution_evidence_hash: str
    enabled_fixture_execution_evidence_hash: str
    metadata_connection_probe_gate_ready: bool
    default_off_blocked: bool
    kill_switch_disabled_blocked: bool
    raw_data_request_blocked: bool
    enabled_fixture_probe_completed: bool
    provider_driver_adapter_contract_bound: bool
    secret_broker_read_path_bound: bool
    metadata_query_allowlist_bound: bool
    timeout_circuit_breaker_bound: bool
    audit_sink_bound: bool
    emergency_disable_bound: bool
    offline_fixture_probe_executed: bool
    external_metadata_connection_probe_executed: bool = False
    provider_driver_adapter_invoked: bool
    provider_driver_loaded_by_adapter: bool = False
    secret_broker_handle_metadata_read: bool
    secret_material_resolved: bool = False
    metadata_query_execution_allowed: bool
    socket_runtime_execution_allowed: bool
    network_socket_opened: bool = False
    network_connection_opened: bool = False
    real_connection_opened: bool = False
    raw_data_access_allowed: bool = False
    raw_rows_returned: bool = False
    sample_values_returned: bool = False
    stored_procedure_body_returned: bool = False
    import_dry_run_allowed: bool = False
    import_write_allowed: bool = False
    destructive_actions_allowed: bool = False
    future_raw_data_gate_required: bool = True
    future_import_dry_run_gate_required: bool = True
    smoke_passed: bool
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @model_validator(mode="after")
    def validate_smoke(self) -> Self:
        if self.schema_version != SMOKE_SCHEMA_VERSION:
            raise ValueError("metadata connection probe skeleton smoke schema mismatch")
        _validate_common_refs(
            tenant_id=self.tenant_id,
            module_id="crm_erp",
            namespaced_refs=(self.command_ref,),
            hashes=(
                self.metadata_connection_probe_gate_evidence_hash,
                self.default_off_execution_evidence_hash,
                self.kill_switch_execution_evidence_hash,
                self.raw_data_request_execution_evidence_hash,
                self.enabled_fixture_execution_evidence_hash,
                self.evidence_hash,
            ),
        )
        unsafe = (
            self.external_metadata_connection_probe_executed
            or self.provider_driver_loaded_by_adapter
            or self.secret_material_resolved
            or self.network_socket_opened
            or self.network_connection_opened
            or self.real_connection_opened
            or self.raw_data_access_allowed
            or self.raw_rows_returned
            or self.sample_values_returned
            or self.stored_procedure_body_returned
            or self.import_dry_run_allowed
            or self.import_write_allowed
            or self.destructive_actions_allowed
        )
        if unsafe:
            raise ValueError("metadata connection probe skeleton smoke leaked external/raw execution")
        if self.smoke_passed:
            required = (
                self.metadata_connection_probe_gate_ready,
                self.default_off_blocked,
                self.kill_switch_disabled_blocked,
                self.raw_data_request_blocked,
                self.enabled_fixture_probe_completed,
                self.provider_driver_adapter_contract_bound,
                self.secret_broker_read_path_bound,
                self.metadata_query_allowlist_bound,
                self.timeout_circuit_breaker_bound,
                self.audit_sink_bound,
                self.emergency_disable_bound,
                self.offline_fixture_probe_executed,
                self.provider_driver_adapter_invoked,
                self.secret_broker_handle_metadata_read,
                self.metadata_query_execution_allowed,
                self.socket_runtime_execution_allowed,
                self.future_raw_data_gate_required,
                self.future_import_dry_run_gate_required,
            )
            if not all(required):
                raise ValueError("passing metadata connection probe skeleton smoke requires all evidence")
        _assert_safe_model(self)
        return self


@dataclass(frozen=True)
class MetadataProbeAdapterResult:
    evidence_hash: str
    executed_query_names: tuple[str, ...]
    result_set_hashes: tuple[str, ...]
    metadata_relation_count: int
    metadata_column_count: int
    provider_driver_adapter_invoked: bool = True
    provider_driver_loaded_by_adapter: bool = False
    network_socket_opened: bool = False
    network_connection_opened: bool = False
    real_connection_opened: bool = False
    raw_rows_returned: bool = False
    sample_values_returned: bool = False
    stored_procedure_body_returned: bool = False


class LegacySqlMetadataProbeSecretBroker(Protocol):
    def read_handle_metadata(
        self,
        *,
        command: LegacySqlConnectorMetadataConnectionProbeSkeletonCommand,
    ) -> str: ...


class LegacySqlMetadataProbeProviderAdapter(Protocol):
    def run_metadata_probe(
        self,
        *,
        command: LegacySqlConnectorMetadataConnectionProbeSkeletonCommand,
        secret_handle_metadata_hash: str,
    ) -> MetadataProbeAdapterResult: ...


class LegacySqlMetadataProbeAuditSink(Protocol):
    def record_probe_event(
        self,
        *,
        tenant_id: str,
        event_type: str,
        source_system_ref: str,
        metadata: dict[str, str],
    ) -> str: ...


@dataclass
class InMemoryMetadataProbeSecretBroker:
    calls: list[str] = field(default_factory=list)

    def read_handle_metadata(self, *, command: LegacySqlConnectorMetadataConnectionProbeSkeletonCommand) -> str:
        self.calls.append(command.sealed_secret_handle_ref)
        payload = {
            "schema_version": "legacy_sql_connector_metadata_connection_probe_secret_handle_metadata.v1",
            "tenant_id": command.tenant_id,
            "module_id": command.module_id,
            "source_system_ref": command.source_system_ref,
            "sealed_secret_handle_ref": command.sealed_secret_handle_ref,
            "secret_broker_read_path_snapshot_hash": command.secret_broker_read_path_snapshot_hash,
            "secret_material_resolved": False,
        }
        _assert_safe_payload(canonical_json(payload))
        return stable_hash(canonical_json(payload))


@dataclass
class FixtureMetadataOnlyProbeProviderAdapter:
    calls: list[tuple[str, ...]] = field(default_factory=list)

    def run_metadata_probe(
        self,
        *,
        command: LegacySqlConnectorMetadataConnectionProbeSkeletonCommand,
        secret_handle_metadata_hash: str,
    ) -> MetadataProbeAdapterResult:
        _validate_hash(secret_handle_metadata_hash)
        executed_query_names = tuple(command.allowed_query_names)
        self.calls.append(executed_query_names)
        result_hashes = tuple(
            stable_hash(canonical_json({"query_name": query_name, "metadata_only_fixture": True}))
            for query_name in executed_query_names
        )
        result_hash = stable_hash(
            canonical_json(
                {
                    "schema_version": "legacy_sql_connector_metadata_connection_probe_adapter_result.v1",
                    "tenant_id": command.tenant_id,
                    "source_system_ref": command.source_system_ref,
                    "executed_query_names": executed_query_names,
                    "result_set_hashes": result_hashes,
                    "metadata_relation_count": 2,
                    "metadata_column_count": 7,
                    "network_socket_opened": False,
                    "raw_rows_returned": False,
                }
            )
        )
        return MetadataProbeAdapterResult(
            evidence_hash=result_hash,
            executed_query_names=executed_query_names,
            result_set_hashes=result_hashes,
            metadata_relation_count=2,
            metadata_column_count=7,
        )


@dataclass
class CapturingMetadataProbeAuditSink:
    event_refs: list[str] = field(default_factory=list)
    event_types: list[str] = field(default_factory=list)

    def record_probe_event(
        self,
        *,
        tenant_id: str,
        event_type: str,
        source_system_ref: str,
        metadata: dict[str, str],
    ) -> str:
        del tenant_id, source_system_ref, metadata
        if event_type not in REQUIRED_AUDIT_EVENT_TYPES:
            raise ValueError("metadata connection probe audit event is not allowed")
        self.event_types.append(event_type)
        event_ref = f"audit:metadata-probe-{len(self.event_refs) + 1}"
        self.event_refs.append(event_ref)
        return event_ref


def build_legacy_sql_connector_metadata_connection_probe_skeleton_command(
    *,
    metadata_connection_probe_gate: LegacySqlConnectorMetadataConnectionProbeGateEvidence,
    requested_by: str,
    metadata_probe_runtime_enabled: bool = False,
    tenant_kill_switch_armed: bool = True,
    tenant_kill_switch_disabled: bool = False,
    global_emergency_disable_active: bool = False,
    raw_data_access_requested: bool = False,
    import_dry_run_requested: bool = False,
    import_write_requested: bool = False,
    destructive_actions_requested: bool = False,
    allowed_query_names: tuple[str, ...] = DEFAULT_ALLOWED_QUERY_NAMES,
    provider_driver_adapter_ref: str = DEFAULT_PROVIDER_DRIVER_ADAPTER_REF,
    sealed_secret_handle_ref: str = DEFAULT_SEALED_SECRET_HANDLE_REF,
    metadata_query_allowlist_ref: str = DEFAULT_METADATA_QUERY_ALLOWLIST_REF,
    connect_timeout_seconds: int = 5,
    metadata_query_timeout_seconds: int = 10,
    total_budget_seconds: int = 20,
) -> LegacySqlConnectorMetadataConnectionProbeSkeletonCommand:
    return LegacySqlConnectorMetadataConnectionProbeSkeletonCommand(
        tenant_id=metadata_connection_probe_gate.tenant_id,
        module_id=metadata_connection_probe_gate.module_id,
        source_system_ref=metadata_connection_probe_gate.source_system_ref,
        connector_kind=metadata_connection_probe_gate.connector_kind,
        metadata_connection_probe_gate_evidence_hash=metadata_connection_probe_gate.evidence_hash,
        provider_driver_snapshot_hash=metadata_connection_probe_gate.provider_driver_snapshot_hash,
        secret_broker_read_path_snapshot_hash=metadata_connection_probe_gate.secret_broker_read_path_snapshot_hash,
        metadata_query_allowlist_snapshot_hash=metadata_connection_probe_gate.metadata_query_allowlist_snapshot_hash,
        timeout_circuit_breaker_execution_snapshot_hash=metadata_connection_probe_gate.timeout_circuit_breaker_execution_snapshot_hash,
        audit_sink_execution_snapshot_hash=metadata_connection_probe_gate.audit_sink_execution_snapshot_hash,
        emergency_disable_execution_snapshot_hash=metadata_connection_probe_gate.emergency_disable_execution_snapshot_hash,
        provider_driver_adapter_ref=provider_driver_adapter_ref,
        sealed_secret_handle_ref=sealed_secret_handle_ref,
        metadata_query_allowlist_ref=metadata_query_allowlist_ref,
        allowed_query_names=allowed_query_names,
        connect_timeout_seconds=connect_timeout_seconds,
        metadata_query_timeout_seconds=metadata_query_timeout_seconds,
        total_budget_seconds=total_budget_seconds,
        metadata_probe_runtime_enabled=metadata_probe_runtime_enabled,
        tenant_kill_switch_armed=tenant_kill_switch_armed,
        tenant_kill_switch_disabled=tenant_kill_switch_disabled,
        global_emergency_disable_active=global_emergency_disable_active,
        raw_data_access_requested=raw_data_access_requested,
        import_dry_run_requested=import_dry_run_requested,
        import_write_requested=import_write_requested,
        destructive_actions_requested=destructive_actions_requested,
        requested_by=requested_by,
    )


def build_legacy_sql_connector_metadata_connection_probe_execution_plan(
    *,
    command: LegacySqlConnectorMetadataConnectionProbeSkeletonCommand,
    metadata_connection_probe_gate: LegacySqlConnectorMetadataConnectionProbeGateEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
) -> LegacySqlConnectorMetadataConnectionProbeExecutionPlan:
    checked_at = checked_at_utc or datetime.now(UTC)
    command_hash = build_legacy_sql_connector_metadata_connection_probe_skeleton_command_hash(command)
    gate_hash_valid = (
        build_legacy_sql_connector_metadata_connection_probe_gate_hash(metadata_connection_probe_gate)
        == metadata_connection_probe_gate.evidence_hash
        == command.metadata_connection_probe_gate_evidence_hash
    )
    gate_ready = (
        metadata_connection_probe_gate.gate_status == LegacySqlConnectorMetadataConnectionProbeGateStatus.READY
        and metadata_connection_probe_gate.metadata_connection_probe_gate_ready
    )
    gate_bound = _metadata_connection_probe_gate_bound(command=command, gate=metadata_connection_probe_gate)
    blocking_reasons = _execution_plan_blocking_reasons(
        command=command,
        gate_hash_valid=gate_hash_valid,
        gate_ready=gate_ready,
        gate_bound=gate_bound,
    )
    ready = not blocking_reasons
    draft = LegacySqlConnectorMetadataConnectionProbeExecutionPlan(
        tenant_id=command.tenant_id,
        module_id=command.module_id,
        source_system_ref=command.source_system_ref,
        connector_kind=command.connector_kind,
        command_hash=command_hash,
        metadata_connection_probe_gate_evidence_hash=metadata_connection_probe_gate.evidence_hash,
        provider_driver_snapshot_hash=metadata_connection_probe_gate.provider_driver_snapshot_hash,
        secret_broker_read_path_snapshot_hash=metadata_connection_probe_gate.secret_broker_read_path_snapshot_hash,
        metadata_query_allowlist_snapshot_hash=metadata_connection_probe_gate.metadata_query_allowlist_snapshot_hash,
        timeout_circuit_breaker_execution_snapshot_hash=metadata_connection_probe_gate.timeout_circuit_breaker_execution_snapshot_hash,
        audit_sink_execution_snapshot_hash=metadata_connection_probe_gate.audit_sink_execution_snapshot_hash,
        emergency_disable_execution_snapshot_hash=metadata_connection_probe_gate.emergency_disable_execution_snapshot_hash,
        provider_driver_adapter_ref=command.provider_driver_adapter_ref,
        sealed_secret_handle_ref=command.sealed_secret_handle_ref,
        metadata_query_allowlist_ref=command.metadata_query_allowlist_ref,
        allowed_query_names=command.allowed_query_names,
        connect_timeout_seconds=command.connect_timeout_seconds,
        metadata_query_timeout_seconds=command.metadata_query_timeout_seconds,
        total_budget_seconds=command.total_budget_seconds,
        metadata_probe_runtime_enabled=command.metadata_probe_runtime_enabled,
        tenant_kill_switch_armed=command.tenant_kill_switch_armed,
        tenant_kill_switch_disabled=command.tenant_kill_switch_disabled,
        global_emergency_disable_active=command.global_emergency_disable_active,
        metadata_connection_probe_gate_hash_valid=gate_hash_valid,
        metadata_connection_probe_gate_ready=gate_ready,
        metadata_connection_probe_gate_bound=gate_bound,
        provider_driver_adapter_invocation_allowed=ready,
        secret_broker_handle_metadata_read_allowed=ready,
        metadata_query_execution_allowed=ready,
        socket_runtime_execution_allowed=ready,
        execution_plan_ready=ready,
        plan_status=LegacySqlConnectorMetadataConnectionProbeSkeletonStatus.READY
        if ready
        else LegacySqlConnectorMetadataConnectionProbeSkeletonStatus.BLOCKED,
        blocking_reasons=blocking_reasons,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_metadata_connection_probe_execution_plan_hash(draft)}
    )


def execute_legacy_sql_connector_metadata_connection_probe_skeleton(
    *,
    command: LegacySqlConnectorMetadataConnectionProbeSkeletonCommand,
    metadata_connection_probe_gate: LegacySqlConnectorMetadataConnectionProbeGateEvidence,
    provider_adapter: LegacySqlMetadataProbeProviderAdapter,
    secret_broker: LegacySqlMetadataProbeSecretBroker,
    audit_sink: LegacySqlMetadataProbeAuditSink | None = None,
    checked_by: str,
    checked_at_utc: datetime | None = None,
) -> LegacySqlConnectorMetadataConnectionProbeExecutionEvidence:
    checked_at = checked_at_utc or datetime.now(UTC)
    plan = build_legacy_sql_connector_metadata_connection_probe_execution_plan(
        command=command,
        metadata_connection_probe_gate=metadata_connection_probe_gate,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    audit_event_refs: list[str] = []
    if audit_sink is not None:
        audit_event_refs.append(
            _record_audit(audit_sink, command, "legacy_sql.metadata_connection_probe.requested", plan)
        )
    if plan.plan_status == LegacySqlConnectorMetadataConnectionProbeSkeletonStatus.BLOCKED:
        if audit_sink is not None:
            audit_event_refs.append(
                _record_audit(audit_sink, command, "legacy_sql.metadata_connection_probe.blocked", plan)
            )
        return _build_execution_evidence(
            command=command,
            plan=plan,
            audit_event_refs=tuple(audit_event_refs),
            checked_by=checked_by,
            checked_at_utc=checked_at + timedelta(seconds=1),
        )
    if audit_sink is not None:
        audit_event_refs.append(
            _record_audit(audit_sink, command, "legacy_sql.metadata_connection_probe.started", plan)
        )
    secret_handle_hash = secret_broker.read_handle_metadata(command=command)
    adapter_result = provider_adapter.run_metadata_probe(
        command=command, secret_handle_metadata_hash=secret_handle_hash
    )
    if audit_sink is not None:
        audit_event_refs.append(
            _record_audit(audit_sink, command, "legacy_sql.metadata_connection_probe.completed", plan)
        )
    return _build_execution_evidence(
        command=command,
        plan=plan,
        adapter_result=adapter_result,
        secret_handle_metadata_hash=secret_handle_hash,
        audit_event_refs=tuple(audit_event_refs),
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=2),
    )


def build_legacy_sql_connector_metadata_connection_probe_skeleton_command_hash(
    command: LegacySqlConnectorMetadataConnectionProbeSkeletonCommand,
) -> str:
    return stable_hash(canonical_json(command.model_dump(mode="json")))


def build_legacy_sql_connector_metadata_connection_probe_execution_plan_hash(
    plan: LegacySqlConnectorMetadataConnectionProbeExecutionPlan,
) -> str:
    return stable_hash(canonical_json(plan.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_metadata_connection_probe_execution_evidence_hash(
    evidence: LegacySqlConnectorMetadataConnectionProbeExecutionEvidence,
) -> str:
    return stable_hash(canonical_json(evidence.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_metadata_connection_probe_skeleton_smoke_report_hash(
    report: LegacySqlConnectorMetadataConnectionProbeSkeletonSmokeReport,
) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def run_legacy_sql_connector_metadata_connection_probe_skeleton_smoke_from_env(
    environ: Mapping[str, str] | None = None,
) -> LegacySqlConnectorMetadataConnectionProbeSkeletonSmokeReport:
    env = os.environ if environ is None else environ
    checked_by = env.get(
        "SUITE_LEGACY_SQL_CONNECTOR_METADATA_CONNECTION_PROBE_SKELETON_CHECKED_BY",
        "legacy-sql-connector-metadata-connection-probe-skeleton-smoke",
    )
    checked_at = datetime.now(UTC)
    store_backend = LegacySqlConnectorRealConnectionPolicyStoreBackend(
        env.get(
            "SUITE_LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_POLICY_STORE_BACKEND",
            LegacySqlConnectorRealConnectionPolicyStoreBackend.JSONL.value,
        )
    )
    bundle, gate = _build_ready_metadata_connection_probe_gate(env=env, checked_by=checked_by, checked_at=checked_at)
    default_off = _execute_with_fixture(gate=gate, checked_by=checked_by, checked_at=checked_at, enabled=False)
    kill_switch = _execute_with_fixture(
        gate=gate,
        checked_by=checked_by,
        checked_at=checked_at + timedelta(seconds=10),
        enabled=True,
        tenant_kill_switch_disabled=True,
    )
    raw_request = _execute_with_fixture(
        gate=gate,
        checked_by=checked_by,
        checked_at=checked_at + timedelta(seconds=20),
        enabled=True,
        raw_data_access_requested=True,
    )
    enabled_fixture = _execute_with_fixture(
        gate=gate,
        checked_by=checked_by,
        checked_at=checked_at + timedelta(seconds=30),
        enabled=True,
    )
    default_off_blocked = _blocked(default_off, "metadata_probe_runtime_default_off")
    kill_switch_disabled_blocked = _blocked(kill_switch, "tenant_connection_kill_switch_disabled")
    raw_data_request_blocked = _blocked(raw_request, "raw_data_access_requires_future_data_gate")
    enabled_fixture_probe_completed = (
        enabled_fixture.evidence_status == LegacySqlConnectorMetadataConnectionProbeSkeletonStatus.EXECUTED
        and enabled_fixture.metadata_connection_probe_executed
        and enabled_fixture.provider_driver_adapter_invoked
        and enabled_fixture.secret_broker_handle_metadata_read
        and enabled_fixture.metadata_query_execution_allowed
        and enabled_fixture.socket_runtime_execution_allowed
        and not enabled_fixture.network_socket_opened
        and not enabled_fixture.real_connection_opened
        and not enabled_fixture.raw_data_access_allowed
    )
    smoke_passed = (
        gate.gate_status == LegacySqlConnectorMetadataConnectionProbeGateStatus.READY
        and gate.metadata_connection_probe_gate_ready
        and default_off_blocked
        and kill_switch_disabled_blocked
        and raw_data_request_blocked
        and enabled_fixture_probe_completed
    )
    draft = LegacySqlConnectorMetadataConnectionProbeSkeletonSmokeReport(
        tenant_id=bundle.tenant_id,
        store_backend=store_backend,
        metadata_connection_probe_gate_evidence_hash=gate.evidence_hash,
        default_off_execution_evidence_hash=default_off.evidence_hash,
        kill_switch_execution_evidence_hash=kill_switch.evidence_hash,
        raw_data_request_execution_evidence_hash=raw_request.evidence_hash,
        enabled_fixture_execution_evidence_hash=enabled_fixture.evidence_hash,
        metadata_connection_probe_gate_ready=gate.metadata_connection_probe_gate_ready,
        default_off_blocked=default_off_blocked,
        kill_switch_disabled_blocked=kill_switch_disabled_blocked,
        raw_data_request_blocked=raw_data_request_blocked,
        enabled_fixture_probe_completed=enabled_fixture_probe_completed,
        provider_driver_adapter_contract_bound=gate.provider_driver_snapshot_bound and gate.provider_driver_passed,
        secret_broker_read_path_bound=gate.secret_broker_read_path_snapshot_bound
        and gate.secret_broker_read_path_passed,
        metadata_query_allowlist_bound=gate.metadata_query_allowlist_snapshot_bound
        and gate.metadata_query_allowlist_passed,
        timeout_circuit_breaker_bound=(
            gate.timeout_circuit_breaker_execution_snapshot_bound and gate.timeout_circuit_breaker_execution_passed
        ),
        audit_sink_bound=gate.audit_sink_execution_snapshot_bound and gate.audit_sink_execution_passed,
        emergency_disable_bound=gate.emergency_disable_execution_snapshot_bound
        and gate.emergency_disable_execution_passed,
        offline_fixture_probe_executed=enabled_fixture.metadata_connection_probe_executed,
        provider_driver_adapter_invoked=enabled_fixture.provider_driver_adapter_invoked,
        secret_broker_handle_metadata_read=enabled_fixture.secret_broker_handle_metadata_read,
        metadata_query_execution_allowed=enabled_fixture.metadata_query_execution_allowed,
        socket_runtime_execution_allowed=enabled_fixture.socket_runtime_execution_allowed,
        smoke_passed=smoke_passed,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    _assert_safe_model(draft)
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_metadata_connection_probe_skeleton_smoke_report_hash(draft)}
    )


def exit_code_for_report(report: LegacySqlConnectorMetadataConnectionProbeSkeletonSmokeReport) -> int:
    return 0 if report.smoke_passed else 1


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Legacy SQL metadata connection probe skeleton smoke.")
    parser.add_argument(
        "--once", action="store_true", help="Run one metadata connection probe skeleton smoke and exit."
    )
    parser.add_argument(
        "--pretty", action="store_true", help="Pretty-print the metadata connection probe skeleton report."
    )
    args = parser.parse_args(argv)
    del args.once

    report = run_legacy_sql_connector_metadata_connection_probe_skeleton_smoke_from_env()
    print(json.dumps(report.model_dump(mode="json"), indent=2 if args.pretty else None, sort_keys=True))
    raise SystemExit(exit_code_for_report(report))


def _record_audit(
    audit_sink: LegacySqlMetadataProbeAuditSink,
    command: LegacySqlConnectorMetadataConnectionProbeSkeletonCommand,
    event_type: str,
    plan: LegacySqlConnectorMetadataConnectionProbeExecutionPlan,
) -> str:
    return audit_sink.record_probe_event(
        tenant_id=command.tenant_id,
        event_type=event_type,
        source_system_ref=command.source_system_ref,
        metadata={"command_hash": plan.command_hash, "plan_hash": plan.evidence_hash},
    )


def _build_execution_evidence(
    *,
    command: LegacySqlConnectorMetadataConnectionProbeSkeletonCommand,
    plan: LegacySqlConnectorMetadataConnectionProbeExecutionPlan,
    audit_event_refs: tuple[str, ...],
    checked_by: str,
    checked_at_utc: datetime,
    adapter_result: MetadataProbeAdapterResult | None = None,
    secret_handle_metadata_hash: str | None = None,
) -> LegacySqlConnectorMetadataConnectionProbeExecutionEvidence:
    executed = adapter_result is not None
    draft = LegacySqlConnectorMetadataConnectionProbeExecutionEvidence(
        tenant_id=command.tenant_id,
        module_id=command.module_id,
        source_system_ref=command.source_system_ref,
        connector_kind=command.connector_kind,
        command_hash=plan.command_hash,
        execution_plan_hash=plan.evidence_hash,
        metadata_connection_probe_gate_evidence_hash=plan.metadata_connection_probe_gate_evidence_hash,
        metadata_connection_probe_result_hash=adapter_result.evidence_hash if adapter_result else None,
        secret_handle_metadata_hash=secret_handle_metadata_hash,
        audit_event_refs=audit_event_refs,
        executed_query_names=adapter_result.executed_query_names if adapter_result else (),
        metadata_result_set_hashes=adapter_result.result_set_hashes if adapter_result else (),
        metadata_relation_count=adapter_result.metadata_relation_count if adapter_result else 0,
        metadata_column_count=adapter_result.metadata_column_count if adapter_result else 0,
        metadata_connection_probe_executed=executed,
        provider_driver_adapter_invoked=bool(adapter_result and adapter_result.provider_driver_adapter_invoked),
        provider_driver_loaded_by_adapter=bool(adapter_result and adapter_result.provider_driver_loaded_by_adapter),
        secret_broker_handle_metadata_read=secret_handle_metadata_hash is not None,
        metadata_query_execution_allowed=plan.metadata_query_execution_allowed,
        socket_runtime_execution_allowed=plan.socket_runtime_execution_allowed,
        network_socket_opened=bool(adapter_result and adapter_result.network_socket_opened),
        network_connection_opened=bool(adapter_result and adapter_result.network_connection_opened),
        real_connection_opened=bool(adapter_result and adapter_result.real_connection_opened),
        raw_rows_returned=bool(adapter_result and adapter_result.raw_rows_returned),
        sample_values_returned=bool(adapter_result and adapter_result.sample_values_returned),
        stored_procedure_body_returned=bool(adapter_result and adapter_result.stored_procedure_body_returned),
        evidence_status=LegacySqlConnectorMetadataConnectionProbeSkeletonStatus.EXECUTED
        if executed
        else LegacySqlConnectorMetadataConnectionProbeSkeletonStatus.BLOCKED,
        blocking_reasons=() if executed else plan.blocking_reasons,
        checked_by=checked_by,
        checked_at_utc=checked_at_utc,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_metadata_connection_probe_execution_evidence_hash(draft)}
    )


def _build_ready_metadata_connection_probe_gate(
    *,
    env: Mapping[str, str],
    checked_by: str,
    checked_at: datetime,
) -> tuple[LegacySqlConnectorRealConnectionExecutorPolicyBundle, LegacySqlConnectorMetadataConnectionProbeGateEvidence]:
    bundle, live_connection_gate = _build_ready_live_connection_gate(
        env=env, checked_by=checked_by, checked_at=checked_at
    )
    snapshots = _build_ready_metadata_connection_probe_snapshots(
        live_connection_gate=live_connection_gate, checked_by=checked_by, checked_at=checked_at
    )
    command = _build_metadata_connection_probe_command_from_snapshots(
        live_connection_gate=live_connection_gate, snapshots=snapshots, requested_by=checked_by
    )
    gate = _build_metadata_connection_probe_gate_from_snapshots(
        command=command,
        bundle=bundle,
        live_connection_gate=live_connection_gate,
        snapshots=snapshots,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=127),
    )
    return bundle, gate


def _execute_with_fixture(
    *,
    gate: LegacySqlConnectorMetadataConnectionProbeGateEvidence,
    checked_by: str,
    checked_at: datetime,
    enabled: bool,
    tenant_kill_switch_disabled: bool = False,
    raw_data_access_requested: bool = False,
) -> LegacySqlConnectorMetadataConnectionProbeExecutionEvidence:
    command = build_legacy_sql_connector_metadata_connection_probe_skeleton_command(
        metadata_connection_probe_gate=gate,
        requested_by=checked_by,
        metadata_probe_runtime_enabled=enabled,
        tenant_kill_switch_disabled=tenant_kill_switch_disabled,
        raw_data_access_requested=raw_data_access_requested,
    )
    return execute_legacy_sql_connector_metadata_connection_probe_skeleton(
        command=command,
        metadata_connection_probe_gate=gate,
        provider_adapter=FixtureMetadataOnlyProbeProviderAdapter(),
        secret_broker=InMemoryMetadataProbeSecretBroker(),
        audit_sink=CapturingMetadataProbeAuditSink(),
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )


def _metadata_connection_probe_gate_bound(
    *,
    command: LegacySqlConnectorMetadataConnectionProbeSkeletonCommand,
    gate: LegacySqlConnectorMetadataConnectionProbeGateEvidence,
) -> bool:
    return (
        command.tenant_id == gate.tenant_id
        and command.module_id == gate.module_id
        and command.source_system_ref == gate.source_system_ref
        and command.connector_kind == gate.connector_kind
        and command.metadata_connection_probe_gate_evidence_hash == gate.evidence_hash
        and command.provider_driver_snapshot_hash == gate.provider_driver_snapshot_hash
        and command.secret_broker_read_path_snapshot_hash == gate.secret_broker_read_path_snapshot_hash
        and command.metadata_query_allowlist_snapshot_hash == gate.metadata_query_allowlist_snapshot_hash
        and command.timeout_circuit_breaker_execution_snapshot_hash
        == gate.timeout_circuit_breaker_execution_snapshot_hash
        and command.audit_sink_execution_snapshot_hash == gate.audit_sink_execution_snapshot_hash
        and command.emergency_disable_execution_snapshot_hash == gate.emergency_disable_execution_snapshot_hash
        and not gate.provider_driver_load_allowed
        and not gate.secret_broker_read_allowed
        and not gate.metadata_connection_probe_executed
        and not gate.real_connection_opened
        and not gate.secret_material_resolved
    )


def _execution_plan_blocking_reasons(
    *,
    command: LegacySqlConnectorMetadataConnectionProbeSkeletonCommand,
    gate_hash_valid: bool,
    gate_ready: bool,
    gate_bound: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not gate_hash_valid:
        reasons.append("metadata_connection_probe_gate_hash_invalid")
    if not gate_ready:
        reasons.append("metadata_connection_probe_gate_not_ready")
    if not gate_bound:
        reasons.append("metadata_connection_probe_gate_not_bound")
    if not command.metadata_probe_runtime_enabled:
        reasons.append("metadata_probe_runtime_default_off")
    if not command.tenant_kill_switch_armed:
        reasons.append("tenant_connection_kill_switch_not_armed")
    if command.tenant_kill_switch_disabled:
        reasons.append("tenant_connection_kill_switch_disabled")
    if command.global_emergency_disable_active:
        reasons.append("global_emergency_disable_active")
    if not command.metadata_connection_probe_requested:
        reasons.append("metadata_connection_probe_not_requested")
    if not command.provider_driver_adapter_requested:
        reasons.append("provider_driver_adapter_not_requested")
    if not command.secret_broker_read_requested:
        reasons.append("secret_broker_handle_metadata_read_not_requested")
    if not command.metadata_query_execution_requested:
        reasons.append("metadata_query_execution_not_requested")
    if not command.socket_runtime_execution_requested:
        reasons.append("socket_runtime_execution_not_requested")
    if command.raw_data_access_requested:
        reasons.append("raw_data_access_requires_future_data_gate")
    if command.import_dry_run_requested:
        reasons.append("import_dry_run_requires_future_import_gate")
    if command.import_write_requested:
        reasons.append("import_write_requires_future_import_gate")
    if command.destructive_actions_requested:
        reasons.append("destructive_actions_require_human_confirmation_gate")
    return tuple(dict.fromkeys(reasons))


def _blocked(evidence: LegacySqlConnectorMetadataConnectionProbeExecutionEvidence, reason: str) -> bool:
    return (
        evidence.evidence_status == LegacySqlConnectorMetadataConnectionProbeSkeletonStatus.BLOCKED
        and reason in evidence.blocking_reasons
        and not evidence.metadata_connection_probe_executed
        and not evidence.provider_driver_adapter_invoked
        and not evidence.secret_broker_handle_metadata_read
    )


def _validate_common_refs(
    *,
    tenant_id: str,
    module_id: str,
    namespaced_refs: tuple[str, ...],
    hashes: tuple[str, ...],
) -> None:
    if not tenant_id.strip():
        raise ValueError("tenant_id is required")
    if not MODULE_ID_PATTERN.fullmatch(module_id):
        raise ValueError("module_id must be lowercase snake_case")
    for value in namespaced_refs:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("reference must be namespaced")
    for value in hashes:
        _validate_hash(value)


def _validate_hash(value: str) -> None:
    if not SHA256_REF_PATTERN.fullmatch(value):
        raise ValueError("hash must be a sha256 reference")


def _validate_query_names(value: tuple[str, ...], *, allow_empty: bool = False) -> None:
    if not value and not allow_empty:
        raise ValueError("query names are required")
    if len(value) != len(set(value)):
        raise ValueError("query names must be unique")
    for query_name in value:
        if not QUERY_NAME_PATTERN.fullmatch(query_name):
            raise ValueError("query names must be snake_case")


def _assert_no_raw_import_or_destructive(
    raw_data_access_allowed: bool,
    import_dry_run_allowed: bool,
    import_write_allowed: bool,
    destructive_actions_allowed: bool,
) -> None:
    if raw_data_access_allowed or import_dry_run_allowed or import_write_allowed or destructive_actions_allowed:
        raise ValueError("metadata connection probe skeleton cannot allow raw/import/destructive work")


def _assert_safe_model(value: BaseModel) -> None:
    _assert_safe_payload(value.model_dump_json().lower())


def _assert_safe_payload(payload: str) -> None:
    lowered = payload.lower()
    for fragment in FORBIDDEN_FRAGMENTS:
        if fragment in lowered:
            raise ValueError(f"metadata connection probe skeleton evidence contains forbidden fragment: {fragment}")


if __name__ == "__main__":
    main()
