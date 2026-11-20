from __future__ import annotations

from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from suite.ai_control_plane.models import DataClass, InferenceRequest, Purpose, RiskLevel, TenantPolicy, UserContext
from suite.ai_control_plane.policy import PolicyViolation
from suite.llm_gateway.gateway import LocalLLMGateway
from suite.platform.office_documents import OfficeDocumentConflictError, OfficeDocumentService
from suite.platform.office_reviews import ReviewAnchor, derive_review_quote

OFFICE_AI_SUMMARY_PROMPT_ID = "document_summary_v1"
LOCAL_MODEL_PROVIDERS = frozenset({"mock", "ollama", "vllm"})


class OfficeAISummaryUnavailable(RuntimeError):
    pass


class OfficeAISummaryCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_current_version_id: str = Field(min_length=1, max_length=128)
    anchor: ReviewAnchor


class OfficeAISummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    object_id: str
    source_version_id: str
    source_anchor: ReviewAnchor
    source_selection_hash: str
    summary: str
    model_id: str
    prompt_template_id: str
    inference_audit_event_id: str
    output_trust: Literal["untrusted"] = "untrusted"
    persisted: Literal[False] = False
    document_changed: Literal[False] = False
    requires_explicit_suggestion_confirmation: Literal[True] = True
    rag_indexing_allowed: Literal[False] = False
    search_indexing_allowed: Literal[False] = False


class OfficeAISummaryService:
    def __init__(self, *, documents: OfficeDocumentService, gateway: LocalLLMGateway) -> None:
        self.documents = documents
        self.gateway = gateway

    def summarize(
        self,
        *,
        user_context: UserContext,
        tenant_policy: TenantPolicy,
        object_id: str,
        command: OfficeAISummaryCommand,
    ) -> OfficeAISummaryResponse:
        source = self.documents.read_content(
            user_context=user_context,
            object_id=object_id,
            version_id=command.expected_current_version_id,
            write_enabled=False,
        )
        if not source.is_current_version or source.document.current_version_id != command.expected_current_version_id:
            raise OfficeDocumentConflictError("AI summary requires the current saved version")

        selection = derive_review_quote(source.content, command.anchor)
        if selection is None:
            raise ValueError("AI summary requires a saved text selection")

        data_class = (
            DataClass.CONFIDENTIAL
            if source.version.information_classification in {"confidential", "restricted"}
            else DataClass.INTERNAL
        )
        # The document repository has authoritatively revalidated the exact object above. Extend only this
        # request-scoped context so the gateway can bind its independent source authorization to that result.
        inference_user = user_context.model_copy(
            update={"readable_object_ids": set(user_context.readable_object_ids) | {object_id}}
        )
        inference = self.gateway.infer(
            request=InferenceRequest(
                prompt_template_id=OFFICE_AI_SUMMARY_PROMPT_ID,
                model_id=self._local_summary_model_id(tenant_policy=tenant_policy, data_class=data_class),
                purpose=Purpose.SUMMARIZATION,
                input_text=selection,
                data_classes={data_class},
                source_object_ids=[object_id],
                risk_level=RiskLevel.LOW,
            ),
            user_context=inference_user,
            tenant_policy=tenant_policy,
        )
        summary = inference.answer.strip()
        if (
            not summary
            or len(summary) > 4000
            or any((ord(character) < 32 and character not in "\n\t") for character in summary)
            or any(0xD800 <= ord(character) <= 0xDFFF for character in summary)
        ):
            raise OfficeAISummaryUnavailable("Local model returned an invalid Office AI summary")

        self.documents._audit(
            user_context,
            "office.ai.selection_summary",
            object_id=object_id,
            version_id=source.version.version_id,
            source_selection_hash="sha256:" + sha256(selection.encode("utf-8")).hexdigest(),
            output_hash="sha256:" + sha256(summary.encode("utf-8")).hexdigest(),
            inference_audit_event_id=inference.audit_event_id,
            model_id=inference.model_id,
            prompt_template_id=inference.prompt_template_id,
            output_trust="untrusted",
            persisted=False,
            document_changed=False,
        )
        return OfficeAISummaryResponse(
            tenant_id=user_context.tenant_id,
            object_id=object_id,
            source_version_id=source.version.version_id,
            source_anchor=command.anchor,
            source_selection_hash="sha256:" + sha256(selection.encode("utf-8")).hexdigest(),
            summary=summary,
            model_id=inference.model_id,
            prompt_template_id=inference.prompt_template_id,
            inference_audit_event_id=inference.audit_event_id,
        )

    def _local_summary_model_id(self, *, tenant_policy: TenantPolicy, data_class: DataClass) -> str:
        candidates = []
        for model_id in tenant_policy.allowed_model_ids:
            try:
                model = self.gateway.model_registry.get(model_id)
            except LookupError:
                continue
            if (
                model.deployment == "local"
                and model.provider in LOCAL_MODEL_PROVIDERS
                and Purpose.SUMMARIZATION in model.approved_for
                and Purpose.SUMMARIZATION not in model.blocked_for
                and data_class in model.allowed_data_classes
            ):
                candidates.append(model)
        if not candidates:
            raise PolicyViolation("Office AI summary requires an admitted local model")
        return min(candidates, key=lambda model: (model.provider == "mock", model.model_id)).model_id
