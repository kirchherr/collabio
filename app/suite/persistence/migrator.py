from __future__ import annotations

import hashlib
import os
from collections.abc import Iterable
from dataclasses import dataclass

import psycopg

from suite.persistence.migration_catalog import SqlMigration, load_migrations


@dataclass(frozen=True)
class MigrationRunResult:
    applied_versions: tuple[str, ...]
    skipped_versions: tuple[str, ...]


def migration_checksum(sql: str) -> str:
    return "sha256:" + hashlib.sha256(sql.encode("utf-8")).hexdigest()


def apply_migrations(database_dsn: str, migrations: Iterable[SqlMigration] | None = None) -> MigrationRunResult:
    catalog = tuple(load_migrations() if migrations is None else migrations)
    applied_versions: list[str] = []
    skipped_versions: list[str] = []

    with psycopg.connect(database_dsn) as connection:
        connection.execute("CREATE SCHEMA IF NOT EXISTS collabio")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS collabio.schema_migrations (
                version text PRIMARY KEY,
                name text NOT NULL,
                checksum text NOT NULL,
                applied_at_utc timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        connection.execute("LOCK TABLE collabio.schema_migrations IN ACCESS EXCLUSIVE MODE")

        for migration in catalog:
            sql = migration.sql()
            checksum = migration_checksum(sql)
            row = connection.execute(
                "SELECT checksum FROM collabio.schema_migrations WHERE version = %s",
                (migration.version,),
            ).fetchone()
            if row is not None:
                stored_checksum = str(row[0])
                if stored_checksum != checksum:
                    raise RuntimeError(
                        f"Migration {migration.version} checksum mismatch: stored {stored_checksum}, current {checksum}"
                    )
                skipped_versions.append(migration.version)
                continue

            connection.execute(sql)
            connection.execute(
                """
                INSERT INTO collabio.schema_migrations (version, name, checksum)
                VALUES (%s, %s, %s)
                """,
                (migration.version, migration.name, checksum),
            )
            applied_versions.append(migration.version)

        connection.commit()

    return MigrationRunResult(
        applied_versions=tuple(applied_versions),
        skipped_versions=tuple(skipped_versions),
    )


def migration_dsn_from_env() -> str:
    dsn = os.environ.get("SUITE_MIGRATION_DATABASE_DSN") or os.environ.get("SUITE_DATABASE_DSN")
    if not dsn:
        raise RuntimeError("SUITE_MIGRATION_DATABASE_DSN or SUITE_DATABASE_DSN must be set")
    return dsn


def main() -> None:
    result = apply_migrations(migration_dsn_from_env())
    print(
        "Applied migrations: "
        f"{','.join(result.applied_versions) or 'none'}; "
        f"skipped: {','.join(result.skipped_versions) or 'none'}"
    )


if __name__ == "__main__":
    main()
