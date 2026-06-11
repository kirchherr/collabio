from dataclasses import dataclass, field

import pytest

from suite.ai_control_plane.models import DataClass
from suite.rag.models import VectorEmbeddingRecord, VectorLifecycleState
from suite.rag.source_indexing import (
    DeterministicHashEmbeddingProvider,
    FixedSizeTextChunker,
    PlainTextExtractor,
    SourceIndexCommand,
    SourceIndexingPipeline,
)
from suite.rag.vector_worker import VectorIndexWorker
from suite.storage.source_objects import (
    InMemorySourceObjectRepository,
    LegalHoldState,
    SourceLifecycleState,
    SourceObjectMetadata,
    SourceObjectRecord,
    SourceObjectResolver,
    SourceObjectType,
    SourceObjectWriteDeniedError,
    build_source_object_manifest_hash,
    sha256_bytes,
)


@dataclass
class CapturingVectorIndexStore:
    upserted: list[VectorEmbeddingRecord] = field(default_factory=list)

    def mark_source_for_reindex(
        self,
        *,
        tenant_id: str,
        source_object_id: str,
        source_version_id: str,
        audit_event_id: str | None = None,
    ) -> int:
        return 0

    def upsert_embedding(self, record: VectorEmbeddingRecord) -> None:
        self.upserted.append(record)

    def delete_reindex_orphans(
        self,
        *,
        tenant_id: str,
        source_object_id: str,
        source_version_id: str,
        keep_chunk_ids: set[str],
        audit_event_id: str | None = None,
    ) -> int:
        return 0

    def transition_source_lifecycle(
        self,
        *,
        tenant_id: str,
        source_object_id: str,
        source_version_id: str,
        lifecycle_state: VectorLifecycleState,
        audit_event_id: str | None = None,
    ) -> int:
        raise AssertionError("source object indexing must not perform lifecycle deletion")


def metadata_for(
    *,
    object_type: SourceObjectType = SourceObjectType.DOCUMENT,
    object_id: str = "doc-1",
    version_id: str = "v1",
    title: str = "Source object",
    text: str = "Authoritative source text",
    mime_type: str = "text/plain",
    parent_object_id: str | None = None,
    thread_id: str | None = None,
    legal_hold_state: LegalHoldState = LegalHoldState.NONE,
    lifecycle_state: SourceLifecycleState = SourceLifecycleState.WORKING,
) -> SourceObjectMetadata:
    content = text.encode("utf-8")
    draft = SourceObjectMetadata(
        tenant_id="tenant-1",
        object_id=object_id,
        object_type=object_type,
        version_id=version_id,
        title=title,
        owner_principal_id="user-owner",
        created_by="user-creator",
        created_at_utc="2026-06-10T00:00:00Z",
        updated_at_utc="2026-06-10T00:01:00Z",
        classification=DataClass.INTERNAL,
        retention_policy_id="rp-standard",
        legal_hold_state=legal_hold_state,
        kms_key_ref="kms://tenant-1/internal/v1",
        manifest_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        audit_chain_ref="audit:chain-1",
        source_system="collabio",
        mime_type=mime_type,
        acl_hash="sha256:acl",
        acl_version=3,
        content_hash=sha256_bytes(content),
        content_byte_length=len(content),
        lifecycle_state=lifecycle_state,
        parent_object_id=parent_object_id,
        thread_id=thread_id,
    )
    return draft.model_copy(update={"manifest_hash": build_source_object_manifest_hash(draft)})


def record_for(
    *,
    object_type: SourceObjectType = SourceObjectType.DOCUMENT,
    object_id: str = "doc-1",
    title: str = "Source object",
    text: str = "Authoritative source text",
    mime_type: str = "text/plain",
    parent_object_id: str | None = None,
    thread_id: str | None = None,
    legal_hold_state: LegalHoldState = LegalHoldState.NONE,
    lifecycle_state: SourceLifecycleState = SourceLifecycleState.WORKING,
) -> SourceObjectRecord:
    return SourceObjectRecord(
        metadata=metadata_for(
            object_type=object_type,
            object_id=object_id,
            title=title,
            text=text,
            mime_type=mime_type,
            parent_object_id=parent_object_id,
            thread_id=thread_id,
            legal_hold_state=legal_hold_state,
            lifecycle_state=lifecycle_state,
        ),
        text=text,
    )


@pytest.mark.parametrize(
    ("object_type", "object_id", "mime_type", "parent_object_id", "thread_id"),
    [
        (SourceObjectType.DOCUMENT, "doc-1", "text/plain", None, None),
        (SourceObjectType.MAIL, "mail-1", "message/rfc822", None, "thread-1"),
        (SourceObjectType.ATTACHMENT, "att-1", "text/plain", "mail-1", None),
        (SourceObjectType.COMMENT, "comment-1", "text/plain", "doc-1", None),
        (SourceObjectType.PROCEDURE_DOC, "procedure-1", "text/plain", None, None),
    ],
)
def test_source_objects_carry_common_compliance_metadata(
    object_type: SourceObjectType,
    object_id: str,
    mime_type: str,
    parent_object_id: str | None,
    thread_id: str | None,
) -> None:
    record = record_for(
        object_type=object_type,
        object_id=object_id,
        mime_type=mime_type,
        parent_object_id=parent_object_id,
        thread_id=thread_id,
    )

    document = record.to_source_document()

    assert record.metadata.tenant_id == "tenant-1"
    assert record.metadata.classification == DataClass.INTERNAL
    assert record.metadata.retention_policy_id == "rp-standard"
    assert record.metadata.kms_key_ref.startswith("kms://")
    assert record.metadata.manifest_hash.startswith("sha256:")
    assert record.metadata.audit_chain_ref.startswith("audit:")
    assert document.object_id == object_id
    assert document.version_id == "v1"
    assert document.mime_type == mime_type
    assert document.classification == DataClass.INTERNAL


@pytest.mark.parametrize("object_type", [SourceObjectType.ATTACHMENT, SourceObjectType.COMMENT])
def test_attachment_and_comment_require_parent_object(object_type: SourceObjectType) -> None:
    with pytest.raises(ValueError, match="parent_object_id"):
        record_for(object_type=object_type, object_id=f"{object_type.value}-1")


@pytest.mark.parametrize(
    "lifecycle_state",
    [SourceLifecycleState.DELETED, SourceLifecycleState.CRYPTOSHREDDED],
)
def test_legal_hold_blocks_deletion_and_cryptoshredding(lifecycle_state: SourceLifecycleState) -> None:
    with pytest.raises(ValueError, match="legal hold blocks"):
        record_for(
            legal_hold_state=LegalHoldState.ACTIVE,
            lifecycle_state=lifecycle_state,
        )


def test_source_object_metadata_rejects_unqualified_compliance_references() -> None:
    with pytest.raises(ValueError, match="kms_key_ref"):
        SourceObjectMetadata(
            **{
                **metadata_for().model_dump(),
                "kms_key_ref": "tenant-key-v1",
            }
        )


def test_source_object_repository_is_tenant_version_scoped() -> None:
    first = record_for(object_id="doc-1", text="Version one")
    second = SourceObjectRecord(
        metadata=metadata_for(object_id="doc-1", version_id="v2", text="Version two"),
        text="Version two",
    )
    repository = InMemorySourceObjectRepository(records=(first,))
    repository.add(second)

    assert repository.get(tenant_id="tenant-1", object_id="doc-1", version_id="v1") == first
    assert repository.latest(tenant_id="tenant-1", object_id="doc-1") == second
    with pytest.raises(KeyError):
        repository.get(tenant_id="tenant-2", object_id="doc-1", version_id="v1")
    with pytest.raises(ValueError, match="already exists"):
        repository.add(first)


def test_source_object_repository_rejects_content_hash_mismatch_before_write() -> None:
    record = record_for()
    tampered = SourceObjectRecord(
        metadata=record.metadata.model_copy(update={"content_hash": "sha256:not-the-content"}),
        text=record.text,
    )
    repository = InMemorySourceObjectRepository()

    with pytest.raises(SourceObjectWriteDeniedError, match="content_hash"):
        repository.add(tampered)


def test_source_object_repository_rejects_manifest_hash_mismatch_before_write() -> None:
    record = record_for()
    tampered = SourceObjectRecord(
        metadata=record.metadata.model_copy(update={"title": "Changed after manifest"}),
        text=record.text,
    )
    repository = InMemorySourceObjectRepository()

    with pytest.raises(SourceObjectWriteDeniedError, match="manifest_hash"):
        repository.add(tampered)


def test_source_object_repository_rejects_non_kms_key_reference_before_write() -> None:
    record = record_for()
    metadata = record.metadata.model_copy(update={"kms_key_ref": "vault://tenant-1/internal/v1"})
    metadata = metadata.model_copy(update={"manifest_hash": build_source_object_manifest_hash(metadata)})
    tampered = SourceObjectRecord(metadata=metadata, text=record.text)
    repository = InMemorySourceObjectRepository()

    with pytest.raises(SourceObjectWriteDeniedError, match="kms_key_ref"):
        repository.add(tampered)


def test_source_object_resolver_feeds_indexing_pipeline_with_authoritative_metadata() -> None:
    record = record_for(
        object_type=SourceObjectType.ATTACHMENT,
        object_id="att-1",
        title="Mail attachment",
        text="Attachment content for authorized indexing.",
        parent_object_id="mail-1",
        legal_hold_state=LegalHoldState.ACTIVE,
    )
    repository = InMemorySourceObjectRepository(records=(record,))
    store = CapturingVectorIndexStore()
    pipeline = SourceIndexingPipeline(
        resolver=SourceObjectResolver(repository),
        text_extractor=PlainTextExtractor(),
        chunker=FixedSizeTextChunker(max_characters=256),
        embedding_provider=DeterministicHashEmbeddingProvider(dimensions=3),
        worker=VectorIndexWorker(store),
        embedding_model_id="mock-embedding",
        embedding_model_version="1",
        indexed_at_clock=lambda: "2026-06-10T00:02:00Z",
    )

    result = pipeline.index_source(
        SourceIndexCommand(
            tenant_id="tenant-1",
            source_object_id="att-1",
            source_version_id="v1",
            audit_event_id="audit-source-object-index",
        )
    )

    assert result.chunk_count == 1
    assert store.upserted[0].metadata.source_object_type == "attachment"
    assert store.upserted[0].metadata.retention_policy_id == "rp-standard"
    assert store.upserted[0].metadata.legal_hold_state == "active"
    assert store.upserted[0].metadata.acl_hash == "sha256:acl"
    assert store.upserted[0].metadata.acl_version == 3
    assert store.upserted[0].metadata.created_at_utc == "2026-06-10T00:00:00Z"
