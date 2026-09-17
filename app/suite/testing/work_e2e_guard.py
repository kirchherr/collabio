from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import urlparse

WORK_E2E_MODE = "isolated-compose-test"
WORK_E2E_TENANT_ID = "tenant-work-e2e"
WORK_E2E_DATABASE_HOST = "work-e2e-postgres"
WORK_E2E_DATABASE_NAME = "collabio_work_e2e"


def require_isolated_work_e2e_environment(environ: Mapping[str, str]) -> bool:
    if environ.get("SUITE_WORK_E2E_MODE") != WORK_E2E_MODE:
        raise RuntimeError("Work E2E server requires the exact isolated Compose test marker")
    if environ.get("SUITE_ENV", "").strip().lower() != "dev":
        raise RuntimeError("Work E2E server is restricted to the development environment")
    if environ.get("SUITE_AUTH_MODE", "").strip().lower() != "dev":
        raise RuntimeError("Work E2E server requires development header authentication")
    if environ.get("SUITE_PRODUCTIVITY_PILOT_RUNTIME_ENABLED", "0") != "0":
        raise RuntimeError("Work E2E server must not enable the productivity pilot runtime switch")
    if environ.get("SUITE_WORK_E2E_TENANT_ID") != WORK_E2E_TENANT_ID:
        raise RuntimeError("Work E2E server is restricted to the synthetic tenant")

    allow_traffic = environ.get("SUITE_WORK_E2E_ALLOW_SYNTHETIC_TRAFFIC")
    if allow_traffic not in {"0", "1"}:
        raise RuntimeError("Work E2E synthetic traffic mode must be explicitly set to 0 or 1")

    data_dir = environ.get("SUITE_DATA_DIR", "")
    if not data_dir.startswith("/tmp/collabio-work-e2e-"):
        raise RuntimeError("Work E2E data must stay in its container-local temporary directory")

    for key in ("SUITE_MIGRATION_DATABASE_DSN", "SUITE_DATABASE_DSN", "SUITE_AUTHZ_ADMIN_DATABASE_DSN"):
        parsed = urlparse(environ.get(key, ""))
        if parsed.scheme not in {"postgres", "postgresql"}:
            raise RuntimeError(f"{key} must use PostgreSQL")
        if parsed.hostname != WORK_E2E_DATABASE_HOST or parsed.path != f"/{WORK_E2E_DATABASE_NAME}":
            raise RuntimeError(f"{key} must address only the ephemeral Work E2E database")

    return allow_traffic == "1"
