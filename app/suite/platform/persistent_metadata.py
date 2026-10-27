from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict

from suite.ai_control_plane.models import DataClass

PERSISTENT_OBJECT_METADATA_SCHEMA_VERSION = "persistent_object_metadata.v1"
PERSISTENT_OBJECT_REQUIRED_FIELDS: tuple[str, ...] = (
    "tenant_id",
    "object_id",
    "object_type",
    "owner_principal_id",
    "created_by",
    "created_at_utc",
    "updated_at_utc",
    "classification",
    "retention_policy_id",
    "legal_hold_state",
    "lifecycle_state",
    "kms_key_ref",
    "audit_chain_ref",
    "source_system",
    "schema_version",
)
PERSISTENT_OBJECT_REQUIRED_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "classification": ("classification", "data_classification"),
    "schema_version": ("schema_version", "source_schema_version"),
}
NAMESPACED_REF_PATTERN = re.compile(r"^[a-z][a-z0-9_+.-]*:.+")
SOURCE_SYSTEM_PATTERN = re.compile(r"^[a-z][a-z0-9_+.-]*$")


class PersistentMetadataError(ValueError):
    pass


class PersistentObjectMetadataCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = PERSISTENT_OBJECT_METADATA_SCHEMA_VERSION
    required_fields: tuple[str, ...] = PERSISTENT_OBJECT_REQUIRED_FIELDS
    tenant_id: str
    object_id: str
    object_type: str
    classification: DataClass
    retention_policy_id: str
    legal_hold_state: str
    lifecycle_state: str
    kms_key_ref: str
    audit_chain_ref: str
    source_system: str
    object_schema_version: str
    checks: tuple[str, ...] = (
        "required_fields_present",
        "timestamps_are_utc",
        "references_are_namespaced",
        "source_system_is_canonical",
    )


def persistent_metadata_audit_metadata() -> dict[str, object]:
    return {
        "persistent_metadata_contract": PERSISTENT_OBJECT_METADATA_SCHEMA_VERSION,
        "persistent_metadata_required_fields": PERSISTENT_OBJECT_REQUIRED_FIELDS,
    }


def validate_persistent_object_metadata(
    subject: object,
    *,
    expected_object_type: str | None = None,
    expected_schema_version: str | None = None,
    expected_classification: DataClass | None = None,
) -> PersistentObjectMetadataCheck:
    values = {field: _required_field(subject, field) for field in PERSISTENT_OBJECT_REQUIRED_FIELDS}
    tenant_id = _string_value(values["tenant_id"], "tenant_id")
    object_id = _string_value(values["object_id"], "object_id")
    object_type = _string_value(values["object_type"], "object_type")
    _string_value(values["owner_principal_id"], "owner_principal_id")
    _string_value(values["created_by"], "created_by")
    created_at_utc = _string_value(values["created_at_utc"], "created_at_utc")
    updated_at_utc = _string_value(values["updated_at_utc"], "updated_at_utc")
    retention_policy_id = _string_value(values["retention_policy_id"], "retention_policy_id")
    legal_hold_state = _string_value(values["legal_hold_state"], "legal_hold_state")
    lifecycle_state = _string_value(values["lifecycle_state"], "lifecycle_state")
    kms_key_ref = _string_value(values["kms_key_ref"], "kms_key_ref")
    audit_chain_ref = _string_value(values["audit_chain_ref"], "audit_chain_ref")
    source_system = _string_value(values["source_system"], "source_system")
    object_schema_version = _string_value(values["schema_version"], "schema_version")
    classification = _data_class_value(values["classification"])

    _require_utc(created_at_utc, "created_at_utc")
    _require_utc(updated_at_utc, "updated_at_utc")
    _require_namespaced(kms_key_ref, "kms_key_ref")
    _require_namespaced(audit_chain_ref, "audit_chain_ref")
    if not SOURCE_SYSTEM_PATTERN.fullmatch(source_system):
        raise PersistentMetadataError("source_system must be lowercase and non-empty")
    if expected_object_type is not None and object_type != expected_object_type:
        raise PersistentMetadataError(f"object_type must be {expected_object_type}")
    if expected_schema_version is not None and object_schema_version != expected_schema_version:
        raise PersistentMetadataError(f"schema_version must be {expected_schema_version}")
    if expected_classification is not None and classification != expected_classification:
        raise PersistentMetadataError(f"classification must be {expected_classification.value}")

    return PersistentObjectMetadataCheck(
        tenant_id=tenant_id,
        object_id=object_id,
        object_type=object_type,
        classification=classification,
        retention_policy_id=retention_policy_id,
        legal_hold_state=legal_hold_state,
        lifecycle_state=lifecycle_state,
        kms_key_ref=kms_key_ref,
        audit_chain_ref=audit_chain_ref,
        source_system=source_system,
        object_schema_version=object_schema_version,
    )


def _required_field(subject: object, field_name: str) -> object:
    aliases = PERSISTENT_OBJECT_REQUIRED_FIELD_ALIASES.get(field_name, (field_name,))
    for alias in aliases:
        if isinstance(subject, Mapping):
            if alias in subject:
                return subject[alias]
        elif hasattr(subject, alias):
            return getattr(subject, alias)
    raise PersistentMetadataError(f"{field_name} is required for persistent object metadata")


def _string_value(value: object, field_name: str) -> str:
    if isinstance(value, Enum):
        value = value.value
    if value is None:
        raise PersistentMetadataError(f"{field_name} is required for persistent object metadata")
    normalized = str(value).strip()
    if not normalized:
        raise PersistentMetadataError(f"{field_name} is required for persistent object metadata")
    return normalized


def _data_class_value(value: object) -> DataClass:
    if isinstance(value, DataClass):
        return value
    try:
        return DataClass(str(value).strip())
    except ValueError as exc:
        raise PersistentMetadataError("classification must be a known data class") from exc


def _require_utc(value: str, field_name: str) -> None:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise PersistentMetadataError(f"{field_name} must be UTC")


def _require_namespaced(value: str, field_name: str) -> None:
    if not NAMESPACED_REF_PATTERN.fullmatch(value):
        raise PersistentMetadataError(f"{field_name} must be a namespaced reference")
