from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol, Self
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.platform.legacy_sql_discovery import MODULE_ID_PATTERN, NAMESPACED_REF_PATTERN, LegacySqlConnectorKind
from suite.platform.legacy_sql_host_profile_adapter import (
    LEGACY_SQL_HOST_PROFILE_ADAPTER_SCHEDULE_SCHEMA_VERSION,
    LegacySqlHostProfileAdapter,
    LegacySqlHostProfileAdapterScheduleEvidence,
    build_legacy_sql_host_profile_adapter_schedule_hash,
    build_legacy_sql_host_profile_adapter_schedule_request_from_gate_smoke,
    legacy_sql_host_profile_adapter_schedule_ref,
)
from suite.platform.legacy_sql_host_profile_release_gate import (
    build_default_legacy_sql_host_profile_release_gate_evidence_store,
)
from suite.platform.legacy_sql_host_profile_release_gate_smoke import (
    run_legacy_sql_host_profile_release_gate_smoke_from_env,
)
from suite.platform.storage_paths import suite_data_dir

LEGACY_SQL_METADATA_WORKER_QUEUE_JOB_SCHEMA_VERSION = "legacy_sql_metadata_worker_queue_job.v1"
LEGACY_SQL_METADATA_WORKER_QUEUE_OPERATIONS_SCHEMA_VERSION = "legacy_sql_metadata_worker_queue_operations_report.v1"
LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN = "background_jobs_queues"
LEGACY_SQL_METADATA_WORKER_QUEUE_COMMAND_REF = "docker-compose:legacy-sql-metadata-worker-queue-drill"
LEGACY_SQL_METADATA_WORKER_JOB_REF_PREFIX = "legacy-sql-metadata-worker-job"
ZERO_HASH = "sha256:" + "0" * 64
SHA256_REF_PATTERN = r"^sha256:[a-f0-9]{64}$"
FORBIDDEN_QUEUE_EVIDENCE_FRAGMENTS = (
    '"connection_secret_ref":',
    "secret:legacy-sql",
    "sqlserver://",
    "password",
    "dsn",
    "raw_payload",
    "sample_values",
    "import_write_payload",
    "dbo.kunden",
    "kundenid",
    "email",
)


class LegacySqlMetadataWorkerQueueBackend(StrEnum):
    JSONL = "jsonl"
    POSTGRES = "postgres"


class LegacySqlMetadataWorkerQueueStatus(StrEnum):
    QUEUED = "queued"
    LEASED = "leased"
    RETRY_SCHEDULED = "retry_scheduled"
    BLOCKED = "blocked"


class LegacySqlMetadataWorkerQueueJob(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_METADATA_WORKER_QUEUE_JOB_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    host_profile_ref: str
    schedule_evidence_hash: str
    schedule_evidence_ref: str
    release_gate_evidence_hash: str
    metadata_worker_command_hash: str
    worker_queue_ref: str
    worker_job_ref: str
    worker_idempotency_key_hash: str
    restore_evidence_hash: str
    queue_status: LegacySqlMetadataWorkerQueueStatus = LegacySqlMetadataWorkerQueueStatus.QUEUED
    attempt_count: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=3, ge=1, le=20)
    lease_id: str | None = None
    lease_owner: str | None = None
    leased_until_utc: datetime | None = None
    next_attempt_after_utc: datetime
    last_error_type: str | None = None
    schedule_evidence: LegacySqlHostProfileAdapterScheduleEvidence
    default_compose_legacy_network_enabled: bool = False
    network_connection_opened: bool = False
    real_connection_opened: bool = False
    raw_data_access_allowed: bool = False
    import_dry_run_allowed: bool = False
    import_write_allowed: bool = False
    destructive_actions_allowed: bool = False
    enqueued_at_utc: datetime
    updated_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL metadata worker queue tenant_id must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL metadata worker queue module_id must be lowercase snake_case")
        return value

    @field_validator(
        "source_system_ref",
        "host_profile_ref",
        "schedule_evidence_ref",
        "worker_queue_ref",
        "worker_job_ref",
    )
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL metadata worker queue references must be namespaced")
        return value

    @field_validator(
        "schedule_evidence_hash",
        "release_gate_evidence_hash",
        "metadata_worker_command_hash",
        "worker_idempotency_key_hash",
        "restore_evidence_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL metadata worker queue hashes must be sha256 references")
        return value

    @field_validator("lease_id")
    @classmethod
    def validate_optional_lease_ref(cls, value: str | None) -> str | None:
        if value is not None and not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL metadata worker queue lease_id must be namespaced")
        return value

    @field_validator("lease_owner", "last_error_type")
    @classmethod
    def validate_optional_non_empty_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("legacy SQL metadata worker queue optional text fields must not be empty")
        return value

    @model_validator(mode="after")
    def require_metadata_only_and_bound_schedule(self) -> Self:
        if self.schedule_evidence.schema_version != LEGACY_SQL_HOST_PROFILE_ADAPTER_SCHEDULE_SCHEMA_VERSION:
            raise ValueError("legacy SQL metadata worker queue requires adapter schedule evidence")
        if build_legacy_sql_host_profile_adapter_schedule_hash(self.schedule_evidence) != self.schedule_evidence_hash:
            raise ValueError("legacy SQL metadata worker queue schedule evidence hash mismatch")
        if self.schedule_evidence.evidence_hash != self.schedule_evidence_hash:
            raise ValueError("legacy SQL metadata worker queue schedule evidence hash is not canonical")
        if legacy_sql_host_profile_adapter_schedule_ref(self.schedule_evidence) != self.schedule_evidence_ref:
            raise ValueError("legacy SQL metadata worker queue schedule evidence ref mismatch")
        if self.tenant_id != self.schedule_evidence.tenant_id:
            raise ValueError("legacy SQL metadata worker queue tenant does not match schedule evidence")
        if self.module_id != self.schedule_evidence.module_id:
            raise ValueError("legacy SQL metadata worker queue module does not match schedule evidence")
        if self.source_system_ref != self.schedule_evidence.source_system_ref:
            raise ValueError("legacy SQL metadata worker queue source system does not match schedule evidence")
        if self.connector_kind != self.schedule_evidence.connector_kind:
            raise ValueError("legacy SQL metadata worker queue connector kind does not match schedule evidence")
        if self.host_profile_ref != self.schedule_evidence.host_profile_ref:
            raise ValueError("legacy SQL metadata worker queue host profile does not match schedule evidence")
        if self.release_gate_evidence_hash != self.schedule_evidence.release_gate_evidence_hash:
            raise ValueError("legacy SQL metadata worker queue release gate hash does not match schedule evidence")
        if self.metadata_worker_command_hash != self.schedule_evidence.metadata_worker_command_hash:
            raise ValueError("legacy SQL metadata worker queue command hash does not match schedule evidence")
        if self.worker_queue_ref != self.schedule_evidence.worker_queue_ref:
            raise ValueError("legacy SQL metadata worker queue worker queue ref does not match schedule evidence")
        if self.worker_idempotency_key_hash != build_legacy_sql_metadata_worker_idempotency_key_hash(
            self.schedule_evidence
        ):
            raise ValueError("legacy SQL metadata worker queue idempotency hash mismatch")
        if self.worker_job_ref != legacy_sql_metadata_worker_job_ref(self.worker_idempotency_key_hash):
            raise ValueError("legacy SQL metadata worker queue job ref mismatch")
        if (
            self.default_compose_legacy_network_enabled
            or self.network_connection_opened
            or self.real_connection_opened
            or self.raw_data_access_allowed
            or self.import_dry_run_allowed
            or self.import_write_allowed
            or self.destructive_actions_allowed
        ):
            raise ValueError("legacy SQL metadata worker queue job must not open connections or allow imports")
        if self.queue_status == LegacySqlMetadataWorkerQueueStatus.QUEUED and (
            self.lease_id or self.lease_owner or self.leased_until_utc or self.last_error_type
        ):
            raise ValueError("queued metadata worker jobs must not carry lease or error state")
        if self.queue_status == LegacySqlMetadataWorkerQueueStatus.LEASED:
            if not self.lease_id or not self.lease_owner or self.leased_until_utc is None:
                raise ValueError("leased metadata worker jobs require lease metadata")
            if self.attempt_count < 1:
                raise ValueError("leased metadata worker jobs require at least one attempt")
        if (
            self.queue_status
            in {
                LegacySqlMetadataWorkerQueueStatus.RETRY_SCHEDULED,
                LegacySqlMetadataWorkerQueueStatus.BLOCKED,
            }
            and not self.last_error_type
        ):
            raise ValueError("retry or blocked metadata worker jobs require an error type")
        _assert_queue_evidence_safe(self)
        return self


class LegacySqlMetadataWorkerQueueOperationsReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_METADATA_WORKER_QUEUE_OPERATIONS_SCHEMA_VERSION
    tenant_id: str
    queue_backend: LegacySqlMetadataWorkerQueueBackend
    continuity_domain: str = LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN
    command_ref: str = LEGACY_SQL_METADATA_WORKER_QUEUE_COMMAND_REF
    schedule_evidence_hash: str
    schedule_evidence_ref: str
    worker_idempotency_key_hash: str
    worker_job_ref: str
    queued_job_hash: str
    leased_job_hash: str
    retry_job_hash: str
    restore_evidence_hash: str
    queue_job_count: int = Field(ge=0)
    queue_status_after_enqueue: LegacySqlMetadataWorkerQueueStatus
    queue_status_after_lease: LegacySqlMetadataWorkerQueueStatus
    queue_status_after_retry: LegacySqlMetadataWorkerQueueStatus
    duplicate_enqueue_idempotent: bool
    tenant_isolation_ok: bool
    restore_hash_bound: bool
    blocked_gate_not_enqueued: bool
    metadata_only_ok: bool
    queue_operational: bool
    default_compose_legacy_network_enabled: bool = False
    network_connection_opened: bool = False
    real_connection_opened: bool = False
    raw_data_access_allowed: bool = False
    import_dry_run_allowed: bool = False
    import_write_allowed: bool = False
    destructive_actions_allowed: bool = False
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str


class LegacySqlMetadataWorkerQueueStore(Protocol):
    def enqueue(self, job: LegacySqlMetadataWorkerQueueJob) -> LegacySqlMetadataWorkerQueueJob:
        raise NotImplementedError

    def get(self, *, tenant_id: str, worker_idempotency_key_hash: str) -> LegacySqlMetadataWorkerQueueJob:
        raise NotImplementedError

    def list_jobs(self, *, tenant_id: str) -> tuple[LegacySqlMetadataWorkerQueueJob, ...]:
        raise NotImplementedError

    def lease_next(
        self,
        *,
        tenant_id: str,
        lease_owner: str,
        lease_duration_seconds: int = 300,
        now: datetime | None = None,
    ) -> LegacySqlMetadataWorkerQueueJob | None:
        raise NotImplementedError

    def record_retry(
        self,
        *,
        tenant_id: str,
        worker_idempotency_key_hash: str,
        lease_id: str,
        error_type: str,
        next_attempt_after_utc: datetime,
        now: datetime | None = None,
    ) -> LegacySqlMetadataWorkerQueueJob:
        raise NotImplementedError


class InMemoryLegacySqlMetadataWorkerQueueStore:
    def __init__(self, jobs: tuple[LegacySqlMetadataWorkerQueueJob, ...] = ()) -> None:
        self._jobs: dict[tuple[str, str], LegacySqlMetadataWorkerQueueJob] = {}
        for job in jobs:
            self.enqueue(job)

    def enqueue(self, job: LegacySqlMetadataWorkerQueueJob) -> LegacySqlMetadataWorkerQueueJob:
        _require_valid_queue_job_hash(job)
        key = _queue_key(job)
        existing = self._jobs.get(key)
        if existing is not None:
            _require_same_queue_identity(existing=existing, incoming=job)
            return existing
        self._jobs[key] = job
        return job

    def get(self, *, tenant_id: str, worker_idempotency_key_hash: str) -> LegacySqlMetadataWorkerQueueJob:
        try:
            return self._jobs[(tenant_id, worker_idempotency_key_hash)]
        except KeyError as exc:
            raise KeyError("legacy SQL metadata worker queue job not found") from exc

    def list_jobs(self, *, tenant_id: str) -> tuple[LegacySqlMetadataWorkerQueueJob, ...]:
        return tuple(
            sorted(
                (job for (stored_tenant_id, _), job in self._jobs.items() if stored_tenant_id == tenant_id),
                key=lambda item: (item.next_attempt_after_utc, item.enqueued_at_utc, item.worker_idempotency_key_hash),
            )
        )

    def lease_next(
        self,
        *,
        tenant_id: str,
        lease_owner: str,
        lease_duration_seconds: int = 300,
        now: datetime | None = None,
    ) -> LegacySqlMetadataWorkerQueueJob | None:
        selected = _select_eligible_job(self.list_jobs(tenant_id=tenant_id), now=now or datetime.now(UTC))
        if selected is None:
            return None
        leased = _leased_queue_job(
            selected,
            lease_owner=lease_owner,
            lease_duration_seconds=lease_duration_seconds,
            now=now or datetime.now(UTC),
        )
        self._jobs[_queue_key(leased)] = leased
        return leased

    def record_retry(
        self,
        *,
        tenant_id: str,
        worker_idempotency_key_hash: str,
        lease_id: str,
        error_type: str,
        next_attempt_after_utc: datetime,
        now: datetime | None = None,
    ) -> LegacySqlMetadataWorkerQueueJob:
        job = self.get(tenant_id=tenant_id, worker_idempotency_key_hash=worker_idempotency_key_hash)
        retry = _retry_queue_job(
            job,
            lease_id=lease_id,
            error_type=error_type,
            next_attempt_after_utc=next_attempt_after_utc,
            now=now or datetime.now(UTC),
        )
        self._jobs[_queue_key(retry)] = retry
        return retry


class JsonlLegacySqlMetadataWorkerQueueStore:
    def __init__(self, *, path: Path) -> None:
        self.path = path
        self._jobs: dict[tuple[str, str], LegacySqlMetadataWorkerQueueJob] = {}
        if not path.exists():
            return
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            job = LegacySqlMetadataWorkerQueueJob.model_validate_json(line)
            _require_valid_queue_job_hash(job)
            self._jobs[_queue_key(job)] = job

    def enqueue(self, job: LegacySqlMetadataWorkerQueueJob) -> LegacySqlMetadataWorkerQueueJob:
        _require_valid_queue_job_hash(job)
        existing = self._jobs.get(_queue_key(job))
        if existing is not None:
            _require_same_queue_identity(existing=existing, incoming=job)
            return existing
        self._append(job)
        self._jobs[_queue_key(job)] = job
        return job

    def get(self, *, tenant_id: str, worker_idempotency_key_hash: str) -> LegacySqlMetadataWorkerQueueJob:
        try:
            return self._jobs[(tenant_id, worker_idempotency_key_hash)]
        except KeyError as exc:
            raise KeyError("legacy SQL metadata worker queue job not found") from exc

    def list_jobs(self, *, tenant_id: str) -> tuple[LegacySqlMetadataWorkerQueueJob, ...]:
        return tuple(
            sorted(
                (job for (stored_tenant_id, _), job in self._jobs.items() if stored_tenant_id == tenant_id),
                key=lambda item: (item.next_attempt_after_utc, item.enqueued_at_utc, item.worker_idempotency_key_hash),
            )
        )

    def lease_next(
        self,
        *,
        tenant_id: str,
        lease_owner: str,
        lease_duration_seconds: int = 300,
        now: datetime | None = None,
    ) -> LegacySqlMetadataWorkerQueueJob | None:
        selected = _select_eligible_job(self.list_jobs(tenant_id=tenant_id), now=now or datetime.now(UTC))
        if selected is None:
            return None
        leased = _leased_queue_job(
            selected,
            lease_owner=lease_owner,
            lease_duration_seconds=lease_duration_seconds,
            now=now or datetime.now(UTC),
        )
        self._append(leased)
        self._jobs[_queue_key(leased)] = leased
        return leased

    def record_retry(
        self,
        *,
        tenant_id: str,
        worker_idempotency_key_hash: str,
        lease_id: str,
        error_type: str,
        next_attempt_after_utc: datetime,
        now: datetime | None = None,
    ) -> LegacySqlMetadataWorkerQueueJob:
        job = self.get(tenant_id=tenant_id, worker_idempotency_key_hash=worker_idempotency_key_hash)
        retry = _retry_queue_job(
            job,
            lease_id=lease_id,
            error_type=error_type,
            next_attempt_after_utc=next_attempt_after_utc,
            now=now or datetime.now(UTC),
        )
        self._append(retry)
        self._jobs[_queue_key(retry)] = retry
        return retry

    def _append(self, job: LegacySqlMetadataWorkerQueueJob) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(job.model_dump(mode="json"), sort_keys=True) + "\n")


class PgLegacySqlMetadataWorkerQueueStore:
    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    def enqueue(self, job: LegacySqlMetadataWorkerQueueJob) -> LegacySqlMetadataWorkerQueueJob:
        _require_valid_queue_job_hash(job)
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, job.tenant_id)
            connection.execute(
                """
                INSERT INTO collabio.legacy_sql_metadata_worker_queue (
                    tenant_id,
                    module_id,
                    source_system_ref,
                    connector_kind,
                    host_profile_ref,
                    schedule_evidence_hash,
                    schedule_evidence_ref,
                    release_gate_evidence_hash,
                    metadata_worker_command_hash,
                    worker_queue_ref,
                    worker_job_ref,
                    worker_idempotency_key_hash,
                    restore_evidence_hash,
                    queue_status,
                    attempt_count,
                    max_attempts,
                    lease_id,
                    lease_owner,
                    leased_until_utc,
                    next_attempt_after_utc,
                    last_error_type,
                    default_compose_legacy_network_enabled,
                    network_connection_opened,
                    real_connection_opened,
                    raw_data_access_allowed,
                    import_dry_run_allowed,
                    import_write_allowed,
                    destructive_actions_allowed,
                    schedule_evidence,
                    job_evidence,
                    enqueued_at_utc,
                    updated_at_utc,
                    evidence_hash,
                    schema_version
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s
                )
                ON CONFLICT (tenant_id, worker_idempotency_key_hash) DO NOTHING
                """,
                self._job_values(job),
            )
            connection.commit()
        existing = self.get(
            tenant_id=job.tenant_id,
            worker_idempotency_key_hash=job.worker_idempotency_key_hash,
        )
        _require_same_queue_identity(existing=existing, incoming=job)
        return existing

    def get(self, *, tenant_id: str, worker_idempotency_key_hash: str) -> LegacySqlMetadataWorkerQueueJob:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            row = connection.execute(
                """
                SELECT job_evidence
                FROM collabio.legacy_sql_metadata_worker_queue
                WHERE tenant_id = %s
                  AND worker_idempotency_key_hash = %s
                """,
                (tenant_id, worker_idempotency_key_hash),
            ).fetchone()
        if row is None:
            raise KeyError("legacy SQL metadata worker queue job not found")
        return self._job_from_row(row)

    def list_jobs(self, *, tenant_id: str) -> tuple[LegacySqlMetadataWorkerQueueJob, ...]:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            rows = connection.execute(
                """
                SELECT job_evidence
                FROM collabio.legacy_sql_metadata_worker_queue
                WHERE tenant_id = %s
                ORDER BY next_attempt_after_utc, enqueued_at_utc, worker_idempotency_key_hash
                """,
                (tenant_id,),
            ).fetchall()
        return tuple(self._job_from_row(row) for row in rows)

    def lease_next(
        self,
        *,
        tenant_id: str,
        lease_owner: str,
        lease_duration_seconds: int = 300,
        now: datetime | None = None,
    ) -> LegacySqlMetadataWorkerQueueJob | None:
        checked_at = now or datetime.now(UTC)
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            row = connection.execute(
                """
                SELECT job_evidence
                FROM collabio.legacy_sql_metadata_worker_queue
                WHERE tenant_id = %s
                  AND queue_status IN ('queued', 'retry_scheduled')
                  AND next_attempt_after_utc <= %s
                ORDER BY next_attempt_after_utc, enqueued_at_utc, worker_idempotency_key_hash
                FOR UPDATE SKIP LOCKED
                LIMIT 1
                """,
                (tenant_id, checked_at),
            ).fetchone()
            if row is None:
                connection.rollback()
                return None
            leased = _leased_queue_job(
                self._job_from_row(row),
                lease_owner=lease_owner,
                lease_duration_seconds=lease_duration_seconds,
                now=checked_at,
            )
            self._update_job(connection, leased)
            connection.commit()
        return leased

    def record_retry(
        self,
        *,
        tenant_id: str,
        worker_idempotency_key_hash: str,
        lease_id: str,
        error_type: str,
        next_attempt_after_utc: datetime,
        now: datetime | None = None,
    ) -> LegacySqlMetadataWorkerQueueJob:
        checked_at = now or datetime.now(UTC)
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            row = connection.execute(
                """
                SELECT job_evidence
                FROM collabio.legacy_sql_metadata_worker_queue
                WHERE tenant_id = %s
                  AND worker_idempotency_key_hash = %s
                FOR UPDATE
                """,
                (tenant_id, worker_idempotency_key_hash),
            ).fetchone()
            if row is None:
                raise KeyError("legacy SQL metadata worker queue job not found")
            retry = _retry_queue_job(
                self._job_from_row(row),
                lease_id=lease_id,
                error_type=error_type,
                next_attempt_after_utc=next_attempt_after_utc,
                now=checked_at,
            )
            self._update_job(connection, retry)
            connection.commit()
        return retry

    def _update_job(self, connection: psycopg.Connection[Any], job: LegacySqlMetadataWorkerQueueJob) -> None:
        connection.execute(
            """
            UPDATE collabio.legacy_sql_metadata_worker_queue
            SET queue_status = %s,
                attempt_count = %s,
                lease_id = %s,
                lease_owner = %s,
                leased_until_utc = %s,
                next_attempt_after_utc = %s,
                last_error_type = %s,
                job_evidence = %s,
                updated_at_utc = %s,
                evidence_hash = %s
            WHERE tenant_id = %s
              AND worker_idempotency_key_hash = %s
            """,
            (
                job.queue_status.value,
                job.attempt_count,
                job.lease_id,
                job.lease_owner,
                job.leased_until_utc,
                job.next_attempt_after_utc,
                job.last_error_type,
                Jsonb(job.model_dump(mode="json")),
                job.updated_at_utc,
                job.evidence_hash,
                job.tenant_id,
                job.worker_idempotency_key_hash,
            ),
        )

    def _job_values(self, job: LegacySqlMetadataWorkerQueueJob) -> tuple[object, ...]:
        return (
            job.tenant_id,
            job.module_id,
            job.source_system_ref,
            job.connector_kind.value,
            job.host_profile_ref,
            job.schedule_evidence_hash,
            job.schedule_evidence_ref,
            job.release_gate_evidence_hash,
            job.metadata_worker_command_hash,
            job.worker_queue_ref,
            job.worker_job_ref,
            job.worker_idempotency_key_hash,
            job.restore_evidence_hash,
            job.queue_status.value,
            job.attempt_count,
            job.max_attempts,
            job.lease_id,
            job.lease_owner,
            job.leased_until_utc,
            job.next_attempt_after_utc,
            job.last_error_type,
            job.default_compose_legacy_network_enabled,
            job.network_connection_opened,
            job.real_connection_opened,
            job.raw_data_access_allowed,
            job.import_dry_run_allowed,
            job.import_write_allowed,
            job.destructive_actions_allowed,
            Jsonb(job.schedule_evidence.model_dump(mode="json")),
            Jsonb(job.model_dump(mode="json")),
            job.enqueued_at_utc,
            job.updated_at_utc,
            job.evidence_hash,
            job.schema_version,
        )

    def _job_from_row(self, row: tuple[Any, ...]) -> LegacySqlMetadataWorkerQueueJob:
        raw = row[0]
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        job = LegacySqlMetadataWorkerQueueJob.model_validate(parsed)
        _require_valid_queue_job_hash(job)
        return job

    def _set_tenant(self, connection: psycopg.Connection[Any], tenant_id: str) -> None:
        connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))


def build_legacy_sql_metadata_worker_queue_job(
    *,
    schedule_evidence: LegacySqlHostProfileAdapterScheduleEvidence,
    restore_evidence_hash: str,
    enqueued_at_utc: datetime | None = None,
    max_attempts: int = 3,
) -> LegacySqlMetadataWorkerQueueJob:
    _require_valid_schedule_evidence(schedule_evidence)
    if not re.fullmatch(SHA256_REF_PATTERN, restore_evidence_hash):
        raise ValueError("legacy SQL metadata worker queue restore evidence hash must be sha256")
    queued_at = enqueued_at_utc or datetime.now(UTC)
    idempotency_hash = build_legacy_sql_metadata_worker_idempotency_key_hash(schedule_evidence)
    draft = LegacySqlMetadataWorkerQueueJob(
        tenant_id=schedule_evidence.tenant_id,
        module_id=schedule_evidence.module_id,
        source_system_ref=schedule_evidence.source_system_ref,
        connector_kind=schedule_evidence.connector_kind,
        host_profile_ref=schedule_evidence.host_profile_ref,
        schedule_evidence_hash=schedule_evidence.evidence_hash,
        schedule_evidence_ref=legacy_sql_host_profile_adapter_schedule_ref(schedule_evidence),
        release_gate_evidence_hash=schedule_evidence.release_gate_evidence_hash,
        metadata_worker_command_hash=schedule_evidence.metadata_worker_command_hash,
        worker_queue_ref=schedule_evidence.worker_queue_ref,
        worker_job_ref=legacy_sql_metadata_worker_job_ref(idempotency_hash),
        worker_idempotency_key_hash=idempotency_hash,
        restore_evidence_hash=restore_evidence_hash,
        next_attempt_after_utc=queued_at,
        schedule_evidence=schedule_evidence,
        enqueued_at_utc=queued_at,
        updated_at_utc=queued_at,
        max_attempts=max_attempts,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_metadata_worker_queue_job_hash(draft)})


def build_legacy_sql_metadata_worker_idempotency_key_hash(
    schedule_evidence: LegacySqlHostProfileAdapterScheduleEvidence,
) -> str:
    return stable_hash(
        canonical_json(
            {
                "tenant_id": schedule_evidence.tenant_id,
                "worker_queue_ref": schedule_evidence.worker_queue_ref,
                "schedule_evidence_hash": schedule_evidence.evidence_hash,
                "metadata_worker_command_hash": schedule_evidence.metadata_worker_command_hash,
            }
        )
    )


def legacy_sql_metadata_worker_job_ref(worker_idempotency_key_hash: str) -> str:
    if not re.fullmatch(SHA256_REF_PATTERN, worker_idempotency_key_hash):
        raise ValueError("legacy SQL metadata worker job ref requires a sha256 idempotency key")
    return f"{LEGACY_SQL_METADATA_WORKER_JOB_REF_PREFIX}:{worker_idempotency_key_hash.removeprefix('sha256:')}"


def build_legacy_sql_metadata_worker_queue_job_hash(job: LegacySqlMetadataWorkerQueueJob) -> str:
    return stable_hash(canonical_json(job.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_metadata_worker_queue_operations_report_hash(
    report: LegacySqlMetadataWorkerQueueOperationsReport,
) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def build_default_legacy_sql_metadata_worker_queue_store(
    *,
    environ: Mapping[str, str] | None = None,
    data_dir: Path | None = None,
) -> LegacySqlMetadataWorkerQueueStore:
    env = os.environ if environ is None else environ
    fallback_backend = env.get(
        "SUITE_LEGACY_SQL_METADATA_WORKER_QUEUE_STORE_BACKEND",
        LegacySqlMetadataWorkerQueueBackend.JSONL.value,
    )
    backend = env.get("SUITE_LEGACY_SQL_METADATA_WORKER_QUEUE_BACKEND", fallback_backend).strip()
    if backend == LegacySqlMetadataWorkerQueueBackend.JSONL.value:
        path_value = env.get("SUITE_LEGACY_SQL_METADATA_WORKER_QUEUE_PATH")
        path = (
            Path(path_value)
            if path_value
            else (data_dir or suite_data_dir()) / "legacy_sql_metadata_worker_queue.jsonl"
        )
        return JsonlLegacySqlMetadataWorkerQueueStore(path=path)
    if backend == LegacySqlMetadataWorkerQueueBackend.POSTGRES.value:
        dsn = env.get("SUITE_LEGACY_SQL_METADATA_WORKER_QUEUE_DSN") or env.get("SUITE_DATABASE_DSN")
        if dsn is None:
            raise ValueError("postgres legacy SQL metadata worker queue store requires a database DSN")
        return PgLegacySqlMetadataWorkerQueueStore(database_dsn=dsn)
    raise ValueError(f"unsupported legacy SQL metadata worker queue backend: {backend}")


def run_legacy_sql_metadata_worker_queue_operations_from_env(
    environ: Mapping[str, str] | None = None,
) -> LegacySqlMetadataWorkerQueueOperationsReport:
    env = os.environ if environ is None else environ
    checked_by = env.get(
        "SUITE_LEGACY_SQL_METADATA_WORKER_QUEUE_DRILL_CHECKED_BY",
        "legacy-sql-metadata-worker-queue-drill",
    )
    checked_at = datetime.now(UTC)
    restore_hash = env.get("SUITE_LEGACY_SQL_METADATA_WORKER_QUEUE_RESTORE_HASH", "sha256:" + "7" * 64)
    queue_backend = LegacySqlMetadataWorkerQueueBackend(
        env.get("SUITE_LEGACY_SQL_METADATA_WORKER_QUEUE_BACKEND", LegacySqlMetadataWorkerQueueBackend.JSONL.value)
    )
    gate_smoke = run_legacy_sql_host_profile_release_gate_smoke_from_env(env)
    gate_store = build_default_legacy_sql_host_profile_release_gate_evidence_store(environ=env)
    adapter = LegacySqlHostProfileAdapter(gate_store=gate_store)
    schedule = adapter.prepare_metadata_worker_schedule(
        request=build_legacy_sql_host_profile_adapter_schedule_request_from_gate_smoke(
            env=env,
            gate_smoke=gate_smoke,
            release_gate_evidence_hash=gate_smoke.ready_gate_evidence_hash,
            checked_by=checked_by,
        ),
        checked_at_utc=checked_at,
    )
    store = build_default_legacy_sql_metadata_worker_queue_store(environ=env)
    queued = build_legacy_sql_metadata_worker_queue_job(
        schedule_evidence=schedule,
        restore_evidence_hash=restore_hash,
        enqueued_at_utc=checked_at,
    )
    persisted = store.enqueue(queued)
    duplicate = store.enqueue(queued)
    leased = store.lease_next(
        tenant_id=schedule.tenant_id,
        lease_owner=checked_by,
        lease_duration_seconds=60,
        now=checked_at + timedelta(seconds=1),
    )
    if leased is None:
        raise RuntimeError("legacy SQL metadata worker queue did not lease the queued job")
    retry = store.record_retry(
        tenant_id=leased.tenant_id,
        worker_idempotency_key_hash=leased.worker_idempotency_key_hash,
        lease_id=leased.lease_id or "",
        error_type="restore-drill-worker-retry",
        next_attempt_after_utc=checked_at + timedelta(seconds=30),
        now=checked_at + timedelta(seconds=2),
    )
    tenant_isolation_ok = not store.list_jobs(tenant_id=f"{schedule.tenant_id}-other")
    blocked_gate_not_enqueued = _blocked_gate_not_enqueued(
        adapter=adapter,
        env=env,
        gate_smoke=gate_smoke,
        checked_by=checked_by,
    )
    metadata_only_ok = all(
        not value
        for value in (
            persisted.default_compose_legacy_network_enabled,
            persisted.network_connection_opened,
            persisted.real_connection_opened,
            persisted.raw_data_access_allowed,
            persisted.import_dry_run_allowed,
            persisted.import_write_allowed,
            persisted.destructive_actions_allowed,
            leased.network_connection_opened,
            retry.import_write_allowed,
        )
    )
    duplicate_enqueue_idempotent = (
        duplicate.worker_idempotency_key_hash == persisted.worker_idempotency_key_hash
        and duplicate.schedule_evidence_hash == persisted.schedule_evidence_hash
    )
    restore_hash_bound = retry.restore_evidence_hash == restore_hash
    queue_operational = (
        duplicate_enqueue_idempotent
        and tenant_isolation_ok
        and restore_hash_bound
        and blocked_gate_not_enqueued
        and metadata_only_ok
        and persisted.queue_status == LegacySqlMetadataWorkerQueueStatus.QUEUED
        and leased.queue_status == LegacySqlMetadataWorkerQueueStatus.LEASED
        and retry.queue_status == LegacySqlMetadataWorkerQueueStatus.RETRY_SCHEDULED
    )
    draft = LegacySqlMetadataWorkerQueueOperationsReport(
        tenant_id=schedule.tenant_id,
        queue_backend=queue_backend,
        schedule_evidence_hash=schedule.evidence_hash,
        schedule_evidence_ref=legacy_sql_host_profile_adapter_schedule_ref(schedule),
        worker_idempotency_key_hash=persisted.worker_idempotency_key_hash,
        worker_job_ref=persisted.worker_job_ref,
        queued_job_hash=persisted.evidence_hash,
        leased_job_hash=leased.evidence_hash,
        retry_job_hash=retry.evidence_hash,
        restore_evidence_hash=restore_hash,
        queue_job_count=len(store.list_jobs(tenant_id=schedule.tenant_id)),
        queue_status_after_enqueue=persisted.queue_status,
        queue_status_after_lease=leased.queue_status,
        queue_status_after_retry=retry.queue_status,
        duplicate_enqueue_idempotent=duplicate_enqueue_idempotent,
        tenant_isolation_ok=tenant_isolation_ok,
        restore_hash_bound=restore_hash_bound,
        blocked_gate_not_enqueued=blocked_gate_not_enqueued,
        metadata_only_ok=metadata_only_ok,
        queue_operational=queue_operational,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    _assert_queue_evidence_safe(draft)
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_metadata_worker_queue_operations_report_hash(draft)}
    )


def exit_code_for_report(report: LegacySqlMetadataWorkerQueueOperationsReport) -> int:
    return 0 if report.queue_operational else 1


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Legacy SQL metadata worker queue drill.")
    parser.add_argument("--once", action="store_true", help="Run one metadata-only queue drill and exit.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the metadata-only queue report.")
    args = parser.parse_args(argv)
    del args.once

    report = run_legacy_sql_metadata_worker_queue_operations_from_env()
    print(json.dumps(report.model_dump(mode="json"), indent=2 if args.pretty else None, sort_keys=True))
    raise SystemExit(exit_code_for_report(report))


def _blocked_gate_not_enqueued(
    *,
    adapter: LegacySqlHostProfileAdapter,
    env: Mapping[str, str],
    gate_smoke: Any,
    checked_by: str,
) -> bool:
    try:
        adapter.prepare_metadata_worker_schedule(
            request=build_legacy_sql_host_profile_adapter_schedule_request_from_gate_smoke(
                env=env,
                gate_smoke=gate_smoke,
                release_gate_evidence_hash=gate_smoke.blocked_gate_evidence_hash,
                checked_by=checked_by,
            )
        )
    except ValueError:
        return True
    return False


def _require_valid_schedule_evidence(evidence: LegacySqlHostProfileAdapterScheduleEvidence) -> None:
    expected_hash = build_legacy_sql_host_profile_adapter_schedule_hash(evidence)
    if expected_hash != evidence.evidence_hash:
        raise ValueError("legacy SQL metadata worker queue schedule evidence hash is invalid")
    _assert_queue_evidence_safe(evidence)


def _require_valid_queue_job_hash(job: LegacySqlMetadataWorkerQueueJob) -> None:
    if build_legacy_sql_metadata_worker_queue_job_hash(job) != job.evidence_hash:
        raise ValueError("legacy SQL metadata worker queue job hash is invalid")
    _assert_queue_evidence_safe(job)


def _require_same_queue_identity(
    *,
    existing: LegacySqlMetadataWorkerQueueJob,
    incoming: LegacySqlMetadataWorkerQueueJob,
) -> None:
    if (
        existing.schedule_evidence_hash != incoming.schedule_evidence_hash
        or existing.schedule_evidence_ref != incoming.schedule_evidence_ref
        or existing.worker_job_ref != incoming.worker_job_ref
        or existing.restore_evidence_hash != incoming.restore_evidence_hash
    ):
        raise ValueError("legacy SQL metadata worker queue idempotency key conflict")


def _queue_key(job: LegacySqlMetadataWorkerQueueJob) -> tuple[str, str]:
    return (job.tenant_id, job.worker_idempotency_key_hash)


def _select_eligible_job(
    jobs: Sequence[LegacySqlMetadataWorkerQueueJob],
    *,
    now: datetime,
) -> LegacySqlMetadataWorkerQueueJob | None:
    for job in jobs:
        if (
            job.queue_status
            in {
                LegacySqlMetadataWorkerQueueStatus.QUEUED,
                LegacySqlMetadataWorkerQueueStatus.RETRY_SCHEDULED,
            }
            and job.next_attempt_after_utc <= now
        ):
            return job
    return None


def _leased_queue_job(
    job: LegacySqlMetadataWorkerQueueJob,
    *,
    lease_owner: str,
    lease_duration_seconds: int,
    now: datetime,
) -> LegacySqlMetadataWorkerQueueJob:
    if lease_duration_seconds <= 0:
        raise ValueError("legacy SQL metadata worker queue lease duration must be positive")
    if not lease_owner.strip():
        raise ValueError("legacy SQL metadata worker queue lease owner must not be empty")
    if job.queue_status not in {
        LegacySqlMetadataWorkerQueueStatus.QUEUED,
        LegacySqlMetadataWorkerQueueStatus.RETRY_SCHEDULED,
    }:
        raise ValueError("legacy SQL metadata worker queue can lease only queued or retry-scheduled jobs")
    if job.next_attempt_after_utc > now:
        raise ValueError("legacy SQL metadata worker queue job is not ready for lease")
    lease_id = f"legacy-sql-metadata-worker-lease:{uuid4().hex}"
    draft = job.model_copy(
        update={
            "queue_status": LegacySqlMetadataWorkerQueueStatus.LEASED,
            "attempt_count": job.attempt_count + 1,
            "lease_id": lease_id,
            "lease_owner": lease_owner,
            "leased_until_utc": now + timedelta(seconds=lease_duration_seconds),
            "next_attempt_after_utc": now + timedelta(seconds=lease_duration_seconds),
            "last_error_type": None,
            "updated_at_utc": now,
            "evidence_hash": ZERO_HASH,
        }
    )
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_metadata_worker_queue_job_hash(draft)})


def _retry_queue_job(
    job: LegacySqlMetadataWorkerQueueJob,
    *,
    lease_id: str,
    error_type: str,
    next_attempt_after_utc: datetime,
    now: datetime,
) -> LegacySqlMetadataWorkerQueueJob:
    if job.queue_status != LegacySqlMetadataWorkerQueueStatus.LEASED:
        raise ValueError("legacy SQL metadata worker queue retry requires a leased job")
    if job.lease_id != lease_id:
        raise ValueError("legacy SQL metadata worker queue retry lease mismatch")
    if not error_type.strip():
        raise ValueError("legacy SQL metadata worker queue retry error type must not be empty")
    status = (
        LegacySqlMetadataWorkerQueueStatus.BLOCKED
        if job.attempt_count >= job.max_attempts
        else LegacySqlMetadataWorkerQueueStatus.RETRY_SCHEDULED
    )
    draft = job.model_copy(
        update={
            "queue_status": status,
            "lease_id": None,
            "lease_owner": None,
            "leased_until_utc": None,
            "next_attempt_after_utc": next_attempt_after_utc,
            "last_error_type": error_type,
            "updated_at_utc": now,
            "evidence_hash": ZERO_HASH,
        }
    )
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_metadata_worker_queue_job_hash(draft)})


def _assert_queue_evidence_safe(value: BaseModel) -> None:
    payload = value.model_dump_json().lower()
    for fragment in FORBIDDEN_QUEUE_EVIDENCE_FRAGMENTS:
        if fragment in payload:
            raise ValueError(f"legacy SQL metadata worker queue evidence leaked forbidden fragment: {fragment}")


if __name__ == "__main__":
    main()
