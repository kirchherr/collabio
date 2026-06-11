from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, Field, field_validator, model_validator

from suite.kms.cryptoshred import (
    CryptoshredSimulationManifest,
    build_cryptoshred_simulation_manifest_hash,
)
from suite.kms.envelope import (
    EnvelopeDecryptionRequest,
    EnvelopeEncryptionManifest,
    EnvelopeEncryptionService,
    build_envelope_encryption_manifest_hash,
)
from suite.storage.content_hash import compute_content_hash
from suite.storage.retention import RetentionManifest, build_retention_manifest_hash
from suite.storage.source_objects import SourceObjectRecord, build_source_object_manifest_hash
from suite.storage.storage_manifest import (
    StorageObjectManifest,
    StorageRestoreVerificationResult,
    build_storage_object_manifest_hash,
    verify_storage_object_restore,
)

NAMESPACED_REF_PATTERN = re.compile(r"^[a-z][a-z0-9_+.-]*:.+")


class RestoreDrillError(ValueError):
    pass


class RestoreDrillStatus(StrEnum):
    RESTORED = "restored"
    UNRECOVERABLE_BY_POLICY = "unrecoverable_by_policy"


class EncryptedObjectRestoreDrillCommand(BaseModel):
    tenant_id: str
    object_id: str
    source_version_id: str
    record: SourceObjectRecord
    storage_manifest: StorageObjectManifest
    retention_manifest: RetentionManifest
    restored_content: bytes
    envelope_ciphertext: bytes
    envelope_manifest: EnvelopeEncryptionManifest
    envelope_aad: dict[str, str] = Field(default_factory=dict)
    requested_by: str
    audit_chain_ref: str
    occurred_at_utc: str

    @field_validator("tenant_id", "object_id", "source_version_id", "requested_by")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized

    @field_validator("audit_chain_ref")
    @classmethod
    def require_namespaced_ref(cls, value: str) -> str:
        normalized = value.strip()
        if not NAMESPACED_REF_PATTERN.fullmatch(normalized):
            raise ValueError("audit_chain_ref must be a namespaced reference")
        return normalized

    @field_validator("restored_content", "envelope_ciphertext")
    @classmethod
    def require_bytes(cls, value: bytes) -> bytes:
        if not value:
            raise ValueError("restore bytes must not be empty")
        return value

    @field_validator("occurred_at_utc")
    @classmethod
    def require_utc_timestamp(cls, value: str) -> str:
        return _require_utc_timestamp(value)


class CryptoshreddedObjectRestoreDrillCommand(BaseModel):
    tenant_id: str
    object_id: str
    source_version_id: str
    record: SourceObjectRecord
    storage_manifest: StorageObjectManifest
    retention_manifest: RetentionManifest
    cryptoshred_manifest: CryptoshredSimulationManifest
    requested_by: str
    audit_chain_ref: str
    occurred_at_utc: str

    @field_validator("tenant_id", "object_id", "source_version_id", "requested_by")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized

    @field_validator("audit_chain_ref")
    @classmethod
    def require_namespaced_ref(cls, value: str) -> str:
        normalized = value.strip()
        if not NAMESPACED_REF_PATTERN.fullmatch(normalized):
            raise ValueError("audit_chain_ref must be a namespaced reference")
        return normalized

    @field_validator("occurred_at_utc")
    @classmethod
    def require_utc_timestamp(cls, value: str) -> str:
        return _require_utc_timestamp(value)


class RestoreDrillReport(BaseModel):
    schema_version: str = "restore_drill_report.v1"
    status: RestoreDrillStatus
    tenant_id: str
    object_id: str
    source_version_id: str
    storage_manifest_hash: str
    source_manifest_hash: str
    retention_manifest_hash: str
    retention_policy_snapshot_hash: str
    content_hash: str | None = None
    envelope_manifest_hash: str | None = None
    kms_evidence_hash: str | None = None
    cryptoshred_manifest_hash: str | None = None
    key_destruction_evidence_hash: str | None = None
    checks: tuple[str, ...] = Field(min_length=1)
    restored_content_released: bool = False
    encrypted_content_unreadable: bool = False
    requested_by: str
    audit_chain_ref: str
    occurred_at_utc: str
    report_hash: str

    @field_validator("tenant_id", "object_id", "source_version_id", "requested_by")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized

    @field_validator(
        "storage_manifest_hash",
        "source_manifest_hash",
        "retention_manifest_hash",
        "retention_policy_snapshot_hash",
        "content_hash",
        "envelope_manifest_hash",
        "kms_evidence_hash",
        "cryptoshred_manifest_hash",
        "key_destruction_evidence_hash",
        "audit_chain_ref",
        "report_hash",
    )
    @classmethod
    def require_namespaced_ref(cls, value: str | None, info: object) -> str | None:
        if value is None:
            return value
        normalized = value.strip()
        if not NAMESPACED_REF_PATTERN.fullmatch(normalized):
            field_name = getattr(info, "field_name", "reference")
            raise ValueError(f"{field_name} must be a namespaced reference")
        return normalized

    @field_validator("occurred_at_utc")
    @classmethod
    def require_utc_timestamp(cls, value: str) -> str:
        return _require_utc_timestamp(value)

    @model_validator(mode="after")
    def require_status_consistency(self) -> Self:
        if self.status == RestoreDrillStatus.RESTORED:
            if not self.restored_content_released:
                raise ValueError("restored reports must mark content as released")
            if self.encrypted_content_unreadable:
                raise ValueError("restored reports must not mark content unreadable")
            if self.envelope_manifest_hash is None or self.kms_evidence_hash is None:
                raise ValueError("restored encrypted reports require envelope and KMS evidence")
        if self.status == RestoreDrillStatus.UNRECOVERABLE_BY_POLICY:
            if self.restored_content_released:
                raise ValueError("unrecoverable reports must not release content")
            if not self.encrypted_content_unreadable:
                raise ValueError("unrecoverable reports must mark encrypted content unreadable")
            if self.cryptoshred_manifest_hash is None or self.key_destruction_evidence_hash is None:
                raise ValueError("unrecoverable reports require cryptoshred and destruction evidence")
        return self


class RestoreDrillRunner:
    def __init__(self, *, envelope_service: EnvelopeEncryptionService | None = None) -> None:
        self.envelope_service = envelope_service

    def verify_encrypted_object_restore(self, command: EncryptedObjectRestoreDrillCommand) -> RestoreDrillReport:
        if self.envelope_service is None:
            raise RestoreDrillError("encrypted restore drill requires an envelope service")
        _require_command_matches_record(command)
        _require_envelope_manifest_matches_storage(command.envelope_manifest, command.storage_manifest)
        storage_result = verify_storage_object_restore(
            manifest=command.storage_manifest,
            record=command.record,
            retention_manifest=command.retention_manifest,
            restored_content=command.restored_content,
        )
        decryption = self.envelope_service.decrypt(
            EnvelopeDecryptionRequest(
                tenant_id=command.tenant_id,
                object_id=command.object_id,
                source_version_id=command.source_version_id,
                data_class=command.storage_manifest.classification,
                kms_key_ref=command.storage_manifest.kms_key_ref,
                ciphertext=command.envelope_ciphertext,
                manifest=command.envelope_manifest,
                aad=command.envelope_aad,
                requested_by=command.requested_by,
                audit_chain_ref=command.audit_chain_ref,
                occurred_at_utc=command.occurred_at_utc,
            )
        )
        if decryption.plaintext_hash != storage_result.content_hash:
            raise RestoreDrillError("decrypted plaintext hash does not match storage restore")
        if compute_content_hash(command.restored_content) != decryption.plaintext_hash:
            raise RestoreDrillError("restored content hash does not match decrypted plaintext")

        checks = _unique_checks(
            storage_result.checks,
            (
                "envelope_encryption_manifest_hash_check",
                "ciphertext_hash_check",
                "aad_hash_check",
                "wrapped_data_key_hash_check",
                "kms_key_reference_check",
                "kms_evidence_hash_check",
                "plaintext_hash_check",
                "restore_drill_report_hash_check",
            ),
        )
        draft = _report_draft(
            status=RestoreDrillStatus.RESTORED,
            command=command,
            storage_result=storage_result,
            checks=checks,
            envelope_manifest_hash=command.envelope_manifest.manifest_hash,
            kms_evidence_hash=decryption.kms_evidence.evidence_hash,
            content_hash=storage_result.content_hash,
            restored_content_released=True,
        )
        return draft.model_copy(update={"report_hash": build_restore_drill_report_hash(draft)})

    def verify_cryptoshredded_object_restore(
        self,
        command: CryptoshreddedObjectRestoreDrillCommand,
    ) -> RestoreDrillReport:
        _require_command_matches_record(command)
        _require_storage_manifest_metadata_matches_record(command.storage_manifest, command.record)
        _require_storage_manifest_matches_retention(command.storage_manifest, command.retention_manifest)
        _require_cryptoshred_manifest_matches_restore(command)

        checks = (
            "storage_object_manifest_hash_check",
            "source_object_manifest_hash_check",
            "retention_manifest_hash_check",
            "retention_policy_snapshot_hash_check",
            "cryptoshred_manifest_hash_check",
            "key_destruction_policy_check",
            "no_plaintext_key_export_check",
            "restore_drill_report_hash_check",
        )
        draft = _report_draft(
            status=RestoreDrillStatus.UNRECOVERABLE_BY_POLICY,
            command=command,
            storage_result=None,
            checks=checks,
            cryptoshred_manifest_hash=command.cryptoshred_manifest.manifest_hash,
            key_destruction_evidence_hash=command.cryptoshred_manifest.key_destruction_evidence_hash,
            encrypted_content_unreadable=True,
        )
        return draft.model_copy(update={"report_hash": build_restore_drill_report_hash(draft)})


def restore_drill_report_payload(report: RestoreDrillReport) -> dict[str, object]:
    return report.model_dump(mode="json", exclude={"report_hash"})


def build_restore_drill_report_hash(report: RestoreDrillReport) -> str:
    report_bytes = json.dumps(
        restore_drill_report_payload(report),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return compute_content_hash(report_bytes)


def _report_draft(
    *,
    status: RestoreDrillStatus,
    command: EncryptedObjectRestoreDrillCommand | CryptoshreddedObjectRestoreDrillCommand,
    storage_result: StorageRestoreVerificationResult | None,
    checks: tuple[str, ...],
    envelope_manifest_hash: str | None = None,
    kms_evidence_hash: str | None = None,
    cryptoshred_manifest_hash: str | None = None,
    key_destruction_evidence_hash: str | None = None,
    content_hash: str | None = None,
    restored_content_released: bool = False,
    encrypted_content_unreadable: bool = False,
) -> RestoreDrillReport:
    storage_manifest = command.storage_manifest
    return RestoreDrillReport(
        status=status,
        tenant_id=command.tenant_id,
        object_id=command.object_id,
        source_version_id=command.source_version_id,
        storage_manifest_hash=storage_manifest.manifest_hash,
        source_manifest_hash=storage_manifest.source_manifest_hash,
        retention_manifest_hash=storage_manifest.retention_manifest_hash,
        retention_policy_snapshot_hash=storage_manifest.retention_policy_snapshot_hash,
        content_hash=content_hash if storage_result is None else storage_result.content_hash,
        envelope_manifest_hash=envelope_manifest_hash,
        kms_evidence_hash=kms_evidence_hash,
        cryptoshred_manifest_hash=cryptoshred_manifest_hash,
        key_destruction_evidence_hash=key_destruction_evidence_hash,
        checks=checks,
        restored_content_released=restored_content_released,
        encrypted_content_unreadable=encrypted_content_unreadable,
        requested_by=command.requested_by,
        audit_chain_ref=command.audit_chain_ref,
        occurred_at_utc=command.occurred_at_utc,
        report_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
    )


def _require_command_matches_record(
    command: EncryptedObjectRestoreDrillCommand | CryptoshreddedObjectRestoreDrillCommand,
) -> None:
    metadata = command.record.metadata
    expected_values = {
        "tenant_id": metadata.tenant_id,
        "object_id": metadata.object_id,
        "source_version_id": metadata.version_id,
    }
    actual_values = {
        "tenant_id": command.tenant_id,
        "object_id": command.object_id,
        "source_version_id": command.source_version_id,
    }
    mismatches = sorted(field for field, expected in expected_values.items() if actual_values[field] != expected)
    if mismatches:
        raise RestoreDrillError(f"restore drill command does not match source object: {', '.join(mismatches)}")


def _require_envelope_manifest_matches_storage(
    envelope_manifest: EnvelopeEncryptionManifest,
    storage_manifest: StorageObjectManifest,
) -> None:
    if envelope_manifest.manifest_hash != build_envelope_encryption_manifest_hash(envelope_manifest):
        raise RestoreDrillError("envelope manifest_hash does not match manifest payload")
    expected_values = {
        "tenant_id": storage_manifest.tenant_id,
        "object_id": storage_manifest.object_id,
        "source_version_id": storage_manifest.source_version_id,
        "data_class": storage_manifest.classification,
        "kms_key_ref": storage_manifest.kms_key_ref,
        "plaintext_hash": storage_manifest.content_hash,
    }
    actual_values = {
        "tenant_id": envelope_manifest.tenant_id,
        "object_id": envelope_manifest.object_id,
        "source_version_id": envelope_manifest.source_version_id,
        "data_class": envelope_manifest.data_class,
        "kms_key_ref": envelope_manifest.kms_key_ref,
        "plaintext_hash": envelope_manifest.plaintext_hash,
    }
    mismatches = sorted(field for field, expected in expected_values.items() if actual_values[field] != expected)
    if mismatches:
        raise RestoreDrillError(f"envelope manifest does not match storage manifest: {', '.join(mismatches)}")


def _require_storage_manifest_metadata_matches_record(
    storage_manifest: StorageObjectManifest,
    record: SourceObjectRecord,
) -> None:
    if storage_manifest.manifest_hash != build_storage_object_manifest_hash(storage_manifest):
        raise RestoreDrillError("storage manifest_hash does not match manifest payload")
    metadata = record.metadata
    if metadata.manifest_hash != build_source_object_manifest_hash(metadata):
        raise RestoreDrillError("source object manifest_hash does not match source metadata")
    expected_values = {
        "tenant_id": metadata.tenant_id,
        "object_id": metadata.object_id,
        "source_version_id": metadata.version_id,
        "classification": metadata.classification,
        "kms_key_ref": metadata.kms_key_ref,
        "source_manifest_hash": metadata.manifest_hash,
    }
    actual_values = {
        "tenant_id": storage_manifest.tenant_id,
        "object_id": storage_manifest.object_id,
        "source_version_id": storage_manifest.source_version_id,
        "classification": storage_manifest.classification,
        "kms_key_ref": storage_manifest.kms_key_ref,
        "source_manifest_hash": storage_manifest.source_manifest_hash,
    }
    mismatches = sorted(field for field, expected in expected_values.items() if actual_values[field] != expected)
    if mismatches:
        raise RestoreDrillError(f"storage manifest does not match source object: {', '.join(mismatches)}")


def _require_storage_manifest_matches_retention(
    storage_manifest: StorageObjectManifest,
    retention_manifest: RetentionManifest,
) -> None:
    expected_retention_hash = build_retention_manifest_hash(retention_manifest)
    if storage_manifest.retention_manifest_hash != expected_retention_hash:
        raise RestoreDrillError("storage manifest retention hash does not match retention manifest")
    if storage_manifest.retention_policy_snapshot_hash != retention_manifest.policy_snapshot_hash:
        raise RestoreDrillError("storage manifest retention policy snapshot does not match retention manifest")


def _require_cryptoshred_manifest_matches_restore(command: CryptoshreddedObjectRestoreDrillCommand) -> None:
    manifest = command.cryptoshred_manifest
    record = command.record
    storage_manifest = command.storage_manifest
    retention_manifest = command.retention_manifest
    if manifest.manifest_hash != build_cryptoshred_simulation_manifest_hash(manifest):
        raise RestoreDrillError("cryptoshred manifest_hash does not match manifest payload")
    expected_values = {
        "tenant_id": record.metadata.tenant_id,
        "object_id": record.metadata.object_id,
        "source_version_id": record.metadata.version_id,
        "classification": record.metadata.classification,
        "retention_policy_id": record.metadata.retention_policy_id,
        "legal_hold_state": record.metadata.legal_hold_state,
        "source_lifecycle_state": record.metadata.lifecycle_state,
        "kms_key_ref": storage_manifest.kms_key_ref,
        "source_manifest_hash": storage_manifest.source_manifest_hash,
        "retention_manifest_hash": build_retention_manifest_hash(retention_manifest),
        "retention_policy_snapshot_hash": retention_manifest.policy_snapshot_hash,
    }
    actual_values = {
        "tenant_id": manifest.tenant_id,
        "object_id": manifest.object_id,
        "source_version_id": manifest.source_version_id,
        "classification": manifest.classification,
        "retention_policy_id": manifest.retention_policy_id,
        "legal_hold_state": manifest.legal_hold_state,
        "source_lifecycle_state": manifest.source_lifecycle_state,
        "kms_key_ref": manifest.kms_key_ref,
        "source_manifest_hash": manifest.source_manifest_hash,
        "retention_manifest_hash": manifest.retention_manifest_hash,
        "retention_policy_snapshot_hash": manifest.retention_policy_snapshot_hash,
    }
    mismatches = sorted(field for field, expected in expected_values.items() if actual_values[field] != expected)
    if mismatches:
        raise RestoreDrillError(f"cryptoshred manifest does not match restore evidence: {', '.join(mismatches)}")
    if manifest.object_bytes_deleted:
        raise RestoreDrillError("cryptoshred restore evidence must not claim object bytes were deleted")
    if manifest.plaintext_key_exported:
        raise RestoreDrillError("cryptoshred restore evidence must not export plaintext keys")
    if not manifest.encrypted_content_unreadable:
        raise RestoreDrillError("cryptoshred restore evidence must mark encrypted content unreadable")


def _unique_checks(*check_groups: tuple[str, ...]) -> tuple[str, ...]:
    checks: list[str] = []
    for group in check_groups:
        for check in group:
            if check not in checks:
                checks.append(check)
    return tuple(checks)


def _require_utc_timestamp(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("timestamp must not be empty")
    parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("timestamp must be UTC")
    return normalized
