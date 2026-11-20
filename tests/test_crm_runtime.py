import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from suite.persistence.migrator import apply_migrations
from suite.platform.crm_accounts import InMemoryCrmAccountRepository
from suite.platform.crm_runtime import (
    PgCrmRepository,
    bootstrap_default_crm_runtime,
    build_default_crm_repositories,
)


@dataclass(frozen=True)
class LiveDatabase:
    migration_dsn: str
    app_dsn: str


def env_or_skip(name: str) -> str:
    value = os.environ.get(name)
    if value is None:
        pytest.skip(f"{name} is not configured")
    return value


@pytest.fixture(scope="module")
def live_database() -> LiveDatabase:
    migration_dsn = env_or_skip("SUITE_MIGRATION_DATABASE_DSN")
    app_dsn = env_or_skip("SUITE_DATABASE_DSN")
    apply_migrations(migration_dsn)
    return LiveDatabase(migration_dsn=migration_dsn, app_dsn=app_dsn)


def test_crm_repository_backend_is_explicit_and_compose_uses_postgres() -> None:
    memory = build_default_crm_repositories({"SUITE_CRM_REPOSITORY_BACKEND": "memory"})
    assert isinstance(memory.account_repository, InMemoryCrmAccountRepository)

    postgres = build_default_crm_repositories(
        {
            "SUITE_CRM_REPOSITORY_BACKEND": "postgres",
            "SUITE_DATABASE_DSN": "postgresql://app:secret@postgres/collabio",
        }
    )
    assert isinstance(postgres.account_repository, PgCrmRepository)
    assert postgres.account_repository is postgres.contact_repository
    assert postgres.account_repository is postgres.activity_repository
    assert postgres.account_repository is postgres.note_repository

    compose = (Path(__file__).parents[1] / "docker-compose.yml").read_text(encoding="utf-8")
    assert "SUITE_CRM_REPOSITORY_BACKEND: postgres" in compose
    assert "crm-runtime-bootstrap:" in compose


def test_postgres_crm_runtime_bootstrap_is_idempotent_and_tenant_scoped(live_database: LiveDatabase) -> None:
    env = {
        "SUITE_CRM_REPOSITORY_BACKEND": "postgres",
        "SUITE_CRM_REPOSITORY_DSN": live_database.app_dsn,
        "SUITE_CRM_RUNTIME_SEED_DEMO": "1",
    }
    first = bootstrap_default_crm_runtime(env)
    second = bootstrap_default_crm_runtime(env)
    repository = PgCrmRepository(database_dsn=live_database.app_dsn)

    demo_accounts = repository.list_accounts(tenant_id="tenant-demo")
    other_accounts = repository.list_accounts(tenant_id="tenant-other")
    demo_contacts = repository.list_contacts(tenant_id="tenant-demo")
    demo_activities = repository.list_activities(tenant_id="tenant-demo")
    demo_notes = repository.list_notes(tenant_id="tenant-demo")

    assert first.schema_version == "crm_runtime_bootstrap_report.v1"
    assert first.attempted_record_count == 12
    assert first.visible_record_count >= 12
    assert first.evidence_hash.startswith("sha256:")
    assert second.inserted_record_count == 0
    assert second.evidence_hash.startswith("sha256:")
    assert {record.object_id for record in demo_accounts} >= {
        "crm-account-acme-demo",
        "crm-account-northwind-demo",
    }
    assert {record.object_id for record in other_accounts} >= {"crm-account-other-tenant"}
    assert all(record.tenant_id == "tenant-demo" for record in demo_accounts)
    assert all(record.tenant_id == "tenant-demo" for record in demo_contacts)
    assert all(record.tenant_id == "tenant-demo" for record in demo_activities)
    assert all(record.tenant_id == "tenant-demo" for record in demo_notes)


def test_crm_runtime_bootstrap_requires_explicit_postgres_seed_enablement() -> None:
    with pytest.raises(ValueError, match="explicitly enabled"):
        bootstrap_default_crm_runtime(
            {
                "SUITE_CRM_REPOSITORY_BACKEND": "postgres",
                "SUITE_DATABASE_DSN": "postgresql://app:secret@postgres/collabio",
            }
        )
