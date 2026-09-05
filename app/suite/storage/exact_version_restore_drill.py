from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel, Field

from suite.storage.adapter_policy import ObjectLockMode, StorageAdapterPolicy
from suite.storage.persistent_source_object_runtime import build_persistent_source_object_repository
from suite.storage.retention import RetentionManifestPolicy, build_retention_manifest
from suite.storage.s3_compatible_content_store import (
    S3CompatibleObjectStoreClient,
    S3CompatibleObjectVersionControls,
    S3CompatibleProviderProfileEvidence,
    S3CompatibleSourceObjectContentStore,
    build_s3_compatible_provider_profile_evidence,
    build_s3_compatible_provider_profile_evidence_hash,
    build_s3_restore_binding_metadata,
)
from suite.storage.s3_sdk_client import (
    build_boto3_s3_compatible_client,
    wait_for_s3_compatible_client,
)
from suite.storage.source_object_storage import SourceObjectStorageError
from suite.storage.source_objects import SourceObjectRecord, sha256_bytes, source_object_content_bytes
from suite.storage.storage_manifest import (
    StorageObjectManifest,
    StorageRestoreVerificationError,
    verify_storage_object_restore,
)

SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")


class ExactVersionRestoreRepository(Protocol):
    def get(self, *, tenant_id: str, object_id: str, version_id: str) -> SourceObjectRecord: ...

    def list_storage_manifests(self, *, tenant_id: str) -> tuple[StorageObjectManifest, ...]: ...


class ExactVersionRestoreTargetClient(S3CompatibleObjectStoreClient, Protocol):
    def object_version_controls(
        self,
        *,
        bucket_id: str,
        object_key: str,
        object_version_id: str,
    ) -> S3CompatibleObjectVersionControls: ...


class ExactVersionRestoreItemEvidence(BaseModel):
    tenant_id: str
    source_storage_manifest_hash: str
    source_object_version_ref_hash: str
    target_object_version_ref_hash: str
    target_version_controls_hash: str
    content_hash: str
    content_byte_length: int = Field(ge=0)
    source_exact_version_read_verified: bool
    target_exact_version_read_verified: bool
    target_metadata_verified: bool
    object_lock_control_verified: bool
    legal_hold_control_verified: bool
    evidence_hash: str
    schema_version: str = "exact_version_restore_item_evidence.v1"


class ExactVersionRestoreDrillReport(BaseModel):
    checked_at_utc: str
    source_provider_profile_evidence_hash: str
    target_provider_profile_evidence_hash: str
    target_isolation_ref_hash: str
    tenant_ids: tuple[str, ...]
    source_manifest_count: int = Field(ge=0)
    restored_object_count: int = Field(ge=0)
    exact_source_version_read_count: int = Field(ge=0)
    exact_target_version_read_count: int = Field(ge=0)
    object_lock_control_verified_count: int = Field(ge=0)
    legal_hold_control_verified_count: int = Field(ge=0)
    source_storage_manifest_hashes: tuple[str, ...]
    restore_item_evidence_hashes: tuple[str, ...]
    failed_source_storage_manifest_hashes: tuple[str, ...] = ()
    blocking_reasons: tuple[str, ...] = ()
    source_provider_profile_ready: bool
    target_provider_profile_ready: bool
    target_isolation_verified: bool
    tenant_scope_verified: bool
    non_empty_restore_verified: bool
    exact_version_restore_verified: bool
    restore_ready: bool
    content_included: bool = False
    report_hash: str
    schema_version: str = "exact_version_restore_drill_report.v1"


def run_exact_version_restore_drill(
    *,
    repository: ExactVersionRestoreRepository,
    target_client: ExactVersionRestoreTargetClient,
    storage_policy: StorageAdapterPolicy,
    retention_policy: RetentionManifestPolicy,
    source_provider_profile_evidence: S3CompatibleProviderProfileEvidence,
    target_provider_profile_evidence: S3CompatibleProviderProfileEvidence,
    target_isolation_ref_hash: str,
    tenant_ids: tuple[str, ...],
    checked_at_utc: str | None = None,
) -> ExactVersionRestoreDrillReport:
    _require_profile_evidence(source_provider_profile_evidence, "source_provider_profile_evidence")
    _require_profile_evidence(target_provider_profile_evidence, "target_provider_profile_evidence")
    _require_sha256(target_isolation_ref_hash, "target_isolation_ref_hash")
    if source_provider_profile_evidence.storage_policy_hash != target_provider_profile_evidence.storage_policy_hash:
        raise ValueError("source and target provider profiles must use the same storage policy")
    policy_hash = _canonical_sha256(storage_policy.model_dump(mode="json"))
    if source_provider_profile_evidence.storage_policy_hash != policy_hash:
        raise ValueError("provider profile evidence does not match the requested storage policy")

    normalized_tenant_ids = tuple(sorted({tenant_id.strip() for tenant_id in tenant_ids if tenant_id.strip()}))
    if not normalized_tenant_ids:
        raise ValueError("at least one tenant_id is required for an exact-version restore drill")

    blocking_reasons: list[str] = []
    if not source_provider_profile_evidence.provider_profile_ready:
        blocking_reasons.append("source_provider_profile_not_ready")
    if not target_provider_profile_evidence.provider_profile_ready:
        blocking_reasons.append("target_provider_profile_not_ready")

    manifests = tuple(
        sorted(
            (
                manifest
                for tenant_id in normalized_tenant_ids
                for manifest in repository.list_storage_manifests(tenant_id=tenant_id)
            ),
            key=lambda item: (item.tenant_id, item.manifest_hash),
        )
    )
    tenant_scope_verified = all(manifest.tenant_id in normalized_tenant_ids for manifest in manifests)
    if not tenant_scope_verified:
        blocking_reasons.append("tenant_scope_mismatch")

    item_evidence: list[ExactVersionRestoreItemEvidence] = []
    failed_manifest_hashes: list[str] = []
    if not blocking_reasons:
        for manifest in manifests:
            try:
                item_evidence.append(
                    _restore_exact_version(
                        repository=repository,
                        target_client=target_client,
                        storage_policy=storage_policy,
                        retention_policy=retention_policy,
                        manifest=manifest,
                    )
                )
            except (KeyError, SourceObjectStorageError, StorageRestoreVerificationError, ValueError):
                failed_manifest_hashes.append(manifest.manifest_hash)

    source_manifest_hashes = tuple(manifest.manifest_hash for manifest in manifests)
    failed_hashes = tuple(sorted(set(failed_manifest_hashes)))
    restored_count = len(item_evidence)
    non_empty_restore_verified = bool(manifests) and restored_count == len(manifests)
    exact_version_restore_verified = non_empty_restore_verified and all(
        item.source_exact_version_read_verified
        and item.target_exact_version_read_verified
        and item.target_metadata_verified
        and item.object_lock_control_verified
        and item.legal_hold_control_verified
        for item in item_evidence
    )
    restore_ready = (
        source_provider_profile_evidence.provider_profile_ready
        and target_provider_profile_evidence.provider_profile_ready
        and tenant_scope_verified
        and exact_version_restore_verified
        and not failed_hashes
        and not blocking_reasons
    )
    draft = ExactVersionRestoreDrillReport(
        checked_at_utc=checked_at_utc or _now_utc(),
        source_provider_profile_evidence_hash=source_provider_profile_evidence.evidence_hash,
        target_provider_profile_evidence_hash=target_provider_profile_evidence.evidence_hash,
        target_isolation_ref_hash=target_isolation_ref_hash,
        tenant_ids=normalized_tenant_ids,
        source_manifest_count=len(manifests),
        restored_object_count=restored_count,
        exact_source_version_read_count=sum(int(item.source_exact_version_read_verified) for item in item_evidence),
        exact_target_version_read_count=sum(int(item.target_exact_version_read_verified) for item in item_evidence),
        object_lock_control_verified_count=sum(int(item.object_lock_control_verified) for item in item_evidence),
        legal_hold_control_verified_count=sum(int(item.legal_hold_control_verified) for item in item_evidence),
        source_storage_manifest_hashes=source_manifest_hashes,
        restore_item_evidence_hashes=tuple(item.evidence_hash for item in item_evidence),
        failed_source_storage_manifest_hashes=failed_hashes,
        blocking_reasons=tuple(sorted(set(blocking_reasons))),
        source_provider_profile_ready=source_provider_profile_evidence.provider_profile_ready,
        target_provider_profile_ready=target_provider_profile_evidence.provider_profile_ready,
        target_isolation_verified=True,
        tenant_scope_verified=tenant_scope_verified,
        non_empty_restore_verified=non_empty_restore_verified,
        exact_version_restore_verified=exact_version_restore_verified,
        restore_ready=restore_ready,
        report_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"report_hash": build_exact_version_restore_drill_report_hash(draft)})


def _restore_exact_version(
    *,
    repository: ExactVersionRestoreRepository,
    target_client: ExactVersionRestoreTargetClient,
    storage_policy: StorageAdapterPolicy,
    retention_policy: RetentionManifestPolicy,
    manifest: StorageObjectManifest,
) -> ExactVersionRestoreItemEvidence:
    record = repository.get(
        tenant_id=manifest.tenant_id,
        object_id=manifest.object_id,
        version_id=manifest.source_version_id,
    )
    content = source_object_content_bytes(record)
    retention_manifest = build_retention_manifest(record, retention_policy)
    verify_storage_object_restore(
        manifest=manifest,
        record=record,
        retention_manifest=retention_manifest,
        restored_content=content,
    )

    target_write = target_client.put_object(
        bucket_id=manifest.bucket_id,
        object_key=manifest.object_key,
        body=content,
        metadata=_target_object_metadata(manifest),
        object_lock_mode=manifest.object_lock_mode,
        legal_hold=manifest.object_lock_legal_hold,
    )
    if target_write.bucket_id != manifest.bucket_id or target_write.object_key != manifest.object_key:
        raise SourceObjectStorageError("restore target write result changed the requested object reference")
    if not target_write.object_version_id.strip():
        raise SourceObjectStorageError("restore target write did not return an object version ID")

    restored_content = target_client.get_object(
        bucket_id=target_write.bucket_id,
        object_key=target_write.object_key,
        object_version_id=target_write.object_version_id,
    )
    verify_storage_object_restore(
        manifest=manifest,
        record=record,
        retention_manifest=retention_manifest,
        restored_content=restored_content,
    )
    controls = target_client.object_version_controls(
        bucket_id=target_write.bucket_id,
        object_key=target_write.object_key,
        object_version_id=target_write.object_version_id,
    )
    if (
        controls.bucket_id != target_write.bucket_id
        or controls.object_key != target_write.object_key
        or controls.object_version_id != target_write.object_version_id
    ):
        raise SourceObjectStorageError("restore target controls do not match the exact target object version")

    target_metadata_verified, object_lock_verified, legal_hold_verified = _verify_target_controls(
        manifest=manifest,
        controls=controls,
    )
    target_bucket_profile = storage_policy.bucket(manifest.bucket_id)
    if target_bucket_profile.object_lock_mode != manifest.object_lock_mode:
        raise SourceObjectStorageError("restore target bucket profile does not match source Object Lock mode")

    draft = ExactVersionRestoreItemEvidence(
        tenant_id=manifest.tenant_id,
        source_storage_manifest_hash=manifest.manifest_hash,
        source_object_version_ref_hash=_object_version_ref_hash(
            storage_provider=manifest.storage_provider,
            bucket_id=manifest.bucket_id,
            object_key=manifest.object_key,
            object_version_id=manifest.object_version_id,
        ),
        target_object_version_ref_hash=_object_version_ref_hash(
            storage_provider=target_write.storage_provider,
            bucket_id=target_write.bucket_id,
            object_key=target_write.object_key,
            object_version_id=target_write.object_version_id,
        ),
        target_version_controls_hash=_canonical_sha256(controls.model_dump(mode="json")),
        content_hash=manifest.content_hash,
        content_byte_length=manifest.content_byte_length,
        source_exact_version_read_verified=True,
        target_exact_version_read_verified=True,
        target_metadata_verified=target_metadata_verified,
        object_lock_control_verified=object_lock_verified,
        legal_hold_control_verified=legal_hold_verified,
        evidence_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"evidence_hash": build_exact_version_restore_item_evidence_hash(draft)})


def _verify_target_controls(
    *,
    manifest: StorageObjectManifest,
    controls: S3CompatibleObjectVersionControls,
) -> tuple[bool, bool, bool]:
    expected_metadata = _target_object_metadata(manifest)
    target_metadata_verified = all(controls.metadata.get(key) == value for key, value in expected_metadata.items())
    object_lock_verified = controls.object_lock_mode == manifest.object_lock_mode
    if manifest.object_lock_mode != ObjectLockMode.NONE:
        object_lock_verified = object_lock_verified and controls.object_lock_retain_until_utc is not None
    legal_hold_verified = controls.legal_hold_enabled == manifest.object_lock_legal_hold
    if not target_metadata_verified:
        raise SourceObjectStorageError("restore target metadata does not match the source storage manifest")
    if not object_lock_verified:
        raise SourceObjectStorageError("restore target Object Lock controls do not match the source storage manifest")
    if not legal_hold_verified:
        raise SourceObjectStorageError("restore target Legal Hold controls do not match the source storage manifest")
    return target_metadata_verified, object_lock_verified, legal_hold_verified


def _target_object_metadata(manifest: StorageObjectManifest) -> dict[str, str]:
    return build_s3_restore_binding_metadata(manifest)


def build_exact_version_restore_item_evidence_hash(evidence: ExactVersionRestoreItemEvidence) -> str:
    return _canonical_sha256(evidence.model_dump(mode="json", exclude={"evidence_hash"}))


def build_exact_version_restore_drill_report_hash(report: ExactVersionRestoreDrillReport) -> str:
    return _canonical_sha256(report.model_dump(mode="json", exclude={"report_hash"}))


def build_restore_target_isolation_ref_hash(
    *,
    source_endpoint: str,
    target_endpoint: str,
    source_provider_profile_id: str,
    target_provider_profile_id: str,
) -> str:
    normalized_source = source_endpoint.strip().rstrip("/")
    normalized_target = target_endpoint.strip().rstrip("/")
    if not normalized_source or not normalized_target:
        raise ValueError("source and target endpoints must not be empty")
    if normalized_source == normalized_target:
        raise ValueError("restore target endpoint must be isolated from the source endpoint")
    if source_provider_profile_id.strip() == target_provider_profile_id.strip():
        raise ValueError("restore target provider profile must differ from the source provider profile")
    return _canonical_sha256(
        {
            "source_endpoint": normalized_source,
            "target_endpoint": normalized_target,
            "source_provider_profile_id": source_provider_profile_id.strip(),
            "target_provider_profile_id": target_provider_profile_id.strip(),
        }
    )


def _object_version_ref_hash(
    *,
    storage_provider: str,
    bucket_id: str,
    object_key: str,
    object_version_id: str,
) -> str:
    return _canonical_sha256(
        {
            "storage_provider": storage_provider,
            "bucket_id": bucket_id,
            "object_key": object_key,
            "object_version_id": object_version_id,
        }
    )


def _require_profile_evidence(evidence: S3CompatibleProviderProfileEvidence, field_name: str) -> None:
    if build_s3_compatible_provider_profile_evidence_hash(evidence) != evidence.evidence_hash:
        raise ValueError(f"{field_name} hash is invalid")


def _require_sha256(value: str, field_name: str) -> None:
    if not SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"{field_name} must be a sha256 reference")


def _canonical_sha256(payload: object) -> str:
    return sha256_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _now_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _required_env(env: Mapping[str, str], name: str) -> str:
    value = env.get(name)
    if value is None or not value.strip():
        raise ValueError(f"Required environment variable missing: {name}")
    return value.strip()


def _parse_tenant_ids(value: str) -> tuple[str, ...]:
    return tuple(sorted({tenant_id.strip() for tenant_id in value.split(",") if tenant_id.strip()}))


def run_exact_version_restore_drill_from_environment(
    env: Mapping[str, str],
) -> ExactVersionRestoreDrillReport:
    repository = build_persistent_source_object_repository(env)
    content_store = repository.content_store
    if not isinstance(content_store, S3CompatibleSourceObjectContentStore):
        raise ValueError("exact-version restore drill requires the S3-compatible source content store")

    source_endpoint = _required_env(env, "SUITE_S3_ENDPOINT_URL")
    target_endpoint = _required_env(env, "SUITE_RESTORE_S3_ENDPOINT_URL")
    source_profile_id = env.get("SUITE_S3_PROVIDER_PROFILE_ID", "s3-compatible-provider").strip()
    target_profile_id = env.get(
        "SUITE_RESTORE_S3_PROVIDER_PROFILE_ID",
        "s3-compatible-restore-target",
    ).strip()
    target_client = build_boto3_s3_compatible_client(
        endpoint_url=target_endpoint,
        access_key_id=_required_env(env, "SUITE_RESTORE_S3_ACCESS_KEY_ID"),
        secret_access_key=_required_env(env, "SUITE_RESTORE_S3_SECRET_ACCESS_KEY"),
        region_name=env.get("SUITE_RESTORE_S3_REGION", "us-east-1"),
        storage_provider=env.get("SUITE_RESTORE_S3_STORAGE_PROVIDER", "s3-compatible-restore"),
    )
    wait_for_s3_compatible_client(
        client=target_client,
        storage_policy=repository.storage_policy,
        retries=int(env.get("SUITE_RESTORE_S3_PROFILE_CHECK_RETRIES", "30")),
    )
    source_profile = build_s3_compatible_provider_profile_evidence(
        client=content_store.client,
        storage_policy=repository.storage_policy,
        provider_profile_id=source_profile_id,
    )
    target_profile = build_s3_compatible_provider_profile_evidence(
        client=target_client,
        storage_policy=repository.storage_policy,
        provider_profile_id=target_profile_id,
    )
    report = run_exact_version_restore_drill(
        repository=repository,
        target_client=target_client,
        storage_policy=repository.storage_policy,
        retention_policy=repository.retention_policy,
        source_provider_profile_evidence=source_profile,
        target_provider_profile_evidence=target_profile,
        target_isolation_ref_hash=build_restore_target_isolation_ref_hash(
            source_endpoint=source_endpoint,
            target_endpoint=target_endpoint,
            source_provider_profile_id=source_profile_id,
            target_provider_profile_id=target_profile_id,
        ),
        tenant_ids=_parse_tenant_ids(env.get("SUITE_SOURCE_OBJECT_RESTORE_DRILL_TENANT_IDS", "tenant-demo")),
    )
    return report


def main() -> None:
    report = run_exact_version_restore_drill_from_environment(os.environ)
    print(json.dumps(report.model_dump(mode="json"), sort_keys=True))
    raise SystemExit(0 if report.restore_ready else 2)


if __name__ == "__main__":
    main()
