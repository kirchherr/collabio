import re
from pathlib import Path

from suite.storage.adapter_policy import ObjectLockMode, load_storage_adapter_policy, storage_adapter_policy_summary
from suite.storage.source_objects import SourceObjectType

REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = REPO_ROOT / "docs" / "storage_adapter_policy.json"
ADR_PATH = REPO_ROOT / "ARCHITECTURE_DECISIONS" / "ADR-0024-s3-compatible-object-storage.md"
BACKLOG_PATH = REPO_ROOT / "docs" / "ADR_BACKLOG.md"
STORAGE_ADAPTER_PLAN_PATH = REPO_ROOT / "docs" / "STORAGE_ADAPTER_PLAN.md"
STORAGE_MANIFEST_PATH = REPO_ROOT / "docs" / "STORAGE_MANIFEST.md"
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"
REQUIREMENTS_PATH = REPO_ROOT / "requirements.txt"


def test_storage_adapter_policy_declares_s3_minio_boundary() -> None:
    policy = load_storage_adapter_policy(POLICY_PATH)

    assert storage_adapter_policy_summary(policy) == {
        "schema_version": "storage_adapter_policy.v1",
        "owner": "platform-storage",
        "provider_api": "s3-compatible",
        "development_provider": "minio",
        "bucket_profile_count": 4,
        "object_lock_bucket_count": 2,
    }
    assert "aws_s3_object_lock" in policy.production_compatibility_targets
    assert "minio_object_lock" in policy.production_compatibility_targets
    assert "source_object_write_guard" in policy.adapter_requirements
    assert "no_direct_sdk_access_from_feature_code" in policy.adapter_requirements
    assert "feature_code_direct_s3_sdk_call" in policy.forbidden_operations


def test_storage_adapter_policy_covers_all_source_object_types() -> None:
    policy = load_storage_adapter_policy(POLICY_PATH)
    covered_source_types = {
        source_type for profile in policy.bucket_profiles for source_type in profile.source_object_types
    }

    assert covered_source_types >= {source_type.value for source_type in SourceObjectType}


def test_storage_adapter_policy_requires_secure_bucket_profiles() -> None:
    policy = load_storage_adapter_policy(POLICY_PATH)

    for profile in policy.bucket_profiles:
        assert profile.versioning_required
        assert profile.encryption_required
        assert profile.kms_key_refs_required
        assert "storage_object_manifest_hash_check" in profile.restore_integrity_checks
        assert "source_object_manifest_hash_check" in profile.restore_integrity_checks
        assert "content_hash_check" in profile.restore_integrity_checks

    business_records = policy.bucket("business-records")
    evidence_records = policy.bucket("evidence-records")
    assert business_records.object_lock_mode == ObjectLockMode.COMPLIANCE
    assert evidence_records.object_lock_mode == ObjectLockMode.COMPLIANCE
    assert business_records.legal_hold_supported
    assert evidence_records.legal_hold_supported
    assert business_records.default_retention_days >= 2555
    assert evidence_records.default_retention_days >= 3650


def test_storage_adapter_adr_and_backlog_are_in_sync() -> None:
    adr = ADR_PATH.read_text(encoding="utf-8")
    backlog = BACKLOG_PATH.read_text(encoding="utf-8")

    assert "Status: accepted" in adr
    assert "S3-compatible" in adr
    assert "MinIO" in adr
    assert "Object Lock" in adr
    assert "SourceObjectWriteGuard" in adr
    assert "- [x] ADR-0024: S3-compatible object storage and MinIO/AWS compatibility target." in backlog


def test_storage_adapter_docs_bind_sdk_behind_content_store_port() -> None:
    adapter_plan = STORAGE_ADAPTER_PLAN_PATH.read_text(encoding="utf-8")
    storage_manifest = STORAGE_MANIFEST_PATH.read_text(encoding="utf-8")

    assert "`S3CompatibleObjectStoreClient`" in adapter_plan
    assert "`SourceObjectContentStore`" in adapter_plan
    assert "`s3_compatible_provider_profile_evidence.v1`" in adapter_plan
    assert "No direct SDK calls from feature code." in adapter_plan
    assert "`S3CompatibleSourceObjectContentStore`" in storage_manifest
    assert "`Boto3S3CompatibleObjectStoreClient`" in storage_manifest
    assert "`source_object_content_recovery_evidence.v1`" in storage_manifest
    assert "`s3_compatible_provider_profile_evidence.v1`" in storage_manifest


def test_object_storage_is_mandatory_api_dependency_and_runs_provider_profile_evidence_check() -> None:
    compose = COMPOSE_PATH.read_text(encoding="utf-8")
    requirements = REQUIREMENTS_PATH.read_text(encoding="utf-8")

    assert re.search(r"^boto3==[0-9]+\.[0-9]+\.[0-9]+$", requirements, flags=re.MULTILINE)
    assert "\n  minio:\n" in compose
    assert 'profiles: ["object-storage"]' not in compose
    assert "\n  object-storage-profile-check:\n" in compose
    assert "python -m suite.storage.s3_provider_profile_check" in compose
    assert 'SUITE_S3_BOOTSTRAP_BUCKETS: "1"' in compose
    assert "\n  source-object-runtime-bootstrap:\n" in compose
    assert "python -m suite.storage.persistent_source_object_runtime" in compose
    assert "source-object-runtime-bootstrap:\n        condition: service_completed_successfully" in compose
