from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

from suite.platform.workspace_source_objects import demo_workspace_source_object_records
from suite.storage.adapter_policy import load_storage_adapter_policy
from suite.storage.persistent_source_object_runtime import (
    build_persistent_source_object_runtime_report_hash,
    run_persistent_source_object_runtime_check,
)
from suite.storage.s3_compatible_content_store import (
    S3CompatibleBucketCapabilities,
    S3CompatibleObjectStoreClient,
    S3CompatibleProviderProfileEvidence,
    build_s3_compatible_provider_profile_evidence,
)
from suite.storage.source_object_storage import (
    SourceObjectContentRecoveryEvidence,
    SourceObjectContentRecoveryStatus,
    build_source_object_content_recovery_evidence_hash,
)
from suite.storage.source_objects import SourceObjectRecord

REPO_ROOT = Path(__file__).resolve().parents[1]
RESTORE_HASH = "sha256:" + "4" * 64
CHECKED_AT = "2026-07-29T10:00:00Z"


class ReadyObjectStoreClient:
    def bucket_capabilities(self, *, bucket_id: str) -> S3CompatibleBucketCapabilities:
        return S3CompatibleBucketCapabilities(
            bucket_id=bucket_id,
            storage_provider="minio",
            versioning_enabled=True,
            object_lock_enabled=bucket_id in {"business-records", "evidence-records"},
            legal_hold_supported=bucket_id in {"business-records", "evidence-records"},
        )


class SharedPersistentRepository:
    def __init__(self, records: dict[tuple[str, str, str], SourceObjectRecord]) -> None:
        self.records = records

    def add(self, record: SourceObjectRecord) -> None:
        metadata = record.metadata
        key = (metadata.tenant_id, metadata.object_id, metadata.version_id)
        if key in self.records:
            raise ValueError("source object version already exists")
        self.records[key] = record

    def get(self, *, tenant_id: str, object_id: str, version_id: str) -> SourceObjectRecord:
        return self.records[(tenant_id, object_id, version_id)]

    def build_content_recovery_evidence(
        self,
        *,
        tenant_id: str,
        restore_drill_report_hash: str,
        checked_at_utc: str | None = None,
    ) -> SourceObjectContentRecoveryEvidence:
        record_count = sum(1 for key in self.records if key[0] == tenant_id)
        draft = SourceObjectContentRecoveryEvidence(
            tenant_id=tenant_id,
            storage_provider="minio",
            checked_at_utc=checked_at_utc or CHECKED_AT,
            restore_drill_report_hash=restore_drill_report_hash,
            reconciliation_status=SourceObjectContentRecoveryStatus.READY,
            stored_object_count=record_count,
            storage_manifest_count=record_count,
            verified_content_count=record_count,
            orphaned_content_count=0,
            missing_content_count=0,
            source_content_recovery_required=False,
            api_wiring_allowed=True,
            evidence_hash="sha256:" + "0" * 64,
        )
        return draft.model_copy(update={"evidence_hash": build_source_object_content_recovery_evidence_hash(draft)})


def _provider_evidence() -> S3CompatibleProviderProfileEvidence:
    return build_s3_compatible_provider_profile_evidence(
        client=cast(S3CompatibleObjectStoreClient, ReadyObjectStoreClient()),
        storage_policy=load_storage_adapter_policy(REPO_ROOT / "docs" / "storage_adapter_policy.json"),
        provider_profile_id="minio-test",
        checked_at_utc=CHECKED_AT,
    )


def _repository_factory(
    records: dict[tuple[str, str, str], SourceObjectRecord],
) -> Callable[[], SharedPersistentRepository]:
    return lambda: SharedPersistentRepository(records)


def test_persistent_runtime_seeds_once_and_verifies_a_fresh_repository_instance() -> None:
    stored_records: dict[tuple[str, str, str], SourceObjectRecord] = {}
    seed_records = demo_workspace_source_object_records()

    first_report = run_persistent_source_object_runtime_check(
        repository_factory=_repository_factory(stored_records),
        provider_profile_evidence=_provider_evidence(),
        restore_drill_report_hash=RESTORE_HASH,
        tenant_ids=("tenant-demo", "tenant-other"),
        seed_records=seed_records,
        checked_at_utc=CHECKED_AT,
    )
    second_report = run_persistent_source_object_runtime_check(
        repository_factory=_repository_factory(stored_records),
        provider_profile_evidence=_provider_evidence(),
        restore_drill_report_hash=RESTORE_HASH,
        tenant_ids=("tenant-demo", "tenant-other"),
        seed_records=seed_records,
        checked_at_utc=CHECKED_AT,
    )

    assert first_report.seeded_source_object_count == 3
    assert first_report.existing_source_object_count == 0
    assert first_report.restart_verified_source_object_count == 3
    assert first_report.runtime_ready is True
    assert first_report.content_included is False
    assert first_report.report_hash == build_persistent_source_object_runtime_report_hash(first_report)
    assert second_report.seeded_source_object_count == 0
    assert second_report.existing_source_object_count == 3
    assert second_report.runtime_ready is True


def test_persistent_runtime_rejects_demo_seeding_in_production() -> None:
    with pytest.raises(ValueError, match="forbidden in production"):
        run_persistent_source_object_runtime_check(
            repository_factory=_repository_factory({}),
            provider_profile_evidence=_provider_evidence(),
            restore_drill_report_hash=RESTORE_HASH,
            tenant_ids=("tenant-demo",),
            seed_records=demo_workspace_source_object_records(),
            runtime_environment="production",
            checked_at_utc=CHECKED_AT,
        )


def test_persistent_runtime_rejects_drift_in_existing_bootstrap_record() -> None:
    expected = demo_workspace_source_object_records()[0]
    drifted = expected.model_copy(
        update={"metadata": expected.metadata.model_copy(update={"title": "Unexpected title"})}
    )
    stored_records = {
        (expected.metadata.tenant_id, expected.metadata.object_id, expected.metadata.version_id): drifted,
    }

    with pytest.raises(ValueError, match="metadata does not match"):
        run_persistent_source_object_runtime_check(
            repository_factory=_repository_factory(stored_records),
            provider_profile_evidence=_provider_evidence(),
            restore_drill_report_hash=RESTORE_HASH,
            tenant_ids=("tenant-demo",),
            seed_records=(expected,),
            checked_at_utc=CHECKED_AT,
        )


def test_persistent_runtime_requires_a_restore_drill_hash() -> None:
    with pytest.raises(ValueError, match="must be a sha256 reference"):
        run_persistent_source_object_runtime_check(
            repository_factory=_repository_factory({}),
            provider_profile_evidence=_provider_evidence(),
            restore_drill_report_hash="not-a-hash",
            tenant_ids=("tenant-demo",),
            checked_at_utc=CHECKED_AT,
        )


def test_compose_wires_persistent_runtime_before_api_and_isolates_test_database() -> None:
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "\n  source-object-runtime-bootstrap:\n" in compose
    assert "command: python -m suite.storage.persistent_source_object_runtime" in compose
    assert "SUITE_WORKSPACE_SOURCE_OBJECT_REPOSITORY_BACKEND: postgres" in compose
    assert "SUITE_WORKSPACE_SOURCE_OBJECT_CONTENT_STORE_BACKEND: s3-compatible" in compose
    assert "source-object-runtime-bootstrap:\n        condition: service_completed_successfully" in compose
    assert 'profiles: ["object-storage"]' not in compose
    assert "\n  postgres-test:\n" in compose
    assert compose.count("postgresql://collabio_owner:collabio_owner@postgres-test:5432/collabio_test") == 2
    assert compose.count("postgres18_test_data:/var/lib/postgresql") == 1
