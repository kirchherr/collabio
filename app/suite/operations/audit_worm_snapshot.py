from __future__ import annotations

import base64
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any, Protocol

import psycopg
from pydantic import BaseModel, Field, field_validator, model_validator

from suite.ai_control_plane.audit import verify_audit_chain
from suite.ai_control_plane.models import AuditEvent
from suite.kms.signing import AuditCheckpointSignature, AuditCheckpointSigner
from suite.storage.audit_worm_store import (
    AuditWormObjectReceipt,
    AuditWormObjectStore,
    AuditWormObjectWriteRequest,
)


class AuditWormSnapshotError(RuntimeError):
    pass


class AuditSnapshotEvent(BaseModel):
    event_id: str
    schema_version: str
    sequence_number: int = Field(ge=1)
    tenant_id: str
    user_id: str
    event_type: str
    model_id: str | None = None
    prompt_template_id: str | None = None
    source_object_ids: list[str] = Field(default_factory=list)
    input_hash: str | None = None
    output_hash: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    previous_event_hash: str
    event_hash: str
    recorded_at_utc: str

    @field_validator("recorded_at_utc")
    @classmethod
    def require_utc_timestamp(cls, value: str) -> str:
        _parse_utc(value)
        return value.strip()

    def audit_event(self) -> AuditEvent:
        return AuditEvent.model_validate(self.model_dump(exclude={"recorded_at_utc"}))


class AuditWormSnapshotManifest(BaseModel):
    schema_version: str = "audit_worm_snapshot_manifest.v2"
    tenant_id: str
    checkpoint_id: str
    from_sequence_number: int = Field(default=1, ge=1)
    through_sequence_number: int = Field(ge=1)
    event_count: int = Field(ge=1)
    first_event_hash: str
    last_event_hash: str
    events_hash: str
    generated_at_utc: str
    generated_by: str
    classification: str = "confidential"
    retention_policy_id: str
    retain_until_utc: str
    legal_hold_state: str

    @field_validator("tenant_id", "checkpoint_id", "generated_by", "retention_policy_id")
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("field must not be empty")
        return normalized

    @field_validator("first_event_hash", "last_event_hash", "events_hash")
    @classmethod
    def require_namespaced_hash(cls, value: str) -> str:
        normalized = value.strip()
        if ":" not in normalized or not normalized.split(":", 1)[0]:
            raise ValueError("field must be a namespaced hash")
        return normalized

    @field_validator("generated_at_utc", "retain_until_utc")
    @classmethod
    def require_utc_timestamp(cls, value: str) -> str:
        _parse_utc(value)
        return value.strip()

    @model_validator(mode="after")
    def require_consistent_range(self) -> AuditWormSnapshotManifest:
        if self.from_sequence_number != 1:
            raise ValueError("audit snapshots must begin at sequence 1")
        if self.event_count != self.through_sequence_number:
            raise ValueError("audit snapshot event count must match the sequence range")
        if self.classification != "confidential":
            raise ValueError("audit snapshots must be classified confidential")
        if self.legal_hold_state not in {"none", "active"}:
            raise ValueError("legal_hold_state must be none or active")
        if _parse_utc(self.retain_until_utc) <= _parse_utc(self.generated_at_utc):
            raise ValueError("audit snapshot retention must end after generation")
        return self


class AuditWormSnapshotBundle(BaseModel):
    schema_version: str = "audit_worm_snapshot_bundle.v2"
    manifest: AuditWormSnapshotManifest
    manifest_hash: str
    signature: AuditCheckpointSignature
    events: list[AuditSnapshotEvent] = Field(min_length=1)

    @model_validator(mode="after")
    def require_bound_bundle(self) -> AuditWormSnapshotBundle:
        if _sha256_ref(_canonical_bytes(self.manifest.model_dump(mode="json"))) != self.manifest_hash:
            raise ValueError("manifest_hash does not match manifest")
        if self.signature.tenant_id != self.manifest.tenant_id:
            raise ValueError("signature tenant does not match manifest tenant")
        if self.signature.signed_digest != self.manifest_hash:
            raise ValueError("signature digest does not match manifest hash")
        event_payload = [event.model_dump(mode="json") for event in self.events]
        if _sha256_ref(_canonical_bytes(event_payload)) != self.manifest.events_hash:
            raise ValueError("events_hash does not match snapshot events")
        if len(self.events) != self.manifest.event_count:
            raise ValueError("event count does not match manifest")
        if self.events[0].event_hash != self.manifest.first_event_hash:
            raise ValueError("first event hash does not match manifest")
        if self.events[-1].event_hash != self.manifest.last_event_hash:
            raise ValueError("last event hash does not match manifest")
        if self.events[-1].sequence_number != self.manifest.through_sequence_number:
            raise ValueError("last event sequence does not match manifest")
        return self


class AuditWormSnapshotResult(BaseModel):
    schema_version: str = "audit_worm_snapshot_result.v2"
    tenant_id: str
    checkpoint_id: str
    export_id: str
    through_sequence_number: int = Field(ge=1)
    event_count: int = Field(ge=1)
    manifest_hash: str
    bundle_hash: str
    signature_hash: str
    storage_uri: str
    object_version_id: str
    object_lock_retain_until_utc: str
    audit_chain_ref: str
    reused_existing: bool = False


class AuditWormSnapshotRepository(Protocol):
    def load_events(self, *, tenant_id: str) -> tuple[AuditSnapshotEvent, ...]: ...

    def find_completed(
        self,
        *,
        tenant_id: str,
        checkpoint_id: str,
    ) -> AuditWormSnapshotResult | None: ...

    def persist_completed(
        self,
        *,
        manifest: AuditWormSnapshotManifest,
        manifest_hash: str,
        signature: AuditCheckpointSignature,
        receipt: AuditWormObjectReceipt,
        bundle_hash: str,
        created_by: str,
    ) -> AuditWormSnapshotResult: ...


class PgAuditWormSnapshotRepository:
    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    def load_events(self, *, tenant_id: str) -> tuple[AuditSnapshotEvent, ...]:
        with psycopg.connect(self.database_dsn) as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            self._set_tenant(connection, tenant_id)
            self._lock_tenant_chain(connection, tenant_id)
            rows = connection.execute(
                """
                SELECT
                    event_id,
                    schema_version,
                    sequence_number,
                    tenant_id,
                    user_id,
                    event_type,
                    model_id,
                    prompt_template_id,
                    source_object_ids,
                    input_hash,
                    output_hash,
                    metadata,
                    previous_event_hash,
                    event_hash,
                    recorded_at_utc
                FROM collabio.audit_events
                WHERE tenant_id = %s
                ORDER BY sequence_number
                """,
                (tenant_id,),
            ).fetchall()
        return tuple(self._event_from_row(row) for row in rows)

    def find_completed(
        self,
        *,
        tenant_id: str,
        checkpoint_id: str,
    ) -> AuditWormSnapshotResult | None:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            row = connection.execute(
                """
                SELECT
                    checkpoint.tenant_id,
                    checkpoint.checkpoint_id,
                    receipt.export_id,
                    checkpoint.through_sequence_number,
                    checkpoint.event_count,
                    checkpoint.manifest_hash,
                    receipt.bundle_hash,
                    checkpoint.signature_sha256,
                    receipt.storage_uri,
                    receipt.object_version_id,
                    receipt.object_lock_retain_until_utc,
                    receipt.audit_chain_ref
                FROM collabio.audit_snapshot_checkpoints_v2 AS checkpoint
                JOIN collabio.audit_worm_snapshot_receipts_v2 AS receipt
                  ON receipt.tenant_id = checkpoint.tenant_id
                 AND receipt.checkpoint_id = checkpoint.checkpoint_id
                WHERE checkpoint.tenant_id = %s
                  AND checkpoint.checkpoint_id = %s
                ORDER BY receipt.created_at_utc
                LIMIT 1
                """,
                (tenant_id, checkpoint_id),
            ).fetchone()
        if row is None:
            return None
        return self._result_from_row(row, reused_existing=True)

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
        if signature.tenant_id != manifest.tenant_id or receipt.tenant_id != manifest.tenant_id:
            raise AuditWormSnapshotError("checkpoint, signature and receipt tenants must match")
        if receipt.checkpoint_id != manifest.checkpoint_id:
            raise AuditWormSnapshotError("storage receipt checkpoint does not match manifest")
        export_id = _stable_id("audit-worm-export-v2", manifest.checkpoint_id, receipt.object_version_id)
        checkpoint_audit_ref = _evidence_ref(
            "audit-snapshot-checkpoint-v2",
            manifest.tenant_id,
            manifest.checkpoint_id,
            manifest_hash,
            signature.signature_sha256,
        )
        export_audit_ref = _evidence_ref(
            "audit-worm-snapshot-receipt-v2",
            manifest.tenant_id,
            export_id,
            bundle_hash,
            receipt.storage_uri,
        )

        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, manifest.tenant_id)
            self._lock_tenant_chain(connection, manifest.tenant_id)
            connection.execute(
                """
                INSERT INTO collabio.audit_snapshot_checkpoints_v2 (
                    tenant_id,
                    checkpoint_id,
                    through_sequence_number,
                    event_count,
                    first_event_hash,
                    last_event_hash,
                    events_hash,
                    manifest_hash,
                    signature_algorithm,
                    signing_message_type,
                    signature_key_ref,
                    signature_key_version,
                    provider_profile,
                    provider_key_id,
                    public_key_sha256,
                    signature,
                    signature_sha256,
                    provider_sign_request_id,
                    provider_verify_request_id,
                    provider_verified,
                    signed_at_utc,
                    created_by,
                    audit_chain_ref
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    manifest.tenant_id,
                    manifest.checkpoint_id,
                    manifest.through_sequence_number,
                    manifest.event_count,
                    manifest.first_event_hash,
                    manifest.last_event_hash,
                    manifest.events_hash,
                    manifest_hash,
                    signature.signing_algorithm.value,
                    signature.signing_message_type,
                    signature.kms_key_ref,
                    signature.kms_key_version,
                    signature.provider_profile,
                    signature.provider_key_id,
                    signature.public_key_sha256,
                    base64.b64decode(signature.signature_base64, validate=True),
                    signature.signature_sha256,
                    signature.provider_sign_request_id,
                    signature.provider_verify_request_id,
                    signature.provider_verified,
                    signature.signed_at_utc,
                    created_by,
                    checkpoint_audit_ref,
                ),
            )
            connection.execute(
                """
                INSERT INTO collabio.audit_worm_snapshot_receipts_v2 (
                    tenant_id,
                    export_id,
                    checkpoint_id,
                    bundle_hash,
                    storage_provider,
                    bucket_id,
                    object_key,
                    object_version_id,
                    storage_uri,
                    object_lock_mode,
                    object_lock_retain_until_utc,
                    legal_hold_enabled,
                    server_side_encryption,
                    storage_kms_key_ref,
                    provider_storage_key_id,
                    put_request_id,
                    get_request_id,
                    head_request_id,
                    readback_verified,
                    object_lock_verified,
                    encryption_verified,
                    created_by,
                    audit_chain_ref
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    manifest.tenant_id,
                    export_id,
                    manifest.checkpoint_id,
                    bundle_hash,
                    receipt.storage_provider,
                    receipt.bucket_id,
                    receipt.object_key,
                    receipt.object_version_id,
                    receipt.storage_uri,
                    receipt.object_lock_mode,
                    receipt.object_lock_retain_until_utc,
                    receipt.legal_hold_enabled,
                    receipt.server_side_encryption,
                    receipt.storage_kms_key_ref,
                    receipt.provider_storage_key_id,
                    receipt.put_request_id,
                    receipt.get_request_id,
                    receipt.head_request_id,
                    receipt.readback_verified,
                    receipt.object_lock_verified,
                    receipt.encryption_verified,
                    created_by,
                    export_audit_ref,
                ),
            )
            connection.commit()

        return AuditWormSnapshotResult(
            tenant_id=manifest.tenant_id,
            checkpoint_id=manifest.checkpoint_id,
            export_id=export_id,
            through_sequence_number=manifest.through_sequence_number,
            event_count=manifest.event_count,
            manifest_hash=manifest_hash,
            bundle_hash=bundle_hash,
            signature_hash=signature.signature_sha256,
            storage_uri=receipt.storage_uri,
            object_version_id=receipt.object_version_id,
            object_lock_retain_until_utc=receipt.object_lock_retain_until_utc,
            audit_chain_ref=export_audit_ref,
        )

    def _event_from_row(self, row: tuple[Any, ...]) -> AuditSnapshotEvent:
        metadata = row[11]
        if not isinstance(metadata, dict):
            metadata = dict(metadata)
        return AuditSnapshotEvent(
            event_id=str(row[0]),
            schema_version=str(row[1]),
            sequence_number=int(row[2]),
            tenant_id=str(row[3]),
            user_id=str(row[4]),
            event_type=str(row[5]),
            model_id=str(row[6]) if row[6] is not None else None,
            prompt_template_id=str(row[7]) if row[7] is not None else None,
            source_object_ids=[str(value) for value in row[8]],
            input_hash=str(row[9]) if row[9] is not None else None,
            output_hash=str(row[10]) if row[10] is not None else None,
            metadata=metadata,
            previous_event_hash=str(row[12]),
            event_hash=str(row[13]),
            recorded_at_utc=_timestamp_text(row[14]),
        )

    def _result_from_row(self, row: tuple[Any, ...], *, reused_existing: bool) -> AuditWormSnapshotResult:
        return AuditWormSnapshotResult(
            tenant_id=str(row[0]),
            checkpoint_id=str(row[1]),
            export_id=str(row[2]),
            through_sequence_number=int(row[3]),
            event_count=int(row[4]),
            manifest_hash=str(row[5]),
            bundle_hash=str(row[6]),
            signature_hash=str(row[7]),
            storage_uri=str(row[8]),
            object_version_id=str(row[9]),
            object_lock_retain_until_utc=_timestamp_text(row[10]),
            audit_chain_ref=str(row[11]),
            reused_existing=reused_existing,
        )

    def _set_tenant(self, connection: psycopg.Connection[Any], tenant_id: str) -> None:
        connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))

    def _lock_tenant_chain(self, connection: psycopg.Connection[Any], tenant_id: str) -> None:
        connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s::text, 0))", (tenant_id,))


class AuditWormSnapshotService:
    def __init__(
        self,
        *,
        repository: AuditWormSnapshotRepository,
        signer: AuditCheckpointSigner,
        object_store: AuditWormObjectStore,
        storage_kms_key_ref: str,
        retention_policy_id: str = "audit-security-10y-v1",
        retention_days: int = 3650,
        bucket_id: str = "evidence-records",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if retention_days < 1:
            raise ValueError("retention_days must be positive")
        if not storage_kms_key_ref.strip():
            raise ValueError("storage_kms_key_ref must not be empty")
        if not retention_policy_id.strip():
            raise ValueError("retention_policy_id must not be empty")
        if not bucket_id.strip():
            raise ValueError("bucket_id must not be empty")
        self.repository = repository
        self.signer = signer
        self.object_store = object_store
        self.storage_kms_key_ref = storage_kms_key_ref.strip()
        self.retention_policy_id = retention_policy_id.strip()
        self.retention_days = retention_days
        self.bucket_id = bucket_id.strip()
        self.clock = clock or (lambda: datetime.now(UTC))

    def create_for_tenant(
        self,
        *,
        tenant_id: str,
        created_by: str,
        legal_hold_enabled: bool = False,
    ) -> AuditWormSnapshotResult:
        if not tenant_id.strip() or not created_by.strip():
            raise ValueError("tenant_id and created_by must not be empty")
        events = self.repository.load_events(tenant_id=tenant_id)
        if not events:
            raise AuditWormSnapshotError("cannot create an audit snapshot for an empty chain")
        if any(event.tenant_id != tenant_id for event in events):
            raise AuditWormSnapshotError("audit snapshot source crossed tenant boundary")
        verification = verify_audit_chain(tuple(event.audit_event() for event in events))
        if not verification.ok:
            raise AuditWormSnapshotError(f"audit chain verification failed: {verification.failure}")

        events_payload = [event.model_dump(mode="json") for event in events]
        events_hash = _sha256_ref(_canonical_bytes(events_payload))
        checkpoint_id = _stable_id(
            "audit-checkpoint-v2",
            tenant_id,
            str(events[-1].sequence_number),
            events_hash,
        )
        existing = self.repository.find_completed(tenant_id=tenant_id, checkpoint_id=checkpoint_id)
        if existing is not None:
            return existing

        generated_at = self.clock().astimezone(UTC)
        retain_until = generated_at + timedelta(days=self.retention_days)
        manifest = AuditWormSnapshotManifest(
            tenant_id=tenant_id,
            checkpoint_id=checkpoint_id,
            through_sequence_number=events[-1].sequence_number,
            event_count=len(events),
            first_event_hash=events[0].event_hash,
            last_event_hash=events[-1].event_hash,
            events_hash=events_hash,
            generated_at_utc=_timestamp_text(generated_at),
            generated_by=created_by,
            retention_policy_id=self.retention_policy_id,
            retain_until_utc=_timestamp_text(retain_until),
            legal_hold_state="active" if legal_hold_enabled else "none",
        )
        manifest_hash = _sha256_ref(_canonical_bytes(manifest.model_dump(mode="json")))
        signature = self.signer.sign_digest(
            tenant_id=tenant_id,
            digest=bytes.fromhex(manifest_hash.removeprefix("sha256:")),
            signed_at_utc=manifest.generated_at_utc,
        )
        bundle = AuditWormSnapshotBundle(
            manifest=manifest,
            manifest_hash=manifest_hash,
            signature=signature,
            events=list(events),
        )
        bundle_body = _canonical_bytes(bundle.model_dump(mode="json"))
        bundle_hash = _sha256_ref(bundle_body)
        object_key = (
            "audit-snapshots/v2/"
            f"{sha256(tenant_id.encode('utf-8')).hexdigest()}/"
            f"{manifest.through_sequence_number:020d}/{checkpoint_id}.json"
        )
        receipt = self.object_store.put_verified(
            request=AuditWormObjectWriteRequest(
                tenant_id=tenant_id,
                checkpoint_id=checkpoint_id,
                bucket_id=self.bucket_id,
                object_key=object_key,
                bundle_hash=bundle_hash,
                manifest_hash=manifest_hash,
                signature_hash=signature.signature_sha256,
                retain_until_utc=manifest.retain_until_utc,
                legal_hold_enabled=legal_hold_enabled,
                storage_kms_key_ref=self.storage_kms_key_ref,
            ),
            body=bundle_body,
        )
        return self.repository.persist_completed(
            manifest=manifest,
            manifest_hash=manifest_hash,
            signature=signature,
            receipt=receipt,
            bundle_hash=bundle_hash,
            created_by=created_by,
        )


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _sha256_ref(value: bytes) -> str:
    return "sha256:" + sha256(value).hexdigest()


def _stable_id(prefix: str, *parts: str) -> str:
    return f"{prefix}-{sha256(chr(31).join(parts).encode('utf-8')).hexdigest()[:32]}"


def _evidence_ref(*parts: str) -> str:
    return "audit:" + sha256(chr(31).join(parts).encode("utf-8")).hexdigest()


def _parse_utc(value: str) -> datetime:
    normalized = value.strip()
    if not normalized:
        raise ValueError("timestamp must not be empty")
    parsed = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError("timestamp must be UTC")
    return parsed.astimezone(UTC)


def _timestamp_text(value: object) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    return _timestamp_text(_parse_utc(str(value)))
