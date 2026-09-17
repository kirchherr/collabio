from __future__ import annotations

from pathlib import Path

import pytest

from suite.testing.work_e2e_guard import (
    WORK_E2E_DATABASE_HOST,
    WORK_E2E_DATABASE_NAME,
    WORK_E2E_MODE,
    WORK_E2E_TENANT_ID,
    require_isolated_work_e2e_environment,
)

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
    assert "SUITE_PRODUCTIVITY_PILOT_RUNTIME_ENABLED: \"0\"" in profile
    assert "SUITE_PRODUCTIVITY_PILOT_TRAFFIC_SCOPE_STORE_BACKEND: memory" in profile
    assert "SUITE_PRODUCTIVITY_PILOT_START_AUTHORIZATION_STORE_BACKEND: memory" in profile
    assert "SUITE_WORK_E2E_ALLOW_SYNTHETIC_TRAFFIC: \"1\"" in profile
    assert "SUITE_WORK_E2E_ALLOW_SYNTHETIC_TRAFFIC: \"0\"" in profile
    assert "ports:" not in profile
    assert "./docker/postgres/initdb:/docker-entrypoint-initdb.d:ro" in profile
    assert 'user: "1000:1000"' in profile
    assert "create_host_path: false" in profile
    assert "work_e2e_internal" in profile
    assert "cap_drop:" in profile
    assert "no-new-privileges:true" in profile


def test_work_e2e_runner_is_version_and_digest_pinned() -> None:
    dockerfile = (REPO_ROOT / "e2e" / "work" / "Dockerfile").read_text(encoding="utf-8")
    package = (REPO_ROOT / "e2e" / "work" / "package.json").read_text(encoding="utf-8")

    assert "mcr.microsoft.com/playwright:v1.63.0-noble@sha256:" in dockerfile
    assert '"@playwright/test": "1.63.0"' in package
    assert "npm ci --ignore-scripts" in dockerfile
    assert "USER pwuser" in dockerfile
