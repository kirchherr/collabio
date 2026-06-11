from collections.abc import Callable
from pathlib import Path

import pytest

from suite.ai_control_plane.models import DataClass
from suite.kms.adapter import (
    KmsKeyReferenceRequest,
    KmsKeyUse,
    KmsPolicyViolation,
    LocalKmsAdapter,
    load_kms_adapter_policy,
)
from suite.kms.cryptoshred import (
    CryptoshredSimulationError,
    CryptoshredSimulationRequest,
    LocalCryptoshredSimulator,
    build_cryptoshred_simulation_manifest_hash,
)
from suite.kms.envelope import (
    EnvelopeDecryptionRequest,
    EnvelopeEncryptionManifest,
    EnvelopeEncryptionRequest,
    LocalEnvelopeEncryptionService,
)
from suite.storage.retention import RetentionManifest, build_retention_manifest, load_retention_manifest_policy
from suite.storage.source_objects import (
    LegalHoldState,
    SourceLifecycleState,
    SourceObjectMetadata,
    SourceObjectRecord,
    SourceObjectType,
    build_source_object_manifest_hash,
    sha256_bytes,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
KMS_POLICY_PATH = REPO_ROOT / "docs" / "kms_adapter_policy.json"
RETENTION_POLICY_PATH = REPO_ROOT / "docs" / "retention_manifest_policy.json"


def fixed_bytes(value: int) -> Callable[[int], bytes]:
    return lambda size: bytes([value]) * size


def record_for(
    *,
    classification: DataClass = DataClass.PERSONAL,
    retention_policy_id: str = "rp-standard",
    legal_hold_state: LegalHoldState = LegalHoldState.NONE,
    lifecycle_state: SourceLifecycleState = SourceLifecycleState.WORKING,
    created_at_utc: str = "2024-01-01T00:00:00Z",
    object_type: SourceObjectType = SourceObjectType.DOCUMENT,
) -> SourceObjectRecord:
    text = "Cryptoshred-governed source content"
    content = text.encode("utf-8")
    draft = SourceObjectMetadata(
        tenant_id="tenant-1",
        object_id="doc-cryptoshred-1",
        object_type=object_type,
        version_id="v1",
        title="Cryptoshred object",
        owner_principal_id="user-owner",
        created_by="user-creator",
        created_at_utc=created_at_utc,
        updated_at_utc=created_at_utc,
        classification=classification,
        retention_policy_id=retention_policy_id,
        legal_hold_state=legal_hold_state,
        kms_key_ref=f"kms://tenant-1/{classification.value}/v1",
        manifest_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        audit_chain_ref="audit:source-object",
        source_system="collabio",
        mime_type="text/plain",
        acl_hash="sha256:acl",
        acl_version=1,
        content_hash=sha256_bytes(content),
        content_byte_length=len(content),
        lifecycle_state=lifecycle_state,
    )
    return SourceObjectRecord(
        metadata=draft.model_copy(update={"manifest_hash": build_source_object_manifest_hash(draft)}),
        text=text,
    )


def retention_manifest_for(record: SourceObjectRecord) -> RetentionManifest:
    return build_retention_manifest(record, load_retention_manifest_policy(RETENTION_POLICY_PATH))


def cryptoshred_request(
    *,
    record: SourceObjectRecord,
    retention_manifest: RetentionManifest,
    occurred_at_utc: str = "2026-06-11T05:00:00Z",
) -> CryptoshredSimulationRequest:
    return CryptoshredSimulationRequest(
        tenant_id=record.metadata.tenant_id,
        object_id=record.metadata.object_id,
        source_version_id=record.metadata.version_id,
        record=record,
        retention_manifest=retention_manifest,
        requested_by="user-privacy",
        approved_by="user-approver",
        approval_ref="approval:cryptoshred-1",
        audit_chain_ref="audit:cryptoshred",
        occurred_at_utc=occurred_at_utc,
        reason="approved privacy deletion after retention end",
    )


def envelope_encryption_request(record: SourceObjectRecord) -> EnvelopeEncryptionRequest:
    return EnvelopeEncryptionRequest(
        tenant_id=record.metadata.tenant_id,
        object_id=record.metadata.object_id,
        source_version_id=record.metadata.version_id,
        data_class=record.metadata.classification,
        kms_key_ref=record.metadata.kms_key_ref,
        plaintext=record.text.encode("utf-8"),
        aad={"storage_manifest_hash": "sha256:" + "a" * 64},
        requested_by="user-storage",
        audit_chain_ref="audit:envelope-encrypt",
        occurred_at_utc="2026-06-11T04:00:00Z",
    )


def envelope_decryption_request(
    *,
    record: SourceObjectRecord,
    encrypted_ciphertext: bytes,
    encrypted_manifest: EnvelopeEncryptionManifest,
) -> EnvelopeDecryptionRequest:
    return EnvelopeDecryptionRequest(
        tenant_id=record.metadata.tenant_id,
        object_id=record.metadata.object_id,
        source_version_id=record.metadata.version_id,
        data_class=record.metadata.classification,
        kms_key_ref=record.metadata.kms_key_ref,
        ciphertext=encrypted_ciphertext,
        manifest=encrypted_manifest,
        aad={"storage_manifest_hash": "sha256:" + "a" * 64},
        requested_by="user-storage",
        audit_chain_ref="audit:envelope-decrypt",
        occurred_at_utc="2026-06-11T05:05:00Z",
    )


def test_cryptoshred_simulation_records_manifest_and_blocks_future_decrypt() -> None:
    record = record_for()
    retention_manifest = retention_manifest_for(record)
    kms_adapter = LocalKmsAdapter(load_kms_adapter_policy(KMS_POLICY_PATH))
    envelope = LocalEnvelopeEncryptionService(
        kms_adapter,
        data_key_generator=fixed_bytes(17),
        nonce_generator=fixed_bytes(34),
    )
    encrypted = envelope.encrypt(envelope_encryption_request(record))

    result = LocalCryptoshredSimulator(kms_adapter).simulate(
        cryptoshred_request(record=record, retention_manifest=retention_manifest)
    )

    assert result.verified is True
    assert result.manifest.classification == DataClass.PERSONAL
    assert result.manifest.target_lifecycle_state == SourceLifecycleState.CRYPTOSHREDDED
    assert result.manifest.object_bytes_deleted is False
    assert result.manifest.plaintext_key_exported is False
    assert result.manifest.encrypted_content_unreadable is True
    assert result.manifest.source_manifest_hash == record.metadata.manifest_hash
    assert result.manifest.retention_manifest_hash.startswith("sha256:")
    assert result.manifest.key_destruction_evidence_hash == result.key_destruction.evidence.evidence_hash
    assert result.manifest.manifest_hash == build_cryptoshred_simulation_manifest_hash(result.manifest)

    with pytest.raises(KmsPolicyViolation, match="destroyed"):
        envelope.decrypt(
            envelope_decryption_request(
                record=record,
                encrypted_ciphertext=encrypted.ciphertext,
                encrypted_manifest=encrypted.manifest,
            )
        )

    with pytest.raises(KmsPolicyViolation, match="destroyed"):
        kms_adapter.validate_key_reference(
            KmsKeyReferenceRequest(
                tenant_id=record.metadata.tenant_id,
                data_class=record.metadata.classification,
                kms_key_ref=record.metadata.kms_key_ref,
                requested_by="user-storage",
                audit_chain_ref="audit:kms-validate",
                occurred_at_utc="2026-06-11T05:10:00Z",
                key_use=KmsKeyUse.STORAGE_RESTORE,
                object_id=record.metadata.object_id,
                source_version_id=record.metadata.version_id,
            )
        )


def test_cryptoshred_simulation_rejects_before_retention_end() -> None:
    record = record_for(created_at_utc="2026-06-10T00:00:00Z")
    retention_manifest = retention_manifest_for(record)

    with pytest.raises(CryptoshredSimulationError, match="retention period"):
        LocalCryptoshredSimulator(LocalKmsAdapter(load_kms_adapter_policy(KMS_POLICY_PATH))).simulate(
            cryptoshred_request(record=record, retention_manifest=retention_manifest)
        )


def test_cryptoshred_simulation_rejects_active_legal_hold() -> None:
    record = record_for(
        classification=DataClass.CONFIDENTIAL,
        legal_hold_state=LegalHoldState.ACTIVE,
    )
    retention_manifest = retention_manifest_for(record)

    with pytest.raises(CryptoshredSimulationError, match="legal hold"):
        LocalCryptoshredSimulator(LocalKmsAdapter(load_kms_adapter_policy(KMS_POLICY_PATH))).simulate(
            cryptoshred_request(record=record, retention_manifest=retention_manifest)
        )


def test_cryptoshred_simulation_rejects_gobd_records() -> None:
    record = record_for(
        classification=DataClass.GOBD,
        retention_policy_id="rp-gobd-10y",
        lifecycle_state=SourceLifecycleState.BUSINESS_RECORD,
    )
    retention_manifest = retention_manifest_for(record)

    with pytest.raises(CryptoshredSimulationError, match="GoBD"):
        LocalCryptoshredSimulator(LocalKmsAdapter(load_kms_adapter_policy(KMS_POLICY_PATH))).simulate(
            cryptoshred_request(record=record, retention_manifest=retention_manifest)
        )


def test_cryptoshred_simulation_rejects_retention_manifest_mismatch() -> None:
    record = record_for()
    retention_manifest = retention_manifest_for(record).model_copy(update={"object_id": "different-object"})

    with pytest.raises(CryptoshredSimulationError, match="retention manifest"):
        LocalCryptoshredSimulator(LocalKmsAdapter(load_kms_adapter_policy(KMS_POLICY_PATH))).simulate(
            cryptoshred_request(record=record, retention_manifest=retention_manifest)
        )
