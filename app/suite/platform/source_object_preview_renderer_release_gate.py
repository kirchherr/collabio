from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.platform.source_object_preview_renderer_operations import (
    SourceObjectPreviewRendererRecoveryDrillReport,
    SourceObjectPreviewRendererRecoveryTenantStatus,
    build_source_object_preview_renderer_recovery_drill_report_hash,
)
from suite.platform.source_object_preview_renderer_smoke_contract import (
    SourceObjectPreviewRendererApiSmokeReport,
    build_source_object_preview_renderer_api_smoke_report_hash,
)
from suite.platform.storage_paths import suite_data_dir

PREVIEW_RENDERER_RELEASE_GATE_SCHEMA_VERSION = "source_object_preview_renderer_release_gate.v1"
PREVIEW_RENDERER_RELEASE_GATE_CONTINUITY_DOMAIN = "source_object_preview_renderer"
PREVIEW_RENDERER_RELEASE_GATE_REQUIRED_INPUTS = (
    "source_object_preview_renderer_api_smoke_report_hash",
    "source_object_preview_renderer_recovery_drill_report_hash",
)
PREVIEW_RENDERER_RELEASE_GATE_ALLOWED_HOURS = 24
PREVIEW_RENDERER_RELEASE_GATE_REF_PREFIX = "preview-renderer-release-gate"
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


class SourceObjectPreviewRendererReleaseGateEvidenceStore(Protocol):
    def append(
        self,
        evidence: SourceObjectPreviewRendererReleaseGateEvidence,
    ) -> SourceObjectPreviewRendererReleaseGateEvidence:
        raise NotImplementedError

    def get(self, *, tenant_id: str, evidence_hash: str) -> SourceObjectPreviewRendererReleaseGateEvidence:
        raise NotImplementedError

    def list_evidence(self, *, tenant_id: str) -> Sequence[SourceObjectPreviewRendererReleaseGateEvidence]:
        raise NotImplementedError


class InMemorySourceObjectPreviewRendererReleaseGateEvidenceStore:
    def __init__(self, evidences: Sequence[SourceObjectPreviewRendererReleaseGateEvidence] = ()) -> None:
        self._evidences: dict[tuple[str, str], SourceObjectPreviewRendererReleaseGateEvidence] = {}
        for evidence in evidences:
            self.append(evidence)

    def append(
        self,
        evidence: SourceObjectPreviewRendererReleaseGateEvidence,
    ) -> SourceObjectPreviewRendererReleaseGateEvidence:
        _require_valid_release_gate_hash(evidence)
        key = (evidence.tenant_id, evidence.evidence_hash)
        if key in self._evidences:
            raise ValueError("preview renderer release gate evidence already exists")
        self._evidences[key] = evidence
        return evidence

    def get(self, *, tenant_id: str, evidence_hash: str) -> SourceObjectPreviewRendererReleaseGateEvidence:
        try:
            return self._evidences[(tenant_id, evidence_hash)]
        except KeyError as exc:
            raise KeyError("preview renderer release gate evidence not found") from exc

    def list_evidence(self, *, tenant_id: str) -> Sequence[SourceObjectPreviewRendererReleaseGateEvidence]:
        return tuple(
            evidence for (stored_tenant_id, _), evidence in self._evidences.items() if stored_tenant_id == tenant_id
        )


class JsonlSourceObjectPreviewRendererReleaseGateEvidenceStore:
    def __init__(self, *, path: Path) -> None:
        self.path = path
        self._evidences: dict[tuple[str, str], SourceObjectPreviewRendererReleaseGateEvidence] = {}
        if not path.exists():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            evidence = SourceObjectPreviewRendererReleaseGateEvidence.model_validate_json(line)
            _require_valid_release_gate_hash(evidence)
            key = (evidence.tenant_id, evidence.evidence_hash)
            if key in self._evidences:
                raise ValueError("duplicate preview renderer release gate evidence in store")
            self._evidences[key] = evidence

    def append(
        self,
        evidence: SourceObjectPreviewRendererReleaseGateEvidence,
    ) -> SourceObjectPreviewRendererReleaseGateEvidence:
        _require_valid_release_gate_hash(evidence)
        key = (evidence.tenant_id, evidence.evidence_hash)
        if key in self._evidences:
            raise ValueError("preview renderer release gate evidence already exists")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(evidence.model_dump(mode="json"), sort_keys=True) + "\n")
        self._evidences[key] = evidence
        return evidence

    def get(self, *, tenant_id: str, evidence_hash: str) -> SourceObjectPreviewRendererReleaseGateEvidence:
        try:
            return self._evidences[(tenant_id, evidence_hash)]
        except KeyError as exc:
            raise KeyError("preview renderer release gate evidence not found") from exc

    def list_evidence(self, *, tenant_id: str) -> Sequence[SourceObjectPreviewRendererReleaseGateEvidence]:
        return tuple(
            evidence for (stored_tenant_id, _), evidence in self._evidences.items() if stored_tenant_id == tenant_id
        )


class PgSourceObjectPreviewRendererReleaseGateEvidenceStore:
    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    def append(
        self,
        evidence: SourceObjectPreviewRendererReleaseGateEvidence,
    ) -> SourceObjectPreviewRendererReleaseGateEvidence:
        _require_valid_release_gate_hash(evidence)
        try:
            with psycopg.connect(self.database_dsn) as connection:
                self._set_tenant(connection, evidence.tenant_id)
                connection.execute(
                    """
                    INSERT INTO collabio.source_object_preview_renderer_release_gate_evidence (
                        tenant_id,
                        api_smoke_report_hash,
                        recovery_drill_report_hash,
                        api_smoke_checked_at_utc,
                        recovery_drill_checked_at_utc,
                        evaluated_at_utc,
                        freshness_window_hours,
                        api_smoke_fresh,
                        recovery_drill_fresh,
                        api_smoke_passed,
                        recovery_drill_ready,
                        recovery_drill_bound,
                        tenant_ready,
                        metadata_only_boundary_verified,
                        renderer_connection_allowed,
                        viewer_connection_allowed,
                        content_release_workflow_allowed,
                        blocking_reasons,
                        gate_status,
                        gate_evidence,
                        evidence_hash,
                        schema_version
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    self._evidence_values(evidence),
                )
                connection.commit()
        except psycopg.errors.UniqueViolation as exc:
            raise ValueError("preview renderer release gate evidence already exists") from exc
        return evidence

    def get(self, *, tenant_id: str, evidence_hash: str) -> SourceObjectPreviewRendererReleaseGateEvidence:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            row = connection.execute(
                """
                SELECT gate_evidence
                FROM collabio.source_object_preview_renderer_release_gate_evidence
                WHERE tenant_id = %s
                  AND evidence_hash = %s
                """,
                (tenant_id, evidence_hash),
            ).fetchone()
        if row is None:
            raise KeyError("preview renderer release gate evidence not found")
        return self._evidence_from_row(row)

    def list_evidence(self, *, tenant_id: str) -> Sequence[SourceObjectPreviewRendererReleaseGateEvidence]:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            rows = connection.execute(
                """
                SELECT gate_evidence
                FROM collabio.source_object_preview_renderer_release_gate_evidence
                WHERE tenant_id = %s
                ORDER BY evaluated_at_utc, evidence_hash
                """,
                (tenant_id,),
            ).fetchall()
        return tuple(self._evidence_from_row(row) for row in rows)

    def _evidence_values(self, evidence: SourceObjectPreviewRendererReleaseGateEvidence) -> tuple[object, ...]:
        return (
            evidence.tenant_id,
            evidence.api_smoke_report_hash,
            evidence.recovery_drill_report_hash,
            evidence.api_smoke_checked_at_utc,
            evidence.recovery_drill_checked_at_utc,
            evidence.evaluated_at_utc,
            evidence.freshness_window_hours,
            evidence.api_smoke_fresh,
            evidence.recovery_drill_fresh,
            evidence.api_smoke_passed,
            evidence.recovery_drill_ready,
            evidence.recovery_drill_bound,
            evidence.tenant_ready,
            evidence.metadata_only_boundary_verified,
            evidence.renderer_connection_allowed,
            evidence.viewer_connection_allowed,
            evidence.content_release_workflow_allowed,
            Jsonb(list(evidence.blocking_reasons)),
            evidence.gate_status.value,
            Jsonb(evidence.model_dump(mode="json")),
            evidence.evidence_hash,
            evidence.schema_version,
        )

    def _evidence_from_row(self, row: tuple[Any, ...]) -> SourceObjectPreviewRendererReleaseGateEvidence:
        raw = row[0]
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        evidence = SourceObjectPreviewRendererReleaseGateEvidence.model_validate(parsed)
        _require_valid_release_gate_hash(evidence)
        return evidence

    def _set_tenant(self, connection: psycopg.Connection[Any], tenant_id: str) -> None:
        connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))


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


def require_source_object_preview_renderer_release_gate_for_wiring(
    *,
    gate: SourceObjectPreviewRendererReleaseGateEvidence,
    tenant_id: str,
    evidence_hash: str,
) -> SourceObjectPreviewRendererReleaseGateEvidence:
    if gate.tenant_id != tenant_id:
        raise ValueError("preview renderer release gate tenant does not match wiring tenant")
    if gate.evidence_hash != evidence_hash:
        raise ValueError("preview renderer release gate evidence hash does not match wiring hash")
    _require_valid_release_gate_hash(gate)
    return require_source_object_preview_renderer_release_gate_ready(gate)


def build_source_object_preview_renderer_release_gate_hash(
    evidence: SourceObjectPreviewRendererReleaseGateEvidence,
) -> str:
    return stable_hash(canonical_json(evidence.model_dump(mode="json", exclude={"evidence_hash"})))


def source_object_preview_renderer_release_gate_evidence_ref(
    evidence: SourceObjectPreviewRendererReleaseGateEvidence,
) -> str:
    return f"{PREVIEW_RENDERER_RELEASE_GATE_REF_PREFIX}:{evidence.evidence_hash}"


def build_default_source_object_preview_renderer_release_gate_evidence_store(
    data_dir: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> SourceObjectPreviewRendererReleaseGateEvidenceStore:
    env = os.environ if environ is None else environ
    backend = env.get("SUITE_SOURCE_PREVIEW_RENDERER_RELEASE_GATE_STORE_BACKEND", "jsonl").strip().lower()
    if backend in {"memory", "in_memory"}:
        return InMemorySourceObjectPreviewRendererReleaseGateEvidenceStore()
    if backend == "jsonl":
        path_value = env.get("SUITE_SOURCE_PREVIEW_RENDERER_RELEASE_GATE_STORE_PATH")
        path = (
            Path(path_value) if path_value else (data_dir or suite_data_dir()) / "preview_renderer_release_gates.jsonl"
        )
        return JsonlSourceObjectPreviewRendererReleaseGateEvidenceStore(path=path)
    if backend in {"postgres", "pg"}:
        database_dsn = env.get("SUITE_SOURCE_PREVIEW_RENDERER_RELEASE_GATE_STORE_DSN") or env.get("SUITE_DATABASE_DSN")
        if database_dsn is None:
            raise ValueError("Postgres preview renderer release gate store requires a database DSN")
        return PgSourceObjectPreviewRendererReleaseGateEvidenceStore(database_dsn=database_dsn)
    raise ValueError(f"Unsupported preview renderer release gate evidence store backend: {backend}")


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


def _require_valid_release_gate_hash(evidence: SourceObjectPreviewRendererReleaseGateEvidence) -> None:
    if build_source_object_preview_renderer_release_gate_hash(evidence) != evidence.evidence_hash:
        raise ValueError("preview renderer release gate evidence hash is invalid")
