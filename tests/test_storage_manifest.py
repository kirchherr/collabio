from pathlib import Path

import pytest

from suite.ai_control_plane.models import DataClass
from suite.storage.adapter_policy import ObjectLockMode, load_storage_adapter_policy
from suite.storage.retention import RetentionManifest, build_retention_manifest, load_retention_manifest_policy
from suite.storage.source_objects import (
    LegalHoldState,
    SourceLifecycleState,
    SourceObjectMetadata,
    SourceObjectRecord,
    SourceObjectType,
    build_source_object_manifest_hash,
    sha256_bytes,
)
from suite.storage.storage_manifest import (
    StorageManifestError,
    StorageObjectManifest,
    StorageRestoreVerificationError,
    build_storage_object_manifest,
    build_storage_object_manifest_hash,
    verify_storage_object_restore,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
RETENTION_POLICY_PATH = REPO_ROOT / "docs" / "retention_manifest_policy.json"
STORAGE_POLICY_PATH = REPO_ROOT / "docs" / "storage_adapter_policy.json"


def record_for(
    *,
    classification: DataClass = DataClass.INTERNAL,
    retention_policy_id: str = "rp-standard",
    lifecycle_state: SourceLifecycleState = SourceLifecycleState.WORKING,
    legal_hold_state: LegalHoldState = LegalHoldState.NONE,
    object_type: SourceObjectType = SourceObjectType.DOCUMENT,
    text: str = "Storage manifest governed content",
) -> SourceObjectRecord:
    content = text.encode("utf-8")
    draft = SourceObjectMetadata(
        tenant_id="tenant-1",
        object_id="doc-1",
        object_type=object_type,
        version_id="v1",
        title="Storage object",
        owner_principal_id="user-owner",
        created_by="user-creator",
        created_at_utc="2026-06-10T00:00:00Z",
        updated_at_utc="2026-06-10T00:01:00Z",
        classification=classification,
        retention_policy_id=retention_policy_id,
        legal_hold_state=legal_hold_state,
        kms_key_ref="kms://tenant-1/internal/v1",
        manifest_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        audit_chain_ref="audit:chain-1",
        source_system="collabio",
        mime_type="text/plain",
        acl_hash="sha256:acl",
        acl_version=1,
        content_hash=sha256_bytes(content),
        content_byte_length=len(content),
        lifecycle_state=lifecycle_state,
    )
    return SourceObjectRecord(
        metadata=draft.model_copy(update={"manifest_hash": build_source_object_manifest_hash(draft)}),
        text=text,
    )


def build_manifest_for(record: SourceObjectRecord) -> tuple[StorageObjectManifest, RetentionManifest]:
    retention_policy = load_retention_manifest_policy(RETENTION_POLICY_PATH)
    storage_policy = load_storage_adapter_policy(STORAGE_POLICY_PATH)
    retention_manifest = build_retention_manifest(record, retention_policy)
    storage_manifest = build_storage_object_manifest(
        record=record,
        retention_manifest=retention_manifest,
        bucket_profile=storage_policy.bucket(retention_manifest.storage_bucket_id),
        object_version_id="s3-version-1",
        stored_at_utc="2026-06-11T00:00:00Z",
    )
    return storage_manifest, retention_manifest


def test_storage_manifest_for_standard_source_records_restore_evidence() -> None:
    record = record_for()
    storage_manifest, retention_manifest = build_manifest_for(record)

    result = verify_storage_object_restore(
        manifest=storage_manifest,
        record=record,
        retention_manifest=retention_manifest,
        restored_content=record.text.encode("utf-8"),
    )

    assert storage_manifest.schema_version == "storage_object_manifest.v1"
    assert storage_manifest.bucket_id == "working-objects"
    assert storage_manifest.object_key == "tenant-1/document/doc-1/v1/content"
    assert storage_manifest.object_version_id == "s3-version-1"
    assert storage_manifest.object_lock_mode == ObjectLockMode.NONE
    assert storage_manifest.manifest_hash == build_storage_object_manifest_hash(storage_manifest)
    assert result.verified is True
    assert result.content_hash_verification.verification_context == "restore"
    assert "storage_object_manifest_hash_check" in result.checks
    assert "content_hash_verifier_check" in result.checks


def test_storage_manifest_for_gobd_business_record_requires_object_lock() -> None:
    record = record_for(
        classification=DataClass.GOBD,
        retention_policy_id="rp-gobd-10y",
        lifecycle_state=SourceLifecycleState.BUSINESS_RECORD,
    )
    storage_manifest, retention_manifest = build_manifest_for(record)

    assert storage_manifest.bucket_id == "business-records"
    assert storage_manifest.worm_required
    assert storage_manifest.object_lock_mode == ObjectLockMode.COMPLIANCE
    assert storage_manifest.object_lock_retain_until_utc == retention_manifest.retain_until_utc
    assert not storage_manifest.object_lock_legal_hold


def test_storage_manifest_for_active_legal_hold_records_object_lock_hold() -> None:
    record = record_for(
        classification=DataClass.LEGAL_HOLD,
        retention_policy_id="rp-legal-hold",
        lifecycle_state=SourceLifecycleState.WORM_EVIDENCE,
        legal_hold_state=LegalHoldState.ACTIVE,
    )
    storage_manifest, _retention_manifest = build_manifest_for(record)

    assert storage_manifest.bucket_id == "evidence-records"
    assert storage_manifest.object_lock_mode == ObjectLockMode.COMPLIANCE
    assert storage_manifest.object_lock_retain_until_utc is None
    assert storage_manifest.object_lock_legal_hold


def test_storage_manifest_rejects_bucket_profile_mismatch() -> None:
    record = record_for(
        classification=DataClass.GOBD,
        retention_policy_id="rp-gobd-10y",
        lifecycle_state=SourceLifecycleState.BUSINESS_RECORD,
    )
    retention_policy = load_retention_manifest_policy(RETENTION_POLICY_PATH)
    storage_policy = load_storage_adapter_policy(STORAGE_POLICY_PATH)
    retention_manifest = build_retention_manifest(record, retention_policy)

    with pytest.raises(StorageManifestError, match="bucket profile"):
        build_storage_object_manifest(
            record=record,
            retention_manifest=retention_manifest,
            bucket_profile=storage_policy.bucket("working-objects"),
            object_version_id="s3-version-1",
            stored_at_utc="2026-06-11T00:00:00Z",
        )


def test_restore_verification_rejects_tampered_storage_manifest_hash() -> None:
    record = record_for()
    storage_manifest, retention_manifest = build_manifest_for(record)
    tampered = storage_manifest.model_copy(update={"manifest_hash": "sha256:" + "1" * 64})

    with pytest.raises(StorageRestoreVerificationError, match="manifest_hash"):
        verify_storage_object_restore(
            manifest=tampered,
            record=record,
            retention_manifest=retention_manifest,
            restored_content=record.text.encode("utf-8"),
        )


def test_restore_verification_rejects_content_hash_mismatch() -> None:
    record = record_for()
    storage_manifest, retention_manifest = build_manifest_for(record)

    with pytest.raises(StorageRestoreVerificationError, match="content_hash"):
        verify_storage_object_restore(
            manifest=storage_manifest,
            record=record,
            retention_manifest=retention_manifest,
            restored_content=b"tampered restore bytes",
        )


def test_restore_verification_rejects_retention_manifest_mismatch() -> None:
    record = record_for()
    storage_manifest, retention_manifest = build_manifest_for(record)
    tampered = storage_manifest.model_copy(update={"retention_policy_snapshot_hash": "sha256:" + "2" * 64})
    tampered = tampered.model_copy(update={"manifest_hash": build_storage_object_manifest_hash(tampered)})

    with pytest.raises(StorageRestoreVerificationError, match="retention manifest"):
        verify_storage_object_restore(
            manifest=tampered,
            record=record,
            retention_manifest=retention_manifest,
            restored_content=record.text.encode("utf-8"),
        )
