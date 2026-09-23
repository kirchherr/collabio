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
    LegacySqlConnectorRealConnectionExecutorStatus,
    LegacySqlConnectorRealConnectionPolicyStoreBackend,
    _policy_store_smoke_input_from_env,
    build_default_legacy_sql_connector_real_connection_executor_policy_store,
    build_legacy_sql_connector_real_connection_executor_policy_bundle,
    build_legacy_sql_connector_real_connection_executor_policy_bundle_hash,
)
from suite.platform.legacy_sql_discovery import MODULE_ID_PATTERN, NAMESPACED_REF_PATTERN, LegacySqlConnectorKind
from suite.platform.legacy_sql_metadata_worker_queue import LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN

LEGACY_SQL_CONNECTOR_EXECUTION_READINESS_HUMAN_REVIEW_SCHEMA_VERSION = (
    "legacy_sql_connector_execution_readiness_human_review.v1"
)
LEGACY_SQL_CONNECTOR_EXECUTION_READINESS_CHANGE_CONTROL_SCHEMA_VERSION = (
    "legacy_sql_connector_execution_readiness_change_control.v1"
)
LEGACY_SQL_CONNECTOR_EXECUTION_READINESS_RESTORE_DRILL_SCHEMA_VERSION = (
    "legacy_sql_connector_execution_readiness_restore_drill.v1"
)
LEGACY_SQL_CONNECTOR_EXECUTION_READINESS_REVIEW_GATE_SCHEMA_VERSION = (
    "legacy_sql_connector_execution_readiness_review_gate.v1"
)
LEGACY_SQL_CONNECTOR_EXECUTION_READINESS_REVIEW_GATE_SMOKE_SCHEMA_VERSION = (
    "legacy_sql_connector_execution_readiness_review_gate_smoke_report.v1"
)
LEGACY_SQL_CONNECTOR_EXECUTION_READINESS_REVIEW_GATE_COMMAND_REF = (
    "docker-compose:legacy-sql-connector-execution-readiness-review-gate-smoke"
)
ZERO_HASH = "sha256:" + "0" * 64
SHA256_REF_PATTERN = r"^sha256:[a-f0-9]{64}$"
REQUIRED_HUMAN_REVIEW_CONTROLS = (
    "executor_policy_bundle_hash",
    "timeout_retry_policy",
    "audit_plan",
    "kill_switch_policy",
    "restore_drill",
    "change_control",
)
FORBIDDEN_REVIEW_GATE_FRAGMENTS = (
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


class LegacySqlConnectorExecutionReadinessReviewGateStatus(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"


class LegacySqlConnectorExecutionReadinessHumanReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_EXECUTION_READINESS_HUMAN_REVIEW_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    policy_bundle_evidence_hash: str
    executor_contract_evidence_hash: str
    reviewer_principal_ref: str
    reviewer_role_ref: str = "role:legacy-sql-execution-readiness-reviewer"
    review_ticket_ref: str
    approval_reference: str
    reviewed_controls: tuple[str, ...] = REQUIRED_HUMAN_REVIEW_CONTROLS
    human_review_completed: bool = True
    reviewer_independent: bool = True
    reviewer_mfa_verified: bool = True
    break_glass_requested: bool = False
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL execution readiness human review text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL execution readiness human review module_id must be lowercase snake_case")
        return value

    @field_validator(
        "source_system_ref", "reviewer_principal_ref", "reviewer_role_ref", "review_ticket_ref", "approval_reference"
    )
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL execution readiness human review references must be namespaced")
        return value

    @field_validator("policy_bundle_evidence_hash", "executor_contract_evidence_hash", "evidence_hash")
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL execution readiness human review hashes must be sha256 references")
        return value

    @field_validator("reviewed_controls")
    @classmethod
    def validate_reviewed_controls(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("legacy SQL execution readiness human review controls must be unique")
        if not set(REQUIRED_HUMAN_REVIEW_CONTROLS).issubset(set(value)):
            raise ValueError("legacy SQL execution readiness human review is missing controls")
        return value

    @model_validator(mode="after")
    def require_safe_human_review(self) -> Self:
        _assert_review_gate_safe(self)
        return self


class LegacySqlConnectorExecutionReadinessChangeControl(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_EXECUTION_READINESS_CHANGE_CONTROL_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    policy_bundle_evidence_hash: str
    executor_contract_evidence_hash: str
    change_request_ref: str
    maintenance_window_ref: str
    rollback_plan_ref: str
    risk_acceptance_ref: str
    change_approved: bool = True
    maintenance_window_active: bool = True
    rollback_plan_verified: bool = True
    risk_acceptance_signed: bool = True
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL execution readiness change-control text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL execution readiness change-control module_id must be lowercase snake_case")
        return value

    @field_validator(
        "source_system_ref",
        "change_request_ref",
        "maintenance_window_ref",
        "rollback_plan_ref",
        "risk_acceptance_ref",
    )
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL execution readiness change-control references must be namespaced")
        return value

    @field_validator("policy_bundle_evidence_hash", "executor_contract_evidence_hash", "evidence_hash")
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL execution readiness change-control hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_safe_change_control(self) -> Self:
        _assert_review_gate_safe(self)
        return self


class LegacySqlConnectorExecutionReadinessRestoreDrill(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_EXECUTION_READINESS_RESTORE_DRILL_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    policy_bundle_evidence_hash: str
    executor_contract_evidence_hash: str
    restore_drill_report_hash: str
    backup_verification_hash: str
    policy_store_roundtrip_hash: str
    restore_drill_passed: bool = True
    policy_store_restored: bool = True
    tenant_isolation_reverified: bool = True
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL execution readiness restore drill text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL execution readiness restore drill module_id must be lowercase snake_case")
        return value

    @field_validator("source_system_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL execution readiness restore drill references must be namespaced")
        return value

    @field_validator(
        "policy_bundle_evidence_hash",
        "executor_contract_evidence_hash",
        "restore_drill_report_hash",
        "backup_verification_hash",
        "policy_store_roundtrip_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL execution readiness restore drill hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_safe_restore_drill(self) -> Self:
        _assert_review_gate_safe(self)
        return self


class LegacySqlConnectorExecutionReadinessReviewGateCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    policy_bundle_evidence_hash: str
    executor_contract_evidence_hash: str
    human_review_evidence_hash: str
    change_control_evidence_hash: str
    restore_drill_evidence_hash: str
    requested_by: str
    execution_readiness_review_requested: bool = True
    socket_materialization_planning_requested: bool = False
    secret_materialization_planning_requested: bool = False
    raw_data_access_requested: bool = False
    import_dry_run_requested: bool = False
    import_write_requested: bool = False
    destructive_actions_requested: bool = False

    @field_validator("tenant_id", "requested_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL execution readiness review gate command text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError(
                "legacy SQL execution readiness review gate command module_id must be lowercase snake_case"
            )
        return value

    @field_validator("source_system_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL execution readiness review gate command references must be namespaced")
        return value

    @field_validator(
        "policy_bundle_evidence_hash",
        "executor_contract_evidence_hash",
        "human_review_evidence_hash",
        "change_control_evidence_hash",
        "restore_drill_evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL execution readiness review gate command hashes must be sha256 references")
        return value


class LegacySqlConnectorExecutionReadinessReviewGateEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_EXECUTION_READINESS_REVIEW_GATE_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    continuity_domain: str = LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN
    command_ref: str = LEGACY_SQL_CONNECTOR_EXECUTION_READINESS_REVIEW_GATE_COMMAND_REF
    policy_bundle_evidence_hash: str
    executor_contract_evidence_hash: str
    preflight_evidence_hash: str
    timeout_retry_policy_hash: str
    audit_plan_hash: str
    kill_switch_policy_hash: str
    human_review_evidence_hash: str
    change_control_evidence_hash: str
    restore_drill_evidence_hash: str
    policy_bundle_hash_valid: bool
    policy_bundle_ready: bool
    policy_bundle_bound: bool
    human_review_hash_valid: bool
    human_review_bound: bool
    human_review_completed: bool
    reviewer_independent: bool
    reviewer_mfa_verified: bool
    change_control_hash_valid: bool
    change_control_bound: bool
    change_approved: bool
    maintenance_window_active: bool
    rollback_plan_verified: bool
    risk_acceptance_signed: bool
    restore_drill_hash_valid: bool
    restore_drill_bound: bool
    restore_drill_passed: bool
    policy_store_restored: bool
    tenant_isolation_reverified: bool
    kill_switch_armed: bool
    tenant_connection_disabled: bool
    global_connection_disabled: bool
    manual_abort_requested: bool
    execution_readiness_review_requested: bool
    execution_readiness_review_passed: bool
    future_materialization_plan_gate_required: bool = True
    socket_materialization_planning_requested: bool = False
    socket_materialization_planning_allowed: bool = False
    secret_materialization_planning_requested: bool = False
    secret_materialization_planning_allowed: bool = False
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
    gate_status: LegacySqlConnectorExecutionReadinessReviewGateStatus
    blocking_reasons: tuple[str, ...]
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL execution readiness review gate evidence text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError(
                "legacy SQL execution readiness review gate evidence module_id must be lowercase snake_case"
            )
        return value

    @field_validator("source_system_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL execution readiness review gate evidence references must be namespaced")
        return value

    @field_validator(
        "policy_bundle_evidence_hash",
        "executor_contract_evidence_hash",
        "preflight_evidence_hash",
        "timeout_retry_policy_hash",
        "audit_plan_hash",
        "kill_switch_policy_hash",
        "human_review_evidence_hash",
        "change_control_evidence_hash",
        "restore_drill_evidence_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL execution readiness review gate hashes must be sha256 references")
        return value

    @field_validator("blocking_reasons")
    @classmethod
    def validate_blocking_reasons(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("legacy SQL execution readiness review gate blocking reasons must be unique")
        for reason in value:
            if not reason.strip():
                raise ValueError("legacy SQL execution readiness review gate blocking reasons must not be empty")
        return value

    @model_validator(mode="after")
    def require_safe_review_gate(self) -> Self:
        if (
            self.socket_materialization_planning_allowed
            or self.secret_materialization_planning_allowed
            or self.network_socket_opened
            or self.network_connection_opened
            or self.real_connection_opened
            or self.secret_material_resolved
            or self.raw_data_access_allowed
            or self.import_dry_run_allowed
            or self.import_write_allowed
            or self.destructive_actions_allowed
        ):
            raise ValueError("legacy SQL execution readiness review gate must remain non-executing")
        if not self.future_materialization_plan_gate_required:
            raise ValueError(
                "legacy SQL execution readiness review gate must require a future materialization plan gate"
            )
        if self.gate_status == LegacySqlConnectorExecutionReadinessReviewGateStatus.READY:
            required = (
                self.policy_bundle_hash_valid,
                self.policy_bundle_ready,
                self.policy_bundle_bound,
                self.human_review_hash_valid,
                self.human_review_bound,
                self.human_review_completed,
                self.reviewer_independent,
                self.reviewer_mfa_verified,
                self.change_control_hash_valid,
                self.change_control_bound,
                self.change_approved,
                self.maintenance_window_active,
                self.rollback_plan_verified,
                self.risk_acceptance_signed,
                self.restore_drill_hash_valid,
                self.restore_drill_bound,
                self.restore_drill_passed,
                self.policy_store_restored,
                self.tenant_isolation_reverified,
                self.kill_switch_armed,
                not self.tenant_connection_disabled,
                not self.global_connection_disabled,
                not self.manual_abort_requested,
                self.execution_readiness_review_requested,
                self.execution_readiness_review_passed,
            )
            if not all(required) or self.blocking_reasons:
                raise ValueError("ready legacy SQL execution readiness review gate requires complete evidence")
        if self.gate_status == LegacySqlConnectorExecutionReadinessReviewGateStatus.BLOCKED:
            if not self.blocking_reasons:
                raise ValueError("blocked legacy SQL execution readiness review gate requires blocking reasons")
            if self.execution_readiness_review_passed:
                raise ValueError("blocked legacy SQL execution readiness review gate cannot pass")
        _assert_review_gate_safe(self)
        return self


class LegacySqlConnectorExecutionReadinessReviewGateSmokeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_EXECUTION_READINESS_REVIEW_GATE_SMOKE_SCHEMA_VERSION
    tenant_id: str
    store_backend: LegacySqlConnectorRealConnectionPolicyStoreBackend
    continuity_domain: str = LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN
    command_ref: str = LEGACY_SQL_CONNECTOR_EXECUTION_READINESS_REVIEW_GATE_COMMAND_REF
    policy_bundle_evidence_hash: str
    review_gate_evidence_hash: str
    human_review_evidence_hash: str
    change_control_evidence_hash: str
    restore_drill_evidence_hash: str
    review_gate_ready: bool
    stored_policy_bundle_required: bool
    human_review_required: bool
    change_control_required: bool
    restore_drill_required: bool
    kill_switch_required: bool
    missing_human_review_blocked: bool
    change_control_missing_blocked: bool
    kill_switch_disabled_blocked: bool
    materialization_planning_request_blocked: bool
    future_materialization_plan_gate_required: bool
    socket_materialization_planning_allowed: bool = False
    secret_materialization_planning_allowed: bool = False
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
            self.socket_materialization_planning_allowed
            or self.secret_materialization_planning_allowed
            or self.network_socket_opened
            or self.network_connection_opened
            or self.real_connection_opened
            or self.secret_material_resolved
            or self.raw_data_access_allowed
            or self.import_dry_run_allowed
            or self.import_write_allowed
            or self.destructive_actions_allowed
        ):
            raise ValueError("legacy SQL execution readiness review gate smoke must remain non-executing")
        _assert_review_gate_safe(self)
        return self


def build_legacy_sql_connector_execution_readiness_human_review(
    *,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    reviewer_principal_ref: str,
    review_ticket_ref: str,
    approval_reference: str,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    human_review_completed: bool = True,
    reviewer_independent: bool = True,
    reviewer_mfa_verified: bool = True,
) -> LegacySqlConnectorExecutionReadinessHumanReview:
    checked_at = checked_at_utc or datetime.now(UTC)
    draft = LegacySqlConnectorExecutionReadinessHumanReview(
        tenant_id=bundle.tenant_id,
        module_id=bundle.module_id,
        source_system_ref=bundle.source_system_ref,
        connector_kind=bundle.connector_kind,
        policy_bundle_evidence_hash=bundle.evidence_hash,
        executor_contract_evidence_hash=bundle.executor_contract_evidence_hash,
        reviewer_principal_ref=reviewer_principal_ref,
        review_ticket_ref=review_ticket_ref,
        approval_reference=approval_reference,
        human_review_completed=human_review_completed,
        reviewer_independent=reviewer_independent,
        reviewer_mfa_verified=reviewer_mfa_verified,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_execution_readiness_human_review_hash(draft)}
    )


def build_legacy_sql_connector_execution_readiness_change_control(
    *,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    change_request_ref: str,
    maintenance_window_ref: str,
    rollback_plan_ref: str,
    risk_acceptance_ref: str,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    change_approved: bool = True,
    maintenance_window_active: bool = True,
    rollback_plan_verified: bool = True,
    risk_acceptance_signed: bool = True,
) -> LegacySqlConnectorExecutionReadinessChangeControl:
    checked_at = checked_at_utc or datetime.now(UTC)
    draft = LegacySqlConnectorExecutionReadinessChangeControl(
        tenant_id=bundle.tenant_id,
        module_id=bundle.module_id,
        source_system_ref=bundle.source_system_ref,
        connector_kind=bundle.connector_kind,
        policy_bundle_evidence_hash=bundle.evidence_hash,
        executor_contract_evidence_hash=bundle.executor_contract_evidence_hash,
        change_request_ref=change_request_ref,
        maintenance_window_ref=maintenance_window_ref,
        rollback_plan_ref=rollback_plan_ref,
        risk_acceptance_ref=risk_acceptance_ref,
        change_approved=change_approved,
        maintenance_window_active=maintenance_window_active,
        rollback_plan_verified=rollback_plan_verified,
        risk_acceptance_signed=risk_acceptance_signed,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_execution_readiness_change_control_hash(draft)}
    )


def build_legacy_sql_connector_execution_readiness_restore_drill(
    *,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    restore_drill_report_hash: str,
    backup_verification_hash: str,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    restore_drill_passed: bool = True,
    policy_store_restored: bool = True,
    tenant_isolation_reverified: bool = True,
) -> LegacySqlConnectorExecutionReadinessRestoreDrill:
    checked_at = checked_at_utc or datetime.now(UTC)
    draft = LegacySqlConnectorExecutionReadinessRestoreDrill(
        tenant_id=bundle.tenant_id,
        module_id=bundle.module_id,
        source_system_ref=bundle.source_system_ref,
        connector_kind=bundle.connector_kind,
        policy_bundle_evidence_hash=bundle.evidence_hash,
        executor_contract_evidence_hash=bundle.executor_contract_evidence_hash,
        restore_drill_report_hash=restore_drill_report_hash,
        backup_verification_hash=backup_verification_hash,
        policy_store_roundtrip_hash=bundle.evidence_hash,
        restore_drill_passed=restore_drill_passed,
        policy_store_restored=policy_store_restored,
        tenant_isolation_reverified=tenant_isolation_reverified,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_execution_readiness_restore_drill_hash(draft)}
    )


def build_legacy_sql_connector_execution_readiness_review_gate_command(
    *,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    human_review: LegacySqlConnectorExecutionReadinessHumanReview,
    change_control: LegacySqlConnectorExecutionReadinessChangeControl,
    restore_drill: LegacySqlConnectorExecutionReadinessRestoreDrill,
    requested_by: str,
    execution_readiness_review_requested: bool = True,
    socket_materialization_planning_requested: bool = False,
    secret_materialization_planning_requested: bool = False,
    raw_data_access_requested: bool = False,
    import_dry_run_requested: bool = False,
    import_write_requested: bool = False,
    destructive_actions_requested: bool = False,
) -> LegacySqlConnectorExecutionReadinessReviewGateCommand:
    return LegacySqlConnectorExecutionReadinessReviewGateCommand(
        tenant_id=bundle.tenant_id,
        module_id=bundle.module_id,
        source_system_ref=bundle.source_system_ref,
        connector_kind=bundle.connector_kind,
        policy_bundle_evidence_hash=bundle.evidence_hash,
        executor_contract_evidence_hash=bundle.executor_contract_evidence_hash,
        human_review_evidence_hash=human_review.evidence_hash,
        change_control_evidence_hash=change_control.evidence_hash,
        restore_drill_evidence_hash=restore_drill.evidence_hash,
        requested_by=requested_by,
        execution_readiness_review_requested=execution_readiness_review_requested,
        socket_materialization_planning_requested=socket_materialization_planning_requested,
        secret_materialization_planning_requested=secret_materialization_planning_requested,
        raw_data_access_requested=raw_data_access_requested,
        import_dry_run_requested=import_dry_run_requested,
        import_write_requested=import_write_requested,
        destructive_actions_requested=destructive_actions_requested,
    )


def build_legacy_sql_connector_execution_readiness_review_gate(
    *,
    command: LegacySqlConnectorExecutionReadinessReviewGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    human_review: LegacySqlConnectorExecutionReadinessHumanReview,
    change_control: LegacySqlConnectorExecutionReadinessChangeControl,
    restore_drill: LegacySqlConnectorExecutionReadinessRestoreDrill,
    checked_by: str,
    checked_at_utc: datetime | None = None,
) -> LegacySqlConnectorExecutionReadinessReviewGateEvidence:
    checked_at = checked_at_utc or datetime.now(UTC)
    policy_bundle_hash_valid = (
        build_legacy_sql_connector_real_connection_executor_policy_bundle_hash(bundle)
        == bundle.evidence_hash
        == command.policy_bundle_evidence_hash
    )
    policy_bundle_ready = (
        bundle.bundle_status == LegacySqlConnectorRealConnectionExecutorStatus.READY
        and bundle.store_persistence_allowed
        and bundle.executor_contract.executor_contract_ready
    )
    policy_bundle_bound = _policy_bundle_bound(command=command, bundle=bundle)
    human_review_hash_valid = (
        build_legacy_sql_connector_execution_readiness_human_review_hash(human_review)
        == human_review.evidence_hash
        == command.human_review_evidence_hash
    )
    human_review_bound = _review_artifact_bound(command=command, artifact=human_review)
    change_control_hash_valid = (
        build_legacy_sql_connector_execution_readiness_change_control_hash(change_control)
        == change_control.evidence_hash
        == command.change_control_evidence_hash
    )
    change_control_bound = _review_artifact_bound(command=command, artifact=change_control)
    restore_drill_hash_valid = (
        build_legacy_sql_connector_execution_readiness_restore_drill_hash(restore_drill)
        == restore_drill.evidence_hash
        == command.restore_drill_evidence_hash
    )
    restore_drill_bound = _review_artifact_bound(command=command, artifact=restore_drill)
    blocking_reasons = _review_gate_blocking_reasons(
        command=command,
        policy_bundle_hash_valid=policy_bundle_hash_valid,
        policy_bundle_ready=policy_bundle_ready,
        policy_bundle_bound=policy_bundle_bound,
        human_review_hash_valid=human_review_hash_valid,
        human_review_bound=human_review_bound,
        human_review=human_review,
        change_control_hash_valid=change_control_hash_valid,
        change_control_bound=change_control_bound,
        change_control=change_control,
        restore_drill_hash_valid=restore_drill_hash_valid,
        restore_drill_bound=restore_drill_bound,
        restore_drill=restore_drill,
        bundle=bundle,
    )
    ready = not blocking_reasons
    draft = LegacySqlConnectorExecutionReadinessReviewGateEvidence(
        tenant_id=bundle.tenant_id,
        module_id=bundle.module_id,
        source_system_ref=bundle.source_system_ref,
        connector_kind=bundle.connector_kind,
        policy_bundle_evidence_hash=bundle.evidence_hash,
        executor_contract_evidence_hash=bundle.executor_contract_evidence_hash,
        preflight_evidence_hash=bundle.preflight_evidence_hash,
        timeout_retry_policy_hash=bundle.timeout_retry_policy_hash,
        audit_plan_hash=bundle.audit_plan_hash,
        kill_switch_policy_hash=bundle.kill_switch_policy_hash,
        human_review_evidence_hash=human_review.evidence_hash,
        change_control_evidence_hash=change_control.evidence_hash,
        restore_drill_evidence_hash=restore_drill.evidence_hash,
        policy_bundle_hash_valid=policy_bundle_hash_valid,
        policy_bundle_ready=policy_bundle_ready,
        policy_bundle_bound=policy_bundle_bound,
        human_review_hash_valid=human_review_hash_valid,
        human_review_bound=human_review_bound,
        human_review_completed=human_review.human_review_completed,
        reviewer_independent=human_review.reviewer_independent,
        reviewer_mfa_verified=human_review.reviewer_mfa_verified,
        change_control_hash_valid=change_control_hash_valid,
        change_control_bound=change_control_bound,
        change_approved=change_control.change_approved,
        maintenance_window_active=change_control.maintenance_window_active,
        rollback_plan_verified=change_control.rollback_plan_verified,
        risk_acceptance_signed=change_control.risk_acceptance_signed,
        restore_drill_hash_valid=restore_drill_hash_valid,
        restore_drill_bound=restore_drill_bound,
        restore_drill_passed=restore_drill.restore_drill_passed,
        policy_store_restored=restore_drill.policy_store_restored,
        tenant_isolation_reverified=restore_drill.tenant_isolation_reverified,
        kill_switch_armed=bundle.kill_switch_policy.kill_switch_armed,
        tenant_connection_disabled=bundle.kill_switch_policy.tenant_connection_disabled,
        global_connection_disabled=bundle.kill_switch_policy.global_connection_disabled,
        manual_abort_requested=bundle.kill_switch_policy.manual_abort_requested,
        execution_readiness_review_requested=command.execution_readiness_review_requested,
        execution_readiness_review_passed=ready,
        socket_materialization_planning_requested=command.socket_materialization_planning_requested,
        secret_materialization_planning_requested=command.secret_materialization_planning_requested,
        raw_data_access_requested=command.raw_data_access_requested,
        import_dry_run_requested=command.import_dry_run_requested,
        import_write_requested=command.import_write_requested,
        destructive_actions_requested=command.destructive_actions_requested,
        gate_status=(
            LegacySqlConnectorExecutionReadinessReviewGateStatus.READY
            if ready
            else LegacySqlConnectorExecutionReadinessReviewGateStatus.BLOCKED
        ),
        blocking_reasons=blocking_reasons,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_execution_readiness_review_gate_hash(draft)}
    )


def build_legacy_sql_connector_execution_readiness_human_review_hash(
    review: LegacySqlConnectorExecutionReadinessHumanReview,
) -> str:
    return stable_hash(canonical_json(review.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_execution_readiness_change_control_hash(
    change_control: LegacySqlConnectorExecutionReadinessChangeControl,
) -> str:
    return stable_hash(canonical_json(change_control.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_execution_readiness_restore_drill_hash(
    restore_drill: LegacySqlConnectorExecutionReadinessRestoreDrill,
) -> str:
    return stable_hash(canonical_json(restore_drill.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_execution_readiness_review_gate_hash(
    gate: LegacySqlConnectorExecutionReadinessReviewGateEvidence,
) -> str:
    return stable_hash(canonical_json(gate.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_execution_readiness_review_gate_smoke_report_hash(
    report: LegacySqlConnectorExecutionReadinessReviewGateSmokeReport,
) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def run_legacy_sql_connector_execution_readiness_review_gate_smoke_from_env(
    environ: Mapping[str, str] | None = None,
) -> LegacySqlConnectorExecutionReadinessReviewGateSmokeReport:
    env = os.environ if environ is None else environ
    checked_by = env.get(
        "SUITE_LEGACY_SQL_CONNECTOR_EXECUTION_READINESS_REVIEW_GATE_CHECKED_BY",
        "legacy-sql-connector-execution-readiness-review-gate-smoke",
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
    stored_bundle = store.append(bundle)
    fetched_bundle = store.get(
        tenant_id=stored_bundle.tenant_id,
        executor_contract_evidence_hash=stored_bundle.executor_contract_evidence_hash,
    )
    human_review = build_legacy_sql_connector_execution_readiness_human_review(
        bundle=fetched_bundle,
        reviewer_principal_ref=env.get(
            "SUITE_LEGACY_SQL_CONNECTOR_EXECUTION_READINESS_REVIEWER_REF",
            "principal:legacy-sql-execution-reviewer",
        ),
        review_ticket_ref=env.get(
            "SUITE_LEGACY_SQL_CONNECTOR_EXECUTION_READINESS_REVIEW_TICKET_REF",
            "review-ticket:legacy-sql-execution-readiness",
        ),
        approval_reference=env.get(
            "SUITE_LEGACY_SQL_CONNECTOR_EXECUTION_READINESS_APPROVAL_REF",
            "approval:legacy-sql-execution-readiness",
        ),
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=19),
    )
    change_control = build_legacy_sql_connector_execution_readiness_change_control(
        bundle=fetched_bundle,
        change_request_ref=env.get(
            "SUITE_LEGACY_SQL_CONNECTOR_EXECUTION_READINESS_CHANGE_REQUEST_REF",
            "change-request:legacy-sql-execution-readiness",
        ),
        maintenance_window_ref=env.get(
            "SUITE_LEGACY_SQL_CONNECTOR_EXECUTION_READINESS_MAINTENANCE_WINDOW_REF",
            "maintenance-window:legacy-sql-execution-readiness",
        ),
        rollback_plan_ref=env.get(
            "SUITE_LEGACY_SQL_CONNECTOR_EXECUTION_READINESS_ROLLBACK_PLAN_REF",
            "rollback-plan:legacy-sql-execution-readiness",
        ),
        risk_acceptance_ref=env.get(
            "SUITE_LEGACY_SQL_CONNECTOR_EXECUTION_READINESS_RISK_ACCEPTANCE_REF",
            "risk-acceptance:legacy-sql-execution-readiness",
        ),
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=20),
    )
    restore_drill = build_legacy_sql_connector_execution_readiness_restore_drill(
        bundle=fetched_bundle,
        restore_drill_report_hash=env.get(
            "SUITE_LEGACY_SQL_CONNECTOR_EXECUTION_READINESS_RESTORE_DRILL_HASH",
            "sha256:" + "8" * 64,
        ),
        backup_verification_hash=env.get(
            "SUITE_LEGACY_SQL_CONNECTOR_EXECUTION_READINESS_BACKUP_VERIFY_HASH",
            "sha256:" + "9" * 64,
        ),
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=21),
    )
    command = build_legacy_sql_connector_execution_readiness_review_gate_command(
        bundle=fetched_bundle,
        human_review=human_review,
        change_control=change_control,
        restore_drill=restore_drill,
        requested_by=checked_by,
    )
    gate = build_legacy_sql_connector_execution_readiness_review_gate(
        command=command,
        bundle=fetched_bundle,
        human_review=human_review,
        change_control=change_control,
        restore_drill=restore_drill,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=22),
    )
    missing_human_review_blocked = _missing_human_review_blocked(
        command=command,
        bundle=fetched_bundle,
        human_review=human_review,
        change_control=change_control,
        restore_drill=restore_drill,
        checked_by=checked_by,
        checked_at=checked_at + timedelta(seconds=23),
    )
    change_control_missing_blocked = _change_control_missing_blocked(
        command=command,
        bundle=fetched_bundle,
        human_review=human_review,
        change_control=change_control,
        restore_drill=restore_drill,
        checked_by=checked_by,
        checked_at=checked_at + timedelta(seconds=24),
    )
    kill_switch_disabled_blocked = _kill_switch_disabled_blocked(
        command=command,
        bundle=fetched_bundle,
        human_review=human_review,
        change_control=change_control,
        restore_drill=restore_drill,
        checked_by=checked_by,
        checked_at=checked_at + timedelta(seconds=25),
    )
    materialization_planning_request_blocked = _materialization_planning_request_blocked(
        command=command,
        bundle=fetched_bundle,
        human_review=human_review,
        change_control=change_control,
        restore_drill=restore_drill,
        checked_by=checked_by,
        checked_at=checked_at + timedelta(seconds=26),
    )
    review_gate_ready = (
        gate.gate_status == LegacySqlConnectorExecutionReadinessReviewGateStatus.READY
        and gate.execution_readiness_review_passed
        and missing_human_review_blocked
        and change_control_missing_blocked
        and kill_switch_disabled_blocked
        and materialization_planning_request_blocked
        and not gate.socket_materialization_planning_allowed
        and not gate.secret_materialization_planning_allowed
        and not gate.real_connection_opened
    )
    draft = LegacySqlConnectorExecutionReadinessReviewGateSmokeReport(
        tenant_id=fetched_bundle.tenant_id,
        store_backend=store_backend,
        policy_bundle_evidence_hash=fetched_bundle.evidence_hash,
        review_gate_evidence_hash=gate.evidence_hash,
        human_review_evidence_hash=human_review.evidence_hash,
        change_control_evidence_hash=change_control.evidence_hash,
        restore_drill_evidence_hash=restore_drill.evidence_hash,
        review_gate_ready=review_gate_ready,
        stored_policy_bundle_required=gate.policy_bundle_ready and gate.policy_bundle_bound,
        human_review_required=gate.human_review_completed and gate.reviewer_independent and gate.reviewer_mfa_verified,
        change_control_required=gate.change_approved and gate.rollback_plan_verified,
        restore_drill_required=gate.restore_drill_passed and gate.policy_store_restored,
        kill_switch_required=gate.kill_switch_armed and not gate.tenant_connection_disabled,
        missing_human_review_blocked=missing_human_review_blocked,
        change_control_missing_blocked=change_control_missing_blocked,
        kill_switch_disabled_blocked=kill_switch_disabled_blocked,
        materialization_planning_request_blocked=materialization_planning_request_blocked,
        future_materialization_plan_gate_required=gate.future_materialization_plan_gate_required,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    _assert_review_gate_safe(draft)
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_execution_readiness_review_gate_smoke_report_hash(draft)}
    )


def exit_code_for_report(report: LegacySqlConnectorExecutionReadinessReviewGateSmokeReport) -> int:
    return 0 if report.review_gate_ready else 1


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Legacy SQL execution readiness review gate smoke.")
    parser.add_argument("--once", action="store_true", help="Run one non-executing review gate smoke and exit.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the review gate report.")
    args = parser.parse_args(argv)
    del args.once

    report = run_legacy_sql_connector_execution_readiness_review_gate_smoke_from_env()
    print(json.dumps(report.model_dump(mode="json"), indent=2 if args.pretty else None, sort_keys=True))
    raise SystemExit(exit_code_for_report(report))


def _policy_bundle_bound(
    *,
    command: LegacySqlConnectorExecutionReadinessReviewGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
) -> bool:
    return (
        command.tenant_id == bundle.tenant_id
        and command.module_id == bundle.module_id
        and command.source_system_ref == bundle.source_system_ref
        and command.connector_kind == bundle.connector_kind
        and command.executor_contract_evidence_hash == bundle.executor_contract_evidence_hash
        and not bundle.network_socket_opened
        and not bundle.secret_material_resolved
        and not bundle.real_connection_opened
        and not bundle.raw_data_access_allowed
        and not bundle.import_dry_run_allowed
        and not bundle.import_write_allowed
        and not bundle.destructive_actions_allowed
    )


def _review_artifact_bound(
    *,
    command: LegacySqlConnectorExecutionReadinessReviewGateCommand,
    artifact: (
        LegacySqlConnectorExecutionReadinessHumanReview
        | LegacySqlConnectorExecutionReadinessChangeControl
        | LegacySqlConnectorExecutionReadinessRestoreDrill
    ),
) -> bool:
    return (
        command.tenant_id == artifact.tenant_id
        and command.module_id == artifact.module_id
        and command.source_system_ref == artifact.source_system_ref
        and command.connector_kind == artifact.connector_kind
        and command.policy_bundle_evidence_hash == artifact.policy_bundle_evidence_hash
        and command.executor_contract_evidence_hash == artifact.executor_contract_evidence_hash
    )


def _review_gate_blocking_reasons(
    *,
    command: LegacySqlConnectorExecutionReadinessReviewGateCommand,
    policy_bundle_hash_valid: bool,
    policy_bundle_ready: bool,
    policy_bundle_bound: bool,
    human_review_hash_valid: bool,
    human_review_bound: bool,
    human_review: LegacySqlConnectorExecutionReadinessHumanReview,
    change_control_hash_valid: bool,
    change_control_bound: bool,
    change_control: LegacySqlConnectorExecutionReadinessChangeControl,
    restore_drill_hash_valid: bool,
    restore_drill_bound: bool,
    restore_drill: LegacySqlConnectorExecutionReadinessRestoreDrill,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not policy_bundle_hash_valid:
        reasons.append("policy_bundle_hash_invalid")
    if not policy_bundle_ready:
        reasons.append("policy_bundle_not_ready")
    if not policy_bundle_bound:
        reasons.append("policy_bundle_not_bound")
    if not human_review_hash_valid:
        reasons.append("human_review_hash_invalid")
    if not human_review_bound:
        reasons.append("human_review_not_bound")
    if not human_review.human_review_completed:
        reasons.append("human_review_not_completed")
    if not human_review.reviewer_independent:
        reasons.append("reviewer_not_independent")
    if not human_review.reviewer_mfa_verified:
        reasons.append("reviewer_mfa_not_verified")
    if human_review.break_glass_requested:
        reasons.append("break_glass_requires_separate_incident_gate")
    if not change_control_hash_valid:
        reasons.append("change_control_hash_invalid")
    if not change_control_bound:
        reasons.append("change_control_not_bound")
    if not change_control.change_approved:
        reasons.append("change_not_approved")
    if not change_control.maintenance_window_active:
        reasons.append("maintenance_window_not_active")
    if not change_control.rollback_plan_verified:
        reasons.append("rollback_plan_not_verified")
    if not change_control.risk_acceptance_signed:
        reasons.append("risk_acceptance_not_signed")
    if not restore_drill_hash_valid:
        reasons.append("restore_drill_hash_invalid")
    if not restore_drill_bound:
        reasons.append("restore_drill_not_bound")
    if not restore_drill.restore_drill_passed:
        reasons.append("restore_drill_not_passed")
    if not restore_drill.policy_store_restored:
        reasons.append("policy_store_not_restored")
    if not restore_drill.tenant_isolation_reverified:
        reasons.append("tenant_isolation_not_reverified")
    if not bundle.kill_switch_policy.kill_switch_armed:
        reasons.append("kill_switch_not_armed")
    if bundle.kill_switch_policy.tenant_connection_disabled:
        reasons.append("tenant_connection_kill_switch_disabled")
    if bundle.kill_switch_policy.global_connection_disabled:
        reasons.append("global_connection_kill_switch_disabled")
    if bundle.kill_switch_policy.manual_abort_requested:
        reasons.append("manual_abort_requested")
    if not command.execution_readiness_review_requested:
        reasons.append("execution_readiness_review_not_requested")
    if command.socket_materialization_planning_requested:
        reasons.append("socket_materialization_planning_requires_future_gate")
    if command.secret_materialization_planning_requested:
        reasons.append("secret_materialization_planning_requires_future_gate")
    if command.raw_data_access_requested:
        reasons.append("raw_data_access_request_requires_separate_gate")
    if command.import_dry_run_requested:
        reasons.append("import_dry_run_request_requires_separate_gate")
    if command.import_write_requested:
        reasons.append("import_write_request_requires_separate_gate")
    if command.destructive_actions_requested:
        reasons.append("destructive_action_request_requires_separate_gate")
    return tuple(sorted(set(reasons)))


def _missing_human_review_blocked(
    *,
    command: LegacySqlConnectorExecutionReadinessReviewGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    human_review: LegacySqlConnectorExecutionReadinessHumanReview,
    change_control: LegacySqlConnectorExecutionReadinessChangeControl,
    restore_drill: LegacySqlConnectorExecutionReadinessRestoreDrill,
    checked_by: str,
    checked_at: datetime,
) -> bool:
    blocked_review = human_review.model_copy(
        update={"human_review_completed": False, "checked_at_utc": checked_at, "evidence_hash": ZERO_HASH}
    )
    blocked_review = blocked_review.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_execution_readiness_human_review_hash(blocked_review)}
    )
    blocked = build_legacy_sql_connector_execution_readiness_review_gate(
        command=command.model_copy(update={"human_review_evidence_hash": blocked_review.evidence_hash}),
        bundle=bundle,
        human_review=blocked_review,
        change_control=change_control,
        restore_drill=restore_drill,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        blocked.gate_status == LegacySqlConnectorExecutionReadinessReviewGateStatus.BLOCKED
        and "human_review_not_completed" in blocked.blocking_reasons
    )


def _change_control_missing_blocked(
    *,
    command: LegacySqlConnectorExecutionReadinessReviewGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    human_review: LegacySqlConnectorExecutionReadinessHumanReview,
    change_control: LegacySqlConnectorExecutionReadinessChangeControl,
    restore_drill: LegacySqlConnectorExecutionReadinessRestoreDrill,
    checked_by: str,
    checked_at: datetime,
) -> bool:
    blocked_change = change_control.model_copy(
        update={"rollback_plan_verified": False, "checked_at_utc": checked_at, "evidence_hash": ZERO_HASH}
    )
    blocked_change = blocked_change.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_execution_readiness_change_control_hash(blocked_change)}
    )
    blocked = build_legacy_sql_connector_execution_readiness_review_gate(
        command=command.model_copy(update={"change_control_evidence_hash": blocked_change.evidence_hash}),
        bundle=bundle,
        human_review=human_review,
        change_control=blocked_change,
        restore_drill=restore_drill,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        blocked.gate_status == LegacySqlConnectorExecutionReadinessReviewGateStatus.BLOCKED
        and "rollback_plan_not_verified" in blocked.blocking_reasons
    )


def _kill_switch_disabled_blocked(
    *,
    command: LegacySqlConnectorExecutionReadinessReviewGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    human_review: LegacySqlConnectorExecutionReadinessHumanReview,
    change_control: LegacySqlConnectorExecutionReadinessChangeControl,
    restore_drill: LegacySqlConnectorExecutionReadinessRestoreDrill,
    checked_by: str,
    checked_at: datetime,
) -> bool:
    disabled_policy = bundle.kill_switch_policy.model_copy(update={"tenant_connection_disabled": True})
    disabled_bundle = bundle.model_copy(update={"kill_switch_policy": disabled_policy})
    blocked = build_legacy_sql_connector_execution_readiness_review_gate(
        command=command,
        bundle=disabled_bundle,
        human_review=human_review,
        change_control=change_control,
        restore_drill=restore_drill,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        blocked.gate_status == LegacySqlConnectorExecutionReadinessReviewGateStatus.BLOCKED
        and "tenant_connection_kill_switch_disabled" in blocked.blocking_reasons
    )


def _materialization_planning_request_blocked(
    *,
    command: LegacySqlConnectorExecutionReadinessReviewGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    human_review: LegacySqlConnectorExecutionReadinessHumanReview,
    change_control: LegacySqlConnectorExecutionReadinessChangeControl,
    restore_drill: LegacySqlConnectorExecutionReadinessRestoreDrill,
    checked_by: str,
    checked_at: datetime,
) -> bool:
    blocked = build_legacy_sql_connector_execution_readiness_review_gate(
        command=command.model_copy(
            update={
                "socket_materialization_planning_requested": True,
                "secret_materialization_planning_requested": True,
            }
        ),
        bundle=bundle,
        human_review=human_review,
        change_control=change_control,
        restore_drill=restore_drill,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        blocked.gate_status == LegacySqlConnectorExecutionReadinessReviewGateStatus.BLOCKED
        and "socket_materialization_planning_requires_future_gate" in blocked.blocking_reasons
        and "secret_materialization_planning_requires_future_gate" in blocked.blocking_reasons
        and not blocked.socket_materialization_planning_allowed
        and not blocked.secret_materialization_planning_allowed
    )


def _assert_review_gate_safe(value: BaseModel) -> None:
    payload = value.model_dump_json().lower()
    for fragment in FORBIDDEN_REVIEW_GATE_FRAGMENTS:
        if fragment in payload:
            raise ValueError(f"legacy SQL execution readiness review gate leaked forbidden fragment: {fragment}")


if __name__ == "__main__":
    main()
