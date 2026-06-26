from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, Self
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.platform.crm_erp_legacy_mapping import CRM_ERP_MODULE_ID
from suite.platform.legacy_sql_discovery import NAMESPACED_REF_PATTERN
from suite.platform.legacy_sql_import_dry_run_worker import (
    JsonlLegacySqlImportDryRunResultStore,
    LegacySqlImportDryRunResult,
    LegacySqlImportDryRunResultStatus,
    LegacySqlImportDryRunWorkerReport,
    build_legacy_sql_import_dry_run_result_hash,
    build_legacy_sql_import_dry_run_worker_report_hash,
    run_legacy_sql_import_dry_run_worker_from_env,
)
from suite.platform.storage_paths import suite_data_dir

LEGACY_SQL_IMPORT_WRITE_APPROVAL_REVIEW_SCHEMA_VERSION = "legacy_sql_import_write_approval_review.v1"
LEGACY_SQL_IMPORT_WRITE_CHANGE_CONTROL_SCHEMA_VERSION = "legacy_sql_import_write_change_control.v1"
LEGACY_SQL_IMPORT_WRITE_RESTORE_DRILL_SCHEMA_VERSION = "legacy_sql_import_write_restore_drill.v1"
LEGACY_SQL_IMPORT_WRITE_APPROVAL_GATE_SCHEMA_VERSION = "legacy_sql_import_write_approval_gate.v1"
LEGACY_SQL_IMPORT_WRITE_APPROVAL_GATE_SMOKE_SCHEMA_VERSION = "legacy_sql_import_write_approval_gate_smoke_report.v1"
LEGACY_SQL_IMPORT_WRITE_APPROVAL_REQUEST_BOUNDARY_SCHEMA_VERSION = (
    "legacy_sql_import_write_approval_request_boundary.v1"
)
LEGACY_SQL_IMPORT_WRITE_APPROVAL_GATE_COMMAND_REF = "docker-compose:legacy-sql-import-write-approval-gate-smoke"
LEGACY_SQL_IMPORT_WRITE_APPROVAL_REQUEST_BOUNDARY_COMMAND_REF = (
    "api:v1-admin-crm-erp-legacy-sql-import-write-approval-request-boundary"
)
LEGACY_SQL_IMPORT_WRITE_APPROVAL_CONTINUITY_DOMAIN = "crm_erp_business_records"
ZERO_HASH = "sha256:" + "0" * 64
SHA256_REF_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
REQUIRED_IMPORT_WRITE_APPROVAL_CONTROLS = (
    "dry_run_result_hash",
    "dry_run_worker_report_hash",
    "row_count_reconciliation",
    "checksum_manifest_review",
    "restore_evidence",
    "rollback_plan",
    "operator_mfa",
)
REQUIRED_IMPORT_WRITE_APPROVAL_REQUEST_EVIDENCE = (
    "legacy_sql_import_write_approval_gate",
    "approval_ticket_ref",
    "human_confirmation_reference",
    "future_import_write_execution_gate",
)
LEGACY_SQL_IMPORT_WRITE_APPROVAL_RECORD_PERSISTENCE_PLAN_SCHEMA_VERSION = (
    "legacy_sql_import_write_approval_record_persistence_plan.v1"
)
LEGACY_SQL_IMPORT_WRITE_APPROVAL_RECORD_PERSISTENCE_PLAN_COMMAND_REF = (
    "planning:legacy-sql-import-write-approval-record-persistence"
)
REQUIRED_IMPORT_WRITE_APPROVAL_RECORD_PERSISTENCE_PLAN_EVIDENCE = (
    "approval_request_boundary",
    "approval_gate_evidence",
    "tenant_scoped_rls_store",
    "append_only_record_store",
    "idempotency_key",
    "future_import_write_execution_gate",
)
FORBIDDEN_APPROVAL_GATE_FRAGMENTS = (
    '"connection_secret_ref":',
    "secret:",
    "sqlserver://",
    "password",
    "dsn",
    "plain_secret",
    "connection_string",
    '"raw_payload":',
    '"sample_values":',
    '"import_write_payload":',
    "dbo.kunden",
    "dbo.freietabelle",
    "kundenid",
    "email",
)


class LegacySqlImportWriteApprovalGateStoreBackend(StrEnum):
    JSONL = "jsonl"
    POSTGRES = "postgres"


class LegacySqlImportWriteApprovalGateStatus(StrEnum):
    READY_FOR_HUMAN_APPROVAL_RECORD = "ready_for_human_approval_record"
    BLOCKED = "blocked"


class LegacySqlImportWriteApprovalRequestBoundaryStatus(StrEnum):
    READY_FOR_APPROVAL_RECORD_REQUEST = "ready_for_approval_record_request"
    BLOCKED = "blocked"


class LegacySqlImportWriteApprovalRecordPersistencePlanStatus(StrEnum):
    READY_FOR_STORE_IMPLEMENTATION = "ready_for_store_implementation"
    BLOCKED = "blocked"


class LegacySqlImportWriteApprovalReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_IMPORT_WRITE_APPROVAL_REVIEW_SCHEMA_VERSION
    tenant_id: str
    module_id: str = CRM_ERP_MODULE_ID
    source_system_ref: str
    dry_run_plan_hash: str
    dry_run_result_hash: str
    dry_run_worker_report_hash: str
    reviewer_principal_ref: str
    reviewer_role_ref: str = "role:legacy-sql-import-write-reviewer"
    review_ticket_ref: str
    approval_reference: str
    reviewed_controls: tuple[str, ...] = REQUIRED_IMPORT_WRITE_APPROVAL_CONTROLS
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
            raise ValueError("legacy SQL import write approval review text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def require_crm_erp_module(cls, value: str) -> str:
        if value != CRM_ERP_MODULE_ID:
            raise ValueError("legacy SQL import write approval review only applies to module crm_erp")
        return value

    @field_validator(
        "source_system_ref",
        "reviewer_principal_ref",
        "reviewer_role_ref",
        "review_ticket_ref",
        "approval_reference",
    )
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL import write approval review references must be namespaced")
        return value

    @field_validator("dry_run_plan_hash", "dry_run_result_hash", "dry_run_worker_report_hash", "evidence_hash")
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL import write approval review hashes must be sha256 references")
        return value

    @field_validator("reviewed_controls")
    @classmethod
    def validate_reviewed_controls(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("legacy SQL import write approval review controls must be unique")
        if not set(REQUIRED_IMPORT_WRITE_APPROVAL_CONTROLS).issubset(set(value)):
            raise ValueError("legacy SQL import write approval review is missing required controls")
        return value

    @model_validator(mode="after")
    def require_safe_review(self) -> Self:
        _assert_approval_gate_safe(self)
        return self


class LegacySqlImportWriteChangeControl(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_IMPORT_WRITE_CHANGE_CONTROL_SCHEMA_VERSION
    tenant_id: str
    module_id: str = CRM_ERP_MODULE_ID
    source_system_ref: str
    dry_run_plan_hash: str
    dry_run_result_hash: str
    dry_run_worker_report_hash: str
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
            raise ValueError("legacy SQL import write change-control text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def require_crm_erp_module(cls, value: str) -> str:
        if value != CRM_ERP_MODULE_ID:
            raise ValueError("legacy SQL import write change-control only applies to module crm_erp")
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
            raise ValueError("legacy SQL import write change-control references must be namespaced")
        return value

    @field_validator("dry_run_plan_hash", "dry_run_result_hash", "dry_run_worker_report_hash", "evidence_hash")
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL import write change-control hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_safe_change_control(self) -> Self:
        _assert_approval_gate_safe(self)
        return self


class LegacySqlImportWriteRestoreDrill(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_IMPORT_WRITE_RESTORE_DRILL_SCHEMA_VERSION
    tenant_id: str
    module_id: str = CRM_ERP_MODULE_ID
    source_system_ref: str
    dry_run_plan_hash: str
    dry_run_result_hash: str
    dry_run_worker_report_hash: str
    restore_drill_report_hash: str
    backup_verification_hash: str
    dry_run_result_store_roundtrip_hash: str
    restore_drill_passed: bool = True
    result_store_restored: bool = True
    tenant_isolation_reverified: bool = True
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL import write restore-drill text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def require_crm_erp_module(cls, value: str) -> str:
        if value != CRM_ERP_MODULE_ID:
            raise ValueError("legacy SQL import write restore-drill only applies to module crm_erp")
        return value

    @field_validator("source_system_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL import write restore-drill references must be namespaced")
        return value

    @field_validator(
        "dry_run_plan_hash",
        "dry_run_result_hash",
        "dry_run_worker_report_hash",
        "restore_drill_report_hash",
        "backup_verification_hash",
        "dry_run_result_store_roundtrip_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL import write restore-drill hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_safe_restore_drill(self) -> Self:
        _assert_approval_gate_safe(self)
        return self


class LegacySqlImportWriteApprovalGateCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = CRM_ERP_MODULE_ID
    source_system_ref: str
    dry_run_plan_hash: str
    dry_run_result_hash: str
    dry_run_worker_report_hash: str
    approval_review_evidence_hash: str
    change_control_evidence_hash: str
    restore_drill_evidence_hash: str
    requested_by: str
    approval_gate_requested: bool = True
    import_write_requested: bool = False
    raw_data_access_requested: bool = False
    destructive_actions_requested: bool = False
    external_side_effect_requested: bool = False

    @field_validator("tenant_id", "requested_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL import write approval gate command text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def require_crm_erp_module(cls, value: str) -> str:
        if value != CRM_ERP_MODULE_ID:
            raise ValueError("legacy SQL import write approval gate command only applies to module crm_erp")
        return value

    @field_validator("source_system_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL import write approval gate command references must be namespaced")
        return value

    @field_validator(
        "dry_run_plan_hash",
        "dry_run_result_hash",
        "dry_run_worker_report_hash",
        "approval_review_evidence_hash",
        "change_control_evidence_hash",
        "restore_drill_evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL import write approval gate command hashes must be sha256 references")
        return value


class LegacySqlImportWriteApprovalGateEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_IMPORT_WRITE_APPROVAL_GATE_SCHEMA_VERSION
    tenant_id: str
    module_id: str = CRM_ERP_MODULE_ID
    source_system_ref: str
    continuity_domain: str = LEGACY_SQL_IMPORT_WRITE_APPROVAL_CONTINUITY_DOMAIN
    command_ref: str = LEGACY_SQL_IMPORT_WRITE_APPROVAL_GATE_COMMAND_REF
    dry_run_plan_hash: str
    dry_run_result_hash: str
    dry_run_worker_report_hash: str
    approval_review_evidence_hash: str
    change_control_evidence_hash: str
    restore_drill_evidence_hash: str
    dry_run_result_hash_valid: bool
    dry_run_result_completed: bool
    dry_run_worker_report_hash_valid: bool
    dry_run_worker_report_bound: bool
    dry_run_worker_passed: bool
    approval_review_hash_valid: bool
    approval_review_bound: bool
    human_review_completed: bool
    reviewer_independent: bool
    reviewer_mfa_verified: bool
    break_glass_requested: bool
    change_control_hash_valid: bool
    change_control_bound: bool
    change_approved: bool
    maintenance_window_active: bool
    rollback_plan_verified: bool
    risk_acceptance_signed: bool
    restore_drill_hash_valid: bool
    restore_drill_bound: bool
    restore_drill_passed: bool
    result_store_restored: bool
    tenant_isolation_reverified: bool
    approval_gate_requested: bool
    future_import_write_execution_gate_required: bool = True
    human_approval_record_allowed: bool
    import_write_execution_allowed: bool = False
    raw_data_access_requested: bool = False
    raw_data_access_allowed: bool = False
    import_write_requested: bool = False
    import_write_payload_allowed: bool = False
    destructive_actions_requested: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_requested: bool = False
    external_side_effect_allowed: bool = False
    gate_status: LegacySqlImportWriteApprovalGateStatus
    blocking_reasons: tuple[str, ...]
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL import write approval gate evidence text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def require_crm_erp_module(cls, value: str) -> str:
        if value != CRM_ERP_MODULE_ID:
            raise ValueError("legacy SQL import write approval gate evidence only applies to module crm_erp")
        return value

    @field_validator("source_system_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL import write approval gate evidence references must be namespaced")
        return value

    @field_validator(
        "dry_run_plan_hash",
        "dry_run_result_hash",
        "dry_run_worker_report_hash",
        "approval_review_evidence_hash",
        "change_control_evidence_hash",
        "restore_drill_evidence_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL import write approval gate evidence hashes must be sha256 references")
        return value

    @field_validator("blocking_reasons")
    @classmethod
    def validate_blocking_reasons(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("legacy SQL import write approval gate blocking reasons must be unique")
        for reason in value:
            if not reason.strip():
                raise ValueError("legacy SQL import write approval gate blocking reasons must not be empty")
        return value

    @model_validator(mode="after")
    def require_safe_gate(self) -> Self:
        if (
            self.import_write_execution_allowed
            or self.raw_data_access_allowed
            or self.import_write_payload_allowed
            or self.destructive_actions_allowed
            or self.external_side_effect_allowed
        ):
            raise ValueError("legacy SQL import write approval gate must not allow execution or side effects")
        if not self.future_import_write_execution_gate_required:
            raise ValueError("legacy SQL import write approval gate must require a future execution gate")
        if self.gate_status == LegacySqlImportWriteApprovalGateStatus.READY_FOR_HUMAN_APPROVAL_RECORD:
            required = (
                self.dry_run_result_hash_valid,
                self.dry_run_result_completed,
                self.dry_run_worker_report_hash_valid,
                self.dry_run_worker_report_bound,
                self.dry_run_worker_passed,
                self.approval_review_hash_valid,
                self.approval_review_bound,
                self.human_review_completed,
                self.reviewer_independent,
                self.reviewer_mfa_verified,
                not self.break_glass_requested,
                self.change_control_hash_valid,
                self.change_control_bound,
                self.change_approved,
                self.maintenance_window_active,
                self.rollback_plan_verified,
                self.risk_acceptance_signed,
                self.restore_drill_hash_valid,
                self.restore_drill_bound,
                self.restore_drill_passed,
                self.result_store_restored,
                self.tenant_isolation_reverified,
                self.approval_gate_requested,
                self.human_approval_record_allowed,
                not self.raw_data_access_requested,
                not self.import_write_requested,
                not self.destructive_actions_requested,
                not self.external_side_effect_requested,
            )
            if not all(required) or self.blocking_reasons:
                raise ValueError("ready legacy SQL import write approval gate requires complete evidence")
        if self.gate_status == LegacySqlImportWriteApprovalGateStatus.BLOCKED:
            if not self.blocking_reasons:
                raise ValueError("blocked legacy SQL import write approval gate requires blocking reasons")
            if self.human_approval_record_allowed:
                raise ValueError("blocked legacy SQL import write approval gate cannot allow approval record")
        _assert_approval_gate_safe(self)
        return self


class LegacySqlImportWriteApprovalRequestCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_system_ref: str
    dry_run_result_hash: str
    approval_gate_evidence_hash: str
    approval_reference: str
    approval_ticket_ref: str
    human_confirmation_reference: str
    reason: str
    approval_request_requested: bool = True
    approval_record_persistence_requested: bool = False
    import_write_requested: bool = False
    raw_data_access_requested: bool = False
    import_write_payload_requested: bool = False
    destructive_actions_requested: bool = False
    external_side_effect_requested: bool = False

    @field_validator("source_system_ref", "approval_reference", "approval_ticket_ref", "human_confirmation_reference")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL import write approval request references must be namespaced")
        return value

    @field_validator("dry_run_result_hash", "approval_gate_evidence_hash")
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL import write approval request hashes must be sha256 references")
        return value

    @field_validator("reason")
    @classmethod
    def require_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL import write approval request reason must not be empty")
        return value

    @model_validator(mode="after")
    def require_safe_request(self) -> Self:
        _assert_approval_gate_safe(self)
        return self


class LegacySqlImportWriteApprovalRequestBoundaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_IMPORT_WRITE_APPROVAL_REQUEST_BOUNDARY_SCHEMA_VERSION
    tenant_id: str
    module_id: str = CRM_ERP_MODULE_ID
    source_system_ref: str
    continuity_domain: str = LEGACY_SQL_IMPORT_WRITE_APPROVAL_CONTINUITY_DOMAIN
    command_ref: str = LEGACY_SQL_IMPORT_WRITE_APPROVAL_REQUEST_BOUNDARY_COMMAND_REF
    dry_run_result_hash: str
    approval_gate_evidence_hash: str
    approval_request_hash: str
    approval_reference: str
    approval_ticket_ref: str
    human_confirmation_reference: str
    approval_gate_hash_valid: bool
    approval_gate_bound: bool
    approval_gate_ready_for_human_record: bool
    human_approval_record_allowed_by_gate: bool
    approval_request_requested: bool
    approval_request_accepted: bool
    approval_record_persistence_requested: bool
    approval_record_persistence_allowed: bool = False
    approval_record_persisted: bool = False
    future_import_write_execution_gate_required: bool = True
    import_write_requested: bool = False
    import_write_execution_allowed: bool = False
    raw_data_access_requested: bool = False
    raw_data_access_allowed: bool = False
    import_write_payload_requested: bool = False
    import_write_payload_allowed: bool = False
    destructive_actions_requested: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_requested: bool = False
    external_side_effect_allowed: bool = False
    required_evidence: tuple[str, ...] = REQUIRED_IMPORT_WRITE_APPROVAL_REQUEST_EVIDENCE
    boundary_status: LegacySqlImportWriteApprovalRequestBoundaryStatus
    blocking_reasons: tuple[str, ...]
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL import write approval request boundary text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def require_crm_erp_module(cls, value: str) -> str:
        if value != CRM_ERP_MODULE_ID:
            raise ValueError("legacy SQL import write approval request boundary only applies to module crm_erp")
        return value

    @field_validator("source_system_ref", "approval_reference", "approval_ticket_ref", "human_confirmation_reference")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL import write approval request boundary references must be namespaced")
        return value

    @field_validator("dry_run_result_hash", "approval_gate_evidence_hash", "approval_request_hash", "evidence_hash")
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL import write approval request boundary hashes must be sha256 references")
        return value

    @field_validator("required_evidence", "blocking_reasons")
    @classmethod
    def validate_unique_non_empty_items(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("legacy SQL import write approval request boundary lists must be unique")
        for item in value:
            if not item.strip():
                raise ValueError("legacy SQL import write approval request boundary lists must not contain empty items")
        return value

    @model_validator(mode="after")
    def require_safe_boundary(self) -> Self:
        if (
            self.approval_record_persistence_allowed
            or self.approval_record_persisted
            or self.import_write_execution_allowed
            or self.raw_data_access_allowed
            or self.import_write_payload_allowed
            or self.destructive_actions_allowed
            or self.external_side_effect_allowed
        ):
            raise ValueError("legacy SQL import write approval request boundary must remain non-executing")
        if not self.future_import_write_execution_gate_required:
            raise ValueError("legacy SQL import write approval request boundary must require a future execution gate")
        if self.boundary_status == LegacySqlImportWriteApprovalRequestBoundaryStatus.READY_FOR_APPROVAL_RECORD_REQUEST:
            required = (
                self.approval_gate_hash_valid,
                self.approval_gate_bound,
                self.approval_gate_ready_for_human_record,
                self.human_approval_record_allowed_by_gate,
                self.approval_request_requested,
                self.approval_request_accepted,
                not self.approval_record_persistence_requested,
                not self.raw_data_access_requested,
                not self.import_write_requested,
                not self.import_write_payload_requested,
                not self.destructive_actions_requested,
                not self.external_side_effect_requested,
            )
            if not all(required) or self.blocking_reasons:
                raise ValueError("ready legacy SQL import write approval request boundary requires complete evidence")
        if self.boundary_status == LegacySqlImportWriteApprovalRequestBoundaryStatus.BLOCKED:
            if not self.blocking_reasons:
                raise ValueError("blocked legacy SQL import write approval request boundary requires blocking reasons")
            if self.approval_request_accepted:
                raise ValueError("blocked legacy SQL import write approval request boundary cannot accept request")
        _assert_approval_gate_safe(self)
        return self


class LegacySqlImportWriteApprovalRecordPersistencePlanCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_request_boundary_evidence_hash: str
    approval_record_store_ref: str
    approval_record_schema_ref: str
    approval_record_retention_policy_ref: str
    approval_record_legal_hold_policy_ref: str
    idempotency_key_ref: str
    operator_mfa_ref: str
    change_control_ref: str
    reason: str
    approval_record_persistence_planning_requested: bool = True
    approval_record_persistence_requested: bool = False
    import_write_requested: bool = False
    raw_data_access_requested: bool = False
    import_write_payload_requested: bool = False
    destructive_actions_requested: bool = False
    external_side_effect_requested: bool = False

    @field_validator("approval_request_boundary_evidence_hash")
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError(
                "legacy SQL import write approval record persistence plan hashes must be sha256 references"
            )
        return value

    @field_validator(
        "approval_record_store_ref",
        "approval_record_schema_ref",
        "approval_record_retention_policy_ref",
        "approval_record_legal_hold_policy_ref",
        "idempotency_key_ref",
        "operator_mfa_ref",
        "change_control_ref",
    )
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL import write approval record persistence plan references must be namespaced")
        return value

    @field_validator("reason")
    @classmethod
    def require_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL import write approval record persistence plan reason must not be empty")
        return value

    @model_validator(mode="after")
    def require_safe_plan_command(self) -> Self:
        _assert_approval_gate_safe(self)
        return self


class LegacySqlImportWriteApprovalRecordPersistencePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_IMPORT_WRITE_APPROVAL_RECORD_PERSISTENCE_PLAN_SCHEMA_VERSION
    tenant_id: str
    module_id: str = CRM_ERP_MODULE_ID
    source_system_ref: str
    continuity_domain: str = LEGACY_SQL_IMPORT_WRITE_APPROVAL_CONTINUITY_DOMAIN
    command_ref: str = LEGACY_SQL_IMPORT_WRITE_APPROVAL_RECORD_PERSISTENCE_PLAN_COMMAND_REF
    approval_request_boundary_evidence_hash: str
    approval_gate_evidence_hash: str
    approval_request_hash: str
    persistence_plan_command_hash: str
    approval_record_store_ref: str
    approval_record_schema_ref: str
    approval_record_retention_policy_ref: str
    approval_record_legal_hold_policy_ref: str
    idempotency_key_ref: str
    operator_mfa_ref: str
    change_control_ref: str
    approval_request_boundary_hash_valid: bool
    approval_request_boundary_bound: bool
    approval_request_boundary_ready: bool
    approval_gate_hash_valid: bool
    approval_gate_ready_for_human_record: bool
    human_approval_record_allowed_by_boundary: bool
    approval_record_store_required: bool = True
    tenant_scoped_rls_required: bool = True
    append_only_store_required: bool = True
    idempotency_required: bool = True
    restore_evidence_required: bool = True
    approval_record_persistence_planning_requested: bool
    approval_record_persistence_plan_accepted: bool
    approval_record_persistence_requested: bool
    approval_record_persistence_allowed: bool = False
    approval_record_persisted: bool = False
    future_import_write_execution_gate_required: bool = True
    import_write_requested: bool = False
    import_write_execution_allowed: bool = False
    raw_data_access_requested: bool = False
    raw_data_access_allowed: bool = False
    import_write_payload_requested: bool = False
    import_write_payload_allowed: bool = False
    destructive_actions_requested: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_requested: bool = False
    external_side_effect_allowed: bool = False
    required_evidence: tuple[str, ...] = REQUIRED_IMPORT_WRITE_APPROVAL_RECORD_PERSISTENCE_PLAN_EVIDENCE
    plan_status: LegacySqlImportWriteApprovalRecordPersistencePlanStatus
    blocking_reasons: tuple[str, ...]
    planned_by: str
    planned_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "planned_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL import write approval record persistence plan text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def require_crm_erp_module(cls, value: str) -> str:
        if value != CRM_ERP_MODULE_ID:
            raise ValueError("legacy SQL import write approval record persistence plan only applies to module crm_erp")
        return value

    @field_validator(
        "source_system_ref",
        "approval_record_store_ref",
        "approval_record_schema_ref",
        "approval_record_retention_policy_ref",
        "approval_record_legal_hold_policy_ref",
        "idempotency_key_ref",
        "operator_mfa_ref",
        "change_control_ref",
    )
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL import write approval record persistence plan references must be namespaced")
        return value

    @field_validator(
        "approval_request_boundary_evidence_hash",
        "approval_gate_evidence_hash",
        "approval_request_hash",
        "persistence_plan_command_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError(
                "legacy SQL import write approval record persistence plan hashes must be sha256 references"
            )
        return value

    @field_validator("required_evidence", "blocking_reasons")
    @classmethod
    def validate_unique_non_empty_items(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("legacy SQL import write approval record persistence plan lists must be unique")
        for item in value:
            if not item.strip():
                raise ValueError(
                    "legacy SQL import write approval record persistence plan lists must not contain empty items"
                )
        return value

    @model_validator(mode="after")
    def require_safe_plan(self) -> Self:
        if (
            self.approval_record_persistence_allowed
            or self.approval_record_persisted
            or self.import_write_execution_allowed
            or self.raw_data_access_allowed
            or self.import_write_payload_allowed
            or self.destructive_actions_allowed
            or self.external_side_effect_allowed
        ):
            raise ValueError("legacy SQL import write approval record persistence plan must remain non-executing")
        if not self.future_import_write_execution_gate_required:
            raise ValueError(
                "legacy SQL import write approval record persistence plan must require a future execution gate"
            )
        if self.plan_status == LegacySqlImportWriteApprovalRecordPersistencePlanStatus.READY_FOR_STORE_IMPLEMENTATION:
            required = (
                self.approval_request_boundary_hash_valid,
                self.approval_request_boundary_bound,
                self.approval_request_boundary_ready,
                self.approval_gate_hash_valid,
                self.approval_gate_ready_for_human_record,
                self.human_approval_record_allowed_by_boundary,
                self.approval_record_store_required,
                self.tenant_scoped_rls_required,
                self.append_only_store_required,
                self.idempotency_required,
                self.restore_evidence_required,
                self.approval_record_persistence_planning_requested,
                self.approval_record_persistence_plan_accepted,
                not self.approval_record_persistence_requested,
                not self.raw_data_access_requested,
                not self.import_write_requested,
                not self.import_write_payload_requested,
                not self.destructive_actions_requested,
                not self.external_side_effect_requested,
            )
            if not all(required) or self.blocking_reasons:
                raise ValueError(
                    "ready legacy SQL import write approval record persistence plan requires complete evidence"
                )
        if self.plan_status == LegacySqlImportWriteApprovalRecordPersistencePlanStatus.BLOCKED:
            if not self.blocking_reasons:
                raise ValueError("blocked legacy SQL import write approval record persistence plan requires blockers")
            if self.approval_record_persistence_plan_accepted:
                raise ValueError("blocked legacy SQL import write approval record persistence plan cannot be accepted")
        _assert_approval_gate_safe(self)
        return self


class LegacySqlImportWriteApprovalGateSmokeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_IMPORT_WRITE_APPROVAL_GATE_SMOKE_SCHEMA_VERSION
    run_id: str
    checked_by: str
    checked_at_utc: datetime
    tenant_id: str
    module_id: str
    source_system_ref: str
    continuity_domain: str = LEGACY_SQL_IMPORT_WRITE_APPROVAL_CONTINUITY_DOMAIN
    command_ref: str = LEGACY_SQL_IMPORT_WRITE_APPROVAL_GATE_COMMAND_REF
    dry_run_result_hash: str
    dry_run_worker_report_hash: str
    approval_review_evidence_hash: str
    change_control_evidence_hash: str
    restore_drill_evidence_hash: str
    approval_gate_evidence_hash: str
    approval_gate_ready_for_human_record: bool
    human_approval_record_allowed: bool
    future_import_write_execution_gate_required: bool
    missing_human_review_blocked: bool
    rollback_plan_missing_blocked: bool
    restore_drill_missing_blocked: bool
    import_write_request_blocked: bool
    tampered_dry_run_result_blocked: bool
    gate_store_write_enabled: bool
    gate_store_backend: LegacySqlImportWriteApprovalGateStoreBackend | None
    import_write_execution_allowed: bool = False
    raw_data_access_allowed: bool = False
    import_write_payload_allowed: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False
    smoke_passed: bool
    evidence_hash: str

    @model_validator(mode="after")
    def require_safe_smoke_report(self) -> Self:
        if (
            self.import_write_execution_allowed
            or self.raw_data_access_allowed
            or self.import_write_payload_allowed
            or self.destructive_actions_allowed
            or self.external_side_effect_allowed
        ):
            raise ValueError("legacy SQL import write approval gate smoke must remain non-executing")
        _assert_approval_gate_safe(self)
        return self


class LegacySqlImportWriteApprovalGateStore(Protocol):
    def append(self, evidence: LegacySqlImportWriteApprovalGateEvidence) -> LegacySqlImportWriteApprovalGateEvidence:
        raise NotImplementedError

    def get(self, *, tenant_id: str, evidence_hash: str) -> LegacySqlImportWriteApprovalGateEvidence:
        raise NotImplementedError

    def list_gates(self, *, tenant_id: str) -> tuple[LegacySqlImportWriteApprovalGateEvidence, ...]:
        raise NotImplementedError


class InMemoryLegacySqlImportWriteApprovalGateStore:
    def __init__(self, gates: Sequence[LegacySqlImportWriteApprovalGateEvidence] = ()) -> None:
        self._gates: dict[tuple[str, str], LegacySqlImportWriteApprovalGateEvidence] = {}
        for gate in gates:
            self.append(gate)

    def append(self, evidence: LegacySqlImportWriteApprovalGateEvidence) -> LegacySqlImportWriteApprovalGateEvidence:
        _require_valid_gate_hash(evidence)
        key = (evidence.tenant_id, evidence.evidence_hash)
        if key in self._gates:
            raise ValueError("legacy SQL import write approval gate evidence already exists")
        self._gates[key] = evidence
        return evidence

    def get(self, *, tenant_id: str, evidence_hash: str) -> LegacySqlImportWriteApprovalGateEvidence:
        try:
            return self._gates[(tenant_id, evidence_hash)]
        except KeyError as exc:
            raise KeyError("legacy SQL import write approval gate evidence not found") from exc

    def list_gates(self, *, tenant_id: str) -> tuple[LegacySqlImportWriteApprovalGateEvidence, ...]:
        return tuple(gate for (stored_tenant_id, _), gate in self._gates.items() if stored_tenant_id == tenant_id)


class JsonlLegacySqlImportWriteApprovalGateStore:
    def __init__(self, *, path: Path) -> None:
        self.path = path
        self._gates: dict[tuple[str, str], LegacySqlImportWriteApprovalGateEvidence] = {}
        if not path.exists():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            gate = LegacySqlImportWriteApprovalGateEvidence.model_validate_json(line)
            _require_valid_gate_hash(gate)
            key = (gate.tenant_id, gate.evidence_hash)
            if key in self._gates:
                raise ValueError("duplicate legacy SQL import write approval gate evidence in store")
            self._gates[key] = gate

    def append(self, evidence: LegacySqlImportWriteApprovalGateEvidence) -> LegacySqlImportWriteApprovalGateEvidence:
        _require_valid_gate_hash(evidence)
        key = (evidence.tenant_id, evidence.evidence_hash)
        if key in self._gates:
            raise ValueError("legacy SQL import write approval gate evidence already exists")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(evidence.model_dump(mode="json"), sort_keys=True) + "\n")
        self._gates[key] = evidence
        return evidence

    def get(self, *, tenant_id: str, evidence_hash: str) -> LegacySqlImportWriteApprovalGateEvidence:
        try:
            return self._gates[(tenant_id, evidence_hash)]
        except KeyError as exc:
            raise KeyError("legacy SQL import write approval gate evidence not found") from exc

    def list_gates(self, *, tenant_id: str) -> tuple[LegacySqlImportWriteApprovalGateEvidence, ...]:
        return tuple(gate for (stored_tenant_id, _), gate in self._gates.items() if stored_tenant_id == tenant_id)


class PgLegacySqlImportWriteApprovalGateStore:
    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    def append(self, evidence: LegacySqlImportWriteApprovalGateEvidence) -> LegacySqlImportWriteApprovalGateEvidence:
        _require_valid_gate_hash(evidence)
        try:
            with psycopg.connect(self.database_dsn) as connection:
                self._set_tenant(connection, evidence.tenant_id)
                connection.execute(
                    """
                    INSERT INTO crm_erp_legacy.import_write_approval_gates (
                        tenant_id,
                        module_id,
                        source_system_ref,
                        dry_run_plan_hash,
                        dry_run_result_hash,
                        dry_run_worker_report_hash,
                        approval_review_evidence_hash,
                        change_control_evidence_hash,
                        restore_drill_evidence_hash,
                        gate_status,
                        human_approval_record_allowed,
                        future_import_write_execution_gate_required,
                        import_write_execution_allowed,
                        raw_data_access_allowed,
                        import_write_payload_allowed,
                        destructive_actions_allowed,
                        external_side_effect_allowed,
                        blocking_reasons,
                        checked_by,
                        checked_at_utc,
                        gate_evidence,
                        evidence_hash,
                        schema_version
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s
                    )
                    """,
                    self._gate_values(evidence),
                )
                connection.commit()
        except psycopg.errors.UniqueViolation as exc:
            raise ValueError("legacy SQL import write approval gate evidence already exists") from exc
        return evidence

    def get(self, *, tenant_id: str, evidence_hash: str) -> LegacySqlImportWriteApprovalGateEvidence:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            row = connection.execute(
                """
                SELECT gate_evidence
                FROM crm_erp_legacy.import_write_approval_gates
                WHERE tenant_id = %s
                  AND evidence_hash = %s
                """,
                (tenant_id, evidence_hash),
            ).fetchone()
        if row is None:
            raise KeyError("legacy SQL import write approval gate evidence not found")
        return self._gate_from_row(row)

    def list_gates(self, *, tenant_id: str) -> tuple[LegacySqlImportWriteApprovalGateEvidence, ...]:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            rows = connection.execute(
                """
                SELECT gate_evidence
                FROM crm_erp_legacy.import_write_approval_gates
                WHERE tenant_id = %s
                ORDER BY checked_at_utc, evidence_hash
                """,
                (tenant_id,),
            ).fetchall()
        return tuple(self._gate_from_row(row) for row in rows)

    def _gate_values(self, evidence: LegacySqlImportWriteApprovalGateEvidence) -> tuple[object, ...]:
        return (
            evidence.tenant_id,
            evidence.module_id,
            evidence.source_system_ref,
            evidence.dry_run_plan_hash,
            evidence.dry_run_result_hash,
            evidence.dry_run_worker_report_hash,
            evidence.approval_review_evidence_hash,
            evidence.change_control_evidence_hash,
            evidence.restore_drill_evidence_hash,
            evidence.gate_status.value,
            evidence.human_approval_record_allowed,
            evidence.future_import_write_execution_gate_required,
            evidence.import_write_execution_allowed,
            evidence.raw_data_access_allowed,
            evidence.import_write_payload_allowed,
            evidence.destructive_actions_allowed,
            evidence.external_side_effect_allowed,
            Jsonb(list(evidence.blocking_reasons)),
            evidence.checked_by,
            evidence.checked_at_utc,
            Jsonb(evidence.model_dump(mode="json")),
            evidence.evidence_hash,
            evidence.schema_version,
        )

    def _gate_from_row(self, row: tuple[Any, ...]) -> LegacySqlImportWriteApprovalGateEvidence:
        raw = row[0]
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        evidence = LegacySqlImportWriteApprovalGateEvidence.model_validate(parsed)
        _require_valid_gate_hash(evidence)
        return evidence

    def _set_tenant(self, connection: psycopg.Connection[Any], tenant_id: str) -> None:
        connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))


def build_legacy_sql_import_write_approval_review(
    *,
    dry_run_result: LegacySqlImportDryRunResult,
    dry_run_worker_report: LegacySqlImportDryRunWorkerReport,
    reviewer_principal_ref: str,
    review_ticket_ref: str,
    approval_reference: str,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    human_review_completed: bool = True,
    reviewer_independent: bool = True,
    reviewer_mfa_verified: bool = True,
    break_glass_requested: bool = False,
) -> LegacySqlImportWriteApprovalReview:
    checked_at = checked_at_utc or datetime.now(UTC)
    draft = LegacySqlImportWriteApprovalReview(
        tenant_id=dry_run_result.tenant_id,
        module_id=dry_run_result.module_id,
        source_system_ref=dry_run_result.source_system_ref,
        dry_run_plan_hash=dry_run_result.dry_run_plan_hash,
        dry_run_result_hash=dry_run_result.result_hash,
        dry_run_worker_report_hash=dry_run_worker_report.evidence_hash,
        reviewer_principal_ref=reviewer_principal_ref,
        review_ticket_ref=review_ticket_ref,
        approval_reference=approval_reference,
        human_review_completed=human_review_completed,
        reviewer_independent=reviewer_independent,
        reviewer_mfa_verified=reviewer_mfa_verified,
        break_glass_requested=break_glass_requested,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_import_write_approval_review_hash(draft)})


def build_legacy_sql_import_write_change_control(
    *,
    dry_run_result: LegacySqlImportDryRunResult,
    dry_run_worker_report: LegacySqlImportDryRunWorkerReport,
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
) -> LegacySqlImportWriteChangeControl:
    checked_at = checked_at_utc or datetime.now(UTC)
    draft = LegacySqlImportWriteChangeControl(
        tenant_id=dry_run_result.tenant_id,
        module_id=dry_run_result.module_id,
        source_system_ref=dry_run_result.source_system_ref,
        dry_run_plan_hash=dry_run_result.dry_run_plan_hash,
        dry_run_result_hash=dry_run_result.result_hash,
        dry_run_worker_report_hash=dry_run_worker_report.evidence_hash,
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
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_import_write_change_control_hash(draft)})


def build_legacy_sql_import_write_restore_drill(
    *,
    dry_run_result: LegacySqlImportDryRunResult,
    dry_run_worker_report: LegacySqlImportDryRunWorkerReport,
    restore_drill_report_hash: str,
    backup_verification_hash: str,
    dry_run_result_store_roundtrip_hash: str,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    restore_drill_passed: bool = True,
    result_store_restored: bool = True,
    tenant_isolation_reverified: bool = True,
) -> LegacySqlImportWriteRestoreDrill:
    checked_at = checked_at_utc or datetime.now(UTC)
    draft = LegacySqlImportWriteRestoreDrill(
        tenant_id=dry_run_result.tenant_id,
        module_id=dry_run_result.module_id,
        source_system_ref=dry_run_result.source_system_ref,
        dry_run_plan_hash=dry_run_result.dry_run_plan_hash,
        dry_run_result_hash=dry_run_result.result_hash,
        dry_run_worker_report_hash=dry_run_worker_report.evidence_hash,
        restore_drill_report_hash=restore_drill_report_hash,
        backup_verification_hash=backup_verification_hash,
        dry_run_result_store_roundtrip_hash=dry_run_result_store_roundtrip_hash,
        restore_drill_passed=restore_drill_passed,
        result_store_restored=result_store_restored,
        tenant_isolation_reverified=tenant_isolation_reverified,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_import_write_restore_drill_hash(draft)})


def build_legacy_sql_import_write_approval_gate_command(
    *,
    dry_run_result: LegacySqlImportDryRunResult,
    dry_run_worker_report: LegacySqlImportDryRunWorkerReport,
    approval_review: LegacySqlImportWriteApprovalReview,
    change_control: LegacySqlImportWriteChangeControl,
    restore_drill: LegacySqlImportWriteRestoreDrill,
    requested_by: str,
    approval_gate_requested: bool = True,
    import_write_requested: bool = False,
    raw_data_access_requested: bool = False,
    destructive_actions_requested: bool = False,
    external_side_effect_requested: bool = False,
) -> LegacySqlImportWriteApprovalGateCommand:
    return LegacySqlImportWriteApprovalGateCommand(
        tenant_id=dry_run_result.tenant_id,
        module_id=dry_run_result.module_id,
        source_system_ref=dry_run_result.source_system_ref,
        dry_run_plan_hash=dry_run_result.dry_run_plan_hash,
        dry_run_result_hash=dry_run_result.result_hash,
        dry_run_worker_report_hash=dry_run_worker_report.evidence_hash,
        approval_review_evidence_hash=approval_review.evidence_hash,
        change_control_evidence_hash=change_control.evidence_hash,
        restore_drill_evidence_hash=restore_drill.evidence_hash,
        requested_by=requested_by,
        approval_gate_requested=approval_gate_requested,
        import_write_requested=import_write_requested,
        raw_data_access_requested=raw_data_access_requested,
        destructive_actions_requested=destructive_actions_requested,
        external_side_effect_requested=external_side_effect_requested,
    )


def build_legacy_sql_import_write_approval_gate(
    *,
    command: LegacySqlImportWriteApprovalGateCommand,
    dry_run_result: LegacySqlImportDryRunResult,
    dry_run_worker_report: LegacySqlImportDryRunWorkerReport,
    approval_review: LegacySqlImportWriteApprovalReview,
    change_control: LegacySqlImportWriteChangeControl,
    restore_drill: LegacySqlImportWriteRestoreDrill,
    checked_by: str,
    checked_at_utc: datetime | None = None,
) -> LegacySqlImportWriteApprovalGateEvidence:
    checked_at = checked_at_utc or datetime.now(UTC)
    dry_run_result_hash_valid = (
        build_legacy_sql_import_dry_run_result_hash(dry_run_result)
        == dry_run_result.result_hash
        == command.dry_run_result_hash
    )
    dry_run_result_completed = (
        dry_run_result.status == LegacySqlImportDryRunResultStatus.COMPLETED_METADATA_ONLY
        and dry_run_result.dry_run_execution_completed
        and dry_run_result.table_result_count == dry_run_result.expected_table_count
    )
    dry_run_worker_report_hash_valid = (
        build_legacy_sql_import_dry_run_worker_report_hash(dry_run_worker_report)
        == dry_run_worker_report.evidence_hash
        == command.dry_run_worker_report_hash
    )
    dry_run_worker_report_bound = _dry_run_worker_report_bound(
        command=command,
        dry_run_result=dry_run_result,
        dry_run_worker_report=dry_run_worker_report,
    )
    approval_review_hash_valid = (
        build_legacy_sql_import_write_approval_review_hash(approval_review)
        == approval_review.evidence_hash
        == command.approval_review_evidence_hash
    )
    approval_review_bound = _approval_artifact_bound(command=command, artifact=approval_review)
    change_control_hash_valid = (
        build_legacy_sql_import_write_change_control_hash(change_control)
        == change_control.evidence_hash
        == command.change_control_evidence_hash
    )
    change_control_bound = _approval_artifact_bound(command=command, artifact=change_control)
    restore_drill_hash_valid = (
        build_legacy_sql_import_write_restore_drill_hash(restore_drill)
        == restore_drill.evidence_hash
        == command.restore_drill_evidence_hash
    )
    restore_drill_bound = _approval_artifact_bound(command=command, artifact=restore_drill)
    blocking_reasons = _approval_gate_blocking_reasons(
        command=command,
        dry_run_result_hash_valid=dry_run_result_hash_valid,
        dry_run_result_completed=dry_run_result_completed,
        dry_run_worker_report_hash_valid=dry_run_worker_report_hash_valid,
        dry_run_worker_report_bound=dry_run_worker_report_bound,
        dry_run_worker_report=dry_run_worker_report,
        approval_review_hash_valid=approval_review_hash_valid,
        approval_review_bound=approval_review_bound,
        approval_review=approval_review,
        change_control_hash_valid=change_control_hash_valid,
        change_control_bound=change_control_bound,
        change_control=change_control,
        restore_drill_hash_valid=restore_drill_hash_valid,
        restore_drill_bound=restore_drill_bound,
        restore_drill=restore_drill,
    )
    ready = not blocking_reasons
    draft = LegacySqlImportWriteApprovalGateEvidence(
        tenant_id=dry_run_result.tenant_id,
        module_id=dry_run_result.module_id,
        source_system_ref=dry_run_result.source_system_ref,
        dry_run_plan_hash=dry_run_result.dry_run_plan_hash,
        dry_run_result_hash=dry_run_result.result_hash,
        dry_run_worker_report_hash=dry_run_worker_report.evidence_hash,
        approval_review_evidence_hash=approval_review.evidence_hash,
        change_control_evidence_hash=change_control.evidence_hash,
        restore_drill_evidence_hash=restore_drill.evidence_hash,
        dry_run_result_hash_valid=dry_run_result_hash_valid,
        dry_run_result_completed=dry_run_result_completed,
        dry_run_worker_report_hash_valid=dry_run_worker_report_hash_valid,
        dry_run_worker_report_bound=dry_run_worker_report_bound,
        dry_run_worker_passed=dry_run_worker_report.worker_passed,
        approval_review_hash_valid=approval_review_hash_valid,
        approval_review_bound=approval_review_bound,
        human_review_completed=approval_review.human_review_completed,
        reviewer_independent=approval_review.reviewer_independent,
        reviewer_mfa_verified=approval_review.reviewer_mfa_verified,
        break_glass_requested=approval_review.break_glass_requested,
        change_control_hash_valid=change_control_hash_valid,
        change_control_bound=change_control_bound,
        change_approved=change_control.change_approved,
        maintenance_window_active=change_control.maintenance_window_active,
        rollback_plan_verified=change_control.rollback_plan_verified,
        risk_acceptance_signed=change_control.risk_acceptance_signed,
        restore_drill_hash_valid=restore_drill_hash_valid,
        restore_drill_bound=restore_drill_bound,
        restore_drill_passed=restore_drill.restore_drill_passed,
        result_store_restored=restore_drill.result_store_restored,
        tenant_isolation_reverified=restore_drill.tenant_isolation_reverified,
        approval_gate_requested=command.approval_gate_requested,
        human_approval_record_allowed=ready,
        raw_data_access_requested=command.raw_data_access_requested,
        import_write_requested=command.import_write_requested,
        destructive_actions_requested=command.destructive_actions_requested,
        external_side_effect_requested=command.external_side_effect_requested,
        gate_status=(
            LegacySqlImportWriteApprovalGateStatus.READY_FOR_HUMAN_APPROVAL_RECORD
            if ready
            else LegacySqlImportWriteApprovalGateStatus.BLOCKED
        ),
        blocking_reasons=blocking_reasons,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_import_write_approval_gate_hash(draft)})


def build_legacy_sql_import_write_approval_review_hash(
    review: LegacySqlImportWriteApprovalReview,
) -> str:
    return stable_hash(canonical_json(review.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_import_write_change_control_hash(
    change_control: LegacySqlImportWriteChangeControl,
) -> str:
    return stable_hash(canonical_json(change_control.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_import_write_restore_drill_hash(
    restore_drill: LegacySqlImportWriteRestoreDrill,
) -> str:
    return stable_hash(canonical_json(restore_drill.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_import_write_approval_gate_hash(
    evidence: LegacySqlImportWriteApprovalGateEvidence,
) -> str:
    return stable_hash(canonical_json(evidence.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_import_write_approval_gate_smoke_report_hash(
    report: LegacySqlImportWriteApprovalGateSmokeReport,
) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_import_write_approval_request_hash(
    command: LegacySqlImportWriteApprovalRequestCommand,
) -> str:
    return stable_hash(canonical_json(command.model_dump(mode="json")))


def build_legacy_sql_import_write_approval_request_boundary_hash(
    response: LegacySqlImportWriteApprovalRequestBoundaryResponse,
) -> str:
    return stable_hash(canonical_json(response.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_import_write_approval_record_persistence_plan_command_hash(
    command: LegacySqlImportWriteApprovalRecordPersistencePlanCommand,
) -> str:
    return stable_hash(canonical_json(command.model_dump(mode="json")))


def build_legacy_sql_import_write_approval_record_persistence_plan_hash(
    plan: LegacySqlImportWriteApprovalRecordPersistencePlan,
) -> str:
    return stable_hash(canonical_json(plan.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_import_write_approval_request_boundary(
    *,
    command: LegacySqlImportWriteApprovalRequestCommand,
    gate_evidence: LegacySqlImportWriteApprovalGateEvidence,
    tenant_id: str,
    checked_by: str,
    checked_at_utc: datetime | None = None,
) -> LegacySqlImportWriteApprovalRequestBoundaryResponse:
    checked_at = checked_at_utc or datetime.now(UTC)
    approval_request_hash = build_legacy_sql_import_write_approval_request_hash(command)
    gate_hash_valid = (
        build_legacy_sql_import_write_approval_gate_hash(gate_evidence)
        == gate_evidence.evidence_hash
        == command.approval_gate_evidence_hash
    )
    gate_bound = _approval_request_gate_bound(
        command=command,
        gate_evidence=gate_evidence,
        tenant_id=tenant_id,
    )
    gate_ready = (
        gate_evidence.gate_status == LegacySqlImportWriteApprovalGateStatus.READY_FOR_HUMAN_APPROVAL_RECORD
        and gate_evidence.human_approval_record_allowed
        and not gate_evidence.import_write_execution_allowed
    )
    blocking_reasons = _approval_request_boundary_blocking_reasons(
        command=command,
        gate_hash_valid=gate_hash_valid,
        gate_bound=gate_bound,
        gate_ready=gate_ready,
        gate_evidence=gate_evidence,
    )
    ready = not blocking_reasons
    draft = LegacySqlImportWriteApprovalRequestBoundaryResponse(
        tenant_id=tenant_id,
        module_id=gate_evidence.module_id,
        source_system_ref=gate_evidence.source_system_ref,
        dry_run_result_hash=gate_evidence.dry_run_result_hash,
        approval_gate_evidence_hash=gate_evidence.evidence_hash,
        approval_request_hash=approval_request_hash,
        approval_reference=command.approval_reference,
        approval_ticket_ref=command.approval_ticket_ref,
        human_confirmation_reference=command.human_confirmation_reference,
        approval_gate_hash_valid=gate_hash_valid,
        approval_gate_bound=gate_bound,
        approval_gate_ready_for_human_record=gate_ready,
        human_approval_record_allowed_by_gate=gate_evidence.human_approval_record_allowed,
        approval_request_requested=command.approval_request_requested,
        approval_request_accepted=ready,
        approval_record_persistence_requested=command.approval_record_persistence_requested,
        import_write_requested=command.import_write_requested,
        raw_data_access_requested=command.raw_data_access_requested,
        import_write_payload_requested=command.import_write_payload_requested,
        destructive_actions_requested=command.destructive_actions_requested,
        external_side_effect_requested=command.external_side_effect_requested,
        boundary_status=(
            LegacySqlImportWriteApprovalRequestBoundaryStatus.READY_FOR_APPROVAL_RECORD_REQUEST
            if ready
            else LegacySqlImportWriteApprovalRequestBoundaryStatus.BLOCKED
        ),
        blocking_reasons=blocking_reasons,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_import_write_approval_request_boundary_hash(draft)}
    )


def build_legacy_sql_import_write_approval_record_persistence_plan(
    *,
    command: LegacySqlImportWriteApprovalRecordPersistencePlanCommand,
    request_boundary: LegacySqlImportWriteApprovalRequestBoundaryResponse,
    gate_evidence: LegacySqlImportWriteApprovalGateEvidence,
    tenant_id: str,
    planned_by: str,
    planned_at_utc: datetime | None = None,
) -> LegacySqlImportWriteApprovalRecordPersistencePlan:
    planned_at = planned_at_utc or datetime.now(UTC)
    command_hash = build_legacy_sql_import_write_approval_record_persistence_plan_command_hash(command)
    boundary_hash_valid = (
        build_legacy_sql_import_write_approval_request_boundary_hash(request_boundary)
        == request_boundary.evidence_hash
        == command.approval_request_boundary_evidence_hash
    )
    gate_hash_valid = (
        build_legacy_sql_import_write_approval_gate_hash(gate_evidence)
        == gate_evidence.evidence_hash
        == request_boundary.approval_gate_evidence_hash
    )
    boundary_bound = _approval_record_persistence_plan_boundary_bound(
        request_boundary=request_boundary,
        gate_evidence=gate_evidence,
        tenant_id=tenant_id,
    )
    boundary_ready = (
        request_boundary.boundary_status
        == LegacySqlImportWriteApprovalRequestBoundaryStatus.READY_FOR_APPROVAL_RECORD_REQUEST
        and request_boundary.approval_request_accepted
        and request_boundary.human_approval_record_allowed_by_gate
        and not request_boundary.approval_record_persistence_allowed
        and not request_boundary.approval_record_persisted
        and not request_boundary.import_write_execution_allowed
    )
    gate_ready = (
        gate_evidence.gate_status == LegacySqlImportWriteApprovalGateStatus.READY_FOR_HUMAN_APPROVAL_RECORD
        and gate_evidence.human_approval_record_allowed
        and not gate_evidence.import_write_execution_allowed
    )
    blocking_reasons = _approval_record_persistence_plan_blocking_reasons(
        command=command,
        request_boundary=request_boundary,
        gate_evidence=gate_evidence,
        boundary_hash_valid=boundary_hash_valid,
        boundary_bound=boundary_bound,
        boundary_ready=boundary_ready,
        gate_hash_valid=gate_hash_valid,
        gate_ready=gate_ready,
    )
    ready = not blocking_reasons
    draft = LegacySqlImportWriteApprovalRecordPersistencePlan(
        tenant_id=tenant_id,
        module_id=request_boundary.module_id,
        source_system_ref=request_boundary.source_system_ref,
        approval_request_boundary_evidence_hash=request_boundary.evidence_hash,
        approval_gate_evidence_hash=request_boundary.approval_gate_evidence_hash,
        approval_request_hash=request_boundary.approval_request_hash,
        persistence_plan_command_hash=command_hash,
        approval_record_store_ref=command.approval_record_store_ref,
        approval_record_schema_ref=command.approval_record_schema_ref,
        approval_record_retention_policy_ref=command.approval_record_retention_policy_ref,
        approval_record_legal_hold_policy_ref=command.approval_record_legal_hold_policy_ref,
        idempotency_key_ref=command.idempotency_key_ref,
        operator_mfa_ref=command.operator_mfa_ref,
        change_control_ref=command.change_control_ref,
        approval_request_boundary_hash_valid=boundary_hash_valid,
        approval_request_boundary_bound=boundary_bound,
        approval_request_boundary_ready=boundary_ready,
        approval_gate_hash_valid=gate_hash_valid,
        approval_gate_ready_for_human_record=gate_ready,
        human_approval_record_allowed_by_boundary=request_boundary.human_approval_record_allowed_by_gate,
        approval_record_persistence_planning_requested=command.approval_record_persistence_planning_requested,
        approval_record_persistence_plan_accepted=ready,
        approval_record_persistence_requested=command.approval_record_persistence_requested,
        import_write_requested=command.import_write_requested,
        raw_data_access_requested=command.raw_data_access_requested,
        import_write_payload_requested=command.import_write_payload_requested,
        destructive_actions_requested=command.destructive_actions_requested,
        external_side_effect_requested=command.external_side_effect_requested,
        plan_status=(
            LegacySqlImportWriteApprovalRecordPersistencePlanStatus.READY_FOR_STORE_IMPLEMENTATION
            if ready
            else LegacySqlImportWriteApprovalRecordPersistencePlanStatus.BLOCKED
        ),
        blocking_reasons=blocking_reasons,
        planned_by=planned_by,
        planned_at_utc=planned_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_import_write_approval_record_persistence_plan_hash(draft)}
    )


def build_default_legacy_sql_import_write_approval_gate_store(
    data_dir: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> LegacySqlImportWriteApprovalGateStore:
    env = os.environ if environ is None else environ
    backend = _gate_store_backend(env)
    if backend == LegacySqlImportWriteApprovalGateStoreBackend.JSONL:
        path_value = env.get("SUITE_LEGACY_SQL_IMPORT_WRITE_APPROVAL_GATE_STORE_PATH")
        path = (
            Path(path_value)
            if path_value
            else (data_dir or suite_data_dir()) / "legacy_sql_import_write_approval_gates.jsonl"
        )
        return JsonlLegacySqlImportWriteApprovalGateStore(path=path)
    if backend == LegacySqlImportWriteApprovalGateStoreBackend.POSTGRES:
        database_dsn = env.get("SUITE_LEGACY_SQL_IMPORT_WRITE_APPROVAL_GATE_STORE_DSN") or env.get("SUITE_DATABASE_DSN")
        if database_dsn is None:
            raise ValueError("Postgres legacy SQL import write approval gate store requires a database DSN")
        return PgLegacySqlImportWriteApprovalGateStore(database_dsn=database_dsn)
    raise ValueError(f"Unsupported legacy SQL import write approval gate store backend: {backend}")


def run_legacy_sql_import_write_approval_gate_smoke_from_env(
    environ: Mapping[str, str] | None = None,
) -> LegacySqlImportWriteApprovalGateSmokeReport:
    env = os.environ if environ is None else environ
    checked_by = env.get(
        "SUITE_LEGACY_SQL_IMPORT_WRITE_APPROVAL_GATE_CHECKED_BY",
        "legacy-sql-import-write-approval-gate-smoke",
    )
    checked_at = datetime.now(UTC)
    dry_run_result, dry_run_worker_report = _dry_run_fixture_pair(env)
    review = build_legacy_sql_import_write_approval_review(
        dry_run_result=dry_run_result,
        dry_run_worker_report=dry_run_worker_report,
        reviewer_principal_ref="principal:legacy-sql-import-reviewer",
        review_ticket_ref="ticket:legacy-sql-import-write-review",
        approval_reference="approval:legacy-sql-import-write-approval-record",
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    change_control = build_legacy_sql_import_write_change_control(
        dry_run_result=dry_run_result,
        dry_run_worker_report=dry_run_worker_report,
        change_request_ref="change:legacy-sql-import-write-approval",
        maintenance_window_ref="window:legacy-sql-import-write-approval",
        rollback_plan_ref="rollback:legacy-sql-import-write-approval",
        risk_acceptance_ref="risk:legacy-sql-import-write-approval",
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    restore_drill = build_legacy_sql_import_write_restore_drill(
        dry_run_result=dry_run_result,
        dry_run_worker_report=dry_run_worker_report,
        restore_drill_report_hash=_fixture_hash("restore-drill", dry_run_result.result_hash),
        backup_verification_hash=_fixture_hash("backup-verification", dry_run_worker_report.evidence_hash),
        dry_run_result_store_roundtrip_hash=dry_run_result.result_hash,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    command = build_legacy_sql_import_write_approval_gate_command(
        dry_run_result=dry_run_result,
        dry_run_worker_report=dry_run_worker_report,
        approval_review=review,
        change_control=change_control,
        restore_drill=restore_drill,
        requested_by=checked_by,
    )
    gate = build_legacy_sql_import_write_approval_gate(
        command=command,
        dry_run_result=dry_run_result,
        dry_run_worker_report=dry_run_worker_report,
        approval_review=review,
        change_control=change_control,
        restore_drill=restore_drill,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    missing_review_blocked = _is_blocked_gate(
        command=command,
        dry_run_result=dry_run_result,
        dry_run_worker_report=dry_run_worker_report,
        approval_review=build_legacy_sql_import_write_approval_review(
            dry_run_result=dry_run_result,
            dry_run_worker_report=dry_run_worker_report,
            reviewer_principal_ref="principal:legacy-sql-import-reviewer",
            review_ticket_ref="ticket:legacy-sql-import-write-review",
            approval_reference="approval:legacy-sql-import-write-approval-record",
            checked_by=checked_by,
            checked_at_utc=checked_at,
            human_review_completed=False,
        ),
        change_control=change_control,
        restore_drill=restore_drill,
        checked_by=checked_by,
        expected_reason="human_review_incomplete",
    )
    rollback_missing_blocked = _is_blocked_gate(
        command=command,
        dry_run_result=dry_run_result,
        dry_run_worker_report=dry_run_worker_report,
        approval_review=review,
        change_control=build_legacy_sql_import_write_change_control(
            dry_run_result=dry_run_result,
            dry_run_worker_report=dry_run_worker_report,
            change_request_ref="change:legacy-sql-import-write-approval",
            maintenance_window_ref="window:legacy-sql-import-write-approval",
            rollback_plan_ref="rollback:legacy-sql-import-write-approval",
            risk_acceptance_ref="risk:legacy-sql-import-write-approval",
            checked_by=checked_by,
            checked_at_utc=checked_at,
            rollback_plan_verified=False,
        ),
        restore_drill=restore_drill,
        checked_by=checked_by,
        expected_reason="rollback_plan_not_verified",
    )
    restore_missing_blocked = _is_blocked_gate(
        command=command,
        dry_run_result=dry_run_result,
        dry_run_worker_report=dry_run_worker_report,
        approval_review=review,
        change_control=change_control,
        restore_drill=build_legacy_sql_import_write_restore_drill(
            dry_run_result=dry_run_result,
            dry_run_worker_report=dry_run_worker_report,
            restore_drill_report_hash=_fixture_hash("restore-drill", dry_run_result.result_hash),
            backup_verification_hash=_fixture_hash("backup-verification", dry_run_worker_report.evidence_hash),
            dry_run_result_store_roundtrip_hash=dry_run_result.result_hash,
            checked_by=checked_by,
            checked_at_utc=checked_at,
            restore_drill_passed=False,
        ),
        checked_by=checked_by,
        expected_reason="restore_drill_not_passed",
    )
    import_write_request_blocked = _unsafe_command_blocked(
        dry_run_result=dry_run_result,
        dry_run_worker_report=dry_run_worker_report,
        approval_review=review,
        change_control=change_control,
        restore_drill=restore_drill,
        checked_by=checked_by,
    )
    tampered_dry_run_result_blocked = _tampered_dry_run_result_blocked(
        command=command,
        dry_run_result=dry_run_result,
        dry_run_worker_report=dry_run_worker_report,
        approval_review=review,
        change_control=change_control,
        restore_drill=restore_drill,
        checked_by=checked_by,
    )
    gate_store_write_enabled = _env_bool(
        env,
        "SUITE_LEGACY_SQL_IMPORT_WRITE_APPROVAL_GATE_STORE_WRITE",
        default=False,
    )
    gate_store_backend = _gate_store_backend(env) if gate_store_write_enabled else None
    if gate_store_write_enabled:
        build_default_legacy_sql_import_write_approval_gate_store(environ=env).append(gate)
    smoke_passed = (
        gate.gate_status == LegacySqlImportWriteApprovalGateStatus.READY_FOR_HUMAN_APPROVAL_RECORD
        and gate.human_approval_record_allowed
        and not gate.import_write_execution_allowed
        and missing_review_blocked
        and rollback_missing_blocked
        and restore_missing_blocked
        and import_write_request_blocked
        and tampered_dry_run_result_blocked
    )
    draft = LegacySqlImportWriteApprovalGateSmokeReport(
        run_id=f"legacy-sql-import-write-approval-gate-smoke-{uuid4().hex}",
        checked_by=checked_by,
        checked_at_utc=checked_at,
        tenant_id=gate.tenant_id,
        module_id=gate.module_id,
        source_system_ref=gate.source_system_ref,
        dry_run_result_hash=gate.dry_run_result_hash,
        dry_run_worker_report_hash=gate.dry_run_worker_report_hash,
        approval_review_evidence_hash=gate.approval_review_evidence_hash,
        change_control_evidence_hash=gate.change_control_evidence_hash,
        restore_drill_evidence_hash=gate.restore_drill_evidence_hash,
        approval_gate_evidence_hash=gate.evidence_hash,
        approval_gate_ready_for_human_record=gate.human_approval_record_allowed,
        human_approval_record_allowed=gate.human_approval_record_allowed,
        future_import_write_execution_gate_required=gate.future_import_write_execution_gate_required,
        missing_human_review_blocked=missing_review_blocked,
        rollback_plan_missing_blocked=rollback_missing_blocked,
        restore_drill_missing_blocked=restore_missing_blocked,
        import_write_request_blocked=import_write_request_blocked,
        tampered_dry_run_result_blocked=tampered_dry_run_result_blocked,
        gate_store_write_enabled=gate_store_write_enabled,
        gate_store_backend=gate_store_backend,
        smoke_passed=smoke_passed,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_import_write_approval_gate_smoke_report_hash(draft)}
    )


def exit_code_for_report(report: LegacySqlImportWriteApprovalGateSmokeReport) -> int:
    return 0 if report.smoke_passed else 1


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Legacy SQL import write approval gate smoke.")
    parser.add_argument("--once", action="store_true", help="Run one non-executing approval gate smoke and exit.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the smoke report.")
    args = parser.parse_args(argv)
    del args.once

    report = run_legacy_sql_import_write_approval_gate_smoke_from_env()
    print(json.dumps(report.model_dump(mode="json"), indent=2 if args.pretty else None, sort_keys=True))
    raise SystemExit(exit_code_for_report(report))


def _dry_run_fixture_pair(
    env: Mapping[str, str],
) -> tuple[LegacySqlImportDryRunResult, LegacySqlImportDryRunWorkerReport]:
    with tempfile.TemporaryDirectory(prefix="legacy-sql-import-write-approval-") as tmp:
        result_store_path = Path(tmp) / "dry-run-results.jsonl"
        dry_run_env = dict(env)
        dry_run_env["SUITE_LEGACY_SQL_IMPORT_DRY_RUN_RESULT_STORE_WRITE"] = "true"
        dry_run_env["SUITE_LEGACY_SQL_IMPORT_DRY_RUN_RESULT_STORE_BACKEND"] = "jsonl"
        dry_run_env["SUITE_LEGACY_SQL_IMPORT_DRY_RUN_RESULT_STORE_PATH"] = str(result_store_path)
        dry_run_worker_report = run_legacy_sql_import_dry_run_worker_from_env(dry_run_env)
        dry_run_result = JsonlLegacySqlImportDryRunResultStore(path=result_store_path).get(
            tenant_id=dry_run_worker_report.tenant_id,
            result_hash=dry_run_worker_report.dry_run_result_hash,
        )
        return dry_run_result, dry_run_worker_report


def _approval_gate_blocking_reasons(
    *,
    command: LegacySqlImportWriteApprovalGateCommand,
    dry_run_result_hash_valid: bool,
    dry_run_result_completed: bool,
    dry_run_worker_report_hash_valid: bool,
    dry_run_worker_report_bound: bool,
    dry_run_worker_report: LegacySqlImportDryRunWorkerReport,
    approval_review_hash_valid: bool,
    approval_review_bound: bool,
    approval_review: LegacySqlImportWriteApprovalReview,
    change_control_hash_valid: bool,
    change_control_bound: bool,
    change_control: LegacySqlImportWriteChangeControl,
    restore_drill_hash_valid: bool,
    restore_drill_bound: bool,
    restore_drill: LegacySqlImportWriteRestoreDrill,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not command.approval_gate_requested:
        reasons.append("approval_gate_not_requested")
    if command.raw_data_access_requested:
        reasons.append("raw_data_access_request_forbidden")
    if command.import_write_requested:
        reasons.append("import_write_request_requires_future_execution_gate")
    if command.destructive_actions_requested:
        reasons.append("destructive_action_request_forbidden")
    if command.external_side_effect_requested:
        reasons.append("external_side_effect_request_forbidden")
    if not dry_run_result_hash_valid:
        reasons.append("dry_run_result_hash_invalid")
    if not dry_run_result_completed:
        reasons.append("dry_run_result_not_completed_metadata_only")
    if not dry_run_worker_report_hash_valid:
        reasons.append("dry_run_worker_report_hash_invalid")
    if not dry_run_worker_report_bound:
        reasons.append("dry_run_worker_report_not_bound")
    if not dry_run_worker_report.worker_passed:
        reasons.append("dry_run_worker_report_not_passed")
    if not approval_review_hash_valid:
        reasons.append("approval_review_hash_invalid")
    if not approval_review_bound:
        reasons.append("approval_review_not_bound")
    if not approval_review.human_review_completed:
        reasons.append("human_review_incomplete")
    if not approval_review.reviewer_independent:
        reasons.append("reviewer_not_independent")
    if not approval_review.reviewer_mfa_verified:
        reasons.append("reviewer_mfa_not_verified")
    if approval_review.break_glass_requested:
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
    if not restore_drill.result_store_restored:
        reasons.append("dry_run_result_store_not_restored")
    if not restore_drill.tenant_isolation_reverified:
        reasons.append("tenant_isolation_not_reverified")
    return tuple(dict.fromkeys(reasons))


def _approval_request_boundary_blocking_reasons(
    *,
    command: LegacySqlImportWriteApprovalRequestCommand,
    gate_hash_valid: bool,
    gate_bound: bool,
    gate_ready: bool,
    gate_evidence: LegacySqlImportWriteApprovalGateEvidence,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not command.approval_request_requested:
        reasons.append("approval_request_not_requested")
    if command.approval_record_persistence_requested:
        reasons.append("approval_record_persistence_not_enabled")
    if command.raw_data_access_requested:
        reasons.append("raw_data_access_request_forbidden")
    if command.import_write_requested:
        reasons.append("import_write_request_requires_future_execution_gate")
    if command.import_write_payload_requested:
        reasons.append("import_write_payload_request_forbidden")
    if command.destructive_actions_requested:
        reasons.append("destructive_action_request_forbidden")
    if command.external_side_effect_requested:
        reasons.append("external_side_effect_request_forbidden")
    if not gate_hash_valid:
        reasons.append("approval_gate_hash_invalid")
    if not gate_bound:
        reasons.append("approval_gate_not_bound_to_request")
    if not gate_ready:
        reasons.append("approval_gate_not_ready_for_human_record")
    if not gate_evidence.human_approval_record_allowed:
        reasons.append("human_approval_record_not_allowed_by_gate")
    if not gate_evidence.future_import_write_execution_gate_required:
        reasons.append("future_import_write_execution_gate_not_required")
    if gate_evidence.import_write_execution_allowed:
        reasons.append("approval_gate_import_write_execution_allowed_unexpectedly")
    return tuple(dict.fromkeys(reasons))


def _approval_request_gate_bound(
    *,
    command: LegacySqlImportWriteApprovalRequestCommand,
    gate_evidence: LegacySqlImportWriteApprovalGateEvidence,
    tenant_id: str,
) -> bool:
    return (
        gate_evidence.tenant_id == tenant_id
        and gate_evidence.module_id == CRM_ERP_MODULE_ID
        and gate_evidence.source_system_ref == command.source_system_ref
        and gate_evidence.dry_run_result_hash == command.dry_run_result_hash
        and gate_evidence.evidence_hash == command.approval_gate_evidence_hash
    )


def _approval_record_persistence_plan_blocking_reasons(
    *,
    command: LegacySqlImportWriteApprovalRecordPersistencePlanCommand,
    request_boundary: LegacySqlImportWriteApprovalRequestBoundaryResponse,
    gate_evidence: LegacySqlImportWriteApprovalGateEvidence,
    boundary_hash_valid: bool,
    boundary_bound: bool,
    boundary_ready: bool,
    gate_hash_valid: bool,
    gate_ready: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not command.approval_record_persistence_planning_requested:
        reasons.append("approval_record_persistence_planning_not_requested")
    if command.approval_record_persistence_requested:
        reasons.append("approval_record_persistence_not_enabled")
    if command.raw_data_access_requested:
        reasons.append("raw_data_access_request_forbidden")
    if command.import_write_requested:
        reasons.append("import_write_request_requires_future_execution_gate")
    if command.import_write_payload_requested:
        reasons.append("import_write_payload_request_forbidden")
    if command.destructive_actions_requested:
        reasons.append("destructive_action_request_forbidden")
    if command.external_side_effect_requested:
        reasons.append("external_side_effect_request_forbidden")
    if not boundary_hash_valid:
        reasons.append("approval_request_boundary_hash_invalid")
    if not boundary_bound:
        reasons.append("approval_request_boundary_not_bound_to_gate")
    if not boundary_ready:
        reasons.append("approval_request_boundary_not_ready_for_persistence_planning")
    if not gate_hash_valid:
        reasons.append("approval_gate_hash_invalid")
    if not gate_ready:
        reasons.append("approval_gate_not_ready_for_human_record")
    if not request_boundary.human_approval_record_allowed_by_gate:
        reasons.append("human_approval_record_not_allowed_by_boundary")
    if (
        not request_boundary.future_import_write_execution_gate_required
        or not gate_evidence.future_import_write_execution_gate_required
    ):
        reasons.append("future_import_write_execution_gate_not_required")
    if request_boundary.approval_record_persistence_allowed or request_boundary.approval_record_persisted:
        reasons.append("approval_record_persistence_already_allowed_unexpectedly")
    if request_boundary.import_write_execution_allowed or gate_evidence.import_write_execution_allowed:
        reasons.append("import_write_execution_allowed_unexpectedly")
    return tuple(dict.fromkeys(reasons))


def _approval_record_persistence_plan_boundary_bound(
    *,
    request_boundary: LegacySqlImportWriteApprovalRequestBoundaryResponse,
    gate_evidence: LegacySqlImportWriteApprovalGateEvidence,
    tenant_id: str,
) -> bool:
    return (
        request_boundary.tenant_id == tenant_id == gate_evidence.tenant_id
        and request_boundary.module_id == gate_evidence.module_id == CRM_ERP_MODULE_ID
        and request_boundary.source_system_ref == gate_evidence.source_system_ref
        and request_boundary.dry_run_result_hash == gate_evidence.dry_run_result_hash
        and request_boundary.approval_gate_evidence_hash == gate_evidence.evidence_hash
        and request_boundary.approval_gate_hash_valid
        and request_boundary.approval_gate_bound
    )


def _dry_run_worker_report_bound(
    *,
    command: LegacySqlImportWriteApprovalGateCommand,
    dry_run_result: LegacySqlImportDryRunResult,
    dry_run_worker_report: LegacySqlImportDryRunWorkerReport,
) -> bool:
    return (
        dry_run_worker_report.tenant_id == command.tenant_id == dry_run_result.tenant_id
        and dry_run_worker_report.module_id == command.module_id == dry_run_result.module_id
        and dry_run_worker_report.source_system_ref == command.source_system_ref == dry_run_result.source_system_ref
        and dry_run_worker_report.dry_run_plan_hash == command.dry_run_plan_hash == dry_run_result.dry_run_plan_hash
        and dry_run_worker_report.dry_run_result_hash == command.dry_run_result_hash == dry_run_result.result_hash
    )


def _approval_artifact_bound(
    *,
    command: LegacySqlImportWriteApprovalGateCommand,
    artifact: LegacySqlImportWriteApprovalReview | LegacySqlImportWriteChangeControl | LegacySqlImportWriteRestoreDrill,
) -> bool:
    return (
        artifact.tenant_id == command.tenant_id
        and artifact.module_id == command.module_id
        and artifact.source_system_ref == command.source_system_ref
        and artifact.dry_run_plan_hash == command.dry_run_plan_hash
        and artifact.dry_run_result_hash == command.dry_run_result_hash
        and artifact.dry_run_worker_report_hash == command.dry_run_worker_report_hash
    )


def _require_valid_gate_hash(evidence: LegacySqlImportWriteApprovalGateEvidence) -> None:
    expected = build_legacy_sql_import_write_approval_gate_hash(evidence)
    if evidence.evidence_hash != expected:
        raise ValueError("legacy SQL import write approval gate evidence hash invalid")


def _is_blocked_gate(
    *,
    command: LegacySqlImportWriteApprovalGateCommand,
    dry_run_result: LegacySqlImportDryRunResult,
    dry_run_worker_report: LegacySqlImportDryRunWorkerReport,
    approval_review: LegacySqlImportWriteApprovalReview,
    change_control: LegacySqlImportWriteChangeControl,
    restore_drill: LegacySqlImportWriteRestoreDrill,
    checked_by: str,
    expected_reason: str,
) -> bool:
    local_command = command.model_copy(
        update={
            "approval_review_evidence_hash": approval_review.evidence_hash,
            "change_control_evidence_hash": change_control.evidence_hash,
            "restore_drill_evidence_hash": restore_drill.evidence_hash,
        }
    )
    gate = build_legacy_sql_import_write_approval_gate(
        command=local_command,
        dry_run_result=dry_run_result,
        dry_run_worker_report=dry_run_worker_report,
        approval_review=approval_review,
        change_control=change_control,
        restore_drill=restore_drill,
        checked_by=checked_by,
    )
    return (
        gate.gate_status == LegacySqlImportWriteApprovalGateStatus.BLOCKED
        and expected_reason in gate.blocking_reasons
        and not gate.human_approval_record_allowed
        and not gate.import_write_execution_allowed
    )


def _unsafe_command_blocked(
    *,
    dry_run_result: LegacySqlImportDryRunResult,
    dry_run_worker_report: LegacySqlImportDryRunWorkerReport,
    approval_review: LegacySqlImportWriteApprovalReview,
    change_control: LegacySqlImportWriteChangeControl,
    restore_drill: LegacySqlImportWriteRestoreDrill,
    checked_by: str,
) -> bool:
    unsafe_command = build_legacy_sql_import_write_approval_gate_command(
        dry_run_result=dry_run_result,
        dry_run_worker_report=dry_run_worker_report,
        approval_review=approval_review,
        change_control=change_control,
        restore_drill=restore_drill,
        requested_by=checked_by,
        import_write_requested=True,
    )
    gate = build_legacy_sql_import_write_approval_gate(
        command=unsafe_command,
        dry_run_result=dry_run_result,
        dry_run_worker_report=dry_run_worker_report,
        approval_review=approval_review,
        change_control=change_control,
        restore_drill=restore_drill,
        checked_by=checked_by,
    )
    return (
        gate.gate_status == LegacySqlImportWriteApprovalGateStatus.BLOCKED
        and "import_write_request_requires_future_execution_gate" in gate.blocking_reasons
        and not gate.import_write_execution_allowed
    )


def _tampered_dry_run_result_blocked(
    *,
    command: LegacySqlImportWriteApprovalGateCommand,
    dry_run_result: LegacySqlImportDryRunResult,
    dry_run_worker_report: LegacySqlImportDryRunWorkerReport,
    approval_review: LegacySqlImportWriteApprovalReview,
    change_control: LegacySqlImportWriteChangeControl,
    restore_drill: LegacySqlImportWriteRestoreDrill,
    checked_by: str,
) -> bool:
    tampered_command = command.model_copy(update={"dry_run_result_hash": ZERO_HASH})
    gate = build_legacy_sql_import_write_approval_gate(
        command=tampered_command,
        dry_run_result=dry_run_result,
        dry_run_worker_report=dry_run_worker_report,
        approval_review=approval_review,
        change_control=change_control,
        restore_drill=restore_drill,
        checked_by=checked_by,
    )
    return (
        gate.gate_status == LegacySqlImportWriteApprovalGateStatus.BLOCKED
        and "dry_run_result_hash_invalid" in gate.blocking_reasons
        and not gate.human_approval_record_allowed
    )


def _fixture_hash(kind: str, seed: str) -> str:
    return stable_hash(canonical_json({"kind": kind, "seed": seed}))


def _gate_store_backend(env: Mapping[str, str]) -> LegacySqlImportWriteApprovalGateStoreBackend:
    backend = env.get("SUITE_LEGACY_SQL_IMPORT_WRITE_APPROVAL_GATE_STORE_BACKEND", "jsonl").strip().lower()
    if backend in {"jsonl", "json"}:
        return LegacySqlImportWriteApprovalGateStoreBackend.JSONL
    if backend in {"postgres", "pg"}:
        return LegacySqlImportWriteApprovalGateStoreBackend.POSTGRES
    raise ValueError(f"Unsupported legacy SQL import write approval gate store backend: {backend}")


def _env_bool(env: Mapping[str, str], name: str, *, default: bool) -> bool:
    value = env.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _assert_approval_gate_safe(value: BaseModel) -> None:
    payload = value.model_dump_json().lower()
    for forbidden in FORBIDDEN_APPROVAL_GATE_FRAGMENTS:
        if forbidden in payload:
            raise ValueError(f"legacy SQL import write approval gate payload contains forbidden fragment: {forbidden}")
