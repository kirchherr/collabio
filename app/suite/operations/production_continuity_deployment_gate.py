from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.operations.backup_failover import BackupFailoverPolicy, load_backup_failover_policy
from suite.storage.source_objects import sha256_bytes

SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")


class StrictEvidenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _require_sha256(value: str) -> str:
    if not SHA256_PATTERN.fullmatch(value):
        raise ValueError("production continuity evidence references must use sha256")
    return value


def _require_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("production continuity evidence timestamps must include a timezone")
    return value.astimezone(UTC)


class PostgresPITREvidence(StrictEvidenceModel):
    implementation_id: str
    implementation_version_ref_hash: str
    deployment_ref_hash: str
    archive_mode_enabled: bool
    wal_level: Literal["replica", "logical"]
    archive_destination_ref_hash: str
    base_backup_hash: str
    pitr_drill_report_hash: str
    complete_wal_chain_verified: bool
    timeline_history_verified: bool
    isolated_restore_verified: bool
    archive_backlog_bytes: int = Field(ge=0)
    observed_rpo_minutes: int = Field(ge=0)
    observed_restore_minutes: int = Field(ge=0)
    observed_at_utc: datetime

    _validate_hashes = field_validator(
        "implementation_version_ref_hash",
        "deployment_ref_hash",
        "archive_destination_ref_hash",
        "base_backup_hash",
        "pitr_drill_report_hash",
    )(_require_sha256)
    _validate_timestamp = field_validator("observed_at_utc")(_require_aware_utc)


class EncryptedOffsiteBackupEvidence(StrictEvidenceModel):
    implementation_id: str
    implementation_version_ref_hash: str
    deployment_ref_hash: str
    source_site_ref_hash: str
    offsite_site_ref_hash: str
    source_repository_ref_hash: str
    offsite_repository_ref_hash: str
    encryption_mode: Literal["client_side_aes256", "provider_kms", "envelope_kms"]
    encryption_key_ref_hash: str
    independent_credentials_verified: bool
    immutable_retention_verified: bool
    no_plaintext_key_export_verified: bool
    offsite_restore_verified: bool
    observed_rpo_minutes: int = Field(ge=0)
    observed_restore_minutes: int = Field(ge=0)
    offsite_restore_report_hash: str
    observed_at_utc: datetime

    _validate_hashes = field_validator(
        "implementation_version_ref_hash",
        "deployment_ref_hash",
        "source_site_ref_hash",
        "offsite_site_ref_hash",
        "source_repository_ref_hash",
        "offsite_repository_ref_hash",
        "encryption_key_ref_hash",
        "offsite_restore_report_hash",
    )(_require_sha256)
    _validate_timestamp = field_validator("observed_at_utc")(_require_aware_utc)


class HAPromotionEvidence(StrictEvidenceModel):
    implementation_id: str
    implementation_version_ref_hash: str
    deployment_ref_hash: str
    postgres_instance_count: int = Field(ge=1)
    failure_domain_count: int = Field(ge=1)
    replication_tls_verified: bool
    synchronous_durability_verified: bool
    fencing_verified: bool
    split_brain_prevention_verified: bool
    manual_promotion_verified: bool
    observed_replica_lag_minutes: int = Field(ge=0)
    observed_promotion_minutes: int = Field(ge=0)
    promotion_drill_report_hash: str
    failback_runbook_hash: str
    automatic_failover_enabled: bool = False
    automatic_failover_drill_report_hash: str | None = None
    observed_at_utc: datetime

    _validate_required_hashes = field_validator(
        "implementation_version_ref_hash",
        "deployment_ref_hash",
        "promotion_drill_report_hash",
        "failback_runbook_hash",
    )(_require_sha256)
    _validate_timestamp = field_validator("observed_at_utc")(_require_aware_utc)

    @field_validator("automatic_failover_drill_report_hash")
    @classmethod
    def validate_optional_hash(cls, value: str | None) -> str | None:
        return _require_sha256(value) if value is not None else None


class CrossSiteFailoverEvidence(StrictEvidenceModel):
    implementation_id: str
    implementation_version_ref_hash: str
    deployment_ref_hash: str
    source_site_ref_hash: str
    recovery_site_ref_hash: str
    postgres_recovery_target_ref_hash: str
    object_storage_recovery_target_ref_hash: str
    kms_recovery_target_ref_hash: str
    independent_failure_domain_verified: bool
    postgres_recovery_verified: bool
    object_version_lock_retention_legal_hold_verified: bool
    kms_recovery_verified: bool
    tenant_isolation_verified: bool
    cross_site_failover_drill_report_hash: str
    failback_runbook_hash: str
    observed_failover_minutes: int = Field(ge=0)
    traffic_switch_executed: Literal[False] = False
    business_write_executed: Literal[False] = False
    observed_at_utc: datetime

    _validate_hashes = field_validator(
        "implementation_version_ref_hash",
        "deployment_ref_hash",
        "source_site_ref_hash",
        "recovery_site_ref_hash",
        "postgres_recovery_target_ref_hash",
        "object_storage_recovery_target_ref_hash",
        "kms_recovery_target_ref_hash",
        "cross_site_failover_drill_report_hash",
        "failback_runbook_hash",
    )(_require_sha256)
    _validate_timestamp = field_validator("observed_at_utc")(_require_aware_utc)


class ProductionContinuityApprovalEvidence(StrictEvidenceModel):
    deployment_ref_hash: str
    change_approver_principal_hash: str
    security_approver_principal_hash: str
    operations_approver_principal_hash: str
    change_approval_hash: str
    security_approval_hash: str
    operations_approval_hash: str
    reviewed_at_utc: datetime

    _validate_hashes = field_validator(
        "deployment_ref_hash",
        "change_approver_principal_hash",
        "security_approver_principal_hash",
        "operations_approver_principal_hash",
        "change_approval_hash",
        "security_approval_hash",
        "operations_approval_hash",
    )(_require_sha256)
    _validate_timestamp = field_validator("reviewed_at_utc")(_require_aware_utc)

    @model_validator(mode="after")
    def require_distinct_approvers(self) -> Self:
        approvers = {
            self.change_approver_principal_hash,
            self.security_approver_principal_hash,
            self.operations_approver_principal_hash,
        }
        if len(approvers) != 3:
            raise ValueError("production continuity approvals require three distinct principal hashes")
        approval_hashes = {
            self.change_approval_hash,
            self.security_approval_hash,
            self.operations_approval_hash,
        }
        if len(approval_hashes) != 3:
            raise ValueError("production continuity approvals require three distinct approval hashes")
        return self


class ProductionContinuityDeploymentEvidenceBundle(StrictEvidenceModel):
    deployment_ref_hash: str
    backup_policy_schema_version: str
    continuity_domain_ids: tuple[str, ...] = Field(min_length=1)
    postgres_pitr: PostgresPITREvidence
    encrypted_offsite_backup: EncryptedOffsiteBackupEvidence
    ha_promotion: HAPromotionEvidence
    cross_site_failover: CrossSiteFailoverEvidence
    approvals: ProductionContinuityApprovalEvidence
    content_included: Literal[False] = False
    secrets_included: Literal[False] = False
    destructive_action_requested: Literal[False] = False
    failover_execution_requested: Literal[False] = False
    environment: Literal["production"] = "production"
    schema_version: Literal["production_continuity_deployment_evidence.v1"] = (
        "production_continuity_deployment_evidence.v1"
    )

    _validate_deployment_hash = field_validator("deployment_ref_hash")(_require_sha256)

    @model_validator(mode="after")
    def require_unique_domains(self) -> Self:
        if len(set(self.continuity_domain_ids)) != len(self.continuity_domain_ids):
            raise ValueError("production continuity domain ids must be unique")
        return self


class ProductionContinuityDeploymentGate(StrictEvidenceModel):
    checked_at_utc: str
    valid_until_utc: str
    deployment_ref_hash: str
    backup_policy_schema_version: str
    backup_policy_hash: str
    evidence_bundle_hash: str
    required_target_ids: tuple[str, ...]
    critical_continuity_domain_count: int = Field(ge=1)
    continuity_domain_coverage_verified: bool
    evidence_deployment_binding_verified: bool
    evidence_freshness_verified: bool
    postgres_pitr_verified: bool
    encrypted_offsite_backup_verified: bool
    ha_manual_promotion_verified: bool
    cross_site_failover_verified: bool
    independent_failure_domains_verified: bool
    encryption_and_key_recovery_verified: bool
    retention_object_lock_legal_hold_verified: bool
    tenant_isolation_verified: bool
    approvals_verified: bool
    automatic_failover_enabled: bool
    automatic_failover_admitted: bool
    metadata_only_evidence_verified: bool
    content_included: Literal[False] = False
    secrets_included: Literal[False] = False
    deployment_execution_allowed: Literal[False] = False
    failover_execution_allowed: Literal[False] = False
    business_write_executed: Literal[False] = False
    blocking_reasons: tuple[str, ...] = ()
    deployment_ready: bool
    gate_hash: str
    schema_version: Literal["production_continuity_deployment_gate.v1"] = "production_continuity_deployment_gate.v1"

    _validate_hashes = field_validator(
        "deployment_ref_hash",
        "backup_policy_hash",
        "evidence_bundle_hash",
        "gate_hash",
    )(_require_sha256)


def _canonical_hash(value: object) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def build_production_continuity_evidence_bundle_hash(
    bundle: ProductionContinuityDeploymentEvidenceBundle,
) -> str:
    return _canonical_hash(bundle.model_dump(mode="json"))


def build_production_continuity_deployment_gate_hash(
    gate: ProductionContinuityDeploymentGate,
) -> str:
    return _canonical_hash(gate.model_dump(mode="json", exclude={"gate_hash"}))


def build_backup_failover_policy_hash(policy: BackupFailoverPolicy) -> str:
    return _canonical_hash(policy.model_dump(mode="json"))


def _freshness_verified(
    *,
    observed_at: tuple[datetime, ...],
    checked_at: datetime,
    maximum_age_hours: int,
) -> bool:
    oldest_allowed = checked_at - timedelta(hours=maximum_age_hours)
    return all(oldest_allowed <= timestamp <= checked_at for timestamp in observed_at)


def _reference_implementation_allowed(
    *,
    policy: BackupFailoverPolicy,
    capability_id: str,
    implementation_id: str,
) -> bool:
    allowed = policy.production_deployment_gate.reference_implementation_ids(capability_id)
    return implementation_id in allowed


def build_production_continuity_deployment_gate(
    *,
    policy: BackupFailoverPolicy,
    bundle: ProductionContinuityDeploymentEvidenceBundle,
    checked_at: datetime | None = None,
) -> ProductionContinuityDeploymentGate:
    gate_policy = policy.production_deployment_gate
    checked = _require_aware_utc(checked_at or datetime.now(UTC))
    postgres_target = policy.target(gate_policy.postgres_target_id)
    object_target = policy.target(gate_policy.object_storage_target_id)
    kms_target = policy.target(gate_policy.kms_target_id)
    critical_domains = {domain.domain_id for domain in policy.continuity_domains if domain.criticality == "critical"}
    supplied_domains = set(bundle.continuity_domain_ids)
    required_targets = set(gate_policy.required_target_ids)
    known_targets = {target.target_id for target in policy.targets}
    target_coverage = {domain_id for target in policy.targets for domain_id in target.covered_domains}

    observed_at = (
        bundle.postgres_pitr.observed_at_utc,
        bundle.encrypted_offsite_backup.observed_at_utc,
        bundle.ha_promotion.observed_at_utc,
        bundle.cross_site_failover.observed_at_utc,
        bundle.approvals.reviewed_at_utc,
    )
    freshness_verified = _freshness_verified(
        observed_at=observed_at,
        checked_at=checked,
        maximum_age_hours=gate_policy.maximum_evidence_age_hours,
    )
    deployment_binding_verified = all(
        (
            bundle.postgres_pitr.deployment_ref_hash == bundle.deployment_ref_hash,
            bundle.encrypted_offsite_backup.deployment_ref_hash == bundle.deployment_ref_hash,
            bundle.ha_promotion.deployment_ref_hash == bundle.deployment_ref_hash,
            bundle.cross_site_failover.deployment_ref_hash == bundle.deployment_ref_hash,
            bundle.approvals.deployment_ref_hash == bundle.deployment_ref_hash,
            bundle.encrypted_offsite_backup.source_site_ref_hash == bundle.cross_site_failover.source_site_ref_hash,
        )
    )
    domain_coverage_verified = (
        required_targets.issubset(known_targets)
        and critical_domains.issubset(supplied_domains)
        and critical_domains.issubset(target_coverage)
    )
    pitr_verified = all(
        (
            bundle.backup_policy_schema_version == policy.schema_version,
            _reference_implementation_allowed(
                policy=policy,
                capability_id="postgres_pitr",
                implementation_id=bundle.postgres_pitr.implementation_id,
            ),
            bundle.postgres_pitr.archive_mode_enabled,
            bundle.postgres_pitr.complete_wal_chain_verified,
            bundle.postgres_pitr.timeline_history_verified,
            bundle.postgres_pitr.isolated_restore_verified,
            bundle.postgres_pitr.archive_backlog_bytes <= gate_policy.maximum_wal_archive_backlog_bytes,
            bundle.postgres_pitr.observed_rpo_minutes <= postgres_target.rpo_minutes,
            bundle.postgres_pitr.observed_restore_minutes <= postgres_target.rto_hours * 60,
        )
    )
    offsite_verified = all(
        (
            _reference_implementation_allowed(
                policy=policy,
                capability_id="encrypted_offsite_backup",
                implementation_id=bundle.encrypted_offsite_backup.implementation_id,
            ),
            bundle.encrypted_offsite_backup.source_site_ref_hash
            != bundle.encrypted_offsite_backup.offsite_site_ref_hash,
            bundle.encrypted_offsite_backup.source_repository_ref_hash
            != bundle.encrypted_offsite_backup.offsite_repository_ref_hash,
            bundle.encrypted_offsite_backup.independent_credentials_verified,
            bundle.encrypted_offsite_backup.immutable_retention_verified,
            bundle.encrypted_offsite_backup.no_plaintext_key_export_verified,
            bundle.encrypted_offsite_backup.offsite_restore_verified,
            bundle.encrypted_offsite_backup.observed_rpo_minutes <= object_target.rpo_minutes,
            bundle.encrypted_offsite_backup.observed_restore_minutes <= object_target.rto_hours * 60,
        )
    )
    automatic_failover_admitted = (
        bundle.ha_promotion.automatic_failover_enabled
        and bundle.ha_promotion.automatic_failover_drill_report_hash is not None
        and gate_policy.automatic_failover_requires_separate_drill
    )
    automatic_failover_safe = not bundle.ha_promotion.automatic_failover_enabled or automatic_failover_admitted
    ha_verified = all(
        (
            _reference_implementation_allowed(
                policy=policy,
                capability_id="ha_orchestration",
                implementation_id=bundle.ha_promotion.implementation_id,
            ),
            bundle.ha_promotion.postgres_instance_count >= gate_policy.minimum_postgres_instances,
            bundle.ha_promotion.failure_domain_count >= gate_policy.minimum_failure_domains,
            bundle.ha_promotion.replication_tls_verified,
            bundle.ha_promotion.synchronous_durability_verified,
            bundle.ha_promotion.fencing_verified,
            bundle.ha_promotion.split_brain_prevention_verified,
            bundle.ha_promotion.manual_promotion_verified,
            bundle.ha_promotion.observed_replica_lag_minutes <= postgres_target.rpo_minutes,
            bundle.ha_promotion.observed_promotion_minutes <= gate_policy.maximum_manual_promotion_minutes,
            automatic_failover_safe,
        )
    )
    cross_site_verified = all(
        (
            _reference_implementation_allowed(
                policy=policy,
                capability_id="cross_site_failover",
                implementation_id=bundle.cross_site_failover.implementation_id,
            ),
            bundle.cross_site_failover.source_site_ref_hash != bundle.cross_site_failover.recovery_site_ref_hash,
            bundle.cross_site_failover.independent_failure_domain_verified,
            bundle.cross_site_failover.postgres_recovery_verified,
            bundle.cross_site_failover.object_version_lock_retention_legal_hold_verified,
            bundle.cross_site_failover.kms_recovery_verified,
            bundle.cross_site_failover.tenant_isolation_verified,
            bundle.cross_site_failover.observed_failover_minutes <= gate_policy.maximum_cross_site_failover_minutes,
        )
    )
    approvals_verified = (
        len(
            {
                bundle.approvals.change_approver_principal_hash,
                bundle.approvals.security_approver_principal_hash,
                bundle.approvals.operations_approver_principal_hash,
            }
        )
        == 3
    )
    independent_failure_domains = all(
        (
            bundle.encrypted_offsite_backup.source_site_ref_hash
            != bundle.encrypted_offsite_backup.offsite_site_ref_hash,
            bundle.ha_promotion.failure_domain_count >= gate_policy.minimum_failure_domains,
            bundle.cross_site_failover.source_site_ref_hash != bundle.cross_site_failover.recovery_site_ref_hash,
            bundle.cross_site_failover.independent_failure_domain_verified,
        )
    )
    encryption_and_key_recovery = all(
        (
            bundle.encrypted_offsite_backup.no_plaintext_key_export_verified,
            bundle.encrypted_offsite_backup.independent_credentials_verified,
            bundle.cross_site_failover.kms_recovery_verified,
            kms_target.rpo_minutes <= gate_policy.maximum_kms_rpo_minutes,
            kms_target.rto_hours * 60 <= gate_policy.maximum_kms_rto_minutes,
        )
    )
    metadata_only = all(
        (
            not bundle.content_included,
            not bundle.secrets_included,
            not bundle.destructive_action_requested,
            not bundle.failover_execution_requested,
            not bundle.cross_site_failover.traffic_switch_executed,
            not bundle.cross_site_failover.business_write_executed,
        )
    )
    checks = {
        "continuity_domain_coverage_not_verified": domain_coverage_verified,
        "evidence_deployment_binding_not_verified": deployment_binding_verified,
        "evidence_is_stale_or_future_dated": freshness_verified,
        "postgres_pitr_not_verified": pitr_verified,
        "encrypted_offsite_backup_not_verified": offsite_verified,
        "ha_manual_promotion_not_verified": ha_verified,
        "cross_site_failover_not_verified": cross_site_verified,
        "independent_failure_domains_not_verified": independent_failure_domains,
        "encryption_or_key_recovery_not_verified": encryption_and_key_recovery,
        "retention_object_lock_or_legal_hold_not_verified": (
            bundle.encrypted_offsite_backup.immutable_retention_verified
            and bundle.cross_site_failover.object_version_lock_retention_legal_hold_verified
        ),
        "tenant_isolation_not_verified": bundle.cross_site_failover.tenant_isolation_verified,
        "three_party_approval_not_verified": approvals_verified,
        "evidence_is_not_metadata_only": metadata_only,
    }
    blocking_reasons = tuple(sorted(reason for reason, passed in checks.items() if not passed))
    draft = ProductionContinuityDeploymentGate(
        checked_at_utc=checked.isoformat(),
        valid_until_utc=(min(observed_at) + timedelta(hours=gate_policy.maximum_evidence_age_hours)).isoformat(),
        deployment_ref_hash=bundle.deployment_ref_hash,
        backup_policy_schema_version=policy.schema_version,
        backup_policy_hash=build_backup_failover_policy_hash(policy),
        evidence_bundle_hash=build_production_continuity_evidence_bundle_hash(bundle),
        required_target_ids=gate_policy.required_target_ids,
        critical_continuity_domain_count=len(critical_domains),
        continuity_domain_coverage_verified=domain_coverage_verified,
        evidence_deployment_binding_verified=deployment_binding_verified,
        evidence_freshness_verified=freshness_verified,
        postgres_pitr_verified=pitr_verified,
        encrypted_offsite_backup_verified=offsite_verified,
        ha_manual_promotion_verified=ha_verified,
        cross_site_failover_verified=cross_site_verified,
        independent_failure_domains_verified=independent_failure_domains,
        encryption_and_key_recovery_verified=encryption_and_key_recovery,
        retention_object_lock_legal_hold_verified=(
            bundle.encrypted_offsite_backup.immutable_retention_verified
            and bundle.cross_site_failover.object_version_lock_retention_legal_hold_verified
        ),
        tenant_isolation_verified=bundle.cross_site_failover.tenant_isolation_verified,
        approvals_verified=approvals_verified,
        automatic_failover_enabled=bundle.ha_promotion.automatic_failover_enabled,
        automatic_failover_admitted=automatic_failover_admitted,
        metadata_only_evidence_verified=metadata_only,
        blocking_reasons=blocking_reasons,
        deployment_ready=not blocking_reasons,
        gate_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"gate_hash": build_production_continuity_deployment_gate_hash(draft)})


def production_continuity_deployment_gate_runtime_ready(
    *,
    gate: ProductionContinuityDeploymentGate,
    policy: BackupFailoverPolicy,
    checked_at: datetime | None = None,
) -> bool:
    try:
        checked = _require_aware_utc(checked_at or datetime.now(UTC))
        gate_checked_at = _require_aware_utc(datetime.fromisoformat(gate.checked_at_utc))
        valid_until = _require_aware_utc(datetime.fromisoformat(gate.valid_until_utc))
    except ValueError:
        return False
    return all(
        (
            build_production_continuity_deployment_gate_hash(gate) == gate.gate_hash,
            gate.deployment_ready,
            gate.metadata_only_evidence_verified,
            not gate.deployment_execution_allowed,
            not gate.failover_execution_allowed,
            gate.backup_policy_schema_version == policy.schema_version,
            gate.backup_policy_hash == build_backup_failover_policy_hash(policy),
            gate_checked_at <= checked <= valid_until,
        )
    )


def persist_production_continuity_deployment_gate(
    *,
    gate: ProductionContinuityDeploymentGate,
    report_path: Path,
) -> None:
    if build_production_continuity_deployment_gate_hash(gate) != gate.gate_hash:
        raise ValueError("production continuity deployment gate hash is invalid")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(gate.model_dump(mode="json"), sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(report_path)


def load_production_continuity_deployment_gate(
    report_path: Path,
) -> ProductionContinuityDeploymentGate:
    gate = ProductionContinuityDeploymentGate.model_validate_json(report_path.read_text(encoding="utf-8"))
    if build_production_continuity_deployment_gate_hash(gate) != gate.gate_hash:
        raise ValueError("persisted production continuity deployment gate hash is invalid")
    return gate


def run_production_continuity_deployment_gate_from_environment(
    env: Mapping[str, str],
) -> ProductionContinuityDeploymentGate:
    policy_path = Path(
        env.get(
            "SUITE_BACKUP_FAILOVER_POLICY_PATH",
            "/workspace/docs/operations/backup_failover_policy.json",
        )
    )
    evidence_path_value = env.get("SUITE_PRODUCTION_CONTINUITY_EVIDENCE_PATH", "").strip()
    if not evidence_path_value:
        raise ValueError("SUITE_PRODUCTION_CONTINUITY_EVIDENCE_PATH is required and must be mounted read-only")
    evidence_path = Path(evidence_path_value)
    policy = load_backup_failover_policy(policy_path)
    bundle = ProductionContinuityDeploymentEvidenceBundle.model_validate_json(evidence_path.read_text(encoding="utf-8"))
    return build_production_continuity_deployment_gate(policy=policy, bundle=bundle)


def main() -> None:
    try:
        gate = run_production_continuity_deployment_gate_from_environment(os.environ)
    except (OSError, ValueError):
        print(
            json.dumps(
                {
                    "schema_version": "production_continuity_deployment_gate_input_error.v1",
                    "deployment_ready": False,
                    "blocking_reasons": ["production_continuity_evidence_unavailable_or_invalid"],
                    "content_included": False,
                    "secrets_included": False,
                    "deployment_execution_allowed": False,
                    "failover_execution_allowed": False,
                },
                sort_keys=True,
            )
        )
        raise SystemExit(2) from None
    report_path = os.environ.get("SUITE_PRODUCTION_CONTINUITY_GATE_REPORT_PATH", "").strip()
    if report_path:
        persist_production_continuity_deployment_gate(gate=gate, report_path=Path(report_path))
    print(json.dumps(gate.model_dump(mode="json"), sort_keys=True))
    raise SystemExit(0 if gate.deployment_ready else 2)


if __name__ == "__main__":
    main()
