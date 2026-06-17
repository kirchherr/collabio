from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from suite.platform.source_object_preview_renderer_operations import (
    SourceObjectPreviewRendererRecoveryDrillReport,
    SourceObjectPreviewRendererRecoveryRunbookEvidence,
    SourceObjectPreviewRendererRecoveryTenantResult,
    SourceObjectPreviewRendererRecoveryTenantStatus,
    build_source_object_preview_renderer_recovery_drill_report_hash,
)
from suite.platform.source_object_preview_renderer_release_gate import (
    InMemorySourceObjectPreviewRendererReleaseGateEvidenceStore,
    JsonlSourceObjectPreviewRendererReleaseGateEvidenceStore,
    SourceObjectPreviewRendererReleaseGateStatus,
    build_source_object_preview_renderer_release_gate,
    build_source_object_preview_renderer_release_gate_hash,
    require_source_object_preview_renderer_release_gate_for_wiring,
    require_source_object_preview_renderer_release_gate_ready,
    source_object_preview_renderer_release_gate_evidence_ref,
)
from suite.platform.source_object_preview_renderer_smoke import (
    SourceObjectPreviewRendererApiSmokeReport,
    build_source_object_preview_renderer_api_smoke_report_hash,
)

ZERO_HASH = "sha256:" + "0" * 64


def test_preview_renderer_release_gate_allows_wiring_only_with_fresh_bound_reports() -> None:
    checked_at = datetime(2026, 6, 17, 10, tzinfo=UTC)
    evaluated_at = datetime(2026, 6, 17, 11, tzinfo=UTC)
    drill_report = ready_drill_report(tenant_id="tenant-release-ready", checked_at=checked_at)
    smoke_report = passed_smoke_report(
        tenant_id="tenant-release-ready",
        drill_report=drill_report,
        checked_at=checked_at + timedelta(minutes=5),
    )

    gate = build_source_object_preview_renderer_release_gate(
        tenant_id="tenant-release-ready",
        api_smoke_report=smoke_report,
        recovery_drill_report=drill_report,
        evaluated_at_utc=evaluated_at,
    )

    assert gate.schema_version == "source_object_preview_renderer_release_gate.v1"
    assert gate.gate_status == SourceObjectPreviewRendererReleaseGateStatus.READY
    assert gate.api_smoke_report_hash == smoke_report.evidence_hash
    assert gate.recovery_drill_report_hash == drill_report.evidence_hash
    assert gate.api_smoke_fresh is True
    assert gate.recovery_drill_fresh is True
    assert gate.api_smoke_passed is True
    assert gate.recovery_drill_ready is True
    assert gate.recovery_drill_bound is True
    assert gate.tenant_ready is True
    assert gate.metadata_only_boundary_verified is True
    assert gate.renderer_connection_allowed is True
    assert gate.viewer_connection_allowed is True
    assert gate.content_release_workflow_allowed is True
    assert gate.blocking_reasons == ()
    assert gate.required_evidence_inputs == (
        "source_object_preview_renderer_api_smoke_report_hash",
        "source_object_preview_renderer_recovery_drill_report_hash",
    )
    assert gate.evidence_hash == build_source_object_preview_renderer_release_gate_hash(gate)
    assert require_source_object_preview_renderer_release_gate_ready(gate) == gate
    assert (
        require_source_object_preview_renderer_release_gate_for_wiring(
            gate=gate,
            tenant_id="tenant-release-ready",
            evidence_hash=gate.evidence_hash,
        )
        == gate
    )
    assert source_object_preview_renderer_release_gate_evidence_ref(gate) == (
        f"preview-renderer-release-gate:{gate.evidence_hash}"
    )


def test_preview_renderer_release_gate_blocks_stale_reports() -> None:
    checked_at = datetime(2026, 6, 15, 10, tzinfo=UTC)
    evaluated_at = datetime(2026, 6, 17, 11, tzinfo=UTC)
    drill_report = ready_drill_report(tenant_id="tenant-release-stale", checked_at=checked_at)
    smoke_report = passed_smoke_report(
        tenant_id="tenant-release-stale",
        drill_report=drill_report,
        checked_at=checked_at,
    )

    gate = build_source_object_preview_renderer_release_gate(
        tenant_id="tenant-release-stale",
        api_smoke_report=smoke_report,
        recovery_drill_report=drill_report,
        evaluated_at_utc=evaluated_at,
        freshness_window_hours=24,
    )

    assert gate.gate_status == SourceObjectPreviewRendererReleaseGateStatus.BLOCKED
    assert gate.renderer_connection_allowed is False
    assert gate.viewer_connection_allowed is False
    assert gate.content_release_workflow_allowed is False
    assert "api_smoke_report_stale" in gate.blocking_reasons
    assert "recovery_drill_report_stale" in gate.blocking_reasons
    with pytest.raises(ValueError, match="api_smoke_report_stale"):
        require_source_object_preview_renderer_release_gate_ready(gate)


def test_preview_renderer_release_gate_blocks_unbound_smoke_and_drill_hashes() -> None:
    checked_at = datetime(2026, 6, 17, 10, tzinfo=UTC)
    drill_report = ready_drill_report(tenant_id="tenant-release-unbound", checked_at=checked_at)
    smoke_report = passed_smoke_report(
        tenant_id="tenant-release-unbound",
        drill_report=drill_report,
        checked_at=checked_at,
    ).model_copy(
        update={
            "recovery_drill_report_hash": "sha256:" + "9" * 64,
            "release_restore_evidence_ref": "preview-renderer-recovery-drill:sha256:" + "9" * 64,
        }
    )
    smoke_report = smoke_report.model_copy(
        update={"evidence_hash": build_source_object_preview_renderer_api_smoke_report_hash(smoke_report)}
    )

    gate = build_source_object_preview_renderer_release_gate(
        tenant_id="tenant-release-unbound",
        api_smoke_report=smoke_report,
        recovery_drill_report=drill_report,
        evaluated_at_utc=datetime(2026, 6, 17, 11, tzinfo=UTC),
    )

    assert gate.gate_status == SourceObjectPreviewRendererReleaseGateStatus.BLOCKED
    assert gate.recovery_drill_bound is False
    assert "api_smoke_recovery_drill_hash_not_bound" in gate.blocking_reasons


def test_preview_renderer_release_gate_blocks_hash_tampering_and_tenant_mismatch() -> None:
    checked_at = datetime(2026, 6, 17, 10, tzinfo=UTC)
    drill_report = ready_drill_report(tenant_id="tenant-release-real", checked_at=checked_at)
    smoke_report = passed_smoke_report(
        tenant_id="tenant-release-other",
        drill_report=drill_report,
        checked_at=checked_at,
    ).model_copy(update={"evidence_hash": "sha256:" + "8" * 64})

    gate = build_source_object_preview_renderer_release_gate(
        tenant_id="tenant-release-real",
        api_smoke_report=smoke_report,
        recovery_drill_report=drill_report,
        evaluated_at_utc=datetime(2026, 6, 17, 11, tzinfo=UTC),
    )

    assert gate.gate_status == SourceObjectPreviewRendererReleaseGateStatus.BLOCKED
    assert "api_smoke_report_hash_invalid" in gate.blocking_reasons
    assert "api_smoke_tenant_mismatch" in gate.blocking_reasons
    assert "tenant_not_ready_for_release_gate" in gate.blocking_reasons
    with pytest.raises(ValueError, match="api_smoke_report_hash_invalid"):
        require_source_object_preview_renderer_release_gate_for_wiring(
            gate=gate,
            tenant_id="tenant-release-real",
            evidence_hash=gate.evidence_hash,
        )


def test_preview_renderer_release_gate_blocks_failed_recovery_drill() -> None:
    checked_at = datetime(2026, 6, 17, 10, tzinfo=UTC)
    drill_report = blocked_drill_report(tenant_id="tenant-release-blocked", checked_at=checked_at)
    smoke_report = passed_smoke_report(
        tenant_id="tenant-release-blocked",
        drill_report=drill_report,
        checked_at=checked_at,
        smoke_passed=False,
        recovery_metadata_only_ok=False,
        recovery_tenant_status="attention_required",
    )

    gate = build_source_object_preview_renderer_release_gate(
        tenant_id="tenant-release-blocked",
        api_smoke_report=smoke_report,
        recovery_drill_report=drill_report,
        evaluated_at_utc=datetime(2026, 6, 17, 11, tzinfo=UTC),
    )

    assert gate.gate_status == SourceObjectPreviewRendererReleaseGateStatus.BLOCKED
    assert gate.recovery_drill_ready is False
    assert gate.metadata_only_boundary_verified is False
    assert "api_smoke_not_passed" in gate.blocking_reasons
    assert "api_smoke_recovery_status_not_ready" in gate.blocking_reasons
    assert "metadata_only_boundary_not_verified" in gate.blocking_reasons
    assert "recovery_drill_not_ready" in gate.blocking_reasons


def test_preview_renderer_release_gate_store_persists_hash_valid_tenant_scoped_evidence(tmp_path: Path) -> None:
    checked_at = datetime(2026, 6, 17, 10, tzinfo=UTC)
    drill_report = ready_drill_report(tenant_id="tenant-release-store", checked_at=checked_at)
    smoke_report = passed_smoke_report(
        tenant_id="tenant-release-store",
        drill_report=drill_report,
        checked_at=checked_at + timedelta(minutes=5),
    )
    gate = build_source_object_preview_renderer_release_gate(
        tenant_id="tenant-release-store",
        api_smoke_report=smoke_report,
        recovery_drill_report=drill_report,
        evaluated_at_utc=datetime(2026, 6, 17, 11, tzinfo=UTC),
    )
    path = tmp_path / "preview_renderer_release_gates.jsonl"
    store = JsonlSourceObjectPreviewRendererReleaseGateEvidenceStore(path=path)

    persisted = store.append(gate)
    reloaded = JsonlSourceObjectPreviewRendererReleaseGateEvidenceStore(path=path)

    assert persisted.evidence_hash == gate.evidence_hash
    assert reloaded.get(tenant_id="tenant-release-store", evidence_hash=gate.evidence_hash) == gate
    assert reloaded.list_evidence(tenant_id="tenant-release-store") == (gate,)
    assert reloaded.list_evidence(tenant_id="tenant-other") == ()


def test_preview_renderer_release_gate_store_rejects_tampered_evidence() -> None:
    checked_at = datetime(2026, 6, 17, 10, tzinfo=UTC)
    drill_report = ready_drill_report(tenant_id="tenant-release-tampered", checked_at=checked_at)
    smoke_report = passed_smoke_report(
        tenant_id="tenant-release-tampered",
        drill_report=drill_report,
        checked_at=checked_at + timedelta(minutes=5),
    )
    gate = build_source_object_preview_renderer_release_gate(
        tenant_id="tenant-release-tampered",
        api_smoke_report=smoke_report,
        recovery_drill_report=drill_report,
        evaluated_at_utc=datetime(2026, 6, 17, 11, tzinfo=UTC),
    ).model_copy(update={"renderer_connection_allowed": False})
    store = InMemorySourceObjectPreviewRendererReleaseGateEvidenceStore()

    with pytest.raises(ValueError, match="evidence hash is invalid"):
        store.append(gate)


def test_preview_renderer_release_gate_wiring_requires_matching_tenant_and_hash() -> None:
    checked_at = datetime(2026, 6, 17, 10, tzinfo=UTC)
    drill_report = ready_drill_report(tenant_id="tenant-release-wiring", checked_at=checked_at)
    smoke_report = passed_smoke_report(
        tenant_id="tenant-release-wiring",
        drill_report=drill_report,
        checked_at=checked_at + timedelta(minutes=5),
    )
    gate = build_source_object_preview_renderer_release_gate(
        tenant_id="tenant-release-wiring",
        api_smoke_report=smoke_report,
        recovery_drill_report=drill_report,
        evaluated_at_utc=datetime(2026, 6, 17, 11, tzinfo=UTC),
    )

    with pytest.raises(ValueError, match="tenant does not match"):
        require_source_object_preview_renderer_release_gate_for_wiring(
            gate=gate,
            tenant_id="tenant-other",
            evidence_hash=gate.evidence_hash,
        )
    with pytest.raises(ValueError, match="evidence hash does not match"):
        require_source_object_preview_renderer_release_gate_for_wiring(
            gate=gate,
            tenant_id="tenant-release-wiring",
            evidence_hash="sha256:" + "9" * 64,
        )


def ready_drill_report(*, tenant_id: str, checked_at: datetime) -> SourceObjectPreviewRendererRecoveryDrillReport:
    tenant_result = SourceObjectPreviewRendererRecoveryTenantResult(
        tenant_id=tenant_id,
        status=SourceObjectPreviewRendererRecoveryTenantStatus.READY,
        decision_evidence_count=1,
        renderer_evidence_count=1,
        verified_decision_renderer_refs=("renderer-sandbox:sha256:" + "1" * 64,),
        recovered_renderer_refs=("renderer-sandbox:sha256:" + "1" * 64,),
        missing_verified_renderer_refs=(),
        unverified_decision_renderer_refs=(),
        worker_queue_binding_refs=("worker-queue:source-preview-renderer-runs:sha256:" + "2" * 64,),
        worker_idempotency_key_hashes=("sha256:" + "2" * 64,),
        worker_queue_resume_ok=True,
        idempotency_replay_ok=True,
        tenant_isolation_smoke_ok=True,
        content_boundary_ok=True,
        metadata_only_recovery_ok=True,
        blocking_reasons=(),
    )
    return drill_report_with_result(
        tenant_id=tenant_id,
        checked_at=checked_at,
        tenant_result=tenant_result,
        ready_count=1,
        attention_required_count=0,
        alert_required=False,
        recommended_actions=(),
    )


def blocked_drill_report(*, tenant_id: str, checked_at: datetime) -> SourceObjectPreviewRendererRecoveryDrillReport:
    tenant_result = SourceObjectPreviewRendererRecoveryTenantResult(
        tenant_id=tenant_id,
        status=SourceObjectPreviewRendererRecoveryTenantStatus.ATTENTION_REQUIRED,
        decision_evidence_count=1,
        renderer_evidence_count=0,
        verified_decision_renderer_refs=("renderer-sandbox:sha256:" + "1" * 64,),
        recovered_renderer_refs=(),
        missing_verified_renderer_refs=("renderer-sandbox:sha256:" + "1" * 64,),
        unverified_decision_renderer_refs=(),
        worker_queue_binding_refs=(),
        worker_idempotency_key_hashes=(),
        worker_queue_resume_ok=False,
        idempotency_replay_ok=False,
        tenant_isolation_smoke_ok=True,
        content_boundary_ok=False,
        metadata_only_recovery_ok=False,
        blocking_reasons=("preview_renderer_evidence_not_found",),
    )
    return drill_report_with_result(
        tenant_id=tenant_id,
        checked_at=checked_at,
        tenant_result=tenant_result,
        ready_count=0,
        attention_required_count=1,
        alert_required=True,
        recommended_actions=("repair preview renderer evidence before release",),
    )


def drill_report_with_result(
    *,
    tenant_id: str,
    checked_at: datetime,
    tenant_result: SourceObjectPreviewRendererRecoveryTenantResult,
    ready_count: int,
    attention_required_count: int,
    alert_required: bool,
    recommended_actions: tuple[str, ...],
) -> SourceObjectPreviewRendererRecoveryDrillReport:
    draft = SourceObjectPreviewRendererRecoveryDrillReport(
        run_id=f"preview-renderer-drill-{tenant_id}",
        checked_by="test-preview-renderer-release-gate",
        checked_at_utc=checked_at,
        tenant_results=(tenant_result,),
        ready_count=ready_count,
        attention_required_count=attention_required_count,
        no_evidence_count=0,
        failed_count=0,
        alert_required=alert_required,
        recommended_actions=recommended_actions,
        runbook_evidence=SourceObjectPreviewRendererRecoveryRunbookEvidence(
            run_id=f"preview-renderer-drill-{tenant_id}",
            checked_by="test-preview-renderer-release-gate",
            checked_at_utc=checked_at,
            selected_tenants=(tenant_id,),
        ),
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(
        update={"evidence_hash": build_source_object_preview_renderer_recovery_drill_report_hash(draft)}
    )


def passed_smoke_report(
    *,
    tenant_id: str,
    drill_report: SourceObjectPreviewRendererRecoveryDrillReport,
    checked_at: datetime,
    smoke_passed: bool = True,
    recovery_metadata_only_ok: bool = True,
    recovery_tenant_status: str = "ready",
) -> SourceObjectPreviewRendererApiSmokeReport:
    draft = SourceObjectPreviewRendererApiSmokeReport(
        tenant_id=tenant_id,
        source_object_id=f"doc-{tenant_id}",
        source_version_id="v1",
        preview_slot_id="office.document.preview.metadata",
        preview_policy_id="preview-policy.document.metadata-first.v1",
        parser_sanitizer_evidence_ref=f"parser-sanitizer:{tenant_id}",
        backup_coverage_evidence_ref=f"backup:{tenant_id}",
        restore_evidence_ref=f"restore-drill:{tenant_id}",
        renderer_sandbox_evidence_ref="renderer-sandbox:sha256:" + "1" * 64,
        renderer_sandbox_evidence_hash="sha256:" + "1" * 64,
        preview_decision_evidence_hash="sha256:" + "3" * 64,
        preview_decision_ledger_ref="preview-decision-ledger:sha256:" + "3" * 64,
        renderer_run_audit_event_id=f"audit:renderer:{tenant_id}",
        preview_decision_audit_event_id=f"audit:decision:{tenant_id}",
        recovery_drill_report_hash=drill_report.evidence_hash,
        release_restore_evidence_ref=f"preview-renderer-recovery-drill:{drill_report.evidence_hash}",
        recovery_tenant_status=recovery_tenant_status,
        recovery_metadata_only_ok=recovery_metadata_only_ok,
        smoke_passed=smoke_passed,
        checked_by="test-preview-renderer-release-gate",
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_source_object_preview_renderer_api_smoke_report_hash(draft)})
