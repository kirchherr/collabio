from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from suite.ai_control_plane.models import DataClass
from suite.kms.adapter import KmsAdapter, KmsDestroyKeyCommand, KmsKeyDestructionResult
from suite.storage.content_hash import compute_content_hash
from suite.storage.retention import RetentionManifest, build_retention_manifest_hash
from suite.storage.source_objects import LegalHoldState, SourceLifecycleState, SourceObjectRecord

NAMESPACED_REF_PATTERN = re.compile(r"^[a-z][a-z0-9_+.-]*:.+")


class CryptoshredSimulationError(ValueError):
    pass


class CryptoshredSimulationMode(StrEnum):
    LOCAL_DEV_KEY_DESTRUCTION_EVIDENCE = "local_dev_key_destruction_evidence"


class CryptoshredSimulationRequest(BaseModel):
    tenant_id: str
    object_id: str
    source_version_id: str
    record: SourceObjectRecord
    retention_manifest: RetentionManifest
    requested_by: str
    approved_by: str
    approval_ref: str
    audit_chain_ref: str
    occurred_at_utc: str
    reason: str

    @field_validator(
        "tenant_id",
        "object_id",
        "source_version_id",
        "requested_by",
        "approved_by",
        "reason",
    )
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized

    @field_validator("approval_ref", "audit_chain_ref")
    @classmethod
    def require_namespaced_ref(cls, value: str, info: object) -> str:
        normalized = value.strip()
        if not NAMESPACED_REF_PATTERN.fullmatch(normalized):
            field_name = getattr(info, "field_name", "reference")
            raise ValueError(f"{field_name} must be a namespaced reference")
        return normalized

    @field_validator("occurred_at_utc")
    @classmethod
    def require_utc_timestamp(cls, value: str) -> str:
        return _require_utc_timestamp(value)


class CryptoshredSimulationManifest(BaseModel):
    schema_version: str = "cryptoshred_simulation_manifest.v1"
    tenant_id: str
    object_id: str
    source_version_id: str
    classification: DataClass
    retention_policy_id: str
    legal_hold_state: LegalHoldState
    source_lifecycle_state: SourceLifecycleState
    target_lifecycle_state: SourceLifecycleState = SourceLifecycleState.CRYPTOSHREDDED
    kms_key_ref: str
    source_manifest_hash: str
    retention_manifest_hash: str
    retention_policy_snapshot_hash: str
    key_destruction_evidence_hash: str
    simulation_mode: CryptoshredSimulationMode = CryptoshredSimulationMode.LOCAL_DEV_KEY_DESTRUCTION_EVIDENCE
    required_checks: list[str] = Field(min_length=1)
    object_bytes_deleted: bool = False
    plaintext_key_exported: bool = False
    encrypted_content_unreadable: bool = True
    requested_by: str
    approved_by: str
    approval_ref: str
    audit_chain_ref: str
    occurred_at_utc: str
    reason: str
    manifest_hash: str

    @field_validator(
        "tenant_id",
        "object_id",
        "source_version_id",
        "retention_policy_id",
        "requested_by",
        "approved_by",
        "reason",
    )
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized

    @field_validator(
        "kms_key_ref",
        "source_manifest_hash",
        "retention_manifest_hash",
        "retention_policy_snapshot_hash",
        "key_destruction_evidence_hash",
        "approval_ref",
        "audit_chain_ref",
        "manifest_hash",
    )
    @classmethod
    def require_namespaced_ref(cls, value: str, info: object) -> str:
        normalized = value.strip()
        if not NAMESPACED_REF_PATTERN.fullmatch(normalized):
            field_name = getattr(info, "field_name", "reference")
            raise ValueError(f"{field_name} must be a namespaced reference")
        return normalized

    @field_validator("occurred_at_utc")
    @classmethod
    def require_utc_timestamp(cls, value: str) -> str:
        return _require_utc_timestamp(value)

    @model_validator(mode="after")
    def require_safe_simulation_claims(self) -> Self:
        if self.target_lifecycle_state != SourceLifecycleState.CRYPTOSHREDDED:
            raise ValueError("cryptoshred target lifecycle must be cryptoshredded")
        if self.object_bytes_deleted:
            raise ValueError("cryptoshred manifest must not claim object bytes were deleted")
        if self.plaintext_key_exported:
            raise ValueError("cryptoshred manifest must never expose plaintext key export")
        if not self.encrypted_content_unreadable:
            raise ValueError("cryptoshred manifest must mark encrypted content unreadable")
        return self


class CryptoshredSimulationResult(BaseModel):
    manifest: CryptoshredSimulationManifest
    key_destruction: KmsKeyDestructionResult
    verified: bool = True


class CryptoshredService(Protocol):
    def simulate(self, request: CryptoshredSimulationRequest) -> CryptoshredSimulationResult: ...


class LocalCryptoshredSimulator:
    def __init__(self, kms_adapter: KmsAdapter) -> None:
        self.kms_adapter = kms_adapter

    def simulate(self, request: CryptoshredSimulationRequest) -> CryptoshredSimulationResult:
        _require_request_matches_record(request)
        _require_retention_manifest_matches_record(request.retention_manifest, request.record)
        _require_cryptoshred_allowed(request)

        metadata = request.record.metadata
        key_destruction = self.kms_adapter.record_key_destruction(
            KmsDestroyKeyCommand(
                tenant_id=request.tenant_id,
                data_class=metadata.classification,
                kms_key_ref=metadata.kms_key_ref,
                retention_policy_id=metadata.retention_policy_id,
                legal_hold_state=metadata.legal_hold_state.value,
                lifecycle_state=metadata.lifecycle_state.value,
                requested_by=request.requested_by,
                approved_by=request.approved_by,
                approval_ref=request.approval_ref,
                audit_chain_ref=request.audit_chain_ref,
                occurred_at_utc=request.occurred_at_utc,
                reason=request.reason,
            )
        )
        draft = CryptoshredSimulationManifest(
            tenant_id=metadata.tenant_id,
            object_id=metadata.object_id,
            source_version_id=metadata.version_id,
            classification=metadata.classification,
            retention_policy_id=metadata.retention_policy_id,
            legal_hold_state=metadata.legal_hold_state,
            source_lifecycle_state=metadata.lifecycle_state,
            kms_key_ref=metadata.kms_key_ref,
            source_manifest_hash=metadata.manifest_hash,
            retention_manifest_hash=build_retention_manifest_hash(request.retention_manifest),
            retention_policy_snapshot_hash=request.retention_manifest.policy_snapshot_hash,
            key_destruction_evidence_hash=key_destruction.evidence.evidence_hash,
            required_checks=[
                "source_manifest_match",
                "retention_manifest_match",
                "retention_disposition_allowed",
                "legal_hold_absent",
                "protected_record_absent",
                "kms_key_destruction_evidence",
                "no_plaintext_key_export",
            ],
            requested_by=request.requested_by,
            approved_by=request.approved_by,
            approval_ref=request.approval_ref,
            audit_chain_ref=request.audit_chain_ref,
            occurred_at_utc=request.occurred_at_utc,
            reason=request.reason,
            manifest_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        )
        manifest = draft.model_copy(update={"manifest_hash": build_cryptoshred_simulation_manifest_hash(draft)})
        return CryptoshredSimulationResult(manifest=manifest, key_destruction=key_destruction)


def cryptoshred_simulation_manifest_payload(manifest: CryptoshredSimulationManifest) -> dict[str, object]:
    return manifest.model_dump(mode="json", exclude={"manifest_hash"})


def build_cryptoshred_simulation_manifest_hash(manifest: CryptoshredSimulationManifest) -> str:
    manifest_bytes = json.dumps(
        cryptoshred_simulation_manifest_payload(manifest),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return compute_content_hash(manifest_bytes)


def _require_request_matches_record(request: CryptoshredSimulationRequest) -> None:
    metadata = request.record.metadata
    expected_values = {
        "tenant_id": metadata.tenant_id,
        "object_id": metadata.object_id,
        "source_version_id": metadata.version_id,
    }
    actual_values = {
        "tenant_id": request.tenant_id,
        "object_id": request.object_id,
        "source_version_id": request.source_version_id,
    }
    mismatches = sorted(field for field, expected in expected_values.items() if actual_values[field] != expected)
    if mismatches:
        raise CryptoshredSimulationError(f"cryptoshred request does not match source object: {', '.join(mismatches)}")


def _require_retention_manifest_matches_record(
    retention_manifest: RetentionManifest,
    record: SourceObjectRecord,
) -> None:
    metadata = record.metadata
    expected_values = {
        "tenant_id": metadata.tenant_id,
        "object_id": metadata.object_id,
        "source_version_id": metadata.version_id,
        "classification": metadata.classification,
        "retention_policy_id": metadata.retention_policy_id,
        "legal_hold_state": metadata.legal_hold_state,
        "source_manifest_hash": metadata.manifest_hash,
    }
    actual_values = {
        "tenant_id": retention_manifest.tenant_id,
        "object_id": retention_manifest.object_id,
        "source_version_id": retention_manifest.version_id,
        "classification": retention_manifest.classification,
        "retention_policy_id": retention_manifest.retention_policy_id,
        "legal_hold_state": retention_manifest.legal_hold_state,
        "source_manifest_hash": retention_manifest.source_manifest_hash,
    }
    mismatches = sorted(field for field, expected in expected_values.items() if actual_values[field] != expected)
    if mismatches:
        raise CryptoshredSimulationError(f"retention manifest does not match source object: {', '.join(mismatches)}")


def _require_cryptoshred_allowed(request: CryptoshredSimulationRequest) -> None:
    metadata = request.record.metadata
    retention_manifest = request.retention_manifest
    if (
        metadata.legal_hold_state == LegalHoldState.ACTIVE
        or retention_manifest.legal_hold_state == LegalHoldState.ACTIVE
    ):
        raise CryptoshredSimulationError("active legal hold blocks cryptoshred")
    if metadata.classification in {DataClass.GOBD, DataClass.LEGAL_HOLD}:
        raise CryptoshredSimulationError("GoBD and legal-hold data classes block cryptoshred")
    if metadata.lifecycle_state in {SourceLifecycleState.BUSINESS_RECORD, SourceLifecycleState.WORM_EVIDENCE}:
        raise CryptoshredSimulationError("record lifecycle blocks cryptoshred")
    if retention_manifest.deletion_blocked or retention_manifest.worm_required:
        raise CryptoshredSimulationError("retention manifest blocks cryptoshred")
    if retention_manifest.cryptoshred_allowed_before_retention_end:
        return
    if retention_manifest.retain_until_utc is None:
        raise CryptoshredSimulationError("retention policy does not define a cryptoshred release time")
    occurred_at = _parse_utc(request.occurred_at_utc)
    retain_until = _parse_utc(retention_manifest.retain_until_utc)
    if occurred_at < retain_until:
        raise CryptoshredSimulationError("retention period has not ended")


def _require_utc_timestamp(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("timestamp must not be empty")
    _parse_utc(normalized)
    return normalized


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("timestamp must be UTC")
    return parsed.astimezone(UTC)
