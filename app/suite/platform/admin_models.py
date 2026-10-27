from pydantic import BaseModel, ConfigDict


class TenantAiPolicyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ai_enabled: bool | None = None
    rag_enabled: bool | None = None
    voice_enabled: bool | None = None
    external_ai_enabled: bool | None = None
    content_preview_enabled: bool | None = None
    raw_audio_storage_allowed: bool | None = None
    allowed_model_ids: set[str] | None = None
