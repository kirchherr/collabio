from collections.abc import Callable
from pathlib import Path

import pytest

from suite.ai_control_plane.models import DataClass
from suite.kms.adapter import (
    KmsDestroyKeyCommand,
    KmsKeyUse,
    KmsOperation,
    KmsPolicyViolation,
    LocalKmsAdapter,
    load_kms_adapter_policy,
)
from suite.kms.envelope import (
    EnvelopeDecryptionRequest,
    EnvelopeEncryptionError,
    EnvelopeEncryptionManifest,
    EnvelopeEncryptionRequest,
    EnvelopeRewrapRequest,
    LocalEnvelopeEncryptionService,
    build_envelope_encryption_manifest_hash,
)
from suite.storage.content_hash import compute_content_hash

REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = REPO_ROOT / "docs" / "kms_adapter_policy.json"


def fixed_bytes(value: int) -> Callable[[int], bytes]:
    return lambda size: bytes([value]) * size


def service_for_tests() -> tuple[LocalEnvelopeEncryptionService, LocalKmsAdapter]:
    kms_adapter = LocalKmsAdapter(load_kms_adapter_policy(POLICY_PATH))
    service = LocalEnvelopeEncryptionService(
        kms_adapter,
        data_key_generator=fixed_bytes(17),
        nonce_generator=fixed_bytes(34),
    )
    return service, kms_adapter


def encryption_request(
    *,
    data_class: DataClass = DataClass.INTERNAL,
    kms_key_ref: str = "kms://tenant-1/internal/v1",
) -> EnvelopeEncryptionRequest:
    return EnvelopeEncryptionRequest(
        tenant_id="tenant-1",
        object_id="doc-1",
        source_version_id="v1",
        data_class=data_class,
        kms_key_ref=kms_key_ref,
        plaintext=b"envelope governed source bytes",
        aad={"storage_manifest_hash": "sha256:" + "a" * 64},
        requested_by="user-storage",
        audit_chain_ref="audit:envelope-encrypt",
        occurred_at_utc="2026-06-11T03:00:00Z",
    )


def decryption_request(
    *,
    ciphertext: bytes,
    manifest: EnvelopeEncryptionManifest,
    aad: dict[str, str] | None = None,
    kms_key_ref: str | None = None,
) -> EnvelopeDecryptionRequest:
    return EnvelopeDecryptionRequest(
        tenant_id=manifest.tenant_id,
        object_id=manifest.object_id,
        source_version_id=manifest.source_version_id,
        data_class=manifest.data_class,
        kms_key_ref=kms_key_ref or manifest.kms_key_ref,
        ciphertext=ciphertext,
        manifest=manifest,
        aad=aad if aad is not None else {"storage_manifest_hash": "sha256:" + "a" * 64},
        requested_by="user-storage",
        audit_chain_ref="audit:envelope-decrypt",
        occurred_at_utc="2026-06-11T03:05:00Z",
    )


def rewrap_request(
    *,
    ciphertext: bytes,
    manifest: EnvelopeEncryptionManifest,
    aad: dict[str, str] | None = None,
    current_kms_key_ref: str | None = None,
    new_kms_key_ref: str | None = None,
) -> EnvelopeRewrapRequest:
    default_new_kms_key_ref = manifest.kms_key_ref.rsplit("/", maxsplit=1)[0] + "/v2"
    return EnvelopeRewrapRequest(
        tenant_id=manifest.tenant_id,
        object_id=manifest.object_id,
        source_version_id=manifest.source_version_id,
        data_class=manifest.data_class,
        ciphertext=ciphertext,
        manifest=manifest,
        aad=aad if aad is not None else {"storage_manifest_hash": "sha256:" + "a" * 64},
        current_kms_key_ref=current_kms_key_ref or manifest.kms_key_ref,
        new_kms_key_ref=new_kms_key_ref or default_new_kms_key_ref,
        requested_by="user-kms",
        approved_by="user-security",
        audit_chain_ref="audit:envelope-rewrap",
        occurred_at_utc="2026-06-11T03:10:00Z",
        reason="scheduled key rotation",
    )


def destroy_personal_key_command() -> KmsDestroyKeyCommand:
    return KmsDestroyKeyCommand(
        tenant_id="tenant-1",
        data_class=DataClass.PERSONAL,
        kms_key_ref="kms://tenant-1/personal/v1",
        retention_policy_id="rp-standard",
        legal_hold_state="none",
        lifecycle_state="working",
        requested_by="user-privacy",
        approved_by="user-approver",
        approval_ref="approval:key-destroy-1",
        audit_chain_ref="audit:kms-destroy",
        occurred_at_utc="2026-06-11T04:00:00Z",
        reason="privacy deletion drill",
    )


def test_local_envelope_encryption_roundtrip_produces_manifest_and_kms_evidence() -> None:
    service, _kms_adapter = service_for_tests()
    request = encryption_request()

    encrypted = service.encrypt(request)
    decrypted = service.decrypt(
        decryption_request(
            ciphertext=encrypted.ciphertext,
            manifest=encrypted.manifest,
        )
    )

    assert encrypted.ciphertext != request.plaintext
    assert encrypted.manifest.plaintext_hash == compute_content_hash(request.plaintext)
    assert encrypted.manifest.ciphertext_hash == compute_content_hash(encrypted.ciphertext)
    assert encrypted.manifest.manifest_hash == build_envelope_encryption_manifest_hash(encrypted.manifest)
    assert encrypted.manifest.kms_evidence_hash == encrypted.kms_evidence.evidence_hash
    assert encrypted.kms_evidence.key_use == KmsKeyUse.ENVELOPE_ENCRYPTION_PREP
    assert encrypted.kms_evidence.raw_key_material_exposed is False
    assert decrypted.plaintext == request.plaintext
    assert decrypted.verified is True
    assert decrypted.kms_evidence.key_use == KmsKeyUse.ENVELOPE_DECRYPTION


def test_envelope_manifest_does_not_expose_raw_key_material() -> None:
    service, _kms_adapter = service_for_tests()

    encrypted = service.encrypt(encryption_request())
    manifest_payload = encrypted.manifest.model_dump(mode="json")

    assert "wrapped_data_key_b64" in manifest_payload
    assert "data_key" not in manifest_payload
    assert "raw_key" not in manifest_payload
    assert "plaintext_key" not in manifest_payload
    assert encrypted.kms_evidence.raw_key_material_exposed is False


def test_envelope_decryption_rejects_aad_mismatch() -> None:
    service, _kms_adapter = service_for_tests()
    encrypted = service.encrypt(encryption_request())

    with pytest.raises(EnvelopeEncryptionError, match="AAD hash"):
        service.decrypt(
            decryption_request(
                ciphertext=encrypted.ciphertext,
                manifest=encrypted.manifest,
                aad={"storage_manifest_hash": "sha256:" + "b" * 64},
            )
        )


def test_envelope_decryption_rejects_kms_reference_mismatch() -> None:
    service, _kms_adapter = service_for_tests()
    encrypted = service.encrypt(encryption_request())

    with pytest.raises(EnvelopeEncryptionError, match="kms_key_ref"):
        service.decrypt(
            decryption_request(
                ciphertext=encrypted.ciphertext,
                manifest=encrypted.manifest,
                kms_key_ref="kms://tenant-1/confidential/v1",
            )
        )


def test_envelope_decryption_rejects_tampered_manifest_hash() -> None:
    service, _kms_adapter = service_for_tests()
    encrypted = service.encrypt(encryption_request())
    tampered_manifest = encrypted.manifest.model_copy(update={"plaintext_hash": "sha256:" + "1" * 64})

    with pytest.raises(EnvelopeEncryptionError, match="manifest_hash"):
        service.decrypt(
            decryption_request(
                ciphertext=encrypted.ciphertext,
                manifest=tampered_manifest,
            )
        )


def test_envelope_decryption_rejects_tampered_ciphertext() -> None:
    service, _kms_adapter = service_for_tests()
    encrypted = service.encrypt(encryption_request())
    tampered = encrypted.ciphertext[:-1] + bytes([encrypted.ciphertext[-1] ^ 1])

    with pytest.raises(EnvelopeEncryptionError, match="ciphertext hash"):
        service.decrypt(
            decryption_request(
                ciphertext=tampered,
                manifest=encrypted.manifest,
            )
        )


def test_envelope_decryption_rejects_wrapped_data_key_hash_mismatch() -> None:
    service, _kms_adapter = service_for_tests()
    encrypted = service.encrypt(encryption_request())
    tampered_draft = encrypted.manifest.model_copy(update={"wrapped_data_key_hash": "sha256:" + "d" * 64})
    tampered_manifest = tampered_draft.model_copy(
        update={"manifest_hash": build_envelope_encryption_manifest_hash(tampered_draft)}
    )

    with pytest.raises(EnvelopeEncryptionError, match="wrapped data key hash"):
        service.decrypt(
            decryption_request(
                ciphertext=encrypted.ciphertext,
                manifest=tampered_manifest,
            )
        )


def test_envelope_decryption_rejects_destroyed_key_version() -> None:
    service, kms_adapter = service_for_tests()
    encrypted = service.encrypt(
        encryption_request(
            data_class=DataClass.PERSONAL,
            kms_key_ref="kms://tenant-1/personal/v1",
        )
    )
    kms_adapter.record_key_destruction(destroy_personal_key_command())

    with pytest.raises(KmsPolicyViolation, match="destroyed"):
        service.decrypt(
            decryption_request(
                ciphertext=encrypted.ciphertext,
                manifest=encrypted.manifest,
            )
        )


def test_envelope_rewrap_rotates_wrapped_key_and_preserves_decryptability() -> None:
    service, _kms_adapter = service_for_tests()
    request = encryption_request()
    encrypted = service.encrypt(request)

    rewrapped = service.rewrap(
        rewrap_request(
            ciphertext=encrypted.ciphertext,
            manifest=encrypted.manifest,
            new_kms_key_ref="kms://tenant-1/internal/v2",
        )
    )
    decrypted = service.decrypt(
        decryption_request(
            ciphertext=encrypted.ciphertext,
            manifest=rewrapped.manifest,
        )
    )

    assert rewrapped.verified is True
    assert rewrapped.previous_manifest_hash == encrypted.manifest.manifest_hash
    assert rewrapped.manifest.previous_manifest_hash == encrypted.manifest.manifest_hash
    assert rewrapped.previous_kms_key_ref == encrypted.manifest.kms_key_ref
    assert rewrapped.new_kms_key_ref == "kms://tenant-1/internal/v2"
    assert rewrapped.kms_rotation_evidence.operation == KmsOperation.ROTATE_KEY_REFERENCE
    assert rewrapped.kms_rotation_evidence.key_use == KmsKeyUse.KEY_ROTATION
    assert rewrapped.manifest.kms_key_ref == "kms://tenant-1/internal/v2"
    assert rewrapped.manifest.previous_kms_key_ref == encrypted.manifest.kms_key_ref
    assert rewrapped.manifest.rotation_evidence_hash == rewrapped.kms_rotation_evidence.evidence_hash
    assert rewrapped.manifest.kms_evidence_hash == rewrapped.kms_rotation_evidence.evidence_hash
    assert rewrapped.manifest.rotated_at_utc == "2026-06-11T03:10:00Z"
    assert rewrapped.manifest.rotation_reason == "scheduled key rotation"
    assert rewrapped.manifest.wrapped_data_key_hash != encrypted.manifest.wrapped_data_key_hash
    assert rewrapped.manifest.aad_hash == encrypted.manifest.aad_hash
    assert rewrapped.manifest.ciphertext_hash == encrypted.manifest.ciphertext_hash
    assert rewrapped.manifest.plaintext_hash == encrypted.manifest.plaintext_hash
    assert rewrapped.manifest.manifest_hash == build_envelope_encryption_manifest_hash(rewrapped.manifest)
    assert decrypted.plaintext == request.plaintext


def test_envelope_rewrap_rejects_tampered_manifest_hash() -> None:
    service, _kms_adapter = service_for_tests()
    encrypted = service.encrypt(encryption_request())
    tampered_manifest = encrypted.manifest.model_copy(update={"ciphertext_hash": "sha256:" + "c" * 64})

    with pytest.raises(EnvelopeEncryptionError, match="manifest_hash"):
        service.rewrap(
            rewrap_request(
                ciphertext=encrypted.ciphertext,
                manifest=tampered_manifest,
            )
        )


def test_envelope_rewrap_rejects_unexpected_rotation_target() -> None:
    service, _kms_adapter = service_for_tests()
    encrypted = service.encrypt(encryption_request())

    with pytest.raises(EnvelopeEncryptionError, match="requested new_kms_key_ref"):
        service.rewrap(
            rewrap_request(
                ciphertext=encrypted.ciphertext,
                manifest=encrypted.manifest,
                new_kms_key_ref="kms://tenant-1/internal/v3",
            )
        )


def test_envelope_rewrap_rejects_destroyed_current_key_version() -> None:
    service, kms_adapter = service_for_tests()
    encrypted = service.encrypt(
        encryption_request(
            data_class=DataClass.PERSONAL,
            kms_key_ref="kms://tenant-1/personal/v1",
        )
    )
    kms_adapter.record_key_destruction(destroy_personal_key_command())

    with pytest.raises(KmsPolicyViolation, match="destroyed"):
        service.rewrap(
            rewrap_request(
                ciphertext=encrypted.ciphertext,
                manifest=encrypted.manifest,
                new_kms_key_ref="kms://tenant-1/personal/v2",
            )
        )
