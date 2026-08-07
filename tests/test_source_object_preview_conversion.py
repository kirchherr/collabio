from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from suite.ai_control_plane.models import DataClass
from suite.operations.backend_foundation_completion_gate import (
    BackendFoundationCompletionGate,
    build_backend_foundation_completion_gate_hash,
)
from suite.operations.derived_preview_recovery_drill import (
    build_derived_preview_recovery_drill_report_hash,
    run_derived_preview_recovery_drill,
)
from suite.persistence.migration_catalog import get_migration
from suite.platform.source_object_preview_conversion import (
    DerivedPreviewWriteUnitOfWork,
    InMemoryDerivedPreviewReceiptStore,
    InMemoryPreviewConversionExecutionGateStore,
    InMemoryPreviewConversionJobEvidenceStore,
    PreviewConversionBlocked,
    PreviewConversionCommand,
    PreviewConversionExecutionGateEvidence,
    PreviewConversionGateStatus,
    PreviewConversionSourcePreflightEvidence,
    PreviewConversionWorkerEnvelope,
    PreviewConversionWorkerResult,
    build_derived_preview_artifact,
    build_preview_conversion_command,
    build_preview_conversion_execution_gate,
    build_preview_conversion_result_hash,
    build_preview_conversion_source_preflight,
    require_preview_conversion_execution_gate,
    require_preview_conversion_worker_envelope,
)
from suite.platform.source_object_preview_conversion_worker import (
    PreviewConversionWorkerError,
    _qpdf_json_contains_active_content,
    run_preview_conversion,
)
from suite.storage.source_objects import (
    InMemorySourceObjectRepository,
    InMemorySourceObjectWriteReceiptStore,
    LegalHoldState,
    SourceLifecycleState,
    SourceObjectMetadata,
    SourceObjectRecord,
    SourceObjectType,
    build_source_object_manifest_hash,
    sha256_bytes,
)

NOW = datetime(2026, 8, 7, 10, 0, tzinfo=UTC)
IMAGE_REF = "registry.example.com/collabio/preview-renderer@sha256:" + ("1" * 64)
PDF_BYTES = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\nstartxref\n0\n%%EOF\n"


def test_execution_gate_requires_all_controls_and_is_hash_bound() -> None:
    gate = _gate()

    assert gate.gate_status == PreviewConversionGateStatus.READY
    assert gate.worker_image_digest == "sha256:" + ("1" * 64)
    assert gate.sandbox_runtime_class == "runsc"
    assert gate.evidence_hash.startswith("sha256:")

    store = InMemoryPreviewConversionExecutionGateStore()
    store.append(gate)
    assert store.get(tenant_id="tenant-demo", evidence_hash=gate.evidence_hash) == gate

    tampered = gate.model_copy(update={"viewer_origin": "https://other.example.test"})
    with pytest.raises(PreviewConversionBlocked, match="hash"):
        store.append(tampered)


def test_execution_gate_blocks_missing_control_stale_evidence_and_tenant_drift() -> None:
    blocked = _gate(network_egress_denied=False)

    assert blocked.gate_status == PreviewConversionGateStatus.BLOCKED
    assert blocked.blocking_reasons == ("network_egress_denied_required",)
    with pytest.raises(PreviewConversionBlocked, match="blocked"):
        require_preview_conversion_execution_gate(
            gate=blocked,
            tenant_id="tenant-demo",
            checked_at_utc=NOW,
        )
    with pytest.raises(PreviewConversionBlocked, match="tenant"):
        require_preview_conversion_execution_gate(
            gate=_gate(),
            tenant_id="tenant-other",
            checked_at_utc=NOW,
        )
    with pytest.raises(PreviewConversionBlocked, match="stale"):
        require_preview_conversion_execution_gate(
            gate=_gate(),
            tenant_id="tenant-demo",
            checked_at_utc=NOW + timedelta(hours=25),
        )


def test_execution_gate_rejects_unpinned_images_and_default_container_runtime() -> None:
    with pytest.raises(ValidationError, match="pinned"):
        PreviewConversionExecutionGateEvidence.model_validate(
            {**_gate().model_dump(mode="json"), "worker_image_ref": "collabio/preview-renderer:latest"}
        )
    with pytest.raises(ValidationError, match="allowlisted"):
        PreviewConversionExecutionGateEvidence.model_validate(
            {**_gate().model_dump(mode="json"), "sandbox_runtime_class": "runc"}
        )


def test_source_preflight_blocks_malware_passwords_and_active_content() -> None:
    source = _source_record()
    evidence = build_preview_conversion_source_preflight(
        source_metadata=source.metadata,
        scanner_profile_ref="clamav:1.4",
        scanner_signature_set_hash="sha256:" + ("9" * 64),
        cdr_profile_ref="cdr:office-preview.v1",
        checked_at_utc=NOW,
        malware_detected=True,
        password_protected=True,
        active_content_execution_required=True,
    )

    assert evidence.conversion_allowed is False
    assert set(evidence.blocking_reasons) == {
        "malware_detected",
        "password_protected_source_not_supported",
        "active_content_execution_required",
    }


def test_command_is_metadata_only_deterministic_and_bound_to_fresh_evidence() -> None:
    source = _source_record()
    gate = _gate()
    preflight = _preflight(source)

    command = _command(source=source, gate=gate, preflight=preflight)

    assert command.input_filename == "source.rtf"
    assert command.output_filename == "preview.pdf"
    assert command.worker_image_ref == gate.worker_image_ref
    assert command.execution_gate_evidence_hash == gate.evidence_hash
    assert command.source_preflight_evidence_hash == preflight.evidence_hash
    assert command.command_hash.startswith("sha256:")
    serialized = command.model_dump_json()
    assert "Quarterly board source" not in serialized
    assert "content_bytes" not in serialized
    assert "reason for conversion" not in serialized

    payload = command.model_dump(mode="json")
    payload["content"] = "forbidden"
    with pytest.raises(ValidationError, match="Extra inputs"):
        command.__class__.model_validate(payload)


def test_worker_envelope_fails_closed_on_image_runtime_font_or_preflight_drift() -> None:
    source = _source_record()
    gate = _gate()
    preflight = _preflight(source)
    command = _command(source=source, gate=gate, preflight=preflight)
    envelope = PreviewConversionWorkerEnvelope(
        command=command,
        execution_gate=gate,
        source_preflight=preflight,
    )

    require_preview_conversion_worker_envelope(
        envelope=envelope,
        configured_worker_image_ref=gate.worker_image_ref,
        configured_runtime_class="runsc",
        actual_font_baseline_hash=gate.font_baseline_hash,
        checked_at_utc=NOW,
    )

    with pytest.raises(PreviewConversionBlocked, match="image"):
        require_preview_conversion_worker_envelope(
            envelope=envelope,
            configured_worker_image_ref="registry.example.com/other@sha256:" + ("2" * 64),
            configured_runtime_class="runsc",
            actual_font_baseline_hash=gate.font_baseline_hash,
            checked_at_utc=NOW,
        )
    with pytest.raises(PreviewConversionBlocked, match="runtime"):
        require_preview_conversion_worker_envelope(
            envelope=envelope,
            configured_worker_image_ref=gate.worker_image_ref,
            configured_runtime_class="kata-clh",
            actual_font_baseline_hash=gate.font_baseline_hash,
            checked_at_utc=NOW,
        )
    with pytest.raises(PreviewConversionBlocked, match="font"):
        require_preview_conversion_worker_envelope(
            envelope=envelope,
            configured_worker_image_ref=gate.worker_image_ref,
            configured_runtime_class="runsc",
            actual_font_baseline_hash="sha256:" + ("2" * 64),
            checked_at_utc=NOW,
        )


def test_derived_preview_inherits_compliance_metadata_and_exact_source_version_lineage() -> None:
    source = _source_record()
    gate = _gate()
    preflight = _preflight(source)
    command = _command(source=source, gate=gate, preflight=preflight)
    result = _result(command=command, gate=gate)

    artifact = build_derived_preview_artifact(
        source_record=source,
        pdf_bytes=PDF_BYTES,
        command=command,
        result=result,
        execution_gate=gate,
        source_preflight=preflight,
        audit_event_id="audit-event-preview-1",
        created_at_utc=NOW,
    )

    derived = artifact.record.metadata
    receipt = artifact.derived_preview_receipt
    assert derived.object_type == SourceObjectType.ATTACHMENT
    assert derived.mime_type == "application/pdf"
    assert derived.parent_object_id == source.metadata.object_id
    assert derived.classification == source.metadata.classification
    assert derived.retention_policy_id == source.metadata.retention_policy_id
    assert derived.legal_hold_state == LegalHoldState.ACTIVE
    assert derived.lifecycle_state == source.metadata.lifecycle_state
    assert derived.acl_hash == source.metadata.acl_hash
    assert derived.acl_version == source.metadata.acl_version
    assert derived.kms_key_ref == source.metadata.kms_key_ref
    assert receipt.source_version_id == source.metadata.version_id
    assert receipt.source_manifest_hash == source.metadata.manifest_hash
    assert receipt.result_hash == result.result_hash
    assert receipt.source_content_in_receipt is False
    assert receipt.output_content_in_receipt is False


def test_derived_preview_write_unit_of_work_persists_source_receipt_and_lineage() -> None:
    source = _source_record()
    gate = _gate()
    preflight = _preflight(source)
    command = _command(source=source, gate=gate, preflight=preflight)
    artifact = build_derived_preview_artifact(
        source_record=source,
        pdf_bytes=PDF_BYTES,
        command=command,
        result=_result(command=command, gate=gate),
        execution_gate=gate,
        source_preflight=preflight,
        audit_event_id="audit-event-preview-2",
        created_at_utc=NOW,
    )
    repository = InMemorySourceObjectRepository(records=(source,))
    source_receipts = InMemorySourceObjectWriteReceiptStore()
    derived_receipts = InMemoryDerivedPreviewReceiptStore()
    job_evidences = InMemoryPreviewConversionJobEvidenceStore()
    unit_of_work = DerivedPreviewWriteUnitOfWork(
        source_repository=repository,
        source_object_write_receipt_store=source_receipts,
        derived_preview_receipt_store=derived_receipts,
        job_evidence_store=job_evidences,
    )

    unit_of_work.commit(artifact)

    persisted = repository.get(
        tenant_id="tenant-demo",
        object_id=artifact.record.metadata.object_id,
        version_id=artifact.record.metadata.version_id,
    )
    assert persisted.content_bytes == PDF_BYTES
    assert (
        source_receipts.get(
            tenant_id="tenant-demo",
            receipt_hash=artifact.source_object_write_receipt.receipt_hash,
        )
        == artifact.source_object_write_receipt
    )
    assert (
        derived_receipts.get(
            tenant_id="tenant-demo",
            receipt_hash=artifact.derived_preview_receipt.receipt_hash,
        )
        == artifact.derived_preview_receipt
    )
    assert (
        job_evidences.get(
            tenant_id="tenant-demo",
            job_evidence_hash=artifact.job_evidence.job_evidence_hash,
        )
        == artifact.job_evidence
    )


NOT_PDF_BYTES = b"X" + PDF_BYTES[1:]
ACTIVE_PDF_BYTES = PDF_BYTES.replace(b"startxref\n0", b"/JavaScript")
TAMPERED_PDF_BYTES = PDF_BYTES.replace(b"Catalog", b"Catxlog")


@pytest.mark.parametrize(
    "pdf_bytes, result_pdf_bytes, expected_error",
    [
        (NOT_PDF_BYTES, NOT_PDF_BYTES, "not a PDF"),
        (ACTIVE_PDF_BYTES, ACTIVE_PDF_BYTES, "active content"),
        (TAMPERED_PDF_BYTES, PDF_BYTES, "content hash"),
    ],
)
def test_derived_preview_import_revalidates_output_bytes(
    pdf_bytes: bytes, result_pdf_bytes: bytes, expected_error: str
) -> None:
    source = _source_record()
    gate = _gate()
    preflight = _preflight(source)
    command = _command(source=source, gate=gate, preflight=preflight)

    with pytest.raises(PreviewConversionBlocked, match=expected_error):
        build_derived_preview_artifact(
            source_record=source,
            pdf_bytes=pdf_bytes,
            command=command,
            result=_result(command=command, gate=gate, pdf_bytes=result_pdf_bytes),
            execution_gate=gate,
            source_preflight=preflight,
            audit_event_id="audit-event-preview-invalid",
            created_at_utc=NOW,
        )


def test_conversion_migration_is_append_only_tenant_scoped_and_content_free() -> None:
    sql = " ".join(get_migration("0072").sql().lower().split())

    assert "source_object_preview_conversion_execution_gates" in sql
    assert "source_object_derived_preview_receipts" in sql
    assert "force row level security" in sql
    assert "source_object_preview_conversion_gate_tenant_select" in sql
    assert "source_object_derived_preview_tenant_insert" in sql
    assert "source_object_preview_conversion_gate_no_update" in sql
    assert "source_object_derived_preview_no_hard_delete" in sql
    assert "gate_status = 'ready'" in sql
    assert "gate_status = 'blocked'" in sql
    assert "jsonb_array_length(evidence -> 'blocking_reasons')" in sql
    assert "malware_cdr_ready" in sql
    assert "strict_viewer_csp_ready" in sql
    assert "not (receipt ? 'content')" in sql
    assert "not (receipt ? 'source_bytes')" in sql
    assert "not (receipt ? 'output_bytes')" in sql


def test_conversion_job_evidence_migration_is_append_only_tenant_scoped_and_content_free() -> None:
    sql = " ".join(get_migration("0073").sql().lower().split())

    assert "source_object_preview_conversion_job_evidence" in sql
    assert "force row level security" in sql
    assert "source_object_preview_conversion_job_tenant_select" in sql
    assert "source_object_preview_conversion_job_tenant_insert" in sql
    assert "source_object_preview_conversion_job_no_update" in sql
    assert "source_object_preview_conversion_job_no_hard_delete" in sql
    assert "source_object_preview_conversion_job_evidence.v1" in sql
    assert "derived_preview_receipt_hash" in sql
    assert "source_object_write_receipt_hash" in sql
    assert "source_preflight_evidence_hash" in sql
    assert "jsonb_typeof(evidence -> 'command') = 'object'" in sql
    assert "jsonb_typeof(evidence -> 'source_preflight') = 'object'" in sql
    assert "jsonb_typeof(evidence -> 'result') = 'object'" in sql
    assert "not (evidence ? 'content')" in sql
    assert "not (evidence ? 'source_bytes')" in sql
    assert "not (evidence ? 'output_bytes')" in sql
    assert "not (evidence ? 'credentials')" in sql


def test_qpdf_object_inspection_detects_canonicalized_active_names() -> None:
    assert _qpdf_json_contains_active_content({"qpdf": [{"obj:1 0 R": {"value": {"/OpenAction": "2 0 R"}}}]})
    assert _qpdf_json_contains_active_content({"qpdf": [{"obj:2 0 R": {"value": {"/S": "/JavaScript"}}}]})
    assert not _qpdf_json_contains_active_content(
        {"qpdf": [{"obj:1 0 R": {"value": {"/Type": "/Catalog", "/Pages": "2 0 R"}}}]}
    )


def test_worker_image_and_compose_service_preserve_credential_less_sandbox_boundary() -> None:
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")

    assert "FROM base AS preview-renderer" in dockerfile
    assert '"libreoffice-writer=${LIBREOFFICE_VERSION}"' in dockerfile
    assert '"libreoffice-calc=${LIBREOFFICE_VERSION}"' in dockerfile
    assert '"libreoffice-impress=${LIBREOFFICE_VERSION}"' in dockerfile
    assert '"qpdf=${QPDF_VERSION}"' in dockerfile
    assert "USER 10002:10002" in dockerfile
    worker = compose.split("  preview-conversion-worker:", maxsplit=1)[1].split("\n  api:", maxsplit=1)[0]
    assert "runtime: ${SUITE_PREVIEW_SANDBOX_RUNTIME:-runsc}" in worker
    assert 'network_mode: "none"' in worker
    assert "read_only: true" in worker
    assert "- ALL" in worker
    assert "no-new-privileges:true" in worker
    assert "preview_conversion_input:/job/input:ro" in worker
    assert "preview_conversion_output:/job/output" in worker
    assert "DATABASE_DSN" not in worker
    assert "S3_" not in worker
    assert "ACCESS_KEY" not in worker
    assert "SECRET" not in worker


def test_worker_rejects_non_empty_output_workspace_before_engine_execution(tmp_path: Path) -> None:
    source = _source_record()
    gate = _gate()
    command = _command(source=source, gate=gate, preflight=_preflight(source))
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    assert source.content_bytes is not None
    (input_dir / command.input_filename).write_bytes(source.content_bytes)
    (output_dir / "stale.pdf").write_bytes(PDF_BYTES)

    with pytest.raises(PreviewConversionWorkerError, match="not empty"):
        run_preview_conversion(
            command=command,
            input_dir=input_dir,
            output_dir=output_dir,
            sandbox_runtime_class=gate.sandbox_runtime_class,
            font_baseline_hash=gate.font_baseline_hash,
        )


def test_worker_result_and_receipt_json_never_include_document_or_process_output() -> None:
    source = _source_record()
    gate = _gate()
    preflight = _preflight(source)
    command = _command(source=source, gate=gate, preflight=preflight)
    result = _result(command=command, gate=gate)
    payload = json.dumps(result.model_dump(mode="json"), sort_keys=True)

    assert "Quarterly board source" not in payload
    assert '"source_content_in_result": false' in payload
    assert '"stdout_in_result": false' in payload
    assert '"stderr_in_result": false' in payload


def _gate(*, network_egress_denied: bool = True) -> PreviewConversionExecutionGateEvidence:
    return build_preview_conversion_execution_gate(
        tenant_id="tenant-demo",
        worker_image_ref=IMAGE_REF,
        sandbox_runtime_class="runsc",
        sandbox_runtime_evidence_hash="sha256:" + ("2" * 64),
        malware_scanner_profile_ref="clamav:1.4",
        malware_scanner_evidence_hash="sha256:" + ("3" * 64),
        cdr_profile_ref="cdr:office-preview.v1",
        cdr_evidence_hash="sha256:" + ("4" * 64),
        pdf_validator_profile_ref="qpdf-pdfinfo:1",
        pdf_validator_evidence_hash="sha256:" + ("5" * 64),
        font_baseline_hash="sha256:" + ("6" * 64),
        backup_restore_evidence_hash="sha256:" + ("7" * 64),
        viewer_origin="https://preview.example.test",
        viewer_csp_evidence_hash="sha256:" + ("8" * 64),
        evaluated_at_utc=NOW,
        network_egress_denied=network_egress_denied,
    )


def _source_record() -> SourceObjectRecord:
    source_bytes = b"Quarterly board source"
    draft = SourceObjectMetadata(
        tenant_id="tenant-demo",
        object_id="doc-1",
        object_type=SourceObjectType.DOCUMENT,
        version_id="v7",
        title="Quarterly board pack",
        owner_principal_id="user-demo",
        created_by="user-demo",
        created_at_utc="2026-08-07T09:00:00Z",
        updated_at_utc="2026-08-07T09:00:00Z",
        classification=DataClass.CONFIDENTIAL,
        retention_policy_id="rp-restricted",
        legal_hold_state=LegalHoldState.ACTIVE,
        kms_key_ref="kms://tenant-demo/confidential/v1",
        manifest_hash="sha256:" + ("0" * 64),
        audit_chain_ref="audit:source-doc-1-v7",
        source_system="collabio",
        mime_type="application/rtf",
        acl_hash="sha256:" + ("a" * 64),
        acl_version=7,
        content_hash=sha256_bytes(source_bytes),
        content_byte_length=len(source_bytes),
        lifecycle_state=SourceLifecycleState.SAVED_VERSION,
    )
    metadata = draft.model_copy(update={"manifest_hash": build_source_object_manifest_hash(draft)})
    return SourceObjectRecord(metadata=metadata, content_bytes=source_bytes)


def _preflight(source: SourceObjectRecord) -> PreviewConversionSourcePreflightEvidence:
    return build_preview_conversion_source_preflight(
        source_metadata=source.metadata,
        scanner_profile_ref="clamav:1.4",
        scanner_signature_set_hash="sha256:" + ("9" * 64),
        cdr_profile_ref="cdr:office-preview.v1",
        checked_at_utc=NOW,
    )


def _command(
    *,
    source: SourceObjectRecord,
    gate: PreviewConversionExecutionGateEvidence,
    preflight: PreviewConversionSourcePreflightEvidence,
) -> PreviewConversionCommand:
    return build_preview_conversion_command(
        source_metadata=source.metadata,
        adapter_id="canonical-pdf-libreoffice-pdfjs.v1",
        adapter_descriptor_hash="sha256:" + ("b" * 64),
        adapter_plan_hash="sha256:" + ("c" * 64),
        conversion_route="isolated_office_to_pdf",
        preview_slot_id="document-body",
        preview_policy_id="document-preview.v1",
        renderer_release_gate_evidence_hash="sha256:" + ("d" * 64),
        execution_gate=gate,
        source_preflight=preflight,
        requested_by="user-demo",
        reason="reason for conversion",
        requested_at_utc=NOW,
    )


def _result(
    *,
    command: PreviewConversionCommand,
    gate: PreviewConversionExecutionGateEvidence,
    pdf_bytes: bytes = PDF_BYTES,
) -> PreviewConversionWorkerResult:
    draft = PreviewConversionWorkerResult(
        tenant_id=command.tenant_id,
        source_object_id=command.source_object_id,
        source_version_id=command.source_version_id,
        source_manifest_hash=command.source_manifest_hash,
        source_content_hash=command.source_content_hash,
        command_hash=command.command_hash,
        execution_gate_evidence_hash=command.execution_gate_evidence_hash,
        source_preflight_evidence_hash=command.source_preflight_evidence_hash,
        worker_image_ref=command.worker_image_ref,
        sandbox_runtime_class=gate.sandbox_runtime_class,
        converter_version="LibreOffice 25.8.7.3",
        pdf_validator_version="qpdf version 12.3.2",
        font_baseline_hash=gate.font_baseline_hash,
        output_content_hash=sha256_bytes(pdf_bytes),
        output_content_byte_length=len(pdf_bytes),
        page_count=1,
        source_hash_verified=True,
        output_hash_verified=True,
        qpdf_validation_passed=True,
        pdfinfo_validation_passed=True,
        active_pdf_content_absent=True,
        temporary_workspace_destroyed=True,
        completed_at_utc=NOW,
        result_hash="sha256:" + ("0" * 64),
    )
    return draft.model_copy(update={"result_hash": build_preview_conversion_result_hash(draft)})


def test_derived_preview_recovery_reconciles_complete_metadata_and_content_lineage() -> None:
    source = _source_record()
    gate = _gate()
    preflight = _preflight(source)
    command = _command(source=source, gate=gate, preflight=preflight)
    artifact = build_derived_preview_artifact(
        source_record=source,
        pdf_bytes=PDF_BYTES,
        command=command,
        result=_result(command=command, gate=gate),
        execution_gate=gate,
        source_preflight=preflight,
        audit_event_id="audit-event-preview-recovery",
        created_at_utc=NOW,
    )
    repository = InMemorySourceObjectRepository(records=(source,))
    source_receipts = InMemorySourceObjectWriteReceiptStore()
    derived_receipts = InMemoryDerivedPreviewReceiptStore()
    job_evidences = InMemoryPreviewConversionJobEvidenceStore()
    execution_gates = InMemoryPreviewConversionExecutionGateStore((gate,))
    DerivedPreviewWriteUnitOfWork(
        source_repository=repository,
        source_object_write_receipt_store=source_receipts,
        derived_preview_receipt_store=derived_receipts,
        job_evidence_store=job_evidences,
    ).commit(artifact)

    report = run_derived_preview_recovery_drill(
        foundation_gate=_foundation_gate(),
        source_repository=repository,
        source_object_write_receipt_store=source_receipts,
        execution_gate_store=execution_gates,
        derived_preview_receipt_store=derived_receipts,
        job_evidence_store=job_evidences,
        checked_at_utc="2026-08-07T10:30:00Z",
    )

    assert report.recovery_ready is True
    assert report.production_admission_evidence_ready is True
    assert report.non_empty_recovery_verified is True
    assert report.reconciled_item_count == 1
    assert report.report_hash == build_derived_preview_recovery_drill_report_hash(report)
    assert report.conversion_dispatch_allowed is False
    assert report.preview_serving_allowed is False
    serialized = report.model_dump_json()
    assert "Quarterly board source" not in serialized
    assert "doc-1" not in serialized

    technical_proof_report = run_derived_preview_recovery_drill(
        foundation_gate=_foundation_gate(),
        source_repository=repository,
        source_object_write_receipt_store=source_receipts,
        execution_gate_store=execution_gates,
        derived_preview_receipt_store=derived_receipts,
        job_evidence_store=job_evidences,
        checked_at_utc="2026-08-07T10:30:00Z",
        production_admission_evaluation_enabled=False,
    )

    assert technical_proof_report.recovery_ready is True
    assert technical_proof_report.non_empty_recovery_verified is True
    assert technical_proof_report.production_admission_evidence_ready is False
    assert "preview.pdf" not in serialized


def test_derived_preview_recovery_fails_closed_when_restored_pdf_is_missing() -> None:
    source = _source_record()
    gate = _gate()
    preflight = _preflight(source)
    command = _command(source=source, gate=gate, preflight=preflight)
    artifact = build_derived_preview_artifact(
        source_record=source,
        pdf_bytes=PDF_BYTES,
        command=command,
        result=_result(command=command, gate=gate),
        execution_gate=gate,
        source_preflight=preflight,
        audit_event_id="audit-event-preview-missing",
        created_at_utc=NOW,
    )
    source_receipts = InMemorySourceObjectWriteReceiptStore((artifact.source_object_write_receipt,))
    derived_receipts = InMemoryDerivedPreviewReceiptStore((artifact.derived_preview_receipt,))
    job_evidences = InMemoryPreviewConversionJobEvidenceStore((artifact.job_evidence,))

    report = run_derived_preview_recovery_drill(
        foundation_gate=_foundation_gate(),
        source_repository=InMemorySourceObjectRepository(records=(source,)),
        source_object_write_receipt_store=source_receipts,
        execution_gate_store=InMemoryPreviewConversionExecutionGateStore((gate,)),
        derived_preview_receipt_store=derived_receipts,
        job_evidence_store=job_evidences,
        checked_at_utc="2026-08-07T10:30:00Z",
    )

    assert report.recovery_ready is False
    assert report.production_admission_evidence_ready is False
    assert report.failed_job_evidence_hashes == (artifact.job_evidence.job_evidence_hash,)
    assert "derived_preview_items_failed_reconciliation" in report.blocking_reasons


def test_derived_preview_recovery_accepts_empty_state_without_claiming_production_evidence() -> None:
    report = run_derived_preview_recovery_drill(
        foundation_gate=_foundation_gate(),
        source_repository=InMemorySourceObjectRepository(),
        source_object_write_receipt_store=InMemorySourceObjectWriteReceiptStore(),
        execution_gate_store=InMemoryPreviewConversionExecutionGateStore(),
        derived_preview_receipt_store=InMemoryDerivedPreviewReceiptStore(),
        job_evidence_store=InMemoryPreviewConversionJobEvidenceStore(),
        checked_at_utc="2026-08-07T10:30:00Z",
    )

    assert report.recovery_ready is True
    assert report.empty_state_verified is True
    assert report.non_empty_recovery_verified is False
    assert report.production_admission_evidence_ready is False
    assert report.conversion_dispatch_allowed is False
    assert report.preview_serving_allowed is False


def _foundation_gate() -> BackendFoundationCompletionGate:
    draft = BackendFoundationCompletionGate(
        checked_at_utc="2026-08-07T10:15:00Z",
        runtime_environment="dev",
        tenant_ids=("tenant-demo",),
        postgres_restore_drill_report_hash="sha256:" + ("a" * 64),
        backend_storage_foundation_gate_hash="sha256:" + ("b" * 64),
        backup_sha256="sha256:" + ("c" * 64),
        migration_count=73,
        database_table_count=80,
        restored_object_count=2,
        tenant_iam_verified=True,
        append_only_audit_verified=True,
        module_registry_verified=True,
        crm_atomic_write_controls_verified=True,
        tasks_activities_write_controls_verified=True,
        time_tracking_write_controls_verified=True,
        productivity_pilot_admission_controls_verified=True,
        productivity_pilot_traffic_scope_controls_verified=True,
        productivity_pilot_start_authorization_controls_verified=True,
        productive_business_write_controls_verified=True,
        migration_catalog_verified=True,
        postgres_backup_restore_verified=True,
        persistent_source_objects_verified=True,
        exact_version_object_restore_verified=True,
        independent_recovery_targets_verified=True,
        tenant_scope_verified=True,
        metadata_only_evidence_verified=True,
        api_start_allowed=True,
        backend_foundation_complete=True,
        gate_hash="sha256:" + ("0" * 64),
    )
    return draft.model_copy(update={"gate_hash": build_backend_foundation_completion_gate_hash(draft)})
