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
from suite.platform.legacy_sql_connector_execution_readiness_review_gate import (
    LegacySqlConnectorExecutionReadinessReviewGateEvidence,
    LegacySqlConnectorExecutionReadinessReviewGateStatus,
    build_legacy_sql_connector_execution_readiness_change_control,
    build_legacy_sql_connector_execution_readiness_human_review,
    build_legacy_sql_connector_execution_readiness_restore_drill,
    build_legacy_sql_connector_execution_readiness_review_gate,
    build_legacy_sql_connector_execution_readiness_review_gate_command,
    build_legacy_sql_connector_execution_readiness_review_gate_hash,
)
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

LEGACY_SQL_CONNECTOR_MATERIALIZATION_PROVIDER_PROFILE_SNAPSHOT_SCHEMA_VERSION = (
    "legacy_sql_connector_materialization_provider_profile_snapshot.v1"
)
LEGACY_SQL_CONNECTOR_MATERIALIZATION_OPERATOR_MFA_SNAPSHOT_SCHEMA_VERSION = (
    "legacy_sql_connector_materialization_operator_mfa_snapshot.v1"
)
LEGACY_SQL_CONNECTOR_MATERIALIZATION_KILL_SWITCH_SNAPSHOT_SCHEMA_VERSION = (
    "legacy_sql_connector_materialization_kill_switch_snapshot.v1"
)
LEGACY_SQL_CONNECTOR_MATERIALIZATION_PLAN_GATE_SCHEMA_VERSION = "legacy_sql_connector_materialization_plan_gate.v1"
LEGACY_SQL_CONNECTOR_MATERIALIZATION_PLAN_GATE_SMOKE_SCHEMA_VERSION = (
    "legacy_sql_connector_materialization_plan_gate_smoke_report.v1"
)
LEGACY_SQL_CONNECTOR_MATERIALIZATION_PLAN_GATE_COMMAND_REF = (
    "docker-compose:legacy-sql-connector-materialization-plan-gate-smoke"
)
ZERO_HASH = "sha256:" + "0" * 64
SHA256_REF_PATTERN = r"^sha256:[a-f0-9]{64}$"
FORBIDDEN_MATERIALIZATION_PLAN_FRAGMENTS = (
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


class LegacySqlConnectorMaterializationPlanGateStatus(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"


class LegacySqlConnectorMaterializationProviderProfileSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_MATERIALIZATION_PROVIDER_PROFILE_SNAPSHOT_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    provider_profile_snapshot_ref: str = "provider-profile-snapshot:legacy-sql-materialization-plan"
    sandbox_profile_ref: str
    sandbox_profile_evidence_hash: str
    preflight_evidence_hash: str
    provider_attestation_adapter_evidence_hash: str
    provider_attestation_hash: str
    network_profile_attested: bool = True
    secret_resolver_profile_attested: bool = True
    audit_profile_attested: bool = True
    provider_metadata_only_boundary_attested: bool = True
    provider_profiles_current: bool = True
    default_compose_legacy_network_enabled: bool = False
    network_connection_opened: bool = False
    real_connection_opened: bool = False
    secret_material_resolved: bool = False
    raw_data_access_allowed: bool = False
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL materialization provider snapshot text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL materialization provider snapshot module_id must be lowercase snake_case")
        return value

    @field_validator("source_system_ref", "provider_profile_snapshot_ref", "sandbox_profile_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL materialization provider snapshot references must be namespaced")
        return value

    @field_validator(
        "sandbox_profile_evidence_hash",
        "preflight_evidence_hash",
        "provider_attestation_adapter_evidence_hash",
        "provider_attestation_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL materialization provider snapshot hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_safe_provider_snapshot(self) -> Self:
        if (
            not self.provider_metadata_only_boundary_attested
            or self.default_compose_legacy_network_enabled
            or self.network_connection_opened
            or self.real_connection_opened
            or self.secret_material_resolved
            or self.raw_data_access_allowed
        ):
            raise ValueError("legacy SQL materialization provider snapshot must stay metadata-only")
        _assert_materialization_plan_safe(self)
        return self


class LegacySqlConnectorMaterializationOperatorMfaSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_MATERIALIZATION_OPERATOR_MFA_SNAPSHOT_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    operator_mfa_snapshot_ref: str = "operator-mfa-snapshot:legacy-sql-materialization-plan"
    operator_context_evidence_hash: str
    operator_principal_ref: str
    operator_role_ref: str
    change_request_ref: str
    maintenance_window_ref: str
    approval_reference: str
    operator_authorized_for_legacy_sql: bool = True
    operator_mfa_verified: bool = True
    compliance_window_active: bool = True
    break_glass_requested: bool = False
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL materialization operator MFA snapshot text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL materialization operator MFA snapshot module_id must be lowercase snake_case")
        return value

    @field_validator(
        "source_system_ref",
        "operator_mfa_snapshot_ref",
        "operator_principal_ref",
        "operator_role_ref",
        "change_request_ref",
        "maintenance_window_ref",
        "approval_reference",
    )
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL materialization operator MFA snapshot references must be namespaced")
        return value

    @field_validator("operator_context_evidence_hash", "evidence_hash")
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL materialization operator MFA snapshot hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_safe_operator_snapshot(self) -> Self:
        if self.break_glass_requested:
            raise ValueError("legacy SQL materialization operator MFA snapshot cannot use break-glass by default")
        _assert_materialization_plan_safe(self)
        return self


class LegacySqlConnectorMaterializationKillSwitchSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_MATERIALIZATION_KILL_SWITCH_SNAPSHOT_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    kill_switch_snapshot_ref: str = "kill-switch-snapshot:legacy-sql-materialization-plan"
    kill_switch_policy_hash: str
    kill_switch_policy_ref: str
    tenant_kill_switch_ref: str
    global_kill_switch_ref: str
    manual_abort_ref: str
    incident_channel_ref: str
    kill_switch_armed: bool
    tenant_connection_disabled: bool
    global_connection_disabled: bool
    manual_abort_requested: bool
    break_glass_allowed: bool = False
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL materialization kill-switch snapshot text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL materialization kill-switch snapshot module_id must be lowercase snake_case")
        return value

    @field_validator(
        "source_system_ref",
        "kill_switch_snapshot_ref",
        "kill_switch_policy_ref",
        "tenant_kill_switch_ref",
        "global_kill_switch_ref",
        "manual_abort_ref",
        "incident_channel_ref",
    )
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL materialization kill-switch snapshot references must be namespaced")
        return value

    @field_validator("kill_switch_policy_hash", "evidence_hash")
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL materialization kill-switch snapshot hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_safe_kill_switch_snapshot(self) -> Self:
        if self.break_glass_allowed:
            raise ValueError("legacy SQL materialization kill-switch snapshot cannot allow break-glass by default")
        _assert_materialization_plan_safe(self)
        return self


class LegacySqlConnectorMaterializationPlanGateCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    policy_bundle_evidence_hash: str
    executor_contract_evidence_hash: str
    review_gate_evidence_hash: str
    provider_profile_snapshot_hash: str
    operator_mfa_snapshot_hash: str
    kill_switch_snapshot_hash: str
    requested_by: str
    materialization_plan_requested: bool = True
    socket_materialization_requested: bool = False
    secret_materialization_requested: bool = False
    execution_implementation_requested: bool = False
    raw_data_access_requested: bool = False
    import_dry_run_requested: bool = False
    import_write_requested: bool = False
    destructive_actions_requested: bool = False

    @field_validator("tenant_id", "requested_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL materialization plan command text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL materialization plan command module_id must be lowercase snake_case")
        return value

    @field_validator("source_system_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL materialization plan command references must be namespaced")
        return value

    @field_validator(
        "policy_bundle_evidence_hash",
        "executor_contract_evidence_hash",
        "review_gate_evidence_hash",
        "provider_profile_snapshot_hash",
        "operator_mfa_snapshot_hash",
        "kill_switch_snapshot_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL materialization plan command hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_safe_command(self) -> Self:
        _assert_materialization_plan_safe(self)
        return self


class LegacySqlConnectorMaterializationPlanGateEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_MATERIALIZATION_PLAN_GATE_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    continuity_domain: str = LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN
    command_ref: str = LEGACY_SQL_CONNECTOR_MATERIALIZATION_PLAN_GATE_COMMAND_REF
    policy_bundle_evidence_hash: str
    executor_contract_evidence_hash: str
    review_gate_evidence_hash: str
    provider_profile_snapshot_hash: str
    operator_mfa_snapshot_hash: str
    kill_switch_snapshot_hash: str
    provider_attestation_adapter_evidence_hash: str
    provider_attestation_hash: str
    operator_context_evidence_hash: str
    kill_switch_policy_hash: str
    review_gate_hash_valid: bool
    review_gate_ready: bool
    review_gate_bound: bool
    provider_profile_snapshot_hash_valid: bool
    provider_profile_snapshot_bound: bool
    provider_profiles_current: bool
    provider_metadata_only_boundary_attested: bool
    operator_mfa_snapshot_hash_valid: bool
    operator_mfa_snapshot_bound: bool
    operator_authorized_for_legacy_sql: bool
    operator_mfa_verified: bool
    compliance_window_active: bool
    break_glass_requested: bool
    kill_switch_snapshot_hash_valid: bool
    kill_switch_snapshot_bound: bool
    kill_switch_armed: bool
    tenant_connection_disabled: bool
    global_connection_disabled: bool
    manual_abort_requested: bool
    materialization_plan_requested: bool
    materialization_plan_ready: bool
    future_socket_materialization_implementation_gate_required: bool = True
    future_secret_materialization_implementation_gate_required: bool = True
    future_execution_implementation_required: bool = True
    socket_materialization_requested: bool = False
    socket_materialization_allowed: bool = False
    secret_materialization_requested: bool = False
    secret_materialization_allowed: bool = False
    execution_implementation_requested: bool = False
    execution_implementation_allowed: bool = False
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
    gate_status: LegacySqlConnectorMaterializationPlanGateStatus
    blocking_reasons: tuple[str, ...]
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL materialization plan gate text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL materialization plan gate module_id must be lowercase snake_case")
        return value

    @field_validator("source_system_ref")
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL materialization plan gate references must be namespaced")
        return value

    @field_validator(
        "policy_bundle_evidence_hash",
        "executor_contract_evidence_hash",
        "review_gate_evidence_hash",
        "provider_profile_snapshot_hash",
        "operator_mfa_snapshot_hash",
        "kill_switch_snapshot_hash",
        "provider_attestation_adapter_evidence_hash",
        "provider_attestation_hash",
        "operator_context_evidence_hash",
        "kill_switch_policy_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL materialization plan gate hashes must be sha256 references")
        return value

    @field_validator("blocking_reasons")
    @classmethod
    def validate_blocking_reasons(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("legacy SQL materialization plan gate blocking reasons must be unique")
        for reason in value:
            if not reason.strip():
                raise ValueError("legacy SQL materialization plan gate blocking reasons must not be empty")
        return value

    @model_validator(mode="after")
    def require_safe_plan_gate(self) -> Self:
        if (
            self.socket_materialization_allowed
            or self.secret_materialization_allowed
            or self.execution_implementation_allowed
            or self.network_socket_opened
            or self.network_connection_opened
            or self.real_connection_opened
            or self.secret_material_resolved
            or self.raw_data_access_allowed
            or self.import_dry_run_allowed
            or self.import_write_allowed
            or self.destructive_actions_allowed
        ):
            raise ValueError("legacy SQL materialization plan gate must remain non-executing")
        if (
            not self.future_socket_materialization_implementation_gate_required
            or not self.future_secret_materialization_implementation_gate_required
            or not self.future_execution_implementation_required
        ):
            raise ValueError("legacy SQL materialization plan gate must require future implementation gates")
        if self.gate_status == LegacySqlConnectorMaterializationPlanGateStatus.READY:
            required = (
                self.review_gate_hash_valid,
                self.review_gate_ready,
                self.review_gate_bound,
                self.provider_profile_snapshot_hash_valid,
                self.provider_profile_snapshot_bound,
                self.provider_profiles_current,
                self.provider_metadata_only_boundary_attested,
                self.operator_mfa_snapshot_hash_valid,
                self.operator_mfa_snapshot_bound,
                self.operator_authorized_for_legacy_sql,
                self.operator_mfa_verified,
                self.compliance_window_active,
                not self.break_glass_requested,
                self.kill_switch_snapshot_hash_valid,
                self.kill_switch_snapshot_bound,
                self.kill_switch_armed,
                not self.tenant_connection_disabled,
                not self.global_connection_disabled,
                not self.manual_abort_requested,
                self.materialization_plan_requested,
                self.materialization_plan_ready,
            )
            if not all(required) or self.blocking_reasons:
                raise ValueError("ready legacy SQL materialization plan gate requires complete evidence")
        if self.gate_status == LegacySqlConnectorMaterializationPlanGateStatus.BLOCKED:
            if not self.blocking_reasons:
                raise ValueError("blocked legacy SQL materialization plan gate requires blocking reasons")
            if self.materialization_plan_ready:
                raise ValueError("blocked legacy SQL materialization plan gate cannot be ready")
        _assert_materialization_plan_safe(self)
        return self


class LegacySqlConnectorMaterializationPlanGateSmokeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_MATERIALIZATION_PLAN_GATE_SMOKE_SCHEMA_VERSION
    tenant_id: str
    store_backend: LegacySqlConnectorRealConnectionPolicyStoreBackend
    continuity_domain: str = LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN
    command_ref: str = LEGACY_SQL_CONNECTOR_MATERIALIZATION_PLAN_GATE_COMMAND_REF
    policy_bundle_evidence_hash: str
    review_gate_evidence_hash: str
    provider_profile_snapshot_hash: str
    operator_mfa_snapshot_hash: str
    kill_switch_snapshot_hash: str
    materialization_plan_gate_evidence_hash: str
    materialization_plan_ready: bool
    review_gate_required: bool
    provider_profile_snapshot_required: bool
    operator_mfa_snapshot_required: bool
    kill_switch_snapshot_required: bool
    review_gate_missing_blocked: bool
    operator_mfa_missing_blocked: bool
    kill_switch_disabled_blocked: bool
    materialization_request_blocked: bool
    future_socket_materialization_implementation_gate_required: bool
    future_secret_materialization_implementation_gate_required: bool
    future_execution_implementation_required: bool
    socket_materialization_allowed: bool = False
    secret_materialization_allowed: bool = False
    execution_implementation_allowed: bool = False
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
            self.socket_materialization_allowed
            or self.secret_materialization_allowed
            or self.execution_implementation_allowed
            or self.network_socket_opened
            or self.network_connection_opened
            or self.real_connection_opened
            or self.secret_material_resolved
            or self.raw_data_access_allowed
            or self.import_dry_run_allowed
            or self.import_write_allowed
            or self.destructive_actions_allowed
        ):
            raise ValueError("legacy SQL materialization plan smoke must remain non-executing")
        _assert_materialization_plan_safe(self)
        return self


def build_legacy_sql_connector_materialization_provider_profile_snapshot(
    *,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    provider_profiles_current: bool = True,
    provider_metadata_only_boundary_attested: bool = True,
) -> LegacySqlConnectorMaterializationProviderProfileSnapshot:
    checked_at = checked_at_utc or datetime.now(UTC)
    draft = LegacySqlConnectorMaterializationProviderProfileSnapshot(
        tenant_id=bundle.tenant_id,
        module_id=bundle.module_id,
        source_system_ref=bundle.source_system_ref,
        connector_kind=bundle.connector_kind,
        sandbox_profile_ref=bundle.sandbox_profile_ref,
        sandbox_profile_evidence_hash=bundle.sandbox_profile_evidence_hash,
        preflight_evidence_hash=bundle.preflight_evidence_hash,
        provider_attestation_adapter_evidence_hash=bundle.executor_contract.provider_attestation_adapter_evidence_hash,
        provider_attestation_hash=bundle.executor_contract.provider_attestation_hash,
        provider_profiles_current=provider_profiles_current,
        provider_metadata_only_boundary_attested=provider_metadata_only_boundary_attested,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_materialization_provider_profile_snapshot_hash(draft)}
    )


def build_legacy_sql_connector_materialization_operator_mfa_snapshot(
    *,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    operator_authorized_for_legacy_sql: bool = True,
    operator_mfa_verified: bool = True,
    compliance_window_active: bool = True,
    break_glass_requested: bool = False,
) -> LegacySqlConnectorMaterializationOperatorMfaSnapshot:
    checked_at = checked_at_utc or datetime.now(UTC)
    contract = bundle.executor_contract
    draft = LegacySqlConnectorMaterializationOperatorMfaSnapshot(
        tenant_id=bundle.tenant_id,
        module_id=bundle.module_id,
        source_system_ref=bundle.source_system_ref,
        connector_kind=bundle.connector_kind,
        operator_context_evidence_hash=contract.operator_context_evidence_hash,
        operator_principal_ref=contract.operator_principal_ref,
        operator_role_ref=contract.operator_role_ref,
        change_request_ref=contract.change_request_ref,
        maintenance_window_ref=contract.maintenance_window_ref,
        approval_reference=contract.approval_reference,
        operator_authorized_for_legacy_sql=operator_authorized_for_legacy_sql,
        operator_mfa_verified=operator_mfa_verified,
        compliance_window_active=compliance_window_active,
        break_glass_requested=break_glass_requested,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_materialization_operator_mfa_snapshot_hash(draft)}
    )


def build_legacy_sql_connector_materialization_kill_switch_snapshot(
    *,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    checked_by: str,
    checked_at_utc: datetime | None = None,
) -> LegacySqlConnectorMaterializationKillSwitchSnapshot:
    checked_at = checked_at_utc or datetime.now(UTC)
    policy = bundle.kill_switch_policy
    draft = LegacySqlConnectorMaterializationKillSwitchSnapshot(
        tenant_id=bundle.tenant_id,
        module_id=bundle.module_id,
        source_system_ref=bundle.source_system_ref,
        connector_kind=bundle.connector_kind,
        kill_switch_policy_hash=bundle.kill_switch_policy_hash,
        kill_switch_policy_ref=policy.kill_switch_policy_ref,
        tenant_kill_switch_ref=policy.tenant_kill_switch_ref,
        global_kill_switch_ref=policy.global_kill_switch_ref,
        manual_abort_ref=policy.manual_abort_ref,
        incident_channel_ref=policy.incident_channel_ref,
        kill_switch_armed=policy.kill_switch_armed,
        tenant_connection_disabled=policy.tenant_connection_disabled,
        global_connection_disabled=policy.global_connection_disabled,
        manual_abort_requested=policy.manual_abort_requested,
        break_glass_allowed=policy.break_glass_allowed,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_materialization_kill_switch_snapshot_hash(draft)}
    )


def build_legacy_sql_connector_materialization_plan_gate_command(
    *,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    review_gate: LegacySqlConnectorExecutionReadinessReviewGateEvidence,
    provider_profile_snapshot: LegacySqlConnectorMaterializationProviderProfileSnapshot,
    operator_mfa_snapshot: LegacySqlConnectorMaterializationOperatorMfaSnapshot,
    kill_switch_snapshot: LegacySqlConnectorMaterializationKillSwitchSnapshot,
    requested_by: str,
    materialization_plan_requested: bool = True,
    socket_materialization_requested: bool = False,
    secret_materialization_requested: bool = False,
    execution_implementation_requested: bool = False,
    raw_data_access_requested: bool = False,
    import_dry_run_requested: bool = False,
    import_write_requested: bool = False,
    destructive_actions_requested: bool = False,
) -> LegacySqlConnectorMaterializationPlanGateCommand:
    return LegacySqlConnectorMaterializationPlanGateCommand(
        tenant_id=bundle.tenant_id,
        module_id=bundle.module_id,
        source_system_ref=bundle.source_system_ref,
        connector_kind=bundle.connector_kind,
        policy_bundle_evidence_hash=bundle.evidence_hash,
        executor_contract_evidence_hash=bundle.executor_contract_evidence_hash,
        review_gate_evidence_hash=review_gate.evidence_hash,
        provider_profile_snapshot_hash=provider_profile_snapshot.evidence_hash,
        operator_mfa_snapshot_hash=operator_mfa_snapshot.evidence_hash,
        kill_switch_snapshot_hash=kill_switch_snapshot.evidence_hash,
        requested_by=requested_by,
        materialization_plan_requested=materialization_plan_requested,
        socket_materialization_requested=socket_materialization_requested,
        secret_materialization_requested=secret_materialization_requested,
        execution_implementation_requested=execution_implementation_requested,
        raw_data_access_requested=raw_data_access_requested,
        import_dry_run_requested=import_dry_run_requested,
        import_write_requested=import_write_requested,
        destructive_actions_requested=destructive_actions_requested,
    )


def build_legacy_sql_connector_materialization_plan_gate(
    *,
    command: LegacySqlConnectorMaterializationPlanGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    review_gate: LegacySqlConnectorExecutionReadinessReviewGateEvidence,
    provider_profile_snapshot: LegacySqlConnectorMaterializationProviderProfileSnapshot,
    operator_mfa_snapshot: LegacySqlConnectorMaterializationOperatorMfaSnapshot,
    kill_switch_snapshot: LegacySqlConnectorMaterializationKillSwitchSnapshot,
    checked_by: str,
    checked_at_utc: datetime | None = None,
) -> LegacySqlConnectorMaterializationPlanGateEvidence:
    checked_at = checked_at_utc or datetime.now(UTC)
    review_gate_hash_valid = (
        build_legacy_sql_connector_execution_readiness_review_gate_hash(review_gate)
        == review_gate.evidence_hash
        == command.review_gate_evidence_hash
    )
    review_gate_ready = (
        review_gate.gate_status == LegacySqlConnectorExecutionReadinessReviewGateStatus.READY
        and review_gate.execution_readiness_review_passed
        and review_gate.future_materialization_plan_gate_required
    )
    review_gate_bound = _review_gate_bound(command=command, bundle=bundle, review_gate=review_gate)
    provider_profile_snapshot_hash_valid = (
        build_legacy_sql_connector_materialization_provider_profile_snapshot_hash(provider_profile_snapshot)
        == provider_profile_snapshot.evidence_hash
        == command.provider_profile_snapshot_hash
    )
    provider_profile_snapshot_bound = _provider_profile_snapshot_bound(
        command=command,
        bundle=bundle,
        snapshot=provider_profile_snapshot,
    )
    operator_mfa_snapshot_hash_valid = (
        build_legacy_sql_connector_materialization_operator_mfa_snapshot_hash(operator_mfa_snapshot)
        == operator_mfa_snapshot.evidence_hash
        == command.operator_mfa_snapshot_hash
    )
    operator_mfa_snapshot_bound = _operator_mfa_snapshot_bound(
        command=command,
        bundle=bundle,
        snapshot=operator_mfa_snapshot,
    )
    kill_switch_snapshot_hash_valid = (
        build_legacy_sql_connector_materialization_kill_switch_snapshot_hash(kill_switch_snapshot)
        == kill_switch_snapshot.evidence_hash
        == command.kill_switch_snapshot_hash
    )
    kill_switch_snapshot_bound = _kill_switch_snapshot_bound(
        command=command,
        bundle=bundle,
        snapshot=kill_switch_snapshot,
    )
    blocking_reasons = _materialization_plan_blocking_reasons(
        command=command,
        bundle=bundle,
        review_gate_hash_valid=review_gate_hash_valid,
        review_gate_ready=review_gate_ready,
        review_gate_bound=review_gate_bound,
        provider_profile_snapshot_hash_valid=provider_profile_snapshot_hash_valid,
        provider_profile_snapshot_bound=provider_profile_snapshot_bound,
        provider_profile_snapshot=provider_profile_snapshot,
        operator_mfa_snapshot_hash_valid=operator_mfa_snapshot_hash_valid,
        operator_mfa_snapshot_bound=operator_mfa_snapshot_bound,
        operator_mfa_snapshot=operator_mfa_snapshot,
        kill_switch_snapshot_hash_valid=kill_switch_snapshot_hash_valid,
        kill_switch_snapshot_bound=kill_switch_snapshot_bound,
        kill_switch_snapshot=kill_switch_snapshot,
    )
    ready = not blocking_reasons
    draft = LegacySqlConnectorMaterializationPlanGateEvidence(
        tenant_id=bundle.tenant_id,
        module_id=bundle.module_id,
        source_system_ref=bundle.source_system_ref,
        connector_kind=bundle.connector_kind,
        policy_bundle_evidence_hash=bundle.evidence_hash,
        executor_contract_evidence_hash=bundle.executor_contract_evidence_hash,
        review_gate_evidence_hash=review_gate.evidence_hash,
        provider_profile_snapshot_hash=provider_profile_snapshot.evidence_hash,
        operator_mfa_snapshot_hash=operator_mfa_snapshot.evidence_hash,
        kill_switch_snapshot_hash=kill_switch_snapshot.evidence_hash,
        provider_attestation_adapter_evidence_hash=provider_profile_snapshot.provider_attestation_adapter_evidence_hash,
        provider_attestation_hash=provider_profile_snapshot.provider_attestation_hash,
        operator_context_evidence_hash=operator_mfa_snapshot.operator_context_evidence_hash,
        kill_switch_policy_hash=kill_switch_snapshot.kill_switch_policy_hash,
        review_gate_hash_valid=review_gate_hash_valid,
        review_gate_ready=review_gate_ready,
        review_gate_bound=review_gate_bound,
        provider_profile_snapshot_hash_valid=provider_profile_snapshot_hash_valid,
        provider_profile_snapshot_bound=provider_profile_snapshot_bound,
        provider_profiles_current=provider_profile_snapshot.provider_profiles_current,
        provider_metadata_only_boundary_attested=provider_profile_snapshot.provider_metadata_only_boundary_attested,
        operator_mfa_snapshot_hash_valid=operator_mfa_snapshot_hash_valid,
        operator_mfa_snapshot_bound=operator_mfa_snapshot_bound,
        operator_authorized_for_legacy_sql=operator_mfa_snapshot.operator_authorized_for_legacy_sql,
        operator_mfa_verified=operator_mfa_snapshot.operator_mfa_verified,
        compliance_window_active=operator_mfa_snapshot.compliance_window_active,
        break_glass_requested=operator_mfa_snapshot.break_glass_requested,
        kill_switch_snapshot_hash_valid=kill_switch_snapshot_hash_valid,
        kill_switch_snapshot_bound=kill_switch_snapshot_bound,
        kill_switch_armed=kill_switch_snapshot.kill_switch_armed,
        tenant_connection_disabled=kill_switch_snapshot.tenant_connection_disabled,
        global_connection_disabled=kill_switch_snapshot.global_connection_disabled,
        manual_abort_requested=kill_switch_snapshot.manual_abort_requested,
        materialization_plan_requested=command.materialization_plan_requested,
        materialization_plan_ready=ready,
        socket_materialization_requested=command.socket_materialization_requested,
        secret_materialization_requested=command.secret_materialization_requested,
        execution_implementation_requested=command.execution_implementation_requested,
        raw_data_access_requested=command.raw_data_access_requested,
        import_dry_run_requested=command.import_dry_run_requested,
        import_write_requested=command.import_write_requested,
        destructive_actions_requested=command.destructive_actions_requested,
        gate_status=(
            LegacySqlConnectorMaterializationPlanGateStatus.READY
            if ready
            else LegacySqlConnectorMaterializationPlanGateStatus.BLOCKED
        ),
        blocking_reasons=blocking_reasons,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_connector_materialization_plan_gate_hash(draft)})


def build_legacy_sql_connector_materialization_provider_profile_snapshot_hash(
    snapshot: LegacySqlConnectorMaterializationProviderProfileSnapshot,
) -> str:
    return stable_hash(canonical_json(snapshot.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_materialization_operator_mfa_snapshot_hash(
    snapshot: LegacySqlConnectorMaterializationOperatorMfaSnapshot,
) -> str:
    return stable_hash(canonical_json(snapshot.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_materialization_kill_switch_snapshot_hash(
    snapshot: LegacySqlConnectorMaterializationKillSwitchSnapshot,
) -> str:
    return stable_hash(canonical_json(snapshot.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_materialization_plan_gate_hash(
    gate: LegacySqlConnectorMaterializationPlanGateEvidence,
) -> str:
    return stable_hash(canonical_json(gate.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_materialization_plan_gate_smoke_report_hash(
    report: LegacySqlConnectorMaterializationPlanGateSmokeReport,
) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def run_legacy_sql_connector_materialization_plan_gate_smoke_from_env(
    environ: Mapping[str, str] | None = None,
) -> LegacySqlConnectorMaterializationPlanGateSmokeReport:
    env = os.environ if environ is None else environ
    checked_by = env.get(
        "SUITE_LEGACY_SQL_CONNECTOR_MATERIALIZATION_PLAN_GATE_CHECKED_BY",
        "legacy-sql-connector-materialization-plan-gate-smoke",
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
    review_gate = _build_ready_review_gate(
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
    gate = build_legacy_sql_connector_materialization_plan_gate(
        command=command,
        bundle=fetched_bundle,
        review_gate=review_gate,
        provider_profile_snapshot=provider_profile_snapshot,
        operator_mfa_snapshot=operator_mfa_snapshot,
        kill_switch_snapshot=kill_switch_snapshot,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=26),
    )
    review_gate_missing_blocked = _review_gate_missing_blocked(
        command=command,
        bundle=fetched_bundle,
        review_gate=review_gate,
        provider_profile_snapshot=provider_profile_snapshot,
        operator_mfa_snapshot=operator_mfa_snapshot,
        kill_switch_snapshot=kill_switch_snapshot,
        checked_by=checked_by,
        checked_at=checked_at + timedelta(seconds=27),
    )
    operator_mfa_missing_blocked = _operator_mfa_missing_blocked(
        command=command,
        bundle=fetched_bundle,
        review_gate=review_gate,
        provider_profile_snapshot=provider_profile_snapshot,
        operator_mfa_snapshot=operator_mfa_snapshot,
        kill_switch_snapshot=kill_switch_snapshot,
        checked_by=checked_by,
        checked_at=checked_at + timedelta(seconds=28),
    )
    kill_switch_disabled_blocked = _kill_switch_disabled_blocked(
        command=command,
        bundle=fetched_bundle,
        review_gate=review_gate,
        provider_profile_snapshot=provider_profile_snapshot,
        operator_mfa_snapshot=operator_mfa_snapshot,
        kill_switch_snapshot=kill_switch_snapshot,
        checked_by=checked_by,
        checked_at=checked_at + timedelta(seconds=29),
    )
    materialization_request_blocked = _materialization_request_blocked(
        command=command,
        bundle=fetched_bundle,
        review_gate=review_gate,
        provider_profile_snapshot=provider_profile_snapshot,
        operator_mfa_snapshot=operator_mfa_snapshot,
        kill_switch_snapshot=kill_switch_snapshot,
        checked_by=checked_by,
        checked_at=checked_at + timedelta(seconds=30),
    )
    materialization_plan_ready = (
        gate.gate_status == LegacySqlConnectorMaterializationPlanGateStatus.READY
        and gate.materialization_plan_ready
        and review_gate_missing_blocked
        and operator_mfa_missing_blocked
        and kill_switch_disabled_blocked
        and materialization_request_blocked
        and not gate.socket_materialization_allowed
        and not gate.secret_materialization_allowed
        and not gate.execution_implementation_allowed
        and not gate.real_connection_opened
    )
    draft = LegacySqlConnectorMaterializationPlanGateSmokeReport(
        tenant_id=fetched_bundle.tenant_id,
        store_backend=store_backend,
        policy_bundle_evidence_hash=fetched_bundle.evidence_hash,
        review_gate_evidence_hash=review_gate.evidence_hash,
        provider_profile_snapshot_hash=provider_profile_snapshot.evidence_hash,
        operator_mfa_snapshot_hash=operator_mfa_snapshot.evidence_hash,
        kill_switch_snapshot_hash=kill_switch_snapshot.evidence_hash,
        materialization_plan_gate_evidence_hash=gate.evidence_hash,
        materialization_plan_ready=materialization_plan_ready,
        review_gate_required=gate.review_gate_ready and gate.review_gate_bound,
        provider_profile_snapshot_required=(
            gate.provider_profile_snapshot_bound and gate.provider_metadata_only_boundary_attested
        ),
        operator_mfa_snapshot_required=gate.operator_mfa_verified and gate.operator_authorized_for_legacy_sql,
        kill_switch_snapshot_required=gate.kill_switch_armed and not gate.tenant_connection_disabled,
        review_gate_missing_blocked=review_gate_missing_blocked,
        operator_mfa_missing_blocked=operator_mfa_missing_blocked,
        kill_switch_disabled_blocked=kill_switch_disabled_blocked,
        materialization_request_blocked=materialization_request_blocked,
        future_socket_materialization_implementation_gate_required=(
            gate.future_socket_materialization_implementation_gate_required
        ),
        future_secret_materialization_implementation_gate_required=(
            gate.future_secret_materialization_implementation_gate_required
        ),
        future_execution_implementation_required=gate.future_execution_implementation_required,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    _assert_materialization_plan_safe(draft)
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_materialization_plan_gate_smoke_report_hash(draft)}
    )


def exit_code_for_report(report: LegacySqlConnectorMaterializationPlanGateSmokeReport) -> int:
    return 0 if report.materialization_plan_ready else 1


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Legacy SQL materialization plan gate smoke.")
    parser.add_argument(
        "--once", action="store_true", help="Run one non-executing materialization plan smoke and exit."
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the materialization plan report.")
    args = parser.parse_args(argv)
    del args.once

    report = run_legacy_sql_connector_materialization_plan_gate_smoke_from_env()
    print(json.dumps(report.model_dump(mode="json"), indent=2 if args.pretty else None, sort_keys=True))
    raise SystemExit(exit_code_for_report(report))


def _build_ready_review_gate(
    *,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    checked_by: str,
    checked_at: datetime,
) -> LegacySqlConnectorExecutionReadinessReviewGateEvidence:
    human_review = build_legacy_sql_connector_execution_readiness_human_review(
        bundle=bundle,
        reviewer_principal_ref="principal:legacy-sql-execution-reviewer",
        review_ticket_ref="review-ticket:legacy-sql-execution-readiness",
        approval_reference="approval:legacy-sql-execution-readiness",
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    change_control = build_legacy_sql_connector_execution_readiness_change_control(
        bundle=bundle,
        change_request_ref="change-request:legacy-sql-execution-readiness",
        maintenance_window_ref="maintenance-window:legacy-sql-execution-readiness",
        rollback_plan_ref="rollback-plan:legacy-sql-execution-readiness",
        risk_acceptance_ref="risk-acceptance:legacy-sql-execution-readiness",
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=1),
    )
    restore_drill = build_legacy_sql_connector_execution_readiness_restore_drill(
        bundle=bundle,
        restore_drill_report_hash="sha256:" + "8" * 64,
        backup_verification_hash="sha256:" + "9" * 64,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=2),
    )
    command = build_legacy_sql_connector_execution_readiness_review_gate_command(
        bundle=bundle,
        human_review=human_review,
        change_control=change_control,
        restore_drill=restore_drill,
        requested_by=checked_by,
    )
    return build_legacy_sql_connector_execution_readiness_review_gate(
        command=command,
        bundle=bundle,
        human_review=human_review,
        change_control=change_control,
        restore_drill=restore_drill,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=3),
    )


def _review_gate_bound(
    *,
    command: LegacySqlConnectorMaterializationPlanGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    review_gate: LegacySqlConnectorExecutionReadinessReviewGateEvidence,
) -> bool:
    return (
        command.tenant_id == bundle.tenant_id == review_gate.tenant_id
        and command.module_id == bundle.module_id == review_gate.module_id
        and command.source_system_ref == bundle.source_system_ref == review_gate.source_system_ref
        and command.connector_kind == bundle.connector_kind == review_gate.connector_kind
        and command.policy_bundle_evidence_hash == bundle.evidence_hash == review_gate.policy_bundle_evidence_hash
        and command.executor_contract_evidence_hash
        == bundle.executor_contract_evidence_hash
        == review_gate.executor_contract_evidence_hash
        and review_gate.kill_switch_policy_hash == bundle.kill_switch_policy_hash
        and not review_gate.socket_materialization_planning_allowed
        and not review_gate.secret_materialization_planning_allowed
        and not review_gate.network_socket_opened
        and not review_gate.secret_material_resolved
    )


def _provider_profile_snapshot_bound(
    *,
    command: LegacySqlConnectorMaterializationPlanGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    snapshot: LegacySqlConnectorMaterializationProviderProfileSnapshot,
) -> bool:
    return (
        command.tenant_id == bundle.tenant_id == snapshot.tenant_id
        and command.module_id == bundle.module_id == snapshot.module_id
        and command.source_system_ref == bundle.source_system_ref == snapshot.source_system_ref
        and command.connector_kind == bundle.connector_kind == snapshot.connector_kind
        and snapshot.sandbox_profile_ref == bundle.sandbox_profile_ref
        and snapshot.sandbox_profile_evidence_hash == bundle.sandbox_profile_evidence_hash
        and snapshot.preflight_evidence_hash == bundle.preflight_evidence_hash
        and snapshot.provider_attestation_adapter_evidence_hash
        == bundle.executor_contract.provider_attestation_adapter_evidence_hash
        and snapshot.provider_attestation_hash == bundle.executor_contract.provider_attestation_hash
        and not snapshot.network_connection_opened
        and not snapshot.secret_material_resolved
        and not snapshot.raw_data_access_allowed
    )


def _operator_mfa_snapshot_bound(
    *,
    command: LegacySqlConnectorMaterializationPlanGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    snapshot: LegacySqlConnectorMaterializationOperatorMfaSnapshot,
) -> bool:
    contract = bundle.executor_contract
    return (
        command.tenant_id == bundle.tenant_id == snapshot.tenant_id
        and command.module_id == bundle.module_id == snapshot.module_id
        and command.source_system_ref == bundle.source_system_ref == snapshot.source_system_ref
        and command.connector_kind == bundle.connector_kind == snapshot.connector_kind
        and snapshot.operator_context_evidence_hash == contract.operator_context_evidence_hash
        and snapshot.operator_principal_ref == contract.operator_principal_ref
        and snapshot.operator_role_ref == contract.operator_role_ref
        and snapshot.change_request_ref == contract.change_request_ref
        and snapshot.maintenance_window_ref == contract.maintenance_window_ref
        and snapshot.approval_reference == contract.approval_reference
    )


def _kill_switch_snapshot_bound(
    *,
    command: LegacySqlConnectorMaterializationPlanGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    snapshot: LegacySqlConnectorMaterializationKillSwitchSnapshot,
) -> bool:
    policy = bundle.kill_switch_policy
    return (
        command.tenant_id == bundle.tenant_id == snapshot.tenant_id
        and command.module_id == bundle.module_id == snapshot.module_id
        and command.source_system_ref == bundle.source_system_ref == snapshot.source_system_ref
        and command.connector_kind == bundle.connector_kind == snapshot.connector_kind
        and snapshot.kill_switch_policy_hash == bundle.kill_switch_policy_hash
        and snapshot.kill_switch_policy_ref == policy.kill_switch_policy_ref
        and snapshot.tenant_kill_switch_ref == policy.tenant_kill_switch_ref
        and snapshot.global_kill_switch_ref == policy.global_kill_switch_ref
        and snapshot.manual_abort_ref == policy.manual_abort_ref
        and snapshot.incident_channel_ref == policy.incident_channel_ref
    )


def _materialization_plan_blocking_reasons(
    *,
    command: LegacySqlConnectorMaterializationPlanGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    review_gate_hash_valid: bool,
    review_gate_ready: bool,
    review_gate_bound: bool,
    provider_profile_snapshot_hash_valid: bool,
    provider_profile_snapshot_bound: bool,
    provider_profile_snapshot: LegacySqlConnectorMaterializationProviderProfileSnapshot,
    operator_mfa_snapshot_hash_valid: bool,
    operator_mfa_snapshot_bound: bool,
    operator_mfa_snapshot: LegacySqlConnectorMaterializationOperatorMfaSnapshot,
    kill_switch_snapshot_hash_valid: bool,
    kill_switch_snapshot_bound: bool,
    kill_switch_snapshot: LegacySqlConnectorMaterializationKillSwitchSnapshot,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if build_legacy_sql_connector_real_connection_executor_policy_bundle_hash(bundle) != bundle.evidence_hash:
        reasons.append("policy_bundle_hash_invalid")
    if bundle.bundle_status != LegacySqlConnectorRealConnectionExecutorStatus.READY:
        reasons.append("policy_bundle_not_ready")
    if not review_gate_hash_valid:
        reasons.append("review_gate_hash_invalid")
    if not review_gate_ready:
        reasons.append("review_gate_not_ready")
    if not review_gate_bound:
        reasons.append("review_gate_not_bound")
    if not provider_profile_snapshot_hash_valid:
        reasons.append("provider_profile_snapshot_hash_invalid")
    if not provider_profile_snapshot_bound:
        reasons.append("provider_profile_snapshot_not_bound")
    if not provider_profile_snapshot.provider_profiles_current:
        reasons.append("provider_profiles_not_current")
    if not provider_profile_snapshot.provider_metadata_only_boundary_attested:
        reasons.append("provider_metadata_only_boundary_not_attested")
    if not provider_profile_snapshot.network_profile_attested:
        reasons.append("network_profile_not_attested")
    if not provider_profile_snapshot.secret_resolver_profile_attested:
        reasons.append("secret_resolver_profile_not_attested")
    if not provider_profile_snapshot.audit_profile_attested:
        reasons.append("audit_profile_not_attested")
    if not operator_mfa_snapshot_hash_valid:
        reasons.append("operator_mfa_snapshot_hash_invalid")
    if not operator_mfa_snapshot_bound:
        reasons.append("operator_mfa_snapshot_not_bound")
    if not operator_mfa_snapshot.operator_authorized_for_legacy_sql:
        reasons.append("operator_not_authorized_for_legacy_sql")
    if not operator_mfa_snapshot.operator_mfa_verified:
        reasons.append("operator_mfa_not_verified")
    if not operator_mfa_snapshot.compliance_window_active:
        reasons.append("compliance_window_not_active")
    if operator_mfa_snapshot.break_glass_requested:
        reasons.append("break_glass_requires_separate_incident_gate")
    if not kill_switch_snapshot_hash_valid:
        reasons.append("kill_switch_snapshot_hash_invalid")
    if not kill_switch_snapshot_bound:
        reasons.append("kill_switch_snapshot_not_bound")
    if not kill_switch_snapshot.kill_switch_armed:
        reasons.append("kill_switch_not_armed")
    if kill_switch_snapshot.tenant_connection_disabled:
        reasons.append("tenant_connection_kill_switch_disabled")
    if kill_switch_snapshot.global_connection_disabled:
        reasons.append("global_connection_kill_switch_disabled")
    if kill_switch_snapshot.manual_abort_requested:
        reasons.append("manual_abort_requested")
    if not command.materialization_plan_requested:
        reasons.append("materialization_plan_not_requested")
    if command.socket_materialization_requested:
        reasons.append("socket_materialization_requires_future_implementation_gate")
    if command.secret_materialization_requested:
        reasons.append("secret_materialization_requires_future_implementation_gate")
    if command.execution_implementation_requested:
        reasons.append("execution_implementation_requires_future_gate")
    if command.raw_data_access_requested:
        reasons.append("raw_data_access_request_requires_separate_gate")
    if command.import_dry_run_requested:
        reasons.append("import_dry_run_request_requires_separate_gate")
    if command.import_write_requested:
        reasons.append("import_write_request_requires_separate_gate")
    if command.destructive_actions_requested:
        reasons.append("destructive_action_request_requires_separate_gate")
    return tuple(sorted(set(reasons)))


def _review_gate_missing_blocked(
    *,
    command: LegacySqlConnectorMaterializationPlanGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    review_gate: LegacySqlConnectorExecutionReadinessReviewGateEvidence,
    provider_profile_snapshot: LegacySqlConnectorMaterializationProviderProfileSnapshot,
    operator_mfa_snapshot: LegacySqlConnectorMaterializationOperatorMfaSnapshot,
    kill_switch_snapshot: LegacySqlConnectorMaterializationKillSwitchSnapshot,
    checked_by: str,
    checked_at: datetime,
) -> bool:
    blocked_review_gate = review_gate.model_copy(
        update={
            "gate_status": LegacySqlConnectorExecutionReadinessReviewGateStatus.BLOCKED,
            "execution_readiness_review_passed": False,
            "blocking_reasons": ("human_review_not_completed",),
            "checked_at_utc": checked_at,
            "evidence_hash": ZERO_HASH,
        }
    )
    blocked_review_gate = blocked_review_gate.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_execution_readiness_review_gate_hash(blocked_review_gate)}
    )
    blocked = build_legacy_sql_connector_materialization_plan_gate(
        command=command.model_copy(update={"review_gate_evidence_hash": blocked_review_gate.evidence_hash}),
        bundle=bundle,
        review_gate=blocked_review_gate,
        provider_profile_snapshot=provider_profile_snapshot,
        operator_mfa_snapshot=operator_mfa_snapshot,
        kill_switch_snapshot=kill_switch_snapshot,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        blocked.gate_status == LegacySqlConnectorMaterializationPlanGateStatus.BLOCKED
        and "review_gate_not_ready" in blocked.blocking_reasons
    )


def _operator_mfa_missing_blocked(
    *,
    command: LegacySqlConnectorMaterializationPlanGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    review_gate: LegacySqlConnectorExecutionReadinessReviewGateEvidence,
    provider_profile_snapshot: LegacySqlConnectorMaterializationProviderProfileSnapshot,
    operator_mfa_snapshot: LegacySqlConnectorMaterializationOperatorMfaSnapshot,
    kill_switch_snapshot: LegacySqlConnectorMaterializationKillSwitchSnapshot,
    checked_by: str,
    checked_at: datetime,
) -> bool:
    blocked_operator = operator_mfa_snapshot.model_copy(
        update={"operator_mfa_verified": False, "checked_at_utc": checked_at, "evidence_hash": ZERO_HASH}
    )
    blocked_operator = blocked_operator.model_copy(
        update={
            "evidence_hash": build_legacy_sql_connector_materialization_operator_mfa_snapshot_hash(blocked_operator)
        }
    )
    blocked = build_legacy_sql_connector_materialization_plan_gate(
        command=command.model_copy(update={"operator_mfa_snapshot_hash": blocked_operator.evidence_hash}),
        bundle=bundle,
        review_gate=review_gate,
        provider_profile_snapshot=provider_profile_snapshot,
        operator_mfa_snapshot=blocked_operator,
        kill_switch_snapshot=kill_switch_snapshot,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        blocked.gate_status == LegacySqlConnectorMaterializationPlanGateStatus.BLOCKED
        and "operator_mfa_not_verified" in blocked.blocking_reasons
    )


def _kill_switch_disabled_blocked(
    *,
    command: LegacySqlConnectorMaterializationPlanGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    review_gate: LegacySqlConnectorExecutionReadinessReviewGateEvidence,
    provider_profile_snapshot: LegacySqlConnectorMaterializationProviderProfileSnapshot,
    operator_mfa_snapshot: LegacySqlConnectorMaterializationOperatorMfaSnapshot,
    kill_switch_snapshot: LegacySqlConnectorMaterializationKillSwitchSnapshot,
    checked_by: str,
    checked_at: datetime,
) -> bool:
    blocked_kill_switch = kill_switch_snapshot.model_copy(
        update={"tenant_connection_disabled": True, "checked_at_utc": checked_at, "evidence_hash": ZERO_HASH}
    )
    blocked_kill_switch = blocked_kill_switch.model_copy(
        update={
            "evidence_hash": build_legacy_sql_connector_materialization_kill_switch_snapshot_hash(blocked_kill_switch)
        }
    )
    blocked = build_legacy_sql_connector_materialization_plan_gate(
        command=command.model_copy(update={"kill_switch_snapshot_hash": blocked_kill_switch.evidence_hash}),
        bundle=bundle,
        review_gate=review_gate,
        provider_profile_snapshot=provider_profile_snapshot,
        operator_mfa_snapshot=operator_mfa_snapshot,
        kill_switch_snapshot=blocked_kill_switch,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        blocked.gate_status == LegacySqlConnectorMaterializationPlanGateStatus.BLOCKED
        and "tenant_connection_kill_switch_disabled" in blocked.blocking_reasons
    )


def _materialization_request_blocked(
    *,
    command: LegacySqlConnectorMaterializationPlanGateCommand,
    bundle: LegacySqlConnectorRealConnectionExecutorPolicyBundle,
    review_gate: LegacySqlConnectorExecutionReadinessReviewGateEvidence,
    provider_profile_snapshot: LegacySqlConnectorMaterializationProviderProfileSnapshot,
    operator_mfa_snapshot: LegacySqlConnectorMaterializationOperatorMfaSnapshot,
    kill_switch_snapshot: LegacySqlConnectorMaterializationKillSwitchSnapshot,
    checked_by: str,
    checked_at: datetime,
) -> bool:
    blocked = build_legacy_sql_connector_materialization_plan_gate(
        command=command.model_copy(
            update={
                "socket_materialization_requested": True,
                "secret_materialization_requested": True,
                "execution_implementation_requested": True,
            }
        ),
        bundle=bundle,
        review_gate=review_gate,
        provider_profile_snapshot=provider_profile_snapshot,
        operator_mfa_snapshot=operator_mfa_snapshot,
        kill_switch_snapshot=kill_switch_snapshot,
        checked_by=checked_by,
        checked_at_utc=checked_at,
    )
    return (
        blocked.gate_status == LegacySqlConnectorMaterializationPlanGateStatus.BLOCKED
        and "socket_materialization_requires_future_implementation_gate" in blocked.blocking_reasons
        and "secret_materialization_requires_future_implementation_gate" in blocked.blocking_reasons
        and "execution_implementation_requires_future_gate" in blocked.blocking_reasons
        and not blocked.socket_materialization_allowed
        and not blocked.secret_materialization_allowed
        and not blocked.execution_implementation_allowed
    )


def _assert_materialization_plan_safe(value: BaseModel) -> None:
    payload = value.model_dump_json().lower()
    for fragment in FORBIDDEN_MATERIALIZATION_PLAN_FRAGMENTS:
        if fragment in payload:
            raise ValueError(f"legacy SQL materialization plan gate leaked forbidden fragment: {fragment}")


if __name__ == "__main__":
    main()
