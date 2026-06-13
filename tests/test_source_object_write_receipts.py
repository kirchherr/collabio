import os
from dataclasses import dataclass
from uuid import uuid4

import pytest

from suite.ai_control_plane.models import DataClass
from suite.persistence.migrator import apply_migrations
from suite.storage.source_objects import (
    LegalHoldState,
    PgSourceObjectWriteReceiptStore,
    SourceLifecycleState,
    SourceObjectMetadata,
    SourceObjectRecord,
    SourceObjectType,
    build_source_object_manifest_hash,
    build_source_object_write_receipt,
    sha256_bytes,
)


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


def source_record_for_receipt(*, tenant_id: str, object_id: str, version_id: str, text: str) -> SourceObjectRecord:
    content = text.encode("utf-8")
    draft = SourceObjectMetadata(
        tenant_id=tenant_id,
        object_id=object_id,
        object_type=SourceObjectType.WIKI,
        version_id=version_id,
        title="Receipt-backed source",
        owner_principal_id=f"user-{tenant_id}",
        created_by=f"tenant-admin-{tenant_id}",
        created_at_utc="2026-06-12T10:00:00Z",
        updated_at_utc="2026-06-12T10:00:00Z",
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
        lifecycle_state=SourceLifecycleState.SAVED_VERSION,
    )
    return SourceObjectRecord(
        metadata=draft.model_copy(update={"manifest_hash": build_source_object_manifest_hash(draft)}),
        text=text,
    )


def test_pg_source_object_write_receipt_store_is_tenant_scoped_and_metadata_only(
    live_database: LiveDatabase,
) -> None:
    suffix = uuid4().hex
    tenant_id = f"tenant-receipt-{suffix}"
    record = source_record_for_receipt(
        tenant_id=tenant_id,
        object_id=f"source-receipt-{suffix}",
        version_id="v1",
        text="Receipt live postgres source content must not be stored in the receipt.",
    )
    receipt = build_source_object_write_receipt(
        record=record,
        receipt_reference=f"receipt:pg-source-write-{suffix}",
        audit_chain_ref=f"audit:pg-source-write-{suffix}",
        captured_at_utc="2026-06-12T10:01:00Z",
    )
    store = PgSourceObjectWriteReceiptStore(database_dsn=live_database.app_dsn)

    persisted = store.append(receipt)

    assert persisted == receipt
    assert store.get(tenant_id=tenant_id, receipt_hash=receipt.receipt_hash) == receipt
    assert store.list_receipts(tenant_id=tenant_id) == (receipt,)
    assert store.list_receipts(tenant_id=f"tenant-other-{suffix}") == ()
    assert "Receipt live postgres source content" not in receipt.model_dump_json()

    with pytest.raises(ValueError, match="already exists"):
        store.append(receipt)
