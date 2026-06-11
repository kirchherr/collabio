from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

from suite.persistence.migration_catalog import SqlMigration, load_migrations


@dataclass(frozen=True)
class MigrationRunResult:
    applied_versions: tuple[str, ...]
    skipped_versions: tuple[str, ...]


class MigrationStartupBlocked(RuntimeError):
    pass


def migration_checksum(sql: str) -> str:
    return "sha256:" + hashlib.sha256(sql.encode("utf-8")).hexdigest()


def migration_evidence_json(migration: SqlMigration) -> str:
    return json.dumps(sorted(migration.evidence_refs), separators=(",", ":"))


def ensure_schema_migrations_table(connection: psycopg.Connection[Any]) -> None:
    connection.execute("CREATE SCHEMA IF NOT EXISTS collabio")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS collabio.schema_migrations (
            version text PRIMARY KEY,
            name text NOT NULL,
            module_id text NOT NULL DEFAULT 'core',
            checksum text NOT NULL,
            evidence_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
            blocks_startup boolean NOT NULL DEFAULT true,
            applied_at_utc timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    connection.execute("ALTER TABLE collabio.schema_migrations ADD COLUMN IF NOT EXISTS module_id text")
    connection.execute("UPDATE collabio.schema_migrations SET module_id = 'core' WHERE module_id IS NULL")
    connection.execute("ALTER TABLE collabio.schema_migrations ALTER COLUMN module_id SET NOT NULL")
    connection.execute("ALTER TABLE collabio.schema_migrations ALTER COLUMN module_id SET DEFAULT 'core'")
    connection.execute("ALTER TABLE collabio.schema_migrations ADD COLUMN IF NOT EXISTS evidence_refs jsonb")
    connection.execute("UPDATE collabio.schema_migrations SET evidence_refs = '[]'::jsonb WHERE evidence_refs IS NULL")
    connection.execute("ALTER TABLE collabio.schema_migrations ALTER COLUMN evidence_refs SET NOT NULL")
    connection.execute("ALTER TABLE collabio.schema_migrations ALTER COLUMN evidence_refs SET DEFAULT '[]'::jsonb")
    connection.execute("ALTER TABLE collabio.schema_migrations ADD COLUMN IF NOT EXISTS blocks_startup boolean")
    connection.execute("UPDATE collabio.schema_migrations SET blocks_startup = true WHERE blocks_startup IS NULL")
    connection.execute("ALTER TABLE collabio.schema_migrations ALTER COLUMN blocks_startup SET NOT NULL")
    connection.execute("ALTER TABLE collabio.schema_migrations ALTER COLUMN blocks_startup SET DEFAULT true")
    connection.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_app') THEN
                EXECUTE 'GRANT USAGE ON SCHEMA collabio TO collabio_app';
                EXECUTE 'GRANT SELECT ON TABLE collabio.schema_migrations TO collabio_app';
            END IF;
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'collabio_worker') THEN
                EXECUTE 'GRANT USAGE ON SCHEMA collabio TO collabio_worker';
                EXECUTE 'GRANT SELECT ON TABLE collabio.schema_migrations TO collabio_worker';
            END IF;
        END
        $$;
        """
    )


def stored_evidence_refs(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    loaded = json.loads(value) if isinstance(value, str) else value
    if not isinstance(loaded, list) or not all(isinstance(item, str) for item in loaded):
        raise MigrationStartupBlocked("Stored migration evidence_refs must be a JSON string array")
    return tuple(sorted(loaded))


def backfill_migration_metadata(
    connection: psycopg.Connection[Any],
    migration: SqlMigration,
) -> None:
    connection.execute(
        """
        UPDATE collabio.schema_migrations
        SET name = %s,
            module_id = %s,
            evidence_refs = %s::jsonb,
            blocks_startup = %s
        WHERE version = %s
        """,
        (
            migration.name,
            migration.module_id,
            migration_evidence_json(migration),
            migration.blocks_startup,
            migration.version,
        ),
    )


def apply_migrations(database_dsn: str, migrations: Iterable[SqlMigration] | None = None) -> MigrationRunResult:
    catalog = tuple(load_migrations() if migrations is None else migrations)
    applied_versions: list[str] = []
    skipped_versions: list[str] = []

    with psycopg.connect(database_dsn) as connection:
        ensure_schema_migrations_table(connection)
        connection.execute("LOCK TABLE collabio.schema_migrations IN ACCESS EXCLUSIVE MODE")

        for migration in catalog:
            sql = migration.sql()
            checksum = migration.checksum()
            row = connection.execute(
                "SELECT checksum FROM collabio.schema_migrations WHERE version = %s",
                (migration.version,),
            ).fetchone()
            if row is not None:
                stored_checksum = str(row[0])
                if stored_checksum != checksum:
                    raise MigrationStartupBlocked(
                        f"Migration {migration.version} checksum mismatch: stored {stored_checksum}, current {checksum}"
                    )
                backfill_migration_metadata(connection, migration)
                skipped_versions.append(migration.version)
                continue

            connection.execute(sql)
            connection.execute(
                """
                INSERT INTO collabio.schema_migrations (
                    version,
                    name,
                    module_id,
                    checksum,
                    evidence_refs,
                    blocks_startup
                )
                VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                """,
                (
                    migration.version,
                    migration.name,
                    migration.module_id,
                    checksum,
                    migration_evidence_json(migration),
                    migration.blocks_startup,
                ),
            )
            applied_versions.append(migration.version)

        connection.commit()

    return MigrationRunResult(
        applied_versions=tuple(applied_versions),
        skipped_versions=tuple(skipped_versions),
    )


def verify_migration_startup_state(database_dsn: str, migrations: Iterable[SqlMigration] | None = None) -> None:
    catalog = tuple(load_migrations() if migrations is None else migrations)
    by_version = {migration.version: migration for migration in catalog}

    with psycopg.connect(database_dsn, row_factory=dict_row) as connection:
        existing_table = connection.execute("SELECT to_regclass('collabio.schema_migrations')").fetchone()
        if existing_table is None or existing_table["to_regclass"] is None:
            raise MigrationStartupBlocked("schema_migrations table is missing")

        rows = connection.execute(
            """
            SELECT version, name, module_id, checksum, evidence_refs, blocks_startup
            FROM collabio.schema_migrations
            """
        ).fetchall()

    stored = {str(row["version"]): row for row in rows}
    for migration in catalog:
        row = stored.get(migration.version)
        if row is None:
            if migration.blocks_startup:
                raise MigrationStartupBlocked(f"Startup migration is missing: {migration.version}")
            continue

        expected_evidence_refs = tuple(sorted(migration.evidence_refs))
        if (
            row["name"] != migration.name
            or row["module_id"] != migration.module_id
            or row["checksum"] != migration.checksum()
            or stored_evidence_refs(row["evidence_refs"]) != expected_evidence_refs
            or bool(row["blocks_startup"]) != migration.blocks_startup
        ):
            raise MigrationStartupBlocked(f"Migration {migration.version} metadata mismatch")

    unknown_blocking_versions = sorted(
        version for version, row in stored.items() if version not in by_version and bool(row["blocks_startup"])
    )
    if unknown_blocking_versions:
        raise MigrationStartupBlocked(
            "Unknown startup-blocking migrations stored: " + ", ".join(unknown_blocking_versions)
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
