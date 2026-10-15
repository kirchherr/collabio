from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field, model_validator


class BackupRetention(BaseModel):
    daily: int = Field(ge=1)
    weekly: int = Field(ge=0)
    monthly: int = Field(ge=0)


class BackupTarget(BaseModel):
    target_id: str
    description: str
    covered_domains: list[str] = Field(min_length=1)
    data_classes: list[str]
    rpo_minutes: int = Field(ge=0)
    rto_hours: int = Field(ge=0)
    backup_methods: list[str] = Field(min_length=1)
    retention: BackupRetention
    restore_drill_frequency_days: int = Field(ge=1, le=90)
    integrity_checks: list[str] = Field(min_length=1)
    restore_verification_gates: list[str] = Field(default_factory=list)
    failover_mode: str
    current_dev_commands: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_actionable_failover_mode(self) -> BackupTarget:
        if not self.failover_mode.strip():
            raise ValueError("failover_mode must not be empty")
        return self


class ContinuityDomain(BaseModel):
    domain_id: str
    description: str
    primary_target_id: str
    criticality: str
    recovery_strategy: str
    state_artifacts: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def require_known_criticality(self) -> ContinuityDomain:
        if self.criticality not in {"critical", "important", "rebuildable"}:
            raise ValueError("criticality must be critical, important, or rebuildable")
        return self


class ProductionContinuityReferenceImplementations(BaseModel):
    capability_id: str
    implementation_ids: list[str] = Field(min_length=1)


class ProductionContinuityDeploymentPolicy(BaseModel):
    schema_version: str
    maximum_evidence_age_hours: int = Field(ge=1, le=720)
    postgres_target_id: str
    object_storage_target_id: str
    kms_target_id: str
    required_target_ids: tuple[str, ...] = Field(min_length=3)
    minimum_postgres_instances: int = Field(ge=2)
    minimum_failure_domains: int = Field(ge=2)
    maximum_wal_archive_backlog_bytes: int = Field(ge=0)
    maximum_manual_promotion_minutes: int = Field(ge=1)
    maximum_cross_site_failover_minutes: int = Field(ge=1)
    maximum_kms_rpo_minutes: int = Field(ge=0)
    maximum_kms_rto_minutes: int = Field(ge=1)
    required_control_ids: tuple[str, ...] = Field(min_length=4)
    reference_implementations: tuple[ProductionContinuityReferenceImplementations, ...] = Field(min_length=4)
    automatic_failover_requires_separate_drill: bool
    deployment_execution_allowed: bool = False

    @model_validator(mode="after")
    def require_unique_fail_closed_contract(self) -> ProductionContinuityDeploymentPolicy:
        if len(set(self.required_target_ids)) != len(self.required_target_ids):
            raise ValueError("production continuity required target ids must be unique")
        if len(set(self.required_control_ids)) != len(self.required_control_ids):
            raise ValueError("production continuity required control ids must be unique")
        capability_ids = [item.capability_id for item in self.reference_implementations]
        if len(set(capability_ids)) != len(capability_ids):
            raise ValueError("production continuity reference capability ids must be unique")
        required_capabilities = {
            "postgres_pitr",
            "encrypted_offsite_backup",
            "ha_orchestration",
            "cross_site_failover",
        }
        missing_capabilities = sorted(required_capabilities - set(capability_ids))
        if missing_capabilities:
            raise ValueError(
                "production continuity reference implementations are missing: " + ", ".join(missing_capabilities)
            )
        selected_targets = {self.postgres_target_id, self.object_storage_target_id, self.kms_target_id}
        if not selected_targets.issubset(set(self.required_target_ids)):
            raise ValueError("production continuity selected targets must be required targets")
        if not self.automatic_failover_requires_separate_drill:
            raise ValueError("automatic failover must require a separate drill")
        if self.deployment_execution_allowed:
            raise ValueError("production continuity evidence gate must not execute deployments")
        return self

    def reference_implementation_ids(self, capability_id: str) -> set[str]:
        for item in self.reference_implementations:
            if item.capability_id == capability_id:
                return set(item.implementation_ids)
        raise LookupError(f"Unknown production continuity capability: {capability_id}")


class BackupFailoverPolicy(BaseModel):
    schema_version: str
    owner: str
    default_timezone: str
    principles: list[str] = Field(min_length=3)
    change_control_rules: list[str] = Field(min_length=3)
    continuity_domains: list[ContinuityDomain] = Field(min_length=1)
    targets: list[BackupTarget] = Field(min_length=1)
    incident_triggers: list[str] = Field(min_length=1)
    restore_drill_evidence: list[str] = Field(min_length=1)
    production_deployment_gate: ProductionContinuityDeploymentPolicy

    @model_validator(mode="after")
    def require_unique_targets_and_domain_coverage(self) -> BackupFailoverPolicy:
        target_ids = [target.target_id for target in self.targets]
        duplicate_ids = sorted({target_id for target_id in target_ids if target_ids.count(target_id) > 1})
        if duplicate_ids:
            raise ValueError(f"duplicate backup target ids: {', '.join(duplicate_ids)}")

        domain_ids = [domain.domain_id for domain in self.continuity_domains]
        duplicate_domain_ids = sorted({domain_id for domain_id in domain_ids if domain_ids.count(domain_id) > 1})
        if duplicate_domain_ids:
            raise ValueError(f"duplicate continuity domain ids: {', '.join(duplicate_domain_ids)}")

        target_id_set = set(target_ids)
        unknown_primary_targets = sorted(
            domain.primary_target_id
            for domain in self.continuity_domains
            if domain.primary_target_id not in target_id_set
        )
        if unknown_primary_targets:
            raise ValueError(f"unknown continuity primary targets: {', '.join(unknown_primary_targets)}")

        covered_domain_ids = {domain_id for target in self.targets for domain_id in target.covered_domains}
        uncovered_domain_ids = sorted(set(domain_ids) - covered_domain_ids)
        if uncovered_domain_ids:
            raise ValueError(f"continuity domains missing target coverage: {', '.join(uncovered_domain_ids)}")

        unknown_covered_domains = sorted(covered_domain_ids - set(domain_ids))
        if unknown_covered_domains:
            raise ValueError(f"targets reference unknown continuity domains: {', '.join(unknown_covered_domains)}")

        required_deployment_targets = set(self.production_deployment_gate.required_target_ids)
        missing_deployment_targets = sorted(required_deployment_targets - target_id_set)
        if missing_deployment_targets:
            raise ValueError(
                "production continuity gate references unknown targets: " + ", ".join(missing_deployment_targets)
            )
        return self

    def target(self, target_id: str) -> BackupTarget:
        for target in self.targets:
            if target.target_id == target_id:
                return target
        raise LookupError(f"Unknown backup target: {target_id}")

    def domain(self, domain_id: str) -> ContinuityDomain:
        for domain in self.continuity_domains:
            if domain.domain_id == domain_id:
                return domain
        raise LookupError(f"Unknown continuity domain: {domain_id}")


def load_backup_failover_policy(path: Path) -> BackupFailoverPolicy:
    return BackupFailoverPolicy.model_validate_json(path.read_text(encoding="utf-8"))


def backup_policy_summary(policy: BackupFailoverPolicy) -> dict[str, object]:
    strictest_rpo = min(target.rpo_minutes for target in policy.targets)
    strictest_rto = min(target.rto_hours for target in policy.targets)
    return {
        "schema_version": policy.schema_version,
        "owner": policy.owner,
        "target_count": len(policy.targets),
        "continuity_domain_count": len(policy.continuity_domains),
        "strictest_rpo_minutes": strictest_rpo,
        "strictest_rto_hours": strictest_rto,
    }


def main() -> None:
    policy = load_backup_failover_policy(Path("docs/operations/backup_failover_policy.json"))
    print(json.dumps(backup_policy_summary(policy), sort_keys=True))


if __name__ == "__main__":
    main()
