from __future__ import annotations

import argparse
import json
import os
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.platform.legacy_sql_discovery import (
    MODULE_ID_PATTERN,
    NAMESPACED_REF_PATTERN,
    LegacySqlConnectorKind,
)
from suite.platform.legacy_sql_discovery_intake import (
    LegacySqlApprovedHostProfile,
    LegacySqlDiscoveryIntakeGate,
    LegacySqlDiscoveryIntakeRequest,
)
from suite.platform.legacy_sql_discovery_intake_operations import (
    LegacySqlMetadataWorkerCommandView,
    build_legacy_sql_metadata_worker_command_hash,
    build_legacy_sql_metadata_worker_command_view,
)
from suite.platform.legacy_sql_host_profile_release_gate import (
    LegacySqlHostProfileReleaseGateEvidence,
    LegacySqlHostProfileReleaseGateEvidenceStore,
    build_default_legacy_sql_host_profile_release_gate_evidence_store,
    legacy_sql_connection_secret_ref_hash,
    legacy_sql_host_profile_release_gate_ref,
    require_legacy_sql_host_profile_release_gate_for_wiring,
)
from suite.platform.legacy_sql_host_profile_release_gate_smoke import (
    LegacySqlHostProfileReleaseGateSmokeReport,
    run_legacy_sql_host_profile_release_gate_smoke_from_env,
)
from suite.platform.legacy_sql_server_metadata import LegacySqlServerNetworkMode

LEGACY_SQL_HOST_PROFILE_ADAPTER_SCHEDULE_SCHEMA_VERSION = "legacy_sql_host_profile_adapter_schedule.v1"
LEGACY_SQL_HOST_PROFILE_ADAPTER_SMOKE_SCHEMA_VERSION = "legacy_sql_host_profile_adapter_smoke_report.v1"
LEGACY_SQL_HOST_PROFILE_ADAPTER_SCHEDULE_REF_PREFIX = "legacy-sql-host-profile-adapter-schedule"
ZERO_HASH = "sha256:" + "0" * 64
SHA256_REF_PATTERN = r"^sha256:[a-f0-9]{64}$"
FORBIDDEN_ADAPTER_EVIDENCE_FRAGMENTS = (
    '"connection_secret_ref":',
    "secret:legacy-sql",
    "sqlserver://",
    "password",
    "dsn",
    "raw_payload",
    "sample_values",
    "import_write_payload",
)


class LegacySqlHostProfileAdapterScheduleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind = LegacySqlConnectorKind.SQLSERVER
    host_profile_ref: str
    connector_policy_ref: str
    policy_snapshot_hash: str
    approved_egress_ref: str
    connection_secret_ref: str
    connection_fingerprint_hash: str
    release_gate_evidence_hash: str
    requested_by: str
    approval_reference: str
    audit_chain_ref: str
    metadata_worker_profile_ref: str = "worker-profile:legacy-sql-metadata-only"
    worker_queue_ref: str = "worker-queue:legacy-sql-metadata-discovery"
    include_row_counts: bool = True
    dsn: str | None = None
    real_connection_requested: bool = False
    raw_data_access_requested: bool = False
    import_dry_run_requested: bool = False
    import_write_requested: bool = False
    destructive_actions_requested: bool = False

    @field_validator("tenant_id", "requested_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL host profile adapter request text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL host profile adapter module_id must be lowercase snake_case")
        return value

    @field_validator(
        "source_system_ref",
        "host_profile_ref",
        "connector_policy_ref",
        "approved_egress_ref",
        "connection_secret_ref",
        "connection_fingerprint_hash",
        "approval_reference",
        "audit_chain_ref",
        "metadata_worker_profile_ref",
        "worker_queue_ref",
    )
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL host profile adapter references must be namespaced")
        return value

    @field_validator("policy_snapshot_hash", "release_gate_evidence_hash")
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL host profile adapter hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def reject_unsafe_adapter_requests(self) -> LegacySqlHostProfileAdapterScheduleRequest:
        if self.dsn is not None:
            raise ValueError("legacy SQL host profile adapter must use secret references, not DSN values")
        if (
            self.real_connection_requested
            or self.raw_data_access_requested
            or self.import_dry_run_requested
            or self.import_write_requested
            or self.destructive_actions_requested
        ):
            raise ValueError("legacy SQL host profile adapter skeleton only schedules metadata discovery")
        return self


class LegacySqlHostProfileAdapterScheduleEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_HOST_PROFILE_ADAPTER_SCHEDULE_SCHEMA_VERSION
    tenant_id: str
    module_id: str = "crm_erp"
    source_system_ref: str
    connector_kind: LegacySqlConnectorKind
    host_profile_ref: str
    connector_policy_ref: str
    policy_snapshot_hash: str
    approved_egress_ref: str
    connection_secret_ref_hash: str
    connection_fingerprint_hash: str
    release_gate_evidence_hash: str
    release_gate_ref: str
    metadata_worker_profile_ref: str
    worker_queue_ref: str
    worker_network_mode: LegacySqlServerNetworkMode
    include_row_counts: bool
    metadata_worker_command_hash: str
    metadata_worker_command_view: LegacySqlMetadataWorkerCommandView
    metadata_worker_scheduling_allowed: bool
    host_profile_adapter_ready: bool
    default_compose_legacy_network_enabled: bool = False
    network_connection_opened: bool = False
    real_connection_opened: bool = False
    raw_data_access_allowed: bool = False
    import_dry_run_allowed: bool = False
    import_write_allowed: bool = False
    destructive_actions_allowed: bool = False
    requested_by: str
    approval_reference: str
    audit_chain_ref: str
    checked_at_utc: datetime
    evidence_hash: str

    @field_validator("tenant_id", "requested_by")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("legacy SQL host profile adapter evidence text fields must not be empty")
        return value

    @field_validator("module_id")
    @classmethod
    def validate_module_id(cls, value: str) -> str:
        if not MODULE_ID_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL host profile adapter evidence module_id must be lowercase snake_case")
        return value

    @field_validator(
        "source_system_ref",
        "host_profile_ref",
        "connector_policy_ref",
        "approved_egress_ref",
        "connection_fingerprint_hash",
        "release_gate_ref",
        "metadata_worker_profile_ref",
        "worker_queue_ref",
        "approval_reference",
        "audit_chain_ref",
    )
    @classmethod
    def validate_namespaced_refs(cls, value: str) -> str:
        if not NAMESPACED_REF_PATTERN.fullmatch(value):
            raise ValueError("legacy SQL host profile adapter evidence references must be namespaced")
        return value

    @field_validator(
        "policy_snapshot_hash",
        "connection_secret_ref_hash",
        "release_gate_evidence_hash",
        "metadata_worker_command_hash",
        "evidence_hash",
    )
    @classmethod
    def validate_sha256_refs(cls, value: str) -> str:
        if not re.fullmatch(SHA256_REF_PATTERN, value):
            raise ValueError("legacy SQL host profile adapter evidence hashes must be sha256 references")
        return value

    @model_validator(mode="after")
    def require_metadata_only_schedule(self) -> LegacySqlHostProfileAdapterScheduleEvidence:
        if self.worker_network_mode != LegacySqlServerNetworkMode.APPROVED_LEGACY_HOST_ONLY:
            raise ValueError("legacy SQL host profile adapter requires approved legacy-host-only network mode")
        if not self.metadata_worker_scheduling_allowed or not self.host_profile_adapter_ready:
            raise ValueError("legacy SQL host profile adapter evidence must represent a ready schedule")
        if (
            self.default_compose_legacy_network_enabled
            or self.network_connection_opened
            or self.real_connection_opened
            or self.raw_data_access_allowed
            or self.import_dry_run_allowed
            or self.import_write_allowed
            or self.destructive_actions_allowed
        ):
            raise ValueError("legacy SQL host profile adapter schedule must not open connections or allow imports")
        if self.metadata_worker_command_view.tenant_id != self.tenant_id:
            raise ValueError("metadata worker command view tenant does not match schedule")
        if self.metadata_worker_command_view.source_system_ref != self.source_system_ref:
            raise ValueError("metadata worker command view source system does not match schedule")
        if self.metadata_worker_command_view.connector_policy_ref != self.connector_policy_ref:
            raise ValueError("metadata worker command view connector policy does not match schedule")
        if self.metadata_worker_command_view.policy_snapshot_hash != self.policy_snapshot_hash:
            raise ValueError("metadata worker command view policy hash does not match schedule")
        if self.metadata_worker_command_view.connection_fingerprint_hash != self.connection_fingerprint_hash:
            raise ValueError("metadata worker command view fingerprint does not match schedule")
        if not self.metadata_worker_command_view.secret_reference_available:
            raise ValueError("metadata worker schedule requires an available secret reference")
        return self


class LegacySqlHostProfileAdapterSmokeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_HOST_PROFILE_ADAPTER_SMOKE_SCHEMA_VERSION
    tenant_id: str
    host_profile_ref: str
    release_gate_smoke_report_hash: str
    ready_gate_evidence_hash: str
    blocked_gate_evidence_hash: str
    schedule_evidence_hash: str
    schedule_evidence_ref: str
    metadata_worker_command_hash: str
    blocked_gate_rejected: bool
    host_profile_adapter_ready: bool
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


class LegacySqlHostProfileAdapter:
    def __init__(self, *, gate_store: LegacySqlHostProfileReleaseGateEvidenceStore) -> None:
        self.gate_store = gate_store

    def prepare_metadata_worker_schedule(
        self,
        *,
        request: LegacySqlHostProfileAdapterScheduleRequest,
        checked_at_utc: datetime | None = None,
    ) -> LegacySqlHostProfileAdapterScheduleEvidence:
        gate = self.gate_store.get(
            tenant_id=request.tenant_id,
            evidence_hash=request.release_gate_evidence_hash,
        )
        require_legacy_sql_host_profile_release_gate_for_wiring(
            gate=gate,
            tenant_id=request.tenant_id,
            host_profile_ref=request.host_profile_ref,
            evidence_hash=request.release_gate_evidence_hash,
        )
        _require_request_bound_to_gate(request=request, gate=gate)

        host_profile = LegacySqlApprovedHostProfile(
            host_profile_ref=request.host_profile_ref,
            connector_kind=request.connector_kind,
            connector_policy_ref=request.connector_policy_ref,
            policy_snapshot_hash=request.policy_snapshot_hash,
            approved_egress_ref=request.approved_egress_ref,
            connection_secret_ref=request.connection_secret_ref,
            connection_fingerprint_hash=request.connection_fingerprint_hash,
            row_count_estimates_allowed=True,
        )
        if request.connector_kind == LegacySqlConnectorKind.SQLSERVER:
            intake_request = LegacySqlDiscoveryIntakeRequest(
                tenant_id=request.tenant_id,
                module_id=request.module_id,
                source_system_ref=request.source_system_ref,
                connector_kind=request.connector_kind,
                requested_by=request.requested_by,
                approval_reference=request.approval_reference,
                audit_chain_ref=request.audit_chain_ref,
                host_profile_ref=request.host_profile_ref,
                connector_policy_ref=request.connector_policy_ref,
                policy_snapshot_hash=request.policy_snapshot_hash,
                include_row_counts=request.include_row_counts,
            )
            intake_result = LegacySqlDiscoveryIntakeGate().evaluate(request=intake_request, host_profile=host_profile)
            if intake_result.command is None:
                reasons = ", ".join(intake_result.evidence.blocking_reasons) or "unknown"
                raise ValueError(f"legacy SQL host profile adapter schedule is blocked: {reasons}")

            command_view = build_legacy_sql_metadata_worker_command_view(intake_result.command)
            command_hash = build_legacy_sql_metadata_worker_command_hash(intake_result.command)
            if command_view is None or command_hash is None:
                raise ValueError("legacy SQL host profile adapter could not build metadata worker command view")
        else:
            command_view = LegacySqlMetadataWorkerCommandView(
                tenant_id=request.tenant_id,
                module_id=request.module_id,
                source_system_ref=request.source_system_ref,
                connector_kind=request.connector_kind,
                include_row_counts=False,
                connector_policy_ref=request.connector_policy_ref,
                policy_snapshot_hash=request.policy_snapshot_hash,
                connection_fingerprint_hash=request.connection_fingerprint_hash,
                secret_reference_available=bool(request.connection_secret_ref.strip()),
            )
            command_hash = stable_hash(canonical_json(command_view.model_dump(mode="json")))

        draft = LegacySqlHostProfileAdapterScheduleEvidence(
            tenant_id=request.tenant_id,
            module_id=request.module_id,
            source_system_ref=request.source_system_ref,
            connector_kind=request.connector_kind,
            host_profile_ref=request.host_profile_ref,
            connector_policy_ref=request.connector_policy_ref,
            policy_snapshot_hash=request.policy_snapshot_hash,
            approved_egress_ref=request.approved_egress_ref,
            connection_secret_ref_hash=legacy_sql_connection_secret_ref_hash(request.connection_secret_ref),
            connection_fingerprint_hash=request.connection_fingerprint_hash,
            release_gate_evidence_hash=gate.evidence_hash,
            release_gate_ref=legacy_sql_host_profile_release_gate_ref(gate),
            metadata_worker_profile_ref=request.metadata_worker_profile_ref,
            worker_queue_ref=request.worker_queue_ref,
            worker_network_mode=LegacySqlServerNetworkMode.APPROVED_LEGACY_HOST_ONLY,
            include_row_counts=request.include_row_counts,
            metadata_worker_command_hash=command_hash,
            metadata_worker_command_view=command_view,
            metadata_worker_scheduling_allowed=True,
            host_profile_adapter_ready=True,
            requested_by=request.requested_by,
            approval_reference=request.approval_reference,
            audit_chain_ref=request.audit_chain_ref,
            checked_at_utc=checked_at_utc or datetime.now(UTC),
            evidence_hash=ZERO_HASH,
        )
        _assert_adapter_evidence_safe(draft)
        return draft.model_copy(update={"evidence_hash": build_legacy_sql_host_profile_adapter_schedule_hash(draft)})


def build_legacy_sql_host_profile_adapter_schedule_hash(
    evidence: LegacySqlHostProfileAdapterScheduleEvidence,
) -> str:
    return stable_hash(canonical_json(evidence.model_dump(mode="json", exclude={"evidence_hash"})))


def legacy_sql_host_profile_adapter_schedule_ref(evidence: LegacySqlHostProfileAdapterScheduleEvidence) -> str:
    return f"{LEGACY_SQL_HOST_PROFILE_ADAPTER_SCHEDULE_REF_PREFIX}:{evidence.evidence_hash}"


def build_legacy_sql_host_profile_adapter_schedule_request_from_gate_smoke(
    *,
    env: Mapping[str, str],
    gate_smoke: LegacySqlHostProfileReleaseGateSmokeReport,
    release_gate_evidence_hash: str,
    checked_by: str,
) -> LegacySqlHostProfileAdapterScheduleRequest:
    connector_kind = LegacySqlConnectorKind(
        env.get("SUITE_LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_CONNECTOR_KIND", LegacySqlConnectorKind.SQLSERVER.value)
    )
    return LegacySqlHostProfileAdapterScheduleRequest(
        tenant_id=gate_smoke.tenant_id,
        source_system_ref=env.get(
            "SUITE_LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_SOURCE_REF",
            "legacy-sql:production-postgres"
            if connector_kind == LegacySqlConnectorKind.POSTGRES
            else "legacy-sql:production-sqlserver",
        ),
        connector_kind=connector_kind,
        host_profile_ref=gate_smoke.host_profile_ref,
        connector_policy_ref=gate_smoke.connector_policy_ref,
        policy_snapshot_hash=gate_smoke.policy_snapshot_hash,
        approved_egress_ref=env.get(
            "SUITE_LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_EGRESS_REF",
            "egress:legacy-sql-production-metadata",
        ),
        connection_secret_ref=env.get(
            "SUITE_LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_SECRET_REF",
            "secret:legacy-sql-production-metadata",
        ),
        connection_fingerprint_hash=env.get(
            "SUITE_LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_FINGERPRINT_HASH",
            "sha256:legacy-sql-production-fingerprint",
        ),
        release_gate_evidence_hash=release_gate_evidence_hash,
        requested_by=checked_by,
        approval_reference=env.get(
            "SUITE_LEGACY_SQL_HOST_PROFILE_ADAPTER_APPROVAL_REF",
            "approval:legacy-sql-host-profile-adapter-smoke",
        ),
        audit_chain_ref=env.get(
            "SUITE_LEGACY_SQL_HOST_PROFILE_ADAPTER_AUDIT_REF",
            "audit:legacy-sql-host-profile-adapter-smoke",
        ),
    )


def build_legacy_sql_host_profile_adapter_smoke_report_hash(
    report: LegacySqlHostProfileAdapterSmokeReport,
) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def run_legacy_sql_host_profile_adapter_smoke_from_env(
    environ: Mapping[str, str] | None = None,
) -> LegacySqlHostProfileAdapterSmokeReport:
    env = os.environ if environ is None else environ
    checked_by = env.get("SUITE_LEGACY_SQL_HOST_PROFILE_ADAPTER_SMOKE_CHECKED_BY", "legacy-sql-host-adapter-smoke")
    gate_smoke = run_legacy_sql_host_profile_release_gate_smoke_from_env(env)
    gate_store = build_default_legacy_sql_host_profile_release_gate_evidence_store(environ=env)
    adapter = LegacySqlHostProfileAdapter(gate_store=gate_store)
    ready_request = _schedule_request_from_gate_smoke(
        env=env,
        gate_smoke=gate_smoke,
        release_gate_evidence_hash=gate_smoke.ready_gate_evidence_hash,
        checked_by=checked_by,
    )
    schedule = adapter.prepare_metadata_worker_schedule(request=ready_request)
    blocked_gate_rejected = _blocked_gate_rejected(
        adapter=adapter,
        env=env,
        gate_smoke=gate_smoke,
        checked_by=checked_by,
    )
    draft = LegacySqlHostProfileAdapterSmokeReport(
        tenant_id=gate_smoke.tenant_id,
        host_profile_ref=gate_smoke.host_profile_ref,
        release_gate_smoke_report_hash=gate_smoke.evidence_hash,
        ready_gate_evidence_hash=gate_smoke.ready_gate_evidence_hash,
        blocked_gate_evidence_hash=gate_smoke.blocked_gate_evidence_hash,
        schedule_evidence_hash=schedule.evidence_hash,
        schedule_evidence_ref=legacy_sql_host_profile_adapter_schedule_ref(schedule),
        metadata_worker_command_hash=schedule.metadata_worker_command_hash,
        blocked_gate_rejected=blocked_gate_rejected,
        host_profile_adapter_ready=schedule.host_profile_adapter_ready and blocked_gate_rejected,
        checked_by=checked_by,
        checked_at_utc=datetime.now(UTC),
        evidence_hash=ZERO_HASH,
    )
    _assert_adapter_evidence_safe(draft)
    return draft.model_copy(update={"evidence_hash": build_legacy_sql_host_profile_adapter_smoke_report_hash(draft)})


def exit_code_for_report(report: LegacySqlHostProfileAdapterSmokeReport) -> int:
    return 0 if report.host_profile_adapter_ready else 1


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Legacy SQL host profile adapter skeleton smoke.")
    parser.add_argument("--once", action="store_true", help="Run one metadata-only adapter smoke and exit.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the metadata-only adapter smoke report.")
    args = parser.parse_args(argv)
    del args.once

    report = run_legacy_sql_host_profile_adapter_smoke_from_env()
    print(json.dumps(report.model_dump(mode="json"), indent=2 if args.pretty else None, sort_keys=True))
    raise SystemExit(exit_code_for_report(report))


def _require_request_bound_to_gate(
    *,
    request: LegacySqlHostProfileAdapterScheduleRequest,
    gate: LegacySqlHostProfileReleaseGateEvidence,
) -> None:
    expected_secret_hash = legacy_sql_connection_secret_ref_hash(request.connection_secret_ref)
    mismatches: list[str] = []
    if request.source_system_ref != gate.source_system_ref:
        mismatches.append("source_system_ref")
    if request.connector_kind != gate.connector_kind:
        mismatches.append("connector_kind")
    if request.connector_policy_ref != gate.connector_policy_ref:
        mismatches.append("connector_policy_ref")
    if request.policy_snapshot_hash != gate.policy_snapshot_hash:
        mismatches.append("policy_snapshot_hash")
    if request.approved_egress_ref != gate.approved_egress_ref:
        mismatches.append("approved_egress_ref")
    if request.connection_fingerprint_hash != gate.connection_fingerprint_hash:
        mismatches.append("connection_fingerprint_hash")
    if expected_secret_hash != gate.connection_secret_ref_hash:
        mismatches.append("connection_secret_ref_hash")
    if mismatches:
        joined = ", ".join(sorted(mismatches))
        raise ValueError(f"legacy SQL host profile adapter request does not match release gate: {joined}")


def _schedule_request_from_gate_smoke(
    *,
    env: Mapping[str, str],
    gate_smoke: LegacySqlHostProfileReleaseGateSmokeReport,
    release_gate_evidence_hash: str,
    checked_by: str,
) -> LegacySqlHostProfileAdapterScheduleRequest:
    return build_legacy_sql_host_profile_adapter_schedule_request_from_gate_smoke(
        env=env,
        gate_smoke=gate_smoke,
        release_gate_evidence_hash=release_gate_evidence_hash,
        checked_by=checked_by,
    )


def _blocked_gate_rejected(
    *,
    adapter: LegacySqlHostProfileAdapter,
    env: Mapping[str, str],
    gate_smoke: LegacySqlHostProfileReleaseGateSmokeReport,
    checked_by: str,
) -> bool:
    try:
        adapter.prepare_metadata_worker_schedule(
            request=_schedule_request_from_gate_smoke(
                env=env,
                gate_smoke=gate_smoke,
                release_gate_evidence_hash=gate_smoke.blocked_gate_evidence_hash,
                checked_by=checked_by,
            )
        )
    except ValueError:
        return True
    return False


def _assert_adapter_evidence_safe(value: BaseModel) -> None:
    payload = value.model_dump_json().lower()
    for fragment in FORBIDDEN_ADAPTER_EVIDENCE_FRAGMENTS:
        if fragment in payload:
            raise ValueError(f"legacy SQL host profile adapter evidence leaked forbidden fragment: {fragment}")


if __name__ == "__main__":
    main()
