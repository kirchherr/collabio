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
