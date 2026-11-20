from __future__ import annotations

import json
import os
from collections.abc import Mapping

from pydantic import BaseModel, Field

from suite.platform.workspace_source_objects import demo_workspace_source_object_records
from suite.storage.exact_version_restore_drill import (
    ExactVersionRestoreDrillReport,
    build_exact_version_restore_drill_report_hash,
    run_exact_version_restore_drill_from_environment,
)
from suite.storage.persistent_source_object_runtime import (
    PersistentSourceObjectRuntimeReport,
    build_persistent_source_object_repository,
    build_persistent_source_object_runtime_report_hash,
    run_persistent_source_object_runtime_check,
)
from suite.storage.s3_compatible_content_store import (
    S3CompatibleSourceObjectContentStore,
    build_s3_compatible_provider_profile_evidence,
)
from suite.storage.source_objects import sha256_bytes


class BackendStorageFoundationGate(BaseModel):
    checked_at_utc: str
    runtime_environment: str
    tenant_ids: tuple[str, ...]
    persistent_runtime_report_hash: str
    exact_version_restore_drill_report_hash: str
    source_provider_profile_evidence_hash: str
    source_manifest_count: int = Field(ge=0)
    restored_object_count: int = Field(ge=0)
    restart_verified_source_object_count: int = Field(ge=0)
    runtime_restore_binding_verified: bool
    persistent_runtime_verified: bool
    exact_version_restore_verified: bool
    independent_restore_target_verified: bool
    tenant_scope_verified: bool
    metadata_only_evidence_verified: bool
    blocking_reasons: tuple[str, ...] = ()
    api_start_allowed: bool
    backend_storage_foundation_ready: bool
    content_included: bool = False
    gate_hash: str
    schema_version: str = "backend_storage_foundation_gate.v1"


def build_backend_storage_foundation_gate(
    *,
    runtime_report: PersistentSourceObjectRuntimeReport,
    restore_report: ExactVersionRestoreDrillReport,
) -> BackendStorageFoundationGate:
    if build_persistent_source_object_runtime_report_hash(runtime_report) != runtime_report.report_hash:
        raise ValueError("persistent runtime report hash is invalid")
    if build_exact_version_restore_drill_report_hash(restore_report) != restore_report.report_hash:
        raise ValueError("exact-version restore drill report hash is invalid")

    runtime_tenant_ids = tuple(sorted(evidence.tenant_id for evidence in runtime_report.tenant_evidence))
    tenant_scope_verified = runtime_tenant_ids == tuple(sorted(restore_report.tenant_ids))
    runtime_restore_binding_verified = runtime_report.restore_drill_report_hash == restore_report.report_hash
    metadata_only_evidence_verified = not runtime_report.content_included and not restore_report.content_included
    blocking_reasons: list[str] = []
    if not runtime_restore_binding_verified:
        blocking_reasons.append("runtime_restore_binding_not_verified")
    if not runtime_report.runtime_ready:
        blocking_reasons.append("persistent_runtime_not_ready")
    if not restore_report.restore_ready:
        blocking_reasons.append("exact_version_restore_not_ready")
    if not restore_report.target_isolation_verified:
        blocking_reasons.append("restore_target_not_isolated")
    if not tenant_scope_verified:
        blocking_reasons.append("tenant_scope_mismatch")
    if not metadata_only_evidence_verified:
        blocking_reasons.append("evidence_contains_content")

    ready = not blocking_reasons
    draft = BackendStorageFoundationGate(
        checked_at_utc=restore_report.checked_at_utc,
        runtime_environment=runtime_report.runtime_environment,
        tenant_ids=tuple(sorted(restore_report.tenant_ids)),
        persistent_runtime_report_hash=runtime_report.report_hash,
        exact_version_restore_drill_report_hash=restore_report.report_hash,
        source_provider_profile_evidence_hash=runtime_report.provider_profile_evidence_hash,
        source_manifest_count=restore_report.source_manifest_count,
        restored_object_count=restore_report.restored_object_count,
        restart_verified_source_object_count=runtime_report.restart_verified_source_object_count,
        runtime_restore_binding_verified=runtime_restore_binding_verified,
        persistent_runtime_verified=runtime_report.runtime_ready,
        exact_version_restore_verified=restore_report.restore_ready,
        independent_restore_target_verified=restore_report.target_isolation_verified,
        tenant_scope_verified=tenant_scope_verified,
        metadata_only_evidence_verified=metadata_only_evidence_verified,
        blocking_reasons=tuple(sorted(set(blocking_reasons))),
        api_start_allowed=ready,
        backend_storage_foundation_ready=ready,
        gate_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"gate_hash": build_backend_storage_foundation_gate_hash(draft)})


def build_backend_storage_foundation_gate_hash(gate: BackendStorageFoundationGate) -> str:
    return sha256_bytes(
        json.dumps(
            gate.model_dump(mode="json", exclude={"gate_hash"}),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def run_backend_storage_foundation_gate_from_environment(
    env: Mapping[str, str],
) -> BackendStorageFoundationGate:
    restore_report = run_exact_version_restore_drill_from_environment(env)
    repository = build_persistent_source_object_repository(env)
    content_store = repository.content_store
    if not isinstance(content_store, S3CompatibleSourceObjectContentStore):
        raise ValueError("backend storage foundation gate requires the S3-compatible content store")

    provider_profile = build_s3_compatible_provider_profile_evidence(
        client=content_store.client,
        storage_policy=repository.storage_policy,
        provider_profile_id=env.get(
            "SUITE_S3_PROVIDER_PROFILE_ID",
            "s3-compatible-provider",
        ),
        checked_at_utc=restore_report.checked_at_utc,
    )
    seed_demo = env.get("SUITE_SOURCE_OBJECT_RUNTIME_SEED_DEMO", "0").strip() == "1"
    runtime_report = run_persistent_source_object_runtime_check(
        repository_factory=lambda: build_persistent_source_object_repository(env),
        provider_profile_evidence=provider_profile,
        restore_drill_report_hash=restore_report.report_hash,
        tenant_ids=restore_report.tenant_ids,
        seed_records=demo_workspace_source_object_records() if seed_demo else (),
        runtime_environment=env.get("SUITE_ENV", "dev"),
        checked_at_utc=restore_report.checked_at_utc,
    )
    return build_backend_storage_foundation_gate(
        runtime_report=runtime_report,
        restore_report=restore_report,
    )


def main() -> None:
    gate = run_backend_storage_foundation_gate_from_environment(os.environ)
    print(json.dumps(gate.model_dump(mode="json"), sort_keys=True))
    raise SystemExit(0 if gate.backend_storage_foundation_ready else 2)


if __name__ == "__main__":
    main()
