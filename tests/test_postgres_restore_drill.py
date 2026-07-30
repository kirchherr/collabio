from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from suite.operations.backend_foundation_completion_gate import (
    build_backend_foundation_completion_gate,
    build_backend_foundation_completion_gate_hash,
    load_backend_foundation_completion_gate,
    persist_backend_foundation_completion_gate,
)
from suite.operations.postgres_restore_drill import (
    AUDIT_APPEND_ONLY_POLICIES_BY_TABLE,
    AUDIT_TABLES,
    CRM_ATOMIC_RECEIPT_POLICIES,
    CRM_ATOMIC_WRITE_TABLES,
    MODULE_REGISTRY_TABLES,
    SERVICE_ROLES,
    SOURCE_OBJECT_TABLES,
    TASKS_ACTIVITIES_APPEND_ONLY_POLICIES_BY_TABLE,
    TASKS_ACTIVITIES_WRITE_TABLES,
    TENANT_IAM_TABLES,
    TIME_TRACKING_APPEND_ONLY_POLICIES_BY_TABLE,
    TIME_TRACKING_WRITE_TABLES,
    PostgresBackupArtifactEvidence,
    PostgresDatabaseSnapshot,
    PostgresRestoreDrillReport,
    build_postgres_backup_artifact_evidence,
    build_postgres_database_snapshot,
    build_postgres_restore_drill_report,
    build_postgres_restore_drill_report_hash,
    build_postgres_restore_target_isolation_ref_hash,
    discover_postgres_backup_artifact,
)
from suite.persistence.migration_catalog import load_migrations
from suite.storage.backend_storage_foundation_gate import (
    BackendStorageFoundationGate,
    build_backend_storage_foundation_gate_hash,
)

CHECKED_AT = "2026-07-30T10:00:00Z"


def _snapshot(
    *, database_hash: str, changed_row_count: bool = False, tasks_controls: bool = True, time_controls: bool = True
) -> PostgresDatabaseSnapshot:
    table_names = sorted(
        TENANT_IAM_TABLES
        | AUDIT_TABLES
        | MODULE_REGISTRY_TABLES
        | SOURCE_OBJECT_TABLES
        | CRM_ATOMIC_WRITE_TABLES
        | TASKS_ACTIVITIES_WRITE_TABLES
        | TIME_TRACKING_WRITE_TABLES
    )
    tables = [
        {
            "schema_name": qualified_name.split(".", 1)[0],
            "table_name": qualified_name.split(".", 1)[1],
            "relation_kind": "r",
            "rls_enabled": True,
            "rls_forced": True,
        }
        for qualified_name in table_names
    ]
    row_counts = [
        {
            "schema_name": table["schema_name"],
            "table_name": table["table_name"],
            "row_count": int(changed_row_count and index == 0),
        }
        for index, table in enumerate(tables)
    ]
    migrations = [
        {
            "version": migration.version,
            "name": migration.name,
            "module_id": migration.module_id,
            "checksum": migration.checksum(),
            "evidence_refs": list(migration.evidence_refs),
            "blocks_startup": migration.blocks_startup,
        }
        for migration in load_migrations()
    ]
    policies = [
        {
            "schema_name": qualified_name.split(".", 1)[0],
            "table_name": qualified_name.split(".", 1)[1],
            "policy_name": policy_name,
        }
        for qualified_name, policy_names in sorted(AUDIT_APPEND_ONLY_POLICIES_BY_TABLE.items())
        for policy_name in sorted(policy_names)
    ]
    policies.extend(
        {
            "schema_name": "crm",
            "table_name": "account_onboarding_receipts",
            "policy_name": policy_name,
        }
        for policy_name in sorted(CRM_ATOMIC_RECEIPT_POLICIES)
    )
    policies.extend(
        {
            "schema_name": table_name.split(".", 1)[0],
            "table_name": table_name.split(".", 1)[1],
            "policy_name": policy_name,
        }
        for table_name, policy_names in sorted(TASKS_ACTIVITIES_APPEND_ONLY_POLICIES_BY_TABLE.items())
        for policy_name in sorted(policy_names)
    )
    policies.extend(
        {
            "schema_name": table_name.split(".", 1)[0],
            "table_name": table_name.split(".", 1)[1],
            "policy_name": policy_name,
        }
        for table_name, policy_names in sorted(TIME_TRACKING_APPEND_ONLY_POLICIES_BY_TABLE.items())
        for policy_name in sorted(policy_names)
    )
    roles = [{"role_name": role_name, "can_login": True} for role_name in sorted(SERVICE_ROLES)]
    grants = [
        {
            "schema_name": table_name.split(".", 1)[0],
            "table_name": table_name.split(".", 1)[1],
            "grantee": "collabio_audit_writer",
            "privilege_type": privilege,
        }
        for table_name in sorted(AUDIT_TABLES)
        for privilege in ("INSERT", "SELECT")
    ]
    grants.extend(
        {
            "schema_name": table_name.split(".", 1)[0],
            "table_name": table_name.split(".", 1)[1],
            "grantee": "collabio_authz_admin",
            "privilege_type": privilege,
        }
        for table_name in sorted(CRM_ATOMIC_WRITE_TABLES)
        for privilege in ("INSERT", "SELECT")
    )
    grants.extend(
        {
            "schema_name": table_name.split(".", 1)[0],
            "table_name": table_name.split(".", 1)[1],
            "grantee": "collabio_authz_admin",
            "privilege_type": privilege,
        }
        for table_name in sorted(TASKS_ACTIVITIES_WRITE_TABLES)
        for privilege in ("INSERT", "SELECT")
    )
    grants.extend(
        {
            "schema_name": table_name.split(".", 1)[0],
            "table_name": table_name.split(".", 1)[1],
            "grantee": "collabio_app",
            "privilege_type": "SELECT",
        }
        for table_name in sorted(TASKS_ACTIVITIES_WRITE_TABLES)
    )
    grants.extend(
        {
            "schema_name": table_name.split(".", 1)[0],
            "table_name": table_name.split(".", 1)[1],
            "grantee": "collabio_authz_admin",
            "privilege_type": privilege,
        }
        for table_name in sorted(TIME_TRACKING_WRITE_TABLES)
        for privilege in ("INSERT", "SELECT")
    )
    grants.extend(
        {
            "schema_name": table_name.split(".", 1)[0],
            "table_name": table_name.split(".", 1)[1],
            "grantee": "collabio_app",
            "privilege_type": "SELECT",
        }
        for table_name in sorted(TIME_TRACKING_WRITE_TABLES)
    )
    if not tasks_controls:
        grants.append(
            {
                "schema_name": "tasks",
                "table_name": "items",
                "grantee": "collabio_app",
                "privilege_type": "INSERT",
            }
        )
    if not time_controls:
        grants.append(
            {
                "schema_name": "time_tracking",
                "table_name": "entries",
                "grantee": "collabio_app",
                "privilege_type": "INSERT",
            }
        )
    return build_postgres_database_snapshot(
        database_ref_hash=database_hash,
        schemas=[{"schema_name": "collabio"}],
        tables=tables,
        columns=[],
        row_counts=row_counts,
        migrations=migrations,
        policies=policies,
        constraints=[],
        indexes=[],
        triggers=[],
        extensions=[{"extension_name": "plpgsql", "extension_version": "1.0"}],
        roles=roles,
        grants=grants,
    )


def _backup_evidence() -> PostgresBackupArtifactEvidence:
    return build_postgres_backup_artifact_evidence(
        artifact_ref="collabio.dump",
        backup_sha256="sha256:" + "a" * 64,
        byte_length=512,
        checksum_sidecar_verified=True,
        restore_loader_receipt_verified=True,
    )


def _restore_report(
    *, changed_target_row_count: bool = False, target_tasks_controls: bool = True, target_time_controls: bool = True
) -> PostgresRestoreDrillReport:
    return build_postgres_restore_drill_report(
        backup_evidence=_backup_evidence(),
        source_snapshot=_snapshot(database_hash="sha256:" + "b" * 64),
        target_snapshot=_snapshot(
            database_hash="sha256:" + "c" * 64,
            changed_row_count=changed_target_row_count,
            tasks_controls=target_tasks_controls,
            time_controls=target_time_controls,
        ),
        target_isolation_ref_hash="sha256:" + "d" * 64,
        checked_at_utc=CHECKED_AT,
    )


def _storage_gate(*, ready: bool = True) -> BackendStorageFoundationGate:
    draft = BackendStorageFoundationGate(
        checked_at_utc=CHECKED_AT,
        runtime_environment="dev",
        tenant_ids=("tenant-demo", "tenant-other"),
        persistent_runtime_report_hash="sha256:" + "1" * 64,
        exact_version_restore_drill_report_hash="sha256:" + "2" * 64,
        source_provider_profile_evidence_hash="sha256:" + "3" * 64,
        source_manifest_count=3,
        restored_object_count=3,
        restart_verified_source_object_count=3,
        runtime_restore_binding_verified=ready,
        persistent_runtime_verified=ready,
        exact_version_restore_verified=ready,
        independent_restore_target_verified=ready,
        tenant_scope_verified=ready,
        metadata_only_evidence_verified=True,
        blocking_reasons=() if ready else ("exact_version_restore_not_ready",),
        api_start_allowed=ready,
        backend_storage_foundation_ready=ready,
        gate_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"gate_hash": build_backend_storage_foundation_gate_hash(draft)})


def test_postgres_restore_drill_verifies_exact_isolated_state() -> None:
    report = _restore_report()

    assert report.restore_ready is True
    assert report.source_target_state_verified is True
    assert report.migration_count == len(load_migrations())
    assert report.tenant_iam_controls_verified is True
    assert report.append_only_audit_controls_verified is True
    assert report.module_registry_controls_verified is True
    assert report.source_object_controls_verified is True
    assert report.content_included is False
    assert report.crm_atomic_write_controls_verified is True
    assert report.tasks_activities_write_controls_verified is True
    assert report.time_tracking_write_controls_verified is True
    assert report.report_hash == build_postgres_restore_drill_report_hash(report)


def test_postgres_restore_drill_blocks_exact_row_count_drift() -> None:
    report = _restore_report(changed_target_row_count=True)

    assert report.restore_ready is False
    assert report.exact_row_counts_verified is False
    assert "exact_row_counts_mismatch" in report.blocking_reasons
    assert "source_target_state_mismatch" in report.blocking_reasons


def test_postgres_restore_drill_blocks_unsafe_tasks_application_grant() -> None:
    report = _restore_report(target_tasks_controls=False)

    assert report.restore_ready is False
    assert report.tasks_activities_write_controls_verified is False
    assert "tasks_activities_write_controls_not_verified" in report.blocking_reasons


def test_postgres_restore_drill_blocks_unsafe_time_tracking_application_grant() -> None:
    report = _restore_report(target_time_controls=False)

    assert report.restore_ready is False
    assert report.time_tracking_write_controls_verified is False
    assert "time_tracking_write_controls_not_verified" in report.blocking_reasons


def test_postgres_restore_target_must_be_independent() -> None:
    dsn = "postgresql://owner:secret@postgres:5432/collabio"

    with pytest.raises(ValueError, match="must be isolated"):
        build_postgres_restore_target_isolation_ref_hash(source_dsn=dsn, target_dsn=dsn)


def test_backup_artifact_evidence_binds_sidecar_and_loader_receipt(tmp_path: Path) -> None:
    artifact = tmp_path / "collabio-restore.dump"
    artifact.write_bytes(b"metadata-only-test-dump")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    Path(str(artifact) + ".sha256").write_text(f"{digest}  /backups/{artifact.name}\n", encoding="ascii")
    receipt = tmp_path / "postgres-restore-receipt.sha256"
    receipt.write_text(f"sha256:{digest}\n", encoding="ascii")

    evidence = discover_postgres_backup_artifact(
        backup_directory=tmp_path,
        restore_receipt_path=receipt,
    )

    assert evidence.checksum_sidecar_verified is True
    assert evidence.restore_loader_receipt_verified is True
    assert evidence.catalog_preflight_verified is True


def test_backend_foundation_completion_gate_binds_database_and_object_recovery() -> None:
    gate = build_backend_foundation_completion_gate(
        postgres_restore_report=_restore_report(),
        storage_gate=_storage_gate(),
    )

    assert gate.backend_foundation_complete is True
    assert gate.api_start_allowed is True
    assert gate.tenant_iam_verified is True
    assert gate.postgres_backup_restore_verified is True
    assert gate.exact_version_object_restore_verified is True
    assert gate.crm_atomic_write_controls_verified is True
    assert gate.tasks_activities_write_controls_verified is True
    assert gate.time_tracking_write_controls_verified is True
    assert gate.productive_business_write_controls_verified is True
    assert gate.content_included is False
    assert gate.gate_hash == build_backend_foundation_completion_gate_hash(gate)


def test_backend_foundation_completion_gate_blocks_missing_productive_write_control() -> None:
    gate = build_backend_foundation_completion_gate(
        postgres_restore_report=_restore_report(target_time_controls=False),
        storage_gate=_storage_gate(),
    )

    assert gate.backend_foundation_complete is False
    assert gate.productive_business_write_controls_verified is False
    assert "time_tracking_write_controls_not_verified" in gate.blocking_reasons
    assert "productive_business_write_controls_not_verified" in gate.blocking_reasons


def test_backend_foundation_completion_gate_report_round_trip_and_tamper_detection(tmp_path: Path) -> None:
    gate = build_backend_foundation_completion_gate(
        postgres_restore_report=_restore_report(),
        storage_gate=_storage_gate(),
    )
    report_path = tmp_path / "backend-gate.json"

    persist_backend_foundation_completion_gate(gate=gate, report_path=report_path)

    assert load_backend_foundation_completion_gate(report_path) == gate
    report_path.write_text(
        report_path.read_text(encoding="utf-8").replace(
            f'"migration_count":{gate.migration_count}',
            f'"migration_count":{gate.migration_count + 1}',
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="hash is invalid"):
        load_backend_foundation_completion_gate(report_path)


def test_backend_foundation_completion_gate_blocks_failed_storage_recovery() -> None:
    gate = build_backend_foundation_completion_gate(
        postgres_restore_report=_restore_report(),
        storage_gate=_storage_gate(ready=False),
    )

    assert gate.backend_foundation_complete is False
    assert "storage_foundation_not_ready" in gate.blocking_reasons
    assert "exact_version_object_restore_not_verified" in gate.blocking_reasons


def test_compose_exposes_isolated_postgres_restore_and_completion_gate() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert "\n  postgres-restore:\n" in compose
    assert "\n  postgres-backup-restore-loader:\n" in compose
    assert "\n  postgres-restore-drill:\n" in compose
    assert "\n  backend-foundation-completion-gate:\n" in compose
    assert "\n  business-backend-release-gate:\n" in compose
    assert "\n  productivity-pilot-preflight-gate:\n" in compose
    assert "dropdb -h postgres-restore" in compose
    assert "pg_restore -h postgres-restore" in compose
    assert "--exit-on-error" in compose
    assert "postgres18_restore_data:/var/lib/postgresql" in compose
    assert "python -m suite.operations.postgres_restore_drill" in compose
    assert "python -m suite.operations.backend_foundation_completion_gate" in compose
    assert "python -m suite.operations.business_backend_release_gate" in compose
    assert "python -m suite.operations.productivity_pilot_preflight" in compose
    assert "SUITE_BACKEND_FOUNDATION_GATE_REPORT_PATH: /backups/backend-foundation-completion-gate.json" in compose
    assert "SUITE_BUSINESS_BACKEND_RELEASE_GATE_REPORT_PATH: /backups/business-backend-release-gate.json" in compose
