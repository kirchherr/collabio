from dataclasses import dataclass
from typing import Any, Literal

import pytest

from office_recovery_proof import require_office_recovery_environment, verify_restored_reviews
from suite.ai_control_plane.audit import InMemoryAuditLogger, canonical_json
from suite.ai_control_plane.models import UserContext
from suite.platform.office_document_repository import InMemoryOfficeDocumentRepository
from suite.platform.office_documents import (
    OfficeDocumentCreateCommand,
    OfficeDocumentSaveCommand,
    OfficeDocumentService,
)
from suite.platform.office_review_repository import InMemoryOfficeReviewRepository
from suite.platform.office_reviews import OfficeReviewService, ReviewAnchor, ReviewCreateCommand, ReviewEventCommand
from suite.storage.source_objects import InMemorySourceObjectRepository, InMemorySourceObjectWriteReceiptStore


def recovery_environment() -> dict[str, str]:
    return {
        "SUITE_OFFICE_RECOVERY_MODE": "isolated-office-recovery",
        "SUITE_ENV": "dev",
        "SUITE_PRODUCTIVITY_PILOT_RUNTIME_ENABLED": "0",
        "SUITE_POSTGRES_RESTORE_SOURCE_DSN": "postgresql://collabio_owner:synthetic@work-e2e-postgres:5432/collabio_work_e2e",
        "SUITE_POSTGRES_RESTORE_TARGET_DSN": "postgresql://collabio_owner:synthetic@postgres-restore:5432/collabio_work_e2e_restore",
        "SUITE_DATABASE_DSN": "postgresql://collabio_app:synthetic@work-e2e-postgres:5432/collabio_work_e2e",
        "SUITE_OFFICE_RECOVERY_TARGET_DSN": "postgresql://collabio_app:synthetic@postgres-restore:5432/collabio_work_e2e_restore",
        "SUITE_S3_ENDPOINT_URL": "http://work-e2e-minio:9000",
        "SUITE_RESTORE_S3_ENDPOINT_URL": "http://minio-restore:9000",
        "SUITE_POSTGRES_BACKUP_DIRECTORY": "/proof-backup",
        "SUITE_POSTGRES_RESTORE_RECEIPT_PATH": "/proof-backup/postgres-restore-receipt.sha256",
    }


def test_office_recovery_accepts_only_explicit_separate_synthetic_targets() -> None:
    require_office_recovery_environment(recovery_environment())


@pytest.mark.parametrize(
    "key,value",
    [
        ("SUITE_OFFICE_RECOVERY_MODE", ""),
        ("SUITE_ENV", "production"),
        ("SUITE_PRODUCTIVITY_PILOT_RUNTIME_ENABLED", "1"),
        ("SUITE_POSTGRES_RESTORE_SOURCE_DSN", "postgresql://collabio_owner:x@postgres:5432/collabio"),
        ("SUITE_POSTGRES_RESTORE_TARGET_DSN", "postgresql://collabio_owner:x@postgres-restore:5432/collabio_restore"),
        ("SUITE_OFFICE_RECOVERY_TARGET_DSN", "postgresql://collabio_app:x@work-e2e-postgres:5432/collabio_work_e2e"),
        ("SUITE_DATABASE_DSN", "postgresql://collabio_app:x@work-e2e-postgres:5432/collabio_work_e2e?host=postgres"),
        ("SUITE_S3_ENDPOINT_URL", "http://minio:9000"),
        ("SUITE_RESTORE_S3_ENDPOINT_URL", "http://work-e2e-minio:9000"),
        ("SUITE_POSTGRES_BACKUP_DIRECTORY", "/backups"),
        ("SUITE_POSTGRES_RESTORE_RECEIPT_PATH", "/backups/postgres-restore-receipt.sha256"),
    ],
)
def test_office_recovery_denies_live_same_target_or_unscoped_overrides(key: str, value: str) -> None:
    env = recovery_environment()
    env[key] = value
    with pytest.raises(ValueError):
        require_office_recovery_environment(env)


@dataclass
class ReviewRecoveryFixture:
    documents: OfficeDocumentService
    document_repository: InMemoryOfficeDocumentRepository
    reviews: OfficeReviewService
    review_repository: InMemoryOfficeReviewRepository
    sources: InMemorySourceObjectRepository
    receipts: InMemorySourceObjectWriteReceiptStore
    user: UserContext
    object_id: str
    thread_id: str
    event_ids: set[str]

    def verify(self) -> dict[str, Any]:
        return verify_restored_reviews(
            documents=self.documents,
            reviews=self.reviews,
            sources=self.sources,
            receipts=self.receipts,
            user=self.user,
            object_ids=(self.object_id,),
            expected_thread_ids={self.thread_id},
            expected_event_ids=self.event_ids,
        )


def review_recovery_fixture(*, replies: int = 1) -> ReviewRecoveryFixture:
    sources = InMemorySourceObjectRepository()
    receipts = InMemorySourceObjectWriteReceiptStore()
    repository = InMemoryOfficeDocumentRepository(source_repository=sources, receipt_store=receipts)
    audit = InMemoryAuditLogger()
    documents = OfficeDocumentService(repository=repository, source_repository=sources, audit=audit)
    user = UserContext(tenant_id="tenant-work-e2e", user_id="work-office-editor-e2e", role_ids={"office-editor"})
    content = {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "😀 private anchor"}]}],
    }
    saved = documents.create(
        user_context=user,
        write_enabled=True,
        command=OfficeDocumentCreateCommand(
            title="Synthetic recovery",
            document=content,
            mutation_reference="recovery-create-document",
            human_confirmation=True,
        ),
    )
    object_id = saved.document.object_id
    user = user.model_copy(update={"readable_object_ids": {object_id}})
    review_repository = InMemoryOfficeReviewRepository(document_service=documents)
    reviews = OfficeReviewService(repository=review_repository, source_repository=sources, audit=audit)
    created = reviews.mutate(
        user_context=user,
        object_id=object_id,
        write_enabled=True,
        command=ReviewCreateCommand(
            anchor_version_id=saved.version.version_id,
            expected_current_version_id=saved.version.version_id,
            anchor=ReviewAnchor.model_validate({"from": 1, "to": 3}),
            body="Private recovery comment",
            mutation_reference="recovery-create-review",
            human_confirmation=True,
        ),
    )
    thread_id = created.thread.thread_id
    current = created
    for number in range(replies):
        current = reviews.mutate(
            user_context=user,
            object_id=object_id,
            thread_id=thread_id,
            write_enabled=True,
            command=ReviewEventCommand(
                operation="reply",
                expected_revision=current.thread.revision,
                body=f"Private recovery reply {number}",
                mutation_reference=f"recovery-reply-{number}",
                human_confirmation=True,
            ),
        )
    status_operations: tuple[Literal["resolve", "reopen"], ...] = ("resolve", "reopen")
    for operation in status_operations:
        current = reviews.mutate(
            user_context=user,
            object_id=object_id,
            thread_id=thread_id,
            write_enabled=True,
            command=ReviewEventCommand(
                operation=operation,
                expected_revision=current.thread.revision,
                mutation_reference=f"recovery-{operation}",
                human_confirmation=True,
            ),
        )
    documents.save(
        user_context=user,
        object_id=object_id,
        write_enabled=True,
        command=OfficeDocumentSaveCommand(
            title="New current version",
            document=content,
            expected_current_version_id=saved.version.version_id,
            mutation_reference="recovery-new-head",
            human_confirmation=True,
        ),
    )
    documents.writes_available = False
    reviews.writes_available = False
    return ReviewRecoveryFixture(
        documents,
        repository,
        reviews,
        review_repository,
        sources,
        receipts,
        user,
        object_id,
        thread_id,
        {event.event_id for event in review_repository.events.values()},
    )


def test_review_recovery_reads_paginated_complete_lifecycle_and_emits_only_metadata() -> None:
    fixture = review_recovery_fixture(replies=51)
    report = fixture.verify()
    assert report["verified_review_thread_count"] == 1
    assert report["verified_review_event_count"] == 54
    assert report["complete_review_lifecycle_count"] == 1
    assert report["anchored_review_thread_count"] == 1
    assert report["historical_review_thread_count"] == 1
    assert report["review_authoritative_acl_verified"]
    assert report["review_receipt_bindings_verified"]
    assert report["review_read_only_verified"]
    serialized = canonical_json(report)
    assert "Private recovery" not in serialized
    assert "private anchor" not in serialized
    assert "😀" not in serialized
    assert len(fixture.review_repository.events) == 54


@pytest.mark.parametrize(
    "tamper", ["missing_event", "previous_event", "status", "anchor", "receipt", "source", "acl", "inventory"]
)
def test_review_recovery_rejects_lost_events_rebound_sources_and_permission_drift(tamper: str) -> None:
    fixture = review_recovery_fixture()
    event = next(event for event in fixture.review_repository.events.values() if event.operation == "reply")
    event_key = (fixture.user.tenant_id, event.event_id)
    thread_key = (fixture.user.tenant_id, fixture.thread_id)
    source_key = (fixture.user.tenant_id, fixture.thread_id, event.event_id)
    if tamper == "missing_event":
        del fixture.review_repository.events[event_key]
    elif tamper == "previous_event":
        fixture.review_repository.events[event_key] = event.model_copy(update={"previous_event_id": "unrelated-event"})
    elif tamper == "status":
        fixture.review_repository.events[event_key] = event.model_copy(update={"status_after": "resolved"})
    elif tamper == "anchor":
        thread = fixture.review_repository.threads[thread_key]
        fixture.review_repository.threads[thread_key] = thread.model_copy(update={"anchor_from": 3, "anchor_to": 4})
    elif tamper == "receipt":
        receipt_key = (fixture.user.tenant_id, event.source_write_receipt_hash)
        receipt = fixture.receipts._receipts[receipt_key]
        fixture.receipts._receipts[receipt_key] = receipt.model_copy(update={"parent_object_id": "unrelated-document"})
    elif tamper == "source":
        record = fixture.sources._records[source_key]
        fixture.sources._records[source_key] = record.model_copy(update={"content_bytes": b"corrupt restored source"})
    elif tamper == "acl":
        fixture.document_repository.grants.clear()
    else:
        fixture.event_ids.add("event-missing-from-restored-service")
    with pytest.raises((ValueError, KeyError)):
        fixture.verify()


def test_review_recovery_rejects_empty_or_incomplete_lifecycle_evidence() -> None:
    fixture = review_recovery_fixture(replies=0)
    with pytest.raises(ValueError, match="complete review lifecycle"):
        fixture.verify()
