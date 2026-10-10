from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from suite.ai_control_plane.models import DataClass


class VoiceTranscriptRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transcript: str = Field(min_length=1, max_length=4000)
    push_to_talk_active: bool = Field(strict=True)
    requested_raw_audio_storage: bool = Field(default=False, strict=True)
    language: str = Field(default="de-DE", pattern=r"^[a-z]{2}-[A-Z]{2}$")
    recognition_adapter: Literal["client_local_stt", "browser_web_speech"] = "client_local_stt"

    @field_validator("transcript")
    @classmethod
    def validate_transcript(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized or any(
            (ord(character) < 32 and character not in "\n\t") or 0xD800 <= ord(character) <= 0xDFFF
            for character in value
        ):
            raise ValueError("Voice transcript is invalid")
        return normalized


class VoiceTranscriptResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transcript_id: str
    classification: DataClass
    raw_audio_stored: bool
    audit_event_id: str
    transcript_hash: str
    transcript_character_count: int = Field(ge=1, le=4000)
    language: str
    recognition_adapter: Literal["client_local_stt", "browser_web_speech"]
    retention_policy_id: Literal["transient-not-persisted"] = "transient-not-persisted"
    transcript_persisted: Literal[False] = False


class VoiceSynthesisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=2000)
    explicit_activation: bool = Field(strict=True)
    requested_audio_storage: bool = Field(default=False, strict=True)
    language: str = Field(default="de-DE", pattern=r"^[a-z]{2}-[A-Z]{2}$")
    rate: float = Field(default=1.0, ge=0.5, le=2.0)
    synthesis_adapter: Literal["client_local_tts", "browser_speech_synthesis"]
    classification: DataClass

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        if not value.strip() or any(
            (ord(character) < 32 and character not in "\n\t") or 0xD800 <= ord(character) <= 0xDFFF
            for character in value
        ):
            raise ValueError("Voice synthesis text is invalid")
        return value


class VoiceSynthesisResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    synthesis_id: str
    classification: DataClass
    audit_event_id: str
    source_text_hash: str
    source_character_count: int = Field(ge=1, le=2000)
    language: str
    rate: float = Field(ge=0.5, le=2.0)
    synthesis_adapter: Literal["client_local_tts", "browser_speech_synthesis"]
    retention_policy_id: Literal["transient-not-persisted"] = "transient-not-persisted"
    source_text_persisted: Literal[False] = False
    audio_generated_by_server: Literal[False] = False
    audio_uploaded: Literal[False] = False
    audio_stored: Literal[False] = False
