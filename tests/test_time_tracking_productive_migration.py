from suite.persistence.migration_catalog import get_migration


def normalized(value: str) -> str:
    return " ".join(value.lower().split())


def test_time_tracking_productive_migration_binds_storage_acl_receipt_and_catalog() -> None:
    migration = get_migration("0060")
    sql = normalized(migration.sql())

    assert migration.module_id == "time_tracking"
    assert "create schema if not exists time_tracking" in sql
    for table in ("entries", "approvals", "entry_creation_receipts"):
        assert f"create table if not exists time_tracking.{table}" in sql
        assert f"alter table time_tracking.{table} force row level security" in sql
        assert f"grant select, insert on table time_tracking.{table} to collabio_authz_admin" in sql
        assert f"grant select on table time_tracking.{table} to collabio_app" in sql
    assert "time_entry_receipts_no_update" in sql
    assert "time_entry_receipts_no_hard_delete" in sql
    assert "work descriptions, payroll values and other business content are forbidden" in sql
    assert "'time_tracking', 'time tracking', '0.1.0'" in sql
    assert "'[\"0060\"]'::jsonb" in sql
