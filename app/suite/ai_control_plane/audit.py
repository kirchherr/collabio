import hmac
import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from suite.ai_control_plane.models import AuditEvent, UserContext

GENESIS_HASH = "sha256:0000000000000000000000000000000000000000000000000000000000000000"


def stable_hash(value: str) -> str:
    return "sha256:" + sha256(value.encode("utf-8")).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def audit_event_hash(event: AuditEvent) -> str:
    payload = event.model_dump(mode="json", exclude={"event_hash"})
    return stable_hash(canonical_json(payload))


@dataclass(frozen=True)
class AuditChainVerificationResult:
    ok: bool
    verified_events: int
    failure: str | None = None


@dataclass(frozen=True)
class AuditCheckpoint:
    tenant_id: str
    checkpoint_id: str
    through_sequence_number: int
    event_count: int
    first_event_hash: str
    last_event_hash: str
    checkpoint_hash: str
    signature_algorithm: str
    signature_key_ref: str
    audit_chain_ref: str


@dataclass(frozen=True)
class AuditWormExport:
    tenant_id: str
    export_id: str
    checkpoint_id: str
    from_sequence_number: int
    through_sequence_number: int
    event_count: int
    first_event_hash: str
    last_event_hash: str
    checkpoint_hash: str
    export_manifest_hash: str
    storage_uri: str
    object_lock_mode: str
    audit_chain_ref: str


def verify_audit_chain(events: Sequence[AuditEvent]) -> AuditChainVerificationResult:
    previous_hash = GENESIS_HASH
    for expected_sequence, event in enumerate(events, start=1):
        if event.sequence_number != expected_sequence:
            return AuditChainVerificationResult(
                ok=False,
                verified_events=expected_sequence - 1,
                failure=f"Expected sequence {expected_sequence}, found {event.sequence_number}",
            )
        if event.previous_event_hash != previous_hash:
            return AuditChainVerificationResult(
                ok=False,
                verified_events=expected_sequence - 1,
                failure=f"Event {event.event_id} has invalid previous hash",
            )
        expected_hash = audit_event_hash(event)
        if event.event_hash != expected_hash:
            return AuditChainVerificationResult(
                ok=False,
                verified_events=expected_sequence - 1,
                failure=f"Event {event.event_id} has invalid event hash",
            )
        previous_hash = event.event_hash
    return AuditChainVerificationResult(ok=True, verified_events=len(events))


class InMemoryAuditLogger:
    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    @property
    def events(self) -> tuple[AuditEvent, ...]:
        return tuple(self._events)

    def record(
        self,
        *,
        user_context: UserContext,
        event_type: str,
        model_id: str | None = None,
        prompt_template_id: str | None = None,
        source_object_ids: list[str] | None = None,
        input_text: str | None = None,
        output_text: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEvent:
        previous_hash = self._events[-1].event_hash if self._events else GENESIS_HASH
        event = AuditEvent(
            sequence_number=len(self._events) + 1,
            tenant_id=user_context.tenant_id,
            user_id=user_context.user_id,
            event_type=event_type,
            model_id=model_id,
            prompt_template_id=prompt_template_id,
            source_object_ids=source_object_ids or [],
            input_hash=stable_hash(input_text) if input_text is not None else None,
            output_hash=stable_hash(output_text) if output_text is not None else None,
            metadata=metadata or {},
            previous_event_hash=previous_hash,
            event_hash="",
        )
        event.event_hash = audit_event_hash(event)
        self._append(event)
        return event

    def _append(self, event: AuditEvent) -> None:
        self._events.append(event)

    def verify(self) -> AuditChainVerificationResult:
        return verify_audit_chain(self.events)


class JsonlAuditLogger(InMemoryAuditLogger):
    def __init__(self, path: Path, events: Sequence[AuditEvent] = ()) -> None:
        super().__init__()
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._events = list(events)
        verification = self.verify()
        if not verification.ok:
            raise ValueError(f"Audit chain verification failed: {verification.failure}")

    @classmethod
    def load(cls, path: Path) -> "JsonlAuditLogger":
        if not path.exists():
            return cls(path=path)
        events = [
            AuditEvent.model_validate_json(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return cls(path=path, events=events)

    def _append(self, event: AuditEvent) -> None:
        with self.path.open("a", encoding="utf-8") as audit_file:
            audit_file.write(event.model_dump_json() + "\n")
            audit_file.flush()
        self._events.append(event)


class PgAuditLogger(InMemoryAuditLogger):
    def __init__(self, *, database_dsn: str) -> None:
        super().__init__()
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    def record(
        self,
        *,
        user_context: UserContext,
        event_type: str,
        model_id: str | None = None,
        prompt_template_id: str | None = None,
        source_object_ids: list[str] | None = None,
        input_text: str | None = None,
        output_text: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEvent:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, user_context.tenant_id)
            self._lock_tenant_chain(connection, user_context.tenant_id)
            previous_row = connection.execute(
                """
                SELECT sequence_number, event_hash
                FROM collabio.audit_events
                WHERE tenant_id = %s
                ORDER BY sequence_number DESC
                LIMIT 1
                """,
                (user_context.tenant_id,),
            ).fetchone()
            previous_sequence = int(previous_row[0]) if previous_row is not None else 0
            previous_hash = str(previous_row[1]) if previous_row is not None else GENESIS_HASH
            event = AuditEvent(
                sequence_number=previous_sequence + 1,
                tenant_id=user_context.tenant_id,
                user_id=user_context.user_id,
                event_type=event_type,
                model_id=model_id,
                prompt_template_id=prompt_template_id,
                source_object_ids=source_object_ids or [],
                input_hash=stable_hash(input_text) if input_text is not None else None,
                output_hash=stable_hash(output_text) if output_text is not None else None,
                metadata=metadata or {},
                previous_event_hash=previous_hash,
                event_hash="",
            )
            event.event_hash = audit_event_hash(event)
            self._insert_event(connection, event)
            connection.commit()

        self._events.append(event)
        return event

    def events_for_tenant(self, tenant_id: str) -> tuple[AuditEvent, ...]:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
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
                    event_hash
                FROM collabio.audit_events
                WHERE tenant_id = %s
                ORDER BY sequence_number
                """,
                (tenant_id,),
            ).fetchall()
        return tuple(self._event_from_row(row) for row in rows)

    def verify_tenant(self, tenant_id: str) -> AuditChainVerificationResult:
        return verify_audit_chain(self.events_for_tenant(tenant_id))

    def create_checkpoint(
        self,
        *,
        tenant_id: str,
        created_by: str,
        signature_key_ref: str,
        signing_secret: str,
    ) -> AuditCheckpoint:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            self._lock_tenant_chain(connection, tenant_id)
            rows = connection.execute(
                """
                SELECT sequence_number, event_hash
                FROM collabio.audit_events
                WHERE tenant_id = %s
                ORDER BY sequence_number
                """,
                (tenant_id,),
            ).fetchall()
            if not rows:
                raise ValueError("cannot checkpoint an empty audit chain")

            first_event_hash = str(rows[0][1])
            through_sequence_number = int(rows[-1][0])
            last_event_hash = str(rows[-1][1])
            event_count = len(rows)
            checkpoint_id = f"audit-checkpoint-{uuid4().hex}"
            checkpoint_hash = build_audit_checkpoint_hash(
                tenant_id=tenant_id,
                through_sequence_number=through_sequence_number,
                event_count=event_count,
                first_event_hash=first_event_hash,
                last_event_hash=last_event_hash,
                signature_key_ref=signature_key_ref,
                signing_secret=signing_secret,
            )
            audit_chain_ref = _audit_evidence_ref(
                "audit-checkpoint",
                tenant_id,
                checkpoint_id,
                str(through_sequence_number),
                checkpoint_hash,
            )
            connection.execute(
                """
                INSERT INTO collabio.audit_checkpoints (
                    tenant_id,
                    checkpoint_id,
                    through_sequence_number,
                    event_count,
                    first_event_hash,
                    last_event_hash,
                    checkpoint_hash,
                    signature_algorithm,
                    signature_key_ref,
                    created_by,
                    audit_chain_ref
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'hmac-sha256', %s, %s, %s)
                """,
                (
                    tenant_id,
                    checkpoint_id,
                    through_sequence_number,
                    event_count,
                    first_event_hash,
                    last_event_hash,
                    checkpoint_hash,
                    signature_key_ref,
                    created_by,
                    audit_chain_ref,
                ),
            )
            connection.commit()

        return AuditCheckpoint(
            tenant_id=tenant_id,
            checkpoint_id=checkpoint_id,
            through_sequence_number=through_sequence_number,
            event_count=event_count,
            first_event_hash=first_event_hash,
            last_event_hash=last_event_hash,
            checkpoint_hash=checkpoint_hash,
            signature_algorithm="hmac-sha256",
            signature_key_ref=signature_key_ref,
            audit_chain_ref=audit_chain_ref,
        )

    def record_worm_export(
        self,
        *,
        tenant_id: str,
        checkpoint_id: str,
        export_manifest_hash: str,
        storage_uri: str,
        created_by: str,
    ) -> AuditWormExport:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            checkpoint_row = connection.execute(
                """
                SELECT
                    through_sequence_number,
                    event_count,
                    first_event_hash,
                    last_event_hash,
                    checkpoint_hash
                FROM collabio.audit_checkpoints
                WHERE tenant_id = %s
                  AND checkpoint_id = %s
                """,
                (tenant_id, checkpoint_id),
            ).fetchone()
            if checkpoint_row is None:
                raise LookupError(f"Unknown audit checkpoint: {checkpoint_id}")

            through_sequence_number = int(checkpoint_row[0])
            event_count = int(checkpoint_row[1])
            first_event_hash = str(checkpoint_row[2])
            last_event_hash = str(checkpoint_row[3])
            checkpoint_hash = str(checkpoint_row[4])
            export_id = f"audit-worm-export-{uuid4().hex}"
            audit_chain_ref = _audit_evidence_ref(
                "audit-worm-export",
                tenant_id,
                export_id,
                checkpoint_id,
                export_manifest_hash,
                storage_uri,
            )
            connection.execute(
                """
                INSERT INTO collabio.audit_worm_exports (
                    tenant_id,
                    export_id,
                    checkpoint_id,
                    through_sequence_number,
                    event_count,
                    first_event_hash,
                    last_event_hash,
                    checkpoint_hash,
                    export_manifest_hash,
                    storage_uri,
                    created_by,
                    audit_chain_ref
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    tenant_id,
                    export_id,
                    checkpoint_id,
                    through_sequence_number,
                    event_count,
                    first_event_hash,
                    last_event_hash,
                    checkpoint_hash,
                    export_manifest_hash,
                    storage_uri,
                    created_by,
                    audit_chain_ref,
                ),
            )
            connection.commit()

        return AuditWormExport(
            tenant_id=tenant_id,
            export_id=export_id,
            checkpoint_id=checkpoint_id,
            from_sequence_number=1,
            through_sequence_number=through_sequence_number,
            event_count=event_count,
            first_event_hash=first_event_hash,
            last_event_hash=last_event_hash,
            checkpoint_hash=checkpoint_hash,
            export_manifest_hash=export_manifest_hash,
            storage_uri=storage_uri,
            object_lock_mode="compliance",
            audit_chain_ref=audit_chain_ref,
        )

    def _insert_event(self, connection: psycopg.Connection[Any], event: AuditEvent) -> None:
        connection.execute(
            """
            INSERT INTO collabio.audit_events (
                tenant_id,
                sequence_number,
                event_id,
                schema_version,
                user_id,
                event_type,
                model_id,
                prompt_template_id,
                source_object_ids,
                input_hash,
                output_hash,
                metadata,
                previous_event_hash,
                event_hash
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                event.tenant_id,
                event.sequence_number,
                event.event_id,
                event.schema_version,
                event.user_id,
                event.event_type,
                event.model_id,
                event.prompt_template_id,
                event.source_object_ids,
                event.input_hash,
                event.output_hash,
                Jsonb(event.metadata),
                event.previous_event_hash,
                event.event_hash,
            ),
        )

    def _event_from_row(self, row: tuple[Any, ...]) -> AuditEvent:
        metadata = row[11]
        if not isinstance(metadata, dict):
            metadata = dict(metadata)
        return AuditEvent(
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
        )

    def _set_tenant(self, connection: psycopg.Connection[Any], tenant_id: str) -> None:
        connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))

    def _lock_tenant_chain(self, connection: psycopg.Connection[Any], tenant_id: str) -> None:
        connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s::text, 0))", (tenant_id,))


def build_audit_checkpoint_hash(
    *,
    tenant_id: str,
    through_sequence_number: int,
    event_count: int,
    first_event_hash: str,
    last_event_hash: str,
    signature_key_ref: str,
    signing_secret: str,
) -> str:
    if not signing_secret:
        raise ValueError("signing_secret must not be empty")
    payload = canonical_json(
        {
            "event_count": event_count,
            "first_event_hash": first_event_hash,
            "last_event_hash": last_event_hash,
            "signature_key_ref": signature_key_ref,
            "tenant_id": tenant_id,
            "through_sequence_number": through_sequence_number,
        }
    )
    digest = hmac.new(signing_secret.encode("utf-8"), payload.encode("utf-8"), sha256).hexdigest()
    return f"hmac-sha256:{digest}"


def build_default_audit_logger(data_dir: Path) -> InMemoryAuditLogger:
    backend = os.getenv("SUITE_AUDIT_LOGGER_BACKEND", "jsonl").strip().lower()
    if backend in {"jsonl", "json", "file"}:
        return JsonlAuditLogger.load(data_dir / "audit" / "events.jsonl")
    if backend in {"postgres", "postgresql", "pg"}:
        database_dsn = os.getenv("SUITE_AUDIT_DATABASE_DSN") or os.getenv("SUITE_DATABASE_DSN")
        if not database_dsn:
            raise ValueError("PostgreSQL audit logger requires SUITE_AUDIT_DATABASE_DSN or SUITE_DATABASE_DSN")
        return PgAuditLogger(database_dsn=database_dsn)
    raise ValueError(f"Unsupported SUITE_AUDIT_LOGGER_BACKEND: {backend}")


def _audit_evidence_ref(*parts: str) -> str:
    return "audit:" + sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
