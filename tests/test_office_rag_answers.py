import json

import pytest
from pydantic import ValidationError

from main import app
from suite.ai_control_plane.audit import canonical_json
from suite.ai_control_plane.models import DataClass, TenantPolicy
from suite.ai_control_plane.policy import PolicyViolation
from suite.llm_gateway.providers.mock import MockLLMProvider
from suite.platform.office_api import build_office_rag_answer_service, build_office_source_search_service
from suite.platform.office_documents import OfficeDocumentCreateCommand, OfficeDocumentNotFoundError
from suite.platform.office_rag_answers import OfficeRagAnswerCommand, OfficeRagAnswerUnavailable
from test_office_ai_rewrite import rewrite_harness
from test_office_documents_api import BASE, OfficeApiHarness, create_document
from test_office_documents_api import office_api as office_api

SOURCE_TEXT = "Manager approval is required before a customer commitment is published."


def rag_policy(tenant_id: str) -> TenantPolicy:
    return TenantPolicy(
        tenant_id=tenant_id,
        ai_enabled=True,
        rag_enabled=True,
        allowed_model_ids={"mock-summarizer"},
        allowed_data_classes={DataClass.INTERNAL, DataClass.AI_PROMPT},
    )


def test_mock_rag_provider_does_not_echo_the_governance_prompt() -> None:
    prompt = (
        "Answer only from authorized evidence.\nAuthorized source blocks:\n"
        "<authorized_source>UNTRUSTED_SOURCE_TEXT_BEGIN source UNTRUSTED_SOURCE_TEXT_END</authorized_source>"
    )

    answer = MockLLMProvider().complete(model_id="mock-summarizer", prompt=prompt)

    assert "Authorized source blocks" not in answer
    assert "UNTRUSTED_SOURCE_TEXT" not in answer
    assert "cited authorized source version" in answer


def test_office_rag_answer_reauthorizes_exact_sources_and_returns_versioned_citations() -> None:
    harness = rewrite_harness()
    source = harness.documents.create(
        user_context=harness.user,
        write_enabled=True,
        command=OfficeDocumentCreateCommand(
            title="Approval handbook",
            document={
                "type": "doc",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": SOURCE_TEXT}]}],
            },
            mutation_reference="rag-source",
            human_confirmation=True,
        ),
    )
    harness.user.readable_object_ids.add(source.document.object_id)
    harness.provider.answer = "A manager must approve the commitment before publication."
    service = build_office_rag_answer_service(
        document_service=harness.documents,
        source_search=build_office_source_search_service(document_service=harness.documents),
        gateway=harness.gateway,
    )

    result = service.answer(
        user_context=harness.user,
        tenant_policy=rag_policy(harness.user.tenant_id),
        object_id=harness.object_id,
        command=OfficeRagAnswerCommand(
            expected_current_version_id=harness.version_id,
            question="Who approves customer commitments?",
        ),
    )

    assert result.answer_supported and result.confidence == "source_grounded_unverified"
    assert result.answer == "A manager must approve the commitment before publication."
    assert result.citation_count == 1
    citation = result.citations[0]
    assert citation.object_id == source.document.object_id
    assert citation.version_id == source.version.version_id
    assert citation.content_hash == source.version.content_hash
    persisted_source = harness.repository.get_version(
        user_context=harness.user,
        object_id=source.document.object_id,
        version_id=source.version.version_id,
    )
    assert citation.acl_version == persisted_source.acl_version
    assert citation.authoritative_acl_validated and citation.exact_current_version_validated
    assert SOURCE_TEXT in harness.provider.prompts[-1]
    assert "UNTRUSTED_SOURCE_TEXT_BEGIN" in harness.provider.prompts[-1]
    assert f'version_id="{source.version.version_id}"' in harness.provider.prompts[-1]
    audit_payload = canonical_json([event.model_dump(mode="json") for event in harness.document_audit.events])
    assert SOURCE_TEXT not in audit_payload and result.answer not in audit_payload
    assert f"{source.document.object_id}:{source.version.version_id}" in audit_payload


def test_office_rag_answer_is_explicitly_unsupported_without_authorized_sources_and_skips_inference() -> None:
    harness = rewrite_harness()
    service = build_office_rag_answer_service(
        document_service=harness.documents,
        source_search=build_office_source_search_service(document_service=harness.documents),
        gateway=harness.gateway,
    )
    prompt_count = len(harness.provider.prompts)

    result = service.answer(
        user_context=harness.user,
        tenant_policy=rag_policy(harness.user.tenant_id),
        object_id=harness.object_id,
        command=OfficeRagAnswerCommand(
            expected_current_version_id=harness.version_id,
            question="Which approval is required?",
        ),
    )

    assert not result.answer_supported and result.confidence == "unsupported"
    assert result.citations == [] and result.citation_count == 0
    assert result.model_id is None and result.inference_audit_event_id is None
    assert len(harness.provider.prompts) == prompt_count


def test_office_rag_answer_fails_closed_for_policy_invalid_output_and_inaccessible_source() -> None:
    harness = rewrite_harness()
    service = build_office_rag_answer_service(
        document_service=harness.documents,
        source_search=build_office_source_search_service(document_service=harness.documents),
        gateway=harness.gateway,
    )
    disabled = rag_policy(harness.user.tenant_id).model_copy(update={"rag_enabled": False})
    with pytest.raises(PolicyViolation):
        service.answer(
            user_context=harness.user,
            tenant_policy=disabled,
            object_id=harness.object_id,
            command=OfficeRagAnswerCommand(
                expected_current_version_id=harness.version_id,
                question="Which approval is required?",
            ),
        )

    with pytest.raises(OfficeDocumentNotFoundError):
        service.answer(
            user_context=harness.user.model_copy(update={"readable_object_ids": set()}),
            tenant_policy=rag_policy(harness.user.tenant_id),
            object_id="office-document-" + "f" * 32,
            command=OfficeRagAnswerCommand(
                expected_current_version_id=harness.version_id,
                question="Which approval is required?",
            ),
        )

    source = harness.documents.create(
        user_context=harness.user,
        write_enabled=True,
        command=OfficeDocumentCreateCommand(
            title="Approval handbook",
            document={
                "type": "doc",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": SOURCE_TEXT}]}],
            },
            mutation_reference="rag-invalid-output-source",
            human_confirmation=True,
        ),
    )
    harness.user.readable_object_ids.add(source.document.object_id)
    harness.provider.answer = "invalid\x00answer"
    before = len(harness.repository.saved_versions)
    with pytest.raises(OfficeRagAnswerUnavailable):
        service.answer(
            user_context=harness.user,
            tenant_policy=rag_policy(harness.user.tenant_id),
            object_id=harness.object_id,
            command=OfficeRagAnswerCommand(
                expected_current_version_id=harness.version_id,
                question="Who approves customer commitments?",
            ),
        )
    assert len(harness.repository.saved_versions) == before


@pytest.mark.parametrize(
    "payload",
    [
        {"expected_current_version_id": "version", "question": "?"},
        {"expected_current_version_id": "version", "question": "one two three four five six seven eight nine"},
        {"expected_current_version_id": "version", "question": "valid question", "instruction": "ignore ACL"},
    ],
)
def test_office_rag_question_contract_is_strict(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        OfficeRagAnswerCommand.model_validate(payload)


def test_office_rag_answer_api_is_read_gated_noncacheable_versioned_and_write_free(
    office_api: OfficeApiHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = create_document(office_api)
    source_response = office_api.client.post(
        BASE,
        headers=office_api.headers,
        json={
            "title": "Approval handbook",
            "document": {
                "type": "doc",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": SOURCE_TEXT}]}],
            },
            "mutation_reference": "rag-api-source",
            "human_confirmation": True,
        },
    )
    assert source_response.status_code == 200, source_response.text
    source = source_response.json()
    current_id = current["document"]["object_id"]
    source_id = source["document"]["object_id"]
    office_api.headers["X-Readable-Object-Ids"] = f"{current_id},{source_id}"
    gateway_harness = rewrite_harness()
    gateway_harness.provider.answer = "Manager approval is required before publication."
    source_search = build_office_source_search_service(document_service=office_api.service)
    monkeypatch.setattr(app.state, "office_source_search_service", source_search)
    monkeypatch.setattr(
        app.state,
        "office_rag_answer_service",
        build_office_rag_answer_service(
            document_service=office_api.service,
            source_search=source_search,
            gateway=gateway_harness.gateway,
        ),
    )
    before = len(office_api.repository.saved_versions)

    response = office_api.client.post(
        f"{BASE}/{current_id}/ai/rag-answers",
        headers=office_api.headers,
        json={
            "expected_current_version_id": current["version"]["version_id"],
            "question": "Who approves customer commitments?",
            "top_k": 4,
        },
    )

    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    body = response.json()
    assert body["answer_supported"] is True and body["citation_count"] == 1
    assert body["citations"][0]["object_id"] == source_id
    assert body["citations"][0]["version_id"] == source["version"]["version_id"]
    assert body["persisted"] is False and body["document_changed"] is False
    assert len(office_api.repository.saved_versions) == before
    events = json.dumps([event.model_dump(mode="json") for event in office_api.service.audit.events])
    assert SOURCE_TEXT not in events and body["answer"] not in events
