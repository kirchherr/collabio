from suite.persistence.migration_catalog import get_migration


def normalized(value: str) -> str:
    return " ".join(value.lower().split())


def test_crm_atomic_onboarding_migration_binds_rls_acl_and_append_only_receipt() -> None:
    migration = get_migration("0057")
    sql = normalized(migration.sql())

    assert migration.module_id == "crm_erp"
    assert "create table if not exists crm.account_onboarding_receipts" in sql
    assert "object_manifest jsonb" in sql
    assert "acl_manifest jsonb" in sql
    assert "business field values and note bodies are forbidden" in sql
    assert "alter table crm.account_onboarding_receipts force row level security" in sql
    assert "create policy crm_account_onboarding_receipts_no_update" in sql
    assert "create policy crm_account_onboarding_receipts_no_hard_delete" in sql
    for table in ("accounts", "contacts", "activities", "notes", "account_onboarding_receipts"):
        assert f"grant select, insert on table crm.{table} to collabio_authz_admin" in sql
    assert "grant insert on table collabio.object_acl_entries to collabio_app" not in sql
    assert '"0057"' in migration.sql()


def test_upgrade_reconciliation_adds_only_stored_checksum_bound_crm_evidence() -> None:
    migration = get_migration("0058")
    sql = normalized(migration.sql())

    assert migration.module_id == "core"
    assert "from collabio.schema_migrations" in sql
    assert "where version = '0057'" in sql
    assert "and module_id = 'crm_erp'" in sql
    assert "update collabio.tenant_modules as tenant_module" in sql
    assert "jsonb_array_elements(migration_evidence)" in sql
    assert "migration_evidence || jsonb_build_array(migration_entry.evidence)" in sql
    assert "set migration_evidence =" in sql
    assert "status =" not in sql
    assert "enabled_features =" not in sql
    assert "changed_by =" not in sql
    assert "audit_chain_ref =" not in sql
