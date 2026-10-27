from __future__ import annotations

import re
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from suite.ai_control_plane.models import DataClass, InferenceRequest, Purpose, RiskLevel, TenantPolicy, UserContext
from suite.ai_control_plane.policy import PolicyViolation
from suite.llm_gateway.gateway import LocalLLMGateway
from suite.platform.office_ai_summary import LOCAL_MODEL_PROVIDERS
from suite.platform.office_documents import OfficeDocumentConflictError, OfficeDocumentService
from suite.platform.office_reviews import ReviewAnchor, derive_review_quote

OfficeAIOutlineDetail = Literal["concise", "detailed"]

OFFICE_AI_OUTLINE_PROMPT_IDS: dict[OfficeAIOutlineDetail, str] = {
    "concise": "document_outline_concise_v1",
    "detailed": "document_outline_detailed_v1",
}
OUTLINE_LINE = re.compile(r"^(?:#{1,3}\s+|[-*]\s+|\d{1,2}[.)]\s+|\s{2,}[-*]\s+).+\S$")


class OfficeAIOutlineUnavailable(RuntimeError):
    pass


class OfficeAIOutlineCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_current_version_id: str = Field(min_length=1, max_length=128)
    anchor: ReviewAnchor
    detail: OfficeAIOutlineDetail


class OfficeAIOutlineResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    object_id: str
    source_version_id: str
    source_anchor: ReviewAnchor
    source_selection_hash: str
    detail: OfficeAIOutlineDetail
    outline: str
    outline_line_count: int
    model_id: str
    prompt_template_id: str
    inference_audit_event_id: str
    output_trust: Literal["untrusted"] = "untrusted"
    persisted: Literal[False] = False
    document_changed: Literal[False] = False
    requires_explicit_suggestion_confirmation: Literal[True] = True
    rag_indexing_allowed: Literal[False] = False
    search_indexing_allowed: Literal[False] = False


class OfficeAIOutlineService:
    def __init__(self, *, documents: OfficeDocumentService, gateway: LocalLLMGateway) -> None:
        self.documents = documents
        self.gateway = gateway

    def generate(
        self,
        *,
        user_context: UserContext,
        tenant_policy: TenantPolicy,
        object_id: str,
        command: OfficeAIOutlineCommand,
    ) -> OfficeAIOutlineResponse:
        source = self.documents.read_content(
            user_context=user_context,
            object_id=object_id,
            version_id=command.expected_current_version_id,
            write_enabled=False,
        )
        if not source.is_current_version or source.document.current_version_id != command.expected_current_version_id:
            raise OfficeDocumentConflictError("AI outline requires the current saved version")

        selection = derive_review_quote(source.content, command.anchor)
        if selection is None:
            raise ValueError("AI outline requires a saved text selection")

        data_class = (
            DataClass.CONFIDENTIAL
            if source.version.information_classification in {"confidential", "restricted"}
            else DataClass.INTERNAL
        )
        prompt_template_id = OFFICE_AI_OUTLINE_PROMPT_IDS[command.detail]
        try:
            self.gateway.prompt_registry.get(prompt_template_id)
        except LookupError as exc:
            raise OfficeAIOutlineUnavailable("Office AI outline prompt is unavailable") from exc

        inference_user = user_context.model_copy(
            update={"readable_object_ids": set(user_context.readable_object_ids) | {object_id}}
        )
        inference = self.gateway.infer(
            request=InferenceRequest(
                prompt_template_id=prompt_template_id,
                model_id=self._local_outline_model_id(tenant_policy=tenant_policy, data_class=data_class),
                purpose=Purpose.DRAFTING,
                input_text=selection,
                data_classes={data_class},
                source_object_ids=[object_id],
                risk_level=RiskLevel.MEDIUM,
            ),
            user_context=inference_user,
            tenant_policy=tenant_policy,
        )
        outline = inference.answer.strip()
        lines = [line.rstrip() for line in outline.splitlines() if line.strip()]
        line_limit = 8 if command.detail == "concise" else 20
        if (
            not outline
            or outline == selection
            or len(outline) > 4000
            or not 2 <= len(lines) <= line_limit
            or any(not OUTLINE_LINE.fullmatch(line) for line in lines)
            or any((ord(character) < 32 and character not in "\n\t") for character in outline)
            or any(0xD800 <= ord(character) <= 0xDFFF for character in outline)
        ):
            raise OfficeAIOutlineUnavailable("Local model returned an invalid Office AI outline")

        selection_hash = "sha256:" + sha256(selection.encode("utf-8")).hexdigest()
        self.documents._audit(
            user_context,
            "office.ai.selection_outline",
            object_id=object_id,
            version_id=source.version.version_id,
            source_selection_hash=selection_hash,
            output_hash="sha256:" + sha256(outline.encode("utf-8")).hexdigest(),
            detail=command.detail,
            outline_line_count=len(lines),
            inference_audit_event_id=inference.audit_event_id,
            model_id=inference.model_id,
            prompt_template_id=inference.prompt_template_id,
            output_trust="untrusted",
            persisted=False,
            document_changed=False,
        )
        return OfficeAIOutlineResponse(
            tenant_id=user_context.tenant_id,
            object_id=object_id,
            source_version_id=source.version.version_id,
            source_anchor=command.anchor,
            source_selection_hash=selection_hash,
            detail=command.detail,
            outline=outline,
            outline_line_count=len(lines),
            model_id=inference.model_id,
            prompt_template_id=inference.prompt_template_id,
            inference_audit_event_id=inference.audit_event_id,
        )

    def _local_outline_model_id(self, *, tenant_policy: TenantPolicy, data_class: DataClass) -> str:
        candidates = []
        for model_id in tenant_policy.allowed_model_ids:
            try:
                model = self.gateway.model_registry.get(model_id)
            except LookupError:
                continue
            if (
                model.deployment == "local"
                and model.provider in LOCAL_MODEL_PROVIDERS
                and Purpose.DRAFTING in model.approved_for
                and Purpose.DRAFTING not in model.blocked_for
                and data_class in model.allowed_data_classes
            ):
                candidates.append(model)
        if not candidates:
            raise PolicyViolation("Office AI outline requires an admitted local model")
        return min(candidates, key=lambda model: (model.provider == "mock", model.model_id)).model_id
