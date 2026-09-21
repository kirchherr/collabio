from typing import Any
from uuid import uuid4

import psycopg
import pytest

import office_recovery_proof as proof
from suite.ai_control_plane.models import UserContext
from suite.storage.source_object_storage import InMemorySourceObjectContentStore
from test_office_documents_pg import Database, command, service_for, set_tenant
from test_office_documents_pg import database as database


def seed_principal(connection: psycopg.Connection[Any], tenant: str, user: str, *, active: bool = True) -> None:
    connection.execute(
        "INSERT INTO collabio.tenant_principals (tenant_id, issuer, subject, user_id, audit_chain_ref) "
        "VALUES (%s, 'https://synthetic.example', %s, %s, 'audit:recovery-test')",
        (tenant, user, user),
    )
    connection.execute(
        "INSERT INTO collabio.tenant_principal_memberships "
        "(tenant_id, issuer, subject, status, disabled_at_utc, audit_chain_ref) "
        "VALUES (%s, 'https://synthetic.example', %s, %s, "
        "CASE WHEN %s THEN NULL ELSE now() END, 'audit:recovery-test')",
        (tenant, user, "active" if active else "suspended", active),
    )


@pytest.mark.parametrize("subject_type", ["role", "group"])
def test_recovery_resolves_only_active_memberships_and_current_typed_acl_without_grants(database: Database, monkeypatch: pytest.MonkeyPatch, subject_type: str) -> None:
    tenant = f"tenant-recovery-{uuid4().hex}"
    monkeypatch.setattr(proof, "TENANT_ID", tenant)
    service = service_for(database, InMemorySourceObjectContentStore())
    owner = UserContext(tenant_id=tenant, user_id="owner", role_ids={"office-editor"})
    saved = service.create(user_context=owner, command=command(), write_enabled=True)
    object_id = saved.document.object_id
    with psycopg.connect(database.admin_dsn) as connection:
        set_tenant(connection, tenant)
        seed_principal(connection, tenant, "owner", active=False)
        seed_principal(connection, tenant, "reader")
        seed_principal(connection, tenant, "disabled")
        connection.execute(
            "UPDATE collabio.tenant_principals SET status = 'disabled' "
            "WHERE tenant_id = %s AND user_id = 'disabled'", (tenant,),
        )
        if subject_type == "role":
            connection.execute(
                "INSERT INTO collabio.tenant_roles (tenant_id, role_id, display_name, audit_chain_ref) "
                "VALUES (%s, 'reviewer', 'Reviewer', 'audit:recovery-test')", (tenant,),
            )
            connection.execute(
                "INSERT INTO collabio.tenant_principal_role_assignments "
                "(tenant_id, issuer, subject, role_id, audit_chain_ref) "
                "VALUES (%s, 'https://synthetic.example', 'reader', 'reviewer', 'audit:recovery-test')", (tenant,),
            )
        else:
            connection.execute(
                "INSERT INTO collabio.tenant_groups (tenant_id, group_id, display_name, audit_chain_ref) "
                "VALUES (%s, 'reviewer', 'Reviewer', 'audit:recovery-test')", (tenant,),
            )
            connection.execute(
                "INSERT INTO collabio.tenant_principal_group_memberships "
                "(tenant_id, issuer, subject, group_id, audit_chain_ref) "
                "VALUES (%s, 'https://synthetic.example', 'reader', 'reviewer', 'audit:recovery-test')", (tenant,),
            )
        connection.execute(
            "INSERT INTO collabio.object_acl_entries (tenant_id, object_id, object_type, acl_subject_type, "
            "acl_subject_id, permission, acl_version, audit_chain_ref) "
            "VALUES (%s, %s, 'office.document', %s, 'reviewer', 'read', 1, 'audit:recovery-test')",
            (tenant, object_id, subject_type),
        )
    service.writes_available = False
    users = proof._restored_readers(database.app_dsn)
    assert [user.user_id for user in users] == ["reader"]
    assert users[0].readable_object_ids == {object_id}
    assert users[0].role_ids == ({"reviewer"} if subject_type == "role" else set())
    expected = [{"object_id": object_id, "current_version_id": saved.version.version_id}]
    documents, readers = proof.restored_document_inventory(documents=service, users=users, expected_documents=expected)
    assert [document.object_id for document in documents] == [object_id]
    assert readers[object_id].user_id == "reader"
    with psycopg.connect(database.admin_dsn) as connection:
        set_tenant(connection, tenant)
        rows = connection.execute(
            "SELECT acl_subject_id, permission FROM collabio.object_acl_entries "
            "WHERE tenant_id = %s ORDER BY acl_subject_id", (tenant,),
        ).fetchall()
        assert rows == [("owner", "admin"), ("reviewer", "read")]
        connection.execute(
            "UPDATE collabio.object_acl_entries SET status = 'revoked', revoked_at_utc = now() "
            "WHERE tenant_id = %s AND acl_subject_id = 'reviewer'", (tenant,),
        )
    # Even a previously resolved readable-ID set cannot bypass the current
    # repository ACL lookup on the next page/read.
    with pytest.raises(ValueError, match="complete document inventory"):
        proof.restored_document_inventory(documents=service, users=users, expected_documents=expected)
    refreshed = proof._restored_readers(database.app_dsn)
    assert not refreshed[0].readable_object_ids
