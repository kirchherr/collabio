from dataclasses import dataclass
from pathlib import Path

import pytest

from suite.ai_control_plane.models import DataClass
from suite.storage.adapter_policy import ObjectLockMode, load_storage_adapter_policy
from suite.storage.s3_compatible_content_store import (
    S3CompatibleBucketCapabilities,
    S3CompatibleObjectWriteResult,
    S3CompatibleProviderProfileStatus,
    S3CompatibleSourceObjectContentStore,
    S3CompatibleStoredObjectVersion,
    build_s3_compatible_provider_profile_evidence,
    build_s3_compatible_provider_profile_evidence_hash,
    build_s3_restore_binding_metadata,
)
from suite.storage.source_object_storage import SourceObjectStorageError, StoredSourceObjectContent
from suite.storage.source_objects import (
    LegalHoldState,
    SourceLifecycleState,
    SourceObjectMetadata,
    SourceObjectRecord,
    SourceObjectType,
    build_source_object_manifest_hash,
    sha256_bytes,
)
from suite.storage.storage_manifest import StorageObjectManifest

REPO_ROOT = Path(__file__).resolve().parents[1]
STORAGE_POLICY_PATH = REPO_ROOT / "docs" / "storage_adapter_policy.json"


@dataclass(frozen=True)
class FakeS3StoredObject:
    body: bytes
    version: S3CompatibleStoredObjectVersion
    object_lock_mode: ObjectLockMode
    legal_hold: bool


class FakeS3CompatibleClient:
    def __init__(self, capabilities: dict[str, S3CompatibleBucketCapabilities]) -> None:
        self.capabilities = capabilities
        self.objects: dict[tuple[str, str, str], FakeS3StoredObject] = {}
        self.version_counter = 0

    def bucket_capabilities(self, *, bucket_id: str) -> S3CompatibleBucketCapabilities:
        return self.capabilities[bucket_id]

    def put_object(
        self,
        *,
        bucket_id: str,
        object_key: str,
        body: bytes,
        metadata: dict[str, str],
        object_lock_mode: ObjectLockMode,
        legal_hold: bool,
    ) -> S3CompatibleObjectWriteResult:
        self.version_counter += 1
        object_version_id = f"version-{self.version_counter}"
        stored_at_utc = f"2026-06-12T12:{self.version_counter:02d}:00Z"
        result = S3CompatibleObjectWriteResult(
            bucket_id=bucket_id,
            object_key=object_key,
            object_version_id=object_version_id,
            storage_provider="fake-s3-compatible",
            stored_at_utc=stored_at_utc,
        )
        version = S3CompatibleStoredObjectVersion(
            bucket_id=bucket_id,
            object_key=object_key,
            object_version_id=object_version_id,
            storage_provider=result.storage_provider,
            stored_at_utc=stored_at_utc,
            metadata=metadata,
        )
        self.objects[(bucket_id, object_key, object_version_id)] = FakeS3StoredObject(
            body=body,
            version=version,
            object_lock_mode=object_lock_mode,
            legal_hold=legal_hold,
        )
        return result

    def get_object(self, *, bucket_id: str, object_key: str, object_version_id: str) -> bytes:
        return self.objects[(bucket_id, object_key, object_version_id)].body

    def list_object_versions(
        self,
        *,
        bucket_id: str,
        prefix: str,
    ) -> tuple[S3CompatibleStoredObjectVersion, ...]:
        return tuple(
            stored.version
            for (stored_bucket_id, object_key, _object_version_id), stored in sorted(self.objects.items())
            if stored_bucket_id == bucket_id and object_key.startswith(prefix)
        )

    def stored_object(self, content: StoredSourceObjectContent) -> FakeS3StoredObject:
        return self.objects[(content.bucket_id, content.object_key, content.object_version_id)]


def source_record_for_s3_content_store(
    *,
    tenant_id: str,
    object_id: str,
    text: str,
    legal_hold_state: LegalHoldState = LegalHoldState.NONE,
    lifecycle_state: SourceLifecycleState = SourceLifecycleState.SAVED_VERSION,
) -> SourceObjectRecord:
    content = text.encode("utf-8")
    draft = SourceObjectMetadata(
        tenant_id=tenant_id,
        object_id=object_id,
        object_type=SourceObjectType.WIKI,
        version_id="v1",
        title="S3 content store source",
        owner_principal_id=f"user-{tenant_id}",
        created_by=f"tenant-admin-{tenant_id}",
        created_at_utc="2026-06-12T12:00:00Z",
        updated_at_utc="2026-06-12T12:00:00Z",
        classification=DataClass.INTERNAL,
        retention_policy_id="rp-standard",
        legal_hold_state=legal_hold_state,
        kms_key_ref=f"kms://{tenant_id}/internal/v1",
        manifest_hash="sha256:" + "0" * 64,
        audit_chain_ref=f"audit:{object_id}",
        source_system="collabio",
        mime_type="text/plain",
        acl_hash="sha256:" + "a" * 64,
        acl_version=3,
        content_hash=sha256_bytes(content),
        content_byte_length=len(content),
        lifecycle_state=lifecycle_state,
    )
    return SourceObjectRecord(
        metadata=draft.model_copy(update={"manifest_hash": build_source_object_manifest_hash(draft)}),
        text=text,
    )


def storage_manifest_for_s3_content(
    *,
    record: SourceObjectRecord,
    content: StoredSourceObjectContent,
    object_lock_mode: ObjectLockMode = ObjectLockMode.NONE,
    object_lock_legal_hold: bool = False,
) -> StorageObjectManifest:
    metadata = record.metadata
    return StorageObjectManifest(
        tenant_id=metadata.tenant_id,
        object_id=metadata.object_id,
        object_type=metadata.object_type,
        source_version_id=metadata.version_id,
        bucket_id=content.bucket_id,
        object_key=content.object_key,
        object_version_id=content.object_version_id,
        storage_provider=content.storage_provider,
        stored_at_utc=content.stored_at_utc,
        classification=metadata.classification,
        lifecycle_state=metadata.lifecycle_state,
        retention_policy_id=metadata.retention_policy_id,
        legal_hold_state=metadata.legal_hold_state,
        kms_key_ref=metadata.kms_key_ref,
        source_manifest_hash=metadata.manifest_hash,
        content_hash=metadata.content_hash,
        content_byte_length=metadata.content_byte_length,
        retention_manifest_hash="sha256:" + "b" * 64,
        retention_policy_snapshot_hash="sha256:" + "c" * 64,
        object_lock_mode=object_lock_mode,
        object_lock_retain_until_utc="2033-06-12T12:00:00Z" if object_lock_mode != ObjectLockMode.NONE else None,
        object_lock_legal_hold=object_lock_legal_hold,
        worm_required=object_lock_mode != ObjectLockMode.NONE,
        audit_chain_ref=metadata.audit_chain_ref,
        manifest_hash="sha256:" + "d" * 64,
    )


def s3_capabilities(*, object_lock_enabled: bool = True) -> dict[str, S3CompatibleBucketCapabilities]:
    return {
        "working-objects": S3CompatibleBucketCapabilities(
            bucket_id="working-objects",
            versioning_enabled=True,
        ),
        "business-records": S3CompatibleBucketCapabilities(
            bucket_id="business-records",
            versioning_enabled=True,
            object_lock_enabled=object_lock_enabled,
            legal_hold_supported=object_lock_enabled,
        ),
        "evidence-records": S3CompatibleBucketCapabilities(
            bucket_id="evidence-records",
            versioning_enabled=True,
            object_lock_enabled=True,
            legal_hold_supported=True,
        ),
        "parser-artifacts": S3CompatibleBucketCapabilities(
            bucket_id="parser-artifacts",
            versioning_enabled=True,
        ),
    }


def test_s3_compatible_content_store_put_get_and_inventory_are_metadata_only() -> None:
    policy = load_storage_adapter_policy(STORAGE_POLICY_PATH)
    client = FakeS3CompatibleClient(s3_capabilities())
    store = S3CompatibleSourceObjectContentStore(client=client, storage_policy=policy)
    record = source_record_for_s3_content_store(
        tenant_id="tenant-s3",
        object_id="kb-article-version-s3-v1",
        text="S3-compatible source bytes must never leak into inventory evidence.",
    )

    stored = store.put(
        record=record,
        bucket_id="working-objects",
        object_key=f"{record.metadata.tenant_id}/wiki/{record.metadata.object_id}/v1/content",
    )
    manifest = storage_manifest_for_s3_content(record=record, content=stored)

    assert store.get(manifest=manifest) == record.text.encode("utf-8")
    assert store.list_stored_objects(tenant_id=record.metadata.tenant_id) == (stored,)
    assert "S3-compatible source bytes" not in stored.model_dump_json()
    assert client.stored_object(stored).version.metadata["kms_key_ref_hash"].startswith("sha256:")


def test_s3_compatible_content_store_resolves_exact_restored_version_from_bound_metadata() -> None:
    policy = load_storage_adapter_policy(STORAGE_POLICY_PATH)
    source_client = FakeS3CompatibleClient(s3_capabilities())
    source_store = S3CompatibleSourceObjectContentStore(client=source_client, storage_policy=policy)
    record = source_record_for_s3_content_store(
        tenant_id="tenant-restore",
        object_id="kb-article-version-restore-v1",
        text="Restore resolution must remain bound to the authoritative source manifest.",
    )
    source_content = source_store.put(
        record=record,
        bucket_id="working-objects",
        object_key=f"{record.metadata.tenant_id}/wiki/{record.metadata.object_id}/v1/content",
    )
    manifest = storage_manifest_for_s3_content(record=record, content=source_content)
    target_client = FakeS3CompatibleClient(s3_capabilities())
    target_client.put_object(
        bucket_id=manifest.bucket_id,
        object_key=manifest.object_key,
        body=record.text.encode("utf-8"),
        metadata=build_s3_restore_binding_metadata(manifest),
        object_lock_mode=manifest.object_lock_mode,
        legal_hold=manifest.object_lock_legal_hold,
    )
    target_store = S3CompatibleSourceObjectContentStore(
        client=target_client,
        storage_policy=policy,
        restore_reference_resolution_enabled=True,
    )

    assert target_store.get(manifest=manifest) == record.text.encode("utf-8")


def test_s3_compatible_restore_resolution_rejects_unbound_target_version() -> None:
    policy = load_storage_adapter_policy(STORAGE_POLICY_PATH)
    source_client = FakeS3CompatibleClient(s3_capabilities())
    source_store = S3CompatibleSourceObjectContentStore(client=source_client, storage_policy=policy)
    record = source_record_for_s3_content_store(
        tenant_id="tenant-restore-blocked",
        object_id="kb-article-version-restore-blocked-v1",
        text="An unbound restore object must not be accepted.",
    )
    source_content = source_store.put(
        record=record,
        bucket_id="working-objects",
        object_key=f"{record.metadata.tenant_id}/wiki/{record.metadata.object_id}/v1/content",
    )
    manifest = storage_manifest_for_s3_content(record=record, content=source_content)
    target_client = FakeS3CompatibleClient(s3_capabilities())
    target_client.put_object(
        bucket_id=manifest.bucket_id,
        object_key=manifest.object_key,
        body=record.text.encode("utf-8"),
        metadata={"storage_manifest_hash": "sha256:" + "f" * 64},
        object_lock_mode=manifest.object_lock_mode,
        legal_hold=manifest.object_lock_legal_hold,
    )
    target_store = S3CompatibleSourceObjectContentStore(
        client=target_client,
        storage_policy=policy,
        restore_reference_resolution_enabled=True,
    )

    with pytest.raises(SourceObjectStorageError, match="exact restored object version binding not found"):
        target_store.get(manifest=manifest)


def test_s3_compatible_content_store_requires_object_lock_for_worm_bucket() -> None:
    policy = load_storage_adapter_policy(STORAGE_POLICY_PATH)
    client = FakeS3CompatibleClient(s3_capabilities(object_lock_enabled=False))
    store = S3CompatibleSourceObjectContentStore(client=client, storage_policy=policy)
    record = source_record_for_s3_content_store(
        tenant_id="tenant-s3-worm",
        object_id="kb-article-version-s3-worm-v1",
        text="WORM bucket writes require Object Lock evidence.",
        lifecycle_state=SourceLifecycleState.BUSINESS_RECORD,
    )

    with pytest.raises(SourceObjectStorageError, match="Object Lock"):
        store.put(
            record=record,
            bucket_id="business-records",
            object_key=f"{record.metadata.tenant_id}/wiki/{record.metadata.object_id}/v1/content",
        )


def test_s3_compatible_content_store_maps_legal_hold_to_object_lock_write() -> None:
    policy = load_storage_adapter_policy(STORAGE_POLICY_PATH)
    client = FakeS3CompatibleClient(s3_capabilities())
    store = S3CompatibleSourceObjectContentStore(client=client, storage_policy=policy)
    record = source_record_for_s3_content_store(
        tenant_id="tenant-s3-hold",
        object_id="kb-article-version-s3-hold-v1",
        text="Legal hold must travel to the object-store write options.",
        legal_hold_state=LegalHoldState.ACTIVE,
        lifecycle_state=SourceLifecycleState.BUSINESS_RECORD,
    )

    stored = store.put(
        record=record,
        bucket_id="business-records",
        object_key=f"{record.metadata.tenant_id}/wiki/{record.metadata.object_id}/v1/content",
    )

    fake_stored_object = client.stored_object(stored)
    assert fake_stored_object.object_lock_mode == ObjectLockMode.COMPLIANCE
    assert fake_stored_object.legal_hold is True


def test_s3_compatible_provider_profile_evidence_allows_ready_profile() -> None:
    policy = load_storage_adapter_policy(STORAGE_POLICY_PATH)
    client = FakeS3CompatibleClient(s3_capabilities())

    evidence = build_s3_compatible_provider_profile_evidence(
        client=client,
        storage_policy=policy,
        provider_profile_id="minio-dev-object-lock",
        checked_at_utc="2026-06-12T12:10:00Z",
    )

    assert evidence.provider_profile_ready is True
    assert evidence.profile_status == S3CompatibleProviderProfileStatus.READY
    assert evidence.bucket_profile_count == 4
    assert evidence.object_lock_bucket_count == 2
    assert evidence.versioning_verified is True
    assert evidence.object_lock_verified is True
    assert evidence.legal_hold_verified is True
    assert evidence.blocking_reasons == ()
    assert evidence.evidence_hash == build_s3_compatible_provider_profile_evidence_hash(evidence)


def test_s3_compatible_provider_profile_evidence_blocks_missing_object_lock() -> None:
    policy = load_storage_adapter_policy(STORAGE_POLICY_PATH)
    client = FakeS3CompatibleClient(s3_capabilities(object_lock_enabled=False))

    evidence = build_s3_compatible_provider_profile_evidence(
        client=client,
        storage_policy=policy,
        provider_profile_id="minio-dev-object-lock",
        checked_at_utc="2026-06-12T12:10:00Z",
    )

    assert evidence.provider_profile_ready is False
    assert evidence.profile_status == S3CompatibleProviderProfileStatus.BLOCKED
    assert evidence.object_lock_verified is False
    assert evidence.legal_hold_verified is False
    assert "business-records:object_lock_required" in evidence.blocking_reasons
    assert "business-records:legal_hold_required" in evidence.blocking_reasons
