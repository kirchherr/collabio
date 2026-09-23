from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from suite.operations.preview_conversion_non_empty_proof import (
    PROOF_TENANT_ID,
    PreviewConversionNonEmptyProofReport,
    PreviewConversionProofStageBundle,
    build_preview_conversion_non_empty_proof_report_hash,
    build_preview_conversion_proof_stage_bundle,
    build_preview_conversion_stage_report_hash,
    import_preview_conversion_non_empty_proof,
    load_preview_conversion_runtime_engine_report,
    prepare_and_commit_preview_conversion_proof_stage,
    stage_preview_conversion_proof_workspaces,
)
from suite.platform.source_object_preview_conversion import (
    DerivedPreviewWriteUnitOfWork,
    InMemoryDerivedPreviewReceiptStore,
    InMemoryPreviewConversionJobEvidenceStore,
    PreviewConversionWorkerResult,
    build_preview_conversion_result_hash,
)
from suite.platform.source_object_preview_conversion_worker import (
    PreviewConversionEngineSelfTestReport,
    build_preview_conversion_engine_self_test_report_hash,
)
from suite.storage.source_objects import (
    InMemorySourceObjectRepository,
    InMemorySourceObjectWriteReceiptStore,
    sha256_bytes,
)

NOW = datetime(2026, 8, 7, 13, 0, tzinfo=UTC)
PROOF_RUN_ID = "preview-proof-20260807-130000"
WORKER_IMAGE_REF = "collabio/preview-renderer@sha256:" + ("1" * 64)
PDF_BYTES = b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\nstartxref\n0\n%%EOF\n"


def test_stage_bundle_is_hash_bound_synthetic_and_dedicated_to_proof_tenant() -> None:
    bundle = _bundle()

    assert bundle.source_record.metadata.tenant_id == PROOF_TENANT_ID
    assert bundle.execution_gate.sandbox_runtime_class == "runsc"
    assert bundle.execution_gate.worker_image_ref == WORKER_IMAGE_REF
    assert bundle.report.runtime_engine_self_test_report_hash == "sha256:" + ("2" * 64)
    assert bundle.report.real_malware_scanner_invoked is False
    assert bundle.report.schema_version == "source_object_preview_conversion_non_empty_stage.v3"
    assert bundle.envelope.command.preview_policy_id == "synthetic-preview-proof.v1"
    assert bundle.report.development_only is True
    assert bundle.report.synthetic_fixture is True
    assert bundle.report.production_admission_requested is False
    assert bundle.report.report_hash == build_preview_conversion_stage_report_hash(bundle.report)
    serialized = bundle.report.model_dump_json()
    assert "synthetic non-empty preview recovery proof" not in serialized.lower()
    assert "content_bytes" not in serialized


def test_stage_and_import_persist_non_empty_lineage_then_destroy_transient_content(tmp_path: Path) -> None:
    bundle = _bundle()
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    stage_preview_conversion_proof_workspaces(bundle=bundle, input_dir=input_dir, output_dir=output_dir)
    result = _result(bundle)
    (output_dir / "preview.pdf").write_bytes(PDF_BYTES)
    (output_dir / "result.json").write_text(result.model_dump_json(), encoding="utf-8")

    repository = InMemorySourceObjectRepository(records=(bundle.source_record,))
    source_receipts = InMemorySourceObjectWriteReceiptStore((bundle.source_write_receipt,))
    derived_receipts = InMemoryDerivedPreviewReceiptStore()
    job_evidence = InMemoryPreviewConversionJobEvidenceStore()
    committer = DerivedPreviewWriteUnitOfWork(
        source_repository=repository,
        source_object_write_receipt_store=source_receipts,
        derived_preview_receipt_store=derived_receipts,
        job_evidence_store=job_evidence,
    )

    report = import_preview_conversion_non_empty_proof(
        proof_run_id=PROOF_RUN_ID,
        source_repository=repository,
        committer=committer,
        input_dir=input_dir,
        output_dir=output_dir,
        completed_at_utc=NOW + timedelta(minutes=2),
    )

    assert report.technical_conversion_verified is True
    assert report.persistent_lineage_verified is True
    assert report.transient_input_destroyed is True
    assert report.transient_output_destroyed is True
    assert report.production_admission_evidence_ready is False
    assert report.conversion_dispatch_allowed is False
    assert report.preview_serving_allowed is False
    assert report.report_hash == build_preview_conversion_non_empty_proof_report_hash(report)
    assert tuple(input_dir.iterdir()) == ()
    assert tuple(output_dir.iterdir()) == ()
    assert job_evidence.get(tenant_id=PROOF_TENANT_ID, job_evidence_hash=report.job_evidence_hash)
    assert derived_receipts.get(tenant_id=PROOF_TENANT_ID, receipt_hash=report.derived_preview_receipt_hash)
    serialized = report.model_dump_json()
    assert "synthetic non-empty preview recovery proof" not in serialized.lower()
    assert "content_bytes" not in serialized


def test_import_failure_still_destroys_transient_workspaces(tmp_path: Path) -> None:
    bundle = _bundle()
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    stage_preview_conversion_proof_workspaces(bundle=bundle, input_dir=input_dir, output_dir=output_dir)
    result = _result(bundle)
    (output_dir / "preview.pdf").write_bytes(b"not-a-pdf")
    (output_dir / "result.json").write_text(result.model_dump_json(), encoding="utf-8")
    repository = InMemorySourceObjectRepository(records=(bundle.source_record,))
    committer = DerivedPreviewWriteUnitOfWork(
        source_repository=repository,
        source_object_write_receipt_store=InMemorySourceObjectWriteReceiptStore((bundle.source_write_receipt,)),
        derived_preview_receipt_store=InMemoryDerivedPreviewReceiptStore(),
        job_evidence_store=InMemoryPreviewConversionJobEvidenceStore(),
    )

    with pytest.raises(ValueError, match=r"output length|content hash|not a PDF"):
        import_preview_conversion_non_empty_proof(
            proof_run_id=PROOF_RUN_ID,
            source_repository=repository,
            committer=committer,
            input_dir=input_dir,
            output_dir=output_dir,
            completed_at_utc=NOW + timedelta(minutes=2),
        )

    assert tuple(input_dir.iterdir()) == ()
    assert tuple(output_dir.iterdir()) == ()


def test_proof_report_rejects_any_production_or_serving_claim() -> None:
    bundle = _bundle()
    result = _result(bundle)
    valid = {
        "proof_run_id": PROOF_RUN_ID,
        "tenant_id": PROOF_TENANT_ID,
        "source_object_ref_hash": "sha256:" + ("1" * 64),
        "derived_object_ref_hash": "sha256:" + ("2" * 64),
        "execution_gate_evidence_hash": bundle.execution_gate.evidence_hash,
        "command_hash": bundle.envelope.command.command_hash,
        "result_hash": result.result_hash,
        "source_write_receipt_hash": bundle.source_write_receipt.receipt_hash,
        "derived_write_receipt_hash": "sha256:" + ("3" * 64),
        "derived_preview_receipt_hash": "sha256:" + ("4" * 64),
        "job_evidence_hash": "sha256:" + ("5" * 64),
        "worker_image_ref": WORKER_IMAGE_REF,
        "sandbox_runtime_class": "runsc",
        "output_content_hash": result.output_content_hash,
        "output_content_byte_length": result.output_content_byte_length,
        "page_count": result.page_count,
        "cdr_manifest_hash": result.cdr_manifest_hash,
        "pixel_reconstruction_verified": True,
        "cdr_trust_boundary_separated": True,
        "technical_conversion_verified": True,
        "persistent_lineage_verified": True,
        "transient_input_destroyed": True,
        "transient_output_destroyed": True,
        "external_network_used_by_worker": False,
        "completed_at_utc": NOW,
        "report_hash": "sha256:" + ("0" * 64),
    }

    with pytest.raises(ValueError, match="fail closed"):
        PreviewConversionNonEmptyProofReport.model_validate({**valid, "preview_serving_allowed": True})
    with pytest.raises(ValueError, match="fail closed"):
        PreviewConversionNonEmptyProofReport.model_validate({**valid, "production_admission_evidence_ready": True})


def test_runtime_preflight_report_must_be_hash_valid_and_isolated(tmp_path: Path) -> None:
    draft = PreviewConversionEngineSelfTestReport(
        converter_engine="LibreOffice",
        converter_version="LibreOffice 25.8.7.3",
        pdf_validator_engine="qpdf+pdfinfo",
        pdf_validator_version="qpdf 12.3.2; pdfinfo 25.12.0",
        font_baseline_hash="sha256:" + ("1" * 64),
        output_content_hash="sha256:" + ("2" * 64),
        output_content_byte_length=128,
        page_count=1,
        cdr_profile_ref="collabio-pixel-cdr:raw-rgb.v1",
        cdr_manifest_hash="sha256:" + ("3" * 64),
        cdr_page_count=1,
        pixel_reconstruction_passed=True,
        cdr_trust_boundary_separated=False,
        qpdf_validation_passed=True,
        pdfinfo_validation_passed=True,
        active_pdf_content_absent=True,
        completed_at_utc=NOW,
        report_hash="sha256:" + ("0" * 64),
    )
    report = draft.model_copy(update={"report_hash": build_preview_conversion_engine_self_test_report_hash(draft)})
    report_path = tmp_path / "runtime-report.json"
    report_path.write_text(report.model_dump_json(), encoding="utf-8")

    loaded = load_preview_conversion_runtime_engine_report(report_path)

    assert loaded.report_hash == report.report_hash

    tampered = report.model_copy(update={"external_network_used": True})
    report_path.write_text(tampered.model_dump_json(), encoding="utf-8")
    with pytest.raises(ValueError, match="hash is invalid"):
        load_preview_conversion_runtime_engine_report(report_path)

    isolated_but_false = tampered.model_copy(
        update={"report_hash": build_preview_conversion_engine_self_test_report_hash(tampered)}
    )
    report_path.write_text(isolated_but_false.model_dump_json(), encoding="utf-8")
    with pytest.raises(ValueError, match="violates proof isolation"):
        load_preview_conversion_runtime_engine_report(report_path)


def test_stage_prepares_workspaces_and_pending_report_before_database_commit(tmp_path: Path) -> None:
    bundle = _bundle()
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    report_path = tmp_path / "stage-report.json"

    class InspectingCommitter:
        committed = False

        def commit(self, candidate: PreviewConversionProofStageBundle) -> PreviewConversionProofStageBundle:
            assert (input_dir / "request.json").is_file()
            assert (input_dir / candidate.envelope.command.input_filename).is_file()
            assert report_path.with_suffix(".json.pending").is_file()
            assert not report_path.exists()
            self.committed = True
            return candidate

    committer = InspectingCommitter()

    report = prepare_and_commit_preview_conversion_proof_stage(
        bundle=bundle,
        committer=committer,
        input_dir=input_dir,
        output_dir=output_dir,
        report_path=report_path,
    )

    assert committer.committed is True
    assert report == bundle.report
    assert report_path.is_file()
    assert not report_path.with_suffix(".json.pending").exists()


def test_stage_commit_failure_clears_workspaces_and_preserves_prior_report(tmp_path: Path) -> None:
    bundle = _bundle()
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    report_path = tmp_path / "stage-report.json"
    report_path.write_text("prior-valid-report\n", encoding="utf-8")

    class FailingCommitter:
        def commit(self, candidate: PreviewConversionProofStageBundle) -> PreviewConversionProofStageBundle:
            assert (input_dir / "request.json").is_file()
            assert report_path.with_suffix(".json.pending").is_file()
            raise RuntimeError("synthetic database failure")

    with pytest.raises(RuntimeError, match="synthetic database failure"):
        prepare_and_commit_preview_conversion_proof_stage(
            bundle=bundle,
            committer=FailingCommitter(),
            input_dir=input_dir,
            output_dir=output_dir,
            report_path=report_path,
        )

    assert tuple(input_dir.iterdir()) == ()
    assert tuple(output_dir.iterdir()) == ()
    assert report_path.read_text(encoding="utf-8") == "prior-valid-report\n"
    assert not report_path.with_suffix(".json.pending").exists()


def test_compose_proof_chain_keeps_worker_credentialless_offline_and_on_runsc() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    preflight = _service(
        compose,
        "preview-conversion-proof-runtime-preflight",
        "preview-conversion-proof-stager",
    )
    updater = _service(compose, "preview-malware-signature-updater", "preview-malware-scanner")
    scanner = _service(compose, "preview-malware-scanner", "preview-malware-scanner-smoke")
    scanner_smoke = _service(compose, "preview-malware-scanner-smoke", "preview-conversion-proof-runtime-preflight")
    stager = _service(compose, "preview-conversion-proof-stager", "preview-conversion-proof-cdr-renderer")
    renderer = _service(compose, "preview-conversion-proof-cdr-renderer", "preview-conversion-proof-worker")
    worker = _service(compose, "preview-conversion-proof-worker", "preview-conversion-proof-importer")
    importer = _service(compose, "preview-conversion-proof-importer", "preview-conversion-proof-cleanup")
    cleanup = _service(compose, "preview-conversion-proof-cleanup", "preview-conversion-engine-smoke")

    assert 'entrypoint: ["freshclam"]' in updater
    assert "preview_malware_updates" in updater
    assert "      - preview_malware\n" not in updater
    assert "SUITE_DATABASE_DSN:" not in updater
    assert "SUITE_S3_SECRET_ACCESS_KEY:" not in updater
    assert "preview-malware-signature-updater:" in scanner
    assert "condition: service_completed_successfully" in scanner
    assert 'CLAMAV_NO_FRESHCLAMD: "true"' in scanner
    assert "clamav/clamav:1.5@sha256:" in scanner
    assert 'user: "clamav"' in scanner
    assert 'entrypoint: ["/init-unprivileged"]' in scanner
    assert "read_only: true" in scanner
    assert "- ALL" in scanner
    assert "ports:" not in scanner
    assert "preview_malware" in scanner
    assert "suite.operations.preview_malware_scanner_smoke" in scanner_smoke
    assert "preview-malware-scanner:" in scanner_smoke
    assert "SUITE_DATABASE_DSN:" not in scanner_smoke
    assert "SUITE_S3_SECRET_ACCESS_KEY:" not in scanner_smoke
    assert "preview-malware-scanner-smoke:" in stager
    assert "SUITE_PREVIEW_MALWARE_SCANNER_BACKEND: clamd" in stager

    assert 'profiles: ["preview-proof"]' in stager
    assert "runtime: runsc" in preflight
    assert 'network_mode: "none"' in preflight
    assert "--engine-self-test" in preflight
    assert "runtime-engine-self-test.json" in preflight
    assert "SUITE_DATABASE_DSN:" not in preflight
    assert "SUITE_S3_SECRET_ACCESS_KEY:" not in preflight
    assert "- DAC_OVERRIDE" in preflight
    assert "preview-conversion-proof-runtime-preflight:" in stager
    assert "- CHOWN" in stager
    assert "- DAC_OVERRIDE" in stager
    assert "- FOWNER" in stager
    assert "SUITE_DATABASE_DSN:" in stager
    assert "SUITE_S3_SECRET_ACCESS_KEY:" in stager
    assert "preview-conversion-proof-stager:" in renderer
    assert "--render-cdr-bundle" in renderer
    assert "runtime: runsc" in renderer
    assert 'network_mode: "none"' in renderer
    assert "preview_conversion_proof_input:/job/proof-input:ro" in renderer
    assert "preview_conversion_proof_control:/job/proof-control:ro" in renderer
    assert "preview_conversion_proof_cdr:/job/proof-cdr" in renderer
    assert "preview_conversion_proof_output:/job/proof-output" not in renderer
    assert "SUITE_DATABASE_DSN:" not in renderer
    assert "preview-conversion-proof-cdr-renderer:" in worker
    assert "--rebuild-cdr-bundle" in worker
    assert "condition: service_completed_successfully" in worker
    assert "runtime: runsc" in worker
    assert 'network_mode: "none"' in worker
    assert "SUITE_DATABASE_DSN:" not in worker
    assert "SUITE_S3_SECRET_ACCESS_KEY:" not in worker
    assert "cap_add:" not in worker
    assert "preview_conversion_proof_input:/job/proof-input:ro" not in worker
    assert "preview_conversion_proof_control:/job/proof-control:ro" in worker
    assert "preview_conversion_proof_cdr:/job/proof-cdr:ro" in worker
    assert "preview-conversion-proof-worker:" in importer
    assert "- DAC_OVERRIDE" in importer
    assert "SUITE_DATABASE_DSN:" in importer
    assert 'command: ["cleanup"]' in cleanup
    assert 'network_mode: "none"' in cleanup
    assert "- DAC_OVERRIDE" in cleanup
    assert "preview_conversion_proof_input:" in compose
    assert "preview_conversion_proof_output:" in compose
    assert "preview_conversion_proof_control:" in compose
    assert "preview_conversion_proof_cdr:" in compose


def _bundle() -> PreviewConversionProofStageBundle:
    return build_preview_conversion_proof_stage_bundle(
        proof_run_id=PROOF_RUN_ID,
        worker_image_ref=WORKER_IMAGE_REF,
        runtime_engine_self_test_report_hash="sha256:" + ("2" * 64),
        font_baseline_hash="sha256:" + ("3" * 64),
        backup_restore_evidence_hash="sha256:" + ("4" * 64),
        staged_at_utc=NOW,
    )


def _result(bundle: PreviewConversionProofStageBundle) -> PreviewConversionWorkerResult:
    command = bundle.envelope.command
    gate = bundle.execution_gate
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
        cdr_profile_ref="collabio-pixel-cdr:raw-rgb.v1",
        cdr_manifest_hash="sha256:" + ("e" * 64),
        cdr_page_count=1,
        pixel_reconstruction_passed=True,
        cdr_fail_closed_verified=True,
        cdr_trust_boundary_separated=True,
        source_bytes_accessible_to_cdr_rebuilder=False,
        output_content_hash=sha256_bytes(PDF_BYTES),
        output_content_byte_length=len(PDF_BYTES),
        page_count=1,
        source_hash_verified=True,
        output_hash_verified=True,
        qpdf_validation_passed=True,
        pdfinfo_validation_passed=True,
        active_pdf_content_absent=True,
        temporary_workspace_destroyed=True,
        completed_at_utc=NOW + timedelta(minutes=1),
        result_hash="sha256:" + ("0" * 64),
    )
    return draft.model_copy(update={"result_hash": build_preview_conversion_result_hash(draft)})


def _service(compose: str, service_name: str, next_service_name: str) -> str:
    return compose.split(f"\n  {service_name}:\n", 1)[1].split(f"\n  {next_service_name}:\n", 1)[0]
