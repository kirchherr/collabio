import re
from typing import Any

import pytest

from suite.ai_control_plane.models import DataClass
from suite.persistence.migration_catalog import (
    get_migration,
    load_migration_manifest,
    load_migrations,
    load_module_migrations,
)
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
        "0011",
        "0012",
        "0013",
        "0014",
        "0015",
        "0016",
        "0017",
        "0018",
        "0019",
        "0020",
        "0021",
        "0022",
        "0023",
        "0024",
        "0025",
        "0026",
        "0027",
        "0028",
        "0029",
        "0030",
        "0031",
    ]
    assert migrations[0].version == "0001"
    assert migrations[0].name == "pgvector_embeddings"
    assert migrations[0].module_id == "core"
    assert migrations[0].evidence_refs
    assert "CREATE EXTENSION IF NOT EXISTS vector;" in migrations[0].sql()


def test_migration_catalog_exposes_module_manifest_with_checksums_and_evidence() -> None:
    core_migrations = load_module_migrations("core")
    crm_erp_migrations = load_module_migrations("crm_erp")
    knowledge_base_migrations = load_module_migrations("knowledge_base")
    manifest = load_migration_manifest()

    assert len(core_migrations) == len(load_migrations()) - 12
    assert [migration.version for migration in crm_erp_migrations] == ["0016", "0017", "0018", "0019", "0020"]
    assert [migration.version for migration in knowledge_base_migrations] == [
        "0021",
        "0022",
        "0023",
        "0024",
        "0025",
        "0028",
        "0029",
    ]
    assert [entry.version for entry in manifest] == [migration.version for migration in load_migrations()]
    assert manifest[-1].module_id == "core"
    assert all(entry.checksum.startswith("sha256:") for entry in manifest)
    assert all(entry.evidence_refs for entry in manifest)
    assert all(entry.blocks_startup for entry in manifest)

    with pytest.raises(ValueError, match="module_id"):
        load_module_migrations("Not-A-Module")


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


def test_platform_module_registry_runtime_store_migration_seeds_catalog_and_worker_select() -> None:
    sql = normalized(get_migration("0030").sql())

    assert "alter table collabio.module_catalog" in sql
    assert "required_migration_versions jsonb not null default '[]'::jsonb" in sql
    assert "module_catalog_required_migration_versions_json_check" in sql
    assert "knowledge_base" in sql
    assert '"0029"' in sql
    assert "on conflict (module_id) do update" in sql
    assert "on conflict (tenant_id, module_id) do nothing" in sql
    assert "tenant_modules_worker_module_select" in sql
    assert "to collabio_worker using (true)" in sql
    assert "grant select on table collabio.module_catalog to collabio_worker" in sql
    assert "grant select on table collabio.tenant_modules to collabio_worker" in sql


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


def test_tenant_module_migration_evidence_migration_requires_manifest_snapshot() -> None:
    sql = normalized(get_migration("0011").sql())

    assert "add column if not exists migration_evidence jsonb" in sql
    assert "tenant_modules_migration_evidence_json_check" in sql
    assert "tenant_modules_provisioned_migration_evidence_check" in sql
    assert "status in ('available', 'provisioning')" in sql
    assert "jsonb_array_length(migration_evidence) > 0" in sql
    assert "startup-blocking migration manifest entries" in sql


def test_principal_authz_store_migration_declares_rls_and_audit_refs() -> None:
    sql = normalized(get_migration("0012").sql())

    required_tables = [
        "tenant_principals",
        "tenant_principal_memberships",
        "tenant_roles",
        "tenant_groups",
        "tenant_principal_role_assignments",
        "tenant_principal_group_memberships",
        "object_acl_entries",
        "abac_policy_bindings",
    ]
    for table in required_tables:
        body = table_body(get_migration("0012").sql(), f"collabio.{table}")
        assert "tenant_id" in body
        assert "audit_chain_ref" in body
        assert "schema_version" in body
        assert f"alter table collabio.{table} enable row level security" in sql
        assert f"alter table collabio.{table} force row level security" in sql
        assert f"create policy {table}_tenant_select" in sql
        assert f"create policy {table}_tenant_insert" in sql
        assert f"create policy {table}_tenant_update" in sql
        assert f"create policy {table}_no_hard_delete" in sql

    assert "tenant_id = collabio.current_tenant_id()" in sql
    assert "using (false)" in sql
    assert "permission in ('read', 'write', 'admin')" in sql
    assert "acl_subject_type in ('user', 'role', 'group')" in sql
    assert "effect in ('allow', 'deny')" in sql
    assert "grant select on table collabio.tenant_principals to collabio_app" in sql
    assert "grant select on table collabio.abac_policy_bindings to collabio_app" in sql
    assert "grant insert" not in sql
    assert "authoritative object acl entries" in sql


def test_jwt_replay_store_migration_declares_rls_and_append_only_events() -> None:
    sql = normalized(get_migration("0013").sql())
    replay_tokens_body = table_body(get_migration("0013").sql(), "collabio.jwt_replay_tokens")
    replay_events_body = table_body(get_migration("0013").sql(), "collabio.jwt_replay_events")

    for column in [
        "tenant_id",
        "issuer",
        "subject",
        "jwt_id",
        "expires_at_epoch",
        "expires_at_utc",
        "audit_chain_ref",
        "schema_version",
    ]:
        assert column in replay_tokens_body
        assert column in replay_events_body

    assert "primary key (issuer, jwt_id)" in sql
    assert "event_type in ('accepted', 'replayed')" in sql
    assert "token bodies are never stored" in sql
    assert "alter table collabio.jwt_replay_tokens enable row level security" in sql
    assert "alter table collabio.jwt_replay_tokens force row level security" in sql
    assert "alter table collabio.jwt_replay_events enable row level security" in sql
    assert "alter table collabio.jwt_replay_events force row level security" in sql
    assert "tenant_id = collabio.current_tenant_id()" in sql
    assert "create policy jwt_replay_tokens_no_hard_delete" in sql
    assert "create policy jwt_replay_events_no_hard_delete" in sql
    assert "grant select, insert on table collabio.jwt_replay_tokens to collabio_app" in sql
    assert "grant insert on table collabio.jwt_replay_events to collabio_app" in sql
    assert "grant update" not in sql
    assert "compact_jwt" not in replay_tokens_body
    assert "token_body" not in replay_tokens_body


def test_audit_event_store_migration_declares_append_only_roles_and_evidence_tables() -> None:
    sql = normalized(get_migration("0014").sql())
    audit_events_body = table_body(get_migration("0014").sql(), "collabio.audit_events")
    checkpoint_body = table_body(get_migration("0014").sql(), "collabio.audit_checkpoints")
    worm_export_body = table_body(get_migration("0014").sql(), "collabio.audit_worm_exports")

    for column in [
        "tenant_id",
        "sequence_number",
        "event_id",
        "schema_version",
        "user_id",
        "event_type",
        "source_object_ids",
        "input_hash",
        "output_hash",
        "metadata",
        "previous_event_hash",
        "event_hash",
    ]:
        assert column in audit_events_body

    for column in [
        "tenant_id",
        "checkpoint_id",
        "through_sequence_number",
        "event_count",
        "first_event_hash",
        "last_event_hash",
        "checkpoint_hash",
        "signature_algorithm",
        "signature_key_ref",
        "audit_chain_ref",
        "schema_version",
    ]:
        assert column in checkpoint_body

    for column in [
        "tenant_id",
        "export_id",
        "checkpoint_id",
        "from_sequence_number",
        "through_sequence_number",
        "event_count",
        "checkpoint_hash",
        "export_manifest_hash",
        "storage_uri",
        "object_lock_mode",
        "audit_chain_ref",
        "schema_version",
    ]:
        assert column in worm_export_body

    assert "create role collabio_audit_writer login password" in sql
    assert "primary key (tenant_id, sequence_number)" in sql
    assert "unique (event_id)" in sql
    assert "unique (tenant_id, event_hash)" in sql
    assert "signature_algorithm text not null check (signature_algorithm in ('hmac-sha256'))" in sql
    assert "object_lock_mode text not null default 'compliance' check (object_lock_mode in ('compliance'))" in sql
    assert "prompt, output, document, mail, transcript, and token bodies are forbidden" in sql

    for table in ["audit_events", "audit_checkpoints", "audit_worm_exports"]:
        assert f"alter table collabio.{table} enable row level security" in sql
        assert f"alter table collabio.{table} force row level security" in sql
        assert f"create policy {table}_tenant_select" in sql
        assert f"create policy {table}_tenant_insert" in sql
        assert f"create policy {table}_no_update" in sql
        assert f"create policy {table}_no_hard_delete" in sql
        assert f"grant select, insert on table collabio.{table} to collabio_audit_writer" in sql
        assert f"revoke all on table collabio.{table} from collabio_app" in sql

    assert "tenant_id = collabio.current_tenant_id()" in sql
    assert "using (false)" in sql
    assert "grant update" not in sql
    assert "grant delete" not in sql
    assert "prompt_text" not in audit_events_body
    assert "output_text" not in audit_events_body
    assert "transcript_text" not in audit_events_body
    assert "token_body" not in audit_events_body


def test_authz_admin_runtime_role_migration_declares_admin_write_boundary() -> None:
    sql = normalized(get_migration("0015").sql())

    assert "create role collabio_authz_admin login password" in sql
    for table in [
        "tenant_principals",
        "tenant_principal_memberships",
        "tenant_roles",
        "tenant_groups",
        "tenant_principal_role_assignments",
        "tenant_principal_group_memberships",
        "object_acl_entries",
        "abac_policy_bindings",
    ]:
        assert f"grant select, insert, update on table collabio.{table} to collabio_authz_admin" in sql
        assert f"grant select, insert, update on table collabio.{table} to collabio_app" not in sql

    assert "create policy jwt_replay_tokens_retention_delete" in sql
    assert "to collabio_authz_admin" in sql
    assert "expires_at_epoch <= coalesce" in sql
    assert "current_setting('app.retention_now_epoch', true)" in sql
    assert "grant select, delete on table collabio.jwt_replay_tokens to collabio_authz_admin" in sql
    assert "grant delete on table collabio.jwt_replay_tokens to collabio_app" not in sql
    assert "grant delete on table collabio.jwt_replay_events" not in sql


def test_crm_erp_schema_scaffold_declares_schemas_object_rules_and_rls() -> None:
    sql = normalized(get_migration("0016").sql())
    schema_plans_body = table_body(get_migration("0016").sql(), "crm_erp.schema_plans")
    object_rules_body = table_body(get_migration("0016").sql(), "crm_erp.object_type_rules")

    for schema_name in ["crm_erp", "crm", "erp", "crm_erp_legacy"]:
        assert f"create schema if not exists {schema_name}" in sql
        assert "grant usage on schema crm_erp, crm, erp, crm_erp_legacy to collabio_app" in sql

    for column in [
        "tenant_id",
        "module_id",
        "schema_name",
        "purpose",
        "manifest_hash",
        "backup_domain_id",
        "rls_required",
        "audit_required",
        "raw_legacy_payload_allowed",
        "audit_chain_ref",
        "schema_version",
    ]:
        assert re.search(rf"\b{column}\b", schema_plans_body), f"{column} missing from CRM/ERP schema plan"

    for column in [
        "tenant_id",
        "object_type",
        "schema_name",
        "table_name",
        "feature_id",
        "classification",
        "retention_policy_id",
        "lifecycle_states",
        "legal_hold_supported",
        "kms_key_ref_required",
        "audit_required",
        "rls_required",
        "search_candidate_only",
        "rag_indexing_default_enabled",
        "raw_import_payload_allowed",
        "required_metadata_fields",
        "audit_chain_ref",
        "schema_version",
    ]:
        assert re.search(rf"\b{column}\b", object_rules_body), f"{column} missing from CRM/ERP object rule"

    for object_type in ["'crm.account'", "'erp.invoice'", "'legacy.row'"]:
        assert object_type in object_rules_body

    assert "required_metadata_fields @> array[" in object_rules_body
    assert "'kms_key_ref'" in object_rules_body
    assert "'audit_chain_ref'" in object_rules_body
    assert "'source_system'" in object_rules_body
    assert "retention_policy_id = 'rp-gobd-10y'" in object_rules_body
    assert "lifecycle_states @> array['record']::text[]" in object_rules_body
    assert "lifecycle_states @> array['quarantined']::text[]" in object_rules_body
    assert "not raw_import_payload_allowed" in object_rules_body
    assert "not rag_indexing_default_enabled" in object_rules_body
    assert "alter table crm_erp.schema_plans enable row level security" in sql
    assert "alter table crm_erp.object_type_rules enable row level security" in sql
    assert "tenant_id = collabio.current_tenant_id()" in sql
    assert "create policy crm_erp_object_type_rules_no_hard_delete" in sql
    assert "grant select, insert on table crm_erp.object_type_rules to collabio_app" in sql
    assert "grant update" not in sql


def test_crm_accounts_migration_declares_required_metadata_rls_and_no_hard_delete() -> None:
    sql = normalized(get_migration("0017").sql())
    body = table_body(get_migration("0017").sql(), "crm.accounts")

    for column in [
        "tenant_id",
        "object_id",
        "object_type",
        "owner_principal_id",
        "created_by",
        "created_at_utc",
        "updated_at_utc",
        "data_classification",
        "retention_policy_id",
        "legal_hold_state",
        "lifecycle_state",
        "kms_key_ref",
        "audit_chain_ref",
        "source_system",
        "schema_version",
        "account_number",
        "display_name",
        "account_kind",
        "status",
    ]:
        assert re.search(rf"\b{column}\b", body), f"{column} missing from crm.accounts"

    assert "object_type text not null default 'crm.account' check (object_type = 'crm.account')" in body
    assert "data_classification text not null default 'personal' check (data_classification = 'personal')" in body
    assert "retention_policy_id text not null default 'rp-standard' check (retention_policy_id = 'rp-standard')" in body
    assert "legal_hold_state text not null default 'none'" in body
    assert "kms_key_ref text not null check" in body
    assert "audit_chain_ref text not null check" in body
    assert "crm_erp.crm.accounts" in sql
    assert "alter table crm.accounts enable row level security" in sql
    assert "alter table crm.accounts force row level security" in sql
    assert "create policy crm_accounts_tenant_select" in sql
    assert "create policy crm_accounts_tenant_insert" in sql
    assert "create policy crm_accounts_tenant_update" in sql
    assert "create policy crm_accounts_no_hard_delete" in sql
    assert "using (tenant_id = collabio.current_tenant_id())" in sql
    assert "using (false)" in sql
    assert "create trigger crm_accounts_touch_updated_at_utc" in sql
    assert "grant select, insert, update on table crm.accounts to collabio_app" in sql
    assert "grant delete" not in sql
    assert "source_text" not in sql
    assert "raw_payload" not in sql


def test_crm_contacts_migration_declares_required_metadata_rls_fk_and_no_hard_delete() -> None:
    sql = normalized(get_migration("0018").sql())
    body = table_body(get_migration("0018").sql(), "crm.contacts")

    for column in [
        "tenant_id",
        "object_id",
        "object_type",
        "owner_principal_id",
        "created_by",
        "created_at_utc",
        "updated_at_utc",
        "data_classification",
        "retention_policy_id",
        "legal_hold_state",
        "lifecycle_state",
        "kms_key_ref",
        "audit_chain_ref",
        "source_system",
        "schema_version",
        "account_object_id",
        "contact_number",
        "display_name",
        "given_name",
        "family_name",
        "primary_email",
        "primary_phone",
        "role_label",
        "status",
    ]:
        assert re.search(rf"\b{column}\b", body), f"{column} missing from crm.contacts"

    assert "object_type text not null default 'crm.contact' check (object_type = 'crm.contact')" in body
    assert "data_classification text not null default 'personal' check (data_classification = 'personal')" in body
    assert "retention_policy_id text not null default 'rp-standard' check (retention_policy_id = 'rp-standard')" in body
    assert "legal_hold_state text not null default 'none'" in body
    assert "kms_key_ref text not null check" in body
    assert "audit_chain_ref text not null check" in body
    assert "foreign key (tenant_id, account_object_id)" in body
    assert "references crm.accounts (tenant_id, object_id)" in body
    assert "crm_erp.crm.contacts" in sql
    assert "alter table crm.contacts enable row level security" in sql
    assert "alter table crm.contacts force row level security" in sql
    assert "create policy crm_contacts_tenant_select" in sql
    assert "create policy crm_contacts_tenant_insert" in sql
    assert "create policy crm_contacts_tenant_update" in sql
    assert "create policy crm_contacts_no_hard_delete" in sql
    assert "using (tenant_id = collabio.current_tenant_id())" in sql
    assert "using (false)" in sql
    assert "create trigger crm_contacts_touch_updated_at_utc" in sql
    assert "grant select, insert, update on table crm.contacts to collabio_app" in sql
    assert "grant delete" not in sql
    assert "source_text" not in sql
    assert "raw_payload" not in sql


def test_crm_activities_notes_migration_declares_required_metadata_rls_fks_and_no_body_storage() -> None:
    sql = normalized(get_migration("0019").sql())
    activities_body = table_body(get_migration("0019").sql(), "crm.activities")
    notes_body = table_body(get_migration("0019").sql(), "crm.notes")

    required_metadata_columns = [
        "tenant_id",
        "object_id",
        "object_type",
        "owner_principal_id",
        "created_by",
        "created_at_utc",
        "updated_at_utc",
        "data_classification",
        "retention_policy_id",
        "legal_hold_state",
        "lifecycle_state",
        "kms_key_ref",
        "audit_chain_ref",
        "source_system",
        "schema_version",
    ]
    for body, table_name in ((activities_body, "crm.activities"), (notes_body, "crm.notes")):
        for column in required_metadata_columns:
            assert re.search(rf"\b{column}\b", body), f"{column} missing from {table_name}"
        assert "data_classification text not null default 'personal' check (data_classification = 'personal')" in body
        assert (
            "retention_policy_id text not null default 'rp-standard' check (retention_policy_id = 'rp-standard')"
        ) in body
        assert "legal_hold_state text not null default 'none'" in body
        assert "kms_key_ref text not null check" in body
        assert "audit_chain_ref text not null check" in body

    for column in [
        "account_object_id",
        "contact_object_id",
        "activity_number",
        "activity_type",
        "subject",
        "due_at_utc",
        "completed_at_utc",
        "status",
    ]:
        assert re.search(rf"\b{column}\b", activities_body), f"{column} missing from crm.activities"

    for column in [
        "account_object_id",
        "contact_object_id",
        "activity_object_id",
        "note_number",
        "title",
        "status",
    ]:
        assert re.search(rf"\b{column}\b", notes_body), f"{column} missing from crm.notes"

    assert "object_type text not null default 'crm.activity' check (object_type = 'crm.activity')" in activities_body
    assert "object_type text not null default 'crm.note' check (object_type = 'crm.note')" in notes_body
    assert "references crm.accounts (tenant_id, object_id)" in activities_body
    assert "references crm.contacts (tenant_id, object_id)" in activities_body
    assert "references crm.activities (tenant_id, object_id)" in notes_body
    assert "status <> 'done' or completed_at_utc is not null" in activities_body
    assert "crm_erp.crm.activities" in sql
    assert "alter table crm.activities enable row level security" in sql
    assert "alter table crm.activities force row level security" in sql
    assert "alter table crm.notes enable row level security" in sql
    assert "alter table crm.notes force row level security" in sql
    assert "create policy crm_activities_tenant_select" in sql
    assert "create policy crm_activities_tenant_insert" in sql
    assert "create policy crm_activities_tenant_update" in sql
    assert "create policy crm_activities_no_hard_delete" in sql
    assert "create policy crm_notes_tenant_select" in sql
    assert "create policy crm_notes_tenant_insert" in sql
    assert "create policy crm_notes_tenant_update" in sql
    assert "create policy crm_notes_no_hard_delete" in sql
    assert "using (tenant_id = collabio.current_tenant_id())" in sql
    assert "using (false)" in sql
    assert "create trigger crm_activities_touch_updated_at_utc" in sql
    assert "create trigger crm_notes_touch_updated_at_utc" in sql
    assert "grant select, insert, update on table crm.activities to collabio_app" in sql
    assert "grant select, insert, update on table crm.notes to collabio_app" in sql
    assert "grant delete" not in sql
    assert "note_body" not in sql
    assert "source_text" not in sql
    assert "raw_payload" not in sql


def test_erp_products_migration_declares_internal_metadata_rls_and_no_hard_delete() -> None:
    sql = normalized(get_migration("0020").sql())
    body = table_body(get_migration("0020").sql(), "erp.products")

    for column in [
        "tenant_id",
        "object_id",
        "object_type",
        "owner_principal_id",
        "created_by",
        "created_at_utc",
        "updated_at_utc",
        "data_classification",
        "retention_policy_id",
        "legal_hold_state",
        "lifecycle_state",
        "kms_key_ref",
        "audit_chain_ref",
        "source_system",
        "schema_version",
        "product_number",
        "display_name",
        "product_kind",
        "unit_code",
        "status",
    ]:
        assert re.search(rf"\b{column}\b", body), f"{column} missing from erp.products"

    assert "object_type text not null default 'erp.product' check (object_type = 'erp.product')" in body
    assert "data_classification text not null default 'internal' check (data_classification = 'internal')" in body
    assert "retention_policy_id text not null default 'rp-standard' check (retention_policy_id = 'rp-standard')" in body
    assert "legal_hold_state text not null default 'none'" in body
    assert "kms_key_ref text not null check" in body
    assert "audit_chain_ref text not null check" in body
    assert "crm_erp.erp.products" in sql
    assert "alter table erp.products enable row level security" in sql
    assert "alter table erp.products force row level security" in sql
    assert "create policy erp_products_tenant_select" in sql
    assert "create policy erp_products_tenant_insert" in sql
    assert "create policy erp_products_tenant_update" in sql
    assert "create policy erp_products_no_hard_delete" in sql
    assert "using (tenant_id = collabio.current_tenant_id())" in sql
    assert "using (false)" in sql
    assert "create trigger erp_products_touch_updated_at_utc" in sql
    assert "grant select, insert, update on table erp.products to collabio_app" in sql
    assert "grant delete" not in sql
    assert "source_text" not in sql
    assert "raw_payload" not in sql


def test_knowledge_base_articles_migration_declares_metadata_versions_rls_and_no_body_storage() -> None:
    sql = normalized(get_migration("0021").sql())
    articles_body = table_body(get_migration("0021").sql(), "knowledge_base.articles")
    versions_body = table_body(get_migration("0021").sql(), "knowledge_base.article_versions")

    required_metadata_columns = [
        "tenant_id",
        "object_id",
        "object_type",
        "owner_principal_id",
        "created_by",
        "created_at_utc",
        "updated_at_utc",
        "data_classification",
        "retention_policy_id",
        "legal_hold_state",
        "lifecycle_state",
        "kms_key_ref",
        "audit_chain_ref",
        "source_system",
        "schema_version",
    ]
    for body, table_name in (
        (articles_body, "knowledge_base.articles"),
        (versions_body, "knowledge_base.article_versions"),
    ):
        for column in required_metadata_columns:
            assert re.search(rf"\b{column}\b", body), f"{column} missing from {table_name}"
        assert "data_classification text not null default 'internal' check (data_classification = 'internal')" in body
        assert (
            "retention_policy_id text not null default 'rp-standard' check (retention_policy_id = 'rp-standard')"
        ) in body
        assert "legal_hold_state text not null default 'none'" in body
        assert "kms_key_ref text not null check" in body
        assert "audit_chain_ref text not null check" in body

    for column in [
        "article_key",
        "title",
        "current_version_object_id",
        "current_version_label",
        "published_at_utc",
        "status",
    ]:
        assert re.search(rf"\b{column}\b", articles_body), f"{column} missing from knowledge_base.articles"

    for column in [
        "article_object_id",
        "version_label",
        "version_state",
        "source_object_version_ref",
        "content_hash",
        "published_at_utc",
    ]:
        assert re.search(rf"\b{column}\b", versions_body), f"{column} missing from article_versions"

    assert "object_type text not null default 'kb.article' check (object_type = 'kb.article')" in articles_body
    assert (
        "object_type text not null default 'kb.article_version' check (object_type = 'kb.article_version')"
    ) in versions_body
    assert "foreign key (tenant_id, article_object_id)" in versions_body
    assert "references knowledge_base.articles (tenant_id, object_id)" in versions_body
    assert "knowledge_base.articles.read" in sql
    assert "alter table knowledge_base.articles enable row level security" in sql
    assert "alter table knowledge_base.articles force row level security" in sql
    assert "alter table knowledge_base.article_versions enable row level security" in sql
    assert "alter table knowledge_base.article_versions force row level security" in sql
    assert "create policy kb_articles_tenant_select" in sql
    assert "create policy kb_articles_tenant_insert" in sql
    assert "create policy kb_articles_tenant_update" in sql
    assert "create policy kb_articles_no_hard_delete" in sql
    assert "create policy kb_article_versions_tenant_select" in sql
    assert "create policy kb_article_versions_tenant_insert" in sql
    assert "create policy kb_article_versions_tenant_update" in sql
    assert "create policy kb_article_versions_no_hard_delete" in sql
    assert "using (tenant_id = collabio.current_tenant_id())" in sql
    assert "using (false)" in sql
    assert "create trigger kb_articles_touch_updated_at_utc" in sql
    assert "create trigger kb_article_versions_touch_updated_at_utc" in sql
    assert "grant select, insert, update on table knowledge_base.articles to collabio_app" in sql
    assert "grant select, insert, update on table knowledge_base.article_versions to collabio_app" in sql
    assert "grant delete" not in sql
    assert "article_body" not in sql
    assert "source_text" not in sql
    assert "raw_payload" not in sql
    assert "prompt_text" not in sql
    assert "output_text" not in sql


def test_knowledge_base_evidence_migration_declares_source_version_and_restore_evidence() -> None:
    sql = normalized(get_migration("0022").sql())
    source_evidence_body = table_body(get_migration("0022").sql(), "knowledge_base.source_version_evidence")
    restore_evidence_body = table_body(get_migration("0022").sql(), "knowledge_base.restore_evidence")

    for column in [
        "tenant_id",
        "article_object_id",
        "article_version_object_id",
        "source_object_id",
        "source_version_id",
        "source_object_type",
        "source_manifest_hash",
        "content_hash",
        "acl_version",
        "data_classification",
        "retention_policy_id",
        "legal_hold_state",
        "evidence_hash",
        "audit_chain_ref",
        "schema_version",
    ]:
        assert re.search(rf"\b{column}\b", source_evidence_body), f"{column} missing from source evidence"

    for column in [
        "tenant_id",
        "module_id",
        "continuity_domain",
        "article_count",
        "article_version_count",
        "source_version_evidence_count",
        "source_version_evidence_hashes",
        "restore_drill_report_hash",
        "row_count_hash",
        "checksum_manifest_hash",
        "tenant_isolation_verified",
        "disabled_state_restore_verified",
        "legal_hold_restore_verified",
        "evidence_hash",
        "audit_chain_ref",
        "schema_version",
    ]:
        assert re.search(rf"\b{column}\b", restore_evidence_body), f"{column} missing from restore evidence"

    assert "article_version_object_id = source_object_id" in source_evidence_body
    assert (
        "source_manifest_hash text not null check (source_manifest_hash ~ '^sha256:[a-f0-9]{64}$')"
        in source_evidence_body
    )
    assert "content_hash text not null check (content_hash ~ '^sha256:[a-f0-9]{64}$')" in source_evidence_body
    assert "acl_version integer not null check (acl_version >= 1)" in source_evidence_body
    assert (
        "data_classification text not null default 'internal' check (data_classification = 'internal')"
        in source_evidence_body
    )
    assert (
        "retention_policy_id text not null default 'rp-standard' check (retention_policy_id = 'rp-standard')"
        in source_evidence_body
    )
    assert "continuity_domain = 'knowledge_base_content'" in restore_evidence_body
    assert "tenant_isolation_verified boolean not null check (tenant_isolation_verified)" in restore_evidence_body
    assert (
        "disabled_state_restore_verified boolean not null check (disabled_state_restore_verified)"
        in restore_evidence_body
    )
    assert "legal_hold_restore_verified boolean not null check (legal_hold_restore_verified)" in restore_evidence_body
    assert "article_version_count = source_version_evidence_count" in restore_evidence_body
    assert "alter table knowledge_base.source_version_evidence enable row level security" in sql
    assert "alter table knowledge_base.restore_evidence enable row level security" in sql
    assert "create policy kb_source_version_evidence_tenant_select" in sql
    assert "create policy kb_source_version_evidence_no_update" in sql
    assert "create policy kb_source_version_evidence_no_hard_delete" in sql
    assert "create policy kb_restore_evidence_tenant_select" in sql
    assert "create policy kb_restore_evidence_no_update" in sql
    assert "create policy kb_restore_evidence_no_hard_delete" in sql
    assert "grant select, insert on table knowledge_base.source_version_evidence to collabio_app" in sql
    assert "grant select, insert on table knowledge_base.restore_evidence to collabio_app" in sql
    assert "grant delete" not in sql
    assert "source_text" not in sql
    assert "article_body" not in sql
    assert "prompt_text" not in sql
    assert "output_text" not in sql


def test_knowledge_base_write_approval_evidence_migration_declares_append_only_ledger() -> None:
    sql = normalized(get_migration("0023").sql())
    body = table_body(get_migration("0023").sql(), "knowledge_base.write_approval_evidence")

    for column in [
        "tenant_id",
        "approval_reference",
        "operation",
        "approval_state",
        "article_object_id",
        "expected_current_version_object_id",
        "proposed_version_object_id",
        "proposed_source_object_id",
        "proposed_source_version_id",
        "proposed_source_object_type",
        "proposed_source_manifest_hash",
        "proposed_content_hash",
        "proposed_acl_version",
        "command_hash",
        "proposed_source_version_evidence_hash",
        "current_restore_evidence_hash",
        "source_object_write_guard_ref",
        "requested_by",
        "persistence_allowed",
        "rag_indexing_allowed",
        "source_authority_verified",
        "audit_event_id",
        "audit_chain_ref",
        "evidence_hash",
        "schema_version",
    ]:
        assert re.search(rf"\b{column}\b", body), f"{column} missing from write approval evidence"

    assert "operation text not null check (operation in ('create', 'edit'))" in body
    assert "approval_state text not null default 'dry_run' check" in body
    assert "'approved_for_write'" in body
    assert "proposed_version_object_id = proposed_source_object_id" in body
    assert "operation <> 'edit' or expected_current_version_object_id is not null" in body
    assert "operation <> 'create' or expected_current_version_object_id is null" in body
    assert "approval_state = 'approved_for_write' or not persistence_allowed" in body
    assert "approval_state = 'approved_for_write' or not rag_indexing_allowed" in body
    assert "approval_state = 'approved_for_write' or not source_authority_verified" in body
    for hash_column in [
        "proposed_source_manifest_hash",
        "proposed_content_hash",
        "command_hash",
        "proposed_source_version_evidence_hash",
        "current_restore_evidence_hash",
        "evidence_hash",
    ]:
        assert f"{hash_column}" in body
        assert "'^sha256:[a-f0-9]{64}$'" in body

    assert "alter table knowledge_base.write_approval_evidence enable row level security" in sql
    assert "alter table knowledge_base.write_approval_evidence force row level security" in sql
    assert "create policy kb_write_approval_evidence_tenant_select" in sql
    assert "create policy kb_write_approval_evidence_tenant_insert" in sql
    assert "create policy kb_write_approval_evidence_no_update" in sql
    assert "create policy kb_write_approval_evidence_no_hard_delete" in sql
    assert "grant select, insert on table knowledge_base.write_approval_evidence to collabio_app" in sql
    assert "grant select on table knowledge_base.write_approval_evidence to collabio_worker" in sql
    assert "grant delete" not in sql
    assert "source_text" not in sql
    assert "article_body" not in sql
    assert "prompt_text" not in sql
    assert "output_text" not in sql
    assert "raw_payload" not in sql


def test_knowledge_base_write_approval_transition_lineage_migration_declares_hash_source() -> None:
    sql = normalized(get_migration("0024").sql())

    assert "alter table knowledge_base.write_approval_evidence" in sql
    assert "add column if not exists transition_source_evidence_hash text" in sql
    assert "kb_write_approval_transition_source_hash_format" in sql
    assert "transition_source_evidence_hash ~ '^sha256:[a-f0-9]{64}$'" in sql
    assert "kb_write_approval_transition_source_required" in sql
    assert "approval_state = 'dry_run' and transition_source_evidence_hash is null" in sql
    assert "approval_state <> 'dry_run' and transition_source_evidence_hash is not null" in sql
    assert "transition_source_evidence_hash <> evidence_hash" in sql
    assert "kb_write_approval_evidence_transition_source_idx" in sql
    assert "source_text" not in sql
    assert "article_body" not in sql
    assert "prompt_text" not in sql
    assert "output_text" not in sql
    assert "raw_payload" not in sql


def test_knowledge_base_write_approval_trusted_metadata_migration_extends_create_evidence() -> None:
    sql = normalized(get_migration("0025").sql())

    assert "alter table knowledge_base.write_approval_evidence" in sql
    assert "add column if not exists article_key text not null default 'legacy-untrusted'" in sql
    assert "add column if not exists title text not null default 'legacy untrusted knowledge base write'" in sql
    assert "add column if not exists proposed_version_label text not null default 'legacy-untrusted'" in sql
    assert "add column if not exists source_system text not null default 'legacy'" in sql
    assert "kb_write_approval_article_key_not_empty" in sql
    assert "kb_write_approval_title_not_empty" in sql
    assert "kb_write_approval_proposed_version_label_not_empty" in sql
    assert "kb_write_approval_source_system_format" in sql
    assert "source_system ~ '^[a-z][a-z0-9_+.-]*$'" in sql
    assert "trusted article key captured at approval time" in sql
    assert "trusted article title captured at approval time" in sql
    assert "trusted proposed article-version label captured before execution" in sql
    assert "trusted source-system identifier captured before create execution" in sql
    assert "kb_write_approval_evidence_article_key_idx" in sql
    assert "kb_write_approval_evidence_source_system_idx" in sql
    assert "source_text" not in sql
    assert "article_body" not in sql
    assert "prompt_text" not in sql
    assert "output_text" not in sql
    assert "raw_payload" not in sql


def test_source_object_write_receipts_migration_is_append_only_metadata_boundary() -> None:
    sql = normalized(get_migration("0026").sql())
    body = table_body(get_migration("0026").sql(), "collabio.source_object_write_receipts")

    assert "create table if not exists collabio.source_object_write_receipts" in sql
    for column in [
        "tenant_id",
        "receipt_reference",
        "object_id",
        "object_type",
        "version_id",
        "classification",
        "retention_policy_id",
        "legal_hold_state",
        "kms_key_ref",
        "manifest_hash",
        "audit_chain_ref",
        "source_system",
        "source_schema_version",
        "acl_hash",
        "acl_version",
        "content_hash",
        "content_byte_length",
        "lifecycle_state",
        "captured_at_utc",
        "receipt_hash",
        "receipt_schema_version",
    ]:
        assert column in body
    assert "primary key (tenant_id, receipt_hash)" in sql
    assert "unique (tenant_id, object_id, version_id)" in sql
    assert "enable row level security" in sql
    assert "force row level security" in sql
    assert "source_object_write_receipts_tenant_select" in sql
    assert "source_object_write_receipts_tenant_insert" in sql
    assert "source_object_write_receipts_no_update" in sql
    assert "source_object_write_receipts_no_hard_delete" in sql
    assert "grant select, insert on table collabio.source_object_write_receipts to collabio_app" in sql
    assert "source_object_write_receipts_object_version_idx" in sql
    assert "source_object_write_receipts_content_hash_idx" in sql
    assert "source_object_write_receipts_audit_chain_idx" in sql
    assert "source_text" not in sql
    assert "article_body" not in sql
    assert "prompt_text" not in sql
    assert "output_text" not in sql
    assert "raw_payload" not in sql


def test_source_object_metadata_storage_bridge_migration_is_metadata_only_and_rls_protected() -> None:
    sql = normalized(get_migration("0027").sql())
    metadata_body = table_body(get_migration("0027").sql(), "collabio.source_object_metadata")
    storage_body = table_body(get_migration("0027").sql(), "collabio.source_object_storage_manifests")

    assert "create table if not exists collabio.source_object_metadata" in sql
    assert "create table if not exists collabio.source_object_storage_manifests" in sql
    for column in [
        "tenant_id",
        "object_id",
        "object_type",
        "version_id",
        "classification",
        "retention_policy_id",
        "legal_hold_state",
        "kms_key_ref",
        "manifest_hash",
        "audit_chain_ref",
        "source_system",
        "source_schema_version",
        "acl_hash",
        "acl_version",
        "content_hash",
        "content_byte_length",
        "lifecycle_state",
        "retention_manifest_hash",
        "retention_policy_snapshot_hash",
        "storage_manifest_hash",
        "source_object_write_receipt_hash",
    ]:
        assert column in metadata_body
    for column in [
        "tenant_id",
        "object_id",
        "source_version_id",
        "bucket_id",
        "object_key",
        "object_version_id",
        "storage_provider",
        "source_manifest_hash",
        "content_hash",
        "retention_manifest_hash",
        "retention_policy_snapshot_hash",
        "object_lock_mode",
        "object_lock_legal_hold",
        "manifest_hash",
    ]:
        assert column in storage_body
    assert "primary key (tenant_id, object_id, version_id)" in sql
    assert "primary key (tenant_id, manifest_hash)" in sql
    assert "references collabio.source_object_storage_manifests" in sql
    assert "references collabio.source_object_write_receipts" in sql
    assert "source_object_metadata_tenant_select" in sql
    assert "source_object_metadata_tenant_insert" in sql
    assert "source_object_metadata_no_update" in sql
    assert "source_object_metadata_no_hard_delete" in sql
    assert "source_object_storage_manifests_tenant_select" in sql
    assert "source_object_storage_manifests_tenant_insert" in sql
    assert "source_object_storage_manifests_no_update" in sql
    assert "source_object_storage_manifests_no_hard_delete" in sql
    assert "enable row level security" in sql
    assert "force row level security" in sql
    assert "grant select, insert on table collabio.source_object_metadata to collabio_app" in sql
    assert "grant select, insert on table collabio.source_object_storage_manifests to collabio_app" in sql
    assert "source_text" not in sql
    assert "article_body" not in sql
    assert "prompt_text" not in sql
    assert "output_text" not in sql
    assert "raw_payload" not in sql
    assert "content_bytes" not in sql


def test_knowledge_base_runtime_activation_migration_is_tenant_scoped_metadata_only() -> None:
    sql = normalized(get_migration("0028").sql())
    table = table_body(get_migration("0028").sql(), "collabio.knowledge_base_runtime_activations")

    assert "create table if not exists collabio.knowledge_base_runtime_activations" in sql
    for column in [
        "tenant_id",
        "activation_id",
        "backend",
        "active",
        "activated_at_utc",
        "activated_by",
        "provider_profile_id",
        "restore_drill_report_hash",
        "source_content_recovery_evidence_hash",
        "provider_profile_evidence_hash",
        "production_write_deployment_gate_evidence_hash",
        "source_content_recovery_evidence",
        "provider_profile_evidence",
        "production_write_deployment_gate_evidence",
        "approval_reference",
        "audit_chain_ref",
        "activation_evidence_hash",
    ]:
        assert column in table
    assert "jsonb_typeof(source_content_recovery_evidence) = 'object'" in sql
    assert "jsonb_typeof(provider_profile_evidence) = 'object'" in sql
    assert "jsonb_typeof(production_write_deployment_gate_evidence) = 'object'" in sql
    assert "knowledge_base_runtime_activations_one_active_idx" in sql
    assert "where active" in sql
    assert "enable row level security" in sql
    assert "force row level security" in sql
    assert "knowledge_base_runtime_activations_tenant_select" in sql
    assert "knowledge_base_runtime_activations_tenant_insert" in sql
    assert "knowledge_base_runtime_activations_tenant_deactivate" in sql
    assert "knowledge_base_runtime_activations_no_hard_delete" in sql
    assert "grant select, insert on table collabio.knowledge_base_runtime_activations to collabio_app" in sql
    assert "grant update (active) on table collabio.knowledge_base_runtime_activations to collabio_app" in sql
    assert "source_text" not in sql
    assert "article_body" not in sql
    assert "prompt_text" not in sql
    assert "output_text" not in sql
    assert "raw_payload" not in sql
    assert "content_bytes" not in sql


def test_knowledge_base_runtime_reconciliation_migration_blocks_drift_metadata_only() -> None:
    sql = normalized(get_migration("0029").sql())
    table = table_body(get_migration("0029").sql(), "collabio.knowledge_base_runtime_reconciliation_evidence")

    assert "alter table collabio.knowledge_base_runtime_activations" in sql
    assert "deactivation_reconciliation_evidence_hash" in sql
    assert "create table if not exists collabio.knowledge_base_runtime_reconciliation_evidence" in sql
    for column in [
        "tenant_id",
        "activation_id",
        "reconciliation_id",
        "checked_at_utc",
        "checked_by",
        "activation_evidence_hash",
        "previous_source_content_recovery_evidence_hash",
        "observed_source_content_recovery_evidence_hash",
        "previous_provider_profile_evidence_hash",
        "observed_provider_profile_evidence_hash",
        "previous_production_write_deployment_gate_evidence_hash",
        "observed_production_write_deployment_gate_evidence_hash",
        "observed_source_content_recovery_evidence",
        "observed_provider_profile_evidence",
        "observed_production_write_deployment_gate_evidence",
        "blocking_reasons",
        "reconciliation_status",
        "recommended_action",
        "runtime_deactivated",
        "audit_chain_ref",
        "evidence_hash",
    ]:
        assert column in table
    assert "references collabio.knowledge_base_runtime_activations" in sql
    assert "jsonb_typeof(observed_source_content_recovery_evidence) = 'object'" in sql
    assert "jsonb_typeof(observed_provider_profile_evidence) = 'object'" in sql
    assert "jsonb_typeof(observed_production_write_deployment_gate_evidence) = 'object'" in sql
    assert "knowledge_base_runtime_reconciliation_tenant_select" in sql
    assert "knowledge_base_runtime_reconciliation_tenant_insert" in sql
    assert "knowledge_base_runtime_reconciliation_no_update" in sql
    assert "knowledge_base_runtime_reconciliation_no_hard_delete" in sql
    assert "enable row level security" in sql
    assert "force row level security" in sql
    assert (
        "grant select, insert on table collabio.knowledge_base_runtime_reconciliation_evidence to collabio_app" in sql
    )
    assert (
        "grant update (active, deactivated_at_utc, deactivated_by, deactivation_reason, "
        "deactivation_reconciliation_evidence_hash) on table collabio.knowledge_base_runtime_activations "
        "to collabio_app" in sql
    )
    assert "source_text" not in sql
    assert "article_body" not in sql
    assert "prompt_text" not in sql
    assert "output_text" not in sql
    assert "raw_payload" not in sql
    assert "content_bytes" not in sql


def test_source_object_preview_decision_ledger_migration_is_metadata_only_and_rls_guarded() -> None:
    sql = normalized(get_migration("0031").sql())
    table = table_body(get_migration("0031").sql(), "collabio.source_object_preview_decision_evidence")

    for column in [
        "tenant_id",
        "source_object_id",
        "source_version_id",
        "source_object_type",
        "preview_slot_id",
        "preview_policy_id",
        "decision_status",
        "content_release_allowed",
        "content_included",
        "tenant_preview_policy_enabled",
        "required_content_release_evidence",
        "provided_evidence",
        "provided_evidence_refs",
        "missing_evidence",
        "blocking_reasons",
        "renderer_sandbox_evidence_ref",
        "backup_coverage_evidence_ref",
        "restore_evidence_ref",
        "human_confirmation_reference",
        "reason_hash",
        "evidence_hash",
    ]:
        assert column in table
    assert "decision_status = 'blocked'" in table
    assert "content_release_allowed = false" in table
    assert "content_included = false" in table
    assert "renderer_sandbox_worker_evidence" in table
    assert "backup_coverage_evidence" in table
    assert "restore_drill_evidence" in table
    assert "source_object_preview_decision_tenant_select" in sql
    assert "source_object_preview_decision_tenant_insert" in sql
    assert "source_object_preview_decision_no_update" in sql
    assert "source_object_preview_decision_no_hard_delete" in sql
    assert "enable row level security" in sql
    assert "force row level security" in sql
    assert "grant select, insert on table collabio.source_object_preview_decision_evidence to collabio_app" in sql
    assert "grant select on table collabio.source_object_preview_decision_evidence to collabio_worker" in sql
    assert "source_text" not in sql
    assert "mail_body" not in sql
    assert "attachment_bytes" not in sql
    assert "prompt_text" not in sql
    assert "output_text" not in sql
    assert "raw_payload" not in sql
    assert "content_bytes" not in sql


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
