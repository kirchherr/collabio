from uuid import uuid4

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import DataClass, TenantPolicy, UserContext
from suite.ai_control_plane.policy import PolicyViolation
from suite.voice.models import VoiceTranscriptRequest, VoiceTranscriptResponse


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
        if request.requested_raw_audio_storage and not tenant_policy.raw_audio_storage_allowed:
            raise PolicyViolation("Raw audio storage is disabled by tenant policy")

        transcript_id = str(uuid4())
        audit_event = self.audit_logger.record(
            user_context=user_context,
            event_type="voice.transcript",
            input_text=request.transcript,
            metadata={
                "transcript_id": transcript_id,
                "classification": DataClass.VOICE_TRANSCRIPT,
                "raw_audio_stored": False,
                "language": request.language,
            },
        )
        return VoiceTranscriptResponse(
            transcript_id=transcript_id,
            classification=DataClass.VOICE_TRANSCRIPT,
            raw_audio_stored=False,
            audit_event_id=audit_event.event_id,
        )

