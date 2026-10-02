"""Review events share the native document lock and exact source/receipt transaction."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.ai_control_plane.models import DataClass, UserContext
from suite.platform.office_document_repository import (
    InMemoryOfficeDocumentRepository,
    PgOfficeDocumentRepository,
    _model_values,
)
from suite.platform.office_documents import (
    OfficeDocumentConflictError,
    OfficeDocumentInvalidContentError,
    OfficeDocumentNotFoundError,
    OfficeDocumentPermissionError,
    OfficeDocumentRecord,
    OfficeDocumentService,
)
from suite.platform.office_reviews import (
    MAX_REVIEW_BYTES,
    REVIEW_MIME,
    REVIEW_SCHEMA,
    REVIEW_SOURCE_SYSTEM,
    ReviewCommit,
    ReviewCreateCommand,
    ReviewDetailSnapshot,
    ReviewEventCommand,
    ReviewEventRecord,
    ReviewListSnapshot,
    ReviewOperation,
    ReviewThreadRecord,
    derive_review_quote,
    read_review_payload,
    review_command_hash,
)
from suite.storage.source_objects import (
    LegalHoldState,
    SourceLifecycleState,
    SourceObjectMetadata,
    SourceObjectRecord,
    SourceObjectType,
    SourceObjectWriteReceipt,
    build_source_object_manifest_hash,
    build_source_object_write_receipt,
    sha256_bytes,
)

_THREAD_COLUMNS = ", ".join(ReviewThreadRecord.model_fields)
_EVENT_COLUMNS = ", ".join(ReviewEventRecord.model_fields)


def _prepare(
    user: UserContext,
    document: OfficeDocumentRecord,
    thread: ReviewThreadRecord | None,
    command: ReviewCreateCommand | ReviewEventCommand,
    command_hash: str,
    quote: str | None,
    anchor_content_hash: str,
    acl_rows: list[tuple[Any, ...]],
) -> tuple[ReviewCommit, SourceObjectRecord, SourceObjectWriteReceipt]:
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    event_id = f"office-review-event-{uuid4().hex}"
    audit_ref = f"audit:office-review-{uuid4().hex}"
    previous_event_id = thread.current_event_id if thread else None
    operation: ReviewOperation
    if isinstance(command, ReviewCreateCommand):
        thread = ReviewThreadRecord(
            tenant_id=user.tenant_id,
            object_id=document.object_id,
            thread_id=f"office-review-{uuid4().hex}",
            anchor_version_id=command.anchor_version_id,
            anchor_content_hash=anchor_content_hash,
            anchor_from=command.anchor.from_ if command.anchor else None,
            anchor_to=command.anchor.to if command.anchor else None,
            revision=1,
            current_event_id=event_id,
            status="open",
            created_by=user.user_id,
            created_at_utc=now,
            updated_at_utc=now,
            audit_chain_ref=audit_ref,
        )
        operation = "create"
    else:
        if thread is None:
            raise OfficeDocumentNotFoundError("Document not found")
        operation = command.operation
        thread = thread.model_copy(
            update={
                "revision": thread.revision + 1,
                "current_event_id": event_id,
                "status": "resolved" if operation == "resolve" else "open",
                "updated_at_utc": now,
            }
        )
    anchor = thread.anchor()
    payload = {
        "schema_version": REVIEW_SCHEMA,
        "thread_id": thread.thread_id,
        "document_id": document.object_id,
        "anchor_version_id": thread.anchor_version_id,
        "anchor_content_hash": thread.anchor_content_hash,
        "anchor": anchor.model_dump(by_alias=True) if anchor else None,
        "quote": quote,
        "operation": operation,
        "body": command.body,
    }
    content = canonical_json(payload).encode("utf-8")
    if len(content) > MAX_REVIEW_BYTES or not acl_rows:
        raise OfficeDocumentInvalidContentError("Review source is invalid")
    metadata = SourceObjectMetadata(
        tenant_id=user.tenant_id,
        object_id=thread.thread_id,
        object_type=SourceObjectType.COMMENT,
        version_id=event_id,
        title="Office review event",
        owner_principal_id=document.owner_principal_id,
        created_by=user.user_id,
        created_at_utc=now,
        updated_at_utc=now,
        classification=DataClass.INTERNAL,
        retention_policy_id="rp-standard",
        legal_hold_state=LegalHoldState.NONE,
        kms_key_ref=f"kms://{user.tenant_id}/internal/v1",
        manifest_hash="sha256:" + "0" * 64,
        audit_chain_ref=audit_ref,
        source_system=REVIEW_SOURCE_SYSTEM,
        schema_version=REVIEW_SCHEMA,
        mime_type=REVIEW_MIME,
        acl_hash=stable_hash(canonical_json(acl_rows)),
        acl_version=max(int(row[3]) for row in acl_rows),
        content_hash=sha256_bytes(content),
        content_byte_length=len(content),
        lifecycle_state=SourceLifecycleState.SAVED_VERSION,
        parent_object_id=document.object_id,
        thread_id=thread.thread_id,
    )
    metadata = metadata.model_copy(update={"manifest_hash": build_source_object_manifest_hash(metadata)})
    source = SourceObjectRecord(metadata=metadata, content_bytes=content)
    receipt = build_source_object_write_receipt(
        record=source,
        receipt_reference=f"office-review-write:{uuid4().hex}",
        audit_chain_ref=audit_ref,
        captured_at_utc=now,
    )
    event = ReviewEventRecord(
        tenant_id=user.tenant_id,
        object_id=document.object_id,
        thread_id=thread.thread_id,
        event_id=event_id,
        revision=thread.revision,
        previous_event_id=previous_event_id,
        operation=operation,
        status_after=thread.status,
        created_by=user.user_id,
        created_at_utc=now,
        content_hash=metadata.content_hash,
        source_manifest_hash=metadata.manifest_hash,
        source_write_receipt_hash=receipt.receipt_hash,
        content_byte_length=len(content),
        acl_hash=metadata.acl_hash,
        acl_version=metadata.acl_version,
        mutation_reference=command.mutation_reference,
        command_hash=command_hash,
        audit_chain_ref=audit_ref,
    )
    return ReviewCommit(document=document, thread=thread, event=event, payload=payload), source, receipt


def _check_command(thread: ReviewThreadRecord, command: ReviewEventCommand) -> None:
    if command.expected_revision != thread.revision:
        raise OfficeDocumentConflictError("Review has a newer revision")
    if (command.operation in {"reply", "resolve"} and thread.status != "open") or (
        command.operation == "reopen" and thread.status != "resolved"
    ):
        raise OfficeDocumentConflictError("Review state conflicts with this operation")


def _replay(
    document: OfficeDocumentRecord,
    thread: ReviewThreadRecord,
    event: ReviewEventRecord,
    document_service: OfficeDocumentService,
) -> ReviewCommit:
    payload = read_review_payload(document_service.source_repository, document, thread, event)
    snapshot = thread.model_copy(
        update={
            "revision": event.revision,
            "current_event_id": event.event_id,
            "status": event.status_after,
            "updated_at_utc": event.created_at_utc,
        }
    )
    return ReviewCommit(document=document, thread=snapshot, event=event, payload=payload, replayed=True)


class PgOfficeReviewRepository:
    def __init__(self, *, document_service: OfficeDocumentService) -> None:
        if not isinstance(document_service.repository, PgOfficeDocumentRepository):
            raise ValueError("Review PostgreSQL repository requires the durable document repository")
        self.document_service = document_service
        self.documents = document_service.repository
        self.database_dsn = self.documents.database_dsn

    @staticmethod
    def _thread(
        connection: psycopg.Connection[Any], user: UserContext, object_id: str, thread_id: str
    ) -> ReviewThreadRecord:
        with connection.cursor(row_factory=dict_row) as cursor:
            row = cursor.execute(
                f"SELECT {_THREAD_COLUMNS} FROM office.review_threads "
                "WHERE tenant_id=%s AND object_id=%s AND thread_id=%s",
                (user.tenant_id, object_id, thread_id),
            ).fetchone()
        if row is None:
            raise OfficeDocumentNotFoundError("Document not found")
        return ReviewThreadRecord.model_validate(_model_values(row))

    @staticmethod
    def _event(connection: psycopg.Connection[Any], user: UserContext, thread: ReviewThreadRecord) -> ReviewEventRecord:
        with connection.cursor(row_factory=dict_row) as cursor:
            row = cursor.execute(
                f"SELECT {_EVENT_COLUMNS} FROM office.review_events "
                "WHERE tenant_id=%s AND thread_id=%s AND event_id=%s",
                (user.tenant_id, thread.thread_id, thread.current_event_id),
            ).fetchone()
        if row is None:
            raise OfficeDocumentNotFoundError("Document not found")
        return ReviewEventRecord.model_validate(_model_values(row))

    def list_threads(
        self, *, user: UserContext, object_id: str, after: str | None, limit: int, anchor_version_id: str | None
    ) -> ReviewListSnapshot:
        with psycopg.connect(self.database_dsn) as connection:
            self.documents._set_tenant(connection, user.tenant_id)
            document = self.documents._authorized_document(connection, user, object_id)
            if anchor_version_id is not None:
                self.documents._version(
                    connection, tenant_id=user.tenant_id, object_id=object_id, version_id=anchor_version_id
                )
            writable = bool(self.documents._permissions(connection, user, object_id) & {"write", "admin"})
            with connection.cursor(row_factory=dict_row) as cursor:
                rows = cursor.execute(
                    f"SELECT {_THREAD_COLUMNS} FROM office.review_threads WHERE tenant_id=%s AND object_id=%s "
                    "AND (%s::text IS NULL OR thread_id>%s) AND (%s::text IS NULL OR anchor_version_id=%s) "
                    "ORDER BY thread_id LIMIT %s",
                    (user.tenant_id, object_id, after, after, anchor_version_id, anchor_version_id, limit + 1),
                ).fetchall()
            return ReviewListSnapshot(
                document=document,
                threads=tuple(ReviewThreadRecord.model_validate(_model_values(row)) for row in rows[:limit]),
                can_write=writable,
                has_more=len(rows) > limit,
            )

    def detail(
        self, *, user: UserContext, object_id: str, thread_id: str, after_revision: int, limit: int
    ) -> ReviewDetailSnapshot:
        with psycopg.connect(self.database_dsn) as connection:
            self.documents._set_tenant(connection, user.tenant_id)
            document = self.documents._authorized_document(connection, user, object_id)
            writable = bool(self.documents._permissions(connection, user, object_id) & {"write", "admin"})
            thread = self._thread(connection, user, object_id, thread_id)
            latest = self._event(connection, user, thread)
            with connection.cursor(row_factory=dict_row) as cursor:
                rows = cursor.execute(
                    f"SELECT {_EVENT_COLUMNS} FROM office.review_events WHERE tenant_id=%s AND thread_id=%s "
                    "AND revision>%s AND revision<=%s ORDER BY revision LIMIT %s",
                    (user.tenant_id, thread_id, after_revision, thread.revision, limit + 1),
                ).fetchall()
            return ReviewDetailSnapshot(
                document=document,
                thread=thread,
                latest=latest,
                events=tuple(ReviewEventRecord.model_validate(_model_values(row)) for row in rows[:limit]),
                can_write=writable,
                has_more=len(rows) > limit,
            )

    def commit(
        self,
        *,
        user: UserContext,
        object_id: str,
        thread_id: str | None,
        command: ReviewCreateCommand | ReviewEventCommand,
    ) -> ReviewCommit:
        command = type(command).model_validate(command.model_dump(mode="python", by_alias=True))
        if (thread_id is None) != isinstance(command, ReviewCreateCommand):
            raise OfficeDocumentConflictError("Review operation is invalid")
        command_hash = review_command_hash(user, object_id, thread_id, command)
        thread: ReviewThreadRecord | None
        try:
            with psycopg.connect(self.database_dsn) as connection, connection.transaction():
                self.documents._set_tenant(connection, user.tenant_id)
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (f"office-document-write:{user.tenant_id}",)
                )
                document = self.documents._authorized_document(connection, user, object_id, write=True)
                with connection.cursor(row_factory=dict_row) as cursor:
                    replay = cursor.execute(
                        f"SELECT {_EVENT_COLUMNS} FROM office.review_events "
                        "WHERE tenant_id=%s AND created_by=%s AND mutation_reference=%s",
                        (user.tenant_id, user.user_id, command.mutation_reference),
                    ).fetchone()
                if replay is not None:
                    event = ReviewEventRecord.model_validate(_model_values(replay))
                    if event.command_hash != command_hash:
                        raise OfficeDocumentConflictError("Mutation reference was already used")
                    thread = self._thread(connection, user, object_id, event.thread_id)
                    return _replay(document, thread, event, self.document_service)
                if isinstance(command, ReviewCreateCommand):
                    if (
                        document.current_version_id != command.expected_current_version_id
                        or command.anchor_version_id != document.current_version_id
                    ):
                        raise OfficeDocumentConflictError("Document has a newer saved version")
                    version = self.documents._version(
                        connection, tenant_id=user.tenant_id, object_id=object_id, version_id=command.anchor_version_id
                    )
                    content = self.document_service._read_content(document, version)
                    quote = derive_review_quote(content, command.anchor)
                    anchor_hash = version.content_hash
                    thread = None
                else:
                    thread = self._thread(connection, user, object_id, str(thread_id))
                    _check_command(thread, command)
                    previous = self._event(connection, user, thread)
                    quote = read_review_payload(self.documents.source_repository, document, thread, previous)["quote"]
                    anchor_hash = thread.anchor_content_hash
                result, source, receipt = _prepare(
                    user,
                    document,
                    thread,
                    command,
                    command_hash,
                    quote,
                    anchor_hash,
                    self.documents._acl_rows(connection, user.tenant_id, object_id),
                )
                if thread is None:
                    values = result.thread.model_dump()
                    connection.execute(
                        f"INSERT INTO office.review_threads ({_THREAD_COLUMNS}) "
                        f"VALUES ({','.join(['%s'] * len(values))})",
                        tuple(values.values()),
                    )
                self.documents.receipt_store.append_in_transaction(connection, receipt)
                self.documents.source_repository.add_with_receipt_in_transaction(
                    connection, record=source, source_object_write_receipt_hash=receipt.receipt_hash
                )
                values = result.event.model_dump()
                connection.execute(
                    f"INSERT INTO office.review_events ({_EVENT_COLUMNS}) VALUES ({','.join(['%s'] * len(values))})",
                    tuple(values.values()),
                )
                if thread is not None:
                    connection.execute(
                        "UPDATE office.review_threads SET revision=%s,current_event_id=%s,status=%s,updated_at_utc=%s "
                        "WHERE tenant_id=%s AND object_id=%s AND thread_id=%s",
                        (
                            result.thread.revision,
                            result.thread.current_event_id,
                            result.thread.status,
                            result.thread.updated_at_utc,
                            user.tenant_id,
                            object_id,
                            thread.thread_id,
                        ),
                    )
                return result
        except psycopg.errors.UniqueViolation as exc:
            raise OfficeDocumentConflictError("Review mutation conflicts with existing metadata") from exc


class InMemoryOfficeReviewRepository:
    """Explicit test adapter, sharing the document repository's lock and permissions."""

    def __init__(self, *, document_service: OfficeDocumentService) -> None:
        if not isinstance(document_service.repository, InMemoryOfficeDocumentRepository):
            raise ValueError("Review memory repository requires the explicit document test adapter")
        self.document_service = document_service
        self.documents = document_service.repository
        self.threads: dict[tuple[str, str], ReviewThreadRecord] = {}
        self.events: dict[tuple[str, str], ReviewEventRecord] = {}

    def _thread(self, user: UserContext, object_id: str, thread_id: str) -> ReviewThreadRecord:
        thread = self.threads.get((user.tenant_id, thread_id))
        if thread is None or thread.object_id != object_id:
            raise OfficeDocumentNotFoundError("Document not found")
        return thread

    def list_threads(
        self, *, user: UserContext, object_id: str, after: str | None, limit: int, anchor_version_id: str | None
    ) -> ReviewListSnapshot:
        with self.documents._lock:
            document = self.documents.get_document(user_context=user, object_id=object_id)
            if anchor_version_id is not None:
                self.documents.get_version(user_context=user, object_id=object_id, version_id=anchor_version_id)
            threads = sorted(
                (
                    thread
                    for (tenant, _), thread in self.threads.items()
                    if tenant == user.tenant_id
                    and thread.object_id == object_id
                    and (after is None or thread.thread_id > after)
                    and (anchor_version_id is None or thread.anchor_version_id == anchor_version_id)
                ),
                key=lambda thread: thread.thread_id,
            )
            return ReviewListSnapshot(
                document=document,
                threads=tuple(threads[:limit]),
                has_more=len(threads) > limit,
                can_write=self.documents.can_write(user_context=user, object_id=object_id),
            )

    def detail(
        self, *, user: UserContext, object_id: str, thread_id: str, after_revision: int, limit: int
    ) -> ReviewDetailSnapshot:
        with self.documents._lock:
            document = self.documents.get_document(user_context=user, object_id=object_id)
            thread = self._thread(user, object_id, thread_id)
            events = sorted(
                (
                    event
                    for (tenant, _), event in self.events.items()
                    if tenant == user.tenant_id and event.thread_id == thread_id and event.revision > after_revision
                ),
                key=lambda event: event.revision,
            )
            return ReviewDetailSnapshot(
                document=document,
                thread=thread,
                events=tuple(events[:limit]),
                latest=self.events[(user.tenant_id, thread.current_event_id)],
                has_more=len(events) > limit,
                can_write=self.documents.can_write(user_context=user, object_id=object_id),
            )

    def commit(
        self,
        *,
        user: UserContext,
        object_id: str,
        thread_id: str | None,
        command: ReviewCreateCommand | ReviewEventCommand,
    ) -> ReviewCommit:
        command = type(command).model_validate(command.model_dump(mode="python", by_alias=True))
        if (thread_id is None) != isinstance(command, ReviewCreateCommand):
            raise OfficeDocumentConflictError("Review operation is invalid")
        with self.documents._lock:
            document = self.documents.get_document(user_context=user, object_id=object_id)
            if not self.documents.can_write(user_context=user, object_id=object_id):
                raise OfficeDocumentPermissionError("Review writing is not permitted")
            command_hash = review_command_hash(user, object_id, thread_id, command)
            for event in self.events.values():
                if (event.tenant_id, event.created_by, event.mutation_reference) == (
                    user.tenant_id,
                    user.user_id,
                    command.mutation_reference,
                ):
                    if event.command_hash != command_hash:
                        raise OfficeDocumentConflictError("Mutation reference was already used")
                    return _replay(
                        document, self._thread(user, object_id, event.thread_id), event, self.document_service
                    )
            if isinstance(command, ReviewCreateCommand):
                if (
                    document.current_version_id != command.expected_current_version_id
                    or command.anchor_version_id != document.current_version_id
                ):
                    raise OfficeDocumentConflictError("Document has a newer saved version")
                version = self.documents.get_version(
                    user_context=user, object_id=object_id, version_id=command.anchor_version_id
                )
                quote = derive_review_quote(self.document_service._read_content(document, version), command.anchor)
                anchor_hash = version.content_hash
                thread = None
            else:
                thread = self._thread(user, object_id, str(thread_id))
                _check_command(thread, command)
                quote = read_review_payload(
                    self.documents.source_repository,
                    document,
                    thread,
                    self.events[(user.tenant_id, thread.current_event_id)],
                )["quote"]
                anchor_hash = thread.anchor_content_hash
            acl_rows = sorted(
                ("user", principal, permission, 1)
                for (tenant, doc, principal), permission in self.documents.grants.items()
                if tenant == user.tenant_id and doc == object_id
            )
            result, source, receipt = _prepare(
                user, document, thread, command, command_hash, quote, anchor_hash, acl_rows
            )
            self.documents.source_repository.add(source)
            self.documents.receipt_store.append(receipt)
            self.events[(user.tenant_id, result.event.event_id)] = result.event
            self.threads[(user.tenant_id, result.thread.thread_id)] = result.thread
            return result
