from __future__ import annotations

from pathlib import Path

from suite.operations.business_backend_release_gate import (
    PRODUCTIVE_SLICES,
    BusinessBackendReleaseGate,
    BusinessSliceReleaseEvidence,
    build_business_backend_release_gate_hash,
)
from suite.operations.productivity_pilot_preflight import (
    ProductivityPilotPolicy,
    build_productivity_pilot_preflight_gate,
    build_productivity_pilot_preflight_gate_hash,
    load_productivity_pilot_policy,
)

CHECKED_AT = "2026-07-30T13:00:00Z"
POLICY_PATH = Path("docs/operations/productivity_pilot_policy.json")


def _business_gate(*, ready: bool = True) -> BusinessBackendReleaseGate:
    slices = tuple(
        BusinessSliceReleaseEvidence(
            slice_id=definition.slice_id,
            module_id=definition.module_id,
            required_migration_versions=definition.required_migration_versions,
            required_api_operations=definition.required_api_operations,
            module_catalog_status="installed",
            module_catalog_entry_present=ready,
            module_package_installed=ready,
            migration_catalog_verified=ready,
            module_required_migrations_verified=ready,
            api_operations_verified=ready,
            postgres_backend_verified=ready,
            restore_write_controls_verified=ready,
            blocking_reasons=() if ready else ("release_control_failed",),
            release_ready=ready,
        )
        for definition in PRODUCTIVE_SLICES
    )
    draft = BusinessBackendReleaseGate(
        checked_at_utc=CHECKED_AT,
        runtime_environment="dev",
        backend_foundation_gate_hash="sha256:" + "1" * 64,
        backend_foundation_complete=ready,
        api_health_verified=ready,
        api_openapi_contract_verified=ready,
        module_catalog_manifest_hash="sha256:" + "2" * 64,
        productive_slice_count=3,
        release_ready_slice_count=3 if ready else 0,
        slices=slices,
        metadata_only_evidence_verified=True,
        blocking_reasons=() if ready else ("release_not_ready",),
        release_ready=ready,
        gate_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"gate_hash": build_business_backend_release_gate_hash(draft)})


def _policy() -> ProductivityPilotPolicy:
    return load_productivity_pilot_policy(POLICY_PATH)


def _tenant_module_rows(policy: ProductivityPilotPolicy) -> list[dict[str, object]]:
    return [
        {
            "tenant_id": "tenant-demo",
            "module_id": slice_policy.module_id,
            "status": "enabled",
            "enabled_features": {
                **{feature_id: True for feature_id in slice_policy.required_feature_ids},
                **{feature_id: False for feature_id in slice_policy.forbidden_feature_ids},
            },
        }
        for slice_policy in policy.slices
    ]


def test_productivity_pilot_preflight_verifies_tenant_scope_without_starting_pilot() -> None:
    policy = _policy()

    gate = build_productivity_pilot_preflight_gate(
        business_gate=_business_gate(),
        policy=policy,
        candidate_tenant_ids=("tenant-demo",),
        tenant_module_rows=_tenant_module_rows(policy),
        checked_at_utc=CHECKED_AT,
    )

    assert gate.preflight_ready is True
    assert gate.candidate_tenant_count == 1
    assert gate.ready_tenant_count == 1
    assert gate.productive_slice_count == 3
    assert gate.route_scope_contract_verified is True
    assert gate.monitoring_contract_verified is True
    assert gate.monitoring_control_count == 5
    assert gate.rollback_contract_verified is True
    assert gate.rollback_control_count == 4
    assert gate.human_admission_required is True
    assert gate.human_admission_recorded is False
    assert gate.traffic_scope_enforcement_required is True
    assert gate.traffic_scope_enforced is False
    assert gate.pilot_start_allowed is False
    assert gate.tenant_state_changed is False
    assert gate.business_write_executed is False
    assert gate.content_included is False
    assert gate.next_action == "record_explicit_human_pilot_admission_and_enforce_traffic_scope"
    assert gate.gate_hash == build_productivity_pilot_preflight_gate_hash(gate)


def test_productivity_pilot_preflight_blocks_missing_and_forbidden_features() -> None:
    policy = _policy()
    rows = _tenant_module_rows(policy)
    tasks_features = rows[1]["enabled_features"]
    time_features = rows[2]["enabled_features"]
    assert isinstance(tasks_features, dict)
    assert isinstance(time_features, dict)
    tasks_features[policy.slices[1].required_feature_ids[0]] = False
    time_features[policy.slices[2].forbidden_feature_ids[0]] = True

    gate = build_productivity_pilot_preflight_gate(
        business_gate=_business_gate(),
        policy=policy,
        candidate_tenant_ids=("tenant-demo",),
        tenant_module_rows=rows,
        checked_at_utc=CHECKED_AT,
    )

    assert gate.preflight_ready is False
    assert "tenant_not_ready:tenant-demo" in gate.blocking_reasons
    tasks = next(item for item in gate.tenants[0].slices if item.slice_id == "tasks_activities")
    time_tracking = next(item for item in gate.tenants[0].slices if item.slice_id == "time_tracking")
    assert "required_pilot_feature_missing" in tasks.blocking_reasons
    assert "forbidden_pilot_feature_enabled" in time_tracking.blocking_reasons
    assert gate.pilot_start_allowed is False


def test_productivity_pilot_preflight_blocks_release_scope_and_tenant_selection_gaps() -> None:
    policy = _policy()
    mismatched_policy = policy.model_copy(update={"allowed_api_operations": policy.allowed_api_operations[:-1]})

    gate = build_productivity_pilot_preflight_gate(
        business_gate=_business_gate(ready=False),
        policy=mismatched_policy,
        candidate_tenant_ids=(),
        tenant_module_rows=(),
        checked_at_utc=CHECKED_AT,
    )

    assert gate.preflight_ready is False
    assert "business_backend_release_not_ready" in gate.blocking_reasons
    assert "candidate_tenant_selection_missing" in gate.blocking_reasons
    assert "pilot_route_scope_contract_mismatch" in gate.blocking_reasons
    assert gate.ready_tenant_count == 0
    assert gate.pilot_start_allowed is False
