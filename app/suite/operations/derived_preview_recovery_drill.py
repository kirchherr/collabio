from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.operations.backend_foundation_completion_gate import (
    BackendFoundationCompletionGate,
    build_backend_foundation_completion_gate_hash,
    load_backend_foundation_completion_gate,
    run_backend_foundation_completion_gate_from_environment,
)
from suite.platform.source_object_preview_conversion import (
    DerivedPreviewReceipt,
    DerivedPreviewReceiptStore,
    PgDerivedPreviewReceiptStore,
    PgPreviewConversionExecutionGateStore,
    PgPreviewConversionJobEvidenceStore,
    PreviewConversionBlocked,
    PreviewConversionExecutionGateEvidence,
    PreviewConversionExecutionGateStore,
    PreviewConversionGateStatus,
    PreviewConversionJobEvidence,
    PreviewConversionJobEvidenceStore,
    build_derived_preview_receipt_hash,
    build_preview_conversion_execution_gate_hash,
    build_preview_conversion_job_evidence_hash,
    validate_derived_preview_pdf_bytes,
)
from suite.platform.workspace_source_objects import build_default_workspace_source_object_repository
from suite.storage.source_objects import (
    PgSourceObjectWriteReceiptStore,
    SourceObjectRecord,
    SourceObjectRepository,
    SourceObjectType,
    SourceObjectWriteReceipt,
    SourceObjectWriteReceiptStore,
    build_source_object_manifest_hash,
    build_source_object_write_receipt_hash,
    source_object_content_bytes,
)

SHA256_REF_PREFIX = "sha256:"
ZERO_HASH = SHA256_REF_PREFIX + ("0" * 64)


class DerivedPreviewRecoveryItemEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str
    job_evidence_hash: str
    derived_preview_receipt_hash: str
    source_object_ref_hash: str
    derived_object_ref_hash: str
    source_object_write_receipt_hash: str
    execution_gate_evidence_hash: str
    job_evidence_verified: bool
    lineage_receipt_verified: bool
    source_object_write_receipt_verified: bool
    execution_gate_verified: bool
    source_exact_version_verified: bool
    derived_exact_version_verified: bool
    derived_pdf_verified: bool
    source_lineage_verified: bool
    derived_lineage_verified: bool
    inherited_controls_verified: bool
    temporal_binding_verified: bool
    item_recovery_ready: bool
    blocking_reasons: tuple[str, ...]
    content_included: bool = False
    evidence_hash: str
    schema_version: str = "source_object_derived_preview_recovery_item.v1"

    @field_validator(
        "job_evidence_hash",
        "derived_preview_receipt_hash",
        "source_object_ref_hash",
        "derived_object_ref_hash",
        "source_object_write_receipt_hash",
        "execution_gate_evidence_hash",
        "evidence_hash",
    )
    @classmethod
    def require_sha256_ref(cls, value: str) -> str:
        if len(value) != 71 or not value.startswith(SHA256_REF_PREFIX):
            raise ValueError("derived preview recovery hashes must be sha256 references")
        int(value.removeprefix(SHA256_REF_PREFIX), 16)
        return value

    @model_validator(mode="after")
    def require_consistent_state(self) -> DerivedPreviewRecoveryItemEvidence:
        checks = (
            self.job_evidence_verified,
            self.lineage_receipt_verified,
            self.source_object_write_receipt_verified,
            self.execution_gate_verified,
            self.source_exact_version_verified,
            self.derived_exact_version_verified,
            self.derived_pdf_verified,
            self.source_lineage_verified,
            self.derived_lineage_verified,
            self.inherited_controls_verified,
            self.temporal_binding_verified,
        )
        if self.item_recovery_ready != (all(checks) and not self.blocking_reasons):
            raise ValueError("derived preview recovery item state is inconsistent")
        if self.content_included:
            raise ValueError("derived preview recovery item must be metadata-only")
        return self


class DerivedPreviewRecoveryDrillReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    checked_at_utc: str
    backend_foundation_gate_hash: str
    postgres_restore_drill_report_hash: str
    backend_storage_foundation_gate_hash: str
    tenant_ids: tuple[str, ...]
    derived_preview_receipt_count: int = Field(ge=0)
    conversion_job_evidence_count: int = Field(ge=0)
    reconciled_item_count: int = Field(ge=0)
    recovery_item_evidence_hashes: tuple[str, ...]
    failed_job_evidence_hashes: tuple[str, ...]
    orphaned_derived_preview_receipt_hashes: tuple[str, ...]
    backend_foundation_verified: bool
    tenant_scope_verified: bool
    empty_state_verified: bool
    non_empty_recovery_verified: bool
    metadata_only_evidence_verified: bool
    recovery_ready: bool
    production_admission_evidence_ready: bool
    conversion_dispatch_allowed: bool = False
    preview_serving_allowed: bool = False
    blocking_reasons: tuple[str, ...]
    content_included: bool = False
    report_hash: str
    schema_version: str = "source_object_derived_preview_recovery_drill_report.v1"

    @field_validator(
        "backend_foundation_gate_hash",
        "postgres_restore_drill_report_hash",
        "backend_storage_foundation_gate_hash",
        "report_hash",
    )
    @classmethod
    def require_sha256_ref(cls, value: str) -> str:
        if len(value) != 71 or not value.startswith(SHA256_REF_PREFIX):
            raise ValueError("derived preview recovery report hashes must be sha256 references")
        int(value.removeprefix(SHA256_REF_PREFIX), 16)
        return value

    @model_validator(mode="after")
    def require_fail_closed_state(self) -> DerivedPreviewRecoveryDrillReport:
        if self.conversion_dispatch_allowed or self.preview_serving_allowed or self.content_included:
            raise ValueError("recovery evidence must not enable conversion or content serving")
        if self.empty_state_verified and self.non_empty_recovery_verified:
            raise ValueError("recovery report cannot describe both empty and non-empty state")
        if self.recovery_ready and not (self.empty_state_verified or self.non_empty_recovery_verified):
            raise ValueError("ready recovery requires verified empty or non-empty state")
        if self.production_admission_evidence_ready and not (self.recovery_ready and self.non_empty_recovery_verified):
            raise ValueError("production admission requires a successful non-empty recovery")
        return self


def run_derived_preview_recovery_drill(
    *,
    foundation_gate: BackendFoundationCompletionGate,
    source_repository: SourceObjectRepository,
    source_object_write_receipt_store: SourceObjectWriteReceiptStore,
    execution_gate_store: PreviewConversionExecutionGateStore,
    derived_preview_receipt_store: DerivedPreviewReceiptStore,
    job_evidence_store: PreviewConversionJobEvidenceStore,
    checked_at_utc: str | None = None,
    production_admission_evaluation_enabled: bool = True,
) -> DerivedPreviewRecoveryDrillReport:
    foundation_hash_verified = (
        build_backend_foundation_completion_gate_hash(foundation_gate) == foundation_gate.gate_hash
    )
    tenant_ids = tuple(sorted(set(foundation_gate.tenant_ids)))
    tenant_scope_verified = bool(tenant_ids) and tenant_ids == foundation_gate.tenant_ids
    items: list[DerivedPreviewRecoveryItemEvidence] = []
    all_receipts: list[DerivedPreviewReceipt] = []
    all_jobs: list[PreviewConversionJobEvidence] = []

    for tenant_id in tenant_ids:
        receipts = tuple(derived_preview_receipt_store.list_receipts(tenant_id=tenant_id))
        jobs = tuple(job_evidence_store.list_evidence(tenant_id=tenant_id))
        all_receipts.extend(receipts)
        all_jobs.extend(jobs)
        for job in jobs:
            items.append(
                _reconcile_item(
                    job=job,
                    source_repository=source_repository,
                    source_object_write_receipt_store=source_object_write_receipt_store,
                    execution_gate_store=execution_gate_store,
                    derived_preview_receipt_store=derived_preview_receipt_store,
                )
            )

    linked_receipt_hashes = {job.derived_preview_receipt_hash for job in all_jobs}
    orphaned_receipt_hashes = tuple(
        sorted(receipt.receipt_hash for receipt in all_receipts if receipt.receipt_hash not in linked_receipt_hashes)
    )
    failed_job_hashes = tuple(sorted(item.job_evidence_hash for item in items if not item.item_recovery_ready))
    blocking_reasons: list[str] = []
    if not foundation_hash_verified or not foundation_gate.backend_foundation_complete:
        blocking_reasons.append("backend_foundation_restore_not_verified")
    if not tenant_scope_verified:
        blocking_reasons.append("tenant_scope_not_verified")
    if failed_job_hashes:
        blocking_reasons.append("derived_preview_items_failed_reconciliation")
    if orphaned_receipt_hashes:
        blocking_reasons.append("derived_preview_receipts_missing_job_evidence")

    empty_state = not all_receipts and not all_jobs
    all_items_ready = len(items) == len(all_jobs) and all(item.item_recovery_ready for item in items)
    non_empty_recovery = bool(all_jobs) and len(all_receipts) == len(all_jobs) and all_items_ready
    recovery_ready = not blocking_reasons and (empty_state or non_empty_recovery)
    checked_at = checked_at_utc or datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    draft = DerivedPreviewRecoveryDrillReport(
        checked_at_utc=checked_at,
        backend_foundation_gate_hash=foundation_gate.gate_hash,
        postgres_restore_drill_report_hash=foundation_gate.postgres_restore_drill_report_hash,
        backend_storage_foundation_gate_hash=foundation_gate.backend_storage_foundation_gate_hash,
        tenant_ids=tenant_ids,
        derived_preview_receipt_count=len(all_receipts),
        conversion_job_evidence_count=len(all_jobs),
        reconciled_item_count=sum(int(item.item_recovery_ready) for item in items),
        recovery_item_evidence_hashes=tuple(sorted(item.evidence_hash for item in items)),
        failed_job_evidence_hashes=failed_job_hashes,
        orphaned_derived_preview_receipt_hashes=orphaned_receipt_hashes,
        backend_foundation_verified=foundation_hash_verified and foundation_gate.backend_foundation_complete,
        tenant_scope_verified=tenant_scope_verified,
        empty_state_verified=empty_state,
        non_empty_recovery_verified=non_empty_recovery,
        metadata_only_evidence_verified=all(not item.content_included for item in items),
        recovery_ready=recovery_ready,
        production_admission_evidence_ready=(
            production_admission_evaluation_enabled and recovery_ready and non_empty_recovery
        ),
        blocking_reasons=tuple(sorted(set(blocking_reasons))),
        report_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"report_hash": build_derived_preview_recovery_drill_report_hash(draft)})


def _reconcile_item(
    *,
    job: PreviewConversionJobEvidence,
    source_repository: SourceObjectRepository,
    source_object_write_receipt_store: SourceObjectWriteReceiptStore,
    execution_gate_store: PreviewConversionExecutionGateStore,
    derived_preview_receipt_store: DerivedPreviewReceiptStore,
) -> DerivedPreviewRecoveryItemEvidence:
    source = _get_record(
        repository=source_repository,
        tenant_id=job.tenant_id,
        object_id=job.source_object_id,
        version_id=job.source_version_id,
    )
    derived = _get_record(
        repository=source_repository,
        tenant_id=job.tenant_id,
        object_id=job.derived_object_id,
        version_id=job.derived_version_id,
    )
    receipt = _get_receipt(derived_preview_receipt_store, job)
    write_receipt = _get_write_receipt(source_object_write_receipt_store, job)
    execution_gate = _get_execution_gate(execution_gate_store, job)

    job_verified = build_preview_conversion_job_evidence_hash(job) == job.job_evidence_hash
    receipt_verified = receipt is not None and build_derived_preview_receipt_hash(receipt) == receipt.receipt_hash
    write_receipt_verified = (
        write_receipt is not None
        and build_source_object_write_receipt_hash(write_receipt) == write_receipt.receipt_hash
        and write_receipt.receipt_hash == job.source_object_write_receipt_hash
    )
    execution_gate_verified = (
        execution_gate is not None
        and build_preview_conversion_execution_gate_hash(execution_gate) == execution_gate.evidence_hash
        and execution_gate.evidence_hash == job.execution_gate_evidence_hash
        and execution_gate.gate_status == PreviewConversionGateStatus.READY
        and execution_gate.worker_image_ref == job.worker_image_ref
    )
    source_exact_version_verified = source is not None and _source_matches_job(source, job)
    derived_exact_version_verified = (
        derived is not None and receipt is not None and _derived_matches_receipt(derived, receipt, job)
    )
    derived_pdf_verified = derived is not None and _validate_recovered_pdf(derived, job)
    source_lineage_verified = source is not None and receipt is not None and _source_matches_receipt(source, receipt)
    derived_lineage_verified = (
        receipt is not None
        and receipt.receipt_hash == job.derived_preview_receipt_hash
        and receipt.command_hash == job.command_hash
        and receipt.source_preflight_evidence_hash == job.source_preflight_evidence_hash
        and receipt.result_hash == job.result_hash
        and receipt.execution_gate_evidence_hash == job.execution_gate_evidence_hash
        and receipt.worker_image_ref == job.worker_image_ref
    )
    inherited_controls_verified = (
        source is not None
        and derived is not None
        and receipt is not None
        and _inherited_controls_match(source, derived, receipt)
    )
    write_receipt_matches = (
        derived is not None and write_receipt is not None and _write_receipt_matches_record(write_receipt, derived)
    )
    source_object_write_receipt_verified = write_receipt_verified and write_receipt_matches
    temporal_binding_verified = (
        execution_gate is not None
        and receipt is not None
        and execution_gate.evaluated_at_utc <= job.command.requested_at_utc
        and job.source_preflight.checked_at_utc <= job.command.requested_at_utc
        and job.command.requested_at_utc <= job.result.completed_at_utc
        and job.result.completed_at_utc <= receipt.created_at_utc
        and receipt.created_at_utc <= execution_gate.expires_at_utc
        and job.command.requested_at_utc <= job.source_preflight.expires_at_utc
    )
    checks = {
        "job_evidence_not_verified": job_verified,
        "lineage_receipt_not_verified": receipt_verified,
        "source_object_write_receipt_not_verified": source_object_write_receipt_verified,
        "execution_gate_not_verified": execution_gate_verified,
        "source_exact_version_not_verified": source_exact_version_verified,
        "derived_exact_version_not_verified": derived_exact_version_verified,
        "derived_pdf_not_verified": derived_pdf_verified,
        "source_lineage_not_verified": source_lineage_verified,
        "derived_lineage_not_verified": derived_lineage_verified,
        "inherited_controls_not_verified": inherited_controls_verified,
        "temporal_binding_not_verified": temporal_binding_verified,
    }
    blocking_reasons = tuple(sorted(reason for reason, passed in checks.items() if not passed))
    draft = DerivedPreviewRecoveryItemEvidence(
        tenant_id=job.tenant_id,
        job_evidence_hash=job.job_evidence_hash,
        derived_preview_receipt_hash=job.derived_preview_receipt_hash,
        source_object_ref_hash=_object_ref_hash(job.tenant_id, job.source_object_id, job.source_version_id),
        derived_object_ref_hash=_object_ref_hash(job.tenant_id, job.derived_object_id, job.derived_version_id),
        source_object_write_receipt_hash=job.source_object_write_receipt_hash,
        execution_gate_evidence_hash=job.execution_gate_evidence_hash,
        job_evidence_verified=job_verified,
        lineage_receipt_verified=receipt_verified,
        source_object_write_receipt_verified=source_object_write_receipt_verified,
        execution_gate_verified=execution_gate_verified,
        source_exact_version_verified=source_exact_version_verified,
        derived_exact_version_verified=derived_exact_version_verified,
        derived_pdf_verified=derived_pdf_verified,
        source_lineage_verified=source_lineage_verified,
        derived_lineage_verified=derived_lineage_verified,
        inherited_controls_verified=inherited_controls_verified,
        temporal_binding_verified=temporal_binding_verified,
        item_recovery_ready=not blocking_reasons,
        blocking_reasons=blocking_reasons,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_derived_preview_recovery_item_hash(draft)})


def _get_record(
    *,
    repository: SourceObjectRepository,
    tenant_id: str,
    object_id: str,
    version_id: str,
) -> SourceObjectRecord | None:
    try:
        return repository.get(tenant_id=tenant_id, object_id=object_id, version_id=version_id)
    except (KeyError, ValueError):
        return None


def _get_receipt(
    store: DerivedPreviewReceiptStore,
    job: PreviewConversionJobEvidence,
) -> DerivedPreviewReceipt | None:
    try:
        return store.get(tenant_id=job.tenant_id, receipt_hash=job.derived_preview_receipt_hash)
    except (KeyError, ValueError):
        return None


def _get_write_receipt(
    store: SourceObjectWriteReceiptStore,
    job: PreviewConversionJobEvidence,
) -> SourceObjectWriteReceipt | None:
    try:
        return store.get(tenant_id=job.tenant_id, receipt_hash=job.source_object_write_receipt_hash)
    except (KeyError, ValueError):
        return None


def _get_execution_gate(
    store: PreviewConversionExecutionGateStore,
    job: PreviewConversionJobEvidence,
) -> PreviewConversionExecutionGateEvidence | None:
    try:
        return store.get(tenant_id=job.tenant_id, evidence_hash=job.execution_gate_evidence_hash)
    except (KeyError, ValueError):
        return None


def _source_matches_job(source: SourceObjectRecord, job: PreviewConversionJobEvidence) -> bool:
    metadata = source.metadata
    return (
        metadata.tenant_id == job.tenant_id
        and metadata.object_id == job.source_object_id
        and metadata.version_id == job.source_version_id
        and metadata.object_type == SourceObjectType.DOCUMENT
        and metadata.manifest_hash == job.command.source_manifest_hash
        and metadata.content_hash == job.command.source_content_hash
        and metadata.acl_version == job.command.source_acl_version
        and build_source_object_manifest_hash(metadata) == metadata.manifest_hash
    )


def _source_matches_receipt(source: SourceObjectRecord, receipt: DerivedPreviewReceipt) -> bool:
    metadata = source.metadata
    return (
        metadata.tenant_id == receipt.tenant_id
        and metadata.object_id == receipt.source_object_id
        and metadata.version_id == receipt.source_version_id
        and metadata.manifest_hash == receipt.source_manifest_hash
        and metadata.content_hash == receipt.source_content_hash
        and metadata.acl_version == receipt.source_acl_version
    )


def _derived_matches_receipt(
    derived: SourceObjectRecord,
    receipt: DerivedPreviewReceipt,
    job: PreviewConversionJobEvidence,
) -> bool:
    metadata = derived.metadata
    return (
        metadata.tenant_id == receipt.tenant_id == job.tenant_id
        and metadata.object_id == receipt.derived_object_id == job.derived_object_id
        and metadata.version_id == receipt.derived_version_id == job.derived_version_id
        and metadata.manifest_hash == receipt.derived_manifest_hash
        and metadata.content_hash == receipt.derived_content_hash == job.result.output_content_hash
        and metadata.content_byte_length == receipt.derived_content_byte_length
        and metadata.mime_type == receipt.derived_mime_type == "application/pdf"
        and metadata.object_type == SourceObjectType.ATTACHMENT
        and metadata.parent_object_id == receipt.source_object_id
        and build_source_object_manifest_hash(metadata) == metadata.manifest_hash
    )


def _inherited_controls_match(
    source: SourceObjectRecord,
    derived: SourceObjectRecord,
    receipt: DerivedPreviewReceipt,
) -> bool:
    source_metadata = source.metadata
    derived_metadata = derived.metadata
    receipt_flags = (
        receipt.source_classification_inherited,
        receipt.source_acl_inherited,
        receipt.source_retention_inherited,
        receipt.source_legal_hold_inherited,
        receipt.source_lifecycle_inherited,
        receipt.source_version_lineage_bound,
        receipt.output_revalidated,
    )
    return all(receipt_flags) and (
        derived_metadata.classification == source_metadata.classification
        and derived_metadata.acl_hash == source_metadata.acl_hash
        and derived_metadata.acl_version == source_metadata.acl_version
        and derived_metadata.retention_policy_id == source_metadata.retention_policy_id
        and derived_metadata.legal_hold_state == source_metadata.legal_hold_state
        and derived_metadata.lifecycle_state == source_metadata.lifecycle_state
        and derived_metadata.kms_key_ref == source_metadata.kms_key_ref
        and derived_metadata.owner_principal_id == source_metadata.owner_principal_id
        and derived_metadata.thread_id == source_metadata.thread_id
    )


def _write_receipt_matches_record(receipt: SourceObjectWriteReceipt, record: SourceObjectRecord) -> bool:
    metadata = record.metadata
    return (
        receipt.tenant_id == metadata.tenant_id
        and receipt.object_id == metadata.object_id
        and receipt.version_id == metadata.version_id
        and receipt.object_type == metadata.object_type
        and receipt.manifest_hash == metadata.manifest_hash
        and receipt.content_hash == metadata.content_hash
        and receipt.content_byte_length == metadata.content_byte_length
        and receipt.classification == metadata.classification
        and receipt.acl_hash == metadata.acl_hash
        and receipt.acl_version == metadata.acl_version
        and receipt.retention_policy_id == metadata.retention_policy_id
        and receipt.legal_hold_state == metadata.legal_hold_state
        and receipt.kms_key_ref == metadata.kms_key_ref
        and receipt.lifecycle_state == metadata.lifecycle_state
        and receipt.parent_object_id == metadata.parent_object_id
    )


def _validate_recovered_pdf(derived: SourceObjectRecord, job: PreviewConversionJobEvidence) -> bool:
    try:
        validate_derived_preview_pdf_bytes(
            pdf_bytes=source_object_content_bytes(derived),
            expected_content_hash=job.result.output_content_hash,
            max_output_bytes=job.result.output_content_byte_length,
        )
    except (PreviewConversionBlocked, ValueError):
        return False
    return True


def _object_ref_hash(tenant_id: str, object_id: str, version_id: str) -> str:
    return stable_hash(canonical_json({"tenant_id": tenant_id, "object_id": object_id, "version_id": version_id}))


def build_derived_preview_recovery_item_hash(item: DerivedPreviewRecoveryItemEvidence) -> str:
    return stable_hash(canonical_json(item.model_dump(mode="json", exclude={"evidence_hash"})))


def build_derived_preview_recovery_drill_report_hash(report: DerivedPreviewRecoveryDrillReport) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"report_hash"})))


def persist_derived_preview_recovery_drill_report(
    *,
    report: DerivedPreviewRecoveryDrillReport,
    report_path: Path,
) -> None:
    if build_derived_preview_recovery_drill_report_hash(report) != report.report_hash:
        raise ValueError("derived preview recovery drill report hash is invalid")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(report.model_dump(mode="json"), sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(report_path)


def load_derived_preview_recovery_drill_report(report_path: Path) -> DerivedPreviewRecoveryDrillReport:
    report = DerivedPreviewRecoveryDrillReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    if build_derived_preview_recovery_drill_report_hash(report) != report.report_hash:
        raise ValueError("persisted derived preview recovery drill report hash is invalid")
    return report


def run_derived_preview_recovery_drill_from_environment(
    env: Mapping[str, str],
) -> DerivedPreviewRecoveryDrillReport:
    foundation_report_path = env.get("SUITE_BACKEND_FOUNDATION_GATE_REPORT_PATH", "").strip()
    if foundation_report_path and Path(foundation_report_path).is_file():
        foundation_gate = load_backend_foundation_completion_gate(Path(foundation_report_path))
    else:
        foundation_gate = run_backend_foundation_completion_gate_from_environment(env)
    target_dsn = _required_env(env, "SUITE_DERIVED_PREVIEW_RESTORE_TARGET_DSN")
    target_env = dict(env)
    target_env.update(
        {
            "SUITE_WORKSPACE_SOURCE_OBJECT_REPOSITORY_BACKEND": "postgres",
            "SUITE_WORKSPACE_SOURCE_OBJECT_REPOSITORY_DSN": target_dsn,
            "SUITE_WORKSPACE_SOURCE_OBJECT_CONTENT_STORE_BACKEND": "s3-compatible",
            "SUITE_S3_ENDPOINT_URL": _required_env(env, "SUITE_RESTORE_S3_ENDPOINT_URL"),
            "SUITE_S3_ACCESS_KEY_ID": _required_env(env, "SUITE_RESTORE_S3_ACCESS_KEY_ID"),
            "SUITE_S3_SECRET_ACCESS_KEY": _required_env(env, "SUITE_RESTORE_S3_SECRET_ACCESS_KEY"),
            "SUITE_S3_REGION": env.get("SUITE_RESTORE_S3_REGION", "us-east-1"),
            "SUITE_S3_STORAGE_PROVIDER": env.get("SUITE_RESTORE_S3_STORAGE_PROVIDER", "s3-compatible-restore"),
        }
    )
    return run_derived_preview_recovery_drill(
        foundation_gate=foundation_gate,
        source_repository=build_default_workspace_source_object_repository(target_env),
        source_object_write_receipt_store=PgSourceObjectWriteReceiptStore(database_dsn=target_dsn),
        execution_gate_store=PgPreviewConversionExecutionGateStore(database_dsn=target_dsn),
        derived_preview_receipt_store=PgDerivedPreviewReceiptStore(database_dsn=target_dsn),
        job_evidence_store=PgPreviewConversionJobEvidenceStore(database_dsn=target_dsn),
        production_admission_evaluation_enabled=_env_bool(
            env.get("SUITE_DERIVED_PREVIEW_PRODUCTION_ADMISSION_EVALUATION_ENABLED"),
            default=False,
        ),
    )


def _required_env(env: Mapping[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ValueError(f"Required environment variable missing: {name}")
    return value


def _env_bool(value: str | None, *, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError("Boolean environment value must use true/false, 1/0, yes/no, or on/off")


def main() -> None:
    report = run_derived_preview_recovery_drill_from_environment(os.environ)
    report_path = os.environ.get("SUITE_DERIVED_PREVIEW_RECOVERY_REPORT_PATH", "").strip()
    if report_path:
        persist_derived_preview_recovery_drill_report(report=report, report_path=Path(report_path))
    print(json.dumps(report.model_dump(mode="json"), sort_keys=True))
    raise SystemExit(0 if report.recovery_ready else 2)


if __name__ == "__main__":
    main()
