import base64
import hmac
import json
from hashlib import sha256
from time import time
from typing import Any
from unittest.mock import Mock

import pytest

from main import app
from suite.platform.context import (
    DEFAULT_DEV_JWT_SECRET,
    DEFAULT_JWT_AUDIENCE,
    DEFAULT_JWT_ISSUER,
    HmacJwtVerifier,
    InMemoryPrincipalDirectory,
    JwtPrincipalResolver,
    PrincipalRecord,
    TenantMembership,
)
from suite.platform.office_document_repository import InMemoryOfficeDocumentRepository
from suite.platform.office_documents import OfficeDocumentConflictError, OfficeDocumentSaveCommand
from suite.platform.office_reviews import ReviewAnchor
from suite.platform.office_suggestions import SuggestionCreateCommand, replace_suggestion_text
from suite.storage.source_object_storage import SourceObjectStorageError
from test_office_documents_api import create_payload, enable_office
from test_office_documents_api import office_api as office_api
from test_office_suggestions import SuggestionHarness, decision_command, paragraph_text, text_document
from test_office_suggestions import suggestions as suggestions
from test_office_suggestions_api import SuggestionApiHarness
from test_office_suggestions_api import suggestion_api as suggestion_api


@pytest.mark.parametrize("operation", ("create", "save"))
def test_document_api_rejects_reserved_suggestion_reference_before_source_put(
    suggestion_api: SuggestionApiHarness, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    harness = suggestion_api.office
    source_write = Mock(side_effect=AssertionError("must not write source content"))
    monkeypatch.setattr(harness.service.source_repository, "add", source_write)
    payload = create_payload("office-suggestion-accept:forged")
    path = "/v1/office/documents"
    if operation == "save":
        path += f"/{suggestion_api.object_id}/versions"
        payload["expected_current_version_id"] = suggestion_api.version_id
    response = harness.client.post(path, headers=harness.headers, json=payload)
    assert response.status_code == 400
    assert response.json() == {"detail": "Document validation failed"}
    assert response.headers["Cache-Control"] == "no-store"
    source_write.assert_not_called()
    assert len(harness.repository.saved_versions) == 1


def test_suggestion_postcommit_response_preserves_anchor_alias_and_exact_retry(suggestions: SuggestionHarness) -> None:
    created = suggestions.create()
    assert created.model_dump(mode="json", by_alias=True)["suggestion"]["anchor"] == {"from": 5, "to": 9}
    accepted = suggestions.decide(created.suggestion.suggestion_id)
    assert accepted.model_dump(mode="json", by_alias=True)["suggestion"]["anchor"] == {"from": 5, "to": 9}
    assert accepted.document_result is not None
    replayed = suggestions.decide(created.suggestion.suggestion_id)
    assert replayed.replayed
    assert replayed.document_result is not None
    assert replayed.document_result.version.version_id == accepted.document_result.version.version_id
    assert replayed.document_result.content == accepted.document_result.content
    assert replayed.suggestion.anchor == accepted.suggestion.anchor


def test_suggestion_maximum_quote_and_replacement_unicode_fit_document_and_evidence(
    suggestions: SuggestionHarness,
) -> None:
    saved = suggestions.documents.save(
        user_context=suggestions.user,
        object_id=suggestions.object_id,
        write_enabled=True,
        command=OfficeDocumentSaveCommand(
            title="Unicode",
            document=text_document("😀" * 2000),
            expected_current_version_id=suggestions.version_id,
            mutation_reference="unicode-document",
            human_confirmation=True,
        ),
    )
    created = suggestions.service.mutate(
        user_context=suggestions.user,
        object_id=suggestions.object_id,
        write_enabled=True,
        command=SuggestionCreateCommand.model_validate(
            {
                "anchor_version_id": saved.version.version_id,
                "expected_current_version_id": saved.version.version_id,
                "anchor": {"from": 1, "to": 4001},
                "replacement_text": "🦊" * 4000,
                "mutation_reference": "unicode-suggestion",
                "human_confirmation": True,
            }
        ),
    )
    assert created.quote == "😀" * 2000
    accepted = suggestions.service.mutate(
        user_context=suggestions.user,
        object_id=suggestions.object_id,
        suggestion_id=created.suggestion.suggestion_id,
        write_enabled=True,
        command=decision_command("accept", saved.version.version_id),
    )
    assert accepted.document_result is not None
    assert paragraph_text(accepted.document_result.content) == "🦊" * 4000


def test_suggestion_deleting_last_text_preserves_empty_table_cell_and_other_cells() -> None:
    cell = {"type": "tableCell", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "cell"}]}]}
    document: dict[str, Any] = {
        "type": "doc",
        "content": [
            {"type": "table", "content": [{"type": "tableRow", "content": [cell, json.loads(json.dumps(cell))]}]}
        ],
    }
    result = replace_suggestion_text(document, ReviewAnchor.model_validate({"from": 4, "to": 8}), "")
    cells = result["content"][0]["content"][0]["content"]
    assert cells[0] == {"type": "tableCell", "content": [{"type": "paragraph", "content": []}]}
    assert cells[1] == cell
    assert document["content"][0]["content"][0]["content"][0] == cell


def test_suggestion_memory_adapter_rolls_back_when_second_source_write_fails(
    suggestions: SuggestionHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = suggestions.create()
    original = suggestions.sources.add
    calls = 0

    def fail(record: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise SourceObjectStorageError("Synthetic failure")
        return original(record)

    monkeypatch.setattr(suggestions.sources, "add", fail)
    with pytest.raises(SourceObjectStorageError):
        suggestions.decide(created.suggestion.suggestion_id)
    latest = suggestions.documents.read_content(user_context=suggestions.user, object_id=suggestions.object_id)
    assert latest.version.version_id == suggestions.version_id
    detail = suggestions.service.detail(
        user_context=suggestions.user,
        object_id=suggestions.object_id,
        suggestion_id=created.suggestion.suggestion_id,
    )
    assert detail.suggestion.status == "open"
    monkeypatch.setattr(suggestions.sources, "add", original)
    assert suggestions.decide(created.suggestion.suggestion_id).suggestion.status == "accepted"


def test_suggestion_another_author_cannot_replay_an_accepted_decision(suggestions: SuggestionHarness) -> None:
    created = suggestions.create()
    suggestions.decide(created.suggestion.suggestion_id)
    other = suggestions.user.model_copy(update={"user_id": "another-writer"})
    repository = suggestions.documents.repository
    assert isinstance(repository, InMemoryOfficeDocumentRepository)
    repository.grants[(other.tenant_id, suggestions.object_id, other.user_id)] = "write"
    with pytest.raises(OfficeDocumentConflictError):
        suggestions.service.mutate(
            user_context=other,
            object_id=suggestions.object_id,
            suggestion_id=created.suggestion.suggestion_id,
            command=decision_command("accept", suggestions.version_id),
            write_enabled=True,
        )


def test_suggestion_feature_disabled_after_prepare_denies_decision_before_repository(
    suggestion_api: SuggestionApiHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = suggestion_api.create()
    enable_office(write=False)
    commit = Mock(side_effect=AssertionError("must not commit"))
    monkeypatch.setattr(suggestion_api.service.repository, "commit", commit)
    response = suggestion_api.office.client.post(
        f"{suggestion_api.base}/{created['suggestion']['suggestion_id']}/decisions",
        headers=suggestion_api.office.headers,
        json=decision_command("accept", suggestion_api.version_id).model_dump(),
    )
    assert response.status_code == 403 and response.headers["Cache-Control"] == "no-store"
    commit.assert_not_called()


def test_suggestion_jwt_ignores_forged_read_grants_even_with_repository_write_permission(
    suggestion_api: SuggestionApiHarness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = suggestion_api.create()
    principal = PrincipalRecord(
        issuer=DEFAULT_JWT_ISSUER,
        subject="suggestion-subject",
        user_id="suggestion-reader",
        memberships=[TenantMembership(tenant_id="tenant-demo", role_ids={"office-reader"})],
    )
    resolver = JwtPrincipalResolver(
        verifier=HmacJwtVerifier(
            issuer=DEFAULT_JWT_ISSUER, audience=DEFAULT_JWT_AUDIENCE, secret=DEFAULT_DEV_JWT_SECRET
        ),
        directory=InMemoryPrincipalDirectory(principals=[principal], object_acls=[]),
    )
    monkeypatch.setattr(app.state, "principal_resolver", resolver)
    monkeypatch.setenv("SUITE_AUTH_MODE", "jwt")
    payload = {
        "iss": DEFAULT_JWT_ISSUER,
        "aud": DEFAULT_JWT_AUDIENCE,
        "sub": principal.subject,
        "tenant_id": "tenant-demo",
        "iat": int(time()) - 1,
        "exp": int(time()) + 120,
        "roles": ["tenant-admin"],
        "readable_object_ids": [suggestion_api.object_id],
    }
    segments = [
        base64.urlsafe_b64encode(json.dumps(part).encode()).decode().rstrip("=")
        for part in ({"alg": "HS256", "typ": "JWT"}, payload)
    ]
    signing_input = ".".join(segments)
    signature = hmac.new(DEFAULT_DEV_JWT_SECRET.encode(), signing_input.encode(), sha256).digest()
    token = f"{signing_input}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"
    headers = {**suggestion_api.office.headers, "Authorization": f"Bearer {token}", "X-Role-Ids": "tenant-admin"}
    suggestion_api.office.repository.grants[("tenant-demo", suggestion_api.object_id, principal.user_id)] = "admin"
    read = Mock(wraps=suggestion_api.office.service.source_repository.get)
    monkeypatch.setattr(suggestion_api.office.service.source_repository, "get", read)
    response = suggestion_api.office.client.get(
        f"{suggestion_api.base}/{created['suggestion']['suggestion_id']}",
        headers=headers,
    )
    assert response.status_code == 404 and response.json() == {"detail": "Document not found"}
    assert (
        suggestion_api.office.client.post(
            suggestion_api.base, headers=headers, json=suggestion_api.payload()
        ).status_code
        == 404
    )
    read.assert_not_called()
