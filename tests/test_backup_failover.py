from pathlib import Path

from suite.operations.backup_failover import backup_policy_summary, load_backup_failover_policy

REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = REPO_ROOT / "docs" / "operations" / "backup_failover_policy.json"
RUNBOOK_PATH = REPO_ROOT / "docs" / "operations" / "BACKUP_FAILOVER.md"
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"


def test_backup_failover_policy_declares_practical_targets_and_drills() -> None:
    policy = load_backup_failover_policy(POLICY_PATH)

    assert policy.schema_version == "backup_failover_policy.v1"
    assert policy.owner == "platform-operations"
    assert len(policy.targets) == 3
    assert backup_policy_summary(policy) == {
        "schema_version": "backup_failover_policy.v1",
        "owner": "platform-operations",
        "target_count": 3,
        "strictest_rpo_minutes": 15,
        "strictest_rto_hours": 4,
    }

    postgres = policy.target("postgres_primary")
    assert postgres.rpo_minutes <= 15
    assert postgres.rto_hours <= 4
    assert postgres.restore_drill_frequency_days <= 30
    assert "sha256_manifest" in postgres.integrity_checks
    assert "pg_restore_catalog" in postgres.integrity_checks
    assert "docker compose run --rm backup" in postgres.current_dev_commands
    assert "docker compose run --rm backup-verify" in postgres.current_dev_commands

    for target in policy.targets:
        assert target.backup_methods
        assert target.integrity_checks
        assert target.failover_mode
        assert target.restore_drill_frequency_days <= 90


def test_backup_failover_runbook_names_restore_culture_and_commands() -> None:
    runbook = RUNBOOK_PATH.read_text(encoding="utf-8")

    assert "a backup does not count until it has a checksum" in runbook
    assert "docker compose run --rm backup" in runbook
    assert "docker compose run --rm backup-verify" in runbook
    assert "RPO" in runbook
    assert "RTO" in runbook
    assert "Failover" in runbook
    assert "Monthly" in runbook


def test_compose_exposes_backup_and_verification_commands() -> None:
    compose = COMPOSE_PATH.read_text(encoding="utf-8")

    assert "\n  backup:\n" in compose
    assert "\n  backup-verify:\n" in compose
    assert "pg_dump" in compose
    assert "sha256sum" in compose
    assert "pg_restore --list" in compose
    assert "./backups:/backups" in compose
