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
    build_legacy_sql_host_profile_adapter_schedule_request_from_gate_smoke,
)
from suite.platform.legacy_sql_host_profile_release_gate import (
    build_default_legacy_sql_host_profile_release_gate_evidence_store,
)
from suite.platform.legacy_sql_host_profile_release_gate_smoke import (
    run_legacy_sql_host_profile_release_gate_smoke_from_env,
)
from suite.platform.legacy_sql_metadata_worker_lease_consumer import (
    LegacySqlMetadataWorkerLeaseConsumer,
    LegacySqlMetadataWorkerLeaseConsumerActivationEvidence,
    LegacySqlMetadataWorkerLeaseConsumerValidationStatus,
    build_legacy_sql_lease_consumer_activation_hash,
)
from suite.platform.legacy_sql_metadata_worker_queue import (
    LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN,
    LegacySqlMetadataWorkerQueueBackend,
    build_default_legacy_sql_metadata_worker_queue_store,
    build_legacy_sql_metadata_worker_queue_job,
)
from suite.platform.legacy_sql_server_metadata import LegacySqlServerNetworkMode

LEGACY_SQL_CONNECTOR_SANDBOX_PROFILE_SCHEMA_VERSION = "legacy_sql_connector_sandbox_profile.v1"
LEGACY_SQL_CONNECTOR_SANDBOX_PROFILE_SMOKE_SCHEMA_VERSION = "legacy_sql_connector_sandbox_profile_smoke_report.v1"
LEGACY_SQL_CONNECTOR_SANDBOX_PROFILE_COMMAND_REF = "docker-compose:legacy-sql-connector-sandbox-profile-smoke"
LEGACY_SQL_CONNECTOR_SANDBOX_PROFILE_REF_PREFIX = "legacy-sql-connector-sandbox-profile"
ZERO_HASH = "sha256:" + "0" * 64
SHA256_REF_PATTERN = r"^sha256:[a-f0-9]{64}$"
FORBIDDEN_SANDBOX_PROFILE_FRAGMENTS = (
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


class LegacySqlConnectorSandboxProfileStatus(StrEnum):
    DEFAULT_OFF = "default_off"
    BLOCKED = "blocked"


class LegacySqlConnectorSandboxProfileEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_SANDBOX_PROFILE_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    host_profile_ref: str
    sandbox_profile_ref: str
    activation_evidence_hash: str
    queue_job_evidence_hash: str
    schedule_evidence_hash: str
    release_gate_evidence_hash: str
    metadata_worker_command_hash: str
    worker_job_ref: str
    worker_idempotency_key_hash: str
    worker_queue_ref: str
    metadata_worker_profile_ref: str
    approved_egress_ref: str
    connection_secret_ref_hash: str
    connection_fingerprint_hash: str
    worker_network_mode: LegacySqlServerNetworkMode
    connector_network_profile_ref: str = "network-profile:legacy-sql-approved-host-default-off"
    secret_resolver_profile_ref: str = "secret-resolver:legacy-sql-handle-only-default-off"
    audit_profile_ref: str = "audit-profile:legacy-sql-connector-sandbox"
    requires_release_gate_evidence: bool = True
    requires_queue_lease: bool = True
    requires_consumer_activation: bool = True
    consumer_activation_validated: bool
    sandbox_profile_visible: bool
    sandbox_profile_enabled: bool = False
    connection_materialization_allowed: bool = False
    secret_material_resolution_allowed: bool = False
    egress_connection_materialized: bool = False
    default_compose_legacy_network_enabled: bool = False
    network_connection_opened: bool = False
    real_connection_opened: bool = False
    raw_data_access_allowed: bool = False
    import_dry_run_allowed: bool = False
    import_write_allowed: bool = False
    destructive_actions_allowed: bool = False
    profile_status: LegacySqlConnectorSandboxProfileStatus
    blocking_reasons: tuple[str, ...]
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "checked_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL connector sandbox profile text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL connector sandbox profile module_id must be lowercase snake_case")
        return value

    @field_validator(
        "source_system_ref",
        "host_profile_ref",
        "sandbox_profile_ref",
        "worker_job_ref",
        "worker_queue_ref",
        "metadata_worker_profile_ref",
        "approved_egress_ref",
        "connection_fingerprint_hash",
        "connector_network_profile_ref",
        "secret_resolver_profile_ref",
        "audit_profile_ref",
    )
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL connector sandbox profile references must be namespaced")
        return value

    @field_validator(
        "activation_evidence_hash",
        "queue_job_evidence_hash",
        "schedule_evidence_hash",
        "release_gate_evidence_hash",
        "metadata_worker_command_hash",
        "worker_idempotency_key_hash",
        "connection_secret_ref_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL connector sandbox profile hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_default_off_sandbox_profile(self) -> Self:
        unsafe = (
            self.sandbox_profile_enabled
            or self.connection_materialization_allowed
            or self.secret_material_resolution_allowed
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
            raise ValueError("legacy SQL connector sandbox profile must stay default-off")
        if self.worker_network_mode != LegacySqlServerNetworkMode.APPROVED_LEGACY_HOST_ONLY:
            raise ValueError("legacy SQL connector sandbox profile requires approved legacy-host-only network mode")
        if self.profile_status == LegacySqlConnectorSandboxProfileStatus.DEFAULT_OFF:
            required = (
                self.requires_release_gate_evidence,
                self.requires_queue_lease,
                self.requires_consumer_activation,
                self.consumer_activation_validated,
                self.sandbox_profile_visible,
            )
            if not all(required) or self.blocking_reasons:
                raise ValueError("default-off sandbox profile requires complete upstream evidence")
        if self.profile_status == LegacySqlConnectorSandboxProfileStatus.BLOCKED and not self.blocking_reasons:
            raise ValueError("blocked sandbox profile requires blocking reasons")
        _assert_sandbox_profile_safe(self)
        return self


class LegacySqlConnectorSandboxProfileSmokeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_CONNECTOR_SANDBOX_PROFILE_SMOKE_SCHEMA_VERSION
    tenant_id: str
    queue_backend: LegacySqlMetadataWorkerQueueBackend
    continuity_domain: str = LEGACY_SQL_METADATA_WORKER_QUEUE_CONTINUITY_DOMAIN
    command_ref: str = LEGACY_SQL_CONNECTOR_SANDBOX_PROFILE_COMMAND_REF
    sandbox_profile_ref: str
    sandbox_profile_evidence_hash: str
    activation_evidence_hash: str
    queue_job_evidence_hash: str
    schedule_evidence_hash: str
    release_gate_evidence_hash: str
    default_off_profile_created: bool
    blocked_activation_rejected: bool
    unsafe_enablement_rejected: bool
    sandbox_profile_visible: bool
    sandbox_profile_enabled: bool = False
    connection_materialization_allowed: bool = False
    secret_material_resolution_allowed: bool = False
    egress_connection_materialized: bool = False
    default_compose_legacy_network_enabled: bool = False
    network_connection_opened: bool = False
    real_connection_opened: bool = False
    raw_data_access_allowed: bool = False
    import_dry_run_allowed: bool = False
    import_write_allowed: bool = False
    destructive_actions_allowed: bool = False
    sandbox_profile_ready: bool
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str


def build_legacy_sql_connector_sandbox_profile(
    *,
    activation: LegacySqlMetadataWorkerLeaseConsumerActivationEvidence,
    checked_by: str,
    checked_at_utc: datetime | None = None,
    sandbox_profile_enabled: bool = False,
) -> LegacySqlConnectorSandboxProfileEvidence:
    checked_at = checked_at_utc or datetime.now(UTC)
    activation_hash_valid = build_legacy_sql_lease_consumer_activation_hash(activation) == activation.evidence_hash
    consumer_activation_validated = (
        activation_hash_valid
        and activation.validation_status == LegacySqlMetadataWorkerLeaseConsumerValidationStatus.VALIDATED
    )
    blocking_reasons = _sandbox_profile_blocking_reasons(
        activation_hash_valid=activation_hash_valid,
        consumer_activation_validated=consumer_activation_validated,
        sandbox_profile_enabled=sandbox_profile_enabled,
    )
    status = (
        LegacySqlConnectorSandboxProfileStatus.DEFAULT_OFF
        if not blocking_reasons
        else LegacySqlConnectorSandboxProfileStatus.BLOCKED
    )
    draft = LegacySqlConnectorSandboxProfileEvidence(
        tenant_id=activation.tenant_id,
        module_id=activation.module_id,
        source_system_ref=activation.source_system_ref,
        connector_kind=activation.connector_kind,
        host_profile_ref=activation.host_profile_ref,
        sandbox_profile_ref=legacy_sql_connector_sandbox_profile_ref(activation),
        activation_evidence_hash=activation.evidence_hash,
        queue_job_evidence_hash=activation.queue_job_evidence_hash,
        schedule_evidence_hash=activation.schedule_evidence_hash,
        release_gate_evidence_hash=activation.release_gate_evidence_hash,
        metadata_worker_command_hash=activation.metadata_worker_command_hash,
        worker_job_ref=activation.worker_job_ref,
        worker_idempotency_key_hash=activation.worker_idempotency_key_hash,
        worker_queue_ref=activation.worker_queue_ref,
        metadata_worker_profile_ref=activation.metadata_worker_profile_ref,
        approved_egress_ref=activation.approved_egress_ref,
        connection_secret_ref_hash=activation.connection_secret_ref_hash,
        connection_fingerprint_hash=activation.connection_fingerprint_hash,
        worker_network_mode=activation.worker_network_mode,
        consumer_activation_validated=consumer_activation_validated,
        sandbox_profile_visible=consumer_activation_validated,
        sandbox_profile_enabled=sandbox_profile_enabled,
        profile_status=status,
        blocking_reasons=blocking_reasons,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    _assert_sandbox_profile_safe(draft)
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_connector_sandbox_profile_hash(draft)})


def legacy_sql_connector_sandbox_profile_ref(
    activation: LegacySqlMetadataWorkerLeaseConsumerActivationEvidence,
) -> str:
    return f"{LEGACY_SQL_CONNECTOR_SANDBOX_PROFILE_REF_PREFIX}:{activation.worker_idempotency_key_hash}"


def build_legacy_sql_connector_sandbox_profile_hash(
    profile: LegacySqlConnectorSandboxProfileEvidence,
) -> str:
    return stable_hash(canonical_json(profile.model_dump(mode="json", exclude={"evidence_hash"})))


def build_legacy_sql_connector_sandbox_profile_smoke_report_hash(
    report: LegacySqlConnectorSandboxProfileSmokeReport,
) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def run_legacy_sql_connector_sandbox_profile_smoke_from_env(
    environ: Mapping[str, str] | None = None,
) -> LegacySqlConnectorSandboxProfileSmokeReport:
    env = os.environ if environ is None else environ
    checked_by = env.get(
        "SUITE_LEGACY_SQL_CONNECTOR_SANDBOX_PROFILE_CHECKED_BY",
        "legacy-sql-connector-sandbox-profile-smoke",
    )
    checked_at = datetime.now(UTC)
    restore_hash = env.get("SUITE_LEGACY_SQL_METADATA_WORKER_QUEUE_RESTORE_HASH", "sha256:" + "a" * 64)
    queue_backend = LegacySqlMetadataWorkerQueueBackend(
        env.get("SUITE_LEGACY_SQL_METADATA_WORKER_QUEUE_BACKEND", LegacySqlMetadataWorkerQueueBackend.JSONL.value)
    )
    activation = _activation_from_env(
        env=env,
        checked_by=checked_by,
        checked_at=checked_at,
        restore_hash=restore_hash,
    )
    profile = build_legacy_sql_connector_sandbox_profile(
        activation=activation,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=3),
    )
    blocked_activation_rejected = (
        build_legacy_sql_connector_sandbox_profile(
            activation=_blocked_activation(activation=activation, checked_at=checked_at + timedelta(seconds=3)),
            checked_by=checked_by,
            checked_at_utc=checked_at + timedelta(seconds=4),
        ).profile_status
        == LegacySqlConnectorSandboxProfileStatus.BLOCKED
    )
    unsafe_enablement_rejected = _unsafe_enablement_rejected(
        activation=activation,
        checked_by=checked_by,
        checked_at=checked_at + timedelta(seconds=5),
    )
    sandbox_profile_ready = (
        profile.profile_status == LegacySqlConnectorSandboxProfileStatus.DEFAULT_OFF
        and profile.sandbox_profile_visible
        and not profile.sandbox_profile_enabled
        and not profile.connection_materialization_allowed
        and not profile.secret_material_resolution_allowed
        and blocked_activation_rejected
        and unsafe_enablement_rejected
    )
    draft = LegacySqlConnectorSandboxProfileSmokeReport(
        tenant_id=activation.tenant_id,
        queue_backend=queue_backend,
        sandbox_profile_ref=profile.sandbox_profile_ref,
        sandbox_profile_evidence_hash=profile.evidence_hash,
        activation_evidence_hash=activation.evidence_hash,
        queue_job_evidence_hash=activation.queue_job_evidence_hash,
        schedule_evidence_hash=activation.schedule_evidence_hash,
        release_gate_evidence_hash=activation.release_gate_evidence_hash,
        default_off_profile_created=profile.profile_status == LegacySqlConnectorSandboxProfileStatus.DEFAULT_OFF,
        blocked_activation_rejected=blocked_activation_rejected,
        unsafe_enablement_rejected=unsafe_enablement_rejected,
        sandbox_profile_visible=profile.sandbox_profile_visible,
        sandbox_profile_ready=sandbox_profile_ready,
        checked_by=checked_by,
        checked_at_utc=checked_at,
        evidence_hash=ZERO_HASH,
    )
    _assert_sandbox_profile_safe(draft)
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_connector_sandbox_profile_smoke_report_hash(draft)}
    )


def exit_code_for_report(report: LegacySqlConnectorSandboxProfileSmokeReport) -> int:
    return 0 if report.sandbox_profile_ready else 1


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Legacy SQL connector sandbox profile smoke.")
    parser.add_argument("--once", action="store_true", help="Run one metadata-only sandbox profile smoke and exit.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the metadata-only sandbox profile report.")
    args = parser.parse_args(argv)
    del args.once

    report = run_legacy_sql_connector_sandbox_profile_smoke_from_env()
    print(json.dumps(report.model_dump(mode="json"), indent=2 if args.pretty else None, sort_keys=True))
    raise SystemExit(exit_code_for_report(report))


def _activation_from_env(
    *,
    env: Mapping[str, str],
    checked_by: str,
    checked_at: datetime,
    restore_hash: str,
) -> LegacySqlMetadataWorkerLeaseConsumerActivationEvidence:
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
    store.enqueue(queued)
    leased = store.lease_next(
        tenant_id=schedule.tenant_id,
        lease_owner=checked_by,
        lease_duration_seconds=60,
        now=checked_at + timedelta(seconds=1),
    )
    if leased is None:
        raise RuntimeError("legacy SQL connector sandbox profile smoke could not acquire a queue lease")
    return LegacySqlMetadataWorkerLeaseConsumer().validate_leased_job(
        job=leased,
        checked_by=checked_by,
        checked_at_utc=checked_at + timedelta(seconds=2),
    )


def _sandbox_profile_blocking_reasons(
    *,
    activation_hash_valid: bool,
    consumer_activation_validated: bool,
    sandbox_profile_enabled: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if not activation_hash_valid:
        reasons.append("consumer_activation_hash_invalid")
    if not consumer_activation_validated:
        reasons.append("consumer_activation_not_validated")
    if sandbox_profile_enabled:
        reasons.append("sandbox_profile_enablement_forbidden_without_enablement_gate")
    return tuple(reasons)


def _blocked_activation(
    *,
    activation: LegacySqlMetadataWorkerLeaseConsumerActivationEvidence,
    checked_at: datetime,
) -> LegacySqlMetadataWorkerLeaseConsumerActivationEvidence:
    draft = activation.model_copy(
        update={
            "validation_status": LegacySqlMetadataWorkerLeaseConsumerValidationStatus.BLOCKED,
            "lease_not_expired": False,
            "blocking_reasons": ("queue_job_lease_expired",),
            "checked_at_utc": checked_at,
            "evidence_hash": ZERO_HASH,
        }
    )
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_lease_consumer_activation_hash(draft)})


def _unsafe_enablement_rejected(
    *,
    activation: LegacySqlMetadataWorkerLeaseConsumerActivationEvidence,
    checked_by: str,
    checked_at: datetime,
) -> bool:
    try:
        build_legacy_sql_connector_sandbox_profile(
            activation=activation,
            checked_by=checked_by,
            checked_at_utc=checked_at,
            sandbox_profile_enabled=True,
        )
    except ValueError:
        return True
    return False


def _assert_sandbox_profile_safe(value: BaseModel) -> None:
    payload = value.model_dump_json().lower()
    for fragment in FORBIDDEN_SANDBOX_PROFILE_FRAGMENTS:
        if fragment in payload:
            raise ValueError(f"legacy SQL connector sandbox profile leaked forbidden fragment: {fragment}")


if __name__ == "__main__":
    main()
