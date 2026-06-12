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
