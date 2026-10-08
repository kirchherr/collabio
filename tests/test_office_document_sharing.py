from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import UserContext
from suite.platform.office_document_repository import InMemoryOfficeDocumentRepository
from suite.platform.office_documents import (
    OfficeDocumentConflictError,
    OfficeDocumentCreateCommand,
    OfficeDocumentNotFoundError,
    OfficeDocumentPermissionError,
    OfficeDocumentService,
    OfficeDocumentShareCommand,
    OfficeDocumentShareRequestError,
    OfficeDocumentUnshareCommand,
)
from suite.storage.source_objects import InMemorySourceObjectRepository


def command(reference: str = "create") -> OfficeDocumentCreateCommand:
    return OfficeDocumentCreateCommand(
        title="Shared document",
        document={"type": "doc", "content": [{"type": "paragraph"}]},
        mutation_reference=reference,
        human_confirmation=True,
    )


def sharing_service() -> tuple[OfficeDocumentService, InMemoryOfficeDocumentRepository, UserContext, str]:
    sources = InMemorySourceObjectRepository()
    repository = InMemoryOfficeDocumentRepository(source_repository=sources)
    audit = InMemoryAuditLogger()
    service = OfficeDocumentService(repository=repository, source_repository=sources, audit=audit)
    owner = UserContext(tenant_id="tenant-share", user_id="owner", role_ids={"office-editor"})
    created = service.create(user_context=owner, command=command(), write_enabled=True)
    object_id = created.document.object_id
    owner.readable_object_ids.add(object_id)
    repository.principals[(owner.tenant_id, "reader")] = ("Leserin", "reader@example.test")
    repository.principals[(owner.tenant_id, "editor")] = ("Bearbeiter", None)
    return service, repository, owner, object_id


def test_owner_can_grant_change_and_revoke_with_monotonic_acl_versions_and_audit() -> None:
    service, repository, owner, object_id = sharing_service()
    initial = service.share_state(user_context=owner, object_id=object_id)
    assert initial.acl_version == 1
    assert [(entry.principal_id, entry.permission, entry.is_owner) for entry in initial.entries] == [
        ("owner", "admin", True)
    ]

    expires_at = datetime.now(UTC) + timedelta(days=7)
    granted = service.set_share(
        user_context=owner,
        object_id=object_id,
        write_enabled=True,
        command=OfficeDocumentShareCommand(
            principal_id="reader",
            permission="read",
            expires_at_utc=expires_at,
            expected_acl_version=1,
            mutation_reference="grant-reader",
            human_confirmation=True,
        ),
    )
    assert granted.acl_version == 2
    assert repository.grants[(owner.tenant_id, object_id, "reader")] == "read"
    assert repository.grant_expirations[(owner.tenant_id, object_id, "reader")] == expires_at
    assert next(entry for entry in granted.entries if entry.principal_id == "reader").expires_at_utc is not None

    changed = service.set_share(
        user_context=owner,
        object_id=object_id,
        write_enabled=True,
        command=OfficeDocumentShareCommand(
            principal_id="reader",
            permission="write",
            expires_at_utc=None,
            expected_acl_version=2,
            mutation_reference="promote-reader",
            human_confirmation=True,
        ),
    )
    assert changed.acl_version == 3
    assert repository.grants[(owner.tenant_id, object_id, "reader")] == "write"
    assert (owner.tenant_id, object_id, "reader") not in repository.grant_expirations

    revoked = service.revoke_share(
        user_context=owner,
        object_id=object_id,
        write_enabled=True,
        command=OfficeDocumentUnshareCommand(
            principal_id="reader",
            expected_acl_version=3,
            mutation_reference="revoke-reader",
            human_confirmation=True,
        ),
    )
    assert revoked.acl_version == 4
    assert (owner.tenant_id, object_id, "reader") not in repository.grants
    assert [event.event_type for event in service.audit.events[-4:]] == [
        "office.documents.shares.read",
        "office.documents.shares.changed",
        "office.documents.shares.changed",
        "office.documents.shares.revoked",
    ]


def test_sharing_rejects_non_admin_cross_tenant_unknown_owner_and_stale_changes() -> None:
    service, repository, owner, object_id = sharing_service()
    writer = owner.model_copy(update={"user_id": "editor", "readable_object_ids": {object_id}})
    repository.grants[(owner.tenant_id, object_id, "editor")] = "write"
    with pytest.raises(OfficeDocumentPermissionError):
        service.share_state(user_context=writer, object_id=object_id)
    with pytest.raises(OfficeDocumentShareRequestError):
        service.set_share(
            user_context=owner,
            object_id=object_id,
            write_enabled=True,
            command=OfficeDocumentShareCommand(
                principal_id="missing",
                permission="read",
                expected_acl_version=1,
                mutation_reference="missing",
                human_confirmation=True,
            ),
        )
    with pytest.raises(OfficeDocumentShareRequestError):
        service.revoke_share(
            user_context=owner,
            object_id=object_id,
            write_enabled=True,
            command=OfficeDocumentUnshareCommand(
                principal_id="owner",
                expected_acl_version=1,
                mutation_reference="owner",
                human_confirmation=True,
            ),
        )
    service.set_share(
        user_context=owner,
        object_id=object_id,
        write_enabled=True,
        command=OfficeDocumentShareCommand(
            principal_id="reader",
            permission="read",
            expected_acl_version=1,
            mutation_reference="fresh",
            human_confirmation=True,
        ),
    )
    with pytest.raises(OfficeDocumentConflictError):
        service.set_share(
            user_context=owner,
            object_id=object_id,
            write_enabled=True,
            command=OfficeDocumentShareCommand(
                principal_id="editor",
                permission="read",
                expected_acl_version=1,
                mutation_reference="stale",
                human_confirmation=True,
            ),
        )


def test_migration_uses_definer_functions_append_only_receipts_and_no_direct_app_acl_write() -> None:
    migration = (
        Path(__file__).resolve().parents[1] / "app/suite/persistence/migrations/0087_office_document_sharing.sql"
    )
    sql = migration.read_text()
    normalized = " ".join(sql.lower().split())
    assert "create table office.document_share_decisions" in normalized
    assert "security definer set search_path = pg_catalog" in normalized
    assert "grant execute on function office.set_document_user_grant" in normalized
    assert "grant execute on function office.revoke_document_user_grant" in normalized
    assert "grant insert on collabio.object_acl_entries to collabio_app" not in normalized
    assert "office_document_share_decisions_no_update" in normalized
    assert "office_document_share_decisions_no_delete" in normalized


def test_share_expiration_is_bounded_and_expired_grants_fail_closed() -> None:
    service, repository, owner, object_id = sharing_service()
    with pytest.raises(ValueError, match="within 366 days"):
        OfficeDocumentShareCommand(
            principal_id="reader",
            permission="read",
            expires_at_utc=datetime.now(UTC) + timedelta(days=367),
            expected_acl_version=1,
            mutation_reference="too-long",
            human_confirmation=True,
        )
    reader = owner.model_copy(update={"user_id": "reader", "readable_object_ids": {object_id}})
    repository.grants[(owner.tenant_id, object_id, "reader")] = "read"
    repository.grant_expirations[(owner.tenant_id, object_id, "reader")] = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(OfficeDocumentNotFoundError):
        service.read_content(user_context=reader, object_id=object_id)


def test_expiration_migration_versions_acl_terms_and_replaces_the_grant_function() -> None:
    migration = (
        Path(__file__).resolve().parents[1]
        / "app/suite/persistence/migrations/0088_office_document_share_expiration.sql"
    )
    normalized = " ".join(migration.read_text().lower().split())
    assert "add column expires_at_utc timestamptz" in normalized
    assert "p_expires_at_utc > now() + interval '366 days'" in normalized
    assert "permission, expires_at_utc, acl_version" in normalized
    assert "drop function office.set_document_user_grant" in normalized
    assert "security definer set search_path = pg_catalog" in normalized
