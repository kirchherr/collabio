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


def test_task_lifecycle_transition_migration_is_append_only_and_hash_chained() -> None:
    migration = get_migration("0077")
    sql = normalized(migration.sql())

    assert migration.module_id == "tasks_activities"
    assert "create table if not exists tasks.lifecycle_transitions" in sql
    assert "unique (tenant_id, task_object_id, sequence_no)" in sql
    assert "previous_transition_hash" in sql
    assert "confirmation_statement_hash" in sql
    assert "create trigger tasks_lifecycle_transitions_validate_append" in sql
    assert "invalid task lifecycle transition chain link" in sql
    assert "task lifecycle transition activity evidence is inconsistent" in sql
    assert "tasks_lifecycle_transitions_no_update" in sql
    assert "tasks_lifecycle_transitions_no_hard_delete" in sql
    assert "alter table tasks.lifecycle_transitions force row level security" in sql
    assert "grant select, insert on table tasks.lifecycle_transitions to collabio_authz_admin" in sql
    assert '\'["0050", "0059", "0077"]\'::jsonb' in sql


def test_task_amendment_migration_versions_planning_and_assignment_acl() -> None:
    migration = get_migration("0079")
    sql = normalized(migration.sql())

    assert migration.module_id == "tasks_activities"
    assert "create table if not exists tasks.amendments" in sql
    assert "unique (tenant_id, task_object_id, sequence_no)" in sql
    assert "previous_amendment_hash" in sql
    assert "assignment_changed" in sql
    assert "due_date_changed" in sql
    assert "create trigger tasks_amendments_validate_append" in sql
    assert "task amendment did not revoke the prior assignment acl" in sql
    assert "task amendment target assignment acl is missing" in sql
    assert "tasks_amendments_no_update" in sql
    assert "tasks_amendments_no_hard_delete" in sql
    assert "alter table tasks.amendments force row level security" in sql
    assert "grant select, insert on table tasks.amendments to collabio_authz_admin" in sql
    assert '\'["0050", "0059", "0077", "0079"]\'::jsonb' in sql


def test_task_mutation_serialization_migration_unifies_transition_and_amendment_lock() -> None:
    migration = get_migration("0081")
    sql = normalized(migration.sql())

    assert migration.module_id == "tasks_activities"
    assert "create or replace function tasks.acquire_task_mutation_lock()" in sql
    assert "new.tenant_id || ':task:' || new.task_object_id" in sql
    assert ":task-transition:" not in sql
    assert "create trigger tasks_lifecycle_transitions_serialize_task_mutations" in sql
    assert "before insert on tasks.lifecycle_transitions" in sql
    assert "module_version = '0.4.1'" in sql
    assert '\'["0050", "0059", "0077", "0079", "0081"]\'::jsonb' in sql
