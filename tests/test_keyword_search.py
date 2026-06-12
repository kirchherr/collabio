from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import DataClass, UserContext
from suite.rag.repositories import InMemoryAclAuthorizer
from suite.search.keyword import InMemoryKeywordIndex, KeywordIndexedChunk, KeywordSearchService, keyword_metadata
from suite.search.models import KeywordSearchQuery


def user_context(*, tenant_id: str = "tenant-demo") -> UserContext:
    return UserContext(
        user_id="user-demo",
        tenant_id=tenant_id,
        role_ids={"knowledge-worker"},
        readable_object_ids=set(),
    )


def indexed_chunk(
    *,
    object_id: str,
    chunk_id: str,
    title: str,
    index_text: str,
    tenant_id: str = "tenant-demo",
    classification: DataClass = DataClass.INTERNAL,
) -> KeywordIndexedChunk:
    return KeywordIndexedChunk(
        metadata=keyword_metadata(
            tenant_id=tenant_id,
            object_id=object_id,
            chunk_id=chunk_id,
            classification=classification,
            retention_policy_id="rp-standard",
            acl_hash=f"sha256:acl-{object_id}",
            content_hash=f"sha256:{object_id}",
        ),
        title=title,
        index_text=index_text,
    )


def build_service(
    *,
    records: list[KeywordIndexedChunk],
    readable_object_ids: set[str],
) -> tuple[KeywordSearchService, InMemoryAuditLogger]:
    audit_logger = InMemoryAuditLogger()
    service = KeywordSearchService(
        index=InMemoryKeywordIndex(records=records),
        acl_authorizer=InMemoryAclAuthorizer(allowed_by_user={"user-demo": readable_object_ids}),
        audit_logger=audit_logger,
    )
    return service, audit_logger


def test_keyword_search_returns_authorized_candidates_without_text_or_snippets() -> None:
    service, audit_logger = build_service(
        records=[
            indexed_chunk(
                object_id="doc-1",
                chunk_id="chunk-doc-1",
                title="Visible policy",
                index_text="Authorized internal payroll policy body that must not be returned.",
            ),
            indexed_chunk(
                object_id="secret-1",
                chunk_id="chunk-secret-1",
                title="Restricted payroll note",
                index_text="PAYROLL_SECRET_123 is confidential and must never leak through search.",
                classification=DataClass.CONFIDENTIAL,
            ),
        ],
        readable_object_ids={"doc-1"},
    )

    response = service.search(
        query=KeywordSearchQuery(query="payroll policy", top_k=10),
        user_context=user_context(),
    )

    serialized_response = response.model_dump_json()
    audit_event = audit_logger.events[-1]
    assert [candidate.object_id for candidate in response.candidates] == ["doc-1"]
    assert all(candidate.access_checked for candidate in response.candidates)
    assert "Authorized internal payroll policy body" not in serialized_response
    assert "PAYROLL_SECRET_123" not in serialized_response
    assert "index_text" not in serialized_response
    assert "snippet" not in serialized_response
    assert audit_event.event_type == "search.keyword.query"
    assert audit_event.input_hash is not None
    assert "payroll policy" not in audit_event.model_dump_json()
    assert audit_event.source_object_ids == ["doc-1"]
    assert audit_event.metadata["candidate_count"] == 2
    assert audit_event.metadata["authorized_candidate_count"] == 1
    assert audit_event.metadata["authorized_candidate_refs"] == ["doc-1:v1:chunk-doc-1"]


def test_keyword_search_is_tenant_scoped_before_authorization() -> None:
    service, audit_logger = build_service(
        records=[
            indexed_chunk(
                object_id="doc-1",
                chunk_id="chunk-doc-1",
                title="Tenant document",
                index_text="shared search phrase",
            ),
            indexed_chunk(
                tenant_id="tenant-other",
                object_id="other-doc",
                chunk_id="chunk-other-doc",
                title="Other tenant document",
                index_text="shared search phrase",
            ),
        ],
        readable_object_ids={"doc-1", "other-doc"},
    )

    response = service.search(
        query=KeywordSearchQuery(query="shared search", top_k=10),
        user_context=user_context(tenant_id="tenant-demo"),
    )

    audit_event = audit_logger.events[-1]
    assert [candidate.object_id for candidate in response.candidates] == ["doc-1"]
    assert audit_event.metadata["candidate_count"] == 1
    assert audit_event.metadata["authorized_candidate_count"] == 1
    assert audit_event.source_object_ids == ["doc-1"]


def test_keyword_search_candidate_schema_carries_compliance_metadata() -> None:
    service, _audit_logger = build_service(
        records=[
            indexed_chunk(
                object_id="doc-1",
                chunk_id="chunk-doc-1",
                title="Compliance source",
                index_text="source citation policy",
            ),
        ],
        readable_object_ids={"doc-1"},
    )

    response = service.search(
        query=KeywordSearchQuery(query="citation", top_k=1),
        user_context=user_context(),
    )

    candidate = response.candidates[0]
    assert candidate.object_id == "doc-1"
    assert candidate.object_type == "document"
    assert candidate.version_id == "v1"
    assert candidate.chunk_id == "chunk-doc-1"
    assert candidate.classification == DataClass.INTERNAL
    assert candidate.retention_policy_id == "rp-standard"
    assert candidate.legal_hold_state == "none"
    assert candidate.acl_version == 1
    assert candidate.content_hash == "sha256:doc-1"
    assert candidate.access_checked is True
