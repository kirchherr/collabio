from pathlib import Path

import pytest

from suite.ai_control_plane.models import DataClass
from suite.storage.legal_hold import (
    LegalHoldAction,
    LegalHoldService,
    LegalHoldTransitionError,
    PlaceLegalHoldCommand,
    ReleaseLegalHoldCommand,
)
from suite.storage.retention import DispositionAfterRetention, RetentionMode, load_retention_manifest_policy
from suite.storage.source_objects import (
    InMemorySourceObjectRepository,
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
ADR_PATH = REPO_ROOT / "ARCHITECTURE_DECISIONS" / "ADR-0026-legal-hold-api-and-reevaluation.md"
BACKLOG_PATH = REPO_ROOT / "docs" / "ADR_BACKLOG.md"


def record_for(
    *,
    retention_policy_id: str = "rp-standard",
    classification: DataClass = DataClass.INTERNAL,
    lifecycle_state: SourceLifecycleState = SourceLifecycleState.WORKING,
    legal_hold_state: LegalHoldState = LegalHoldState.NONE,
    version_id: str = "v1",
) -> SourceObjectRecord:
    text = "Legal hold governed source text"
    content = text.encode("utf-8")
    draft = SourceObjectMetadata(
        tenant_id="tenant-1",
        object_id="doc-1",
        object_type=SourceObjectType.DOCUMENT,
        version_id=version_id,
        title="Legal hold object",
        owner_principal_id="user-owner",
        created_by="user-creator",
        created_at_utc="2026-06-10T00:00:00Z",
        updated_at_utc="2026-06-10T00:01:00Z",
        classification=classification,
        retention_policy_id=retention_policy_id,
        legal_hold_state=legal_hold_state,
        kms_key_ref="kms://tenant-1/internal/v1",
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


def service_for(record: SourceObjectRecord) -> LegalHoldService:
    repository = InMemorySourceObjectRepository(records=(record,))
    return LegalHoldService(repository, load_retention_manifest_policy(RETENTION_POLICY_PATH))


def place_command(*, source_version_id: str = "v1", new_version_id: str = "v2") -> PlaceLegalHoldCommand:
    return PlaceLegalHoldCommand(
        tenant_id="tenant-1",
        object_id="doc-1",
        source_version_id=source_version_id,
        new_version_id=new_version_id,
        hold_id="hold-1",
        matter_id="matter-1",
        reason="Regulatory inquiry",
        requested_by="user-legal",
        approved_by="user-approver",
        audit_chain_ref="audit:hold-placed",
        occurred_at_utc="2026-06-11T00:00:00Z",
    )


def release_command(*, source_version_id: str = "v2", new_version_id: str = "v3") -> ReleaseLegalHoldCommand:
    return ReleaseLegalHoldCommand(
        tenant_id="tenant-1",
        object_id="doc-1",
        source_version_id=source_version_id,
        new_version_id=new_version_id,
        hold_id="hold-1",
        matter_id="matter-1",
        release_reason="Matter closed",
        next_retention_policy_id="rp-standard",
        requested_by="user-legal",
        approved_by="user-approver",
        audit_chain_ref="audit:hold-released",
        occurred_at_utc="2026-06-12T00:00:00Z",
    )


def test_place_legal_hold_creates_new_version_and_blocks_retention_disposition() -> None:
    original = record_for()
    service = service_for(original)

    decision = service.place_hold(place_command())

    assert decision.action == LegalHoldAction.PLACED
    assert decision.previous_version_id == "v1"
    assert decision.new_version_id == "v2"
    assert decision.record.metadata.version_id == "v2"
    assert decision.record.metadata.legal_hold_state == LegalHoldState.ACTIVE
    assert decision.record.metadata.updated_at_utc == "2026-06-11T00:00:00Z"
    assert decision.record.metadata.audit_chain_ref == "audit:hold-placed"
    assert decision.record.metadata.manifest_hash != original.metadata.manifest_hash
    assert decision.retention_manifest.legal_hold_state == LegalHoldState.ACTIVE
    assert decision.retention_manifest.deletion_blocked
    assert (
        decision.retention_manifest.disposition_after_retention == DispositionAfterRetention.BLOCKED_UNTIL_HOLD_RELEASE
    )
    assert not decision.retention_manifest.cryptoshred_allowed_before_retention_end


def test_release_legal_hold_creates_new_version_and_reevaluates_retention_manifest() -> None:
    original = record_for()
    service = service_for(original)
    placed = service.place_hold(place_command())

    released = service.release_hold(release_command())

    assert placed.record.metadata.legal_hold_state == LegalHoldState.ACTIVE
    assert released.action == LegalHoldAction.RELEASED
    assert released.previous_version_id == "v2"
    assert released.new_version_id == "v3"
    assert released.record.metadata.legal_hold_state == LegalHoldState.NONE
    assert released.record.metadata.retention_policy_id == "rp-standard"
    assert released.record.metadata.audit_chain_ref == "audit:hold-released"
    assert released.retention_manifest.legal_hold_state == LegalHoldState.NONE
    assert released.retention_manifest.retention_mode == RetentionMode.FIXED_DAYS
    assert released.retention_manifest.retain_until_utc == "2027-06-10T00:00:00Z"
    assert not released.retention_manifest.deletion_blocked
    assert released.retention_manifest.disposition_after_retention == DispositionAfterRetention.RESTRICT


def test_release_requires_active_legal_hold() -> None:
    service = service_for(record_for())

    with pytest.raises(LegalHoldTransitionError, match="active legal hold"):
        service.release_hold(release_command(source_version_id="v1", new_version_id="v2"))


def test_place_rejects_already_active_legal_hold() -> None:
    service = service_for(record_for(legal_hold_state=LegalHoldState.ACTIVE))

    with pytest.raises(LegalHoldTransitionError, match="already under active legal hold"):
        service.place_hold(place_command())


def test_legal_hold_commands_require_new_versions_and_audit_reference() -> None:
    with pytest.raises(ValueError, match="new_version_id"):
        place_command(source_version_id="v1", new_version_id="v1")

    with pytest.raises(ValueError, match="audit_chain_ref"):
        PlaceLegalHoldCommand(
            tenant_id="tenant-1",
            object_id="doc-1",
            source_version_id="v1",
            new_version_id="v2",
            hold_id="hold-1",
            matter_id="matter-1",
            reason="Regulatory inquiry",
            requested_by="user-legal",
            approved_by="user-approver",
            audit_chain_ref="hold-placed",
            occurred_at_utc="2026-06-11T00:00:00Z",
        )


def test_legal_hold_adr_and_backlog_are_in_sync() -> None:
    adr = ADR_PATH.read_text(encoding="utf-8")
    backlog = BACKLOG_PATH.read_text(encoding="utf-8")

    assert "Status: accepted" in adr
    assert "LegalHoldService" in adr
    assert "RetentionManifest" in adr
    assert "- [x] ADR-0026: Legal hold semantics." in backlog
