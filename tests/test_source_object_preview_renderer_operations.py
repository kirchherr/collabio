from datetime import UTC, datetime

from suite.platform.source_object_preview_decisions import (
    InMemorySourceObjectPreviewDecisionLedger,
    SourceObjectPreviewDecisionEvidence,
    build_source_object_preview_decision_evidence,
)
from suite.platform.source_object_preview_renderer import (
    RENDERER_SANDBOX_BOUNDARIES,
    RENDERER_SANDBOX_WORKER_PROFILE_ID,
    RENDERER_SANDBOX_WORKER_QUEUE_ID,
    InMemorySourceObjectPreviewRendererEvidenceStore,
    SourceObjectPreviewRendererRunEvidence,
    build_source_object_preview_renderer_run_evidence,
    build_source_object_preview_renderer_worker_idempotency_key_hash,
)
from suite.platform.source_object_preview_renderer_operations import (
    SourceObjectPreviewRendererRecoveryTenantStatus,
    build_source_object_preview_renderer_recovery_drill_report,
    build_source_object_preview_renderer_recovery_drill_report_hash,
    exit_code_for_report,
)
from suite.storage.source_objects import SourceObjectType


def test_preview_renderer_recovery_drill_verifies_queue_idempotency_tenant_and_evidence_recovery() -> None:
    tenant_id = "tenant-preview-drill-ready"
    renderer_evidence = renderer_evidence_for_tenant(tenant_id=tenant_id)
    decision = decision_evidence_for_tenant(
        tenant_id=tenant_id,
        renderer_ref=renderer_evidence.renderer_sandbox_evidence_ref,
        renderer_verified=True,
    )
    report = build_source_object_preview_renderer_recovery_drill_report(
        preview_decision_ledger=InMemorySourceObjectPreviewDecisionLedger((decision,)),
        preview_renderer_evidence_store=InMemorySourceObjectPreviewRendererEvidenceStore((renderer_evidence,)),
        tenant_ids=(tenant_id,),
        checked_by="test-preview-renderer-drill",
        checked_at_utc=datetime(2026, 6, 17, tzinfo=UTC),
    )

    assert report.schema_version == "source_object_preview_renderer_recovery_drill_report.v1"
    assert report.ready_count == 1
    assert report.attention_required_count == 0
    assert report.no_evidence_count == 0
    assert report.failed_count == 0
    assert report.alert_required is False
    assert exit_code_for_report(report) == 0
    assert report.evidence_hash == build_source_object_preview_renderer_recovery_drill_report_hash(report)
    assert report.runbook_evidence.command_ref == "docker-compose:preview-renderer-drill"
    assert "worker_idempotency_replay_check" in report.runbook_evidence.required_smoke_tests
    assert "background_jobs_queues" in report.runbook_evidence.continuity_domains
    assert "preview renderer recovery drill report hash" in report.runbook_evidence.required_backup_evidence_artifacts

    result = report.tenant_results[0]
    assert result.status == SourceObjectPreviewRendererRecoveryTenantStatus.READY
    assert result.decision_evidence_count == 1
    assert result.renderer_evidence_count == 1
    assert result.verified_decision_renderer_refs == (renderer_evidence.renderer_sandbox_evidence_ref,)
    assert result.recovered_renderer_refs == (renderer_evidence.renderer_sandbox_evidence_ref,)
    assert result.missing_verified_renderer_refs == ()
    assert result.unverified_decision_renderer_refs == ()
    assert result.worker_queue_binding_refs == (renderer_evidence.worker_queue_binding_ref,)
    assert result.worker_idempotency_key_hashes == (renderer_evidence.worker_idempotency_key_hash,)
    assert result.worker_queue_resume_ok is True
    assert result.idempotency_replay_ok is True
    assert result.tenant_isolation_smoke_ok is True
    assert result.content_boundary_ok is True
    assert result.metadata_only_recovery_ok is True
    assert result.blocking_reasons == ()
    assert "source content" not in report.model_dump_json()
    assert "mail body" not in report.model_dump_json()


def test_preview_renderer_recovery_drill_blocks_when_verified_renderer_ref_is_missing() -> None:
    tenant_id = "tenant-preview-drill-missing"
    missing_renderer_ref = "renderer-sandbox:sha256:" + "9" * 64
    decision = decision_evidence_for_tenant(
        tenant_id=tenant_id,
        renderer_ref=missing_renderer_ref,
        renderer_verified=True,
    )

    report = build_source_object_preview_renderer_recovery_drill_report(
        preview_decision_ledger=InMemorySourceObjectPreviewDecisionLedger((decision,)),
        preview_renderer_evidence_store=InMemorySourceObjectPreviewRendererEvidenceStore(),
        tenant_ids=(tenant_id,),
        checked_at_utc=datetime(2026, 6, 17, tzinfo=UTC),
    )

    result = report.tenant_results[0]
    assert report.alert_required is True
    assert exit_code_for_report(report) == 1
    assert result.status == SourceObjectPreviewRendererRecoveryTenantStatus.ATTENTION_REQUIRED
    assert result.missing_verified_renderer_refs == (missing_renderer_ref,)
    assert "preview_renderer_evidence_not_found" in result.blocking_reasons
    assert "verified_renderer_evidence_missing_after_restore" in result.blocking_reasons
    assert result.metadata_only_recovery_ok is False


def test_preview_renderer_recovery_drill_detects_idempotency_replay_mismatch() -> None:
    tenant_id = "tenant-preview-drill-idempotency"
    renderer_evidence = renderer_evidence_for_tenant(tenant_id=tenant_id).model_copy(
        update={
            "worker_idempotency_key_hash": "sha256:" + "0" * 64,
            "worker_job_id": "preview-renderer-job:sha256:" + "0" * 64,
            "worker_queue_binding_ref": f"worker-queue:{RENDERER_SANDBOX_WORKER_QUEUE_ID}:sha256:" + "0" * 64,
        }
    )
    decision = decision_evidence_for_tenant(
        tenant_id=tenant_id,
        renderer_ref=renderer_evidence.renderer_sandbox_evidence_ref,
        renderer_verified=True,
    )

    report = build_source_object_preview_renderer_recovery_drill_report(
        preview_decision_ledger=InMemorySourceObjectPreviewDecisionLedger((decision,)),
        preview_renderer_evidence_store=InMemorySourceObjectPreviewRendererEvidenceStore((renderer_evidence,)),
        tenant_ids=(tenant_id,),
        checked_at_utc=datetime(2026, 6, 17, tzinfo=UTC),
    )

    result = report.tenant_results[0]
    assert report.alert_required is True
    assert result.status == SourceObjectPreviewRendererRecoveryTenantStatus.ATTENTION_REQUIRED
    assert result.worker_queue_resume_ok is True
    assert result.idempotency_replay_ok is False
    assert "worker_idempotency_replay_mismatch" in result.blocking_reasons


def test_preview_renderer_recovery_drill_marks_tenant_without_evidence() -> None:
    report = build_source_object_preview_renderer_recovery_drill_report(
        preview_decision_ledger=InMemorySourceObjectPreviewDecisionLedger(),
        preview_renderer_evidence_store=InMemorySourceObjectPreviewRendererEvidenceStore(),
        tenant_ids=("tenant-empty",),
        checked_at_utc=datetime(2026, 6, 17, tzinfo=UTC),
    )

    result = report.tenant_results[0]
    assert report.no_evidence_count == 1
    assert report.alert_required is True
    assert result.status == SourceObjectPreviewRendererRecoveryTenantStatus.NO_EVIDENCE
    assert "preview_decision_evidence_not_found" in result.blocking_reasons
    assert "preview_renderer_evidence_not_found" in result.blocking_reasons


def renderer_evidence_for_tenant(*, tenant_id: str) -> SourceObjectPreviewRendererRunEvidence:
    source_object_id = f"doc-{tenant_id}"
    parser_ref = f"parser-sanitizer:{tenant_id}"
    backup_ref = f"backup:{tenant_id}"
    restore_ref = f"restore-drill:{tenant_id}"
    worker_idempotency_key_hash = build_source_object_preview_renderer_worker_idempotency_key_hash(
        tenant_id=tenant_id,
        source_object_id=source_object_id,
        source_version_id="v1",
        preview_slot_id="office.document.preview.metadata",
        preview_policy_id="preview-policy.document.metadata-first.v1",
        parser_sanitizer_evidence_ref=parser_ref,
        backup_coverage_evidence_ref=backup_ref,
        restore_evidence_ref=restore_ref,
    )
    return build_source_object_preview_renderer_run_evidence(
        tenant_id=tenant_id,
        source_object_id=source_object_id,
        source_version_id="v1",
        source_object_type=SourceObjectType.DOCUMENT,
        source_manifest_hash="sha256:" + "1" * 64,
        source_content_hash="sha256:" + "2" * 64,
        source_acl_version=1,
        preview_slot_id="office.document.preview.metadata",
        preview_policy_id="preview-policy.document.metadata-first.v1",
        gate_id="office.document.preview.gate.v1",
        parser_profile_id="rich-document-parser-worker:1",
        sanitizer_profile_id="document-preview-sanitizer:metadata-first.v1",
        worker_profile_id=RENDERER_SANDBOX_WORKER_PROFILE_ID,
        worker_queue_id=RENDERER_SANDBOX_WORKER_QUEUE_ID,
        worker_job_id=f"preview-renderer-job:{worker_idempotency_key_hash}",
        worker_idempotency_key_hash=worker_idempotency_key_hash,
        worker_queue_binding_ref=f"worker-queue:{RENDERER_SANDBOX_WORKER_QUEUE_ID}:{worker_idempotency_key_hash}",
        parser_sanitizer_evidence_ref=parser_ref,
        backup_coverage_evidence_ref=backup_ref,
        restore_evidence_ref=restore_ref,
        sandbox_boundaries=RENDERER_SANDBOX_BOUNDARIES,
        source_detail_audit_event_id=f"audit:detail:{tenant_id}",
        audit_event_id=f"audit:renderer:{tenant_id}",
        requested_by=f"user-{tenant_id}",
        reason_hash="sha256:" + "3" * 64,
    )


def decision_evidence_for_tenant(
    *,
    tenant_id: str,
    renderer_ref: str,
    renderer_verified: bool,
) -> SourceObjectPreviewDecisionEvidence:
    provided_evidence = [
        "tenant_preview_policy_enabled",
        "source_object_acl_checked",
        "source_detail_audit_event",
        "parser_sanitizer_evidence",
        "human_content_release_confirmation",
        "backup_coverage_evidence",
        "restore_drill_evidence",
    ]
    if renderer_verified:
        provided_evidence.append("renderer_sandbox_worker_evidence")
    return build_source_object_preview_decision_evidence(
        tenant_id=tenant_id,
        source_object_id=f"doc-{tenant_id}",
        source_version_id="v1",
        source_object_type=SourceObjectType.DOCUMENT,
        preview_slot_id="office.document.preview.metadata",
        preview_policy_id="preview-policy.document.metadata-first.v1",
        tenant_preview_policy_enabled=True,
        required_content_release_evidence=(
            "tenant_preview_policy_enabled",
            "source_object_acl_checked",
            "source_detail_audit_event",
            "parser_sanitizer_evidence",
            "human_content_release_confirmation",
            "renderer_sandbox_worker_evidence",
            "backup_coverage_evidence",
            "restore_drill_evidence",
        ),
        provided_evidence=tuple(provided_evidence),
        provided_evidence_refs=(
            f"tenant_policy:{tenant_id}:content_preview_enabled",
            f"acl:source_object:doc-{tenant_id}:v1",
            f"audit:detail:{tenant_id}",
            f"parser-sanitizer:{tenant_id}",
            renderer_ref,
            f"backup:{tenant_id}",
            f"restore-drill:{tenant_id}",
            f"approval:{tenant_id}",
        ),
        missing_evidence=() if renderer_verified else ("renderer_sandbox_worker_evidence",),
        blocking_reasons=("content_preview_skeleton_blocks_release_until_renderer_operational",),
        parser_profile_id="rich-document-parser-worker:1",
        sanitizer_profile_id="document-preview-sanitizer:metadata-first.v1",
        renderer_sandbox_evidence_ref=renderer_ref,
        backup_coverage_evidence_ref=f"backup:{tenant_id}",
        restore_evidence_ref=f"restore-drill:{tenant_id}",
        human_confirmation_reference=f"approval:{tenant_id}",
        renderer_sandbox_evidence_verified=renderer_verified,
        backup_coverage_evidence_verified=True,
        restore_evidence_verified=True,
        human_confirmation_verified=True,
        content_release_evidence_complete=renderer_verified,
        source_detail_audit_event_id=f"audit:detail:{tenant_id}",
        audit_event_id=f"audit:decision:{tenant_id}",
        requested_by=f"user-{tenant_id}",
        reason_hash="sha256:" + "4" * 64,
    )
