from pathlib import Path

import pytest

from suite.ai_control_plane.models import DataClass
from suite.storage.adapter_policy import ObjectLockMode, load_storage_adapter_policy
from suite.storage.retention import (
    DispositionAfterRetention,
    RetentionManifestError,
    RetentionMode,
    build_retention_manifest,
    load_retention_manifest_policy,
    retention_policy_summary,
)
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
RETENTION_POLICY_PATH = REPO_ROOT / "docs" / "retention_manifest_policy.json"
STORAGE_POLICY_PATH = REPO_ROOT / "docs" / "storage_adapter_policy.json"
ADR_PATH = REPO_ROOT / "ARCHITECTURE_DECISIONS" / "ADR-0025-retention-defaults-and-manifest.md"
BACKLOG_PATH = REPO_ROOT / "docs" / "ADR_BACKLOG.md"


def record_for(
    *,
    classification: DataClass = DataClass.INTERNAL,
    retention_policy_id: str = "rp-standard",
    lifecycle_state: SourceLifecycleState = SourceLifecycleState.WORKING,
    legal_hold_state: LegalHoldState = LegalHoldState.NONE,
    object_type: SourceObjectType = SourceObjectType.DOCUMENT,
    object_id: str = "doc-1",
    text: str = "Retention-governed content",
) -> SourceObjectRecord:
    content = text.encode("utf-8")
    draft = SourceObjectMetadata(
        tenant_id="tenant-1",
        object_id=object_id,
        object_type=object_type,
        version_id="v1",
        title="Retention object",
        owner_principal_id="user-owner",
        created_by="user-creator",
        created_at_utc="2026-06-10T00:00:00Z",
        updated_at_utc="2026-06-10T00:01:00Z",
        classification=classification,
        retention_policy_id=retention_policy_id,
        legal_hold_state=legal_hold_state,
        kms_key_ref=f"kms://tenant-1/{classification.value}/v1",
        manifest_hash="sha256:0000000000000000000000000000000000000000000000000000000000000000",
        audit_chain_ref="audit:chain-1",
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


def test_retention_manifest_policy_declares_defaults() -> None:
    policy = load_retention_manifest_policy(RETENTION_POLICY_PATH)

    assert retention_policy_summary(policy) == {
        "schema_version": "retention_manifest_policy.v1",
        "owner": "platform-retention",
        "policy_count": 9,
        "worm_policy_count": 3,
        "follows_source_count": 1,
    }
    assert policy.policy("rp-standard").retention_days == 365
    assert policy.policy("rp-gobd-10y").worm_required
    assert policy.policy("rp-legal-hold").retention_mode == RetentionMode.UNTIL_HOLD_RELEASE
    assert policy.policy("rp-embedding-follows-source").retention_mode == RetentionMode.FOLLOWS_SOURCE


def test_retention_policy_bucket_ids_match_storage_adapter_policy() -> None:
    retention_policy = load_retention_manifest_policy(RETENTION_POLICY_PATH)
    storage_policy = load_storage_adapter_policy(STORAGE_POLICY_PATH)
    bucket_ids = {bucket.bucket_id for bucket in storage_policy.bucket_profiles}

    assert {policy.storage_bucket_id for policy in retention_policy.policy_defaults} <= bucket_ids


def test_retention_manifest_for_standard_source_sets_retain_until_and_bucket() -> None:
    policy = load_retention_manifest_policy(RETENTION_POLICY_PATH)

    manifest = build_retention_manifest(record_for(), policy)

    assert manifest.retention_policy_id == "rp-standard"
    assert manifest.retention_mode == RetentionMode.FIXED_DAYS
    assert manifest.retention_days == 365
    assert manifest.retain_from_utc == "2026-06-10T00:00:00Z"
    assert manifest.retain_until_utc == "2027-06-10T00:00:00Z"
    assert manifest.storage_bucket_id == "working-objects"
    assert manifest.object_lock_mode == ObjectLockMode.NONE
    assert not manifest.worm_required
    assert not manifest.deletion_blocked
    assert manifest.policy_snapshot_hash.startswith("sha256:")


def test_gobd_business_record_manifest_requires_worm_and_blocks_early_cryptoshred() -> None:
    policy = load_retention_manifest_policy(RETENTION_POLICY_PATH)
    record = record_for(
        classification=DataClass.GOBD,
        retention_policy_id="rp-gobd-10y",
        lifecycle_state=SourceLifecycleState.BUSINESS_RECORD,
    )

    manifest = build_retention_manifest(record, policy)

    assert manifest.worm_required
    assert manifest.object_lock_mode == ObjectLockMode.COMPLIANCE
    assert manifest.storage_bucket_id == "business-records"
    assert manifest.retention_days == 3650
    assert manifest.deletion_blocked
    assert not manifest.cryptoshred_allowed_before_retention_end


def test_active_legal_hold_manifest_blocks_disposition_until_release() -> None:
    policy = load_retention_manifest_policy(RETENTION_POLICY_PATH)
    record = record_for(
        classification=DataClass.LEGAL_HOLD,
        retention_policy_id="rp-legal-hold",
        lifecycle_state=SourceLifecycleState.WORM_EVIDENCE,
        legal_hold_state=LegalHoldState.ACTIVE,
    )

    manifest = build_retention_manifest(record, policy)

    assert manifest.retention_mode == RetentionMode.UNTIL_HOLD_RELEASE
    assert manifest.retain_until_utc is None
    assert manifest.deletion_blocked
    assert manifest.disposition_after_retention == DispositionAfterRetention.BLOCKED_UNTIL_HOLD_RELEASE
    assert not manifest.cryptoshred_allowed_before_retention_end


def test_worm_lifecycle_rejects_non_worm_retention_policy() -> None:
    policy = load_retention_manifest_policy(RETENTION_POLICY_PATH)
    record = record_for(lifecycle_state=SourceLifecycleState.BUSINESS_RECORD)

    with pytest.raises(RetentionManifestError, match="requires WORM"):
        build_retention_manifest(record, policy)


def test_legal_hold_rejects_policy_that_disallows_holds() -> None:
    policy = load_retention_manifest_policy(RETENTION_POLICY_PATH)
    record = record_for(retention_policy_id="rp-temporary-7d", legal_hold_state=LegalHoldState.ACTIVE)

    with pytest.raises(RetentionManifestError, match="does not allow legal hold"):
        build_retention_manifest(record, policy)


def test_retention_adr_and_backlog_are_in_sync() -> None:
    adr = ADR_PATH.read_text(encoding="utf-8")
    backlog = BACKLOG_PATH.read_text(encoding="utf-8")

    assert "Status: accepted" in adr
    assert "RetentionManifest" in adr
    assert "retention_manifest_policy.v1" in adr
    assert "- [x] ADR-0025: Retention policy engine." in backlog
