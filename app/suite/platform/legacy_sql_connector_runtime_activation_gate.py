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
from suite.platform.legacy_sql_connector_runtime_merge_gate import (
    LegacySqlConnectorRuntimeMergeGateEvidence,
    LegacySqlConnectorRuntimeMergeGateStatus,
    _build_ready_runtime_merge_snapshots,
    _build_ready_runtime_pr_gate,
    _build_runtime_merge_command_from_snapshots,
    _build_runtime_merge_gate_from_snapshots,
    build_legacy_sql_connector_runtime_merge_gate_hash,
)
from suite.platform.legacy_sql_discovery import MODULE_ID_PATTERN, NAMESPACED_REF_PATTERN, LegacySqlConnectorKind
from suite.platform.legacy_sql_metadata_worker_queue import LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN

LEGACY_SQL_CONNECTOR_RUNTIME_ACTIVATION_TENANT_APPROVAL_SNAPSHOT_SCHEMA_VERSION = (
    "legacy_sql_connector_runtime_activation_tenant_approval_snapshot.v1"
)
LEGACY_SQL_CONNECTOR_RUNTIME_ACTIVATION_FEATURE_FLAG_SNAPSHOT_SCHEMA_VERSION = (
    "legacy_sql_connector_runtime_activation_feature_flag_snapshot.v1"
)
LEGACY_SQL_CONNECTOR_RUNTIME_ACTIVATION_SECRET_ROTATION_CONFIRMATION_SNAPSHOT_SCHEMA_VERSION = (
    "legacy_sql_connector_runtime_activation_secret_rotation_confirmation_snapshot.v1"
)
LEGACY_SQL_CONNECTOR_RUNTIME_ACTIVATION_NETWORK_AUTHORIZATION_SNAPSHOT_SCHEMA_VERSION = (
    "legacy_sql_connector_runtime_activation_network_authorization_snapshot.v1"
)
LEGACY_SQL_CONNECTOR_RUNTIME_ACTIVATION_ROLLBACK_FREEZE_SNAPSHOT_SCHEMA_VERSION = (
    "legacy_sql_connector_runtime_activation_rollback_freeze_snapshot.v1"
)
LEGACY_SQL_CONNECTOR_RUNTIME_ACTIVATION_KILL_SWITCH_ARMING_SNAPSHOT_SCHEMA_VERSION = (
    "legacy_sql_connector_runtime_activation_kill_switch_arming_snapshot.v1"
)
LEGACY_SQL_CONNECTOR_RUNTIME_ACTIVATION_GATE_SCHEMA_VERSION = "legacy_sql_connector_runtime_activation_gate.v1"
LEGACY_SQL_CONNECTOR_RUNTIME_ACTIVATION_GATE_SMOKE_SCHEMA_VERSION = (
    "legacy_sql_connector_runtime_activation_gate_smoke_report.v1"
)
LEGACY_SQL_CONNECTOR_RUNTIME_ACTIVATION_GATE_COMMAND_REF = (
    "docker-compose:legacy-sql-connector-runtime-activation-gate-smoke"
)
ZERO_HASH = "sha256:" + "0" * 64
SHA256_REF_PATTERN = r"^sha256:[a-f0-9]{64}$"
_ALLOWED_SNAPSHOT_SCHEMAS = {
    LEGACY_SQL_CONNECTOR_RUNTIME_ACTIVATION_TENANT_APPROVAL_SNAPSHOT_SCHEMA_VERSION,
    LEGACY_SQL_CONNECTOR_RUNTIME_ACTIVATION_FEATURE_FLAG_SNAPSHOT_SCHEMA_VERSION,
    LEGACY_SQL_CONNECTOR_RUNTIME_ACTIVATION_SECRET_ROTATION_CONFIRMATION_SNAPSHOT_SCHEMA_VERSION,
    LEGACY_SQL_CONNECTOR_RUNTIME_ACTIVATION_NETWORK_AUTHORIZATION_SNAPSHOT_SCHEMA_VERSION,
    LEGACY_SQL_CONNECTOR_RUNTIME_ACTIVATION_ROLLBACK_FREEZE_SNAPSHOT_SCHEMA_VERSION,
    LEGACY_SQL_CONNECTOR_RUNTIME_ACTIVATION_KILL_SWITCH_ARMING_SNAPSHOT_SCHEMA_VERSION,
}
FORBIDDEN_RUNTIME_ACTIVATION_FRAGMENTS = (
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


class LegacySqlConnectorRuntimeActivationGateStatus(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"


class LegacySqlConnectorRuntimeActivationEvidenceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    snapshot_ref: str
    runtime_merge_gate_evidence_hash: str
    upstream_evidence_hashes: tuple[str, ...] = ()
    required_controls: tuple[str, ...]
    passed_controls: tuple[str, ...]
    failed_controls: tuple[str, ...] = ()
    runtime_activation_allowed: bool = False
    activatable_runtime_allowed: bool = False
    runtime_feature_flag_enabled: bool = False
    socket_runtime_execution_allowed: bool = False
    secret_materialization_allowed: bool = False
    live_secret_rotation_allowed: bool = False
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
            raise ValueError("legacy SQL runtime activation snapshot schema is not allowed")
        return value

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL runtime activation snapshot text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL runtime activation snapshot module_id must be lowercase snake_case")
        return value

    @field_validator("source_system_ref", "snapshot_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL runtime activation snapshot references must be namespaced")
        return value

    @field_validator("runtime_merge_gate_evidence_hash", "evidence_hash")
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL runtime activation snapshot hashes must be sha256 references")
        return value

    @field_validator("upstream_evidence_hashes")
    @classmethod
    def validate_upstream_hashes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for item in value:
            if not re.fullmatch(SHA256_REF_PATTERN, item):
                raise ValueError("legacy SQL runtime activation snapshot upstream hashes must be sha256 references")
        return value

    @field_validator("required_controls", "passed_controls", "failed_controls")
    @classmethod
    def validate_controls(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("legacy SQL runtime activation snapshot controls must be unique")
        for item in value:
            if not item.strip():
                raise ValueError("legacy SQL runtime activation snapshot controls must not be empty")
        return value

    @model_validator(mode="after")
    def require_safe_snapshot(self) -> Self:
        if (
            self.runtime_activation_allowed
            or self.activatable_runtime_allowed
            or self.runtime_feature_flag_enabled
            or self.socket_runtime_execution_allowed
            or self.secret_materialization_allowed
            or self.live_secret_rotation_allowed
            or self.network_socket_opened
            or self.network_connection_opened
            or self.real_connection_opened
            or self.secret_material_resolved
            or self.raw_data_access_allowed
            or self.import_dry_run_allowed
            or self.import_write_allowed
            or self.destructive_actions_allowed
        ):
            raise ValueError("legacy SQL runtime activation snapshot must remain non-executing")
        missing_controls = set(self.required_controls) - set(self.passed_controls) - set(self.failed_controls)
        if missing_controls:
            raise ValueError("legacy SQL runtime activation snapshot must classify every required control")
        _assert_runtime_activation_safe(self)
        return self


class LegacySqlConnectorRuntimeActivationGateCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    runtime_merge_gate_evidence_hash: str
    tenant_approval_snapshot_hash: str
    feature_flag_snapshot_hash: str
    secret_rotation_confirmation_snapshot_hash: str
    network_authorization_snapshot_hash: str
    rollback_freeze_snapshot_hash: str
    kill_switch_arming_snapshot_hash: str
    requested_by: str
    runtime_activation_gate_requested: bool = True
    runtime_activation_requested: bool = False
    runtime_feature_flag_enable_requested: bool = False
    activatable_runtime_requested: bool = False
    socket_runtime_execution_requested: bool = False
    secret_materialization_requested: bool = False
    live_secret_rotation_requested: bool = False
    raw_data_access_requested: bool = False
    import_dry_run_requested: bool = False
    import_write_requested: bool = False
    destructive_actions_requested: bool = False

    @field_validator("tenant_id", "requested_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL runtime activation gate command text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL runtime activation gate command module_id must be lowercase snake_case")
        return value

    @field_validator("source_system_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL runtime activation gate command references must be namespaced")
        return value

    @field_validator(
        "runtime_merge_gate_evidence_hash",
        "tenant_approval_snapshot_hash",
        "feature_flag_snapshot_hash",
        "secret_rotation_confirmation_snapshot_hash",
        "network_authorization_snapshot_hash",
        "rollback_freeze_snapshot_hash",
        "kill_switch_arming_snapshot_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL runtime activation gate command hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_safe_command(self) -> Self:
        _assert_runtime_activation_safe(self)
        return self


class LegacySqlConnectorRuntimeActivationGateEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_RUNTIME_ACTIVATION_GATE_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    continuity_domain: str = LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN
    command_ref: str = LEGACY_SQL_CONNECTOR_RUNTIME_ACTIVATION_GATE_COMMAND_REF
    runtime_merge_gate_evidence_hash: str
    tenant_approval_snapshot_hash: str
    feature_flag_snapshot_hash: str
    secret_rotation_confirmation_snapshot_hash: str
    network_authorization_snapshot_hash: str
    rollback_freeze_snapshot_hash: str
    kill_switch_arming_snapshot_hash: str
    runtime_merge_gate_hash_valid: bool
    runtime_merge_gate_ready: bool
    runtime_merge_gate_bound: bool
    tenant_approval_snapshot_hash_valid: bool
    tenant_approval_snapshot_bound: bool
    tenant_approval_passed: bool
    feature_flag_snapshot_hash_valid: bool
    feature_flag_snapshot_bound: bool
    feature_flag_passed: bool
    secret_rotation_confirmation_snapshot_hash_valid: bool
    secret_rotation_confirmation_snapshot_bound: bool
    secret_rotation_confirmation_passed: bool
    network_authorization_snapshot_hash_valid: bool
    network_authorization_snapshot_bound: bool
    network_authorization_passed: bool
    rollback_freeze_snapshot_hash_valid: bool
    rollback_freeze_snapshot_bound: bool
    rollback_freeze_passed: bool
    kill_switch_arming_snapshot_hash_valid: bool
    kill_switch_arming_snapshot_bound: bool
    kill_switch_arming_passed: bool
    runtime_activation_gate_requested: bool
    runtime_activation_gate_ready: bool
    future_live_connection_gate_required: bool = True
    future_secret_materialization_gate_required: bool = True
    future_import_dry_run_gate_required: bool = True
    runtime_activation_requested: bool = False
    runtime_activation_allowed: bool = False
    runtime_feature_flag_enable_requested: bool = False
    runtime_feature_flag_enabled: bool = False
    activatable_runtime_requested: bool = False
    activatable_runtime_allowed: bool = False
    socket_runtime_execution_requested: bool = False
    socket_runtime_execution_allowed: bool = False
    secret_materialization_requested: bool = False
    secret_materialization_allowed: bool = False
    live_secret_rotation_requested: bool = False
    live_secret_rotation_allowed: bool = False
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
    gate_status: LegacySqlConnectorRuntimeActivationGateStatus
    blocking_reasons: tuple[str, ...]
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL runtime activation gate text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL runtime activation gate module_id must be lowercase snake_case")
        return value

    @field_validator("source_system_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL runtime activation gate references must be namespaced")
        return value

    @field_validator(
        "runtime_merge_gate_evidence_hash",
        "tenant_approval_snapshot_hash",
        "feature_flag_snapshot_hash",
        "secret_rotation_confirmation_snapshot_hash",
        "network_authorization_snapshot_hash",
        "rollback_freeze_snapshot_hash",
        "kill_switch_arming_snapshot_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL runtime activation gate hashes must be sha256 references")
        return value

    @field_validator("blocking_reasons")
    @classmethod
    def validate_blocking_reasons(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("legacy SQL runtime activation gate blocking reasons must be unique")
        for reason in value:
            if not reason.strip():
                raise ValueError("legacy SQL runtime activation gate blocking reasons must not be empty")
        return value

    @model_validator(mode="after")
    def require_safe_gate(self) -> Self:
        if (
            self.runtime_activation_allowed
            or self.runtime_feature_flag_enabled
            or self.activatable_runtime_allowed
            or self.socket_runtime_execution_allowed
            or self.secret_materialization_allowed
            or self.live_secret_rotation_allowed
            or self.network_socket_opened
            or self.network_connection_opened
            or self.real_connection_opened
            or self.secret_material_resolved
            or self.raw_data_access_allowed
            or self.import_dry_run_allowed
            or self.import_write_allowed
            or self.destructive_actions_allowed
        ):
            raise ValueError("legacy SQL runtime activation gate must remain non-executing")
        if (
            not self.future_live_connection_gate_required
            or not self.future_secret_materialization_gate_required
            or not self.future_import_dry_run_gate_required
        ):
            raise ValueError("legacy SQL runtime activation gate must require future runtime gates")
        if self.gate_status == LegacySqlConnectorRuntimeActivationGateStatus.READY:
            required = (
                self.runtime_merge_gate_hash_valid,
                self.runtime_merge_gate_ready,
                self.runtime_merge_gate_bound,
                self.tenant_approval_snapshot_hash_valid,
                self.tenant_approval_snapshot_bound,
                self.tenant_approval_passed,
                self.feature_flag_snapshot_hash_valid,
                self.feature_flag_snapshot_bound,
                self.feature_flag_passed,
                self.secret_rotation_confirmation_snapshot_hash_valid,
                self.secret_rotation_confirmation_snapshot_bound,
                self.secret_rotation_confirmation_passed,
                self.network_authorization_snapshot_hash_valid,
                self.network_authorization_snapshot_bound,
                self.network_authorization_passed,
                self.rollback_freeze_snapshot_hash_valid,
                self.rollback_freeze_snapshot_bound,
                self.rollback_freeze_passed,
                self.kill_switch_arming_snapshot_hash_valid,
                self.kill_switch_arming_snapshot_bound,
                self.kill_switch_arming_passed,
                self.runtime_activation_gate_requested,
                self.runtime_activation_gate_ready,
            )
            if not all(required) or self.blocking_reasons:
                raise ValueError("ready legacy SQL runtime activation gate requires complete evidence")
        if self.gate_status == LegacySqlConnectorRuntimeActivationGateStatus.BLOCKED:
            if not self.blocking_reasons:
                raise ValueError("blocked legacy SQL runtime activation gate requires blocking reasons")
            if self.runtime_activation_gate_ready:
                raise ValueError("blocked legacy SQL runtime activation gate cannot be ready")
        _assert_runtime_activation_safe(self)
        return self


class LegacySqlConnectorRuntimeActivationGateSmokeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_RUNTIME_ACTIVATION_GATE_SMOKE_SCHEMA_VERSION
    tenant_id: str
    store_backend: LegacySqlConnectorRealConnectionPolicyStoreBackend
    continuity_domain: str = LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN
    command_ref: str = LEGACY_SQL_CONNECTOR_RUNTIME_ACTIVATION_GATE_COMMAND_REF
    runtime_merge_gate_evidence_hash: str
    runtime_activation_gate_evidence_hash: str
    runtime_activation_gate_ready: bool
    runtime_merge_gate_required: bool
    tenant_approval_snapshot_required: bool
    feature_flag_snapshot_required: bool
    secret_rotation_confirmation_snapshot_required: bool
    network_authorization_snapshot_required: bool
    rollback_freeze_snapshot_required: bool
    kill_switch_arming_snapshot_required: bool
    runtime_merge_gate_missing_blocked: bool
    tenant_approval_missing_blocked: bool
    feature_flag_missing_blocked: bool
    secret_rotation_confirmation_missing_blocked: bool
    network_authorization_missing_blocked: bool
    rollback_freeze_missing_blocked: bool
    kill_switch_arming_missing_blocked: bool
    direct_connection_request_blocked: bool
    future_live_connection_gate_required: bool
    future_secret_materialization_gate_required: bool
    future_import_dry_run_gate_required: bool
    runtime_activation_allowed: bool = False
    runtime_feature_flag_enabled: bool = False
    activatable_runtime_allowed: bool = False
    socket_runtime_execution_allowed: bool = False
    secret_materialization_allowed: bool = False
    live_secret_rotation_allowed: bool = False
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
            self.runtime_activation_allowed
            or self.runtime_feature_flag_enabled
            or self.activatable_runtime_allowed
            or self.socket_runtime_execution_allowed
            or self.secret_materialization_allowed
            or self.live_secret_rotation_allowed
            or self.network_socket_opened
            or self.network_connection_opened
            or self.real_connection_opened
            or self.secret_material_resolved
            or self.raw_data_access_allowed
            or self.import_dry_run_allowed
            or self.import_write_allowed
            or self.destructive_actions_allowed
        ):
            raise ValueError("legacy SQL runtime activation smoke must remain non-executing")
        _assert_runtime_activation_safe(self)
        return self


def build_legacy_sql_connector_runtime_activation_tenant_approval_snapshot(
    *,
    runtime_merge_gate: LegacySqlConnectorRuntimeMergeGateEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    passed: bool = True,
) -> LegacySqlConnectorRuntimeActivationEvidenceSnapshot:
    return _build_snapshot(
        schema_version=LEGACY_SQL_CONNECTOR_RUNTIME_ACTIVATION_TENANT_APPROVAL_SNAPSHOT_SCHEMA_VERSION,
        snapshot_ref="runtime-activation-tenant-approval:legacy-sql-runtime-activation",
        runtime_merge_gate=runtime_merge_gate,
        required_controls=(
            "tenant_owner_activation_approval_recorded",
            "purpose_bound_to_migration_scope",
            "classification_policy_reviewed",
            "legal_hold_and_retention_checked",
            "human_confirmation_recorded_metadata_only",
        ),
        failed_controls=() if passed else ("tenant_owner_activation_approval_recorded",),
        checked_by=checked_by,
        checked_at_utc=checked_at_utc,
    )


def build_legacy_sql_connector_runtime_activation_feature_flag_snapshot(
    *,
    runtime_merge_gate: LegacySqlConnectorRuntimeMergeGateEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    passed: bool = True,
) -> LegacySqlConnectorRuntimeActivationEvidenceSnapshot:
    return _build_snapshot(
        schema_version=LEGACY_SQL_CONNECTOR_RUNTIME_ACTIVATION_FEATURE_FLAG_SNAPSHOT_SCHEMA_VERSION,
        snapshot_ref="runtime-activation-feature-flag:legacy-sql-runtime-activation",
        runtime_merge_gate=runtime_merge_gate,
        required_controls=(
            "runtime_feature_flag_default_off",
            "feature_flag_scope_tenant_and_module",
            "two_person_change_control_ready",
            "rollback_flag_disable_tested_metadata_only",
            "production_flag_not_enabled_by_gate",
        ),
        failed_controls=() if passed else ("runtime_feature_flag_default_off",),
        checked_by=checked_by,
        checked_at_utc=checked_at_utc,
    )


def build_legacy_sql_connector_runtime_activation_secret_rotation_confirmation_snapshot(
    *,
    runtime_merge_gate: LegacySqlConnectorRuntimeMergeGateEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    passed: bool = True,
) -> LegacySqlConnectorRuntimeActivationEvidenceSnapshot:
    return _build_snapshot(
        schema_version=LEGACY_SQL_CONNECTOR_RUNTIME_ACTIVATION_SECRET_ROTATION_CONFIRMATION_SNAPSHOT_SCHEMA_VERSION,
        snapshot_ref="runtime-activation-secret-rotation-confirmation:legacy-sql-runtime-activation",
        runtime_merge_gate=runtime_merge_gate,
        upstream_evidence_hashes=(runtime_merge_gate.secret_rotation_plan_snapshot_hash,),
        required_controls=(
            "rotation_window_confirmed",
            "sealed_secret_version_ready",
            "old_secret_revocation_plan_confirmed",
            "live_secret_not_resolved_by_gate",
            "tenant_kms_audit_binding_confirmed",
        ),
        failed_controls=() if passed else ("rotation_window_confirmed",),
        checked_by=checked_by,
        checked_at_utc=checked_at_utc,
    )


def build_legacy_sql_connector_runtime_activation_network_authorization_snapshot(
    *,
    runtime_merge_gate: LegacySqlConnectorRuntimeMergeGateEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    passed: bool = True,
) -> LegacySqlConnectorRuntimeActivationEvidenceSnapshot:
    return _build_snapshot(
        schema_version=LEGACY_SQL_CONNECTOR_RUNTIME_ACTIVATION_NETWORK_AUTHORIZATION_SNAPSHOT_SCHEMA_VERSION,
        snapshot_ref="runtime-activation-network-authorization:legacy-sql-runtime-activation",
        runtime_merge_gate=runtime_merge_gate,
        required_controls=(
            "egress_policy_approved",
            "target_host_allowlist_reviewed_metadata_only",
            "firewall_change_ticket_approved",
            "no_socket_probe_performed",
            "least_privilege_database_role_confirmed",
        ),
        failed_controls=() if passed else ("egress_policy_approved",),
        checked_by=checked_by,
        checked_at_utc=checked_at_utc,
    )


def build_legacy_sql_connector_runtime_activation_rollback_freeze_snapshot(
    *,
    runtime_merge_gate: LegacySqlConnectorRuntimeMergeGateEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    passed: bool = True,
) -> LegacySqlConnectorRuntimeActivationEvidenceSnapshot:
    return _build_snapshot(
        schema_version=LEGACY_SQL_CONNECTOR_RUNTIME_ACTIVATION_ROLLBACK_FREEZE_SNAPSHOT_SCHEMA_VERSION,
        snapshot_ref="runtime-activation-rollback-freeze:legacy-sql-runtime-activation",
        runtime_merge_gate=runtime_merge_gate,
        required_controls=(
            "deployment_freeze_window_confirmed",
            "rollback_plan_frozen",
            "backup_restore_checkpoint_required",
            "migration_pause_switch_ready",
            "activation_can_be_aborted",
        ),
        failed_controls=() if passed else ("deployment_freeze_window_confirmed",),
        checked_by=checked_by,
        checked_at_utc=checked_at_utc,
    )


def build_legacy_sql_connector_runtime_activation_kill_switch_arming_snapshot(
    *,
    runtime_merge_gate: LegacySqlConnectorRuntimeMergeGateEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    passed: bool = True,
) -> LegacySqlConnectorRuntimeActivationEvidenceSnapshot:
    return _build_snapshot(
        schema_version=LEGACY_SQL_CONNECTOR_RUNTIME_ACTIVATION_KILL_SWITCH_ARMING_SNAPSHOT_SCHEMA_VERSION,
        snapshot_ref="runtime-activation-kill-switch-arming:legacy-sql-runtime-activation",
        runtime_merge_gate=runtime_merge_gate,
        upstream_evidence_hashes=(runtime_merge_gate.kill_switch_drill_snapshot_hash,),
        required_controls=(
            "tenant_kill_switch_armed",
            "global_kill_switch_armed",
            "operator_abort_path_confirmed",
            "post_activation_monitoring_alert_ready",
            "break_glass_forbidden",
        ),
        failed_controls=() if passed else ("tenant_kill_switch_armed",),
        checked_by=checked_by,
        checked_at_utc=checked_at_utc,
    )


def build_legacy_sql_connector_runtime_activation_gate_command(
    *,
    runtime_merge_gate: LegacySqlConnectorRuntimeMergeGateEvidence,
    tenant_approval_snapshot: LegacySqlConnectorRuntimeActivationEvidenceSnapshot,
    feature_flag_snapshot: LegacySqlConnectorRuntimeActivationEvidenceSnapshot,
    secret_rotation_confirmation_snapshot: LegacySqlConnectorRuntimeActivationEvidenceSnapshot,
    network_authorization_snapshot: LegacySqlConnectorRuntimeActivationEvidenceSnapshot,
    rollback_freeze_snapshot: LegacySqlConnectorRuntimeActivationEvidenceSnapshot,
    kill_switch_arming_snapshot: LegacySqlConnectorRuntimeActivationEvidenceSnapshot,
    requested_by: str,
    runtime_activation_gate_requested: bool = True,
    runtime_activation_requested: bool = False,
    runtime_feature_flag_enable_requested: bool = False,
    activatable_runtime_requested: bool = False,
    socket_runtime_execution_requested: bool = False,
    secret_materialization_requested: bool = False,
    live_secret_rotation_requested: bool = False,
    raw_data_access_requested: bool = False,
    import_dry_run_requested: bool = False,
    import_write_requested: bool = False,
    destructive_actions_requested: bool = False,
) -> LegacySqlConnectorRuntimeActivationGateCommand:
    return LegacySqlConnectorRuntimeActivationGateCommand(
        tenant_id=runtime_merge_gate.tenant_id,
        module_id=runtime_merge_gate.module_id,
        source_system_ref=runtime_merge_gate.source_system_ref,
        connector_kind=runtime_merge_gate.connector_kind,
        runtime_merge_gate_evidence_hash=runtime_merge_gate.evidence_hash,
        tenant_approval_snapshot_hash=tenant_approval_snapshot.evidence_hash,
        feature_flag_snapshot_hash=feature_flag_snapshot.evidence_hash,
        secret_rotation_confirmation_snapshot_hash=secret_rotation_confirmation_snapshot.evidence_hash,
        network_authorization_snapshot_hash=network_authorization_snapshot.evidence_hash,
        rollback_freeze_snapshot_hash=rollback_freeze_snapshot.evidence_hash,
        kill_switch_arming_snapshot_hash=kill_switch_arming_snapshot.evidence_hash,
        requested_by=requested_by,
        runtime_activation_gate_requested=runtime_activation_gate_requested,
        runtime_activation_requested=runtime_activation_requested,
        runtime_feature_flag_enable_requested=runtime_feature_flag_enable_requested,
        activatable_runtime_requested=activatable_runtime_requested,
        socket_runtime_execution_requested=socket_runtime_execution_requested,
        secret_materialization_requested=secret_materialization_requested,
        live_secret_rotation_requested=live_secret_rotation_requested,
        raw_data_access_requested=raw_data_access_requested,
        import_dry_run_requested=import_dry_run_requested,
        import_write_requested=import_write_requested,
        destructive_actions_requested=destructive_actions_requested,
    )


def build_legacy_sql_connector_runtime_activation_gate(
    *,
    command: LegacySqlConnectorRuntimeActivationGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    runtime_merge_gate: LegacySqlConnectorRuntimeMergeGateEvidence,
    tenant_approval_snapshot: LegacySqlConnectorRuntimeActivationEvidenceSnapshot,
    feature_flag_snapshot: LegacySqlConnectorRuntimeActivationEvidenceSnapshot,
    secret_rotation_confirmation_snapshot: LegacySqlConnectorRuntimeActivationEvidenceSnapshot,
    network_authorization_snapshot: LegacySqlConnectorRuntimeActivationEvidenceSnapshot,
    rollback_freeze_snapshot: LegacySqlConnectorRuntimeActivationEvidenceSnapshot,
    kill_switch_arming_snapshot: LegacySqlConnectorRuntimeActivationEvidenceSnapshot,
    checked_by: str,
    checked_at_utc: datetime | None = None,
) -> LegacySqlConnectorRuntimeActivationGateEvidence:
    checked_at = checked_at_utc or datetime.now(UTC)
    runtime_merge_gate_hash_valid = (
        build_legacy_sql_connector_runtime_merge_gate_hash(runtime_merge_gate)
        == runtime_merge_gate.evidence_hash
        == command.runtime_merge_gate_evidence_hash
    )
    runtime_merge_gate_ready = (
        runtime_merge_gate.gate_status == LegacySqlConnectorRuntimeMergeGateStatus.READY
        and runtime_merge_gate.runtime_merge_gate_ready
        and runtime_merge_gate.future_runtime_activation_gate_required
    )
    runtime_merge_gate_bound = _runtime_merge_gate_bound(
        command=command, bundle=bundle, runtime_merge_gate=runtime_merge_gate
    )
    tenant_hash_valid = _snapshot_hash_valid(tenant_approval_snapshot, command.tenant_approval_snapshot_hash)
    feature_flag_hash_valid = _snapshot_hash_valid(feature_flag_snapshot, command.feature_flag_snapshot_hash)
    rotation_hash_valid = _snapshot_hash_valid(
        secret_rotation_confirmation_snapshot, command.secret_rotation_confirmation_snapshot_hash
    )
    network_hash_valid = _snapshot_hash_valid(
        network_authorization_snapshot, command.network_authorization_snapshot_hash
    )
    rollback_hash_valid = _snapshot_hash_valid(rollback_freeze_snapshot, command.rollback_freeze_snapshot_hash)
    kill_switch_hash_valid = _snapshot_hash_valid(kill_switch_arming_snapshot, command.kill_switch_arming_snapshot_hash)
    tenant_bound = _snapshot_bound(
        command=command,
        runtime_merge_gate=runtime_merge_gate,
        snapshot=tenant_approval_snapshot,
        expected_schema=LEGACY_SQL_CONNECTOR_RUNTIME_ACTIVATION_TENANT_APPROVAL_SNAPSHOT_SCHEMA_VERSION,
    )
    feature_flag_bound = _snapshot_bound(
        command=command,
        runtime_merge_gate=runtime_merge_gate,
        snapshot=feature_flag_snapshot,
        expected_schema=LEGACY_SQL_CONNECTOR_RUNTIME_ACTIVATION_FEATURE_FLAG_SNAPSHOT_SCHEMA_VERSION,
    )
    rotation_bound = _snapshot_bound(
        command=command,
        runtime_merge_gate=runtime_merge_gate,
        snapshot=secret_rotation_confirmation_snapshot,
        expected_schema=LEGACY_SQL_CONNECTOR_RUNTIME_ACTIVATION_SECRET_ROTATION_CONFIRMATION_SNAPSHOT_SCHEMA_VERSION,
        required_upstream_hash=runtime_merge_gate.secret_rotation_plan_snapshot_hash,
    )
    network_bound = _snapshot_bound(
        command=command,
        runtime_merge_gate=runtime_merge_gate,
        snapshot=network_authorization_snapshot,
        expected_schema=LEGACY_SQL_CONNECTOR_RUNTIME_ACTIVATION_NETWORK_AUTHORIZATION_SNAPSHOT_SCHEMA_VERSION,
    )
    rollback_bound = _snapshot_bound(
        command=command,
        runtime_merge_gate=runtime_merge_gate,
        snapshot=rollback_freeze_snapshot,
        expected_schema=LEGACY_SQL_CONNECTOR_RUNTIME_ACTIVATION_ROLLBACK_FREEZE_SNAPSHOT_SCHEMA_VERSION,
    )
    kill_switch_bound = _snapshot_bound(
        command=command,
        runtime_merge_gate=runtime_merge_gate,
        snapshot=kill_switch_arming_snapshot,
        expected_schema=LEGACY_SQL_CONNECTOR_RUNTIME_ACTIVATION_KILL_SWITCH_ARMING_SNAPSHOT_SCHEMA_VERSION,
        required_upstream_hash=runtime_merge_gate.kill_switch_drill_snapshot_hash,
    )
    tenant_passed = _snapshot_passed(tenant_approval_snapshot)
    feature_flag_passed = _snapshot_passed(feature_flag_snapshot)
    rotation_passed = _snapshot_passed(secret_rotation_confirmation_snapshot)
    network_passed = _snapshot_passed(network_authorization_snapshot)
    rollback_passed = _snapshot_passed(rollback_freeze_snapshot)
    kill_switch_passed = _snapshot_passed(kill_switch_arming_snapshot)
    blocking_reasons = _runtime_activation_blocking_reasons(
        command=command,
        runtime_merge_gate_hash_valid=runtime_merge_gate_hash_valid,
        runtime_merge_gate_ready=runtime_merge_gate_ready,
        runtime_merge_gate_bound=runtime_merge_gate_bound,
        snapshot_checks=(
            ("tenant_approval", tenant_hash_valid, tenant_bound, tenant_passed, tenant_approval_snapshot),
            ("feature_flag", feature_flag_hash_valid, feature_flag_bound, feature_flag_passed, feature_flag_snapshot),
            (
                "secret_rotation_confirmation",
                rotation_hash_valid,
                rotation_bound,
                rotation_passed,
                secret_rotation_confirmation_snapshot,
            ),
            (
                "network_authorization",
                network_hash_valid,
                network_bound,
                network_passed,
                network_authorization_snapshot,
            ),
            ("rollback_freeze", rollback_hash_valid, rollback_bound, rollback_passed, rollback_freeze_snapshot),
            (
                "kill_switch_arming",
                kill_switch_hash_valid,
                kill_switch_bound,
                kill_switch_passed,
                kill_switch_arming_snapshot,
            ),
        ),
    )
    ready = not blocking_reasons
    draft = LegacySqlConnectorRuntimeActivationGateEvidence(
        tenant_id=runtime_merge_gate.tenant_id,
        module_id=runtime_merge_gate.module_id,
        source_system_ref=runtime_merge_gate.source_system_ref,
        connector_kind=runtime_merge_gate.connector_kind,
        runtime_merge_gate_evidence_hash=runtime_merge_gate.evidence_hash,
        tenant_approval_snapshot_hash=tenant_approval_snapshot.evidence_hash,
        feature_flag_snapshot_hash=feature_flag_snapshot.evidence_hash,
        secret_rotation_confirmation_snapshot_hash=secret_rotation_confirmation_snapshot.evidence_hash,
        network_authorization_snapshot_hash=network_authorization_snapshot.evidence_hash,
        rollback_freeze_snapshot_hash=rollback_freeze_snapshot.evidence_hash,
        kill_switch_arming_snapshot_hash=kill_switch_arming_snapshot.evidence_hash,
        runtime_merge_gate_hash_valid=runtime_merge_gate_hash_valid,
        runtime_merge_gate_ready=runtime_merge_gate_ready,
        runtime_merge_gate_bound=runtime_merge_gate_bound,
        tenant_approval_snapshot_hash_valid=tenant_hash_valid,
        tenant_approval_snapshot_bound=tenant_bound,
        tenant_approval_passed=tenant_passed,
        feature_flag_snapshot_hash_valid=feature_flag_hash_valid,
        feature_flag_snapshot_bound=feature_flag_bound,
        feature_flag_passed=feature_flag_passed,
        secret_rotation_confirmation_snapshot_hash_valid=rotation_hash_valid,
        secret_rotation_confirmation_snapshot_bound=rotation_bound,
        secret_rotation_confirmation_passed=rotation_passed,
        network_authorization_snapshot_hash_valid=network_hash_valid,
        network_authorization_snapshot_bound=network_bound,
        network_authorization_passed=network_passed,
        rollback_freeze_snapshot_hash_valid=rollback_hash_valid,
        rollback_freeze_snapshot_bound=rollback_bound,
        rollback_freeze_passed=rollback_passed,
        kill_switch_arming_snapshot_hash_valid=kill_switch_hash_valid,
        kill_switch_arming_snapshot_bound=kill_switch_bound,
        kill_switch_arming_passed=kill_switch_passed,
        runtime_activation_gate_requested=command.runtime_activation_gate_requested,
        runtime_activation_gate_ready=ready,
        runtime_activation_requested=command.runtime_activation_requested,
        runtime_feature_flag_enable_requested=command.runtime_feature_flag_enable_requested,
        activatable_runtime_requested=command.activatable_runtime_requested,
        socket_runtime_execution_requested=command.socket_runtime_execution_requested,
        secret_materialization_requested=command.secret_materialization_requested,
        live_secret_rotation_requested=command.live_secret_rotation_requested,
        raw_data_access_requested=command.raw_data_access_requested,
        import_dry_run_requested=command.import_dry_run_requested,
        import_write_requested=command.import_write_requested,
        destructive_actions_requested=command.destructive_actions_requested,
        gate_status=LegacySqlConnectorRuntimeActivationGateStatus.READY
        if ready
        else LegacySqlConnectorRuntimeActivationGateStatus.BLOCKED,
        blocking_reasons=blocking_reasons,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_connector_runtime_activation_gate_hash(draft)})


def build_legacy_sql_connector_runtime_activation_snapshot_hash(
    snapshot: LegacySqlConnectorRuntimeActivationEvidenceSnapshot,
) -> str:
    return stable_hash(canonical_json(snapshot.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_runtime_activation_gate_hash(
    gate: LegacySqlConnectorRuntimeActivationGateEvidence,
) -> str:
    return stable_hash(canonical_json(gate.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_runtime_activation_gate_smoke_report_hash(
    report: LegacySqlConnectorRuntimeActivationGateSmokeReport,
) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def run_legacy_sql_connector_runtime_activation_gate_smoke_from_env(
    environ: Mapping[str, str] | None = None,
) -> LegacySqlConnectorRuntimeActivationGateSmokeReport:
    env = os.environ if environ is None else environ
    checked_by = env.get(
        "SUITE_LEGACY_SQL_CONNECTOR_RUNTIME_ACTIVATION_GATE_CHECKED_BY",
        "legacy-sql-connector-runtime-activation-gate-smoke",
    )
    checked_at = datetime.now(UTC)
    store_backend = LegacySqlConnectorRealConnectionPolicyStoreBackend(
        env.get(
            "SUITE_LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_POLICY_STORE_BACKEND",
            LegacySqlConnectorRealConnectionPolicyStoreBackend.JSONL.value,
        )
    )
    bundle, runtime_merge_gate = _build_ready_runtime_merge_gate(env=env, checked_by=checked_by, checked_at=checked_at)
    snapshots = _build_ready_runtime_activation_snapshots(
        runtime_merge_gate=runtime_merge_gate,
        checked_by=checked_by,
        checked_at=checked_at,
    )
    command = _build_runtime_activation_command_from_snapshots(
        runtime_merge_gate=runtime_merge_gate,
        snapshots=snapshots,
        requested_by=checked_by,
    )
    gate = _build_runtime_activation_gate_from_snapshots(
        command=command,
        bundle=bundle,
        runtime_merge_gate=runtime_merge_gate,
        snapshots=snapshots,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=87),
    )
    runtime_merge_gate_missing_blocked = _runtime_merge_gate_missing_blocked(
        command, bundle, runtime_merge_gate, snapshots, checked_by, checked_at + timedelta(seconds=88)
    )
    tenant_missing_blocked = _snapshot_missing_blocked(
        command,
        bundle,
        runtime_merge_gate,
        snapshots,
        "tenant_approval_snapshot",
        "tenant_owner_activation_approval_recorded",
        "tenant_approval_snapshot_failed",
        checked_by,
        checked_at + timedelta(seconds=89),
    )
    feature_flag_missing_blocked = _snapshot_missing_blocked(
        command,
        bundle,
        runtime_merge_gate,
        snapshots,
        "feature_flag_snapshot",
        "runtime_feature_flag_default_off",
        "feature_flag_snapshot_failed",
        checked_by,
        checked_at + timedelta(seconds=90),
    )
    rotation_missing_blocked = _snapshot_missing_blocked(
        command,
        bundle,
        runtime_merge_gate,
        snapshots,
        "secret_rotation_confirmation_snapshot",
        "rotation_window_confirmed",
        "secret_rotation_confirmation_snapshot_failed",
        checked_by,
        checked_at + timedelta(seconds=91),
    )
    network_missing_blocked = _snapshot_missing_blocked(
        command,
        bundle,
        runtime_merge_gate,
        snapshots,
        "network_authorization_snapshot",
        "egress_policy_approved",
        "network_authorization_snapshot_failed",
        checked_by,
        checked_at + timedelta(seconds=92),
    )
    rollback_missing_blocked = _snapshot_missing_blocked(
        command,
        bundle,
        runtime_merge_gate,
        snapshots,
        "rollback_freeze_snapshot",
        "deployment_freeze_window_confirmed",
        "rollback_freeze_snapshot_failed",
        checked_by,
        checked_at + timedelta(seconds=93),
    )
    kill_switch_missing_blocked = _snapshot_missing_blocked(
        command,
        bundle,
        runtime_merge_gate,
        snapshots,
        "kill_switch_arming_snapshot",
        "tenant_kill_switch_armed",
        "kill_switch_arming_snapshot_failed",
        checked_by,
        checked_at + timedelta(seconds=94),
    )
    direct_connection_request_blocked = _direct_connection_request_blocked(
        command,
        bundle,
        runtime_merge_gate,
        snapshots,
        checked_by,
        checked_at + timedelta(seconds=95),
    )
    runtime_activation_gate_ready = (
        gate.gate_status == LegacySqlConnectorRuntimeActivationGateStatus.READY
        and gate.runtime_activation_gate_ready
        and runtime_merge_gate_missing_blocked
        and tenant_missing_blocked
        and feature_flag_missing_blocked
        and rotation_missing_blocked
        and network_missing_blocked
        and rollback_missing_blocked
        and kill_switch_missing_blocked
        and direct_connection_request_blocked
        and not gate.runtime_activation_allowed
        and not gate.activatable_runtime_allowed
        and not gate.real_connection_opened
    )
    draft = LegacySqlConnectorRuntimeActivationGateSmokeReport(
        tenant_id=bundle.tenant_id,
        store_backend=store_backend,
        runtime_merge_gate_evidence_hash=runtime_merge_gate.evidence_hash,
        runtime_activation_gate_evidence_hash=gate.evidence_hash,
        runtime_activation_gate_ready=runtime_activation_gate_ready,
        runtime_merge_gate_required=gate.runtime_merge_gate_bound and gate.runtime_merge_gate_ready,
        tenant_approval_snapshot_required=gate.tenant_approval_snapshot_bound and gate.tenant_approval_passed,
        feature_flag_snapshot_required=gate.feature_flag_snapshot_bound and gate.feature_flag_passed,
        secret_rotation_confirmation_snapshot_required=(
            gate.secret_rotation_confirmation_snapshot_bound and gate.secret_rotation_confirmation_passed
        ),
        network_authorization_snapshot_required=(
            gate.network_authorization_snapshot_bound and gate.network_authorization_passed
        ),
        rollback_freeze_snapshot_required=gate.rollback_freeze_snapshot_bound and gate.rollback_freeze_passed,
        kill_switch_arming_snapshot_required=gate.kill_switch_arming_snapshot_bound and gate.kill_switch_arming_passed,
        runtime_merge_gate_missing_blocked=runtime_merge_gate_missing_blocked,
        tenant_approval_missing_blocked=tenant_missing_blocked,
        feature_flag_missing_blocked=feature_flag_missing_blocked,
        secret_rotation_confirmation_missing_blocked=rotation_missing_blocked,
        network_authorization_missing_blocked=network_missing_blocked,
        rollback_freeze_missing_blocked=rollback_missing_blocked,
        kill_switch_arming_missing_blocked=kill_switch_missing_blocked,
        direct_connection_request_blocked=direct_connection_request_blocked,
        future_live_connection_gate_required=gate.future_live_connection_gate_required,
        future_secret_materialization_gate_required=gate.future_secret_materialization_gate_required,
        future_import_dry_run_gate_required=gate.future_import_dry_run_gate_required,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    _assert_runtime_activation_safe(draft)
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_runtime_activation_gate_smoke_report_hash(draft)}
    )


def exit_code_for_report(report: LegacySqlConnectorRuntimeActivationGateSmokeReport) -> int:
    return 0 if report.runtime_activation_gate_ready else 1


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Legacy SQL runtime activation gate smoke.")
    parser.add_argument(
        "--once", action="store_true", help="Run one non-executing runtime activation gate smoke and exit."
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the runtime activation gate report.")
    args = parser.parse_args(argv)
    del args.once

    report = run_legacy_sql_connector_runtime_activation_gate_smoke_from_env()
    print(json.dumps(report.model_dump(mode="json"), indent=2 if args.pretty else None, sort_keys=True))
    raise SystemExit(exit_code_for_report(report))


def _build_snapshot(
    *,
    schema_version: str,
    snapshot_ref: str,
    runtime_merge_gate: LegacySqlConnectorRuntimeMergeGateEvidence,
    required_controls: tuple[str, ...],
    failed_controls: tuple[str, ...],
    checked_by: str,
    checked_at_utc: datetime | None,
    upstream_evidence_hashes: tuple[str, ...] = (),
) -> LegacySqlConnectorRuntimeActivationEvidenceSnapshot:
    checked_at = checked_at_utc or datetime.now(UTC)
    passed_controls = tuple(control for control in required_controls if control not in failed_controls)
    draft = LegacySqlConnectorRuntimeActivationEvidenceSnapshot(
        schema_version=schema_version,
        tenant_id=runtime_merge_gate.tenant_id,
        module_id=runtime_merge_gate.module_id,
        source_system_ref=runtime_merge_gate.source_system_ref,
        connector_kind=runtime_merge_gate.connector_kind,
        snapshot_ref=snapshot_ref,
        runtime_merge_gate_evidence_hash=runtime_merge_gate.evidence_hash,
        upstream_evidence_hashes=upstream_evidence_hashes,
        required_controls=required_controls,
        passed_controls=passed_controls,
        failed_controls=failed_controls,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_runtime_activation_snapshot_hash(draft)}
    )


def _build_ready_runtime_merge_gate(
    *,
    env: Mapping[str, str],
    checked_by: str,
    checked_at: datetime,
) -> tuple[LegacySqlConnectorRealConnectionExecutorPolicyBundle, LegacySqlConnectorRuntimeMergeGateEvidence]:
    bundle, runtime_pr_gate = _build_ready_runtime_pr_gate(env=env, checked_by=checked_by, checked_at=checked_at)
    merge_snapshots = _build_ready_runtime_merge_snapshots(
        runtime_pr_gate=runtime_pr_gate,
        checked_by=checked_by,
        checked_at=checked_at,
    )
    merge_command = _build_runtime_merge_command_from_snapshots(
        runtime_pr_gate=runtime_pr_gate,
        snapshots=merge_snapshots,
        requested_by=checked_by,
    )
    runtime_merge_gate = _build_runtime_merge_gate_from_snapshots(
        command=merge_command,
        bundle=bundle,
        runtime_pr_gate=runtime_pr_gate,
        snapshots=merge_snapshots,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=70),
    )
    return bundle, runtime_merge_gate


def _build_ready_runtime_activation_snapshots(
    *,
    runtime_merge_gate: LegacySqlConnectorRuntimeMergeGateEvidence,
    checked_by: str,
    checked_at: datetime,
) -> dict[str, LegacySqlConnectorRuntimeActivationEvidenceSnapshot]:
    return {
        "tenant_approval_snapshot": build_legacy_sql_connector_runtime_activation_tenant_approval_snapshot(
            runtime_merge_gate=runtime_merge_gate,
            checked_by=checked_by,
            checked_at_utc=checked_at + timedelta(seconds=81),
        ),
        "feature_flag_snapshot": build_legacy_sql_connector_runtime_activation_feature_flag_snapshot(
            runtime_merge_gate=runtime_merge_gate,
            checked_by=checked_by,
            checked_at_utc=checked_at + timedelta(seconds=82),
        ),
        "secret_rotation_confirmation_snapshot": (
            build_legacy_sql_connector_runtime_activation_secret_rotation_confirmation_snapshot(
                runtime_merge_gate=runtime_merge_gate,
                checked_by=checked_by,
                checked_at_utc=checked_at + timedelta(seconds=83),
            )
        ),
        "network_authorization_snapshot": build_legacy_sql_connector_runtime_activation_network_authorization_snapshot(
            runtime_merge_gate=runtime_merge_gate,
            checked_by=checked_by,
            checked_at_utc=checked_at + timedelta(seconds=84),
        ),
        "rollback_freeze_snapshot": build_legacy_sql_connector_runtime_activation_rollback_freeze_snapshot(
            runtime_merge_gate=runtime_merge_gate,
            checked_by=checked_by,
            checked_at_utc=checked_at + timedelta(seconds=85),
        ),
        "kill_switch_arming_snapshot": build_legacy_sql_connector_runtime_activation_kill_switch_arming_snapshot(
            runtime_merge_gate=runtime_merge_gate,
            checked_by=checked_by,
            checked_at_utc=checked_at + timedelta(seconds=86),
        ),
    }


def _snapshot_hash_valid(snapshot: LegacySqlConnectorRuntimeActivationEvidenceSnapshot, expected_hash: str) -> bool:
    return (
        build_legacy_sql_connector_runtime_activation_snapshot_hash(snapshot) == snapshot.evidence_hash == expected_hash
    )


def _snapshot_passed(snapshot: LegacySqlConnectorRuntimeActivationEvidenceSnapshot) -> bool:
    return not snapshot.failed_controls and set(snapshot.required_controls) == set(snapshot.passed_controls)


def _snapshot_bound(
    *,
    command: LegacySqlConnectorRuntimeActivationGateCommand,
    runtime_merge_gate: LegacySqlConnectorRuntimeMergeGateEvidence,
    snapshot: LegacySqlConnectorRuntimeActivationEvidenceSnapshot,
    expected_schema: str,
    required_upstream_hash: str | None = None,
) -> bool:
    upstream_bound = required_upstream_hash is None or required_upstream_hash in snapshot.upstream_evidence_hashes
    return (
        command.tenant_id == runtime_merge_gate.tenant_id == snapshot.tenant_id
        and command.module_id == runtime_merge_gate.module_id == snapshot.module_id
        and command.source_system_ref == runtime_merge_gate.source_system_ref == snapshot.source_system_ref
        and command.connector_kind == runtime_merge_gate.connector_kind == snapshot.connector_kind
        and snapshot.schema_version == expected_schema
        and snapshot.runtime_merge_gate_evidence_hash == runtime_merge_gate.evidence_hash
        and upstream_bound
    )


def _runtime_merge_gate_bound(
    *,
    command: LegacySqlConnectorRuntimeActivationGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    runtime_merge_gate: LegacySqlConnectorRuntimeMergeGateEvidence,
) -> bool:
    return (
        command.tenant_id == bundle.tenant_id == runtime_merge_gate.tenant_id
        and command.module_id == bundle.module_id == runtime_merge_gate.module_id
        and command.source_system_ref == bundle.source_system_ref == runtime_merge_gate.source_system_ref
        and command.connector_kind == bundle.connector_kind == runtime_merge_gate.connector_kind
        and command.runtime_merge_gate_evidence_hash == runtime_merge_gate.evidence_hash
        and not runtime_merge_gate.merge_allowed
        and not runtime_merge_gate.runtime_code_merge_allowed
        and not runtime_merge_gate.activatable_runtime_allowed
        and not runtime_merge_gate.socket_runtime_execution_allowed
        and not runtime_merge_gate.secret_materialization_allowed
        and not runtime_merge_gate.network_socket_opened
        and not runtime_merge_gate.secret_material_resolved
    )


def _runtime_activation_blocking_reasons(
    *,
    command: LegacySqlConnectorRuntimeActivationGateCommand,
    runtime_merge_gate_hash_valid: bool,
    runtime_merge_gate_ready: bool,
    runtime_merge_gate_bound: bool,
    snapshot_checks: tuple[tuple[str, bool, bool, bool, LegacySqlConnectorRuntimeActivationEvidenceSnapshot], ...],
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not runtime_merge_gate_hash_valid:
        reasons.append("runtime_merge_gate_hash_invalid")
    if not runtime_merge_gate_ready:
        reasons.append("runtime_merge_gate_not_ready")
    if not runtime_merge_gate_bound:
        reasons.append("runtime_merge_gate_not_bound")
    for prefix, hash_valid, bound, passed, snapshot in snapshot_checks:
        if not hash_valid:
            reasons.append(f"{prefix}_snapshot_hash_invalid")
        if not bound:
            reasons.append(f"{prefix}_snapshot_not_bound")
        if not passed:
            reasons.append(f"{prefix}_snapshot_failed")
        for failed_control in snapshot.failed_controls:
            reasons.append(f"{prefix}_{failed_control}_failed")
    if not command.runtime_activation_gate_requested:
        reasons.append("runtime_activation_gate_not_requested")
    if command.runtime_activation_requested:
        reasons.append("runtime_activation_requires_future_live_connection_gate")
    if command.runtime_feature_flag_enable_requested:
        reasons.append("runtime_feature_flag_enable_requires_future_live_connection_gate")
    if command.activatable_runtime_requested:
        reasons.append("activatable_runtime_requires_future_live_connection_gate")
    if command.socket_runtime_execution_requested:
        reasons.append("socket_runtime_execution_requires_future_live_connection_gate")
    if command.secret_materialization_requested:
        reasons.append("secret_materialization_requires_future_secret_gate")
    if command.live_secret_rotation_requested:
        reasons.append("live_secret_rotation_requires_future_rotation_gate")
    if command.raw_data_access_requested:
        reasons.append("raw_data_access_requires_future_data_gate")
    if command.import_dry_run_requested:
        reasons.append("import_dry_run_requires_future_import_gate")
    if command.import_write_requested:
        reasons.append("import_write_requires_future_import_gate")
    if command.destructive_actions_requested:
        reasons.append("destructive_actions_require_human_confirmation_gate")
    return tuple(dict.fromkeys(reasons))


def _build_runtime_activation_command_from_snapshots(
    *,
    runtime_merge_gate: LegacySqlConnectorRuntimeMergeGateEvidence,
    snapshots: dict[str, LegacySqlConnectorRuntimeActivationEvidenceSnapshot],
    requested_by: str,
) -> LegacySqlConnectorRuntimeActivationGateCommand:
    return build_legacy_sql_connector_runtime_activation_gate_command(
        runtime_merge_gate=runtime_merge_gate,
        tenant_approval_snapshot=snapshots["tenant_approval_snapshot"],
        feature_flag_snapshot=snapshots["feature_flag_snapshot"],
        secret_rotation_confirmation_snapshot=snapshots["secret_rotation_confirmation_snapshot"],
        network_authorization_snapshot=snapshots["network_authorization_snapshot"],
        rollback_freeze_snapshot=snapshots["rollback_freeze_snapshot"],
        kill_switch_arming_snapshot=snapshots["kill_switch_arming_snapshot"],
        requested_by=requested_by,
    )


def _build_runtime_activation_gate_from_snapshots(
    *,
    command: LegacySqlConnectorRuntimeActivationGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    runtime_merge_gate: LegacySqlConnectorRuntimeMergeGateEvidence,
    snapshots: dict[str, LegacySqlConnectorRuntimeActivationEvidenceSnapshot],
    checked_by: str,
    checked_at_utc: datetime,
) -> LegacySqlConnectorRuntimeActivationGateEvidence:
    return build_legacy_sql_connector_runtime_activation_gate(
        command=command,
        bundle=bundle,
        runtime_merge_gate=runtime_merge_gate,
        tenant_approval_snapshot=snapshots["tenant_approval_snapshot"],
        feature_flag_snapshot=snapshots["feature_flag_snapshot"],
        secret_rotation_confirmation_snapshot=snapshots["secret_rotation_confirmation_snapshot"],
        network_authorization_snapshot=snapshots["network_authorization_snapshot"],
        rollback_freeze_snapshot=snapshots["rollback_freeze_snapshot"],
        kill_switch_arming_snapshot=snapshots["kill_switch_arming_snapshot"],
        checked_by=checked_by,
        checked_at_utc=checked_at_utc,
    )


def _runtime_merge_gate_missing_blocked(
    command: LegacySqlConnectorRuntimeActivationGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    runtime_merge_gate: LegacySqlConnectorRuntimeMergeGateEvidence,
    snapshots: dict[str, LegacySqlConnectorRuntimeActivationEvidenceSnapshot],
    checked_by: str,
    checked_at: datetime,
) -> bool:
    blocked_merge_gate = runtime_merge_gate.model_copy(
        update={
            "gate_status": LegacySqlConnectorRuntimeMergeGateStatus.BLOCKED,
            "runtime_merge_gate_ready": False,
            "blocking_reasons": ("runtime_activation_test_merge_gate_missing",),
            "checked_at_utc": checked_at,
            "evidence_hash": ZERO_HASH,
        }
    )
    blocked_merge_gate = blocked_merge_gate.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_runtime_merge_gate_hash(blocked_merge_gate)}
    )
    blocked = _build_runtime_activation_gate_from_snapshots(
        command=command.model_copy(update={"runtime_merge_gate_evidence_hash": blocked_merge_gate.evidence_hash}),
        bundle=bundle,
        runtime_merge_gate=blocked_merge_gate,
        snapshots=snapshots,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        blocked.gate_status == LegacySqlConnectorRuntimeActivationGateStatus.BLOCKED
        and "runtime_merge_gate_not_ready" in blocked.blocking_reasons
    )


def _snapshot_missing_blocked(
    command: LegacySqlConnectorRuntimeActivationGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    runtime_merge_gate: LegacySqlConnectorRuntimeMergeGateEvidence,
    snapshots: dict[str, LegacySqlConnectorRuntimeActivationEvidenceSnapshot],
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
        update={"evidence_hash": build_legacy_sql_connector_runtime_activation_snapshot_hash(blocked_snapshot)}
    )
    updated_snapshots[snapshot_key] = blocked_snapshot
    command_field = f"{snapshot_key}_hash"
    blocked = _build_runtime_activation_gate_from_snapshots(
        command=command.model_copy(update={command_field: blocked_snapshot.evidence_hash}),
        bundle=bundle,
        runtime_merge_gate=runtime_merge_gate,
        snapshots=updated_snapshots,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        blocked.gate_status == LegacySqlConnectorRuntimeActivationGateStatus.BLOCKED
        and expected_reason in blocked.blocking_reasons
    )


def _direct_connection_request_blocked(
    command: LegacySqlConnectorRuntimeActivationGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    runtime_merge_gate: LegacySqlConnectorRuntimeMergeGateEvidence,
    snapshots: dict[str, LegacySqlConnectorRuntimeActivationEvidenceSnapshot],
    checked_by: str,
    checked_at: datetime,
) -> bool:
    blocked = _build_runtime_activation_gate_from_snapshots(
        command=command.model_copy(
            update={
                "runtime_activation_requested": True,
                "runtime_feature_flag_enable_requested": True,
                "activatable_runtime_requested": True,
                "socket_runtime_execution_requested": True,
                "secret_materialization_requested": True,
                "live_secret_rotation_requested": True,
                "raw_data_access_requested": True,
            }
        ),
        bundle=bundle,
        runtime_merge_gate=runtime_merge_gate,
        snapshots=snapshots,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        blocked.gate_status == LegacySqlConnectorRuntimeActivationGateStatus.BLOCKED
        and "runtime_activation_requires_future_live_connection_gate" in blocked.blocking_reasons
        and "runtime_feature_flag_enable_requires_future_live_connection_gate" in blocked.blocking_reasons
        and "activatable_runtime_requires_future_live_connection_gate" in blocked.blocking_reasons
        and "socket_runtime_execution_requires_future_live_connection_gate" in blocked.blocking_reasons
        and "secret_materialization_requires_future_secret_gate" in blocked.blocking_reasons
        and "live_secret_rotation_requires_future_rotation_gate" in blocked.blocking_reasons
        and "raw_data_access_requires_future_data_gate" in blocked.blocking_reasons
        and not blocked.runtime_activation_allowed
        and not blocked.activatable_runtime_allowed
    )


def _assert_runtime_activation_safe(value: BaseModel) -> None:
    payload = value.model_dump_json().lower()
    for fragment in FORBIDDEN_RUNTIME_ACTIVATION_FRAGMENTS:
        if fragment in payload:
            raise ValueError(f"legacy SQL runtime activation evidence contains forbidden fragment: {fragment}")


if __name__ == "__main__":
    main()
