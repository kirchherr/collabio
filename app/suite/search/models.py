from pydantic import BaseModel, Field

from suite.ai_control_plane.models import DataClass

SEARCH_POLICY_ID = "keyword_candidate_acl_v1"


class KeywordSearchQuery(BaseModel):
    query: str = Field(min_length=1)
    top_k: int = Field(default=10, ge=1, le=50)


class KeywordSearchCandidate(BaseModel):
    object_id: str
    object_type: str
    version_id: str
    chunk_id: str
    title: str
    classification: DataClass
    retention_policy_id: str
    legal_hold_state: str
    acl_version: int
    content_hash: str
    score: float
    access_checked: bool = True


class KeywordSearchResponse(BaseModel):
    candidates: list[KeywordSearchCandidate]
    search_policy_id: str = SEARCH_POLICY_ID
    audit_event_id: str
