from __future__ import annotations

from hashlib import sha256
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field

from suite.ai_control_plane.models import DataClass, InferenceRequest, Purpose, RiskLevel, TenantPolicy, UserContext
from suite.ai_control_plane.policy import PolicyViolation
from suite.llm_gateway.gateway import LocalLLMGateway
from suite.platform.office_ai_summary import LOCAL_MODEL_PROVIDERS
from suite.platform.office_documents import OfficeDocumentConflictError, OfficeDocumentService
from suite.platform.office_reviews import ReviewAnchor, derive_review_quote

OFFICE_AI_RISK_MARKING_PROMPT_ID = "document_risk_marking_v1"
MAX_RISK_MARKING_SOURCE_CHARACTERS = 16_000
MAX_RISK_MARKINGS = 8
OfficeAIRiskStatus = Literal["clear", "risks"]
OfficeAIRiskSeverity = Literal["low", "medium", "high"]
OfficeAIRiskCategory = Literal["legal", "financial", "privacy", "security", "operational", "commitment"]


class OfficeAIRiskMarkingUnavailable(RuntimeError):
    pass


class OfficeAIRiskMarkingCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_current_version_id: str = Field(min_length=1, max_length=128)


class OfficeAIRiskFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: OfficeAIRiskSeverity
    category: OfficeAIRiskCategory
    anchor: ReviewAnchor
    source_excerpt: str
    explanation: str


class OfficeAIRiskMarkingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    object_id: str
    source_version_id: str
    source_content_hash: str
    status: OfficeAIRiskStatus
    highest_severity: OfficeAIRiskSeverity | None
    risk_count: int
    risks: list[OfficeAIRiskFinding]
    model_id: str
    prompt_template_id: str
    inference_audit_event_id: str
    output_trust: Literal["untrusted"] = "untrusted"
    requires_human_review: Literal[True] = True
    persisted: Literal[False] = False
    document_changed: Literal[False] = False
    automatic_action_allowed: Literal[False] = False
    compliance_decision_allowed: Literal[False] = False
    rag_indexing_allowed: Literal[False] = False
    search_indexing_allowed: Literal[False] = False


class _RiskBlock(BaseModel):
    index: int
    anchor: ReviewAnchor
    text: str


def office_document_risk_blocks(content: dict[str, Any]) -> list[_RiskBlock]:
    """Return exact native text runs with ProseMirror UTF-16 positions."""
    runs: list[tuple[int, str]] = []

    def visit(node: dict[str, Any], position: int) -> int:
        kind = node["type"]
        if kind == "text":
            return len(node["text"].encode("utf-16-le")) // 2
        children = node.get("content", [])
        if not children:
            return 1 if kind in {"hardBreak", "horizontalRule", "image", "pageBreak", "sectionBreak"} else 2
        offset = position + (0 if kind == "doc" else 1)
        if kind in {"paragraph", "heading", "codeBlock"}:
            start = offset
            parts: list[str] = []
            for child in children:
                if child["type"] == "text":
                    parts.append(child["text"])
                else:
                    if parts:
                        runs.append((start, "".join(parts)))
                    parts = []
                    start = offset + 1
                offset += visit(child, offset)
            if parts:
                runs.append((start, "".join(parts)))
        else:
            for child in children:
                offset += visit(child, offset)
        return offset - position + (0 if kind == "doc" else 1)

    visit(content, 0)
    blocks: list[_RiskBlock] = []
    for start, text in runs:
        if not text.strip() or len(text) > 2000:
            continue
        anchor = ReviewAnchor.model_validate({"from": start, "to": start + len(text.encode("utf-16-le")) // 2})
        if derive_review_quote(content, anchor) != text:
            raise OfficeAIRiskMarkingUnavailable("Risk marking source anchor is invalid")
        blocks.append(_RiskBlock(index=len(blocks) + 1, anchor=anchor, text=text))
    return blocks


class OfficeAIRiskMarkingService:
    def __init__(self, *, documents: OfficeDocumentService, gateway: LocalLLMGateway) -> None:
        self.documents = documents
        self.gateway = gateway

    def mark(
        self,
        *,
        user_context: UserContext,
        tenant_policy: TenantPolicy,
        object_id: str,
        command: OfficeAIRiskMarkingCommand,
    ) -> OfficeAIRiskMarkingResponse:
        source = self.documents.read_content(
            user_context=user_context,
            object_id=object_id,
            version_id=command.expected_current_version_id,
            write_enabled=False,
        )
        if not source.is_current_version or source.document.current_version_id != command.expected_current_version_id:
            raise OfficeDocumentConflictError("AI risk marking requires the current saved document version")

        blocks = office_document_risk_blocks(source.content)
        if not blocks:
            raise OfficeAIRiskMarkingUnavailable("Risk marking requires native document text")
        indexed_source = "\n".join(f"BLOCK {block.index}: {block.text}" for block in blocks)
        if len(indexed_source) > MAX_RISK_MARKING_SOURCE_CHARACTERS:
            raise OfficeAIRiskMarkingUnavailable("Risk marking source exceeds the admitted bound")
        source_text = "\n".join(block.text for block in blocks)

        data_class = (
            DataClass.CONFIDENTIAL
            if source.version.information_classification in {"confidential", "restricted"}
            else DataClass.INTERNAL
        )
        try:
            self.gateway.prompt_registry.get(OFFICE_AI_RISK_MARKING_PROMPT_ID)
        except LookupError as exc:
            raise OfficeAIRiskMarkingUnavailable("Office AI risk marking prompt is unavailable") from exc
        inference = self.gateway.infer(
            request=InferenceRequest(
                prompt_template_id=OFFICE_AI_RISK_MARKING_PROMPT_ID,
                model_id=self._local_model_id(tenant_policy=tenant_policy, data_class=data_class),
                purpose=Purpose.DRAFTING,
                input_text=f"RISK_MARKING_INPUT_V1\nUNTRUSTED_DOCUMENT_BEGIN\n{indexed_source}\nUNTRUSTED_DOCUMENT_END",
                data_classes={data_class},
                source_object_ids=[object_id],
                risk_level=RiskLevel.HIGH,
            ),
            user_context=user_context,
            tenant_policy=tenant_policy,
        )
        raw = inference.answer.strip()
        status, findings = self._validated_findings(raw, blocks)
        source_hash = "sha256:" + sha256(source_text.encode("utf-8")).hexdigest()
        highest: OfficeAIRiskSeverity | None = None
        if any(finding.severity == "high" for finding in findings):
            highest = "high"
        elif any(finding.severity == "medium" for finding in findings):
            highest = "medium"
        elif findings:
            highest = "low"
        self.documents._audit(
            user_context,
            "office.ai.risk_marking",
            object_id=object_id,
            version_id=source.version.version_id,
            source_text_hash=source_hash,
            output_hash="sha256:" + sha256(raw.encode("utf-8")).hexdigest(),
            status=status,
            risk_count=len(findings),
            highest_severity=highest,
            inference_audit_event_id=inference.audit_event_id,
            model_id=inference.model_id,
            prompt_template_id=inference.prompt_template_id,
            output_trust="untrusted",
            persisted=False,
            document_changed=False,
            automatic_action_allowed=False,
            compliance_decision_allowed=False,
        )
        return OfficeAIRiskMarkingResponse(
            tenant_id=user_context.tenant_id,
            object_id=object_id,
            source_version_id=source.version.version_id,
            source_content_hash=source_hash,
            status=status,
            highest_severity=highest,
            risk_count=len(findings),
            risks=findings,
            model_id=inference.model_id,
            prompt_template_id=inference.prompt_template_id,
            inference_audit_event_id=inference.audit_event_id,
        )

    @staticmethod
    def _validated_findings(raw: str, blocks: list[_RiskBlock]) -> tuple[OfficeAIRiskStatus, list[OfficeAIRiskFinding]]:
        if len(raw) > 6000 or any(
            (ord(character) < 32 and character not in "\n\t") or 0xD800 <= ord(character) <= 0xDFFF for character in raw
        ):
            raise OfficeAIRiskMarkingUnavailable("Local model returned invalid risk markings")
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        if not lines or lines[0] not in {"STATUS: clear", "STATUS: risks"}:
            raise OfficeAIRiskMarkingUnavailable("Local model returned invalid risk status")
        status = cast(OfficeAIRiskStatus, lines[0].removeprefix("STATUS: "))
        if status == "clear":
            if len(lines) != 1:
                raise OfficeAIRiskMarkingUnavailable("Clear risk status cannot contain findings")
            return status, []
        if not 2 <= len(lines) <= MAX_RISK_MARKINGS + 1:
            raise OfficeAIRiskMarkingUnavailable("Risk result count is invalid")

        block_by_index = {block.index: block for block in blocks}
        seen: set[int] = set()
        findings: list[OfficeAIRiskFinding] = []
        for line in lines[1:]:
            if not line.startswith("RISK: "):
                raise OfficeAIRiskMarkingUnavailable("Local model returned invalid risk markings")
            parts = line.removeprefix("RISK: ").split("|", 3)
            if len(parts) != 4:
                raise OfficeAIRiskMarkingUnavailable("Local model returned invalid risk markings")
            severity, category, index_text, explanation = (part.strip() for part in parts)
            if severity not in {"low", "medium", "high"} or category not in {
                "legal",
                "financial",
                "privacy",
                "security",
                "operational",
                "commitment",
            }:
                raise OfficeAIRiskMarkingUnavailable("Local model returned invalid risk markings")
            try:
                block_index = int(index_text)
            except ValueError as exc:
                raise OfficeAIRiskMarkingUnavailable("Local model returned invalid risk anchor") from exc
            block = block_by_index.get(block_index)
            if block is None or block_index in seen or not explanation or len(explanation) > 500 or "|" in explanation:
                raise OfficeAIRiskMarkingUnavailable("Local model returned invalid risk finding")
            seen.add(block_index)
            findings.append(
                OfficeAIRiskFinding(
                    severity=cast(OfficeAIRiskSeverity, severity),
                    category=cast(OfficeAIRiskCategory, category),
                    anchor=block.anchor,
                    source_excerpt=block.text,
                    explanation=explanation,
                )
            )
        return status, findings

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
            raise PolicyViolation("Office AI risk marking requires an admitted local model")
        return min(candidates, key=lambda model: (model.provider == "mock", model.model_id)).model_id
