from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.models import UserContext
from suite.operations.backup_failover import BackupFailoverPolicy, load_backup_failover_policy
from suite.operations.production_continuity_deployment_gate import (
    build_backup_failover_policy_hash,
    load_production_continuity_deployment_gate,
    production_continuity_deployment_gate_runtime_ready,
)

PRODUCTION_CONTINUITY_REQUIREMENTS_SCHEMA_VERSION: Literal["production_continuity_evidence_requirements.v1"] = (
    "production_continuity_evidence_requirements.v1"
)
PRODUCTION_CONTINUITY_GATE_STATUS_SCHEMA_VERSION: Literal["production_continuity_gate_status.v1"] = (
    "production_continuity_gate_status.v1"
)
PRODUCTION_CONTINUITY_EVIDENCE_SCHEMA_VERSION: Literal["production_continuity_deployment_evidence.v1"] = (
    "production_continuity_deployment_evidence.v1"
)
DEFAULT_BACKUP_FAILOVER_POLICY_PATH = (
    Path(__file__).resolve().parents[3] / "docs" / "operations" / "backup_failover_policy.json"
)


class ProductionContinuityReadModelUnavailable(RuntimeError):
    pass


class StrictReadModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ProductionContinuityGateState(StrEnum):
    MISSING = "missing"
    INVALID = "invalid"
    EXPIRED = "expired"
    BLOCKED = "blocked"
    READY = "ready"


class ProductionContinuityTargetRequirement(StrictReadModel):
    target_id: str
    rpo_minutes: int = Field(ge=0)
    rto_minutes: int = Field(ge=0)
    restore_drill_frequency_days: int = Field(ge=1)


class ProductionContinuityImplementationRequirement(StrictReadModel):
    capability_id: str
    allowed_implementation_ids: tuple[str, ...] = Field(min_length=1)


class ProductionContinuityEvidenceRequirementsResponse(StrictReadModel):
    tenant_id: str
    policy_schema_version: str
    policy_hash: str
    evidence_schema_version: Literal["production_continuity_deployment_evidence.v1"] = (
        PRODUCTION_CONTINUITY_EVIDENCE_SCHEMA_VERSION
    )
    required_section_ids: tuple[str, ...]
    required_control_ids: tuple[str, ...]
    critical_continuity_domain_ids: tuple[str, ...]
    target_requirements: tuple[ProductionContinuityTargetRequirement, ...]
    implementation_requirements: tuple[ProductionContinuityImplementationRequirement, ...]
    maximum_evidence_age_hours: int = Field(ge=1)
    minimum_postgres_instances: int = Field(ge=2)
    minimum_failure_domains: int = Field(ge=2)
    maximum_wal_archive_backlog_bytes: int = Field(ge=0)
    maximum_manual_promotion_minutes: int = Field(ge=1)
    maximum_cross_site_failover_minutes: int = Field(ge=1)
    maximum_kms_rpo_minutes: int = Field(ge=0)
    maximum_kms_rto_minutes: int = Field(ge=1)
    required_distinct_approval_count: Literal[3] = 3
    evidence_reference_format: Literal["sha256_only"] = "sha256_only"
    automatic_failover_requires_separate_drill: Literal[True] = True
    manual_promotion_evidence_required: Literal[True] = True
    evidence_submission_allowed: Literal[False] = False
    deployment_execution_allowed: Literal[False] = False
    failover_execution_allowed: Literal[False] = False
    content_included: Literal[False] = False
    secrets_included: Literal[False] = False
    schema_version: Literal["production_continuity_evidence_requirements.v1"] = (
        PRODUCTION_CONTINUITY_REQUIREMENTS_SCHEMA_VERSION
    )

    @field_validator("tenant_id", "policy_schema_version")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value:
            raise ValueError("production continuity requirements text must not be empty")
        return value

    @model_validator(mode="after")
    def require_metadata_only_non_executing_contract(self) -> Self:
        if not self.required_section_ids or not self.required_control_ids:
            raise ValueError("production continuity requirements must identify sections and controls")
        if self.evidence_submission_allowed or self.deployment_execution_allowed or self.failover_execution_allowed:
            raise ValueError("production continuity requirements must remain read-only")
        if self.content_included or self.secrets_included:
            raise ValueError("production continuity requirements must remain metadata-only")
        return self


class ProductionContinuityGateStatusResponse(StrictReadModel):
    tenant_id: str
    state: ProductionContinuityGateState
    report_configured: bool
    report_present: bool
    report_hash_verified: bool
    policy_binding_verified: bool
    evidence_freshness_verified: bool
    continuity_gate_ready: bool
    runtime_switch_requested: bool
    runtime_enablement_allowed: bool
    checked_at_utc: str
    report_checked_at_utc: str | None = None
    valid_until_utc: str | None = None
    blocking_reasons: tuple[str, ...]
    deployment_execution_allowed: Literal[False] = False
    failover_execution_allowed: Literal[False] = False
    pilot_traffic_allowed: Literal[False] = False
    business_write_allowed: Literal[False] = False
    content_included: Literal[False] = False
    secrets_included: Literal[False] = False
    schema_version: Literal["production_continuity_gate_status.v1"] = PRODUCTION_CONTINUITY_GATE_STATUS_SCHEMA_VERSION

    @model_validator(mode="after")
    def require_fail_closed_status(self) -> Self:
        if self.runtime_enablement_allowed and not (
            self.continuity_gate_ready
            and self.runtime_switch_requested
            and self.state == ProductionContinuityGateState.READY
        ):
            raise ValueError("runtime enablement requires a ready gate and an explicit switch request")
        if self.state == ProductionContinuityGateState.READY and self.blocking_reasons:
            raise ValueError("ready production continuity status must not contain blockers")
        if self.state != ProductionContinuityGateState.READY and not self.blocking_reasons:
            raise ValueError("non-ready production continuity status must contain blockers")
        if (
            self.deployment_execution_allowed
            or self.failover_execution_allowed
            or self.pilot_traffic_allowed
            or self.business_write_allowed
        ):
            raise ValueError("production continuity status must never authorize execution")
        if self.content_included or self.secrets_included:
            raise ValueError("production continuity status must remain metadata-only")
        return self


def build_production_continuity_evidence_requirements_response(
    *,
    user_context: UserContext,
    policy: BackupFailoverPolicy,
) -> ProductionContinuityEvidenceRequirementsResponse:
    gate_policy = policy.production_deployment_gate
    targets = tuple(
        ProductionContinuityTargetRequirement(
            target_id=target_id,
            rpo_minutes=policy.target(target_id).rpo_minutes,
            rto_minutes=policy.target(target_id).rto_hours * 60,
            restore_drill_frequency_days=policy.target(target_id).restore_drill_frequency_days,
        )
        for target_id in gate_policy.required_target_ids
    )
    implementations = tuple(
        ProductionContinuityImplementationRequirement(
            capability_id=requirement.capability_id,
            allowed_implementation_ids=tuple(sorted(requirement.implementation_ids)),
        )
        for requirement in sorted(gate_policy.reference_implementations, key=lambda item: item.capability_id)
    )
    critical_domains = tuple(
        sorted(domain.domain_id for domain in policy.continuity_domains if domain.criticality == "critical")
    )
    return ProductionContinuityEvidenceRequirementsResponse(
        tenant_id=user_context.tenant_id,
        policy_schema_version=policy.schema_version,
        policy_hash=build_backup_failover_policy_hash(policy),
        required_section_ids=(
            "postgres_pitr",
            "encrypted_offsite_backup",
            "ha_promotion",
            "cross_site_failover",
            "approvals",
        ),
        required_control_ids=gate_policy.required_control_ids,
        critical_continuity_domain_ids=critical_domains,
        target_requirements=targets,
        implementation_requirements=implementations,
        maximum_evidence_age_hours=gate_policy.maximum_evidence_age_hours,
        minimum_postgres_instances=gate_policy.minimum_postgres_instances,
        minimum_failure_domains=gate_policy.minimum_failure_domains,
        maximum_wal_archive_backlog_bytes=gate_policy.maximum_wal_archive_backlog_bytes,
        maximum_manual_promotion_minutes=gate_policy.maximum_manual_promotion_minutes,
        maximum_cross_site_failover_minutes=gate_policy.maximum_cross_site_failover_minutes,
        maximum_kms_rpo_minutes=gate_policy.maximum_kms_rpo_minutes,
        maximum_kms_rto_minutes=gate_policy.maximum_kms_rto_minutes,
    )


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("production continuity status timestamps must include a timezone")
    return value.astimezone(UTC)


def _runtime_switch_requested(environ: Mapping[str, str]) -> bool:
    return environ.get("SUITE_PRODUCTIVITY_PILOT_RUNTIME_ENABLED", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _status_response(
    *,
    user_context: UserContext,
    state: ProductionContinuityGateState,
    checked_at: datetime,
    runtime_switch_requested: bool,
    blocking_reasons: tuple[str, ...],
    report_configured: bool,
    report_present: bool,
    report_hash_verified: bool = False,
    policy_binding_verified: bool = False,
    evidence_freshness_verified: bool = False,
    continuity_gate_ready: bool = False,
    runtime_enablement_allowed: bool = False,
    report_checked_at_utc: str | None = None,
    valid_until_utc: str | None = None,
) -> ProductionContinuityGateStatusResponse:
    return ProductionContinuityGateStatusResponse(
        tenant_id=user_context.tenant_id,
        state=state,
        report_configured=report_configured,
        report_present=report_present,
        report_hash_verified=report_hash_verified,
        policy_binding_verified=policy_binding_verified,
        evidence_freshness_verified=evidence_freshness_verified,
        continuity_gate_ready=continuity_gate_ready,
        runtime_switch_requested=runtime_switch_requested,
        runtime_enablement_allowed=runtime_enablement_allowed,
        checked_at_utc=checked_at.isoformat(),
        report_checked_at_utc=report_checked_at_utc,
        valid_until_utc=valid_until_utc,
        blocking_reasons=blocking_reasons,
    )


def build_production_continuity_gate_status_response(
    *,
    user_context: UserContext,
    policy: BackupFailoverPolicy,
    report_path: Path | None,
    runtime_switch_requested: bool,
    checked_at: datetime | None = None,
) -> ProductionContinuityGateStatusResponse:
    checked = _aware_utc(checked_at or datetime.now(UTC))
    if report_path is None:
        return _status_response(
            user_context=user_context,
            state=ProductionContinuityGateState.MISSING,
            checked_at=checked,
            runtime_switch_requested=runtime_switch_requested,
            blocking_reasons=("production_continuity_gate_report_not_configured",),
            report_configured=False,
            report_present=False,
        )
    if not report_path.is_file():
        return _status_response(
            user_context=user_context,
            state=ProductionContinuityGateState.MISSING,
            checked_at=checked,
            runtime_switch_requested=runtime_switch_requested,
            blocking_reasons=("production_continuity_gate_report_missing",),
            report_configured=True,
            report_present=False,
        )
    try:
        gate = load_production_continuity_deployment_gate(report_path)
        report_checked_at = _aware_utc(datetime.fromisoformat(gate.checked_at_utc))
        valid_until = _aware_utc(datetime.fromisoformat(gate.valid_until_utc))
    except (OSError, ValueError):
        return _status_response(
            user_context=user_context,
            state=ProductionContinuityGateState.INVALID,
            checked_at=checked,
            runtime_switch_requested=runtime_switch_requested,
            blocking_reasons=("production_continuity_gate_report_invalid",),
            report_configured=True,
            report_present=True,
        )

    policy_binding_verified = (
        gate.backup_policy_schema_version == policy.schema_version
        and gate.backup_policy_hash == build_backup_failover_policy_hash(policy)
    )
    freshness_verified = report_checked_at <= checked <= valid_until
    runtime_gate_ready = production_continuity_deployment_gate_runtime_ready(
        gate=gate,
        policy=policy,
        checked_at=checked,
    )

    def loaded_status(
        *,
        state: ProductionContinuityGateState,
        blocking_reasons: tuple[str, ...],
        continuity_gate_ready: bool = False,
        runtime_enablement_allowed: bool = False,
    ) -> ProductionContinuityGateStatusResponse:
        return _status_response(
            user_context=user_context,
            state=state,
            checked_at=checked,
            runtime_switch_requested=runtime_switch_requested,
            blocking_reasons=blocking_reasons,
            report_configured=True,
            report_present=True,
            report_hash_verified=True,
            policy_binding_verified=policy_binding_verified,
            evidence_freshness_verified=freshness_verified,
            continuity_gate_ready=continuity_gate_ready,
            runtime_enablement_allowed=runtime_enablement_allowed,
            report_checked_at_utc=report_checked_at.isoformat(),
            valid_until_utc=valid_until.isoformat(),
        )

    if not policy_binding_verified:
        return loaded_status(
            state=ProductionContinuityGateState.INVALID,
            blocking_reasons=("production_continuity_gate_policy_binding_invalid",),
        )
    if report_checked_at > checked:
        return loaded_status(
            state=ProductionContinuityGateState.INVALID,
            blocking_reasons=("production_continuity_gate_report_future_dated",),
        )
    if checked > valid_until:
        return loaded_status(
            state=ProductionContinuityGateState.EXPIRED,
            blocking_reasons=("production_continuity_gate_report_expired",),
        )
    if not gate.deployment_ready:
        return loaded_status(
            state=ProductionContinuityGateState.BLOCKED,
            blocking_reasons=gate.blocking_reasons or ("production_continuity_gate_blocked",),
        )
    if not runtime_gate_ready:
        return loaded_status(
            state=ProductionContinuityGateState.INVALID,
            blocking_reasons=("production_continuity_gate_runtime_contract_invalid",),
        )
    return loaded_status(
        state=ProductionContinuityGateState.READY,
        blocking_reasons=(),
        continuity_gate_ready=True,
        runtime_enablement_allowed=runtime_switch_requested,
    )


def load_production_continuity_policy_from_environment(
    environ: Mapping[str, str] | None = None,
) -> BackupFailoverPolicy:
    env = os.environ if environ is None else environ
    policy_path = Path(env.get("SUITE_BACKUP_FAILOVER_POLICY_PATH", str(DEFAULT_BACKUP_FAILOVER_POLICY_PATH)).strip())
    try:
        return load_backup_failover_policy(policy_path)
    except (OSError, ValueError) as exc:
        raise ProductionContinuityReadModelUnavailable("Production continuity policy is unavailable") from exc


def build_production_continuity_gate_status_from_environment(
    *,
    user_context: UserContext,
    environ: Mapping[str, str] | None = None,
    checked_at: datetime | None = None,
) -> ProductionContinuityGateStatusResponse:
    env = os.environ if environ is None else environ
    policy = load_production_continuity_policy_from_environment(env)
    report_path_value = env.get("SUITE_PRODUCTION_CONTINUITY_GATE_REPORT_PATH", "").strip()
    return build_production_continuity_gate_status_response(
        user_context=user_context,
        policy=policy,
        report_path=Path(report_path_value) if report_path_value else None,
        runtime_switch_requested=_runtime_switch_requested(env),
        checked_at=checked_at,
    )
