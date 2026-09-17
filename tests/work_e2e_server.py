from __future__ import annotations

import importlib
import os
from datetime import UTC, datetime
from typing import Any, cast

from fastapi import FastAPI

from suite.platform.crm_erp_subfeatures import default_crm_erp_subfeature_enabled_features
from suite.platform.knowledge_base import default_knowledge_base_enabled_features
from suite.platform.modules import (
    InMemoryModuleRegistry,
    ModuleStatus,
    TenantModuleState,
    default_module_catalog_entries,
)
from suite.platform.productivity_pilot_traffic_scope import ProductivityPilotTrafficDecision
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
from suite.testing.work_e2e_guard import WORK_E2E_TENANT_ID, require_isolated_work_e2e_environment


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


if allow_synthetic_traffic:
    traffic_dependency = cast(Any, main_module.require_productivity_pilot_traffic_scope)
    app.dependency_overrides[traffic_dependency] = _allow_isolated_synthetic_traffic
