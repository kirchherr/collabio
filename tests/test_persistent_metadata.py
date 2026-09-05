import pytest

from suite.ai_control_plane.models import DataClass
from suite.platform.persistent_metadata import (
    PERSISTENT_OBJECT_METADATA_SCHEMA_VERSION,
    PERSISTENT_OBJECT_REQUIRED_FIELDS,
    PersistentMetadataError,
    persistent_metadata_audit_metadata,
    validate_persistent_object_metadata,
)


def valid_metadata_payload() -> dict[str, object]:
    return {
        "tenant_id": "tenant-demo",
        "object_id": "crm-account-demo",
        "object_type": "crm.account",
        "owner_principal_id": "user-demo",
        "created_by": "system",
        "created_at_utc": "2026-06-11T12:00:00Z",
        "updated_at_utc": "2026-06-11T12:01:00Z",
        "data_classification": "personal",
        "retention_policy_id": "rp-standard",
        "legal_hold_state": "none",
        "lifecycle_state": "active",
        "kms_key_ref": "kms:tenant-demo:crm-account",
        "audit_chain_ref": "audit:crm-account-demo",
        "source_system": "native",
        "schema_version": "crm_account.v1",
    }


def test_persistent_metadata_contract_accepts_data_classification_alias() -> None:
    check = validate_persistent_object_metadata(
        valid_metadata_payload(),
        expected_object_type="crm.account",
        expected_schema_version="crm_account.v1",
        expected_classification=DataClass.PERSONAL,
    )

    assert check.schema_version == PERSISTENT_OBJECT_METADATA_SCHEMA_VERSION
    assert check.required_fields == PERSISTENT_OBJECT_REQUIRED_FIELDS
    assert check.object_id == "crm-account-demo"
    assert check.classification == DataClass.PERSONAL
    assert persistent_metadata_audit_metadata() == {
        "persistent_metadata_contract": PERSISTENT_OBJECT_METADATA_SCHEMA_VERSION,
        "persistent_metadata_required_fields": PERSISTENT_OBJECT_REQUIRED_FIELDS,
    }


def test_persistent_metadata_contract_rejects_missing_core_fields() -> None:
    payload = valid_metadata_payload()
    del payload["source_system"]

    with pytest.raises(PersistentMetadataError, match="source_system is required"):
        validate_persistent_object_metadata(payload)


def test_persistent_metadata_contract_requires_utc_timestamps_and_namespaced_refs() -> None:
    with pytest.raises(PersistentMetadataError, match="created_at_utc must be UTC"):
        validate_persistent_object_metadata({**valid_metadata_payload(), "created_at_utc": "2026-06-11T12:00:00"})

    with pytest.raises(PersistentMetadataError, match="audit_chain_ref must be a namespaced reference"):
        validate_persistent_object_metadata({**valid_metadata_payload(), "audit_chain_ref": "audit-chain-demo"})


def test_persistent_metadata_contract_enforces_expected_type_schema_and_classification() -> None:
    with pytest.raises(PersistentMetadataError, match=r"object_type must be crm\.account"):
        validate_persistent_object_metadata(valid_metadata_payload(), expected_object_type="crm.account.other")

    with pytest.raises(PersistentMetadataError, match=r"schema_version must be crm_account\.v2"):
        validate_persistent_object_metadata(valid_metadata_payload(), expected_schema_version="crm_account.v2")

    with pytest.raises(PersistentMetadataError, match="classification must be internal"):
        validate_persistent_object_metadata(valid_metadata_payload(), expected_classification=DataClass.INTERNAL)
