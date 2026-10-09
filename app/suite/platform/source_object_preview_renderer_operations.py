from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.platform.source_object_preview_decisions import (
    SourceObjectPreviewDecisionEvidence,
    SourceObjectPreviewDecisionLedger,
    build_default_source_object_preview_decision_ledger,
)
from suite.platform.source_object_preview_renderer import (
    RENDERER_SANDBOX_WORKER_QUEUE_ID,
    SourceObjectPreviewRendererEvidenceStore,
    SourceObjectPreviewRendererRunEvidence,
    build_default_source_object_preview_renderer_evidence_store,
    build_source_object_preview_renderer_worker_idempotency_key_hash,
)
from suite.platform.storage_paths import suite_data_dir

PREVIEW_RENDERER_RECOVERY_DRILL_SCHEMA_VERSION = "source_object_preview_renderer_recovery_drill_report.v1"
PREVIEW_RENDERER_RECOVERY_CONTINUITY_DOMAINS = (
    "postgres_metadata",
    "audit_evidence",
    "background_jobs_queues",
)
PREVIEW_RENDERER_REQUIRED_BACKUP_EVIDENCE_ARTIFACTS = (
    "source object preview decision evidence",
    "source object preview renderer sandbox evidence",
    "preview renderer worker queue bindings",
    "preview renderer idempotency key hashes",
    "preview renderer recovery drill report hash",
)


class SourceObjectPreviewRendererRecoveryTenantStatus(StrEnum):
    READY = "ready"
    NO_EVIDENCE = "no_evidence"
    ATTENTION_REQUIRED = "attention_required"
    FAILED = "failed"


class SourceObjectPreviewRendererRecoveryTenantResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    status: SourceObjectPreviewRendererRecoveryTenantStatus
    decision_evidence_count: int = Field(ge=0)
    renderer_evidence_count: int = Field(ge=0)
    verified_decision_renderer_refs: tuple[str, ...]
    recovered_renderer_refs: tuple[str, ...]
    missing_verified_renderer_refs: tuple[str, ...]
    unverified_decision_renderer_refs: tuple[str, ...]
    worker_queue_binding_refs: tuple[str, ...]
    worker_idempotency_key_hashes: tuple[str, ...]
    worker_queue_resume_ok: bool
    idempotency_replay_ok: bool
    tenant_isolation_smoke_ok: bool
    content_boundary_ok: bool
    metadata_only_recovery_ok: bool
    blocking_reasons: tuple[str, ...]
    last_error: str | None = None


class SourceObjectPreviewRendererRecoveryRunbookEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    checked_by: str
    checked_at_utc: datetime
    command_ref: str = "docker-compose:preview-renderer-drill"
    continuity_domains: tuple[str, ...] = PREVIEW_RENDERER_RECOVERY_CONTINUITY_DOMAINS
    required_backup_evidence_artifacts: tuple[str, ...] = PREVIEW_RENDERER_REQUIRED_BACKUP_EVIDENCE_ARTIFACTS
    selected_tenants: tuple[str, ...]
    required_smoke_tests: tuple[str, ...] = (
        "preview_decision_evidence_recovery",
        "preview_renderer_evidence_recovery",
        "worker_queue_resume_binding_check",
        "worker_idempotency_replay_check",
        "tenant_isolation_smoke_check",
        "metadata_only_boundary_check",
    )


class SourceObjectPreviewRendererRecoveryDrillReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = PREVIEW_RENDERER_RECOVERY_DRILL_SCHEMA_VERSION
    run_id: str
    checked_by: str
    checked_at_utc: datetime
    tenant_results: tuple[SourceObjectPreviewRendererRecoveryTenantResult, ...]
    ready_count: int = Field(ge=0)
    attention_required_count: int = Field(ge=0)
    no_evidence_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    alert_required: bool
    recommended_actions: tuple[str, ...]
    runbook_evidence: SourceObjectPreviewRendererRecoveryRunbookEvidence
    evidence_hash: str


def build_source_object_preview_renderer_recovery_drill_report(
    *,
    preview_decision_ledger: SourceObjectPreviewDecisionLedger,
    preview_renderer_evidence_store: SourceObjectPreviewRendererEvidenceStore,
    tenant_ids: Sequence[str],
    checked_by: str = "preview-renderer-drill",
    checked_at_utc: datetime | None = None,
) -> SourceObjectPreviewRendererRecoveryDrillReport:
    checked_at = checked_at_utc or datetime.now(UTC)
    selected_tenants = _clean_tenant_ids(tenant_ids)
    run_id = f"preview-renderer-drill-{uuid4().hex}"
    tenant_results = tuple(
        _tenant_recovery_result(
            tenant_id=tenant_id,
            preview_decision_ledger=preview_decision_ledger,
            preview_renderer_evidence_store=preview_renderer_evidence_store,
        )
        for tenant_id in selected_tenants
    )
    ready_count = _status_count(tenant_results, SourceObjectPreviewRendererRecoveryTenantStatus.READY)
    attention_required_count = _status_count(
        tenant_results,
        SourceObjectPreviewRendererRecoveryTenantStatus.ATTENTION_REQUIRED,
    )
    no_evidence_count = _status_count(tenant_results, SourceObjectPreviewRendererRecoveryTenantStatus.NO_EVIDENCE)
    failed_count = _status_count(tenant_results, SourceObjectPreviewRendererRecoveryTenantStatus.FAILED)
    recommended_actions = _recommended_actions(tenant_results)
    draft = SourceObjectPreviewRendererRecoveryDrillReport(
        run_id=run_id,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        tenant_results=tenant_results,
        ready_count=ready_count,
        attention_required_count=attention_required_count,
        no_evidence_count=no_evidence_count,
        failed_count=failed_count,
        alert_required=attention_required_count > 0 or no_evidence_count > 0 or failed_count > 0,
        recommended_actions=recommended_actions,
        runbook_evidence=SourceObjectPreviewRendererRecoveryRunbookEvidence(
            run_id=run_id,
            checked_by=checked_by,
            checked_at_utc=checked_at,
            selected_tenants=selected_tenants,
        ),
        evidence_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(
        update={
            "evidence_hash": build_source_object_preview_renderer_recovery_drill_report_hash(draft),
        }
    )


def build_source_object_preview_renderer_recovery_drill_report_hash(
    report: SourceObjectPreviewRendererRecoveryDrillReport,
) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def _status_count(
    tenant_results: Sequence[SourceObjectPreviewRendererRecoveryTenantResult],
    status: SourceObjectPreviewRendererRecoveryTenantStatus,
) -> int:
    return sum(1 for result in tenant_results if result.status == status)


def run_source_object_preview_renderer_recovery_drill_from_env(
    environ: Mapping[str, str] | None = None,
) -> SourceObjectPreviewRendererRecoveryDrillReport:
    env = os.environ if environ is None else environ
    data_dir = suite_data_dir()
    tenant_ids = _tenant_ids_from_env(env)
    return build_source_object_preview_renderer_recovery_drill_report(
        preview_decision_ledger=build_default_source_object_preview_decision_ledger(data_dir),
        preview_renderer_evidence_store=build_default_source_object_preview_renderer_evidence_store(data_dir),
        tenant_ids=tenant_ids,
        checked_by=env.get("SUITE_PREVIEW_RENDERER_DRILL_CHECKED_BY", "preview-renderer-drill"),
    )


def exit_code_for_report(report: SourceObjectPreviewRendererRecoveryDrillReport) -> int:
    return 1 if report.alert_required else 0


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the source object preview renderer recovery drill.")
    parser.add_argument("--once", action="store_true", help="Run one metadata-only drill and exit.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the metadata-only run report.")
    args = parser.parse_args(argv)
    del args.once

    report = run_source_object_preview_renderer_recovery_drill_from_env()
    print(json.dumps(report.model_dump(mode="json"), indent=2 if args.pretty else None, sort_keys=True))
    raise SystemExit(exit_code_for_report(report))


def _tenant_recovery_result(
    *,
    tenant_id: str,
    preview_decision_ledger: SourceObjectPreviewDecisionLedger,
    preview_renderer_evidence_store: SourceObjectPreviewRendererEvidenceStore,
) -> SourceObjectPreviewRendererRecoveryTenantResult:
    try:
        decisions = tuple(preview_decision_ledger.list_decisions(tenant_id=tenant_id))
        renderer_evidence = tuple(preview_renderer_evidence_store.list_evidence(tenant_id=tenant_id))
    except Exception as exc:  # pragma: no cover - report path for operational store failures.
        return SourceObjectPreviewRendererRecoveryTenantResult(
            tenant_id=tenant_id,
            status=SourceObjectPreviewRendererRecoveryTenantStatus.FAILED,
            decision_evidence_count=0,
            renderer_evidence_count=0,
            verified_decision_renderer_refs=(),
            recovered_renderer_refs=(),
            missing_verified_renderer_refs=(),
            unverified_decision_renderer_refs=(),
            worker_queue_binding_refs=(),
            worker_idempotency_key_hashes=(),
            worker_queue_resume_ok=False,
            idempotency_replay_ok=False,
            tenant_isolation_smoke_ok=False,
            content_boundary_ok=False,
            metadata_only_recovery_ok=False,
            blocking_reasons=("preview_renderer_recovery_store_error",),
            last_error=type(exc).__name__,
        )

    verified_refs = _verified_decision_renderer_refs(decisions)
    renderer_by_ref = {evidence.renderer_sandbox_evidence_ref: evidence for evidence in renderer_evidence}
    recovered_refs = tuple(ref for ref in verified_refs if ref in renderer_by_ref)
    missing_refs = tuple(ref for ref in verified_refs if ref not in renderer_by_ref)
    unverified_refs = _unverified_decision_renderer_refs(decisions)
    worker_queue_resume_ok = _worker_queue_resume_ok(renderer_evidence)
    idempotency_replay_ok = _idempotency_replay_ok(renderer_evidence)
    tenant_isolation_smoke_ok = _tenant_isolation_smoke_ok(
        tenant_id=tenant_id,
        decisions=decisions,
        renderer_evidence=renderer_evidence,
        preview_decision_ledger=preview_decision_ledger,
        preview_renderer_evidence_store=preview_renderer_evidence_store,
    )
    content_boundary_ok = _content_boundary_ok(renderer_evidence)
    blocking_reasons = _blocking_reasons(
        decisions=decisions,
        renderer_evidence=renderer_evidence,
        missing_refs=missing_refs,
        worker_queue_resume_ok=worker_queue_resume_ok,
        idempotency_replay_ok=idempotency_replay_ok,
        tenant_isolation_smoke_ok=tenant_isolation_smoke_ok,
        content_boundary_ok=content_boundary_ok,
    )
    status = _tenant_status(decisions=decisions, renderer_evidence=renderer_evidence, blocking_reasons=blocking_reasons)
    return SourceObjectPreviewRendererRecoveryTenantResult(
        tenant_id=tenant_id,
        status=status,
        decision_evidence_count=len(decisions),
        renderer_evidence_count=len(renderer_evidence),
        verified_decision_renderer_refs=verified_refs,
        recovered_renderer_refs=recovered_refs,
        missing_verified_renderer_refs=missing_refs,
        unverified_decision_renderer_refs=unverified_refs,
        worker_queue_binding_refs=tuple(sorted(evidence.worker_queue_binding_ref for evidence in renderer_evidence)),
        worker_idempotency_key_hashes=tuple(
            sorted(evidence.worker_idempotency_key_hash for evidence in renderer_evidence)
        ),
        worker_queue_resume_ok=worker_queue_resume_ok,
        idempotency_replay_ok=idempotency_replay_ok,
        tenant_isolation_smoke_ok=tenant_isolation_smoke_ok,
        content_boundary_ok=content_boundary_ok,
        metadata_only_recovery_ok=not blocking_reasons,
        blocking_reasons=blocking_reasons,
    )


def _verified_decision_renderer_refs(decisions: Sequence[SourceObjectPreviewDecisionEvidence]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                decision.renderer_sandbox_evidence_ref
                for decision in decisions
                if decision.renderer_sandbox_evidence_verified and decision.renderer_sandbox_evidence_ref is not None
            }
        )
    )


def _unverified_decision_renderer_refs(decisions: Sequence[SourceObjectPreviewDecisionEvidence]) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                decision.renderer_sandbox_evidence_ref
                for decision in decisions
                if (
                    not decision.renderer_sandbox_evidence_verified
                    and decision.renderer_sandbox_evidence_ref is not None
                )
            }
        )
    )


def _worker_queue_resume_ok(renderer_evidence: Sequence[SourceObjectPreviewRendererRunEvidence]) -> bool:
    return all(
        evidence.worker_queue_id == RENDERER_SANDBOX_WORKER_QUEUE_ID
        and evidence.worker_job_id == f"preview-renderer-job:{evidence.worker_idempotency_key_hash}"
        and evidence.worker_queue_binding_ref
        == f"worker-queue:{RENDERER_SANDBOX_WORKER_QUEUE_ID}:{evidence.worker_idempotency_key_hash}"
        for evidence in renderer_evidence
    )


def _idempotency_replay_ok(renderer_evidence: Sequence[SourceObjectPreviewRendererRunEvidence]) -> bool:
    seen: set[str] = set()
    for evidence in renderer_evidence:
        expected = build_source_object_preview_renderer_worker_idempotency_key_hash(
            tenant_id=evidence.tenant_id,
            source_object_id=evidence.source_object_id,
            source_version_id=evidence.source_version_id,
            preview_slot_id=evidence.preview_slot_id,
            preview_policy_id=evidence.preview_policy_id,
            parser_sanitizer_evidence_ref=evidence.parser_sanitizer_evidence_ref,
            backup_coverage_evidence_ref=evidence.backup_coverage_evidence_ref,
            restore_evidence_ref=evidence.restore_evidence_ref,
        )
        if evidence.worker_idempotency_key_hash != expected:
            return False
        if evidence.worker_idempotency_key_hash in seen:
            return False
        seen.add(evidence.worker_idempotency_key_hash)
    return True


def _tenant_isolation_smoke_ok(
    *,
    tenant_id: str,
    decisions: Sequence[SourceObjectPreviewDecisionEvidence],
    renderer_evidence: Sequence[SourceObjectPreviewRendererRunEvidence],
    preview_decision_ledger: SourceObjectPreviewDecisionLedger,
    preview_renderer_evidence_store: SourceObjectPreviewRendererEvidenceStore,
) -> bool:
    if any(decision.tenant_id != tenant_id for decision in decisions):
        return False
    if any(evidence.tenant_id != tenant_id for evidence in renderer_evidence):
        return False
    probe_tenant = f"{tenant_id}-isolation-probe"
    if decisions and _decision_visible_to_tenant(
        preview_decision_ledger=preview_decision_ledger,
        tenant_id=probe_tenant,
        evidence_hash=decisions[0].evidence_hash,
    ):
        return False
    return not (
        renderer_evidence
        and _renderer_evidence_visible_to_tenant(
            preview_renderer_evidence_store=preview_renderer_evidence_store,
            tenant_id=probe_tenant,
            evidence_hash=renderer_evidence[0].renderer_sandbox_evidence_hash,
        )
    )


def _decision_visible_to_tenant(
    *,
    preview_decision_ledger: SourceObjectPreviewDecisionLedger,
    tenant_id: str,
    evidence_hash: str,
) -> bool:
    try:
        preview_decision_ledger.get(tenant_id=tenant_id, evidence_hash=evidence_hash)
    except KeyError:
        return False
    return True


def _renderer_evidence_visible_to_tenant(
    *,
    preview_renderer_evidence_store: SourceObjectPreviewRendererEvidenceStore,
    tenant_id: str,
    evidence_hash: str,
) -> bool:
    try:
        preview_renderer_evidence_store.get(tenant_id=tenant_id, evidence_hash=evidence_hash)
    except KeyError:
        return False
    return True


def _content_boundary_ok(renderer_evidence: Sequence[SourceObjectPreviewRendererRunEvidence]) -> bool:
    return all(
        not evidence.rendering_allowed
        and not evidence.content_rendered
        and not evidence.content_included
        and not evidence.output_persisted
        and not evidence.external_fetch_allowed
        and evidence.temporary_workspace_destroyed
        for evidence in renderer_evidence
    )


def _blocking_reasons(
    *,
    decisions: Sequence[SourceObjectPreviewDecisionEvidence],
    renderer_evidence: Sequence[SourceObjectPreviewRendererRunEvidence],
    missing_refs: tuple[str, ...],
    worker_queue_resume_ok: bool,
    idempotency_replay_ok: bool,
    tenant_isolation_smoke_ok: bool,
    content_boundary_ok: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not decisions:
        reasons.append("preview_decision_evidence_not_found")
    if not renderer_evidence:
        reasons.append("preview_renderer_evidence_not_found")
    if missing_refs:
        reasons.append("verified_renderer_evidence_missing_after_restore")
    if not worker_queue_resume_ok:
        reasons.append("worker_queue_resume_binding_invalid")
    if not idempotency_replay_ok:
        reasons.append("worker_idempotency_replay_mismatch")
    if not tenant_isolation_smoke_ok:
        reasons.append("tenant_isolation_smoke_failed")
    if not content_boundary_ok:
        reasons.append("metadata_only_boundary_violation")
    return tuple(reasons)


def _tenant_status(
    *,
    decisions: Sequence[SourceObjectPreviewDecisionEvidence],
    renderer_evidence: Sequence[SourceObjectPreviewRendererRunEvidence],
    blocking_reasons: tuple[str, ...],
) -> SourceObjectPreviewRendererRecoveryTenantStatus:
    if not decisions and not renderer_evidence:
        return SourceObjectPreviewRendererRecoveryTenantStatus.NO_EVIDENCE
    if blocking_reasons:
        return SourceObjectPreviewRendererRecoveryTenantStatus.ATTENTION_REQUIRED
    return SourceObjectPreviewRendererRecoveryTenantStatus.READY


def _recommended_actions(tenant_results: Sequence[SourceObjectPreviewRendererRecoveryTenantResult]) -> tuple[str, ...]:
    actions: list[str] = []
    for result in tenant_results:
        if result.status == SourceObjectPreviewRendererRecoveryTenantStatus.READY:
            continue
        if result.status == SourceObjectPreviewRendererRecoveryTenantStatus.NO_EVIDENCE:
            actions.append(f"{result.tenant_id}: create preview decision and renderer evidence before restore drill")
            continue
        reasons = ",".join(result.blocking_reasons)
        actions.append(f"{result.tenant_id}: repair preview renderer recovery evidence ({reasons})")
    if not actions:
        actions.append("preview renderer decision evidence, queue bindings, and tenant isolation are recoverable")
    return tuple(actions)


def _tenant_ids_from_env(environ: Mapping[str, str]) -> tuple[str, ...]:
    value = environ.get("SUITE_PREVIEW_RENDERER_DRILL_TENANT_IDS", "tenant-demo")
    return _clean_tenant_ids(value.split(","))


def _clean_tenant_ids(tenant_ids: Sequence[str]) -> tuple[str, ...]:
    cleaned = tuple(tenant_id.strip() for tenant_id in tenant_ids if tenant_id.strip())
    return tuple(dict.fromkeys(cleaned))
