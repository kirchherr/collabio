from __future__ import annotations

from hashlib import sha256
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from suite.ai_control_plane.models import DataClass, InferenceRequest, Purpose, RiskLevel, TenantPolicy, UserContext
from suite.ai_control_plane.policy import PolicyViolation
from suite.llm_gateway.gateway import LocalLLMGateway
from suite.platform.office_ai_summary import LOCAL_MODEL_PROVIDERS
from suite.platform.office_documents import OfficeDocumentConflictError, OfficeDocumentService

OFFICE_AI_POLICY_COMPARISON_PROMPT_ID = "document_policy_comparison_v1"
MAX_POLICY_COMPARISON_SOURCE_CHARACTERS = 16_000
POLICY_COMPARISON_PREFIXES = ("FINDING: ", "RECOMMENDATION: ")
OfficeAIPolicyComparisonStatus = Literal["conform", "deviation", "unclear"]


class OfficeAIPolicyComparisonUnavailable(RuntimeError):
    pass


class OfficeAIPolicyComparisonCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_current_version_id: str = Field(min_length=1, max_length=128)
    policy_object_id: str = Field(min_length=1, max_length=128)
    policy_version_id: str = Field(min_length=1, max_length=128)


class OfficeAIPolicyCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str
    version_id: str
    title: str
    content_hash: str
    authoritative_acl_validated: Literal[True] = True


class OfficeAIPolicyComparisonResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    object_id: str
    source_version_id: str
    source_content_hash: str
    policy_citation: OfficeAIPolicyCitation
    status: OfficeAIPolicyComparisonStatus
    comparison: str
    finding_count: int
    model_id: str
    prompt_template_id: str
    inference_audit_event_id: str
    output_trust: Literal["untrusted"] = "untrusted"
    requires_human_review: Literal[True] = True
    persisted: Literal[False] = False
    document_changed: Literal[False] = False
    automatic_action_allowed: Literal[False] = False
    rag_indexing_allowed: Literal[False] = False
    search_indexing_allowed: Literal[False] = False


def office_document_plain_text(content: dict[str, Any]) -> str:
    parts: list[str] = []
    block_types = {
        "paragraph",
        "heading",
        "listItem",
        "blockquote",
        "codeBlock",
        "tableCell",
        "tableHeader",
        "tableRow",
    }

    def walk(node: Any) -> None:
        if not isinstance(node, dict):
            return
        node_type = node.get("type")
        if node_type == "text" and isinstance(node.get("text"), str):
            parts.append(node["text"])
            return
        if node_type == "hardBreak":
            parts.append("\n")
        children = node.get("content", [])
        if isinstance(children, list):
            for child in children:
                walk(child)
        if node_type in block_types:
            parts.append("\n")

    walk(content)
    return "\n".join(" ".join(line.split()) for line in "".join(parts).splitlines() if line.strip())


class OfficeAIPolicyComparisonService:
    def __init__(self, *, documents: OfficeDocumentService, gateway: LocalLLMGateway) -> None:
        self.documents = documents
        self.gateway = gateway

    def compare(
        self,
        *,
        user_context: UserContext,
        tenant_policy: TenantPolicy,
        object_id: str,
        command: OfficeAIPolicyComparisonCommand,
    ) -> OfficeAIPolicyComparisonResponse:
        if command.policy_object_id == object_id:
            raise ValueError("Policy comparison requires a different readable document")
        source = self.documents.read_content(
            user_context=user_context,
            object_id=object_id,
            version_id=command.expected_current_version_id,
            write_enabled=False,
        )
        policy = self.documents.read_content(
            user_context=user_context,
            object_id=command.policy_object_id,
            version_id=command.policy_version_id,
            write_enabled=False,
        )
        if not source.is_current_version or source.document.current_version_id != command.expected_current_version_id:
            raise OfficeDocumentConflictError("AI policy comparison requires the current saved document version")
        if not policy.is_current_version or policy.document.current_version_id != command.policy_version_id:
            raise OfficeDocumentConflictError("AI policy comparison requires the current saved policy version")

        source_text = office_document_plain_text(source.content)
        policy_text = office_document_plain_text(policy.content)
        if not source_text or not policy_text:
            raise OfficeAIPolicyComparisonUnavailable("Policy comparison requires text in both documents")
        if (
            len(source_text) > MAX_POLICY_COMPARISON_SOURCE_CHARACTERS
            or len(policy_text) > MAX_POLICY_COMPARISON_SOURCE_CHARACTERS
        ):
            raise OfficeAIPolicyComparisonUnavailable("Policy comparison source exceeds the admitted bound")

        data_class = (
            DataClass.CONFIDENTIAL
            if {source.version.information_classification, policy.version.information_classification}
            & {"confidential", "restricted"}
            else DataClass.INTERNAL
        )
        try:
            self.gateway.prompt_registry.get(OFFICE_AI_POLICY_COMPARISON_PROMPT_ID)
        except LookupError as exc:
            raise OfficeAIPolicyComparisonUnavailable("Office AI policy comparison prompt is unavailable") from exc
        combined = (
            "POLICY_COMPARISON_INPUT_V1\n"
            "UNTRUSTED_DOCUMENT_BEGIN\n"
            f"{source_text}\n"
            "UNTRUSTED_DOCUMENT_END\n"
            "UNTRUSTED_POLICY_BEGIN\n"
            f"{policy_text}\n"
            "UNTRUSTED_POLICY_END"
        )
        inference_user = user_context.model_copy(
            update={
                "readable_object_ids": set(user_context.readable_object_ids) | {object_id, command.policy_object_id}
            }
        )
        inference = self.gateway.infer(
            request=InferenceRequest(
                prompt_template_id=OFFICE_AI_POLICY_COMPARISON_PROMPT_ID,
                model_id=self._local_model_id(tenant_policy=tenant_policy, data_class=data_class),
                purpose=Purpose.DRAFTING,
                input_text=combined,
                data_classes={data_class},
                source_object_ids=[object_id, command.policy_object_id],
                risk_level=RiskLevel.HIGH,
            ),
            user_context=inference_user,
            tenant_policy=tenant_policy,
        )
        comparison = inference.answer.strip()
        lines = [line.strip() for line in comparison.splitlines() if line.strip()]
        status = self._validated_status(lines)
        finding_count = sum(line.startswith("FINDING: ") for line in lines[1:])
        if (
            len(comparison) > 6000
            or not 2 <= len(lines) <= 12
            or finding_count < 1
            or any(not line.startswith(POLICY_COMPARISON_PREFIXES) for line in lines[1:])
            or any((ord(character) < 32 and character not in "\n\t") for character in comparison)
            or any(0xD800 <= ord(character) <= 0xDFFF for character in comparison)
        ):
            raise OfficeAIPolicyComparisonUnavailable("Local model returned an invalid policy comparison")

        source_hash = "sha256:" + sha256(source_text.encode("utf-8")).hexdigest()
        policy_hash = "sha256:" + sha256(policy_text.encode("utf-8")).hexdigest()
        self.documents._audit(
            user_context,
            "office.ai.policy_comparison",
            object_id=object_id,
            version_id=source.version.version_id,
            source_text_hash=source_hash,
            policy_object_id=command.policy_object_id,
            policy_version_id=policy.version.version_id,
            policy_text_hash=policy_hash,
            output_hash="sha256:" + sha256(comparison.encode("utf-8")).hexdigest(),
            status=status,
            finding_count=finding_count,
            inference_audit_event_id=inference.audit_event_id,
            model_id=inference.model_id,
            prompt_template_id=inference.prompt_template_id,
            output_trust="untrusted",
            persisted=False,
            document_changed=False,
            automatic_action_allowed=False,
        )
        return OfficeAIPolicyComparisonResponse(
            tenant_id=user_context.tenant_id,
            object_id=object_id,
            source_version_id=source.version.version_id,
            source_content_hash=source_hash,
            policy_citation=OfficeAIPolicyCitation(
                object_id=command.policy_object_id,
                version_id=policy.version.version_id,
                title=policy.version.title,
                content_hash=policy_hash,
            ),
            status=status,
            comparison=comparison,
            finding_count=finding_count,
            model_id=inference.model_id,
            prompt_template_id=inference.prompt_template_id,
            inference_audit_event_id=inference.audit_event_id,
        )

    @staticmethod
    def _validated_status(lines: list[str]) -> OfficeAIPolicyComparisonStatus:
        if not lines or not lines[0].startswith("STATUS: "):
            raise OfficeAIPolicyComparisonUnavailable("Local model returned an invalid policy comparison status")
        status = lines[0].removeprefix("STATUS: ")
        if status not in {"conform", "deviation", "unclear"}:
            raise OfficeAIPolicyComparisonUnavailable("Local model returned an invalid policy comparison status")
        return cast(OfficeAIPolicyComparisonStatus, status)

    def _local_model_id(self, *, tenant_policy: TenantPolicy, data_class: DataClass) -> str:
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
            raise PolicyViolation("Office AI policy comparison requires an admitted local model")
        return min(candidates, key=lambda model: (model.provider == "mock", model.model_id)).model_id
