from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, Field

from suite.operations.postgres_restore_drill import (
    PostgresRestoreDrillReport,
    build_postgres_restore_drill_report_hash,
    run_postgres_restore_drill_from_environment,
)
from suite.storage.backend_storage_foundation_gate import (
    BackendStorageFoundationGate,
    build_backend_storage_foundation_gate_hash,
    run_backend_storage_foundation_gate_from_environment,
)
from suite.storage.source_objects import sha256_bytes


class BackendFoundationCompletionGate(BaseModel):
    checked_at_utc: str
    runtime_environment: str
    tenant_ids: tuple[str, ...]
    postgres_restore_drill_report_hash: str
    backend_storage_foundation_gate_hash: str
    backup_sha256: str
    migration_count: int = Field(ge=1)
    database_table_count: int = Field(ge=1)
    restored_object_count: int = Field(ge=0)
    tenant_iam_verified: bool
    append_only_audit_verified: bool
    module_registry_verified: bool
    crm_atomic_write_controls_verified: bool
    tasks_activities_write_controls_verified: bool
    time_tracking_write_controls_verified: bool
    productivity_pilot_admission_controls_verified: bool
    productivity_pilot_traffic_scope_controls_verified: bool
    productive_business_write_controls_verified: bool
    migration_catalog_verified: bool
    postgres_backup_restore_verified: bool
    persistent_source_objects_verified: bool
    exact_version_object_restore_verified: bool
    independent_recovery_targets_verified: bool
    tenant_scope_verified: bool
    metadata_only_evidence_verified: bool
    blocking_reasons: tuple[str, ...] = ()
    api_start_allowed: bool
    backend_foundation_complete: bool
    content_included: bool = False
    gate_hash: str
    schema_version: str = "backend_foundation_completion_gate.v1"


def build_backend_foundation_completion_gate(
    *,
    postgres_restore_report: PostgresRestoreDrillReport,
    storage_gate: BackendStorageFoundationGate,
) -> BackendFoundationCompletionGate:
    if build_postgres_restore_drill_report_hash(postgres_restore_report) != postgres_restore_report.report_hash:
        raise ValueError("PostgreSQL restore drill report hash is invalid")
    if build_backend_storage_foundation_gate_hash(storage_gate) != storage_gate.gate_hash:
        raise ValueError("backend storage foundation gate hash is invalid")

    independent_targets = (
        postgres_restore_report.target_isolation_verified and storage_gate.independent_restore_target_verified
    )
    metadata_only = (
        postgres_restore_report.metadata_only_evidence_verified
        and storage_gate.metadata_only_evidence_verified
        and not postgres_restore_report.content_included
        and not storage_gate.content_included
    )
    productive_business_writes = (
        postgres_restore_report.crm_atomic_write_controls_verified
        and postgres_restore_report.tasks_activities_write_controls_verified
        and postgres_restore_report.time_tracking_write_controls_verified
    )
    checks = {
        "tenant_iam_not_verified": postgres_restore_report.tenant_iam_controls_verified,
        "append_only_audit_not_verified": postgres_restore_report.append_only_audit_controls_verified,
        "module_registry_not_verified": postgres_restore_report.module_registry_controls_verified,
        "crm_atomic_write_controls_not_verified": postgres_restore_report.crm_atomic_write_controls_verified,
        "tasks_activities_write_controls_not_verified": (
            postgres_restore_report.tasks_activities_write_controls_verified
        ),
        "time_tracking_write_controls_not_verified": postgres_restore_report.time_tracking_write_controls_verified,
        "productivity_pilot_admission_controls_not_verified": (
            postgres_restore_report.productivity_pilot_admission_controls_verified
        ),
        "productivity_pilot_traffic_scope_controls_not_verified": (
            postgres_restore_report.productivity_pilot_traffic_scope_controls_verified
        ),
        "productive_business_write_controls_not_verified": productive_business_writes,
        "migration_catalog_not_verified": postgres_restore_report.migration_catalog_verified,
        "postgres_backup_restore_not_verified": postgres_restore_report.restore_ready,
        "persistent_source_objects_not_verified": storage_gate.persistent_runtime_verified,
        "exact_version_object_restore_not_verified": storage_gate.exact_version_restore_verified,
        "independent_recovery_targets_not_verified": independent_targets,
        "tenant_scope_not_verified": storage_gate.tenant_scope_verified,
        "evidence_contains_content": metadata_only,
        "storage_foundation_not_ready": storage_gate.backend_storage_foundation_ready,
    }
    blocking_reasons = tuple(sorted(reason for reason, passed in checks.items() if not passed))
    ready = not blocking_reasons
    draft = BackendFoundationCompletionGate(
        checked_at_utc=postgres_restore_report.checked_at_utc,
        runtime_environment=storage_gate.runtime_environment,
        tenant_ids=storage_gate.tenant_ids,
        postgres_restore_drill_report_hash=postgres_restore_report.report_hash,
        backend_storage_foundation_gate_hash=storage_gate.gate_hash,
        backup_sha256=postgres_restore_report.backup_sha256,
        migration_count=postgres_restore_report.migration_count,
        database_table_count=postgres_restore_report.table_count,
        restored_object_count=storage_gate.restored_object_count,
        tenant_iam_verified=postgres_restore_report.tenant_iam_controls_verified,
        append_only_audit_verified=postgres_restore_report.append_only_audit_controls_verified,
        module_registry_verified=postgres_restore_report.module_registry_controls_verified,
        crm_atomic_write_controls_verified=postgres_restore_report.crm_atomic_write_controls_verified,
        tasks_activities_write_controls_verified=postgres_restore_report.tasks_activities_write_controls_verified,
        time_tracking_write_controls_verified=postgres_restore_report.time_tracking_write_controls_verified,
        productivity_pilot_admission_controls_verified=(
            postgres_restore_report.productivity_pilot_admission_controls_verified
        ),
        productivity_pilot_traffic_scope_controls_verified=(
            postgres_restore_report.productivity_pilot_traffic_scope_controls_verified
        ),
        productive_business_write_controls_verified=productive_business_writes,
        migration_catalog_verified=postgres_restore_report.migration_catalog_verified,
        postgres_backup_restore_verified=postgres_restore_report.restore_ready,
        persistent_source_objects_verified=storage_gate.persistent_runtime_verified,
        exact_version_object_restore_verified=storage_gate.exact_version_restore_verified,
        independent_recovery_targets_verified=independent_targets,
        tenant_scope_verified=storage_gate.tenant_scope_verified,
        metadata_only_evidence_verified=metadata_only,
        blocking_reasons=blocking_reasons,
        api_start_allowed=ready,
        backend_foundation_complete=ready,
        gate_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"gate_hash": build_backend_foundation_completion_gate_hash(draft)})


def build_backend_foundation_completion_gate_hash(gate: BackendFoundationCompletionGate) -> str:
    return sha256_bytes(
        json.dumps(
            gate.model_dump(mode="json", exclude={"gate_hash"}),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def persist_backend_foundation_completion_gate(
    *,
    gate: BackendFoundationCompletionGate,
    report_path: Path,
) -> None:
    if build_backend_foundation_completion_gate_hash(gate) != gate.gate_hash:
        raise ValueError("backend foundation completion gate hash is invalid")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(gate.model_dump(mode="json"), sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(report_path)


def load_backend_foundation_completion_gate(report_path: Path) -> BackendFoundationCompletionGate:
    gate = BackendFoundationCompletionGate.model_validate_json(report_path.read_text(encoding="utf-8"))
    if build_backend_foundation_completion_gate_hash(gate) != gate.gate_hash:
        raise ValueError("persisted backend foundation completion gate hash is invalid")
    return gate


def run_backend_foundation_completion_gate_from_environment(
    env: Mapping[str, str],
) -> BackendFoundationCompletionGate:
    postgres_restore_report = run_postgres_restore_drill_from_environment(env)
    storage_gate = run_backend_storage_foundation_gate_from_environment(env)
    return build_backend_foundation_completion_gate(
        postgres_restore_report=postgres_restore_report,
        storage_gate=storage_gate,
    )


def main() -> None:
    gate = run_backend_foundation_completion_gate_from_environment(os.environ)
    report_path = os.environ.get("SUITE_BACKEND_FOUNDATION_GATE_REPORT_PATH", "").strip()
    if report_path:
        persist_backend_foundation_completion_gate(gate=gate, report_path=Path(report_path))
    print(json.dumps(gate.model_dump(mode="json"), sort_keys=True))
    raise SystemExit(0 if gate.backend_foundation_complete else 2)


if __name__ == "__main__":
    main()
