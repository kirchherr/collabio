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


class BackupFailoverPolicy(BaseModel):
    schema_version: str
    owner: str
    default_timezone: str
    principles: list[str] = Field(min_length=3)
    targets: list[BackupTarget] = Field(min_length=1)
    incident_triggers: list[str] = Field(min_length=1)
    restore_drill_evidence: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_target_ids(self) -> BackupFailoverPolicy:
        target_ids = [target.target_id for target in self.targets]
        duplicate_ids = sorted({target_id for target_id in target_ids if target_ids.count(target_id) > 1})
        if duplicate_ids:
            raise ValueError(f"duplicate backup target ids: {', '.join(duplicate_ids)}")
        return self

    def target(self, target_id: str) -> BackupTarget:
        for target in self.targets:
            if target.target_id == target_id:
                return target
        raise LookupError(f"Unknown backup target: {target_id}")


def load_backup_failover_policy(path: Path) -> BackupFailoverPolicy:
    return BackupFailoverPolicy.model_validate_json(path.read_text(encoding="utf-8"))


def backup_policy_summary(policy: BackupFailoverPolicy) -> dict[str, object]:
    strictest_rpo = min(target.rpo_minutes for target in policy.targets)
    strictest_rto = min(target.rto_hours for target in policy.targets)
    return {
        "schema_version": policy.schema_version,
        "owner": policy.owner,
        "target_count": len(policy.targets),
        "strictest_rpo_minutes": strictest_rpo,
        "strictest_rto_hours": strictest_rto,
    }


def main() -> None:
    policy = load_backup_failover_policy(Path("docs/operations/backup_failover_policy.json"))
    print(json.dumps(backup_policy_summary(policy), sort_keys=True))


if __name__ == "__main__":
    main()
