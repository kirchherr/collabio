import os
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import psycopg
import pytest

from suite.persistence.migrator import apply_migrations


@dataclass(frozen=True)
class AclDatabase:
    owner_dsn: str
    app_dsn: str


@pytest.fixture(scope="module")
def acl_database() -> AclDatabase:
    owner_dsn = os.environ.get("SUITE_MIGRATION_DATABASE_DSN")
    app_dsn = os.environ.get("SUITE_DATABASE_DSN")
    if not owner_dsn or not app_dsn:
        pytest.skip("PostgreSQL migration and application DSNs are required")
    apply_migrations(owner_dsn)
    return AclDatabase(owner_dsn, app_dsn)


def set_tenant(connection: psycopg.Connection[Any], tenant_id: str) -> None:
    connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))


def insert_article(connection: psycopg.Connection[Any], tenant_id: str, article_id: str, version_id: str) -> None:
    connection.execute(
        """
        INSERT INTO knowledge_base.articles (
            tenant_id, object_id, owner_principal_id, created_by, kms_key_ref, audit_chain_ref,
            source_system, article_key, title, current_version_object_id, current_version_label,
            status, lifecycle_state
        ) VALUES (%s, %s, 'creator', 'creator', 'kms:test', 'audit:kb-acl-test',
                  'native', %s, 'ACL migration test', %s, 'v1', 'draft', 'working')
        """,
        (tenant_id, article_id, article_id, version_id),
    )


def insert_version(
    connection: psycopg.Connection[Any], tenant_id: str, article_id: str, version_id: str, label: str = "v1"
) -> None:
    connection.execute(
        """
        INSERT INTO knowledge_base.article_versions (
            tenant_id, object_id, owner_principal_id, created_by, kms_key_ref, audit_chain_ref,
            source_system, article_object_id, version_label, source_object_version_ref,
            content_hash, version_state, lifecycle_state
        ) VALUES (%s, %s, 'creator', 'creator', 'kms:test', 'audit:kb-acl-test',
                  'native', %s, %s, 'source:acl-test', %s, 'draft', 'working')
        """,
        (tenant_id, version_id, article_id, label, "sha256:" + "a" * 64),
    )


def insert_foreign_acl(connection: psycopg.Connection[Any], tenant_id: str, object_id: str) -> None:
    connection.execute(
        """
        INSERT INTO collabio.object_acl_entries (
            tenant_id, object_id, object_type, acl_subject_type, acl_subject_id,
            permission, acl_version, audit_chain_ref
        ) VALUES (%s, %s, 'document', 'user', 'unrelated-reader', 'read', 1, 'audit:unrelated-object')
        """,
        (tenant_id, object_id),
    )


@pytest.mark.parametrize("target", ["article", "version"])
def test_kb_acl_collision_rolls_back_article_and_creator_grant(acl_database: AclDatabase, target: str) -> None:
    tenant_id = f"tenant-kb-acl-{uuid4().hex}"
    article_id = f"article-{uuid4().hex}"
    version_id = f"version-{uuid4().hex}"
    collision_id = article_id if target == "article" else version_id
    with psycopg.connect(acl_database.owner_dsn) as connection:
        set_tenant(connection, tenant_id)
        insert_foreign_acl(connection, tenant_id, collision_id)

    with (
        pytest.raises(psycopg.errors.RaiseException, match=f"knowledge base {target} identity already exists"),
        psycopg.connect(acl_database.app_dsn) as connection,
    ):
        set_tenant(connection, tenant_id)
        insert_article(connection, tenant_id, article_id, version_id)
        assert connection.execute(
            "SELECT COUNT(*) FROM collabio.object_acl_entries WHERE tenant_id = %s AND object_id = %s",
            (tenant_id, article_id),
        ).fetchone() == (1,)
        insert_version(connection, tenant_id, article_id, version_id)

    with psycopg.connect(acl_database.owner_dsn) as connection:
        set_tenant(connection, tenant_id)
        assert connection.execute(
            "SELECT COUNT(*) FROM knowledge_base.articles WHERE tenant_id = %s", (tenant_id,)
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM knowledge_base.article_versions WHERE tenant_id = %s", (tenant_id,)
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT object_id, object_type, acl_subject_id FROM collabio.object_acl_entries WHERE tenant_id = %s",
            (tenant_id,),
        ).fetchall() == [(collision_id, "document", "unrelated-reader")]


def test_kb_version_cannot_reuse_its_article_identity(acl_database: AclDatabase) -> None:
    tenant_id = f"tenant-kb-acl-{uuid4().hex}"
    article_id = f"article-{uuid4().hex}"
    with (
        pytest.raises(psycopg.errors.RaiseException, match="knowledge base version identity already exists"),
        psycopg.connect(acl_database.app_dsn) as connection,
    ):
        set_tenant(connection, tenant_id)
        insert_article(connection, tenant_id, article_id, article_id)
        insert_version(connection, tenant_id, article_id, article_id)
    with psycopg.connect(acl_database.app_dsn) as connection:
        set_tenant(connection, tenant_id)
        assert connection.execute(
            "SELECT COUNT(*) FROM collabio.object_acl_entries WHERE tenant_id = %s", (tenant_id,)
        ).fetchone() == (0,)


def test_kb_new_version_does_not_restore_revoked_creator_access(acl_database: AclDatabase) -> None:
    tenant_id = f"tenant-kb-acl-{uuid4().hex}"
    article_id = f"article-{uuid4().hex}"
    version_id = f"version-{uuid4().hex}"
    with psycopg.connect(acl_database.app_dsn) as connection:
        set_tenant(connection, tenant_id)
        insert_article(connection, tenant_id, article_id, version_id)
        insert_version(connection, tenant_id, article_id, version_id)
    with psycopg.connect(acl_database.owner_dsn) as connection:
        set_tenant(connection, tenant_id)
        connection.execute(
            """
            UPDATE collabio.object_acl_entries SET status = 'revoked', revoked_at_utc = now()
            WHERE tenant_id = %s AND object_id = %s AND acl_subject_id = 'creator'
            """,
            (tenant_id, article_id),
        )
        connection.execute(
            """
            INSERT INTO collabio.object_acl_entries (
                tenant_id, object_id, object_type, acl_subject_type, acl_subject_id,
                permission, acl_version, audit_chain_ref
            ) VALUES (%s, %s, 'kb.article', 'group', 'remaining-readers', 'read', 2, 'audit:replacement-grant')
            """,
            (tenant_id, article_id),
        )
    new_version_id = f"version-{uuid4().hex}"
    with psycopg.connect(acl_database.app_dsn) as connection:
        set_tenant(connection, tenant_id)
        insert_version(connection, tenant_id, article_id, new_version_id, "v2")
        assert connection.execute(
            """
            SELECT acl_subject_type, acl_subject_id, permission, acl_version
            FROM collabio.object_acl_entries WHERE tenant_id = %s AND object_id = %s AND status = 'active'
            """,
            (tenant_id, new_version_id),
        ).fetchall() == [("group", "remaining-readers", "read", 2)]
        assert connection.execute(
            """
            SELECT status FROM collabio.object_acl_entries
            WHERE tenant_id = %s AND object_id = %s AND acl_subject_id = 'creator'
            """,
            (tenant_id, article_id),
        ).fetchone() == ("revoked",)


def test_kb_version_without_active_article_acl_fails_closed(acl_database: AclDatabase) -> None:
    tenant_id = f"tenant-kb-acl-{uuid4().hex}"
    article_id = f"article-{uuid4().hex}"
    version_id = f"version-{uuid4().hex}"
    with psycopg.connect(acl_database.app_dsn) as connection:
        set_tenant(connection, tenant_id)
        insert_article(connection, tenant_id, article_id, version_id)
    with psycopg.connect(acl_database.owner_dsn) as connection:
        set_tenant(connection, tenant_id)
        connection.execute(
            "UPDATE collabio.object_acl_entries SET status = 'revoked', revoked_at_utc = now() WHERE tenant_id = %s",
            (tenant_id,),
        )
    with (
        pytest.raises(psycopg.errors.RaiseException, match="knowledge base article has no active ACL"),
        psycopg.connect(acl_database.app_dsn) as connection,
    ):
        set_tenant(connection, tenant_id)
        insert_version(connection, tenant_id, article_id, version_id)


@pytest.mark.parametrize("operation", ["insert_acl", "bind_article_acl", "bind_version_acls"])
def test_kb_app_role_has_no_general_acl_mutation_capability(acl_database: AclDatabase, operation: str) -> None:
    tenant_id = f"tenant-kb-acl-{uuid4().hex}"
    with pytest.raises(psycopg.errors.InsufficientPrivilege), psycopg.connect(acl_database.app_dsn) as connection:
        set_tenant(connection, tenant_id)
        if operation == "insert_acl":
            insert_foreign_acl(connection, tenant_id, f"unrelated-{uuid4().hex}")
        elif operation == "bind_article_acl":
            connection.execute("SELECT knowledge_base.bind_article_acl()")
        else:
            connection.execute("SELECT knowledge_base.bind_version_acls()")


@pytest.mark.parametrize("role", ["app", "owner"])
def test_kb_acl_trigger_rejects_other_tenant(acl_database: AclDatabase, role: str) -> None:
    selected_tenant = f"tenant-kb-acl-{uuid4().hex}"
    other_tenant = f"tenant-kb-acl-other-{uuid4().hex}"
    expected_error = psycopg.errors.InsufficientPrivilege if role == "app" else psycopg.errors.RaiseException
    dsn = acl_database.app_dsn if role == "app" else acl_database.owner_dsn
    with pytest.raises(expected_error), psycopg.connect(dsn) as connection:
        set_tenant(connection, selected_tenant)
        insert_article(connection, other_tenant, f"article-{uuid4().hex}", f"version-{uuid4().hex}")
    with psycopg.connect(acl_database.owner_dsn) as connection:
        set_tenant(connection, other_tenant)
        assert connection.execute(
            "SELECT COUNT(*) FROM collabio.object_acl_entries WHERE tenant_id = %s", (other_tenant,)
        ).fetchone() == (0,)
