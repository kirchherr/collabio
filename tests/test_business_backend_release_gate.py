from __future__ import annotations

from pathlib import Path

import pytest

from suite.operations.backend_foundation_completion_gate import (
    BackendFoundationCompletionGate,
    build_backend_foundation_completion_gate_hash,
)
from suite.operations.business_backend_release_gate import (
    PRODUCTIVE_SLICES,
    build_business_backend_release_gate,
    build_business_backend_release_gate_hash,
    load_business_backend_release_gate,
    persist_business_backend_release_gate,
)

CHECKED_AT = "2026-07-30T12:00:00Z"


def _backend_gate(*, complete: bool = True) -> BackendFoundationCompletionGate:
    draft = BackendFoundationCompletionGate(
        checked_at_utc=CHECKED_AT,
        runtime_environment="dev",
        tenant_ids=("tenant-demo", "tenant-other"),
        postgres_restore_drill_report_hash="sha256:" + "1" * 64,
        backend_storage_foundation_gate_hash="sha256:" + "2" * 64,
        backup_sha256="sha256:" + "3" * 64,
        migration_count=60,
        database_table_count=66,
        restored_object_count=3,
        tenant_iam_verified=complete,
        append_only_audit_verified=complete,
        module_registry_verified=complete,
        crm_atomic_write_controls_verified=complete,
        tasks_activities_write_controls_verified=complete,
        time_tracking_write_controls_verified=complete,
        productivity_pilot_admission_controls_verified=complete,
        productivity_pilot_traffic_scope_controls_verified=complete,
        productivity_pilot_start_authorization_controls_verified=complete,
        productive_business_write_controls_verified=complete,
        migration_catalog_verified=complete,
        postgres_backup_restore_verified=complete,
        persistent_source_objects_verified=complete,
        exact_version_object_restore_verified=complete,
        independent_recovery_targets_verified=complete,
        tenant_scope_verified=complete,
        metadata_only_evidence_verified=True,
        blocking_reasons=() if complete else ("backend_not_ready",),
        api_start_allowed=complete,
        backend_foundation_complete=complete,
        gate_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"gate_hash": build_backend_foundation_completion_gate_hash(draft)})


def _catalog_rows() -> list[dict[str, object]]:
    return [
        {
            "module_id": definition.module_id,
            "status": "installed",
            "required_migration_versions": list(definition.required_migration_versions),
        }
        for definition in PRODUCTIVE_SLICES
    ]


def _api_operations() -> set[str]:
    return {operation for definition in PRODUCTIVE_SLICES for operation in definition.required_api_operations}


def _backend_settings() -> dict[str, str]:
    return {definition.backend_environment_variable: "postgres" for definition in PRODUCTIVE_SLICES}


def test_business_backend_release_gate_binds_three_productive_slices() -> None:
    gate = build_business_backend_release_gate(
        backend_gate=_backend_gate(),
        module_catalog_rows=_catalog_rows(),
        api_operations=_api_operations(),
        api_health_verified=True,
        backend_settings=_backend_settings(),
        checked_at_utc=CHECKED_AT,
    )

    assert gate.release_ready is True
    assert gate.productive_slice_count == 3
    assert gate.release_ready_slice_count == 3
    assert gate.api_openapi_contract_verified is True
    assert gate.metadata_only_evidence_verified is True
    assert gate.tenant_activation_executed is False
    assert gate.business_write_executed is False
    assert gate.content_included is False
    assert gate.gate_hash == build_business_backend_release_gate_hash(gate)
    assert {item.slice_id for item in gate.slices} == {
        "crm_account_onboarding",
        "tasks_activities",
        "time_tracking",
    }


def test_business_backend_release_gate_blocks_missing_route_and_unsafe_backend() -> None:
    settings = _backend_settings()
    settings["SUITE_TIME_TRACKING_BACKEND"] = "memory"
    operations = _api_operations()
    operations.remove("GET /v1/tasks/activities")

    gate = build_business_backend_release_gate(
        backend_gate=_backend_gate(),
        module_catalog_rows=_catalog_rows(),
        api_operations=operations,
        api_health_verified=True,
        backend_settings=settings,
        checked_at_utc=CHECKED_AT,
    )

    assert gate.release_ready is False
    assert gate.release_ready_slice_count == 1
    assert gate.api_openapi_contract_verified is False
    assert "slice_not_ready:tasks_activities" in gate.blocking_reasons
    assert "slice_not_ready:time_tracking" in gate.blocking_reasons
    tasks = next(item for item in gate.slices if item.slice_id == "tasks_activities")
    time_tracking = next(item for item in gate.slices if item.slice_id == "time_tracking")
    assert "api_operation_missing" in tasks.blocking_reasons
    assert "non_postgres_backend_configured" in time_tracking.blocking_reasons


def test_business_backend_release_gate_blocks_incomplete_catalog_and_foundation() -> None:
    rows = _catalog_rows()
    rows[0]["status"] = "available"
    rows[1]["required_migration_versions"] = ["0050"]

    gate = build_business_backend_release_gate(
        backend_gate=_backend_gate(complete=False),
        module_catalog_rows=rows,
        api_operations=_api_operations(),
        api_health_verified=False,
        backend_settings=_backend_settings(),
        checked_at_utc=CHECKED_AT,
    )

    assert gate.release_ready is False
    assert "backend_foundation_not_complete" in gate.blocking_reasons
    assert "api_health_not_verified" in gate.blocking_reasons
    crm = next(item for item in gate.slices if item.slice_id == "crm_account_onboarding")
    tasks = next(item for item in gate.slices if item.slice_id == "tasks_activities")
    assert "module_package_not_installed" in crm.blocking_reasons
    assert "module_required_migration_missing" in tasks.blocking_reasons


def test_business_backend_release_gate_report_round_trip_and_tamper_detection(tmp_path: Path) -> None:
    gate = build_business_backend_release_gate(
        backend_gate=_backend_gate(),
        module_catalog_rows=_catalog_rows(),
        api_operations=_api_operations(),
        api_health_verified=True,
        backend_settings=_backend_settings(),
        checked_at_utc=CHECKED_AT,
    )
    report_path = tmp_path / "business-release-gate.json"

    persist_business_backend_release_gate(gate=gate, report_path=report_path)

    assert load_business_backend_release_gate(report_path) == gate
    report_path.write_text(
        report_path.read_text(encoding="utf-8").replace('"release_ready":true', '"release_ready":false'),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="hash is invalid"):
        load_business_backend_release_gate(report_path)
