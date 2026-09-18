from suite.persistence.migration_catalog import get_migration
from suite.storage.retention import load_retention_manifest_policy
from suite.storage.source_objects import SourceLifecycleState, SourceObjectType
from pathlib import Path


def test_office_review_migration_extends_module_without_activating_tenants() -> None:
    migration = get_migration("0084")
    assert migration.module_id == "office_documents" and migration.resource_name == "0084_office_native_reviews.sql"
    sql = migration.sql()
    assert "required_migration_versions = '[\"0083\", \"0084\"]'::jsonb" in sql
    assert "tenant_modules" not in sql and "INSERT INTO collabio.module_catalog" not in sql


def test_comment_sources_already_have_saved_version_retention() -> None:
    policy = load_retention_manifest_policy(Path(__file__).resolve().parents[1] / "docs" / "retention_manifest_policy.json")
    standard = policy.policy("rp-standard")
    assert SourceObjectType.COMMENT in standard.source_object_types
    assert SourceLifecycleState.SAVED_VERSION in standard.lifecycle_states
    assert standard.legal_hold_allowed and standard.audit_required
