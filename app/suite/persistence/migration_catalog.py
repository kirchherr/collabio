import hashlib
import re
from dataclasses import dataclass
from importlib import resources

MODULE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
NAMESPACED_REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")


@dataclass(frozen=True)
class SqlMigration:
    version: str
    name: str
    resource_name: str
    module_id: str
    evidence_refs: tuple[str, ...]
    blocks_startup: bool = True

    def __post_init__(self) -> None:
        if not self.version.isdigit() or len(self.version) != 4:
            raise ValueError("migration version must be a four digit string")
        if not self.name.strip():
            raise ValueError("migration name must not be empty")
        if not self.resource_name.endswith(".sql"):
            raise ValueError("migration resource_name must point to a SQL file")
        if not MODULE_ID_PATTERN.fullmatch(self.module_id):
            raise ValueError("migration module_id must be lowercase snake_case")
        if self.blocks_startup and not self.evidence_refs:
            raise ValueError("startup-blocking migrations require evidence references")
        for evidence_ref in self.evidence_refs:
            if not NAMESPACED_REF_PATTERN.fullmatch(evidence_ref):
                raise ValueError("migration evidence references must be namespaced references")

    def sql(self) -> str:
        return resources.files("suite.persistence.migrations").joinpath(self.resource_name).read_text(encoding="utf-8")

    def checksum(self) -> str:
        return "sha256:" + hashlib.sha256(self.sql().encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class MigrationManifestEntry:
    version: str
    name: str
    module_id: str
    checksum: str
    evidence_refs: tuple[str, ...]
    blocks_startup: bool


MIGRATIONS: tuple[SqlMigration, ...] = (
    SqlMigration(
        version="0001",
        name="pgvector_embeddings",
        resource_name="0001_pgvector_embeddings.sql",
        module_id="core",
        evidence_refs=("adr:pgvector-embeddings", "test:pgvector-migration"),
    ),
    SqlMigration(
        version="0002",
        name="pgvector_lifecycle_worker_role",
        resource_name="0002_pgvector_lifecycle_worker_role.sql",
        module_id="core",
        evidence_refs=("adr:pgvector-rls", "test:pgvector-worker-role"),
    ),
    SqlMigration(
        version="0003",
        name="pgvector_role_scoped_insert_policy",
        resource_name="0003_pgvector_role_scoped_insert_policy.sql",
        module_id="core",
        evidence_refs=("adr:pgvector-rls", "test:pgvector-insert-policy"),
    ),
    SqlMigration(
        version="0004",
        name="pgvector_role_scoped_update_policy",
        resource_name="0004_pgvector_role_scoped_update_policy.sql",
        module_id="core",
        evidence_refs=("adr:pgvector-rls", "test:pgvector-update-policy"),
    ),
    SqlMigration(
        version="0005",
        name="pgvector_worker_write_policy",
        resource_name="0005_pgvector_worker_write_policy.sql",
        module_id="core",
        evidence_refs=("adr:pgvector-worker", "test:pgvector-worker-write-policy"),
    ),
    SqlMigration(
        version="0006",
        name="vector_metadata_guardrails",
        resource_name="0006_vector_metadata_guardrails.sql",
        module_id="core",
        evidence_refs=("adr:vector-metadata", "test:vector-metadata-guardrails"),
    ),
    SqlMigration(
        version="0007",
        name="platform_module_registry",
        resource_name="0007_platform_module_registry.sql",
        module_id="core",
        evidence_refs=("adr:platform-module-system", "test:platform-module-registry"),
    ),
    SqlMigration(
        version="0008",
        name="tenant_module_decommission_evidence",
        resource_name="0008_tenant_module_decommission_evidence.sql",
        module_id="core",
        evidence_refs=("adr:platform-module-system", "test:module-decommission-request"),
    ),
    SqlMigration(
        version="0009",
        name="tenant_module_decommission_completion",
        resource_name="0009_tenant_module_decommission_completion.sql",
        module_id="core",
        evidence_refs=("adr:platform-module-system", "test:module-decommission-completion"),
    ),
    SqlMigration(
        version="0010",
        name="tenant_module_decommission_cancel_reopen",
        resource_name="0010_tenant_module_decommission_cancel_reopen.sql",
        module_id="core",
        evidence_refs=("adr:platform-module-system", "test:module-decommission-cancel-reopen"),
    ),
    SqlMigration(
        version="0011",
        name="tenant_module_migration_evidence",
        resource_name="0011_tenant_module_migration_evidence.sql",
        module_id="core",
        evidence_refs=("adr:platform-module-system", "test:module-provisioning-migration-evidence"),
    ),
    SqlMigration(
        version="0012",
        name="principal_authz_store",
        resource_name="0012_principal_authz_store.sql",
        module_id="core",
        evidence_refs=("doc:auth-context", "test:principal-authz-store"),
    ),
    SqlMigration(
        version="0013",
        name="jwt_replay_store",
        resource_name="0013_jwt_replay_store.sql",
        module_id="core",
        evidence_refs=("doc:auth-context", "test:jwt-replay-store"),
    ),
    SqlMigration(
        version="0014",
        name="audit_event_store",
        resource_name="0014_audit_event_store.sql",
        module_id="core",
        evidence_refs=("adr:audit-persistence", "test:audit-event-store"),
    ),
    SqlMigration(
        version="0015",
        name="authz_admin_runtime_role",
        resource_name="0015_authz_admin_runtime_role.sql",
        module_id="core",
        evidence_refs=("doc:auth-context", "test:authz-admin-store"),
    ),
    SqlMigration(
        version="0016",
        name="crm_erp_schema_scaffold",
        resource_name="0016_crm_erp_schema_scaffold.sql",
        module_id="crm_erp",
        evidence_refs=("doc:crm-erp-object-rules", "test:crm-erp-schema-scaffold"),
    ),
    SqlMigration(
        version="0017",
        name="crm_accounts",
        resource_name="0017_crm_accounts.sql",
        module_id="crm_erp",
        evidence_refs=("doc:crm-accounts-vertical-slice", "test:crm-accounts-slice"),
    ),
    SqlMigration(
        version="0018",
        name="crm_contacts",
        resource_name="0018_crm_contacts.sql",
        module_id="crm_erp",
        evidence_refs=("doc:crm-contacts-vertical-slice", "test:crm-contacts-slice"),
    ),
    SqlMigration(
        version="0019",
        name="crm_activities_notes",
        resource_name="0019_crm_activities_notes.sql",
        module_id="crm_erp",
        evidence_refs=("doc:crm-activities-notes-vertical-slice", "test:crm-activities-notes-slice"),
    ),
    SqlMigration(
        version="0020",
        name="erp_products",
        resource_name="0020_erp_products.sql",
        module_id="crm_erp",
        evidence_refs=("doc:erp-products-vertical-slice", "test:erp-products-slice"),
    ),
    SqlMigration(
        version="0021",
        name="knowledge_base_articles",
        resource_name="0021_knowledge_base_articles.sql",
        module_id="knowledge_base",
        evidence_refs=("doc:knowledge-base-articles-vertical-slice", "test:knowledge-base-articles-slice"),
    ),
    SqlMigration(
        version="0022",
        name="knowledge_base_source_restore_evidence",
        resource_name="0022_knowledge_base_source_restore_evidence.sql",
        module_id="knowledge_base",
        evidence_refs=("doc:knowledge-base-source-restore-evidence", "test:knowledge-base-evidence-slice"),
    ),
    SqlMigration(
        version="0023",
        name="knowledge_base_write_approval_evidence",
        resource_name="0023_knowledge_base_write_approval_evidence.sql",
        module_id="knowledge_base",
        evidence_refs=("doc:knowledge-base-write-approval-ledger", "test:knowledge-base-write-approval-ledger"),
    ),
    SqlMigration(
        version="0024",
        name="knowledge_base_write_approval_transition_lineage",
        resource_name="0024_knowledge_base_write_approval_transition_lineage.sql",
        module_id="knowledge_base",
        evidence_refs=(
            "doc:knowledge-base-write-approval-ledger",
            "test:knowledge-base-write-approval-transition",
        ),
    ),
    SqlMigration(
        version="0025",
        name="knowledge_base_write_approval_trusted_article_metadata",
        resource_name="0025_knowledge_base_write_approval_trusted_article_metadata.sql",
        module_id="knowledge_base",
        evidence_refs=(
            "doc:knowledge-base-write-approval-ledger",
            "test:knowledge-base-write-approval-create",
        ),
    ),
    SqlMigration(
        version="0026",
        name="source_object_write_receipts",
        resource_name="0026_source_object_write_receipts.sql",
        module_id="core",
        evidence_refs=("doc:source-object-model", "test:source-object-write-receipts"),
    ),
    SqlMigration(
        version="0027",
        name="source_object_metadata_storage_bridge",
        resource_name="0027_source_object_metadata_storage_bridge.sql",
        module_id="core",
        evidence_refs=("doc:source-object-model", "test:source-object-storage-bridge"),
    ),
    SqlMigration(
        version="0028",
        name="knowledge_base_runtime_activation",
        resource_name="0028_knowledge_base_runtime_activation.sql",
        module_id="knowledge_base",
        evidence_refs=("doc:knowledge-base-source-restore-evidence", "test:knowledge-base-runtime-activation"),
    ),
    SqlMigration(
        version="0029",
        name="knowledge_base_runtime_reconciliation",
        resource_name="0029_knowledge_base_runtime_reconciliation.sql",
        module_id="knowledge_base",
        evidence_refs=("doc:knowledge-base-source-restore-evidence", "test:knowledge-base-runtime-reconciliation"),
    ),
    SqlMigration(
        version="0030",
        name="platform_module_registry_runtime_store",
        resource_name="0030_platform_module_registry_runtime_store.sql",
        module_id="core",
        evidence_refs=("adr:platform-module-system", "test:platform-module-registry-runtime-store"),
    ),
    SqlMigration(
        version="0031",
        name="source_object_preview_decision_ledger",
        resource_name="0031_source_object_preview_decision_ledger.sql",
        module_id="core",
        evidence_refs=(
            "doc:source-object-preview-decision-ledger",
            "test:source-object-preview-decision-ledger",
        ),
    ),
    SqlMigration(
        version="0032",
        name="source_object_preview_renderer_evidence",
        resource_name="0032_source_object_preview_renderer_evidence.sql",
        module_id="core",
        evidence_refs=(
            "doc:source-object-preview-renderer-sandbox",
            "test:source-object-preview-renderer-evidence",
        ),
    ),
    SqlMigration(
        version="0033",
        name="source_object_preview_renderer_release_gate_evidence",
        resource_name="0033_source_object_preview_renderer_release_gate_evidence.sql",
        module_id="core",
        evidence_refs=(
            "doc:source-object-preview-renderer-sandbox",
            "test:source-object-preview-renderer-release-gate-evidence",
        ),
    ),
    SqlMigration(
        version="0034",
        name="legacy_sql_evidence_ledger",
        resource_name="0034_legacy_sql_evidence_ledger.sql",
        module_id="crm_erp",
        evidence_refs=(
            "doc:legacy-sql-discovery",
            "test:legacy-sql-evidence-ledger",
        ),
    ),
    SqlMigration(
        version="0035",
        name="legacy_sql_host_profile_release_gate_evidence",
        resource_name="0035_legacy_sql_host_profile_release_gate_evidence.sql",
        module_id="crm_erp",
        evidence_refs=(
            "doc:legacy-sql-discovery",
            "test:legacy-sql-host-profile-release-gate",
        ),
    ),
    SqlMigration(
        version="0036",
        name="legacy_sql_metadata_worker_queue",
        resource_name="0036_legacy_sql_metadata_worker_queue.sql",
        module_id="crm_erp",
        evidence_refs=(
            "doc:legacy-sql-discovery",
            "test:legacy-sql-metadata-worker-queue",
        ),
    ),
    SqlMigration(
        version="0037",
        name="legacy_sql_real_connection_executor_policy_store",
        resource_name="0037_legacy_sql_real_connection_executor_policy_store.sql",
        module_id="crm_erp",
        evidence_refs=(
            "doc:legacy-sql-discovery",
            "test:legacy-sql-real-connection-executor-policy-store",
        ),
    ),
    SqlMigration(
        version="0038",
        name="legacy_sql_postgres_metadata_probe_provider_constraints",
        resource_name="0038_legacy_sql_postgres_metadata_probe_provider_constraints.sql",
        module_id="crm_erp",
        evidence_refs=(
            "doc:legacy-sql-discovery",
            "test:legacy-sql-metadata-connection-probe-live-adapter",
        ),
    ),
    SqlMigration(
        version="0039",
        name="crm_erp_legacy_staging_metadata_profiles",
        resource_name="0039_crm_erp_legacy_staging_metadata_profiles.sql",
        module_id="crm_erp",
        evidence_refs=(
            "doc:legacy-sql-discovery",
            "test:crm-erp-legacy-staging-metadata-profiles",
        ),
    ),
    SqlMigration(
        version="0040",
        name="crm_erp_legacy_import_dry_run_plans",
        resource_name="0040_crm_erp_legacy_import_dry_run_plans.sql",
        module_id="crm_erp",
        evidence_refs=(
            "doc:legacy-sql-discovery",
            "test:crm-erp-legacy-import-dry-run-plan",
        ),
    ),
    SqlMigration(
        version="0041",
        name="crm_erp_legacy_import_dry_run_results",
        resource_name="0041_crm_erp_legacy_import_dry_run_results.sql",
        module_id="crm_erp",
        evidence_refs=(
            "doc:legacy-sql-discovery",
            "test:legacy-sql-import-dry-run-worker",
        ),
    ),
    SqlMigration(
        version="0042",
        name="crm_erp_legacy_import_write_approval_gates",
        resource_name="0042_crm_erp_legacy_import_write_approval_gates.sql",
        module_id="crm_erp",
        evidence_refs=(
            "doc:legacy-sql-discovery",
            "test:legacy-sql-import-write-approval-gate",
        ),
    ),
    SqlMigration(
        version="0043",
        name="crm_erp_legacy_import_write_approval_records",
        resource_name="0043_crm_erp_legacy_import_write_approval_records.sql",
        module_id="crm_erp",
        evidence_refs=(
            "doc:legacy-sql-discovery",
            "test:legacy-sql-import-write-approval-record-store",
        ),
    ),
    SqlMigration(
        version="0044",
        name="crm_erp_legacy_migration_run_registry",
        resource_name="0044_crm_erp_legacy_migration_run_registry.sql",
        module_id="crm_erp",
        evidence_refs=(
            "doc:legacy-sql-discovery",
            "test:legacy-sql-migration-run-registry-skeleton",
        ),
    ),
    SqlMigration(
        version="0045",
        name="lms_catalog_registration",
        resource_name="0045_lms_catalog_registration.sql",
        module_id="lms",
        evidence_refs=(
            "doc:lms-module-charter",
            "test:lms-catalog-registration",
        ),
    ),
    SqlMigration(
        version="0046",
        name="lms_metadata_schema",
        resource_name="0046_lms_metadata_schema.sql",
        module_id="lms",
        evidence_refs=(
            "doc:lms-module-charter",
            "test:lms-metadata-schema",
        ),
    ),
    SqlMigration(
        version="0047",
        name="lms_package_install_approval_records",
        resource_name="0047_lms_package_install_approval_records.sql",
        module_id="lms",
        evidence_refs=(
            "doc:lms-module-charter",
            "test:lms-package-install-approval-records",
        ),
    ),
    SqlMigration(
        version="0048",
        name="lms_dry_run_execution_approval_records",
        resource_name="0048_lms_dry_run_execution_approval_records.sql",
        module_id="lms",
        evidence_refs=(
            "doc:lms-module-charter",
            "test:lms-dry-run-execution-approval-records",
        ),
    ),
    SqlMigration(
        version="0049",
        name="lms_dry_run_execution_job_outbox",
        resource_name="0049_lms_dry_run_execution_job_outbox.sql",
        module_id="lms",
        evidence_refs=(
            "doc:lms-module-charter",
            "test:lms-dry-run-execution-job-outbox",
        ),
    ),
    SqlMigration(
        version="0050",
        name="tasks_activities_catalog_registration",
        resource_name="0050_tasks_activities_catalog_registration.sql",
        module_id="tasks_activities",
        evidence_refs=(
            "doc:tasks-activities-module-charter",
            "test:tasks-activities-catalog-registration",
        ),
    ),
    SqlMigration(
        version="0051",
        name="tickets_incidents_catalog_registration",
        resource_name="0051_tickets_incidents_catalog_registration.sql",
        module_id="tickets_incidents",
        evidence_refs=(
            "doc:tickets-incidents-module-charter",
            "test:tickets-incidents-catalog-registration",
        ),
    ),
    SqlMigration(
        version="0052",
        name="tickets_incidents_metadata_schema",
        resource_name="0052_tickets_incidents_metadata_schema.sql",
        module_id="tickets_incidents",
        evidence_refs=(
            "doc:tickets-incidents-module-charter",
            "test:tickets-incidents-metadata-schema",
        ),
    ),
    SqlMigration(
        version="0053",
        name="tickets_incidents_dry_run_execution_approval_records",
        resource_name="0053_tickets_incidents_dry_run_execution_approval_records.sql",
        module_id="tickets_incidents",
        evidence_refs=(
            "doc:tickets-incidents-module-charter",
            "test:tickets-incidents-dry-run-execution-approval-records",
        ),
    ),
    SqlMigration(
        version="0054",
        name="tickets_incidents_controlled_pilot",
        resource_name="0054_tickets_incidents_controlled_pilot.sql",
        module_id="tickets_incidents",
        evidence_refs=(
            "doc:tickets-incidents-module-charter",
            "test:tickets-incidents-controlled-pilot",
        ),
    ),
    SqlMigration(
        version="0055",
        name="source_object_preview_content_release_receipts",
        resource_name="0055_source_object_preview_content_release_receipts.sql",
        module_id="core",
        evidence_refs=(
            "doc:source-object-preview-content-release",
            "test:source-object-preview-content-release",
        ),
    ),
    SqlMigration(
        version="0056",
        name="source_object_preview_content_release_nonempty",
        resource_name="0056_source_object_preview_content_release_nonempty.sql",
        module_id="core",
        evidence_refs=(
            "doc:source-object-preview-content-release",
            "test:source-object-preview-content-release",
        ),
    ),
    SqlMigration(
        version="0057",
        name="crm_atomic_account_onboarding",
        resource_name="0057_crm_atomic_account_onboarding.sql",
        module_id="crm_erp",
        evidence_refs=("doc:crm-account-onboarding", "test:crm-atomic-account-onboarding"),
    ),
    SqlMigration(
        version="0058",
        name="tenant_module_migration_evidence_reconciliation",
        resource_name="0058_tenant_module_migration_evidence_reconciliation.sql",
        module_id="core",
        evidence_refs=(
            "adr:platform-module-system",
            "test:tenant-module-migration-evidence-reconciliation",
        ),
    ),
    SqlMigration(
        version="0059",
        name="tasks_activities_productive_slice",
        resource_name="0059_tasks_activities_productive_slice.sql",
        module_id="tasks_activities",
        evidence_refs=("doc:tasks-activities-productive-slice", "test:tasks-activities-productive-slice"),
    ),
    SqlMigration(
        version="0060",
        name="time_tracking_productive_slice",
        resource_name="0060_time_tracking_productive_slice.sql",
        module_id="time_tracking",
        evidence_refs=("doc:time-tracking-module-charter", "test:time-tracking-productive-slice"),
    ),
    SqlMigration(
        version="0061",
        name="productivity_pilot_admission",
        resource_name="0061_productivity_pilot_admission.sql",
        module_id="core",
        evidence_refs=("doc:productivity-pilot-admission", "test:productivity-pilot-admission"),
    ),
    SqlMigration(
        version="0062",
        name="productivity_pilot_traffic_scope",
        resource_name="0062_productivity_pilot_traffic_scope.sql",
        module_id="core",
        evidence_refs=("doc:productivity-pilot-traffic-scope", "test:productivity-pilot-traffic-scope"),
    ),
    SqlMigration(
        version="0063",
        name="productivity_pilot_start_authorization",
        resource_name="0063_productivity_pilot_start_authorization.sql",
        module_id="core",
        evidence_refs=("doc:productivity-pilot-start-authorization", "test:productivity-pilot-start-authorization"),
    ),
    SqlMigration(
        version="0064",
        name="productivity_pilot_runtime_window",
        resource_name="0064_productivity_pilot_runtime_window.sql",
        module_id="core",
        evidence_refs=("doc:productivity-pilot-runtime-window", "test:productivity-pilot-runtime-window"),
    ),
    SqlMigration(
        version="0065",
        name="productivity_pilot_closure_report",
        resource_name="0065_productivity_pilot_closure_report.sql",
        module_id="core",
        evidence_refs=("doc:productivity-pilot-closure-report", "test:productivity-pilot-closure-report"),
    ),
    SqlMigration(
        version="0066",
        name="productivity_pilot_real_user_admission",
        resource_name="0066_productivity_pilot_real_user_admission.sql",
        module_id="core",
        evidence_refs=(
            "doc:productivity-pilot-real-user-admission",
            "test:productivity-pilot-real-user-admission",
        ),
    ),
    SqlMigration(
        version="0067",
        name="productivity_pilot_real_user_runtime_window",
        resource_name="0067_productivity_pilot_real_user_runtime_window.sql",
        module_id="core",
        evidence_refs=(
            "doc:productivity-pilot-real-user-runtime-window",
            "test:productivity-pilot-real-user-runtime-window",
        ),
    ),
    SqlMigration(
        version="0068",
        name="productivity_pilot_real_user_runtime_policy_name",
        resource_name="0068_productivity_pilot_real_user_runtime_policy_name.sql",
        module_id="core",
        evidence_refs=(
            "doc:productivity-pilot-real-user-runtime-window",
            "test:productivity-pilot-real-user-runtime-window",
        ),
    ),
    SqlMigration(
        version="0069",
        name="productivity_pilot_real_user_closure_report",
        resource_name="0069_productivity_pilot_real_user_closure_report.sql",
        module_id="core",
        evidence_refs=(
            "doc:productivity-pilot-real-user-closure-report",
            "test:productivity-pilot-real-user-closure-report",
        ),
    ),
    SqlMigration(
        version="0070",
        name="productivity_pilot_real_user_closure_owner_refs",
        resource_name="0070_productivity_pilot_real_user_closure_owner_refs.sql",
        module_id="core",
        evidence_refs=(
            "doc:productivity-pilot-real-user-closure-report",
            "test:productivity-pilot-real-user-closure-report",
        ),
    ),
    SqlMigration(
        version="0071",
        name="productivity_pilot_real_user_runtime_owner_ref",
        resource_name="0071_productivity_pilot_real_user_runtime_owner_ref.sql",
        module_id="core",
        evidence_refs=(
            "doc:productivity-pilot-real-user-runtime-window",
            "test:productivity-pilot-real-user-runtime-window",
        ),
    ),
    SqlMigration(
        version="0072",
        name="source_object_preview_conversion_lifecycle",
        resource_name="0072_source_object_preview_conversion_lifecycle.sql",
        module_id="core",
        evidence_refs=(
            "adr:renderer-viewer-adapter",
            "test:source-object-preview-conversion",
        ),
    ),
)


def load_migrations() -> tuple[SqlMigration, ...]:
    return MIGRATIONS


def get_migration(version: str) -> SqlMigration:
    for migration in MIGRATIONS:
        if migration.version == version:
            return migration
    raise LookupError(f"Unknown migration version: {version}")


def load_module_migrations(module_id: str) -> tuple[SqlMigration, ...]:
    if not MODULE_ID_PATTERN.fullmatch(module_id):
        raise ValueError("module_id must be lowercase snake_case")
    return tuple(migration for migration in MIGRATIONS if migration.module_id == module_id)


def load_migration_manifest() -> tuple[MigrationManifestEntry, ...]:
    return tuple(
        MigrationManifestEntry(
            version=migration.version,
            name=migration.name,
            module_id=migration.module_id,
            checksum=migration.checksum(),
            evidence_refs=tuple(sorted(migration.evidence_refs)),
            blocks_startup=migration.blocks_startup,
        )
        for migration in MIGRATIONS
    )
