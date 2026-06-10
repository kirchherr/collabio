from pydantic import BaseModel

from suite.ai_control_plane.models import DataClass


class VoiceTranscriptRequest(BaseModel):
    transcript: str
    push_to_talk_active: bool
    requested_raw_audio_storage: bool = False
    language: str = "de-DE"


class VoiceTranscriptResponse(BaseModel):
    transcript_id: str
    classification: DataClass
    raw_audio_stored: bool
    audit_event_id: str

