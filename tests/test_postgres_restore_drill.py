from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from suite.operations.backend_foundation_completion_gate import (
    build_backend_foundation_completion_gate,
    build_backend_foundation_completion_gate_hash,
    load_backend_foundation_completion_gate,
    persist_backend_foundation_completion_gate,
)
from suite.operations.postgres_restore_drill import (
    AUDIT_APPEND_ONLY_POLICIES_BY_TABLE,
    AUDIT_TABLES,
    CRM_ATOMIC_RECEIPT_POLICIES,
    CRM_ATOMIC_WRITE_TABLES,
    KB_ACL_TABLES,
    KB_ACL_TRIGGER,
    KB_ARTICLE_ACL_TRIGGER,
    MODULE_REGISTRY_TABLES,
    OFFICE_DOCUMENT_TABLES,
    OFFICE_OWNER_COLUMN_PRIVILEGES,
    OFFICE_OWNER_TABLE_PRIVILEGES,
    OFFICE_POLICY_DEFINITIONS,
    OFFICE_REQUIRED_CONSTRAINTS,
    OFFICE_TRIGGER_FUNCTIONS,
    OFFICE_UPDATE_COLUMNS,
    PRODUCTIVITY_PILOT_APPEND_ONLY_POLICIES_BY_TABLE,
    PRODUCTIVITY_PILOT_APPEND_ONLY_TRIGGERS_BY_TABLE,
    PRODUCTIVITY_PILOT_AUTHZ_PRIVILEGES_BY_TABLE,
    PRODUCTIVITY_PILOT_CONTROL_TABLES,
    PRODUCTIVITY_PILOT_START_AUTHORIZATION_APPEND_ONLY_POLICIES_BY_TABLE,
    PRODUCTIVITY_PILOT_START_AUTHORIZATION_APPEND_ONLY_TRIGGERS_BY_TABLE,
    PRODUCTIVITY_PILOT_START_AUTHORIZATION_TABLES,
    PRODUCTIVITY_PILOT_TRAFFIC_SCOPE_APPEND_ONLY_POLICIES_BY_TABLE,
    PRODUCTIVITY_PILOT_TRAFFIC_SCOPE_APPEND_ONLY_TRIGGERS_BY_TABLE,
    PRODUCTIVITY_PILOT_TRAFFIC_SCOPE_TABLES,
    SERVICE_ROLES,
    SOURCE_OBJECT_TABLES,
    TASKS_ACTIVITIES_APPEND_ONLY_POLICIES_BY_TABLE,
    TASKS_ACTIVITIES_APPEND_ONLY_TRIGGERS_BY_TABLE,
    TASKS_ACTIVITIES_WRITE_TABLES,
    TENANT_IAM_TABLES,
    TIME_TRACKING_APPEND_ONLY_POLICIES_BY_TABLE,
    TIME_TRACKING_APPEND_ONLY_TRIGGERS_BY_TABLE,
    TIME_TRACKING_WRITE_TABLES,
    PostgresBackupArtifactEvidence,
    PostgresDatabaseSnapshot,
    PostgresRestoreDrillReport,
    build_postgres_backup_artifact_evidence,
    build_postgres_database_snapshot,
    build_postgres_restore_drill_report,
    build_postgres_restore_drill_report_hash,
    build_postgres_restore_target_isolation_ref_hash,
    discover_postgres_backup_artifact,
    inspect_postgres_database,
)
from suite.persistence.migration_catalog import load_migrations
from suite.persistence.migrator import apply_migrations
from suite.storage.backend_storage_foundation_gate import (
    BackendStorageFoundationGate,
    build_backend_storage_foundation_gate_hash,
)

CHECKED_AT = "2026-07-30T10:00:00Z"


def _office_fixture() -> dict[str, list[dict[str, object]]]:
    migration_sql = "\n".join(
        migration.sql() for migration in load_migrations() if migration.module_id == "office_documents"
    )
    triggers: list[dict[str, object]] = []
    columns: list[dict[str, object]] = [
        {"schema_name": "office", "table_name": table.split(".")[1], "column_name": column}
        for table in sorted(OFFICE_DOCUMENT_TABLES)
        for column in sorted({"tenant_id"} | OFFICE_UPDATE_COLUMNS.get(table, set()))
    ]
    for (table_name, trigger_name), (function_name, timing, security_definer) in OFFICE_TRIGGER_FUNCTIONS.items():
        function_sql = migration_sql.split(f"CREATE FUNCTION office.{function_name}()", 1)[1]
        triggers.append(
            {
                "schema_name": "office",
                "table_name": table_name.split(".")[1],
                "trigger_name": trigger_name,
                "trigger_enabled": "O",
                "trigger_definition": (
                    f"CREATE TRIGGER {trigger_name} {timing} ON {table_name} "
                    f"FOR EACH ROW EXECUTE FUNCTION office.{function_name}()"
                ),
                "function_schema": "office",
                "function_name": function_name,
                "function_owner": "collabio_owner",
                "function_security_definer": security_definer,
                "function_config": ["search_path=pg_catalog"],
                "function_acl": "{collabio_owner=X/collabio_owner}",
                "function_language": "plpgsql",
                "function_identity_arguments": "",
                "function_result": "trigger",
                "function_definition": f"CREATE FUNCTION office.{function_name}(){function_sql.split('$$;', 1)[0]}$$;",
                "function_body": function_sql.split("AS $$", 1)[1].split("$$;", 1)[0],
                "function_public_execute": False,
                "function_runtime_execute": False,
            }
        )
    return {
        "schemas": [{"schema_name": "office"}],
        "tables": [
            {
                "schema_name": "office",
                "table_name": table_name.split(".")[1],
                "relation_kind": "r",
                "table_owner": "collabio_owner",
                "rls_enabled": True,
                "rls_forced": True,
            }
            for table_name in sorted(OFFICE_DOCUMENT_TABLES)
        ],
        "triggers": triggers,
        "columns": columns,
        "policies": [
            {
                "schema_name": "office",
                "table_name": table_name.split(".")[1],
                "policy_name": policy_name,
                "cmd": command,
                "qual": qualifier,
                "with_check": check,
                "permissive": "PERMISSIVE",
                "roles": "{public}",
            }
            for (table_name, policy_name), (command, qualifier, check) in OFFICE_POLICY_DEFINITIONS.items()
        ],
        "constraints": [
            {
                "schema_name": "office",
                "table_name": table_name.split(".")[1],
                "constraint_definition": definition,
            }
            for table_name, definitions in OFFICE_REQUIRED_CONSTRAINTS.items()
            for definition in sorted(definitions)
        ],
        "grants": [
            {
                "schema_name": "office",
                "table_name": table_name.split(".")[1],
                "grantee": grantee,
                "grantor": "collabio_owner",
                "privilege_type": privilege,
                "is_grantable": "YES" if grantee == "collabio_owner" else "NO",
            }
            for table_name in sorted(OFFICE_DOCUMENT_TABLES)
            for grantee, privileges in (
                ("collabio_app", ("SELECT", "INSERT")),
                ("collabio_worker", ("SELECT",)),
                ("collabio_owner", sorted(OFFICE_OWNER_TABLE_PRIVILEGES)),
            )
            for privilege in privileges
        ],
        "column_grants": [
            {
                **column,
                "grantee": "collabio_owner",
                "grantor": "collabio_owner",
                "privilege_type": privilege,
                "is_grantable": "YES",
            }
            for column in columns
            for privilege in sorted(OFFICE_OWNER_COLUMN_PRIVILEGES)
        ] + [
            {
                "schema_name": "office",
                "table_name": table_name.split(".")[1],
                "grantee": "collabio_app",
                "grantor": "collabio_owner",
                "column_name": column,
                "privilege_type": "UPDATE",
                "is_grantable": "NO",
            }
            for table_name, columns in OFFICE_UPDATE_COLUMNS.items()
            for column in sorted(columns)
        ],
    }


def _snapshot(
    *,
    database_hash: str,
    changed_row_count: bool = False,
    tasks_controls: bool = True,
    tasks_transition_trigger: bool = True,
    time_controls: bool = True,
    time_decision_trigger: bool = True,
    pilot_controls: bool = True,
    traffic_scope_controls: bool = True,
    start_authorization_controls: bool = True,
    kb_acl_trigger: bool = True,
    kb_trigger_overrides: dict[str, object] | None = None,
    office_mutate: Callable[[dict[str, list[dict[str, object]]]], None] | None = None,
) -> PostgresDatabaseSnapshot:
    office = _office_fixture()
    if office_mutate:
        office_mutate(office)
    table_names = sorted(
        TENANT_IAM_TABLES
        | KB_ACL_TABLES
        | AUDIT_TABLES
        | MODULE_REGISTRY_TABLES
        | SOURCE_OBJECT_TABLES
        | CRM_ATOMIC_WRITE_TABLES
        | TASKS_ACTIVITIES_WRITE_TABLES
        | TIME_TRACKING_WRITE_TABLES
        | PRODUCTIVITY_PILOT_CONTROL_TABLES
        | PRODUCTIVITY_PILOT_TRAFFIC_SCOPE_TABLES
        | PRODUCTIVITY_PILOT_START_AUTHORIZATION_TABLES
    )
    tables: list[dict[str, object]] = [
        {
            "schema_name": qualified_name.split(".", 1)[0],
            "table_name": qualified_name.split(".", 1)[1],
            "relation_kind": "r",
            "rls_enabled": True,
            "rls_forced": True,
        }
        for qualified_name in table_names
    ]
    tables.extend(office["tables"])
    row_counts = [
        {
            "schema_name": table["schema_name"],
            "table_name": table["table_name"],
            "row_count": int(changed_row_count and index == 0),
        }
        for index, table in enumerate(tables)
    ]
    migrations = [
        {
            "version": migration.version,
            "name": migration.name,
            "module_id": migration.module_id,
            "checksum": migration.checksum(),
            "evidence_refs": list(migration.evidence_refs),
            "blocks_startup": migration.blocks_startup,
        }
        for migration in load_migrations()
    ]
    policies: list[dict[str, object]] = [
        {
            "schema_name": qualified_name.split(".", 1)[0],
            "table_name": qualified_name.split(".", 1)[1],
            "policy_name": policy_name,
        }
        for qualified_name, policy_names in sorted(AUDIT_APPEND_ONLY_POLICIES_BY_TABLE.items())
        for policy_name in sorted(policy_names)
    ]
    policies.extend(office["policies"])
    policies.extend(
        {
            "schema_name": "crm",
            "table_name": "account_onboarding_receipts",
            "policy_name": policy_name,
        }
        for policy_name in sorted(CRM_ATOMIC_RECEIPT_POLICIES)
    )
    policies.extend(
        {
            "schema_name": table_name.split(".", 1)[0],
            "table_name": table_name.split(".", 1)[1],
            "policy_name": policy_name,
        }
        for table_name, policy_names in sorted(TASKS_ACTIVITIES_APPEND_ONLY_POLICIES_BY_TABLE.items())
        for policy_name in sorted(policy_names)
    )
    policies.extend(
        {
            "schema_name": table_name.split(".", 1)[0],
            "table_name": table_name.split(".", 1)[1],
            "policy_name": policy_name,
        }
        for table_name, policy_names in sorted(TIME_TRACKING_APPEND_ONLY_POLICIES_BY_TABLE.items())
        for policy_name in sorted(policy_names)
    )
    policies.extend(
        {
            "schema_name": table_name.split(".", 1)[0],
            "table_name": table_name.split(".", 1)[1],
            "policy_name": policy_name,
        }
        for table_name, policy_names in sorted(PRODUCTIVITY_PILOT_APPEND_ONLY_POLICIES_BY_TABLE.items())
        for policy_name in sorted(policy_names)
    )
    policies.extend(
        {
            "schema_name": table_name.split(".", 1)[0],
            "table_name": table_name.split(".", 1)[1],
            "policy_name": policy_name,
        }
        for table_name, policy_names in sorted(PRODUCTIVITY_PILOT_TRAFFIC_SCOPE_APPEND_ONLY_POLICIES_BY_TABLE.items())
        for policy_name in sorted(policy_names)
    )
    policies.extend(
        {
            "schema_name": table_name.split(".", 1)[0],
            "table_name": table_name.split(".", 1)[1],
            "policy_name": policy_name,
        }
        for table_name, policy_names in sorted(
            PRODUCTIVITY_PILOT_START_AUTHORIZATION_APPEND_ONLY_POLICIES_BY_TABLE.items()
        )
        for policy_name in sorted(policy_names)
    )
    triggers: list[dict[str, object]] = [
        {
            "schema_name": table_name.split(".", 1)[0],
            "table_name": table_name.split(".", 1)[1],
            "trigger_name": trigger_name,
        }
        for table_name, trigger_names in sorted(TASKS_ACTIVITIES_APPEND_ONLY_TRIGGERS_BY_TABLE.items())
        for trigger_name in sorted(trigger_names)
    ]
    triggers.extend(
        {
            "schema_name": table_name.split(".", 1)[0],
            "table_name": table_name.split(".", 1)[1],
            "trigger_name": trigger_name,
        }
        for table_name, trigger_names in sorted(TIME_TRACKING_APPEND_ONLY_TRIGGERS_BY_TABLE.items())
        for trigger_name in sorted(trigger_names)
    )
    if not tasks_transition_trigger:
        triggers = [row for row in triggers if row["trigger_name"] != "tasks_lifecycle_transitions_validate_append"]
    if not time_decision_trigger:
        triggers = [row for row in triggers if row["trigger_name"] != "time_approval_decisions_validate_append"]
    triggers.extend(
        {
            "schema_name": table_name.split(".", 1)[0],
            "table_name": table_name.split(".", 1)[1],
            "trigger_name": trigger_name,
        }
        for table_name, trigger_names in sorted(PRODUCTIVITY_PILOT_APPEND_ONLY_TRIGGERS_BY_TABLE.items())
        for trigger_name in sorted(trigger_names)
    )
    triggers.extend(
        {
            "schema_name": table_name.split(".", 1)[0],
            "table_name": table_name.split(".", 1)[1],
            "trigger_name": trigger_name,
        }
        for table_name, trigger_names in sorted(PRODUCTIVITY_PILOT_TRAFFIC_SCOPE_APPEND_ONLY_TRIGGERS_BY_TABLE.items())
        for trigger_name in sorted(trigger_names)
    )
    triggers.extend(
        {
            "schema_name": table_name.split(".", 1)[0],
            "table_name": table_name.split(".", 1)[1],
            "trigger_name": trigger_name,
        }
        for table_name, trigger_names in sorted(
            PRODUCTIVITY_PILOT_START_AUTHORIZATION_APPEND_ONLY_TRIGGERS_BY_TABLE.items()
        )
        for trigger_name in sorted(trigger_names)
    )
    if kb_acl_trigger:
        migration_sql = next(migration.sql() for migration in load_migrations() if migration.version == "0082")
        for table_name, trigger_name, function_name in (
            ("articles", KB_ARTICLE_ACL_TRIGGER, "bind_article_acl"),
            ("article_versions", KB_ACL_TRIGGER, "bind_version_acls"),
        ):
            function_sql = migration_sql.split(f"CREATE FUNCTION knowledge_base.{function_name}()", 1)[1]
            function_body = function_sql.split("AS $$", 1)[1].split("$$;", 1)[0]
            triggers.append(
                {
                    "schema_name": "knowledge_base",
                    "table_name": table_name,
                    "trigger_name": trigger_name,
                    "trigger_enabled": "O",
                    "trigger_definition": (
                        f"CREATE TRIGGER {trigger_name} AFTER INSERT ON knowledge_base.{table_name} "
                        f"FOR EACH ROW EXECUTE FUNCTION knowledge_base.{function_name}()"
                    ),
                    "function_schema": "knowledge_base",
                    "function_name": function_name,
                    "function_owner": "collabio_owner",
                    "function_security_definer": True,
                    "function_config": ["search_path=pg_catalog"],
                    "function_acl": "{collabio_owner=X/collabio_owner}",
                    "function_language": "plpgsql",
                    "function_identity_arguments": "",
                    "function_result": "trigger",
                    "function_definition": (
                        f"CREATE FUNCTION knowledge_base.{function_name}(){function_sql.split('$$;', 1)[0]}$$;"
                    ),
                    "function_body": function_body,
                    "function_public_execute": False,
                    "function_runtime_execute": False,
                    **(kb_trigger_overrides or {}),
                }
            )
    roles = [{"role_name": role_name, "can_login": True} for role_name in sorted(SERVICE_ROLES)]
    triggers.extend(office["triggers"])
    grants: list[dict[str, object]] = [
        {
            "schema_name": table_name.split(".", 1)[0],
            "table_name": table_name.split(".", 1)[1],
            "grantee": "collabio_audit_writer",
            "privilege_type": privilege,
        }
        for table_name in sorted(AUDIT_TABLES)
        for privilege in ("INSERT", "SELECT")
    ]
    grants.extend(office["grants"])
    grants.extend(
        {
            "schema_name": table_name.split(".", 1)[0],
            "table_name": table_name.split(".", 1)[1],
            "grantee": "collabio_authz_admin",
            "privilege_type": privilege,
        }
        for table_name in sorted(CRM_ATOMIC_WRITE_TABLES)
        for privilege in ("INSERT", "SELECT")
    )
    grants.extend(
        {
            "schema_name": table_name.split(".", 1)[0],
            "table_name": table_name.split(".", 1)[1],
            "grantee": "collabio_authz_admin",
            "privilege_type": privilege,
        }
        for table_name in sorted(TASKS_ACTIVITIES_WRITE_TABLES)
        for privilege in ("INSERT", "SELECT")
    )
    grants.extend(
        {
            "schema_name": table_name.split(".", 1)[0],
            "table_name": table_name.split(".", 1)[1],
            "grantee": "collabio_app",
            "privilege_type": "SELECT",
        }
        for table_name in sorted(TASKS_ACTIVITIES_WRITE_TABLES)
    )
    grants.extend(
        {
            "schema_name": table_name.split(".", 1)[0],
            "table_name": table_name.split(".", 1)[1],
            "grantee": "collabio_authz_admin",
            "privilege_type": privilege,
        }
        for table_name in sorted(TIME_TRACKING_WRITE_TABLES)
        for privilege in ("INSERT", "SELECT")
    )
    grants.extend(
        {
            "schema_name": table_name.split(".", 1)[0],
            "table_name": table_name.split(".", 1)[1],
            "grantee": "collabio_app",
            "privilege_type": "SELECT",
        }
        for table_name in sorted(TIME_TRACKING_WRITE_TABLES)
    )
    grants.extend(
        {
            "schema_name": table_name.split(".", 1)[0],
            "table_name": table_name.split(".", 1)[1],
            "grantee": "collabio_authz_admin",
            "privilege_type": privilege,
        }
        for table_name, privileges in sorted(PRODUCTIVITY_PILOT_AUTHZ_PRIVILEGES_BY_TABLE.items())
        for privilege in sorted(privileges)
    )
    grants.extend(
        {
            "schema_name": table_name.split(".", 1)[0],
            "table_name": table_name.split(".", 1)[1],
            "grantee": "collabio_authz_admin",
            "privilege_type": privilege,
        }
        for table_name in sorted(PRODUCTIVITY_PILOT_TRAFFIC_SCOPE_TABLES)
        for privilege in ("INSERT", "SELECT")
    )
    grants.extend(
        {
            "schema_name": table_name.split(".", 1)[0],
            "table_name": table_name.split(".", 1)[1],
            "grantee": "collabio_authz_admin",
            "privilege_type": privilege,
        }
        for table_name in sorted(PRODUCTIVITY_PILOT_START_AUTHORIZATION_TABLES)
        for privilege in ("INSERT", "SELECT")
    )
    if not pilot_controls:
        grants.append(
            {
                "schema_name": "collabio",
                "table_name": "productivity_pilot_admission_records",
                "grantee": "collabio_app",
                "privilege_type": "INSERT",
            }
        )
    if not traffic_scope_controls:
        grants.append(
            {
                "schema_name": "collabio",
                "table_name": "productivity_pilot_traffic_scope_enforcements",
                "grantee": "collabio_app",
                "privilege_type": "INSERT",
            }
        )
    if not start_authorization_controls:
        grants.append(
            {
                "schema_name": "collabio",
                "table_name": "productivity_pilot_start_authorizations",
                "grantee": "collabio_app",
                "privilege_type": "INSERT",
            }
        )
    if not tasks_controls:
        grants.append(
            {
                "schema_name": "tasks",
                "table_name": "items",
                "grantee": "collabio_app",
                "privilege_type": "INSERT",
            }
        )
    if not time_controls:
        grants.append(
            {
                "schema_name": "time_tracking",
                "table_name": "entries",
                "grantee": "collabio_app",
                "privilege_type": "INSERT",
            }
        )
    return build_postgres_database_snapshot(
        database_ref_hash=database_hash,
        schemas=[{"schema_name": "collabio"}, *office["schemas"]],
        tables=tables,
        columns=office["columns"],
        row_counts=row_counts,
        migrations=migrations,
        policies=policies,
        constraints=office["constraints"],
        indexes=[],
        triggers=triggers,
        extensions=[{"extension_name": "plpgsql", "extension_version": "1.0"}],
        roles=roles,
        grants=grants,
        column_grants=office["column_grants"],
    )


def test_restore_iam_requires_knowledge_base_version_acl_trigger() -> None:
    assert _snapshot(database_hash="sha256:" + "b" * 64).tenant_iam_controls_verified is True
    assert _snapshot(database_hash="sha256:" + "b" * 64, kb_acl_trigger=False).tenant_iam_controls_verified is False


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("trigger_enabled", "D"),
        ("trigger_enabled", "R"),
        ("trigger_definition", "CREATE TRIGGER replaced BEFORE INSERT ON knowledge_base.articles"),
        ("function_schema", "public"),
        ("function_name", "replacement_function"),
        ("function_owner", "collabio_app"),
        ("function_security_definer", False),
        ("function_config", ["search_path=public, pg_catalog"]),
        ("function_config", None),
        ("function_public_execute", True),
        ("function_runtime_execute", True),
        ("function_language", "sql"),
        ("function_identity_arguments", "arg text"),
        ("function_result", "text"),
        ("function_body", "BEGIN RETURN NEW; END"),
        ("function_body", None),
    ),
)
def test_restore_blocks_identically_tampered_kb_trigger_functions(field: str, value: object) -> None:
    source = _snapshot(database_hash="sha256:" + "b" * 64, kb_trigger_overrides={field: value})
    target = _snapshot(database_hash="sha256:" + "c" * 64, kb_trigger_overrides={field: value})
    report = build_postgres_restore_drill_report(
        backup_evidence=_backup_evidence(),
        source_snapshot=source,
        target_snapshot=target,
        target_isolation_ref_hash="sha256:" + "d" * 64,
        checked_at_utc=CHECKED_AT,
    )

    assert report.source_target_state_verified is True
    assert report.tenant_iam_controls_verified is False
    assert report.restore_ready is False
    assert "tenant_iam_controls_not_verified" in report.blocking_reasons


@pytest.mark.parametrize("field", ("function_definition", "function_acl"))
def test_restore_hashes_complete_trigger_function_definition_and_privileges(field: str) -> None:
    source = _snapshot(database_hash="sha256:" + "b" * 64)
    target = _snapshot(database_hash="sha256:" + "c" * 64, kb_trigger_overrides={field: "changed"})
    report = build_postgres_restore_drill_report(
        backup_evidence=_backup_evidence(),
        source_snapshot=source,
        target_snapshot=target,
        target_isolation_ref_hash="sha256:" + "d" * 64,
        checked_at_utc=CHECKED_AT,
    )

    assert source.relation_manifest_hash != target.relation_manifest_hash
    assert report.source_target_state_verified is False
    assert report.restore_ready is False


def test_live_postgres_snapshot_verifies_authored_kb_and_office_integrity_controls() -> None:
    database_dsn = os.environ.get("SUITE_MIGRATION_DATABASE_DSN")
    if not database_dsn:
        pytest.skip("SUITE_MIGRATION_DATABASE_DSN is not configured")
    apply_migrations(database_dsn)

    snapshot = inspect_postgres_database(database_dsn)

    assert snapshot.migration_catalog_verified is True
    assert snapshot.tenant_iam_controls_verified is True
    assert snapshot.office_document_controls_verified is True


@pytest.mark.parametrize("privilege", ("SELECT", "MAINTAIN", "SELECT (tenant_id)"))
def test_live_postgres_snapshot_captures_and_rejects_unknown_office_grantee(privilege: str) -> None:
    database_dsn = os.environ.get("SUITE_MIGRATION_DATABASE_DSN")
    if not database_dsn:
        pytest.skip("SUITE_MIGRATION_DATABASE_DSN is not configured")
    apply_migrations(database_dsn)
    before = inspect_postgres_database(database_dsn)
    assert before.office_document_controls_verified is True
    role_name = f"office_restore_grant_test_{uuid4().hex}"
    with psycopg.connect(database_dsn, autocommit=True) as connection:
        connection.execute(sql.SQL("CREATE ROLE {} NOLOGIN").format(sql.Identifier(role_name)))
        try:
            connection.execute(
                sql.SQL("GRANT {} ON TABLE office.review_events TO {}").format(
                    sql.SQL(privilege), sql.Identifier(role_name)
                )
            )
            tampered = inspect_postgres_database(database_dsn)
            assert tampered.office_document_controls_verified is False
            assert tampered.database_control_manifest_hash != before.database_control_manifest_hash
        finally:
            connection.execute(
                sql.SQL("REVOKE {} ON TABLE office.review_events FROM {}").format(
                    sql.SQL(privilege), sql.Identifier(role_name)
                )
            )
            connection.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name)))
    restored = inspect_postgres_database(database_dsn)
    assert restored.office_document_controls_verified is True
    assert restored.database_control_manifest_hash == before.database_control_manifest_hash


def _office_tamper_report(
    mutate: Callable[[dict[str, list[dict[str, object]]]], None],
) -> PostgresRestoreDrillReport:
    return build_postgres_restore_drill_report(
        backup_evidence=_backup_evidence(),
        source_snapshot=_snapshot(database_hash="sha256:" + "b" * 64, office_mutate=mutate),
        target_snapshot=_snapshot(database_hash="sha256:" + "c" * 64, office_mutate=mutate),
        target_isolation_ref_hash="sha256:" + "d" * 64,
        checked_at_utc=CHECKED_AT,
    )


def _assert_office_tamper_blocked(report: PostgresRestoreDrillReport) -> None:
    assert report.source_target_state_verified is True
    assert report.office_document_controls_verified is False
    assert report.restore_ready is False
    assert "office_document_controls_not_verified" in report.blocking_reasons


def test_restore_requires_native_office_controls() -> None:
    snapshot = _snapshot(database_hash="sha256:" + "b" * 64)
    assert snapshot.office_document_controls_verified is True


@pytest.mark.parametrize(
    ("table_name", "definition"),
    [
        (table, definition)
        for table in ("office.review_threads", "office.review_events")
        for definition in sorted(OFFICE_REQUIRED_CONSTRAINTS[table])
    ],
)
def test_restore_rejects_each_missing_review_identity_state_anchor_or_receipt_constraint(
    table_name: str,
    definition: str,
) -> None:
    def remove(rows: dict[str, list[dict[str, object]]]) -> None:
        rows["constraints"] = [
            row
            for row in rows["constraints"]
            if not (row["table_name"] == table_name.split(".")[1] and row["constraint_definition"] == definition)
        ]

    _assert_office_tamper_blocked(_office_tamper_report(remove))


@pytest.mark.parametrize(
    ("table_name", "definition"),
    [
        (table, definition)
        for table in ("office.review_threads", "office.review_events")
        for definition in sorted(OFFICE_REQUIRED_CONSTRAINTS[table])
        if definition.startswith("CHECK ")
    ],
)
def test_restore_rejects_identical_review_check_drift(table_name: str, definition: str) -> None:
    def weaken(rows: dict[str, list[dict[str, object]]]) -> None:
        constraint = next(
            row
            for row in rows["constraints"]
            if row["table_name"] == table_name.split(".")[1] and row["constraint_definition"] == definition
        )
        constraint["constraint_definition"] = "CHECK (true)"

    _assert_office_tamper_blocked(_office_tamper_report(weaken))


@pytest.mark.parametrize(
    "collection", ("schemas", "tables", "policies", "constraints", "triggers", "grants", "column_grants")
)
def test_restore_rejects_identically_missing_office_controls(collection: str) -> None:
    def remove(rows: dict[str, list[dict[str, object]]]) -> None:
        rows[collection].pop()

    _assert_office_tamper_blocked(_office_tamper_report(remove))


@pytest.mark.parametrize("function_name", tuple(definition[0] for definition in OFFICE_TRIGGER_FUNCTIONS.values()))
@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("trigger_enabled", "D"),
        ("trigger_enabled", "R"),
        ("trigger_definition", "CREATE TRIGGER replacement AFTER DELETE ON office.documents"),
        ("function_schema", "public"),
        ("function_name", "replacement_function"),
        ("function_owner", "collabio_app"),
        ("function_config", ["search_path=public, pg_catalog"]),
        ("function_config", None),
        ("function_acl", "{collabio_owner=X/collabio_owner,unreviewed_role=X/collabio_owner}"),
        ("function_public_execute", True),
        ("function_runtime_execute", True),
        ("function_language", "sql"),
        ("function_identity_arguments", "arg text"),
        ("function_result", "text"),
        ("function_body", "BEGIN RETURN NEW; END"),
        ("function_body", None),
    ),
)
def test_restore_rejects_identical_office_trigger_function_drift(function_name: str, field: str, value: object) -> None:
    def tamper(rows: dict[str, list[dict[str, object]]]) -> None:
        next(row for row in rows["triggers"] if row["function_name"] == function_name)[field] = value

    _assert_office_tamper_blocked(_office_tamper_report(tamper))


@pytest.mark.parametrize("function_name", tuple(definition[0] for definition in OFFICE_TRIGGER_FUNCTIONS.values()))
def test_restore_pins_each_office_function_security_mode(function_name: str) -> None:
    def flip_security(rows: dict[str, list[dict[str, object]]]) -> None:
        function = next(row for row in rows["triggers"] if row["function_name"] == function_name)
        function["function_security_definer"] = not function["function_security_definer"]

    _assert_office_tamper_blocked(_office_tamper_report(flip_security))


@pytest.mark.parametrize("table_name", tuple(table.split(".")[1] for table in sorted(OFFICE_DOCUMENT_TABLES)))
@pytest.mark.parametrize(
    ("field", "value"), (("rls_enabled", False), ("rls_forced", False), ("table_owner", "collabio_app"))
)
def test_restore_rejects_office_table_security_drift(table_name: str, field: str, value: object) -> None:
    def tamper(rows: dict[str, list[dict[str, object]]]) -> None:
        next(row for row in rows["tables"] if row["table_name"] == table_name)[field] = value

    _assert_office_tamper_blocked(_office_tamper_report(tamper))


@pytest.mark.parametrize("policy_name", tuple(policy for _, policy in OFFICE_POLICY_DEFINITIONS))
def test_restore_checks_office_policy_expressions_including_append_only_denials(policy_name: str) -> None:
    def permit_all(rows: dict[str, list[dict[str, object]]]) -> None:
        policy = next(row for row in rows["policies"] if row["policy_name"] == policy_name)
        policy["with_check" if policy["cmd"] == "INSERT" else "qual"] = "true"

    _assert_office_tamper_blocked(_office_tamper_report(permit_all))


@pytest.mark.parametrize("collection", ("triggers", "policies"))
def test_restore_rejects_additional_unreviewed_office_trigger_or_policy(collection: str) -> None:
    def append(rows: dict[str, list[dict[str, object]]]) -> None:
        name = "trigger_name" if collection == "triggers" else "policy_name"
        rows[collection].append({**rows[collection][0], name: "unreviewed_bypass"})

    _assert_office_tamper_blocked(_office_tamper_report(append))


@pytest.mark.parametrize(
    ("collection", "table_name", "grantee", "privilege", "column"),
    (
        ("grants", "documents", "collabio_app", "UPDATE", ""),
        ("grants", "documents", "PUBLIC", "DELETE", ""),
        ("grants", "document_versions", "collabio_app", "UPDATE", ""),
        ("grants", "document_versions", "collabio_worker", "INSERT", ""),
        ("column_grants", "documents", "collabio_app", "UPDATE", "owner_principal_id"),
        ("column_grants", "document_versions", "collabio_app", "UPDATE", "content_hash"),
        ("column_grants", "documents", "PUBLIC", "UPDATE", "title"),
        ("grants", "review_threads", "collabio_app", "UPDATE", ""),
        ("grants", "review_events", "collabio_worker", "INSERT", ""),
        ("grants", "review_events", "collabio_app", "DELETE", ""),
        ("column_grants", "review_threads", "collabio_app", "UPDATE", "anchor_version_id"),
        ("column_grants", "review_events", "collabio_app", "UPDATE", "content_hash"),
        ("grants", "documents", "unreviewed_export_role", "SELECT", ""),
        ("grants", "document_versions", "unreviewed_export_role", "MAINTAIN", ""),
        ("grants", "review_threads", "unreviewed_export_role", "SELECT", ""),
        ("grants", "review_events", "unreviewed_export_role", "SELECT", ""),
        ("column_grants", "review_events", "unreviewed_export_role", "SELECT", "content_hash"),
        ("column_grants", "documents", "unreviewed_export_role", "SELECT", "title"),
    ),
)
def test_restore_rejects_broadened_office_table_and_column_grants(
    collection: str,
    table_name: str,
    grantee: str,
    privilege: str,
    column: str,
) -> None:
    def grant(rows: dict[str, list[dict[str, object]]]) -> None:
        rows[collection].append(
            {
                "schema_name": "office",
                "table_name": table_name,
                "grantee": grantee,
                "grantor": "collabio_owner",
                "privilege_type": privilege,
                "column_name": column,
                "is_grantable": "NO",
            }
        )

    _assert_office_tamper_blocked(_office_tamper_report(grant))


@pytest.mark.parametrize("collection", ("grants", "column_grants"))
@pytest.mark.parametrize(
    ("field", "value"),
    (("is_grantable", "NO"), ("privilege_type", "EXECUTE"), ("grantor", "unreviewed_owner_role")),
)
def test_restore_pins_legitimate_office_owner_grants(collection: str, field: str, value: str) -> None:
    def tamper(rows: dict[str, list[dict[str, object]]]) -> None:
        next(row for row in rows[collection] if row["grantee"] == "collabio_owner")[field] = value

    _assert_office_tamper_blocked(_office_tamper_report(tamper))


@pytest.mark.parametrize("collection", ("grants", "column_grants"))
def test_restore_rejects_missing_office_owner_privilege(collection: str) -> None:
    def remove(rows: dict[str, list[dict[str, object]]]) -> None:
        owner_grant = next(row for row in rows[collection] if row["grantee"] == "collabio_owner")
        rows[collection].remove(owner_grant)

    _assert_office_tamper_blocked(_office_tamper_report(remove))


@pytest.mark.parametrize("collection", ("grants", "column_grants"))
def test_restore_does_not_treat_runtime_grant_options_as_owner_rights(collection: str) -> None:
    def delegate(rows: dict[str, list[dict[str, object]]]) -> None:
        next(row for row in rows[collection] if row["grantee"] == "collabio_app")["is_grantable"] = "YES"

    _assert_office_tamper_blocked(_office_tamper_report(delegate))


def test_restore_hashes_office_column_grants_and_complete_function_definitions() -> None:
    source = _snapshot(database_hash="sha256:" + "b" * 64)

    def alter_definition(rows: dict[str, list[dict[str, object]]]) -> None:
        rows["triggers"][0]["function_definition"] = "changed"
        rows["column_grants"][0]["is_grantable"] = "YES"

    target = _snapshot(database_hash="sha256:" + "c" * 64, office_mutate=alter_definition)
    assert source.relation_manifest_hash != target.relation_manifest_hash
    assert source.database_control_manifest_hash != target.database_control_manifest_hash
    assert source.state_manifest_hash != target.state_manifest_hash


def _backup_evidence() -> PostgresBackupArtifactEvidence:
    return build_postgres_backup_artifact_evidence(
        artifact_ref="collabio.dump",
        backup_sha256="sha256:" + "a" * 64,
        byte_length=512,
        checksum_sidecar_verified=True,
        restore_loader_receipt_verified=True,
    )


def _restore_report(
    *,
    changed_target_row_count: bool = False,
    target_tasks_controls: bool = True,
    target_time_controls: bool = True,
    target_pilot_controls: bool = True,
    target_traffic_scope_controls: bool = True,
    target_start_authorization_controls: bool = True,
) -> PostgresRestoreDrillReport:
    return build_postgres_restore_drill_report(
        backup_evidence=_backup_evidence(),
        source_snapshot=_snapshot(database_hash="sha256:" + "b" * 64),
        target_snapshot=_snapshot(
            database_hash="sha256:" + "c" * 64,
            changed_row_count=changed_target_row_count,
            tasks_controls=target_tasks_controls,
            time_controls=target_time_controls,
            pilot_controls=target_pilot_controls,
            traffic_scope_controls=target_traffic_scope_controls,
            start_authorization_controls=target_start_authorization_controls,
        ),
        target_isolation_ref_hash="sha256:" + "d" * 64,
        checked_at_utc=CHECKED_AT,
    )


def _storage_gate(*, ready: bool = True) -> BackendStorageFoundationGate:
    draft = BackendStorageFoundationGate(
        checked_at_utc=CHECKED_AT,
        runtime_environment="dev",
        tenant_ids=("tenant-demo", "tenant-other"),
        persistent_runtime_report_hash="sha256:" + "1" * 64,
        exact_version_restore_drill_report_hash="sha256:" + "2" * 64,
        source_provider_profile_evidence_hash="sha256:" + "3" * 64,
        source_manifest_count=3,
        restored_object_count=3,
        restart_verified_source_object_count=3,
        runtime_restore_binding_verified=ready,
        persistent_runtime_verified=ready,
        exact_version_restore_verified=ready,
        independent_restore_target_verified=ready,
        tenant_scope_verified=ready,
        metadata_only_evidence_verified=True,
        blocking_reasons=() if ready else ("exact_version_restore_not_ready",),
        api_start_allowed=ready,
        backend_storage_foundation_ready=ready,
        gate_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"gate_hash": build_backend_storage_foundation_gate_hash(draft)})


def test_postgres_restore_drill_verifies_exact_isolated_state() -> None:
    report = _restore_report()

    assert report.restore_ready is True
    assert report.source_target_state_verified is True
    assert report.migration_count == len(load_migrations())
    assert report.tenant_iam_controls_verified is True
    assert report.append_only_audit_controls_verified is True
    assert report.module_registry_controls_verified is True
    assert report.source_object_controls_verified is True
    assert report.content_included is False
    assert report.crm_atomic_write_controls_verified is True
    assert report.tasks_activities_write_controls_verified is True
    assert report.time_tracking_write_controls_verified is True
    assert report.productivity_pilot_admission_controls_verified is True
    assert report.productivity_pilot_traffic_scope_controls_verified is True
    assert report.productivity_pilot_start_authorization_controls_verified is True
    assert report.report_hash == build_postgres_restore_drill_report_hash(report)


def test_postgres_restore_drill_blocks_exact_row_count_drift() -> None:
    report = _restore_report(changed_target_row_count=True)

    assert report.restore_ready is False
    assert report.exact_row_counts_verified is False
    assert "exact_row_counts_mismatch" in report.blocking_reasons
    assert "source_target_state_mismatch" in report.blocking_reasons


def test_postgres_restore_drill_blocks_unsafe_tasks_application_grant() -> None:
    report = _restore_report(target_tasks_controls=False)

    assert report.restore_ready is False
    assert report.tasks_activities_write_controls_verified is False
    assert "tasks_activities_write_controls_not_verified" in report.blocking_reasons


def test_postgres_restore_drill_blocks_unsafe_time_tracking_application_grant() -> None:
    report = _restore_report(target_time_controls=False)

    assert report.restore_ready is False
    assert report.time_tracking_write_controls_verified is False
    assert "time_tracking_write_controls_not_verified" in report.blocking_reasons


def test_postgres_restore_drill_blocks_missing_task_transition_trigger() -> None:
    source = _snapshot(
        database_hash="sha256:" + "1" * 64,
        tasks_transition_trigger=False,
    )

    assert source.tasks_activities_write_controls_verified is False


def test_postgres_restore_drill_blocks_missing_time_decision_trigger() -> None:
    source = _snapshot(
        database_hash="sha256:" + "1" * 64,
        time_decision_trigger=False,
    )

    assert source.time_tracking_write_controls_verified is False


def test_postgres_restore_drill_blocks_unsafe_productivity_pilot_application_grant() -> None:
    report = _restore_report(target_pilot_controls=False)

    assert report.restore_ready is False
    assert report.productivity_pilot_admission_controls_verified is False
    assert "productivity_pilot_admission_controls_not_verified" in report.blocking_reasons


def test_postgres_restore_drill_blocks_unsafe_productivity_pilot_traffic_scope_grant() -> None:
    report = _restore_report(target_traffic_scope_controls=False)

    assert report.restore_ready is False
    assert report.productivity_pilot_traffic_scope_controls_verified is False
    assert "productivity_pilot_traffic_scope_controls_not_verified" in report.blocking_reasons


def test_postgres_restore_drill_blocks_unsafe_productivity_pilot_start_authorization_grant() -> None:
    report = _restore_report(target_start_authorization_controls=False)

    assert report.restore_ready is False
    assert report.productivity_pilot_start_authorization_controls_verified is False
    assert "productivity_pilot_start_authorization_controls_not_verified" in report.blocking_reasons


def test_postgres_restore_target_must_be_independent() -> None:
    dsn = "postgresql://owner:secret@postgres:5432/collabio"

    with pytest.raises(ValueError, match="must be isolated"):
        build_postgres_restore_target_isolation_ref_hash(source_dsn=dsn, target_dsn=dsn)


def test_backup_artifact_evidence_binds_sidecar_and_loader_receipt(tmp_path: Path) -> None:
    artifact = tmp_path / "collabio-restore.dump"
    artifact.write_bytes(b"metadata-only-test-dump")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    Path(str(artifact) + ".sha256").write_text(f"{digest}  /backups/{artifact.name}\n", encoding="ascii")
    receipt = tmp_path / "postgres-restore-receipt.sha256"
    receipt.write_text(f"sha256:{digest}\n", encoding="ascii")

    evidence = discover_postgres_backup_artifact(
        backup_directory=tmp_path,
        restore_receipt_path=receipt,
    )

    assert evidence.checksum_sidecar_verified is True
    assert evidence.restore_loader_receipt_verified is True
    assert evidence.catalog_preflight_verified is True


def test_backend_foundation_completion_gate_binds_database_and_object_recovery() -> None:
    gate = build_backend_foundation_completion_gate(
        postgres_restore_report=_restore_report(),
        storage_gate=_storage_gate(),
    )

    assert gate.backend_foundation_complete is True
    assert gate.api_start_allowed is True
    assert gate.tenant_iam_verified is True
    assert gate.office_document_controls_verified is True
    assert gate.postgres_backup_restore_verified is True
    assert gate.exact_version_object_restore_verified is True
    assert gate.crm_atomic_write_controls_verified is True
    assert gate.tasks_activities_write_controls_verified is True
    assert gate.time_tracking_write_controls_verified is True
    assert gate.productivity_pilot_admission_controls_verified is True
    assert gate.productivity_pilot_traffic_scope_controls_verified is True
    assert gate.productivity_pilot_start_authorization_controls_verified is True
    assert gate.productive_business_write_controls_verified is True
    assert gate.content_included is False
    assert gate.gate_hash == build_backend_foundation_completion_gate_hash(gate)


def test_backend_foundation_completion_gate_blocks_missing_productive_write_control() -> None:
    gate = build_backend_foundation_completion_gate(
        postgres_restore_report=_restore_report(target_time_controls=False),
        storage_gate=_storage_gate(),
    )

    assert gate.backend_foundation_complete is False
    assert gate.productive_business_write_controls_verified is False
    assert "time_tracking_write_controls_not_verified" in gate.blocking_reasons
    assert "productive_business_write_controls_not_verified" in gate.blocking_reasons


def test_backend_foundation_gate_independently_requires_office_integrity_even_when_restore_ready_is_claimed() -> None:
    report = _restore_report().model_copy(update={"office_document_controls_verified": False})
    report = report.model_copy(update={"report_hash": build_postgres_restore_drill_report_hash(report)})
    assert report.restore_ready is True
    gate = build_backend_foundation_completion_gate(postgres_restore_report=report, storage_gate=_storage_gate())
    assert gate.office_document_controls_verified is False
    assert gate.backend_foundation_complete is False
    assert gate.api_start_allowed is False
    assert "office_document_controls_not_verified" in gate.blocking_reasons


def test_backend_foundation_completion_gate_report_round_trip_and_tamper_detection(tmp_path: Path) -> None:
    gate = build_backend_foundation_completion_gate(
        postgres_restore_report=_restore_report(),
        storage_gate=_storage_gate(),
    )
    report_path = tmp_path / "backend-gate.json"

    persist_backend_foundation_completion_gate(gate=gate, report_path=report_path)

    assert load_backend_foundation_completion_gate(report_path) == gate
    report_path.write_text(
        report_path.read_text(encoding="utf-8").replace(
            f'"migration_count":{gate.migration_count}',
            f'"migration_count":{gate.migration_count + 1}',
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="hash is invalid"):
        load_backend_foundation_completion_gate(report_path)


def test_backend_foundation_completion_gate_blocks_failed_storage_recovery() -> None:
    gate = build_backend_foundation_completion_gate(
        postgres_restore_report=_restore_report(),
        storage_gate=_storage_gate(ready=False),
    )

    assert gate.backend_foundation_complete is False
    assert "storage_foundation_not_ready" in gate.blocking_reasons
    assert "exact_version_object_restore_not_verified" in gate.blocking_reasons


def test_compose_exposes_isolated_postgres_restore_and_completion_gate() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "\n  postgres-restore:\n" in compose
    assert "\n  postgres-backup-restore-loader:\n" in compose
    assert "\n  postgres-restore-drill:\n" in compose
    assert "\n  backend-foundation-completion-gate:\n" in compose
    assert "\n  business-backend-release-gate:\n" in compose
    assert "\n  productivity-pilot-preflight-gate:\n" in compose
    assert "dropdb -h postgres-restore" in compose
    assert "pg_restore -h postgres-restore" in compose
    assert "--exit-on-error" in compose
    assert "postgres18_restore_data:/var/lib/postgresql" in compose
    assert "python -m suite.operations.postgres_restore_drill" in compose
    assert "python -m suite.operations.backend_foundation_completion_gate" in compose
    assert "python -m suite.operations.business_backend_release_gate" in compose
    assert "python -m suite.operations.productivity_pilot_preflight" in compose
    assert "SUITE_BACKEND_FOUNDATION_GATE_REPORT_PATH: /backups/backend-foundation-completion-gate.json" in compose
    assert "SUITE_BUSINESS_BACKEND_RELEASE_GATE_REPORT_PATH: /backups/business-backend-release-gate.json" in compose
