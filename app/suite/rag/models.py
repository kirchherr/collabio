from pydantic import BaseModel, Field

from suite.ai_control_plane.models import DataClass


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
    acl_version: int
    created_at_utc: str
    embedding_model_id: str
    embedding_model_version: str
    content_hash: str


class VectorCandidate(BaseModel):
    chunk_id: str
    score: float
    metadata: ChunkMetadata


class SourceDocument(BaseModel):
    object_id: str
    version_id: str
    title: str
    text: str
    classification: DataClass


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
