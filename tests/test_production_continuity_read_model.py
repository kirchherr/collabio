from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from suite.ai_control_plane.models import UserContext
from suite.operations.backup_failover import BackupFailoverPolicy, load_backup_failover_policy
from suite.operations.production_continuity_deployment_gate import (
    ProductionContinuityDeploymentGate,
    build_backup_failover_policy_hash,
    build_production_continuity_deployment_gate_hash,
    persist_production_continuity_deployment_gate,
)
from suite.platform.production_continuity_read_model import (
    ProductionContinuityGateState,
    ProductionContinuityReadModelUnavailable,
    build_production_continuity_evidence_requirements_response,
    build_production_continuity_gate_status_from_environment,
    build_production_continuity_gate_status_response,
    load_production_continuity_policy_from_environment,
)
from suite.storage.source_objects import sha256_bytes

REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = REPO_ROOT / "docs" / "operations" / "backup_failover_policy.json"


def _hash(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def _user_context(tenant_id: str = "tenant-demo") -> UserContext:
    return UserContext(user_id="security-admin-1", tenant_id=tenant_id, role_ids={"security-admin"})


def _policy() -> BackupFailoverPolicy:
    return load_backup_failover_policy(POLICY_PATH)


def _gate(
    *,
    policy: BackupFailoverPolicy,
    checked_at: datetime,
    valid_until: datetime | None = None,
    ready: bool = True,
) -> ProductionContinuityDeploymentGate:
    blocking_reasons = () if ready else ("cross_site_failover_not_verified",)
    draft = ProductionContinuityDeploymentGate(
        checked_at_utc=checked_at.isoformat(),
        valid_until_utc=(valid_until or checked_at + timedelta(hours=1)).isoformat(),
        deployment_ref_hash=_hash("deployment"),
        backup_policy_schema_version=policy.schema_version,
        backup_policy_hash=build_backup_failover_policy_hash(policy),
        evidence_bundle_hash=_hash("evidence-bundle"),
        required_target_ids=policy.production_deployment_gate.required_target_ids,
        critical_continuity_domain_count=sum(
            1 for domain in policy.continuity_domains if domain.criticality == "critical"
        ),
        continuity_domain_coverage_verified=True,
        evidence_deployment_binding_verified=True,
        evidence_freshness_verified=True,
        postgres_pitr_verified=True,
        encrypted_offsite_backup_verified=True,
        ha_manual_promotion_verified=True,
        cross_site_failover_verified=ready,
        independent_failure_domains_verified=True,
        encryption_and_key_recovery_verified=True,
        retention_object_lock_legal_hold_verified=True,
        tenant_isolation_verified=True,
        approvals_verified=True,
        automatic_failover_enabled=False,
        automatic_failover_admitted=False,
        metadata_only_evidence_verified=True,
        blocking_reasons=blocking_reasons,
        deployment_ready=ready,
        gate_hash=_hash("draft"),
    )
    return draft.model_copy(update={"gate_hash": build_production_continuity_deployment_gate_hash(draft)})


def test_requirements_are_tenant_bound_policy_derived_and_non_executing() -> None:
    policy = _policy()

    response = build_production_continuity_evidence_requirements_response(
        user_context=_user_context("tenant-a"),
        policy=policy,
    )

    assert response.tenant_id == "tenant-a"
    assert response.policy_schema_version == "backup_failover_policy.v3"
    assert response.policy_hash == build_backup_failover_policy_hash(policy)
    assert response.required_section_ids == (
        "postgres_pitr",
        "encrypted_offsite_backup",
        "ha_promotion",
        "cross_site_failover",
        "approvals",
    )
    assert len(response.target_requirements) == 3
    assert {item.capability_id for item in response.implementation_requirements} == {
        "postgres_pitr",
        "encrypted_offsite_backup",
        "ha_orchestration",
        "cross_site_failover",
    }
    assert response.required_distinct_approval_count == 3
    assert response.evidence_reference_format == "sha256_only"
    assert response.evidence_submission_allowed is False
    assert response.deployment_execution_allowed is False
    assert response.failover_execution_allowed is False
    assert response.content_included is False
    assert response.secrets_included is False


def test_gate_status_is_missing_without_configured_report() -> None:
    response = build_production_continuity_gate_status_response(
        user_context=_user_context(),
        policy=_policy(),
        report_path=None,
        runtime_switch_requested=True,
        checked_at=datetime(2026, 8, 5, 7, 0, tzinfo=UTC),
    )

    assert response.state == ProductionContinuityGateState.MISSING
    assert response.blocking_reasons == ("production_continuity_gate_report_not_configured",)
    assert response.report_present is False
    assert response.continuity_gate_ready is False
    assert response.runtime_switch_requested is True
    assert response.runtime_enablement_allowed is False


def test_gate_status_rejects_invalid_report_without_leaking_input(tmp_path: Path) -> None:
    report_path = tmp_path / "gate.json"
    report_path.write_text('{"secret":"do-not-leak"}', encoding="utf-8")

    response = build_production_continuity_gate_status_response(
        user_context=_user_context(),
        policy=_policy(),
        report_path=report_path,
        runtime_switch_requested=False,
        checked_at=datetime(2026, 8, 5, 7, 0, tzinfo=UTC),
    )

    assert response.state == ProductionContinuityGateState.INVALID
    assert response.blocking_reasons == ("production_continuity_gate_report_invalid",)
    assert response.report_present is True
    assert response.report_hash_verified is False
    assert "do-not-leak" not in response.model_dump_json()
    assert str(report_path) not in response.model_dump_json()


def test_gate_status_reports_blocked_gate_without_opening_runtime(tmp_path: Path) -> None:
    policy = _policy()
    now = datetime(2026, 8, 5, 7, 0, tzinfo=UTC)
    report_path = tmp_path / "gate.json"
    persist_production_continuity_deployment_gate(
        gate=_gate(policy=policy, checked_at=now - timedelta(minutes=5), ready=False),
        report_path=report_path,
    )

    response = build_production_continuity_gate_status_response(
        user_context=_user_context(),
        policy=policy,
        report_path=report_path,
        runtime_switch_requested=True,
        checked_at=now,
    )

    assert response.state == ProductionContinuityGateState.BLOCKED
    assert response.blocking_reasons == ("cross_site_failover_not_verified",)
    assert response.report_hash_verified is True
    assert response.policy_binding_verified is True
    assert response.evidence_freshness_verified is True
    assert response.continuity_gate_ready is False
    assert response.runtime_enablement_allowed is False


def test_gate_status_expires_a_previously_ready_report(tmp_path: Path) -> None:
    policy = _policy()
    now = datetime(2026, 8, 5, 7, 0, tzinfo=UTC)
    report_path = tmp_path / "gate.json"
    persist_production_continuity_deployment_gate(
        gate=_gate(
            policy=policy,
            checked_at=now - timedelta(hours=2),
            valid_until=now - timedelta(minutes=1),
        ),
        report_path=report_path,
    )

    response = build_production_continuity_gate_status_response(
        user_context=_user_context(),
        policy=policy,
        report_path=report_path,
        runtime_switch_requested=True,
        checked_at=now,
    )

    assert response.state == ProductionContinuityGateState.EXPIRED
    assert response.blocking_reasons == ("production_continuity_gate_report_expired",)
    assert response.evidence_freshness_verified is False
    assert response.runtime_enablement_allowed is False


def test_gate_status_separates_ready_evidence_from_runtime_switch(tmp_path: Path) -> None:
    policy = _policy()
    now = datetime(2026, 8, 5, 7, 0, tzinfo=UTC)
    report_path = tmp_path / "gate.json"
    persist_production_continuity_deployment_gate(
        gate=_gate(policy=policy, checked_at=now - timedelta(minutes=5)),
        report_path=report_path,
    )

    switch_closed = build_production_continuity_gate_status_response(
        user_context=_user_context("tenant-a"),
        policy=policy,
        report_path=report_path,
        runtime_switch_requested=False,
        checked_at=now,
    )
    switch_requested = build_production_continuity_gate_status_response(
        user_context=_user_context("tenant-b"),
        policy=policy,
        report_path=report_path,
        runtime_switch_requested=True,
        checked_at=now,
    )

    assert switch_closed.state == ProductionContinuityGateState.READY
    assert switch_closed.continuity_gate_ready is True
    assert switch_closed.runtime_enablement_allowed is False
    assert switch_requested.state == ProductionContinuityGateState.READY
    assert switch_requested.runtime_enablement_allowed is True
    assert switch_requested.pilot_traffic_allowed is False
    assert switch_closed.tenant_id == "tenant-a"
    assert switch_requested.tenant_id == "tenant-b"


def test_environment_builder_uses_fail_closed_defaults(tmp_path: Path) -> None:
    response = build_production_continuity_gate_status_from_environment(
        user_context=_user_context(),
        environ={"SUITE_BACKUP_FAILOVER_POLICY_PATH": str(POLICY_PATH)},
        checked_at=datetime(2026, 8, 5, 7, 0, tzinfo=UTC),
    )

    assert response.state == ProductionContinuityGateState.MISSING
    assert response.runtime_switch_requested is False
    assert response.runtime_enablement_allowed is False

    missing_policy = tmp_path / "missing-policy.json"
    with pytest.raises(ProductionContinuityReadModelUnavailable):
        load_production_continuity_policy_from_environment({"SUITE_BACKUP_FAILOVER_POLICY_PATH": str(missing_policy)})


def test_requirements_response_contains_no_policy_descriptions_or_commands() -> None:
    policy = _policy()
    response_json = build_production_continuity_evidence_requirements_response(
        user_context=_user_context(),
        policy=policy,
    ).model_dump_json()

    for target in policy.targets:
        assert target.description not in response_json
        for command in target.current_dev_commands:
            assert command not in response_json
    parsed = json.loads(response_json)
    assert parsed["content_included"] is False
    assert parsed["secrets_included"] is False
