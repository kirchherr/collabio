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
from suite.platform.legacy_sql_connector_materialization_plan_gate import (
    LegacySqlConnectorMaterializationKillSwitchSnapshot,
    LegacySqlConnectorMaterializationPlanGateEvidence,
    LegacySqlConnectorMaterializationPlanGateStatus,
    build_legacy_sql_connector_materialization_kill_switch_snapshot,
    build_legacy_sql_connector_materialization_operator_mfa_snapshot,
    build_legacy_sql_connector_materialization_plan_gate,
    build_legacy_sql_connector_materialization_plan_gate_command,
    build_legacy_sql_connector_materialization_plan_gate_hash,
    build_legacy_sql_connector_materialization_provider_profile_snapshot,
)
from suite.platform.legacy_sql_connector_materialization_plan_gate import (
    _build_ready_review_gate as _build_ready_materialization_review_gate,
)
from suite.platform.legacy_sql_connector_real_connection_executor import (
    LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    LegacySqlConnectorRealConnectionPolicyStoreBackend,
    _policy_store_smoke_input_from_env,
    build_default_legacy_sql_connector_real_connection_executor_policy_store,
    build_legacy_sql_connector_real_connection_executor_policy_bundle,
)
from suite.platform.legacy_sql_discovery import MODULE_ID_PATTERN, NAMESPACED_REF_PATTERN, LegacySqlConnectorKind
from suite.platform.legacy_sql_metadata_worker_queue import LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN

LEGACY_SQL_CONNECTOR_SOCKET_SECRET_PROVIDER_LIMITS_SNAPSHOT_SCHEMA_VERSION = (
    "legacy_sql_connector_socket_secret_provider_limits_snapshot.v1"
)
LEGACY_SQL_CONNECTOR_SOCKET_SECRET_NETWORK_ROUTE_SNAPSHOT_SCHEMA_VERSION = (
    "legacy_sql_connector_socket_secret_network_route_snapshot.v1"
)
LEGACY_SQL_CONNECTOR_SOCKET_SECRET_SECRET_MANAGER_SNAPSHOT_SCHEMA_VERSION = (
    "legacy_sql_connector_socket_secret_secret_manager_snapshot.v1"
)
LEGACY_SQL_CONNECTOR_SOCKET_SECRET_ROLLBACK_RUNBOOK_SNAPSHOT_SCHEMA_VERSION = (
    "legacy_sql_connector_socket_secret_rollback_runbook_snapshot.v1"
)
LEGACY_SQL_CONNECTOR_SOCKET_SECRET_KILL_SWITCH_RUNBOOK_SNAPSHOT_SCHEMA_VERSION = (
    "legacy_sql_connector_socket_secret_kill_switch_runbook_snapshot.v1"
)
LEGACY_SQL_CONNECTOR_SOCKET_SECRET_IMPLEMENTATION_ADR_GATE_SCHEMA_VERSION = (
    "legacy_sql_connector_socket_secret_implementation_adr_gate.v1"
)
LEGACY_SQL_CONNECTOR_SOCKET_SECRET_IMPLEMENTATION_ADR_GATE_SMOKE_SCHEMA_VERSION = (
    "legacy_sql_connector_socket_secret_implementation_adr_gate_smoke_report.v1"
)
LEGACY_SQL_CONNECTOR_SOCKET_SECRET_IMPLEMENTATION_ADR_GATE_COMMAND_REF = (
    "docker-compose:legacy-sql-connector-socket-secret-implementation-adr-gate-smoke"
)
ZERO_HASH = "sha256:" + "0" * 64
SHA256_REF_PATTERN = r"^sha256:[a-f0-9]{64}$"
FORBIDDEN_SOCKET_SECRET_ADR_FRAGMENTS = (
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


class LegacySqlConnectorSocketSecretImplementationAdrGateStatus(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"


class LegacySqlConnectorSocketSecretProviderLimitsSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_SOCKET_SECRET_PROVIDER_LIMITS_SNAPSHOT_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    provider_limits_snapshot_ref: str = "provider-limits-snapshot:legacy-sql-socket-secret-adr"
    materialization_plan_gate_evidence_hash: str
    provider_profile_snapshot_hash: str
    max_concurrent_connection_attempts: int = 1
    socket_connect_timeout_ms: int = 1500
    metadata_probe_timeout_ms: int = 3000
    max_retry_attempts: int = 0
    provider_rate_limit_per_minute: int = 2
    bulk_read_limit: int = 0
    provider_limits_attested: bool = True
    raw_data_access_allowed: bool = False
    import_dry_run_allowed: bool = False
    import_write_allowed: bool = False
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL socket-secret ADR provider limits text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL socket-secret ADR provider limits module_id must be lowercase snake_case")
        return value

    @field_validator("source_system_ref", "provider_limits_snapshot_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL socket-secret ADR provider limits references must be namespaced")
        return value

    @field_validator("materialization_plan_gate_evidence_hash", "provider_profile_snapshot_hash", "evidence_hash")
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL socket-secret ADR provider limits hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_safe_limits(self) -> Self:
        if self.max_concurrent_connection_attempts < 1:
            raise ValueError("legacy SQL socket-secret ADR provider limits require at least one bounded attempt")
        if self.socket_connect_timeout_ms < 100 or self.metadata_probe_timeout_ms < 100:
            raise ValueError("legacy SQL socket-secret ADR provider limits require bounded timeouts")
        if self.max_retry_attempts != 0 or self.bulk_read_limit != 0:
            raise ValueError("legacy SQL socket-secret ADR provider limits must not enable retries or bulk reads")
        if self.raw_data_access_allowed or self.import_dry_run_allowed or self.import_write_allowed:
            raise ValueError("legacy SQL socket-secret ADR provider limits must remain non-importing")
        _assert_socket_secret_adr_safe(self)
        return self


class LegacySqlConnectorSocketSecretNetworkRouteSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_SOCKET_SECRET_NETWORK_ROUTE_SNAPSHOT_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    network_route_snapshot_ref: str = "network-route-snapshot:legacy-sql-socket-secret-adr"
    materialization_plan_gate_evidence_hash: str
    network_route_ref: str = "network-route:legacy-sql-controlled-egress"
    firewall_change_ref: str = "change-request:legacy-sql-controlled-egress"
    route_owner_ref: str = "team:platform-network"
    approved_route_bound_to_tenant: bool = True
    tenant_route_isolated: bool = True
    egress_allowlist_reviewed: bool = True
    inbound_access_forbidden: bool = True
    default_compose_legacy_network_enabled: bool = False
    network_socket_opened: bool = False
    network_connection_opened: bool = False
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL socket-secret ADR network route text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL socket-secret ADR network route module_id must be lowercase snake_case")
        return value

    @field_validator(
        "source_system_ref", "network_route_snapshot_ref", "network_route_ref", "firewall_change_ref", "route_owner_ref"
    )
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL socket-secret ADR network route references must be namespaced")
        return value

    @field_validator("materialization_plan_gate_evidence_hash", "evidence_hash")
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL socket-secret ADR network route hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_safe_route(self) -> Self:
        if self.default_compose_legacy_network_enabled or self.network_socket_opened or self.network_connection_opened:
            raise ValueError("legacy SQL socket-secret ADR network route snapshot must not open routes")
        _assert_socket_secret_adr_safe(self)
        return self


class LegacySqlConnectorSocketSecretSecretManagerSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_SOCKET_SECRET_SECRET_MANAGER_SNAPSHOT_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    secret_manager_snapshot_ref: str = "secret-manager-snapshot:legacy-sql-socket-secret-adr"
    materialization_plan_gate_evidence_hash: str
    secret_manager_ref: str = "secret-manager:tenant-runtime-vault"
    secret_access_policy_ref: str = "secret-access-policy:legacy-sql-runtime"
    rotation_policy_ref: str = "rotation-policy:legacy-sql-runtime"
    tenant_kms_policy_ref: str = "kms-policy:tenant-runtime-keys"
    secret_manager_ready: bool = True
    tenant_kms_required: bool = True
    no_plaintext_secret_reviewed: bool = True
    direct_connection_secret_ref_allowed: bool = False
    secret_material_resolved: bool = False
    secret_value_export_allowed: bool = False
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL socket-secret ADR secret manager text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL socket-secret ADR secret manager module_id must be lowercase snake_case")
        return value

    @field_validator(
        "source_system_ref",
        "secret_manager_snapshot_ref",
        "secret_manager_ref",
        "secret_access_policy_ref",
        "rotation_policy_ref",
        "tenant_kms_policy_ref",
    )
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL socket-secret ADR secret manager references must be namespaced")
        return value

    @field_validator("materialization_plan_gate_evidence_hash", "evidence_hash")
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL socket-secret ADR secret manager hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_safe_secret_manager(self) -> Self:
        if (
            self.direct_connection_secret_ref_allowed
            or self.secret_material_resolved
            or self.secret_value_export_allowed
        ):
            raise ValueError("legacy SQL socket-secret ADR secret manager snapshot must not expose secret material")
        _assert_socket_secret_adr_safe(self)
        return self


class LegacySqlConnectorSocketSecretRollbackRunbookSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_SOCKET_SECRET_ROLLBACK_RUNBOOK_SNAPSHOT_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    rollback_runbook_snapshot_ref: str = "rollback-runbook-snapshot:legacy-sql-socket-secret-adr"
    materialization_plan_gate_evidence_hash: str
    rollback_plan_ref: str = "rollback-plan:legacy-sql-socket-secret-implementation"
    restore_checkpoint_ref: str = "restore-checkpoint:legacy-sql-socket-secret-implementation"
    rollback_owner_ref: str = "team:platform-operations"
    restore_drill_report_hash: str
    backup_verification_hash: str
    rollback_runbook_tested: bool = True
    recover_without_import_writes: bool = True
    destructive_rollback_forbidden: bool = True
    import_write_allowed: bool = False
    destructive_actions_allowed: bool = False
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL socket-secret ADR rollback runbook text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL socket-secret ADR rollback runbook module_id must be lowercase snake_case")
        return value

    @field_validator(
        "source_system_ref",
        "rollback_runbook_snapshot_ref",
        "rollback_plan_ref",
        "restore_checkpoint_ref",
        "rollback_owner_ref",
    )
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL socket-secret ADR rollback runbook references must be namespaced")
        return value

    @field_validator(
        "materialization_plan_gate_evidence_hash",
        "restore_drill_report_hash",
        "backup_verification_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL socket-secret ADR rollback runbook hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_safe_rollback(self) -> Self:
        if self.import_write_allowed or self.destructive_actions_allowed or not self.destructive_rollback_forbidden:
            raise ValueError("legacy SQL socket-secret ADR rollback runbook must not allow writes")
        _assert_socket_secret_adr_safe(self)
        return self


class LegacySqlConnectorSocketSecretKillSwitchRunbookSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_SOCKET_SECRET_KILL_SWITCH_RUNBOOK_SNAPSHOT_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    kill_switch_runbook_snapshot_ref: str = "kill-switch-runbook-snapshot:legacy-sql-socket-secret-adr"
    materialization_plan_gate_evidence_hash: str
    kill_switch_snapshot_hash: str
    kill_switch_policy_hash: str
    kill_switch_runbook_ref: str = "runbook:legacy-sql-kill-switch"
    operator_drill_ref: str = "operator-drill:legacy-sql-kill-switch"
    incident_channel_ref: str
    tenant_kill_switch_ref: str
    global_kill_switch_ref: str
    manual_abort_ref: str
    kill_switch_armed: bool = True
    kill_switch_runbook_tested: bool = True
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
            raise ValueError("legacy SQL socket-secret ADR kill-switch runbook text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL socket-secret ADR kill-switch runbook module_id must be lowercase snake_case")
        return value

    @field_validator(
        "source_system_ref",
        "kill_switch_runbook_snapshot_ref",
        "kill_switch_runbook_ref",
        "operator_drill_ref",
        "incident_channel_ref",
        "tenant_kill_switch_ref",
        "global_kill_switch_ref",
        "manual_abort_ref",
    )
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL socket-secret ADR kill-switch runbook references must be namespaced")
        return value

    @field_validator(
        "materialization_plan_gate_evidence_hash",
        "kill_switch_snapshot_hash",
        "kill_switch_policy_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL socket-secret ADR kill-switch runbook hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_safe_kill_switch(self) -> Self:
        if self.break_glass_allowed:
            raise ValueError("legacy SQL socket-secret ADR kill-switch runbook cannot allow break-glass by default")
        _assert_socket_secret_adr_safe(self)
        return self


class LegacySqlConnectorSocketSecretImplementationAdrGateCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    architecture_decision_record_ref: str = "adr:legacy-sql-socket-secret-implementation"
    materialization_plan_gate_evidence_hash: str
    provider_limits_snapshot_hash: str
    network_route_snapshot_hash: str
    secret_manager_snapshot_hash: str
    rollback_runbook_snapshot_hash: str
    kill_switch_runbook_snapshot_hash: str
    requested_by: str
    adr_review_requested: bool = True
    socket_implementation_requested: bool = False
    secret_materialization_requested: bool = False
    executor_code_requested: bool = False
    raw_data_access_requested: bool = False
    import_dry_run_requested: bool = False
    import_write_requested: bool = False
    destructive_actions_requested: bool = False

    @field_validator("tenant_id", "requested_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL socket-secret ADR command text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL socket-secret ADR command module_id must be lowercase snake_case")
        return value

    @field_validator("source_system_ref", "architecture_decision_record_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL socket-secret ADR command references must be namespaced")
        return value

    @field_validator(
        "materialization_plan_gate_evidence_hash",
        "provider_limits_snapshot_hash",
        "network_route_snapshot_hash",
        "secret_manager_snapshot_hash",
        "rollback_runbook_snapshot_hash",
        "kill_switch_runbook_snapshot_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL socket-secret ADR command hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_safe_command(self) -> Self:
        _assert_socket_secret_adr_safe(self)
        return self


class LegacySqlConnectorSocketSecretImplementationAdrGateEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_SOCKET_SECRET_IMPLEMENTATION_ADR_GATE_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    continuity_domain: str = LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN
    command_ref: str = LEGACY_SQL_CONNECTOR_SOCKET_SECRET_IMPLEMENTATION_ADR_GATE_COMMAND_REF
    architecture_decision_record_ref: str
    materialization_plan_gate_evidence_hash: str
    provider_limits_snapshot_hash: str
    network_route_snapshot_hash: str
    secret_manager_snapshot_hash: str
    rollback_runbook_snapshot_hash: str
    kill_switch_runbook_snapshot_hash: str
    materialization_plan_gate_hash_valid: bool
    materialization_plan_gate_ready: bool
    materialization_plan_gate_bound: bool
    provider_limits_snapshot_hash_valid: bool
    provider_limits_snapshot_bound: bool
    provider_limits_attested: bool
    network_route_snapshot_hash_valid: bool
    network_route_snapshot_bound: bool
    network_route_approved: bool
    tenant_route_isolated: bool
    egress_allowlist_reviewed: bool
    inbound_access_forbidden: bool
    secret_manager_snapshot_hash_valid: bool
    secret_manager_snapshot_bound: bool
    secret_manager_ready: bool
    tenant_kms_required: bool
    no_plaintext_secret_reviewed: bool
    rollback_runbook_snapshot_hash_valid: bool
    rollback_runbook_snapshot_bound: bool
    rollback_runbook_tested: bool
    recover_without_import_writes: bool
    destructive_rollback_forbidden: bool
    kill_switch_runbook_snapshot_hash_valid: bool
    kill_switch_runbook_snapshot_bound: bool
    kill_switch_armed: bool
    kill_switch_runbook_tested: bool
    tenant_connection_disabled: bool
    global_connection_disabled: bool
    manual_abort_requested: bool
    break_glass_allowed: bool
    adr_review_requested: bool
    implementation_adr_ready: bool
    future_socket_secret_runtime_pr_required: bool = True
    future_secret_manager_runtime_binding_required: bool = True
    future_network_route_runtime_binding_required: bool = True
    socket_implementation_requested: bool = False
    socket_implementation_allowed: bool = False
    secret_materialization_requested: bool = False
    secret_materialization_allowed: bool = False
    executor_code_requested: bool = False
    executor_code_allowed: bool = False
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
    gate_status: LegacySqlConnectorSocketSecretImplementationAdrGateStatus
    blocking_reasons: tuple[str, ...]
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL socket-secret ADR gate text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL socket-secret ADR gate module_id must be lowercase snake_case")
        return value

    @field_validator("source_system_ref", "architecture_decision_record_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL socket-secret ADR gate references must be namespaced")
        return value

    @field_validator(
        "materialization_plan_gate_evidence_hash",
        "provider_limits_snapshot_hash",
        "network_route_snapshot_hash",
        "secret_manager_snapshot_hash",
        "rollback_runbook_snapshot_hash",
        "kill_switch_runbook_snapshot_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL socket-secret ADR gate hashes must be sha256 references")
        return value

    @field_validator("blocking_reasons")
    @classmethod
    def validate_blocking_reasons(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("legacy SQL socket-secret ADR gate blocking reasons must be unique")
        for reason in value:
            if not reason.strip():
                raise ValueError("legacy SQL socket-secret ADR gate blocking reasons must not be empty")
        return value

    @model_validator(mode="after")
    def require_safe_gate(self) -> Self:
        if (
            self.socket_implementation_allowed
            or self.secret_materialization_allowed
            or self.executor_code_allowed
            or self.network_socket_opened
            or self.network_connection_opened
            or self.real_connection_opened
            or self.secret_material_resolved
            or self.raw_data_access_allowed
            or self.import_dry_run_allowed
            or self.import_write_allowed
            or self.destructive_actions_allowed
        ):
            raise ValueError("legacy SQL socket-secret ADR gate must remain non-executing")
        if (
            not self.future_socket_secret_runtime_pr_required
            or not self.future_secret_manager_runtime_binding_required
            or not self.future_network_route_runtime_binding_required
        ):
            raise ValueError("legacy SQL socket-secret ADR gate must require future runtime gates")
        if self.gate_status == LegacySqlConnectorSocketSecretImplementationAdrGateStatus.READY:
            required = (
                self.materialization_plan_gate_hash_valid,
                self.materialization_plan_gate_ready,
                self.materialization_plan_gate_bound,
                self.provider_limits_snapshot_hash_valid,
                self.provider_limits_snapshot_bound,
                self.provider_limits_attested,
                self.network_route_snapshot_hash_valid,
                self.network_route_snapshot_bound,
                self.network_route_approved,
                self.tenant_route_isolated,
                self.egress_allowlist_reviewed,
                self.inbound_access_forbidden,
                self.secret_manager_snapshot_hash_valid,
                self.secret_manager_snapshot_bound,
                self.secret_manager_ready,
                self.tenant_kms_required,
                self.no_plaintext_secret_reviewed,
                self.rollback_runbook_snapshot_hash_valid,
                self.rollback_runbook_snapshot_bound,
                self.rollback_runbook_tested,
                self.recover_without_import_writes,
                self.destructive_rollback_forbidden,
                self.kill_switch_runbook_snapshot_hash_valid,
                self.kill_switch_runbook_snapshot_bound,
                self.kill_switch_armed,
                self.kill_switch_runbook_tested,
                not self.tenant_connection_disabled,
                not self.global_connection_disabled,
                not self.manual_abort_requested,
                not self.break_glass_allowed,
                self.adr_review_requested,
                self.implementation_adr_ready,
            )
            if not all(required) or self.blocking_reasons:
                raise ValueError("ready legacy SQL socket-secret ADR gate requires complete evidence")
        if self.gate_status == LegacySqlConnectorSocketSecretImplementationAdrGateStatus.BLOCKED:
            if not self.blocking_reasons:
                raise ValueError("blocked legacy SQL socket-secret ADR gate requires blocking reasons")
            if self.implementation_adr_ready:
                raise ValueError("blocked legacy SQL socket-secret ADR gate cannot be ready")
        _assert_socket_secret_adr_safe(self)
        return self


class LegacySqlConnectorSocketSecretImplementationAdrGateSmokeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_SOCKET_SECRET_IMPLEMENTATION_ADR_GATE_SMOKE_SCHEMA_VERSION
    tenant_id: str
    store_backend: LegacySqlConnectorRealConnectionPolicyStoreBackend
    continuity_domain: str = LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN
    command_ref: str = LEGACY_SQL_CONNECTOR_SOCKET_SECRET_IMPLEMENTATION_ADR_GATE_COMMAND_REF
    materialization_plan_gate_evidence_hash: str
    provider_limits_snapshot_hash: str
    network_route_snapshot_hash: str
    secret_manager_snapshot_hash: str
    rollback_runbook_snapshot_hash: str
    kill_switch_runbook_snapshot_hash: str
    adr_gate_evidence_hash: str
    implementation_adr_ready: bool
    materialization_plan_gate_required: bool
    provider_limits_snapshot_required: bool
    network_route_snapshot_required: bool
    secret_manager_snapshot_required: bool
    rollback_runbook_snapshot_required: bool
    kill_switch_runbook_snapshot_required: bool
    materialization_plan_missing_blocked: bool
    provider_limits_missing_blocked: bool
    network_route_missing_blocked: bool
    secret_manager_missing_blocked: bool
    rollback_runbook_missing_blocked: bool
    kill_switch_runbook_missing_blocked: bool
    implementation_request_blocked: bool
    future_socket_secret_runtime_pr_required: bool
    future_secret_manager_runtime_binding_required: bool
    future_network_route_runtime_binding_required: bool
    socket_implementation_allowed: bool = False
    secret_materialization_allowed: bool = False
    executor_code_allowed: bool = False
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
            self.socket_implementation_allowed
            or self.secret_materialization_allowed
            or self.executor_code_allowed
            or self.network_socket_opened
            or self.network_connection_opened
            or self.real_connection_opened
            or self.secret_material_resolved
            or self.raw_data_access_allowed
            or self.import_dry_run_allowed
            or self.import_write_allowed
            or self.destructive_actions_allowed
        ):
            raise ValueError("legacy SQL socket-secret ADR smoke must remain non-executing")
        _assert_socket_secret_adr_safe(self)
        return self


def build_legacy_sql_connector_socket_secret_provider_limits_snapshot(
    *,
    materialization_gate: LegacySqlConnectorMaterializationPlanGateEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    provider_limits_attested: bool = True,
) -> LegacySqlConnectorSocketSecretProviderLimitsSnapshot:
    checked_at = checked_at_utc or datetime.now(UTC)
    draft = LegacySqlConnectorSocketSecretProviderLimitsSnapshot(
        tenant_id=materialization_gate.tenant_id,
        module_id=materialization_gate.module_id,
        source_system_ref=materialization_gate.source_system_ref,
        connector_kind=materialization_gate.connector_kind,
        materialization_plan_gate_evidence_hash=materialization_gate.evidence_hash,
        provider_profile_snapshot_hash=materialization_gate.provider_profile_snapshot_hash,
        provider_limits_attested=provider_limits_attested,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_socket_secret_provider_limits_snapshot_hash(draft)}
    )


def build_legacy_sql_connector_socket_secret_network_route_snapshot(
    *,
    materialization_gate: LegacySqlConnectorMaterializationPlanGateEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    approved_route_bound_to_tenant: bool = True,
) -> LegacySqlConnectorSocketSecretNetworkRouteSnapshot:
    checked_at = checked_at_utc or datetime.now(UTC)
    draft = LegacySqlConnectorSocketSecretNetworkRouteSnapshot(
        tenant_id=materialization_gate.tenant_id,
        module_id=materialization_gate.module_id,
        source_system_ref=materialization_gate.source_system_ref,
        connector_kind=materialization_gate.connector_kind,
        materialization_plan_gate_evidence_hash=materialization_gate.evidence_hash,
        approved_route_bound_to_tenant=approved_route_bound_to_tenant,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_socket_secret_network_route_snapshot_hash(draft)}
    )


def build_legacy_sql_connector_socket_secret_secret_manager_snapshot(
    *,
    materialization_gate: LegacySqlConnectorMaterializationPlanGateEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    secret_manager_ready: bool = True,
) -> LegacySqlConnectorSocketSecretSecretManagerSnapshot:
    checked_at = checked_at_utc or datetime.now(UTC)
    draft = LegacySqlConnectorSocketSecretSecretManagerSnapshot(
        tenant_id=materialization_gate.tenant_id,
        module_id=materialization_gate.module_id,
        source_system_ref=materialization_gate.source_system_ref,
        connector_kind=materialization_gate.connector_kind,
        materialization_plan_gate_evidence_hash=materialization_gate.evidence_hash,
        secret_manager_ready=secret_manager_ready,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_socket_secret_secret_manager_snapshot_hash(draft)}
    )


def build_legacy_sql_connector_socket_secret_rollback_runbook_snapshot(
    *,
    materialization_gate: LegacySqlConnectorMaterializationPlanGateEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    rollback_runbook_tested: bool = True,
) -> LegacySqlConnectorSocketSecretRollbackRunbookSnapshot:
    checked_at = checked_at_utc or datetime.now(UTC)
    draft = LegacySqlConnectorSocketSecretRollbackRunbookSnapshot(
        tenant_id=materialization_gate.tenant_id,
        module_id=materialization_gate.module_id,
        source_system_ref=materialization_gate.source_system_ref,
        connector_kind=materialization_gate.connector_kind,
        materialization_plan_gate_evidence_hash=materialization_gate.evidence_hash,
        restore_drill_report_hash="sha256:" + "8" * 64,
        backup_verification_hash="sha256:" + "9" * 64,
        rollback_runbook_tested=rollback_runbook_tested,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_socket_secret_rollback_runbook_snapshot_hash(draft)}
    )


def build_legacy_sql_connector_socket_secret_kill_switch_runbook_snapshot(
    *,
    materialization_gate: LegacySqlConnectorMaterializationPlanGateEvidence,
    kill_switch_snapshot: LegacySqlConnectorMaterializationKillSwitchSnapshot,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    kill_switch_runbook_tested: bool = True,
) -> LegacySqlConnectorSocketSecretKillSwitchRunbookSnapshot:
    checked_at = checked_at_utc or datetime.now(UTC)
    draft = LegacySqlConnectorSocketSecretKillSwitchRunbookSnapshot(
        tenant_id=materialization_gate.tenant_id,
        module_id=materialization_gate.module_id,
        source_system_ref=materialization_gate.source_system_ref,
        connector_kind=materialization_gate.connector_kind,
        materialization_plan_gate_evidence_hash=materialization_gate.evidence_hash,
        kill_switch_snapshot_hash=kill_switch_snapshot.evidence_hash,
        kill_switch_policy_hash=kill_switch_snapshot.kill_switch_policy_hash,
        incident_channel_ref=kill_switch_snapshot.incident_channel_ref,
        tenant_kill_switch_ref=kill_switch_snapshot.tenant_kill_switch_ref,
        global_kill_switch_ref=kill_switch_snapshot.global_kill_switch_ref,
        manual_abort_ref=kill_switch_snapshot.manual_abort_ref,
        kill_switch_armed=kill_switch_snapshot.kill_switch_armed,
        kill_switch_runbook_tested=kill_switch_runbook_tested,
        tenant_connection_disabled=kill_switch_snapshot.tenant_connection_disabled,
        global_connection_disabled=kill_switch_snapshot.global_connection_disabled,
        manual_abort_requested=kill_switch_snapshot.manual_abort_requested,
        break_glass_allowed=kill_switch_snapshot.break_glass_allowed,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_socket_secret_kill_switch_runbook_snapshot_hash(draft)}
    )


def build_legacy_sql_connector_socket_secret_implementation_adr_gate_command(
    *,
    materialization_gate: LegacySqlConnectorMaterializationPlanGateEvidence,
    provider_limits_snapshot: LegacySqlConnectorSocketSecretProviderLimitsSnapshot,
    network_route_snapshot: LegacySqlConnectorSocketSecretNetworkRouteSnapshot,
    secret_manager_snapshot: LegacySqlConnectorSocketSecretSecretManagerSnapshot,
    rollback_runbook_snapshot: LegacySqlConnectorSocketSecretRollbackRunbookSnapshot,
    kill_switch_runbook_snapshot: LegacySqlConnectorSocketSecretKillSwitchRunbookSnapshot,
    requested_by: str,
    adr_review_requested: bool = True,
    socket_implementation_requested: bool = False,
    secret_materialization_requested: bool = False,
    executor_code_requested: bool = False,
    raw_data_access_requested: bool = False,
    import_dry_run_requested: bool = False,
    import_write_requested: bool = False,
    destructive_actions_requested: bool = False,
) -> LegacySqlConnectorSocketSecretImplementationAdrGateCommand:
    return LegacySqlConnectorSocketSecretImplementationAdrGateCommand(
        tenant_id=materialization_gate.tenant_id,
        module_id=materialization_gate.module_id,
        source_system_ref=materialization_gate.source_system_ref,
        connector_kind=materialization_gate.connector_kind,
        materialization_plan_gate_evidence_hash=materialization_gate.evidence_hash,
        provider_limits_snapshot_hash=provider_limits_snapshot.evidence_hash,
        network_route_snapshot_hash=network_route_snapshot.evidence_hash,
        secret_manager_snapshot_hash=secret_manager_snapshot.evidence_hash,
        rollback_runbook_snapshot_hash=rollback_runbook_snapshot.evidence_hash,
        kill_switch_runbook_snapshot_hash=kill_switch_runbook_snapshot.evidence_hash,
        requested_by=requested_by,
        adr_review_requested=adr_review_requested,
        socket_implementation_requested=socket_implementation_requested,
        secret_materialization_requested=secret_materialization_requested,
        executor_code_requested=executor_code_requested,
        raw_data_access_requested=raw_data_access_requested,
        import_dry_run_requested=import_dry_run_requested,
        import_write_requested=import_write_requested,
        destructive_actions_requested=destructive_actions_requested,
    )


def build_legacy_sql_connector_socket_secret_implementation_adr_gate(
    *,
    command: LegacySqlConnectorSocketSecretImplementationAdrGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    materialization_gate: LegacySqlConnectorMaterializationPlanGateEvidence,
    provider_limits_snapshot: LegacySqlConnectorSocketSecretProviderLimitsSnapshot,
    network_route_snapshot: LegacySqlConnectorSocketSecretNetworkRouteSnapshot,
    secret_manager_snapshot: LegacySqlConnectorSocketSecretSecretManagerSnapshot,
    rollback_runbook_snapshot: LegacySqlConnectorSocketSecretRollbackRunbookSnapshot,
    kill_switch_runbook_snapshot: LegacySqlConnectorSocketSecretKillSwitchRunbookSnapshot,
    checked_by: str,
    checked_at_utc: datetime | None = None,
) -> LegacySqlConnectorSocketSecretImplementationAdrGateEvidence:
    checked_at = checked_at_utc or datetime.now(UTC)
    materialization_plan_gate_hash_valid = (
        build_legacy_sql_connector_materialization_plan_gate_hash(materialization_gate)
        == materialization_gate.evidence_hash
        == command.materialization_plan_gate_evidence_hash
    )
    materialization_plan_gate_ready = (
        materialization_gate.gate_status == LegacySqlConnectorMaterializationPlanGateStatus.READY
        and materialization_gate.materialization_plan_ready
    )
    materialization_plan_gate_bound = _materialization_plan_gate_bound(
        command=command,
        bundle=bundle,
        materialization_gate=materialization_gate,
    )
    provider_limits_snapshot_hash_valid = (
        build_legacy_sql_connector_socket_secret_provider_limits_snapshot_hash(provider_limits_snapshot)
        == provider_limits_snapshot.evidence_hash
        == command.provider_limits_snapshot_hash
    )
    network_route_snapshot_hash_valid = (
        build_legacy_sql_connector_socket_secret_network_route_snapshot_hash(network_route_snapshot)
        == network_route_snapshot.evidence_hash
        == command.network_route_snapshot_hash
    )
    secret_manager_snapshot_hash_valid = (
        build_legacy_sql_connector_socket_secret_secret_manager_snapshot_hash(secret_manager_snapshot)
        == secret_manager_snapshot.evidence_hash
        == command.secret_manager_snapshot_hash
    )
    rollback_runbook_snapshot_hash_valid = (
        build_legacy_sql_connector_socket_secret_rollback_runbook_snapshot_hash(rollback_runbook_snapshot)
        == rollback_runbook_snapshot.evidence_hash
        == command.rollback_runbook_snapshot_hash
    )
    kill_switch_runbook_snapshot_hash_valid = (
        build_legacy_sql_connector_socket_secret_kill_switch_runbook_snapshot_hash(kill_switch_runbook_snapshot)
        == kill_switch_runbook_snapshot.evidence_hash
        == command.kill_switch_runbook_snapshot_hash
    )
    provider_limits_snapshot_bound = _provider_limits_snapshot_bound(
        command=command,
        materialization_gate=materialization_gate,
        snapshot=provider_limits_snapshot,
    )
    network_route_snapshot_bound = _control_snapshot_bound(
        command=command,
        materialization_gate=materialization_gate,
        snapshot=network_route_snapshot,
    )
    secret_manager_snapshot_bound = _control_snapshot_bound(
        command=command,
        materialization_gate=materialization_gate,
        snapshot=secret_manager_snapshot,
    )
    rollback_runbook_snapshot_bound = _control_snapshot_bound(
        command=command,
        materialization_gate=materialization_gate,
        snapshot=rollback_runbook_snapshot,
    )
    kill_switch_runbook_snapshot_bound = _kill_switch_runbook_snapshot_bound(
        command=command,
        materialization_gate=materialization_gate,
        snapshot=kill_switch_runbook_snapshot,
    )
    blocking_reasons = _socket_secret_adr_blocking_reasons(
        command=command,
        materialization_plan_gate_hash_valid=materialization_plan_gate_hash_valid,
        materialization_plan_gate_ready=materialization_plan_gate_ready,
        materialization_plan_gate_bound=materialization_plan_gate_bound,
        provider_limits_snapshot_hash_valid=provider_limits_snapshot_hash_valid,
        provider_limits_snapshot_bound=provider_limits_snapshot_bound,
        provider_limits_snapshot=provider_limits_snapshot,
        network_route_snapshot_hash_valid=network_route_snapshot_hash_valid,
        network_route_snapshot_bound=network_route_snapshot_bound,
        network_route_snapshot=network_route_snapshot,
        secret_manager_snapshot_hash_valid=secret_manager_snapshot_hash_valid,
        secret_manager_snapshot_bound=secret_manager_snapshot_bound,
        secret_manager_snapshot=secret_manager_snapshot,
        rollback_runbook_snapshot_hash_valid=rollback_runbook_snapshot_hash_valid,
        rollback_runbook_snapshot_bound=rollback_runbook_snapshot_bound,
        rollback_runbook_snapshot=rollback_runbook_snapshot,
        kill_switch_runbook_snapshot_hash_valid=kill_switch_runbook_snapshot_hash_valid,
        kill_switch_runbook_snapshot_bound=kill_switch_runbook_snapshot_bound,
        kill_switch_runbook_snapshot=kill_switch_runbook_snapshot,
    )
    ready = not blocking_reasons
    draft = LegacySqlConnectorSocketSecretImplementationAdrGateEvidence(
        tenant_id=materialization_gate.tenant_id,
        module_id=materialization_gate.module_id,
        source_system_ref=materialization_gate.source_system_ref,
        connector_kind=materialization_gate.connector_kind,
        architecture_decision_record_ref=command.architecture_decision_record_ref,
        materialization_plan_gate_evidence_hash=materialization_gate.evidence_hash,
        provider_limits_snapshot_hash=provider_limits_snapshot.evidence_hash,
        network_route_snapshot_hash=network_route_snapshot.evidence_hash,
        secret_manager_snapshot_hash=secret_manager_snapshot.evidence_hash,
        rollback_runbook_snapshot_hash=rollback_runbook_snapshot.evidence_hash,
        kill_switch_runbook_snapshot_hash=kill_switch_runbook_snapshot.evidence_hash,
        materialization_plan_gate_hash_valid=materialization_plan_gate_hash_valid,
        materialization_plan_gate_ready=materialization_plan_gate_ready,
        materialization_plan_gate_bound=materialization_plan_gate_bound,
        provider_limits_snapshot_hash_valid=provider_limits_snapshot_hash_valid,
        provider_limits_snapshot_bound=provider_limits_snapshot_bound,
        provider_limits_attested=provider_limits_snapshot.provider_limits_attested,
        network_route_snapshot_hash_valid=network_route_snapshot_hash_valid,
        network_route_snapshot_bound=network_route_snapshot_bound,
        network_route_approved=network_route_snapshot.approved_route_bound_to_tenant,
        tenant_route_isolated=network_route_snapshot.tenant_route_isolated,
        egress_allowlist_reviewed=network_route_snapshot.egress_allowlist_reviewed,
        inbound_access_forbidden=network_route_snapshot.inbound_access_forbidden,
        secret_manager_snapshot_hash_valid=secret_manager_snapshot_hash_valid,
        secret_manager_snapshot_bound=secret_manager_snapshot_bound,
        secret_manager_ready=secret_manager_snapshot.secret_manager_ready,
        tenant_kms_required=secret_manager_snapshot.tenant_kms_required,
        no_plaintext_secret_reviewed=secret_manager_snapshot.no_plaintext_secret_reviewed,
        rollback_runbook_snapshot_hash_valid=rollback_runbook_snapshot_hash_valid,
        rollback_runbook_snapshot_bound=rollback_runbook_snapshot_bound,
        rollback_runbook_tested=rollback_runbook_snapshot.rollback_runbook_tested,
        recover_without_import_writes=rollback_runbook_snapshot.recover_without_import_writes,
        destructive_rollback_forbidden=rollback_runbook_snapshot.destructive_rollback_forbidden,
        kill_switch_runbook_snapshot_hash_valid=kill_switch_runbook_snapshot_hash_valid,
        kill_switch_runbook_snapshot_bound=kill_switch_runbook_snapshot_bound,
        kill_switch_armed=kill_switch_runbook_snapshot.kill_switch_armed,
        kill_switch_runbook_tested=kill_switch_runbook_snapshot.kill_switch_runbook_tested,
        tenant_connection_disabled=kill_switch_runbook_snapshot.tenant_connection_disabled,
        global_connection_disabled=kill_switch_runbook_snapshot.global_connection_disabled,
        manual_abort_requested=kill_switch_runbook_snapshot.manual_abort_requested,
        break_glass_allowed=kill_switch_runbook_snapshot.break_glass_allowed,
        adr_review_requested=command.adr_review_requested,
        implementation_adr_ready=ready,
        socket_implementation_requested=command.socket_implementation_requested,
        secret_materialization_requested=command.secret_materialization_requested,
        executor_code_requested=command.executor_code_requested,
        raw_data_access_requested=command.raw_data_access_requested,
        import_dry_run_requested=command.import_dry_run_requested,
        import_write_requested=command.import_write_requested,
        destructive_actions_requested=command.destructive_actions_requested,
        gate_status=(
            LegacySqlConnectorSocketSecretImplementationAdrGateStatus.READY
            if ready
            else LegacySqlConnectorSocketSecretImplementationAdrGateStatus.BLOCKED
        ),
        blocking_reasons=blocking_reasons,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_socket_secret_implementation_adr_gate_hash(draft)}
    )


def build_legacy_sql_connector_socket_secret_provider_limits_snapshot_hash(
    snapshot: LegacySqlConnectorSocketSecretProviderLimitsSnapshot,
) -> str:
    return stable_hash(canonical_json(snapshot.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_socket_secret_network_route_snapshot_hash(
    snapshot: LegacySqlConnectorSocketSecretNetworkRouteSnapshot,
) -> str:
    return stable_hash(canonical_json(snapshot.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_socket_secret_secret_manager_snapshot_hash(
    snapshot: LegacySqlConnectorSocketSecretSecretManagerSnapshot,
) -> str:
    return stable_hash(canonical_json(snapshot.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_socket_secret_rollback_runbook_snapshot_hash(
    snapshot: LegacySqlConnectorSocketSecretRollbackRunbookSnapshot,
) -> str:
    return stable_hash(canonical_json(snapshot.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_socket_secret_kill_switch_runbook_snapshot_hash(
    snapshot: LegacySqlConnectorSocketSecretKillSwitchRunbookSnapshot,
) -> str:
    return stable_hash(canonical_json(snapshot.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_socket_secret_implementation_adr_gate_hash(
    gate: LegacySqlConnectorSocketSecretImplementationAdrGateEvidence,
) -> str:
    return stable_hash(canonical_json(gate.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_socket_secret_implementation_adr_gate_smoke_report_hash(
    report: LegacySqlConnectorSocketSecretImplementationAdrGateSmokeReport,
) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def run_legacy_sql_connector_socket_secret_implementation_adr_gate_smoke_from_env(
    environ: Mapping[str, str] | None = None,
) -> LegacySqlConnectorSocketSecretImplementationAdrGateSmokeReport:
    env = os.environ if environ is None else environ
    checked_by = env.get(
        "SUITE_LEGACY_SQL_CONNECTOR_SOCKET_SECRET_IMPLEMENTATION_ADR_GATE_CHECKED_BY",
        "legacy-sql-connector-socket-secret-implementation-adr-gate-smoke",
    )
    checked_at = datetime.now(UTC)
    store_backend = LegacySqlConnectorRealConnectionPolicyStoreBackend(
        env.get(
            "SUITE_LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_POLICY_STORE_BACKEND",
            LegacySqlConnectorRealConnectionPolicyStoreBackend.JSONL.value,
        )
    )
    bundle, materialization_gate, kill_switch_snapshot = _build_ready_materialization_chain(
        env=env,
        checked_by=checked_by,
        checked_at=checked_at,
    )
    provider_limits_snapshot = build_legacy_sql_connector_socket_secret_provider_limits_snapshot(
        materialization_gate=materialization_gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=31),
    )
    network_route_snapshot = build_legacy_sql_connector_socket_secret_network_route_snapshot(
        materialization_gate=materialization_gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=32),
    )
    secret_manager_snapshot = build_legacy_sql_connector_socket_secret_secret_manager_snapshot(
        materialization_gate=materialization_gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=33),
    )
    rollback_runbook_snapshot = build_legacy_sql_connector_socket_secret_rollback_runbook_snapshot(
        materialization_gate=materialization_gate,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=34),
    )
    kill_switch_runbook_snapshot = build_legacy_sql_connector_socket_secret_kill_switch_runbook_snapshot(
        materialization_gate=materialization_gate,
        kill_switch_snapshot=kill_switch_snapshot,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=35),
    )
    command = build_legacy_sql_connector_socket_secret_implementation_adr_gate_command(
        materialization_gate=materialization_gate,
        provider_limits_snapshot=provider_limits_snapshot,
        network_route_snapshot=network_route_snapshot,
        secret_manager_snapshot=secret_manager_snapshot,
        rollback_runbook_snapshot=rollback_runbook_snapshot,
        kill_switch_runbook_snapshot=kill_switch_runbook_snapshot,
        requested_by=checked_by,
    )
    gate = build_legacy_sql_connector_socket_secret_implementation_adr_gate(
        command=command,
        bundle=bundle,
        materialization_gate=materialization_gate,
        provider_limits_snapshot=provider_limits_snapshot,
        network_route_snapshot=network_route_snapshot,
        secret_manager_snapshot=secret_manager_snapshot,
        rollback_runbook_snapshot=rollback_runbook_snapshot,
        kill_switch_runbook_snapshot=kill_switch_runbook_snapshot,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=36),
    )
    materialization_plan_missing_blocked = _materialization_plan_missing_blocked(
        command=command,
        bundle=bundle,
        materialization_gate=materialization_gate,
        provider_limits_snapshot=provider_limits_snapshot,
        network_route_snapshot=network_route_snapshot,
        secret_manager_snapshot=secret_manager_snapshot,
        rollback_runbook_snapshot=rollback_runbook_snapshot,
        kill_switch_runbook_snapshot=kill_switch_runbook_snapshot,
        checked_by=checked_by,
        checked_at=checked_at + timedelta(seconds=37),
    )
    provider_limits_missing_blocked = _provider_limits_missing_blocked(
        command=command,
        bundle=bundle,
        materialization_gate=materialization_gate,
        provider_limits_snapshot=provider_limits_snapshot,
        network_route_snapshot=network_route_snapshot,
        secret_manager_snapshot=secret_manager_snapshot,
        rollback_runbook_snapshot=rollback_runbook_snapshot,
        kill_switch_runbook_snapshot=kill_switch_runbook_snapshot,
        checked_by=checked_by,
        checked_at=checked_at + timedelta(seconds=38),
    )
    network_route_missing_blocked = _network_route_missing_blocked(
        command=command,
        bundle=bundle,
        materialization_gate=materialization_gate,
        provider_limits_snapshot=provider_limits_snapshot,
        network_route_snapshot=network_route_snapshot,
        secret_manager_snapshot=secret_manager_snapshot,
        rollback_runbook_snapshot=rollback_runbook_snapshot,
        kill_switch_runbook_snapshot=kill_switch_runbook_snapshot,
        checked_by=checked_by,
        checked_at=checked_at + timedelta(seconds=39),
    )
    secret_manager_missing_blocked = _secret_manager_missing_blocked(
        command=command,
        bundle=bundle,
        materialization_gate=materialization_gate,
        provider_limits_snapshot=provider_limits_snapshot,
        network_route_snapshot=network_route_snapshot,
        secret_manager_snapshot=secret_manager_snapshot,
        rollback_runbook_snapshot=rollback_runbook_snapshot,
        kill_switch_runbook_snapshot=kill_switch_runbook_snapshot,
        checked_by=checked_by,
        checked_at=checked_at + timedelta(seconds=40),
    )
    rollback_runbook_missing_blocked = _rollback_runbook_missing_blocked(
        command=command,
        bundle=bundle,
        materialization_gate=materialization_gate,
        provider_limits_snapshot=provider_limits_snapshot,
        network_route_snapshot=network_route_snapshot,
        secret_manager_snapshot=secret_manager_snapshot,
        rollback_runbook_snapshot=rollback_runbook_snapshot,
        kill_switch_runbook_snapshot=kill_switch_runbook_snapshot,
        checked_by=checked_by,
        checked_at=checked_at + timedelta(seconds=41),
    )
    kill_switch_runbook_missing_blocked = _kill_switch_runbook_missing_blocked(
        command=command,
        bundle=bundle,
        materialization_gate=materialization_gate,
        provider_limits_snapshot=provider_limits_snapshot,
        network_route_snapshot=network_route_snapshot,
        secret_manager_snapshot=secret_manager_snapshot,
        rollback_runbook_snapshot=rollback_runbook_snapshot,
        kill_switch_runbook_snapshot=kill_switch_runbook_snapshot,
        checked_by=checked_by,
        checked_at=checked_at + timedelta(seconds=42),
    )
    implementation_request_blocked = _implementation_request_blocked(
        command=command,
        bundle=bundle,
        materialization_gate=materialization_gate,
        provider_limits_snapshot=provider_limits_snapshot,
        network_route_snapshot=network_route_snapshot,
        secret_manager_snapshot=secret_manager_snapshot,
        rollback_runbook_snapshot=rollback_runbook_snapshot,
        kill_switch_runbook_snapshot=kill_switch_runbook_snapshot,
        checked_by=checked_by,
        checked_at=checked_at + timedelta(seconds=43),
    )
    implementation_adr_ready = (
        gate.gate_status == LegacySqlConnectorSocketSecretImplementationAdrGateStatus.READY
        and gate.implementation_adr_ready
        and materialization_plan_missing_blocked
        and provider_limits_missing_blocked
        and network_route_missing_blocked
        and secret_manager_missing_blocked
        and rollback_runbook_missing_blocked
        and kill_switch_runbook_missing_blocked
        and implementation_request_blocked
        and not gate.socket_implementation_allowed
        and not gate.secret_materialization_allowed
        and not gate.executor_code_allowed
        and not gate.real_connection_opened
    )
    draft = LegacySqlConnectorSocketSecretImplementationAdrGateSmokeReport(
        tenant_id=bundle.tenant_id,
        store_backend=store_backend,
        materialization_plan_gate_evidence_hash=materialization_gate.evidence_hash,
        provider_limits_snapshot_hash=provider_limits_snapshot.evidence_hash,
        network_route_snapshot_hash=network_route_snapshot.evidence_hash,
        secret_manager_snapshot_hash=secret_manager_snapshot.evidence_hash,
        rollback_runbook_snapshot_hash=rollback_runbook_snapshot.evidence_hash,
        kill_switch_runbook_snapshot_hash=kill_switch_runbook_snapshot.evidence_hash,
        adr_gate_evidence_hash=gate.evidence_hash,
        implementation_adr_ready=implementation_adr_ready,
        materialization_plan_gate_required=gate.materialization_plan_gate_bound
        and gate.materialization_plan_gate_ready,
        provider_limits_snapshot_required=gate.provider_limits_snapshot_bound and gate.provider_limits_attested,
        network_route_snapshot_required=(
            gate.network_route_snapshot_bound and gate.network_route_approved and gate.tenant_route_isolated
        ),
        secret_manager_snapshot_required=(
            gate.secret_manager_snapshot_bound and gate.secret_manager_ready and gate.tenant_kms_required
        ),
        rollback_runbook_snapshot_required=(
            gate.rollback_runbook_snapshot_bound and gate.rollback_runbook_tested and gate.recover_without_import_writes
        ),
        kill_switch_runbook_snapshot_required=(
            gate.kill_switch_runbook_snapshot_bound and gate.kill_switch_runbook_tested and gate.kill_switch_armed
        ),
        materialization_plan_missing_blocked=materialization_plan_missing_blocked,
        provider_limits_missing_blocked=provider_limits_missing_blocked,
        network_route_missing_blocked=network_route_missing_blocked,
        secret_manager_missing_blocked=secret_manager_missing_blocked,
        rollback_runbook_missing_blocked=rollback_runbook_missing_blocked,
        kill_switch_runbook_missing_blocked=kill_switch_runbook_missing_blocked,
        implementation_request_blocked=implementation_request_blocked,
        future_socket_secret_runtime_pr_required=gate.future_socket_secret_runtime_pr_required,
        future_secret_manager_runtime_binding_required=gate.future_secret_manager_runtime_binding_required,
        future_network_route_runtime_binding_required=gate.future_network_route_runtime_binding_required,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    _assert_socket_secret_adr_safe(draft)
    return draft.model_copy(
        update={
            "evidence_hash": build_legacy_sql_connector_socket_secret_implementation_adr_gate_smoke_report_hash(draft)
        }
    )


def exit_code_for_report(report: LegacySqlConnectorSocketSecretImplementationAdrGateSmokeReport) -> int:
    return 0 if report.implementation_adr_ready else 1


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Legacy SQL socket/secret implementation ADR gate smoke.")
    parser.add_argument("--once", action="store_true", help="Run one non-executing socket/secret ADR smoke and exit.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the socket/secret ADR report.")
    args = parser.parse_args(argv)
    del args.once

    report = run_legacy_sql_connector_socket_secret_implementation_adr_gate_smoke_from_env()
    print(json.dumps(report.model_dump(mode="json"), indent=2 if args.pretty else None, sort_keys=True))
    raise SystemExit(exit_code_for_report(report))


def _build_ready_materialization_chain(
    *,
    env: Mapping[str, str],
    checked_by: str,
    checked_at: datetime,
) -> tuple[
    LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    LegacySqlConnectorMaterializationPlanGateEvidence,
    LegacySqlConnectorMaterializationKillSwitchSnapshot,
]:
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
    stored_bundle = store.append(bundle)
    fetched_bundle = store.get(
        tenant_id=stored_bundle.tenant_id,
        executor_contract_evidence_hash=stored_bundle.executor_contract_evidence_hash,
    )
    review_gate = _build_ready_materialization_review_gate(
        bundle=fetched_bundle,
        checked_by=checked_by,
        checked_at=checked_at + timedelta(seconds=19),
    )
    provider_profile_snapshot = build_legacy_sql_connector_materialization_provider_profile_snapshot(
        bundle=fetched_bundle,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=23),
    )
    operator_mfa_snapshot = build_legacy_sql_connector_materialization_operator_mfa_snapshot(
        bundle=fetched_bundle,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=24),
    )
    kill_switch_snapshot = build_legacy_sql_connector_materialization_kill_switch_snapshot(
        bundle=fetched_bundle,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=25),
    )
    command = build_legacy_sql_connector_materialization_plan_gate_command(
        bundle=fetched_bundle,
        review_gate=review_gate,
        provider_profile_snapshot=provider_profile_snapshot,
        operator_mfa_snapshot=operator_mfa_snapshot,
        kill_switch_snapshot=kill_switch_snapshot,
        requested_by=checked_by,
    )
    materialization_gate = build_legacy_sql_connector_materialization_plan_gate(
        command=command,
        bundle=fetched_bundle,
        review_gate=review_gate,
        provider_profile_snapshot=provider_profile_snapshot,
        operator_mfa_snapshot=operator_mfa_snapshot,
        kill_switch_snapshot=kill_switch_snapshot,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=26),
    )
    return fetched_bundle, materialization_gate, kill_switch_snapshot


def _materialization_plan_gate_bound(
    *,
    command: LegacySqlConnectorSocketSecretImplementationAdrGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    materialization_gate: LegacySqlConnectorMaterializationPlanGateEvidence,
) -> bool:
    return (
        command.tenant_id == bundle.tenant_id == materialization_gate.tenant_id
        and command.module_id == bundle.module_id == materialization_gate.module_id
        and command.source_system_ref == bundle.source_system_ref == materialization_gate.source_system_ref
        and command.connector_kind == bundle.connector_kind == materialization_gate.connector_kind
        and command.materialization_plan_gate_evidence_hash == materialization_gate.evidence_hash
        and materialization_gate.policy_bundle_evidence_hash == bundle.evidence_hash
        and materialization_gate.executor_contract_evidence_hash == bundle.executor_contract_evidence_hash
        and materialization_gate.kill_switch_policy_hash == bundle.kill_switch_policy_hash
        and not materialization_gate.socket_materialization_allowed
        and not materialization_gate.secret_materialization_allowed
        and not materialization_gate.execution_implementation_allowed
        and not materialization_gate.network_socket_opened
        and not materialization_gate.secret_material_resolved
    )


def _provider_limits_snapshot_bound(
    *,
    command: LegacySqlConnectorSocketSecretImplementationAdrGateCommand,
    materialization_gate: LegacySqlConnectorMaterializationPlanGateEvidence,
    snapshot: LegacySqlConnectorSocketSecretProviderLimitsSnapshot,
) -> bool:
    return (
        command.tenant_id == materialization_gate.tenant_id == snapshot.tenant_id
        and command.module_id == materialization_gate.module_id == snapshot.module_id
        and command.source_system_ref == materialization_gate.source_system_ref == snapshot.source_system_ref
        and command.connector_kind == materialization_gate.connector_kind == snapshot.connector_kind
        and snapshot.materialization_plan_gate_evidence_hash == materialization_gate.evidence_hash
        and snapshot.provider_profile_snapshot_hash == materialization_gate.provider_profile_snapshot_hash
    )


def _control_snapshot_bound(
    *,
    command: LegacySqlConnectorSocketSecretImplementationAdrGateCommand,
    materialization_gate: LegacySqlConnectorMaterializationPlanGateEvidence,
    snapshot: (
        LegacySqlConnectorSocketSecretNetworkRouteSnapshot
        | LegacySqlConnectorSocketSecretSecretManagerSnapshot
        | LegacySqlConnectorSocketSecretRollbackRunbookSnapshot
        | LegacySqlConnectorSocketSecretKillSwitchRunbookSnapshot
    ),
) -> bool:
    return (
        command.tenant_id == materialization_gate.tenant_id == snapshot.tenant_id
        and command.module_id == materialization_gate.module_id == snapshot.module_id
        and command.source_system_ref == materialization_gate.source_system_ref == snapshot.source_system_ref
        and command.connector_kind == materialization_gate.connector_kind == snapshot.connector_kind
        and snapshot.materialization_plan_gate_evidence_hash == materialization_gate.evidence_hash
    )


def _kill_switch_runbook_snapshot_bound(
    *,
    command: LegacySqlConnectorSocketSecretImplementationAdrGateCommand,
    materialization_gate: LegacySqlConnectorMaterializationPlanGateEvidence,
    snapshot: LegacySqlConnectorSocketSecretKillSwitchRunbookSnapshot,
) -> bool:
    return (
        _control_snapshot_bound(command=command, materialization_gate=materialization_gate, snapshot=snapshot)
        and snapshot.kill_switch_snapshot_hash == materialization_gate.kill_switch_snapshot_hash
        and snapshot.kill_switch_policy_hash == materialization_gate.kill_switch_policy_hash
    )


def _socket_secret_adr_blocking_reasons(
    *,
    command: LegacySqlConnectorSocketSecretImplementationAdrGateCommand,
    materialization_plan_gate_hash_valid: bool,
    materialization_plan_gate_ready: bool,
    materialization_plan_gate_bound: bool,
    provider_limits_snapshot_hash_valid: bool,
    provider_limits_snapshot_bound: bool,
    provider_limits_snapshot: LegacySqlConnectorSocketSecretProviderLimitsSnapshot,
    network_route_snapshot_hash_valid: bool,
    network_route_snapshot_bound: bool,
    network_route_snapshot: LegacySqlConnectorSocketSecretNetworkRouteSnapshot,
    secret_manager_snapshot_hash_valid: bool,
    secret_manager_snapshot_bound: bool,
    secret_manager_snapshot: LegacySqlConnectorSocketSecretSecretManagerSnapshot,
    rollback_runbook_snapshot_hash_valid: bool,
    rollback_runbook_snapshot_bound: bool,
    rollback_runbook_snapshot: LegacySqlConnectorSocketSecretRollbackRunbookSnapshot,
    kill_switch_runbook_snapshot_hash_valid: bool,
    kill_switch_runbook_snapshot_bound: bool,
    kill_switch_runbook_snapshot: LegacySqlConnectorSocketSecretKillSwitchRunbookSnapshot,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not materialization_plan_gate_hash_valid:
        reasons.append("materialization_plan_gate_hash_invalid")
    if not materialization_plan_gate_ready:
        reasons.append("materialization_plan_gate_not_ready")
    if not materialization_plan_gate_bound:
        reasons.append("materialization_plan_gate_not_bound")
    if not provider_limits_snapshot_hash_valid:
        reasons.append("provider_limits_snapshot_hash_invalid")
    if not provider_limits_snapshot_bound:
        reasons.append("provider_limits_snapshot_not_bound")
    if not provider_limits_snapshot.provider_limits_attested:
        reasons.append("provider_limits_not_attested")
    if not network_route_snapshot_hash_valid:
        reasons.append("network_route_snapshot_hash_invalid")
    if not network_route_snapshot_bound:
        reasons.append("network_route_snapshot_not_bound")
    if not network_route_snapshot.approved_route_bound_to_tenant:
        reasons.append("network_route_not_approved")
    if not network_route_snapshot.tenant_route_isolated:
        reasons.append("tenant_route_not_isolated")
    if not network_route_snapshot.egress_allowlist_reviewed:
        reasons.append("egress_allowlist_not_reviewed")
    if not network_route_snapshot.inbound_access_forbidden:
        reasons.append("inbound_access_not_forbidden")
    if network_route_snapshot.default_compose_legacy_network_enabled or network_route_snapshot.network_socket_opened:
        reasons.append("network_route_materialization_attempted")
    if not secret_manager_snapshot_hash_valid:
        reasons.append("secret_manager_snapshot_hash_invalid")
    if not secret_manager_snapshot_bound:
        reasons.append("secret_manager_snapshot_not_bound")
    if not secret_manager_snapshot.secret_manager_ready:
        reasons.append("secret_manager_not_ready")
    if not secret_manager_snapshot.tenant_kms_required:
        reasons.append("tenant_kms_not_required")
    if not secret_manager_snapshot.no_plaintext_secret_reviewed:
        reasons.append("plaintext_secret_review_missing")
    if secret_manager_snapshot.direct_connection_secret_ref_allowed or secret_manager_snapshot.secret_material_resolved:
        reasons.append("secret_materialization_attempted")
    if not rollback_runbook_snapshot_hash_valid:
        reasons.append("rollback_runbook_snapshot_hash_invalid")
    if not rollback_runbook_snapshot_bound:
        reasons.append("rollback_runbook_snapshot_not_bound")
    if not rollback_runbook_snapshot.rollback_runbook_tested:
        reasons.append("rollback_runbook_not_tested")
    if not rollback_runbook_snapshot.recover_without_import_writes:
        reasons.append("recover_without_import_writes_missing")
    if not rollback_runbook_snapshot.destructive_rollback_forbidden:
        reasons.append("destructive_rollback_not_forbidden")
    if rollback_runbook_snapshot.import_write_allowed or rollback_runbook_snapshot.destructive_actions_allowed:
        reasons.append("rollback_write_attempted")
    if not kill_switch_runbook_snapshot_hash_valid:
        reasons.append("kill_switch_runbook_snapshot_hash_invalid")
    if not kill_switch_runbook_snapshot_bound:
        reasons.append("kill_switch_runbook_snapshot_not_bound")
    if not kill_switch_runbook_snapshot.kill_switch_armed:
        reasons.append("kill_switch_not_armed")
    if not kill_switch_runbook_snapshot.kill_switch_runbook_tested:
        reasons.append("kill_switch_runbook_not_tested")
    if kill_switch_runbook_snapshot.tenant_connection_disabled:
        reasons.append("tenant_connection_kill_switch_disabled")
    if kill_switch_runbook_snapshot.global_connection_disabled:
        reasons.append("global_connection_kill_switch_disabled")
    if kill_switch_runbook_snapshot.manual_abort_requested:
        reasons.append("manual_abort_requested")
    if kill_switch_runbook_snapshot.break_glass_allowed:
        reasons.append("break_glass_allowed")
    if not command.adr_review_requested:
        reasons.append("adr_review_not_requested")
    if command.socket_implementation_requested:
        reasons.append("socket_implementation_requires_future_pr_gate")
    if command.secret_materialization_requested:
        reasons.append("secret_materialization_requires_future_pr_gate")
    if command.executor_code_requested:
        reasons.append("executor_code_requires_future_pr_gate")
    if command.raw_data_access_requested:
        reasons.append("raw_data_access_requires_future_data_gate")
    if command.import_dry_run_requested:
        reasons.append("import_dry_run_requires_future_import_gate")
    if command.import_write_requested:
        reasons.append("import_write_requires_future_import_gate")
    if command.destructive_actions_requested:
        reasons.append("destructive_actions_require_human_confirmation_gate")
    return tuple(dict.fromkeys(reasons))


def _materialization_plan_missing_blocked(
    *,
    command: LegacySqlConnectorSocketSecretImplementationAdrGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    materialization_gate: LegacySqlConnectorMaterializationPlanGateEvidence,
    provider_limits_snapshot: LegacySqlConnectorSocketSecretProviderLimitsSnapshot,
    network_route_snapshot: LegacySqlConnectorSocketSecretNetworkRouteSnapshot,
    secret_manager_snapshot: LegacySqlConnectorSocketSecretSecretManagerSnapshot,
    rollback_runbook_snapshot: LegacySqlConnectorSocketSecretRollbackRunbookSnapshot,
    kill_switch_runbook_snapshot: LegacySqlConnectorSocketSecretKillSwitchRunbookSnapshot,
    checked_by: str,
    checked_at: datetime,
) -> bool:
    blocked_plan = materialization_gate.model_copy(
        update={
            "gate_status": LegacySqlConnectorMaterializationPlanGateStatus.BLOCKED,
            "materialization_plan_ready": False,
            "blocking_reasons": ("adr_gate_test_materialization_plan_missing",),
            "checked_at_utc": checked_at,
            "evidence_hash": ZERO_HASH,
        }
    )
    blocked_plan = blocked_plan.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_materialization_plan_gate_hash(blocked_plan)}
    )
    blocked = build_legacy_sql_connector_socket_secret_implementation_adr_gate(
        command=command.model_copy(update={"materialization_plan_gate_evidence_hash": blocked_plan.evidence_hash}),
        bundle=bundle,
        materialization_gate=blocked_plan,
        provider_limits_snapshot=provider_limits_snapshot,
        network_route_snapshot=network_route_snapshot,
        secret_manager_snapshot=secret_manager_snapshot,
        rollback_runbook_snapshot=rollback_runbook_snapshot,
        kill_switch_runbook_snapshot=kill_switch_runbook_snapshot,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        blocked.gate_status == LegacySqlConnectorSocketSecretImplementationAdrGateStatus.BLOCKED
        and "materialization_plan_gate_not_ready" in blocked.blocking_reasons
    )


def _provider_limits_missing_blocked(
    *,
    command: LegacySqlConnectorSocketSecretImplementationAdrGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    materialization_gate: LegacySqlConnectorMaterializationPlanGateEvidence,
    provider_limits_snapshot: LegacySqlConnectorSocketSecretProviderLimitsSnapshot,
    network_route_snapshot: LegacySqlConnectorSocketSecretNetworkRouteSnapshot,
    secret_manager_snapshot: LegacySqlConnectorSocketSecretSecretManagerSnapshot,
    rollback_runbook_snapshot: LegacySqlConnectorSocketSecretRollbackRunbookSnapshot,
    kill_switch_runbook_snapshot: LegacySqlConnectorSocketSecretKillSwitchRunbookSnapshot,
    checked_by: str,
    checked_at: datetime,
) -> bool:
    blocked_limits = provider_limits_snapshot.model_copy(
        update={"provider_limits_attested": False, "checked_at_utc": checked_at, "evidence_hash": ZERO_HASH}
    )
    blocked_limits = blocked_limits.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_socket_secret_provider_limits_snapshot_hash(blocked_limits)}
    )
    blocked = build_legacy_sql_connector_socket_secret_implementation_adr_gate(
        command=command.model_copy(update={"provider_limits_snapshot_hash": blocked_limits.evidence_hash}),
        bundle=bundle,
        materialization_gate=materialization_gate,
        provider_limits_snapshot=blocked_limits,
        network_route_snapshot=network_route_snapshot,
        secret_manager_snapshot=secret_manager_snapshot,
        rollback_runbook_snapshot=rollback_runbook_snapshot,
        kill_switch_runbook_snapshot=kill_switch_runbook_snapshot,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        blocked.gate_status == LegacySqlConnectorSocketSecretImplementationAdrGateStatus.BLOCKED
        and "provider_limits_not_attested" in blocked.blocking_reasons
    )


def _network_route_missing_blocked(
    *,
    command: LegacySqlConnectorSocketSecretImplementationAdrGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    materialization_gate: LegacySqlConnectorMaterializationPlanGateEvidence,
    provider_limits_snapshot: LegacySqlConnectorSocketSecretProviderLimitsSnapshot,
    network_route_snapshot: LegacySqlConnectorSocketSecretNetworkRouteSnapshot,
    secret_manager_snapshot: LegacySqlConnectorSocketSecretSecretManagerSnapshot,
    rollback_runbook_snapshot: LegacySqlConnectorSocketSecretRollbackRunbookSnapshot,
    kill_switch_runbook_snapshot: LegacySqlConnectorSocketSecretKillSwitchRunbookSnapshot,
    checked_by: str,
    checked_at: datetime,
) -> bool:
    blocked_route = network_route_snapshot.model_copy(
        update={"approved_route_bound_to_tenant": False, "checked_at_utc": checked_at, "evidence_hash": ZERO_HASH}
    )
    blocked_route = blocked_route.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_socket_secret_network_route_snapshot_hash(blocked_route)}
    )
    blocked = build_legacy_sql_connector_socket_secret_implementation_adr_gate(
        command=command.model_copy(update={"network_route_snapshot_hash": blocked_route.evidence_hash}),
        bundle=bundle,
        materialization_gate=materialization_gate,
        provider_limits_snapshot=provider_limits_snapshot,
        network_route_snapshot=blocked_route,
        secret_manager_snapshot=secret_manager_snapshot,
        rollback_runbook_snapshot=rollback_runbook_snapshot,
        kill_switch_runbook_snapshot=kill_switch_runbook_snapshot,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        blocked.gate_status == LegacySqlConnectorSocketSecretImplementationAdrGateStatus.BLOCKED
        and "network_route_not_approved" in blocked.blocking_reasons
    )


def _secret_manager_missing_blocked(
    *,
    command: LegacySqlConnectorSocketSecretImplementationAdrGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    materialization_gate: LegacySqlConnectorMaterializationPlanGateEvidence,
    provider_limits_snapshot: LegacySqlConnectorSocketSecretProviderLimitsSnapshot,
    network_route_snapshot: LegacySqlConnectorSocketSecretNetworkRouteSnapshot,
    secret_manager_snapshot: LegacySqlConnectorSocketSecretSecretManagerSnapshot,
    rollback_runbook_snapshot: LegacySqlConnectorSocketSecretRollbackRunbookSnapshot,
    kill_switch_runbook_snapshot: LegacySqlConnectorSocketSecretKillSwitchRunbookSnapshot,
    checked_by: str,
    checked_at: datetime,
) -> bool:
    blocked_secret_manager = secret_manager_snapshot.model_copy(
        update={"secret_manager_ready": False, "checked_at_utc": checked_at, "evidence_hash": ZERO_HASH}
    )
    blocked_secret_manager = blocked_secret_manager.model_copy(
        update={
            "evidence_hash": build_legacy_sql_connector_socket_secret_secret_manager_snapshot_hash(
                blocked_secret_manager
            )
        }
    )
    blocked = build_legacy_sql_connector_socket_secret_implementation_adr_gate(
        command=command.model_copy(update={"secret_manager_snapshot_hash": blocked_secret_manager.evidence_hash}),
        bundle=bundle,
        materialization_gate=materialization_gate,
        provider_limits_snapshot=provider_limits_snapshot,
        network_route_snapshot=network_route_snapshot,
        secret_manager_snapshot=blocked_secret_manager,
        rollback_runbook_snapshot=rollback_runbook_snapshot,
        kill_switch_runbook_snapshot=kill_switch_runbook_snapshot,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        blocked.gate_status == LegacySqlConnectorSocketSecretImplementationAdrGateStatus.BLOCKED
        and "secret_manager_not_ready" in blocked.blocking_reasons
    )


def _rollback_runbook_missing_blocked(
    *,
    command: LegacySqlConnectorSocketSecretImplementationAdrGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    materialization_gate: LegacySqlConnectorMaterializationPlanGateEvidence,
    provider_limits_snapshot: LegacySqlConnectorSocketSecretProviderLimitsSnapshot,
    network_route_snapshot: LegacySqlConnectorSocketSecretNetworkRouteSnapshot,
    secret_manager_snapshot: LegacySqlConnectorSocketSecretSecretManagerSnapshot,
    rollback_runbook_snapshot: LegacySqlConnectorSocketSecretRollbackRunbookSnapshot,
    kill_switch_runbook_snapshot: LegacySqlConnectorSocketSecretKillSwitchRunbookSnapshot,
    checked_by: str,
    checked_at: datetime,
) -> bool:
    blocked_rollback = rollback_runbook_snapshot.model_copy(
        update={"rollback_runbook_tested": False, "checked_at_utc": checked_at, "evidence_hash": ZERO_HASH}
    )
    blocked_rollback = blocked_rollback.model_copy(
        update={
            "evidence_hash": build_legacy_sql_connector_socket_secret_rollback_runbook_snapshot_hash(blocked_rollback)
        }
    )
    blocked = build_legacy_sql_connector_socket_secret_implementation_adr_gate(
        command=command.model_copy(update={"rollback_runbook_snapshot_hash": blocked_rollback.evidence_hash}),
        bundle=bundle,
        materialization_gate=materialization_gate,
        provider_limits_snapshot=provider_limits_snapshot,
        network_route_snapshot=network_route_snapshot,
        secret_manager_snapshot=secret_manager_snapshot,
        rollback_runbook_snapshot=blocked_rollback,
        kill_switch_runbook_snapshot=kill_switch_runbook_snapshot,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        blocked.gate_status == LegacySqlConnectorSocketSecretImplementationAdrGateStatus.BLOCKED
        and "rollback_runbook_not_tested" in blocked.blocking_reasons
    )


def _kill_switch_runbook_missing_blocked(
    *,
    command: LegacySqlConnectorSocketSecretImplementationAdrGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    materialization_gate: LegacySqlConnectorMaterializationPlanGateEvidence,
    provider_limits_snapshot: LegacySqlConnectorSocketSecretProviderLimitsSnapshot,
    network_route_snapshot: LegacySqlConnectorSocketSecretNetworkRouteSnapshot,
    secret_manager_snapshot: LegacySqlConnectorSocketSecretSecretManagerSnapshot,
    rollback_runbook_snapshot: LegacySqlConnectorSocketSecretRollbackRunbookSnapshot,
    kill_switch_runbook_snapshot: LegacySqlConnectorSocketSecretKillSwitchRunbookSnapshot,
    checked_by: str,
    checked_at: datetime,
) -> bool:
    blocked_kill_switch = kill_switch_runbook_snapshot.model_copy(
        update={"kill_switch_runbook_tested": False, "checked_at_utc": checked_at, "evidence_hash": ZERO_HASH}
    )
    blocked_kill_switch = blocked_kill_switch.model_copy(
        update={
            "evidence_hash": build_legacy_sql_connector_socket_secret_kill_switch_runbook_snapshot_hash(
                blocked_kill_switch
            )
        }
    )
    blocked = build_legacy_sql_connector_socket_secret_implementation_adr_gate(
        command=command.model_copy(update={"kill_switch_runbook_snapshot_hash": blocked_kill_switch.evidence_hash}),
        bundle=bundle,
        materialization_gate=materialization_gate,
        provider_limits_snapshot=provider_limits_snapshot,
        network_route_snapshot=network_route_snapshot,
        secret_manager_snapshot=secret_manager_snapshot,
        rollback_runbook_snapshot=rollback_runbook_snapshot,
        kill_switch_runbook_snapshot=blocked_kill_switch,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        blocked.gate_status == LegacySqlConnectorSocketSecretImplementationAdrGateStatus.BLOCKED
        and "kill_switch_runbook_not_tested" in blocked.blocking_reasons
    )


def _implementation_request_blocked(
    *,
    command: LegacySqlConnectorSocketSecretImplementationAdrGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    materialization_gate: LegacySqlConnectorMaterializationPlanGateEvidence,
    provider_limits_snapshot: LegacySqlConnectorSocketSecretProviderLimitsSnapshot,
    network_route_snapshot: LegacySqlConnectorSocketSecretNetworkRouteSnapshot,
    secret_manager_snapshot: LegacySqlConnectorSocketSecretSecretManagerSnapshot,
    rollback_runbook_snapshot: LegacySqlConnectorSocketSecretRollbackRunbookSnapshot,
    kill_switch_runbook_snapshot: LegacySqlConnectorSocketSecretKillSwitchRunbookSnapshot,
    checked_by: str,
    checked_at: datetime,
) -> bool:
    blocked = build_legacy_sql_connector_socket_secret_implementation_adr_gate(
        command=command.model_copy(
            update={
                "socket_implementation_requested": True,
                "secret_materialization_requested": True,
                "executor_code_requested": True,
                "raw_data_access_requested": True,
            }
        ),
        bundle=bundle,
        materialization_gate=materialization_gate,
        provider_limits_snapshot=provider_limits_snapshot,
        network_route_snapshot=network_route_snapshot,
        secret_manager_snapshot=secret_manager_snapshot,
        rollback_runbook_snapshot=rollback_runbook_snapshot,
        kill_switch_runbook_snapshot=kill_switch_runbook_snapshot,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        blocked.gate_status == LegacySqlConnectorSocketSecretImplementationAdrGateStatus.BLOCKED
        and "socket_implementation_requires_future_pr_gate" in blocked.blocking_reasons
        and "secret_materialization_requires_future_pr_gate" in blocked.blocking_reasons
        and "executor_code_requires_future_pr_gate" in blocked.blocking_reasons
        and "raw_data_access_requires_future_data_gate" in blocked.blocking_reasons
        and not blocked.socket_implementation_allowed
        and not blocked.secret_materialization_allowed
        and not blocked.executor_code_allowed
    )


def _assert_socket_secret_adr_safe(value: BaseModel) -> None:
    payload = value.model_dump_json().lower()
    for fragment in FORBIDDEN_SOCKET_SECRET_ADR_FRAGMENTS:
        if fragment in payload:
            raise ValueError(f"legacy SQL socket-secret ADR evidence contains forbidden fragment: {fragment}")
