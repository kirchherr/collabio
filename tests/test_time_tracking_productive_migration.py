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


def test_time_approval_decision_migration_is_append_only_and_maker_checker_ready() -> None:
    migration = get_migration("0078")
    sql = normalized(migration.sql())

    assert migration.module_id == "time_tracking"
    assert "create table if not exists time_tracking.approval_decisions" in sql
    assert "unique (tenant_id, approval_object_id, sequence_no)" in sql
    assert "previous_decision_hash" in sql
    assert "confirmation_statement_hash" in sql
    assert "create trigger time_approval_decisions_validate_append" in sql
    assert "invalid time approval decision chain link" in sql
    assert "time approval maker-checker separation required" in sql
    assert "time_approval_decisions_no_update" in sql
    assert "time_approval_decisions_no_hard_delete" in sql
    assert "alter table time_tracking.approval_decisions force row level security" in sql
    assert "grant select, insert on table time_tracking.approval_decisions to collabio_authz_admin" in sql
    assert '\'["0060", "0078"]\'::jsonb' in sql


def test_time_correction_migration_binds_revision_to_resubmission() -> None:
    migration = get_migration("0080")
    sql = normalized(migration.sql())

    assert migration.module_id == "time_tracking"
    assert "create table if not exists time_tracking.entry_corrections" in sql
    assert "unique (tenant_id, entry_object_id, revision_no)" in sql
    assert "correction_request_decision_hash" in sql
    assert "correction_revision_no" in sql
    assert "time_approval_decisions_correction_binding_check" in sql
    assert "create trigger time_entry_corrections_validate_append" in sql
    assert "time approval resubmission is not bound to the latest requested correction" in sql
    assert "time_entry_corrections_no_update" in sql
    assert "time_entry_corrections_no_hard_delete" in sql
    assert "alter table time_tracking.entry_corrections force row level security" in sql
    assert "grant select, insert on table time_tracking.entry_corrections to collabio_authz_admin" in sql
    assert '\'["0060", "0078", "0080"]\'::jsonb' in sql
