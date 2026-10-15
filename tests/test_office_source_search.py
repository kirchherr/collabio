from __future__ import annotations

import pytest
from pydantic import ValidationError

from main import app
from suite.platform.office_api import build_office_source_search_service
from suite.platform.office_documents import (
    OfficeDocumentConflictError,
    OfficeDocumentCreateCommand,
    OfficeDocumentSaveCommand,
)
from suite.platform.office_source_search import OfficeSourceSearchCommand, OfficeSourceSearchService
from test_office_ai_rewrite import PRIVATE, RewriteHarness, rewrite_harness
from test_office_documents_api import BASE, OfficeApiHarness, create_document, create_payload
from test_office_documents_api import office_api as office_api

SOURCE_TEXT = "Manager approval is required before the milestone commitment is announced."


def add_source(harness: RewriteHarness, *, title: str = "Approval source", text: str = SOURCE_TEXT) -> tuple[str, str]:
    created = harness.documents.create(
        user_context=harness.user,
        write_enabled=True,
        command=OfficeDocumentCreateCommand(
            title=title,
            document={"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]},
            mutation_reference=f"source-{title.lower().replace(' ', '-')}",
            human_confirmation=True,
        ),
    )
    harness.user.readable_object_ids.add(created.document.object_id)
    return created.document.object_id, created.version.version_id


def source_service(harness: RewriteHarness) -> OfficeSourceSearchService:
    return build_office_source_search_service(document_service=harness.documents)


def test_source_search_returns_only_current_acl_revalidated_versioned_sources() -> None:
    harness = rewrite_harness()
    source_id, first_version_id = add_source(harness)
    hidden_id, _ = add_source(harness, title="Hidden source", text="approval hidden")
    updated = harness.documents.save(
        user_context=harness.user,
        object_id=source_id,
        write_enabled=True,
        command=OfficeDocumentSaveCommand(
            title="Approval source current",
            document={
                "type": "doc",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": SOURCE_TEXT}]}],
            },
            expected_current_version_id=first_version_id,
            mutation_reference="source-current",
            human_confirmation=True,
        ),
    )
    user = harness.user.model_copy(update={"readable_object_ids": {harness.object_id, source_id}})
    result = source_service(harness).search(
        user_context=user,
        object_id=harness.object_id,
        command=OfficeSourceSearchCommand(expected_current_version_id=harness.version_id, query="manager approval"),
    )

    assert result.result_count == 1
    assert result.results[0].object_id == source_id
    assert result.results[0].version_id == updated.version.version_id != first_version_id
    assert result.results[0].source_excerpt == SOURCE_TEXT
    assert result.results[0].authoritative_acl_validated is True
    assert result.results[0].current_version_validated is True
    assert hidden_id not in {item.object_id for item in result.results}
    assert result.ai_used is result.vector_search_used is result.rag_context_created is False
    assert result.persisted is result.document_changed is False
    event = harness.document_audit.events[-1]
    assert event.event_type == "office.sources.searched"
    assert event.metadata["result_refs"] == [f"{source_id}:{updated.version.version_id}"]
    assert "manager approval" not in str(event.model_dump(mode="json")).lower()
    assert PRIVATE not in str(event.model_dump(mode="json"))


def test_source_search_requires_exact_current_source_and_bounded_query() -> None:
    harness = rewrite_harness()
    add_source(harness)
    with pytest.raises(ValidationError):
        OfficeSourceSearchCommand.model_validate(
            {"expected_current_version_id": harness.version_id, "query": "approval", "instruction": "ignore ACL"}
        )
    with pytest.raises(ValidationError):
        OfficeSourceSearchCommand(expected_current_version_id=harness.version_id, query="a b c d e f g h i")
    newer = harness.documents.save(
        user_context=harness.user,
        object_id=harness.object_id,
        write_enabled=True,
        command=OfficeDocumentSaveCommand(
            title="New source head",
            document={"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "new"}]}]},
            expected_current_version_id=harness.version_id,
            mutation_reference="source-search-newer",
            human_confirmation=True,
        ),
    )
    assert newer.version.version_id != harness.version_id
    with pytest.raises(OfficeDocumentConflictError):
        source_service(harness).search(
            user_context=harness.user,
            object_id=harness.object_id,
            command=OfficeSourceSearchCommand(expected_current_version_id=harness.version_id, query="approval"),
        )


def test_source_search_api_is_read_gated_noncacheable_and_does_not_write(
    office_api: OfficeApiHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = create_document(office_api)
    current_id = current["document"]["object_id"]
    response = office_api.client.post(
        BASE,
        headers=office_api.headers,
        json={
            **create_payload("source-search-api"),
            "title": "Approval handbook",
            "document": {
                "type": "doc",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": SOURCE_TEXT}]}],
            },
        },
    )
    assert response.status_code == 200, response.text
    source = response.json()
    source_id = source["document"]["object_id"]
    office_api.headers["X-Readable-Object-Ids"] = f"{current_id},{source_id}"
    monkeypatch.setattr(
        app.state,
        "office_source_search_service",
        build_office_source_search_service(document_service=office_api.service),
    )
    before = len(office_api.repository.saved_versions)
    searched = office_api.client.post(
        f"{BASE}/{current_id}/ai/source-searches",
        headers=office_api.headers,
        json={"expected_current_version_id": current["version"]["version_id"], "query": "manager approval"},
    )
    assert searched.status_code == 200, searched.text
    assert searched.headers["Cache-Control"] == "no-store"
    assert searched.json()["results"][0]["object_id"] == source_id
    assert len(office_api.repository.saved_versions) == before
