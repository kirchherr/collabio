from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field, model_validator


class ObjectLockMode(StrEnum):
    NONE = "none"
    GOVERNANCE = "governance"
    COMPLIANCE = "compliance"


class BucketProfile(BaseModel):
    bucket_id: str
    purpose: str
    source_object_types: list[str] = Field(min_length=1)
    lifecycle_states: list[str] = Field(min_length=1)
    versioning_required: bool = True
    object_lock_mode: ObjectLockMode = ObjectLockMode.NONE
    legal_hold_supported: bool = False
    default_retention_days: int = Field(ge=0)
    encryption_required: bool = True
    kms_key_refs_required: bool = True
    replication_target_required_before_production: bool = True
    restore_integrity_checks: list[str] = Field(min_length=1)

    @property
    def object_lock_required(self) -> bool:
        return self.object_lock_mode != ObjectLockMode.NONE

    @model_validator(mode="after")
    def require_secure_bucket_profile(self) -> BucketProfile:
        if not self.bucket_id.strip():
            raise ValueError("bucket_id must not be empty")
        if not self.purpose.strip():
            raise ValueError("purpose must not be empty")
        if not self.versioning_required:
            raise ValueError("S3-compatible object buckets must require versioning")
        if not self.encryption_required:
            raise ValueError("object buckets must require encryption")
        if not self.kms_key_refs_required:
            raise ValueError("object buckets must require KMS key references")
        if self.object_lock_required:
            if self.default_retention_days < 1:
                raise ValueError("object-lock buckets require a positive default retention")
            if not self.legal_hold_supported:
                raise ValueError("object-lock buckets must support legal hold")
            required_checks = {"source_object_manifest_hash_check", "content_hash_check", "retention_policy_check"}
            missing_checks = sorted(required_checks - set(self.restore_integrity_checks))
            if missing_checks:
                raise ValueError(f"object-lock buckets are missing restore checks: {', '.join(missing_checks)}")
        return self


class StorageAdapterPolicy(BaseModel):
    schema_version: str
    owner: str
    provider_api: str
    development_provider: str
    production_compatibility_targets: list[str] = Field(min_length=1)
    required_source_object_types: list[str] = Field(min_length=1)
    adapter_requirements: list[str] = Field(min_length=1)
    forbidden_operations: list[str] = Field(min_length=1)
    bucket_profiles: list[BucketProfile] = Field(min_length=1)

    @model_validator(mode="after")
    def require_complete_adapter_policy(self) -> StorageAdapterPolicy:
        if self.provider_api != "s3-compatible":
            raise ValueError("provider_api must be s3-compatible")
        if self.development_provider != "minio":
            raise ValueError("development_provider must be minio")

        bucket_ids = [profile.bucket_id for profile in self.bucket_profiles]
        duplicate_ids = sorted({bucket_id for bucket_id in bucket_ids if bucket_ids.count(bucket_id) > 1})
        if duplicate_ids:
            raise ValueError(f"duplicate bucket profile ids: {', '.join(duplicate_ids)}")

        covered_source_types = {
            source_type for profile in self.bucket_profiles for source_type in profile.source_object_types
        }
        missing_source_types = sorted(set(self.required_source_object_types) - covered_source_types)
        if missing_source_types:
            raise ValueError(f"source object types missing bucket coverage: {', '.join(missing_source_types)}")

        if not any(profile.object_lock_required for profile in self.bucket_profiles):
            raise ValueError("at least one bucket profile must require object lock")

        required_requirements = {
            "source_object_write_guard",
            "bucket_versioning",
            "object_lock_for_records",
            "restore_manifest_verification",
        }
        missing_requirements = sorted(required_requirements - set(self.adapter_requirements))
        if missing_requirements:
            raise ValueError(f"adapter policy is missing requirements: {', '.join(missing_requirements)}")
        return self

    def bucket(self, bucket_id: str) -> BucketProfile:
        for profile in self.bucket_profiles:
            if profile.bucket_id == bucket_id:
                return profile
        raise LookupError(f"Unknown bucket profile: {bucket_id}")


def load_storage_adapter_policy(path: Path) -> StorageAdapterPolicy:
    return StorageAdapterPolicy.model_validate_json(path.read_text(encoding="utf-8"))


def storage_adapter_policy_summary(policy: StorageAdapterPolicy) -> dict[str, object]:
    object_lock_bucket_count = sum(1 for profile in policy.bucket_profiles if profile.object_lock_required)
    return {
        "schema_version": policy.schema_version,
        "owner": policy.owner,
        "provider_api": policy.provider_api,
        "development_provider": policy.development_provider,
        "bucket_profile_count": len(policy.bucket_profiles),
        "object_lock_bucket_count": object_lock_bucket_count,
    }


def main() -> None:
    policy = load_storage_adapter_policy(Path("docs/storage_adapter_policy.json"))
    print(json.dumps(storage_adapter_policy_summary(policy), sort_keys=True))


if __name__ == "__main__":
    main()
