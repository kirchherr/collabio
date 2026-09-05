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
from suite.platform.legacy_sql_connector_socket_secret_implementation_adr_gate import (
    LegacySqlConnectorSocketSecretImplementationAdrGateEvidence,
    LegacySqlConnectorSocketSecretImplementationAdrGateStatus,
    _build_ready_materialization_chain,
    build_legacy_sql_connector_socket_secret_implementation_adr_gate,
    build_legacy_sql_connector_socket_secret_implementation_adr_gate_command,
    build_legacy_sql_connector_socket_secret_implementation_adr_gate_hash,
    build_legacy_sql_connector_socket_secret_kill_switch_runbook_snapshot,
    build_legacy_sql_connector_socket_secret_network_route_snapshot,
    build_legacy_sql_connector_socket_secret_provider_limits_snapshot,
    build_legacy_sql_connector_socket_secret_rollback_runbook_snapshot,
    build_legacy_sql_connector_socket_secret_secret_manager_snapshot,
)
from suite.platform.legacy_sql_discovery import MODULE_ID_PATTERN, NAMESPACED_REF_PATTERN, LegacySqlConnectorKind
from suite.platform.legacy_sql_metadata_worker_queue import LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN

LEGACY_SQL_CONNECTOR_RUNTIME_PR_CODE_REVIEW_SNAPSHOT_SCHEMA_VERSION = (
    "legacy_sql_connector_runtime_pr_code_review_snapshot.v1"
)
LEGACY_SQL_CONNECTOR_RUNTIME_PR_TEST_CONTAINER_SNAPSHOT_SCHEMA_VERSION = (
    "legacy_sql_connector_runtime_pr_test_container_snapshot.v1"
)
LEGACY_SQL_CONNECTOR_RUNTIME_PR_SECRET_BINDING_SNAPSHOT_SCHEMA_VERSION = (
    "legacy_sql_connector_runtime_pr_secret_binding_snapshot.v1"
)
LEGACY_SQL_CONNECTOR_RUNTIME_PR_NETWORK_BINDING_SNAPSHOT_SCHEMA_VERSION = (
    "legacy_sql_connector_runtime_pr_network_binding_snapshot.v1"
)
LEGACY_SQL_CONNECTOR_RUNTIME_PR_ROLLBACK_PROBE_SNAPSHOT_SCHEMA_VERSION = (
    "legacy_sql_connector_runtime_pr_rollback_probe_snapshot.v1"
)
LEGACY_SQL_CONNECTOR_RUNTIME_PR_KILL_SWITCH_PROBE_SNAPSHOT_SCHEMA_VERSION = (
    "legacy_sql_connector_runtime_pr_kill_switch_probe_snapshot.v1"
)
LEGACY_SQL_CONNECTOR_RUNTIME_PR_GATE_SCHEMA_VERSION = "legacy_sql_connector_runtime_pr_gate.v1"
LEGACY_SQL_CONNECTOR_RUNTIME_PR_GATE_SMOKE_SCHEMA_VERSION = "legacy_sql_connector_runtime_pr_gate_smoke_report.v1"
LEGACY_SQL_CONNECTOR_RUNTIME_PR_GATE_COMMAND_REF = "docker-compose:legacy-sql-connector-runtime-pr-gate-smoke"
ZERO_HASH = "sha256:" + "0" * 64
SHA256_REF_PATTERN = r"^sha256:[a-f0-9]{64}$"
_ALLOWED_SNAPSHOT_SCHEMAS = {
    LEGACY_SQL_CONNECTOR_RUNTIME_PR_CODE_REVIEW_SNAPSHOT_SCHEMA_VERSION,
    LEGACY_SQL_CONNECTOR_RUNTIME_PR_TEST_CONTAINER_SNAPSHOT_SCHEMA_VERSION,
    LEGACY_SQL_CONNECTOR_RUNTIME_PR_SECRET_BINDING_SNAPSHOT_SCHEMA_VERSION,
    LEGACY_SQL_CONNECTOR_RUNTIME_PR_NETWORK_BINDING_SNAPSHOT_SCHEMA_VERSION,
    LEGACY_SQL_CONNECTOR_RUNTIME_PR_ROLLBACK_PROBE_SNAPSHOT_SCHEMA_VERSION,
    LEGACY_SQL_CONNECTOR_RUNTIME_PR_KILL_SWITCH_PROBE_SNAPSHOT_SCHEMA_VERSION,
}
FORBIDDEN_RUNTIME_PR_FRAGMENTS = (
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


class LegacySqlConnectorRuntimePrGateStatus(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"


class LegacySqlConnectorRuntimePrEvidenceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    snapshot_ref: str
    adr_gate_evidence_hash: str
    upstream_evidence_hashes: tuple[str, ...] = ()
    required_controls: tuple[str, ...]
    passed_controls: tuple[str, ...]
    failed_controls: tuple[str, ...] = ()
    runtime_code_merge_allowed: bool = False
    merge_allowed: bool = False
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
            raise ValueError("legacy SQL runtime PR snapshot schema is not allowed")
        return value

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL runtime PR snapshot text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL runtime PR snapshot module_id must be lowercase snake_case")
        return value

    @field_validator("source_system_ref", "snapshot_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL runtime PR snapshot references must be namespaced")
        return value

    @field_validator("adr_gate_evidence_hash", "evidence_hash")
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL runtime PR snapshot hashes must be sha256 references")
        return value

    @field_validator("upstream_evidence_hashes")
    @classmethod
    def validate_upstream_hashes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for item in value:
            if not re.fullmatch(SHA256_REF_PATTERN, item):
                raise ValueError("legacy SQL runtime PR snapshot upstream hashes must be sha256 references")
        return value

    @field_validator("required_controls", "passed_controls", "failed_controls")
    @classmethod
    def validate_controls(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("legacy SQL runtime PR snapshot controls must be unique")
        for item in value:
            if not item.strip():
                raise ValueError("legacy SQL runtime PR snapshot controls must not be empty")
        return value

    @model_validator(mode="after")
    def require_safe_snapshot(self) -> Self:
        if (
            self.runtime_code_merge_allowed
            or self.merge_allowed
            or self.network_socket_opened
            or self.network_connection_opened
            or self.real_connection_opened
            or self.secret_material_resolved
            or self.raw_data_access_allowed
            or self.import_dry_run_allowed
            or self.import_write_allowed
            or self.destructive_actions_allowed
        ):
            raise ValueError("legacy SQL runtime PR snapshot must remain non-executing")
        missing_controls = set(self.required_controls) - set(self.passed_controls) - set(self.failed_controls)
        if missing_controls:
            raise ValueError("legacy SQL runtime PR snapshot must classify every required control")
        _assert_runtime_pr_safe(self)
        return self


class LegacySqlConnectorRuntimePrGateCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    adr_gate_evidence_hash: str
    code_review_snapshot_hash: str
    test_container_snapshot_hash: str
    secret_binding_snapshot_hash: str
    network_binding_snapshot_hash: str
    rollback_probe_snapshot_hash: str
    kill_switch_probe_snapshot_hash: str
    requested_by: str
    runtime_pr_gate_requested: bool = True
    merge_requested: bool = False
    runtime_code_merge_requested: bool = False
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
            raise ValueError("legacy SQL runtime PR gate command text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL runtime PR gate command module_id must be lowercase snake_case")
        return value

    @field_validator("source_system_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL runtime PR gate command references must be namespaced")
        return value

    @field_validator(
        "adr_gate_evidence_hash",
        "code_review_snapshot_hash",
        "test_container_snapshot_hash",
        "secret_binding_snapshot_hash",
        "network_binding_snapshot_hash",
        "rollback_probe_snapshot_hash",
        "kill_switch_probe_snapshot_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL runtime PR gate command hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_safe_command(self) -> Self:
        _assert_runtime_pr_safe(self)
        return self


class LegacySqlConnectorRuntimePrGateEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_RUNTIME_PR_GATE_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    continuity_domain: str = LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN
    command_ref: str = LEGACY_SQL_CONNECTOR_RUNTIME_PR_GATE_COMMAND_REF
    adr_gate_evidence_hash: str
    code_review_snapshot_hash: str
    test_container_snapshot_hash: str
    secret_binding_snapshot_hash: str
    network_binding_snapshot_hash: str
    rollback_probe_snapshot_hash: str
    kill_switch_probe_snapshot_hash: str
    adr_gate_hash_valid: bool
    adr_gate_ready: bool
    adr_gate_bound: bool
    code_review_snapshot_hash_valid: bool
    code_review_snapshot_bound: bool
    code_review_passed: bool
    test_container_snapshot_hash_valid: bool
    test_container_snapshot_bound: bool
    test_container_passed: bool
    secret_binding_snapshot_hash_valid: bool
    secret_binding_snapshot_bound: bool
    secret_binding_passed: bool
    network_binding_snapshot_hash_valid: bool
    network_binding_snapshot_bound: bool
    network_binding_passed: bool
    rollback_probe_snapshot_hash_valid: bool
    rollback_probe_snapshot_bound: bool
    rollback_probe_passed: bool
    kill_switch_probe_snapshot_hash_valid: bool
    kill_switch_probe_snapshot_bound: bool
    kill_switch_probe_passed: bool
    runtime_pr_gate_requested: bool
    runtime_pr_gate_ready: bool
    future_runtime_merge_gate_required: bool = True
    future_live_secret_rotation_gate_required: bool = True
    future_import_dry_run_gate_required: bool = True
    merge_requested: bool = False
    merge_allowed: bool = False
    runtime_code_merge_requested: bool = False
    runtime_code_merge_allowed: bool = False
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
    gate_status: LegacySqlConnectorRuntimePrGateStatus
    blocking_reasons: tuple[str, ...]
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL runtime PR gate text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL runtime PR gate module_id must be lowercase snake_case")
        return value

    @field_validator("source_system_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL runtime PR gate references must be namespaced")
        return value

    @field_validator(
        "adr_gate_evidence_hash",
        "code_review_snapshot_hash",
        "test_container_snapshot_hash",
        "secret_binding_snapshot_hash",
        "network_binding_snapshot_hash",
        "rollback_probe_snapshot_hash",
        "kill_switch_probe_snapshot_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL runtime PR gate hashes must be sha256 references")
        return value

    @field_validator("blocking_reasons")
    @classmethod
    def validate_blocking_reasons(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("legacy SQL runtime PR gate blocking reasons must be unique")
        for reason in value:
            if not reason.strip():
                raise ValueError("legacy SQL runtime PR gate blocking reasons must not be empty")
        return value

    @model_validator(mode="after")
    def require_safe_gate(self) -> Self:
        if (
            self.merge_allowed
            or self.runtime_code_merge_allowed
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
            raise ValueError("legacy SQL runtime PR gate must remain non-executing")
        if (
            not self.future_runtime_merge_gate_required
            or not self.future_live_secret_rotation_gate_required
            or not self.future_import_dry_run_gate_required
        ):
            raise ValueError("legacy SQL runtime PR gate must require future runtime gates")
        if self.gate_status == LegacySqlConnectorRuntimePrGateStatus.READY:
            required = (
                self.adr_gate_hash_valid,
                self.adr_gate_ready,
                self.adr_gate_bound,
                self.code_review_snapshot_hash_valid,
                self.code_review_snapshot_bound,
                self.code_review_passed,
                self.test_container_snapshot_hash_valid,
                self.test_container_snapshot_bound,
                self.test_container_passed,
                self.secret_binding_snapshot_hash_valid,
                self.secret_binding_snapshot_bound,
                self.secret_binding_passed,
                self.network_binding_snapshot_hash_valid,
                self.network_binding_snapshot_bound,
                self.network_binding_passed,
                self.rollback_probe_snapshot_hash_valid,
                self.rollback_probe_snapshot_bound,
                self.rollback_probe_passed,
                self.kill_switch_probe_snapshot_hash_valid,
                self.kill_switch_probe_snapshot_bound,
                self.kill_switch_probe_passed,
                self.runtime_pr_gate_requested,
                self.runtime_pr_gate_ready,
            )
            if not all(required) or self.blocking_reasons:
                raise ValueError("ready legacy SQL runtime PR gate requires complete evidence")
        if self.gate_status == LegacySqlConnectorRuntimePrGateStatus.BLOCKED:
            if not self.blocking_reasons:
                raise ValueError("blocked legacy SQL runtime PR gate requires blocking reasons")
            if self.runtime_pr_gate_ready:
                raise ValueError("blocked legacy SQL runtime PR gate cannot be ready")
        _assert_runtime_pr_safe(self)
        return self


class LegacySqlConnectorRuntimePrGateSmokeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_RUNTIME_PR_GATE_SMOKE_SCHEMA_VERSION
    tenant_id: str
    store_backend: LegacySqlConnectorRealConnectionPolicyStoreBackend
    continuity_domain: str = LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN
    command_ref: str = LEGACY_SQL_CONNECTOR_RUNTIME_PR_GATE_COMMAND_REF
    adr_gate_evidence_hash: str
    runtime_pr_gate_evidence_hash: str
    runtime_pr_gate_ready: bool
    adr_gate_required: bool
    code_review_snapshot_required: bool
    test_container_snapshot_required: bool
    secret_binding_snapshot_required: bool
    network_binding_snapshot_required: bool
    rollback_probe_snapshot_required: bool
    kill_switch_probe_snapshot_required: bool
    adr_gate_missing_blocked: bool
    code_review_missing_blocked: bool
    test_container_missing_blocked: bool
    secret_binding_missing_blocked: bool
    network_binding_missing_blocked: bool
    rollback_probe_missing_blocked: bool
    kill_switch_probe_missing_blocked: bool
    merge_request_blocked: bool
    future_runtime_merge_gate_required: bool
    future_live_secret_rotation_gate_required: bool
    future_import_dry_run_gate_required: bool
    merge_allowed: bool = False
    runtime_code_merge_allowed: bool = False
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
            self.merge_allowed
            or self.runtime_code_merge_allowed
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
            raise ValueError("legacy SQL runtime PR smoke must remain non-executing")
        _assert_runtime_pr_safe(self)
        return self


def build_legacy_sql_connector_runtime_pr_code_review_snapshot(
    *,
    adr_gate: LegacySqlConnectorSocketSecretImplementationAdrGateEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    passed: bool = True,
) -> LegacySqlConnectorRuntimePrEvidenceSnapshot:
    return _build_snapshot(
        schema_version=LEGACY_SQL_CONNECTOR_RUNTIME_PR_CODE_REVIEW_SNAPSHOT_SCHEMA_VERSION,
        snapshot_ref="runtime-pr-code-review:legacy-sql-runtime-pr",
        adr_gate=adr_gate,
        required_controls=(
            "code_owner_review",
            "security_review",
            "test_plan_review",
            "no_prompt_output_logging",
            "no_raw_data_logging",
            "no_destructive_action_path",
            "direct_db_driver_usage_forbidden",
        ),
        failed_controls=() if passed else ("code_owner_review",),
        checked_by=checked_by,
        checked_at_utc=checked_at_utc,
    )


def build_legacy_sql_connector_runtime_pr_test_container_snapshot(
    *,
    adr_gate: LegacySqlConnectorSocketSecretImplementationAdrGateEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    passed: bool = True,
) -> LegacySqlConnectorRuntimePrEvidenceSnapshot:
    return _build_snapshot(
        schema_version=LEGACY_SQL_CONNECTOR_RUNTIME_PR_TEST_CONTAINER_SNAPSHOT_SCHEMA_VERSION,
        snapshot_ref="runtime-pr-test-container:legacy-sql-runtime-pr",
        adr_gate=adr_gate,
        required_controls=(
            "read_only_filesystem",
            "cap_drop_all",
            "no_new_privileges",
            "tmpfs_noexec",
            "live_secret_tests_forbidden",
            "external_network_disabled_by_default",
            "runtime_tests_passed",
        ),
        failed_controls=() if passed else ("runtime_tests_passed",),
        checked_by=checked_by,
        checked_at_utc=checked_at_utc,
    )


def build_legacy_sql_connector_runtime_pr_secret_binding_snapshot(
    *,
    adr_gate: LegacySqlConnectorSocketSecretImplementationAdrGateEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    passed: bool = True,
) -> LegacySqlConnectorRuntimePrEvidenceSnapshot:
    return _build_snapshot(
        schema_version=LEGACY_SQL_CONNECTOR_RUNTIME_PR_SECRET_BINDING_SNAPSHOT_SCHEMA_VERSION,
        snapshot_ref="runtime-pr-secret-binding:legacy-sql-runtime-pr",
        adr_gate=adr_gate,
        upstream_evidence_hashes=(adr_gate.secret_manager_snapshot_hash,),
        required_controls=(
            "runtime_secret_binding_reviewed",
            "sealed_secret_only",
            "no_plaintext_secret_ref",
            "tenant_kms_binding_required",
            "secret_material_not_resolved",
        ),
        failed_controls=() if passed else ("runtime_secret_binding_reviewed",),
        checked_by=checked_by,
        checked_at_utc=checked_at_utc,
    )


def build_legacy_sql_connector_runtime_pr_network_binding_snapshot(
    *,
    adr_gate: LegacySqlConnectorSocketSecretImplementationAdrGateEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    passed: bool = True,
) -> LegacySqlConnectorRuntimePrEvidenceSnapshot:
    return _build_snapshot(
        schema_version=LEGACY_SQL_CONNECTOR_RUNTIME_PR_NETWORK_BINDING_SNAPSHOT_SCHEMA_VERSION,
        snapshot_ref="runtime-pr-network-binding:legacy-sql-runtime-pr",
        adr_gate=adr_gate,
        upstream_evidence_hashes=(adr_gate.network_route_snapshot_hash,),
        required_controls=(
            "runtime_route_binding_reviewed",
            "tenant_route_isolated",
            "egress_allowlist_bound",
            "inbound_access_forbidden",
            "network_not_opened",
        ),
        failed_controls=() if passed else ("runtime_route_binding_reviewed",),
        checked_by=checked_by,
        checked_at_utc=checked_at_utc,
    )


def build_legacy_sql_connector_runtime_pr_rollback_probe_snapshot(
    *,
    adr_gate: LegacySqlConnectorSocketSecretImplementationAdrGateEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    passed: bool = True,
) -> LegacySqlConnectorRuntimePrEvidenceSnapshot:
    return _build_snapshot(
        schema_version=LEGACY_SQL_CONNECTOR_RUNTIME_PR_ROLLBACK_PROBE_SNAPSHOT_SCHEMA_VERSION,
        snapshot_ref="runtime-pr-rollback-probe:legacy-sql-runtime-pr",
        adr_gate=adr_gate,
        upstream_evidence_hashes=(adr_gate.rollback_runbook_snapshot_hash,),
        required_controls=(
            "rollback_probe_passed",
            "restore_checkpoint_verified",
            "recover_without_import_writes",
            "destructive_rollback_forbidden",
        ),
        failed_controls=() if passed else ("rollback_probe_passed",),
        checked_by=checked_by,
        checked_at_utc=checked_at_utc,
    )


def build_legacy_sql_connector_runtime_pr_kill_switch_probe_snapshot(
    *,
    adr_gate: LegacySqlConnectorSocketSecretImplementationAdrGateEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    passed: bool = True,
) -> LegacySqlConnectorRuntimePrEvidenceSnapshot:
    return _build_snapshot(
        schema_version=LEGACY_SQL_CONNECTOR_RUNTIME_PR_KILL_SWITCH_PROBE_SNAPSHOT_SCHEMA_VERSION,
        snapshot_ref="runtime-pr-kill-switch-probe:legacy-sql-runtime-pr",
        adr_gate=adr_gate,
        upstream_evidence_hashes=(adr_gate.kill_switch_runbook_snapshot_hash,),
        required_controls=(
            "kill_switch_probe_passed",
            "kill_switch_armed",
            "tenant_kill_switch_checked",
            "global_kill_switch_checked",
            "manual_abort_checked",
            "break_glass_forbidden",
        ),
        failed_controls=() if passed else ("kill_switch_probe_passed",),
        checked_by=checked_by,
        checked_at_utc=checked_at_utc,
    )


def build_legacy_sql_connector_runtime_pr_gate_command(
    *,
    adr_gate: LegacySqlConnectorSocketSecretImplementationAdrGateEvidence,
    code_review_snapshot: LegacySqlConnectorRuntimePrEvidenceSnapshot,
    test_container_snapshot: LegacySqlConnectorRuntimePrEvidenceSnapshot,
    secret_binding_snapshot: LegacySqlConnectorRuntimePrEvidenceSnapshot,
    network_binding_snapshot: LegacySqlConnectorRuntimePrEvidenceSnapshot,
    rollback_probe_snapshot: LegacySqlConnectorRuntimePrEvidenceSnapshot,
    kill_switch_probe_snapshot: LegacySqlConnectorRuntimePrEvidenceSnapshot,
    requested_by: str,
    runtime_pr_gate_requested: bool = True,
    merge_requested: bool = False,
    runtime_code_merge_requested: bool = False,
    socket_runtime_execution_requested: bool = False,
    secret_materialization_requested: bool = False,
    raw_data_access_requested: bool = False,
    import_dry_run_requested: bool = False,
    import_write_requested: bool = False,
    destructive_actions_requested: bool = False,
) -> LegacySqlConnectorRuntimePrGateCommand:
    return LegacySqlConnectorRuntimePrGateCommand(
        tenant_id=adr_gate.tenant_id,
        module_id=adr_gate.module_id,
        source_system_ref=adr_gate.source_system_ref,
        connector_kind=adr_gate.connector_kind,
        adr_gate_evidence_hash=adr_gate.evidence_hash,
        code_review_snapshot_hash=code_review_snapshot.evidence_hash,
        test_container_snapshot_hash=test_container_snapshot.evidence_hash,
        secret_binding_snapshot_hash=secret_binding_snapshot.evidence_hash,
        network_binding_snapshot_hash=network_binding_snapshot.evidence_hash,
        rollback_probe_snapshot_hash=rollback_probe_snapshot.evidence_hash,
        kill_switch_probe_snapshot_hash=kill_switch_probe_snapshot.evidence_hash,
        requested_by=requested_by,
        runtime_pr_gate_requested=runtime_pr_gate_requested,
        merge_requested=merge_requested,
        runtime_code_merge_requested=runtime_code_merge_requested,
        socket_runtime_execution_requested=socket_runtime_execution_requested,
        secret_materialization_requested=secret_materialization_requested,
        raw_data_access_requested=raw_data_access_requested,
        import_dry_run_requested=import_dry_run_requested,
        import_write_requested=import_write_requested,
        destructive_actions_requested=destructive_actions_requested,
    )


def build_legacy_sql_connector_runtime_pr_gate(
    *,
    command: LegacySqlConnectorRuntimePrGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    adr_gate: LegacySqlConnectorSocketSecretImplementationAdrGateEvidence,
    code_review_snapshot: LegacySqlConnectorRuntimePrEvidenceSnapshot,
    test_container_snapshot: LegacySqlConnectorRuntimePrEvidenceSnapshot,
    secret_binding_snapshot: LegacySqlConnectorRuntimePrEvidenceSnapshot,
    network_binding_snapshot: LegacySqlConnectorRuntimePrEvidenceSnapshot,
    rollback_probe_snapshot: LegacySqlConnectorRuntimePrEvidenceSnapshot,
    kill_switch_probe_snapshot: LegacySqlConnectorRuntimePrEvidenceSnapshot,
    checked_by: str,
    checked_at_utc: datetime | None = None,
) -> LegacySqlConnectorRuntimePrGateEvidence:
    checked_at = checked_at_utc or datetime.now(UTC)
    adr_gate_hash_valid = (
        build_legacy_sql_connector_socket_secret_implementation_adr_gate_hash(adr_gate)
        == adr_gate.evidence_hash
        == command.adr_gate_evidence_hash
    )
    adr_gate_ready = (
        adr_gate.gate_status == LegacySqlConnectorSocketSecretImplementationAdrGateStatus.READY
        and adr_gate.implementation_adr_ready
        and adr_gate.future_socket_secret_runtime_pr_required
    )
    adr_gate_bound = _adr_gate_bound(command=command, bundle=bundle, adr_gate=adr_gate)
    code_review_hash_valid = _snapshot_hash_valid(code_review_snapshot, command.code_review_snapshot_hash)
    test_container_hash_valid = _snapshot_hash_valid(test_container_snapshot, command.test_container_snapshot_hash)
    secret_binding_hash_valid = _snapshot_hash_valid(secret_binding_snapshot, command.secret_binding_snapshot_hash)
    network_binding_hash_valid = _snapshot_hash_valid(network_binding_snapshot, command.network_binding_snapshot_hash)
    rollback_probe_hash_valid = _snapshot_hash_valid(rollback_probe_snapshot, command.rollback_probe_snapshot_hash)
    kill_switch_probe_hash_valid = _snapshot_hash_valid(
        kill_switch_probe_snapshot, command.kill_switch_probe_snapshot_hash
    )
    code_review_bound = _snapshot_bound(
        command=command,
        adr_gate=adr_gate,
        snapshot=code_review_snapshot,
        expected_schema=LEGACY_SQL_CONNECTOR_RUNTIME_PR_CODE_REVIEW_SNAPSHOT_SCHEMA_VERSION,
    )
    test_container_bound = _snapshot_bound(
        command=command,
        adr_gate=adr_gate,
        snapshot=test_container_snapshot,
        expected_schema=LEGACY_SQL_CONNECTOR_RUNTIME_PR_TEST_CONTAINER_SNAPSHOT_SCHEMA_VERSION,
    )
    secret_binding_bound = _snapshot_bound(
        command=command,
        adr_gate=adr_gate,
        snapshot=secret_binding_snapshot,
        expected_schema=LEGACY_SQL_CONNECTOR_RUNTIME_PR_SECRET_BINDING_SNAPSHOT_SCHEMA_VERSION,
        required_upstream_hash=adr_gate.secret_manager_snapshot_hash,
    )
    network_binding_bound = _snapshot_bound(
        command=command,
        adr_gate=adr_gate,
        snapshot=network_binding_snapshot,
        expected_schema=LEGACY_SQL_CONNECTOR_RUNTIME_PR_NETWORK_BINDING_SNAPSHOT_SCHEMA_VERSION,
        required_upstream_hash=adr_gate.network_route_snapshot_hash,
    )
    rollback_probe_bound = _snapshot_bound(
        command=command,
        adr_gate=adr_gate,
        snapshot=rollback_probe_snapshot,
        expected_schema=LEGACY_SQL_CONNECTOR_RUNTIME_PR_ROLLBACK_PROBE_SNAPSHOT_SCHEMA_VERSION,
        required_upstream_hash=adr_gate.rollback_runbook_snapshot_hash,
    )
    kill_switch_probe_bound = _snapshot_bound(
        command=command,
        adr_gate=adr_gate,
        snapshot=kill_switch_probe_snapshot,
        expected_schema=LEGACY_SQL_CONNECTOR_RUNTIME_PR_KILL_SWITCH_PROBE_SNAPSHOT_SCHEMA_VERSION,
        required_upstream_hash=adr_gate.kill_switch_runbook_snapshot_hash,
    )
    code_review_passed = _snapshot_passed(code_review_snapshot)
    test_container_passed = _snapshot_passed(test_container_snapshot)
    secret_binding_passed = _snapshot_passed(secret_binding_snapshot)
    network_binding_passed = _snapshot_passed(network_binding_snapshot)
    rollback_probe_passed = _snapshot_passed(rollback_probe_snapshot)
    kill_switch_probe_passed = _snapshot_passed(kill_switch_probe_snapshot)
    blocking_reasons = _runtime_pr_blocking_reasons(
        command=command,
        adr_gate_hash_valid=adr_gate_hash_valid,
        adr_gate_ready=adr_gate_ready,
        adr_gate_bound=adr_gate_bound,
        snapshot_checks=(
            ("code_review", code_review_hash_valid, code_review_bound, code_review_passed, code_review_snapshot),
            (
                "test_container",
                test_container_hash_valid,
                test_container_bound,
                test_container_passed,
                test_container_snapshot,
            ),
            (
                "secret_binding",
                secret_binding_hash_valid,
                secret_binding_bound,
                secret_binding_passed,
                secret_binding_snapshot,
            ),
            (
                "network_binding",
                network_binding_hash_valid,
                network_binding_bound,
                network_binding_passed,
                network_binding_snapshot,
            ),
            (
                "rollback_probe",
                rollback_probe_hash_valid,
                rollback_probe_bound,
                rollback_probe_passed,
                rollback_probe_snapshot,
            ),
            (
                "kill_switch_probe",
                kill_switch_probe_hash_valid,
                kill_switch_probe_bound,
                kill_switch_probe_passed,
                kill_switch_probe_snapshot,
            ),
        ),
    )
    ready = not blocking_reasons
    draft = LegacySqlConnectorRuntimePrGateEvidence(
        tenant_id=adr_gate.tenant_id,
        module_id=adr_gate.module_id,
        source_system_ref=adr_gate.source_system_ref,
        connector_kind=adr_gate.connector_kind,
        adr_gate_evidence_hash=adr_gate.evidence_hash,
        code_review_snapshot_hash=code_review_snapshot.evidence_hash,
        test_container_snapshot_hash=test_container_snapshot.evidence_hash,
        secret_binding_snapshot_hash=secret_binding_snapshot.evidence_hash,
        network_binding_snapshot_hash=network_binding_snapshot.evidence_hash,
        rollback_probe_snapshot_hash=rollback_probe_snapshot.evidence_hash,
        kill_switch_probe_snapshot_hash=kill_switch_probe_snapshot.evidence_hash,
        adr_gate_hash_valid=adr_gate_hash_valid,
        adr_gate_ready=adr_gate_ready,
        adr_gate_bound=adr_gate_bound,
        code_review_snapshot_hash_valid=code_review_hash_valid,
        code_review_snapshot_bound=code_review_bound,
        code_review_passed=code_review_passed,
        test_container_snapshot_hash_valid=test_container_hash_valid,
        test_container_snapshot_bound=test_container_bound,
        test_container_passed=test_container_passed,
        secret_binding_snapshot_hash_valid=secret_binding_hash_valid,
        secret_binding_snapshot_bound=secret_binding_bound,
        secret_binding_passed=secret_binding_passed,
        network_binding_snapshot_hash_valid=network_binding_hash_valid,
        network_binding_snapshot_bound=network_binding_bound,
        network_binding_passed=network_binding_passed,
        rollback_probe_snapshot_hash_valid=rollback_probe_hash_valid,
        rollback_probe_snapshot_bound=rollback_probe_bound,
        rollback_probe_passed=rollback_probe_passed,
        kill_switch_probe_snapshot_hash_valid=kill_switch_probe_hash_valid,
        kill_switch_probe_snapshot_bound=kill_switch_probe_bound,
        kill_switch_probe_passed=kill_switch_probe_passed,
        runtime_pr_gate_requested=command.runtime_pr_gate_requested,
        runtime_pr_gate_ready=ready,
        merge_requested=command.merge_requested,
        runtime_code_merge_requested=command.runtime_code_merge_requested,
        socket_runtime_execution_requested=command.socket_runtime_execution_requested,
        secret_materialization_requested=command.secret_materialization_requested,
        raw_data_access_requested=command.raw_data_access_requested,
        import_dry_run_requested=command.import_dry_run_requested,
        import_write_requested=command.import_write_requested,
        destructive_actions_requested=command.destructive_actions_requested,
        gate_status=LegacySqlConnectorRuntimePrGateStatus.READY
        if ready
        else LegacySqlConnectorRuntimePrGateStatus.BLOCKED,
        blocking_reasons=blocking_reasons,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_connector_runtime_pr_gate_hash(draft)})


def build_legacy_sql_connector_runtime_pr_snapshot_hash(snapshot: LegacySqlConnectorRuntimePrEvidenceSnapshot) -> str:
    return stable_hash(canonical_json(snapshot.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_runtime_pr_gate_hash(gate: LegacySqlConnectorRuntimePrGateEvidence) -> str:
    return stable_hash(canonical_json(gate.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_runtime_pr_gate_smoke_report_hash(
    report: LegacySqlConnectorRuntimePrGateSmokeReport,
) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def run_legacy_sql_connector_runtime_pr_gate_smoke_from_env(
    environ: Mapping[str, str] | None = None,
) -> LegacySqlConnectorRuntimePrGateSmokeReport:
    env = os.environ if environ is None else environ
    checked_by = env.get(
        "SUITE_LEGACY_SQL_CONNECTOR_RUNTIME_PR_GATE_CHECKED_BY", "legacy-sql-connector-runtime-pr-gate-smoke"
    )
    checked_at = datetime.now(UTC)
    store_backend = LegacySqlConnectorRealConnectionPolicyStoreBackend(
        env.get(
            "SUITE_LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_POLICY_STORE_BACKEND",
            LegacySqlConnectorRealConnectionPolicyStoreBackend.JSONL.value,
        )
    )
    bundle, adr_gate = _build_ready_adr_gate(env=env, checked_by=checked_by, checked_at=checked_at)
    snapshots = _build_ready_runtime_pr_snapshots(adr_gate=adr_gate, checked_by=checked_by, checked_at=checked_at)
    command = _build_runtime_pr_command_from_snapshots(
        adr_gate=adr_gate,
        snapshots=snapshots,
        requested_by=checked_by,
    )
    gate = _build_runtime_pr_gate_from_snapshots(
        command=command,
        bundle=bundle,
        adr_gate=adr_gate,
        snapshots=snapshots,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=50),
    )
    adr_gate_missing_blocked = _adr_gate_missing_blocked(
        command, bundle, adr_gate, snapshots, checked_by, checked_at + timedelta(seconds=51)
    )
    code_review_missing_blocked = _snapshot_missing_blocked(
        command,
        bundle,
        adr_gate,
        snapshots,
        "code_review_snapshot",
        "code_owner_review",
        "code_review_snapshot_failed",
        checked_by,
        checked_at + timedelta(seconds=52),
    )
    test_container_missing_blocked = _snapshot_missing_blocked(
        command,
        bundle,
        adr_gate,
        snapshots,
        "test_container_snapshot",
        "runtime_tests_passed",
        "test_container_snapshot_failed",
        checked_by,
        checked_at + timedelta(seconds=53),
    )
    secret_binding_missing_blocked = _snapshot_missing_blocked(
        command,
        bundle,
        adr_gate,
        snapshots,
        "secret_binding_snapshot",
        "runtime_secret_binding_reviewed",
        "secret_binding_snapshot_failed",
        checked_by,
        checked_at + timedelta(seconds=54),
    )
    network_binding_missing_blocked = _snapshot_missing_blocked(
        command,
        bundle,
        adr_gate,
        snapshots,
        "network_binding_snapshot",
        "runtime_route_binding_reviewed",
        "network_binding_snapshot_failed",
        checked_by,
        checked_at + timedelta(seconds=55),
    )
    rollback_probe_missing_blocked = _snapshot_missing_blocked(
        command,
        bundle,
        adr_gate,
        snapshots,
        "rollback_probe_snapshot",
        "rollback_probe_passed",
        "rollback_probe_snapshot_failed",
        checked_by,
        checked_at + timedelta(seconds=56),
    )
    kill_switch_probe_missing_blocked = _snapshot_missing_blocked(
        command,
        bundle,
        adr_gate,
        snapshots,
        "kill_switch_probe_snapshot",
        "kill_switch_probe_passed",
        "kill_switch_probe_snapshot_failed",
        checked_by,
        checked_at + timedelta(seconds=57),
    )
    merge_request_blocked = _merge_request_blocked(
        command, bundle, adr_gate, snapshots, checked_by, checked_at + timedelta(seconds=58)
    )
    runtime_pr_gate_ready = (
        gate.gate_status == LegacySqlConnectorRuntimePrGateStatus.READY
        and gate.runtime_pr_gate_ready
        and adr_gate_missing_blocked
        and code_review_missing_blocked
        and test_container_missing_blocked
        and secret_binding_missing_blocked
        and network_binding_missing_blocked
        and rollback_probe_missing_blocked
        and kill_switch_probe_missing_blocked
        and merge_request_blocked
        and not gate.merge_allowed
        and not gate.runtime_code_merge_allowed
        and not gate.real_connection_opened
    )
    draft = LegacySqlConnectorRuntimePrGateSmokeReport(
        tenant_id=bundle.tenant_id,
        store_backend=store_backend,
        adr_gate_evidence_hash=adr_gate.evidence_hash,
        runtime_pr_gate_evidence_hash=gate.evidence_hash,
        runtime_pr_gate_ready=runtime_pr_gate_ready,
        adr_gate_required=gate.adr_gate_bound and gate.adr_gate_ready,
        code_review_snapshot_required=gate.code_review_snapshot_bound and gate.code_review_passed,
        test_container_snapshot_required=gate.test_container_snapshot_bound and gate.test_container_passed,
        secret_binding_snapshot_required=gate.secret_binding_snapshot_bound and gate.secret_binding_passed,
        network_binding_snapshot_required=gate.network_binding_snapshot_bound and gate.network_binding_passed,
        rollback_probe_snapshot_required=gate.rollback_probe_snapshot_bound and gate.rollback_probe_passed,
        kill_switch_probe_snapshot_required=gate.kill_switch_probe_snapshot_bound and gate.kill_switch_probe_passed,
        adr_gate_missing_blocked=adr_gate_missing_blocked,
        code_review_missing_blocked=code_review_missing_blocked,
        test_container_missing_blocked=test_container_missing_blocked,
        secret_binding_missing_blocked=secret_binding_missing_blocked,
        network_binding_missing_blocked=network_binding_missing_blocked,
        rollback_probe_missing_blocked=rollback_probe_missing_blocked,
        kill_switch_probe_missing_blocked=kill_switch_probe_missing_blocked,
        merge_request_blocked=merge_request_blocked,
        future_runtime_merge_gate_required=gate.future_runtime_merge_gate_required,
        future_live_secret_rotation_gate_required=gate.future_live_secret_rotation_gate_required,
        future_import_dry_run_gate_required=gate.future_import_dry_run_gate_required,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    _assert_runtime_pr_safe(draft)
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_runtime_pr_gate_smoke_report_hash(draft)}
    )


def exit_code_for_report(report: LegacySqlConnectorRuntimePrGateSmokeReport) -> int:
    return 0 if report.runtime_pr_gate_ready else 1


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Legacy SQL runtime PR gate smoke.")
    parser.add_argument("--once", action="store_true", help="Run one non-executing runtime PR gate smoke and exit.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the runtime PR gate report.")
    args = parser.parse_args(argv)
    del args.once

    report = run_legacy_sql_connector_runtime_pr_gate_smoke_from_env()
    print(json.dumps(report.model_dump(mode="json"), indent=2 if args.pretty else None, sort_keys=True))
    raise SystemExit(exit_code_for_report(report))


def _build_snapshot(
    *,
    schema_version: str,
    snapshot_ref: str,
    adr_gate: LegacySqlConnectorSocketSecretImplementationAdrGateEvidence,
    required_controls: tuple[str, ...],
    failed_controls: tuple[str, ...],
    checked_by: str,
    checked_at_utc: datetime | None,
    upstream_evidence_hashes: tuple[str, ...] = (),
) -> LegacySqlConnectorRuntimePrEvidenceSnapshot:
    checked_at = checked_at_utc or datetime.now(UTC)
    passed_controls = tuple(control for control in required_controls if control not in failed_controls)
    draft = LegacySqlConnectorRuntimePrEvidenceSnapshot(
        schema_version=schema_version,
        tenant_id=adr_gate.tenant_id,
        module_id=adr_gate.module_id,
        source_system_ref=adr_gate.source_system_ref,
        connector_kind=adr_gate.connector_kind,
        snapshot_ref=snapshot_ref,
        adr_gate_evidence_hash=adr_gate.evidence_hash,
        upstream_evidence_hashes=upstream_evidence_hashes,
        required_controls=required_controls,
        passed_controls=passed_controls,
        failed_controls=failed_controls,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_connector_runtime_pr_snapshot_hash(draft)})


def _build_ready_adr_gate(
    *,
    env: Mapping[str, str],
    checked_by: str,
    checked_at: datetime,
) -> tuple[
    LegacySqlConnectorRealConnectionExecutorPolicyBundle, LegacySqlConnectorSocketSecretImplementationAdrGateEvidence
]:
    bundle, materialization_gate, materialization_kill_switch_snapshot = _build_ready_materialization_chain(
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
        kill_switch_snapshot=materialization_kill_switch_snapshot,
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
    adr_gate = build_legacy_sql_connector_socket_secret_implementation_adr_gate(
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
    return bundle, adr_gate


def _build_ready_runtime_pr_snapshots(
    *,
    adr_gate: LegacySqlConnectorSocketSecretImplementationAdrGateEvidence,
    checked_by: str,
    checked_at: datetime,
) -> dict[str, LegacySqlConnectorRuntimePrEvidenceSnapshot]:
    return {
        "code_review_snapshot": build_legacy_sql_connector_runtime_pr_code_review_snapshot(
            adr_gate=adr_gate,
            checked_by=checked_by,
            checked_at_utc=checked_at + timedelta(seconds=44),
        ),
        "test_container_snapshot": build_legacy_sql_connector_runtime_pr_test_container_snapshot(
            adr_gate=adr_gate,
            checked_by=checked_by,
            checked_at_utc=checked_at + timedelta(seconds=45),
        ),
        "secret_binding_snapshot": build_legacy_sql_connector_runtime_pr_secret_binding_snapshot(
            adr_gate=adr_gate,
            checked_by=checked_by,
            checked_at_utc=checked_at + timedelta(seconds=46),
        ),
        "network_binding_snapshot": build_legacy_sql_connector_runtime_pr_network_binding_snapshot(
            adr_gate=adr_gate,
            checked_by=checked_by,
            checked_at_utc=checked_at + timedelta(seconds=47),
        ),
        "rollback_probe_snapshot": build_legacy_sql_connector_runtime_pr_rollback_probe_snapshot(
            adr_gate=adr_gate,
            checked_by=checked_by,
            checked_at_utc=checked_at + timedelta(seconds=48),
        ),
        "kill_switch_probe_snapshot": build_legacy_sql_connector_runtime_pr_kill_switch_probe_snapshot(
            adr_gate=adr_gate,
            checked_by=checked_by,
            checked_at_utc=checked_at + timedelta(seconds=49),
        ),
    }


def _snapshot_hash_valid(snapshot: LegacySqlConnectorRuntimePrEvidenceSnapshot, expected_hash: str) -> bool:
    return build_legacy_sql_connector_runtime_pr_snapshot_hash(snapshot) == snapshot.evidence_hash == expected_hash


def _snapshot_passed(snapshot: LegacySqlConnectorRuntimePrEvidenceSnapshot) -> bool:
    return not snapshot.failed_controls and set(snapshot.required_controls) == set(snapshot.passed_controls)


def _snapshot_bound(
    *,
    command: LegacySqlConnectorRuntimePrGateCommand,
    adr_gate: LegacySqlConnectorSocketSecretImplementationAdrGateEvidence,
    snapshot: LegacySqlConnectorRuntimePrEvidenceSnapshot,
    expected_schema: str,
    required_upstream_hash: str | None = None,
) -> bool:
    upstream_bound = required_upstream_hash is None or required_upstream_hash in snapshot.upstream_evidence_hashes
    return (
        command.tenant_id == adr_gate.tenant_id == snapshot.tenant_id
        and command.module_id == adr_gate.module_id == snapshot.module_id
        and command.source_system_ref == adr_gate.source_system_ref == snapshot.source_system_ref
        and command.connector_kind == adr_gate.connector_kind == snapshot.connector_kind
        and snapshot.schema_version == expected_schema
        and snapshot.adr_gate_evidence_hash == adr_gate.evidence_hash
        and upstream_bound
    )


def _adr_gate_bound(
    *,
    command: LegacySqlConnectorRuntimePrGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    adr_gate: LegacySqlConnectorSocketSecretImplementationAdrGateEvidence,
) -> bool:
    return (
        command.tenant_id == bundle.tenant_id == adr_gate.tenant_id
        and command.module_id == bundle.module_id == adr_gate.module_id
        and command.source_system_ref == bundle.source_system_ref == adr_gate.source_system_ref
        and command.connector_kind == bundle.connector_kind == adr_gate.connector_kind
        and command.adr_gate_evidence_hash == adr_gate.evidence_hash
        and not adr_gate.socket_implementation_allowed
        and not adr_gate.secret_materialization_allowed
        and not adr_gate.executor_code_allowed
        and not adr_gate.network_socket_opened
        and not adr_gate.secret_material_resolved
    )


def _runtime_pr_blocking_reasons(
    *,
    command: LegacySqlConnectorRuntimePrGateCommand,
    adr_gate_hash_valid: bool,
    adr_gate_ready: bool,
    adr_gate_bound: bool,
    snapshot_checks: tuple[tuple[str, bool, bool, bool, LegacySqlConnectorRuntimePrEvidenceSnapshot], ...],
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not adr_gate_hash_valid:
        reasons.append("adr_gate_hash_invalid")
    if not adr_gate_ready:
        reasons.append("adr_gate_not_ready")
    if not adr_gate_bound:
        reasons.append("adr_gate_not_bound")
    for prefix, hash_valid, bound, passed, snapshot in snapshot_checks:
        if not hash_valid:
            reasons.append(f"{prefix}_snapshot_hash_invalid")
        if not bound:
            reasons.append(f"{prefix}_snapshot_not_bound")
        if not passed:
            reasons.append(f"{prefix}_snapshot_failed")
        for failed_control in snapshot.failed_controls:
            reasons.append(f"{prefix}_{failed_control}_failed")
    if not command.runtime_pr_gate_requested:
        reasons.append("runtime_pr_gate_not_requested")
    if command.merge_requested:
        reasons.append("merge_requires_future_runtime_merge_gate")
    if command.runtime_code_merge_requested:
        reasons.append("runtime_code_merge_requires_future_runtime_merge_gate")
    if command.socket_runtime_execution_requested:
        reasons.append("socket_runtime_execution_requires_future_execution_gate")
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


def _build_runtime_pr_command_from_snapshots(
    *,
    adr_gate: LegacySqlConnectorSocketSecretImplementationAdrGateEvidence,
    snapshots: dict[str, LegacySqlConnectorRuntimePrEvidenceSnapshot],
    requested_by: str,
) -> LegacySqlConnectorRuntimePrGateCommand:
    return build_legacy_sql_connector_runtime_pr_gate_command(
        adr_gate=adr_gate,
        code_review_snapshot=snapshots["code_review_snapshot"],
        test_container_snapshot=snapshots["test_container_snapshot"],
        secret_binding_snapshot=snapshots["secret_binding_snapshot"],
        network_binding_snapshot=snapshots["network_binding_snapshot"],
        rollback_probe_snapshot=snapshots["rollback_probe_snapshot"],
        kill_switch_probe_snapshot=snapshots["kill_switch_probe_snapshot"],
        requested_by=requested_by,
    )


def _build_runtime_pr_gate_from_snapshots(
    *,
    command: LegacySqlConnectorRuntimePrGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    adr_gate: LegacySqlConnectorSocketSecretImplementationAdrGateEvidence,
    snapshots: dict[str, LegacySqlConnectorRuntimePrEvidenceSnapshot],
    checked_by: str,
    checked_at_utc: datetime,
) -> LegacySqlConnectorRuntimePrGateEvidence:
    return build_legacy_sql_connector_runtime_pr_gate(
        command=command,
        bundle=bundle,
        adr_gate=adr_gate,
        code_review_snapshot=snapshots["code_review_snapshot"],
        test_container_snapshot=snapshots["test_container_snapshot"],
        secret_binding_snapshot=snapshots["secret_binding_snapshot"],
        network_binding_snapshot=snapshots["network_binding_snapshot"],
        rollback_probe_snapshot=snapshots["rollback_probe_snapshot"],
        kill_switch_probe_snapshot=snapshots["kill_switch_probe_snapshot"],
        checked_by=checked_by,
        checked_at_utc=checked_at_utc,
    )


def _adr_gate_missing_blocked(
    command: LegacySqlConnectorRuntimePrGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    adr_gate: LegacySqlConnectorSocketSecretImplementationAdrGateEvidence,
    snapshots: dict[str, LegacySqlConnectorRuntimePrEvidenceSnapshot],
    checked_by: str,
    checked_at: datetime,
) -> bool:
    blocked_adr = adr_gate.model_copy(
        update={
            "gate_status": LegacySqlConnectorSocketSecretImplementationAdrGateStatus.BLOCKED,
            "implementation_adr_ready": False,
            "blocking_reasons": ("runtime_pr_test_adr_gate_missing",),
            "checked_at_utc": checked_at,
            "evidence_hash": ZERO_HASH,
        }
    )
    blocked_adr = blocked_adr.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_socket_secret_implementation_adr_gate_hash(blocked_adr)}
    )
    blocked = _build_runtime_pr_gate_from_snapshots(
        command=command.model_copy(update={"adr_gate_evidence_hash": blocked_adr.evidence_hash}),
        bundle=bundle,
        adr_gate=blocked_adr,
        snapshots=snapshots,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        blocked.gate_status == LegacySqlConnectorRuntimePrGateStatus.BLOCKED
        and "adr_gate_not_ready" in blocked.blocking_reasons
    )


def _snapshot_missing_blocked(
    command: LegacySqlConnectorRuntimePrGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    adr_gate: LegacySqlConnectorSocketSecretImplementationAdrGateEvidence,
    snapshots: dict[str, LegacySqlConnectorRuntimePrEvidenceSnapshot],
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
        update={"evidence_hash": build_legacy_sql_connector_runtime_pr_snapshot_hash(blocked_snapshot)}
    )
    updated_snapshots[snapshot_key] = blocked_snapshot
    command_field = f"{snapshot_key}_hash"
    blocked = _build_runtime_pr_gate_from_snapshots(
        command=command.model_copy(update={command_field: blocked_snapshot.evidence_hash}),
        bundle=bundle,
        adr_gate=adr_gate,
        snapshots=updated_snapshots,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        blocked.gate_status == LegacySqlConnectorRuntimePrGateStatus.BLOCKED
        and expected_reason in blocked.blocking_reasons
    )


def _merge_request_blocked(
    command: LegacySqlConnectorRuntimePrGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    adr_gate: LegacySqlConnectorSocketSecretImplementationAdrGateEvidence,
    snapshots: dict[str, LegacySqlConnectorRuntimePrEvidenceSnapshot],
    checked_by: str,
    checked_at: datetime,
) -> bool:
    blocked = _build_runtime_pr_gate_from_snapshots(
        command=command.model_copy(
            update={
                "merge_requested": True,
                "runtime_code_merge_requested": True,
                "socket_runtime_execution_requested": True,
                "secret_materialization_requested": True,
                "raw_data_access_requested": True,
            }
        ),
        bundle=bundle,
        adr_gate=adr_gate,
        snapshots=snapshots,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        blocked.gate_status == LegacySqlConnectorRuntimePrGateStatus.BLOCKED
        and "merge_requires_future_runtime_merge_gate" in blocked.blocking_reasons
        and "runtime_code_merge_requires_future_runtime_merge_gate" in blocked.blocking_reasons
        and "socket_runtime_execution_requires_future_execution_gate" in blocked.blocking_reasons
        and "secret_materialization_requires_future_secret_gate" in blocked.blocking_reasons
        and "raw_data_access_requires_future_data_gate" in blocked.blocking_reasons
        and not blocked.merge_allowed
        and not blocked.runtime_code_merge_allowed
    )


def _assert_runtime_pr_safe(value: BaseModel) -> None:
    payload = value.model_dump_json().lower()
    for fragment in FORBIDDEN_RUNTIME_PR_FRAGMENTS:
        if fragment in payload:
            raise ValueError(f"legacy SQL runtime PR evidence contains forbidden fragment: {fragment}")
