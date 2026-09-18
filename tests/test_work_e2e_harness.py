from __future__ import annotations

from pathlib import Path

import pytest

from suite.testing.work_e2e_guard import (
    WORK_E2E_DATABASE_HOST,
    WORK_E2E_DATABASE_NAME,
    WORK_E2E_MODE,
    WORK_E2E_S3_ENDPOINT,
    WORK_E2E_TENANT_ID,
    require_isolated_work_e2e_environment,
)
from work_e2e_controls import WORK_E2E_READER_ID, permits_reader_acl_fixture, storage_failure_modes

REPO_ROOT = Path(__file__).parents[1]


def valid_environment() -> dict[str, str]:
    owner_dsn = f"postgresql://owner:secret@{WORK_E2E_DATABASE_HOST}:5432/{WORK_E2E_DATABASE_NAME}"
    app_dsn = f"postgresql://app:secret@{WORK_E2E_DATABASE_HOST}:5432/{WORK_E2E_DATABASE_NAME}"
    admin_dsn = f"postgresql://admin:secret@{WORK_E2E_DATABASE_HOST}:5432/{WORK_E2E_DATABASE_NAME}"
    return {
        "SUITE_WORK_E2E_MODE": WORK_E2E_MODE,
        "SUITE_WORK_E2E_TENANT_ID": WORK_E2E_TENANT_ID,
        "SUITE_WORK_E2E_ALLOW_SYNTHETIC_TRAFFIC": "1",
        "SUITE_ENV": "dev",
        "SUITE_AUTH_MODE": "dev",
        "SUITE_PRODUCTIVITY_PILOT_RUNTIME_ENABLED": "0",
        "SUITE_PRODUCTIVITY_PILOT_TRAFFIC_SCOPE_STORE_BACKEND": "memory",
        "SUITE_PRODUCTIVITY_PILOT_START_AUTHORIZATION_STORE_BACKEND": "memory",
        "SUITE_DATA_DIR": "/tmp/collabio-work-e2e-api",
        "SUITE_MIGRATION_DATABASE_DSN": owner_dsn,
        "SUITE_DATABASE_DSN": app_dsn,
        "SUITE_AUTHZ_ADMIN_DATABASE_DSN": admin_dsn,
        "SUITE_S3_ENDPOINT_URL": WORK_E2E_S3_ENDPOINT,
        "SUITE_KB_WRITE_APPROVAL_LEDGER_BACKEND": "postgres",
        "SUITE_KB_RUNTIME_ACTIVATION_STORE_BACKEND": "memory",
    }


def test_work_e2e_guard_accepts_only_explicit_isolated_configuration() -> None:
    assert require_isolated_work_e2e_environment(valid_environment()) is True
    blocked = valid_environment()
    blocked["SUITE_WORK_E2E_ALLOW_SYNTHETIC_TRAFFIC"] = "0"
    assert require_isolated_work_e2e_environment(blocked) is False


@pytest.mark.parametrize(
    ("key", "value"),
    (
        ("SUITE_WORK_E2E_MODE", "development"),
        ("SUITE_WORK_E2E_TENANT_ID", "tenant-demo"),
        ("SUITE_WORK_E2E_ALLOW_SYNTHETIC_TRAFFIC", "yes"),
        ("SUITE_ENV", "production"),
        ("SUITE_AUTH_MODE", "jwt"),
        ("SUITE_PRODUCTIVITY_PILOT_RUNTIME_ENABLED", "1"),
        ("SUITE_PRODUCTIVITY_PILOT_TRAFFIC_SCOPE_STORE_BACKEND", "postgres"),
        ("SUITE_PRODUCTIVITY_PILOT_START_AUTHORIZATION_STORE_BACKEND", "postgres"),
        ("SUITE_DATA_DIR", "/workspace/data"),
        ("SUITE_DATABASE_DSN", "postgresql://app:secret@postgres:5432/collabio"),
        ("SUITE_S3_ENDPOINT_URL", "http://minio:9000"),
        ("SUITE_S3_ENDPOINT_URL", "https://external.invalid"),
        ("SUITE_KB_WRITE_APPROVAL_LEDGER_BACKEND", "memory"),
        ("SUITE_KB_RUNTIME_ACTIVATION_STORE_BACKEND", "postgres"),
        ("SUITE_KB_RUNTIME_DATABASE_DSN", "postgresql://app:secret@postgres:5432/collabio"),
        ("SUITE_KB_WRITE_APPROVAL_LEDGER_DSN", "postgresql://app:secret@postgres:5432/collabio"),
    ),
)
def test_work_e2e_guard_fails_closed_outside_synthetic_boundary(key: str, value: str) -> None:
    environment = valid_environment()
    environment[key] = value
    with pytest.raises(RuntimeError):
        require_isolated_work_e2e_environment(environment)


def test_work_e2e_compose_profile_has_no_host_ports_and_keeps_runtime_switch_closed() -> None:
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    profile_start = compose.index("\n  work-e2e-postgres:\n")
    profile_end = compose.index("\n  test:\n", profile_start)
    profile = compose[profile_start:profile_end]

    assert 'profiles: ["work-e2e"]' in profile
    assert 'SUITE_PRODUCTIVITY_PILOT_RUNTIME_ENABLED: "0"' in profile
    assert "SUITE_PRODUCTIVITY_PILOT_TRAFFIC_SCOPE_STORE_BACKEND: memory" in profile
    assert "SUITE_PRODUCTIVITY_PILOT_START_AUTHORIZATION_STORE_BACKEND: memory" in profile
    assert 'SUITE_WORK_E2E_ALLOW_SYNTHETIC_TRAFFIC: "1"' in profile
    assert 'SUITE_WORK_E2E_ALLOW_SYNTHETIC_TRAFFIC: "0"' in profile
    assert "ports:" not in profile
    assert "./docker/postgres/initdb:/docker-entrypoint-initdb.d:ro" in profile
    assert 'user: "1000:1000"' in profile
    assert "create_host_path: false" in profile
    assert "work_e2e_internal" in profile
    assert "work-e2e-minio:" in profile
    assert "SUITE_S3_ENDPOINT_URL: http://work-e2e-minio:9000" in profile
    assert "/data:size=512m,uid=1000,gid=1000" in profile
    assert "minio_data" not in profile
    assert "cap_drop:" in profile
    assert "no-new-privileges:true" in profile


def test_work_e2e_runner_is_version_and_digest_pinned() -> None:
    dockerfile = (REPO_ROOT / "e2e" / "work" / "Dockerfile").read_text(encoding="utf-8")
    package = (REPO_ROOT / "e2e" / "work" / "package.json").read_text(encoding="utf-8")

    assert "mcr.microsoft.com/playwright:v1.63.0-noble@sha256:" in dockerfile
    assert '"@playwright/test": "1.63.0"' in package
    assert "npm ci --ignore-scripts" in dockerfile
    assert "USER pwuser" in dockerfile


@pytest.mark.parametrize("allow_traffic", (True, False))
def test_synthetic_read_failure_is_independent_of_write_and_pilot_switch(allow_traffic: bool) -> None:
    assert storage_failure_modes(
        tenant_id=WORK_E2E_TENANT_ID,
        method="GET",
        path="/v1/kb/articles/kb-article-test/content",
        requested=True,
        allow_synthetic_traffic=allow_traffic,
    ) == (False, True)
    assert storage_failure_modes(
        tenant_id=WORK_E2E_TENANT_ID,
        method="POST",
        path="/v1/admin/kb/articles/write-approvals/execute",
        requested=True,
        allow_synthetic_traffic=allow_traffic,
    ) == (allow_traffic, False)


@pytest.mark.parametrize(
    ("tenant_id", "method", "path", "requested"),
    (
        ("tenant-demo", "GET", "/v1/kb/articles/kb-article-test/content", True),
        (None, "GET", "/v1/kb/articles/kb-article-test/content", True),
        (WORK_E2E_TENANT_ID, "GET", "/v1/kb/articles/kb-article-test/content", False),
        (WORK_E2E_TENANT_ID, "POST", "/v1/kb/articles/kb-article-test/content", True),
        (WORK_E2E_TENANT_ID, "GET", "/v1/kb/articles", True),
        (WORK_E2E_TENANT_ID, "GET", "/v1/kb/articles/nested/id/content", True),
        (WORK_E2E_TENANT_ID, "GET", "/v1/admin/kb/articles/kb-article-test/edit-content", True),
        (WORK_E2E_TENANT_ID, "GET", "/v1/admin/kb/articles/write-approvals/execute", True),
        (WORK_E2E_TENANT_ID, "POST", "/v1/tasks/items", True),
    ),
)
def test_storage_failure_fixture_cannot_escape_exact_read_write_scope(
    tenant_id: str | None, method: str, path: str, requested: bool
) -> None:
    assert storage_failure_modes(
        tenant_id=tenant_id, method=method, path=path, requested=requested, allow_synthetic_traffic=True
    ) == (False, False)


@pytest.mark.parametrize(
    ("object_type", "prefix"), (("kb.article", "kb-article-"), ("kb.article_version", "kb-article-version-"))
)
def test_reader_acl_fixture_grants_only_synthetic_article_and_version_read(object_type: str, prefix: str) -> None:
    assert permits_reader_acl_fixture(
        tenant_id=WORK_E2E_TENANT_ID,
        object_id=prefix + "a" * 32,
        object_type=object_type,
        subject_type="user",
        subject_id=WORK_E2E_READER_ID,
        permission="read",
    )


@pytest.mark.parametrize(
    ("key", "value"),
    (
        ("tenant_id", "tenant-demo"),
        ("object_id", "kb-article-existing-demo"),
        ("object_id", "kb-article-version-" + "a" * 32),
        ("object_type", "task.item"),
        ("subject_type", "role"),
        ("subject_id", "work-user-e2e"),
        ("permission", "write"),
        ("permission", "admin"),
    ),
)
def test_reader_acl_fixture_rejects_broader_authorization(key: str, value: str) -> None:
    fields = {
        "tenant_id": WORK_E2E_TENANT_ID,
        "object_id": "kb-article-" + "a" * 32,
        "object_type": "kb.article",
        "subject_type": "user",
        "subject_id": WORK_E2E_READER_ID,
        "permission": "read",
    }
    fields[key] = value
    assert not permits_reader_acl_fixture(**fields)
