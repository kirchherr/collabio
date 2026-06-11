from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import BaseModel, Field, model_validator

from suite.ai_control_plane.models import DataClass
from suite.storage.adapter_policy import ObjectLockMode
from suite.storage.content_hash import compute_content_hash
from suite.storage.source_objects import LegalHoldState, SourceLifecycleState, SourceObjectRecord, SourceObjectType


class RetentionManifestError(ValueError):
    pass


class RetentionMode(StrEnum):
    FIXED_DAYS = "fixed_days"
    FOLLOWS_SOURCE = "follows_source"
    UNTIL_HOLD_RELEASE = "until_hold_release"


class DispositionAfterRetention(StrEnum):
    DELETE = "delete"
    RESTRICT = "restrict"
    DELETE_AFTER_RETENTION_IF_NO_HOLD = "delete_after_retention_if_no_hold"
    DELETE_OR_REINDEX_WITH_SOURCE = "delete_or_reindex_with_source"
    BLOCKED_UNTIL_HOLD_RELEASE = "blocked_until_hold_release"
    EXPORT_REVIEW_REQUIRED = "export_review_required"


class RetentionPolicyDefault(BaseModel):
    retention_policy_id: str
    description: str
    classifications: list[DataClass] = Field(min_length=1)
    source_object_types: list[SourceObjectType] = Field(min_length=1)
    lifecycle_states: list[SourceLifecycleState] = Field(min_length=1)
    retention_mode: RetentionMode
    retention_days: int | None = Field(default=None, ge=1)
    disposition_after_retention: DispositionAfterRetention
    legal_hold_allowed: bool
    worm_required: bool
    object_lock_mode: ObjectLockMode = ObjectLockMode.NONE
    storage_bucket_id: str
    cryptoshred_allowed_before_retention_end: bool = False
    audit_required: bool = True
    manifest_required: bool = True

    @model_validator(mode="after")
    def require_consistent_policy_default(self) -> Self:
        if not self.retention_policy_id.strip():
            raise ValueError("retention_policy_id must not be empty")
        if not self.description.strip():
            raise ValueError("description must not be empty")
        if not self.storage_bucket_id.strip():
            raise ValueError("storage_bucket_id must not be empty")
        if self.retention_mode == RetentionMode.FIXED_DAYS and self.retention_days is None:
            raise ValueError("fixed-days retention policies require retention_days")
        if self.retention_mode != RetentionMode.FIXED_DAYS and self.retention_days is not None:
            raise ValueError("non-fixed retention policies must not set retention_days")
        if self.worm_required and self.object_lock_mode == ObjectLockMode.NONE:
            raise ValueError("WORM retention policies require object lock")
        if not self.worm_required and self.object_lock_mode != ObjectLockMode.NONE:
            raise ValueError("object lock must not be configured when worm_required is false")
        if self.cryptoshred_allowed_before_retention_end and any(
            data_class in {DataClass.GOBD, DataClass.LEGAL_HOLD} for data_class in self.classifications
        ):
            raise ValueError("GoBD and legal-hold policies cannot allow early cryptoshred")
        return self

    def applies_to(self, record: SourceObjectRecord) -> bool:
        metadata = record.metadata
        return (
            metadata.classification in self.classifications
            and metadata.object_type in self.source_object_types
            and metadata.lifecycle_state in self.lifecycle_states
        )


class RetentionManifestPolicy(BaseModel):
    schema_version: str
    owner: str
    default_timezone: str = "UTC"
    policy_defaults: list[RetentionPolicyDefault] = Field(min_length=1)

    @model_validator(mode="after")
    def require_complete_policy_set(self) -> Self:
        policy_ids = [policy.retention_policy_id for policy in self.policy_defaults]
        duplicate_policy_ids = sorted({policy_id for policy_id in policy_ids if policy_ids.count(policy_id) > 1})
        if duplicate_policy_ids:
            raise ValueError(f"duplicate retention policy ids: {', '.join(duplicate_policy_ids)}")
        if not any(policy.worm_required for policy in self.policy_defaults):
            raise ValueError("at least one retention policy must require WORM")
        if not any(policy.retention_mode == RetentionMode.FOLLOWS_SOURCE for policy in self.policy_defaults):
            raise ValueError("retention policy set must include follows-source handling")
        return self

    def policy(self, retention_policy_id: str) -> RetentionPolicyDefault:
        for policy in self.policy_defaults:
            if policy.retention_policy_id == retention_policy_id:
                return policy
        raise LookupError(f"Unknown retention policy: {retention_policy_id}")


class RetentionManifest(BaseModel):
    schema_version: str = "retention_manifest.v1"
    tenant_id: str
    object_id: str
    object_type: SourceObjectType
    version_id: str
    classification: DataClass
    lifecycle_state: SourceLifecycleState
    retention_policy_id: str
    retention_mode: RetentionMode
    retention_days: int | None = None
    retain_from_utc: str
    retain_until_utc: str | None
    legal_hold_state: LegalHoldState
    disposition_after_retention: DispositionAfterRetention
    deletion_blocked: bool
    worm_required: bool
    object_lock_mode: ObjectLockMode
    storage_bucket_id: str
    cryptoshred_allowed_before_retention_end: bool
    audit_required: bool
    source_manifest_hash: str
    policy_snapshot_hash: str

    @model_validator(mode="after")
    def require_consistent_manifest(self) -> Self:
        if self.retention_mode == RetentionMode.FIXED_DAYS and self.retain_until_utc is None:
            raise ValueError("fixed-days retention manifests require retain_until_utc")
        if self.retention_mode != RetentionMode.FIXED_DAYS and self.retain_until_utc is not None:
            raise ValueError("non-fixed retention manifests must not set retain_until_utc")
        if self.legal_hold_state == LegalHoldState.ACTIVE:
            if not self.deletion_blocked:
                raise ValueError("active legal hold must block deletion")
            if self.disposition_after_retention != DispositionAfterRetention.BLOCKED_UNTIL_HOLD_RELEASE:
                raise ValueError("active legal hold must block disposition until release")
            if self.cryptoshred_allowed_before_retention_end:
                raise ValueError("active legal hold cannot allow early cryptoshred")
        if self.worm_required and self.object_lock_mode == ObjectLockMode.NONE:
            raise ValueError("WORM manifests require object lock")
        protected_classification = self.classification in {DataClass.GOBD, DataClass.LEGAL_HOLD}
        if protected_classification and self.cryptoshred_allowed_before_retention_end:
            raise ValueError("GoBD and legal-hold manifests cannot allow early cryptoshred")
        return self


def load_retention_manifest_policy(path: Path) -> RetentionManifestPolicy:
    return RetentionManifestPolicy.model_validate_json(path.read_text(encoding="utf-8"))


def build_policy_snapshot_hash(policy: RetentionPolicyDefault) -> str:
    payload = policy.model_dump(mode="json")
    policy_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return compute_content_hash(policy_bytes)


def build_retention_manifest_hash(manifest: RetentionManifest) -> str:
    payload = manifest.model_dump(mode="json")
    manifest_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return compute_content_hash(manifest_bytes)


def build_retention_manifest(record: SourceObjectRecord, policy_set: RetentionManifestPolicy) -> RetentionManifest:
    metadata = record.metadata
    policy = policy_set.policy(metadata.retention_policy_id)
    if _record_requires_worm(record) and not policy.worm_required:
        raise RetentionManifestError("record lifecycle or classification requires WORM retention policy")

    if not policy.applies_to(record):
        raise RetentionManifestError("retention policy does not apply to source object metadata")

    if metadata.legal_hold_state == LegalHoldState.ACTIVE and not policy.legal_hold_allowed:
        raise RetentionManifestError("retention policy does not allow legal hold")

    retain_from = _parse_utc(metadata.created_at_utc)
    retain_until = retain_from + timedelta(days=policy.retention_days) if policy.retention_days is not None else None
    active_hold = metadata.legal_hold_state == LegalHoldState.ACTIVE

    return RetentionManifest(
        tenant_id=metadata.tenant_id,
        object_id=metadata.object_id,
        object_type=metadata.object_type,
        version_id=metadata.version_id,
        classification=metadata.classification,
        lifecycle_state=metadata.lifecycle_state,
        retention_policy_id=policy.retention_policy_id,
        retention_mode=policy.retention_mode,
        retention_days=policy.retention_days,
        retain_from_utc=_to_utc_iso(retain_from),
        retain_until_utc=_to_utc_iso(retain_until) if retain_until is not None else None,
        legal_hold_state=metadata.legal_hold_state,
        disposition_after_retention=(
            DispositionAfterRetention.BLOCKED_UNTIL_HOLD_RELEASE if active_hold else policy.disposition_after_retention
        ),
        deletion_blocked=active_hold or policy.worm_required,
        worm_required=policy.worm_required,
        object_lock_mode=policy.object_lock_mode,
        storage_bucket_id=policy.storage_bucket_id,
        cryptoshred_allowed_before_retention_end=False
        if active_hold
        else policy.cryptoshred_allowed_before_retention_end,
        audit_required=policy.audit_required,
        source_manifest_hash=metadata.manifest_hash,
        policy_snapshot_hash=build_policy_snapshot_hash(policy),
    )


def retention_policy_summary(policy_set: RetentionManifestPolicy) -> dict[str, object]:
    worm_policy_count = sum(1 for policy in policy_set.policy_defaults if policy.worm_required)
    follows_source_count = sum(
        1 for policy in policy_set.policy_defaults if policy.retention_mode == RetentionMode.FOLLOWS_SOURCE
    )
    return {
        "schema_version": policy_set.schema_version,
        "owner": policy_set.owner,
        "policy_count": len(policy_set.policy_defaults),
        "worm_policy_count": worm_policy_count,
        "follows_source_count": follows_source_count,
    }


def _record_requires_worm(record: SourceObjectRecord) -> bool:
    metadata = record.metadata
    return metadata.lifecycle_state in {
        SourceLifecycleState.BUSINESS_RECORD,
        SourceLifecycleState.WORM_EVIDENCE,
    } or metadata.classification in {DataClass.GOBD, DataClass.LEGAL_HOLD}


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise RetentionManifestError("retention timestamp must be UTC")
    return parsed.astimezone(UTC)


def _to_utc_iso(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def main() -> None:
    policy_set = load_retention_manifest_policy(Path("docs/retention_manifest_policy.json"))
    print(json.dumps(retention_policy_summary(policy_set), sort_keys=True))


if __name__ == "__main__":
    main()
