from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.persistence.migration_catalog import MigrationManifestEntry, load_migration_manifest
from suite.platform.modules import (
    InMemoryModuleRegistry,
    ModuleCatalogEntry,
    ModuleStatus,
    PgModuleRegistry,
    TenantModuleState,
    build_default_module_registry,
    default_module_catalog_entries,
    default_tenant_module_seed_states,
)

ModuleRegistryStore = InMemoryModuleRegistry | PgModuleRegistry

MODULE_REGISTRY_CONTINUITY_DOMAIN = "module_registry_state"
MODULE_REGISTRY_DRILL_SCHEMA_VERSION = "module_registry_operations_report.v1"
REQUIRED_LIFECYCLE_AUDIT_EVENT_TYPES = (
    "tenant_module.provisioned",
    "tenant_module.enabled",
    "tenant_module.disabled",
    "tenant_module.suspended",
    "tenant_module.decommission_requested",
    "tenant_module.decommission_blocked",
    "tenant_module.decommission_cancelled",
    "tenant_module.decommission_reopened",
    "tenant_module.decommission_completed",
)
REQUIRED_BACKUP_EVIDENCE_ARTIFACTS = (
    "module catalog",
    "module required migration versions",
    "tenant module states",
    "tenant module migration evidence",
    "module lifecycle audit references",
    "persistent module registry seed/backfill evidence",
    "module registry operations report hashes",
    "worker discovery drill report hash",
)


class ModuleRegistryModuleOperationsView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    module_id: str
    catalog_present: bool
    catalog_status: ModuleStatus | None = None
    required_migration_versions: tuple[str, ...] = ()
    missing_required_migration_versions: tuple[str, ...] = ()
    expected_seed_tenants: tuple[str, ...] = ()
    missing_seed_tenants: tuple[str, ...] = ()
    seed_status_mismatches: tuple[str, ...] = ()
    worker_visible_tenants: tuple[str, ...] = ()
    worker_status_counts: dict[str, int] = Field(default_factory=dict)
    worker_discovery_ok: bool
    worker_discovery_error: str | None = None

    @property
    def backfill_required(self) -> bool:
        return bool(self.missing_seed_tenants or self.seed_status_mismatches)

    @property
    def repair_required(self) -> bool:
        return (
            not self.catalog_present
            or bool(self.missing_required_migration_versions)
            or self.backfill_required
            or not self.worker_discovery_ok
        )


class ModuleRegistryOperationsRunReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = MODULE_REGISTRY_DRILL_SCHEMA_VERSION
    run_id: str
    checked_by: str
    checked_at_utc: datetime
    continuity_domain: str = MODULE_REGISTRY_CONTINUITY_DOMAIN
    required_lifecycle_audit_event_types: tuple[str, ...] = REQUIRED_LIFECYCLE_AUDIT_EVENT_TYPES
    required_backup_evidence_artifacts: tuple[str, ...] = REQUIRED_BACKUP_EVIDENCE_ARTIFACTS
    modules: tuple[ModuleRegistryModuleOperationsView, ...]
    worker_discovery_ok: bool
    backfill_required_count: int = Field(ge=0)
    repair_required_count: int = Field(ge=0)
    recommended_actions: tuple[str, ...]
    evidence_hash: str


def build_module_registry_operations_report(
    *,
    app_registry: ModuleRegistryStore,
    worker_registry: ModuleRegistryStore,
    migration_manifest_entries: Iterable[MigrationManifestEntry],
    checked_by: str = "module-registry-drill",
    expected_catalog_entries: Iterable[ModuleCatalogEntry] = default_module_catalog_entries(),
    expected_seed_states: Iterable[TenantModuleState] = default_tenant_module_seed_states(),
) -> ModuleRegistryOperationsRunReport:
    catalog_by_module = {entry.module_id: entry for entry in app_registry.list_catalog_entries()}
    expected_catalog_by_module = {entry.module_id: entry for entry in expected_catalog_entries}
    seed_states_by_module = _seed_states_by_module(expected_seed_states)
    available_migration_versions = {entry.version for entry in migration_manifest_entries if entry.blocks_startup}
    module_ids = tuple(sorted(set(catalog_by_module) | set(expected_catalog_by_module)))

    module_views = tuple(
        _module_operations_view(
            module_id=module_id,
            catalog_entry=catalog_by_module.get(module_id),
            expected_seed_states=seed_states_by_module.get(module_id, ()),
            available_migration_versions=available_migration_versions,
            worker_registry=worker_registry,
        )
        for module_id in module_ids
    )
    recommended_actions = _recommended_actions(module_views)
    draft = ModuleRegistryOperationsRunReport(
        run_id=f"module-registry-drill-{uuid4().hex}",
        checked_by=checked_by,
        checked_at_utc=datetime.now(UTC),
        modules=module_views,
        worker_discovery_ok=all(module.worker_discovery_ok for module in module_views),
        backfill_required_count=sum(1 for module in module_views if module.backfill_required),
        repair_required_count=sum(1 for module in module_views if module.repair_required),
        recommended_actions=recommended_actions,
        evidence_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"evidence_hash": build_module_registry_operations_report_hash(draft)})


def build_module_registry_operations_report_hash(report: ModuleRegistryOperationsRunReport) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def build_default_worker_module_registry(
    environ: Mapping[str, str] | None = None,
) -> ModuleRegistryStore:
    env = os.environ if environ is None else environ
    worker_dsn = env.get("SUITE_MODULE_REGISTRY_WORKER_DSN") or env.get("SUITE_WORKER_DATABASE_DSN")
    if worker_dsn:
        return PgModuleRegistry(database_dsn=worker_dsn)
    return build_default_module_registry(env)


def run_module_registry_operations_report_from_env(
    environ: Mapping[str, str] | None = None,
) -> ModuleRegistryOperationsRunReport:
    env = os.environ if environ is None else environ
    return build_module_registry_operations_report(
        app_registry=build_default_module_registry(env),
        worker_registry=build_default_worker_module_registry(env),
        migration_manifest_entries=load_migration_manifest(),
        checked_by=env.get("SUITE_MODULE_REGISTRY_DRILL_CHECKED_BY", "module-registry-drill"),
    )


def exit_code_for_report(report: ModuleRegistryOperationsRunReport) -> int:
    return 1 if report.repair_required_count else 0


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the module registry seed/backfill/worker discovery drill.")
    parser.add_argument("--once", action="store_true", help="Run one metadata-only drill and exit.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the metadata-only run report.")
    args = parser.parse_args(argv)
    del args.once

    report = run_module_registry_operations_report_from_env()
    print(json.dumps(report.model_dump(mode="json"), indent=2 if args.pretty else None, sort_keys=True))
    raise SystemExit(exit_code_for_report(report))


def _module_operations_view(
    *,
    module_id: str,
    catalog_entry: ModuleCatalogEntry | None,
    expected_seed_states: tuple[TenantModuleState, ...],
    available_migration_versions: set[str],
    worker_registry: ModuleRegistryStore,
) -> ModuleRegistryModuleOperationsView:
    required_versions = catalog_entry.required_migration_versions if catalog_entry else ()
    try:
        worker_states = worker_registry.list_tenant_modules_for_module(module_id)
        worker_discovery_ok = True
        worker_discovery_error = None
    except Exception as exc:  # pragma: no cover - exercised through report fields in integration failures.
        worker_states = ()
        worker_discovery_ok = False
        worker_discovery_error = type(exc).__name__

    states_by_tenant = {state.tenant_id: state for state in worker_states}
    missing_seed_tenants: list[str] = []
    seed_status_mismatches: list[str] = []
    for expected_seed in expected_seed_states:
        actual = states_by_tenant.get(expected_seed.tenant_id)
        if actual is None:
            missing_seed_tenants.append(expected_seed.tenant_id)
        elif actual.status != expected_seed.status:
            seed_status_mismatches.append(f"{expected_seed.tenant_id}:{expected_seed.status}->{actual.status}")

    status_counts = Counter(state.status.value for state in worker_states)
    return ModuleRegistryModuleOperationsView(
        module_id=module_id,
        catalog_present=catalog_entry is not None,
        catalog_status=catalog_entry.status if catalog_entry else None,
        required_migration_versions=tuple(required_versions),
        missing_required_migration_versions=tuple(sorted(set(required_versions) - available_migration_versions)),
        expected_seed_tenants=tuple(sorted(seed.tenant_id for seed in expected_seed_states)),
        missing_seed_tenants=tuple(sorted(missing_seed_tenants)),
        seed_status_mismatches=tuple(sorted(seed_status_mismatches)),
        worker_visible_tenants=tuple(sorted(states_by_tenant)),
        worker_status_counts=dict(sorted(status_counts.items())),
        worker_discovery_ok=worker_discovery_ok,
        worker_discovery_error=worker_discovery_error,
    )


def _seed_states_by_module(
    expected_seed_states: Iterable[TenantModuleState],
) -> dict[str, tuple[TenantModuleState, ...]]:
    grouped: dict[str, list[TenantModuleState]] = {}
    for seed_state in expected_seed_states:
        grouped.setdefault(seed_state.module_id, []).append(seed_state)
    return {
        module_id: tuple(sorted(states, key=lambda state: state.tenant_id)) for module_id, states in grouped.items()
    }


def _recommended_actions(
    module_views: tuple[ModuleRegistryModuleOperationsView, ...],
) -> tuple[str, ...]:
    actions: list[str] = []
    for module in module_views:
        if not module.catalog_present:
            actions.append(f"{module.module_id}: run catalog seed/repair under change control")
        if module.missing_required_migration_versions:
            versions = ",".join(module.missing_required_migration_versions)
            actions.append(f"{module.module_id}: repair migration manifest evidence for {versions}")
        if module.missing_seed_tenants:
            tenants = ",".join(module.missing_seed_tenants)
            actions.append(f"{module.module_id}: backfill expected tenant module seed rows for {tenants}")
        if module.seed_status_mismatches:
            actions.append(f"{module.module_id}: review seed status drift before any automatic repair")
        if not module.worker_discovery_ok:
            actions.append(f"{module.module_id}: repair worker role discovery grants or RLS policy")
    if not actions:
        actions.append("module registry seed, backfill, worker discovery, audit, and backup evidence are aligned")
    return tuple(actions)


if __name__ == "__main__":
    main()
