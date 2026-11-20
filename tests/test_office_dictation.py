from __future__ import annotations

import pytest
from pydantic import ValidationError

from main import app
from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import DataClass, TenantPolicy
from suite.ai_control_plane.policy import PolicyViolation
from suite.platform.office_api import build_office_dictation_service
from suite.platform.office_dictation import OfficeDictationCommand, OfficeDictationRequestError, OfficeDictationService
from suite.platform.office_documents import (
    OfficeDocumentConflictError,
    OfficeDocumentNotFoundError,
    OfficeDocumentSaveCommand,
)
from suite.voice.privacy import VoicePrivacyGuard
from test_office_ai_rewrite import PRIVATE, RewriteHarness, rewrite_harness
from test_office_documents_api import BASE, OfficeApiHarness, create_document
from test_office_documents_api import office_api as office_api

TRANSCRIPT = "Dies ist ein bewusst diktiertes Stück Text."


def dictation_service(
    harness: RewriteHarness, voice_audit: InMemoryAuditLogger | None = None
) -> tuple[OfficeDictationService, InMemoryAuditLogger]:
    audit = voice_audit or InMemoryAuditLogger()
    return build_office_dictation_service(
        document_service=harness.documents,
        voice_guard=VoicePrivacyGuard(audit_logger=audit),
    ), audit


def voice_policy(harness: RewriteHarness, *, external: bool = False, enabled: bool = True) -> TenantPolicy:
    return TenantPolicy(
        tenant_id=harness.user.tenant_id,
        voice_enabled=enabled,
        external_ai_enabled=external,
        raw_audio_storage_allowed=False,
    )


def command(harness: RewriteHarness, **updates: object) -> OfficeDictationCommand:
    payload = {
        "expected_current_version_id": harness.version_id,
        "insertion_position": 1,
        "transcript": TRANSCRIPT,
        "push_to_talk_active": True,
        "requested_raw_audio_storage": False,
        "language": "de-DE",
        "recognition_adapter": "client_local_stt",
        **updates,
    }
    return OfficeDictationCommand.model_validate(payload)


def test_office_dictation_is_hash_audited_transient_and_requires_explicit_save() -> None:
    harness = rewrite_harness()
    service, voice_audit = dictation_service(harness)
    before = len(harness.repository.saved_versions)

    result = service.prepare(
        user_context=harness.user,
        tenant_policy=voice_policy(harness),
        object_id=harness.object_id,
        command=command(harness),
    )

    assert result.source_version_id == harness.version_id
    assert result.transcript_hash.startswith("sha256:")
    assert result.transcript_character_count == len(TRANSCRIPT)
    assert result.classification == DataClass.VOICE_TRANSCRIPT
    assert result.activation_contract == "explicit_push_to_talk"
    assert result.raw_audio_uploaded is result.raw_audio_stored is False
    assert result.transcript_persisted is result.document_changed is result.ai_used is False
    assert result.requires_explicit_version_save is True
    assert len(harness.repository.saved_versions) == before
    voice_event = voice_audit.events[-1]
    assert voice_event.event_type == "voice.transcript"
    assert voice_event.input_hash == result.transcript_hash
    assert TRANSCRIPT not in str(voice_event.model_dump(mode="json"))
    office_event = harness.document_audit.events[-1]
    assert office_event.event_type == "office.voice.dictation_prepared"
    assert office_event.metadata["transcript_hash"] == result.transcript_hash
    assert TRANSCRIPT not in str(office_event.model_dump(mode="json"))
    assert PRIVATE not in str(office_event.model_dump(mode="json"))


def test_office_dictation_capability_exposes_policy_without_enabling_raw_audio() -> None:
    harness = rewrite_harness()
    service, _ = dictation_service(harness)

    local = service.capability(
        user_context=harness.user,
        tenant_policy=voice_policy(harness),
        object_id=harness.object_id,
        expected_current_version_id=harness.version_id,
    )
    browser = service.capability(
        user_context=harness.user,
        tenant_policy=voice_policy(harness, external=True),
        object_id=harness.object_id,
        expected_current_version_id=harness.version_id,
    )

    assert local.voice_enabled is local.client_local_stt_allowed is True
    assert local.browser_speech_recognition_allowed is False
    assert browser.browser_speech_recognition_allowed is True
    assert browser.raw_audio_upload_allowed is browser.raw_audio_storage_allowed is False
    assert browser.transcript_persisted is False


def test_office_dictation_revalidates_acl_and_exact_current_version() -> None:
    harness = rewrite_harness()
    service, voice_audit = dictation_service(harness)
    denied = harness.user.model_copy(update={"user_id": "unknown", "readable_object_ids": {harness.object_id}})

    with pytest.raises(OfficeDocumentNotFoundError):
        service.prepare(
            user_context=denied,
            tenant_policy=voice_policy(harness),
            object_id=harness.object_id,
            command=command(harness),
        )

    harness.documents.save(
        user_context=harness.user,
        object_id=harness.object_id,
        write_enabled=True,
        command=OfficeDocumentSaveCommand(
            title="Newer",
            document={"type": "doc", "content": [{"type": "paragraph", "content": []}]},
            expected_current_version_id=harness.version_id,
            mutation_reference="dictation-newer",
            human_confirmation=True,
        ),
    )
    with pytest.raises(OfficeDocumentConflictError):
        service.prepare(
            user_context=harness.user,
            tenant_policy=voice_policy(harness),
            object_id=harness.object_id,
            command=command(harness),
        )
    assert not voice_audit.events


def test_office_dictation_fails_closed_for_activation_policy_adapter_and_position() -> None:
    harness = rewrite_harness()
    service, _ = dictation_service(harness)
    with pytest.raises(PolicyViolation):
        service.prepare(
            user_context=harness.user,
            tenant_policy=voice_policy(harness, enabled=False),
            object_id=harness.object_id,
            command=command(harness),
        )
    with pytest.raises(PolicyViolation):
        service.prepare(
            user_context=harness.user,
            tenant_policy=voice_policy(harness),
            object_id=harness.object_id,
            command=command(harness, push_to_talk_active=False),
        )
    with pytest.raises(PolicyViolation):
        service.prepare(
            user_context=harness.user,
            tenant_policy=voice_policy(harness),
            object_id=harness.object_id,
            command=command(harness, recognition_adapter="browser_web_speech"),
        )
    with pytest.raises(PolicyViolation):
        service.prepare(
            user_context=harness.user,
            tenant_policy=voice_policy(harness),
            object_id=harness.object_id,
            command=command(harness, requested_raw_audio_storage=True),
        )
    with pytest.raises(OfficeDictationRequestError):
        service.prepare(
            user_context=harness.user,
            tenant_policy=voice_policy(harness),
            object_id=harness.object_id,
            command=command(harness, insertion_position=100_000),
        )
    with pytest.raises(ValidationError):
        command(harness, instruction="keep listening after release")


def test_office_dictation_api_is_write_gated_noncacheable_and_never_saves(
    office_api: OfficeApiHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = create_document(office_api)
    object_id = current["document"]["object_id"]
    voice_audit = InMemoryAuditLogger()
    monkeypatch.setattr(
        app.state,
        "office_dictation_service",
        build_office_dictation_service(
            document_service=office_api.service,
            voice_guard=VoicePrivacyGuard(audit_logger=voice_audit),
        ),
    )
    before = len(office_api.repository.saved_versions)
    capability = office_api.client.get(
        f"{BASE}/{object_id}/voice/dictation-capability",
        params={"expected_current_version_id": current["version"]["version_id"]},
        headers=office_api.headers,
    )
    assert capability.status_code == 200, capability.text
    assert capability.headers["Cache-Control"] == "no-store"
    assert capability.json()["push_to_talk_required"] is True
    prepared = office_api.client.post(
        f"{BASE}/{object_id}/voice/dictations",
        headers=office_api.headers,
        json={
            "expected_current_version_id": current["version"]["version_id"],
            "insertion_position": 1,
            "transcript": TRANSCRIPT,
            "push_to_talk_active": True,
            "requested_raw_audio_storage": False,
            "language": "de-DE",
            "recognition_adapter": "client_local_stt",
        },
    )
    assert prepared.status_code == 200, prepared.text
    assert prepared.headers["Cache-Control"] == "no-store"
    assert prepared.json()["document_changed"] is False
    assert prepared.json()["transcript_persisted"] is False
    assert len(office_api.repository.saved_versions) == before
