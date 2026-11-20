from __future__ import annotations

from hashlib import sha256
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from suite.ai_control_plane.models import DataClass, TenantPolicy, UserContext
from suite.platform.office_documents import OfficeDocumentConflictError, OfficeDocumentService
from suite.platform.office_reviews import ReviewAnchor, derive_review_quote
from suite.voice.models import VoiceSynthesisRequest
from suite.voice.privacy import VoicePrivacyGuard

OFFICE_READ_ALOUD_POLICY_ID = "office_explicit_read_aloud_v1"


class OfficeReadAloudCapabilityResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    object_id: str
    source_version_id: str
    voice_enabled: bool
    explicit_activation_required: Literal[True] = True
    browser_speech_synthesis_allowed: bool
    client_local_tts_allowed: bool
    audio_generated_by_server: Literal[False] = False
    audio_upload_allowed: Literal[False] = False
    audio_storage_allowed: Literal[False] = False
    source_text_persisted: Literal[False] = False
    document_read_authorized: Literal[True] = True
    policy_id: str = OFFICE_READ_ALOUD_POLICY_ID
    audit_event_id: str


class OfficeReadAloudCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_current_version_id: str = Field(pattern=r"^office-version-[a-f0-9]{32}$")
    anchor: ReviewAnchor
    explicit_activation: bool = Field(strict=True)
    requested_audio_storage: bool = Field(default=False, strict=True)
    language: str = Field(default="de-DE", pattern=r"^[a-z]{2}-[A-Z]{2}$")
    rate: float = Field(default=1.0, ge=0.5, le=2.0)
    synthesis_adapter: Literal["client_local_tts", "browser_speech_synthesis"]


class OfficeReadAloudResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    object_id: str
    source_version_id: str
    source_anchor: ReviewAnchor
    source_text: str = Field(min_length=1, max_length=2000)
    source_text_hash: str
    source_character_count: int = Field(ge=1, le=2000)
    classification: DataClass
    language: str
    rate: float = Field(ge=0.5, le=2.0)
    synthesis_adapter: Literal["client_local_tts", "browser_speech_synthesis"]
    synthesis_id: str
    voice_audit_event_id: str
    audit_event_id: str
    policy_id: str = OFFICE_READ_ALOUD_POLICY_ID
    activation_contract: Literal["explicit_read_aloud"] = "explicit_read_aloud"
    retention_policy_id: Literal["transient-not-persisted"] = "transient-not-persisted"
    source_text_persisted: Literal[False] = False
    audio_generated_by_server: Literal[False] = False
    audio_uploaded: Literal[False] = False
    audio_stored: Literal[False] = False
    document_changed: Literal[False] = False
    ai_used: Literal[False] = False
    rag_indexing_allowed: Literal[False] = False
    search_indexing_allowed: Literal[False] = False


class OfficeReadAloudService:
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
    ) -> OfficeReadAloudCapabilityResponse:
        source = self._current_source(
            user_context=user_context,
            object_id=object_id,
            expected_current_version_id=expected_current_version_id,
        )
        event_id = self.documents._audit(
            user_context,
            "office.voice.read_aloud_capability.read",
            object_id=object_id,
            version_id=source.version.version_id,
            voice_enabled=tenant_policy.voice_enabled,
            browser_speech_synthesis_allowed=tenant_policy.voice_enabled and tenant_policy.external_ai_enabled,
            client_local_tts_allowed=tenant_policy.voice_enabled,
            audio_generated_by_server=False,
            audio_upload_allowed=False,
            audio_storage_allowed=False,
            source_text_persisted=False,
            policy_id=OFFICE_READ_ALOUD_POLICY_ID,
        )
        return OfficeReadAloudCapabilityResponse(
            tenant_id=user_context.tenant_id,
            object_id=object_id,
            source_version_id=source.version.version_id,
            voice_enabled=tenant_policy.voice_enabled,
            browser_speech_synthesis_allowed=tenant_policy.voice_enabled and tenant_policy.external_ai_enabled,
            client_local_tts_allowed=tenant_policy.voice_enabled,
            audit_event_id=event_id,
        )

    def prepare(
        self,
        *,
        user_context: UserContext,
        tenant_policy: TenantPolicy,
        object_id: str,
        command: OfficeReadAloudCommand,
    ) -> OfficeReadAloudResponse:
        source = self._current_source(
            user_context=user_context,
            object_id=object_id,
            expected_current_version_id=command.expected_current_version_id,
        )
        selection = derive_review_quote(source.content, command.anchor)
        if selection is None:
            raise ValueError("Office read aloud requires a saved text selection")
        classification = _data_class(source.version.information_classification)
        admitted = self.voice_guard.admit_synthesis(
            request=VoiceSynthesisRequest(
                text=selection,
                explicit_activation=command.explicit_activation,
                requested_audio_storage=command.requested_audio_storage,
                language=command.language,
                rate=command.rate,
                synthesis_adapter=command.synthesis_adapter,
                classification=classification,
            ),
            user_context=user_context,
            tenant_policy=tenant_policy,
        )
        event_id = self.documents._audit(
            user_context,
            "office.voice.read_aloud_prepared",
            object_id=object_id,
            version_id=source.version.version_id,
            source_anchor=command.anchor.model_dump(mode="json", by_alias=True),
            source_text_hash=admitted.source_text_hash,
            source_character_count=admitted.source_character_count,
            classification=classification,
            language=admitted.language,
            rate=admitted.rate,
            synthesis_adapter=admitted.synthesis_adapter,
            synthesis_id=admitted.synthesis_id,
            voice_audit_event_id=admitted.audit_event_id,
            activation_contract="explicit_read_aloud",
            source_text_persisted=False,
            audio_generated_by_server=False,
            audio_uploaded=False,
            audio_stored=False,
            document_changed=False,
            ai_used=False,
            rag_indexing_allowed=False,
            search_indexing_allowed=False,
            policy_id=OFFICE_READ_ALOUD_POLICY_ID,
        )
        return OfficeReadAloudResponse(
            tenant_id=user_context.tenant_id,
            object_id=object_id,
            source_version_id=source.version.version_id,
            source_anchor=command.anchor,
            source_text=selection,
            source_text_hash="sha256:" + sha256(selection.encode("utf-8")).hexdigest(),
            source_character_count=admitted.source_character_count,
            classification=classification,
            language=admitted.language,
            rate=admitted.rate,
            synthesis_adapter=admitted.synthesis_adapter,
            synthesis_id=admitted.synthesis_id,
            voice_audit_event_id=admitted.audit_event_id,
            audit_event_id=event_id,
        )

    def _current_source(
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
            write_enabled=False,
        )
        if not source.is_current_version or source.document.current_version_id != expected_current_version_id:
            raise OfficeDocumentConflictError("Office read aloud requires the current saved document version")
        return source


def _data_class(information_classification: str) -> DataClass:
    if information_classification == "public":
        return DataClass.PUBLIC
    if information_classification in {"confidential", "restricted"}:
        return DataClass.CONFIDENTIAL
    return DataClass.INTERNAL
