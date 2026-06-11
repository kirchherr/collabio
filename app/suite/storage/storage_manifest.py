from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Self

from pydantic import BaseModel, Field, field_validator, model_validator

from suite.ai_control_plane.models import DataClass
from suite.kms.adapter import KmsKeyReference, KmsKeyReferenceError
from suite.storage.adapter_policy import BucketProfile, ObjectLockMode
from suite.storage.content_hash import (
    ContentHashVerificationError,
    ContentHashVerificationResult,
    compute_content_hash,
    verify_content_hash,
)
from suite.storage.retention import RetentionManifest, build_retention_manifest_hash
from suite.storage.source_objects import (
    LegalHoldState,
    SourceLifecycleState,
    SourceObjectRecord,
    SourceObjectType,
    build_source_object_manifest_hash,
    source_object_content_bytes,
)

NAMESPACED_REF_PATTERN = re.compile(r"^[a-z][a-z0-9_+.-]*:.+")


class StorageManifestError(ValueError):
    pass


class StorageRestoreVerificationError(ValueError):
    pass


class StorageObjectManifest(BaseModel):
    schema_version: str = "storage_object_manifest.v1"
    tenant_id: str
    object_id: str
    object_type: SourceObjectType
    source_version_id: str
    bucket_id: str
    object_key: str
    object_version_id: str
    storage_provider: str = "s3-compatible"
    stored_at_utc: str
    classification: DataClass
    lifecycle_state: SourceLifecycleState
    retention_policy_id: str
    legal_hold_state: LegalHoldState
    kms_key_ref: str
    source_manifest_hash: str
    content_hash: str
    content_byte_length: int = Field(ge=0)
    retention_manifest_hash: str
    retention_policy_snapshot_hash: str
    object_lock_mode: ObjectLockMode
    object_lock_retain_until_utc: str | None = None
    object_lock_legal_hold: bool = False
    worm_required: bool
    audit_chain_ref: str
    manifest_hash: str

    @field_validator(
        "schema_version",
        "tenant_id",
        "object_id",
        "source_version_id",
        "bucket_id",
        "object_key",
        "object_version_id",
        "storage_provider",
        "retention_policy_id",
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
        "content_hash",
        "retention_manifest_hash",
        "retention_policy_snapshot_hash",
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

    @field_validator("stored_at_utc", "object_lock_retain_until_utc")
    @classmethod
    def require_utc_timestamp(cls, value: str | None, info: object) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        if not normalized:
            field_name = getattr(info, "field_name", "timestamp")
            raise ValueError(f"{field_name} must not be empty")
        _parse_utc(normalized)
        return normalized

    @model_validator(mode="after")
    def require_consistent_object_lock(self) -> Self:
        if self.worm_required and self.object_lock_mode == ObjectLockMode.NONE:
            raise ValueError("WORM storage manifests require object lock")
        if self.object_lock_retain_until_utc is not None and self.object_lock_mode == ObjectLockMode.NONE:
            raise ValueError("object_lock_retain_until_utc requires object lock")
        if self.object_lock_legal_hold and self.object_lock_mode == ObjectLockMode.NONE:
            raise ValueError("object_lock_legal_hold requires object lock")
        if self.object_lock_mode != ObjectLockMode.NONE and not (
            self.object_lock_retain_until_utc or self.object_lock_legal_hold
        ):
            raise ValueError("object-lock manifests require retain-until or legal-hold evidence")
        return self


class StorageRestoreVerificationResult(BaseModel):
    verified: bool = True
    manifest_hash: str
    source_manifest_hash: str
    retention_manifest_hash: str
    content_hash: str
    bucket_id: str
    object_key: str
    object_version_id: str
    checks: tuple[str, ...]
    content_hash_verification: ContentHashVerificationResult


def storage_object_manifest_payload(manifest: StorageObjectManifest) -> dict[str, object]:
    return manifest.model_dump(mode="json", exclude={"manifest_hash"})


def build_storage_object_manifest_hash(manifest: StorageObjectManifest) -> str:
    manifest_bytes = json.dumps(
        storage_object_manifest_payload(manifest),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return compute_content_hash(manifest_bytes)


def build_storage_object_key(record: SourceObjectRecord) -> str:
    metadata = record.metadata
    return f"{metadata.tenant_id}/{metadata.object_type.value}/{metadata.object_id}/{metadata.version_id}/content"


def build_storage_object_manifest(
    *,
    record: SourceObjectRecord,
    retention_manifest: RetentionManifest,
    bucket_profile: BucketProfile,
    object_version_id: str,
    stored_at_utc: str,
    object_key: str | None = None,
    storage_provider: str = "s3-compatible",
) -> StorageObjectManifest:
    _require_source_matches_retention(record, retention_manifest)
    _require_kms_reference_matches_source(record)
    _require_bucket_matches_retention(bucket_profile, retention_manifest)
    try:
        verify_content_hash(
            content=source_object_content_bytes(record),
            expected_hash=record.metadata.content_hash,
            verification_context="storage_manifest_build",
        )
    except ContentHashVerificationError as exc:
        raise StorageManifestError(f"content_hash verification failed: {exc}") from exc

    metadata = record.metadata
    object_lock_legal_hold = (
        retention_manifest.legal_hold_state == LegalHoldState.ACTIVE and bucket_profile.legal_hold_supported
    )
    draft = StorageObjectManifest(
        tenant_id=metadata.tenant_id,
        object_id=metadata.object_id,
        object_type=metadata.object_type,
        source_version_id=metadata.version_id,
        bucket_id=bucket_profile.bucket_id,
        object_key=object_key or build_storage_object_key(record),
        object_version_id=object_version_id,
        storage_provider=storage_provider,
        stored_at_utc=stored_at_utc,
        classification=metadata.classification,
        lifecycle_state=metadata.lifecycle_state,
        retention_policy_id=metadata.retention_policy_id,
        legal_hold_state=metadata.legal_hold_state,
        kms_key_ref=metadata.kms_key_ref,
        source_manifest_hash=metadata.manifest_hash,
        content_hash=metadata.content_hash,
        content_byte_length=metadata.content_byte_length,
        retention_manifest_hash=build_retention_manifest_hash(retention_manifest),
        retention_policy_snapshot_hash=retention_manifest.policy_snapshot_hash,
        object_lock_mode=retention_manifest.object_lock_mode,
        object_lock_retain_until_utc=retention_manifest.retain_until_utc
        if retention_manifest.object_lock_mode != ObjectLockMode.NONE
        else None,
        object_lock_legal_hold=object_lock_legal_hold,
        worm_required=retention_manifest.worm_required,
        audit_chain_ref=metadata.audit_chain_ref,
        manifest_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
    )
    return draft.model_copy(update={"manifest_hash": build_storage_object_manifest_hash(draft)})


def verify_storage_object_restore(
    *,
    manifest: StorageObjectManifest,
    record: SourceObjectRecord,
    retention_manifest: RetentionManifest,
    restored_content: bytes,
) -> StorageRestoreVerificationResult:
    _require_manifest_hash_match(manifest)
    _require_manifest_matches_source(manifest, record)
    _require_manifest_matches_retention(manifest, retention_manifest)
    try:
        content_result = verify_content_hash(
            content=restored_content,
            expected_hash=manifest.content_hash,
            verification_context="restore",
        )
    except ContentHashVerificationError as exc:
        raise StorageRestoreVerificationError(f"content_hash verification failed: {exc}") from exc

    if manifest.content_byte_length != len(restored_content):
        raise StorageRestoreVerificationError("content_byte_length does not match restored content")

    return StorageRestoreVerificationResult(
        manifest_hash=manifest.manifest_hash,
        source_manifest_hash=manifest.source_manifest_hash,
        retention_manifest_hash=manifest.retention_manifest_hash,
        content_hash=manifest.content_hash,
        bucket_id=manifest.bucket_id,
        object_key=manifest.object_key,
        object_version_id=manifest.object_version_id,
        checks=(
            "storage_object_manifest_hash_check",
            "source_object_manifest_hash_check",
            "retention_manifest_hash_check",
            "retention_policy_snapshot_hash_check",
            "content_hash_verifier_check",
            "object_lock_configuration_check",
            "legal_hold_check",
        ),
        content_hash_verification=content_result,
    )


def _require_source_matches_retention(record: SourceObjectRecord, retention_manifest: RetentionManifest) -> None:
    metadata = record.metadata
    expected_values = {
        "tenant_id": metadata.tenant_id,
        "object_id": metadata.object_id,
        "object_type": metadata.object_type,
        "version_id": metadata.version_id,
        "classification": metadata.classification,
        "lifecycle_state": metadata.lifecycle_state,
        "retention_policy_id": metadata.retention_policy_id,
        "legal_hold_state": metadata.legal_hold_state,
    }
    actual_values = {
        "tenant_id": retention_manifest.tenant_id,
        "object_id": retention_manifest.object_id,
        "object_type": retention_manifest.object_type,
        "version_id": retention_manifest.version_id,
        "classification": retention_manifest.classification,
        "lifecycle_state": retention_manifest.lifecycle_state,
        "retention_policy_id": retention_manifest.retention_policy_id,
        "legal_hold_state": retention_manifest.legal_hold_state,
    }
    mismatches = sorted(field for field, expected in expected_values.items() if actual_values[field] != expected)
    if mismatches:
        raise StorageManifestError(f"retention manifest does not match source object: {', '.join(mismatches)}")
    if retention_manifest.source_manifest_hash != metadata.manifest_hash:
        raise StorageManifestError("retention manifest source_manifest_hash does not match source object")


def _require_kms_reference_matches_source(record: SourceObjectRecord) -> None:
    metadata = record.metadata
    try:
        key_ref = KmsKeyReference.parse(metadata.kms_key_ref)
    except KmsKeyReferenceError as exc:
        raise StorageManifestError(f"kms_key_ref invalid: {exc}") from exc
    if key_ref.tenant_id != metadata.tenant_id:
        raise StorageManifestError("kms_key_ref tenant_id does not match source object")
    if key_ref.data_class != metadata.classification:
        raise StorageManifestError("kms_key_ref data_class does not match source object")


def _require_bucket_matches_retention(bucket_profile: BucketProfile, retention_manifest: RetentionManifest) -> None:
    if bucket_profile.bucket_id != retention_manifest.storage_bucket_id:
        raise StorageManifestError("bucket profile does not match retention manifest storage_bucket_id")
    if retention_manifest.object_type.value not in bucket_profile.source_object_types:
        raise StorageManifestError("bucket profile does not allow source object type")
    if retention_manifest.lifecycle_state.value not in bucket_profile.lifecycle_states:
        raise StorageManifestError("bucket profile does not allow lifecycle state")
    if bucket_profile.object_lock_mode != retention_manifest.object_lock_mode:
        raise StorageManifestError("bucket profile object lock mode does not match retention manifest")
    if retention_manifest.worm_required and not bucket_profile.object_lock_required:
        raise StorageManifestError("WORM retention requires object-lock bucket profile")
    if (
        retention_manifest.legal_hold_state == LegalHoldState.ACTIVE
        and retention_manifest.object_lock_mode != ObjectLockMode.NONE
        and not bucket_profile.legal_hold_supported
    ):
        raise StorageManifestError("active legal hold requires bucket legal-hold support")


def _require_manifest_hash_match(manifest: StorageObjectManifest) -> None:
    expected_hash = build_storage_object_manifest_hash(manifest)
    if manifest.manifest_hash != expected_hash:
        raise StorageRestoreVerificationError("storage object manifest_hash does not match manifest payload")


def _require_manifest_matches_source(manifest: StorageObjectManifest, record: SourceObjectRecord) -> None:
    metadata = record.metadata
    expected_source_manifest_hash = build_source_object_manifest_hash(metadata)
    if metadata.manifest_hash != expected_source_manifest_hash:
        raise StorageRestoreVerificationError("source object manifest_hash does not match source metadata")

    expected_values = {
        "tenant_id": metadata.tenant_id,
        "object_id": metadata.object_id,
        "object_type": metadata.object_type,
        "source_version_id": metadata.version_id,
        "classification": metadata.classification,
        "lifecycle_state": metadata.lifecycle_state,
        "retention_policy_id": metadata.retention_policy_id,
        "legal_hold_state": metadata.legal_hold_state,
        "kms_key_ref": metadata.kms_key_ref,
        "source_manifest_hash": metadata.manifest_hash,
        "content_hash": metadata.content_hash,
        "content_byte_length": metadata.content_byte_length,
        "audit_chain_ref": metadata.audit_chain_ref,
    }
    actual_values = {
        "tenant_id": manifest.tenant_id,
        "object_id": manifest.object_id,
        "object_type": manifest.object_type,
        "source_version_id": manifest.source_version_id,
        "classification": manifest.classification,
        "lifecycle_state": manifest.lifecycle_state,
        "retention_policy_id": manifest.retention_policy_id,
        "legal_hold_state": manifest.legal_hold_state,
        "kms_key_ref": manifest.kms_key_ref,
        "source_manifest_hash": manifest.source_manifest_hash,
        "content_hash": manifest.content_hash,
        "content_byte_length": manifest.content_byte_length,
        "audit_chain_ref": manifest.audit_chain_ref,
    }
    mismatches = sorted(field for field, expected in expected_values.items() if actual_values[field] != expected)
    if mismatches:
        raise StorageRestoreVerificationError(f"storage manifest does not match source object: {', '.join(mismatches)}")


def _require_manifest_matches_retention(
    manifest: StorageObjectManifest,
    retention_manifest: RetentionManifest,
) -> None:
    expected_retention_manifest_hash = build_retention_manifest_hash(retention_manifest)
    if manifest.retention_manifest_hash != expected_retention_manifest_hash:
        raise StorageRestoreVerificationError("retention_manifest_hash does not match retention manifest")

    expected_values = {
        "bucket_id": retention_manifest.storage_bucket_id,
        "retention_policy_snapshot_hash": retention_manifest.policy_snapshot_hash,
        "object_lock_mode": retention_manifest.object_lock_mode,
        "object_lock_retain_until_utc": retention_manifest.retain_until_utc
        if retention_manifest.object_lock_mode != ObjectLockMode.NONE
        else None,
        "worm_required": retention_manifest.worm_required,
    }
    actual_values = {
        "bucket_id": manifest.bucket_id,
        "retention_policy_snapshot_hash": manifest.retention_policy_snapshot_hash,
        "object_lock_mode": manifest.object_lock_mode,
        "object_lock_retain_until_utc": manifest.object_lock_retain_until_utc,
        "worm_required": manifest.worm_required,
    }
    mismatches = sorted(field for field, expected in expected_values.items() if actual_values[field] != expected)
    if mismatches:
        raise StorageRestoreVerificationError(
            f"storage manifest does not match retention manifest: {', '.join(mismatches)}"
        )

    if (
        retention_manifest.legal_hold_state == LegalHoldState.ACTIVE
        and manifest.object_lock_mode != ObjectLockMode.NONE
        and not manifest.object_lock_legal_hold
    ):
        raise StorageRestoreVerificationError("active legal hold requires object-lock legal-hold evidence")


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("timestamp must be UTC")
    return parsed.astimezone(UTC)
