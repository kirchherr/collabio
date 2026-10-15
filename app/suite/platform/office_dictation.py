from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from suite.ai_control_plane.models import DataClass, TenantPolicy, UserContext
from suite.ai_control_plane.policy import PolicyViolation
from suite.platform.office_documents import (
    OfficeDocumentConflictError,
    OfficeDocumentPermissionError,
    OfficeDocumentService,
)
from suite.voice.models import VoiceTranscriptRequest
from suite.voice.privacy import VoicePrivacyGuard

OFFICE_DICTATION_POLICY_ID = "office_push_to_talk_transcript_v1"


class OfficeDictationRequestError(ValueError):
    pass


class OfficeDictationCapabilityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    object_id: str
    source_version_id: str
    voice_enabled: bool
    push_to_talk_required: Literal[True] = True
    browser_speech_recognition_allowed: bool
    client_local_stt_allowed: bool
    raw_audio_upload_allowed: Literal[False] = False
    raw_audio_storage_allowed: Literal[False] = False
    transcript_persisted: Literal[False] = False
    document_write_authorized: Literal[True] = True
    policy_id: str = OFFICE_DICTATION_POLICY_ID
    audit_event_id: str


class OfficeDictationCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_current_version_id: str = Field(pattern=r"^office-version-[a-f0-9]{32}$")
    insertion_position: int = Field(ge=1)
    transcript: str = Field(min_length=1, max_length=4000)
    push_to_talk_active: bool = Field(strict=True)
    requested_raw_audio_storage: bool = Field(default=False, strict=True)
    language: str = Field(default="de-DE", pattern=r"^[a-z]{2}-[A-Z]{2}$")
    recognition_adapter: Literal["client_local_stt", "browser_web_speech"]

    @field_validator("transcript")
    @classmethod
    def validate_transcript(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized or any(
            (ord(character) < 32 and character not in "\n\t") or 0xD800 <= ord(character) <= 0xDFFF
            for character in value
        ):
            raise ValueError("Office dictation transcript is invalid")
        return normalized


class OfficeDictationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    object_id: str
    source_version_id: str
    insertion_position: int = Field(ge=1)
    transcript_id: str
    transcript_hash: str
    transcript_character_count: int = Field(ge=1, le=4000)
    language: str
    recognition_adapter: Literal["client_local_stt", "browser_web_speech"]
    classification: Literal[DataClass.VOICE_TRANSCRIPT] = DataClass.VOICE_TRANSCRIPT
    retention_policy_id: Literal["transient-not-persisted"] = "transient-not-persisted"
    voice_audit_event_id: str
    audit_event_id: str
    policy_id: str = OFFICE_DICTATION_POLICY_ID
    activation_contract: Literal["explicit_push_to_talk"] = "explicit_push_to_talk"
    raw_audio_uploaded: Literal[False] = False
    raw_audio_stored: Literal[False] = False
    transcript_persisted: Literal[False] = False
    document_changed: Literal[False] = False
    requires_explicit_version_save: Literal[True] = True
    ai_used: Literal[False] = False
    rag_indexing_allowed: Literal[False] = False
    search_indexing_allowed: Literal[False] = False


class OfficeDictationService:
    def __init__(self, *, documents: OfficeDocumentService, voice_guard: VoicePrivacyGuard) -> None:
        self.documents = documents
        self.voice_guard = voice_guard

    def capability(
        self,
        *,
        user_context: UserContext,
        tenant_policy: TenantPolicy,
        object_id: str,
        expected_current_version_id: str,
    ) -> OfficeDictationCapabilityResponse:
        source = self._writable_current_source(
            user_context=user_context,
            object_id=object_id,
            expected_current_version_id=expected_current_version_id,
        )
        event_id = self.documents._audit(
            user_context,
            "office.voice.dictation_capability.read",
            object_id=object_id,
            version_id=source.version.version_id,
            voice_enabled=tenant_policy.voice_enabled,
            browser_speech_recognition_allowed=tenant_policy.voice_enabled and tenant_policy.external_ai_enabled,
            client_local_stt_allowed=tenant_policy.voice_enabled,
            raw_audio_upload_allowed=False,
            raw_audio_storage_allowed=False,
            transcript_persisted=False,
            policy_id=OFFICE_DICTATION_POLICY_ID,
        )
        return OfficeDictationCapabilityResponse(
            tenant_id=user_context.tenant_id,
            object_id=object_id,
            source_version_id=source.version.version_id,
            voice_enabled=tenant_policy.voice_enabled,
            browser_speech_recognition_allowed=tenant_policy.voice_enabled and tenant_policy.external_ai_enabled,
            client_local_stt_allowed=tenant_policy.voice_enabled,
            audit_event_id=event_id,
        )

    def prepare(
        self,
        *,
        user_context: UserContext,
        tenant_policy: TenantPolicy,
        object_id: str,
        command: OfficeDictationCommand,
    ) -> OfficeDictationResponse:
        source = self._writable_current_source(
            user_context=user_context,
            object_id=object_id,
            expected_current_version_id=command.expected_current_version_id,
        )
        maximum_position = max(1, _prosemirror_content_size(source.content) - 1)
        if command.insertion_position > maximum_position:
            raise OfficeDictationRequestError("Office dictation insertion position is outside the saved document")
        if command.requested_raw_audio_storage:
            raise PolicyViolation("Office dictation does not upload or store raw audio")
        if command.recognition_adapter == "browser_web_speech" and not tenant_policy.external_ai_enabled:
            raise PolicyViolation("Browser speech recognition is disabled by tenant policy")

        transcript = self.voice_guard.accept_transcript(
            request=VoiceTranscriptRequest(
                transcript=command.transcript,
                push_to_talk_active=command.push_to_talk_active,
                requested_raw_audio_storage=command.requested_raw_audio_storage,
                language=command.language,
                recognition_adapter=command.recognition_adapter,
            ),
            user_context=user_context,
            tenant_policy=tenant_policy,
        )
        event_id = self.documents._audit(
            user_context,
            "office.voice.dictation_prepared",
            object_id=object_id,
            version_id=source.version.version_id,
            insertion_position=command.insertion_position,
            transcript_id=transcript.transcript_id,
            transcript_hash=transcript.transcript_hash,
            transcript_character_count=transcript.transcript_character_count,
            language=transcript.language,
            recognition_adapter=transcript.recognition_adapter,
            voice_audit_event_id=transcript.audit_event_id,
            activation_contract="explicit_push_to_talk",
            raw_audio_uploaded=False,
            raw_audio_stored=False,
            transcript_persisted=False,
            document_changed=False,
            requires_explicit_version_save=True,
            ai_used=False,
            rag_indexing_allowed=False,
            search_indexing_allowed=False,
            policy_id=OFFICE_DICTATION_POLICY_ID,
        )
        return OfficeDictationResponse(
            tenant_id=user_context.tenant_id,
            object_id=object_id,
            source_version_id=source.version.version_id,
            insertion_position=command.insertion_position,
            transcript_id=transcript.transcript_id,
            transcript_hash=transcript.transcript_hash,
            transcript_character_count=transcript.transcript_character_count,
            language=transcript.language,
            recognition_adapter=transcript.recognition_adapter,
            voice_audit_event_id=transcript.audit_event_id,
            audit_event_id=event_id,
        )

    def _writable_current_source(
        self,
        *,
        user_context: UserContext,
        object_id: str,
        expected_current_version_id: str,
    ) -> Any:
        source = self.documents.read_content(
            user_context=user_context,
            object_id=object_id,
            version_id=expected_current_version_id,
            write_enabled=True,
        )
        if not source.can_write:
            raise OfficeDocumentPermissionError("Office dictation requires document write access")
        if not source.is_current_version or source.document.current_version_id != expected_current_version_id:
            raise OfficeDocumentConflictError("Office dictation requires the current saved document version")
        return source


def _prosemirror_content_size(document: dict[str, Any]) -> int:
    def node_size(node: dict[str, Any]) -> int:
        if node.get("type") == "text":
            return len(str(node.get("text", "")).encode("utf-16-le")) // 2
        return 2 + sum(node_size(child) for child in node.get("content", []))

    return sum(node_size(child) for child in document.get("content", []))
