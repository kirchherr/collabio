from collections.abc import Callable
from pathlib import Path

import pytest

from suite.ai_control_plane.models import DataClass
from suite.kms.adapter import LocalKmsAdapter, load_kms_adapter_policy
from suite.kms.cryptoshred import CryptoshredSimulationRequest, LocalCryptoshredSimulator
from suite.kms.envelope import (
    EnvelopeEncryptionError,
    EnvelopeEncryptionManifest,
    EnvelopeEncryptionRequest,
    LocalEnvelopeEncryptionService,
    build_envelope_encryption_manifest_hash,
)
from suite.operations.restore_drill import (
    CryptoshreddedObjectRestoreDrillCommand,
    EncryptedObjectRestoreDrillCommand,
    RestoreDrillError,
    RestoreDrillRunner,
    RestoreDrillStatus,
    build_restore_drill_report_hash,
)
from suite.storage.adapter_policy import load_storage_adapter_policy
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
from suite.storage.storage_manifest import StorageObjectManifest, build_storage_object_manifest

REPO_ROOT = Path(__file__).resolve().parents[1]
KMS_POLICY_PATH = REPO_ROOT / "docs" / "kms_adapter_policy.json"
RETENTION_POLICY_PATH = REPO_ROOT / "docs" / "retention_manifest_policy.json"
STORAGE_POLICY_PATH = REPO_ROOT / "docs" / "storage_adapter_policy.json"


def fixed_bytes(value: int) -> Callable[[int], bytes]:
    return lambda size: bytes([value]) * size


def record_for(
    *,
    classification: DataClass = DataClass.INTERNAL,
    retention_policy_id: str = "rp-standard",
    created_at_utc: str = "2024-01-01T00:00:00Z",
    legal_hold_state: LegalHoldState = LegalHoldState.NONE,
    lifecycle_state: SourceLifecycleState = SourceLifecycleState.WORKING,
) -> SourceObjectRecord:
    text = "Restore drill source content"
    content = text.encode("utf-8")
    draft = SourceObjectMetadata(
        tenant_id="tenant-1",
        object_id="doc-restore-1",
        object_type=SourceObjectType.DOCUMENT,
        version_id="v1",
        title="Restore drill object",
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


def storage_manifest_for(
    record: SourceObjectRecord,
    retention_manifest: RetentionManifest,
) -> StorageObjectManifest:
    storage_policy = load_storage_adapter_policy(STORAGE_POLICY_PATH)
    return build_storage_object_manifest(
        record=record,
        retention_manifest=retention_manifest,
        bucket_profile=storage_policy.bucket(retention_manifest.storage_bucket_id),
        object_version_id="s3-version-restore-1",
        stored_at_utc="2026-06-11T06:00:00Z",
    )


def envelope_service_for_tests(kms_adapter: LocalKmsAdapter) -> LocalEnvelopeEncryptionService:
    return LocalEnvelopeEncryptionService(
        kms_adapter,
        data_key_generator=fixed_bytes(17),
        nonce_generator=fixed_bytes(34),
    )


def envelope_request(
    *,
    record: SourceObjectRecord,
    storage_manifest: StorageObjectManifest,
) -> EnvelopeEncryptionRequest:
    return EnvelopeEncryptionRequest(
        tenant_id=record.metadata.tenant_id,
        object_id=record.metadata.object_id,
        source_version_id=record.metadata.version_id,
        data_class=record.metadata.classification,
        kms_key_ref=record.metadata.kms_key_ref,
        plaintext=record.text.encode("utf-8"),
        aad={"storage_manifest_hash": storage_manifest.manifest_hash},
        requested_by="user-storage",
        audit_chain_ref="audit:envelope-encrypt",
        occurred_at_utc="2026-06-11T06:01:00Z",
    )


def encrypted_restore_command(
    *,
    record: SourceObjectRecord,
    storage_manifest: StorageObjectManifest,
    retention_manifest: RetentionManifest,
    envelope_ciphertext: bytes,
    envelope_manifest: EnvelopeEncryptionManifest,
    envelope_aad: dict[str, str] | None = None,
) -> EncryptedObjectRestoreDrillCommand:
    aad = envelope_aad if envelope_aad is not None else {"storage_manifest_hash": storage_manifest.manifest_hash}
    return EncryptedObjectRestoreDrillCommand(
        tenant_id=record.metadata.tenant_id,
        object_id=record.metadata.object_id,
        source_version_id=record.metadata.version_id,
        record=record,
        storage_manifest=storage_manifest,
        retention_manifest=retention_manifest,
        restored_content=record.text.encode("utf-8"),
        envelope_ciphertext=envelope_ciphertext,
        envelope_manifest=envelope_manifest,
        envelope_aad=aad,
        requested_by="user-restore",
        audit_chain_ref="audit:restore-drill",
        occurred_at_utc="2026-06-11T06:05:00Z",
    )


def test_restore_drill_verifies_storage_envelope_retention_and_kms_evidence() -> None:
    record = record_for()
    retention_manifest = retention_manifest_for(record)
    storage_manifest = storage_manifest_for(record, retention_manifest)
    kms_adapter = LocalKmsAdapter(load_kms_adapter_policy(KMS_POLICY_PATH))
    envelope_service = envelope_service_for_tests(kms_adapter)
    encrypted = envelope_service.encrypt(envelope_request(record=record, storage_manifest=storage_manifest))

    report = RestoreDrillRunner(envelope_service=envelope_service).verify_encrypted_object_restore(
        encrypted_restore_command(
            record=record,
            storage_manifest=storage_manifest,
            retention_manifest=retention_manifest,
            envelope_ciphertext=encrypted.ciphertext,
            envelope_manifest=encrypted.manifest,
        )
    )

    assert report.status == RestoreDrillStatus.RESTORED
    assert report.restored_content_released is True
    assert report.encrypted_content_unreadable is False
    assert report.storage_manifest_hash == storage_manifest.manifest_hash
    assert report.envelope_manifest_hash == encrypted.manifest.manifest_hash
    assert report.kms_evidence_hash is not None
    assert report.content_hash == record.metadata.content_hash
    assert report.report_hash == build_restore_drill_report_hash(report)
    assert "storage_object_manifest_hash_check" in report.checks
    assert "envelope_encryption_manifest_hash_check" in report.checks
    assert "kms_evidence_hash_check" in report.checks
    assert "Restore drill source content" not in report.model_dump_json()


def test_restore_drill_rejects_envelope_aad_mismatch() -> None:
    record = record_for()
    retention_manifest = retention_manifest_for(record)
    storage_manifest = storage_manifest_for(record, retention_manifest)
    kms_adapter = LocalKmsAdapter(load_kms_adapter_policy(KMS_POLICY_PATH))
    envelope_service = envelope_service_for_tests(kms_adapter)
    encrypted = envelope_service.encrypt(envelope_request(record=record, storage_manifest=storage_manifest))

    with pytest.raises(EnvelopeEncryptionError, match="AAD hash"):
        RestoreDrillRunner(envelope_service=envelope_service).verify_encrypted_object_restore(
            encrypted_restore_command(
                record=record,
                storage_manifest=storage_manifest,
                retention_manifest=retention_manifest,
                envelope_ciphertext=encrypted.ciphertext,
                envelope_manifest=encrypted.manifest,
                envelope_aad={"storage_manifest_hash": "sha256:" + "b" * 64},
            )
        )


def test_restore_drill_rejects_envelope_manifest_storage_mismatch() -> None:
    record = record_for()
    retention_manifest = retention_manifest_for(record)
    storage_manifest = storage_manifest_for(record, retention_manifest)
    kms_adapter = LocalKmsAdapter(load_kms_adapter_policy(KMS_POLICY_PATH))
    envelope_service = envelope_service_for_tests(kms_adapter)
    encrypted = envelope_service.encrypt(envelope_request(record=record, storage_manifest=storage_manifest))
    tampered_draft = encrypted.manifest.model_copy(update={"kms_key_ref": "kms://tenant-1/internal/v2"})
    tampered_manifest = tampered_draft.model_copy(
        update={"manifest_hash": build_envelope_encryption_manifest_hash(tampered_draft)}
    )

    with pytest.raises(RestoreDrillError, match="envelope manifest"):
        RestoreDrillRunner(envelope_service=envelope_service).verify_encrypted_object_restore(
            encrypted_restore_command(
                record=record,
                storage_manifest=storage_manifest,
                retention_manifest=retention_manifest,
                envelope_ciphertext=encrypted.ciphertext,
                envelope_manifest=tampered_manifest,
            )
        )


def test_restore_drill_marks_cryptoshredded_objects_unrecoverable_by_policy() -> None:
    record = record_for(classification=DataClass.PERSONAL)
    retention_manifest = retention_manifest_for(record)
    storage_manifest = storage_manifest_for(record, retention_manifest)
    kms_adapter = LocalKmsAdapter(load_kms_adapter_policy(KMS_POLICY_PATH))
    cryptoshred = LocalCryptoshredSimulator(kms_adapter).simulate(
        request=CryptoshredSimulationRequest(
            tenant_id=record.metadata.tenant_id,
            object_id=record.metadata.object_id,
            source_version_id=record.metadata.version_id,
            record=record,
            retention_manifest=retention_manifest,
            requested_by="user-privacy",
            approved_by="user-approver",
            approval_ref="approval:cryptoshred-restore-1",
            audit_chain_ref="audit:cryptoshred",
            occurred_at_utc="2026-06-11T06:10:00Z",
            reason="approved privacy deletion after retention end",
        )
    )

    report = RestoreDrillRunner().verify_cryptoshredded_object_restore(
        CryptoshreddedObjectRestoreDrillCommand(
            tenant_id=record.metadata.tenant_id,
            object_id=record.metadata.object_id,
            source_version_id=record.metadata.version_id,
            record=record,
            storage_manifest=storage_manifest,
            retention_manifest=retention_manifest,
            cryptoshred_manifest=cryptoshred.manifest,
            requested_by="user-restore",
            audit_chain_ref="audit:restore-drill",
            occurred_at_utc="2026-06-11T06:15:00Z",
        )
    )

    assert report.status == RestoreDrillStatus.UNRECOVERABLE_BY_POLICY
    assert report.restored_content_released is False
    assert report.encrypted_content_unreadable is True
    assert report.cryptoshred_manifest_hash == cryptoshred.manifest.manifest_hash
    assert report.key_destruction_evidence_hash == cryptoshred.key_destruction.evidence.evidence_hash
    assert report.report_hash == build_restore_drill_report_hash(report)
    assert "cryptoshred_manifest_hash_check" in report.checks
    assert "no_plaintext_key_export_check" in report.checks


def test_restore_drill_rejects_tampered_cryptoshred_manifest_hash() -> None:
    record = record_for(classification=DataClass.PERSONAL)
    retention_manifest = retention_manifest_for(record)
    storage_manifest = storage_manifest_for(record, retention_manifest)
    kms_adapter = LocalKmsAdapter(load_kms_adapter_policy(KMS_POLICY_PATH))
    cryptoshred = LocalCryptoshredSimulator(kms_adapter).simulate(
        request=CryptoshredSimulationRequest(
            tenant_id=record.metadata.tenant_id,
            object_id=record.metadata.object_id,
            source_version_id=record.metadata.version_id,
            record=record,
            retention_manifest=retention_manifest,
            requested_by="user-privacy",
            approved_by="user-approver",
            approval_ref="approval:cryptoshred-restore-1",
            audit_chain_ref="audit:cryptoshred",
            occurred_at_utc="2026-06-11T06:10:00Z",
            reason="approved privacy deletion after retention end",
        )
    )
    tampered_manifest = cryptoshred.manifest.model_copy(update={"manifest_hash": "sha256:" + "2" * 64})

    with pytest.raises(RestoreDrillError, match="cryptoshred manifest_hash"):
        RestoreDrillRunner().verify_cryptoshredded_object_restore(
            CryptoshreddedObjectRestoreDrillCommand(
                tenant_id=record.metadata.tenant_id,
                object_id=record.metadata.object_id,
                source_version_id=record.metadata.version_id,
                record=record,
                storage_manifest=storage_manifest,
                retention_manifest=retention_manifest,
                cryptoshred_manifest=tampered_manifest,
                requested_by="user-restore",
                audit_chain_ref="audit:restore-drill",
                occurred_at_utc="2026-06-11T06:15:00Z",
            )
        )
