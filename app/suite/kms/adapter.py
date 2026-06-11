from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from suite.ai_control_plane.models import DataClass
from suite.storage.content_hash import compute_content_hash

NAMESPACED_REF_PATTERN = re.compile(r"^[a-z][a-z0-9_+.-]*:.+")
KEY_VERSION_PATTERN = re.compile(r"^v([1-9][0-9]*)$")


class KmsKeyReferenceError(ValueError):
    pass


class KmsPolicyViolation(ValueError):
    pass


class KmsOperation(StrEnum):
    VALIDATE_KEY_REFERENCE = "validate_key_reference"
    ROTATE_KEY_REFERENCE = "rotate_key_reference"
    RECORD_KEY_DESTRUCTION = "record_key_destruction"


class KmsKeyUse(StrEnum):
    STORAGE_WRITE = "storage_write"
    STORAGE_RESTORE = "storage_restore"
    PARSER_ARTIFACT = "parser_artifact"
    EXPORT_PACKAGE = "export_package"
    KEY_ROTATION = "key_rotation"
    KEY_DESTRUCTION = "key_destruction"
    ENVELOPE_ENCRYPTION_PREP = "envelope_encryption_prep"
    ENVELOPE_DECRYPTION = "envelope_decryption"


class KmsKeyReference(BaseModel):
    tenant_id: str
    data_class: DataClass
    key_version: int = Field(ge=1)

    @field_validator("tenant_id")
    @classmethod
    def require_non_empty_tenant(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("tenant_id must not be empty")
        return normalized

    @property
    def canonical_ref(self) -> str:
        return f"kms://{self.tenant_id}/{self.data_class.value}/v{self.key_version}"

    @classmethod
    def parse(cls, value: str) -> KmsKeyReference:
        normalized = value.strip()
        if not normalized.startswith("kms://"):
            raise KmsKeyReferenceError("kms_key_ref must use kms://")

        parts = normalized.removeprefix("kms://").split("/")
        if len(parts) != 3:
            raise KmsKeyReferenceError("kms_key_ref must be kms://<tenant_id>/<data_class>/v<version>")

        tenant_id, data_class_value, version_value = parts
        if not tenant_id.strip():
            raise KmsKeyReferenceError("kms_key_ref tenant_id must not be empty")
        try:
            data_class = DataClass(data_class_value)
        except ValueError as exc:
            raise KmsKeyReferenceError(f"unknown kms data class: {data_class_value}") from exc

        version_match = KEY_VERSION_PATTERN.fullmatch(version_value)
        if version_match is None:
            raise KmsKeyReferenceError("kms_key_ref version must be v<positive integer>")

        reference = cls(
            tenant_id=tenant_id,
            data_class=data_class,
            key_version=int(version_match.group(1)),
        )
        if normalized != reference.canonical_ref:
            raise KmsKeyReferenceError("kms_key_ref must be canonical")
        return reference


class KmsDataClassKeyPolicy(BaseModel):
    data_class: DataClass
    key_hierarchy_level: str = "data_class_key"
    min_key_version: int = Field(default=1, ge=1)
    rotation_required: bool = True
    rotation_period_days: int = Field(ge=1)
    destruction_requires_human_approval: bool = True
    cryptoshred_allowed: bool = False

    @model_validator(mode="after")
    def require_safe_policy(self) -> Self:
        if not self.key_hierarchy_level.strip():
            raise ValueError("key_hierarchy_level must not be empty")
        if self.cryptoshred_allowed and self.data_class in {DataClass.GOBD, DataClass.LEGAL_HOLD}:
            raise ValueError("GoBD and legal-hold data classes cannot allow cryptoshred")
        if self.cryptoshred_allowed and not self.destruction_requires_human_approval:
            raise ValueError("cryptoshred-capable classes require human approval")
        return self


class KmsAdapterPolicy(BaseModel):
    schema_version: str
    owner: str
    default_provider_profile: str
    provider_profiles: list[str] = Field(min_length=1)
    required_key_hierarchy: list[str] = Field(min_length=4)
    forbidden_operations: list[str] = Field(min_length=1)
    required_evidence_fields: list[str] = Field(min_length=1)
    data_class_key_policies: list[KmsDataClassKeyPolicy] = Field(min_length=1)

    @model_validator(mode="after")
    def require_complete_policy(self) -> Self:
        if self.default_provider_profile not in self.provider_profiles:
            raise ValueError("default_provider_profile must be listed in provider_profiles")

        required_hierarchy = {
            "tenant_master_key",
            "data_class_key",
            "object_encryption_key",
            "version_envelope_key",
        }
        missing_hierarchy = sorted(required_hierarchy - set(self.required_key_hierarchy))
        if missing_hierarchy:
            raise ValueError(f"KMS policy is missing hierarchy levels: {', '.join(missing_hierarchy)}")

        required_forbidden = {
            "raw_key_material_export",
            "feature_code_direct_crypto_call",
            "plaintext_key_backup",
            "destroy_key_without_human_approval",
            "destroy_gobd_or_legal_hold_key",
        }
        missing_forbidden = sorted(required_forbidden - set(self.forbidden_operations))
        if missing_forbidden:
            raise ValueError(f"KMS policy is missing forbidden operations: {', '.join(missing_forbidden)}")

        data_classes = [policy.data_class for policy in self.data_class_key_policies]
        duplicate_classes = sorted(
            {data_class.value for data_class in data_classes if data_classes.count(data_class) > 1}
        )
        if duplicate_classes:
            raise ValueError(f"duplicate KMS data class policies: {', '.join(duplicate_classes)}")

        missing_classes = sorted({data_class.value for data_class in set(DataClass) - set(data_classes)})
        if missing_classes:
            raise ValueError(f"KMS policy is missing data classes: {', '.join(missing_classes)}")
        return self

    def data_class_policy(self, data_class: DataClass) -> KmsDataClassKeyPolicy:
        for policy in self.data_class_key_policies:
            if policy.data_class == data_class:
                return policy
        raise LookupError(f"Unknown KMS data class policy: {data_class.value}")


class KmsKeyReferenceRequest(BaseModel):
    tenant_id: str
    data_class: DataClass
    kms_key_ref: str
    requested_by: str
    audit_chain_ref: str
    occurred_at_utc: str
    key_use: KmsKeyUse
    object_id: str | None = None
    source_version_id: str | None = None

    @field_validator("tenant_id", "requested_by")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized

    @field_validator("kms_key_ref", "audit_chain_ref")
    @classmethod
    def require_namespaced_ref(cls, value: str, info: object) -> str:
        normalized = value.strip()
        if not NAMESPACED_REF_PATTERN.fullmatch(normalized):
            field_name = getattr(info, "field_name", "reference")
            raise ValueError(f"{field_name} must be a namespaced reference")
        return normalized

    @field_validator("occurred_at_utc")
    @classmethod
    def require_utc_timestamp(cls, value: str) -> str:
        return _require_utc_timestamp(value)


class KmsRotateKeyCommand(BaseModel):
    tenant_id: str
    data_class: DataClass
    current_kms_key_ref: str
    requested_by: str
    approved_by: str
    audit_chain_ref: str
    occurred_at_utc: str
    reason: str

    @field_validator("tenant_id", "requested_by", "approved_by", "reason")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized

    @field_validator("current_kms_key_ref", "audit_chain_ref")
    @classmethod
    def require_namespaced_ref(cls, value: str, info: object) -> str:
        normalized = value.strip()
        if not NAMESPACED_REF_PATTERN.fullmatch(normalized):
            field_name = getattr(info, "field_name", "reference")
            raise ValueError(f"{field_name} must be a namespaced reference")
        return normalized

    @field_validator("occurred_at_utc")
    @classmethod
    def require_utc_timestamp(cls, value: str) -> str:
        return _require_utc_timestamp(value)


class KmsDestroyKeyCommand(BaseModel):
    tenant_id: str
    data_class: DataClass
    kms_key_ref: str
    retention_policy_id: str
    legal_hold_state: str
    lifecycle_state: str
    requested_by: str
    approved_by: str
    approval_ref: str
    audit_chain_ref: str
    occurred_at_utc: str
    reason: str

    @field_validator(
        "tenant_id",
        "retention_policy_id",
        "legal_hold_state",
        "lifecycle_state",
        "requested_by",
        "approved_by",
        "reason",
    )
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized

    @field_validator("kms_key_ref", "approval_ref", "audit_chain_ref")
    @classmethod
    def require_namespaced_ref(cls, value: str, info: object) -> str:
        normalized = value.strip()
        if not NAMESPACED_REF_PATTERN.fullmatch(normalized):
            field_name = getattr(info, "field_name", "reference")
            raise ValueError(f"{field_name} must be a namespaced reference")
        return normalized

    @field_validator("occurred_at_utc")
    @classmethod
    def require_utc_timestamp(cls, value: str) -> str:
        return _require_utc_timestamp(value)


class KmsOperationEvidence(BaseModel):
    schema_version: str = "kms_operation_evidence.v1"
    operation: KmsOperation
    tenant_id: str
    data_class: DataClass
    kms_key_ref: str
    key_version: int = Field(ge=1)
    provider_profile: str
    requested_by: str
    audit_chain_ref: str
    occurred_at_utc: str
    key_use: KmsKeyUse
    approved_by: str | None = None
    object_id: str | None = None
    source_version_id: str | None = None
    previous_kms_key_ref: str | None = None
    new_kms_key_ref: str | None = None
    approval_ref: str | None = None
    reason: str | None = None
    raw_key_material_exposed: bool = False
    key_destroyed: bool = False
    evidence_hash: str

    @field_validator(
        "kms_key_ref",
        "audit_chain_ref",
        "previous_kms_key_ref",
        "new_kms_key_ref",
        "approval_ref",
        "evidence_hash",
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
    def forbid_raw_key_material_exposure(self) -> Self:
        if self.raw_key_material_exposed:
            raise ValueError("KMS evidence must never expose raw key material")
        return self


class KmsRotationResult(BaseModel):
    previous_kms_key_ref: str
    new_kms_key_ref: str
    evidence: KmsOperationEvidence


class KmsKeyDestructionResult(BaseModel):
    kms_key_ref: str
    evidence: KmsOperationEvidence


class KmsAdapter(Protocol):
    def validate_key_reference(self, request: KmsKeyReferenceRequest) -> KmsOperationEvidence: ...

    def rotate_key_reference(self, command: KmsRotateKeyCommand) -> KmsRotationResult: ...

    def record_key_destruction(self, command: KmsDestroyKeyCommand) -> KmsKeyDestructionResult: ...


class LocalKmsAdapter:
    def __init__(self, policy: KmsAdapterPolicy, *, provider_profile: str | None = None) -> None:
        self.policy = policy
        self.provider_profile = provider_profile or policy.default_provider_profile
        if self.provider_profile not in policy.provider_profiles:
            raise KmsPolicyViolation("provider_profile is not allowed by KMS policy")
        self._destroyed_key_refs: set[str] = set()

    def validate_key_reference(self, request: KmsKeyReferenceRequest) -> KmsOperationEvidence:
        key_ref = self._validate_key_ref(
            tenant_id=request.tenant_id,
            data_class=request.data_class,
            kms_key_ref=request.kms_key_ref,
        )
        return build_kms_operation_evidence(
            operation=KmsOperation.VALIDATE_KEY_REFERENCE,
            tenant_id=request.tenant_id,
            data_class=request.data_class,
            kms_key_ref=key_ref.canonical_ref,
            key_version=key_ref.key_version,
            provider_profile=self.provider_profile,
            requested_by=request.requested_by,
            audit_chain_ref=request.audit_chain_ref,
            occurred_at_utc=request.occurred_at_utc,
            key_use=request.key_use,
            object_id=request.object_id,
            source_version_id=request.source_version_id,
        )

    def rotate_key_reference(self, command: KmsRotateKeyCommand) -> KmsRotationResult:
        current_ref = self._validate_key_ref(
            tenant_id=command.tenant_id,
            data_class=command.data_class,
            kms_key_ref=command.current_kms_key_ref,
        )
        new_ref = KmsKeyReference(
            tenant_id=current_ref.tenant_id,
            data_class=current_ref.data_class,
            key_version=current_ref.key_version + 1,
        )
        evidence = build_kms_operation_evidence(
            operation=KmsOperation.ROTATE_KEY_REFERENCE,
            tenant_id=command.tenant_id,
            data_class=command.data_class,
            kms_key_ref=current_ref.canonical_ref,
            key_version=current_ref.key_version,
            provider_profile=self.provider_profile,
            requested_by=command.requested_by,
            approved_by=command.approved_by,
            audit_chain_ref=command.audit_chain_ref,
            occurred_at_utc=command.occurred_at_utc,
            key_use=KmsKeyUse.KEY_ROTATION,
            previous_kms_key_ref=current_ref.canonical_ref,
            new_kms_key_ref=new_ref.canonical_ref,
            reason=command.reason,
        )
        return KmsRotationResult(
            previous_kms_key_ref=current_ref.canonical_ref,
            new_kms_key_ref=new_ref.canonical_ref,
            evidence=evidence,
        )

    def record_key_destruction(self, command: KmsDestroyKeyCommand) -> KmsKeyDestructionResult:
        key_ref = self._validate_key_ref(
            tenant_id=command.tenant_id,
            data_class=command.data_class,
            kms_key_ref=command.kms_key_ref,
        )
        data_class_policy = self.policy.data_class_policy(command.data_class)
        self._require_key_destruction_allowed(data_class_policy, command)
        self._destroyed_key_refs.add(key_ref.canonical_ref)
        evidence = build_kms_operation_evidence(
            operation=KmsOperation.RECORD_KEY_DESTRUCTION,
            tenant_id=command.tenant_id,
            data_class=command.data_class,
            kms_key_ref=key_ref.canonical_ref,
            key_version=key_ref.key_version,
            provider_profile=self.provider_profile,
            requested_by=command.requested_by,
            approved_by=command.approved_by,
            audit_chain_ref=command.audit_chain_ref,
            occurred_at_utc=command.occurred_at_utc,
            key_use=KmsKeyUse.KEY_DESTRUCTION,
            approval_ref=command.approval_ref,
            reason=command.reason,
            key_destroyed=True,
        )
        return KmsKeyDestructionResult(kms_key_ref=key_ref.canonical_ref, evidence=evidence)

    def _validate_key_ref(self, *, tenant_id: str, data_class: DataClass, kms_key_ref: str) -> KmsKeyReference:
        key_ref = KmsKeyReference.parse(kms_key_ref)
        if key_ref.tenant_id != tenant_id:
            raise KmsPolicyViolation("kms_key_ref tenant_id does not match request tenant")
        if key_ref.data_class != data_class:
            raise KmsPolicyViolation("kms_key_ref data_class does not match request data_class")
        data_class_policy = self.policy.data_class_policy(data_class)
        if key_ref.key_version < data_class_policy.min_key_version:
            raise KmsPolicyViolation("kms_key_ref version is below policy minimum")
        if key_ref.canonical_ref in self._destroyed_key_refs:
            raise KmsPolicyViolation("kms key version is destroyed")
        return key_ref

    def _require_key_destruction_allowed(
        self,
        data_class_policy: KmsDataClassKeyPolicy,
        command: KmsDestroyKeyCommand,
    ) -> None:
        if command.legal_hold_state == "active":
            raise KmsPolicyViolation("active legal hold blocks key destruction")
        if command.data_class in {DataClass.GOBD, DataClass.LEGAL_HOLD}:
            raise KmsPolicyViolation("GoBD and legal-hold data classes block key destruction")
        if command.lifecycle_state in {"business_record", "worm_evidence"}:
            raise KmsPolicyViolation("record lifecycle blocks key destruction")
        if data_class_policy.destruction_requires_human_approval and not command.approval_ref:
            raise KmsPolicyViolation("key destruction requires human approval reference")
        if not data_class_policy.cryptoshred_allowed:
            raise KmsPolicyViolation("data class policy does not allow cryptoshred")


def load_kms_adapter_policy(path: Path) -> KmsAdapterPolicy:
    return KmsAdapterPolicy.model_validate_json(path.read_text(encoding="utf-8"))


def kms_adapter_policy_summary(policy: KmsAdapterPolicy) -> dict[str, object]:
    cryptoshred_capable_count = sum(
        1 for data_class_policy in policy.data_class_key_policies if data_class_policy.cryptoshred_allowed
    )
    return {
        "schema_version": policy.schema_version,
        "owner": policy.owner,
        "provider_profile_count": len(policy.provider_profiles),
        "data_class_policy_count": len(policy.data_class_key_policies),
        "cryptoshred_capable_count": cryptoshred_capable_count,
    }


def kms_operation_evidence_payload(evidence: KmsOperationEvidence) -> dict[str, object]:
    return evidence.model_dump(mode="json", exclude={"evidence_hash"})


def build_kms_operation_evidence_hash(evidence: KmsOperationEvidence) -> str:
    evidence_bytes = json.dumps(
        kms_operation_evidence_payload(evidence),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return compute_content_hash(evidence_bytes)


def build_kms_operation_evidence(
    *,
    operation: KmsOperation,
    tenant_id: str,
    data_class: DataClass,
    kms_key_ref: str,
    key_version: int,
    provider_profile: str,
    requested_by: str,
    audit_chain_ref: str,
    occurred_at_utc: str,
    key_use: KmsKeyUse,
    approved_by: str | None = None,
    object_id: str | None = None,
    source_version_id: str | None = None,
    previous_kms_key_ref: str | None = None,
    new_kms_key_ref: str | None = None,
    approval_ref: str | None = None,
    reason: str | None = None,
    key_destroyed: bool = False,
) -> KmsOperationEvidence:
    draft = KmsOperationEvidence(
        operation=operation,
        tenant_id=tenant_id,
        data_class=data_class,
        kms_key_ref=kms_key_ref,
        key_version=key_version,
        provider_profile=provider_profile,
        requested_by=requested_by,
        approved_by=approved_by,
        audit_chain_ref=audit_chain_ref,
        occurred_at_utc=occurred_at_utc,
        key_use=key_use,
        object_id=object_id,
        source_version_id=source_version_id,
        previous_kms_key_ref=previous_kms_key_ref,
        new_kms_key_ref=new_kms_key_ref,
        approval_ref=approval_ref,
        reason=reason,
        key_destroyed=key_destroyed,
        evidence_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
    )
    return draft.model_copy(update={"evidence_hash": build_kms_operation_evidence_hash(draft)})


def _require_utc_timestamp(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("timestamp must not be empty")
    parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("timestamp must be UTC")
    return normalized


def main() -> None:
    policy = load_kms_adapter_policy(Path("docs/kms_adapter_policy.json"))
    print(json.dumps(kms_adapter_policy_summary(policy), sort_keys=True))


if __name__ == "__main__":
    main()
