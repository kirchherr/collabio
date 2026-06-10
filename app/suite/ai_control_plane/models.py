from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class DataClass(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    PERSONAL = "personal"
    CONFIDENTIAL = "confidential"
    GOBD = "gobd"
    LEGAL_HOLD = "legal_hold"
    AI_PROMPT = "ai_prompt"
    AI_OUTPUT = "ai_output"
    RAG_CHUNK = "rag_chunk"
    EMBEDDING = "embedding"
    VOICE_TRANSCRIPT = "voice_transcript"


class RiskLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Purpose(StrEnum):
    SUMMARIZATION = "summarization"
    DRAFTING = "drafting"
    CLASSIFICATION = "classification"
    RAG = "rag"
    VOICE_COMMAND = "voice_command"


class UserContext(BaseModel):
    user_id: str
    tenant_id: str
    role_ids: set[str] = Field(default_factory=set)
    readable_object_ids: set[str] = Field(default_factory=set)


class TenantPolicy(BaseModel):
    tenant_id: str
    ai_enabled: bool = False
    rag_enabled: bool = False
    voice_enabled: bool = False
    external_ai_enabled: bool = False
    raw_audio_storage_allowed: bool = False
    allowed_model_ids: set[str] = Field(default_factory=set)
    allowed_data_classes: set[DataClass] = Field(default_factory=set)
    human_approval_required_for: set[RiskLevel] = Field(default_factory=lambda: {RiskLevel.HIGH, RiskLevel.CRITICAL})


class ModelConfig(BaseModel):
    model_id: str
    provider: str
    deployment: str
    license: str
    checksum: str
    allowed_data_classes: set[DataClass]
    max_context_tokens: int
    supports_tools: bool = False
    supports_json_mode: bool = False
    supports_embeddings: bool = False
    approved_for: set[Purpose]
    blocked_for: set[Purpose] = Field(default_factory=set)


class PromptTemplate(BaseModel):
    prompt_template_id: str
    version: str
    owner: str
    allowed_data_classes: set[DataClass]
    required_sources: bool
    output_schema: dict[str, Any] | None = None
    known_risks: list[str] = Field(default_factory=list)
    approval_status: str = "draft"
    template: str


class ToolPermission(BaseModel):
    tool_name: str
    allowed_role_ids: set[str]
    risk_level: RiskLevel
    requires_human_approval: bool = False


class InferenceRequest(BaseModel):
    prompt_template_id: str = "document_summary_v1"
    model_id: str = "mock-summarizer"
    purpose: Purpose = Purpose.SUMMARIZATION
    input_text: str
    data_classes: set[DataClass] = Field(default_factory=lambda: {DataClass.INTERNAL})
    source_object_ids: list[str] = Field(default_factory=list)
    risk_level: RiskLevel = RiskLevel.LOW
    requested_tool: str | None = None


class InferenceResponse(BaseModel):
    answer: str
    model_id: str
    prompt_template_id: str
    audit_event_id: str
    output_trust: str = "untrusted"
    requires_human_approval: bool = False
    source_object_ids: list[str] = Field(default_factory=list)


class AuditEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    schema_version: str = "audit_event.v1"
    sequence_number: int
    tenant_id: str
    user_id: str
    event_type: str
    model_id: str | None = None
    prompt_template_id: str | None = None
    source_object_ids: list[str] = Field(default_factory=list)
    input_hash: str | None = None
    output_hash: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    previous_event_hash: str
    event_hash: str
