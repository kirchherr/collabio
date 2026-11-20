from __future__ import annotations

import pytest
from pydantic import ValidationError

from main import app
from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import DataClass, TenantPolicy
from suite.ai_control_plane.policy import PolicyViolation
from suite.platform.office_api import build_office_read_aloud_service
from suite.platform.office_documents import (
    OfficeDocumentConflictError,
    OfficeDocumentNotFoundError,
    OfficeDocumentSaveCommand,
)
from suite.platform.office_read_aloud import OfficeReadAloudCommand, OfficeReadAloudService
from suite.voice.privacy import VoicePrivacyGuard
from test_office_ai_rewrite import PRIVATE, RewriteHarness, rewrite_harness
from test_office_documents_api import BASE, OfficeApiHarness, create_document, enable_office
from test_office_documents_api import office_api as office_api


def read_aloud_service(
    harness: RewriteHarness, voice_audit: InMemoryAuditLogger | None = None
) -> tuple[OfficeReadAloudService, InMemoryAuditLogger]:
    audit = voice_audit or InMemoryAuditLogger()
    return build_office_read_aloud_service(
        document_service=harness.documents,
        voice_guard=VoicePrivacyGuard(audit_logger=audit),
    ), audit


def voice_policy(harness: RewriteHarness, *, external: bool = False, enabled: bool = True) -> TenantPolicy:
    return TenantPolicy(tenant_id=harness.user.tenant_id, voice_enabled=enabled, external_ai_enabled=external)


def command(harness: RewriteHarness, **updates: object) -> OfficeReadAloudCommand:
    return OfficeReadAloudCommand.model_validate(
        {
            "expected_current_version_id": harness.version_id,
            "anchor": {"from": 1, "to": 16},
            "explicit_activation": True,
            "requested_audio_storage": False,
            "language": "de-DE",
            "rate": 1.0,
            "synthesis_adapter": "client_local_tts",
            **updates,
        }
    )


def test_read_aloud_derives_exact_saved_selection_and_audits_only_hashes() -> None:
    harness = rewrite_harness()
    service, voice_audit = read_aloud_service(harness)
    before = len(harness.repository.saved_versions)

    result = service.prepare(
        user_context=harness.user,
        tenant_policy=voice_policy(harness),
        object_id=harness.object_id,
        command=command(harness),
    )

    assert result.source_text == PRIVATE[:15]
    assert result.source_anchor.model_dump(by_alias=True) == {"from": 1, "to": 16}
    assert result.source_text_hash.startswith("sha256:")
    assert result.source_character_count == 15
    assert result.classification == DataClass.INTERNAL
    assert result.activation_contract == "explicit_read_aloud"
    assert result.source_text_persisted is result.audio_generated_by_server is False
    assert result.audio_uploaded is result.audio_stored is result.document_changed is False
    assert result.ai_used is result.rag_indexing_allowed is result.search_indexing_allowed is False
    assert len(harness.repository.saved_versions) == before
    voice_event = voice_audit.events[-1]
    assert voice_event.event_type == "voice.synthesis"
    assert voice_event.input_hash == result.source_text_hash
    assert result.source_text not in str(voice_event.model_dump(mode="json"))
    office_event = harness.document_audit.events[-1]
    assert office_event.event_type == "office.voice.read_aloud_prepared"
    assert office_event.metadata["source_text_hash"] == result.source_text_hash
    assert PRIVATE not in str(office_event.model_dump(mode="json"))


def test_read_aloud_capability_is_read_only_and_provider_policy_bound() -> None:
    harness = rewrite_harness()
    service, _ = read_aloud_service(harness)
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

    assert local.voice_enabled is local.client_local_tts_allowed is True
    assert local.browser_speech_synthesis_allowed is False
    assert browser.browser_speech_synthesis_allowed is True
    assert browser.document_read_authorized is True
    assert browser.audio_generated_by_server is browser.audio_upload_allowed is browser.audio_storage_allowed is False
    assert browser.source_text_persisted is False


def test_read_aloud_revalidates_acl_and_exact_current_version() -> None:
    harness = rewrite_harness()
    service, voice_audit = read_aloud_service(harness)
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
            mutation_reference="read-aloud-newer",
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


def test_read_aloud_fails_closed_for_activation_provider_storage_and_schema() -> None:
    harness = rewrite_harness()
    service, _ = read_aloud_service(harness)
    for request, policy in (
        (command(harness), voice_policy(harness, enabled=False)),
        (command(harness, explicit_activation=False), voice_policy(harness)),
        (command(harness, requested_audio_storage=True), voice_policy(harness)),
        (command(harness, synthesis_adapter="browser_speech_synthesis"), voice_policy(harness)),
    ):
        with pytest.raises(PolicyViolation):
            service.prepare(
                user_context=harness.user,
                tenant_policy=policy,
                object_id=harness.object_id,
                command=request,
            )
    with pytest.raises(ValidationError):
        command(harness, text="browser supplied secret")
    with pytest.raises(ValidationError):
        command(harness, rate=3.0)


def test_read_aloud_api_is_read_gated_noncacheable_and_never_writes(
    office_api: OfficeApiHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = create_document(office_api)
    object_id = current["document"]["object_id"]
    voice_audit = InMemoryAuditLogger()
    monkeypatch.setattr(
        app.state,
        "office_read_aloud_service",
        build_office_read_aloud_service(
            document_service=office_api.service,
            voice_guard=VoicePrivacyGuard(audit_logger=voice_audit),
        ),
    )
    before = len(office_api.repository.saved_versions)
    enable_office(read=True, write=False)
    capability = office_api.client.get(
        f"{BASE}/{object_id}/voice/read-aloud-capability",
        params={"expected_current_version_id": current["version"]["version_id"]},
        headers=office_api.headers,
    )
    assert capability.status_code == 200, capability.text
    assert capability.headers["Cache-Control"] == "no-store"
    prepared = office_api.client.post(
        f"{BASE}/{object_id}/voice/read-aloud-preparations",
        headers=office_api.headers,
        json={
            "expected_current_version_id": current["version"]["version_id"],
            "anchor": {"from": 1, "to": 15},
            "explicit_activation": True,
            "requested_audio_storage": False,
            "language": "de-DE",
            "rate": 1.0,
            "synthesis_adapter": "client_local_tts",
        },
    )
    assert prepared.status_code == 200, prepared.text
    assert prepared.headers["Cache-Control"] == "no-store"
    assert prepared.json()["source_text"] == "OFFICE PRIVATE"
    assert prepared.json()["document_changed"] is False
    assert prepared.json()["audio_stored"] is False
    assert len(office_api.repository.saved_versions) == before
