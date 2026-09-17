from __future__ import annotations

import importlib
import os
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from fastapi import FastAPI

from suite.operations.productivity_pilot_preflight import ProductivityPilotControl
from suite.platform.crm_erp_subfeatures import default_crm_erp_subfeature_enabled_features
from suite.platform.knowledge_base import default_knowledge_base_enabled_features
from suite.platform.modules import (
    InMemoryModuleRegistry,
    ModuleStatus,
    TenantModuleState,
    default_module_catalog_entries,
)
from suite.platform.productivity_pilot_start_authorization import (
    ProductivityPilotControlEvidence,
    ProductivityPilotStartAuthorization,
    build_productivity_pilot_control_evidence_manifest_hash,
    build_productivity_pilot_start_authorization_hash,
)
from suite.platform.productivity_pilot_traffic_scope import (
    ProductivityPilotTrafficDecision,
    ProductivityPilotTrafficScopeEnforcement,
    build_productivity_pilot_traffic_scope_hash,
)
from suite.platform.tasks_activities_module import (
    TASKS_WORKFLOW_WRITE_FEATURE_ID,
    default_tasks_activities_enabled_features,
)
from suite.platform.tenant_policies import InMemoryTenantPolicyRepository
from suite.platform.time_tracking_module import (
    TIME_APPROVALS_WRITE_FEATURE_ID,
    TIME_ENTRIES_WRITE_FEATURE_ID,
    default_time_tracking_enabled_features,
)
from suite.storage.source_objects import sha256_bytes
from suite.testing.work_e2e_guard import (
    WORK_E2E_TENANT_ID,
    require_isolated_work_e2e_environment,
)

allow_synthetic_traffic = require_isolated_work_e2e_environment(os.environ)
main_module = importlib.import_module("main")
app = cast(FastAPI, main_module.app)
catalog_entries = tuple(default_module_catalog_entries())
catalog_registry = InMemoryModuleRegistry(catalog_entries=list(catalog_entries))
migration_manifest = tuple(app.state.migration_manifest)


def _enabled_state(module_id: str, enabled_features: dict[str, bool]) -> TenantModuleState:
    now = datetime.now(UTC)
    return TenantModuleState(
        tenant_id=WORK_E2E_TENANT_ID,
        module_id=module_id,
        status=ModuleStatus.ENABLED,
        enabled_features=enabled_features,
        policy_snapshot_hash="sha256:work-e2e-synthetic-policy",
        provisioned_at_utc=now,
        enabled_at_utc=now,
        changed_by="work-e2e-harness",
        audit_chain_ref="audit:work-e2e-module-state",
        migration_evidence=catalog_registry.migration_evidence_for_module(
            module_id=module_id,
            migration_manifest_entries=migration_manifest,
        ),
    )


task_features = default_tasks_activities_enabled_features()
task_features[TASKS_WORKFLOW_WRITE_FEATURE_ID] = True
time_features = default_time_tracking_enabled_features()
time_features[TIME_ENTRIES_WRITE_FEATURE_ID] = True
time_features[TIME_APPROVALS_WRITE_FEATURE_ID] = True

app.state.module_registry = InMemoryModuleRegistry(
    catalog_entries=list(catalog_entries),
    tenant_modules=[
        _enabled_state("crm_erp", default_crm_erp_subfeature_enabled_features()),
        _enabled_state("knowledge_base", default_knowledge_base_enabled_features()),
        _enabled_state("tasks_activities", task_features),
        _enabled_state("time_tracking", time_features),
    ],
)

base_policy = InMemoryTenantPolicyRepository.default().get("tenant-demo")
synthetic_policy = base_policy.model_copy(
    update={
        "tenant_id": WORK_E2E_TENANT_ID,
        "ai_enabled": False,
        "allowed_model_ids": set(),
        "rag_enabled": False,
        "voice_enabled": False,
        "raw_audio_storage_allowed": False,
    }
)
app.state.tenant_policy_repository = InMemoryTenantPolicyRepository(
    policies={WORK_E2E_TENANT_ID: synthetic_policy}
)


def _allow_isolated_synthetic_traffic() -> ProductivityPilotTrafficDecision:
    return ProductivityPilotTrafficDecision(
        tenant_id=WORK_E2E_TENANT_ID,
        operation="TEST /work-e2e",
        pilot_traffic_managed=False,
        operation_in_scope=False,
        tenant_scope_enforced=True,
        route_scope_enforced=True,
        default_deny_enabled=True,
        authorization_allowed=True,
        http_status_code=200,
    )


def _synthetic_hash(label: str) -> str:
    return sha256_bytes(f"work-e2e:{label}".encode())


def _install_closed_runtime_fixture() -> None:
    service = app.state.productivity_pilot_start_authorization_service
    now = datetime.now(UTC)
    allowed_operations = tuple(service.policy.allowed_api_operations)
    traffic_scope_draft = ProductivityPilotTrafficScopeEnforcement(
        tenant_id=WORK_E2E_TENANT_ID,
        enforcement_id="work-e2e-traffic-scope",
        admission_id="work-e2e-admission",
        admission_evidence_hash=_synthetic_hash("admission"),
        preflight_gate_hash=_synthetic_hash("preflight"),
        policy_hash=service.policy_hash,
        allowed_api_operations=allowed_operations,
        route_scope_hash=_synthetic_hash("route-scope"),
        command_hash=_synthetic_hash("traffic-command"),
        idempotency_key_hash=_synthetic_hash("traffic-idempotency"),
        human_confirmation_statement_hash=_synthetic_hash("traffic-confirmation"),
        change_request_ref="change:work-e2e-traffic-scope",
        ingress_policy_ref="ingress:work-e2e-internal-only",
        human_confirmation_reference="test-fixture:work-e2e-traffic-scope",
        audit_chain_ref="audit:work-e2e-traffic-scope",
        enforced_by="work-e2e-harness",
        enforced_at_utc=now - timedelta(minutes=10),
        evidence_hash="sha256:" + "0" * 64,
    )
    traffic_scope = traffic_scope_draft.model_copy(
        update={"evidence_hash": build_productivity_pilot_traffic_scope_hash(traffic_scope_draft)}
    )
    app.state.productivity_pilot_traffic_scope_store.append(traffic_scope)

    observed_at = now - timedelta(minutes=5)
    valid_until = now + timedelta(hours=1)

    def control_evidence(
        controls: tuple[ProductivityPilotControl, ...],
    ) -> tuple[ProductivityPilotControlEvidence, ...]:
        return tuple(
            ProductivityPilotControlEvidence(
                control_id=control.control_id,
                evidence_hash=_synthetic_hash(f"control:{control.control_id}"),
                observed_at_utc=observed_at,
                valid_until_utc=valid_until,
            )
            for control in controls
        )

    monitoring_evidence = control_evidence(tuple(service.policy.monitoring_controls))
    rollback_evidence = control_evidence(tuple(service.policy.rollback_controls))
    start_draft = ProductivityPilotStartAuthorization(
        tenant_id=WORK_E2E_TENANT_ID,
        authorization_id="work-e2e-start-authorization",
        enforcement_id=traffic_scope.enforcement_id,
        traffic_scope_evidence_hash=traffic_scope.evidence_hash,
        route_scope_hash=traffic_scope.route_scope_hash,
        admission_evidence_hash=traffic_scope.admission_evidence_hash,
        preflight_gate_hash=traffic_scope.preflight_gate_hash,
        policy_hash=traffic_scope.policy_hash,
        allowed_api_operations=allowed_operations,
        monitoring_evidence=monitoring_evidence,
        rollback_evidence=rollback_evidence,
        monitoring_evidence_manifest_hash=build_productivity_pilot_control_evidence_manifest_hash(
            monitoring_evidence
        ),
        rollback_evidence_manifest_hash=build_productivity_pilot_control_evidence_manifest_hash(
            rollback_evidence
        ),
        command_hash=_synthetic_hash("start-command"),
        idempotency_key_hash=_synthetic_hash("start-idempotency"),
        human_confirmation_statement_hash=_synthetic_hash("start-confirmation"),
        change_request_ref="change:work-e2e-start",
        human_confirmation_reference="test-fixture:work-e2e-start",
        security_approval_ref="test-fixture:work-e2e-security",
        audit_chain_ref="audit:work-e2e-start",
        authorized_by="work-e2e-harness",
        authorized_at_utc=now - timedelta(minutes=4),
        effective_at_utc=now - timedelta(minutes=3),
        expires_at_utc=now + timedelta(minutes=30),
        evidence_hash="sha256:" + "0" * 64,
    )
    start = start_draft.model_copy(
        update={"evidence_hash": build_productivity_pilot_start_authorization_hash(start_draft)}
    )
    app.state.productivity_pilot_start_authorization_store.append(start)


if allow_synthetic_traffic:
    traffic_dependency = cast(Any, main_module.require_productivity_pilot_traffic_scope)
    app.dependency_overrides[traffic_dependency] = _allow_isolated_synthetic_traffic
else:
    _install_closed_runtime_fixture()
