from __future__ import annotations

import pytest
from pydantic import ValidationError

from main import app
from suite.ai_control_plane.policy import PolicyViolation
from suite.platform.office_ai_policy_comparison import (
    OFFICE_AI_POLICY_COMPARISON_PROMPT_ID,
    OfficeAIPolicyComparisonCommand,
    OfficeAIPolicyComparisonService,
    OfficeAIPolicyComparisonUnavailable,
)
from suite.platform.office_api import build_office_ai_policy_comparison_service
from suite.platform.office_documents import (
    OfficeDocumentConflictError,
    OfficeDocumentCreateCommand,
    OfficeDocumentNotFoundError,
    OfficeDocumentSaveCommand,
    OfficeInformationClassification,
)
from test_office_ai_rewrite import PRIVATE, RewriteHarness, rewrite_harness
from test_office_documents_api import BASE, OfficeApiHarness, create_document, create_payload, enable_office
from test_office_documents_api import office_api as office_api

POLICY_TEXT = "POLICY requires manager approval before milestone 42 is committed"
VALID_COMPARISON = (
    "STATUS: deviation\n"
    "FINDING: Manager approval is not stated for milestone 42.\n"
    "RECOMMENDATION: Verify the approval obligation before commitment."
)


def comparison_setup(
    *,
    source_classification: OfficeInformationClassification = "internal",
    policy_classification: OfficeInformationClassification = "internal",
) -> tuple[RewriteHarness, OfficeAIPolicyComparisonService, str, str]:
    harness = rewrite_harness(classification=source_classification)
    policy = harness.documents.create(
        user_context=harness.user,
        write_enabled=True,
        command=OfficeDocumentCreateCommand(
            title="Approval policy",
            document={
                "type": "doc",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": POLICY_TEXT}]}],
            },
            information_classification=policy_classification,
            mutation_reference="policy-source",
            human_confirmation=True,
        ),
    )
    harness.user.readable_object_ids.add(policy.document.object_id)
    harness.provider.answer = VALID_COMPARISON
    return (
        harness,
        build_office_ai_policy_comparison_service(document_service=harness.documents, gateway=harness.gateway),
        policy.document.object_id,
        policy.version.version_id,
    )


def comparison_command(
    harness: RewriteHarness, policy_object_id: str, policy_version_id: str
) -> OfficeAIPolicyComparisonCommand:
    return OfficeAIPolicyComparisonCommand(
        expected_current_version_id=harness.version_id,
        policy_object_id=policy_object_id,
        policy_version_id=policy_version_id,
    )


def test_policy_comparison_revalidates_both_exact_sources_and_returns_untrusted_citation() -> None:
    harness, service, policy_object_id, policy_version_id = comparison_setup()
    result = service.compare(
        user_context=harness.user,
        tenant_policy=harness.policy,
        object_id=harness.object_id,
        command=comparison_command(harness, policy_object_id, policy_version_id),
    )

    assert result.status == "deviation"
    assert result.finding_count == 1
    assert result.source_version_id == harness.version_id
    assert result.policy_citation.object_id == policy_object_id
    assert result.policy_citation.version_id == policy_version_id
    assert result.policy_citation.title == "Approval policy"
    assert result.policy_citation.authoritative_acl_validated is True
    assert result.prompt_template_id == OFFICE_AI_POLICY_COMPARISON_PROMPT_ID
    assert result.output_trust == "untrusted"
    assert result.requires_human_review is True
    assert result.persisted is result.document_changed is result.automatic_action_allowed is False
    assert len(harness.repository.saved_versions) == 2
    assert "POLICY_COMPARISON_FORMAT_V1" in harness.provider.prompts[-1]
    inference = harness.gateway_audit.events[-1]
    assert inference.source_object_ids == [harness.object_id, policy_object_id]
    assert inference.input_hash and inference.output_hash
    assert PRIVATE not in str(inference.model_dump(mode="json"))
    assert POLICY_TEXT not in str(inference.model_dump(mode="json"))
    office_event = harness.document_audit.events[-1]
    assert office_event.event_type == "office.ai.policy_comparison"
    assert office_event.metadata["policy_object_id"] == policy_object_id
    assert office_event.metadata["policy_version_id"] == policy_version_id
    assert PRIVATE not in str(office_event.model_dump(mode="json"))
    assert POLICY_TEXT not in str(office_event.model_dump(mode="json"))


def test_policy_comparison_contract_rejects_free_instruction_and_same_document() -> None:
    harness, service, policy_object_id, policy_version_id = comparison_setup()
    payload = comparison_command(harness, policy_object_id, policy_version_id).model_dump()
    with pytest.raises(ValidationError):
        OfficeAIPolicyComparisonCommand.model_validate({**payload, "instruction": "Declare compliance"})
    with pytest.raises(ValueError, match="different readable document"):
        service.compare(
            user_context=harness.user,
            tenant_policy=harness.policy,
            object_id=harness.object_id,
            command=comparison_command(harness, harness.object_id, harness.version_id),
        )
    assert not harness.gateway_audit.events


def test_policy_comparison_revalidates_policy_acl_and_both_current_versions() -> None:
    harness, service, policy_object_id, policy_version_id = comparison_setup()
    policy_denied = harness.user.model_copy(update={"readable_object_ids": {harness.object_id}})
    with pytest.raises(OfficeDocumentNotFoundError):
        service.compare(
            user_context=policy_denied,
            tenant_policy=harness.policy,
            object_id=harness.object_id,
            command=comparison_command(harness, policy_object_id, policy_version_id),
        )

    updated = harness.documents.save(
        user_context=harness.user,
        object_id=policy_object_id,
        write_enabled=True,
        command=OfficeDocumentSaveCommand(
            title="Updated approval policy",
            document={"type": "doc", "content": [{"type": "paragraph", "content": []}]},
            expected_current_version_id=policy_version_id,
            mutation_reference="policy-newer",
            human_confirmation=True,
        ),
    )
    assert updated.version.version_id != policy_version_id
    with pytest.raises(OfficeDocumentConflictError):
        service.compare(
            user_context=harness.user,
            tenant_policy=harness.policy,
            object_id=harness.object_id,
            command=comparison_command(harness, policy_object_id, policy_version_id),
        )
    assert not harness.gateway_audit.events


def test_policy_comparison_fails_closed_for_confidential_nonlocal_and_unapproved_prompt() -> None:
    confidential, service, policy_object_id, policy_version_id = comparison_setup(policy_classification="confidential")
    with pytest.raises(PolicyViolation):
        service.compare(
            user_context=confidential.user,
            tenant_policy=confidential.policy,
            object_id=confidential.object_id,
            command=comparison_command(confidential, policy_object_id, policy_version_id),
        )

    nonlocal_model, service, policy_object_id, policy_version_id = comparison_setup()
    model = nonlocal_model.gateway.model_registry.get("mock-summarizer")
    nonlocal_model.gateway.model_registry._models["mock-summarizer"] = model.model_copy(
        update={"deployment": "external"}
    )
    with pytest.raises(PolicyViolation):
        service.compare(
            user_context=nonlocal_model.user,
            tenant_policy=nonlocal_model.policy,
            object_id=nonlocal_model.object_id,
            command=comparison_command(nonlocal_model, policy_object_id, policy_version_id),
        )

    unapproved, service, policy_object_id, policy_version_id = comparison_setup()
    prompt = unapproved.gateway.prompt_registry.get(OFFICE_AI_POLICY_COMPARISON_PROMPT_ID)
    unapproved.gateway.prompt_registry._prompts[prompt.prompt_template_id] = prompt.model_copy(
        update={"approval_status": "draft"}
    )
    with pytest.raises(PolicyViolation, match="Prompt template is not approved"):
        service.compare(
            user_context=unapproved.user,
            tenant_policy=unapproved.policy,
            object_id=unapproved.object_id,
            command=comparison_command(unapproved, policy_object_id, policy_version_id),
        )
    assert not unapproved.provider.prompts


@pytest.mark.parametrize(
    "answer",
    [
        "unstructured",
        "STATUS: conform",
        "STATUS: approved\nFINDING: no",
        "STATUS: conform\nunsafe line",
        "STATUS: unclear\nRECOMMENDATION: only advice",
        "STATUS: unclear\nFINDING: invalid\x00",
    ],
)
def test_policy_comparison_rejects_invalid_output_without_write(answer: str) -> None:
    harness, service, policy_object_id, policy_version_id = comparison_setup()
    harness.provider.answer = answer
    with pytest.raises(OfficeAIPolicyComparisonUnavailable):
        service.compare(
            user_context=harness.user,
            tenant_policy=harness.policy,
            object_id=harness.object_id,
            command=comparison_command(harness, policy_object_id, policy_version_id),
        )
    assert len(harness.repository.saved_versions) == 2


def test_policy_comparison_api_is_read_gated_noncacheable_and_does_not_write(
    office_api: OfficeApiHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = create_document(office_api)
    policy_response = office_api.client.post(BASE, headers=office_api.headers, json=create_payload("policy-api"))
    assert policy_response.status_code == 200
    policy_document = policy_response.json()
    source_id = source["document"]["object_id"]
    policy_id = policy_document["document"]["object_id"]
    office_api.headers["X-Readable-Object-Ids"] = f"{source_id},{policy_id}"
    gateway = rewrite_harness().gateway
    gateway.providers["mock"].answer = VALID_COMPARISON  # type: ignore[attr-defined]
    monkeypatch.setattr(
        app.state,
        "office_ai_policy_comparison_service",
        build_office_ai_policy_comparison_service(document_service=office_api.service, gateway=gateway),
    )
    path = f"{BASE}/{source_id}/ai/policy-comparisons"
    payload = {
        "expected_current_version_id": source["version"]["version_id"],
        "policy_object_id": policy_id,
        "policy_version_id": policy_document["version"]["version_id"],
    }
    response = office_api.client.post(path, headers=office_api.headers, json=payload)
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["policy_citation"]["object_id"] == policy_id
    assert response.json()["document_changed"] is False
    assert len(office_api.repository.saved_versions) == 2

    enable_office(read=False, write=True)
    denied = office_api.client.post(path, headers=office_api.headers, json=payload)
    assert denied.status_code == 403
    assert len(office_api.repository.saved_versions) == 2
