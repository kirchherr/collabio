import math
import re
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator

from suite.ai_control_plane.models import DataClass

NAMESPACED_REF_PATTERN = re.compile(r"^[a-z][a-z0-9_+.-]*:.+")
SOURCE_OBJECT_TYPES = frozenset({"document", "mail", "attachment", "comment", "wiki", "procedure_doc"})
LEGAL_HOLD_STATES = frozenset({"none", "active"})


class ChunkMetadata(BaseModel):
    tenant_id: str
    source_object_id: str
    source_object_type: str
    source_version_id: str
    chunk_id: str
    classification: DataClass
    retention_policy_id: str
    legal_hold_state: str
    acl_hash: str
    acl_version: int = Field(ge=1)
    created_at_utc: str
    embedding_model_id: str
    embedding_model_version: str
    content_hash: str

    @field_validator(
        "tenant_id",
        "source_object_id",
        "source_version_id",
        "chunk_id",
        "retention_policy_id",
        "embedding_model_id",
        "embedding_model_version",
    )
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized

    @field_validator("source_object_type")
    @classmethod
    def require_known_source_object_type(cls, value: str) -> str:
        normalized = value.strip()
        if normalized not in SOURCE_OBJECT_TYPES:
            raise ValueError("source_object_type must be a known source object type")
        return normalized

    @field_validator("legal_hold_state")
    @classmethod
    def require_known_legal_hold_state(cls, value: str) -> str:
        normalized = value.strip()
        if normalized not in LEGAL_HOLD_STATES:
            raise ValueError("legal_hold_state must be none or active")
        return normalized

    @field_validator("acl_hash", "content_hash")
    @classmethod
    def require_namespaced_ref(cls, value: str, info: object) -> str:
        normalized = value.strip()
        if not NAMESPACED_REF_PATTERN.fullmatch(normalized):
            field_name = getattr(info, "field_name", "reference")
            raise ValueError(f"{field_name} must be a namespaced reference")
        return normalized

    @field_validator("created_at_utc")
    @classmethod
    def require_utc_timestamp(cls, value: str) -> str:
        return _require_utc_timestamp(value)


class VectorLifecycleState(StrEnum):
    ACTIVE = "active"
    REINDEX_PENDING = "reindex_pending"
    RESTRICTED = "restricted"
    DELETED = "deleted"
    CRYPTOSHREDDED = "cryptoshredded"


class VectorCandidate(BaseModel):
    chunk_id: str
    score: float
    metadata: ChunkMetadata


class VectorEmbeddingRecord(BaseModel):
    metadata: ChunkMetadata
    embedding: list[float]
    embedding_dimensions: int = Field(ge=1)
    content_byte_length: int = Field(ge=0)
    lifecycle_state: VectorLifecycleState = VectorLifecycleState.ACTIVE
    indexed_at_utc: str
    expires_at_utc: str | None = None
    audit_event_id: str | None = None

    @field_validator("indexed_at_utc", "expires_at_utc")
    @classmethod
    def require_utc_timestamp(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _require_utc_timestamp(value)

    @model_validator(mode="after")
    def require_dimensions_match(self) -> "VectorEmbeddingRecord":
        if self.embedding_dimensions != len(self.embedding):
            raise ValueError("embedding_dimensions must match embedding length")
        if not all(math.isfinite(value) for value in self.embedding):
            raise ValueError("embedding values must be finite")
        return self


class SourceDocument(BaseModel):
    object_id: str
    version_id: str
    title: str
    text: str
    classification: DataClass
    mime_type: str = "text/plain"
    content_bytes: bytes | None = None


class RagQuery(BaseModel):
    question: str
    top_k: int = Field(default=3, ge=1, le=10)


class RagSource(BaseModel):
    object_id: str
    version_id: str
    chunk_id: str
    title: str
    classification: DataClass
    access_checked: bool


class RagResponse(BaseModel):
    answer: str
    confidence: str
    sources: list[RagSource]
    model_id: str
    prompt_template_id: str
    retrieval_policy_id: str
    audit_event_id: str


def _require_utc_timestamp(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("timestamp must not be empty")
    parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("timestamp must be UTC")
    return normalized
