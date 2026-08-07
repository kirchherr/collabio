from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import psycopg
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.ai_control_plane.models import DataClass
from suite.operations.backend_foundation_completion_gate import load_backend_foundation_completion_gate
from suite.platform.source_object_preview_conversion import (
    DerivedPreviewArtifact,
    PgDerivedPreviewReceiptStore,
    PgPreviewConversionExecutionGateStore,
    PgPreviewConversionJobEvidenceStore,
    PostgresDerivedPreviewWriteUnitOfWork,
    PreviewConversionExecutionGateEvidence,
    PreviewConversionWorkerEnvelope,
    PreviewConversionWorkerResult,
    build_derived_preview_artifact,
    build_preview_conversion_command,
    build_preview_conversion_execution_gate,
    build_preview_conversion_source_preflight,
)
from suite.platform.source_object_preview_conversion_worker import build_installed_font_baseline_hash
from suite.platform.workspace_source_objects import build_default_workspace_source_object_repository
from suite.storage.source_object_storage import PgSourceObjectRepository
from suite.storage.source_objects import (
    LegalHoldState,
    PgSourceObjectWriteReceiptStore,
    SourceLifecycleState,
    SourceObjectMetadata,
    SourceObjectRecord,
    SourceObjectRepository,
    SourceObjectWriteReceipt,
    SourceObjectType,
    build_source_object_manifest_hash,
    build_source_object_write_receipt,
    sha256_bytes,
)

PROOF_TENANT_ID = "tenant-preview-proof"
PROOF_RUNTIME_CLASS = "runsc"
PROOF_RUN_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{7,79}$")
SHA256_REF_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
IMAGE_DIGEST_REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._/:+-]*@sha256:[a-f0-9]{64}$")
ZERO_HASH = "sha256:" + ("0" * 64)
SYNTHETIC_RTF_BYTES = (
    b"{\\rtf1\\ansi\\deff0{\\fonttbl{\\f0 Liberation Sans;}}"
    b"\\fs24 Collabio synthetic non-empty preview recovery proof.}"
)


class PreviewConversionProofStageReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    proof_run_id: str
    tenant_id: str
    development_only: bool = True
    synthetic_fixture: bool = True
    production_admission_requested: bool = False
    source_object_ref_hash: str
    source_write_receipt_hash: str
    execution_gate_evidence_hash: str
    command_hash: str
    source_content_hash: str
    worker_image_ref: str
    sandbox_runtime_class: str
    backup_restore_evidence_hash: str
    input_workspace_ready: bool
    output_workspace_ready: bool
    content_included: bool = False
    staged_at_utc: datetime
    report_hash: str
    schema_version: str = "source_object_preview_conversion_non_empty_stage.v1"

    @field_validator(
        "source_object_ref_hash",
        "source_write_receipt_hash",
        "execution_gate_evidence_hash",
        "command_hash",
        "source_content_hash",
        "backup_restore_evidence_hash",
        "report_hash",
    )
    @classmethod
    def require_sha256_ref(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("preview conversion proof hashes must be sha256 references")
        return value

    @field_validator("worker_image_ref")
    @classmethod
    def require_pinned_worker_image(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not IMAGE_DIGEST_REF_PATTERN.fullmatch(normalized):
            raise ValueError("preview conversion proof worker image must be digest pinned")
        return normalized

    @model_validator(mode="after")
    def require_development_only_stage(self) -> PreviewConversionProofStageReport:
        if self.tenant_id != PROOF_TENANT_ID:
            raise ValueError("preview conversion proof must use its dedicated synthetic tenant")
        if not PROOF_RUN_ID_PATTERN.fullmatch(self.proof_run_id):
            raise ValueError("preview conversion proof run ID is invalid")
        if self.sandbox_runtime_class != PROOF_RUNTIME_CLASS:
            raise ValueError("preview conversion proof requires runsc")
        if not self.development_only or not self.synthetic_fixture:
            raise ValueError("preview conversion proof stage must remain synthetic and development-only")
        if self.production_admission_requested or self.content_included:
            raise ValueError("preview conversion proof stage cannot request production admission or include content")
        if not self.input_workspace_ready or not self.output_workspace_ready:
            raise ValueError("preview conversion proof workspaces must be ready before execution")
        return self


class PreviewConversionNonEmptyProofReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    proof_run_id: str
    tenant_id: str
    development_only: bool = True
    synthetic_fixture: bool = True
    production_admission_requested: bool = False
    source_object_ref_hash: str
    derived_object_ref_hash: str
    execution_gate_evidence_hash: str
    command_hash: str
    result_hash: str
    source_write_receipt_hash: str
    derived_write_receipt_hash: str
    derived_preview_receipt_hash: str
    job_evidence_hash: str
    worker_image_ref: str
    sandbox_runtime_class: str
    output_content_hash: str
    output_content_byte_length: int = Field(ge=1)
    page_count: int = Field(ge=1)
    technical_conversion_verified: bool
    persistent_lineage_verified: bool
    transient_input_destroyed: bool
    transient_output_destroyed: bool
    external_network_used_by_worker: bool
    conversion_dispatch_allowed: bool = False
    preview_serving_allowed: bool = False
    production_admission_evidence_ready: bool = False
    content_included: bool = False
    completed_at_utc: datetime
    report_hash: str
    schema_version: str = "source_object_preview_conversion_non_empty_proof.v1"

    @field_validator(
        "source_object_ref_hash",
        "derived_object_ref_hash",
        "execution_gate_evidence_hash",
        "command_hash",
        "result_hash",
        "source_write_receipt_hash",
        "derived_write_receipt_hash",
        "derived_preview_receipt_hash",
        "job_evidence_hash",
        "output_content_hash",
        "report_hash",
    )
    @classmethod
    def require_sha256_ref(cls, value: str) -> str:
        if not SHA256_REF_PATTERN.fullmatch(value):
            raise ValueError("preview conversion proof hashes must be sha256 references")
        return value

    @field_validator("worker_image_ref")
    @classmethod
    def require_pinned_worker_image(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not IMAGE_DIGEST_REF_PATTERN.fullmatch(normalized):
            raise ValueError("preview conversion proof worker image must be digest pinned")
        return normalized

    @model_validator(mode="after")
    def require_fail_closed_proof(self) -> PreviewConversionNonEmptyProofReport:
        if self.tenant_id != PROOF_TENANT_ID or not PROOF_RUN_ID_PATTERN.fullmatch(self.proof_run_id):
            raise ValueError("preview conversion proof identity is invalid")
        if self.sandbox_runtime_class != PROOF_RUNTIME_CLASS:
            raise ValueError("preview conversion proof requires runsc")
        required = (
            self.development_only,
            self.synthetic_fixture,
            self.technical_conversion_verified,
            self.persistent_lineage_verified,
            self.transient_input_destroyed,
            self.transient_output_destroyed,
        )
        forbidden = (
            self.production_admission_requested,
            self.external_network_used_by_worker,
            self.conversion_dispatch_allowed,
            self.preview_serving_allowed,
            self.production_admission_evidence_ready,
            self.content_included,
        )
        if not all(required) or any(forbidden):
            raise ValueError("preview conversion proof must remain verified, synthetic, and fail closed")
        return self


@dataclass(frozen=True)
class PreviewConversionProofStageBundle:
    source_record: SourceObjectRecord
    source_write_receipt: SourceObjectWriteReceipt
    execution_gate: PreviewConversionExecutionGateEvidence
    envelope: PreviewConversionWorkerEnvelope
    report: PreviewConversionProofStageReport


class DerivedPreviewCommitter(Protocol):
    def commit(self, artifact: DerivedPreviewArtifact) -> DerivedPreviewArtifact: ...


class PostgresPreviewConversionProofStageUnitOfWork:
    def __init__(
        self,
        *,
        database_dsn: str,
        source_repository: PgSourceObjectRepository,
        source_write_receipt_store: PgSourceObjectWriteReceiptStore,
        execution_gate_store: PgPreviewConversionExecutionGateStore,
    ) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn
        self.source_repository = source_repository
        self.source_write_receipt_store = source_write_receipt_store
        self.execution_gate_store = execution_gate_store

    def commit(self, bundle: PreviewConversionProofStageBundle) -> PreviewConversionProofStageBundle:
        tenant_id = bundle.source_record.metadata.tenant_id
        with psycopg.connect(self.database_dsn) as connection, connection.transaction():
            connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))
            self.source_write_receipt_store.append_in_transaction(connection, bundle.source_write_receipt)
            self.source_repository.add_with_receipt_in_transaction(
                connection,
                record=bundle.source_record,
                source_object_write_receipt_hash=bundle.source_write_receipt.receipt_hash,
            )
            self.execution_gate_store.append_in_transaction(connection, bundle.execution_gate)
        return bundle


def build_preview_conversion_proof_stage_bundle(
    *,
    proof_run_id: str,
    worker_image_ref: str,
    sandbox_runtime_evidence_hash: str,
    font_baseline_hash: str,
    backup_restore_evidence_hash: str,
    staged_at_utc: datetime | None = None,
) -> PreviewConversionProofStageBundle:
    normalized_run_id = proof_run_id.strip().lower()
    if not PROOF_RUN_ID_PATTERN.fullmatch(normalized_run_id):
        raise ValueError("preview conversion proof run ID must be lowercase letters, digits, and hyphens")
    staged_at = staged_at_utc or datetime.now(UTC)
    timestamp = staged_at.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    source_record = _build_synthetic_source_record(proof_run_id=normalized_run_id, timestamp=timestamp)
    fixture_evidence_hash = stable_hash(
        canonical_json(
            {
                "generator": "collabio.synthetic_preview_recovery_fixture.v1",
                "proof_run_id": normalized_run_id,
                "source_content_hash": source_record.metadata.content_hash,
            }
        )
    )
    execution_gate = build_preview_conversion_execution_gate(
        tenant_id=PROOF_TENANT_ID,
        worker_image_ref=worker_image_ref,
        sandbox_runtime_class=PROOF_RUNTIME_CLASS,
        sandbox_runtime_evidence_hash=sandbox_runtime_evidence_hash,
        malware_scanner_profile_ref="synthetic-fixture:trusted-generator.v1",
        malware_scanner_evidence_hash=fixture_evidence_hash,
        cdr_profile_ref="synthetic-fixture:no-active-content.v1",
        cdr_evidence_hash=stable_hash(f"{fixture_evidence_hash}:cdr"),
        pdf_validator_profile_ref="qpdf-pdfinfo:preview-proof.v1",
        pdf_validator_evidence_hash=stable_hash("qpdf-pdfinfo:preview-proof.v1"),
        font_baseline_hash=font_baseline_hash,
        backup_restore_evidence_hash=backup_restore_evidence_hash,
        viewer_origin="https://preview-proof.invalid",
        viewer_csp_evidence_hash=stable_hash("preview-proof-viewer-csp:disabled.v1"),
        evaluated_at_utc=staged_at,
        validity_hours=1,
    )
    source_preflight = build_preview_conversion_source_preflight(
        source_metadata=source_record.metadata,
        scanner_profile_ref="synthetic-fixture:trusted-generator.v1",
        scanner_signature_set_hash=fixture_evidence_hash,
        cdr_profile_ref="synthetic-fixture:no-active-content.v1",
        checked_at_utc=staged_at,
        validity_hours=1,
    )
    command = build_preview_conversion_command(
        source_metadata=source_record.metadata,
        adapter_id="canonical-pdf-libreoffice-pdfjs.v1",
        adapter_descriptor_hash=stable_hash("canonical-pdf-libreoffice-pdfjs.v1:descriptor"),
        adapter_plan_hash=stable_hash("canonical-pdf-libreoffice-pdfjs.v1:synthetic-proof-plan"),
        conversion_route="isolated_office_to_pdf",
        preview_slot_id="document-body",
        preview_policy_id="synthetic-preview-proof.v1",
        renderer_release_gate_evidence_hash=stable_hash("synthetic-preview-proof:renderer-release-disabled"),
        execution_gate=execution_gate,
        source_preflight=source_preflight,
        requested_by="system-preview-proof",
        reason="synthetic non-empty preview restore proof",
        requested_at_utc=staged_at,
    )
    source_receipt = build_source_object_write_receipt(
        record=source_record,
        receipt_reference=f"preview-proof-source:{normalized_run_id}",
        audit_chain_ref=source_record.metadata.audit_chain_ref,
        captured_at_utc=timestamp,
    )
    envelope = PreviewConversionWorkerEnvelope(
        command=command,
        execution_gate=execution_gate,
        source_preflight=source_preflight,
    )
    report_draft = PreviewConversionProofStageReport(
        proof_run_id=normalized_run_id,
        tenant_id=PROOF_TENANT_ID,
        source_object_ref_hash=_object_ref_hash(source_record),
        source_write_receipt_hash=source_receipt.receipt_hash,
        execution_gate_evidence_hash=execution_gate.evidence_hash,
        command_hash=command.command_hash,
        source_content_hash=source_record.metadata.content_hash,
        worker_image_ref=worker_image_ref,
        sandbox_runtime_class=PROOF_RUNTIME_CLASS,
        backup_restore_evidence_hash=backup_restore_evidence_hash,
        input_workspace_ready=True,
        output_workspace_ready=True,
        staged_at_utc=staged_at,
        report_hash=ZERO_HASH,
    )
    report = report_draft.model_copy(update={"report_hash": build_preview_conversion_stage_report_hash(report_draft)})
    return PreviewConversionProofStageBundle(
        source_record=source_record,
        source_write_receipt=source_receipt,
        execution_gate=execution_gate,
        envelope=envelope,
        report=report,
    )


def stage_preview_conversion_proof_workspaces(
    *,
    bundle: PreviewConversionProofStageBundle,
    input_dir: Path,
    output_dir: Path,
) -> None:
    _clear_workspace(input_dir)
    _clear_workspace(output_dir)
    _write_bytes_atomically(input_dir / bundle.envelope.command.input_filename, SYNTHETIC_RTF_BYTES)
    _write_json_atomically(input_dir / "request.json", bundle.envelope.model_dump(mode="json"))
    _prepare_worker_ownership(input_dir=input_dir, output_dir=output_dir)


def import_preview_conversion_non_empty_proof(
    *,
    proof_run_id: str,
    source_repository: SourceObjectRepository,
    committer: DerivedPreviewCommitter,
    input_dir: Path,
    output_dir: Path,
    completed_at_utc: datetime | None = None,
) -> PreviewConversionNonEmptyProofReport:
    normalized_run_id = proof_run_id.strip().lower()
    if not PROOF_RUN_ID_PATTERN.fullmatch(normalized_run_id):
        raise ValueError("preview conversion proof run ID is invalid")
    report: PreviewConversionNonEmptyProofReport | None = None
    try:
        envelope = PreviewConversionWorkerEnvelope.model_validate_json(
            (input_dir / "request.json").read_text(encoding="utf-8")
        )
        _require_expected_proof_envelope(envelope=envelope, proof_run_id=normalized_run_id)
        result = PreviewConversionWorkerResult.model_validate_json(
            (output_dir / "result.json").read_text(encoding="utf-8")
        )
        source = source_repository.get(
            tenant_id=PROOF_TENANT_ID,
            object_id=envelope.command.source_object_id,
            version_id=envelope.command.source_version_id,
        )
        pdf_bytes = (output_dir / envelope.command.output_filename).read_bytes()
        artifact = build_derived_preview_artifact(
            source_record=source,
            pdf_bytes=pdf_bytes,
            command=envelope.command,
            result=result,
            execution_gate=envelope.execution_gate,
            source_preflight=envelope.source_preflight,
            audit_event_id=f"preview-proof-{normalized_run_id}",
            created_at_utc=completed_at_utc or datetime.now(UTC),
        )
        committer.commit(artifact)
        persisted = source_repository.get(
            tenant_id=PROOF_TENANT_ID,
            object_id=artifact.record.metadata.object_id,
            version_id=artifact.record.metadata.version_id,
        )
        if persisted.metadata.manifest_hash != artifact.record.metadata.manifest_hash:
            raise ValueError("persisted preview proof manifest does not match imported artifact")
        _clear_workspace(input_dir)
        _clear_workspace(output_dir)
        report = _build_final_report(
            proof_run_id=normalized_run_id,
            source=source,
            artifact=artifact,
            result=result,
            input_destroyed=not any(input_dir.iterdir()),
            output_destroyed=not any(output_dir.iterdir()),
            completed_at_utc=completed_at_utc or datetime.now(UTC),
        )
        return report
    finally:
        if report is None:
            _clear_workspace(input_dir)
            _clear_workspace(output_dir)


def build_preview_conversion_stage_report_hash(report: PreviewConversionProofStageReport) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"report_hash"})))


def build_preview_conversion_non_empty_proof_report_hash(report: PreviewConversionNonEmptyProofReport) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"report_hash"})))


def persist_preview_conversion_proof_report(
    *,
    report: PreviewConversionProofStageReport | PreviewConversionNonEmptyProofReport,
    report_path: Path,
) -> None:
    expected_hash = (
        build_preview_conversion_stage_report_hash(report)
        if isinstance(report, PreviewConversionProofStageReport)
        else build_preview_conversion_non_empty_proof_report_hash(report)
    )
    if report.report_hash != expected_hash:
        raise ValueError("preview conversion proof report hash is invalid")
    _write_json_atomically(report_path, report.model_dump(mode="json"))


def run_preview_conversion_proof_stage_from_environment(
    env: Mapping[str, str],
) -> PreviewConversionProofStageReport:
    input_dir = Path(env.get("SUITE_PREVIEW_PROOF_INPUT_DIR", "/job/proof-input"))
    output_dir = Path(env.get("SUITE_PREVIEW_PROOF_OUTPUT_DIR", "/job/proof-output"))
    _require_job_workspace(input_dir)
    _require_job_workspace(output_dir)
    foundation_gate = load_backend_foundation_completion_gate(
        Path(_required_env(env, "SUITE_BACKEND_FOUNDATION_GATE_REPORT_PATH"))
    )
    if not foundation_gate.backend_foundation_complete:
        raise ValueError("preview conversion proof requires a successful prior backend restore gate")
    database_dsn = _required_env(env, "SUITE_DATABASE_DSN")
    source_repository = build_default_workspace_source_object_repository(env)
    if not isinstance(source_repository, PgSourceObjectRepository):
        raise ValueError("preview conversion proof requires the PostgreSQL SourceObject repository")
    bundle = build_preview_conversion_proof_stage_bundle(
        proof_run_id=_required_env(env, "SUITE_PREVIEW_PROOF_RUN_ID"),
        worker_image_ref=_required_env(env, "SUITE_PREVIEW_CONVERTER_IMAGE_REF"),
        sandbox_runtime_evidence_hash=_required_env(env, "SUITE_PREVIEW_PROOF_RUNSC_EVIDENCE_HASH"),
        font_baseline_hash=build_installed_font_baseline_hash(),
        backup_restore_evidence_hash=foundation_gate.gate_hash,
    )
    stage_uow = PostgresPreviewConversionProofStageUnitOfWork(
        database_dsn=database_dsn,
        source_repository=source_repository,
        source_write_receipt_store=PgSourceObjectWriteReceiptStore(database_dsn=database_dsn),
        execution_gate_store=PgPreviewConversionExecutionGateStore(database_dsn=database_dsn),
    )
    stage_uow.commit(bundle)
    stage_preview_conversion_proof_workspaces(bundle=bundle, input_dir=input_dir, output_dir=output_dir)
    report_path = Path(_required_env(env, "SUITE_PREVIEW_PROOF_STAGE_REPORT_PATH"))
    persist_preview_conversion_proof_report(report=bundle.report, report_path=report_path)
    return bundle.report


def run_preview_conversion_proof_import_from_environment(
    env: Mapping[str, str],
) -> PreviewConversionNonEmptyProofReport:
    input_dir = Path(env.get("SUITE_PREVIEW_PROOF_INPUT_DIR", "/job/proof-input"))
    output_dir = Path(env.get("SUITE_PREVIEW_PROOF_OUTPUT_DIR", "/job/proof-output"))
    _require_job_workspace(input_dir)
    _require_job_workspace(output_dir)
    database_dsn = _required_env(env, "SUITE_DATABASE_DSN")
    source_repository = build_default_workspace_source_object_repository(env)
    if not isinstance(source_repository, PgSourceObjectRepository):
        raise ValueError("preview conversion proof requires the PostgreSQL SourceObject repository")
    committer = PostgresDerivedPreviewWriteUnitOfWork(
        database_dsn=database_dsn,
        source_repository=source_repository,
        source_object_write_receipt_store=PgSourceObjectWriteReceiptStore(database_dsn=database_dsn),
        derived_preview_receipt_store=PgDerivedPreviewReceiptStore(database_dsn=database_dsn),
        job_evidence_store=PgPreviewConversionJobEvidenceStore(database_dsn=database_dsn),
    )
    report = import_preview_conversion_non_empty_proof(
        proof_run_id=_required_env(env, "SUITE_PREVIEW_PROOF_RUN_ID"),
        source_repository=source_repository,
        committer=committer,
        input_dir=input_dir,
        output_dir=output_dir,
    )
    persist_preview_conversion_proof_report(
        report=report,
        report_path=Path(_required_env(env, "SUITE_PREVIEW_PROOF_REPORT_PATH")),
    )
    return report


def cleanup_preview_conversion_proof_workspaces(env: Mapping[str, str]) -> dict[str, object]:
    input_dir = Path(env.get("SUITE_PREVIEW_PROOF_INPUT_DIR", "/job/proof-input"))
    output_dir = Path(env.get("SUITE_PREVIEW_PROOF_OUTPUT_DIR", "/job/proof-output"))
    _require_job_workspace(input_dir)
    _require_job_workspace(output_dir)
    _clear_workspace(input_dir)
    _clear_workspace(output_dir)
    return {
        "schema_version": "source_object_preview_conversion_proof_cleanup.v1",
        "input_workspace_empty": not any(input_dir.iterdir()),
        "output_workspace_empty": not any(output_dir.iterdir()),
        "content_included": False,
    }


def _build_synthetic_source_record(*, proof_run_id: str, timestamp: str) -> SourceObjectRecord:
    source_id = f"preview-proof-source-{stable_hash(proof_run_id).removeprefix('sha256:')[:24]}"
    draft = SourceObjectMetadata(
        tenant_id=PROOF_TENANT_ID,
        object_id=source_id,
        object_type=SourceObjectType.DOCUMENT,
        version_id="v1",
        title="Synthetic non-empty preview recovery proof",
        owner_principal_id="system-preview-proof",
        created_by="system-preview-proof",
        created_at_utc=timestamp,
        updated_at_utc=timestamp,
        classification=DataClass.INTERNAL,
        retention_policy_id="rp-standard",
        legal_hold_state=LegalHoldState.NONE,
        kms_key_ref=f"kms://{PROOF_TENANT_ID}/internal/v1",
        manifest_hash=ZERO_HASH,
        audit_chain_ref=f"audit:preview-proof:{proof_run_id}:source",
        source_system="collabio.synthetic_preview_proof",
        schema_version="source_object.synthetic_preview_proof.v1",
        mime_type="application/rtf",
        acl_hash=stable_hash(f"preview-proof-acl:{proof_run_id}"),
        acl_version=1,
        content_hash=sha256_bytes(SYNTHETIC_RTF_BYTES),
        content_byte_length=len(SYNTHETIC_RTF_BYTES),
        lifecycle_state=SourceLifecycleState.SAVED_VERSION,
        parser_profile_id="synthetic-rtf.preview-proof.v1",
    )
    metadata = draft.model_copy(update={"manifest_hash": build_source_object_manifest_hash(draft)})
    return SourceObjectRecord(metadata=metadata, content_bytes=SYNTHETIC_RTF_BYTES)


def _build_final_report(
    *,
    proof_run_id: str,
    source: SourceObjectRecord,
    artifact: DerivedPreviewArtifact,
    result: PreviewConversionWorkerResult,
    input_destroyed: bool,
    output_destroyed: bool,
    completed_at_utc: datetime,
) -> PreviewConversionNonEmptyProofReport:
    draft = PreviewConversionNonEmptyProofReport(
        proof_run_id=proof_run_id,
        tenant_id=PROOF_TENANT_ID,
        source_object_ref_hash=_object_ref_hash(source),
        derived_object_ref_hash=_object_ref_hash(artifact.record),
        execution_gate_evidence_hash=artifact.job_evidence.execution_gate_evidence_hash,
        command_hash=artifact.job_evidence.command_hash,
        result_hash=result.result_hash,
        source_write_receipt_hash=build_source_object_write_receipt(
            record=source,
            receipt_reference=f"preview-proof-source:{proof_run_id}",
            audit_chain_ref=source.metadata.audit_chain_ref,
            captured_at_utc=source.metadata.created_at_utc,
        ).receipt_hash,
        derived_write_receipt_hash=artifact.source_object_write_receipt.receipt_hash,
        derived_preview_receipt_hash=artifact.derived_preview_receipt.receipt_hash,
        job_evidence_hash=artifact.job_evidence.job_evidence_hash,
        worker_image_ref=result.worker_image_ref,
        sandbox_runtime_class=result.sandbox_runtime_class,
        output_content_hash=result.output_content_hash,
        output_content_byte_length=result.output_content_byte_length,
        page_count=result.page_count,
        technical_conversion_verified=True,
        persistent_lineage_verified=True,
        transient_input_destroyed=input_destroyed,
        transient_output_destroyed=output_destroyed,
        external_network_used_by_worker=result.external_network_used,
        completed_at_utc=completed_at_utc,
        report_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"report_hash": build_preview_conversion_non_empty_proof_report_hash(draft)})


def _require_expected_proof_envelope(*, envelope: PreviewConversionWorkerEnvelope, proof_run_id: str) -> None:
    expected_source_id = f"preview-proof-source-{stable_hash(proof_run_id).removeprefix('sha256:')[:24]}"
    if envelope.command.tenant_id != PROOF_TENANT_ID:
        raise ValueError("preview conversion proof envelope tenant mismatch")
    if envelope.command.source_object_id != expected_source_id or envelope.command.source_version_id != "v1":
        raise ValueError("preview conversion proof envelope source identity mismatch")
    if envelope.execution_gate.sandbox_runtime_class != PROOF_RUNTIME_CLASS:
        raise ValueError("preview conversion proof envelope does not require runsc")
    if envelope.command.preview_policy_id != "synthetic-preview-proof.v1":
        raise ValueError("preview conversion proof envelope policy mismatch")


def _object_ref_hash(record: SourceObjectRecord) -> str:
    metadata = record.metadata
    return stable_hash("\x1f".join((metadata.tenant_id, metadata.object_id, metadata.version_id)))


def _require_job_workspace(path: Path) -> None:
    resolved = path.resolve()
    job_root = Path("/job").resolve()
    if resolved == job_root or job_root not in resolved.parents:
        raise ValueError("preview conversion proof workspace must be a child of /job")
    if path.is_symlink():
        raise ValueError("preview conversion proof workspace must not be a symlink")


def _clear_workspace(path: Path) -> None:
    if path.is_symlink():
        raise ValueError("preview conversion proof workspace must not be a symlink")
    path.mkdir(parents=True, exist_ok=True)
    for child in path.iterdir():
        if child.is_symlink() or child.is_file():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)
        else:
            raise ValueError("preview conversion proof workspace contains an unsupported entry")


def _prepare_worker_ownership(*, input_dir: Path, output_dir: Path) -> None:
    for directory in (input_dir, output_dir):
        directory.chmod(0o700)
        if os.geteuid() == 0:
            os.chown(directory, 10002, 10002)
    for path in input_dir.iterdir():
        path.chmod(0o440)
        if os.geteuid() == 0:
            os.chown(path, 10002, 10002)


def _write_bytes_atomically(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_bytes(payload)
    temporary_path.replace(path)


def _write_json_atomically(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def _required_env(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ValueError(f"Required environment variable missing: {name}")
    return value


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Controlled Collabio non-empty preview conversion proof")
    parser.add_argument("mode", choices=("stage", "import", "cleanup"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.mode == "stage":
        payload: BaseModel | dict[str, object] = run_preview_conversion_proof_stage_from_environment(os.environ)
    elif args.mode == "import":
        payload = run_preview_conversion_proof_import_from_environment(os.environ)
    else:
        payload = cleanup_preview_conversion_proof_workspaces(os.environ)
    serialized = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
    print(json.dumps(serialized, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
