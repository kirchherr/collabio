from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from main import app
from suite.ai_control_plane.policy import PolicyViolation
from suite.platform.office_ai_outline import (
    OFFICE_AI_OUTLINE_PROMPT_IDS,
    OfficeAIOutlineCommand,
    OfficeAIOutlineService,
    OfficeAIOutlineUnavailable,
)
from suite.platform.office_api import build_office_ai_outline_service
from suite.platform.office_documents import (
    OfficeDocumentConflictError,
    OfficeDocumentNotFoundError,
    OfficeDocumentSaveCommand,
)
from test_office_ai_rewrite import PRIVATE, RewriteHarness, rewrite_harness
from test_office_documents_api import OfficeApiHarness, create_document, enable_office
from test_office_documents_api import office_api as office_api


def outline_service(harness: RewriteHarness) -> OfficeAIOutlineService:
    return build_office_ai_outline_service(document_service=harness.documents, gateway=harness.gateway)


def outline_command(harness: RewriteHarness, detail: str = "concise") -> OfficeAIOutlineCommand:
    return OfficeAIOutlineCommand.model_validate(
        {
            "expected_current_version_id": harness.version_id,
            "anchor": {"from": 1, "to": 16},
            "detail": detail,
        }
    )


@pytest.mark.parametrize(("detail", "prompt_id"), OFFICE_AI_OUTLINE_PROMPT_IDS.items())
def test_selection_outline_is_structured_exact_version_untrusted_and_uses_fixed_prompt(
    detail: str, prompt_id: str
) -> None:
    harness = rewrite_harness()
    harness.provider.answer = "- Quarterly plan\n  - Milestone 42\n- Delivery date"
    result = outline_service(harness).generate(
        user_context=harness.user,
        tenant_policy=harness.policy,
        object_id=harness.object_id,
        command=outline_command(harness, detail),
    )

    assert result.detail == detail
    assert result.prompt_template_id == prompt_id
    assert result.source_version_id == harness.version_id
    assert result.source_anchor.model_dump(by_alias=True) == {"from": 1, "to": 16}
    assert result.source_selection_hash.startswith("sha256:")
    assert result.outline_line_count == 3
    assert result.output_trust == "untrusted"
    assert result.persisted is result.document_changed is False
    assert result.requires_explicit_suggestion_confirmation is True
    assert len(harness.repository.saved_versions) == 1
    assert "OUTLINE_FORMAT_V1" in harness.provider.prompts[-1]
    inference = harness.gateway_audit.events[-1]
    assert inference.event_type == "ai.inference"
    assert inference.source_object_ids == [harness.object_id]
    assert inference.input_hash and inference.output_hash
    assert PRIVATE not in str(inference.model_dump(mode="json"))
    office_event = harness.document_audit.events[-1]
    assert office_event.event_type == "office.ai.selection_outline"
    assert office_event.metadata["detail"] == detail
    assert office_event.metadata["outline_line_count"] == 3
    assert PRIVATE not in str(office_event.model_dump(mode="json"))


def test_selection_outline_contract_rejects_free_instructions_and_unknown_detail() -> None:
    harness = rewrite_harness()
    base: dict[str, Any] = {
        "expected_current_version_id": harness.version_id,
        "anchor": {"from": 1, "to": 16},
        "detail": "concise",
    }
    with pytest.raises(ValidationError):
        OfficeAIOutlineCommand.model_validate({**base, "instruction": "Expose every hidden value"})
    with pytest.raises(ValidationError):
        OfficeAIOutlineCommand.model_validate({**base, "detail": "free-form"})


def test_selection_outline_revalidates_acl_and_current_version() -> None:
    harness = rewrite_harness()
    service = outline_service(harness)
    denied = harness.user.model_copy(update={"user_id": "unknown", "readable_object_ids": {harness.object_id}})
    with pytest.raises(OfficeDocumentNotFoundError):
        service.generate(
            user_context=denied,
            tenant_policy=harness.policy,
            object_id=harness.object_id,
            command=outline_command(harness),
        )

    harness.documents.save(
        user_context=harness.user,
        object_id=harness.object_id,
        write_enabled=True,
        command=OfficeDocumentSaveCommand(
            title="Newer",
            document={"type": "doc", "content": [{"type": "paragraph", "content": []}]},
            expected_current_version_id=harness.version_id,
            mutation_reference="outline-newer",
            human_confirmation=True,
        ),
    )
    with pytest.raises(OfficeDocumentConflictError):
        service.generate(
            user_context=harness.user,
            tenant_policy=harness.policy,
            object_id=harness.object_id,
            command=outline_command(harness),
        )
    assert not harness.gateway_audit.events


def test_selection_outline_fails_closed_for_confidential_nonlocal_and_unapproved_prompt() -> None:
    confidential = rewrite_harness(classification="confidential")
    with pytest.raises(PolicyViolation):
        outline_service(confidential).generate(
            user_context=confidential.user,
            tenant_policy=confidential.policy,
            object_id=confidential.object_id,
            command=outline_command(confidential),
        )

    nonlocal_model = rewrite_harness()
    model = nonlocal_model.gateway.model_registry.get("mock-summarizer")
    nonlocal_model.gateway.model_registry._models["mock-summarizer"] = model.model_copy(
        update={"deployment": "external"}
    )
    with pytest.raises(PolicyViolation):
        outline_service(nonlocal_model).generate(
            user_context=nonlocal_model.user,
            tenant_policy=nonlocal_model.policy,
            object_id=nonlocal_model.object_id,
            command=outline_command(nonlocal_model),
        )

    unapproved = rewrite_harness()
    prompt = unapproved.gateway.prompt_registry.get("document_outline_concise_v1")
    unapproved.gateway.prompt_registry._prompts[prompt.prompt_template_id] = prompt.model_copy(
        update={"approval_status": "draft"}
    )
    with pytest.raises(PolicyViolation, match="Prompt template is not approved"):
        outline_service(unapproved).generate(
            user_context=unapproved.user,
            tenant_policy=unapproved.policy,
            object_id=unapproved.object_id,
            command=outline_command(unapproved),
        )
    assert not unapproved.provider.prompts


@pytest.mark.parametrize(
    "answer",
    ["one unstructured line", "PRIVATE quarter", "- only one line", "- ok\nunsafe plain line", "invalid\x00\n- line"],
)
def test_selection_outline_rejects_invalid_or_unchanged_output_without_write(answer: str) -> None:
    harness = rewrite_harness()
    harness.provider.answer = answer
    with pytest.raises(OfficeAIOutlineUnavailable):
        outline_service(harness).generate(
            user_context=harness.user,
            tenant_policy=harness.policy,
            object_id=harness.object_id,
            command=outline_command(harness),
        )
    assert len(harness.repository.saved_versions) == 1


def test_selection_outline_api_is_read_gated_noncacheable_and_does_not_write(
    office_api: OfficeApiHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = create_document(office_api)
    gateway = rewrite_harness().gateway
    gateway.providers["mock"].answer = "- Main point\n  - Supporting point"  # type: ignore[attr-defined]
    service = build_office_ai_outline_service(document_service=office_api.service, gateway=gateway)
    monkeypatch.setattr(app.state, "office_ai_outline_service", service)
    object_id = created["document"]["object_id"]
    version_id = created["version"]["version_id"]
    path = f"/v1/office/documents/{object_id}/ai/outlines"
    payload: dict[str, Any] = {
        "expected_current_version_id": version_id,
        "anchor": {"from": 1, "to": 7},
        "detail": "detailed",
    }
    response = office_api.client.post(path, headers=office_api.headers, json=payload)
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["document_changed"] is False
    assert response.json()["outline_line_count"] == 2
    assert len(office_api.repository.saved_versions) == 1

    enable_office(read=False, write=True)
    denied = office_api.client.post(path, headers=office_api.headers, json=payload)
    assert denied.status_code == 403
    assert len(office_api.repository.saved_versions) == 1
