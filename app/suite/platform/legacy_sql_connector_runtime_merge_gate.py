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
from suite.platform.legacy_sql_connector_runtime_pr_gate import (
    LegacySqlConnectorRuntimePrGateEvidence,
    LegacySqlConnectorRuntimePrGateStatus,
    _build_ready_adr_gate,
    _build_ready_runtime_pr_snapshots,
    _build_runtime_pr_command_from_snapshots,
    _build_runtime_pr_gate_from_snapshots,
    build_legacy_sql_connector_runtime_pr_gate_hash,
)
from suite.platform.legacy_sql_discovery import MODULE_ID_PATTERN, NAMESPACED_REF_PATTERN, LegacySqlConnectorKind
from suite.platform.legacy_sql_metadata_worker_queue import LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN

LEGACY_SQL_CONNECTOR_RUNTIME_MERGE_BRANCH_PROTECTION_SNAPSHOT_SCHEMA_VERSION = (
    "legacy_sql_connector_runtime_merge_branch_protection_snapshot.v1"
)
LEGACY_SQL_CONNECTOR_RUNTIME_MERGE_SECURITY_SCAN_SNAPSHOT_SCHEMA_VERSION = (
    "legacy_sql_connector_runtime_merge_security_scan_snapshot.v1"
)
LEGACY_SQL_CONNECTOR_RUNTIME_MERGE_CONTAINER_PROVENANCE_SNAPSHOT_SCHEMA_VERSION = (
    "legacy_sql_connector_runtime_merge_container_provenance_snapshot.v1"
)
LEGACY_SQL_CONNECTOR_RUNTIME_MERGE_SECRET_ROTATION_PLAN_SNAPSHOT_SCHEMA_VERSION = (
    "legacy_sql_connector_runtime_merge_secret_rotation_plan_snapshot.v1"
)
LEGACY_SQL_CONNECTOR_RUNTIME_MERGE_KILL_SWITCH_DRILL_SNAPSHOT_SCHEMA_VERSION = (
    "legacy_sql_connector_runtime_merge_kill_switch_drill_snapshot.v1"
)
LEGACY_SQL_CONNECTOR_RUNTIME_MERGE_GATE_SCHEMA_VERSION = "legacy_sql_connector_runtime_merge_gate.v1"
LEGACY_SQL_CONNECTOR_RUNTIME_MERGE_GATE_SMOKE_SCHEMA_VERSION = "legacy_sql_connector_runtime_merge_gate_smoke_report.v1"
LEGACY_SQL_CONNECTOR_RUNTIME_MERGE_GATE_COMMAND_REF = "docker-compose:legacy-sql-connector-runtime-merge-gate-smoke"
ZERO_HASH = "sha256:" + "0" * 64
SHA256_REF_PATTERN = r"^sha256:[a-f0-9]{64}$"
_ALLOWED_SNAPSHOT_SCHEMAS = {
    LEGACY_SQL_CONNECTOR_RUNTIME_MERGE_BRANCH_PROTECTION_SNAPSHOT_SCHEMA_VERSION,
    LEGACY_SQL_CONNECTOR_RUNTIME_MERGE_SECURITY_SCAN_SNAPSHOT_SCHEMA_VERSION,
    LEGACY_SQL_CONNECTOR_RUNTIME_MERGE_CONTAINER_PROVENANCE_SNAPSHOT_SCHEMA_VERSION,
    LEGACY_SQL_CONNECTOR_RUNTIME_MERGE_SECRET_ROTATION_PLAN_SNAPSHOT_SCHEMA_VERSION,
    LEGACY_SQL_CONNECTOR_RUNTIME_MERGE_KILL_SWITCH_DRILL_SNAPSHOT_SCHEMA_VERSION,
}
FORBIDDEN_RUNTIME_MERGE_FRAGMENTS = (
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


class LegacySqlConnectorRuntimeMergeGateStatus(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"


class LegacySqlConnectorRuntimeMergeEvidenceSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    snapshot_ref: str
    runtime_pr_gate_evidence_hash: str
    upstream_evidence_hashes: tuple[str, ...] = ()
    required_controls: tuple[str, ...]
    passed_controls: tuple[str, ...]
    failed_controls: tuple[str, ...] = ()
    merge_allowed: bool = False
    runtime_code_merge_allowed: bool = False
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

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, value: str) -> str:
        if value not in _ALLOWED_SNAPSHOT_SCHEMAS:
            raise ValueError("legacy SQL runtime merge snapshot schema is not allowed")
        return value

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL runtime merge snapshot text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL runtime merge snapshot module_id must be lowercase snake_case")
        return value

    @field_validator("source_system_ref", "snapshot_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL runtime merge snapshot references must be namespaced")
        return value

    @field_validator("runtime_pr_gate_evidence_hash", "evidence_hash")
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL runtime merge snapshot hashes must be sha256 references")
        return value

    @field_validator("upstream_evidence_hashes")
    @classmethod
    def validate_upstream_hashes(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for item in value:
            if not re.fullmatch(SHA256_REF_PATTERN, item):
                raise ValueError("legacy SQL runtime merge snapshot upstream hashes must be sha256 references")
        return value

    @field_validator("required_controls", "passed_controls", "failed_controls")
    @classmethod
    def validate_controls(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("legacy SQL runtime merge snapshot controls must be unique")
        for item in value:
            if not item.strip():
                raise ValueError("legacy SQL runtime merge snapshot controls must not be empty")
        return value

    @model_validator(mode="after")
    def require_safe_snapshot(self) -> Self:
        if (
            self.merge_allowed
            or self.runtime_code_merge_allowed
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
            raise ValueError("legacy SQL runtime merge snapshot must remain non-executing")
        missing_controls = set(self.required_controls) - set(self.passed_controls) - set(self.failed_controls)
        if missing_controls:
            raise ValueError("legacy SQL runtime merge snapshot must classify every required control")
        _assert_runtime_merge_safe(self)
        return self


class LegacySqlConnectorRuntimeMergeGateCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    runtime_pr_gate_evidence_hash: str
    branch_protection_snapshot_hash: str
    security_scan_snapshot_hash: str
    container_provenance_snapshot_hash: str
    secret_rotation_plan_snapshot_hash: str
    kill_switch_drill_snapshot_hash: str
    requested_by: str
    runtime_merge_gate_requested: bool = True
    merge_requested: bool = False
    runtime_code_merge_requested: bool = False
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
            raise ValueError("legacy SQL runtime merge gate command text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL runtime merge gate command module_id must be lowercase snake_case")
        return value

    @field_validator("source_system_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL runtime merge gate command references must be namespaced")
        return value

    @field_validator(
        "runtime_pr_gate_evidence_hash",
        "branch_protection_snapshot_hash",
        "security_scan_snapshot_hash",
        "container_provenance_snapshot_hash",
        "secret_rotation_plan_snapshot_hash",
        "kill_switch_drill_snapshot_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL runtime merge gate command hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_safe_command(self) -> Self:
        _assert_runtime_merge_safe(self)
        return self


class LegacySqlConnectorRuntimeMergeGateEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_RUNTIME_MERGE_GATE_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    continuity_domain: str = LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN
    command_ref: str = LEGACY_SQL_CONNECTOR_RUNTIME_MERGE_GATE_COMMAND_REF
    runtime_pr_gate_evidence_hash: str
    branch_protection_snapshot_hash: str
    security_scan_snapshot_hash: str
    container_provenance_snapshot_hash: str
    secret_rotation_plan_snapshot_hash: str
    kill_switch_drill_snapshot_hash: str
    runtime_pr_gate_hash_valid: bool
    runtime_pr_gate_ready: bool
    runtime_pr_gate_bound: bool
    branch_protection_snapshot_hash_valid: bool
    branch_protection_snapshot_bound: bool
    branch_protection_passed: bool
    security_scan_snapshot_hash_valid: bool
    security_scan_snapshot_bound: bool
    security_scan_passed: bool
    container_provenance_snapshot_hash_valid: bool
    container_provenance_snapshot_bound: bool
    container_provenance_passed: bool
    secret_rotation_plan_snapshot_hash_valid: bool
    secret_rotation_plan_snapshot_bound: bool
    secret_rotation_plan_passed: bool
    kill_switch_drill_snapshot_hash_valid: bool
    kill_switch_drill_snapshot_bound: bool
    kill_switch_drill_passed: bool
    runtime_merge_gate_requested: bool
    runtime_merge_gate_ready: bool
    future_runtime_activation_gate_required: bool = True
    future_live_connection_gate_required: bool = True
    future_import_dry_run_gate_required: bool = True
    merge_requested: bool = False
    merge_allowed: bool = False
    runtime_code_merge_requested: bool = False
    runtime_code_merge_allowed: bool = False
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
    gate_status: LegacySqlConnectorRuntimeMergeGateStatus
    blocking_reasons: tuple[str, ...]
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL runtime merge gate text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL runtime merge gate module_id must be lowercase snake_case")
        return value

    @field_validator("source_system_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL runtime merge gate references must be namespaced")
        return value

    @field_validator(
        "runtime_pr_gate_evidence_hash",
        "branch_protection_snapshot_hash",
        "security_scan_snapshot_hash",
        "container_provenance_snapshot_hash",
        "secret_rotation_plan_snapshot_hash",
        "kill_switch_drill_snapshot_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL runtime merge gate hashes must be sha256 references")
        return value

    @field_validator("blocking_reasons")
    @classmethod
    def validate_blocking_reasons(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("legacy SQL runtime merge gate blocking reasons must be unique")
        for reason in value:
            if not reason.strip():
                raise ValueError("legacy SQL runtime merge gate blocking reasons must not be empty")
        return value

    @model_validator(mode="after")
    def require_safe_gate(self) -> Self:
        if (
            self.merge_allowed
            or self.runtime_code_merge_allowed
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
            raise ValueError("legacy SQL runtime merge gate must remain non-executing")
        if (
            not self.future_runtime_activation_gate_required
            or not self.future_live_connection_gate_required
            or not self.future_import_dry_run_gate_required
        ):
            raise ValueError("legacy SQL runtime merge gate must require future runtime gates")
        if self.gate_status == LegacySqlConnectorRuntimeMergeGateStatus.READY:
            required = (
                self.runtime_pr_gate_hash_valid,
                self.runtime_pr_gate_ready,
                self.runtime_pr_gate_bound,
                self.branch_protection_snapshot_hash_valid,
                self.branch_protection_snapshot_bound,
                self.branch_protection_passed,
                self.security_scan_snapshot_hash_valid,
                self.security_scan_snapshot_bound,
                self.security_scan_passed,
                self.container_provenance_snapshot_hash_valid,
                self.container_provenance_snapshot_bound,
                self.container_provenance_passed,
                self.secret_rotation_plan_snapshot_hash_valid,
                self.secret_rotation_plan_snapshot_bound,
                self.secret_rotation_plan_passed,
                self.kill_switch_drill_snapshot_hash_valid,
                self.kill_switch_drill_snapshot_bound,
                self.kill_switch_drill_passed,
                self.runtime_merge_gate_requested,
                self.runtime_merge_gate_ready,
            )
            if not all(required) or self.blocking_reasons:
                raise ValueError("ready legacy SQL runtime merge gate requires complete evidence")
        if self.gate_status == LegacySqlConnectorRuntimeMergeGateStatus.BLOCKED:
            if not self.blocking_reasons:
                raise ValueError("blocked legacy SQL runtime merge gate requires blocking reasons")
            if self.runtime_merge_gate_ready:
                raise ValueError("blocked legacy SQL runtime merge gate cannot be ready")
        _assert_runtime_merge_safe(self)
        return self


class LegacySqlConnectorRuntimeMergeGateSmokeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_RUNTIME_MERGE_GATE_SMOKE_SCHEMA_VERSION
    tenant_id: str
    store_backend: LegacySqlConnectorRealConnectionPolicyStoreBackend
    continuity_domain: str = LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN
    command_ref: str = LEGACY_SQL_CONNECTOR_RUNTIME_MERGE_GATE_COMMAND_REF
    runtime_pr_gate_evidence_hash: str
    runtime_merge_gate_evidence_hash: str
    runtime_merge_gate_ready: bool
    runtime_pr_gate_required: bool
    branch_protection_snapshot_required: bool
    security_scan_snapshot_required: bool
    container_provenance_snapshot_required: bool
    secret_rotation_plan_snapshot_required: bool
    kill_switch_drill_snapshot_required: bool
    runtime_pr_gate_missing_blocked: bool
    branch_protection_missing_blocked: bool
    security_scan_missing_blocked: bool
    container_provenance_missing_blocked: bool
    secret_rotation_plan_missing_blocked: bool
    kill_switch_drill_missing_blocked: bool
    activation_request_blocked: bool
    future_runtime_activation_gate_required: bool
    future_live_connection_gate_required: bool
    future_import_dry_run_gate_required: bool
    merge_allowed: bool = False
    runtime_code_merge_allowed: bool = False
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
            self.merge_allowed
            or self.runtime_code_merge_allowed
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
            raise ValueError("legacy SQL runtime merge smoke must remain non-executing")
        _assert_runtime_merge_safe(self)
        return self


def build_legacy_sql_connector_runtime_merge_branch_protection_snapshot(
    *,
    runtime_pr_gate: LegacySqlConnectorRuntimePrGateEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    passed: bool = True,
) -> LegacySqlConnectorRuntimeMergeEvidenceSnapshot:
    return _build_snapshot(
        schema_version=LEGACY_SQL_CONNECTOR_RUNTIME_MERGE_BRANCH_PROTECTION_SNAPSHOT_SCHEMA_VERSION,
        snapshot_ref="runtime-merge-branch-protection:legacy-sql-runtime-merge",
        runtime_pr_gate=runtime_pr_gate,
        required_controls=(
            "branch_protection_enabled",
            "required_status_checks_passed",
            "required_reviews_passed",
            "signed_commits_or_linear_history",
            "force_push_disabled",
            "admin_bypass_disabled",
        ),
        failed_controls=() if passed else ("branch_protection_enabled",),
        checked_by=checked_by,
        checked_at_utc=checked_at_utc,
    )


def build_legacy_sql_connector_runtime_merge_security_scan_snapshot(
    *,
    runtime_pr_gate: LegacySqlConnectorRuntimePrGateEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    passed: bool = True,
) -> LegacySqlConnectorRuntimeMergeEvidenceSnapshot:
    return _build_snapshot(
        schema_version=LEGACY_SQL_CONNECTOR_RUNTIME_MERGE_SECURITY_SCAN_SNAPSHOT_SCHEMA_VERSION,
        snapshot_ref="runtime-merge-security-scan:legacy-sql-runtime-merge",
        runtime_pr_gate=runtime_pr_gate,
        required_controls=(
            "sast_passed",
            "dependency_scan_passed",
            "secret_scan_passed",
            "container_scan_passed",
            "license_policy_passed",
            "no_high_or_critical_findings",
        ),
        failed_controls=() if passed else ("sast_passed",),
        checked_by=checked_by,
        checked_at_utc=checked_at_utc,
    )


def build_legacy_sql_connector_runtime_merge_container_provenance_snapshot(
    *,
    runtime_pr_gate: LegacySqlConnectorRuntimePrGateEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    passed: bool = True,
) -> LegacySqlConnectorRuntimeMergeEvidenceSnapshot:
    return _build_snapshot(
        schema_version=LEGACY_SQL_CONNECTOR_RUNTIME_MERGE_CONTAINER_PROVENANCE_SNAPSHOT_SCHEMA_VERSION,
        snapshot_ref="runtime-merge-container-provenance:legacy-sql-runtime-merge",
        runtime_pr_gate=runtime_pr_gate,
        required_controls=(
            "image_digest_recorded",
            "sbom_attached",
            "slsa_provenance_present",
            "base_image_digest_pinned",
            "non_root_runtime_confirmed",
            "read_only_runtime_confirmed",
        ),
        failed_controls=() if passed else ("slsa_provenance_present",),
        checked_by=checked_by,
        checked_at_utc=checked_at_utc,
    )


def build_legacy_sql_connector_runtime_merge_secret_rotation_plan_snapshot(
    *,
    runtime_pr_gate: LegacySqlConnectorRuntimePrGateEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    passed: bool = True,
) -> LegacySqlConnectorRuntimeMergeEvidenceSnapshot:
    return _build_snapshot(
        schema_version=LEGACY_SQL_CONNECTOR_RUNTIME_MERGE_SECRET_ROTATION_PLAN_SNAPSHOT_SCHEMA_VERSION,
        snapshot_ref="runtime-merge-secret-rotation-plan:legacy-sql-runtime-merge",
        runtime_pr_gate=runtime_pr_gate,
        upstream_evidence_hashes=(runtime_pr_gate.secret_binding_snapshot_hash,),
        required_controls=(
            "rotation_plan_reviewed",
            "sealed_secret_binding_ready",
            "tenant_kms_binding_ready",
            "live_secret_not_rotated_by_gate",
            "rollback_secret_revocation_ready",
        ),
        failed_controls=() if passed else ("rotation_plan_reviewed",),
        checked_by=checked_by,
        checked_at_utc=checked_at_utc,
    )


def build_legacy_sql_connector_runtime_merge_kill_switch_drill_snapshot(
    *,
    runtime_pr_gate: LegacySqlConnectorRuntimePrGateEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    passed: bool = True,
) -> LegacySqlConnectorRuntimeMergeEvidenceSnapshot:
    return _build_snapshot(
        schema_version=LEGACY_SQL_CONNECTOR_RUNTIME_MERGE_KILL_SWITCH_DRILL_SNAPSHOT_SCHEMA_VERSION,
        snapshot_ref="runtime-merge-kill-switch-drill:legacy-sql-runtime-merge",
        runtime_pr_gate=runtime_pr_gate,
        upstream_evidence_hashes=(runtime_pr_gate.kill_switch_probe_snapshot_hash,),
        required_controls=(
            "kill_switch_drill_passed",
            "tenant_disable_checked_metadata_only",
            "global_disable_checked_metadata_only",
            "manual_abort_runbook_verified",
            "break_glass_forbidden",
        ),
        failed_controls=() if passed else ("kill_switch_drill_passed",),
        checked_by=checked_by,
        checked_at_utc=checked_at_utc,
    )


def build_legacy_sql_connector_runtime_merge_gate_command(
    *,
    runtime_pr_gate: LegacySqlConnectorRuntimePrGateEvidence,
    branch_protection_snapshot: LegacySqlConnectorRuntimeMergeEvidenceSnapshot,
    security_scan_snapshot: LegacySqlConnectorRuntimeMergeEvidenceSnapshot,
    container_provenance_snapshot: LegacySqlConnectorRuntimeMergeEvidenceSnapshot,
    secret_rotation_plan_snapshot: LegacySqlConnectorRuntimeMergeEvidenceSnapshot,
    kill_switch_drill_snapshot: LegacySqlConnectorRuntimeMergeEvidenceSnapshot,
    requested_by: str,
    runtime_merge_gate_requested: bool = True,
    merge_requested: bool = False,
    runtime_code_merge_requested: bool = False,
    activatable_runtime_requested: bool = False,
    socket_runtime_execution_requested: bool = False,
    secret_materialization_requested: bool = False,
    live_secret_rotation_requested: bool = False,
    raw_data_access_requested: bool = False,
    import_dry_run_requested: bool = False,
    import_write_requested: bool = False,
    destructive_actions_requested: bool = False,
) -> LegacySqlConnectorRuntimeMergeGateCommand:
    return LegacySqlConnectorRuntimeMergeGateCommand(
        tenant_id=runtime_pr_gate.tenant_id,
        module_id=runtime_pr_gate.module_id,
        source_system_ref=runtime_pr_gate.source_system_ref,
        connector_kind=runtime_pr_gate.connector_kind,
        runtime_pr_gate_evidence_hash=runtime_pr_gate.evidence_hash,
        branch_protection_snapshot_hash=branch_protection_snapshot.evidence_hash,
        security_scan_snapshot_hash=security_scan_snapshot.evidence_hash,
        container_provenance_snapshot_hash=container_provenance_snapshot.evidence_hash,
        secret_rotation_plan_snapshot_hash=secret_rotation_plan_snapshot.evidence_hash,
        kill_switch_drill_snapshot_hash=kill_switch_drill_snapshot.evidence_hash,
        requested_by=requested_by,
        runtime_merge_gate_requested=runtime_merge_gate_requested,
        merge_requested=merge_requested,
        runtime_code_merge_requested=runtime_code_merge_requested,
        activatable_runtime_requested=activatable_runtime_requested,
        socket_runtime_execution_requested=socket_runtime_execution_requested,
        secret_materialization_requested=secret_materialization_requested,
        live_secret_rotation_requested=live_secret_rotation_requested,
        raw_data_access_requested=raw_data_access_requested,
        import_dry_run_requested=import_dry_run_requested,
        import_write_requested=import_write_requested,
        destructive_actions_requested=destructive_actions_requested,
    )


def build_legacy_sql_connector_runtime_merge_gate(
    *,
    command: LegacySqlConnectorRuntimeMergeGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    runtime_pr_gate: LegacySqlConnectorRuntimePrGateEvidence,
    branch_protection_snapshot: LegacySqlConnectorRuntimeMergeEvidenceSnapshot,
    security_scan_snapshot: LegacySqlConnectorRuntimeMergeEvidenceSnapshot,
    container_provenance_snapshot: LegacySqlConnectorRuntimeMergeEvidenceSnapshot,
    secret_rotation_plan_snapshot: LegacySqlConnectorRuntimeMergeEvidenceSnapshot,
    kill_switch_drill_snapshot: LegacySqlConnectorRuntimeMergeEvidenceSnapshot,
    checked_by: str,
    checked_at_utc: datetime | None = None,
) -> LegacySqlConnectorRuntimeMergeGateEvidence:
    checked_at = checked_at_utc or datetime.now(UTC)
    runtime_pr_gate_hash_valid = (
        build_legacy_sql_connector_runtime_pr_gate_hash(runtime_pr_gate)
        == runtime_pr_gate.evidence_hash
        == command.runtime_pr_gate_evidence_hash
    )
    runtime_pr_gate_ready = (
        runtime_pr_gate.gate_status == LegacySqlConnectorRuntimePrGateStatus.READY
        and runtime_pr_gate.runtime_pr_gate_ready
        and runtime_pr_gate.future_runtime_merge_gate_required
    )
    runtime_pr_gate_bound = _runtime_pr_gate_bound(command=command, bundle=bundle, runtime_pr_gate=runtime_pr_gate)
    branch_hash_valid = _snapshot_hash_valid(branch_protection_snapshot, command.branch_protection_snapshot_hash)
    security_hash_valid = _snapshot_hash_valid(security_scan_snapshot, command.security_scan_snapshot_hash)
    provenance_hash_valid = _snapshot_hash_valid(
        container_provenance_snapshot, command.container_provenance_snapshot_hash
    )
    rotation_hash_valid = _snapshot_hash_valid(
        secret_rotation_plan_snapshot, command.secret_rotation_plan_snapshot_hash
    )
    kill_switch_hash_valid = _snapshot_hash_valid(kill_switch_drill_snapshot, command.kill_switch_drill_snapshot_hash)
    branch_bound = _snapshot_bound(
        command=command,
        runtime_pr_gate=runtime_pr_gate,
        snapshot=branch_protection_snapshot,
        expected_schema=LEGACY_SQL_CONNECTOR_RUNTIME_MERGE_BRANCH_PROTECTION_SNAPSHOT_SCHEMA_VERSION,
    )
    security_bound = _snapshot_bound(
        command=command,
        runtime_pr_gate=runtime_pr_gate,
        snapshot=security_scan_snapshot,
        expected_schema=LEGACY_SQL_CONNECTOR_RUNTIME_MERGE_SECURITY_SCAN_SNAPSHOT_SCHEMA_VERSION,
    )
    provenance_bound = _snapshot_bound(
        command=command,
        runtime_pr_gate=runtime_pr_gate,
        snapshot=container_provenance_snapshot,
        expected_schema=LEGACY_SQL_CONNECTOR_RUNTIME_MERGE_CONTAINER_PROVENANCE_SNAPSHOT_SCHEMA_VERSION,
    )
    rotation_bound = _snapshot_bound(
        command=command,
        runtime_pr_gate=runtime_pr_gate,
        snapshot=secret_rotation_plan_snapshot,
        expected_schema=LEGACY_SQL_CONNECTOR_RUNTIME_MERGE_SECRET_ROTATION_PLAN_SNAPSHOT_SCHEMA_VERSION,
        required_upstream_hash=runtime_pr_gate.secret_binding_snapshot_hash,
    )
    kill_switch_bound = _snapshot_bound(
        command=command,
        runtime_pr_gate=runtime_pr_gate,
        snapshot=kill_switch_drill_snapshot,
        expected_schema=LEGACY_SQL_CONNECTOR_RUNTIME_MERGE_KILL_SWITCH_DRILL_SNAPSHOT_SCHEMA_VERSION,
        required_upstream_hash=runtime_pr_gate.kill_switch_probe_snapshot_hash,
    )
    branch_passed = _snapshot_passed(branch_protection_snapshot)
    security_passed = _snapshot_passed(security_scan_snapshot)
    provenance_passed = _snapshot_passed(container_provenance_snapshot)
    rotation_passed = _snapshot_passed(secret_rotation_plan_snapshot)
    kill_switch_passed = _snapshot_passed(kill_switch_drill_snapshot)
    blocking_reasons = _runtime_merge_blocking_reasons(
        command=command,
        runtime_pr_gate_hash_valid=runtime_pr_gate_hash_valid,
        runtime_pr_gate_ready=runtime_pr_gate_ready,
        runtime_pr_gate_bound=runtime_pr_gate_bound,
        snapshot_checks=(
            ("branch_protection", branch_hash_valid, branch_bound, branch_passed, branch_protection_snapshot),
            ("security_scan", security_hash_valid, security_bound, security_passed, security_scan_snapshot),
            (
                "container_provenance",
                provenance_hash_valid,
                provenance_bound,
                provenance_passed,
                container_provenance_snapshot,
            ),
            (
                "secret_rotation_plan",
                rotation_hash_valid,
                rotation_bound,
                rotation_passed,
                secret_rotation_plan_snapshot,
            ),
            (
                "kill_switch_drill",
                kill_switch_hash_valid,
                kill_switch_bound,
                kill_switch_passed,
                kill_switch_drill_snapshot,
            ),
        ),
    )
    ready = not blocking_reasons
    draft = LegacySqlConnectorRuntimeMergeGateEvidence(
        tenant_id=runtime_pr_gate.tenant_id,
        module_id=runtime_pr_gate.module_id,
        source_system_ref=runtime_pr_gate.source_system_ref,
        connector_kind=runtime_pr_gate.connector_kind,
        runtime_pr_gate_evidence_hash=runtime_pr_gate.evidence_hash,
        branch_protection_snapshot_hash=branch_protection_snapshot.evidence_hash,
        security_scan_snapshot_hash=security_scan_snapshot.evidence_hash,
        container_provenance_snapshot_hash=container_provenance_snapshot.evidence_hash,
        secret_rotation_plan_snapshot_hash=secret_rotation_plan_snapshot.evidence_hash,
        kill_switch_drill_snapshot_hash=kill_switch_drill_snapshot.evidence_hash,
        runtime_pr_gate_hash_valid=runtime_pr_gate_hash_valid,
        runtime_pr_gate_ready=runtime_pr_gate_ready,
        runtime_pr_gate_bound=runtime_pr_gate_bound,
        branch_protection_snapshot_hash_valid=branch_hash_valid,
        branch_protection_snapshot_bound=branch_bound,
        branch_protection_passed=branch_passed,
        security_scan_snapshot_hash_valid=security_hash_valid,
        security_scan_snapshot_bound=security_bound,
        security_scan_passed=security_passed,
        container_provenance_snapshot_hash_valid=provenance_hash_valid,
        container_provenance_snapshot_bound=provenance_bound,
        container_provenance_passed=provenance_passed,
        secret_rotation_plan_snapshot_hash_valid=rotation_hash_valid,
        secret_rotation_plan_snapshot_bound=rotation_bound,
        secret_rotation_plan_passed=rotation_passed,
        kill_switch_drill_snapshot_hash_valid=kill_switch_hash_valid,
        kill_switch_drill_snapshot_bound=kill_switch_bound,
        kill_switch_drill_passed=kill_switch_passed,
        runtime_merge_gate_requested=command.runtime_merge_gate_requested,
        runtime_merge_gate_ready=ready,
        merge_requested=command.merge_requested,
        runtime_code_merge_requested=command.runtime_code_merge_requested,
        activatable_runtime_requested=command.activatable_runtime_requested,
        socket_runtime_execution_requested=command.socket_runtime_execution_requested,
        secret_materialization_requested=command.secret_materialization_requested,
        live_secret_rotation_requested=command.live_secret_rotation_requested,
        raw_data_access_requested=command.raw_data_access_requested,
        import_dry_run_requested=command.import_dry_run_requested,
        import_write_requested=command.import_write_requested,
        destructive_actions_requested=command.destructive_actions_requested,
        gate_status=LegacySqlConnectorRuntimeMergeGateStatus.READY
        if ready
        else LegacySqlConnectorRuntimeMergeGateStatus.BLOCKED,
        blocking_reasons=blocking_reasons,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_connector_runtime_merge_gate_hash(draft)})


def build_legacy_sql_connector_runtime_merge_snapshot_hash(
    snapshot: LegacySqlConnectorRuntimeMergeEvidenceSnapshot,
) -> str:
    return stable_hash(canonical_json(snapshot.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_runtime_merge_gate_hash(gate: LegacySqlConnectorRuntimeMergeGateEvidence) -> str:
    return stable_hash(canonical_json(gate.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_runtime_merge_gate_smoke_report_hash(
    report: LegacySqlConnectorRuntimeMergeGateSmokeReport,
) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def run_legacy_sql_connector_runtime_merge_gate_smoke_from_env(
    environ: Mapping[str, str] | None = None,
) -> LegacySqlConnectorRuntimeMergeGateSmokeReport:
    env = os.environ if environ is None else environ
    checked_by = env.get(
        "SUITE_LEGACY_SQL_CONNECTOR_RUNTIME_MERGE_GATE_CHECKED_BY",
        "legacy-sql-connector-runtime-merge-gate-smoke",
    )
    checked_at = datetime.now(UTC)
    store_backend = LegacySqlConnectorRealConnectionPolicyStoreBackend(
        env.get(
            "SUITE_LEGACY_SQL_CONNECTOR_REAL_CONNECTION_EXECUTOR_POLICY_STORE_BACKEND",
            LegacySqlConnectorRealConnectionPolicyStoreBackend.JSONL.value,
        )
    )
    bundle, runtime_pr_gate = _build_ready_runtime_pr_gate(env=env, checked_by=checked_by, checked_at=checked_at)
    snapshots = _build_ready_runtime_merge_snapshots(
        runtime_pr_gate=runtime_pr_gate,
        checked_by=checked_by,
        checked_at=checked_at,
    )
    command = _build_runtime_merge_command_from_snapshots(
        runtime_pr_gate=runtime_pr_gate,
        snapshots=snapshots,
        requested_by=checked_by,
    )
    gate = _build_runtime_merge_gate_from_snapshots(
        command=command,
        bundle=bundle,
        runtime_pr_gate=runtime_pr_gate,
        snapshots=snapshots,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=67),
    )
    runtime_pr_gate_missing_blocked = _runtime_pr_gate_missing_blocked(
        command, bundle, runtime_pr_gate, snapshots, checked_by, checked_at + timedelta(seconds=68)
    )
    branch_missing_blocked = _snapshot_missing_blocked(
        command,
        bundle,
        runtime_pr_gate,
        snapshots,
        "branch_protection_snapshot",
        "branch_protection_enabled",
        "branch_protection_snapshot_failed",
        checked_by,
        checked_at + timedelta(seconds=69),
    )
    security_missing_blocked = _snapshot_missing_blocked(
        command,
        bundle,
        runtime_pr_gate,
        snapshots,
        "security_scan_snapshot",
        "sast_passed",
        "security_scan_snapshot_failed",
        checked_by,
        checked_at + timedelta(seconds=70),
    )
    provenance_missing_blocked = _snapshot_missing_blocked(
        command,
        bundle,
        runtime_pr_gate,
        snapshots,
        "container_provenance_snapshot",
        "slsa_provenance_present",
        "container_provenance_snapshot_failed",
        checked_by,
        checked_at + timedelta(seconds=71),
    )
    rotation_missing_blocked = _snapshot_missing_blocked(
        command,
        bundle,
        runtime_pr_gate,
        snapshots,
        "secret_rotation_plan_snapshot",
        "rotation_plan_reviewed",
        "secret_rotation_plan_snapshot_failed",
        checked_by,
        checked_at + timedelta(seconds=72),
    )
    kill_switch_missing_blocked = _snapshot_missing_blocked(
        command,
        bundle,
        runtime_pr_gate,
        snapshots,
        "kill_switch_drill_snapshot",
        "kill_switch_drill_passed",
        "kill_switch_drill_snapshot_failed",
        checked_by,
        checked_at + timedelta(seconds=73),
    )
    activation_request_blocked = _activation_request_blocked(
        command,
        bundle,
        runtime_pr_gate,
        snapshots,
        checked_by,
        checked_at + timedelta(seconds=74),
    )
    runtime_merge_gate_ready = (
        gate.gate_status == LegacySqlConnectorRuntimeMergeGateStatus.READY
        and gate.runtime_merge_gate_ready
        and runtime_pr_gate_missing_blocked
        and branch_missing_blocked
        and security_missing_blocked
        and provenance_missing_blocked
        and rotation_missing_blocked
        and kill_switch_missing_blocked
        and activation_request_blocked
        and not gate.merge_allowed
        and not gate.activatable_runtime_allowed
        and not gate.real_connection_opened
    )
    draft = LegacySqlConnectorRuntimeMergeGateSmokeReport(
        tenant_id=bundle.tenant_id,
        store_backend=store_backend,
        runtime_pr_gate_evidence_hash=runtime_pr_gate.evidence_hash,
        runtime_merge_gate_evidence_hash=gate.evidence_hash,
        runtime_merge_gate_ready=runtime_merge_gate_ready,
        runtime_pr_gate_required=gate.runtime_pr_gate_bound and gate.runtime_pr_gate_ready,
        branch_protection_snapshot_required=gate.branch_protection_snapshot_bound and gate.branch_protection_passed,
        security_scan_snapshot_required=gate.security_scan_snapshot_bound and gate.security_scan_passed,
        container_provenance_snapshot_required=(
            gate.container_provenance_snapshot_bound and gate.container_provenance_passed
        ),
        secret_rotation_plan_snapshot_required=(
            gate.secret_rotation_plan_snapshot_bound and gate.secret_rotation_plan_passed
        ),
        kill_switch_drill_snapshot_required=gate.kill_switch_drill_snapshot_bound and gate.kill_switch_drill_passed,
        runtime_pr_gate_missing_blocked=runtime_pr_gate_missing_blocked,
        branch_protection_missing_blocked=branch_missing_blocked,
        security_scan_missing_blocked=security_missing_blocked,
        container_provenance_missing_blocked=provenance_missing_blocked,
        secret_rotation_plan_missing_blocked=rotation_missing_blocked,
        kill_switch_drill_missing_blocked=kill_switch_missing_blocked,
        activation_request_blocked=activation_request_blocked,
        future_runtime_activation_gate_required=gate.future_runtime_activation_gate_required,
        future_live_connection_gate_required=gate.future_live_connection_gate_required,
        future_import_dry_run_gate_required=gate.future_import_dry_run_gate_required,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    _assert_runtime_merge_safe(draft)
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_runtime_merge_gate_smoke_report_hash(draft)}
    )


def exit_code_for_report(report: LegacySqlConnectorRuntimeMergeGateSmokeReport) -> int:
    return 0 if report.runtime_merge_gate_ready else 1


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Legacy SQL runtime merge gate smoke.")
    parser.add_argument("--once", action="store_true", help="Run one non-executing runtime merge gate smoke and exit.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the runtime merge gate report.")
    args = parser.parse_args(argv)
    del args.once

    report = run_legacy_sql_connector_runtime_merge_gate_smoke_from_env()
    print(json.dumps(report.model_dump(mode="json"), indent=2 if args.pretty else None, sort_keys=True))
    raise SystemExit(exit_code_for_report(report))


def _build_snapshot(
    *,
    schema_version: str,
    snapshot_ref: str,
    runtime_pr_gate: LegacySqlConnectorRuntimePrGateEvidence,
    required_controls: tuple[str, ...],
    failed_controls: tuple[str, ...],
    checked_by: str,
    checked_at_utc: datetime | None,
    upstream_evidence_hashes: tuple[str, ...] = (),
) -> LegacySqlConnectorRuntimeMergeEvidenceSnapshot:
    checked_at = checked_at_utc or datetime.now(UTC)
    passed_controls = tuple(control for control in required_controls if control not in failed_controls)
    draft = LegacySqlConnectorRuntimeMergeEvidenceSnapshot(
        schema_version=schema_version,
        tenant_id=runtime_pr_gate.tenant_id,
        module_id=runtime_pr_gate.module_id,
        source_system_ref=runtime_pr_gate.source_system_ref,
        connector_kind=runtime_pr_gate.connector_kind,
        snapshot_ref=snapshot_ref,
        runtime_pr_gate_evidence_hash=runtime_pr_gate.evidence_hash,
        upstream_evidence_hashes=upstream_evidence_hashes,
        required_controls=required_controls,
        passed_controls=passed_controls,
        failed_controls=failed_controls,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_connector_runtime_merge_snapshot_hash(draft)})


def _build_ready_runtime_pr_gate(
    *,
    env: Mapping[str, str],
    checked_by: str,
    checked_at: datetime,
) -> tuple[LegacySqlConnectorRealConnectionExecutorPolicyBundle, LegacySqlConnectorRuntimePrGateEvidence]:
    bundle, adr_gate = _build_ready_adr_gate(env=env, checked_by=checked_by, checked_at=checked_at)
    pr_snapshots = _build_ready_runtime_pr_snapshots(
        adr_gate=adr_gate,
        checked_by=checked_by,
        checked_at=checked_at,
    )
    pr_command = _build_runtime_pr_command_from_snapshots(
        adr_gate=adr_gate,
        snapshots=pr_snapshots,
        requested_by=checked_by,
    )
    runtime_pr_gate = _build_runtime_pr_gate_from_snapshots(
        command=pr_command,
        bundle=bundle,
        adr_gate=adr_gate,
        snapshots=pr_snapshots,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=50),
    )
    return bundle, runtime_pr_gate


def _build_ready_runtime_merge_snapshots(
    *,
    runtime_pr_gate: LegacySqlConnectorRuntimePrGateEvidence,
    checked_by: str,
    checked_at: datetime,
) -> dict[str, LegacySqlConnectorRuntimeMergeEvidenceSnapshot]:
    return {
        "branch_protection_snapshot": build_legacy_sql_connector_runtime_merge_branch_protection_snapshot(
            runtime_pr_gate=runtime_pr_gate,
            checked_by=checked_by,
            checked_at_utc=checked_at + timedelta(seconds=61),
        ),
        "security_scan_snapshot": build_legacy_sql_connector_runtime_merge_security_scan_snapshot(
            runtime_pr_gate=runtime_pr_gate,
            checked_by=checked_by,
            checked_at_utc=checked_at + timedelta(seconds=62),
        ),
        "container_provenance_snapshot": build_legacy_sql_connector_runtime_merge_container_provenance_snapshot(
            runtime_pr_gate=runtime_pr_gate,
            checked_by=checked_by,
            checked_at_utc=checked_at + timedelta(seconds=63),
        ),
        "secret_rotation_plan_snapshot": build_legacy_sql_connector_runtime_merge_secret_rotation_plan_snapshot(
            runtime_pr_gate=runtime_pr_gate,
            checked_by=checked_by,
            checked_at_utc=checked_at + timedelta(seconds=64),
        ),
        "kill_switch_drill_snapshot": build_legacy_sql_connector_runtime_merge_kill_switch_drill_snapshot(
            runtime_pr_gate=runtime_pr_gate,
            checked_by=checked_by,
            checked_at_utc=checked_at + timedelta(seconds=65),
        ),
    }


def _snapshot_hash_valid(snapshot: LegacySqlConnectorRuntimeMergeEvidenceSnapshot, expected_hash: str) -> bool:
    return build_legacy_sql_connector_runtime_merge_snapshot_hash(snapshot) == snapshot.evidence_hash == expected_hash


def _snapshot_passed(snapshot: LegacySqlConnectorRuntimeMergeEvidenceSnapshot) -> bool:
    return not snapshot.failed_controls and set(snapshot.required_controls) == set(snapshot.passed_controls)


def _snapshot_bound(
    *,
    command: LegacySqlConnectorRuntimeMergeGateCommand,
    runtime_pr_gate: LegacySqlConnectorRuntimePrGateEvidence,
    snapshot: LegacySqlConnectorRuntimeMergeEvidenceSnapshot,
    expected_schema: str,
    required_upstream_hash: str | None = None,
) -> bool:
    upstream_bound = required_upstream_hash is None or required_upstream_hash in snapshot.upstream_evidence_hashes
    return (
        command.tenant_id == runtime_pr_gate.tenant_id == snapshot.tenant_id
        and command.module_id == runtime_pr_gate.module_id == snapshot.module_id
        and command.source_system_ref == runtime_pr_gate.source_system_ref == snapshot.source_system_ref
        and command.connector_kind == runtime_pr_gate.connector_kind == snapshot.connector_kind
        and snapshot.schema_version == expected_schema
        and snapshot.runtime_pr_gate_evidence_hash == runtime_pr_gate.evidence_hash
        and upstream_bound
    )


def _runtime_pr_gate_bound(
    *,
    command: LegacySqlConnectorRuntimeMergeGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    runtime_pr_gate: LegacySqlConnectorRuntimePrGateEvidence,
) -> bool:
    return (
        command.tenant_id == bundle.tenant_id == runtime_pr_gate.tenant_id
        and command.module_id == bundle.module_id == runtime_pr_gate.module_id
        and command.source_system_ref == bundle.source_system_ref == runtime_pr_gate.source_system_ref
        and command.connector_kind == bundle.connector_kind == runtime_pr_gate.connector_kind
        and command.runtime_pr_gate_evidence_hash == runtime_pr_gate.evidence_hash
        and not runtime_pr_gate.merge_allowed
        and not runtime_pr_gate.runtime_code_merge_allowed
        and not runtime_pr_gate.socket_runtime_execution_allowed
        and not runtime_pr_gate.secret_materialization_allowed
        and not runtime_pr_gate.network_socket_opened
        and not runtime_pr_gate.secret_material_resolved
    )


def _runtime_merge_blocking_reasons(
    *,
    command: LegacySqlConnectorRuntimeMergeGateCommand,
    runtime_pr_gate_hash_valid: bool,
    runtime_pr_gate_ready: bool,
    runtime_pr_gate_bound: bool,
    snapshot_checks: tuple[tuple[str, bool, bool, bool, LegacySqlConnectorRuntimeMergeEvidenceSnapshot], ...],
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not runtime_pr_gate_hash_valid:
        reasons.append("runtime_pr_gate_hash_invalid")
    if not runtime_pr_gate_ready:
        reasons.append("runtime_pr_gate_not_ready")
    if not runtime_pr_gate_bound:
        reasons.append("runtime_pr_gate_not_bound")
    for prefix, hash_valid, bound, passed, snapshot in snapshot_checks:
        if not hash_valid:
            reasons.append(f"{prefix}_snapshot_hash_invalid")
        if not bound:
            reasons.append(f"{prefix}_snapshot_not_bound")
        if not passed:
            reasons.append(f"{prefix}_snapshot_failed")
        for failed_control in snapshot.failed_controls:
            reasons.append(f"{prefix}_{failed_control}_failed")
    if not command.runtime_merge_gate_requested:
        reasons.append("runtime_merge_gate_not_requested")
    if command.merge_requested:
        reasons.append("merge_requires_future_activation_gate")
    if command.runtime_code_merge_requested:
        reasons.append("runtime_code_merge_requires_future_activation_gate")
    if command.activatable_runtime_requested:
        reasons.append("activatable_runtime_requires_future_activation_gate")
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


def _build_runtime_merge_command_from_snapshots(
    *,
    runtime_pr_gate: LegacySqlConnectorRuntimePrGateEvidence,
    snapshots: dict[str, LegacySqlConnectorRuntimeMergeEvidenceSnapshot],
    requested_by: str,
) -> LegacySqlConnectorRuntimeMergeGateCommand:
    return build_legacy_sql_connector_runtime_merge_gate_command(
        runtime_pr_gate=runtime_pr_gate,
        branch_protection_snapshot=snapshots["branch_protection_snapshot"],
        security_scan_snapshot=snapshots["security_scan_snapshot"],
        container_provenance_snapshot=snapshots["container_provenance_snapshot"],
        secret_rotation_plan_snapshot=snapshots["secret_rotation_plan_snapshot"],
        kill_switch_drill_snapshot=snapshots["kill_switch_drill_snapshot"],
        requested_by=requested_by,
    )


def _build_runtime_merge_gate_from_snapshots(
    *,
    command: LegacySqlConnectorRuntimeMergeGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    runtime_pr_gate: LegacySqlConnectorRuntimePrGateEvidence,
    snapshots: dict[str, LegacySqlConnectorRuntimeMergeEvidenceSnapshot],
    checked_by: str,
    checked_at_utc: datetime,
) -> LegacySqlConnectorRuntimeMergeGateEvidence:
    return build_legacy_sql_connector_runtime_merge_gate(
        command=command,
        bundle=bundle,
        runtime_pr_gate=runtime_pr_gate,
        branch_protection_snapshot=snapshots["branch_protection_snapshot"],
        security_scan_snapshot=snapshots["security_scan_snapshot"],
        container_provenance_snapshot=snapshots["container_provenance_snapshot"],
        secret_rotation_plan_snapshot=snapshots["secret_rotation_plan_snapshot"],
        kill_switch_drill_snapshot=snapshots["kill_switch_drill_snapshot"],
        checked_by=checked_by,
        checked_at_utc=checked_at_utc,
    )


def _runtime_pr_gate_missing_blocked(
    command: LegacySqlConnectorRuntimeMergeGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    runtime_pr_gate: LegacySqlConnectorRuntimePrGateEvidence,
    snapshots: dict[str, LegacySqlConnectorRuntimeMergeEvidenceSnapshot],
    checked_by: str,
    checked_at: datetime,
) -> bool:
    blocked_pr = runtime_pr_gate.model_copy(
        update={
            "gate_status": LegacySqlConnectorRuntimePrGateStatus.BLOCKED,
            "runtime_pr_gate_ready": False,
            "blocking_reasons": ("runtime_merge_test_pr_gate_missing",),
            "checked_at_utc": checked_at,
            "evidence_hash": ZERO_HASH,
        }
    )
    blocked_pr = blocked_pr.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_runtime_pr_gate_hash(blocked_pr)}
    )
    blocked = _build_runtime_merge_gate_from_snapshots(
        command=command.model_copy(update={"runtime_pr_gate_evidence_hash": blocked_pr.evidence_hash}),
        bundle=bundle,
        runtime_pr_gate=blocked_pr,
        snapshots=snapshots,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        blocked.gate_status == LegacySqlConnectorRuntimeMergeGateStatus.BLOCKED
        and "runtime_pr_gate_not_ready" in blocked.blocking_reasons
    )


def _snapshot_missing_blocked(
    command: LegacySqlConnectorRuntimeMergeGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    runtime_pr_gate: LegacySqlConnectorRuntimePrGateEvidence,
    snapshots: dict[str, LegacySqlConnectorRuntimeMergeEvidenceSnapshot],
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
        update={"evidence_hash": build_legacy_sql_connector_runtime_merge_snapshot_hash(blocked_snapshot)}
    )
    updated_snapshots[snapshot_key] = blocked_snapshot
    command_field = f"{snapshot_key}_hash"
    blocked = _build_runtime_merge_gate_from_snapshots(
        command=command.model_copy(update={command_field: blocked_snapshot.evidence_hash}),
        bundle=bundle,
        runtime_pr_gate=runtime_pr_gate,
        snapshots=updated_snapshots,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        blocked.gate_status == LegacySqlConnectorRuntimeMergeGateStatus.BLOCKED
        and expected_reason in blocked.blocking_reasons
    )


def _activation_request_blocked(
    command: LegacySqlConnectorRuntimeMergeGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    runtime_pr_gate: LegacySqlConnectorRuntimePrGateEvidence,
    snapshots: dict[str, LegacySqlConnectorRuntimeMergeEvidenceSnapshot],
    checked_by: str,
    checked_at: datetime,
) -> bool:
    blocked = _build_runtime_merge_gate_from_snapshots(
        command=command.model_copy(
            update={
                "merge_requested": True,
                "runtime_code_merge_requested": True,
                "activatable_runtime_requested": True,
                "socket_runtime_execution_requested": True,
                "secret_materialization_requested": True,
                "live_secret_rotation_requested": True,
                "raw_data_access_requested": True,
            }
        ),
        bundle=bundle,
        runtime_pr_gate=runtime_pr_gate,
        snapshots=snapshots,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        blocked.gate_status == LegacySqlConnectorRuntimeMergeGateStatus.BLOCKED
        and "merge_requires_future_activation_gate" in blocked.blocking_reasons
        and "runtime_code_merge_requires_future_activation_gate" in blocked.blocking_reasons
        and "activatable_runtime_requires_future_activation_gate" in blocked.blocking_reasons
        and "socket_runtime_execution_requires_future_live_connection_gate" in blocked.blocking_reasons
        and "secret_materialization_requires_future_secret_gate" in blocked.blocking_reasons
        and "live_secret_rotation_requires_future_rotation_gate" in blocked.blocking_reasons
        and "raw_data_access_requires_future_data_gate" in blocked.blocking_reasons
        and not blocked.merge_allowed
        and not blocked.activatable_runtime_allowed
    )


def _assert_runtime_merge_safe(value: BaseModel) -> None:
    payload = value.model_dump_json().lower()
    for fragment in FORBIDDEN_RUNTIME_MERGE_FRAGMENTS:
        if fragment in payload:
            raise ValueError(f"legacy SQL runtime merge evidence contains forbidden fragment: {fragment}")
