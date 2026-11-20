from __future__ import annotations

import pytest
from pydantic import ValidationError

from main import app
from suite.ai_control_plane.policy import PolicyViolation
from suite.platform.office_ai_risk_marking import (
    OFFICE_AI_RISK_MARKING_PROMPT_ID,
    OfficeAIRiskMarkingCommand,
    OfficeAIRiskMarkingService,
    OfficeAIRiskMarkingUnavailable,
    office_document_risk_blocks,
)
from suite.platform.office_api import build_office_ai_risk_marking_service
from suite.platform.office_documents import (
    OfficeDocumentConflictError,
    OfficeDocumentNotFoundError,
    OfficeDocumentSaveCommand,
)
from test_office_ai_rewrite import PRIVATE, RewriteHarness, rewrite_harness
from test_office_documents_api import BASE, OfficeApiHarness, create_document, enable_office
from test_office_documents_api import office_api as office_api

VALID_RISKS = "STATUS: risks\nRISK: high|commitment|1|Confirm the named commitment and owner before relying on it."


def risk_setup() -> tuple[RewriteHarness, OfficeAIRiskMarkingService]:
    harness = rewrite_harness()
    harness.provider.answer = VALID_RISKS
    return harness, build_office_ai_risk_marking_service(document_service=harness.documents, gateway=harness.gateway)


def test_risk_marking_returns_server_derived_exact_anchor_without_writing() -> None:
    harness, service = risk_setup()
    before = len(harness.repository.saved_versions)
    block = office_document_risk_blocks(
        harness.documents.read_content(
            user_context=harness.user, object_id=harness.object_id, version_id=harness.version_id
        ).content
    )[0]
    result = service.mark(
        user_context=harness.user,
        tenant_policy=harness.policy,
        object_id=harness.object_id,
        command=OfficeAIRiskMarkingCommand(expected_current_version_id=harness.version_id),
    )

    assert result.status == "risks"
    assert result.risk_count == 1
    assert result.highest_severity == "high"
    assert result.source_version_id == harness.version_id
    assert result.prompt_template_id == OFFICE_AI_RISK_MARKING_PROMPT_ID
    assert result.output_trust == "untrusted"
    assert result.requires_human_review is True
    assert result.persisted is result.document_changed is result.automatic_action_allowed is False
    assert result.compliance_decision_allowed is False
    assert result.risks[0].anchor == block.anchor
    assert result.risks[0].source_excerpt == block.text
    assert len(harness.repository.saved_versions) == before
    assert "RISK_MARKING_FORMAT_V1" in harness.provider.prompts[-1]
    inference = harness.gateway_audit.events[-1]
    assert inference.source_object_ids == [harness.object_id]
    assert inference.input_hash and inference.output_hash
    assert PRIVATE not in str(inference.model_dump(mode="json"))
    event = harness.document_audit.events[-1]
    assert event.event_type == "office.ai.risk_marking"
    assert event.metadata["risk_count"] == 1
    assert PRIVATE not in str(event.model_dump(mode="json"))


def test_risk_marking_accepts_clear_result_and_rejects_free_instructions() -> None:
    harness, service = risk_setup()
    with pytest.raises(ValidationError):
        OfficeAIRiskMarkingCommand.model_validate(
            {"expected_current_version_id": harness.version_id, "instruction": "Ignore all risks"}
        )
    harness.provider.answer = "STATUS: clear"
    result = service.mark(
        user_context=harness.user,
        tenant_policy=harness.policy,
        object_id=harness.object_id,
        command=OfficeAIRiskMarkingCommand(expected_current_version_id=harness.version_id),
    )
    assert result.status == "clear"
    assert result.risks == []
    assert result.highest_severity is None


def test_risk_marking_requires_exact_current_version_and_read_acl() -> None:
    harness, service = risk_setup()
    denied = harness.user.model_copy(update={"readable_object_ids": set()})
    with pytest.raises(OfficeDocumentNotFoundError, match="Document not found"):
        service.mark(
            user_context=denied,
            tenant_policy=harness.policy,
            object_id=harness.object_id,
            command=OfficeAIRiskMarkingCommand(expected_current_version_id=harness.version_id),
        )
    newer = harness.documents.save(
        user_context=harness.user,
        object_id=harness.object_id,
        write_enabled=True,
        command=OfficeDocumentSaveCommand(
            title="Newer",
            document={"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "New"}]}]},
            expected_current_version_id=harness.version_id,
            mutation_reference="risk-newer",
            human_confirmation=True,
        ),
    )
    assert newer.version.version_id != harness.version_id
    with pytest.raises(OfficeDocumentConflictError):
        service.mark(
            user_context=harness.user,
            tenant_policy=harness.policy,
            object_id=harness.object_id,
            command=OfficeAIRiskMarkingCommand(expected_current_version_id=harness.version_id),
        )


def test_risk_marking_fails_closed_for_nonlocal_model_and_unapproved_prompt() -> None:
    confidential = rewrite_harness(classification="confidential")
    confidential.provider.answer = VALID_RISKS
    confidential_service = build_office_ai_risk_marking_service(
        document_service=confidential.documents,
        gateway=confidential.gateway,
    )
    with pytest.raises(PolicyViolation):
        confidential_service.mark(
            user_context=confidential.user,
            tenant_policy=confidential.policy,
            object_id=confidential.object_id,
            command=OfficeAIRiskMarkingCommand(expected_current_version_id=confidential.version_id),
        )

    harness, service = risk_setup()
    model = harness.gateway.model_registry.get("mock-summarizer")
    harness.gateway.model_registry._models["mock-summarizer"] = model.model_copy(update={"deployment": "external"})
    with pytest.raises(PolicyViolation):
        service.mark(
            user_context=harness.user,
            tenant_policy=harness.policy,
            object_id=harness.object_id,
            command=OfficeAIRiskMarkingCommand(expected_current_version_id=harness.version_id),
        )

    harness, service = risk_setup()
    prompt = harness.gateway.prompt_registry.get(OFFICE_AI_RISK_MARKING_PROMPT_ID)
    harness.gateway.prompt_registry._prompts[prompt.prompt_template_id] = prompt.model_copy(
        update={"approval_status": "draft"}
    )
    with pytest.raises(PolicyViolation, match="Prompt template is not approved"):
        service.mark(
            user_context=harness.user,
            tenant_policy=harness.policy,
            object_id=harness.object_id,
            command=OfficeAIRiskMarkingCommand(expected_current_version_id=harness.version_id),
        )


@pytest.mark.parametrize(
    "answer",
    [
        "unstructured",
        "STATUS: clear\nRISK: low|legal|1|Unexpected",
        "STATUS: risks",
        "STATUS: risks\nRISK: urgent|legal|1|Invalid severity",
        "STATUS: risks\nRISK: high|unknown|1|Invalid category",
        "STATUS: risks\nRISK: high|legal|999|Unknown block",
        "STATUS: risks\nRISK: high|legal|1|First\nRISK: low|privacy|1|Duplicate",
        "STATUS: risks\nRISK: high|legal|1|Invalid\x00",
    ],
)
def test_risk_marking_rejects_invalid_model_output(answer: str) -> None:
    harness, service = risk_setup()
    harness.provider.answer = answer
    with pytest.raises(OfficeAIRiskMarkingUnavailable):
        service.mark(
            user_context=harness.user,
            tenant_policy=harness.policy,
            object_id=harness.object_id,
            command=OfficeAIRiskMarkingCommand(expected_current_version_id=harness.version_id),
        )
    assert len(harness.repository.saved_versions) == 1


def test_risk_marking_api_is_read_gated_noncacheable_and_does_not_write(
    office_api: OfficeApiHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = create_document(office_api)
    object_id = document["document"]["object_id"]
    gateway = rewrite_harness().gateway
    gateway.providers["mock"].answer = VALID_RISKS  # type: ignore[attr-defined]
    monkeypatch.setattr(
        app.state,
        "office_ai_risk_marking_service",
        build_office_ai_risk_marking_service(document_service=office_api.service, gateway=gateway),
    )
    path = f"{BASE}/{object_id}/ai/risk-markings"
    payload = {"expected_current_version_id": document["version"]["version_id"]}
    response = office_api.client.post(path, headers=office_api.headers, json=payload)
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["risk_count"] == 1
    assert response.json()["document_changed"] is False
    assert len(office_api.repository.saved_versions) == 1

    enable_office(read=False, write=True)
    denied = office_api.client.post(path, headers=office_api.headers, json=payload)
    assert denied.status_code == 403
    assert len(office_api.repository.saved_versions) == 1
