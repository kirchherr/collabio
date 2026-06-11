from dataclasses import dataclass
from importlib import resources


@dataclass(frozen=True)
class SqlMigration:
    version: str
    name: str
    resource_name: str

    def sql(self) -> str:
        return resources.files("suite.persistence.migrations").joinpath(self.resource_name).read_text(encoding="utf-8")


MIGRATIONS: tuple[SqlMigration, ...] = (
    SqlMigration(
        version="0001",
        name="pgvector_embeddings",
        resource_name="0001_pgvector_embeddings.sql",
    ),
    SqlMigration(
        version="0002",
        name="pgvector_lifecycle_worker_role",
        resource_name="0002_pgvector_lifecycle_worker_role.sql",
    ),
    SqlMigration(
        version="0003",
        name="pgvector_role_scoped_insert_policy",
        resource_name="0003_pgvector_role_scoped_insert_policy.sql",
    ),
    SqlMigration(
        version="0004",
        name="pgvector_role_scoped_update_policy",
        resource_name="0004_pgvector_role_scoped_update_policy.sql",
    ),
    SqlMigration(
        version="0005",
        name="pgvector_worker_write_policy",
        resource_name="0005_pgvector_worker_write_policy.sql",
    ),
    SqlMigration(
        version="0006",
        name="vector_metadata_guardrails",
        resource_name="0006_vector_metadata_guardrails.sql",
    ),
    SqlMigration(
        version="0007",
        name="platform_module_registry",
        resource_name="0007_platform_module_registry.sql",
    ),
    SqlMigration(
        version="0008",
        name="tenant_module_decommission_evidence",
        resource_name="0008_tenant_module_decommission_evidence.sql",
    ),
    SqlMigration(
        version="0009",
        name="tenant_module_decommission_completion",
        resource_name="0009_tenant_module_decommission_completion.sql",
    ),
)


def load_migrations() -> tuple[SqlMigration, ...]:
    return MIGRATIONS


def get_migration(version: str) -> SqlMigration:
    for migration in MIGRATIONS:
        if migration.version == version:
            return migration
    raise LookupError(f"Unknown migration version: {version}")
