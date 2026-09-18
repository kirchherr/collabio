from __future__ import annotations

from datetime import UTC, datetime
from threading import RLock
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.ai_control_plane.models import DataClass, UserContext
from suite.platform.office_document_schema import OFFICE_DOCUMENT_MIME_TYPE, OFFICE_DOCUMENT_SCHEMA_VERSION
from suite.platform.office_documents import (
    OFFICE_DOCUMENT_OBJECT_TYPE,
    OFFICE_DOCUMENT_SOURCE_SYSTEM,
    OfficeDocumentCommit,
    OfficeDocumentConflictError,
    OfficeDocumentCreateCommand,
    OfficeDocumentNotFoundError,
    OfficeDocumentPermissionError,
    OfficeDocumentRecord,
    OfficeDocumentSaveCommand,
    OfficeDocumentService,
    OfficeDocumentVersion,
    can_create_office_document,
    office_document_command_hash,
)
from suite.storage.source_object_storage import PgSourceObjectRepository
from suite.storage.source_objects import (
    InMemorySourceObjectRepository,
    InMemorySourceObjectWriteReceiptStore,
    LegalHoldState,
    PgSourceObjectWriteReceiptStore,
    SourceLifecycleState,
    SourceObjectMetadata,
    SourceObjectRecord,
    SourceObjectType,
    SourceObjectWriteReceipt,
    build_source_object_manifest_hash,
    build_source_object_write_receipt,
    sha256_bytes,
)

_DOCUMENT_COLUMNS = ", ".join(OfficeDocumentRecord.model_fields)
_VERSION_COLUMNS = ", ".join(OfficeDocumentVersion.model_fields)


def _model_values(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value.astimezone(UTC).isoformat().replace("+00:00", "Z") if isinstance(value, datetime) else value
            for key, value in values.items()}


def _new_document(user: UserContext, title: str) -> OfficeDocumentRecord:
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return OfficeDocumentRecord(
        tenant_id=user.tenant_id, object_id=f"office-doc-{uuid4().hex}", title=title,
        current_version_id=f"office-version-{uuid4().hex}", owner_principal_id=user.user_id,
        created_by=user.user_id, created_at_utc=now, updated_at_utc=now,
        audit_chain_ref=f"audit:office-document-{uuid4().hex}",
    )


def _prepare_version(
    *, user: UserContext, document: OfficeDocumentRecord, previous_version_id: str | None,
    command: OfficeDocumentCreateCommand, command_hash: str, acl_rows: list[tuple[Any, ...]],
) -> tuple[OfficeDocumentRecord, OfficeDocumentVersion, SourceObjectRecord, SourceObjectWriteReceipt]:
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    version_id = document.current_version_id if previous_version_id is None else f"office-version-{uuid4().hex}"
    audit_ref = f"audit:office-document-version-{uuid4().hex}"
    document = document.model_copy(update={
        "title": command.title, "current_version_id": version_id, "updated_at_utc": now,
    })
    content = canonical_json(command.document).encode("utf-8")
    metadata = SourceObjectMetadata(
        tenant_id=user.tenant_id, object_id=document.object_id, object_type=SourceObjectType.DOCUMENT,
        version_id=version_id, title=command.title, owner_principal_id=document.owner_principal_id,
        created_by=user.user_id, created_at_utc=now, updated_at_utc=now,
        classification=DataClass.INTERNAL, retention_policy_id="rp-standard", legal_hold_state=LegalHoldState.NONE,
        kms_key_ref=f"kms://{user.tenant_id}/internal/v1", manifest_hash="sha256:" + "0" * 64,
        audit_chain_ref=audit_ref, source_system=OFFICE_DOCUMENT_SOURCE_SYSTEM,
        schema_version=OFFICE_DOCUMENT_SCHEMA_VERSION, mime_type=OFFICE_DOCUMENT_MIME_TYPE,
        acl_hash=stable_hash(canonical_json(acl_rows)), acl_version=max(int(row[3]) for row in acl_rows),
        content_hash=sha256_bytes(content), content_byte_length=len(content),
        lifecycle_state=SourceLifecycleState.SAVED_VERSION,
    )
    metadata = metadata.model_copy(update={"manifest_hash": build_source_object_manifest_hash(metadata)})
    source = SourceObjectRecord(metadata=metadata, content_bytes=content)
    receipt = build_source_object_write_receipt(
        record=source, receipt_reference=f"office-write:{uuid4().hex}", audit_chain_ref=audit_ref, captured_at_utc=now,
    )
    version = OfficeDocumentVersion(
        tenant_id=user.tenant_id, object_id=document.object_id, version_id=version_id,
        previous_version_id=previous_version_id, title=command.title, created_at_utc=now, created_by=user.user_id,
        content_hash=metadata.content_hash, source_manifest_hash=metadata.manifest_hash,
        source_write_receipt_hash=receipt.receipt_hash, content_byte_length=len(content),
        acl_hash=metadata.acl_hash, acl_version=metadata.acl_version,
        mutation_reference=command.mutation_reference, command_hash=command_hash, audit_chain_ref=audit_ref,
    )
    return document, version, source, receipt


class PgOfficeDocumentRepository:
    """Native document writes share the source/receipt transaction and serialize before PUT.

    S3 is not a PostgreSQL participant. An unexpected database failure after PUT
    may leave an orphan, which the source content recovery reconciler detects.
    """

    def __init__(
        self, *, database_dsn: str, source_repository: PgSourceObjectRepository,
        receipt_store: PgSourceObjectWriteReceiptStore,
    ) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        if source_repository.database_dsn != database_dsn or receipt_store.database_dsn != database_dsn:
            raise ValueError("Office metadata, source and receipt stores require the same database")
        self.database_dsn = database_dsn
        self.source_repository = source_repository
        self.receipt_store = receipt_store

    @staticmethod
    def _set_tenant(connection: psycopg.Connection[Any], tenant_id: str) -> None:
        connection.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))

    @staticmethod
    def _permissions(connection: psycopg.Connection[Any], user: UserContext, object_id: str) -> set[str]:
        # The request's readable IDs include ABAC decisions. The second query is
        # authoritative and typed; an arbitrary readable ID never grants write.
        if object_id not in user.readable_object_ids:
            return set()
        rows = connection.execute(
            """
            SELECT DISTINCT acl.permission
            FROM collabio.object_acl_entries AS acl
            WHERE acl.tenant_id = %s AND acl.object_id = %s AND acl.object_type = %s
              AND acl.status = 'active'
              AND (
                (acl.acl_subject_type = 'user' AND acl.acl_subject_id = %s)
                OR (acl.acl_subject_type = 'role' AND acl.acl_subject_id = ANY(%s::text[]))
                OR (acl.acl_subject_type = 'group' AND acl.acl_subject_id IN (
                    SELECT membership.group_id
                    FROM collabio.tenant_principal_group_memberships AS membership
                    JOIN collabio.tenant_principals AS principal
                      ON principal.tenant_id = membership.tenant_id
                     AND principal.issuer = membership.issuer AND principal.subject = membership.subject
                    JOIN collabio.tenant_groups AS tenant_group
                      ON tenant_group.tenant_id = membership.tenant_id
                     AND tenant_group.group_id = membership.group_id
                    WHERE principal.tenant_id = acl.tenant_id AND principal.user_id = %s
                      AND principal.status = 'active' AND membership.status = 'active'
                      AND tenant_group.status = 'active'
                ))
              )
            """,
            (user.tenant_id, object_id, OFFICE_DOCUMENT_OBJECT_TYPE, user.user_id,
             sorted(user.role_ids), user.user_id),
        ).fetchall()
        return {str(row[0]) for row in rows}

    @staticmethod
    def _document(connection: psycopg.Connection[Any], tenant_id: str, object_id: str) -> OfficeDocumentRecord:
        with connection.cursor(row_factory=dict_row) as cursor:
            row = cursor.execute(
                f"SELECT {_DOCUMENT_COLUMNS} FROM office.documents WHERE tenant_id = %s AND object_id = %s",
                (tenant_id, object_id),
            ).fetchone()
        if row is None:
            raise OfficeDocumentNotFoundError("Document not found")
        return OfficeDocumentRecord.model_validate(_model_values(row))

    def _authorized_document(
        self, connection: psycopg.Connection[Any], user: UserContext, object_id: str, *, write: bool = False,
    ) -> OfficeDocumentRecord:
        permissions = self._permissions(connection, user, object_id)
        if not permissions:
            raise OfficeDocumentNotFoundError("Document not found")
        if write and not permissions & {"write", "admin"}:
            raise OfficeDocumentPermissionError("Document saving is not permitted")
        return self._document(connection, user.tenant_id, object_id)

    def list_documents(self, *, user_context: UserContext) -> tuple[OfficeDocumentRecord, ...]:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, user_context.tenant_id)
            with connection.cursor(row_factory=dict_row) as cursor:
                rows = cursor.execute(
                    f"SELECT {_DOCUMENT_COLUMNS} FROM office.documents "
                    "WHERE tenant_id = %s AND object_id = ANY(%s::text[]) "
                    "ORDER BY updated_at_utc DESC, object_id LIMIT 200",
                    (user_context.tenant_id, sorted(user_context.readable_object_ids)),
                ).fetchall()
            return tuple(OfficeDocumentRecord.model_validate(_model_values(row)) for row in rows
                         if self._permissions(connection, user_context, str(row["object_id"])))

    def get_document(self, *, user_context: UserContext, object_id: str) -> OfficeDocumentRecord:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, user_context.tenant_id)
            return self._authorized_document(connection, user_context, object_id)

    def can_write(self, *, user_context: UserContext, object_id: str) -> bool:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, user_context.tenant_id)
            return bool(self._permissions(connection, user_context, object_id) & {"write", "admin"})

    def versions(self, *, user_context: UserContext, object_id: str) -> tuple[OfficeDocumentVersion, ...]:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, user_context.tenant_id)
            self._authorized_document(connection, user_context, object_id)
            with connection.cursor(row_factory=dict_row) as cursor:
                rows = cursor.execute(
                    f"SELECT {_VERSION_COLUMNS} FROM office.document_versions "
                    "WHERE tenant_id = %s AND object_id = %s ORDER BY created_at_utc DESC, version_id LIMIT 200",
                    (user_context.tenant_id, object_id),
                ).fetchall()
        return tuple(OfficeDocumentVersion.model_validate(_model_values(row)) for row in rows)

    @staticmethod
    def _version(
        connection: psycopg.Connection[Any], *, tenant_id: str, object_id: str, version_id: str,
    ) -> OfficeDocumentVersion:
        with connection.cursor(row_factory=dict_row) as cursor:
            row = cursor.execute(
                f"SELECT {_VERSION_COLUMNS} FROM office.document_versions "
                "WHERE tenant_id = %s AND object_id = %s AND version_id = %s",
                (tenant_id, object_id, version_id),
            ).fetchone()
        if row is None:
            raise OfficeDocumentNotFoundError("Document not found")
        return OfficeDocumentVersion.model_validate(_model_values(row))

    def get_version(self, *, user_context: UserContext, object_id: str, version_id: str) -> OfficeDocumentVersion:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, user_context.tenant_id)
            self._authorized_document(connection, user_context, object_id)
            return self._version(connection, tenant_id=user_context.tenant_id, object_id=object_id, version_id=version_id)

    @staticmethod
    def _acl_rows(connection: psycopg.Connection[Any], tenant_id: str, object_id: str) -> list[tuple[Any, ...]]:
        return connection.execute(
            "SELECT acl_subject_type, acl_subject_id, permission, acl_version "
            "FROM collabio.object_acl_entries WHERE tenant_id = %s AND object_id = %s "
            "AND object_type = %s AND status = 'active' "
            "ORDER BY acl_subject_type, acl_subject_id, permission, acl_version",
            (tenant_id, object_id, OFFICE_DOCUMENT_OBJECT_TYPE),
        ).fetchall()

    def commit(
        self, *, user_context: UserContext, object_id: str | None, command: OfficeDocumentCreateCommand,
    ) -> OfficeDocumentCommit:
        command = type(command).model_validate(command.model_dump(mode="python"))
        if object_id is None and not can_create_office_document(user_context):
            raise OfficeDocumentPermissionError("Document creation is not permitted")
        if object_id is not None and not isinstance(command, OfficeDocumentSaveCommand):
            raise OfficeDocumentConflictError("Expected current version is required")
        command_hash = office_document_command_hash(user_context=user_context, object_id=object_id, command=command)
        try:
            with psycopg.connect(self.database_dsn) as connection, connection.transaction():
                self._set_tenant(connection, user_context.tenant_id)
                connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                                   (f"office-document-write:{user_context.tenant_id}",))
                with connection.cursor(row_factory=dict_row) as cursor:
                    replay = cursor.execute(
                        f"SELECT {_VERSION_COLUMNS} FROM office.document_versions "
                        "WHERE tenant_id = %s AND created_by = %s AND mutation_reference = %s",
                        (user_context.tenant_id, user_context.user_id, command.mutation_reference),
                    ).fetchone()
                if replay is not None:
                    version = OfficeDocumentVersion.model_validate(_model_values(replay))
                    if version.command_hash != command_hash:
                        raise OfficeDocumentConflictError("Mutation reference was already used for another command")
                    document = self._authorized_document(connection, user_context, version.object_id, write=True)
                    return OfficeDocumentCommit(document=document, version=version, replayed=True)
                previous_version_id: str | None = None
                if object_id is None:
                    document = _new_document(user_context, command.title)
                    # Creator ACL and identity collision checks run atomically in the insert trigger.
                    self._insert_document(connection, document)
                else:
                    document = self._authorized_document(connection, user_context, object_id, write=True)
                    if not isinstance(command, OfficeDocumentSaveCommand) or document.current_version_id != command.expected_current_version_id:
                        raise OfficeDocumentConflictError("The document has a newer saved version")
                    previous_version_id = document.current_version_id
                    previous = self._version(connection, tenant_id=user_context.tenant_id,
                                             object_id=object_id, version_id=previous_version_id)
                    OfficeDocumentService._validate_source(self.source_repository.get_metadata(
                        tenant_id=user_context.tenant_id, object_id=object_id, version_id=previous_version_id
                    ), document, previous)
                acl_rows = self._acl_rows(connection, user_context.tenant_id, document.object_id)
                if not acl_rows:
                    raise OfficeDocumentPermissionError("Document saving is not permitted")
                document, version, source, receipt = _prepare_version(
                    user=user_context, document=document, previous_version_id=previous_version_id,
                    command=command, command_hash=command_hash, acl_rows=acl_rows,
                )
                self.receipt_store.append_in_transaction(connection, receipt)
                self.source_repository.add_with_receipt_in_transaction(
                    connection, record=source, source_object_write_receipt_hash=receipt.receipt_hash,
                )
                self._insert_version(connection, version)
                connection.execute(
                    "UPDATE office.documents SET title = %s, current_version_id = %s, updated_at_utc = %s "
                    "WHERE tenant_id = %s AND object_id = %s",
                    (document.title, document.current_version_id, document.updated_at_utc,
                     document.tenant_id, document.object_id),
                )
                result = OfficeDocumentCommit(document=document, version=version)
        except psycopg.errors.UniqueViolation as exc:
            raise OfficeDocumentConflictError("Document mutation conflicts with existing metadata") from exc
        return result

    @staticmethod
    def _insert_document(connection: psycopg.Connection[Any], document: OfficeDocumentRecord) -> None:
        values = document.model_dump()
        connection.execute(
            f"INSERT INTO office.documents ({_DOCUMENT_COLUMNS}) VALUES ({', '.join(['%s'] * len(values))})",
            tuple(values.values()),
        )

    @staticmethod
    def _insert_version(connection: psycopg.Connection[Any], version: OfficeDocumentVersion) -> None:
        values = version.model_dump()
        connection.execute(
            f"INSERT INTO office.document_versions ({_VERSION_COLUMNS}) VALUES ({', '.join(['%s'] * len(values))})",
            tuple(values.values()),
        )


class InMemoryOfficeDocumentRepository:
    """Explicit unit-test/demo adapter; never a durable runtime fallback."""

    def __init__(
        self, *, source_repository: InMemorySourceObjectRepository,
        receipt_store: InMemorySourceObjectWriteReceiptStore | None = None,
    ) -> None:
        self.source_repository = source_repository
        self.receipt_store = receipt_store or InMemorySourceObjectWriteReceiptStore()
        self.documents: dict[tuple[str, str], OfficeDocumentRecord] = {}
        self.saved_versions: dict[tuple[str, str, str], OfficeDocumentVersion] = {}
        self.grants: dict[tuple[str, str, str], str] = {}
        self._lock = RLock()

    def _permission(self, user: UserContext, object_id: str) -> str | None:
        if object_id not in user.readable_object_ids:
            return None
        return self.grants.get((user.tenant_id, object_id, user.user_id))

    def list_documents(self, *, user_context: UserContext) -> tuple[OfficeDocumentRecord, ...]:
        return tuple(document for (tenant_id, object_id), document in self.documents.items()
                     if tenant_id == user_context.tenant_id and self._permission(user_context, object_id))

    def get_document(self, *, user_context: UserContext, object_id: str) -> OfficeDocumentRecord:
        if not self._permission(user_context, object_id):
            raise OfficeDocumentNotFoundError("Document not found")
        try:
            return self.documents[(user_context.tenant_id, object_id)]
        except KeyError as exc:
            raise OfficeDocumentNotFoundError("Document not found") from exc

    def can_write(self, *, user_context: UserContext, object_id: str) -> bool:
        return self._permission(user_context, object_id) in {"write", "admin"}

    def versions(self, *, user_context: UserContext, object_id: str) -> tuple[OfficeDocumentVersion, ...]:
        self.get_document(user_context=user_context, object_id=object_id)
        return tuple(sorted((version for (tenant_id, doc_id, _), version in self.saved_versions.items()
                             if tenant_id == user_context.tenant_id and doc_id == object_id),
                            key=lambda version: (version.created_at_utc, version.version_id), reverse=True)[:200])

    def get_version(self, *, user_context: UserContext, object_id: str, version_id: str) -> OfficeDocumentVersion:
        self.get_document(user_context=user_context, object_id=object_id)
        try:
            return self.saved_versions[(user_context.tenant_id, object_id, version_id)]
        except KeyError as exc:
            raise OfficeDocumentNotFoundError("Document not found") from exc

    def commit(
        self, *, user_context: UserContext, object_id: str | None, command: OfficeDocumentCreateCommand,
    ) -> OfficeDocumentCommit:
        command = type(command).model_validate(command.model_dump(mode="python"))
        with self._lock:
            if object_id is None and not can_create_office_document(user_context):
                raise OfficeDocumentPermissionError("Document creation is not permitted")
            command_hash = office_document_command_hash(user_context=user_context, object_id=object_id, command=command)
            for version in self.saved_versions.values():
                if (version.tenant_id, version.created_by, version.mutation_reference) == (
                    user_context.tenant_id, user_context.user_id, command.mutation_reference
                ):
                    if version.command_hash != command_hash:
                        raise OfficeDocumentConflictError("Mutation reference was already used for another command")
                    document = self.get_document(user_context=user_context, object_id=version.object_id)
                    if not self.can_write(user_context=user_context, object_id=version.object_id):
                        raise OfficeDocumentPermissionError("Document saving is not permitted")
                    return OfficeDocumentCommit(document=document, version=version, replayed=True)
            previous: str | None = None
            if object_id is None:
                document = _new_document(user_context, command.title)
                acl_rows = [("user", user_context.user_id, "admin", 1)]
            else:
                document = self.get_document(user_context=user_context, object_id=object_id)
                if not self.can_write(user_context=user_context, object_id=object_id):
                    raise OfficeDocumentPermissionError("Document saving is not permitted")
                if not isinstance(command, OfficeDocumentSaveCommand) or command.expected_current_version_id != document.current_version_id:
                    raise OfficeDocumentConflictError("The document has a newer saved version")
                previous = document.current_version_id
                old_version = self.get_version(user_context=user_context, object_id=object_id, version_id=previous)
                OfficeDocumentService._validate_source(self.source_repository.get_metadata(
                    tenant_id=user_context.tenant_id, object_id=object_id, version_id=previous
                ), document, old_version)
                acl_rows = sorted(("user", principal, permission, 1)
                                  for (tenant_id, doc_id, principal), permission in self.grants.items()
                                  if tenant_id == user_context.tenant_id and doc_id == object_id)
            document, version, source, receipt = _prepare_version(
                user=user_context, document=document, previous_version_id=previous,
                command=command, command_hash=command_hash, acl_rows=acl_rows,
            )
            self.source_repository.add(source)
            self.receipt_store.append(receipt)
            self.documents[(document.tenant_id, document.object_id)] = document
            self.saved_versions[(document.tenant_id, document.object_id, version.version_id)] = version
            if object_id is None:
                self.grants[(document.tenant_id, document.object_id, user_context.user_id)] = "admin"
            return OfficeDocumentCommit(document=document, version=version)
