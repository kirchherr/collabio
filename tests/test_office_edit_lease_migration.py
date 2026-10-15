from suite.persistence.migration_catalog import get_migration


def test_office_edit_leases_are_tenant_scoped_bounded_and_advisory() -> None:
    migration = get_migration("0090")
    sql = migration.sql()

    assert migration.module_id == "office_documents"
    assert "CREATE TABLE office.document_edit_leases" in sql
    assert "PRIMARY KEY (tenant_id, object_id)" in sql
    assert "FOREIGN KEY (tenant_id, object_id, base_version_id)" in sql
    assert "ALTER TABLE office.document_edit_leases FORCE ROW LEVEL SECURITY" in sql
    assert "tenant_id = collabio.current_tenant_id()" in sql
    assert "office_document_edit_leases_no_delete" in sql
    assert "holder_session_hash text NOT NULL" in sql
    assert "holder_session_hash ~ '^sha256:[a-f0-9]{64}$'" in sql
    assert "GRANT UPDATE (" in sql and "holder_session_hash" in sql
    assert "GRANT SELECT ON office.document_edit_leases TO collabio_worker" in sql
    required = (
        'required_migration_versions = \'["0083", "0084", "0085", "0086", "0087", "0088", "0089", "0090"]\'::jsonb'
    )
    assert required in sql
