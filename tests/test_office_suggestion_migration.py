from suite.persistence.migration_catalog import get_migration


def test_office_suggestions_are_additive_without_tenant_activation_or_review_v1_changes() -> None:
    migration = get_migration("0085")
    assert migration.module_id == "office_documents"
    assert migration.resource_name == "0085_office_native_suggestions.sql"
    sql = migration.sql()
    assert 'required_migration_versions = \'["0083", "0084", "0085"]\'::jsonb' in sql
    assert "tenant_modules" not in sql and "ALTER TABLE office.review_" not in sql
    assert "CREATE CONSTRAINT TRIGGER office_versions_require_suggestion_decision" in sql
    assert "DEFERRABLE INITIALLY DEFERRED" in sql
    assert "UNIQUE (tenant_id, result_version_id)" in sql
