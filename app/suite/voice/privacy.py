from hashlib import sha256
from uuid import uuid4

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import DataClass, TenantPolicy, UserContext
from suite.ai_control_plane.policy import PolicyViolation
from suite.voice.models import (
    VoiceSynthesisRequest,
    VoiceSynthesisResponse,
    VoiceTranscriptRequest,
    VoiceTranscriptResponse,
)


class VoicePrivacyGuard:
    def __init__(self, *, audit_logger: InMemoryAuditLogger) -> None:
        self.audit_logger = audit_logger

    def accept_transcript(
        self,
        *,
        request: VoiceTranscriptRequest,
        user_context: UserContext,
        tenant_policy: TenantPolicy,
    ) -> VoiceTranscriptResponse:
        if user_context.tenant_id != tenant_policy.tenant_id:
            raise PolicyViolation("User tenant does not match tenant policy")
        if not tenant_policy.voice_enabled:
            raise PolicyViolation("Voice is disabled for this tenant")
        if not request.push_to_talk_active:
            raise PolicyViolation("Voice input must be explicit push-to-talk or explicitly activated")
        if request.recognition_adapter == "browser_web_speech" and not tenant_policy.external_ai_enabled:
            raise PolicyViolation("Browser speech recognition is disabled by tenant policy")
        if request.requested_raw_audio_storage and not tenant_policy.raw_audio_storage_allowed:
            raise PolicyViolation("Raw audio storage is disabled by tenant policy")

        transcript_id = str(uuid4())
        transcript_hash = "sha256:" + sha256(request.transcript.encode("utf-8")).hexdigest()
        audit_event = self.audit_logger.record(
            user_context=user_context,
            event_type="voice.transcript",
            input_text=request.transcript,
            metadata={
                "transcript_id": transcript_id,
                "classification": DataClass.VOICE_TRANSCRIPT,
                "raw_audio_stored": False,
                "language": request.language,
                "recognition_adapter": request.recognition_adapter,
                "retention_policy_id": "transient-not-persisted",
                "transcript_persisted": False,
            },
        )
        return VoiceTranscriptResponse(
            transcript_id=transcript_id,
            classification=DataClass.VOICE_TRANSCRIPT,
            raw_audio_stored=False,
            audit_event_id=audit_event.event_id,
            transcript_hash=transcript_hash,
            transcript_character_count=len(request.transcript),
            language=request.language,
            recognition_adapter=request.recognition_adapter,
        )

    def admit_synthesis(
        self,
        *,
        request: VoiceSynthesisRequest,
        user_context: UserContext,
        tenant_policy: TenantPolicy,
    ) -> VoiceSynthesisResponse:
        if user_context.tenant_id != tenant_policy.tenant_id:
            raise PolicyViolation("User tenant does not match tenant policy")
        if not tenant_policy.voice_enabled:
            raise PolicyViolation("Voice is disabled for this tenant")
        if not request.explicit_activation:
            raise PolicyViolation("Voice output must be explicitly activated")
        if request.synthesis_adapter == "browser_speech_synthesis" and not tenant_policy.external_ai_enabled:
            raise PolicyViolation("Browser speech synthesis is disabled by tenant policy")
        if request.requested_audio_storage:
            raise PolicyViolation("Read-aloud audio storage is disabled")

        synthesis_id = str(uuid4())
        source_text_hash = "sha256:" + sha256(request.text.encode("utf-8")).hexdigest()
        audit_event = self.audit_logger.record(
            user_context=user_context,
            event_type="voice.synthesis",
            source_object_ids=[],
            input_text=request.text,
            metadata={
                "synthesis_id": synthesis_id,
                "classification": request.classification,
                "language": request.language,
                "rate": request.rate,
                "synthesis_adapter": request.synthesis_adapter,
                "retention_policy_id": "transient-not-persisted",
                "source_text_persisted": False,
                "audio_generated_by_server": False,
                "audio_uploaded": False,
                "audio_stored": False,
            },
        )
        return VoiceSynthesisResponse(
            synthesis_id=synthesis_id,
            classification=request.classification,
            audit_event_id=audit_event.event_id,
            source_text_hash=source_text_hash,
            source_character_count=len(request.text),
            language=request.language,
            rate=request.rate,
            synthesis_adapter=request.synthesis_adapter,
        )
