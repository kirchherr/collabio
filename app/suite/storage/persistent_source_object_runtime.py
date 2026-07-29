from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel, Field

from suite.platform.runtime import PRODUCTION_ENVIRONMENTS
from suite.platform.workspace_source_objects import (
    build_default_workspace_source_object_repository,
    demo_workspace_source_object_records,
)
from suite.storage.s3_compatible_content_store import (
    S3CompatibleProviderProfileEvidence,
    S3CompatibleSourceObjectContentStore,
    build_s3_compatible_provider_profile_evidence,
    build_s3_compatible_provider_profile_evidence_hash,
)
from suite.storage.source_object_storage import (
    PgSourceObjectRepository,
    SourceObjectContentRecoveryEvidence,
)
from suite.storage.source_objects import SourceObjectRecord, sha256_bytes, source_object_content_bytes

SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")


class PersistentSourceObjectRuntimeRepository(Protocol):
    def add(self, record: SourceObjectRecord) -> None: ...

    def get(self, *, tenant_id: str, object_id: str, version_id: str) -> SourceObjectRecord: ...

    def build_content_recovery_evidence(
        self,
        *,
        tenant_id: str,
        restore_drill_report_hash: str,
        checked_at_utc: str | None = None,
    ) -> SourceObjectContentRecoveryEvidence: ...


class PersistentSourceObjectTenantRuntimeEvidence(BaseModel):
    tenant_id: str
    expected_source_object_count: int = Field(ge=0)
    restart_verified_source_object_count: int = Field(ge=0)
    stored_object_count: int = Field(ge=0)
    storage_manifest_count: int = Field(ge=0)
    verified_content_count: int = Field(ge=0)
    orphaned_content_count: int = Field(ge=0)
    missing_content_count: int = Field(ge=0)
    source_content_recovery_evidence_hash: str
    api_wiring_allowed: bool
    schema_version: str = "persistent_source_object_tenant_runtime_evidence.v1"


class PersistentSourceObjectRuntimeReport(BaseModel):
    checked_at_utc: str
    runtime_environment: str
    repository_backend: str = "postgres"
    content_store_backend: str = "s3-compatible"
    provider_profile_evidence_hash: str
    restore_drill_report_hash: str
    expected_source_object_count: int = Field(ge=0)
    seeded_source_object_count: int = Field(ge=0)
    existing_source_object_count: int = Field(ge=0)
    restart_verified_source_object_count: int = Field(ge=0)
    tenant_evidence: tuple[PersistentSourceObjectTenantRuntimeEvidence, ...]
    provider_profile_ready: bool
    restart_read_verified: bool
    recovery_verified: bool
    runtime_ready: bool
    content_included: bool = False
    report_hash: str
    schema_version: str = "persistent_source_object_runtime_report.v1"


def run_persistent_source_object_runtime_check(
    *,
    repository_factory: Callable[[], PersistentSourceObjectRuntimeRepository],
    provider_profile_evidence: S3CompatibleProviderProfileEvidence,
    restore_drill_report_hash: str,
    tenant_ids: tuple[str, ...],
    seed_records: tuple[SourceObjectRecord, ...] = (),
    runtime_environment: str = "dev",
    checked_at_utc: str | None = None,
) -> PersistentSourceObjectRuntimeReport:
    environment = runtime_environment.strip().lower()
    if not environment:
        raise ValueError("runtime_environment must not be empty")
    if seed_records and environment in PRODUCTION_ENVIRONMENTS:
        raise ValueError("demo source object seeding is forbidden in production")
    _require_sha256(restore_drill_report_hash, "restore_drill_report_hash")
    if (
        build_s3_compatible_provider_profile_evidence_hash(provider_profile_evidence)
        != provider_profile_evidence.evidence_hash
    ):
        raise ValueError("provider profile evidence hash is invalid")

    expected_records = tuple(
        sorted(
            seed_records,
            key=lambda record: (
                record.metadata.tenant_id,
                record.metadata.object_id,
                record.metadata.version_id,
            ),
        )
    )
    normalized_tenant_ids = tuple(
        sorted(
            {
                *(tenant_id.strip() for tenant_id in tenant_ids if tenant_id.strip()),
                *(record.metadata.tenant_id for record in expected_records),
            }
        )
    )
    if not normalized_tenant_ids:
        raise ValueError("at least one tenant_id is required for persistent source object runtime verification")

    repository = repository_factory()
    seeded_count = 0
    existing_count = 0
    for expected_record in expected_records:
        metadata = expected_record.metadata
        try:
            observed_record = repository.get(
                tenant_id=metadata.tenant_id,
                object_id=metadata.object_id,
                version_id=metadata.version_id,
            )
        except KeyError:
            repository.add(expected_record)
            seeded_count += 1
        else:
            _require_record_match(expected=expected_record, observed=observed_record)
            existing_count += 1

    restarted_repository = repository_factory()
    restart_verified_by_tenant = {tenant_id: 0 for tenant_id in normalized_tenant_ids}
    for expected_record in expected_records:
        metadata = expected_record.metadata
        observed_record = restarted_repository.get(
            tenant_id=metadata.tenant_id,
            object_id=metadata.object_id,
            version_id=metadata.version_id,
        )
        _require_record_match(expected=expected_record, observed=observed_record)
        restart_verified_by_tenant[metadata.tenant_id] += 1

    evidence_time = checked_at_utc or _now_utc()
    tenant_evidence: list[PersistentSourceObjectTenantRuntimeEvidence] = []
    for tenant_id in normalized_tenant_ids:
        recovery = restarted_repository.build_content_recovery_evidence(
            tenant_id=tenant_id,
            restore_drill_report_hash=restore_drill_report_hash,
            checked_at_utc=evidence_time,
        )
        expected_count = sum(1 for record in expected_records if record.metadata.tenant_id == tenant_id)
        tenant_evidence.append(
            PersistentSourceObjectTenantRuntimeEvidence(
                tenant_id=tenant_id,
                expected_source_object_count=expected_count,
                restart_verified_source_object_count=restart_verified_by_tenant[tenant_id],
                stored_object_count=recovery.stored_object_count,
                storage_manifest_count=recovery.storage_manifest_count,
                verified_content_count=recovery.verified_content_count,
                orphaned_content_count=recovery.orphaned_content_count,
                missing_content_count=recovery.missing_content_count,
                source_content_recovery_evidence_hash=recovery.evidence_hash,
                api_wiring_allowed=recovery.api_wiring_allowed,
            )
        )

    restart_verified_count = sum(restart_verified_by_tenant.values())
    restart_read_verified = restart_verified_count == len(expected_records)
    recovery_verified = all(evidence.api_wiring_allowed for evidence in tenant_evidence)
    runtime_ready = provider_profile_evidence.provider_profile_ready and restart_read_verified and recovery_verified
    draft = PersistentSourceObjectRuntimeReport(
        checked_at_utc=evidence_time,
        runtime_environment=environment,
        provider_profile_evidence_hash=provider_profile_evidence.evidence_hash,
        restore_drill_report_hash=restore_drill_report_hash,
        expected_source_object_count=len(expected_records),
        seeded_source_object_count=seeded_count,
        existing_source_object_count=existing_count,
        restart_verified_source_object_count=restart_verified_count,
        tenant_evidence=tuple(tenant_evidence),
        provider_profile_ready=provider_profile_evidence.provider_profile_ready,
        restart_read_verified=restart_read_verified,
        recovery_verified=recovery_verified,
        runtime_ready=runtime_ready,
        report_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"report_hash": build_persistent_source_object_runtime_report_hash(draft)})


def build_persistent_source_object_runtime_report_hash(report: PersistentSourceObjectRuntimeReport) -> str:
    payload = json.dumps(
        report.model_dump(mode="json", exclude={"report_hash"}),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_bytes(payload)


def build_persistent_source_object_repository(
    environ: Mapping[str, str] | None = None,
) -> PgSourceObjectRepository:
    repository = build_default_workspace_source_object_repository(environ)
    if not isinstance(repository, PgSourceObjectRepository):
        raise ValueError("persistent source object runtime requires the PostgreSQL repository backend")
    if not isinstance(repository.content_store, S3CompatibleSourceObjectContentStore):
        raise ValueError("persistent source object runtime requires the S3-compatible content store backend")
    return repository


def main() -> None:
    env = os.environ
    repository = build_persistent_source_object_repository(env)
    content_store = repository.content_store
    if not isinstance(content_store, S3CompatibleSourceObjectContentStore):
        raise ValueError("persistent source object runtime requires the S3-compatible content store backend")
    provider_profile_evidence = build_s3_compatible_provider_profile_evidence(
        client=content_store.client,
        storage_policy=repository.storage_policy,
        provider_profile_id=env.get("SUITE_S3_PROVIDER_PROFILE_ID", "s3-compatible-provider"),
    )
    seed_demo = env.get("SUITE_SOURCE_OBJECT_RUNTIME_SEED_DEMO", "0").strip() == "1"
    tenant_ids = _parse_tenant_ids(env.get("SUITE_SOURCE_OBJECT_RUNTIME_TENANT_IDS", "tenant-demo"))
    report = run_persistent_source_object_runtime_check(
        repository_factory=lambda: build_persistent_source_object_repository(env),
        provider_profile_evidence=provider_profile_evidence,
        restore_drill_report_hash=_required_env(env, "SUITE_SOURCE_OBJECT_RUNTIME_RESTORE_DRILL_REPORT_HASH"),
        tenant_ids=tenant_ids,
        seed_records=demo_workspace_source_object_records() if seed_demo else (),
        runtime_environment=env.get("SUITE_ENV", "dev"),
    )
    print(json.dumps(report.model_dump(mode="json"), sort_keys=True))
    raise SystemExit(0 if report.runtime_ready else 2)


def _require_record_match(*, expected: SourceObjectRecord, observed: SourceObjectRecord) -> None:
    if observed.metadata != expected.metadata:
        raise ValueError("persisted source object metadata does not match the expected bootstrap record")
    if source_object_content_bytes(observed) != source_object_content_bytes(expected):
        raise ValueError("persisted source object content hash boundary does not match the expected bootstrap record")


def _parse_tenant_ids(value: str) -> tuple[str, ...]:
    return tuple(sorted({tenant_id.strip() for tenant_id in value.split(",") if tenant_id.strip()}))


def _required_env(env: Mapping[str, str], name: str) -> str:
    value = env.get(name)
    if value is None or not value.strip():
        raise ValueError(f"Required environment variable missing: {name}")
    return value.strip()


def _require_sha256(value: str, field_name: str) -> None:
    if not SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"{field_name} must be a sha256 reference")


def _now_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


if __name__ == "__main__":
    main()
