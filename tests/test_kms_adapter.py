from pathlib import Path

import pytest

from suite.ai_control_plane.models import DataClass
from suite.kms.adapter import (
    KmsDestroyKeyCommand,
    KmsKeyReference,
    KmsKeyReferenceError,
    KmsKeyReferenceRequest,
    KmsKeyUse,
    KmsOperation,
    KmsPolicyViolation,
    KmsRotateKeyCommand,
    LocalKmsAdapter,
    build_kms_operation_evidence_hash,
    kms_adapter_policy_summary,
    load_kms_adapter_policy,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = REPO_ROOT / "docs" / "kms_adapter_policy.json"


def adapter_for_tests() -> LocalKmsAdapter:
    return LocalKmsAdapter(load_kms_adapter_policy(POLICY_PATH))


def key_request(
    *,
    tenant_id: str = "tenant-1",
    data_class: DataClass = DataClass.INTERNAL,
    kms_key_ref: str = "kms://tenant-1/internal/v1",
) -> KmsKeyReferenceRequest:
    return KmsKeyReferenceRequest(
        tenant_id=tenant_id,
        data_class=data_class,
        kms_key_ref=kms_key_ref,
        requested_by="user-storage",
        audit_chain_ref="audit:kms-validate",
        occurred_at_utc="2026-06-11T00:00:00Z",
        key_use=KmsKeyUse.STORAGE_WRITE,
        object_id="doc-1",
        source_version_id="v1",
    )


def rotate_command() -> KmsRotateKeyCommand:
    return KmsRotateKeyCommand(
        tenant_id="tenant-1",
        data_class=DataClass.INTERNAL,
        current_kms_key_ref="kms://tenant-1/internal/v1",
        requested_by="user-security",
        approved_by="user-approver",
        audit_chain_ref="audit:kms-rotate",
        occurred_at_utc="2026-06-11T01:00:00Z",
        reason="scheduled rotation rehearsal",
    )


def destroy_command(
    *,
    data_class: DataClass = DataClass.PERSONAL,
    kms_key_ref: str = "kms://tenant-1/personal/v1",
    legal_hold_state: str = "none",
    lifecycle_state: str = "working",
) -> KmsDestroyKeyCommand:
    return KmsDestroyKeyCommand(
        tenant_id="tenant-1",
        data_class=data_class,
        kms_key_ref=kms_key_ref,
        retention_policy_id="rp-standard",
        legal_hold_state=legal_hold_state,
        lifecycle_state=lifecycle_state,
        requested_by="user-privacy",
        approved_by="user-approver",
        approval_ref="approval:key-destroy-1",
        audit_chain_ref="audit:kms-destroy",
        occurred_at_utc="2026-06-11T02:00:00Z",
        reason="approved privacy deletion drill",
    )


def test_kms_adapter_policy_covers_data_classes_and_forbidden_operations() -> None:
    policy = load_kms_adapter_policy(POLICY_PATH)

    assert kms_adapter_policy_summary(policy) == {
        "schema_version": "kms_adapter_policy.v1",
        "owner": "platform-security",
        "provider_profile_count": 4,
        "data_class_policy_count": len(DataClass),
        "cryptoshred_capable_count": 6,
    }
    assert {profile.data_class for profile in policy.data_class_key_policies} == set(DataClass)
    assert "raw_key_material_export" in policy.forbidden_operations
    assert "feature_code_direct_crypto_call" in policy.forbidden_operations
    assert not policy.data_class_policy(DataClass.GOBD).cryptoshred_allowed
    assert not policy.data_class_policy(DataClass.LEGAL_HOLD).cryptoshred_allowed


def test_kms_key_reference_parses_canonical_tenant_class_version() -> None:
    key_ref = KmsKeyReference.parse("kms://tenant-1/internal/v3")

    assert key_ref.tenant_id == "tenant-1"
    assert key_ref.data_class == DataClass.INTERNAL
    assert key_ref.key_version == 3
    assert key_ref.canonical_ref == "kms://tenant-1/internal/v3"


@pytest.mark.parametrize(
    "value",
    [
        "vault://tenant-1/internal/v1",
        "kms://tenant-1/unknown/v1",
        "kms://tenant-1/internal/1",
        "kms://tenant-1/internal/v0",
        "kms://tenant-1/internal/v1/extra",
    ],
)
def test_kms_key_reference_rejects_invalid_refs(value: str) -> None:
    with pytest.raises(KmsKeyReferenceError):
        KmsKeyReference.parse(value)


def test_local_kms_adapter_validates_key_reference_without_raw_key_material() -> None:
    adapter = adapter_for_tests()

    evidence = adapter.validate_key_reference(key_request())

    assert evidence.operation == KmsOperation.VALIDATE_KEY_REFERENCE
    assert evidence.kms_key_ref == "kms://tenant-1/internal/v1"
    assert evidence.key_version == 1
    assert evidence.object_id == "doc-1"
    assert evidence.source_version_id == "v1"
    assert evidence.raw_key_material_exposed is False
    assert evidence.evidence_hash == build_kms_operation_evidence_hash(evidence)


def test_local_kms_adapter_rejects_tenant_or_data_class_mismatch() -> None:
    adapter = adapter_for_tests()

    with pytest.raises(KmsPolicyViolation, match="tenant_id"):
        adapter.validate_key_reference(key_request(tenant_id="tenant-2"))

    with pytest.raises(KmsPolicyViolation, match="data_class"):
        adapter.validate_key_reference(
            key_request(
                data_class=DataClass.CONFIDENTIAL,
                kms_key_ref="kms://tenant-1/internal/v1",
            )
        )


def test_local_kms_adapter_rotates_key_references_as_evidence_only() -> None:
    adapter = adapter_for_tests()

    result = adapter.rotate_key_reference(rotate_command())

    assert result.previous_kms_key_ref == "kms://tenant-1/internal/v1"
    assert result.new_kms_key_ref == "kms://tenant-1/internal/v2"
    assert result.evidence.operation == KmsOperation.ROTATE_KEY_REFERENCE
    assert result.evidence.previous_kms_key_ref == "kms://tenant-1/internal/v1"
    assert result.evidence.new_kms_key_ref == "kms://tenant-1/internal/v2"
    assert result.evidence.raw_key_material_exposed is False
    assert result.evidence.evidence_hash == build_kms_operation_evidence_hash(result.evidence)


def test_local_kms_adapter_blocks_protected_key_destruction() -> None:
    adapter = adapter_for_tests()

    with pytest.raises(KmsPolicyViolation, match="legal hold"):
        adapter.record_key_destruction(destroy_command(legal_hold_state="active"))

    with pytest.raises(KmsPolicyViolation, match="GoBD"):
        adapter.record_key_destruction(destroy_command(data_class=DataClass.GOBD, kms_key_ref="kms://tenant-1/gobd/v1"))

    with pytest.raises(KmsPolicyViolation, match="record lifecycle"):
        adapter.record_key_destruction(destroy_command(lifecycle_state="business_record"))


def test_local_kms_adapter_records_allowed_key_destruction_and_blocks_future_use() -> None:
    adapter = adapter_for_tests()

    result = adapter.record_key_destruction(destroy_command())

    assert result.kms_key_ref == "kms://tenant-1/personal/v1"
    assert result.evidence.operation == KmsOperation.RECORD_KEY_DESTRUCTION
    assert result.evidence.key_destroyed
    assert result.evidence.approval_ref == "approval:key-destroy-1"
    assert result.evidence.raw_key_material_exposed is False

    with pytest.raises(KmsPolicyViolation, match="destroyed"):
        adapter.validate_key_reference(
            key_request(
                data_class=DataClass.PERSONAL,
                kms_key_ref="kms://tenant-1/personal/v1",
            )
        )
