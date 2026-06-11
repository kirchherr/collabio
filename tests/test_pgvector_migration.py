import re
from typing import Any

import pytest

from suite.ai_control_plane.models import DataClass
from suite.persistence.migration_catalog import get_migration, load_migrations
from suite.rag.models import ChunkMetadata, VectorEmbeddingRecord, VectorLifecycleState


def normalized(sql: str) -> str:
    return re.sub(r"\s+", " ", sql.lower())


def table_body(sql: str, table_name: str) -> str:
    pattern = rf"create table if not exists {re.escape(table_name)}\s*\((.*?)\);"
    match = re.search(pattern, sql, flags=re.IGNORECASE | re.DOTALL)
    assert match is not None, f"{table_name} table definition not found"
    return match.group(1).lower()


def pgvector_sql() -> str:
    return get_migration("0001").sql()


def test_migration_catalog_is_ordered_and_loads_pgvector_schema() -> None:
    migrations = load_migrations()

    assert [migration.version for migration in migrations] == [
        "0001",
        "0002",
        "0003",
        "0004",
        "0005",
        "0006",
        "0007",
        "0008",
        "0009",
        "0010",
    ]
    assert migrations[0].version == "0001"
    assert migrations[0].name == "pgvector_embeddings"
    assert "CREATE EXTENSION IF NOT EXISTS vector;" in migrations[0].sql()


def test_pgvector_embedding_schema_declares_required_compliance_metadata() -> None:
    body = table_body(pgvector_sql(), "collabio.vector_embedding_chunks")

    for column in [
        "tenant_id",
        "source_object_id",
        "source_object_type",
        "source_version_id",
        "chunk_id",
        "classification",
        "retention_policy_id",
        "legal_hold_state",
        "acl_hash",
        "acl_version",
        "embedding_model_id",
        "embedding_model_version",
        "embedding_dimensions",
        "embedding",
        "content_hash",
        "content_byte_length",
        "lifecycle_state",
        "audit_event_id",
    ]:
        assert re.search(rf"\b{column}\b", body), f"{column} missing from vector embedding schema"

    for data_class in DataClass:
        assert f"'{data_class.value}'" in body


def test_pgvector_embedding_schema_enforces_lifecycle_and_dimension_guardrails() -> None:
    sql = normalized(pgvector_sql())

    for state in VectorLifecycleState:
        assert f"'{state.value}'" in sql

    assert "check (embedding_dimensions = vector_dims(embedding))" in sql
    assert "lifecycle_state <> 'restricted' or restricted_at_utc is not null" in sql
    assert "lifecycle_state <> 'deleted' or deleted_at_utc is not null" in sql
    assert "lifecycle_state <> 'cryptoshredded' or cryptoshredded_at_utc is not null" in sql
    assert "source text must be fetched only after authoritative acl validation" in sql


def test_pgvector_embedding_schema_enables_rls_with_null_safe_tenant_setting() -> None:
    sql = normalized(pgvector_sql())

    assert "nullif(current_setting('app.tenant_id', true), '')" in sql
    assert "alter table collabio.vector_embedding_chunks enable row level security" in sql
    assert "alter table collabio.vector_embedding_chunks force row level security" in sql
    assert "for select" in sql
    assert "for insert" in sql
    assert "for update" in sql
    assert "for delete" in sql
    assert "tenant_id = collabio.current_tenant_id()" in sql
    assert "lifecycle_state = 'active'" in sql
    assert "create policy vector_embedding_chunks_no_hard_delete" in sql
    assert "using (false)" in sql
    assert "grant select, insert, update, delete on table collabio.vector_embedding_chunks to collabio_app" in sql


def test_pgvector_role_policy_migrations_split_app_and_worker_permissions() -> None:
    worker_sql = normalized(get_migration("0002").sql())
    insert_policy_sql = normalized(get_migration("0003").sql())
    update_policy_sql = normalized(get_migration("0004").sql())
    worker_write_sql = normalized(get_migration("0005").sql())

    assert "create role collabio_worker login password" in worker_sql
    assert "grant select, update on table collabio.vector_embedding_chunks to collabio_worker" in worker_sql
    assert "create policy vector_embedding_chunks_worker_select" in worker_sql
    assert "to collabio_worker using (tenant_id = collabio.current_tenant_id())" in worker_sql
    assert "drop policy if exists vector_embedding_chunks_tenant_insert" in insert_policy_sql
    assert "for insert to collabio_app" in insert_policy_sql
    assert "drop policy if exists vector_embedding_chunks_tenant_update" in update_policy_sql
    assert "for update to collabio_app" in update_policy_sql
    assert "lifecycle_state in ('active', 'reindex_pending')" in update_policy_sql
    assert (
        "revoke insert, update, delete on table collabio.vector_embedding_chunks from collabio_app" in worker_write_sql
    )
    assert (
        "grant select, insert, update on table collabio.vector_embedding_chunks to collabio_worker" in worker_write_sql
    )
    assert "create policy vector_embedding_chunks_worker_insert" in worker_write_sql
    assert "drop policy if exists vector_embedding_chunks_tenant_update" in worker_write_sql


def test_vector_metadata_guardrail_migration_validates_acl_and_source_type() -> None:
    sql = normalized(get_migration("0006").sql())

    assert "vector_embedding_chunks_source_object_type_check" in sql
    assert "'procedure_doc'" in sql
    assert "vector_embedding_chunks_acl_metadata_check" in sql
    assert "acl_version >= 1" in sql
    assert "authoritative acl snapshot" in sql


def test_platform_module_registry_migration_declares_lifecycle_tables_and_rls() -> None:
    sql = normalized(get_migration("0007").sql())
    module_catalog_body = table_body(get_migration("0007").sql(), "collabio.module_catalog")
    tenant_modules_body = table_body(get_migration("0007").sql(), "collabio.tenant_modules")

    for column in [
        "module_id",
        "display_name",
        "module_version",
        "module_kind",
        "status",
        "manifest_hash",
        "schema_version",
    ]:
        assert re.search(rf"\b{column}\b", module_catalog_body), f"{column} missing from module catalog schema"

    for column in [
        "tenant_id",
        "module_id",
        "status",
        "enabled_features",
        "policy_snapshot_hash",
        "changed_by",
        "audit_chain_ref",
        "schema_version",
    ]:
        assert re.search(rf"\b{column}\b", tenant_modules_body), f"{column} missing from tenant module schema"

    assert "'enabled'" in tenant_modules_body
    assert "'disabled'" in tenant_modules_body
    assert "'decommission_blocked'" in tenant_modules_body
    assert "status <> 'enabled' or enabled_at_utc is not null" in sql
    assert "alter table collabio.tenant_modules enable row level security" in sql
    assert "alter table collabio.tenant_modules force row level security" in sql
    assert "tenant_id = collabio.current_tenant_id()" in sql
    assert "create policy tenant_modules_no_hard_delete" in sql
    assert "using (false)" in sql


def test_tenant_module_decommission_evidence_migration_requires_evidence_refs() -> None:
    sql = normalized(get_migration("0008").sql())

    assert "add column if not exists decommission_evidence_refs jsonb" in sql
    assert "tenant_modules_decommission_evidence_json_check" in sql
    assert "tenant_modules_decommission_request_evidence_check" in sql
    assert "decommission_evidence_refs ? 'retention_evaluation_ref'" in sql
    assert "decommission_evidence_refs ? 'legal_hold_check_ref'" in sql
    assert "decommission_evidence_refs ? 'export_archive_decision_ref'" in sql
    assert "decommission_evidence_refs ? 'audit_evidence_ref'" in sql
    assert "decommission_evidence_refs ? 'backup_restore_evidence_ref'" in sql
    assert "tenant_modules_decommission_request_features_check" in sql
    assert "status <> 'decommission_requested'" in sql
    assert "enabled_features @? '$.* ? (@ == true)'" in sql


def test_tenant_module_decommission_completion_migration_requires_final_evidence() -> None:
    sql = normalized(get_migration("0009").sql())

    assert "add column if not exists decommission_blocked_at_utc timestamptz" in sql
    assert "tenant_modules_decommission_blocked_timestamp_check" in sql
    assert "tenant_modules_decommission_after_request_check" in sql
    assert "tenant_modules_decommission_blocked_evidence_check" in sql
    assert "decommission_evidence_refs ? 'blocker_report_ref'" in sql
    assert "decommission_evidence_refs ? 'remediation_plan_ref'" in sql
    assert "tenant_modules_decommission_completed_evidence_check" in sql
    assert "decommission_evidence_refs ? 'final_retention_disposition_ref'" in sql
    assert "decommission_evidence_refs ? 'final_legal_hold_clearance_ref'" in sql
    assert "decommission_evidence_refs ? 'final_export_archive_manifest_ref'" in sql
    assert "decommission_evidence_refs ? 'final_audit_closure_ref'" in sql
    assert "decommission_evidence_refs ? 'final_backup_disposition_ref'" in sql
    assert "decommission_evidence_refs ? 'final_data_disposition_ref'" in sql
    assert "status not in ('decommission_requested', 'decommission_blocked', 'decommissioned')" in sql


def test_tenant_module_decommission_cancel_reopen_migration_requires_audit_evidence() -> None:
    sql = normalized(get_migration("0010").sql())

    assert "add column if not exists decommission_cancelled_at_utc timestamptz" in sql
    assert "add column if not exists decommission_reopened_at_utc timestamptz" in sql
    assert "tenant_modules_decommission_cancel_evidence_check" in sql
    assert "decommission_evidence_refs ? 'cancel_approval_ref'" in sql
    assert "decommission_evidence_refs ? 'cancel_audit_evidence_ref'" in sql
    assert "tenant_modules_decommission_cancel_disabled_features_check" in sql
    assert "tenant_modules_decommission_reopen_evidence_check" in sql
    assert "decommission_blocked_at_utc is not null" in sql
    assert "decommission_evidence_refs ? 'reopen_approval_ref'" in sql
    assert "decommission_evidence_refs ? 'blocker_remediation_evidence_ref'" in sql
    assert "decommission_evidence_refs ? 'reopen_audit_evidence_ref'" in sql


def test_pgvector_embedding_schema_does_not_store_source_text_or_generated_answers() -> None:
    body = table_body(pgvector_sql(), "collabio.vector_embedding_chunks")

    forbidden_columns = ["source_text", "chunk_text", "document_text", "prompt_text", "answer_text", "output_text"]
    for column in forbidden_columns:
        assert re.search(rf"\b{column}\b", body) is None


def test_vector_embedding_record_requires_declared_dimensions_to_match_embedding() -> None:
    metadata = ChunkMetadata(
        tenant_id="tenant-1",
        source_object_id="doc-1",
        source_object_type="document",
        source_version_id="v1",
        chunk_id="chunk-1",
        classification=DataClass.EMBEDDING,
        retention_policy_id="rp-standard",
        legal_hold_state="none",
        acl_hash="sha256:acl",
        acl_version=1,
        created_at_utc="2026-06-10T00:00:00Z",
        embedding_model_id="mock-embedding",
        embedding_model_version="1",
        content_hash="sha256:content",
    )

    record = VectorEmbeddingRecord(
        metadata=metadata,
        embedding=[0.1, 0.2, 0.3],
        embedding_dimensions=3,
        content_byte_length=42,
        indexed_at_utc="2026-06-10T00:01:00Z",
    )

    assert record.lifecycle_state == VectorLifecycleState.ACTIVE

    with pytest.raises(ValueError, match="embedding_dimensions"):
        VectorEmbeddingRecord(
            metadata=metadata,
            embedding=[0.1, 0.2, 0.3],
            embedding_dimensions=2,
            content_byte_length=42,
            indexed_at_utc="2026-06-10T00:01:00Z",
        )


def test_vector_metadata_schema_rejects_invalid_acl_and_source_metadata() -> None:
    with pytest.raises(ValueError, match="source_object_type"):
        chunk_metadata_for(source_object_type="unknown")

    with pytest.raises(ValueError, match="legal_hold_state"):
        chunk_metadata_for(legal_hold_state="maybe")

    with pytest.raises(ValueError, match="acl_hash"):
        chunk_metadata_for(acl_hash="not-namespaced")

    with pytest.raises(ValueError, match="acl_version"):
        chunk_metadata_for(acl_version=0)

    with pytest.raises(ValueError, match="UTC"):
        chunk_metadata_for(created_at_utc="2026-06-10T00:00:00+02:00")


def test_vector_embedding_record_rejects_non_finite_embeddings() -> None:
    metadata = ChunkMetadata(
        tenant_id="tenant-1",
        source_object_id="doc-1",
        source_object_type="document",
        source_version_id="v1",
        chunk_id="chunk-1",
        classification=DataClass.EMBEDDING,
        retention_policy_id="rp-standard",
        legal_hold_state="none",
        acl_hash="sha256:acl",
        acl_version=1,
        created_at_utc="2026-06-10T00:00:00Z",
        embedding_model_id="mock-embedding",
        embedding_model_version="1",
        content_hash="sha256:content",
    )

    with pytest.raises(ValueError, match="finite"):
        VectorEmbeddingRecord(
            metadata=metadata,
            embedding=[0.1, float("nan"), 0.3],
            embedding_dimensions=3,
            content_byte_length=42,
            indexed_at_utc="2026-06-10T00:01:00Z",
        )


def chunk_metadata_for(**overrides: Any) -> ChunkMetadata:
    values = {
        "tenant_id": "tenant-1",
        "source_object_id": "doc-1",
        "source_object_type": "document",
        "source_version_id": "v1",
        "chunk_id": "chunk-1",
        "classification": DataClass.EMBEDDING,
        "retention_policy_id": "rp-standard",
        "legal_hold_state": "none",
        "acl_hash": "sha256:acl",
        "acl_version": 1,
        "created_at_utc": "2026-06-10T00:00:00Z",
        "embedding_model_id": "mock-embedding",
        "embedding_model_version": "1",
        "content_hash": "sha256:content",
    }
    values.update(overrides)
    return ChunkMetadata.model_validate(values)
