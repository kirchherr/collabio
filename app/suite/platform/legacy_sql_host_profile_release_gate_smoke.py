from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.platform.legacy_sql_discovery import LegacySqlConnectorKind
from suite.platform.legacy_sql_discovery_intake import LegacySqlApprovedHostProfile
from suite.platform.legacy_sql_evidence_ledger_operations import (
    LegacySqlEvidenceLedgerBackend,
    LegacySqlEvidenceLedgerOperationsReport,
    run_legacy_sql_evidence_ledger_operations_from_env,
)
from suite.platform.legacy_sql_host_profile_release_gate import (
    LegacySqlHostProfileReleaseGateCommand,
    LegacySqlHostProfileReleaseGateEvidence,
    build_default_legacy_sql_host_profile_release_gate_evidence_store,
    build_legacy_sql_host_profile_release_gate,
    legacy_sql_host_profile_release_gate_ref,
    require_legacy_sql_host_profile_release_gate_for_wiring,
)
from suite.platform.legacy_sql_server_metadata import (
    DEFAULT_CONNECTOR_POLICY_PATH,
    build_legacy_sql_connector_policy_hash,
    load_legacy_sql_connector_policy,
)

LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_SMOKE_SCHEMA_VERSION = "legacy_sql_host_profile_release_gate_smoke_report.v1"


class LegacySqlHostProfileReleaseGateSmokeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_SMOKE_SCHEMA_VERSION
    tenant_id: str
    host_profile_ref: str
    connector_policy_ref: str
    policy_snapshot_hash: str
    ledger_operations_report_hash: str
    ledger_operations_report_ref: str
    ready_gate_evidence_hash: str
    ready_gate_evidence_ref: str
    ready_gate_status: str
    ready_gate_persisted: bool
    ready_wiring_guard_ok: bool
    blocked_gate_evidence_hash: str
    blocked_gate_evidence_ref: str
    blocked_gate_status: str
    blocked_gate_blocking_reasons: tuple[str, ...]
    blocked_gate_persisted: bool
    blocked_wiring_guard_ok: bool
    host_profile_adapter_precondition_ok: bool
    real_connection_used: bool = False
    raw_data_access_allowed: bool = False
    import_dry_run_allowed: bool = False
    import_write_allowed: bool = False
    destructive_actions_allowed: bool = False
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str


def run_legacy_sql_host_profile_release_gate_smoke_from_env(
    environ: Mapping[str, str] | None = None,
) -> LegacySqlHostProfileReleaseGateSmokeReport:
    env = os.environ if environ is None else environ
    checked_by = env.get("SUITE_LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_SMOKE_CHECKED_BY", "legacy-sql-host-gate-smoke")
    ledger_report = run_legacy_sql_evidence_ledger_operations_from_env(env)
    tenant_id = _release_gate_tenant_id(ledger_report=ledger_report, env=env)
    policy = load_legacy_sql_connector_policy(
        Path(env.get("SUITE_LEGACY_SQL_CONNECTOR_POLICY_PATH", str(DEFAULT_CONNECTOR_POLICY_PATH)))
    )
    policy_hash = build_legacy_sql_connector_policy_hash(policy)
    connector_policy_ref = env.get("SUITE_LEGACY_SQL_CONNECTOR_POLICY_REF", "policy:legacy-sql-connector")
    host_profile = LegacySqlApprovedHostProfile(
        host_profile_ref=env.get(
            "SUITE_LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_HOST_PROFILE_REF",
            "legacy-host:sqlserver-production-metadata",
        ),
        connector_kind=LegacySqlConnectorKind.SQLSERVER,
        connector_policy_ref=connector_policy_ref,
        policy_snapshot_hash=policy_hash,
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
    )
    ready_command = _release_gate_command(
        env=env,
        checked_by=checked_by,
        tenant_id=tenant_id,
        host_profile=host_profile,
        policy_hash=policy_hash,
        ledger_report_hash=ledger_report.evidence_hash,
        human_confirmation=True,
    )
    blocked_command = _release_gate_command(
        env=env,
        checked_by=checked_by,
        tenant_id=tenant_id,
        host_profile=host_profile,
        policy_hash=policy_hash,
        ledger_report_hash=ledger_report.evidence_hash,
        human_confirmation=False,
    )
    gate_store = build_default_legacy_sql_host_profile_release_gate_evidence_store(environ=env)
    ready_gate = gate_store.append(
        build_legacy_sql_host_profile_release_gate(
            command=ready_command,
            host_profile=host_profile,
            connector_policy=policy,
            ledger_operations_report=ledger_report,
        )
    )
    blocked_gate = gate_store.append(
        build_legacy_sql_host_profile_release_gate(
            command=blocked_command,
            host_profile=host_profile,
            connector_policy=policy,
            ledger_operations_report=ledger_report,
        )
    )
    ready_wiring_guard_ok = _ready_wiring_guard_ok(gate=ready_gate)
    blocked_wiring_guard_ok = _blocked_wiring_guard_ok(gate=blocked_gate)
    ready_gate_persisted = gate_store.get(tenant_id=tenant_id, evidence_hash=ready_gate.evidence_hash) == ready_gate
    blocked_gate_persisted = (
        gate_store.get(tenant_id=tenant_id, evidence_hash=blocked_gate.evidence_hash) == blocked_gate
    )
    draft = LegacySqlHostProfileReleaseGateSmokeReport(
        tenant_id=tenant_id,
        host_profile_ref=host_profile.host_profile_ref,
        connector_policy_ref=connector_policy_ref,
        policy_snapshot_hash=policy_hash,
        ledger_operations_report_hash=ledger_report.evidence_hash,
        ledger_operations_report_ref=f"legacy-sql-evidence-ledger-operations:{ledger_report.evidence_hash}",
        ready_gate_evidence_hash=ready_gate.evidence_hash,
        ready_gate_evidence_ref=legacy_sql_host_profile_release_gate_ref(ready_gate),
        ready_gate_status=ready_gate.gate_status.value,
        ready_gate_persisted=ready_gate_persisted,
        ready_wiring_guard_ok=ready_wiring_guard_ok,
        blocked_gate_evidence_hash=blocked_gate.evidence_hash,
        blocked_gate_evidence_ref=legacy_sql_host_profile_release_gate_ref(blocked_gate),
        blocked_gate_status=blocked_gate.gate_status.value,
        blocked_gate_blocking_reasons=blocked_gate.blocking_reasons,
        blocked_gate_persisted=blocked_gate_persisted,
        blocked_wiring_guard_ok=blocked_wiring_guard_ok,
        host_profile_adapter_precondition_ok=(
            ready_gate.host_profile_activation_allowed
            and ready_gate.metadata_worker_scheduling_allowed
            and ready_gate_persisted
            and ready_wiring_guard_ok
            and not blocked_gate.host_profile_activation_allowed
            and blocked_gate_persisted
            and blocked_wiring_guard_ok
        ),
        checked_by=checked_by,
        checked_at_utc=datetime.now(UTC),
        evidence_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(
        update={"evidence_hash": build_legacy_sql_host_profile_release_gate_smoke_report_hash(draft)}
    )


def build_legacy_sql_host_profile_release_gate_smoke_report_hash(
    report: LegacySqlHostProfileReleaseGateSmokeReport,
) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def exit_code_for_report(report: LegacySqlHostProfileReleaseGateSmokeReport) -> int:
    return 0 if report.host_profile_adapter_precondition_ok else 1


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the Legacy SQL host profile release gate smoke.")
    parser.add_argument("--once", action="store_true", help="Run one metadata-only smoke and exit.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the metadata-only smoke report.")
    args = parser.parse_args(argv)
    del args.once

    report = run_legacy_sql_host_profile_release_gate_smoke_from_env()
    print(json.dumps(report.model_dump(mode="json"), indent=2 if args.pretty else None, sort_keys=True))
    raise SystemExit(exit_code_for_report(report))


def _release_gate_tenant_id(
    *,
    ledger_report: LegacySqlEvidenceLedgerOperationsReport,
    env: Mapping[str, str],
) -> str:
    tenant_id = env.get("SUITE_LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_TENANT_ID")
    if tenant_id:
        return tenant_id
    for result in ledger_report.backend_results:
        if result.backend == LegacySqlEvidenceLedgerBackend.POSTGRES:
            return result.tenant_id
    return ledger_report.backend_results[0].tenant_id


def _release_gate_command(
    *,
    env: Mapping[str, str],
    checked_by: str,
    tenant_id: str,
    host_profile: LegacySqlApprovedHostProfile,
    policy_hash: str,
    ledger_report_hash: str,
    human_confirmation: bool,
) -> LegacySqlHostProfileReleaseGateCommand:
    confirmation_ref = (
        env.get("SUITE_LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_HUMAN_CONFIRMATION_REF")
        if human_confirmation
        else env.get("SUITE_LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_BLOCKED_CONFIRMATION_REF")
    )
    return LegacySqlHostProfileReleaseGateCommand(
        tenant_id=tenant_id,
        source_system_ref=env.get(
            "SUITE_LEGACY_SQL_HOST_PROFILE_RELEASE_GATE_SOURCE_REF",
            "legacy-sql:production-sqlserver",
        ),
        connector_kind=LegacySqlConnectorKind.SQLSERVER,
        host_profile_ref=host_profile.host_profile_ref,
        connector_policy_ref=host_profile.connector_policy_ref,
        policy_snapshot_hash=policy_hash,
        approved_egress_ref=host_profile.approved_egress_ref,
        connection_secret_ref=host_profile.connection_secret_ref,
        connection_fingerprint_hash=host_profile.connection_fingerprint_hash,
        ledger_operations_report_hash=ledger_report_hash,
        requested_by=checked_by,
        human_confirmation_reference=confirmation_ref
        or (
            "human-confirmation:legacy-sql-host-profile-release"
            if human_confirmation
            else "human-confirmation:legacy-sql-host-profile-blocked-smoke"
        ),
        human_confirmation=human_confirmation,
    )


def _ready_wiring_guard_ok(*, gate: LegacySqlHostProfileReleaseGateEvidence) -> bool:
    try:
        require_legacy_sql_host_profile_release_gate_for_wiring(
            gate=gate,
            tenant_id=gate.tenant_id,
            host_profile_ref=gate.host_profile_ref,
            evidence_hash=gate.evidence_hash,
        )
    except ValueError:
        return False
    return True


def _blocked_wiring_guard_ok(*, gate: LegacySqlHostProfileReleaseGateEvidence) -> bool:
    try:
        require_legacy_sql_host_profile_release_gate_for_wiring(
            gate=gate,
            tenant_id=gate.tenant_id,
            host_profile_ref=gate.host_profile_ref,
            evidence_hash=gate.evidence_hash,
        )
    except ValueError:
        return True
    return False


if __name__ == "__main__":
    main()
