from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from typing import Any

import psycopg
import pytest

import suite.platform.office_suggestion_repository as suggestion_repository
from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.platform.office_api import build_office_suggestion_service
from suite.platform.office_documents import OfficeDocumentConflictError, OfficeDocumentPermissionError, OfficeDocumentSaveCommand
from suite.platform.office_suggestions import SuggestionCreateCommand
from suite.storage.source_object_storage import InMemorySourceObjectContentStore, SourceObjectStorageError
from test_office_documents_pg import Database, command, editor, service_for, set_tenant
from test_office_documents_pg import database as database
from test_office_suggestions import decision_command, paragraph_text


def prepared(database: Database) -> tuple[Any, ...]:
    store = InMemorySourceObjectContentStore()
    docs = service_for(database, store)
    user = editor()
    saved = docs.create(user_context=user, command=command(text="Private café 😀 document"), write_enabled=True)
    user.readable_object_ids.add(saved.document.object_id)
    suggestions = build_office_suggestion_service(document_service=docs, audit=InMemoryAuditLogger())
    create = SuggestionCreateCommand.model_validate({
        "anchor_version_id": saved.version.version_id, "expected_current_version_id": saved.version.version_id,
        "anchor": {"from": 9, "to": 13}, "replacement_text": "changed", "mutation_reference": "create-suggestion",
        "human_confirmation": True,
    })
    created = suggestions.mutate(user_context=user, object_id=saved.document.object_id, command=create, write_enabled=True)
    return store, docs, user, saved, suggestions, created


def counts(database: Database, user: Any) -> tuple[int, ...]:
    with psycopg.connect(database.app_dsn) as connection:
        set_tenant(connection, user.tenant_id)
        rows = []
        for table in ("office.document_versions", "office.text_suggestions", "office.text_suggestion_decisions",
                      "collabio.source_object_metadata", "collabio.source_object_write_receipts"):
            result = connection.execute(f"SELECT count(*) FROM {table} WHERE tenant_id=%s", (user.tenant_id,)).fetchone()
            assert result is not None
            rows.append(int(result[0]))
        return tuple(rows)


def test_pg_suggestion_accept_is_one_reopenable_exact_version_and_decision(database: Database) -> None:
    store, docs, user, saved, suggestions, created = prepared(database)
    assert counts(database, user) == (1, 1, 0, 2, 2)
    accept = decision_command("accept", saved.version.version_id)
    result = suggestions.mutate(user_context=user, object_id=saved.document.object_id,
        suggestion_id=created.suggestion.suggestion_id, command=accept, write_enabled=True)
    assert counts(database, user) == (2, 1, 1, 4, 4)
    assert result.document_result.version.previous_version_id == saved.version.version_id
    assert paragraph_text(result.document_result.content) == "Private changed 😀 document"
    restored = build_office_suggestion_service(document_service=service_for(database, store), audit=InMemoryAuditLogger())
    replay = restored.mutate(user_context=user, object_id=saved.document.object_id,
        suggestion_id=created.suggestion.suggestion_id, command=accept, write_enabled=True)
    assert replay.replayed and replay.suggestion.result_version_id == result.suggestion.result_version_id
    assert counts(database, user) == (2, 1, 1, 4, 4)
    assert docs.read_content(user_context=user, object_id=saved.document.object_id).version.version_id == result.suggestion.result_version_id
    with psycopg.connect(database.admin_dsn) as connection:
        set_tenant(connection, user.tenant_id)
        connection.execute("UPDATE collabio.object_acl_entries SET permission='read' WHERE tenant_id=%s AND object_id=%s",
                           (user.tenant_id, saved.document.object_id))
    with pytest.raises(OfficeDocumentPermissionError):
        restored.mutate(user_context=user, object_id=saved.document.object_id,
            suggestion_id=created.suggestion.suggestion_id, command=accept, write_enabled=True)


def test_pg_suggestion_racing_accept_and_reject_have_only_one_result_and_no_loser_put(database: Database) -> None:
    store, _, user, saved, _, created = prepared(database)
    barrier = Barrier(2)
    def decide(operation: str) -> str:
        service = build_office_suggestion_service(document_service=service_for(database, store), audit=InMemoryAuditLogger())
        barrier.wait(timeout=10)
        try:
            service.mutate(user_context=user, object_id=saved.document.object_id,
                suggestion_id=created.suggestion.suggestion_id,
                command=decision_command(operation, saved.version.version_id, operation), write_enabled=True)
        except OfficeDocumentConflictError:
            return "conflict"
        return operation
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(decide, ("accept", "reject")))
    assert results.count("conflict") == 1
    expected = (2, 1, 1, 4, 4) if "accept" in results else (1, 1, 1, 3, 3)
    assert counts(database, user) == expected
    assert len(store.list_stored_objects(tenant_id=user.tenant_id)) == expected[-1]


def test_pg_suggestion_stale_accept_has_no_put_and_reject_preserves_head(database: Database) -> None:
    store, docs, user, saved, service, created = prepared(database)
    latest = docs.save(user_context=user, object_id=saved.document.object_id, write_enabled=True,
        command=OfficeDocumentSaveCommand(**command("later", "later content").model_dump(),
            expected_current_version_id=saved.version.version_id))
    before = counts(database, user)
    with pytest.raises(OfficeDocumentConflictError):
        service.mutate(user_context=user, object_id=saved.document.object_id,
            suggestion_id=created.suggestion.suggestion_id, command=decision_command("accept", latest.version.version_id), write_enabled=True)
    assert counts(database, user) == before
    assert len(store.list_stored_objects(tenant_id=user.tenant_id)) == before[-1]
    rejected = service.mutate(user_context=user, object_id=saved.document.object_id,
        suggestion_id=created.suggestion.suggestion_id, command=decision_command("reject", latest.version.version_id), write_enabled=True)
    assert rejected.suggestion.status == "rejected" and rejected.current_version_id == latest.version.version_id


@pytest.mark.parametrize("fail_at", (1, 2))
def test_pg_suggestion_put_failure_rolls_back_both_heads_and_receipts(
    database: Database, monkeypatch: pytest.MonkeyPatch, fail_at: int,
) -> None:
    store, docs, user, saved, service, created = prepared(database)
    original = store.put
    calls = 0
    def fail(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if calls == fail_at:
            raise SourceObjectStorageError("Synthetic private storage failure")
        return original(*args, **kwargs)
    monkeypatch.setattr(store, "put", fail)
    with pytest.raises(SourceObjectStorageError):
        service.mutate(user_context=user, object_id=saved.document.object_id,
            suggestion_id=created.suggestion.suggestion_id, command=decision_command("accept", saved.version.version_id), write_enabled=True)
    assert counts(database, user) == (1, 1, 0, 2, 2)
    assert docs.read_content(user_context=user, object_id=saved.document.object_id).version.version_id == saved.version.version_id
    recovery = docs.source_repository.build_content_recovery_evidence(tenant_id=user.tenant_id, restore_drill_report_hash="sha256:" + "a" * 64)
    assert recovery.orphaned_content_count == fail_at - 1


def test_pg_suggestion_post_put_database_failure_rolls_back_both_records_and_detects_two_orphans(
    database: Database, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, docs, user, saved, service, created = prepared(database)
    original = suggestion_repository._prepare_evidence
    def corrupt(*args: Any, **kwargs: Any) -> Any:
        evidence, source, receipt = original(*args, **kwargs)
        return evidence.model_copy(update={"content_hash": "sha256:" + "f" * 64}), source, receipt
    monkeypatch.setattr(suggestion_repository, "_prepare_evidence", corrupt)
    with pytest.raises(psycopg.Error):
        service.mutate(user_context=user, object_id=saved.document.object_id,
            suggestion_id=created.suggestion.suggestion_id, command=decision_command("accept", saved.version.version_id), write_enabled=True)
    assert counts(database, user) == (1, 1, 0, 2, 2)
    recovery = docs.source_repository.build_content_recovery_evidence(tenant_id=user.tenant_id, restore_drill_report_hash="sha256:" + "a" * 64)
    assert recovery.orphaned_content_count == 2 and not recovery.api_wiring_allowed


def test_pg_suggestion_rls_append_only_and_deferred_acceptance_binding(database: Database) -> None:
    _, docs, user, saved, _, _ = prepared(database)
    with psycopg.connect(database.app_dsn) as connection:
        set_tenant(connection, "foreign")
        assert connection.execute("SELECT count(*) FROM office.text_suggestions").fetchone() == (0,)
        set_tenant(connection, user.tenant_id)
        for table in ("text_suggestions", "text_suggestion_decisions"):
            for operation in (f"DELETE FROM office.{table}", f"UPDATE office.{table} SET created_by='forged'"):
                with pytest.raises(psycopg.Error), connection.transaction():
                    connection.execute(operation)
    with pytest.raises(psycopg.Error):
        docs.save(user_context=user, object_id=saved.document.object_id, write_enabled=True,
            command=OfficeDocumentSaveCommand(
                **command("office-suggestion-accept:office-suggestion-decision-" + "a" * 32, "forged").model_dump(),
                expected_current_version_id=saved.version.version_id,
            ))
    assert counts(database, user) == (1, 1, 0, 2, 2)
