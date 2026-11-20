import base64
import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

import pytest

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import UserContext
from suite.kms.signing import AuditCheckpointSignature, AuditSigningAlgorithm
from suite.operations.audit_worm_snapshot import (
    AuditSnapshotEvent,
    AuditWormSnapshotError,
    AuditWormSnapshotManifest,
    AuditWormSnapshotResult,
    AuditWormSnapshotService,
)
from suite.storage.audit_worm_store import (
    AuditWormObjectReceipt,
    AuditWormObjectWriteRequest,
)


class FakeAuditSnapshotRepository:
    def __init__(self, events: tuple[AuditSnapshotEvent, ...]) -> None:
        self.events = events
        self.existing: AuditWormSnapshotResult | None = None
        self.persisted = False

    def load_events(self, *, tenant_id: str) -> tuple[AuditSnapshotEvent, ...]:
        return self.events

    def find_completed(
        self,
        *,
        tenant_id: str,
        checkpoint_id: str,
    ) -> AuditWormSnapshotResult | None:
        return self.existing

    def persist_completed(
        self,
        *,
        manifest: AuditWormSnapshotManifest,
        manifest_hash: str,
        signature: AuditCheckpointSignature,
        receipt: AuditWormObjectReceipt,
        bundle_hash: str,
        created_by: str,
    ) -> AuditWormSnapshotResult:
        self.persisted = True
        return AuditWormSnapshotResult(
            tenant_id=manifest.tenant_id,
            checkpoint_id=manifest.checkpoint_id,
            export_id="audit-worm-export-v2-test",
            through_sequence_number=manifest.through_sequence_number,
            event_count=manifest.event_count,
            manifest_hash=manifest_hash,
            bundle_hash=bundle_hash,
            signature_hash=signature.signature_sha256,
            storage_uri=receipt.storage_uri,
            object_version_id=receipt.object_version_id,
            object_lock_retain_until_utc=receipt.object_lock_retain_until_utc,
            audit_chain_ref="audit:completed",
        )


class FakeAuditCheckpointSigner:
    def __init__(self) -> None:
        self.calls = 0

    def sign_digest(
        self,
        *,
        tenant_id: str,
        digest: bytes,
        signed_at_utc: str,
    ) -> AuditCheckpointSignature:
        self.calls += 1
        signature = b"kms-signature"
        return AuditCheckpointSignature(
            tenant_id=tenant_id,
            signed_digest="sha256:" + digest.hex(),
            signing_algorithm=AuditSigningAlgorithm.ECDSA_SHA_256,
            kms_key_ref=f"kms-sign://{tenant_id}/audit/v4",
            kms_key_version=4,
            provider_profile="aws-kms",
            provider_key_id="arn:aws:kms:eu-central-1:123456789012:key/signing",
            public_key_der_base64=base64.b64encode(b"public-key-der").decode("ascii"),
            public_key_sha256="sha256:" + sha256(b"public-key-der").hexdigest(),
            signature_base64=base64.b64encode(signature).decode("ascii"),
            signature_sha256="sha256:" + sha256(signature).hexdigest(),
            signed_at_utc=signed_at_utc,
            provider_sign_request_id="kms-sign-request",
            provider_verify_request_id="kms-verify-request",
            provider_verified=True,
        )


class FakeAuditWormObjectStore:
    def __init__(self) -> None:
        self.calls = 0
        self.last_request: AuditWormObjectWriteRequest | None = None
        self.last_body: bytes | None = None

    def put_verified(
        self,
        *,
        request: AuditWormObjectWriteRequest,
        body: bytes,
    ) -> AuditWormObjectReceipt:
        self.calls += 1
        self.last_request = request
        self.last_body = body
        return AuditWormObjectReceipt(
            tenant_id=request.tenant_id,
            checkpoint_id=request.checkpoint_id,
            storage_provider="aws-s3",
            bucket_id=request.bucket_id,
            object_key=request.object_key,
            object_version_id="object-version-1",
            storage_uri=f"s3://{request.bucket_id}/{request.object_key}?versionId=object-version-1",
            bundle_hash=request.bundle_hash,
            object_lock_mode="compliance",
            object_lock_retain_until_utc=request.retain_until_utc,
            legal_hold_enabled=request.legal_hold_enabled,
            server_side_encryption="aws:kms",
            storage_kms_key_ref=request.storage_kms_key_ref,
            provider_storage_key_id="arn:aws:kms:eu-central-1:123456789012:key/storage",
            put_request_id="s3-put-request",
            get_request_id="s3-get-request",
            head_request_id="s3-head-request",
            readback_verified=True,
            object_lock_verified=True,
            encryption_verified=True,
        )


def snapshot_events(tenant_id: str = "tenant-audit") -> tuple[AuditSnapshotEvent, ...]:
    logger = InMemoryAuditLogger()
    user = UserContext(user_id="security-admin", tenant_id=tenant_id)
    first = logger.record(
        user_context=user,
        event_type="audit.first",
        input_text="sensitive prompt body",
        metadata={"purpose": "security_audit"},
    )
    second = logger.record(
        user_context=user,
        event_type="audit.second",
        output_text="sensitive output body",
        source_object_ids=["doc-1"],
    )
    return tuple(
        AuditSnapshotEvent(
            **event.model_dump(mode="json"),
            recorded_at_utc=f"2026-08-17T10:00:0{index}Z",
        )
        for index, event in enumerate((first, second), start=1)
    )


def service(
    repository: FakeAuditSnapshotRepository,
    signer: FakeAuditCheckpointSigner,
    store: FakeAuditWormObjectStore,
) -> AuditWormSnapshotService:
    return AuditWormSnapshotService(
        repository=repository,
        signer=signer,
        object_store=store,
        storage_kms_key_ref="kms://tenant-audit/confidential/v2",
        clock=lambda: datetime(2026, 8, 17, 10, 0, 0, tzinfo=UTC),
    )


def test_audit_worm_snapshot_service_verifies_chain_signs_manifest_and_persists_only_after_storage_proof() -> None:
    repository = FakeAuditSnapshotRepository(snapshot_events())
    signer = FakeAuditCheckpointSigner()
    store = FakeAuditWormObjectStore()

    result = service(repository, signer, store).create_for_tenant(
        tenant_id="tenant-audit",
        created_by="security-admin",
        legal_hold_enabled=True,
    )

    assert result.event_count == 2
    assert result.through_sequence_number == 2
    assert result.manifest_hash.startswith("sha256:")
    assert result.bundle_hash.startswith("sha256:")
    assert signer.calls == 1
    assert store.calls == 1
    assert repository.persisted is True
    assert store.last_request is not None
    assert store.last_request.legal_hold_enabled is True
    assert store.last_request.object_key.startswith("audit-snapshots/v2/")
    assert "tenant-audit" not in store.last_request.object_key
    assert store.last_body is not None
    bundle = json.loads(store.last_body)
    assert bundle["manifest"]["legal_hold_state"] == "active"
    assert bundle["signature"]["provider_verified"] is True
    assert bundle["events"][0]["input_hash"].startswith("sha256:")
    assert "sensitive prompt body" not in store.last_body.decode("utf-8")
    assert "sensitive output body" not in store.last_body.decode("utf-8")


def test_audit_worm_snapshot_service_rejects_tampered_chain_before_sign_or_write() -> None:
    events = list(snapshot_events())
    events[1] = events[1].model_copy(update={"previous_event_hash": "sha256:" + ("0" * 64)})
    repository = FakeAuditSnapshotRepository(tuple(events))
    signer = FakeAuditCheckpointSigner()
    store = FakeAuditWormObjectStore()

    with pytest.raises(AuditWormSnapshotError, match="verification failed"):
        service(repository, signer, store).create_for_tenant(
            tenant_id="tenant-audit",
            created_by="security-admin",
        )

    assert signer.calls == 0
    assert store.calls == 0
    assert repository.persisted is False


def test_audit_worm_snapshot_service_is_idempotent_for_completed_chain_prefix() -> None:
    repository = FakeAuditSnapshotRepository(snapshot_events())
    repository.existing = AuditWormSnapshotResult(
        tenant_id="tenant-audit",
        checkpoint_id="existing-checkpoint",
        export_id="existing-export",
        through_sequence_number=2,
        event_count=2,
        manifest_hash="sha256:" + ("a" * 64),
        bundle_hash="sha256:" + ("b" * 64),
        signature_hash="sha256:" + ("c" * 64),
        storage_uri="s3://evidence/existing?versionId=1",
        object_version_id="1",
        object_lock_retain_until_utc="2036-08-14T10:00:00Z",
        audit_chain_ref="audit:existing",
        reused_existing=True,
    )
    signer = FakeAuditCheckpointSigner()
    store = FakeAuditWormObjectStore()

    result = service(repository, signer, store).create_for_tenant(
        tenant_id="tenant-audit",
        created_by="security-admin",
    )

    assert result.reused_existing is True
    assert signer.calls == 0
    assert store.calls == 0
    assert repository.persisted is False


def test_audit_worm_snapshot_worker_is_explicit_default_off_and_documented_without_local_private_keys() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    runbook = Path("docs/operations/AUDIT_WORM_SNAPSHOTS.md").read_text(encoding="utf-8")
    audit_schema = Path("docs/AI_AUDIT_SCHEMA.md").read_text(encoding="utf-8")
    adr = Path("ARCHITECTURE_DECISIONS/ADR-0077-kms-signed-audit-worm-snapshots.md").read_text(encoding="utf-8")

    assert 'profiles: ["audit-worm"]' in compose
    assert "SUITE_AUDIT_WORM_SNAPSHOT_ENABLED: ${SUITE_AUDIT_WORM_SNAPSHOT_ENABLED:-0}" in compose
    assert "python -m suite.operations.audit_worm_snapshot_worker" in compose
    assert "private key" not in compose.lower()
    assert "exact-version readback" in runbook
    assert "deletion attempt against that exact protected version is denied" in runbook
    assert "collabio.audit_snapshot_checkpoints_v2" in audit_schema
    assert "No private key or signing secret enters Collabio" in audit_schema
    assert "Status: Accepted" in adr
