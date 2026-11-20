from __future__ import annotations

from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from suite.ai_control_plane.models import DataClass, InferenceRequest, Purpose, RiskLevel, TenantPolicy, UserContext
from suite.ai_control_plane.policy import PolicyViolation
from suite.llm_gateway.gateway import LocalLLMGateway
from suite.platform.office_ai_summary import LOCAL_MODEL_PROVIDERS
from suite.platform.office_documents import OfficeDocumentConflictError, OfficeDocumentService
from suite.platform.office_reviews import ReviewAnchor, derive_review_quote

OfficeAIRewriteOperation = Literal["rewrite", "tone"]
OfficeAITone = Literal["neutral", "professional", "friendly", "formal", "concise"]

OFFICE_AI_REWRITE_PROMPT_IDS: dict[tuple[OfficeAIRewriteOperation, OfficeAITone | None], str] = {
    ("rewrite", None): "document_rewrite_v1",
    ("tone", "neutral"): "document_tone_neutral_v1",
    ("tone", "professional"): "document_tone_professional_v1",
    ("tone", "friendly"): "document_tone_friendly_v1",
    ("tone", "formal"): "document_tone_formal_v1",
    ("tone", "concise"): "document_tone_concise_v1",
}


class OfficeAIRewriteUnavailable(RuntimeError):
    pass


class OfficeAIRewriteCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_current_version_id: str = Field(min_length=1, max_length=128)
    anchor: ReviewAnchor
    operation: OfficeAIRewriteOperation
    tone: OfficeAITone | None = None

    @model_validator(mode="after")
    def operation_matches_tone(self) -> OfficeAIRewriteCommand:
        if self.operation == "tone" and self.tone is None:
            raise ValueError("Tone transformation requires one admitted tone")
        if self.operation == "rewrite" and self.tone is not None:
            raise ValueError("Plain rewrite does not accept a tone")
        return self


class OfficeAIRewriteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    object_id: str
    source_version_id: str
    source_anchor: ReviewAnchor
    source_selection_hash: str
    operation: OfficeAIRewriteOperation
    tone: OfficeAITone | None
    replacement_text: str
    model_id: str
    prompt_template_id: str
    inference_audit_event_id: str
    output_trust: Literal["untrusted"] = "untrusted"
    persisted: Literal[False] = False
    document_changed: Literal[False] = False
    requires_explicit_suggestion_confirmation: Literal[True] = True
    rag_indexing_allowed: Literal[False] = False
    search_indexing_allowed: Literal[False] = False


class OfficeAIRewriteService:
    def __init__(self, *, documents: OfficeDocumentService, gateway: LocalLLMGateway) -> None:
        self.documents = documents
        self.gateway = gateway

    def transform(
        self,
        *,
        user_context: UserContext,
        tenant_policy: TenantPolicy,
        object_id: str,
        command: OfficeAIRewriteCommand,
    ) -> OfficeAIRewriteResponse:
        source = self.documents.read_content(
            user_context=user_context,
            object_id=object_id,
            version_id=command.expected_current_version_id,
            write_enabled=False,
        )
        if not source.is_current_version or source.document.current_version_id != command.expected_current_version_id:
            raise OfficeDocumentConflictError("AI rewrite requires the current saved version")

        selection = derive_review_quote(source.content, command.anchor)
        if selection is None:
            raise ValueError("AI rewrite requires a saved text selection")

        data_class = (
            DataClass.CONFIDENTIAL
            if source.version.information_classification in {"confidential", "restricted"}
            else DataClass.INTERNAL
        )
        prompt_template_id = OFFICE_AI_REWRITE_PROMPT_IDS[(command.operation, command.tone)]
        try:
            self.gateway.prompt_registry.get(prompt_template_id)
        except LookupError as exc:
            raise OfficeAIRewriteUnavailable("Office AI rewrite prompt is unavailable") from exc

        inference_user = user_context.model_copy(
            update={"readable_object_ids": set(user_context.readable_object_ids) | {object_id}}
        )
        inference = self.gateway.infer(
            request=InferenceRequest(
                prompt_template_id=prompt_template_id,
                model_id=self._local_drafting_model_id(tenant_policy=tenant_policy, data_class=data_class),
                purpose=Purpose.DRAFTING,
                input_text=selection,
                data_classes={data_class},
                source_object_ids=[object_id],
                risk_level=RiskLevel.MEDIUM,
            ),
            user_context=inference_user,
            tenant_policy=tenant_policy,
        )
        replacement = inference.answer.strip()
        if (
            not replacement
            or replacement == selection
            or len(replacement) > 4000
            or any((ord(character) < 32 and character not in "\n\t") for character in replacement)
            or any(0xD800 <= ord(character) <= 0xDFFF for character in replacement)
        ):
            raise OfficeAIRewriteUnavailable("Local model returned an invalid Office AI rewrite")

        selection_hash = "sha256:" + sha256(selection.encode("utf-8")).hexdigest()
        self.documents._audit(
            user_context,
            "office.ai.selection_rewrite",
            object_id=object_id,
            version_id=source.version.version_id,
            source_selection_hash=selection_hash,
            output_hash="sha256:" + sha256(replacement.encode("utf-8")).hexdigest(),
            operation=command.operation,
            tone=command.tone or "none",
            inference_audit_event_id=inference.audit_event_id,
            model_id=inference.model_id,
            prompt_template_id=inference.prompt_template_id,
            output_trust="untrusted",
            persisted=False,
            document_changed=False,
        )
        return OfficeAIRewriteResponse(
            tenant_id=user_context.tenant_id,
            object_id=object_id,
            source_version_id=source.version.version_id,
            source_anchor=command.anchor,
            source_selection_hash=selection_hash,
            operation=command.operation,
            tone=command.tone,
            replacement_text=replacement,
            model_id=inference.model_id,
            prompt_template_id=inference.prompt_template_id,
            inference_audit_event_id=inference.audit_event_id,
        )

    def _local_drafting_model_id(self, *, tenant_policy: TenantPolicy, data_class: DataClass) -> str:
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
            raise PolicyViolation("Office AI rewrite requires an admitted local model")
        return min(candidates, key=lambda model: (model.provider == "mock", model.model_id)).model_id
