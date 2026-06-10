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
)


def load_migrations() -> tuple[SqlMigration, ...]:
    return MIGRATIONS


def get_migration(version: str) -> SqlMigration:
    for migration in MIGRATIONS:
        if migration.version == version:
            return migration
    raise LookupError(f"Unknown migration version: {version}")
