from suite.persistence.migration_catalog import get_migration


def test_office_information_classification_is_versioned_bounded_and_head_bound() -> None:
    migration = get_migration("0086")
    sql = migration.sql()

    assert migration.module_id == "office_documents"
    assert sql.count("ADD COLUMN information_classification") == 2
    assert "'public', 'internal', 'confidential', 'restricted'" in sql
    assert "information_classification = NEW.information_classification" in sql
    assert "GRANT UPDATE (information_classification) ON office.documents TO collabio_app" in sql
    assert 'required_migration_versions = \'["0083", "0084", "0085", "0086"]\'::jsonb' in sql
