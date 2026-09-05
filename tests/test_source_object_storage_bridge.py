import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from suite.ai_control_plane.models import DataClass
from suite.persistence.migrator import apply_migrations
from suite.storage.adapter_policy import load_storage_adapter_policy
from suite.storage.retention import load_retention_manifest_policy
from suite.storage.source_object_storage import (
    InMemorySourceObjectContentStore,
    PgSourceObjectRepository,
    SourceObjectContentReconciliationAction,
    SourceObjectContentReconciliationWorker,
    SourceObjectContentRecoveryStatus,
    build_source_object_content_recovery_evidence_hash,
)
from suite.storage.source_objects import (
    LegalHoldState,
    SourceLifecycleState,
    SourceObjectMetadata,
    SourceObjectRecord,
    SourceObjectType,
    build_source_object_manifest_hash,
    sha256_bytes,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
RETENTION_POLICY_PATH = REPO_ROOT / "docs" / "retention_manifest_policy.json"
STORAGE_POLICY_PATH = REPO_ROOT / "docs" / "storage_adapter_policy.json"


@dataclass(frozen=True)
class LiveDatabase:
    migration_dsn: str
    app_dsn: str


def env_or_skip(name: str) -> str:
    value = os.environ.get(name)
    if value is None:
        pytest.skip(f"{name} is not configured")
    return value


@pytest.fixture(scope="module")
def live_database() -> LiveDatabase:
    migration_dsn = env_or_skip("SUITE_MIGRATION_DATABASE_DSN")
    app_dsn = env_or_skip("SUITE_DATABASE_DSN")
    apply_migrations(migration_dsn)
    return LiveDatabase(migration_dsn=migration_dsn, app_dsn=app_dsn)


def source_record_for_storage_bridge(
    *,
    tenant_id: str,
    object_id: str,
    version_id: str,
    text: str,
) -> SourceObjectRecord:
    content = text.encode("utf-8")
    draft = SourceObjectMetadata(
        tenant_id=tenant_id,
        object_id=object_id,
        object_type=SourceObjectType.DOCUMENT,
        version_id=version_id,
        title="Storage bridge source",
        owner_principal_id=f"user-{tenant_id}",
        created_by=f"tenant-admin-{tenant_id}",
        created_at_utc="2026-06-12T11:00:00Z",
        updated_at_utc="2026-06-12T11:00:00Z",
        classification=DataClass.INTERNAL,
        retention_policy_id="rp-standard",
        legal_hold_state=LegalHoldState.NONE,
        kms_key_ref=f"kms://{tenant_id}/internal/v1",
        manifest_hash="sha256:" + "0" * 64,
        audit_chain_ref=f"audit:{object_id}",
        source_system="collabio",
        mime_type="text/plain",
        acl_hash="sha256:" + "a" * 64,
        acl_version=1,
        content_hash=sha256_bytes(content),
        content_byte_length=len(content),
        lifecycle_state=SourceLifecycleState.WORKING,
    )
    return SourceObjectRecord(
        metadata=draft.model_copy(update={"manifest_hash": build_source_object_manifest_hash(draft)}),
        text=text,
    )


def set_tenant(connection: psycopg.Connection[object], tenant_id: str) -> None:
    connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))


def test_pg_source_object_repository_bridges_metadata_storage_manifest_and_content(
    live_database: LiveDatabase,
) -> None:
    suffix = uuid4().hex
    tenant_id = f"tenant-source-storage-{suffix}"
    record = source_record_for_storage_bridge(
        tenant_id=tenant_id,
        object_id=f"source-storage-{suffix}",
        version_id="v1",
        text="Source object storage bridge content must stay outside PostgreSQL.",
    )
    repository = PgSourceObjectRepository(
        database_dsn=live_database.app_dsn,
        content_store=InMemorySourceObjectContentStore(stored_at_clock=lambda: "2026-06-12T11:01:00Z"),
        retention_policy=load_retention_manifest_policy(RETENTION_POLICY_PATH),
        storage_policy=load_storage_adapter_policy(STORAGE_POLICY_PATH),
    )

    repository.add(record)

    fetched = repository.get(
        tenant_id=tenant_id,
        object_id=record.metadata.object_id,
        version_id=record.metadata.version_id,
    )
    latest = repository.latest(tenant_id=tenant_id, object_id=record.metadata.object_id)

    assert fetched == record
    assert latest == record
    assert "Source object storage bridge content" not in fetched.metadata.model_dump_json()
    with pytest.raises(KeyError, match="not found"):
        repository.get(tenant_id=f"tenant-other-{suffix}", object_id=record.metadata.object_id, version_id="v1")

    with psycopg.connect(live_database.app_dsn) as connection:
        set_tenant(connection, tenant_id)
        metadata_count = connection.execute(
            "SELECT COUNT(*) FROM collabio.source_object_metadata WHERE tenant_id = %s",
            (tenant_id,),
        ).fetchone()
        manifest_count = connection.execute(
            "SELECT COUNT(*) FROM collabio.source_object_storage_manifests WHERE tenant_id = %s",
            (tenant_id,),
        ).fetchone()
    assert metadata_count is not None
    assert manifest_count is not None
    assert int(metadata_count[0]) == 1
    assert int(manifest_count[0]) == 1

    recovery_evidence = repository.build_content_recovery_evidence(
        tenant_id=tenant_id,
        restore_drill_report_hash="sha256:" + "b" * 64,
        checked_at_utc="2026-06-12T11:02:00Z",
    )
    assert recovery_evidence.reconciliation_status == SourceObjectContentRecoveryStatus.READY
    assert recovery_evidence.stored_object_count == 1
    assert recovery_evidence.storage_manifest_count == 1
    assert recovery_evidence.verified_content_count == 1
    assert recovery_evidence.orphaned_content_count == 0
    assert recovery_evidence.missing_content_count == 0
    assert recovery_evidence.source_content_recovery_required is False
    assert recovery_evidence.api_wiring_allowed is True
    assert recovery_evidence.evidence_hash == build_source_object_content_recovery_evidence_hash(recovery_evidence)
    assert "Source object storage bridge content" not in recovery_evidence.model_dump_json()
    reconciliation_run = SourceObjectContentReconciliationWorker(repository).run(
        tenant_id=tenant_id,
        restore_drill_report_hash="sha256:" + "b" * 64,
        checked_at_utc="2026-06-12T11:02:00Z",
    )
    assert reconciliation_run.evidence_hash == recovery_evidence.evidence_hash
    assert reconciliation_run.recommended_action == SourceObjectContentReconciliationAction.READY_FOR_API_WIRING
    assert reconciliation_run.api_wiring_allowed is True

    with pytest.raises(ValueError, match="already exists"):
        repository.add(record)
