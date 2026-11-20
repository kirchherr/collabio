from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from main import app
from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import DataClass, TenantPolicy, UserContext
from suite.ai_control_plane.policy import PolicyEngine, PolicyViolation
from suite.ai_control_plane.registries import (
    InMemoryModelRegistry,
    InMemoryPromptRegistry,
    InMemoryToolPermissionRegistry,
)
from suite.llm_gateway.gateway import LocalLLMGateway
from suite.llm_gateway.providers.mock import MockLLMProvider
from suite.platform.office_ai_summary import (
    OfficeAISummaryCommand,
    OfficeAISummaryService,
    OfficeAISummaryUnavailable,
)
from suite.platform.office_api import build_office_ai_summary_service
from suite.platform.office_document_repository import InMemoryOfficeDocumentRepository
from suite.platform.office_documents import (
    OfficeDocumentConflictError,
    OfficeDocumentCreateCommand,
    OfficeDocumentNotFoundError,
    OfficeDocumentSaveCommand,
    OfficeDocumentService,
    OfficeInformationClassification,
)
from suite.storage.source_objects import InMemorySourceObjectRepository
from test_office_documents_api import OfficeApiHarness, create_document, enable_office
from test_office_documents_api import office_api as office_api

PRIVATE = "PRIVATE quarterly plan with milestones and delivery dates"


@dataclass
class SummaryHarness:
    service: OfficeAISummaryService
    documents: OfficeDocumentService
    repository: InMemoryOfficeDocumentRepository
    gateway_audit: InMemoryAuditLogger
    document_audit: InMemoryAuditLogger
    user: UserContext
    policy: TenantPolicy
    object_id: str
    version_id: str

    def command(self) -> OfficeAISummaryCommand:
        return OfficeAISummaryCommand.model_validate(
            {"expected_current_version_id": self.version_id, "anchor": {"from": 1, "to": 16}}
        )


def summary_harness(*, classification: OfficeInformationClassification = "internal") -> SummaryHarness:
    sources = InMemorySourceObjectRepository()
    document_audit = InMemoryAuditLogger()
    repository = InMemoryOfficeDocumentRepository(source_repository=sources)
    documents = OfficeDocumentService(
        repository=repository,
        source_repository=sources,
        audit=document_audit,
    )
    user = UserContext(tenant_id="tenant-summary", user_id="editor", role_ids={"office-editor"})
    saved = documents.create(
        user_context=user,
        write_enabled=True,
        command=OfficeDocumentCreateCommand(
            title="Summary source",
            document={
                "type": "doc",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": PRIVATE}]}],
            },
            information_classification=classification,
            mutation_reference="summary-source",
            human_confirmation=True,
        ),
    )
    user.readable_object_ids.add(saved.document.object_id)
    models = InMemoryModelRegistry.default()
    gateway_audit = InMemoryAuditLogger()
    gateway = LocalLLMGateway(
        providers={"mock": MockLLMProvider()},
        model_registry=models,
        prompt_registry=InMemoryPromptRegistry.default(),
        policy_engine=PolicyEngine(
            model_registry=models, tool_permission_registry=InMemoryToolPermissionRegistry.default()
        ),
        audit_logger=gateway_audit,
    )
    return SummaryHarness(
        service=build_office_ai_summary_service(document_service=documents, gateway=gateway),
        documents=documents,
        repository=repository,
        gateway_audit=gateway_audit,
        document_audit=document_audit,
        user=user,
        policy=TenantPolicy(
            tenant_id=user.tenant_id,
            ai_enabled=True,
            allowed_model_ids={"mock-summarizer"},
            allowed_data_classes={DataClass.INTERNAL},
        ),
        object_id=saved.document.object_id,
        version_id=saved.version.version_id,
    )


def test_selection_summary_is_exact_version_untrusted_and_never_persisted() -> None:
    harness = summary_harness()
    result = harness.service.summarize(
        user_context=harness.user,
        tenant_policy=harness.policy,
        object_id=harness.object_id,
        command=harness.command(),
    )

    assert result.source_version_id == harness.version_id
    assert result.source_anchor.model_dump(by_alias=True) == {"from": 1, "to": 16}
    assert result.source_selection_hash.startswith("sha256:")
    assert result.output_trust == "untrusted"
    assert result.persisted is result.document_changed is False
    assert result.requires_explicit_suggestion_confirmation is True
    assert len(harness.repository.saved_versions) == 1
    inference = harness.gateway_audit.events[-1]
    assert inference.event_type == "ai.inference"
    assert inference.source_object_ids == [harness.object_id]
    assert inference.input_hash and inference.output_hash
    assert PRIVATE not in str(inference.model_dump(mode="json"))
    office_event = harness.document_audit.events[-1]
    assert office_event.event_type == "office.ai.selection_summary"
    assert PRIVATE not in str(office_event.model_dump(mode="json"))


def test_selection_summary_revalidates_acl_and_current_version() -> None:
    harness = summary_harness()
    denied = harness.user.model_copy(update={"user_id": "unknown", "readable_object_ids": {harness.object_id}})
    with pytest.raises(OfficeDocumentNotFoundError):
        harness.service.summarize(
            user_context=denied,
            tenant_policy=harness.policy,
            object_id=harness.object_id,
            command=harness.command(),
        )

    harness.documents.save(
        user_context=harness.user,
        object_id=harness.object_id,
        write_enabled=True,
        command=OfficeDocumentSaveCommand(
            title="Newer",
            document={"type": "doc", "content": [{"type": "paragraph", "content": []}]},
            expected_current_version_id=harness.version_id,
            mutation_reference="newer",
            human_confirmation=True,
        ),
    )
    with pytest.raises(OfficeDocumentConflictError):
        harness.service.summarize(
            user_context=harness.user,
            tenant_policy=harness.policy,
            object_id=harness.object_id,
            command=harness.command(),
        )
    assert not harness.gateway_audit.events


def test_selection_summary_fails_closed_for_confidential_data_and_nonlocal_models() -> None:
    confidential = summary_harness(classification="confidential")
    with pytest.raises(PolicyViolation):
        confidential.service.summarize(
            user_context=confidential.user,
            tenant_policy=confidential.policy,
            object_id=confidential.object_id,
            command=confidential.command(),
        )
    assert not confidential.gateway_audit.events

    nonlocal_model = summary_harness()
    model = nonlocal_model.service.gateway.model_registry.get("mock-summarizer")
    nonlocal_model.service.gateway.model_registry._models["mock-summarizer"] = model.model_copy(
        update={"deployment": "external"}
    )
    with pytest.raises(PolicyViolation):
        nonlocal_model.service.summarize(
            user_context=nonlocal_model.user,
            tenant_policy=nonlocal_model.policy,
            object_id=nonlocal_model.object_id,
            command=nonlocal_model.command(),
        )


def test_selection_summary_rejects_invalid_model_output_without_a_document_write() -> None:
    harness = summary_harness()

    class InvalidProvider:
        def complete(self, *, model_id: str, prompt: str) -> str:
            del model_id, prompt
            return "invalid\x00output"

    harness.service.gateway.providers["mock"] = InvalidProvider()
    with pytest.raises(OfficeAISummaryUnavailable):
        harness.service.summarize(
            user_context=harness.user,
            tenant_policy=harness.policy,
            object_id=harness.object_id,
            command=harness.command(),
        )
    assert len(harness.repository.saved_versions) == 1


def test_selection_summary_api_is_read_gated_noncacheable_and_does_not_write(
    office_api: OfficeApiHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = create_document(office_api)
    gateway = app.state.llm_gateway
    service = build_office_ai_summary_service(document_service=office_api.service, gateway=gateway)
    monkeypatch.setattr(app.state, "office_ai_summary_service", service)
    object_id = created["document"]["object_id"]
    version_id = created["version"]["version_id"]
    path = f"/v1/office/documents/{object_id}/ai/summaries"
    payload: dict[str, Any] = {
        "expected_current_version_id": version_id,
        "anchor": {"from": 1, "to": 7},
    }
    response = office_api.client.post(path, headers=office_api.headers, json=payload)
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == "no-store"
    assert response.json()["document_changed"] is False
    assert len(office_api.repository.saved_versions) == 1

    enable_office(read=False, write=True)
    denied = office_api.client.post(path, headers=office_api.headers, json=payload)
    assert denied.status_code == 403
    assert len(office_api.repository.saved_versions) == 1
