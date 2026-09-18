from __future__ import annotations

from pathlib import Path

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.platform.office_document_repository import PgOfficeDocumentRepository
from suite.platform.office_documents import OfficeDocumentService
from suite.platform.office_review_repository import PgOfficeReviewRepository
from suite.platform.office_reviews import OfficeReviewService
from suite.storage.adapter_policy import load_storage_adapter_policy
from suite.storage.retention import load_retention_manifest_policy
from suite.storage.s3_compatible_content_store import S3CompatibleSourceObjectContentStore
from suite.storage.s3_sdk_client import Boto3S3CompatibleObjectStoreClient
from suite.storage.source_object_storage import PgSourceObjectRepository
from suite.storage.source_objects import PgSourceObjectWriteReceiptStore


def build_synthetic_office_service(
    *, database_dsn: str, client: Boto3S3CompatibleObjectStoreClient, audit: InMemoryAuditLogger
) -> OfficeDocumentService:
    """Called only after the server's isolated-environment guard has succeeded."""
    storage_policy = load_storage_adapter_policy(Path("docs/storage_adapter_policy.json"))
    source_repository = PgSourceObjectRepository(
        database_dsn=database_dsn,
        content_store=S3CompatibleSourceObjectContentStore(client=client, storage_policy=storage_policy),
        storage_policy=storage_policy,
        retention_policy=load_retention_manifest_policy(Path("docs/retention_manifest_policy.json")),
    )
    return OfficeDocumentService(
        repository=PgOfficeDocumentRepository(
            database_dsn=database_dsn,
            source_repository=source_repository,
            receipt_store=PgSourceObjectWriteReceiptStore(database_dsn=database_dsn),
        ),
        source_repository=source_repository,
        audit=audit,
    )


def build_synthetic_office_review_service(
    *, document_service: OfficeDocumentService, audit: InMemoryAuditLogger
) -> OfficeReviewService:
    """Share the guarded real document database, source store and receipt transaction."""
    return OfficeReviewService(
        repository=PgOfficeReviewRepository(document_service=document_service),
        source_repository=document_service.source_repository,
        audit=audit,
    )
