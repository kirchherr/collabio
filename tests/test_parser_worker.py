from dataclasses import dataclass, field

import pytest

from suite.ai_control_plane.models import DataClass
from suite.rag.models import SourceDocument, VectorEmbeddingRecord, VectorLifecycleState
from suite.rag.parser_worker import (
    ParserInputTooLargeError,
    ParserSandboxPolicy,
    ParserWorkerRequest,
    ParserWorkerTextExtractor,
    PolicyEnforcedParserWorker,
    UnsupportedParserInputError,
)
from suite.rag.repositories import InMemorySourceRepository
from suite.rag.source_indexing import (
    DeterministicHashEmbeddingProvider,
    FixedSizeTextChunker,
    RepositorySourceResolver,
    SourceIndexCommand,
    SourceIndexingPipeline,
)
from suite.rag.vector_worker import VectorIndexWorker


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
        raise AssertionError("parser indexing tests must not perform lifecycle deletion")


def parser_request(
    *,
    source_object_type: str = "document",
    mime_type: str = "text/plain",
    content: bytes = b"Hello\r\nworld",
) -> ParserWorkerRequest:
    return ParserWorkerRequest(
        tenant_id="tenant-1",
        source_object_id="doc-1",
        source_version_id="v1",
        source_object_type=source_object_type,
        mime_type=mime_type,
        content=content,
    )


def test_policy_enforced_parser_worker_extracts_plain_text_with_hashes() -> None:
    worker = PolicyEnforcedParserWorker()

    artifact = worker.parse(parser_request(content=b"Hello\r\nworld   \n"))

    assert artifact.text == "Hello\nworld"
    assert artifact.mime_type == "text/plain"
    assert artifact.source_object_type == "document"
    assert artifact.input_hash.startswith("sha256:")
    assert artifact.text_hash.startswith("sha256:")
    assert artifact.text_byte_length == len(b"Hello\nworld")
    assert artifact.warnings == ()


def test_policy_enforced_parser_worker_extracts_mail_text_and_skips_attachments() -> None:
    raw_mail = (
        b"From: alice@example.test\r\n"
        b"To: team@example.test\r\n"
        b"Subject: Retention approval\r\n"
        b"MIME-Version: 1.0\r\n"
        b"Content-Type: multipart/mixed; boundary=frontier\r\n"
        b"\r\n"
        b"--frontier\r\n"
        b"Content-Type: text/plain; charset=utf-8\r\n"
        b"\r\n"
        b"Please approve the retention policy.\r\n"
        b"--frontier\r\n"
        b"Content-Type: text/plain; name=secret.txt\r\n"
        b"Content-Disposition: attachment; filename=secret.txt\r\n"
        b"\r\n"
        b"ATTACHMENT_SECRET_SHOULD_NOT_BE_EXTRACTED\r\n"
        b"--frontier--\r\n"
    )
    worker = PolicyEnforcedParserWorker()

    artifact = worker.parse(
        parser_request(
            source_object_type="mail",
            mime_type="message/rfc822",
            content=raw_mail,
        )
    )

    assert "Subject: Retention approval" in artifact.text
    assert "Please approve the retention policy." in artifact.text
    assert "ATTACHMENT_SECRET_SHOULD_NOT_BE_EXTRACTED" not in artifact.text
    assert artifact.warnings == ("attachment skipped: secret.txt",)


def test_policy_enforced_parser_worker_rejects_unsupported_binary_document_until_sandbox_exists() -> None:
    worker = PolicyEnforcedParserWorker()

    with pytest.raises(UnsupportedParserInputError, match="unsupported mime type"):
        worker.parse(
            parser_request(
                mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                content=b"PK\x03\x04fake-docx",
            )
        )


def test_policy_enforced_parser_worker_enforces_input_limits() -> None:
    worker = PolicyEnforcedParserWorker(policy=ParserSandboxPolicy(max_input_bytes=4))

    with pytest.raises(ParserInputTooLargeError, match="byte limit"):
        worker.parse(parser_request(content=b"hello"))


def test_parser_worker_text_extractor_feeds_mail_into_source_indexing_pipeline() -> None:
    raw_mail = (
        "From: alice@example.test\r\n"
        "To: team@example.test\r\n"
        "Subject: Policy\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "\r\n"
        "Index this mail body for authorized search only."
    )
    store = CapturingVectorIndexStore()
    repository = InMemorySourceRepository(
        documents={
            "mail-1": SourceDocument(
                object_id="mail-1",
                version_id="v1",
                title="Policy mail",
                text=raw_mail,
                classification=DataClass.INTERNAL,
                mime_type="message/rfc822",
            )
        }
    )
    pipeline = SourceIndexingPipeline(
        resolver=RepositorySourceResolver(
            repository,
            source_object_type="mail",
            created_at_clock=lambda: "2026-06-10T00:00:00Z",
        ),
        text_extractor=ParserWorkerTextExtractor(PolicyEnforcedParserWorker()),
        chunker=FixedSizeTextChunker(max_characters=512),
        embedding_provider=DeterministicHashEmbeddingProvider(dimensions=3),
        worker=VectorIndexWorker(store),
        embedding_model_id="mock-embedding",
        embedding_model_version="1",
        indexed_at_clock=lambda: "2026-06-10T00:01:00Z",
    )

    result = pipeline.index_source(
        SourceIndexCommand(
            tenant_id="tenant-1",
            source_object_id="mail-1",
            source_version_id="v1",
            audit_event_id="audit-mail-index",
        )
    )

    assert result.chunk_count == 1
    assert store.upserted[0].metadata.source_object_type == "mail"
    assert store.upserted[0].metadata.source_object_id == "mail-1"
    assert store.upserted[0].metadata.classification == DataClass.INTERNAL
    assert store.upserted[0].content_byte_length > 0
    assert store.upserted[0].audit_event_id == "audit-mail-index"
