from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from suite.ai_control_plane.models import DataClass
from suite.platform.workspace_source_objects import demo_workspace_source_object_records
from suite.storage.adapter_policy import ObjectLockMode, load_storage_adapter_policy
from suite.storage.backend_storage_foundation_gate import (
    build_backend_storage_foundation_gate,
    build_backend_storage_foundation_gate_hash,
)
from suite.storage.exact_version_restore_drill import (
    ExactVersionRestoreDrillReport,
    build_exact_version_restore_drill_report_hash,
    build_restore_target_isolation_ref_hash,
    run_exact_version_restore_drill,
)
from suite.storage.persistent_source_object_runtime import (
    PersistentSourceObjectRuntimeReport,
    PersistentSourceObjectTenantRuntimeEvidence,
    build_persistent_source_object_runtime_report_hash,
)
from suite.storage.retention import build_retention_manifest, load_retention_manifest_policy
from suite.storage.s3_compatible_content_store import (
    S3CompatibleBucketCapabilities,
    S3CompatibleObjectVersionControls,
    S3CompatibleObjectWriteResult,
    S3CompatibleProviderProfileEvidence,
    S3CompatibleStoredObjectVersion,
    build_s3_compatible_provider_profile_evidence,
)
from suite.storage.source_objects import (
    SourceLifecycleState,
    SourceObjectRecord,
    build_source_object_manifest_hash,
)
from suite.storage.storage_manifest import (
    StorageObjectManifest,
    build_storage_object_manifest,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CHECKED_AT = "2026-07-29T10:00:00Z"


class ManifestRepository:
    def __init__(
        self,
        records: tuple[SourceObjectRecord, ...],
        manifests: tuple[StorageObjectManifest, ...],
    ) -> None:
        self.records = {
            (record.metadata.tenant_id, record.metadata.object_id, record.metadata.version_id): record
            for record in records
        }
        self.manifests = manifests

    def get(self, *, tenant_id: str, object_id: str, version_id: str) -> SourceObjectRecord:
        return self.records[(tenant_id, object_id, version_id)]

    def list_storage_manifests(self, *, tenant_id: str) -> tuple[StorageObjectManifest, ...]:
        return tuple(manifest for manifest in self.manifests if manifest.tenant_id == tenant_id)


@dataclass
class StoredTargetVersion:
    body: bytes
    metadata: dict[str, str]
    object_lock_mode: ObjectLockMode
    legal_hold: bool


class RestoreTargetClient:
    def __init__(
        self,
        *,
        corrupt_metadata: bool = False,
        rewrite_reference: bool = False,
        controls_version_mismatch: bool = False,
    ) -> None:
        self.corrupt_metadata = corrupt_metadata
        self.rewrite_reference = rewrite_reference
        self.controls_version_mismatch = controls_version_mismatch
        self.objects: dict[tuple[str, str, str], StoredTargetVersion] = {}
        self.version_counter = 0

    def bucket_capabilities(self, *, bucket_id: str) -> S3CompatibleBucketCapabilities:
        locked = bucket_id in {"business-records", "evidence-records"}
        return S3CompatibleBucketCapabilities(
            bucket_id=bucket_id,
            storage_provider="restore-target",
            versioning_enabled=True,
            object_lock_enabled=locked,
            legal_hold_supported=locked,
        )

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
        object_version_id = f"restored-version-{self.version_counter}"
        stored_metadata = dict(metadata)
        if self.corrupt_metadata:
            stored_metadata["content_hash"] = "sha256:" + "f" * 64
        self.objects[(bucket_id, object_key, object_version_id)] = StoredTargetVersion(
            body=body,
            metadata=stored_metadata,
            object_lock_mode=object_lock_mode,
            legal_hold=legal_hold,
        )
        return S3CompatibleObjectWriteResult(
            bucket_id=f"{bucket_id}-unexpected" if self.rewrite_reference else bucket_id,
            object_key=object_key,
            object_version_id=object_version_id,
            storage_provider="restore-target",
            stored_at_utc=CHECKED_AT,
        )

    def get_object(self, *, bucket_id: str, object_key: str, object_version_id: str) -> bytes:
        return self.objects[(bucket_id, object_key, object_version_id)].body

    def list_object_versions(
        self,
        *,
        bucket_id: str,
        prefix: str,
    ) -> tuple[S3CompatibleStoredObjectVersion, ...]:
        return tuple(
            S3CompatibleStoredObjectVersion(
                bucket_id=stored_bucket,
                object_key=object_key,
                object_version_id=version_id,
                storage_provider="restore-target",
                stored_at_utc=CHECKED_AT,
                metadata=stored.metadata,
            )
            for (stored_bucket, object_key, version_id), stored in sorted(self.objects.items())
            if stored_bucket == bucket_id and object_key.startswith(prefix)
        )

    def object_version_controls(
        self,
        *,
        bucket_id: str,
        object_key: str,
        object_version_id: str,
    ) -> S3CompatibleObjectVersionControls:
        stored = self.objects[(bucket_id, object_key, object_version_id)]
        return S3CompatibleObjectVersionControls(
            bucket_id=bucket_id,
            object_key=object_key,
            object_version_id=("unexpected-version" if self.controls_version_mismatch else object_version_id),
            storage_provider="restore-target",
            object_lock_mode=stored.object_lock_mode,
            object_lock_retain_until_utc=(
                "2036-07-29T10:00:00Z" if stored.object_lock_mode != ObjectLockMode.NONE else None
            ),
            legal_hold_enabled=stored.legal_hold,
            metadata=stored.metadata,
        )


def _records_and_manifests() -> tuple[
    tuple[SourceObjectRecord, ...],
    tuple[StorageObjectManifest, ...],
]:
    storage_policy = load_storage_adapter_policy(REPO_ROOT / "docs" / "storage_adapter_policy.json")
    retention_policy = load_retention_manifest_policy(REPO_ROOT / "docs" / "retention_manifest_policy.json")
    records = list(demo_workspace_source_object_records())
    source = records[0]
    business_metadata = source.metadata.model_copy(
        update={
            "object_id": "business-record-1",
            "title": "Business record",
            "lifecycle_state": SourceLifecycleState.BUSINESS_RECORD,
            "retention_policy_id": "rp-gobd-10y",
            "manifest_hash": "sha256:" + "0" * 64,
            "classification": DataClass.GOBD,
            "kms_key_ref": "kms://tenant-demo/gobd/v1",
        }
    )
    records.append(
        source.model_copy(
            update={
                "metadata": business_metadata.model_copy(
                    update={"manifest_hash": build_source_object_manifest_hash(business_metadata)}
                )
            }
        )
    )

    manifests: list[StorageObjectManifest] = []
    for index, record in enumerate(records, start=1):
        retention_manifest = build_retention_manifest(record, retention_policy)
        bucket_profile = storage_policy.bucket(retention_manifest.storage_bucket_id)
        manifests.append(
            build_storage_object_manifest(
                record=record,
                retention_manifest=retention_manifest,
                bucket_profile=bucket_profile,
                object_version_id=f"source-version-{index}",
                stored_at_utc=CHECKED_AT,
                storage_provider="source-store",
            )
        )
    return tuple(records), tuple(manifests)


def _profile(client: RestoreTargetClient, profile_id: str) -> S3CompatibleProviderProfileEvidence:
    return build_s3_compatible_provider_profile_evidence(
        client=client,
        storage_policy=load_storage_adapter_policy(REPO_ROOT / "docs" / "storage_adapter_policy.json"),
        provider_profile_id=profile_id,
        checked_at_utc=CHECKED_AT,
    )


def _restore_report(target_client: RestoreTargetClient | None = None) -> ExactVersionRestoreDrillReport:
    records, manifests = _records_and_manifests()
    repository = ManifestRepository(records, manifests)
    target_client = target_client or RestoreTargetClient()
    source_profile = _profile(RestoreTargetClient(), "source-profile")
    target_profile = _profile(target_client, "restore-target-profile")
    return run_exact_version_restore_drill(
        repository=repository,
        target_client=target_client,
        storage_policy=load_storage_adapter_policy(REPO_ROOT / "docs" / "storage_adapter_policy.json"),
        retention_policy=load_retention_manifest_policy(REPO_ROOT / "docs" / "retention_manifest_policy.json"),
        source_provider_profile_evidence=source_profile,
        target_provider_profile_evidence=target_profile,
        target_isolation_ref_hash=build_restore_target_isolation_ref_hash(
            source_endpoint="http://source:9000",
            target_endpoint="http://restore:9000",
            source_provider_profile_id="source-profile",
            target_provider_profile_id="restore-target-profile",
        ),
        tenant_ids=("tenant-demo", "tenant-other"),
        checked_at_utc=CHECKED_AT,
    )


def test_exact_version_restore_drill_verifies_independent_target_and_controls() -> None:
    report = _restore_report()

    assert report.restore_ready is True
    assert report.source_manifest_count == 4
    assert report.restored_object_count == 4
    assert report.exact_source_version_read_count == 4
    assert report.exact_target_version_read_count == 4
    assert report.object_lock_control_verified_count == 4
    assert report.legal_hold_control_verified_count == 4
    assert report.target_isolation_verified is True
    assert report.content_included is False
    assert report.report_hash == build_exact_version_restore_drill_report_hash(report)


def test_exact_version_restore_drill_blocks_corrupt_target_metadata() -> None:
    records, manifests = _records_and_manifests()
    target_client = RestoreTargetClient(corrupt_metadata=True)
    report = run_exact_version_restore_drill(
        repository=ManifestRepository(records, manifests),
        target_client=target_client,
        storage_policy=load_storage_adapter_policy(REPO_ROOT / "docs" / "storage_adapter_policy.json"),
        retention_policy=load_retention_manifest_policy(REPO_ROOT / "docs" / "retention_manifest_policy.json"),
        source_provider_profile_evidence=_profile(RestoreTargetClient(), "source-profile"),
        target_provider_profile_evidence=_profile(target_client, "restore-target-profile"),
        target_isolation_ref_hash=build_restore_target_isolation_ref_hash(
            source_endpoint="http://source:9000",
            target_endpoint="http://restore:9000",
            source_provider_profile_id="source-profile",
            target_provider_profile_id="restore-target-profile",
        ),
        tenant_ids=("tenant-demo", "tenant-other"),
        checked_at_utc=CHECKED_AT,
    )

    assert report.restore_ready is False
    assert report.restored_object_count == 0
    assert set(report.failed_source_storage_manifest_hashes) == set(report.source_storage_manifest_hashes)


def test_exact_version_restore_drill_rejects_target_reference_rewrite() -> None:
    report = _restore_report(RestoreTargetClient(rewrite_reference=True))

    assert report.restore_ready is False
    assert report.restored_object_count == 0
    assert set(report.failed_source_storage_manifest_hashes) == set(report.source_storage_manifest_hashes)


def test_exact_version_restore_drill_rejects_controls_from_another_version() -> None:
    report = _restore_report(RestoreTargetClient(controls_version_mismatch=True))

    assert report.restore_ready is False
    assert report.restored_object_count == 0
    assert set(report.failed_source_storage_manifest_hashes) == set(report.source_storage_manifest_hashes)


def test_restore_target_must_be_independent() -> None:
    try:
        build_restore_target_isolation_ref_hash(
            source_endpoint="http://minio:9000/",
            target_endpoint="http://minio:9000",
            source_provider_profile_id="source-profile",
            target_provider_profile_id="target-profile",
        )
    except ValueError as exc:
        assert "isolated" in str(exc)
    else:
        raise AssertionError("same source and restore endpoint must be rejected")


def _runtime_report_for_restore(
    restore_report: ExactVersionRestoreDrillReport,
    *,
    restore_hash: str | None = None,
) -> PersistentSourceObjectRuntimeReport:
    tenant_evidence = tuple(
        PersistentSourceObjectTenantRuntimeEvidence(
            tenant_id=tenant_id,
            expected_source_object_count=2,
            restart_verified_source_object_count=2,
            stored_object_count=2,
            storage_manifest_count=2,
            verified_content_count=2,
            orphaned_content_count=0,
            missing_content_count=0,
            source_content_recovery_evidence_hash="sha256:" + str(index) * 64,
            api_wiring_allowed=True,
        )
        for index, tenant_id in enumerate(restore_report.tenant_ids, start=1)
    )
    draft = PersistentSourceObjectRuntimeReport(
        checked_at_utc=CHECKED_AT,
        runtime_environment="dev",
        provider_profile_evidence_hash=restore_report.source_provider_profile_evidence_hash,
        restore_drill_report_hash=restore_hash or restore_report.report_hash,
        expected_source_object_count=4,
        seeded_source_object_count=0,
        existing_source_object_count=4,
        restart_verified_source_object_count=4,
        tenant_evidence=tenant_evidence,
        provider_profile_ready=True,
        restart_read_verified=True,
        recovery_verified=True,
        runtime_ready=True,
        report_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"report_hash": build_persistent_source_object_runtime_report_hash(draft)})


def test_backend_storage_foundation_gate_binds_runtime_to_restore_report() -> None:
    restore_report = _restore_report()
    runtime_report = _runtime_report_for_restore(restore_report)

    gate = build_backend_storage_foundation_gate(
        runtime_report=runtime_report,
        restore_report=restore_report,
    )

    assert gate.backend_storage_foundation_ready is True
    assert gate.api_start_allowed is True
    assert gate.runtime_restore_binding_verified is True
    assert gate.metadata_only_evidence_verified is True
    assert gate.gate_hash == build_backend_storage_foundation_gate_hash(gate)


def test_backend_storage_foundation_gate_blocks_stale_runtime_restore_binding() -> None:
    restore_report = _restore_report()
    runtime_report = _runtime_report_for_restore(
        restore_report,
        restore_hash="sha256:" + "e" * 64,
    )

    gate = build_backend_storage_foundation_gate(
        runtime_report=runtime_report,
        restore_report=restore_report,
    )

    assert gate.backend_storage_foundation_ready is False
    assert gate.api_start_allowed is False
    assert gate.blocking_reasons == ("runtime_restore_binding_not_verified",)


def test_compose_exposes_isolated_restore_target_and_foundation_gate() -> None:
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "\n  minio-restore:\n" in compose
    assert compose.count('profiles: ["restore-drill"]') == 3
    assert "\n  object-storage-restore-profile-check:\n" in compose
    assert "\n  backend-storage-foundation-gate:\n" in compose
    assert "command: python -m suite.storage.backend_storage_foundation_gate" in compose
    assert "SUITE_RESTORE_S3_ENDPOINT_URL: http://minio-restore:9000" in compose
    assert "SUITE_SOURCE_OBJECT_RESTORE_DRILL_TENANT_IDS:" in compose
    assert "minio_restore_data:/data" in compose
    assert "\n  minio_restore_data:\n" in compose
