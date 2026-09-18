import pytest

from office_recovery_proof import require_office_recovery_environment


def recovery_environment() -> dict[str, str]:
    return {
        "SUITE_OFFICE_RECOVERY_MODE": "isolated-office-recovery",
        "SUITE_ENV": "dev",
        "SUITE_PRODUCTIVITY_PILOT_RUNTIME_ENABLED": "0",
        "SUITE_POSTGRES_RESTORE_SOURCE_DSN": "postgresql://collabio_owner:synthetic@work-e2e-postgres:5432/collabio_work_e2e",
        "SUITE_POSTGRES_RESTORE_TARGET_DSN": "postgresql://collabio_owner:synthetic@postgres-restore:5432/collabio_work_e2e_restore",
        "SUITE_DATABASE_DSN": "postgresql://collabio_app:synthetic@work-e2e-postgres:5432/collabio_work_e2e",
        "SUITE_OFFICE_RECOVERY_TARGET_DSN": "postgresql://collabio_app:synthetic@postgres-restore:5432/collabio_work_e2e_restore",
        "SUITE_S3_ENDPOINT_URL": "http://work-e2e-minio:9000",
        "SUITE_RESTORE_S3_ENDPOINT_URL": "http://minio-restore:9000",
        "SUITE_POSTGRES_BACKUP_DIRECTORY": "/proof-backup",
        "SUITE_POSTGRES_RESTORE_RECEIPT_PATH": "/proof-backup/postgres-restore-receipt.sha256",
    }


def test_office_recovery_accepts_only_explicit_separate_synthetic_targets() -> None:
    require_office_recovery_environment(recovery_environment())


@pytest.mark.parametrize("key,value", [
    ("SUITE_OFFICE_RECOVERY_MODE", ""),
    ("SUITE_ENV", "production"),
    ("SUITE_PRODUCTIVITY_PILOT_RUNTIME_ENABLED", "1"),
    ("SUITE_POSTGRES_RESTORE_SOURCE_DSN", "postgresql://collabio_owner:x@postgres:5432/collabio"),
    ("SUITE_POSTGRES_RESTORE_TARGET_DSN", "postgresql://collabio_owner:x@postgres-restore:5432/collabio_restore"),
    ("SUITE_OFFICE_RECOVERY_TARGET_DSN", "postgresql://collabio_app:x@work-e2e-postgres:5432/collabio_work_e2e"),
    ("SUITE_DATABASE_DSN", "postgresql://collabio_app:x@work-e2e-postgres:5432/collabio_work_e2e?host=postgres"),
    ("SUITE_S3_ENDPOINT_URL", "http://minio:9000"),
    ("SUITE_RESTORE_S3_ENDPOINT_URL", "http://work-e2e-minio:9000"),
    ("SUITE_POSTGRES_BACKUP_DIRECTORY", "/backups"),
    ("SUITE_POSTGRES_RESTORE_RECEIPT_PATH", "/backups/postgres-restore-receipt.sha256"),
])
def test_office_recovery_denies_live_same_target_or_unscoped_overrides(key: str, value: str) -> None:
    env = recovery_environment()
    env[key] = value
    with pytest.raises(ValueError):
        require_office_recovery_environment(env)
