"""Suggestions and document acceptance share one Office transaction and lock."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.ai_control_plane.models import DataClass, UserContext
from suite.platform.office_document_repository import (
    InMemoryOfficeDocumentRepository,
    PgOfficeDocumentRepository,
    _model_values,
    _prepare_version,
)
from suite.platform.office_documents import (
    OfficeDocumentConflictError,
    OfficeDocumentInvalidContentError,
    OfficeDocumentNotFoundError,
    OfficeDocumentPermissionError,
    OfficeDocumentRecord,
    OfficeDocumentSaveCommand,
    OfficeDocumentService,
    OfficeDocumentVersion,
    office_document_command_hash,
)
from suite.platform.office_reviews import derive_review_quote
from suite.platform.office_suggestions import (
    MAX_SUGGESTION_BYTES,
    SUGGESTION_MIME,
    SUGGESTION_SCHEMA,
    SUGGESTION_SOURCE_SYSTEM,
    SuggestionCreateCommand,
    SuggestionDecisionCommand,
    SuggestionDecisionRecord,
    SuggestionEvidence,
    SuggestionListSnapshot,
    SuggestionSnapshot,
    TextSuggestionRecord,
    read_suggestion_payload,
    replace_suggestion_text,
    suggestion_command_hash,
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

Connection = psycopg.Connection[Any] | None
TABLE_MODELS = {"text_suggestions": TextSuggestionRecord, "text_suggestion_decisions": SuggestionDecisionRecord}


def _prepare_evidence(
    user: UserContext,
    document: OfficeDocumentRecord,
    suggestion_id: str,
    source_version_id: str,
    payload: dict[str, Any],
    command_hash: str,
    mutation_reference: str,
    acl_rows: list[tuple[Any, ...]],
) -> tuple[SuggestionEvidence, SourceObjectRecord, SourceObjectWriteReceipt]:
    content = canonical_json(payload).encode("utf-8")
    if not acl_rows or len(content) > MAX_SUGGESTION_BYTES:
        raise OfficeDocumentInvalidContentError("Suggestion source is invalid")
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    audit_ref = f"audit:office-suggestion-{uuid4().hex}"
    metadata = SourceObjectMetadata(
        tenant_id=user.tenant_id,
        object_id=suggestion_id,
        version_id=source_version_id,
        object_type=SourceObjectType.COMMENT,
        title="Office text suggestion",
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
        source_system=SUGGESTION_SOURCE_SYSTEM,
        schema_version=SUGGESTION_SCHEMA,
        mime_type=SUGGESTION_MIME,
        lifecycle_state=SourceLifecycleState.SAVED_VERSION,
        acl_hash=stable_hash(canonical_json(acl_rows)),
        acl_version=max(int(row[3]) for row in acl_rows),
        content_hash=sha256_bytes(content),
        content_byte_length=len(content),
        parent_object_id=document.object_id,
        thread_id=suggestion_id,
    )
    metadata = metadata.model_copy(update={"manifest_hash": build_source_object_manifest_hash(metadata)})
    source = SourceObjectRecord(metadata=metadata, content_bytes=content)
    receipt = build_source_object_write_receipt(
        record=source,
        receipt_reference=f"office-suggestion-write:{uuid4().hex}",
        audit_chain_ref=audit_ref,
        captured_at_utc=now,
    )
    evidence = SuggestionEvidence(
        tenant_id=user.tenant_id,
        object_id=document.object_id,
        suggestion_id=suggestion_id,
        source_version_id=source_version_id,
        created_by=user.user_id,
        created_at_utc=now,
        content_hash=metadata.content_hash,
        source_manifest_hash=metadata.manifest_hash,
        source_write_receipt_hash=receipt.receipt_hash,
        content_byte_length=len(content),
        acl_hash=metadata.acl_hash,
        acl_version=metadata.acl_version,
        mutation_reference=mutation_reference,
        command_hash=command_hash,
        audit_chain_ref=audit_ref,
    )
    return evidence, source, receipt


class OfficeSuggestionRepositoryAdapter:
    """Durable PostgreSQL adapter, with an explicitly constructed in-memory test mode."""

    def __init__(self, *, document_service: OfficeDocumentService) -> None:
        if not isinstance(document_service.repository, PgOfficeDocumentRepository | InMemoryOfficeDocumentRepository):
            raise ValueError("Unsupported Office repository")
        self.documents = document_service.repository
        self.document_service = document_service
        self._memory: dict[str, dict[tuple[str, str], dict[str, Any]]] = {table: {} for table in TABLE_MODELS}

    @contextmanager
    def _session(self, user: UserContext, *, write: bool = False) -> Iterator[Connection]:
        if isinstance(self.documents, PgOfficeDocumentRepository):
            try:
                with psycopg.connect(self.documents.database_dsn) as connection, connection.transaction():
                    self.documents._set_tenant(connection, user.tenant_id)
                    if write:
                        connection.execute(
                            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                            (f"office-document-write:{user.tenant_id}",),
                        )
                    yield connection
            except psycopg.errors.UniqueViolation as exc:
                raise OfficeDocumentConflictError("Suggestion decision conflicts with existing metadata") from exc
        else:
            with self.documents._lock:
                stores = [
                    (self.documents, "documents"),
                    (self.documents, "saved_versions"),
                    (self.documents.source_repository, "_records"),
                    (self.documents.source_repository, "_latest_keys"),
                    (self.documents.receipt_store, "_receipts"),
                    (self.documents.receipt_store, "_object_versions"),
                ]
                previous = [(owner, name, getattr(owner, name).copy()) for owner, name in stores]
                old_memory = {table: records.copy() for table, records in self._memory.items()}
                try:
                    yield None
                except Exception:
                    if write:
                        for owner, name, value in previous:
                            setattr(owner, name, value)
                        self._memory = old_memory
                    raise

    def _document(
        self, connection: Connection, user: UserContext, object_id: str, *, write: bool = False
    ) -> OfficeDocumentRecord:
        if isinstance(self.documents, PgOfficeDocumentRepository):
            assert connection is not None
            return self.documents._authorized_document(connection, user, object_id, write=write)
        document = self.documents.get_document(user_context=user, object_id=object_id)
        if write and not self.documents.can_write(user_context=user, object_id=object_id):
            raise OfficeDocumentPermissionError("Document write is not allowed")
        return document

    def _can_write(self, connection: Connection, user: UserContext, object_id: str) -> bool:
        if isinstance(self.documents, PgOfficeDocumentRepository):
            assert connection is not None
            return bool(self.documents._permissions(connection, user, object_id) & {"write", "admin"})
        return self.documents.can_write(user_context=user, object_id=object_id)

    def _version(
        self, connection: Connection, user: UserContext, object_id: str, version_id: str
    ) -> OfficeDocumentVersion:
        if isinstance(self.documents, PgOfficeDocumentRepository):
            assert connection is not None
            return self.documents._version(
                connection, tenant_id=user.tenant_id, object_id=object_id, version_id=version_id
            )
        return self.documents.get_version(user_context=user, object_id=object_id, version_id=version_id)

    def _rows(
        self,
        connection: Connection,
        table: str,
        user: UserContext,
        *,
        after: str | None = None,
        limit: int = 1,
        **filters: str,
    ) -> list[dict[str, Any]]:
        if table not in TABLE_MODELS:
            raise ValueError("Invalid suggestion table")
        filters = {"tenant_id": user.tenant_id, **filters}
        if connection is None:
            rows = [
                row for row in self._memory[table].values() if all(row[key] == value for key, value in filters.items())
            ]
            return sorted(
                (row for row in rows if after is None or row["suggestion_id"] > after),
                key=lambda row: row["suggestion_id"],
            )[:limit]
        conditions = [sql.SQL("{}=%s").format(sql.Identifier(key)) for key in filters]
        params: list[Any] = list(filters.values())
        if after is not None:
            conditions.append(sql.SQL("suggestion_id>%s"))
            params.append(after)
        params.append(limit)
        with connection.cursor(row_factory=dict_row) as cursor:
            rows = cursor.execute(
                sql.SQL("SELECT {} FROM office.{} WHERE {} ORDER BY suggestion_id LIMIT %s").format(
                    sql.SQL(", ").join(sql.Identifier(key) for key in TABLE_MODELS[table].model_fields),
                    sql.Identifier(table),
                    sql.SQL(" AND ").join(conditions),
                ),
                params,
            ).fetchall()
        return [_model_values(row) for row in rows]

    def _suggestion(
        self, connection: Connection, user: UserContext, object_id: str, suggestion_id: str
    ) -> TextSuggestionRecord:
        rows = self._rows(connection, "text_suggestions", user, object_id=object_id, suggestion_id=suggestion_id)
        if not rows:
            raise OfficeDocumentNotFoundError("Document not found")
        return TextSuggestionRecord.model_validate(rows[0])

    def _decision(
        self, connection: Connection, user: UserContext, suggestion_id: str
    ) -> SuggestionDecisionRecord | None:
        rows = self._rows(connection, "text_suggestion_decisions", user, suggestion_id=suggestion_id)
        return SuggestionDecisionRecord.model_validate(rows[0]) if rows else None

    def list_suggestions(
        self,
        *,
        user: UserContext,
        object_id: str,
        after: str | None,
        limit: int,
        anchor_version_id: str | None,
    ) -> SuggestionListSnapshot:
        with self._session(user) as connection:
            document = self._document(connection, user, object_id)
            filters = {"object_id": object_id}
            if anchor_version_id is not None:
                self._version(connection, user, object_id, anchor_version_id)
                filters["anchor_version_id"] = anchor_version_id
            writable = self._can_write(connection, user, object_id)
            rows = self._rows(connection, "text_suggestions", user, after=after, limit=limit + 1, **filters)
            return SuggestionListSnapshot(
                document=document,
                can_write=writable,
                has_more=len(rows) > limit,
                entries=tuple(
                    SuggestionSnapshot(
                        document=document,
                        suggestion=TextSuggestionRecord.model_validate(row),
                        decision=self._decision(connection, user, row["suggestion_id"]),
                        can_write=writable,
                    )
                    for row in rows[:limit]
                ),
            )

    def detail(self, *, user: UserContext, object_id: str, suggestion_id: str) -> SuggestionSnapshot:
        with self._session(user) as connection:
            document = self._document(connection, user, object_id)
            return SuggestionSnapshot(
                document=document,
                suggestion=self._suggestion(connection, user, object_id, suggestion_id),
                decision=self._decision(connection, user, suggestion_id),
                can_write=self._can_write(connection, user, object_id),
            )

    def _store(
        self,
        connection: Connection,
        table: str,
        evidence: SuggestionEvidence,
        source: SourceObjectRecord,
        receipt: SourceObjectWriteReceipt,
    ) -> None:
        if isinstance(self.documents, PgOfficeDocumentRepository):
            assert connection is not None
            self.documents.receipt_store.append_in_transaction(connection, receipt)
            self.documents.source_repository.add_with_receipt_in_transaction(
                connection, record=source, source_object_write_receipt_hash=receipt.receipt_hash
            )
            values = evidence.model_dump()
            connection.execute(
                sql.SQL("INSERT INTO office.{} ({}) VALUES ({})").format(
                    sql.Identifier(table),
                    sql.SQL(", ").join(map(sql.Identifier, values)),
                    sql.SQL(", ").join(sql.Placeholder() for _ in values),
                ),
                tuple(values.values()),
            )
        else:
            self.documents.source_repository.add(source)
            self.documents.receipt_store.append(receipt)
            self._memory[table][(evidence.tenant_id, evidence.suggestion_id)] = evidence.model_dump()

    def _acl_rows(self, connection: Connection, user: UserContext, object_id: str) -> list[tuple[Any, ...]]:
        if isinstance(self.documents, PgOfficeDocumentRepository):
            assert connection is not None
            return self.documents._acl_rows(connection, user.tenant_id, object_id)
        return sorted(
            ("user", actor, permission, 1)
            for (tenant, doc, actor), permission in self.documents.grants.items()
            if tenant == user.tenant_id and doc == object_id
        )

    def _replay(
        self,
        connection: Connection,
        user: UserContext,
        document: OfficeDocumentRecord,
        suggestion: TextSuggestionRecord,
        decision: SuggestionDecisionRecord | None,
    ) -> SuggestionSnapshot:
        payload = read_suggestion_payload(
            self.documents.source_repository, document, suggestion, decision or suggestion
        )
        version = (
            self._version(connection, user, document.object_id, decision.result_version_id)
            if decision and decision.result_version_id
            else None
        )
        content = self.document_service._read_content(document, version) if version else None
        return SuggestionSnapshot(
            document=document,
            suggestion=suggestion,
            decision=decision,
            can_write=True,
            payload=payload,
            result_version=version,
            result_content=content,
            replayed=True,
        )

    def commit(
        self,
        *,
        user: UserContext,
        object_id: str,
        suggestion_id: str | None,
        command: SuggestionCreateCommand | SuggestionDecisionCommand,
    ) -> SuggestionSnapshot:
        command = type(command).model_validate(command.model_dump(mode="python", by_alias=True))
        if (suggestion_id is None) != isinstance(command, SuggestionCreateCommand):
            raise OfficeDocumentConflictError("Suggestion operation is invalid")
        command_hash = suggestion_command_hash(user, object_id, suggestion_id, command)
        with self._session(user, write=True) as connection:
            document = self._document(connection, user, object_id, write=True)
            for table in TABLE_MODELS:
                rows = self._rows(
                    connection, table, user, created_by=user.user_id, mutation_reference=command.mutation_reference
                )
                if rows:
                    if rows[0]["command_hash"] != command_hash:
                        raise OfficeDocumentConflictError("Mutation reference was already used")
                    original = self._suggestion(connection, user, object_id, rows[0]["suggestion_id"])
                    decision = (
                        SuggestionDecisionRecord.model_validate(rows[0])
                        if table == "text_suggestion_decisions"
                        else None
                    )
                    return self._replay(connection, user, document, original, decision)
            acl_rows = self._acl_rows(connection, user, object_id)
            if isinstance(command, SuggestionCreateCommand):
                if (
                    document.current_version_id != command.anchor_version_id
                    or document.current_version_id != command.expected_current_version_id
                ):
                    raise OfficeDocumentConflictError("Document has a newer saved version")
                version = self._version(connection, user, object_id, command.anchor_version_id)
                content = self.document_service._read_content(document, version)
                quote = derive_review_quote(content, command.anchor)
                replace_suggestion_text(content, command.anchor, command.replacement_text)
                new_id = f"office-suggestion-{uuid4().hex}"
                payload = {
                    "schema_version": SUGGESTION_SCHEMA,
                    "suggestion_id": new_id,
                    "document_id": object_id,
                    "anchor_version_id": version.version_id,
                    "anchor_content_hash": version.content_hash,
                    "anchor": command.anchor.model_dump(by_alias=True),
                    "quote": quote,
                    "replacement_text": command.replacement_text,
                    "operation": "create",
                    "result_version_id": None,
                    "result_content_hash": None,
                }
                evidence, source, receipt = _prepare_evidence(
                    user,
                    document,
                    new_id,
                    f"office-suggestion-event-{uuid4().hex}",
                    payload,
                    command_hash,
                    command.mutation_reference,
                    acl_rows,
                )
                suggestion = TextSuggestionRecord(
                    **evidence.model_dump(),
                    anchor_version_id=version.version_id,
                    anchor_content_hash=version.content_hash,
                    anchor_from=command.anchor.from_,
                    anchor_to=command.anchor.to,
                )
                self._store(connection, "text_suggestions", suggestion, source, receipt)
                return SuggestionSnapshot(document=document, suggestion=suggestion, can_write=True, payload=payload)
            suggestion = self._suggestion(connection, user, object_id, str(suggestion_id))
            if self._decision(connection, user, suggestion.suggestion_id) is not None:
                raise OfficeDocumentConflictError("Suggestion already has a decision")
            payload = read_suggestion_payload(self.documents.source_repository, document, suggestion, suggestion)
            decision_id = f"office-suggestion-decision-{uuid4().hex}"
            result_version: OfficeDocumentVersion | None = None
            result_content: dict[str, Any] | None = None
            if command.operation == "accept":
                if (
                    document.current_version_id != suggestion.anchor_version_id
                    or document.current_version_id != command.expected_current_version_id
                ):
                    raise OfficeDocumentConflictError("Document has a newer saved version")
                previous = self._version(connection, user, object_id, suggestion.anchor_version_id)
                original_content = self.document_service._read_content(document, previous)
                if (
                    previous.content_hash != suggestion.anchor_content_hash
                    or derive_review_quote(original_content, suggestion.anchor()) != payload["quote"]
                ):
                    raise OfficeDocumentInvalidContentError("Suggestion anchor is invalid")
                result_content = replace_suggestion_text(
                    original_content, suggestion.anchor(), payload["replacement_text"]
                )
                save = OfficeDocumentSaveCommand(
                    title=document.title,
                    document=result_content,
                    expected_current_version_id=document.current_version_id,
                    mutation_reference=f"office-suggestion-accept:{decision_id}",
                    human_confirmation=True,
                )
                document, result_version, doc_source, doc_receipt = _prepare_version(
                    user=user,
                    document=document,
                    previous_version_id=document.current_version_id,
                    command=save,
                    command_hash=office_document_command_hash(user_context=user, object_id=object_id, command=save),
                    acl_rows=acl_rows,
                )
                if isinstance(self.documents, PgOfficeDocumentRepository):
                    assert connection is not None
                    self.documents._persist_prepared_version(
                        connection, document, result_version, doc_source, doc_receipt
                    )
                else:
                    self.documents.source_repository.add(doc_source)
                    self.documents.receipt_store.append(doc_receipt)
                    self.documents.documents[(user.tenant_id, object_id)] = document
                    self.documents.saved_versions[(user.tenant_id, object_id, result_version.version_id)] = (
                        result_version
                    )
            payload = {
                **payload,
                "operation": command.operation,
                "result_version_id": result_version.version_id if result_version else None,
                "result_content_hash": result_version.content_hash if result_version else None,
            }
            evidence, source, receipt = _prepare_evidence(
                user,
                document,
                suggestion.suggestion_id,
                decision_id,
                payload,
                command_hash,
                command.mutation_reference,
                acl_rows,
            )
            decision = SuggestionDecisionRecord(
                **evidence.model_dump(),
                decision_id=decision_id,
                operation=command.operation,
                result_version_id=result_version.version_id if result_version else None,
                result_content_hash=result_version.content_hash if result_version else None,
            )
            self._store(connection, "text_suggestion_decisions", decision, source, receipt)
            return SuggestionSnapshot(
                document=document,
                suggestion=suggestion,
                decision=decision,
                can_write=True,
                payload=payload,
                result_version=result_version,
                result_content=result_content,
            )
