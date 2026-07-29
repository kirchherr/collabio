from __future__ import annotations

import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, Field

from suite.storage.adapter_policy import ObjectLockMode, StorageAdapterPolicy
from suite.storage.content_hash import ContentHashVerificationError, verify_content_hash
from suite.storage.source_object_storage import (
    SourceObjectStorageError,
    StoredSourceObjectContent,
)
from suite.storage.source_objects import (
    LegalHoldState,
    SourceObjectRecord,
    sha256_bytes,
    source_object_content_bytes,
)
from suite.storage.storage_manifest import StorageObjectManifest


class S3CompatibleBucketCapabilities(BaseModel):
    bucket_id: str
    storage_provider: str = "s3-compatible"
    versioning_enabled: bool
    object_lock_enabled: bool = False
    legal_hold_supported: bool = False


class S3CompatibleObjectWriteResult(BaseModel):
    bucket_id: str
    object_key: str
    object_version_id: str
    storage_provider: str
    stored_at_utc: str


class S3CompatibleStoredObjectVersion(BaseModel):
    bucket_id: str
    object_key: str
    object_version_id: str
    storage_provider: str
    stored_at_utc: str
    metadata: dict[str, str]


class S3CompatibleObjectVersionControls(BaseModel):
    bucket_id: str
    object_key: str
    object_version_id: str
    storage_provider: str = "s3-compatible"
    object_lock_mode: ObjectLockMode = ObjectLockMode.NONE
    object_lock_retain_until_utc: str | None = None
    legal_hold_enabled: bool = False
    metadata: dict[str, str]


class S3CompatibleProviderProfileStatus(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"


class S3CompatibleProviderProfileEvidence(BaseModel):
    provider_profile_id: str
    storage_provider: str = "s3-compatible"
    checked_at_utc: str
    storage_policy_hash: str
    bucket_profile_count: int = Field(ge=0)
    object_lock_bucket_count: int = Field(ge=0)
    bucket_capability_hashes: tuple[str, ...]
    versioning_verified: bool
    object_lock_verified: bool
    legal_hold_verified: bool
    blocking_reasons: tuple[str, ...] = ()
    provider_profile_ready: bool
    profile_status: S3CompatibleProviderProfileStatus
    evidence_hash: str
    schema_version: str = "s3_compatible_provider_profile_evidence.v1"


class S3CompatibleObjectStoreClient(Protocol):
    def bucket_capabilities(self, *, bucket_id: str) -> S3CompatibleBucketCapabilities: ...

    def put_object(
        self,
        *,
        bucket_id: str,
        object_key: str,
        body: bytes,
        metadata: dict[str, str],
        object_lock_mode: ObjectLockMode,
        legal_hold: bool,
    ) -> S3CompatibleObjectWriteResult: ...

    def get_object(self, *, bucket_id: str, object_key: str, object_version_id: str) -> bytes: ...

    def list_object_versions(
        self,
        *,
        bucket_id: str,
        prefix: str,
    ) -> tuple[S3CompatibleStoredObjectVersion, ...]: ...


def build_s3_compatible_provider_profile_evidence(
    *,
    client: S3CompatibleObjectStoreClient,
    storage_policy: StorageAdapterPolicy,
    provider_profile_id: str,
    checked_at_utc: str | None = None,
) -> S3CompatibleProviderProfileEvidence:
    if not provider_profile_id.strip():
        raise SourceObjectStorageError("provider_profile_id must not be empty")

    blocking_reasons: list[str] = []
    capability_hashes: list[str] = []
    versioning_verified = True
    object_lock_verified = True
    legal_hold_verified = True

    for bucket_profile in storage_policy.bucket_profiles:
        try:
            capabilities = client.bucket_capabilities(bucket_id=bucket_profile.bucket_id)
        except (KeyError, SourceObjectStorageError):
            blocking_reasons.append(f"{bucket_profile.bucket_id}:capabilities_unavailable")
            versioning_verified = False
            if bucket_profile.object_lock_required:
                object_lock_verified = False
                legal_hold_verified = False
            continue

        capability_hashes.append(
            _canonical_sha256(
                {
                    "bucket_id": capabilities.bucket_id,
                    "storage_provider": capabilities.storage_provider,
                    "versioning_enabled": capabilities.versioning_enabled,
                    "object_lock_enabled": capabilities.object_lock_enabled,
                    "legal_hold_supported": capabilities.legal_hold_supported,
                    "required_versioning": bucket_profile.versioning_required,
                    "required_object_lock_mode": bucket_profile.object_lock_mode,
                    "required_legal_hold": bucket_profile.legal_hold_supported,
                }
            )
        )
        if capabilities.bucket_id != bucket_profile.bucket_id:
            blocking_reasons.append(f"{bucket_profile.bucket_id}:capability_bucket_mismatch")
        if bucket_profile.versioning_required and not capabilities.versioning_enabled:
            blocking_reasons.append(f"{bucket_profile.bucket_id}:versioning_required")
            versioning_verified = False
        if bucket_profile.object_lock_required and not capabilities.object_lock_enabled:
            blocking_reasons.append(f"{bucket_profile.bucket_id}:object_lock_required")
            object_lock_verified = False
        if bucket_profile.object_lock_required and not capabilities.legal_hold_supported:
            blocking_reasons.append(f"{bucket_profile.bucket_id}:legal_hold_required")
            legal_hold_verified = False

    unique_blocking_reasons = tuple(sorted(set(blocking_reasons)))
    provider_profile_ready = not unique_blocking_reasons
    draft = S3CompatibleProviderProfileEvidence(
        provider_profile_id=provider_profile_id,
        checked_at_utc=checked_at_utc or datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        storage_policy_hash=_canonical_sha256(storage_policy.model_dump(mode="json")),
        bucket_profile_count=len(storage_policy.bucket_profiles),
        object_lock_bucket_count=sum(1 for profile in storage_policy.bucket_profiles if profile.object_lock_required),
        bucket_capability_hashes=tuple(sorted(capability_hashes)),
        versioning_verified=versioning_verified,
        object_lock_verified=object_lock_verified,
        legal_hold_verified=legal_hold_verified,
        blocking_reasons=unique_blocking_reasons,
        provider_profile_ready=provider_profile_ready,
        profile_status=(
            S3CompatibleProviderProfileStatus.READY
            if provider_profile_ready
            else S3CompatibleProviderProfileStatus.BLOCKED
        ),
        evidence_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"evidence_hash": build_s3_compatible_provider_profile_evidence_hash(draft)})


def build_s3_compatible_provider_profile_evidence_hash(
    evidence: S3CompatibleProviderProfileEvidence,
) -> str:
    return _canonical_sha256(evidence.model_dump(mode="json", exclude={"evidence_hash"}))


class S3CompatibleSourceObjectContentStore:
    def __init__(
        self,
        *,
        client: S3CompatibleObjectStoreClient,
        storage_policy: StorageAdapterPolicy,
    ) -> None:
        self.client = client
        self.storage_policy = storage_policy
        self.storage_provider = "s3-compatible"

    def put(
        self,
        *,
        record: SourceObjectRecord,
        bucket_id: str,
        object_key: str,
    ) -> StoredSourceObjectContent:
        bucket_profile = self.storage_policy.bucket(bucket_id)
        capabilities = self.client.bucket_capabilities(bucket_id=bucket_id)
        self._require_bucket_capabilities(bucket_id=bucket_id, capabilities=capabilities)

        content = source_object_content_bytes(record)
        try:
            verify_content_hash(
                content=content,
                expected_hash=record.metadata.content_hash,
                verification_context="s3_compatible_content_store_put",
            )
        except ContentHashVerificationError as exc:
            raise SourceObjectStorageError(f"content_hash verification failed: {exc}") from exc

        result = self.client.put_object(
            bucket_id=bucket_id,
            object_key=object_key,
            body=content,
            metadata=self._object_metadata(record),
            object_lock_mode=bucket_profile.object_lock_mode,
            legal_hold=record.metadata.legal_hold_state == LegalHoldState.ACTIVE
            and bucket_profile.legal_hold_supported,
        )
        if result.bucket_id != bucket_id or result.object_key != object_key:
            raise SourceObjectStorageError("object store write result does not match requested object reference")
        if not result.object_version_id.strip():
            raise SourceObjectStorageError("object store write did not return an object version ID")
        return StoredSourceObjectContent(
            tenant_id=record.metadata.tenant_id,
            object_id=record.metadata.object_id,
            version_id=record.metadata.version_id,
            bucket_id=bucket_id,
            object_key=object_key,
            object_version_id=result.object_version_id,
            storage_provider=result.storage_provider,
            stored_at_utc=result.stored_at_utc,
            content_hash=record.metadata.content_hash,
            content_byte_length=len(content),
        )

    def get(self, *, manifest: StorageObjectManifest) -> bytes:
        content = self.client.get_object(
            bucket_id=manifest.bucket_id,
            object_key=manifest.object_key,
            object_version_id=manifest.object_version_id,
        )
        try:
            verify_content_hash(
                content=content,
                expected_hash=manifest.content_hash,
                verification_context="s3_compatible_content_store_get",
            )
        except ContentHashVerificationError as exc:
            raise SourceObjectStorageError(f"content_hash verification failed: {exc}") from exc
        if len(content) != manifest.content_byte_length:
            raise SourceObjectStorageError("content_byte_length does not match storage manifest")
        return content

    def list_stored_objects(self, *, tenant_id: str) -> tuple[StoredSourceObjectContent, ...]:
        stored_objects: list[StoredSourceObjectContent] = []
        for bucket_profile in self.storage_policy.bucket_profiles:
            for version in self.client.list_object_versions(
                bucket_id=bucket_profile.bucket_id,
                prefix=f"{tenant_id}/",
            ):
                stored_object = self._stored_content_from_version(version)
                if stored_object.tenant_id == tenant_id:
                    stored_objects.append(stored_object)
        return tuple(sorted(stored_objects, key=self._stored_object_sort_key))

    def _require_bucket_capabilities(
        self,
        *,
        bucket_id: str,
        capabilities: S3CompatibleBucketCapabilities,
    ) -> None:
        bucket_profile = self.storage_policy.bucket(bucket_id)
        if capabilities.bucket_id != bucket_id:
            raise SourceObjectStorageError("object store capabilities do not match bucket profile")
        if bucket_profile.versioning_required and not capabilities.versioning_enabled:
            raise SourceObjectStorageError("S3-compatible bucket versioning is required before writes")
        if bucket_profile.object_lock_required and not capabilities.object_lock_enabled:
            raise SourceObjectStorageError("S3-compatible bucket Object Lock is required before writes")
        if bucket_profile.object_lock_required and not capabilities.legal_hold_supported:
            raise SourceObjectStorageError("S3-compatible Object Lock bucket must support legal hold")

    def _object_metadata(self, record: SourceObjectRecord) -> dict[str, str]:
        metadata = record.metadata
        return {
            "tenant_id": metadata.tenant_id,
            "object_id": metadata.object_id,
            "version_id": metadata.version_id,
            "object_type": metadata.object_type.value,
            "classification": metadata.classification.value,
            "retention_policy_id": metadata.retention_policy_id,
            "legal_hold_state": metadata.legal_hold_state.value,
            "kms_key_ref_hash": sha256_bytes(metadata.kms_key_ref.encode("utf-8")),
            "source_manifest_hash": metadata.manifest_hash,
            "content_hash": metadata.content_hash,
            "content_byte_length": str(metadata.content_byte_length),
            "acl_version": str(metadata.acl_version),
            "audit_chain_ref": metadata.audit_chain_ref,
        }

    def _stored_content_from_version(
        self,
        version: S3CompatibleStoredObjectVersion,
    ) -> StoredSourceObjectContent:
        metadata = version.metadata
        required_fields = {
            "tenant_id",
            "object_id",
            "version_id",
            "content_hash",
            "content_byte_length",
        }
        missing_fields = sorted(required_fields - set(metadata))
        if missing_fields:
            raise SourceObjectStorageError(f"stored object version is missing metadata: {', '.join(missing_fields)}")
        return StoredSourceObjectContent(
            tenant_id=metadata["tenant_id"],
            object_id=metadata["object_id"],
            version_id=metadata["version_id"],
            bucket_id=version.bucket_id,
            object_key=version.object_key,
            object_version_id=version.object_version_id,
            storage_provider=version.storage_provider,
            stored_at_utc=version.stored_at_utc,
            content_hash=metadata["content_hash"],
            content_byte_length=int(metadata["content_byte_length"]),
        )

    def _stored_object_sort_key(self, stored_object: StoredSourceObjectContent) -> tuple[str, str, str, str]:
        return (
            stored_object.tenant_id,
            stored_object.bucket_id,
            stored_object.object_key,
            stored_object.object_version_id,
        )


def _canonical_sha256(payload: object) -> str:
    payload_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256_bytes(payload_bytes)
