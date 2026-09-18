from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Self, cast

import psycopg
from pydantic import BaseModel, ConfigDict, Field, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.platform.legacy_sql_connector_metadata_connection_probe_gate import (
    LegacySqlConnectorMetadataConnectionProbeGateEvidence,
    LegacySqlConnectorMetadataConnectionProbeGateStatus,
    build_legacy_sql_connector_metadata_connection_probe_gate_hash,
)
from suite.platform.legacy_sql_connector_metadata_connection_probe_skeleton import (
    CapturingMetadataProbeAuditSink,
    LegacySqlConnectorMetadataConnectionProbeExecutionEvidence,
    LegacySqlConnectorMetadataConnectionProbeSkeletonStatus,
    MetadataProbeAdapterResult,
    _build_ready_metadata_connection_probe_gate,
    build_legacy_sql_connector_metadata_connection_probe_skeleton_command,
    execute_legacy_sql_connector_metadata_connection_probe_skeleton,
)
from suite.platform.legacy_sql_connector_real_connection_executor import (
    LegacySqlConnectorRealConnectionPolicyStoreBackend,
)
from suite.platform.legacy_sql_discovery import MODULE_ID_PATTERN, NAMESPACED_REF_PATTERN, LegacySqlConnectorKind
from suite.platform.legacy_sql_metadata_worker_queue import LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN

COMMAND_SCHEMA_VERSION = "legacy_sql_connector_metadata_connection_probe_live_adapter_command.v1"
EVIDENCE_SCHEMA_VERSION = "legacy_sql_connector_metadata_connection_probe_live_adapter_evidence.v1"
SMOKE_SCHEMA_VERSION = "legacy_sql_connector_metadata_connection_probe_live_adapter_smoke_report.v1"
COMMAND_REF = "docker-compose:legacy-sql-connector-metadata-connection-probe-live-adapter-smoke"
LIVE_POSTGRES_PROVIDER_ADAPTER_REF = "provider-driver-adapter:legacy-sql-metadata-only-live-postgres"
LIVE_POSTGRES_SECRET_HANDLE_REF = "sealed-handle:legacy-sql-metadata-live-postgres"
LIVE_METADATA_QUERY_ALLOWLIST_REF = "metadata-query-allowlist:legacy-sql-live-catalog-v1"
SUPPORTED_LIVE_PROVIDER = LegacySqlConnectorKind.POSTGRES
ZERO_HASH = "sha256:" + "0" * 64
POSTGRES_METADATA_QUERIES: dict[str, str] = {
    "tables": """
        SELECT count(*)
        FROM information_schema.tables
        WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
    """,
    "columns": """
        SELECT count(*)
        FROM information_schema.columns
        WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
    """,
    "primary_keys": """
        SELECT count(*)
        FROM information_schema.table_constraints
        WHERE constraint_type = 'PRIMARY KEY'
          AND table_schema NOT IN ('pg_catalog', 'information_schema')
    """,
}
FORBIDDEN_LIVE_EVIDENCE_FRAGMENTS = (
    '"dsn":',
    "postgresql://",
    "postgres://",
    "sqlserver://",
    "password",
    "connection_string",
    "plain_secret",
    '"secret_material_value":',
    '"raw_payload":',
    '"sample_values":',
    '"row_values":',
    '"record_values":',
    '"import_write_payload":',
)


class LegacySqlConnectorMetadataConnectionProbeLiveAdapterStatus(StrEnum):
    BLOCKED = "blocked"
    EXECUTED = "executed"


class LegacySqlConnectorMetadataConnectionProbeLiveAdapterCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = COMMAND_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    metadata_connection_probe_gate_evidence_hash: str
    provider_driver_adapter_ref: str = LIVE_POSTGRES_PROVIDER_ADAPTER_REF
    sealed_secret_handle_ref: str = LIVE_POSTGRES_SECRET_HANDLE_REF
    metadata_query_allowlist_ref: str = LIVE_METADATA_QUERY_ALLOWLIST_REF
    allowed_query_names: tuple[str, ...] = tuple(POSTGRES_METADATA_QUERIES)
    connect_timeout_seconds: int = Field(default=5, ge=1, le=30)
    metadata_query_timeout_seconds: int = Field(default=10, ge=1, le=60)
    total_budget_seconds: int = Field(default=20, ge=1, le=120)
    live_adapter_runtime_enabled: bool = False
    secret_materialization_enabled: bool = False
    network_route_allowed: bool = False
    isolated_worker_enabled: bool = True
    redaction_boundary_enabled: bool = True
    audit_sink_enabled: bool = True
    timeout_circuit_breaker_enabled: bool = True
    emergency_stop_armed: bool = True
    emergency_stop_active: bool = False
    raw_data_access_requested: bool = False
    import_dry_run_requested: bool = False
    import_write_requested: bool = False
    destructive_actions_requested: bool = False
    requested_by: str

    @model_validator(mode="after")
    def validate_command(self) -> Self:
        if self.schema_version != COMMAND_SCHEMA_VERSION:
            raise ValueError("metadata connection probe live adapter command schema mismatch")
        _validate_refs(
            tenant_id=self.tenant_id,
            module_id=self.module_id,
            refs=(
                self.source_system_ref,
                self.provider_driver_adapter_ref,
                self.sealed_secret_handle_ref,
                self.metadata_query_allowlist_ref,
            ),
            hashes=(self.metadata_connection_probe_gate_evidence_hash,),
        )
        if self.total_budget_seconds < self.connect_timeout_seconds + self.metadata_query_timeout_seconds:
            raise ValueError("metadata connection probe live adapter time budget is too small")
        if not self.requested_by.strip():
            raise ValueError("metadata connection probe live adapter requested_by is required")
        if not self.allowed_query_names:
            raise ValueError("metadata connection probe live adapter query allowlist is required")
        if len(self.allowed_query_names) != len(set(self.allowed_query_names)):
            raise ValueError("metadata connection probe live adapter query allowlist must be unique")
        for query_name in self.allowed_query_names:
            if query_name not in POSTGRES_METADATA_QUERIES:
                raise ValueError("metadata connection probe live adapter query is not allowlisted")
        _assert_safe_payload(canonical_json(self.model_dump(mode="json")))
        return self


class LegacySqlConnectorMetadataConnectionProbeLiveAdapterEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = EVIDENCE_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    command_ref: str = COMMAND_REF
    command_hash: str
    metadata_connection_probe_gate_evidence_hash: str
    skeleton_execution_evidence_hash: str | None = None
    skeleton_command_hash: str | None = None
    skeleton_execution_status: LegacySqlConnectorMetadataConnectionProbeSkeletonStatus | None = None
    live_provider_adapter_ref: str
    sealed_secret_handle_ref: str
    metadata_query_allowlist_ref: str
    executed_query_names: tuple[str, ...] = ()
    metadata_result_set_hashes: tuple[str, ...] = ()
    metadata_relation_count: int = Field(default=0, ge=0)
    metadata_column_count: int = Field(default=0, ge=0)
    metadata_primary_key_count: int = Field(default=0, ge=0)
    live_adapter_runtime_enabled: bool
    secret_materialization_enabled: bool
    secret_materialized_inside_worker: bool = False
    secret_material_exposed_to_evidence: bool = False
    network_route_allowed: bool
    isolated_worker_enabled: bool
    redaction_boundary_enabled: bool
    redaction_boundary_passed: bool
    audit_sink_enabled: bool
    timeout_circuit_breaker_enabled: bool
    emergency_stop_armed: bool
    emergency_stop_active: bool
    provider_driver_loaded_by_adapter: bool = False
    network_socket_opened: bool = False
    network_connection_opened: bool = False
    real_connection_opened: bool = False
    read_only_transaction_verified: bool = False
    raw_data_access_allowed: bool = False
    raw_rows_returned: bool = False
    sample_values_returned: bool = False
    stored_procedure_body_returned: bool = False
    import_dry_run_allowed: bool = False
    import_write_allowed: bool = False
    destructive_actions_allowed: bool = False
    future_raw_data_gate_required: bool = True
    future_import_dry_run_gate_required: bool = True
    evidence_status: LegacySqlConnectorMetadataConnectionProbeLiveAdapterStatus
    blocking_reasons: tuple[str, ...]
    redacted_error_hash: str | None = None
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @model_validator(mode="after")
    def validate_evidence(self) -> Self:
        if self.schema_version != EVIDENCE_SCHEMA_VERSION:
            raise ValueError("metadata connection probe live adapter evidence schema mismatch")
        hashes = [self.command_hash, self.metadata_connection_probe_gate_evidence_hash, self.evidence_hash]
        for optional_hash in (
            self.skeleton_execution_evidence_hash,
            self.skeleton_command_hash,
            self.redacted_error_hash,
            *self.metadata_result_set_hashes,
        ):
            if optional_hash is not None:
                hashes.append(optional_hash)
        _validate_refs(
            tenant_id=self.tenant_id,
            module_id=self.module_id,
            refs=(
                self.source_system_ref,
                self.command_ref,
                self.live_provider_adapter_ref,
                self.sealed_secret_handle_ref,
                self.metadata_query_allowlist_ref,
            ),
            hashes=tuple(hashes),
        )
        unsafe = (
            self.secret_material_exposed_to_evidence
            or self.raw_data_access_allowed
            or self.raw_rows_returned
            or self.sample_values_returned
            or self.stored_procedure_body_returned
            or self.import_dry_run_allowed
            or self.import_write_allowed
            or self.destructive_actions_allowed
        )
        if unsafe:
            raise ValueError("metadata connection probe live adapter evidence must remain metadata-only")
        if self.evidence_status == LegacySqlConnectorMetadataConnectionProbeLiveAdapterStatus.EXECUTED:
            required = (
                self.skeleton_execution_evidence_hash is not None,
                self.skeleton_command_hash is not None,
                self.skeleton_execution_status == LegacySqlConnectorMetadataConnectionProbeSkeletonStatus.EXECUTED,
                self.live_adapter_runtime_enabled,
                self.secret_materialization_enabled,
                self.secret_materialized_inside_worker,
                self.network_route_allowed,
                self.isolated_worker_enabled,
                self.redaction_boundary_enabled,
                self.redaction_boundary_passed,
                self.audit_sink_enabled,
                self.timeout_circuit_breaker_enabled,
                self.emergency_stop_armed,
                not self.emergency_stop_active,
                self.provider_driver_loaded_by_adapter,
                self.network_socket_opened,
                self.network_connection_opened,
                self.real_connection_opened,
                self.read_only_transaction_verified,
                self.future_raw_data_gate_required,
                self.future_import_dry_run_gate_required,
            )
            if self.blocking_reasons or not all(required):
                raise ValueError("executed metadata connection probe live adapter evidence is incomplete")
        if self.evidence_status == LegacySqlConnectorMetadataConnectionProbeLiveAdapterStatus.BLOCKED:
            if not self.blocking_reasons:
                raise ValueError("blocked metadata connection probe live adapter evidence requires blockers")
            if self.network_socket_opened or self.real_connection_opened or self.secret_materialized_inside_worker:
                raise ValueError("blocked metadata connection probe live adapter must not materialize or connect")
        _assert_safe_payload(canonical_json(self.model_dump(mode="json")))
        return self


class LegacySqlConnectorMetadataConnectionProbeLiveAdapterSmokeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SMOKE_SCHEMA_VERSION
    tenant_id: str
    store_backend: LegacySqlConnectorRealConnectionPolicyStoreBackend
    continuity_domain: str = LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN
    command_ref: str = COMMAND_REF
    metadata_connection_probe_gate_evidence_hash: str
    default_off_evidence_hash: str
    no_secret_materialization_evidence_hash: str
    no_network_route_evidence_hash: str
    emergency_stop_evidence_hash: str
    live_postgres_evidence_hash: str
    metadata_connection_probe_gate_ready: bool
    default_off_blocked: bool
    no_secret_materialization_blocked: bool
    no_network_route_blocked: bool
    emergency_stop_blocked: bool
    live_postgres_probe_completed: bool
    live_adapter_runtime_enabled: bool
    secret_materialized_inside_worker: bool
    secret_material_exposed_to_evidence: bool = False
    network_route_allowed: bool
    provider_driver_loaded_by_adapter: bool
    network_socket_opened: bool
    network_connection_opened: bool
    real_connection_opened: bool
    read_only_transaction_verified: bool
    redaction_boundary_passed: bool
    audit_sink_bound: bool
    timeout_circuit_breaker_bound: bool
    emergency_stop_bound: bool
    isolated_worker_bound: bool
    raw_data_access_allowed: bool = False
    raw_rows_returned: bool = False
    sample_values_returned: bool = False
    stored_procedure_body_returned: bool = False
    import_dry_run_allowed: bool = False
    import_write_allowed: bool = False
    destructive_actions_allowed: bool = False
    future_raw_data_gate_required: bool = True
    future_import_dry_run_gate_required: bool = True
    metadata_relation_count: int = Field(default=0, ge=0)
    metadata_column_count: int = Field(default=0, ge=0)
    metadata_primary_key_count: int = Field(default=0, ge=0)
    smoke_passed: bool
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @model_validator(mode="after")
    def validate_smoke(self) -> Self:
        if self.schema_version != SMOKE_SCHEMA_VERSION:
            raise ValueError("metadata connection probe live adapter smoke schema mismatch")
        _validate_refs(
            tenant_id=self.tenant_id,
            module_id="crm_erp",
            refs=(self.command_ref,),
            hashes=(
                self.metadata_connection_probe_gate_evidence_hash,
                self.default_off_evidence_hash,
                self.no_secret_materialization_evidence_hash,
                self.no_network_route_evidence_hash,
                self.emergency_stop_evidence_hash,
                self.live_postgres_evidence_hash,
                self.evidence_hash,
            ),
        )
        unsafe = (
            self.secret_material_exposed_to_evidence
            or self.raw_data_access_allowed
            or self.raw_rows_returned
            or self.sample_values_returned
            or self.stored_procedure_body_returned
            or self.import_dry_run_allowed
            or self.import_write_allowed
            or self.destructive_actions_allowed
        )
        if unsafe:
            raise ValueError("metadata connection probe live adapter smoke must remain metadata-only")
        if self.smoke_passed:
            required = (
                self.metadata_connection_probe_gate_ready,
                self.default_off_blocked,
                self.no_secret_materialization_blocked,
                self.no_network_route_blocked,
                self.emergency_stop_blocked,
                self.live_postgres_probe_completed,
                self.live_adapter_runtime_enabled,
                self.secret_materialized_inside_worker,
                self.network_route_allowed,
                self.provider_driver_loaded_by_adapter,
                self.network_socket_opened,
                self.network_connection_opened,
                self.real_connection_opened,
                self.read_only_transaction_verified,
                self.redaction_boundary_passed,
                self.audit_sink_bound,
                self.timeout_circuit_breaker_bound,
                self.emergency_stop_bound,
                self.isolated_worker_bound,
                self.future_raw_data_gate_required,
                self.future_import_dry_run_gate_required,
            )
            if not all(required):
                raise ValueError("passing metadata connection probe live adapter smoke requires all evidence")
        _assert_safe_payload(canonical_json(self.model_dump(mode="json")))
        return self


@dataclass(frozen=True)
class _LivePostgresSecretMaterial:
    dsn: str


@dataclass
class LivePostgresMetadataProbeSecretBroker:
    dsn: str
    calls: list[str] = field(default_factory=list)

    def read_handle_metadata(self, *, command: Any) -> str:
        self.calls.append("read_handle_metadata")
        payload = {
            "schema_version": "legacy_sql_connector_metadata_connection_probe_live_secret_handle_metadata.v1",
            "tenant_id": command.tenant_id,
            "module_id": command.module_id,
            "source_system_ref": command.source_system_ref,
            "sealed_secret_handle_ref": command.sealed_secret_handle_ref,
            "secret_material_exposed_to_evidence": False,
        }
        _assert_safe_payload(canonical_json(payload))
        return stable_hash(canonical_json(payload))

    def materialize_for_worker(
        self, *, command: LegacySqlConnectorMetadataConnectionProbeLiveAdapterCommand
    ) -> _LivePostgresSecretMaterial:
        self.calls.append("materialize_for_worker")
        if not command.secret_materialization_enabled:
            raise RuntimeError("secret materialization is disabled")
        if not self.dsn.strip():
            raise RuntimeError("live adapter secret handle is empty")
        return _LivePostgresSecretMaterial(dsn=self.dsn)


@dataclass
class PostgresMetadataOnlyProbeProviderAdapter:
    live_command: LegacySqlConnectorMetadataConnectionProbeLiveAdapterCommand
    secret_broker: LivePostgresMetadataProbeSecretBroker
    calls: list[tuple[str, ...]] = field(default_factory=list)
    secret_materialized_inside_worker: bool = False
    read_only_transaction_verified: bool = False
    metadata_primary_key_count: int = 0

    def run_metadata_probe(self, *, command: Any, secret_handle_metadata_hash: str) -> MetadataProbeAdapterResult:
        _validate_hash(secret_handle_metadata_hash)
        if self.live_command.connector_kind != SUPPORTED_LIVE_PROVIDER:
            raise RuntimeError("live metadata adapter currently supports postgres only")
        if not self.live_command.network_route_allowed:
            raise RuntimeError("live metadata adapter network route is not allowed")
        if self.live_command.emergency_stop_active:
            raise RuntimeError("live metadata adapter emergency stop is active")
        if tuple(command.allowed_query_names) != self.live_command.allowed_query_names:
            raise RuntimeError("live metadata adapter query allowlist mismatch")
        secret_material = self.secret_broker.materialize_for_worker(command=self.live_command)
        self.secret_materialized_inside_worker = True
        counts: dict[str, int] = {}
        timeout_ms = self.live_command.metadata_query_timeout_seconds * 1000
        with (
            psycopg.connect(
                secret_material.dsn,
                connect_timeout=self.live_command.connect_timeout_seconds,
                options=f"-c statement_timeout={timeout_ms} -c default_transaction_read_only=on",
            ) as connection,
            connection.cursor() as cursor,
        ):
            cursor.execute("SELECT current_setting('transaction_read_only')")
            readonly_row = cursor.fetchone()
            self.read_only_transaction_verified = readonly_row is not None and readonly_row[0] == "on"
            if not self.read_only_transaction_verified:
                raise RuntimeError("live metadata adapter read-only transaction was not enforced")
            for query_name in self.live_command.allowed_query_names:
                counts[query_name] = _fetch_metadata_count(cursor, POSTGRES_METADATA_QUERIES[query_name])
        self.calls.append(self.live_command.allowed_query_names)
        relation_count = counts.get("tables", 0)
        column_count = counts.get("columns", 0)
        self.metadata_primary_key_count = counts.get("primary_keys", 0)
        result_hashes = tuple(
            stable_hash(
                canonical_json(
                    {
                        "query_name": query_name,
                        "metadata_count": counts[query_name],
                        "metadata_only_live_postgres": True,
                    }
                )
            )
            for query_name in self.live_command.allowed_query_names
        )
        result_hash = stable_hash(
            canonical_json(
                {
                    "schema_version": "legacy_sql_connector_metadata_connection_probe_live_adapter_result.v1",
                    "tenant_id": self.live_command.tenant_id,
                    "source_system_ref": self.live_command.source_system_ref,
                    "executed_query_names": self.live_command.allowed_query_names,
                    "result_set_hashes": result_hashes,
                    "metadata_relation_count": relation_count,
                    "metadata_column_count": column_count,
                    "metadata_primary_key_count": self.metadata_primary_key_count,
                    "read_only_transaction_verified": self.read_only_transaction_verified,
                    "secret_material_exposed_to_evidence": False,
                    "raw_rows_returned": False,
                    "sample_values_returned": False,
                }
            )
        )
        return MetadataProbeAdapterResult(
            evidence_hash=result_hash,
            executed_query_names=self.live_command.allowed_query_names,
            result_set_hashes=result_hashes,
            metadata_relation_count=relation_count,
            metadata_column_count=column_count,
            provider_driver_adapter_invoked=True,
            provider_driver_loaded_by_adapter=True,
            network_socket_opened=True,
            network_connection_opened=True,
            real_connection_opened=True,
            raw_rows_returned=False,
            sample_values_returned=False,
            stored_procedure_body_returned=False,
        )


def build_legacy_sql_connector_metadata_connection_probe_live_adapter_command(
    *,
    metadata_connection_probe_gate: LegacySqlConnectorMetadataConnectionProbeGateEvidence,
    requested_by: str,
    live_adapter_runtime_enabled: bool = False,
    secret_materialization_enabled: bool = False,
    network_route_allowed: bool = False,
    isolated_worker_enabled: bool = True,
    redaction_boundary_enabled: bool = True,
    audit_sink_enabled: bool = True,
    timeout_circuit_breaker_enabled: bool = True,
    emergency_stop_armed: bool = True,
    emergency_stop_active: bool = False,
    allowed_query_names: tuple[str, ...] = tuple(POSTGRES_METADATA_QUERIES),
    raw_data_access_requested: bool = False,
    import_dry_run_requested: bool = False,
    import_write_requested: bool = False,
    destructive_actions_requested: bool = False,
) -> LegacySqlConnectorMetadataConnectionProbeLiveAdapterCommand:
    return LegacySqlConnectorMetadataConnectionProbeLiveAdapterCommand(
        tenant_id=metadata_connection_probe_gate.tenant_id,
        module_id=metadata_connection_probe_gate.module_id,
        source_system_ref=metadata_connection_probe_gate.source_system_ref,
        connector_kind=metadata_connection_probe_gate.connector_kind,
        metadata_connection_probe_gate_evidence_hash=metadata_connection_probe_gate.evidence_hash,
        allowed_query_names=allowed_query_names,
        live_adapter_runtime_enabled=live_adapter_runtime_enabled,
        secret_materialization_enabled=secret_materialization_enabled,
        network_route_allowed=network_route_allowed,
        isolated_worker_enabled=isolated_worker_enabled,
        redaction_boundary_enabled=redaction_boundary_enabled,
        audit_sink_enabled=audit_sink_enabled,
        timeout_circuit_breaker_enabled=timeout_circuit_breaker_enabled,
        emergency_stop_armed=emergency_stop_armed,
        emergency_stop_active=emergency_stop_active,
        raw_data_access_requested=raw_data_access_requested,
        import_dry_run_requested=import_dry_run_requested,
        import_write_requested=import_write_requested,
        destructive_actions_requested=destructive_actions_requested,
        requested_by=requested_by,
    )


def execute_legacy_sql_connector_metadata_connection_probe_live_adapter(
    *,
    command: LegacySqlConnectorMetadataConnectionProbeLiveAdapterCommand,
    metadata_connection_probe_gate: LegacySqlConnectorMetadataConnectionProbeGateEvidence,
    secret_broker: LivePostgresMetadataProbeSecretBroker,
    checked_by: str,
    checked_at_utc: datetime | None = None,
) -> LegacySqlConnectorMetadataConnectionProbeLiveAdapterEvidence:
    checked_at = checked_at_utc or datetime.now(UTC)
    command_hash = build_legacy_sql_connector_metadata_connection_probe_live_adapter_command_hash(command)
    blocking_reasons = _live_adapter_blocking_reasons(command=command, gate=metadata_connection_probe_gate)
    if blocking_reasons:
        return _build_live_adapter_evidence(
            command=command,
            command_hash=command_hash,
            metadata_connection_probe_gate=metadata_connection_probe_gate,
            blocking_reasons=blocking_reasons,
            checked_by=checked_by,
            checked_at_utc=checked_at,
        )
    provider_adapter = PostgresMetadataOnlyProbeProviderAdapter(live_command=command, secret_broker=secret_broker)
    skeleton_command = build_legacy_sql_connector_metadata_connection_probe_skeleton_command(
        metadata_connection_probe_gate=metadata_connection_probe_gate,
        requested_by=command.requested_by,
        metadata_probe_runtime_enabled=True,
        allowed_query_names=command.allowed_query_names,
        provider_driver_adapter_ref=command.provider_driver_adapter_ref,
        sealed_secret_handle_ref=command.sealed_secret_handle_ref,
        metadata_query_allowlist_ref=command.metadata_query_allowlist_ref,
        connect_timeout_seconds=command.connect_timeout_seconds,
        metadata_query_timeout_seconds=command.metadata_query_timeout_seconds,
        total_budget_seconds=command.total_budget_seconds,
    )
    try:
        skeleton_evidence = execute_legacy_sql_connector_metadata_connection_probe_skeleton(
            command=skeleton_command,
            metadata_connection_probe_gate=metadata_connection_probe_gate,
            provider_adapter=provider_adapter,
            secret_broker=secret_broker,
            audit_sink=CapturingMetadataProbeAuditSink() if command.audit_sink_enabled else None,
            checked_by=checked_by,
            checked_at_utc=checked_at + timedelta(seconds=1),
        )
    except Exception as exc:  # pragma: no cover - covered through redacted failure assertions
        return _build_live_adapter_evidence(
            command=command,
            command_hash=command_hash,
            metadata_connection_probe_gate=metadata_connection_probe_gate,
            blocking_reasons=("live_adapter_execution_failed",),
            checked_by=checked_by,
            checked_at_utc=checked_at + timedelta(seconds=2),
            redacted_error_hash=stable_hash(canonical_json({"error_type": type(exc).__name__})),
        )
    return _build_live_adapter_evidence(
        command=command,
        command_hash=command_hash,
        metadata_connection_probe_gate=metadata_connection_probe_gate,
        skeleton_evidence=skeleton_evidence,
        provider_adapter=provider_adapter,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=3),
    )


def build_legacy_sql_connector_metadata_connection_probe_live_adapter_command_hash(
    command: LegacySqlConnectorMetadataConnectionProbeLiveAdapterCommand,
) -> str:
    return stable_hash(canonical_json(command.model_dump(mode="json")))


def build_legacy_sql_connector_metadata_connection_probe_live_adapter_evidence_hash(
    evidence: LegacySqlConnectorMetadataConnectionProbeLiveAdapterEvidence,
) -> str:
    return stable_hash(canonical_json(evidence.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_metadata_connection_probe_live_adapter_smoke_report_hash(
    report: LegacySqlConnectorMetadataConnectionProbeLiveAdapterSmokeReport,
) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def run_legacy_sql_connector_metadata_connection_probe_live_adapter_smoke_from_env(
    environ: Mapping[str, str] | None = None,
) -> LegacySqlConnectorMetadataConnectionProbeLiveAdapterSmokeReport:
    raw_env = os.environ if environ is None else environ
    env = dict(raw_env)
    env.setdefault("SUITE_LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_CONNECTOR_KIND", LegacySqlConnectorKind.POSTGRES.value)
    env.setdefault("SUITE_LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_SOURCE_REF", "legacy-sql:production-postgres")
    env.setdefault(
        "SUITE_LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_HOST_PROFILE_REF",
        "legacy-host:postgres-production-metadata",
    )
    checked_by = env.get(
        "SUITE_LEGACY_SQL_CONNECTOR_METADATA_CONNECTION_PROBE_LIVE_ADAPTER_CHECKED_BY",
        "legacy-sql-connector-metadata-connection-probe-live-adapter-smoke",
    )
    checked_at = datetime.now(UTC)
    store_backend = LegacySqlConnectorRealConnectionPolicyStoreBackend(
        env.get(
            "SUITE_LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_POLICY_STORE_BACKEND",
            LegacySqlConnectorRealConnectionPolicyStoreBackend.JSONL.value,
        )
    )
    secret_dsn = _first_required_env(
        env,
        "SUITE_LEGACY_SQL_CONNECTOR_METADATA_CONNECTION_PROBE_LIVE_ADAPTER_SECRET_DSN",
        "SUITE_WORKER_DATABASE_DSN",
        "SUITE_DATABASE_DSN",
    )
    _bundle, gate = _build_ready_metadata_connection_probe_gate(env=env, checked_by=checked_by, checked_at=checked_at)
    default_off = _execute_smoke_case(
        gate=gate,
        secret_dsn=secret_dsn,
        checked_by=checked_by,
        checked_at=checked_at,
    )
    no_secret = _execute_smoke_case(
        gate=gate,
        secret_dsn=secret_dsn,
        checked_by=checked_by,
        checked_at=checked_at + timedelta(seconds=10),
        live_adapter_runtime_enabled=True,
        network_route_allowed=True,
    )
    no_network = _execute_smoke_case(
        gate=gate,
        secret_dsn=secret_dsn,
        checked_by=checked_by,
        checked_at=checked_at + timedelta(seconds=20),
        live_adapter_runtime_enabled=True,
        secret_materialization_enabled=True,
    )
    emergency_stop = _execute_smoke_case(
        gate=gate,
        secret_dsn=secret_dsn,
        checked_by=checked_by,
        checked_at=checked_at + timedelta(seconds=30),
        live_adapter_runtime_enabled=True,
        secret_materialization_enabled=True,
        network_route_allowed=True,
        emergency_stop_active=True,
    )
    live_postgres = _execute_smoke_case(
        gate=gate,
        secret_dsn=secret_dsn,
        checked_by=checked_by,
        checked_at=checked_at + timedelta(seconds=40),
        live_adapter_runtime_enabled=True,
        secret_materialization_enabled=True,
        network_route_allowed=True,
    )
    default_off_blocked = _blocked(default_off, "live_adapter_runtime_default_off")
    no_secret_blocked = _blocked(no_secret, "secret_materialization_not_enabled")
    no_network_blocked = _blocked(no_network, "network_route_not_allowed")
    emergency_stop_blocked = _blocked(emergency_stop, "emergency_stop_active")
    live_completed = (
        live_postgres.evidence_status == LegacySqlConnectorMetadataConnectionProbeLiveAdapterStatus.EXECUTED
    )
    smoke_passed = (
        gate.gate_status == LegacySqlConnectorMetadataConnectionProbeGateStatus.READY
        and gate.metadata_connection_probe_gate_ready
        and default_off_blocked
        and no_secret_blocked
        and no_network_blocked
        and emergency_stop_blocked
        and live_completed
    )
    draft = LegacySqlConnectorMetadataConnectionProbeLiveAdapterSmokeReport(
        tenant_id=gate.tenant_id,
        store_backend=store_backend,
        metadata_connection_probe_gate_evidence_hash=gate.evidence_hash,
        default_off_evidence_hash=default_off.evidence_hash,
        no_secret_materialization_evidence_hash=no_secret.evidence_hash,
        no_network_route_evidence_hash=no_network.evidence_hash,
        emergency_stop_evidence_hash=emergency_stop.evidence_hash,
        live_postgres_evidence_hash=live_postgres.evidence_hash,
        metadata_connection_probe_gate_ready=gate.metadata_connection_probe_gate_ready,
        default_off_blocked=default_off_blocked,
        no_secret_materialization_blocked=no_secret_blocked,
        no_network_route_blocked=no_network_blocked,
        emergency_stop_blocked=emergency_stop_blocked,
        live_postgres_probe_completed=live_completed,
        live_adapter_runtime_enabled=live_postgres.live_adapter_runtime_enabled,
        secret_materialized_inside_worker=live_postgres.secret_materialized_inside_worker,
        network_route_allowed=live_postgres.network_route_allowed,
        provider_driver_loaded_by_adapter=live_postgres.provider_driver_loaded_by_adapter,
        network_socket_opened=live_postgres.network_socket_opened,
        network_connection_opened=live_postgres.network_connection_opened,
        real_connection_opened=live_postgres.real_connection_opened,
        read_only_transaction_verified=live_postgres.read_only_transaction_verified,
        redaction_boundary_passed=live_postgres.redaction_boundary_passed,
        audit_sink_bound=live_postgres.audit_sink_enabled,
        timeout_circuit_breaker_bound=live_postgres.timeout_circuit_breaker_enabled,
        emergency_stop_bound=live_postgres.emergency_stop_armed,
        isolated_worker_bound=live_postgres.isolated_worker_enabled,
        metadata_relation_count=live_postgres.metadata_relation_count,
        metadata_column_count=live_postgres.metadata_column_count,
        metadata_primary_key_count=live_postgres.metadata_primary_key_count,
        smoke_passed=smoke_passed,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(
        update={
            "evidence_hash": build_legacy_sql_connector_metadata_connection_probe_live_adapter_smoke_report_hash(draft)
        }
    )


def exit_code_for_report(report: LegacySqlConnectorMetadataConnectionProbeLiveAdapterSmokeReport) -> int:
    return 0 if report.smoke_passed else 1


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Legacy SQL metadata connection probe live adapter smoke.")
    parser.add_argument(
        "--once", action="store_true", help="Run one metadata connection probe live adapter smoke and exit."
    )
    parser.add_argument(
        "--pretty", action="store_true", help="Pretty-print the metadata connection probe live adapter report."
    )
    args = parser.parse_args(argv)
    del args.once

    report = run_legacy_sql_connector_metadata_connection_probe_live_adapter_smoke_from_env()
    print(json.dumps(report.model_dump(mode="json"), indent=2 if args.pretty else None, sort_keys=True))
    raise SystemExit(exit_code_for_report(report))


def _execute_smoke_case(
    *,
    gate: LegacySqlConnectorMetadataConnectionProbeGateEvidence,
    secret_dsn: str,
    checked_by: str,
    checked_at: datetime,
    live_adapter_runtime_enabled: bool = False,
    secret_materialization_enabled: bool = False,
    network_route_allowed: bool = False,
    emergency_stop_active: bool = False,
) -> LegacySqlConnectorMetadataConnectionProbeLiveAdapterEvidence:
    command = build_legacy_sql_connector_metadata_connection_probe_live_adapter_command(
        metadata_connection_probe_gate=gate,
        requested_by=checked_by,
        live_adapter_runtime_enabled=live_adapter_runtime_enabled,
        secret_materialization_enabled=secret_materialization_enabled,
        network_route_allowed=network_route_allowed,
        emergency_stop_active=emergency_stop_active,
    )
    return execute_legacy_sql_connector_metadata_connection_probe_live_adapter(
        command=command,
        metadata_connection_probe_gate=gate,
        secret_broker=LivePostgresMetadataProbeSecretBroker(dsn=secret_dsn),
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )


def _build_live_adapter_evidence(
    *,
    command: LegacySqlConnectorMetadataConnectionProbeLiveAdapterCommand,
    command_hash: str,
    metadata_connection_probe_gate: LegacySqlConnectorMetadataConnectionProbeGateEvidence,
    checked_by: str,
    checked_at_utc: datetime,
    blocking_reasons: tuple[str, ...] = (),
    skeleton_evidence: LegacySqlConnectorMetadataConnectionProbeExecutionEvidence | None = None,
    provider_adapter: PostgresMetadataOnlyProbeProviderAdapter | None = None,
    redacted_error_hash: str | None = None,
) -> LegacySqlConnectorMetadataConnectionProbeLiveAdapterEvidence:
    executed = skeleton_evidence is not None and not blocking_reasons
    payload_safe = True
    metadata_result_hashes = skeleton_evidence.metadata_result_set_hashes if skeleton_evidence else ()
    draft = LegacySqlConnectorMetadataConnectionProbeLiveAdapterEvidence(
        tenant_id=command.tenant_id,
        module_id=command.module_id,
        source_system_ref=command.source_system_ref,
        connector_kind=command.connector_kind,
        command_hash=command_hash,
        metadata_connection_probe_gate_evidence_hash=metadata_connection_probe_gate.evidence_hash,
        skeleton_execution_evidence_hash=skeleton_evidence.evidence_hash if skeleton_evidence else None,
        skeleton_command_hash=skeleton_evidence.command_hash if skeleton_evidence else None,
        skeleton_execution_status=skeleton_evidence.evidence_status if skeleton_evidence else None,
        live_provider_adapter_ref=command.provider_driver_adapter_ref,
        sealed_secret_handle_ref=command.sealed_secret_handle_ref,
        metadata_query_allowlist_ref=command.metadata_query_allowlist_ref,
        executed_query_names=skeleton_evidence.executed_query_names if skeleton_evidence else (),
        metadata_result_set_hashes=metadata_result_hashes,
        metadata_relation_count=skeleton_evidence.metadata_relation_count if skeleton_evidence else 0,
        metadata_column_count=skeleton_evidence.metadata_column_count if skeleton_evidence else 0,
        metadata_primary_key_count=provider_adapter.metadata_primary_key_count if provider_adapter else 0,
        live_adapter_runtime_enabled=command.live_adapter_runtime_enabled,
        secret_materialization_enabled=command.secret_materialization_enabled,
        secret_materialized_inside_worker=bool(provider_adapter and provider_adapter.secret_materialized_inside_worker),
        network_route_allowed=command.network_route_allowed,
        isolated_worker_enabled=command.isolated_worker_enabled,
        redaction_boundary_enabled=command.redaction_boundary_enabled,
        redaction_boundary_passed=payload_safe,
        audit_sink_enabled=command.audit_sink_enabled,
        timeout_circuit_breaker_enabled=command.timeout_circuit_breaker_enabled,
        emergency_stop_armed=command.emergency_stop_armed,
        emergency_stop_active=command.emergency_stop_active,
        provider_driver_loaded_by_adapter=bool(
            skeleton_evidence and skeleton_evidence.provider_driver_loaded_by_adapter
        ),
        network_socket_opened=bool(skeleton_evidence and skeleton_evidence.network_socket_opened),
        network_connection_opened=bool(skeleton_evidence and skeleton_evidence.network_connection_opened),
        real_connection_opened=bool(skeleton_evidence and skeleton_evidence.real_connection_opened),
        read_only_transaction_verified=bool(provider_adapter and provider_adapter.read_only_transaction_verified),
        evidence_status=LegacySqlConnectorMetadataConnectionProbeLiveAdapterStatus.EXECUTED
        if executed
        else LegacySqlConnectorMetadataConnectionProbeLiveAdapterStatus.BLOCKED,
        blocking_reasons=blocking_reasons,
        redacted_error_hash=redacted_error_hash,
        checked_by=checked_by,
        checked_at_utc=checked_at_utc,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_metadata_connection_probe_live_adapter_evidence_hash(draft)}
    )


def _live_adapter_blocking_reasons(
    *,
    command: LegacySqlConnectorMetadataConnectionProbeLiveAdapterCommand,
    gate: LegacySqlConnectorMetadataConnectionProbeGateEvidence,
) -> tuple[str, ...]:
    reasons: list[str] = []
    gate_hash_valid = (
        build_legacy_sql_connector_metadata_connection_probe_gate_hash(gate)
        == gate.evidence_hash
        == command.metadata_connection_probe_gate_evidence_hash
    )
    if not gate_hash_valid:
        reasons.append("metadata_connection_probe_gate_hash_invalid")
    if not (
        gate.gate_status == LegacySqlConnectorMetadataConnectionProbeGateStatus.READY
        and gate.metadata_connection_probe_gate_ready
    ):
        reasons.append("metadata_connection_probe_gate_not_ready")
    if not _gate_matches_command(command=command, gate=gate):
        reasons.append("metadata_connection_probe_gate_not_bound")
    if command.connector_kind != SUPPORTED_LIVE_PROVIDER:
        reasons.append("live_adapter_provider_not_supported")
    if not command.live_adapter_runtime_enabled:
        reasons.append("live_adapter_runtime_default_off")
    if not command.secret_materialization_enabled:
        reasons.append("secret_materialization_not_enabled")
    if not command.network_route_allowed:
        reasons.append("network_route_not_allowed")
    if not command.isolated_worker_enabled:
        reasons.append("isolated_worker_not_enabled")
    if not command.redaction_boundary_enabled:
        reasons.append("redaction_boundary_not_enabled")
    if not command.audit_sink_enabled:
        reasons.append("audit_sink_not_enabled")
    if not command.timeout_circuit_breaker_enabled:
        reasons.append("timeout_circuit_breaker_not_enabled")
    if not command.emergency_stop_armed:
        reasons.append("emergency_stop_not_armed")
    if command.emergency_stop_active:
        reasons.append("emergency_stop_active")
    if command.raw_data_access_requested:
        reasons.append("raw_data_access_requires_future_data_gate")
    if command.import_dry_run_requested:
        reasons.append("import_dry_run_requires_future_import_gate")
    if command.import_write_requested:
        reasons.append("import_write_requires_future_import_gate")
    if command.destructive_actions_requested:
        reasons.append("destructive_actions_require_human_confirmation_gate")
    return tuple(dict.fromkeys(reasons))


def _gate_matches_command(
    *,
    command: LegacySqlConnectorMetadataConnectionProbeLiveAdapterCommand,
    gate: LegacySqlConnectorMetadataConnectionProbeGateEvidence,
) -> bool:
    return (
        command.tenant_id == gate.tenant_id
        and command.module_id == gate.module_id
        and command.source_system_ref == gate.source_system_ref
        and command.connector_kind == gate.connector_kind
        and command.metadata_connection_probe_gate_evidence_hash == gate.evidence_hash
        and not gate.metadata_connection_probe_executed
        and not gate.real_connection_opened
        and not gate.secret_material_resolved
    )


def _blocked(evidence: LegacySqlConnectorMetadataConnectionProbeLiveAdapterEvidence, reason: str) -> bool:
    return (
        evidence.evidence_status == LegacySqlConnectorMetadataConnectionProbeLiveAdapterStatus.BLOCKED
        and reason in evidence.blocking_reasons
        and not evidence.network_socket_opened
        and not evidence.real_connection_opened
        and not evidence.secret_materialized_inside_worker
    )


def _fetch_metadata_count(cursor: Any, sql: str) -> int:
    cursor.execute(sql)
    row = cursor.fetchone()
    if row is None or len(row) != 1:
        raise RuntimeError("metadata count query returned an invalid shape")
    return int(cast(int, row[0]))


def _validate_refs(*, tenant_id: str, module_id: str, refs: tuple[str, ...], hashes: tuple[str, ...]) -> None:
    if not tenant_id.strip():
        raise ValueError("tenant_id is required")
    if not MODULE_ID_PATTERN.fullmatch(module_id):
        raise ValueError("module_id must be lowercase snake_case")
    for ref in refs:
        if not NAMESPACED_REF_PATTERN.fullmatch(ref):
            raise ValueError("reference must be namespaced")
    for value in hashes:
        _validate_hash(value)


def _validate_hash(value: str) -> None:
    if not value.startswith("sha256:") or len(value) != 71:
        raise ValueError("hash must be a sha256 reference")
    suffix = value.removeprefix("sha256:")
    if any(char not in "0123456789abcdef" for char in suffix):
        raise ValueError("hash must be lowercase hex")


def _assert_safe_payload(payload: str) -> None:
    lowered = payload.lower()
    for fragment in FORBIDDEN_LIVE_EVIDENCE_FRAGMENTS:
        if fragment in lowered:
            raise ValueError("metadata connection probe live adapter evidence contains forbidden material")


def _first_required_env(env: Mapping[str, str], *names: str) -> str:
    for name in names:
        value = env.get(name)
        if value:
            return value
    joined = ", ".join(names)
    raise ValueError(f"one of {joined} is required")


if __name__ == "__main__":
    main()
