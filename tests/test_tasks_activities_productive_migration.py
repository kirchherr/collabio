from suite.persistence.migration_catalog import get_migration


def normalized(value: str) -> str:
    return " ".join(value.lower().split())


def test_tasks_activities_productive_migration_binds_storage_acl_receipt_and_catalog() -> None:
    migration = get_migration("0059")
    sql = normalized(migration.sql())

    assert migration.module_id == "tasks_activities"
    assert "create schema if not exists tasks" in sql
    for table in ("items", "activities", "creation_receipts"):
        assert f"create table if not exists tasks.{table}" in sql
        assert f"alter table tasks.{table} force row level security" in sql
        assert f"grant select, insert on table tasks.{table} to collabio_authz_admin" in sql
        assert f"grant select on table tasks.{table} to collabio_app" in sql
    assert "tasks_creation_receipts_no_update" in sql
    assert "tasks_creation_receipts_no_hard_delete" in sql
    assert "task titles, activity summaries and other business field values are forbidden" in sql
    assert "status = 'installed'" in sql
    assert '\'["0050", "0059"]\'::jsonb' in sql
