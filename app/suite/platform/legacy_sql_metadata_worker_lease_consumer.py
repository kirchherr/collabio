from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.platform.legacy_sql_discovery import MODULE_ID_PATTERN, NAMESPACED_REF_PATTERN, LegacySqlConnectorKind
from suite.platform.legacy_sql_host_profile_adapter import (
    LegacySqlHostProfileAdapter,
    build_legacy_sql_host_profile_adapter_schedule_hash,
    build_legacy_sql_host_profile_adapter_schedule_request_from_gate_smoke,
)
from suite.platform.legacy_sql_host_profile_release_gate import (
    build_default_legacy_sql_host_profile_release_gate_evidence_store,
)
from suite.platform.legacy_sql_host_profile_release_gate_smoke import (
    run_legacy_sql_host_profile_release_gate_smoke_from_env,
)
from suite.platform.legacy_sql_metadata_worker_queue import (
    LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN,
    LEGACY_SQL_METADATA_WORKER_QUEUE_JOB_SCHEMA_VERSION,
    LegacySqlMetadataWorkerQueueBackend,
    LegacySqlMetadataWorkerQueueJob,
    LegacySqlMetadataWorkerQueueStatus,
    build_default_legacy_sql_metadata_worker_queue_store,
    build_legacy_sql_metadata_worker_queue_job,
    build_legacy_sql_metadata_worker_queue_job_hash,
)
from suite.platform.legacy_sql_server_metadata import LegacySqlServerNetworkMode

LEGACY_SQL_METADATA_WORKER_LEASE_CONSUMER_ACTIVATION_SCHEMA_VERSION = (
    "legacy_sql_metadata_worker_lease_consumer_activation.v1"
)
LEGACY_SQL_METADATA_WORKER_LEASE_CONSUMER_SMOKE_SCHEMA_VERSION = (
    "legacy_sql_metadata_worker_lease_consumer_smoke_report.v1"
)
LEGACY_SQL_METADATA_WORKER_LEASE_CONSUMER_COMMAND_REF = "docker-compose:legacy-sql-metadata-worker-lease-consumer-smoke"
ZERO_HASH = "sha256:" + "0" * 64
SHA256_REF_PATTERN = r"^sha256:[a-f0-9]{64}$"
FORBIDDEN_CONSUMER_EVIDENCE_FRAGMENTS = (
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


class LegacySqlMetadataWorkerLeaseConsumerValidationStatus(StrEnum):
    VALIDATED = "validated"
    BLOCKED = "blocked"


class LegacySqlMetadataWorkerLeaseConsumerActivationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_METADATA_WORKER_LEASE_CONSUMER_ACTIVATION_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    host_profile_ref: str
    worker_queue_ref: str
    worker_job_ref: str
    worker_idempotency_key_hash: str
    queue_job_schema_version: str = LEGACY_SQL_METADATA_WORKER_QUEUE_JOB_SCHEMA_VERSION
    queue_job_evidence_hash: str
    schedule_evidence_hash: str
    schedule_evidence_ref: str
    release_gate_evidence_hash: str
    metadata_worker_command_hash: str
    metadata_worker_command_view_hash: str
    metadata_worker_profile_ref: str
    approved_egress_ref: str
    connection_secret_ref_hash: str
    connection_fingerprint_hash: str
    worker_network_mode: LegacySqlServerNetworkMode
    lease_id: str | None
    lease_owner: str | None
    leased_until_utc: datetime | None
    restore_evidence_hash: str
    queue_job_hash_valid: bool
    schedule_evidence_hash_valid: bool
    command_hash_verified: bool
    lease_state_verified: bool
    lease_not_expired: bool
    egress_handle_verified: bool
    secret_handle_hash_verified: bool
    fingerprint_handle_verified: bool
    network_mode_verified: bool
    offline_runner_only: bool = True
    secret_material_resolved: bool = False
    egress_connection_materialized: bool = False
    default_compose_legacy_network_enabled: bool = False
    network_connection_opened: bool = False
    real_connection_opened: bool = False
    raw_data_access_allowed: bool = False
    import_dry_run_allowed: bool = False
    import_write_allowed: bool = False
    destructive_actions_allowed: bool = False
    validation_status: LegacySqlMetadataWorkerLeaseConsumerValidationStatus
    blocking_reasons: tuple[str, ...]
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL lease consumer evidence text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL lease consumer module_id must be lowercase snake_case")
        return value

    @field_validator(
        "source_system_ref",
        "host_profile_ref",
        "worker_queue_ref",
        "worker_job_ref",
        "schedule_evidence_ref",
        "metadata_worker_profile_ref",
        "approved_egress_ref",
        "connection_fingerprint_hash",
    )
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL lease consumer references must be namespaced")
        return value

    @field_validator("lease_id")
    @classmethod
    def validate_optional_lease_ref(cls, value: str | None) -> str | None:
        if value is not None and not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL lease consumer lease_id must be namespaced")
        return value

    @field_validator("lease_owner")
    @classmethod
    def validate_optional_non_empty_text(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("legacy SQL lease consumer lease_owner must not be empty")
        return value

    @field_validator(
        "worker_idempotency_key_hash",
        "queue_job_evidence_hash",
        "schedule_evidence_hash",
        "release_gate_evidence_hash",
        "metadata_worker_command_hash",
        "metadata_worker_command_view_hash",
        "connection_secret_ref_hash",
        "restore_evidence_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL lease consumer hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_safe_consumer_evidence(self) -> Self:
        unsafe = (
            self.secret_material_resolved
            or self.egress_connection_materialized
            or self.default_compose_legacy_network_enabled
            or self.network_connection_opened
            or self.real_connection_opened
            or self.raw_data_access_allowed
            or self.import_dry_run_allowed
            or self.import_write_allowed
            or self.destructive_actions_allowed
        )
        if unsafe:
            raise ValueError("legacy SQL lease consumer evidence must stay metadata-only")
        if self.validation_status == LegacySqlMetadataWorkerLeaseConsumerValidationStatus.VALIDATED:
            required = (
                self.queue_job_hash_valid,
                self.schedule_evidence_hash_valid,
                self.command_hash_verified,
                self.lease_state_verified,
                self.lease_not_expired,
                self.egress_handle_verified,
                self.secret_handle_hash_verified,
                self.fingerprint_handle_verified,
                self.network_mode_verified,
                self.offline_runner_only,
            )
            if not all(required) or self.blocking_reasons:
                raise ValueError("validated legacy SQL lease consumer evidence cannot have blocking reasons")
        if (
            self.validation_status == LegacySqlMetadataWorkerLeaseConsumerValidationStatus.BLOCKED
            and not self.blocking_reasons
        ):
            raise ValueError("blocked legacy SQL lease consumer evidence requires blocking reasons")
        _assert_consumer_evidence_safe(self)
        return self


class LegacySqlMetadataWorkerLeaseConsumerSmokeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_METADATA_WORKER_LEASE_CONSUMER_SMOKE_SCHEMA_VERSION
    tenant_id: str
    queue_backend: LegacySqlMetadataWorkerQueueBackend
    continuity_domain: str = LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN
    command_ref: str = LEGACY_SQL_METADATA_WORKER_LEASE_CONSUMER_COMMAND_REF
    worker_job_ref: str
    worker_idempotency_key_hash: str
    schedule_evidence_hash: str
    queue_job_evidence_hash: str
    activation_evidence_hash: str
    queued_job_rejected: bool
    expired_lease_rejected: bool
    egress_handle_verified: bool
    secret_handle_hash_verified: bool
    fingerprint_handle_verified: bool
    offline_runner_only: bool
    lease_consumer_ready: bool
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


class LegacySqlMetadataWorkerLeaseConsumer:
    def validate_leased_job(
        self,
        *,
        job: LegacySqlMetadataWorkerQueueJob,
        checked_by: str,
        checked_at_utc: datetime | None = None,
    ) -> LegacySqlMetadataWorkerLeaseConsumerActivationEvidence:
        checked_at = checked_at_utc or datetime.now(UTC)
        schedule = job.schedule_evidence
        queue_job_hash_valid = build_legacy_sql_metadata_worker_queue_job_hash(job) == job.evidence_hash
        schedule_evidence_hash_valid = (
            build_legacy_sql_host_profile_adapter_schedule_hash(schedule)
            == job.schedule_evidence_hash
            == schedule.evidence_hash
        )
        command_hash_verified = job.metadata_worker_command_hash == schedule.metadata_worker_command_hash
        lease_state_verified = (
            job.queue_status == LegacySqlMetadataWorkerQueueStatus.LEASED
            and job.lease_id is not None
            and job.lease_owner is not None
            and job.leased_until_utc is not None
        )
        lease_not_expired = job.leased_until_utc is not None and job.leased_until_utc > checked_at
        egress_handle_verified = bool(NAMESPACED_REF_PATTERN.fullmatch(schedule.approved_egress_ref))
        secret_handle_hash_verified = bool(re.fullmatch(SHA256_REF_PATTERN, schedule.connection_secret_ref_hash))
        fingerprint_handle_verified = bool(NAMESPACED_REF_PATTERN.fullmatch(schedule.connection_fingerprint_hash))
        network_mode_verified = schedule.worker_network_mode == LegacySqlServerNetworkMode.APPROVED_LEGACY_HOST_ONLY
        metadata_only = _queue_job_metadata_only(job)
        blocking_reasons = _consumer_blocking_reasons(
            queue_job_hash_valid=queue_job_hash_valid,
            schedule_evidence_hash_valid=schedule_evidence_hash_valid,
            command_hash_verified=command_hash_verified,
            lease_state_verified=lease_state_verified,
            lease_not_expired=lease_not_expired,
            egress_handle_verified=egress_handle_verified,
            secret_handle_hash_verified=secret_handle_hash_verified,
            fingerprint_handle_verified=fingerprint_handle_verified,
            network_mode_verified=network_mode_verified,
            metadata_only=metadata_only,
        )
        status = (
            LegacySqlMetadataWorkerLeaseConsumerValidationStatus.VALIDATED
            if not blocking_reasons
            else LegacySqlMetadataWorkerLeaseConsumerValidationStatus.BLOCKED
        )
        draft = LegacySqlMetadataWorkerLeaseConsumerActivationEvidence(
            tenant_id=job.tenant_id,
            module_id=job.module_id,
            source_system_ref=job.source_system_ref,
            connector_kind=job.connector_kind,
            host_profile_ref=job.host_profile_ref,
            worker_queue_ref=job.worker_queue_ref,
            worker_job_ref=job.worker_job_ref,
            worker_idempotency_key_hash=job.worker_idempotency_key_hash,
            queue_job_evidence_hash=job.evidence_hash,
            schedule_evidence_hash=job.schedule_evidence_hash,
            schedule_evidence_ref=job.schedule_evidence_ref,
            release_gate_evidence_hash=job.release_gate_evidence_hash,
            metadata_worker_command_hash=job.metadata_worker_command_hash,
            metadata_worker_command_view_hash=stable_hash(
                canonical_json(schedule.metadata_worker_command_view.model_dump(mode="json"))
            ),
            metadata_worker_profile_ref=schedule.metadata_worker_profile_ref,
            approved_egress_ref=schedule.approved_egress_ref,
            connection_secret_ref_hash=schedule.connection_secret_ref_hash,
            connection_fingerprint_hash=schedule.connection_fingerprint_hash,
            worker_network_mode=schedule.worker_network_mode,
            lease_id=job.lease_id,
            lease_owner=job.lease_owner,
            leased_until_utc=job.leased_until_utc,
            restore_evidence_hash=job.restore_evidence_hash,
            queue_job_hash_valid=queue_job_hash_valid,
            schedule_evidence_hash_valid=schedule_evidence_hash_valid,
            command_hash_verified=command_hash_verified,
            lease_state_verified=lease_state_verified,
            lease_not_expired=lease_not_expired,
            egress_handle_verified=egress_handle_verified,
            secret_handle_hash_verified=secret_handle_hash_verified,
            fingerprint_handle_verified=fingerprint_handle_verified,
            network_mode_verified=network_mode_verified,
            validation_status=status,
            blocking_reasons=blocking_reasons,
            checked_by=checked_by,
            checked_at_utc=checked_at,
            evidence_hash=ZERO_HASH,
        )
        _assert_consumer_evidence_safe(draft)
        return draft.model_copy(update={"evidence_hash": build_legacy_sql_lease_consumer_activation_hash(draft)})


def build_legacy_sql_lease_consumer_activation_hash(
    evidence: LegacySqlMetadataWorkerLeaseConsumerActivationEvidence,
) -> str:
    return stable_hash(canonical_json(evidence.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_lease_consumer_smoke_report_hash(
    report: LegacySqlMetadataWorkerLeaseConsumerSmokeReport,
) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def run_legacy_sql_metadata_worker_lease_consumer_smoke_from_env(
    environ: Mapping[str, str] | None = None,
) -> LegacySqlMetadataWorkerLeaseConsumerSmokeReport:
    env = os.environ if environ is None else environ
    checked_by = env.get(
        "SUITE_LEGACY_SQL_METADATA_WORKER_LEASE_CONSUMER_CHECKED_BY",
        "legacy-sql-metadata-worker-lease-consumer-smoke",
    )
    checked_at = datetime.now(UTC)
    restore_hash = env.get("SUITE_LEGACY_SQL_METADATA_WORKER_QUEUE_RESTORE_HASH", "sha256:" + "8" * 64)
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
    leased = store.lease_next(
        tenant_id=schedule.tenant_id,
        lease_owner=checked_by,
        lease_duration_seconds=60,
        now=checked_at + timedelta(seconds=1),
    )
    if leased is None:
        raise RuntimeError("legacy SQL metadata worker lease consumer could not acquire a queue lease")

    consumer = LegacySqlMetadataWorkerLeaseConsumer()
    activation = consumer.validate_leased_job(
        job=leased,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=2),
    )
    queued_job_rejected = (
        consumer.validate_leased_job(
            job=persisted,
            checked_by=checked_by,
            checked_at_utc=checked_at + timedelta(seconds=2),
        ).validation_status
        == LegacySqlMetadataWorkerLeaseConsumerValidationStatus.BLOCKED
    )
    expired_lease_rejected = (
        consumer.validate_leased_job(
            job=_expired_queue_job(leased=leased, expired_at=checked_at),
            checked_by=checked_by,
            checked_at_utc=checked_at + timedelta(seconds=2),
        ).validation_status
        == LegacySqlMetadataWorkerLeaseConsumerValidationStatus.BLOCKED
    )
    lease_consumer_ready = (
        activation.validation_status == LegacySqlMetadataWorkerLeaseConsumerValidationStatus.VALIDATED
        and queued_job_rejected
        and expired_lease_rejected
        and activation.egress_handle_verified
        and activation.secret_handle_hash_verified
        and activation.fingerprint_handle_verified
        and activation.offline_runner_only
        and not activation.network_connection_opened
        and not activation.real_connection_opened
        and not activation.import_write_allowed
    )
    draft = LegacySqlMetadataWorkerLeaseConsumerSmokeReport(
        tenant_id=schedule.tenant_id,
        queue_backend=queue_backend,
        worker_job_ref=leased.worker_job_ref,
        worker_idempotency_key_hash=leased.worker_idempotency_key_hash,
        schedule_evidence_hash=schedule.evidence_hash,
        queue_job_evidence_hash=leased.evidence_hash,
        activation_evidence_hash=activation.evidence_hash,
        queued_job_rejected=queued_job_rejected,
        expired_lease_rejected=expired_lease_rejected,
        egress_handle_verified=activation.egress_handle_verified,
        secret_handle_hash_verified=activation.secret_handle_hash_verified,
        fingerprint_handle_verified=activation.fingerprint_handle_verified,
        offline_runner_only=activation.offline_runner_only,
        lease_consumer_ready=lease_consumer_ready,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    _assert_consumer_evidence_safe(draft)
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_lease_consumer_smoke_report_hash(draft)})


def exit_code_for_report(report: LegacySqlMetadataWorkerLeaseConsumerSmokeReport) -> int:
    return 0 if report.lease_consumer_ready else 1


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Legacy SQL metadata worker lease consumer smoke.")
    parser.add_argument("--once", action="store_true", help="Run one metadata-only lease consumer smoke and exit.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the metadata-only consumer report.")
    args = parser.parse_args(argv)
    del args.once

    report = run_legacy_sql_metadata_worker_lease_consumer_smoke_from_env()
    print(json.dumps(report.model_dump(mode="json"), indent=2 if args.pretty else None, sort_keys=True))
    raise SystemExit(exit_code_for_report(report))


def _consumer_blocking_reasons(
    *,
    queue_job_hash_valid: bool,
    schedule_evidence_hash_valid: bool,
    command_hash_verified: bool,
    lease_state_verified: bool,
    lease_not_expired: bool,
    egress_handle_verified: bool,
    secret_handle_hash_verified: bool,
    fingerprint_handle_verified: bool,
    network_mode_verified: bool,
    metadata_only: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not queue_job_hash_valid:
        reasons.append("queue_job_hash_invalid")
    if not schedule_evidence_hash_valid:
        reasons.append("schedule_evidence_hash_invalid")
    if not command_hash_verified:
        reasons.append("metadata_worker_command_hash_mismatch")
    if not lease_state_verified:
        reasons.append("queue_job_not_leased")
    if not lease_not_expired:
        reasons.append("queue_job_lease_expired")
    if not egress_handle_verified:
        reasons.append("egress_handle_not_verified")
    if not secret_handle_hash_verified:
        reasons.append("secret_handle_hash_not_verified")
    if not fingerprint_handle_verified:
        reasons.append("fingerprint_handle_not_verified")
    if not network_mode_verified:
        reasons.append("network_mode_not_approved_legacy_host_only")
    if not metadata_only:
        reasons.append("metadata_only_boundary_broken")
    return tuple(reasons)


def _queue_job_metadata_only(job: LegacySqlMetadataWorkerQueueJob) -> bool:
    schedule = job.schedule_evidence
    return not any(
        (
            job.default_compose_legacy_network_enabled,
            job.network_connection_opened,
            job.real_connection_opened,
            job.raw_data_access_allowed,
            job.import_dry_run_allowed,
            job.import_write_allowed,
            job.destructive_actions_allowed,
            schedule.default_compose_legacy_network_enabled,
            schedule.network_connection_opened,
            schedule.real_connection_opened,
            schedule.raw_data_access_allowed,
            schedule.import_dry_run_allowed,
            schedule.import_write_allowed,
            schedule.destructive_actions_allowed,
        )
    )


def _expired_queue_job(
    *,
    leased: LegacySqlMetadataWorkerQueueJob,
    expired_at: datetime,
) -> LegacySqlMetadataWorkerQueueJob:
    draft = leased.model_copy(
        update={
            "leased_until_utc": expired_at - timedelta(seconds=1),
            "next_attempt_after_utc": expired_at - timedelta(seconds=1),
            "updated_at_utc": expired_at,
            "evidence_hash": ZERO_HASH,
        }
    )
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_metadata_worker_queue_job_hash(draft)})


def _assert_consumer_evidence_safe(value: BaseModel) -> None:
    payload = value.model_dump_json().lower()
    for fragment in FORBIDDEN_CONSUMER_EVIDENCE_FRAGMENTS:
        if fragment in payload:
            raise ValueError(f"legacy SQL lease consumer evidence leaked forbidden fragment: {fragment}")


if __name__ == "__main__":
    main()
