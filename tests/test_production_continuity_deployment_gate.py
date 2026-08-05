import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from suite.operations.backup_failover import BackupFailoverPolicy, load_backup_failover_policy
from suite.operations.production_continuity_deployment_gate import (
    CrossSiteFailoverEvidence,
    EncryptedOffsiteBackupEvidence,
    HAPromotionEvidence,
    PostgresPITREvidence,
    ProductionContinuityApprovalEvidence,
    ProductionContinuityDeploymentEvidenceBundle,
    build_production_continuity_deployment_gate,
    build_production_continuity_deployment_gate_hash,
    load_production_continuity_deployment_gate,
    persist_production_continuity_deployment_gate,
    production_continuity_deployment_gate_runtime_ready,
)
from suite.operations.production_continuity_deployment_gate import (
    main as continuity_gate_main,
)
from suite.platform.productivity_pilot_start_authorization import (
    productivity_pilot_runtime_enabled,
)
from suite.storage.source_objects import sha256_bytes

REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = REPO_ROOT / "docs" / "operations" / "backup_failover_policy.json"
CHECKED_AT = datetime(2026, 8, 5, 8, 0, tzinfo=UTC)


def _hash(label: str) -> str:
    return sha256_bytes(label.encode("utf-8"))


def _policy() -> BackupFailoverPolicy:
    return load_backup_failover_policy(POLICY_PATH)


def _bundle(
    *,
    policy: BackupFailoverPolicy | None = None,
    checked_at: datetime = CHECKED_AT,
) -> ProductionContinuityDeploymentEvidenceBundle:
    selected_policy = policy or _policy()
    observed_at = checked_at - timedelta(hours=1)
    deployment_ref_hash = _hash("production-deployment")
    return ProductionContinuityDeploymentEvidenceBundle(
        deployment_ref_hash=deployment_ref_hash,
        backup_policy_schema_version=selected_policy.schema_version,
        continuity_domain_ids=tuple(
            sorted(
                domain.domain_id for domain in selected_policy.continuity_domains if domain.criticality == "critical"
            )
        ),
        postgres_pitr=PostgresPITREvidence(
            implementation_id="pgbackrest",
            implementation_version_ref_hash=_hash("pgbackrest-version-provenance"),
            deployment_ref_hash=deployment_ref_hash,
            archive_mode_enabled=True,
            wal_level="replica",
            archive_destination_ref_hash=_hash("wal-offsite-repository"),
            base_backup_hash=_hash("base-backup"),
            pitr_drill_report_hash=_hash("pitr-drill"),
            complete_wal_chain_verified=True,
            timeline_history_verified=True,
            isolated_restore_verified=True,
            archive_backlog_bytes=0,
            observed_rpo_minutes=5,
            observed_restore_minutes=120,
            observed_at_utc=observed_at,
        ),
        encrypted_offsite_backup=EncryptedOffsiteBackupEvidence(
            implementation_id="pgbackrest",
            implementation_version_ref_hash=_hash("pgbackrest-version-provenance"),
            deployment_ref_hash=deployment_ref_hash,
            source_site_ref_hash=_hash("primary-site"),
            offsite_site_ref_hash=_hash("offsite-site"),
            source_repository_ref_hash=_hash("source-repository"),
            offsite_repository_ref_hash=_hash("offsite-repository"),
            encryption_mode="client_side_aes256",
            encryption_key_ref_hash=_hash("offsite-key-ref"),
            independent_credentials_verified=True,
            immutable_retention_verified=True,
            no_plaintext_key_export_verified=True,
            offsite_restore_verified=True,
            observed_rpo_minutes=30,
            observed_restore_minutes=180,
            offsite_restore_report_hash=_hash("offsite-restore"),
            observed_at_utc=observed_at,
        ),
        ha_promotion=HAPromotionEvidence(
            implementation_id="patroni",
            implementation_version_ref_hash=_hash("patroni-version-provenance"),
            deployment_ref_hash=deployment_ref_hash,
            postgres_instance_count=3,
            failure_domain_count=3,
            replication_tls_verified=True,
            synchronous_durability_verified=True,
            fencing_verified=True,
            split_brain_prevention_verified=True,
            manual_promotion_verified=True,
            observed_replica_lag_minutes=1,
            observed_promotion_minutes=5,
            promotion_drill_report_hash=_hash("promotion-drill"),
            failback_runbook_hash=_hash("ha-failback-runbook"),
            observed_at_utc=observed_at,
        ),
        cross_site_failover=CrossSiteFailoverEvidence(
            implementation_id="minio_bucket_replication",
            implementation_version_ref_hash=_hash("minio-version-provenance"),
            deployment_ref_hash=deployment_ref_hash,
            source_site_ref_hash=_hash("primary-site"),
            recovery_site_ref_hash=_hash("recovery-site"),
            postgres_recovery_target_ref_hash=_hash("recovery-postgres"),
            object_storage_recovery_target_ref_hash=_hash("recovery-object-storage"),
            kms_recovery_target_ref_hash=_hash("recovery-kms"),
            independent_failure_domain_verified=True,
            postgres_recovery_verified=True,
            object_version_lock_retention_legal_hold_verified=True,
            kms_recovery_verified=True,
            tenant_isolation_verified=True,
            cross_site_failover_drill_report_hash=_hash("cross-site-drill"),
            failback_runbook_hash=_hash("cross-site-failback-runbook"),
            observed_failover_minutes=180,
            observed_at_utc=observed_at,
        ),
        approvals=ProductionContinuityApprovalEvidence(
            deployment_ref_hash=deployment_ref_hash,
            change_approver_principal_hash=_hash("change-approver"),
            security_approver_principal_hash=_hash("security-approver"),
            operations_approver_principal_hash=_hash("operations-approver"),
            change_approval_hash=_hash("change-approval"),
            security_approval_hash=_hash("security-approval"),
            operations_approval_hash=_hash("operations-approval"),
            reviewed_at_utc=observed_at,
        ),
    )


def test_gate_accepts_fresh_complete_metadata_only_production_continuity_evidence() -> None:
    policy = _policy()

    gate = build_production_continuity_deployment_gate(
        policy=policy,
        bundle=_bundle(policy=policy),
        checked_at=CHECKED_AT,
    )

    assert gate.schema_version == "production_continuity_deployment_gate.v1"
    assert gate.deployment_ready is True
    assert gate.blocking_reasons == ()
    assert gate.postgres_pitr_verified is True
    assert gate.encrypted_offsite_backup_verified is True
    assert gate.ha_manual_promotion_verified is True
    assert gate.cross_site_failover_verified is True
    assert gate.independent_failure_domains_verified is True
    assert gate.evidence_deployment_binding_verified is True
    assert gate.encryption_and_key_recovery_verified is True
    assert gate.retention_object_lock_legal_hold_verified is True
    assert gate.tenant_isolation_verified is True
    assert gate.approvals_verified is True
    assert gate.automatic_failover_enabled is False
    assert gate.automatic_failover_admitted is False
    assert gate.deployment_execution_allowed is False
    assert gate.failover_execution_allowed is False
    assert gate.business_write_executed is False
    assert gate.content_included is False
    assert gate.secrets_included is False
    assert build_production_continuity_deployment_gate_hash(gate) == gate.gate_hash


def test_gate_blocks_stale_or_future_dated_evidence() -> None:
    policy = _policy()
    bundle = _bundle(policy=policy)
    stale_pitr = bundle.postgres_pitr.model_copy(update={"observed_at_utc": CHECKED_AT - timedelta(days=8)})

    gate = build_production_continuity_deployment_gate(
        policy=policy,
        bundle=bundle.model_copy(update={"postgres_pitr": stale_pitr}),
        checked_at=CHECKED_AT,
    )

    assert gate.deployment_ready is False
    assert gate.evidence_freshness_verified is False
    assert "evidence_is_stale_or_future_dated" in gate.blocking_reasons


def test_gate_blocks_site_collisions_and_missing_independence() -> None:
    policy = _policy()
    bundle = _bundle(policy=policy)
    offsite = bundle.encrypted_offsite_backup.model_copy(
        update={
            "offsite_site_ref_hash": bundle.encrypted_offsite_backup.source_site_ref_hash,
            "offsite_repository_ref_hash": bundle.encrypted_offsite_backup.source_repository_ref_hash,
        }
    )

    gate = build_production_continuity_deployment_gate(
        policy=policy,
        bundle=bundle.model_copy(update={"encrypted_offsite_backup": offsite}),
        checked_at=CHECKED_AT,
    )

    assert gate.deployment_ready is False
    assert gate.encrypted_offsite_backup_verified is False
    assert gate.independent_failure_domains_verified is False
    assert "encrypted_offsite_backup_not_verified" in gate.blocking_reasons
    assert "independent_failure_domains_not_verified" in gate.blocking_reasons


def test_gate_blocks_automatic_failover_without_separate_drill() -> None:
    policy = _policy()
    bundle = _bundle(policy=policy)
    ha = bundle.ha_promotion.model_copy(update={"automatic_failover_enabled": True})

    gate = build_production_continuity_deployment_gate(
        policy=policy,
        bundle=bundle.model_copy(update={"ha_promotion": ha}),
        checked_at=CHECKED_AT,
    )

    assert gate.deployment_ready is False
    assert gate.automatic_failover_enabled is True
    assert gate.automatic_failover_admitted is False
    assert "ha_manual_promotion_not_verified" in gate.blocking_reasons


def test_gate_admits_automatic_failover_only_with_separate_drill_hash() -> None:
    policy = _policy()
    bundle = _bundle(policy=policy)
    ha = bundle.ha_promotion.model_copy(
        update={
            "automatic_failover_enabled": True,
            "automatic_failover_drill_report_hash": _hash("automatic-failover-drill"),
        }
    )

    gate = build_production_continuity_deployment_gate(
        policy=policy,
        bundle=bundle.model_copy(update={"ha_promotion": ha}),
        checked_at=CHECKED_AT,
    )

    assert gate.deployment_ready is True
    assert gate.automatic_failover_admitted is True
    assert gate.failover_execution_allowed is False


def test_gate_blocks_evidence_combined_from_another_deployment() -> None:
    policy = _policy()
    bundle = _bundle(policy=policy)
    foreign_pitr = bundle.postgres_pitr.model_copy(
        update={"deployment_ref_hash": _hash("another-production-deployment")}
    )

    gate = build_production_continuity_deployment_gate(
        policy=policy,
        bundle=bundle.model_copy(update={"postgres_pitr": foreign_pitr}),
        checked_at=CHECKED_AT,
    )

    assert gate.deployment_ready is False
    assert gate.evidence_deployment_binding_verified is False
    assert "evidence_deployment_binding_not_verified" in gate.blocking_reasons


def test_evidence_bundle_rejects_unknown_secret_bearing_fields() -> None:
    payload = _bundle().model_dump(mode="json")
    payload["postgres_pitr"]["connection_secret"] = "not-allowed"

    with pytest.raises(ValidationError, match="connection_secret"):
        ProductionContinuityDeploymentEvidenceBundle.model_validate(payload)


def test_evidence_bundle_rejects_non_hash_references_and_duplicate_approvers() -> None:
    payload = _bundle().model_dump(mode="json")
    payload["encrypted_offsite_backup"]["encryption_key_ref_hash"] = "kms://plaintext-reference"
    payload["approvals"]["security_approver_principal_hash"] = payload["approvals"]["change_approver_principal_hash"]

    with pytest.raises(ValidationError):
        ProductionContinuityDeploymentEvidenceBundle.model_validate(payload)


def test_evidence_bundle_rejects_duplicate_approval_artifact_hashes() -> None:
    payload = _bundle().model_dump(mode="json")
    payload["approvals"]["security_approval_hash"] = payload["approvals"]["change_approval_hash"]

    with pytest.raises(ValidationError, match="three distinct approval hashes"):
        ProductionContinuityDeploymentEvidenceBundle.model_validate(payload)


def test_persisted_gate_is_hash_verified_and_tamper_evident(tmp_path: Path) -> None:
    policy = _policy()
    gate = build_production_continuity_deployment_gate(
        policy=policy,
        bundle=_bundle(policy=policy),
        checked_at=CHECKED_AT,
    )
    report_path = tmp_path / "production-continuity-gate.json"
    persist_production_continuity_deployment_gate(gate=gate, report_path=report_path)

    assert load_production_continuity_deployment_gate(report_path) == gate

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["deployment_ready"] = False
    report_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="hash is invalid"):
        load_production_continuity_deployment_gate(report_path)


def test_runtime_switch_requires_a_hash_valid_ready_production_continuity_gate(tmp_path: Path) -> None:
    policy = _policy()
    runtime_checked_at = datetime.now(UTC)
    gate = build_production_continuity_deployment_gate(
        policy=policy,
        bundle=_bundle(policy=policy, checked_at=runtime_checked_at),
        checked_at=runtime_checked_at,
    )
    report_path = tmp_path / "production-continuity-gate.json"
    persist_production_continuity_deployment_gate(gate=gate, report_path=report_path)

    assert productivity_pilot_runtime_enabled({"SUITE_PRODUCTIVITY_PILOT_RUNTIME_ENABLED": "1"}) is False
    assert (
        productivity_pilot_runtime_enabled(
            {
                "SUITE_PRODUCTIVITY_PILOT_RUNTIME_ENABLED": "1",
                "SUITE_PRODUCTION_CONTINUITY_GATE_REPORT_PATH": str(report_path),
                "SUITE_BACKUP_FAILOVER_POLICY_PATH": str(POLICY_PATH),
            }
        )
        is True
    )

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    payload["deployment_ready"] = False
    report_path.write_text(json.dumps(payload), encoding="utf-8")
    assert (
        productivity_pilot_runtime_enabled(
            {
                "SUITE_PRODUCTIVITY_PILOT_RUNTIME_ENABLED": "1",
                "SUITE_PRODUCTION_CONTINUITY_GATE_REPORT_PATH": str(report_path),
                "SUITE_BACKUP_FAILOVER_POLICY_PATH": str(POLICY_PATH),
            }
        )
        is False
    )


def test_runtime_rejects_an_expired_otherwise_hash_valid_gate() -> None:
    policy = _policy()
    gate = build_production_continuity_deployment_gate(
        policy=policy,
        bundle=_bundle(policy=policy),
        checked_at=CHECKED_AT,
    )

    assert gate.deployment_ready is True
    assert (
        production_continuity_deployment_gate_runtime_ready(
            gate=gate,
            policy=policy,
            checked_at=CHECKED_AT + timedelta(days=8),
        )
        is False
    )


def test_gate_blocks_incomplete_critical_domain_manifest() -> None:
    policy = _policy()
    bundle = _bundle(policy=policy)

    gate = build_production_continuity_deployment_gate(
        policy=policy,
        bundle=bundle.model_copy(update={"continuity_domain_ids": bundle.continuity_domain_ids[1:]}),
        checked_at=CHECKED_AT,
    )

    assert gate.deployment_ready is False
    assert gate.continuity_domain_coverage_verified is False
    assert "continuity_domain_coverage_not_verified" in gate.blocking_reasons


def test_cli_fails_closed_without_exposing_missing_evidence_path(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    missing_path = tmp_path / "operator-secret-location" / "evidence.json"
    monkeypatch.setenv("SUITE_BACKUP_FAILOVER_POLICY_PATH", str(POLICY_PATH))
    monkeypatch.setenv("SUITE_PRODUCTION_CONTINUITY_EVIDENCE_PATH", str(missing_path))
    monkeypatch.delenv("SUITE_PRODUCTION_CONTINUITY_GATE_REPORT_PATH", raising=False)

    with pytest.raises(SystemExit) as error:
        continuity_gate_main()

    assert error.value.code == 2
    output = capsys.readouterr().out
    body = json.loads(output)
    assert body["deployment_ready"] is False
    assert body["blocking_reasons"] == ["production_continuity_evidence_unavailable_or_invalid"]
    assert body["content_included"] is False
    assert body["secrets_included"] is False
    assert str(missing_path) not in output
