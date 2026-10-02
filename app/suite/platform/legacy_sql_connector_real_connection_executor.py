from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, Self

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.platform.legacy_sql_connector_connection_preflight_gate import (
    LegacySqlConnectorConnectionPreflightEvidence,
    LegacySqlConnectorConnectionPreflightStatus,
    _operator_context_from_env,
    _sandbox_profile_from_env,
    build_legacy_sql_connector_connection_preflight_command,
    build_legacy_sql_connector_connection_preflight_gate,
    build_legacy_sql_connector_connection_preflight_hash,
)
from suite.platform.legacy_sql_connector_provider_attestation_adapter import (
    LegacySqlConnectorProviderAttestationAdapter,
    build_legacy_sql_connector_audit_deployment_profile,
    build_legacy_sql_connector_network_deployment_profile,
    build_legacy_sql_connector_provider_attestation_adapter_command,
    build_legacy_sql_connector_secret_resolver_deployment_profile,
)
from suite.platform.legacy_sql_connector_sandbox_enablement_gate import (
    build_legacy_sql_connector_sandbox_enablement_command,
    build_legacy_sql_connector_sandbox_enablement_gate,
)
from suite.platform.legacy_sql_discovery import MODULE_ID_PATTERN, NAMESPACED_REF_PATTERN, LegacySqlConnectorKind
from suite.platform.legacy_sql_metadata_worker_queue import (
    LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN,
    LegacySqlMetadataWorkerQueueBackend,
)
from suite.platform.storage_paths import suite_data_dir

LEGACY_SQL_CONNECTOR_REAL_CONNECTION_TIMEOUT_RETRY_POLICY_SCHEMA_VERSION = (
    "legacy_sql_connector_real_connection_timeout_retry_policy.v1"
)
LEGACY_SQL_CONNECTOR_REAL_CONNECTION_AUDIT_PLAN_SCHEMA_VERSION = "legacy_sql_connector_real_connection_audit_plan.v1"
LEGACY_SQL_CONNECTOR_REAL_CONNECTION_KILL_SWITCH_POLICY_SCHEMA_VERSION = (
    "legacy_sql_connector_real_connection_kill_switch_policy.v1"
)
LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_CONTRACT_SCHEMA_VERSION = (
    "legacy_sql_connector_real_connection_executor_contract.v1"
)
LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_SMOKE_SCHEMA_VERSION = (
    "legacy_sql_connector_real_connection_executor_smoke_report.v1"
)
LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_POLICY_BUNDLE_SCHEMA_VERSION = (
    "legacy_sql_connector_real_connection_executor_policy_bundle.v1"
)
LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_POLICY_STORE_SMOKE_SCHEMA_VERSION = (
    "legacy_sql_connector_real_connection_executor_policy_store_smoke_report.v1"
)
LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_COMMAND_REF = (
    "docker-compose:legacy-sql-connector-real-connection-executor-smoke"
)
LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_POLICY_STORE_COMMAND_REF = (
    "docker-compose:legacy-sql-connector-real-connection-executor-policy-store-smoke"
)
LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_POLICY_BUNDLE_REF_PREFIX = (
    "legacy-sql-real-connection-executor-policy-bundle"
)
ZERO_HASH = "sha256:" + "0" * 64
SHA256_REF_PATTERN = r"^sha256:[a-f0-9]{64}$"
REQUIRED_AUDIT_EVENT_TYPES = (
    "connection_attempt_requested",
    "connection_attempt_started",
    "connection_attempt_blocked",
    "connection_attempt_completed",
    "connection_attempt_failed",
    "connection_attempt_killed",
)
FORBIDDEN_EXECUTOR_FRAGMENTS = (
    '"connection_secret_ref":',
    "secret:legacy-sql",
    "sqlserver://",
    "password",
    "dsn",
    "plain_secret",
    "connection_string",
    '"raw_payload":',
    '"sample_values":',
    '"import_write_payload":',
    "dbo.kunden",
    "kundenid",
    "email",
)


class LegacySqlConnectorRealConnectionExecutorStatus(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"


class LegacySqlConnectorRealConnectionPolicyStoreBackend(StrEnum):
    JSONL = "jsonl"
    POSTGRES = "postgres"


class LegacySqlConnectorRealConnectionTimeoutRetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_REAL_CONNECTION_TIMEOUT_RETRY_POLICY_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    sandbox_profile_ref: str
    sandbox_profile_evidence_hash: str
    preflight_evidence_hash: str
    retry_policy_ref: str = "retry-policy:legacy-sql-real-connection-default"
    connect_timeout_seconds: int = Field(default=5, ge=1, le=30)
    handshake_timeout_seconds: int = Field(default=5, ge=1, le=30)
    statement_timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_attempts: int = Field(default=1, ge=1, le=3)
    retry_backoff_seconds: int = Field(default=0, ge=0, le=60)
    total_budget_seconds: int = Field(default=45, ge=1, le=600)
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL real-connection timeout/retry policy text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL real-connection timeout/retry policy module_id must be lowercase snake_case")
        return value

    @field_validator("source_system_ref", "sandbox_profile_ref", "retry_policy_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL real-connection timeout/retry policy references must be namespaced")
        return value

    @field_validator("sandbox_profile_evidence_hash", "preflight_evidence_hash", "evidence_hash")
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL real-connection timeout/retry policy hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_bounded_time_budget(self) -> Self:
        minimum_budget = (
            self.max_attempts * (self.connect_timeout_seconds + self.handshake_timeout_seconds)
            + self.statement_timeout_seconds
            + ((self.max_attempts - 1) * self.retry_backoff_seconds)
        )
        if self.total_budget_seconds < minimum_budget:
            raise ValueError("legacy SQL real-connection timeout/retry policy budget is too small")
        _assert_executor_safe(self)
        return self


class LegacySqlConnectorRealConnectionAuditPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_REAL_CONNECTION_AUDIT_PLAN_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    sandbox_profile_ref: str
    sandbox_profile_evidence_hash: str
    preflight_evidence_hash: str
    audit_plan_ref: str = "audit-plan:legacy-sql-real-connection-metadata-only"
    audit_sink_ref: str = "audit-sink:append-only-metadata-events"
    audit_event_schema_ref: str = "audit-event-schema:legacy-sql-connection-attempt"
    redaction_policy_ref: str = "redaction-policy:legacy-sql-connection-attempt"
    required_event_types: tuple[str, ...] = REQUIRED_AUDIT_EVENT_TYPES
    metadata_only_events: bool = True
    prompt_or_output_body_logging_allowed: bool = False
    raw_payload_logging_allowed: bool = False
    secret_material_logging_allowed: bool = False
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL real-connection audit plan text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL real-connection audit plan module_id must be lowercase snake_case")
        return value

    @field_validator(
        "source_system_ref",
        "sandbox_profile_ref",
        "audit_plan_ref",
        "audit_sink_ref",
        "audit_event_schema_ref",
        "redaction_policy_ref",
    )
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL real-connection audit plan references must be namespaced")
        return value

    @field_validator("sandbox_profile_evidence_hash", "preflight_evidence_hash", "evidence_hash")
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL real-connection audit plan hashes must be sha256 references")
        return value

    @field_validator("required_event_types")
    @classmethod
    def validate_required_event_types(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("legacy SQL real-connection audit plan event types must be unique")
        for event_type in value:
            if not event_type.strip():
                raise ValueError("legacy SQL real-connection audit plan event types must not be empty")
        return value

    @model_validator(mode="after")
    def require_metadata_only_audit(self) -> Self:
        if not set(REQUIRED_AUDIT_EVENT_TYPES).issubset(set(self.required_event_types)):
            raise ValueError("legacy SQL real-connection audit plan is missing required event types")
        if (
            not self.metadata_only_events
            or self.prompt_or_output_body_logging_allowed
            or self.raw_payload_logging_allowed
            or self.secret_material_logging_allowed
        ):
            raise ValueError("legacy SQL real-connection audit plan must be metadata-only")
        _assert_executor_safe(self)
        return self


class LegacySqlConnectorRealConnectionKillSwitchPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_REAL_CONNECTION_KILL_SWITCH_POLICY_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    sandbox_profile_ref: str
    sandbox_profile_evidence_hash: str
    preflight_evidence_hash: str
    kill_switch_policy_ref: str = "kill-switch-policy:legacy-sql-real-connection"
    tenant_kill_switch_ref: str = "kill-switch:tenant-legacy-sql-real-connections"
    global_kill_switch_ref: str = "kill-switch:global-legacy-sql-real-connections"
    manual_abort_ref: str = "manual-abort:legacy-sql-real-connection"
    incident_channel_ref: str = "incident-channel:platform-operations"
    kill_switch_armed: bool = True
    tenant_connection_disabled: bool = False
    global_connection_disabled: bool = False
    manual_abort_requested: bool = False
    break_glass_allowed: bool = False
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL real-connection kill-switch policy text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL real-connection kill-switch policy module_id must be lowercase snake_case")
        return value

    @field_validator(
        "source_system_ref",
        "sandbox_profile_ref",
        "kill_switch_policy_ref",
        "tenant_kill_switch_ref",
        "global_kill_switch_ref",
        "manual_abort_ref",
        "incident_channel_ref",
    )
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL real-connection kill-switch policy references must be namespaced")
        return value

    @field_validator("sandbox_profile_evidence_hash", "preflight_evidence_hash", "evidence_hash")
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL real-connection kill-switch policy hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_no_break_glass_default(self) -> Self:
        if self.break_glass_allowed:
            raise ValueError("legacy SQL real-connection kill-switch policy cannot allow break-glass by default")
        _assert_executor_safe(self)
        return self


class LegacySqlConnectorRealConnectionExecutorCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    sandbox_profile_ref: str
    sandbox_profile_evidence_hash: str
    preflight_evidence_hash: str
    timeout_retry_policy_hash: str
    audit_plan_hash: str
    kill_switch_policy_hash: str
    restore_evidence_hash: str
    requested_by: str
    executor_contract_requested: bool = True
    socket_materialization_requested: bool = False
    secret_materialization_requested: bool = False
    raw_data_access_requested: bool = False
    import_dry_run_requested: bool = False
    import_write_requested: bool = False
    destructive_actions_requested: bool = False

    @field_validator("tenant_id", "requested_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL real-connection executor command text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL real-connection executor command module_id must be lowercase snake_case")
        return value

    @field_validator("source_system_ref", "sandbox_profile_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL real-connection executor command references must be namespaced")
        return value

    @field_validator(
        "sandbox_profile_evidence_hash",
        "preflight_evidence_hash",
        "timeout_retry_policy_hash",
        "audit_plan_hash",
        "kill_switch_policy_hash",
        "restore_evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL real-connection executor command hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_safe_command(self) -> Self:
        _assert_executor_safe(self)
        return self


class LegacySqlConnectorRealConnectionExecutorContractEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_CONTRACT_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    continuity_domain: str = LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN
    command_ref: str = LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_COMMAND_REF
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
    preflight_evidence_hash: str
    preflight_restore_evidence_hash: str
    timeout_retry_policy_hash: str
    retry_policy_ref: str
    audit_plan_hash: str
    audit_plan_ref: str
    audit_sink_ref: str
    audit_event_schema_ref: str
    redaction_policy_ref: str
    kill_switch_policy_hash: str
    kill_switch_policy_ref: str
    tenant_kill_switch_ref: str
    global_kill_switch_ref: str
    manual_abort_ref: str
    incident_channel_ref: str
    executor_restore_evidence_hash: str
    operator_principal_ref: str
    operator_role_ref: str
    change_request_ref: str
    maintenance_window_ref: str
    approval_reference: str
    preflight_hash_valid: bool
    preflight_ready: bool
    preflight_bound: bool
    timeout_retry_policy_hash_valid: bool
    timeout_retry_policy_bound: bool
    timeout_retry_policy_ready: bool
    audit_plan_hash_valid: bool
    audit_plan_bound: bool
    audit_plan_metadata_only: bool
    audit_plan_required_event_types_present: bool
    kill_switch_policy_hash_valid: bool
    kill_switch_policy_bound: bool
    kill_switch_armed: bool
    tenant_connection_disabled: bool
    global_connection_disabled: bool
    manual_abort_requested: bool
    kill_switch_policy_ready: bool
    executor_restore_evidence_hash_valid: bool
    executor_contract_requested: bool
    executor_contract_ready: bool
    future_socket_materialization_gate_required: bool = True
    future_secret_materialization_gate_required: bool = True
    future_execution_implementation_required: bool = True
    socket_materialization_requested: bool = False
    socket_materialization_allowed: bool = False
    network_socket_opened: bool = False
    network_connection_opened: bool = False
    real_connection_opened: bool = False
    secret_materialization_requested: bool = False
    secret_material_resolved: bool = False
    raw_data_access_requested: bool = False
    raw_data_access_allowed: bool = False
    import_dry_run_requested: bool = False
    import_dry_run_allowed: bool = False
    import_write_requested: bool = False
    import_write_allowed: bool = False
    destructive_actions_requested: bool = False
    destructive_actions_allowed: bool = False
    contract_status: LegacySqlConnectorRealConnectionExecutorStatus
    blocking_reasons: tuple[str, ...]
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL real-connection executor contract text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL real-connection executor contract module_id must be lowercase snake_case")
        return value

    @field_validator(
        "source_system_ref",
        "sandbox_profile_ref",
        "retry_policy_ref",
        "audit_plan_ref",
        "audit_sink_ref",
        "audit_event_schema_ref",
        "redaction_policy_ref",
        "kill_switch_policy_ref",
        "tenant_kill_switch_ref",
        "global_kill_switch_ref",
        "manual_abort_ref",
        "incident_channel_ref",
        "operator_principal_ref",
        "operator_role_ref",
        "change_request_ref",
        "maintenance_window_ref",
        "approval_reference",
    )
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL real-connection executor contract references must be namespaced")
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
        "preflight_evidence_hash",
        "preflight_restore_evidence_hash",
        "timeout_retry_policy_hash",
        "audit_plan_hash",
        "kill_switch_policy_hash",
        "executor_restore_evidence_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL real-connection executor contract hashes must be sha256 references")
        return value

    @field_validator("blocking_reasons")
    @classmethod
    def validate_blocking_reasons(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("legacy SQL real-connection executor contract blocking reasons must be unique")
        for reason in value:
            if not reason.strip():
                raise ValueError("legacy SQL real-connection executor contract blocking reasons must not be empty")
        return value

    @model_validator(mode="after")
    def require_non_executing_contract(self) -> Self:
        if (
            self.socket_materialization_allowed
            or self.network_socket_opened
            or self.network_connection_opened
            or self.real_connection_opened
            or self.secret_material_resolved
            or self.raw_data_access_allowed
            or self.import_dry_run_allowed
            or self.import_write_allowed
            or self.destructive_actions_allowed
        ):
            raise ValueError("legacy SQL real-connection executor contract must remain non-executing")
        if (
            not self.future_socket_materialization_gate_required
            or not self.future_secret_materialization_gate_required
            or not self.future_execution_implementation_required
        ):
            raise ValueError("legacy SQL real-connection executor contract must require future execution gates")
        if self.contract_status == LegacySqlConnectorRealConnectionExecutorStatus.READY:
            required = (
                self.preflight_hash_valid,
                self.preflight_ready,
                self.preflight_bound,
                self.timeout_retry_policy_hash_valid,
                self.timeout_retry_policy_bound,
                self.timeout_retry_policy_ready,
                self.audit_plan_hash_valid,
                self.audit_plan_bound,
                self.audit_plan_metadata_only,
                self.audit_plan_required_event_types_present,
                self.kill_switch_policy_hash_valid,
                self.kill_switch_policy_bound,
                self.kill_switch_armed,
                not self.tenant_connection_disabled,
                not self.global_connection_disabled,
                not self.manual_abort_requested,
                self.kill_switch_policy_ready,
                self.executor_restore_evidence_hash_valid,
                self.executor_contract_requested,
                self.executor_contract_ready,
            )
            if not all(required) or self.blocking_reasons:
                raise ValueError("ready legacy SQL real-connection executor contract requires complete evidence")
        if self.contract_status == LegacySqlConnectorRealConnectionExecutorStatus.BLOCKED:
            if not self.blocking_reasons:
                raise ValueError("blocked legacy SQL real-connection executor contract requires blocking reasons")
            if self.executor_contract_ready:
                raise ValueError("blocked legacy SQL real-connection executor contract cannot be ready")
        _assert_executor_safe(self)
        return self


class LegacySqlConnectorRealConnectionExecutorSmokeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_SMOKE_SCHEMA_VERSION
    tenant_id: str
    queue_backend: LegacySqlMetadataWorkerQueueBackend
    continuity_domain: str = LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN
    command_ref: str = LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_COMMAND_REF
    sandbox_profile_ref: str
    sandbox_profile_evidence_hash: str
    preflight_evidence_hash: str
    timeout_retry_policy_hash: str
    audit_plan_hash: str
    kill_switch_policy_hash: str
    executor_contract_evidence_hash: str
    executor_restore_evidence_hash: str
    executor_contract_ready: bool
    preflight_required: bool
    timeout_retry_policy_required: bool
    audit_plan_required: bool
    kill_switch_policy_required: bool
    materialization_request_blocked: bool
    kill_switch_disabled_blocked: bool
    tampered_preflight_blocked: bool
    future_socket_materialization_gate_required: bool
    future_secret_materialization_gate_required: bool
    future_execution_implementation_required: bool
    socket_materialization_allowed: bool = False
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
    def require_smoke_to_remain_non_executing(self) -> Self:
        if (
            self.socket_materialization_allowed
            or self.network_socket_opened
            or self.network_connection_opened
            or self.real_connection_opened
            or self.secret_material_resolved
            or self.raw_data_access_allowed
            or self.import_dry_run_allowed
            or self.import_write_allowed
            or self.destructive_actions_allowed
        ):
            raise ValueError("legacy SQL real-connection executor smoke must remain non-executing")
        _assert_executor_safe(self)
        return self


class LegacySqlConnectorRealConnectionExecutorPolicyBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_POLICY_BUNDLE_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    continuity_domain: str = LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN
    command_ref: str = LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_POLICY_STORE_COMMAND_REF
    policy_bundle_ref: str
    sandbox_profile_ref: str
    sandbox_profile_evidence_hash: str
    preflight_evidence_hash: str
    timeout_retry_policy_hash: str
    audit_plan_hash: str
    kill_switch_policy_hash: str
    executor_contract_evidence_hash: str
    executor_restore_evidence_hash: str
    timeout_retry_policy: LegacySqlConnectorRealConnectionTimeoutRetryPolicy
    audit_plan: LegacySqlConnectorRealConnectionAuditPlan
    kill_switch_policy: LegacySqlConnectorRealConnectionKillSwitchPolicy
    executor_contract: LegacySqlConnectorRealConnectionExecutorContractEvidence
    timeout_retry_policy_hash_valid: bool
    audit_plan_hash_valid: bool
    kill_switch_policy_hash_valid: bool
    executor_contract_hash_valid: bool
    policy_chain_bound: bool
    tenant_scope_verified: bool
    restore_evidence_hash_valid: bool
    store_persistence_allowed: bool
    future_socket_materialization_gate_required: bool = True
    future_secret_materialization_gate_required: bool = True
    future_execution_implementation_required: bool = True
    socket_materialization_allowed: bool = False
    network_socket_opened: bool = False
    network_connection_opened: bool = False
    real_connection_opened: bool = False
    secret_material_resolved: bool = False
    raw_data_access_allowed: bool = False
    import_dry_run_allowed: bool = False
    import_write_allowed: bool = False
    destructive_actions_allowed: bool = False
    bundle_status: LegacySqlConnectorRealConnectionExecutorStatus
    blocking_reasons: tuple[str, ...]
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL real-connection executor policy bundle text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL real-connection executor policy bundle module_id must be lowercase snake_case")
        return value

    @field_validator("source_system_ref", "policy_bundle_ref", "sandbox_profile_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL real-connection executor policy bundle references must be namespaced")
        return value

    @field_validator(
        "sandbox_profile_evidence_hash",
        "preflight_evidence_hash",
        "timeout_retry_policy_hash",
        "audit_plan_hash",
        "kill_switch_policy_hash",
        "executor_contract_evidence_hash",
        "executor_restore_evidence_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL real-connection executor policy bundle hashes must be sha256 references")
        return value

    @field_validator("blocking_reasons")
    @classmethod
    def validate_blocking_reasons(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("legacy SQL real-connection executor policy bundle blocking reasons must be unique")
        for reason in value:
            if not reason.strip():
                raise ValueError("legacy SQL real-connection executor policy bundle blocking reasons must not be empty")
        return value

    @model_validator(mode="after")
    def require_safe_policy_bundle(self) -> Self:
        if (
            self.socket_materialization_allowed
            or self.network_socket_opened
            or self.network_connection_opened
            or self.real_connection_opened
            or self.secret_material_resolved
            or self.raw_data_access_allowed
            or self.import_dry_run_allowed
            or self.import_write_allowed
            or self.destructive_actions_allowed
        ):
            raise ValueError("legacy SQL real-connection executor policy bundle must remain non-executing")
        if (
            not self.future_socket_materialization_gate_required
            or not self.future_secret_materialization_gate_required
            or not self.future_execution_implementation_required
        ):
            raise ValueError("legacy SQL real-connection executor policy bundle must require future execution gates")
        if self.bundle_status == LegacySqlConnectorRealConnectionExecutorStatus.READY:
            required = (
                self.timeout_retry_policy_hash_valid,
                self.audit_plan_hash_valid,
                self.kill_switch_policy_hash_valid,
                self.executor_contract_hash_valid,
                self.policy_chain_bound,
                self.tenant_scope_verified,
                self.restore_evidence_hash_valid,
                self.store_persistence_allowed,
                self.executor_contract.executor_contract_ready,
            )
            if not all(required) or self.blocking_reasons:
                raise ValueError("ready legacy SQL real-connection executor policy bundle requires complete evidence")
        if self.bundle_status == LegacySqlConnectorRealConnectionExecutorStatus.BLOCKED:
            if not self.blocking_reasons:
                raise ValueError("blocked legacy SQL real-connection executor policy bundle requires blocking reasons")
            if self.store_persistence_allowed:
                raise ValueError("blocked legacy SQL real-connection executor policy bundle cannot persist")
        _assert_executor_safe(self)
        return self


class LegacySqlConnectorRealConnectionExecutorPolicyStoreSmokeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_POLICY_STORE_SMOKE_SCHEMA_VERSION
    tenant_id: str
    store_backend: LegacySqlConnectorRealConnectionPolicyStoreBackend
    continuity_domain: str = LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN
    command_ref: str = LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_POLICY_STORE_COMMAND_REF
    policy_bundle_evidence_hash: str
    executor_contract_evidence_hash: str
    preflight_evidence_hash: str
    timeout_retry_policy_hash: str
    audit_plan_hash: str
    kill_switch_policy_hash: str
    executor_restore_evidence_hash: str
    bundle_ready: bool
    persistence_roundtrip_ok: bool
    duplicate_append_idempotent: bool
    tenant_isolation_ok: bool
    restore_evidence_required: bool
    policy_store_operational: bool
    future_socket_materialization_gate_required: bool
    future_secret_materialization_gate_required: bool
    future_execution_implementation_required: bool
    socket_materialization_allowed: bool = False
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
    def require_policy_store_smoke_safe(self) -> Self:
        if (
            self.socket_materialization_allowed
            or self.network_socket_opened
            or self.network_connection_opened
            or self.real_connection_opened
            or self.secret_material_resolved
            or self.raw_data_access_allowed
            or self.import_dry_run_allowed
            or self.import_write_allowed
            or self.destructive_actions_allowed
        ):
            raise ValueError("legacy SQL real-connection executor policy store smoke must remain non-executing")
        _assert_executor_safe(self)
        return self


class LegacySqlConnectorRealConnectionExecutorPolicyStore(Protocol):
    def append(
        self,
        bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    ) -> LegacySqlConnectorRealConnectionExecutorPolicyBundle:
        raise NotImplementedError

    def get(
        self,
        *,
        tenant_id: str,
        executor_contract_evidence_hash: str,
    ) -> LegacySqlConnectorRealConnectionExecutorPolicyBundle:
        raise NotImplementedError

    def list_bundles(self, *, tenant_id: str) -> tuple[LegacySqlConnectorRealConnectionExecutorPolicyBundle, ...]:
        raise NotImplementedError


class InMemoryLegacySqlConnectorRealConnectionExecutorPolicyStore:
    def __init__(self, bundles: tuple[LegacySqlConnectorRealConnectionExecutorPolicyBundle, ...] = ()) -> None:
        self._bundles: dict[tuple[str, str], LegacySqlConnectorRealConnectionExecutorPolicyBundle] = {}
        for bundle in bundles:
            self.append(bundle)

    def append(
        self,
        bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    ) -> LegacySqlConnectorRealConnectionExecutorPolicyBundle:
        _require_valid_policy_bundle_hash(bundle)
        key = _policy_bundle_key(bundle)
        existing = self._bundles.get(key)
        if existing is not None:
            _require_same_policy_bundle_identity(existing=existing, incoming=bundle)
            return existing
        self._bundles[key] = bundle
        return bundle

    def get(
        self,
        *,
        tenant_id: str,
        executor_contract_evidence_hash: str,
    ) -> LegacySqlConnectorRealConnectionExecutorPolicyBundle:
        try:
            return self._bundles[(tenant_id, executor_contract_evidence_hash)]
        except KeyError as exc:
            raise KeyError("legacy SQL real-connection executor policy bundle not found") from exc

    def list_bundles(self, *, tenant_id: str) -> tuple[LegacySqlConnectorRealConnectionExecutorPolicyBundle, ...]:
        return tuple(
            sorted(
                (bundle for (stored_tenant_id, _), bundle in self._bundles.items() if stored_tenant_id == tenant_id),
                key=lambda item: (item.checked_at_utc, item.executor_contract_evidence_hash),
            )
        )


class JsonlLegacySqlConnectorRealConnectionExecutorPolicyStore:
    def __init__(self, *, path: Path) -> None:
        self.path = path
        self._bundles: dict[tuple[str, str], LegacySqlConnectorRealConnectionExecutorPolicyBundle] = {}
        if not path.exists():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            bundle = LegacySqlConnectorRealConnectionExecutorPolicyBundle.model_validate_json(line)
            _require_valid_policy_bundle_hash(bundle)
            key = _policy_bundle_key(bundle)
            if key in self._bundles:
                raise ValueError("duplicate legacy SQL real-connection executor policy bundle in store")
            self._bundles[key] = bundle

    def append(
        self,
        bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    ) -> LegacySqlConnectorRealConnectionExecutorPolicyBundle:
        _require_valid_policy_bundle_hash(bundle)
        key = _policy_bundle_key(bundle)
        existing = self._bundles.get(key)
        if existing is not None:
            _require_same_policy_bundle_identity(existing=existing, incoming=bundle)
            return existing
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(bundle.model_dump(mode="json"), sort_keys=True) + "\n")
        self._bundles[key] = bundle
        return bundle

    def get(
        self,
        *,
        tenant_id: str,
        executor_contract_evidence_hash: str,
    ) -> LegacySqlConnectorRealConnectionExecutorPolicyBundle:
        try:
            return self._bundles[(tenant_id, executor_contract_evidence_hash)]
        except KeyError as exc:
            raise KeyError("legacy SQL real-connection executor policy bundle not found") from exc

    def list_bundles(self, *, tenant_id: str) -> tuple[LegacySqlConnectorRealConnectionExecutorPolicyBundle, ...]:
        return tuple(
            sorted(
                (bundle for (stored_tenant_id, _), bundle in self._bundles.items() if stored_tenant_id == tenant_id),
                key=lambda item: (item.checked_at_utc, item.executor_contract_evidence_hash),
            )
        )


class PgLegacySqlConnectorRealConnectionExecutorPolicyStore:
    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    def append(
        self,
        bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    ) -> LegacySqlConnectorRealConnectionExecutorPolicyBundle:
        _require_valid_policy_bundle_hash(bundle)
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, bundle.tenant_id)
            connection.execute(
                """
                INSERT INTO collabio.legacy_sql_real_connection_executor_policy_store (
                    tenant_id,
                    module_id,
                    source_system_ref,
                    connector_kind,
                    policy_bundle_ref,
                    sandbox_profile_ref,
                    sandbox_profile_evidence_hash,
                    preflight_evidence_hash,
                    timeout_retry_policy_hash,
                    audit_plan_hash,
                    kill_switch_policy_hash,
                    executor_contract_evidence_hash,
                    executor_restore_evidence_hash,
                    timeout_retry_policy,
                    audit_plan,
                    kill_switch_policy,
                    executor_contract,
                    policy_bundle,
                    store_persistence_allowed,
                    socket_materialization_allowed,
                    network_socket_opened,
                    network_connection_opened,
                    real_connection_opened,
                    secret_material_resolved,
                    raw_data_access_allowed,
                    import_dry_run_allowed,
                    import_write_allowed,
                    destructive_actions_allowed,
                    checked_by,
                    checked_at_utc,
                    evidence_hash,
                    schema_version
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s
                )
                ON CONFLICT (tenant_id, executor_contract_evidence_hash) DO NOTHING
                """,
                self._bundle_values(bundle),
            )
            connection.commit()
        existing = self.get(
            tenant_id=bundle.tenant_id,
            executor_contract_evidence_hash=bundle.executor_contract_evidence_hash,
        )
        _require_same_policy_bundle_identity(existing=existing, incoming=bundle)
        return existing

    def get(
        self,
        *,
        tenant_id: str,
        executor_contract_evidence_hash: str,
    ) -> LegacySqlConnectorRealConnectionExecutorPolicyBundle:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            row = connection.execute(
                """
                SELECT policy_bundle
                FROM collabio.legacy_sql_real_connection_executor_policy_store
                WHERE tenant_id = %s
                  AND executor_contract_evidence_hash = %s
                """,
                (tenant_id, executor_contract_evidence_hash),
            ).fetchone()
        if row is None:
            raise KeyError("legacy SQL real-connection executor policy bundle not found")
        return self._bundle_from_row(row)

    def list_bundles(self, *, tenant_id: str) -> tuple[LegacySqlConnectorRealConnectionExecutorPolicyBundle, ...]:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            rows = connection.execute(
                """
                SELECT policy_bundle
                FROM collabio.legacy_sql_real_connection_executor_policy_store
                WHERE tenant_id = %s
                ORDER BY checked_at_utc, executor_contract_evidence_hash
                """,
                (tenant_id,),
            ).fetchall()
        return tuple(self._bundle_from_row(row) for row in rows)

    def _bundle_values(self, bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle) -> tuple[object, ...]:
        return (
            bundle.tenant_id,
            bundle.module_id,
            bundle.source_system_ref,
            bundle.connector_kind.value,
            bundle.policy_bundle_ref,
            bundle.sandbox_profile_ref,
            bundle.sandbox_profile_evidence_hash,
            bundle.preflight_evidence_hash,
            bundle.timeout_retry_policy_hash,
            bundle.audit_plan_hash,
            bundle.kill_switch_policy_hash,
            bundle.executor_contract_evidence_hash,
            bundle.executor_restore_evidence_hash,
            Jsonb(bundle.timeout_retry_policy.model_dump(mode="json")),
            Jsonb(bundle.audit_plan.model_dump(mode="json")),
            Jsonb(bundle.kill_switch_policy.model_dump(mode="json")),
            Jsonb(bundle.executor_contract.model_dump(mode="json")),
            Jsonb(bundle.model_dump(mode="json")),
            bundle.store_persistence_allowed,
            bundle.socket_materialization_allowed,
            bundle.network_socket_opened,
            bundle.network_connection_opened,
            bundle.real_connection_opened,
            bundle.secret_material_resolved,
            bundle.raw_data_access_allowed,
            bundle.import_dry_run_allowed,
            bundle.import_write_allowed,
            bundle.destructive_actions_allowed,
            bundle.checked_by,
            bundle.checked_at_utc,
            bundle.evidence_hash,
            bundle.schema_version,
        )

    def _bundle_from_row(self, row: tuple[Any, ...]) -> LegacySqlConnectorRealConnectionExecutorPolicyBundle:
        raw = row[0]
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        bundle = LegacySqlConnectorRealConnectionExecutorPolicyBundle.model_validate(parsed)
        _require_valid_policy_bundle_hash(bundle)
        return bundle

    def _set_tenant(self, connection: psycopg.Connection[Any], tenant_id: str) -> None:
        connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))


@dataclass(frozen=True)
class LegacySqlConnectorRealConnectionExecutorPolicyStoreSmokeInput:
    preflight: LegacySqlConnectorConnectionPreflightEvidence
    timeout_retry_policy: LegacySqlConnectorRealConnectionTimeoutRetryPolicy
    audit_plan: LegacySqlConnectorRealConnectionAuditPlan
    kill_switch_policy: LegacySqlConnectorRealConnectionKillSwitchPolicy
    executor_contract: LegacySqlConnectorRealConnectionExecutorContractEvidence


def build_legacy_sql_connector_real_connection_timeout_retry_policy(
    *,
    preflight: LegacySqlConnectorConnectionPreflightEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    retry_policy_ref: str = "retry-policy:legacy-sql-real-connection-default",
    connect_timeout_seconds: int = 5,
    handshake_timeout_seconds: int = 5,
    statement_timeout_seconds: int = 30,
    max_attempts: int = 1,
    retry_backoff_seconds: int = 0,
    total_budget_seconds: int = 45,
) -> LegacySqlConnectorRealConnectionTimeoutRetryPolicy:
    checked_at = checked_at_utc or datetime.now(UTC)
    draft = LegacySqlConnectorRealConnectionTimeoutRetryPolicy(
        tenant_id=preflight.tenant_id,
        module_id=preflight.module_id,
        source_system_ref=preflight.source_system_ref,
        connector_kind=preflight.connector_kind,
        sandbox_profile_ref=preflight.sandbox_profile_ref,
        sandbox_profile_evidence_hash=preflight.sandbox_profile_evidence_hash,
        preflight_evidence_hash=preflight.evidence_hash,
        retry_policy_ref=retry_policy_ref,
        connect_timeout_seconds=connect_timeout_seconds,
        handshake_timeout_seconds=handshake_timeout_seconds,
        statement_timeout_seconds=statement_timeout_seconds,
        max_attempts=max_attempts,
        retry_backoff_seconds=retry_backoff_seconds,
        total_budget_seconds=total_budget_seconds,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_real_connection_timeout_retry_policy_hash(draft)}
    )


def build_legacy_sql_connector_real_connection_audit_plan(
    *,
    preflight: LegacySqlConnectorConnectionPreflightEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    audit_plan_ref: str = "audit-plan:legacy-sql-real-connection-metadata-only",
    audit_sink_ref: str = "audit-sink:append-only-metadata-events",
    audit_event_schema_ref: str = "audit-event-schema:legacy-sql-connection-attempt",
    redaction_policy_ref: str = "redaction-policy:legacy-sql-connection-attempt",
) -> LegacySqlConnectorRealConnectionAuditPlan:
    checked_at = checked_at_utc or datetime.now(UTC)
    draft = LegacySqlConnectorRealConnectionAuditPlan(
        tenant_id=preflight.tenant_id,
        module_id=preflight.module_id,
        source_system_ref=preflight.source_system_ref,
        connector_kind=preflight.connector_kind,
        sandbox_profile_ref=preflight.sandbox_profile_ref,
        sandbox_profile_evidence_hash=preflight.sandbox_profile_evidence_hash,
        preflight_evidence_hash=preflight.evidence_hash,
        audit_plan_ref=audit_plan_ref,
        audit_sink_ref=audit_sink_ref,
        audit_event_schema_ref=audit_event_schema_ref,
        redaction_policy_ref=redaction_policy_ref,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_connector_real_connection_audit_plan_hash(draft)})


def build_legacy_sql_connector_real_connection_kill_switch_policy(
    *,
    preflight: LegacySqlConnectorConnectionPreflightEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    kill_switch_armed: bool = True,
    tenant_connection_disabled: bool = False,
    global_connection_disabled: bool = False,
    manual_abort_requested: bool = False,
) -> LegacySqlConnectorRealConnectionKillSwitchPolicy:
    checked_at = checked_at_utc or datetime.now(UTC)
    draft = LegacySqlConnectorRealConnectionKillSwitchPolicy(
        tenant_id=preflight.tenant_id,
        module_id=preflight.module_id,
        source_system_ref=preflight.source_system_ref,
        connector_kind=preflight.connector_kind,
        sandbox_profile_ref=preflight.sandbox_profile_ref,
        sandbox_profile_evidence_hash=preflight.sandbox_profile_evidence_hash,
        preflight_evidence_hash=preflight.evidence_hash,
        kill_switch_armed=kill_switch_armed,
        tenant_connection_disabled=tenant_connection_disabled,
        global_connection_disabled=global_connection_disabled,
        manual_abort_requested=manual_abort_requested,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_real_connection_kill_switch_policy_hash(draft)}
    )


def build_legacy_sql_connector_real_connection_executor_command(
    *,
    preflight: LegacySqlConnectorConnectionPreflightEvidence,
    timeout_retry_policy: LegacySqlConnectorRealConnectionTimeoutRetryPolicy,
    audit_plan: LegacySqlConnectorRealConnectionAuditPlan,
    kill_switch_policy: LegacySqlConnectorRealConnectionKillSwitchPolicy,
    restore_evidence_hash: str,
    requested_by: str,
    executor_contract_requested: bool = True,
    socket_materialization_requested: bool = False,
    secret_materialization_requested: bool = False,
    raw_data_access_requested: bool = False,
    import_dry_run_requested: bool = False,
    import_write_requested: bool = False,
    destructive_actions_requested: bool = False,
) -> LegacySqlConnectorRealConnectionExecutorCommand:
    return LegacySqlConnectorRealConnectionExecutorCommand(
        tenant_id=preflight.tenant_id,
        module_id=preflight.module_id,
        source_system_ref=preflight.source_system_ref,
        connector_kind=preflight.connector_kind,
        sandbox_profile_ref=preflight.sandbox_profile_ref,
        sandbox_profile_evidence_hash=preflight.sandbox_profile_evidence_hash,
        preflight_evidence_hash=preflight.evidence_hash,
        timeout_retry_policy_hash=timeout_retry_policy.evidence_hash,
        audit_plan_hash=audit_plan.evidence_hash,
        kill_switch_policy_hash=kill_switch_policy.evidence_hash,
        restore_evidence_hash=restore_evidence_hash,
        requested_by=requested_by,
        executor_contract_requested=executor_contract_requested,
        socket_materialization_requested=socket_materialization_requested,
        secret_materialization_requested=secret_materialization_requested,
        raw_data_access_requested=raw_data_access_requested,
        import_dry_run_requested=import_dry_run_requested,
        import_write_requested=import_write_requested,
        destructive_actions_requested=destructive_actions_requested,
    )


def build_legacy_sql_connector_real_connection_executor_contract(
    *,
    command: LegacySqlConnectorRealConnectionExecutorCommand,
    preflight: LegacySqlConnectorConnectionPreflightEvidence,
    timeout_retry_policy: LegacySqlConnectorRealConnectionTimeoutRetryPolicy,
    audit_plan: LegacySqlConnectorRealConnectionAuditPlan,
    kill_switch_policy: LegacySqlConnectorRealConnectionKillSwitchPolicy,
    checked_by: str,
    checked_at_utc: datetime | None = None,
) -> LegacySqlConnectorRealConnectionExecutorContractEvidence:
    checked_at = checked_at_utc or datetime.now(UTC)
    preflight_hash_valid = (
        build_legacy_sql_connector_connection_preflight_hash(preflight)
        == preflight.evidence_hash
        == command.preflight_evidence_hash
    )
    preflight_ready = (
        preflight.gate_status == LegacySqlConnectorConnectionPreflightStatus.READY
        and preflight.connection_attempt_preflight_ready
        and preflight.future_real_connection_executor_required
    )
    preflight_bound = _preflight_bound(command=command, preflight=preflight)
    timeout_retry_policy_hash_valid = (
        build_legacy_sql_connector_real_connection_timeout_retry_policy_hash(timeout_retry_policy)
        == timeout_retry_policy.evidence_hash
        == command.timeout_retry_policy_hash
    )
    timeout_retry_policy_bound = _policy_bound(preflight=preflight, policy=timeout_retry_policy)
    timeout_retry_policy_ready = timeout_retry_policy_hash_valid and timeout_retry_policy_bound
    audit_plan_hash_valid = (
        build_legacy_sql_connector_real_connection_audit_plan_hash(audit_plan)
        == audit_plan.evidence_hash
        == command.audit_plan_hash
    )
    audit_plan_bound = _policy_bound(preflight=preflight, policy=audit_plan)
    audit_plan_required_event_types_present = set(REQUIRED_AUDIT_EVENT_TYPES).issubset(
        set(audit_plan.required_event_types)
    )
    audit_plan_metadata_only = (
        audit_plan.metadata_only_events
        and not audit_plan.prompt_or_output_body_logging_allowed
        and not audit_plan.raw_payload_logging_allowed
        and not audit_plan.secret_material_logging_allowed
    )
    kill_switch_policy_hash_valid = (
        build_legacy_sql_connector_real_connection_kill_switch_policy_hash(kill_switch_policy)
        == kill_switch_policy.evidence_hash
        == command.kill_switch_policy_hash
    )
    kill_switch_policy_bound = _policy_bound(preflight=preflight, policy=kill_switch_policy)
    kill_switch_policy_ready = (
        kill_switch_policy_hash_valid
        and kill_switch_policy_bound
        and kill_switch_policy.kill_switch_armed
        and not kill_switch_policy.tenant_connection_disabled
        and not kill_switch_policy.global_connection_disabled
        and not kill_switch_policy.manual_abort_requested
        and not kill_switch_policy.break_glass_allowed
    )
    executor_restore_evidence_hash_valid = bool(re.fullmatch(SHA256_REF_PATTERN, command.restore_evidence_hash))
    blocking_reasons = _executor_blocking_reasons(
        command=command,
        preflight_hash_valid=preflight_hash_valid,
        preflight_ready=preflight_ready,
        preflight_bound=preflight_bound,
        timeout_retry_policy_hash_valid=timeout_retry_policy_hash_valid,
        timeout_retry_policy_bound=timeout_retry_policy_bound,
        audit_plan_hash_valid=audit_plan_hash_valid,
        audit_plan_bound=audit_plan_bound,
        audit_plan_metadata_only=audit_plan_metadata_only,
        audit_plan_required_event_types_present=audit_plan_required_event_types_present,
        kill_switch_policy_hash_valid=kill_switch_policy_hash_valid,
        kill_switch_policy_bound=kill_switch_policy_bound,
        kill_switch_policy=kill_switch_policy,
        executor_restore_evidence_hash_valid=executor_restore_evidence_hash_valid,
    )
    ready = not blocking_reasons
    draft = LegacySqlConnectorRealConnectionExecutorContractEvidence(
        tenant_id=preflight.tenant_id,
        module_id=preflight.module_id,
        source_system_ref=preflight.source_system_ref,
        connector_kind=preflight.connector_kind,
        sandbox_profile_ref=preflight.sandbox_profile_ref,
        sandbox_profile_evidence_hash=preflight.sandbox_profile_evidence_hash,
        activation_evidence_hash=preflight.activation_evidence_hash,
        queue_job_evidence_hash=preflight.queue_job_evidence_hash,
        schedule_evidence_hash=preflight.schedule_evidence_hash,
        release_gate_evidence_hash=preflight.release_gate_evidence_hash,
        enablement_gate_evidence_hash=preflight.enablement_gate_evidence_hash,
        provider_attestation_adapter_evidence_hash=preflight.provider_attestation_adapter_evidence_hash,
        provider_attestation_hash=preflight.provider_attestation_hash,
        operator_context_evidence_hash=preflight.operator_context_evidence_hash,
        preflight_evidence_hash=preflight.evidence_hash,
        preflight_restore_evidence_hash=preflight.restore_evidence_hash,
        timeout_retry_policy_hash=timeout_retry_policy.evidence_hash,
        retry_policy_ref=timeout_retry_policy.retry_policy_ref,
        audit_plan_hash=audit_plan.evidence_hash,
        audit_plan_ref=audit_plan.audit_plan_ref,
        audit_sink_ref=audit_plan.audit_sink_ref,
        audit_event_schema_ref=audit_plan.audit_event_schema_ref,
        redaction_policy_ref=audit_plan.redaction_policy_ref,
        kill_switch_policy_hash=kill_switch_policy.evidence_hash,
        kill_switch_policy_ref=kill_switch_policy.kill_switch_policy_ref,
        tenant_kill_switch_ref=kill_switch_policy.tenant_kill_switch_ref,
        global_kill_switch_ref=kill_switch_policy.global_kill_switch_ref,
        manual_abort_ref=kill_switch_policy.manual_abort_ref,
        incident_channel_ref=kill_switch_policy.incident_channel_ref,
        executor_restore_evidence_hash=command.restore_evidence_hash,
        operator_principal_ref=preflight.operator_principal_ref,
        operator_role_ref=preflight.operator_role_ref,
        change_request_ref=preflight.change_request_ref,
        maintenance_window_ref=preflight.maintenance_window_ref,
        approval_reference=preflight.approval_reference,
        preflight_hash_valid=preflight_hash_valid,
        preflight_ready=preflight_ready,
        preflight_bound=preflight_bound,
        timeout_retry_policy_hash_valid=timeout_retry_policy_hash_valid,
        timeout_retry_policy_bound=timeout_retry_policy_bound,
        timeout_retry_policy_ready=timeout_retry_policy_ready,
        audit_plan_hash_valid=audit_plan_hash_valid,
        audit_plan_bound=audit_plan_bound,
        audit_plan_metadata_only=audit_plan_metadata_only,
        audit_plan_required_event_types_present=audit_plan_required_event_types_present,
        kill_switch_policy_hash_valid=kill_switch_policy_hash_valid,
        kill_switch_policy_bound=kill_switch_policy_bound,
        kill_switch_armed=kill_switch_policy.kill_switch_armed,
        tenant_connection_disabled=kill_switch_policy.tenant_connection_disabled,
        global_connection_disabled=kill_switch_policy.global_connection_disabled,
        manual_abort_requested=kill_switch_policy.manual_abort_requested,
        kill_switch_policy_ready=kill_switch_policy_ready,
        executor_restore_evidence_hash_valid=executor_restore_evidence_hash_valid,
        executor_contract_requested=command.executor_contract_requested,
        executor_contract_ready=ready,
        socket_materialization_requested=command.socket_materialization_requested,
        secret_materialization_requested=command.secret_materialization_requested,
        raw_data_access_requested=command.raw_data_access_requested,
        import_dry_run_requested=command.import_dry_run_requested,
        import_write_requested=command.import_write_requested,
        destructive_actions_requested=command.destructive_actions_requested,
        contract_status=(
            LegacySqlConnectorRealConnectionExecutorStatus.READY
            if ready
            else LegacySqlConnectorRealConnectionExecutorStatus.BLOCKED
        ),
        blocking_reasons=blocking_reasons,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_real_connection_executor_contract_hash(draft)}
    )


def build_legacy_sql_connector_real_connection_executor_policy_bundle(
    *,
    timeout_retry_policy: LegacySqlConnectorRealConnectionTimeoutRetryPolicy,
    audit_plan: LegacySqlConnectorRealConnectionAuditPlan,
    kill_switch_policy: LegacySqlConnectorRealConnectionKillSwitchPolicy,
    executor_contract: LegacySqlConnectorRealConnectionExecutorContractEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
) -> LegacySqlConnectorRealConnectionExecutorPolicyBundle:
    checked_at = checked_at_utc or datetime.now(UTC)
    timeout_retry_policy_hash_valid = (
        build_legacy_sql_connector_real_connection_timeout_retry_policy_hash(timeout_retry_policy)
        == timeout_retry_policy.evidence_hash
        == executor_contract.timeout_retry_policy_hash
    )
    audit_plan_hash_valid = (
        build_legacy_sql_connector_real_connection_audit_plan_hash(audit_plan)
        == audit_plan.evidence_hash
        == executor_contract.audit_plan_hash
    )
    kill_switch_policy_hash_valid = (
        build_legacy_sql_connector_real_connection_kill_switch_policy_hash(kill_switch_policy)
        == kill_switch_policy.evidence_hash
        == executor_contract.kill_switch_policy_hash
    )
    executor_contract_hash_valid = (
        build_legacy_sql_connector_real_connection_executor_contract_hash(executor_contract)
        == executor_contract.evidence_hash
    )
    policy_chain_bound = _policy_chain_bound_to_contract(
        timeout_retry_policy=timeout_retry_policy,
        audit_plan=audit_plan,
        kill_switch_policy=kill_switch_policy,
        executor_contract=executor_contract,
    )
    tenant_scope_verified = _policy_bundle_tenant_scope_verified(
        timeout_retry_policy=timeout_retry_policy,
        audit_plan=audit_plan,
        kill_switch_policy=kill_switch_policy,
        executor_contract=executor_contract,
    )
    restore_evidence_hash_valid = bool(
        re.fullmatch(SHA256_REF_PATTERN, executor_contract.executor_restore_evidence_hash)
    )
    blocking_reasons = _policy_bundle_blocking_reasons(
        timeout_retry_policy_hash_valid=timeout_retry_policy_hash_valid,
        audit_plan_hash_valid=audit_plan_hash_valid,
        kill_switch_policy_hash_valid=kill_switch_policy_hash_valid,
        executor_contract_hash_valid=executor_contract_hash_valid,
        policy_chain_bound=policy_chain_bound,
        tenant_scope_verified=tenant_scope_verified,
        restore_evidence_hash_valid=restore_evidence_hash_valid,
        executor_contract=executor_contract,
    )
    ready = not blocking_reasons
    draft = LegacySqlConnectorRealConnectionExecutorPolicyBundle(
        tenant_id=executor_contract.tenant_id,
        module_id=executor_contract.module_id,
        source_system_ref=executor_contract.source_system_ref,
        connector_kind=executor_contract.connector_kind,
        policy_bundle_ref=legacy_sql_connector_real_connection_executor_policy_bundle_ref(executor_contract),
        sandbox_profile_ref=executor_contract.sandbox_profile_ref,
        sandbox_profile_evidence_hash=executor_contract.sandbox_profile_evidence_hash,
        preflight_evidence_hash=executor_contract.preflight_evidence_hash,
        timeout_retry_policy_hash=timeout_retry_policy.evidence_hash,
        audit_plan_hash=audit_plan.evidence_hash,
        kill_switch_policy_hash=kill_switch_policy.evidence_hash,
        executor_contract_evidence_hash=executor_contract.evidence_hash,
        executor_restore_evidence_hash=executor_contract.executor_restore_evidence_hash,
        timeout_retry_policy=timeout_retry_policy,
        audit_plan=audit_plan,
        kill_switch_policy=kill_switch_policy,
        executor_contract=executor_contract,
        timeout_retry_policy_hash_valid=timeout_retry_policy_hash_valid,
        audit_plan_hash_valid=audit_plan_hash_valid,
        kill_switch_policy_hash_valid=kill_switch_policy_hash_valid,
        executor_contract_hash_valid=executor_contract_hash_valid,
        policy_chain_bound=policy_chain_bound,
        tenant_scope_verified=tenant_scope_verified,
        restore_evidence_hash_valid=restore_evidence_hash_valid,
        store_persistence_allowed=ready,
        bundle_status=(
            LegacySqlConnectorRealConnectionExecutorStatus.READY
            if ready
            else LegacySqlConnectorRealConnectionExecutorStatus.BLOCKED
        ),
        blocking_reasons=blocking_reasons,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_real_connection_executor_policy_bundle_hash(draft)}
    )


def build_legacy_sql_connector_real_connection_timeout_retry_policy_hash(
    policy: LegacySqlConnectorRealConnectionTimeoutRetryPolicy,
) -> str:
    return stable_hash(canonical_json(policy.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_real_connection_audit_plan_hash(
    plan: LegacySqlConnectorRealConnectionAuditPlan,
) -> str:
    return stable_hash(canonical_json(plan.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_real_connection_kill_switch_policy_hash(
    policy: LegacySqlConnectorRealConnectionKillSwitchPolicy,
) -> str:
    return stable_hash(canonical_json(policy.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_real_connection_executor_contract_hash(
    evidence: LegacySqlConnectorRealConnectionExecutorContractEvidence,
) -> str:
    return stable_hash(canonical_json(evidence.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_real_connection_executor_policy_bundle_hash(
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
) -> str:
    return stable_hash(canonical_json(bundle.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_real_connection_executor_smoke_report_hash(
    report: LegacySqlConnectorRealConnectionExecutorSmokeReport,
) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_real_connection_executor_policy_store_smoke_report_hash(
    report: LegacySqlConnectorRealConnectionExecutorPolicyStoreSmokeReport,
) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def legacy_sql_connector_real_connection_executor_policy_bundle_ref(
    executor_contract: LegacySqlConnectorRealConnectionExecutorContractEvidence,
) -> str:
    return (
        f"{LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_POLICY_BUNDLE_REF_PREFIX}:"
        f"{executor_contract.evidence_hash.removeprefix('sha256:')}"
    )


def run_legacy_sql_connector_real_connection_executor_smoke_from_env(
    environ: Mapping[str, str] | None = None,
) -> LegacySqlConnectorRealConnectionExecutorSmokeReport:
    env = os.environ if environ is None else environ
    checked_by = env.get(
        "SUITE_LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_CHECKED_BY",
        "legacy-sql-connector-real-connection-executor-smoke",
    )
    checked_at = datetime.now(UTC)
    queue_restore_hash = env.get("SUITE_LEGACY_SQL_METADATA_WORKER_QUEUE_RESTORE_HASH", "sha256:" + "4" * 64)
    enablement_restore_hash = env.get(
        "SUITE_LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_ENABLEMENT_RESTORE_HASH",
        "sha256:" + "5" * 64,
    )
    preflight_restore_hash = env.get(
        "SUITE_LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_PREFLIGHT_RESTORE_HASH",
        "sha256:" + "6" * 64,
    )
    executor_restore_hash = env.get(
        "SUITE_LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_RESTORE_HASH",
        "sha256:" + "7" * 64,
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
            "SUITE_LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_HUMAN_CONFIRMATION_REF",
            "human-confirmation:legacy-sql-real-connection-executor-smoke",
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
    timeout_retry_policy = build_legacy_sql_connector_real_connection_timeout_retry_policy(
        preflight=preflight_gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=11),
    )
    audit_plan = build_legacy_sql_connector_real_connection_audit_plan(
        preflight=preflight_gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=12),
    )
    kill_switch_policy = build_legacy_sql_connector_real_connection_kill_switch_policy(
        preflight=preflight_gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=13),
    )
    executor_command = build_legacy_sql_connector_real_connection_executor_command(
        preflight=preflight_gate,
        timeout_retry_policy=timeout_retry_policy,
        audit_plan=audit_plan,
        kill_switch_policy=kill_switch_policy,
        restore_evidence_hash=executor_restore_hash,
        requested_by=checked_by,
    )
    executor_contract = build_legacy_sql_connector_real_connection_executor_contract(
        command=executor_command,
        preflight=preflight_gate,
        timeout_retry_policy=timeout_retry_policy,
        audit_plan=audit_plan,
        kill_switch_policy=kill_switch_policy,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=14),
    )
    materialization_request_blocked = _materialization_request_blocked(
        command=executor_command,
        preflight=preflight_gate,
        timeout_retry_policy=timeout_retry_policy,
        audit_plan=audit_plan,
        kill_switch_policy=kill_switch_policy,
        checked_by=checked_by,
        checked_at=checked_at + timedelta(seconds=15),
    )
    kill_switch_disabled_blocked = _kill_switch_disabled_blocked(
        command=executor_command,
        preflight=preflight_gate,
        timeout_retry_policy=timeout_retry_policy,
        audit_plan=audit_plan,
        kill_switch_policy=kill_switch_policy,
        checked_by=checked_by,
        checked_at=checked_at + timedelta(seconds=16),
    )
    tampered_preflight_blocked = _tampered_preflight_blocked(
        command=executor_command,
        preflight=preflight_gate,
        timeout_retry_policy=timeout_retry_policy,
        audit_plan=audit_plan,
        kill_switch_policy=kill_switch_policy,
        checked_by=checked_by,
        checked_at=checked_at + timedelta(seconds=17),
    )
    executor_contract_ready = (
        executor_contract.contract_status == LegacySqlConnectorRealConnectionExecutorStatus.READY
        and executor_contract.executor_contract_ready
        and materialization_request_blocked
        and kill_switch_disabled_blocked
        and tampered_preflight_blocked
        and not executor_contract.socket_materialization_allowed
        and not executor_contract.network_socket_opened
        and not executor_contract.secret_material_resolved
        and not executor_contract.real_connection_opened
        and not executor_contract.raw_data_access_allowed
        and not executor_contract.import_dry_run_allowed
        and not executor_contract.import_write_allowed
    )
    draft = LegacySqlConnectorRealConnectionExecutorSmokeReport(
        tenant_id=preflight_gate.tenant_id,
        queue_backend=queue_backend,
        sandbox_profile_ref=preflight_gate.sandbox_profile_ref,
        sandbox_profile_evidence_hash=preflight_gate.sandbox_profile_evidence_hash,
        preflight_evidence_hash=preflight_gate.evidence_hash,
        timeout_retry_policy_hash=timeout_retry_policy.evidence_hash,
        audit_plan_hash=audit_plan.evidence_hash,
        kill_switch_policy_hash=kill_switch_policy.evidence_hash,
        executor_contract_evidence_hash=executor_contract.evidence_hash,
        executor_restore_evidence_hash=executor_restore_hash,
        executor_contract_ready=executor_contract_ready,
        preflight_required=executor_contract.preflight_ready and executor_contract.preflight_bound,
        timeout_retry_policy_required=executor_contract.timeout_retry_policy_ready,
        audit_plan_required=executor_contract.audit_plan_metadata_only
        and executor_contract.audit_plan_required_event_types_present,
        kill_switch_policy_required=executor_contract.kill_switch_policy_ready,
        materialization_request_blocked=materialization_request_blocked,
        kill_switch_disabled_blocked=kill_switch_disabled_blocked,
        tampered_preflight_blocked=tampered_preflight_blocked,
        future_socket_materialization_gate_required=executor_contract.future_socket_materialization_gate_required,
        future_secret_materialization_gate_required=executor_contract.future_secret_materialization_gate_required,
        future_execution_implementation_required=executor_contract.future_execution_implementation_required,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    _assert_executor_safe(draft)
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_real_connection_executor_smoke_report_hash(draft)}
    )


def build_default_legacy_sql_connector_real_connection_executor_policy_store(
    *,
    environ: Mapping[str, str] | None = None,
    data_dir: Path | None = None,
) -> LegacySqlConnectorRealConnectionExecutorPolicyStore:
    env = os.environ if environ is None else environ
    backend = env.get(
        "SUITE_LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_POLICY_STORE_BACKEND",
        LegacySqlConnectorRealConnectionPolicyStoreBackend.JSONL.value,
    ).strip()
    if backend in {"memory", "in_memory"}:
        return InMemoryLegacySqlConnectorRealConnectionExecutorPolicyStore()
    if backend == LegacySqlConnectorRealConnectionPolicyStoreBackend.JSONL.value:
        path_value = env.get("SUITE_LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_POLICY_STORE_PATH")
        path = (
            Path(path_value)
            if path_value
            else (data_dir or suite_data_dir()) / "legacy_sql_real_connection_executor_policy_store.jsonl"
        )
        return JsonlLegacySqlConnectorRealConnectionExecutorPolicyStore(path=path)
    if backend == LegacySqlConnectorRealConnectionPolicyStoreBackend.POSTGRES.value:
        database_resource = env.get("SUITE_LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_POLICY_STORE_DSN") or env.get(
            "SUITE_DATABASE_DSN"
        )
        if database_resource is None:
            raise ValueError("postgres legacy SQL real-connection executor policy store requires a database resource")
        return PgLegacySqlConnectorRealConnectionExecutorPolicyStore(database_dsn=database_resource)
    raise ValueError(f"unsupported legacy SQL real-connection executor policy store backend: {backend}")


def run_legacy_sql_connector_real_connection_executor_policy_store_smoke_from_env(
    environ: Mapping[str, str] | None = None,
) -> LegacySqlConnectorRealConnectionExecutorPolicyStoreSmokeReport:
    env = os.environ if environ is None else environ
    checked_by = env.get(
        "SUITE_LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_POLICY_STORE_CHECKED_BY",
        "legacy-sql-connector-real-connection-executor-policy-store-smoke",
    )
    checked_at = datetime.now(UTC)
    store_backend = LegacySqlConnectorRealConnectionPolicyStoreBackend(
        env.get(
            "SUITE_LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_POLICY_STORE_BACKEND",
            LegacySqlConnectorRealConnectionPolicyStoreBackend.JSONL.value,
        )
    )
    smoke_input = _policy_store_smoke_input_from_env(env=env, checked_by=checked_by, checked_at=checked_at)
    bundle = build_legacy_sql_connector_real_connection_executor_policy_bundle(
        timeout_retry_policy=smoke_input.timeout_retry_policy,
        audit_plan=smoke_input.audit_plan,
        kill_switch_policy=smoke_input.kill_switch_policy,
        executor_contract=smoke_input.executor_contract,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=18),
    )
    store = build_default_legacy_sql_connector_real_connection_executor_policy_store(environ=env)
    stored = store.append(bundle)
    duplicate = store.append(bundle)
    fetched = store.get(
        tenant_id=bundle.tenant_id,
        executor_contract_evidence_hash=bundle.executor_contract_evidence_hash,
    )
    tenant_isolation_ok = _policy_store_tenant_isolation_ok(store=store, bundle=bundle)
    persistence_roundtrip_ok = (
        stored.evidence_hash == bundle.evidence_hash
        and fetched.evidence_hash == bundle.evidence_hash
        and fetched.executor_contract_evidence_hash == smoke_input.executor_contract.evidence_hash
        and len(store.list_bundles(tenant_id=bundle.tenant_id)) == 1
    )
    duplicate_append_idempotent = duplicate.evidence_hash == bundle.evidence_hash
    policy_store_operational = (
        bundle.store_persistence_allowed
        and persistence_roundtrip_ok
        and duplicate_append_idempotent
        and tenant_isolation_ok
        and not bundle.network_socket_opened
        and not bundle.secret_material_resolved
        and not bundle.real_connection_opened
    )
    draft = LegacySqlConnectorRealConnectionExecutorPolicyStoreSmokeReport(
        tenant_id=bundle.tenant_id,
        store_backend=store_backend,
        policy_bundle_evidence_hash=bundle.evidence_hash,
        executor_contract_evidence_hash=bundle.executor_contract_evidence_hash,
        preflight_evidence_hash=bundle.preflight_evidence_hash,
        timeout_retry_policy_hash=bundle.timeout_retry_policy_hash,
        audit_plan_hash=bundle.audit_plan_hash,
        kill_switch_policy_hash=bundle.kill_switch_policy_hash,
        executor_restore_evidence_hash=bundle.executor_restore_evidence_hash,
        bundle_ready=bundle.store_persistence_allowed,
        persistence_roundtrip_ok=persistence_roundtrip_ok,
        duplicate_append_idempotent=duplicate_append_idempotent,
        tenant_isolation_ok=tenant_isolation_ok,
        restore_evidence_required=bundle.restore_evidence_hash_valid,
        policy_store_operational=policy_store_operational,
        future_socket_materialization_gate_required=bundle.future_socket_materialization_gate_required,
        future_secret_materialization_gate_required=bundle.future_secret_materialization_gate_required,
        future_execution_implementation_required=bundle.future_execution_implementation_required,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    _assert_executor_safe(draft)
    return draft.model_copy(
        update={
            "evidence_hash": build_legacy_sql_connector_real_connection_executor_policy_store_smoke_report_hash(draft)
        }
    )


def exit_code_for_report(
    report: LegacySqlConnectorRealConnectionExecutorSmokeReport
    | LegacySqlConnectorRealConnectionExecutorPolicyStoreSmokeReport,
) -> int:
    if isinstance(report, LegacySqlConnectorRealConnectionExecutorPolicyStoreSmokeReport):
        return 0 if report.policy_store_operational else 1
    return 0 if report.executor_contract_ready else 1


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Legacy SQL real-connection executor contract smoke.")
    parser.add_argument("--once", action="store_true", help="Run one non-executing executor contract smoke and exit.")
    parser.add_argument(
        "--policy-store-once",
        action="store_true",
        help="Run one non-executing executor policy store smoke and exit.",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the executor contract report.")
    args = parser.parse_args(argv)
    del args.once

    report = (
        run_legacy_sql_connector_real_connection_executor_policy_store_smoke_from_env()
        if args.policy_store_once
        else run_legacy_sql_connector_real_connection_executor_smoke_from_env()
    )
    print(json.dumps(report.model_dump(mode="json"), indent=2 if args.pretty else None, sort_keys=True))
    raise SystemExit(exit_code_for_report(report))


def _preflight_bound(
    *,
    command: LegacySqlConnectorRealConnectionExecutorCommand,
    preflight: LegacySqlConnectorConnectionPreflightEvidence,
) -> bool:
    return (
        command.tenant_id == preflight.tenant_id
        and command.module_id == preflight.module_id
        and command.source_system_ref == preflight.source_system_ref
        and command.connector_kind == preflight.connector_kind
        and command.sandbox_profile_ref == preflight.sandbox_profile_ref
        and command.sandbox_profile_evidence_hash == preflight.sandbox_profile_evidence_hash
        and not preflight.network_socket_opened
        and not preflight.network_connection_opened
        and not preflight.real_connection_opened
        and not preflight.secret_material_resolved
        and not preflight.raw_data_access_allowed
        and not preflight.import_dry_run_allowed
        and not preflight.import_write_allowed
        and not preflight.destructive_actions_allowed
    )


def _policy_bound(
    *,
    preflight: LegacySqlConnectorConnectionPreflightEvidence,
    policy: (
        LegacySqlConnectorRealConnectionTimeoutRetryPolicy
        | LegacySqlConnectorRealConnectionAuditPlan
        | LegacySqlConnectorRealConnectionKillSwitchPolicy
    ),
) -> bool:
    return (
        policy.tenant_id == preflight.tenant_id
        and policy.module_id == preflight.module_id
        and policy.source_system_ref == preflight.source_system_ref
        and policy.connector_kind == preflight.connector_kind
        and policy.sandbox_profile_ref == preflight.sandbox_profile_ref
        and policy.sandbox_profile_evidence_hash == preflight.sandbox_profile_evidence_hash
        and policy.preflight_evidence_hash == preflight.evidence_hash
    )


def _executor_blocking_reasons(
    *,
    command: LegacySqlConnectorRealConnectionExecutorCommand,
    preflight_hash_valid: bool,
    preflight_ready: bool,
    preflight_bound: bool,
    timeout_retry_policy_hash_valid: bool,
    timeout_retry_policy_bound: bool,
    audit_plan_hash_valid: bool,
    audit_plan_bound: bool,
    audit_plan_metadata_only: bool,
    audit_plan_required_event_types_present: bool,
    kill_switch_policy_hash_valid: bool,
    kill_switch_policy_bound: bool,
    kill_switch_policy: LegacySqlConnectorRealConnectionKillSwitchPolicy,
    executor_restore_evidence_hash_valid: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not preflight_hash_valid:
        reasons.append("preflight_hash_invalid")
    if not preflight_ready:
        reasons.append("preflight_not_ready")
    if not preflight_bound:
        reasons.append("preflight_not_bound")
    if not timeout_retry_policy_hash_valid:
        reasons.append("timeout_retry_policy_hash_invalid")
    if not timeout_retry_policy_bound:
        reasons.append("timeout_retry_policy_not_bound")
    if not audit_plan_hash_valid:
        reasons.append("audit_plan_hash_invalid")
    if not audit_plan_bound:
        reasons.append("audit_plan_not_bound")
    if not audit_plan_metadata_only:
        reasons.append("audit_plan_not_metadata_only")
    if not audit_plan_required_event_types_present:
        reasons.append("audit_plan_required_event_types_missing")
    if not kill_switch_policy_hash_valid:
        reasons.append("kill_switch_policy_hash_invalid")
    if not kill_switch_policy_bound:
        reasons.append("kill_switch_policy_not_bound")
    if not kill_switch_policy.kill_switch_armed:
        reasons.append("kill_switch_not_armed")
    if kill_switch_policy.tenant_connection_disabled:
        reasons.append("tenant_connection_kill_switch_disabled")
    if kill_switch_policy.global_connection_disabled:
        reasons.append("global_connection_kill_switch_disabled")
    if kill_switch_policy.manual_abort_requested:
        reasons.append("manual_abort_requested")
    if kill_switch_policy.break_glass_allowed:
        reasons.append("break_glass_requires_separate_incident_gate")
    if not executor_restore_evidence_hash_valid:
        reasons.append("executor_restore_evidence_hash_invalid")
    if not command.executor_contract_requested:
        reasons.append("executor_contract_not_requested")
    if command.socket_materialization_requested:
        reasons.append("socket_materialization_requires_future_execution_gate")
    if command.secret_materialization_requested:
        reasons.append("secret_materialization_requires_future_execution_gate")
    if command.raw_data_access_requested:
        reasons.append("raw_data_access_request_requires_separate_gate")
    if command.import_dry_run_requested:
        reasons.append("import_dry_run_request_requires_separate_gate")
    if command.import_write_requested:
        reasons.append("import_write_request_requires_separate_gate")
    if command.destructive_actions_requested:
        reasons.append("destructive_action_request_requires_separate_gate")
    return tuple(sorted(set(reasons)))


def _materialization_request_blocked(
    *,
    command: LegacySqlConnectorRealConnectionExecutorCommand,
    preflight: LegacySqlConnectorConnectionPreflightEvidence,
    timeout_retry_policy: LegacySqlConnectorRealConnectionTimeoutRetryPolicy,
    audit_plan: LegacySqlConnectorRealConnectionAuditPlan,
    kill_switch_policy: LegacySqlConnectorRealConnectionKillSwitchPolicy,
    checked_by: str,
    checked_at: datetime,
) -> bool:
    blocked = build_legacy_sql_connector_real_connection_executor_contract(
        command=command.model_copy(
            update={"socket_materialization_requested": True, "secret_materialization_requested": True}
        ),
        preflight=preflight,
        timeout_retry_policy=timeout_retry_policy,
        audit_plan=audit_plan,
        kill_switch_policy=kill_switch_policy,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        blocked.contract_status == LegacySqlConnectorRealConnectionExecutorStatus.BLOCKED
        and "socket_materialization_requires_future_execution_gate" in blocked.blocking_reasons
        and "secret_materialization_requires_future_execution_gate" in blocked.blocking_reasons
        and not blocked.socket_materialization_allowed
        and not blocked.network_socket_opened
        and not blocked.secret_material_resolved
    )


def _kill_switch_disabled_blocked(
    *,
    command: LegacySqlConnectorRealConnectionExecutorCommand,
    preflight: LegacySqlConnectorConnectionPreflightEvidence,
    timeout_retry_policy: LegacySqlConnectorRealConnectionTimeoutRetryPolicy,
    audit_plan: LegacySqlConnectorRealConnectionAuditPlan,
    kill_switch_policy: LegacySqlConnectorRealConnectionKillSwitchPolicy,
    checked_by: str,
    checked_at: datetime,
) -> bool:
    blocked_policy = kill_switch_policy.model_copy(
        update={"tenant_connection_disabled": True, "checked_at_utc": checked_at, "evidence_hash": ZERO_HASH}
    )
    blocked_policy = blocked_policy.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_real_connection_kill_switch_policy_hash(blocked_policy)}
    )
    blocked_command = command.model_copy(update={"kill_switch_policy_hash": blocked_policy.evidence_hash})
    blocked = build_legacy_sql_connector_real_connection_executor_contract(
        command=blocked_command,
        preflight=preflight,
        timeout_retry_policy=timeout_retry_policy,
        audit_plan=audit_plan,
        kill_switch_policy=blocked_policy,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        blocked.contract_status == LegacySqlConnectorRealConnectionExecutorStatus.BLOCKED
        and "tenant_connection_kill_switch_disabled" in blocked.blocking_reasons
        and not blocked.real_connection_opened
    )


def _tampered_preflight_blocked(
    *,
    command: LegacySqlConnectorRealConnectionExecutorCommand,
    preflight: LegacySqlConnectorConnectionPreflightEvidence,
    timeout_retry_policy: LegacySqlConnectorRealConnectionTimeoutRetryPolicy,
    audit_plan: LegacySqlConnectorRealConnectionAuditPlan,
    kill_switch_policy: LegacySqlConnectorRealConnectionKillSwitchPolicy,
    checked_by: str,
    checked_at: datetime,
) -> bool:
    tampered_preflight = preflight.model_copy(update={"evidence_hash": "sha256:" + "f" * 64})
    blocked = build_legacy_sql_connector_real_connection_executor_contract(
        command=command,
        preflight=tampered_preflight,
        timeout_retry_policy=timeout_retry_policy,
        audit_plan=audit_plan,
        kill_switch_policy=kill_switch_policy,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        blocked.contract_status == LegacySqlConnectorRealConnectionExecutorStatus.BLOCKED
        and "preflight_hash_invalid" in blocked.blocking_reasons
    )


def _policy_store_smoke_input_from_env(
    *,
    env: Mapping[str, str],
    checked_by: str,
    checked_at: datetime,
) -> LegacySqlConnectorRealConnectionExecutorPolicyStoreSmokeInput:
    queue_restore_hash = env.get("SUITE_LEGACY_SQL_METADATA_WORKER_QUEUE_RESTORE_HASH", "sha256:" + "4" * 64)
    enablement_restore_hash = env.get(
        "SUITE_LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_POLICY_STORE_ENABLEMENT_RESTORE_HASH",
        "sha256:" + "5" * 64,
    )
    preflight_restore_hash = env.get(
        "SUITE_LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_POLICY_STORE_PREFLIGHT_RESTORE_HASH",
        "sha256:" + "6" * 64,
    )
    executor_restore_hash = env.get(
        "SUITE_LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_POLICY_STORE_RESTORE_HASH",
        "sha256:" + "7" * 64,
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
            "SUITE_LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_POLICY_STORE_HUMAN_CONFIRMATION_REF",
            "human-confirmation:legacy-sql-real-connection-executor-policy-store-smoke",
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
    timeout_retry_policy = build_legacy_sql_connector_real_connection_timeout_retry_policy(
        preflight=preflight_gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=11),
    )
    audit_plan = build_legacy_sql_connector_real_connection_audit_plan(
        preflight=preflight_gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=12),
    )
    kill_switch_policy = build_legacy_sql_connector_real_connection_kill_switch_policy(
        preflight=preflight_gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=13),
    )
    executor_command = build_legacy_sql_connector_real_connection_executor_command(
        preflight=preflight_gate,
        timeout_retry_policy=timeout_retry_policy,
        audit_plan=audit_plan,
        kill_switch_policy=kill_switch_policy,
        restore_evidence_hash=executor_restore_hash,
        requested_by=checked_by,
    )
    executor_contract = build_legacy_sql_connector_real_connection_executor_contract(
        command=executor_command,
        preflight=preflight_gate,
        timeout_retry_policy=timeout_retry_policy,
        audit_plan=audit_plan,
        kill_switch_policy=kill_switch_policy,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=14),
    )
    return LegacySqlConnectorRealConnectionExecutorPolicyStoreSmokeInput(
        preflight=preflight_gate,
        timeout_retry_policy=timeout_retry_policy,
        audit_plan=audit_plan,
        kill_switch_policy=kill_switch_policy,
        executor_contract=executor_contract,
    )


def _policy_chain_bound_to_contract(
    *,
    timeout_retry_policy: LegacySqlConnectorRealConnectionTimeoutRetryPolicy,
    audit_plan: LegacySqlConnectorRealConnectionAuditPlan,
    kill_switch_policy: LegacySqlConnectorRealConnectionKillSwitchPolicy,
    executor_contract: LegacySqlConnectorRealConnectionExecutorContractEvidence,
) -> bool:
    return (
        timeout_retry_policy.tenant_id
        == audit_plan.tenant_id
        == kill_switch_policy.tenant_id
        == executor_contract.tenant_id
        and timeout_retry_policy.module_id
        == audit_plan.module_id
        == kill_switch_policy.module_id
        == executor_contract.module_id
        and timeout_retry_policy.source_system_ref
        == audit_plan.source_system_ref
        == kill_switch_policy.source_system_ref
        == executor_contract.source_system_ref
        and timeout_retry_policy.connector_kind
        == audit_plan.connector_kind
        == kill_switch_policy.connector_kind
        == executor_contract.connector_kind
        and timeout_retry_policy.sandbox_profile_ref
        == audit_plan.sandbox_profile_ref
        == kill_switch_policy.sandbox_profile_ref
        == executor_contract.sandbox_profile_ref
        and timeout_retry_policy.sandbox_profile_evidence_hash
        == audit_plan.sandbox_profile_evidence_hash
        == kill_switch_policy.sandbox_profile_evidence_hash
        == executor_contract.sandbox_profile_evidence_hash
        and timeout_retry_policy.preflight_evidence_hash
        == audit_plan.preflight_evidence_hash
        == kill_switch_policy.preflight_evidence_hash
        == executor_contract.preflight_evidence_hash
        and timeout_retry_policy.evidence_hash == executor_contract.timeout_retry_policy_hash
        and audit_plan.evidence_hash == executor_contract.audit_plan_hash
        and kill_switch_policy.evidence_hash == executor_contract.kill_switch_policy_hash
    )


def _policy_bundle_tenant_scope_verified(
    *,
    timeout_retry_policy: LegacySqlConnectorRealConnectionTimeoutRetryPolicy,
    audit_plan: LegacySqlConnectorRealConnectionAuditPlan,
    kill_switch_policy: LegacySqlConnectorRealConnectionKillSwitchPolicy,
    executor_contract: LegacySqlConnectorRealConnectionExecutorContractEvidence,
) -> bool:
    return (
        len(
            {
                timeout_retry_policy.tenant_id,
                audit_plan.tenant_id,
                kill_switch_policy.tenant_id,
                executor_contract.tenant_id,
            }
        )
        == 1
    )


def _policy_bundle_blocking_reasons(
    *,
    timeout_retry_policy_hash_valid: bool,
    audit_plan_hash_valid: bool,
    kill_switch_policy_hash_valid: bool,
    executor_contract_hash_valid: bool,
    policy_chain_bound: bool,
    tenant_scope_verified: bool,
    restore_evidence_hash_valid: bool,
    executor_contract: LegacySqlConnectorRealConnectionExecutorContractEvidence,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not timeout_retry_policy_hash_valid:
        reasons.append("timeout_retry_policy_hash_invalid")
    if not audit_plan_hash_valid:
        reasons.append("audit_plan_hash_invalid")
    if not kill_switch_policy_hash_valid:
        reasons.append("kill_switch_policy_hash_invalid")
    if not executor_contract_hash_valid:
        reasons.append("executor_contract_hash_invalid")
    if not policy_chain_bound:
        reasons.append("policy_chain_not_bound")
    if not tenant_scope_verified:
        reasons.append("tenant_scope_not_verified")
    if not restore_evidence_hash_valid:
        reasons.append("executor_restore_evidence_hash_invalid")
    if executor_contract.contract_status != LegacySqlConnectorRealConnectionExecutorStatus.READY:
        reasons.append("executor_contract_not_ready")
    if not executor_contract.executor_contract_ready:
        reasons.append("executor_contract_not_ready_for_persistence")
    if (
        executor_contract.network_socket_opened
        or executor_contract.real_connection_opened
        or executor_contract.secret_material_resolved
        or executor_contract.raw_data_access_allowed
        or executor_contract.import_dry_run_allowed
        or executor_contract.import_write_allowed
        or executor_contract.destructive_actions_allowed
    ):
        reasons.append("executor_contract_not_non_executing")
    return tuple(sorted(set(reasons)))


def _policy_bundle_key(bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle) -> tuple[str, str]:
    return (bundle.tenant_id, bundle.executor_contract_evidence_hash)


def _require_valid_policy_bundle_hash(bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle) -> None:
    if build_legacy_sql_connector_real_connection_executor_policy_bundle_hash(bundle) != bundle.evidence_hash:
        raise ValueError("legacy SQL real-connection executor policy bundle hash mismatch")
    if not bundle.store_persistence_allowed:
        raise ValueError("legacy SQL real-connection executor policy bundle is not allowed to persist")


def _require_same_policy_bundle_identity(
    *,
    existing: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    incoming: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
) -> None:
    if existing.evidence_hash != incoming.evidence_hash:
        raise ValueError("legacy SQL real-connection executor policy bundle already exists with different evidence")


def _policy_store_tenant_isolation_ok(
    *,
    store: LegacySqlConnectorRealConnectionExecutorPolicyStore,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
) -> bool:
    other_tenant_id = f"{bundle.tenant_id}-other"
    try:
        store.get(
            tenant_id=other_tenant_id,
            executor_contract_evidence_hash=bundle.executor_contract_evidence_hash,
        )
    except KeyError:
        return store.list_bundles(tenant_id=other_tenant_id) == ()
    return False


def _assert_executor_safe(value: BaseModel) -> None:
    payload = value.model_dump_json().lower()
    for fragment in FORBIDDEN_EXECUTOR_FRAGMENTS:
        if fragment in payload:
            raise ValueError(f"legacy SQL real-connection executor leaked forbidden fragment: {fragment}")


if __name__ == "__main__":
    main()
