from __future__ import annotations

import json
from datetime import UTC, datetime
from threading import RLock
from typing import Any, Literal, cast
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from suite.ai_control_plane.audit import InMemoryAuditLogger, canonical_json, stable_hash
from suite.ai_control_plane.models import DataClass, UserContext
from suite.platform.office_document_schema import (
    OFFICE_DOCUMENT_MIME_TYPE,
    OFFICE_DOCUMENT_SCHEMA_VERSION,
    OfficeDocumentInvalidContentError,
)
from suite.platform.office_documents import (
    OFFICE_DOCUMENT_OBJECT_TYPE,
    OFFICE_DOCUMENT_SOURCE_SYSTEM,
    OfficeDocumentCommit,
    OfficeDocumentConflictError,
    OfficeDocumentCreateCommand,
    OfficeDocumentHistoryPage,
    OfficeDocumentNotFoundError,
    OfficeDocumentPermissionError,
    OfficeDocumentRecord,
    OfficeDocumentSaveCommand,
    OfficeDocumentService,
    OfficeDocumentShareCommand,
    OfficeDocumentShareEntry,
    OfficeDocumentSharePrincipal,
    OfficeDocumentShareRequestError,
    OfficeDocumentShareState,
    OfficeDocumentUnshareCommand,
    OfficeDocumentVersion,
    OfficeInformationClassification,
    can_create_office_document,
    office_document_command_hash,
    validate_office_classification_change,
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
_ACL_SUBJECT_SQL = """
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
"""


def _model_values(values: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.astimezone(UTC).isoformat().replace("+00:00", "Z") if isinstance(value, datetime) else value
        for key, value in values.items()
    }


def _validated_history_page(
    *,
    document: OfficeDocumentRecord,
    head: str,
    start: str,
    versions: tuple[OfficeDocumentVersion, ...],
    limit: int,
) -> OfficeDocumentHistoryPage:
    expected: str | None = start
    seen: set[str] = set()
    for version in versions:
        if (
            version.tenant_id != document.tenant_id
            or version.object_id != document.object_id
            or version.version_id != expected
            or version.version_id in seen
            or (start != head and version.version_id == head)
        ):
            raise OfficeDocumentInvalidContentError("Document history integrity failed")
        seen.add(version.version_id)
        expected = version.previous_version_id
    if not versions or expected in seen or (len(versions) < limit and expected is not None):
        raise OfficeDocumentInvalidContentError("Document history integrity failed")
    return OfficeDocumentHistoryPage(
        history_head_version_id=head,
        current_version_id=document.current_version_id,
        versions=versions,
    )


def _new_document(
    user: UserContext, title: str, information_classification: OfficeInformationClassification
) -> OfficeDocumentRecord:
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return OfficeDocumentRecord(
        tenant_id=user.tenant_id,
        object_id=f"office-doc-{uuid4().hex}",
        title=title,
        information_classification=information_classification,
        current_version_id=f"office-version-{uuid4().hex}",
        owner_principal_id=user.user_id,
        created_by=user.user_id,
        created_at_utc=now,
        updated_at_utc=now,
        audit_chain_ref=f"audit:office-document-{uuid4().hex}",
    )


def _prepare_version(
    *,
    user: UserContext,
    document: OfficeDocumentRecord,
    previous_version_id: str | None,
    command: OfficeDocumentCreateCommand,
    command_hash: str,
    acl_rows: list[tuple[Any, ...]],
) -> tuple[OfficeDocumentRecord, OfficeDocumentVersion, SourceObjectRecord, SourceObjectWriteReceipt]:
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    version_id = document.current_version_id if previous_version_id is None else f"office-version-{uuid4().hex}"
    audit_ref = f"audit:office-document-version-{uuid4().hex}"
    document = document.model_copy(
        update={
            "title": command.title,
            "information_classification": command.information_classification,
            "current_version_id": version_id,
            "updated_at_utc": now,
        }
    )
    content = canonical_json(command.document).encode("utf-8")
    metadata = SourceObjectMetadata(
        tenant_id=user.tenant_id,
        object_id=document.object_id,
        object_type=SourceObjectType.DOCUMENT,
        version_id=version_id,
        title=command.title,
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
        source_system=OFFICE_DOCUMENT_SOURCE_SYSTEM,
        schema_version=OFFICE_DOCUMENT_SCHEMA_VERSION,
        mime_type=OFFICE_DOCUMENT_MIME_TYPE,
        acl_hash=stable_hash(canonical_json(acl_rows)),
        acl_version=max(int(row[3]) for row in acl_rows),
        content_hash=sha256_bytes(content),
        content_byte_length=len(content),
        lifecycle_state=SourceLifecycleState.SAVED_VERSION,
    )
    metadata = metadata.model_copy(update={"manifest_hash": build_source_object_manifest_hash(metadata)})
    source = SourceObjectRecord(metadata=metadata, content_bytes=content)
    receipt = build_source_object_write_receipt(
        record=source,
        receipt_reference=f"office-write:{uuid4().hex}",
        audit_chain_ref=audit_ref,
        captured_at_utc=now,
    )
    version = OfficeDocumentVersion(
        tenant_id=user.tenant_id,
        object_id=document.object_id,
        version_id=version_id,
        previous_version_id=previous_version_id,
        title=command.title,
        information_classification=command.information_classification,
        created_at_utc=now,
        created_by=user.user_id,
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
    return document, version, source, receipt


class PgOfficeDocumentRepository:
    """Native document writes share the source/receipt transaction and serialize before PUT.

    S3 is not a PostgreSQL participant. An unexpected database failure after PUT
    may leave an orphan, which the source content recovery reconciler detects.
    """

    def __init__(
        self,
        *,
        database_dsn: str,
        source_repository: PgSourceObjectRepository,
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
            f"""
            SELECT DISTINCT acl.permission
            FROM collabio.object_acl_entries AS acl
            WHERE acl.tenant_id = %s AND acl.object_id = %s AND acl.object_type = %s
              AND acl.status = 'active'
              AND (acl.expires_at_utc IS NULL OR acl.expires_at_utc > now())
              AND ({_ACL_SUBJECT_SQL})
            """,
            (user.tenant_id, object_id, OFFICE_DOCUMENT_OBJECT_TYPE, user.user_id, sorted(user.role_ids), user.user_id),
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
        self,
        connection: psycopg.Connection[Any],
        user: UserContext,
        object_id: str,
        *,
        write: bool = False,
    ) -> OfficeDocumentRecord:
        permissions = self._permissions(connection, user, object_id)
        if not permissions:
            raise OfficeDocumentNotFoundError("Document not found")
        if write and not permissions & {"write", "admin"}:
            raise OfficeDocumentPermissionError("Document saving is not permitted")
        return self._document(connection, user.tenant_id, object_id)

    def list_documents(
        self,
        *,
        user_context: UserContext,
        query: str = "",
        after: tuple[str, str] | None = None,
        limit: int = 200,
    ) -> tuple[OfficeDocumentRecord, ...]:
        # Every returned row, including the lookahead, is authorized before LIMIT.
        columns = ", ".join(f"document.{name}" for name in OfficeDocumentRecord.model_fields)
        parameters: list[Any] = [
            user_context.tenant_id,
            sorted(user_context.readable_object_ids),
            query,
            OFFICE_DOCUMENT_OBJECT_TYPE,
            user_context.user_id,
            sorted(user_context.role_ids),
            user_context.user_id,
        ]
        boundary = ""
        if after is not None:
            boundary = "AND (document.created_at_utc, document.object_id) < (%s::timestamptz, %s)"
            parameters.extend(after)
        parameters.append(limit)
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, user_context.tenant_id)
            with connection.cursor(row_factory=dict_row) as cursor:
                rows = cursor.execute(
                    f"""
                    SELECT {columns} FROM office.documents AS document
                    WHERE document.tenant_id = %s AND document.object_id = ANY(%s::text[])
                      AND strpos(lower(document.title), lower(%s)) > 0
                      AND EXISTS (
                        SELECT 1 FROM collabio.object_acl_entries AS acl
                        WHERE acl.tenant_id = document.tenant_id AND acl.object_id = document.object_id
                          AND acl.object_type = %s AND acl.status = 'active'
                          AND (acl.expires_at_utc IS NULL OR acl.expires_at_utc > now())
                          AND ({_ACL_SUBJECT_SQL})
                      )
                      {boundary}
                    ORDER BY document.created_at_utc DESC, document.object_id DESC LIMIT %s
                    """,
                    parameters,
                ).fetchall()
            return tuple(OfficeDocumentRecord.model_validate(_model_values(row)) for row in rows)

    def get_document(self, *, user_context: UserContext, object_id: str) -> OfficeDocumentRecord:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, user_context.tenant_id)
            return self._authorized_document(connection, user_context, object_id)

    def can_write(self, *, user_context: UserContext, object_id: str) -> bool:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, user_context.tenant_id)
            return bool(self._permissions(connection, user_context, object_id) & {"write", "admin"})

    @staticmethod
    def _can_manage_shares(connection: psycopg.Connection[Any], user: UserContext, object_id: str) -> bool:
        if object_id not in user.readable_object_ids:
            return False
        row = connection.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM collabio.object_acl_entries AS acl
                WHERE acl.tenant_id = %s AND acl.object_id = %s AND acl.object_type = %s
                  AND acl.acl_subject_type = 'user' AND acl.acl_subject_id = %s
                  AND acl.permission = 'admin' AND acl.status = 'active'
            )
            """,
            (user.tenant_id, object_id, OFFICE_DOCUMENT_OBJECT_TYPE, user.user_id),
        ).fetchone()
        return bool(row and row[0])

    def can_admin(self, *, user_context: UserContext, object_id: str) -> bool:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, user_context.tenant_id)
            return self._can_manage_shares(connection, user_context, object_id)

    def share_state(self, *, user_context: UserContext, object_id: str) -> OfficeDocumentShareState:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, user_context.tenant_id)
            document = self._authorized_document(connection, user_context, object_id)
            if not self._can_manage_shares(connection, user_context, object_id):
                raise OfficeDocumentPermissionError("Document sharing is not permitted")
            return self._share_state(connection, document)

    @staticmethod
    def _share_state(connection: psycopg.Connection[Any], document: OfficeDocumentRecord) -> OfficeDocumentShareState:
        acl_version_row = connection.execute(
            "SELECT COALESCE(MAX(acl_version), 1) FROM collabio.object_acl_entries "
            "WHERE tenant_id = %s AND object_id = %s AND object_type = %s",
            (document.tenant_id, document.object_id, OFFICE_DOCUMENT_OBJECT_TYPE),
        ).fetchone()
        rows = connection.execute(
            """
            SELECT principal.user_id, COALESCE(NULLIF(principal.display_name, ''), principal.user_id),
                   principal.email, acl.permission, acl.expires_at_utc
            FROM collabio.object_acl_entries AS acl
            JOIN collabio.tenant_principals AS principal
              ON principal.tenant_id = acl.tenant_id AND principal.user_id = acl.acl_subject_id
            JOIN collabio.tenant_principal_memberships AS membership
              ON membership.tenant_id = principal.tenant_id
             AND membership.issuer = principal.issuer AND membership.subject = principal.subject
            WHERE acl.tenant_id = %s AND acl.object_id = %s AND acl.object_type = %s
              AND acl.acl_subject_type = 'user' AND acl.status = 'active'
              AND (acl.expires_at_utc IS NULL OR acl.expires_at_utc > now())
              AND principal.status = 'active' AND membership.status = 'active'
            ORDER BY lower(COALESCE(NULLIF(principal.display_name, ''), principal.user_id)), principal.user_id
            """,
            (document.tenant_id, document.object_id, OFFICE_DOCUMENT_OBJECT_TYPE),
        ).fetchall()
        available = connection.execute(
            """
            SELECT principal.user_id, COALESCE(NULLIF(principal.display_name, ''), principal.user_id), principal.email
            FROM collabio.tenant_principals AS principal
            JOIN collabio.tenant_principal_memberships AS membership
              ON membership.tenant_id = principal.tenant_id
             AND membership.issuer = principal.issuer AND membership.subject = principal.subject
            WHERE principal.tenant_id = %s AND principal.status = 'active' AND membership.status = 'active'
            ORDER BY lower(COALESCE(NULLIF(principal.display_name, ''), principal.user_id)), principal.user_id
            LIMIT 500
            """,
            (document.tenant_id,),
        ).fetchall()
        return OfficeDocumentShareState(
            tenant_id=document.tenant_id,
            object_id=document.object_id,
            acl_version=int(acl_version_row[0]) if acl_version_row else 1,
            entries=[
                OfficeDocumentShareEntry(
                    principal_id=str(row[0]),
                    display_name=str(row[1]),
                    email=str(row[2]) if row[2] is not None else None,
                    permission=cast(Literal["read", "write", "admin"], str(row[3])),
                    is_owner=str(row[0]) == document.owner_principal_id,
                    expires_at_utc=(row[4].astimezone(UTC).isoformat().replace("+00:00", "Z") if row[4] else None),
                )
                for row in rows
            ],
            available_principals=[
                OfficeDocumentSharePrincipal(
                    principal_id=str(row[0]),
                    display_name=str(row[1]),
                    email=str(row[2]) if row[2] is not None else None,
                )
                for row in available
            ],
        )

    def set_share(
        self, *, user_context: UserContext, object_id: str, command: OfficeDocumentShareCommand
    ) -> OfficeDocumentShareState:
        return self._mutate_share(user_context=user_context, object_id=object_id, command=command, revoke=False)

    def revoke_share(
        self, *, user_context: UserContext, object_id: str, command: OfficeDocumentUnshareCommand
    ) -> OfficeDocumentShareState:
        return self._mutate_share(user_context=user_context, object_id=object_id, command=command, revoke=True)

    def _mutate_share(
        self,
        *,
        user_context: UserContext,
        object_id: str,
        command: OfficeDocumentShareCommand | OfficeDocumentUnshareCommand,
        revoke: bool,
    ) -> OfficeDocumentShareState:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, user_context.tenant_id)
            document = self._authorized_document(connection, user_context, object_id)
            if not self._can_manage_shares(connection, user_context, object_id):
                raise OfficeDocumentPermissionError("Document sharing is not permitted")
            if command.principal_id == document.owner_principal_id:
                raise OfficeDocumentShareRequestError("The document owner share cannot be changed")
            function = "office.revoke_document_user_grant" if revoke else "office.set_document_user_grant"
            parameters: tuple[Any, ...]
            if revoke:
                parameters = (
                    user_context.tenant_id,
                    object_id,
                    user_context.user_id,
                    command.principal_id,
                    command.expected_acl_version,
                    command.mutation_reference,
                )
            else:
                assert isinstance(command, OfficeDocumentShareCommand)
                parameters = (
                    user_context.tenant_id,
                    object_id,
                    user_context.user_id,
                    command.principal_id,
                    command.permission,
                    command.expires_at_utc,
                    command.expected_acl_version,
                    command.mutation_reference,
                )
            try:
                connection.execute(f"SELECT {function}({', '.join(['%s'] * len(parameters))})", parameters).fetchone()
            except psycopg.errors.SerializationFailure as exc:
                raise OfficeDocumentConflictError("The document shares have changed") from exc
            except psycopg.errors.CheckViolation as exc:
                raise OfficeDocumentShareRequestError("The document share is invalid") from exc
            return self._share_state(connection, document)

    def versions(self, *, user_context: UserContext, object_id: str) -> tuple[OfficeDocumentVersion, ...]:
        return self.history_page(user_context=user_context, object_id=object_id, limit=201).versions[:200]

    def history_page(
        self,
        *,
        user_context: UserContext,
        object_id: str,
        history_head_version_id: str | None = None,
        next_version_id: str | None = None,
        limit: int = 201,
    ) -> OfficeDocumentHistoryPage:
        if not 1 <= limit <= 201:
            raise OfficeDocumentInvalidContentError("Document history page is invalid")
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, user_context.tenant_id)
            document = self._authorized_document(connection, user_context, object_id)
            head = history_head_version_id or document.current_version_id
            start = next_version_id or head
            if history_head_version_id is not None:
                try:
                    self._version(connection, tenant_id=user_context.tenant_id, object_id=object_id, version_id=head)
                except OfficeDocumentNotFoundError as exc:
                    raise OfficeDocumentInvalidContentError("Document history integrity failed") from exc
            with connection.cursor(row_factory=dict_row) as cursor:
                rows = cursor.execute(
                    """
                    WITH RECURSIVE history AS (
                        SELECT version.*, 1 AS depth, ARRAY[version.version_id] AS path, false AS cycle
                        FROM office.document_versions AS version
                        WHERE version.tenant_id = %s AND version.object_id = %s AND version.version_id = %s
                        UNION ALL
                        SELECT previous.*, history.depth + 1, history.path || previous.version_id,
                               previous.version_id = ANY(history.path)
                        FROM history
                        JOIN office.document_versions AS previous
                          ON previous.tenant_id = history.tenant_id AND previous.object_id = history.object_id
                         AND previous.version_id = history.previous_version_id
                        WHERE history.depth < %s AND NOT history.cycle
                    )
                    SELECT * FROM history ORDER BY depth
                    """,
                    (user_context.tenant_id, object_id, start, limit),
                ).fetchall()
        versions = tuple(
            OfficeDocumentVersion.model_validate(
                _model_values({name: row[name] for name in OfficeDocumentVersion.model_fields})
            )
            for row in rows
        )
        return _validated_history_page(document=document, head=head, start=start, versions=versions, limit=limit)

    @staticmethod
    def _version(
        connection: psycopg.Connection[Any],
        *,
        tenant_id: str,
        object_id: str,
        version_id: str,
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
            return self._version(
                connection, tenant_id=user_context.tenant_id, object_id=object_id, version_id=version_id
            )

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
        self,
        *,
        user_context: UserContext,
        object_id: str | None,
        command: OfficeDocumentCreateCommand,
    ) -> OfficeDocumentCommit:
        from suite.platform.office_images import prepare_image_references

        command = type(command).model_validate(command.model_dump(mode="python"))
        if command.mutation_reference.startswith("office-suggestion-accept:"):
            raise OfficeDocumentInvalidContentError("Document mutation reference is reserved")
        if object_id is None and not can_create_office_document(user_context):
            raise OfficeDocumentPermissionError("Document creation is not permitted")
        if object_id is not None and not isinstance(command, OfficeDocumentSaveCommand):
            raise OfficeDocumentConflictError("Expected current version is required")
        command_hash = office_document_command_hash(user_context=user_context, object_id=object_id, command=command)
        try:
            with psycopg.connect(self.database_dsn) as connection, connection.transaction():
                self._set_tenant(connection, user_context.tenant_id)
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"office-document-write:{user_context.tenant_id}",),
                )
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
                    saved = OfficeDocumentService(
                        repository=self, source_repository=self.source_repository, audit=InMemoryAuditLogger()
                    )
                    return OfficeDocumentCommit(
                        document=document,
                        version=version,
                        replayed=True,
                        content=saved._read_content(document, version),
                    )
                previous_version_id: str | None = None
                if object_id is None:
                    validate_office_classification_change(
                        user_context=user_context, current=None, target=command.information_classification
                    )
                    document = _new_document(user_context, command.title, command.information_classification)
                    # Creator ACL and identity collision checks run atomically in the insert trigger.
                    self._insert_document(connection, document)
                else:
                    document = self._authorized_document(connection, user_context, object_id, write=True)
                    if (
                        not isinstance(command, OfficeDocumentSaveCommand)
                        or document.current_version_id != command.expected_current_version_id
                    ):
                        raise OfficeDocumentConflictError("The document has a newer saved version")
                    previous_version_id = document.current_version_id
                    validate_office_classification_change(
                        user_context=user_context,
                        current=document.information_classification,
                        target=command.information_classification,
                    )
                    previous = self._version(
                        connection,
                        tenant_id=user_context.tenant_id,
                        object_id=object_id,
                        version_id=previous_version_id,
                    )
                    OfficeDocumentService._validate_source(
                        self.source_repository.get_metadata(
                            tenant_id=user_context.tenant_id, object_id=object_id, version_id=previous_version_id
                        ),
                        document,
                        previous,
                    )
                acl_rows = self._acl_rows(connection, user_context.tenant_id, document.object_id)
                if not acl_rows:
                    raise OfficeDocumentPermissionError("Document saving is not permitted")
                content = prepare_image_references(
                    self, connection, user_context, document, command.document, creating=object_id is None
                )
                command = command.model_copy(update={"document": content})
                document, version, source, receipt = _prepare_version(
                    user=user_context,
                    document=document,
                    previous_version_id=previous_version_id,
                    command=command,
                    command_hash=command_hash,
                    acl_rows=acl_rows,
                )
                result = self._persist_prepared_version(connection, document, version, source, receipt)
        except psycopg.errors.UniqueViolation as exc:
            raise OfficeDocumentConflictError("Document mutation conflicts with existing metadata") from exc
        return result

    def _persist_prepared_version(
        self,
        connection: psycopg.Connection[Any],
        document: OfficeDocumentRecord,
        version: OfficeDocumentVersion,
        source: SourceObjectRecord,
        receipt: SourceObjectWriteReceipt,
    ) -> OfficeDocumentCommit:
        """Internal primitive; caller owns the tenant lock, authorization and CAS checks."""
        self.receipt_store.append_in_transaction(connection, receipt)
        self.source_repository.add_with_receipt_in_transaction(
            connection, record=source, source_object_write_receipt_hash=receipt.receipt_hash
        )
        self._insert_version(connection, version)
        connection.execute(
            "UPDATE office.documents SET title = %s, information_classification = %s, "
            "current_version_id = %s, updated_at_utc = %s "
            "WHERE tenant_id = %s AND object_id = %s",
            (
                document.title,
                document.information_classification,
                document.current_version_id,
                document.updated_at_utc,
                document.tenant_id,
                document.object_id,
            ),
        )
        return OfficeDocumentCommit(
            document=document, version=version, content=json.loads(source.content_bytes or b"{}")
        )

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
        self,
        *,
        source_repository: InMemorySourceObjectRepository,
        receipt_store: InMemorySourceObjectWriteReceiptStore | None = None,
    ) -> None:
        self.source_repository = source_repository
        self.receipt_store = receipt_store or InMemorySourceObjectWriteReceiptStore()
        self.documents: dict[tuple[str, str], OfficeDocumentRecord] = {}
        self.saved_versions: dict[tuple[str, str, str], OfficeDocumentVersion] = {}
        self.grants: dict[tuple[str, str, str], str] = {}
        self.grant_expirations: dict[tuple[str, str, str], datetime] = {}
        self.share_versions: dict[tuple[str, str], int] = {}
        self.principals: dict[tuple[str, str], tuple[str, str | None]] = {}
        self._lock = RLock()

    def _permission(self, user: UserContext, object_id: str) -> str | None:
        if object_id not in user.readable_object_ids:
            return None
        key = (user.tenant_id, object_id, user.user_id)
        expiration = self.grant_expirations.get(key)
        if expiration is not None and expiration <= datetime.now(UTC):
            return None
        return self.grants.get(key)

    def list_documents(
        self,
        *,
        user_context: UserContext,
        query: str = "",
        after: tuple[str, str] | None = None,
        limit: int = 200,
    ) -> tuple[OfficeDocumentRecord, ...]:
        with self._lock:
            boundary = (datetime.fromisoformat(after[0]), after[1]) if after else None
            records = [
                document
                for (tenant_id, object_id), document in self.documents.items()
                if tenant_id == user_context.tenant_id
                and self._permission(user_context, object_id)
                and query.lower() in document.title.lower()
                and (
                    boundary is None or (datetime.fromisoformat(document.created_at_utc), document.object_id) < boundary
                )
            ]
            return tuple(
                sorted(
                    records,
                    key=lambda record: (datetime.fromisoformat(record.created_at_utc), record.object_id),
                    reverse=True,
                )[:limit]
            )

    def get_document(self, *, user_context: UserContext, object_id: str) -> OfficeDocumentRecord:
        if not self._permission(user_context, object_id):
            raise OfficeDocumentNotFoundError("Document not found")
        try:
            return self.documents[(user_context.tenant_id, object_id)]
        except KeyError as exc:
            raise OfficeDocumentNotFoundError("Document not found") from exc

    def can_write(self, *, user_context: UserContext, object_id: str) -> bool:
        return self._permission(user_context, object_id) in {"write", "admin"}

    def can_admin(self, *, user_context: UserContext, object_id: str) -> bool:
        return self._permission(user_context, object_id) == "admin"

    def share_state(self, *, user_context: UserContext, object_id: str) -> OfficeDocumentShareState:
        with self._lock:
            document = self.get_document(user_context=user_context, object_id=object_id)
            if self._permission(user_context, object_id) != "admin":
                raise OfficeDocumentPermissionError("Document sharing is not permitted")
            known = dict(self.principals)
            for (tenant_id, doc_id, principal_id), _permission in self.grants.items():
                if tenant_id == user_context.tenant_id and doc_id == object_id:
                    known.setdefault((tenant_id, principal_id), (principal_id, None))
            known.setdefault((user_context.tenant_id, user_context.user_id), (user_context.user_id, None))
            entries = []
            for (tenant_id, doc_id, principal_id), permission in sorted(self.grants.items()):
                if tenant_id != user_context.tenant_id or doc_id != object_id:
                    continue
                expiration = self.grant_expirations.get((tenant_id, doc_id, principal_id))
                if expiration is not None and expiration <= datetime.now(UTC):
                    continue
                display_name, email = known[(tenant_id, principal_id)]
                entries.append(
                    OfficeDocumentShareEntry(
                        principal_id=principal_id,
                        display_name=display_name,
                        email=email,
                        permission=cast(Literal["read", "write", "admin"], permission),
                        is_owner=principal_id == document.owner_principal_id,
                        expires_at_utc=(
                            expiration.astimezone(UTC).isoformat().replace("+00:00", "Z") if expiration else None
                        ),
                    )
                )
            available = [
                OfficeDocumentSharePrincipal(principal_id=principal_id, display_name=value[0], email=value[1])
                for (tenant_id, principal_id), value in sorted(known.items(), key=lambda item: item[1][0].lower())
                if tenant_id == user_context.tenant_id
            ]
            return OfficeDocumentShareState(
                tenant_id=user_context.tenant_id,
                object_id=object_id,
                acl_version=self.share_versions.get((user_context.tenant_id, object_id), 1),
                entries=entries,
                available_principals=available,
            )

    def set_share(
        self, *, user_context: UserContext, object_id: str, command: OfficeDocumentShareCommand
    ) -> OfficeDocumentShareState:
        return self._mutate_memory_share(user_context, object_id, command, revoke=False)

    def revoke_share(
        self, *, user_context: UserContext, object_id: str, command: OfficeDocumentUnshareCommand
    ) -> OfficeDocumentShareState:
        return self._mutate_memory_share(user_context, object_id, command, revoke=True)

    def _mutate_memory_share(
        self,
        user_context: UserContext,
        object_id: str,
        command: OfficeDocumentShareCommand | OfficeDocumentUnshareCommand,
        *,
        revoke: bool,
    ) -> OfficeDocumentShareState:
        with self._lock:
            document = self.get_document(user_context=user_context, object_id=object_id)
            if self._permission(user_context, object_id) != "admin":
                raise OfficeDocumentPermissionError("Document sharing is not permitted")
            current = self.share_versions.get((user_context.tenant_id, object_id), 1)
            if current != command.expected_acl_version:
                raise OfficeDocumentConflictError("The document shares have changed")
            if command.principal_id == document.owner_principal_id:
                raise OfficeDocumentShareRequestError("The document owner share cannot be changed")
            if (user_context.tenant_id, command.principal_id) not in self.principals:
                raise OfficeDocumentShareRequestError("The principal is not an active tenant member")
            key = (user_context.tenant_id, object_id, command.principal_id)
            if revoke:
                self.grants.pop(key, None)
                self.grant_expirations.pop(key, None)
            else:
                assert isinstance(command, OfficeDocumentShareCommand)
                self.grants[key] = command.permission
                if command.expires_at_utc is None:
                    self.grant_expirations.pop(key, None)
                else:
                    self.grant_expirations[key] = command.expires_at_utc
            self.share_versions[(user_context.tenant_id, object_id)] = current + 1
            return self.share_state(user_context=user_context, object_id=object_id)

    def versions(self, *, user_context: UserContext, object_id: str) -> tuple[OfficeDocumentVersion, ...]:
        return self.history_page(user_context=user_context, object_id=object_id, limit=201).versions[:200]

    def history_page(
        self,
        *,
        user_context: UserContext,
        object_id: str,
        history_head_version_id: str | None = None,
        next_version_id: str | None = None,
        limit: int = 201,
    ) -> OfficeDocumentHistoryPage:
        if not 1 <= limit <= 201:
            raise OfficeDocumentInvalidContentError("Document history page is invalid")
        with self._lock:
            document = self.get_document(user_context=user_context, object_id=object_id)
            head = history_head_version_id or document.current_version_id
            start = next_version_id or head
            if (user_context.tenant_id, object_id, head) not in self.saved_versions:
                raise OfficeDocumentInvalidContentError("Document history integrity failed")
            versions: list[OfficeDocumentVersion] = []
            version_id: str | None = start
            seen: set[str] = set()
            while version_id is not None and len(versions) < limit:
                version = self.saved_versions.get((user_context.tenant_id, object_id, version_id))
                if version is None or version_id in seen:
                    raise OfficeDocumentInvalidContentError("Document history integrity failed")
                versions.append(version)
                seen.add(version_id)
                version_id = version.previous_version_id
            return _validated_history_page(
                document=document,
                head=head,
                start=start,
                versions=tuple(versions),
                limit=limit,
            )

    def get_version(self, *, user_context: UserContext, object_id: str, version_id: str) -> OfficeDocumentVersion:
        self.get_document(user_context=user_context, object_id=object_id)
        try:
            return self.saved_versions[(user_context.tenant_id, object_id, version_id)]
        except KeyError as exc:
            raise OfficeDocumentNotFoundError("Document not found") from exc

    def commit(
        self,
        *,
        user_context: UserContext,
        object_id: str | None,
        command: OfficeDocumentCreateCommand,
    ) -> OfficeDocumentCommit:
        command = type(command).model_validate(command.model_dump(mode="python"))
        from suite.platform.office_image_schema import image_references

        if image_references(command.document):
            raise OfficeDocumentInvalidContentError("Image writes require the durable Office repository")
        if command.mutation_reference.startswith("office-suggestion-accept:"):
            raise OfficeDocumentInvalidContentError("Document mutation reference is reserved")
        with self._lock:
            if object_id is None and not can_create_office_document(user_context):
                raise OfficeDocumentPermissionError("Document creation is not permitted")
            command_hash = office_document_command_hash(user_context=user_context, object_id=object_id, command=command)
            for version in self.saved_versions.values():
                if (version.tenant_id, version.created_by, version.mutation_reference) == (
                    user_context.tenant_id,
                    user_context.user_id,
                    command.mutation_reference,
                ):
                    if version.command_hash != command_hash:
                        raise OfficeDocumentConflictError("Mutation reference was already used for another command")
                    document = self.get_document(user_context=user_context, object_id=version.object_id)
                    if not self.can_write(user_context=user_context, object_id=version.object_id):
                        raise OfficeDocumentPermissionError("Document saving is not permitted")
                    return OfficeDocumentCommit(document=document, version=version, replayed=True)
            previous: str | None = None
            if object_id is None:
                validate_office_classification_change(
                    user_context=user_context, current=None, target=command.information_classification
                )
                document = _new_document(user_context, command.title, command.information_classification)
                acl_rows = [("user", user_context.user_id, "admin", 1)]
            else:
                document = self.get_document(user_context=user_context, object_id=object_id)
                if not self.can_write(user_context=user_context, object_id=object_id):
                    raise OfficeDocumentPermissionError("Document saving is not permitted")
                if (
                    not isinstance(command, OfficeDocumentSaveCommand)
                    or command.expected_current_version_id != document.current_version_id
                ):
                    raise OfficeDocumentConflictError("The document has a newer saved version")
                previous = document.current_version_id
                validate_office_classification_change(
                    user_context=user_context,
                    current=document.information_classification,
                    target=command.information_classification,
                )
                old_version = self.get_version(user_context=user_context, object_id=object_id, version_id=previous)
                OfficeDocumentService._validate_source(
                    self.source_repository.get_metadata(
                        tenant_id=user_context.tenant_id, object_id=object_id, version_id=previous
                    ),
                    document,
                    old_version,
                )
                acl_rows = sorted(
                    (
                        "user",
                        principal,
                        permission,
                        self.share_versions.get((user_context.tenant_id, object_id), 1),
                    )
                    for (tenant_id, doc_id, principal), permission in self.grants.items()
                    if tenant_id == user_context.tenant_id and doc_id == object_id
                )
            document, version, source, receipt = _prepare_version(
                user=user_context,
                document=document,
                previous_version_id=previous,
                command=command,
                command_hash=command_hash,
                acl_rows=acl_rows,
            )
            self.source_repository.add(source)
            self.receipt_store.append(receipt)
            self.documents[(document.tenant_id, document.object_id)] = document
            self.saved_versions[(document.tenant_id, document.object_id, version.version_id)] = version
            if object_id is None:
                self.grants[(document.tenant_id, document.object_id, user_context.user_id)] = "admin"
                self.share_versions[(document.tenant_id, document.object_id)] = 1
                self.principals.setdefault((document.tenant_id, user_context.user_id), (user_context.user_id, None))
            return OfficeDocumentCommit(document=document, version=version)
