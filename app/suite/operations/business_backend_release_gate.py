from __future__ import annotations

import json
import os
import time
from collections.abc import Collection, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import psycopg
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

from suite.operations.backend_foundation_completion_gate import (
    BackendFoundationCompletionGate,
    build_backend_foundation_completion_gate_hash,
    load_backend_foundation_completion_gate,
)
from suite.persistence.migration_catalog import load_migrations
from suite.storage.source_objects import sha256_bytes


class ProductiveSliceDefinition(BaseModel):
    slice_id: str
    module_id: str
    required_migration_versions: tuple[str, ...]
    required_api_operations: tuple[str, ...]
    backend_environment_variable: str
    restore_control_field: str


PRODUCTIVE_SLICES: tuple[ProductiveSliceDefinition, ...] = (
    ProductiveSliceDefinition(
        slice_id="crm_account_onboarding",
        module_id="crm_erp",
        required_migration_versions=("0057",),
        required_api_operations=("POST /v1/crm/account-onboardings",),
        backend_environment_variable="SUITE_CRM_ONBOARDING_BACKEND",
        restore_control_field="crm_atomic_write_controls_verified",
    ),
    ProductiveSliceDefinition(
        slice_id="tasks_activities",
        module_id="tasks_activities",
        required_migration_versions=("0050", "0059"),
        required_api_operations=(
            "POST /v1/tasks/items",
            "GET /v1/tasks/items",
            "GET /v1/tasks/activities",
        ),
        backend_environment_variable="SUITE_TASKS_ACTIVITIES_BACKEND",
        restore_control_field="tasks_activities_write_controls_verified",
    ),
    ProductiveSliceDefinition(
        slice_id="time_tracking",
        module_id="time_tracking",
        required_migration_versions=("0060",),
        required_api_operations=(
            "POST /v1/time-tracking/entries",
            "GET /v1/time-tracking/entries",
            "GET /v1/time-tracking/approvals",
        ),
        backend_environment_variable="SUITE_TIME_TRACKING_BACKEND",
        restore_control_field="time_tracking_write_controls_verified",
    ),
)


class BusinessSliceReleaseEvidence(BaseModel):
    slice_id: str
    module_id: str
    required_migration_versions: tuple[str, ...]
    required_api_operations: tuple[str, ...]
    module_catalog_status: str
    module_catalog_entry_present: bool
    module_package_installed: bool
    migration_catalog_verified: bool
    module_required_migrations_verified: bool
    api_operations_verified: bool
    postgres_backend_verified: bool
    restore_write_controls_verified: bool
    blocking_reasons: tuple[str, ...] = ()
    release_ready: bool
    schema_version: str = "business_slice_release_evidence.v1"


class BusinessBackendReleaseGate(BaseModel):
    checked_at_utc: str
    runtime_environment: str
    backend_foundation_gate_hash: str
    backend_foundation_complete: bool
    api_health_verified: bool
    api_openapi_contract_verified: bool
    module_catalog_manifest_hash: str
    productive_slice_count: int = Field(ge=1)
    release_ready_slice_count: int = Field(ge=0)
    slices: tuple[BusinessSliceReleaseEvidence, ...]
    metadata_only_evidence_verified: bool
    tenant_activation_executed: bool = False
    business_write_executed: bool = False
    content_included: bool = False
    blocking_reasons: tuple[str, ...] = ()
    release_ready: bool
    gate_hash: str
    schema_version: str = "business_backend_release_gate.v1"


def _catalog_manifest_hash(rows: Sequence[Mapping[str, object]]) -> str:
    normalized = [
        {
            "module_id": str(row["module_id"]),
            "required_migration_versions": sorted(_required_versions(row)),
            "status": str(row["status"]),
        }
        for row in rows
    ]
    return sha256_bytes(
        json.dumps(
            sorted(normalized, key=lambda item: item["module_id"]), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    )


def _required_versions(row: Mapping[str, object]) -> set[str]:
    value = row["required_migration_versions"]
    if not isinstance(value, (list, tuple)):
        raise ValueError("module catalog required_migration_versions must be a list")
    return {str(item) for item in value}


def build_business_backend_release_gate(
    *,
    backend_gate: BackendFoundationCompletionGate,
    module_catalog_rows: Sequence[Mapping[str, object]],
    api_operations: Collection[str],
    api_health_verified: bool,
    backend_settings: Mapping[str, str],
    checked_at_utc: str | None = None,
) -> BusinessBackendReleaseGate:
    if build_backend_foundation_completion_gate_hash(backend_gate) != backend_gate.gate_hash:
        raise ValueError("backend foundation completion gate hash is invalid")
    catalog_by_module = {str(row["module_id"]): row for row in module_catalog_rows}
    available_migrations = {(migration.module_id, migration.version) for migration in load_migrations()}
    normalized_operations = {operation.strip() for operation in api_operations}
    slice_evidence: list[BusinessSliceReleaseEvidence] = []

    for definition in PRODUCTIVE_SLICES:
        catalog_row = catalog_by_module.get(definition.module_id)
        catalog_versions = _required_versions(catalog_row) if catalog_row else set()
        catalog_status = str(catalog_row["status"]) if catalog_row else "missing"
        checks = {
            "module_catalog_entry_missing": catalog_row is not None,
            "module_package_not_installed": catalog_status == "installed",
            "migration_not_registered_in_code": all(
                (definition.module_id, version) in available_migrations
                for version in definition.required_migration_versions
            ),
            "module_required_migration_missing": set(definition.required_migration_versions).issubset(catalog_versions),
            "api_operation_missing": set(definition.required_api_operations).issubset(normalized_operations),
            "non_postgres_backend_configured": backend_settings.get(definition.backend_environment_variable, "")
            .strip()
            .lower()
            in {"postgres", "postgresql", "pg"},
            "restore_write_controls_not_verified": bool(getattr(backend_gate, definition.restore_control_field)),
        }
        blocking_reasons = tuple(sorted(reason for reason, passed in checks.items() if not passed))
        slice_evidence.append(
            BusinessSliceReleaseEvidence(
                slice_id=definition.slice_id,
                module_id=definition.module_id,
                required_migration_versions=definition.required_migration_versions,
                required_api_operations=definition.required_api_operations,
                module_catalog_status=catalog_status,
                module_catalog_entry_present=checks["module_catalog_entry_missing"],
                module_package_installed=checks["module_package_not_installed"],
                migration_catalog_verified=checks["migration_not_registered_in_code"],
                module_required_migrations_verified=checks["module_required_migration_missing"],
                api_operations_verified=checks["api_operation_missing"],
                postgres_backend_verified=checks["non_postgres_backend_configured"],
                restore_write_controls_verified=checks["restore_write_controls_not_verified"],
                blocking_reasons=blocking_reasons,
                release_ready=not blocking_reasons,
            )
        )

    openapi_contract_verified = all(item.api_operations_verified for item in slice_evidence)
    global_checks = {
        "backend_foundation_not_complete": backend_gate.backend_foundation_complete,
        "api_health_not_verified": api_health_verified,
        "api_openapi_contract_not_verified": openapi_contract_verified,
    }
    global_blocking_reasons = [reason for reason, passed in global_checks.items() if not passed]
    global_blocking_reasons.extend(
        f"slice_not_ready:{item.slice_id}" for item in slice_evidence if not item.release_ready
    )
    ready = not global_blocking_reasons
    draft = BusinessBackendReleaseGate(
        checked_at_utc=checked_at_utc or datetime.now(UTC).isoformat(),
        runtime_environment=backend_gate.runtime_environment,
        backend_foundation_gate_hash=backend_gate.gate_hash,
        backend_foundation_complete=backend_gate.backend_foundation_complete,
        api_health_verified=api_health_verified,
        api_openapi_contract_verified=openapi_contract_verified,
        module_catalog_manifest_hash=_catalog_manifest_hash(module_catalog_rows),
        productive_slice_count=len(slice_evidence),
        release_ready_slice_count=sum(item.release_ready for item in slice_evidence),
        slices=tuple(slice_evidence),
        metadata_only_evidence_verified=True,
        blocking_reasons=tuple(sorted(global_blocking_reasons)),
        release_ready=ready,
        gate_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"gate_hash": build_business_backend_release_gate_hash(draft)})


def build_business_backend_release_gate_hash(gate: BusinessBackendReleaseGate) -> str:
    return sha256_bytes(
        json.dumps(
            gate.model_dump(mode="json", exclude={"gate_hash"}),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def _read_json_url(*, url: str, retries: int, retry_delay_seconds: float) -> Any:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            request = Request(url, headers={"Accept": "application/json"})
            with urlopen(request, timeout=3) as response:
                return json.loads(response.read())
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            if attempt + 1 < retries:
                time.sleep(retry_delay_seconds)
    raise RuntimeError(f"release gate could not read {url}") from last_error


def _load_runtime_evidence(env: Mapping[str, str]) -> tuple[list[dict[str, object]], set[str], bool]:
    module_ids = tuple(definition.module_id for definition in PRODUCTIVE_SLICES)
    with psycopg.connect(env["SUITE_POSTGRES_RESTORE_SOURCE_DSN"], row_factory=dict_row) as connection:
        rows = connection.execute(
            """
            SELECT module_id, status, required_migration_versions
            FROM collabio.module_catalog
            WHERE module_id = ANY(%s)
            ORDER BY module_id
            """,
            (list(module_ids),),
        ).fetchall()

    base_url = env.get("SUITE_RELEASE_API_BASE_URL", "http://api:8000").rstrip("/")
    retries = int(env.get("SUITE_RELEASE_API_RETRIES", "30"))
    retry_delay_seconds = float(env.get("SUITE_RELEASE_API_RETRY_DELAY_SECONDS", "1"))
    health = _read_json_url(
        url=f"{base_url}/health",
        retries=retries,
        retry_delay_seconds=retry_delay_seconds,
    )
    openapi = _read_json_url(
        url=f"{base_url}/openapi.json",
        retries=retries,
        retry_delay_seconds=retry_delay_seconds,
    )
    operations = {
        f"{method.upper()} {path}"
        for path, path_item in openapi.get("paths", {}).items()
        for method in path_item
        if method.lower() in {"get", "post", "put", "patch", "delete"}
    }
    return [dict(row) for row in rows], operations, health.get("status") == "ok"


def run_business_backend_release_gate_from_environment(
    env: Mapping[str, str],
) -> BusinessBackendReleaseGate:
    report_path = Path(
        env.get(
            "SUITE_BACKEND_FOUNDATION_GATE_REPORT_PATH",
            "/backups/backend-foundation-completion-gate.json",
        )
    )
    backend_gate = load_backend_foundation_completion_gate(report_path)
    rows, operations, health_verified = _load_runtime_evidence(env)
    return build_business_backend_release_gate(
        backend_gate=backend_gate,
        module_catalog_rows=rows,
        api_operations=operations,
        api_health_verified=health_verified,
        backend_settings=env,
    )


def main() -> None:
    gate = run_business_backend_release_gate_from_environment(os.environ)
    print(json.dumps(gate.model_dump(mode="json"), sort_keys=True))
    raise SystemExit(0 if gate.release_ready else 2)


if __name__ == "__main__":
    main()
