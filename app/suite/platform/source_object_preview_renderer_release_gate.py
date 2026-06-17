from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.platform.source_object_preview_renderer_operations import (
    SourceObjectPreviewRendererRecoveryDrillReport,
    SourceObjectPreviewRendererRecoveryTenantStatus,
    build_source_object_preview_renderer_recovery_drill_report_hash,
)
from suite.platform.source_object_preview_renderer_smoke import (
    SourceObjectPreviewRendererApiSmokeReport,
    build_source_object_preview_renderer_api_smoke_report_hash,
)

PREVIEW_RENDERER_RELEASE_GATE_SCHEMA_VERSION = "source_object_preview_renderer_release_gate.v1"
PREVIEW_RENDERER_RELEASE_GATE_CONTINUITY_DOMAIN = "source_object_preview_renderer"
PREVIEW_RENDERER_RELEASE_GATE_REQUIRED_INPUTS = (
    "source_object_preview_renderer_api_smoke_report_hash",
    "source_object_preview_renderer_recovery_drill_report_hash",
)
PREVIEW_RENDERER_RELEASE_GATE_ALLOWED_HOURS = 24
SHA256_REF_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
ZERO_HASH = "sha256:" + "0" * 64


class SourceObjectPreviewRendererReleaseGateStatus(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"


class SourceObjectPreviewRendererReleaseGateEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = PREVIEW_RENDERER_RELEASE_GATE_SCHEMA_VERSION
    tenant_id: str
    continuity_domain: str = PREVIEW_RENDERER_RELEASE_GATE_CONTINUITY_DOMAIN
    required_evidence_inputs: tuple[str, ...] = PREVIEW_RENDERER_RELEASE_GATE_REQUIRED_INPUTS
    api_smoke_report_hash: str
    recovery_drill_report_hash: str
    api_smoke_checked_at_utc: datetime
    recovery_drill_checked_at_utc: datetime
    evaluated_at_utc: datetime
    freshness_window_hours: int = Field(gt=0, le=720)
    api_smoke_fresh: bool
    recovery_drill_fresh: bool
    api_smoke_passed: bool
    recovery_drill_ready: bool
    recovery_drill_bound: bool
    tenant_ready: bool
    metadata_only_boundary_verified: bool
    renderer_connection_allowed: bool
    viewer_connection_allowed: bool
    content_release_workflow_allowed: bool
    blocking_reasons: tuple[str, ...]
    gate_status: SourceObjectPreviewRendererReleaseGateStatus
    evidence_hash: str

    @field_validator("tenant_id")
    @classmethod
    def require_non_empty_tenant(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("preview renderer release gate tenant_id must not be empty")
        return value

    @field_validator("api_smoke_report_hash", "recovery_drill_report_hash", "evidence_hash")
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("preview renderer release gate hashes must be sha256 references")
        return value

    @field_validator("required_evidence_inputs")
    @classmethod
    def require_expected_inputs(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if value != PREVIEW_RENDERER_RELEASE_GATE_REQUIRED_INPUTS:
            raise ValueError("preview renderer release gate must require smoke and recovery drill hashes")
        return value

    @field_validator("blocking_reasons")
    @classmethod
    def validate_blocking_reasons(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("preview renderer release gate blocking reasons must be unique")
        for reason in value:
            if not reason.strip():
                raise ValueError("preview renderer release gate blocking reasons must not be empty")
        return value

    @model_validator(mode="after")
    def require_gate_consistency(self) -> SourceObjectPreviewRendererReleaseGateEvidence:
        allowed = (
            self.renderer_connection_allowed
            and self.viewer_connection_allowed
            and self.content_release_workflow_allowed
        )
        if self.continuity_domain != PREVIEW_RENDERER_RELEASE_GATE_CONTINUITY_DOMAIN:
            raise ValueError("preview renderer release gate must use the preview renderer continuity domain")
        if allowed and self.blocking_reasons:
            raise ValueError("preview renderer release gate cannot allow release wiring with blocking reasons")
        if allowed and self.gate_status != SourceObjectPreviewRendererReleaseGateStatus.READY:
            raise ValueError("preview renderer release gate allowed state must be ready")
        if not allowed and self.gate_status != SourceObjectPreviewRendererReleaseGateStatus.BLOCKED:
            raise ValueError("preview renderer release gate blocked state must be blocked")
        return self


def build_source_object_preview_renderer_release_gate(
    *,
    tenant_id: str,
    api_smoke_report: SourceObjectPreviewRendererApiSmokeReport,
    recovery_drill_report: SourceObjectPreviewRendererRecoveryDrillReport,
    evaluated_at_utc: datetime | None = None,
    freshness_window_hours: int = PREVIEW_RENDERER_RELEASE_GATE_ALLOWED_HOURS,
) -> SourceObjectPreviewRendererReleaseGateEvidence:
    evaluated_at = _aware(evaluated_at_utc or datetime.now(UTC))
    freshness_window = timedelta(hours=freshness_window_hours)
    api_smoke_checked_at = _aware(api_smoke_report.checked_at_utc)
    recovery_drill_checked_at = _aware(recovery_drill_report.checked_at_utc)
    tenant_result = next(
        (result for result in recovery_drill_report.tenant_results if result.tenant_id == tenant_id),
        None,
    )

    api_smoke_report_hash_valid = (
        build_source_object_preview_renderer_api_smoke_report_hash(api_smoke_report) == api_smoke_report.evidence_hash
    )
    recovery_drill_report_hash_valid = (
        build_source_object_preview_renderer_recovery_drill_report_hash(recovery_drill_report)
        == recovery_drill_report.evidence_hash
    )
    api_smoke_fresh = _fresh(checked_at=api_smoke_checked_at, evaluated_at=evaluated_at, window=freshness_window)
    recovery_drill_fresh = _fresh(
        checked_at=recovery_drill_checked_at,
        evaluated_at=evaluated_at,
        window=freshness_window,
    )
    recovery_drill_bound = (
        api_smoke_report.recovery_drill_report_hash == recovery_drill_report.evidence_hash
        and api_smoke_report.release_restore_evidence_ref
        == f"preview-renderer-recovery-drill:{recovery_drill_report.evidence_hash}"
    )
    recovery_drill_ready = (
        tenant_result is not None
        and tenant_result.status == SourceObjectPreviewRendererRecoveryTenantStatus.READY
        and tenant_result.metadata_only_recovery_ok
        and not tenant_result.blocking_reasons
    )
    tenant_ready = (
        api_smoke_report.tenant_id == tenant_id and tenant_result is not None and tenant_result.tenant_id == tenant_id
    )
    metadata_only_boundary_verified = (
        api_smoke_report.recovery_metadata_only_ok
        and tenant_result is not None
        and tenant_result.content_boundary_ok
        and tenant_result.metadata_only_recovery_ok
    )
    blocking_reasons = _release_gate_blocking_reasons(
        tenant_id=tenant_id,
        api_smoke_report=api_smoke_report,
        recovery_drill_report=recovery_drill_report,
        api_smoke_report_hash_valid=api_smoke_report_hash_valid,
        recovery_drill_report_hash_valid=recovery_drill_report_hash_valid,
        api_smoke_fresh=api_smoke_fresh,
        recovery_drill_fresh=recovery_drill_fresh,
        recovery_drill_bound=recovery_drill_bound,
        recovery_drill_ready=recovery_drill_ready,
        tenant_ready=tenant_ready,
        metadata_only_boundary_verified=metadata_only_boundary_verified,
    )
    release_allowed = not blocking_reasons
    draft = SourceObjectPreviewRendererReleaseGateEvidence(
        tenant_id=tenant_id,
        api_smoke_report_hash=api_smoke_report.evidence_hash,
        recovery_drill_report_hash=recovery_drill_report.evidence_hash,
        api_smoke_checked_at_utc=api_smoke_checked_at,
        recovery_drill_checked_at_utc=recovery_drill_checked_at,
        evaluated_at_utc=evaluated_at,
        freshness_window_hours=freshness_window_hours,
        api_smoke_fresh=api_smoke_fresh,
        recovery_drill_fresh=recovery_drill_fresh,
        api_smoke_passed=api_smoke_report.smoke_passed,
        recovery_drill_ready=recovery_drill_ready,
        recovery_drill_bound=recovery_drill_bound,
        tenant_ready=tenant_ready,
        metadata_only_boundary_verified=metadata_only_boundary_verified,
        renderer_connection_allowed=release_allowed,
        viewer_connection_allowed=release_allowed,
        content_release_workflow_allowed=release_allowed,
        blocking_reasons=blocking_reasons,
        gate_status=(
            SourceObjectPreviewRendererReleaseGateStatus.READY
            if release_allowed
            else SourceObjectPreviewRendererReleaseGateStatus.BLOCKED
        ),
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_source_object_preview_renderer_release_gate_hash(draft)})


def require_source_object_preview_renderer_release_gate_ready(
    gate: SourceObjectPreviewRendererReleaseGateEvidence,
) -> SourceObjectPreviewRendererReleaseGateEvidence:
    if (
        gate.gate_status != SourceObjectPreviewRendererReleaseGateStatus.READY
        or not gate.renderer_connection_allowed
        or not gate.viewer_connection_allowed
        or not gate.content_release_workflow_allowed
    ):
        reasons = ", ".join(gate.blocking_reasons) or "unknown"
        raise ValueError(f"preview renderer release gate is blocked: {reasons}")
    return gate


def build_source_object_preview_renderer_release_gate_hash(
    evidence: SourceObjectPreviewRendererReleaseGateEvidence,
) -> str:
    return stable_hash(canonical_json(evidence.model_dump(mode="json", exclude={"evidence_hash"})))


def _release_gate_blocking_reasons(
    *,
    tenant_id: str,
    api_smoke_report: SourceObjectPreviewRendererApiSmokeReport,
    recovery_drill_report: SourceObjectPreviewRendererRecoveryDrillReport,
    api_smoke_report_hash_valid: bool,
    recovery_drill_report_hash_valid: bool,
    api_smoke_fresh: bool,
    recovery_drill_fresh: bool,
    recovery_drill_bound: bool,
    recovery_drill_ready: bool,
    tenant_ready: bool,
    metadata_only_boundary_verified: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if api_smoke_report.tenant_id != tenant_id:
        reasons.append("api_smoke_tenant_mismatch")
    if not any(result.tenant_id == tenant_id for result in recovery_drill_report.tenant_results):
        reasons.append("recovery_drill_tenant_missing")
    if not tenant_ready:
        reasons.append("tenant_not_ready_for_release_gate")
    if not api_smoke_report_hash_valid:
        reasons.append("api_smoke_report_hash_invalid")
    if not recovery_drill_report_hash_valid:
        reasons.append("recovery_drill_report_hash_invalid")
    if not api_smoke_fresh:
        reasons.append("api_smoke_report_stale")
    if not recovery_drill_fresh:
        reasons.append("recovery_drill_report_stale")
    if not api_smoke_report.smoke_passed:
        reasons.append("api_smoke_not_passed")
    if api_smoke_report.recovery_tenant_status != SourceObjectPreviewRendererRecoveryTenantStatus.READY:
        reasons.append("api_smoke_recovery_status_not_ready")
    if not api_smoke_report.recovery_metadata_only_ok:
        reasons.append("api_smoke_metadata_boundary_not_verified")
    if not recovery_drill_ready:
        reasons.append("recovery_drill_not_ready")
    if not recovery_drill_bound:
        reasons.append("api_smoke_recovery_drill_hash_not_bound")
    if not metadata_only_boundary_verified:
        reasons.append("metadata_only_boundary_not_verified")
    return tuple(sorted(set(reasons)))


def _fresh(*, checked_at: datetime, evaluated_at: datetime, window: timedelta) -> bool:
    if checked_at > evaluated_at:
        return False
    return evaluated_at - checked_at <= window


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
