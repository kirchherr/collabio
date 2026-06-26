from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.persistence.migrator import apply_migrations
from suite.platform.legacy_sql_migration_run_registry import (
    InMemoryLegacySqlMigrationRunRegistryStore,
    JsonlLegacySqlMigrationRunRegistryStore,
    LegacySqlMigrationReportMetadata,
    LegacySqlMigrationReportMetadataCommand,
    LegacySqlMigrationReportStatus,
    LegacySqlMigrationRunCreationBoundaryCommand,
    LegacySqlMigrationRunCreationBoundaryStatus,
    LegacySqlMigrationRunCreationStoreCommand,
    LegacySqlMigrationRunCreationStoreStatus,
    LegacySqlMigrationRunRegistryEntry,
    LegacySqlMigrationRunRegistryEntryCommand,
    LegacySqlMigrationRunStatus,
    PgLegacySqlMigrationRunRegistryStore,
    build_default_legacy_sql_migration_run_registry_store,
    build_legacy_sql_migration_report_metadata,
    build_legacy_sql_migration_report_metadata_hash,
    build_legacy_sql_migration_report_metadata_idempotency_key_hash,
    build_legacy_sql_migration_run_creation_boundary,
    build_legacy_sql_migration_run_creation_boundary_hash,
    build_legacy_sql_migration_run_creation_request_hash,
    build_legacy_sql_migration_run_creation_store_response_hash,
    build_legacy_sql_migration_run_registry_entry,
    build_legacy_sql_migration_run_registry_entry_from_boundary,
    build_legacy_sql_migration_run_registry_entry_hash,
    build_legacy_sql_migration_run_registry_idempotency_key_hash,
    persist_legacy_sql_migration_run_creation,
)


@dataclass(frozen=True)
class LiveDatabase:
    migration_dsn: str
    worker_dsn: str


def env_or_skip(name: str) -> str:
    value = os.environ.get(name)
    if value is None:
        pytest.skip(f"{name} is not configured")
    return value


@pytest.fixture(scope="module")
def live_database() -> LiveDatabase:
    migration_dsn = env_or_skip("SUITE_MIGRATION_DATABASE_DSN")
    worker_dsn = env_or_skip("SUITE_WORKER_DATABASE_DSN")
    apply_migrations(migration_dsn)
    return LiveDatabase(migration_dsn=migration_dsn, worker_dsn=worker_dsn)


def test_legacy_sql_migration_run_registry_entry_and_report_are_metadata_only_and_hashable() -> None:
    run_command = migration_run_command()
    run_entry = build_legacy_sql_migration_run_registry_entry(
        command=run_command,
        tenant_id="tenant-demo",
        requested_at_utc=fixed_time(),
    )
    report_command = migration_report_command(migration_run_hash=run_entry.evidence_hash)
    report = build_legacy_sql_migration_report_metadata(command=report_command, tenant_id=run_entry.tenant_id)

    assert run_entry.schema_version == "legacy_sql_migration_run_registry_entry.v1"
    assert run_entry.run_status == LegacySqlMigrationRunStatus.PLANNED_METADATA_ONLY
    assert run_entry.evidence_hash == build_legacy_sql_migration_run_registry_entry_hash(run_entry)
    assert run_entry.idempotency_key_hash == build_legacy_sql_migration_run_registry_idempotency_key_hash(
        command=run_command,
        tenant_id=run_entry.tenant_id,
    )
    assert run_entry.future_import_write_execution_gate_required
    assert not run_entry.run_creation_enabled
    assert not run_entry.run_execution_allowed
    assert not run_entry.import_write_execution_allowed
    assert not run_entry.raw_data_access_allowed
    assert not run_entry.import_write_payload_allowed
    assert not run_entry.destructive_actions_allowed
    assert not run_entry.external_side_effect_allowed
    assert run_entry.metadata_only_report_required

    assert report.schema_version == "legacy_sql_migration_report_metadata.v1"
    assert report.report_status == LegacySqlMigrationReportStatus.PLANNED_METADATA_ONLY
    assert report.migration_run_hash == run_entry.evidence_hash
    assert report.evidence_hash == build_legacy_sql_migration_report_metadata_hash(report)
    assert report.idempotency_key_hash == build_legacy_sql_migration_report_metadata_idempotency_key_hash(
        command=report_command,
        tenant_id=report.tenant_id,
    )
    assert report.metadata_only_ok
    assert report.future_import_write_execution_gate_required
    assert not report.report_retrieval_enabled
    assert not report.run_execution_completed
    assert not report.import_write_execution_allowed
    assert not report.raw_data_access_allowed
    assert not report.import_write_payload_allowed
    assert not report.destructive_actions_allowed
    assert not report.external_side_effect_allowed

    payload = f"{run_entry.model_dump_json()} {report.model_dump_json()}".lower()
    assert "dbo.kunden" not in payload
    assert "kundenid" not in payload
    assert "email" not in payload
    assert "connection_secret_ref" not in payload
    assert "sqlserver://" not in payload
    assert "raw_payload" not in payload
    assert '"import_write_payload":' not in payload


def test_legacy_sql_migration_run_creation_boundary_is_metadata_only_and_hashable() -> None:
    command = migration_run_creation_boundary_command()

    boundary = build_legacy_sql_migration_run_creation_boundary(
        command=command,
        tenant_id="tenant-demo",
        checked_by="migration-boundary-test",
        checked_at_utc=fixed_time(),
    )

    assert boundary.schema_version == "legacy_sql_migration_run_creation_boundary.v1"
    assert boundary.boundary_status == LegacySqlMigrationRunCreationBoundaryStatus.READY_FOR_RUN_REGISTRY_REQUEST
    assert boundary.evidence_hash == build_legacy_sql_migration_run_creation_boundary_hash(boundary)
    assert boundary.run_creation_request_hash == build_legacy_sql_migration_run_creation_request_hash(command)
    assert boundary.run_creation_requested
    assert boundary.run_creation_boundary_accepted
    assert boundary.future_import_write_execution_gate_required
    assert not boundary.run_registry_persistence_requested
    assert not boundary.run_registry_persistence_allowed
    assert not boundary.run_registry_entry_persisted
    assert not boundary.approval_grant_requested
    assert not boundary.approval_grant_enabled
    assert not boundary.report_retrieval_requested
    assert not boundary.report_retrieval_enabled
    assert not boundary.run_creation_enabled
    assert not boundary.run_execution_allowed
    assert not boundary.import_write_execution_allowed
    assert not boundary.raw_data_access_allowed
    assert not boundary.import_write_payload_allowed
    assert not boundary.destructive_actions_allowed
    assert not boundary.external_side_effect_allowed
    assert boundary.blocking_reasons == ()

    payload = boundary.model_dump_json().lower()
    assert "dbo.kunden" not in payload
    assert "kundenid" not in payload
    assert "email" not in payload
    assert "connection_secret_ref" not in payload
    assert "sqlserver://" not in payload
    assert "raw_payload" not in payload
    assert '"import_write_payload":' not in payload


def test_legacy_sql_migration_run_creation_boundary_blocks_persistence_and_execution_requests() -> None:
    command = migration_run_creation_boundary_command(
        run_registry_persistence_requested=True,
        approval_grant_requested=True,
        report_retrieval_requested=True,
        import_write_execution_requested=True,
        raw_data_access_requested=True,
        import_write_payload_requested=True,
        destructive_actions_requested=True,
        external_side_effect_requested=True,
    )

    boundary = build_legacy_sql_migration_run_creation_boundary(
        command=command,
        tenant_id="tenant-demo",
        checked_by="migration-boundary-test",
        checked_at_utc=fixed_time(),
    )

    assert boundary.boundary_status == LegacySqlMigrationRunCreationBoundaryStatus.BLOCKED
    assert not boundary.run_creation_boundary_accepted
    assert "run_registry_persistence_not_enabled" in boundary.blocking_reasons
    assert "approval_grant_requires_future_gate" in boundary.blocking_reasons
    assert "report_retrieval_not_enabled" in boundary.blocking_reasons
    assert "import_write_execution_requires_future_gate" in boundary.blocking_reasons
    assert "raw_data_access_request_forbidden" in boundary.blocking_reasons
    assert "import_write_payload_request_forbidden" in boundary.blocking_reasons
    assert "destructive_action_request_forbidden" in boundary.blocking_reasons
    assert "external_side_effect_request_forbidden" in boundary.blocking_reasons
    assert not boundary.run_registry_persistence_allowed
    assert not boundary.approval_grant_enabled
    assert not boundary.import_write_execution_allowed


def test_legacy_sql_migration_run_creation_store_persists_boundary_idempotently_metadata_only() -> None:
    boundary = build_legacy_sql_migration_run_creation_boundary(
        command=migration_run_creation_boundary_command(),
        tenant_id="tenant-demo",
        checked_by="migration-boundary-test",
        checked_at_utc=fixed_time(),
    )
    command = LegacySqlMigrationRunCreationStoreCommand(run_creation_boundary=boundary)
    store = InMemoryLegacySqlMigrationRunRegistryStore()

    response = persist_legacy_sql_migration_run_creation(
        command=command,
        store=store,
        tenant_id="tenant-demo",
        checked_by="migration-store-test",
        checked_at_utc=fixed_time(),
    )

    assert response.schema_version == "legacy_sql_migration_run_creation_store.v1"
    assert response.store_status == LegacySqlMigrationRunCreationStoreStatus.PERSISTED_METADATA_ONLY
    assert response.evidence_hash == build_legacy_sql_migration_run_creation_store_response_hash(response)
    assert response.run_creation_boundary_evidence_hash == boundary.evidence_hash
    assert response.run_creation_request_hash == boundary.run_creation_request_hash
    assert response.idempotency_key_hash == boundary.idempotency_key_hash
    assert response.run_registry_persistence_requested
    assert response.run_registry_persistence_allowed
    assert response.run_registry_entry_persisted
    assert not response.idempotent_replay
    assert response.migration_run is not None
    assert response.migration_run_hash == response.migration_run.evidence_hash
    assert response.migration_run == build_legacy_sql_migration_run_registry_entry_from_boundary(boundary)
    assert response.migration_run.evidence_hash == build_legacy_sql_migration_run_registry_entry_hash(
        response.migration_run
    )
    assert store.list_runs(tenant_id="tenant-demo") == (response.migration_run,)
    assert not response.approval_grant_enabled
    assert not response.report_retrieval_enabled
    assert not response.run_creation_enabled
    assert not response.run_execution_allowed
    assert not response.import_write_execution_allowed
    assert not response.raw_data_access_allowed
    assert not response.import_write_payload_allowed
    assert not response.destructive_actions_allowed
    assert not response.external_side_effect_allowed

    replay = persist_legacy_sql_migration_run_creation(
        command=command,
        store=store,
        tenant_id="tenant-demo",
        checked_by="migration-store-test",
        checked_at_utc=fixed_time(),
    )
    assert replay.store_status == LegacySqlMigrationRunCreationStoreStatus.IDEMPOTENT_REPLAY
    assert replay.idempotent_replay
    assert replay.migration_run == response.migration_run
    assert store.list_runs(tenant_id="tenant-demo") == (response.migration_run,)


def test_legacy_sql_migration_run_creation_store_blocks_unready_or_unsafe_requests() -> None:
    blocked_boundary = build_legacy_sql_migration_run_creation_boundary(
        command=migration_run_creation_boundary_command(import_write_execution_requested=True),
        tenant_id="tenant-demo",
        checked_by="migration-boundary-test",
        checked_at_utc=fixed_time(),
    )
    unsafe_command = LegacySqlMigrationRunCreationStoreCommand(
        run_creation_boundary=blocked_boundary,
        approval_grant_requested=True,
        report_retrieval_requested=True,
        raw_data_access_requested=True,
        import_write_payload_requested=True,
    )
    store = InMemoryLegacySqlMigrationRunRegistryStore()

    response = persist_legacy_sql_migration_run_creation(
        command=unsafe_command,
        store=store,
        tenant_id="tenant-demo",
        checked_by="migration-store-test",
        checked_at_utc=fixed_time(),
    )

    assert response.store_status == LegacySqlMigrationRunCreationStoreStatus.BLOCKED
    assert not response.run_registry_persistence_allowed
    assert not response.run_registry_entry_persisted
    assert response.migration_run is None
    assert response.migration_run_hash is None
    assert "run_creation_boundary_not_ready" in response.blocking_reasons
    assert "approval_grant_requires_future_gate" in response.blocking_reasons
    assert "report_retrieval_not_enabled" in response.blocking_reasons
    assert "raw_data_access_request_forbidden" in response.blocking_reasons
    assert "import_write_payload_request_forbidden" in response.blocking_reasons
    assert store.list_runs(tenant_id="tenant-demo") == ()


def test_legacy_sql_migration_run_registry_blocks_execution_and_raw_data_requests() -> None:
    with pytest.raises(ValueError, match="must not request execution or side effects"):
        migration_run_command(
            run_creation_requested=True,
            run_execution_requested=True,
            import_write_execution_requested=True,
            raw_data_access_requested=True,
        )

    with pytest.raises(ValueError, match="must not request execution or side effects"):
        migration_report_command(
            report_retrieval_requested=True,
            run_execution_completed_requested=True,
            import_write_execution_requested=True,
            raw_data_access_requested=True,
        )

    with pytest.raises(ValueError, match="raw data or secrets"):
        migration_run_command(migration_run_ref="legacy-sql:dbo.kunden")


def test_legacy_sql_migration_run_registry_jsonl_store_replays_lookup_indexes_and_idempotency(
    tmp_path: Path,
) -> None:
    run_entry = migration_run_entry()
    report = migration_report(run_entry)
    store = JsonlLegacySqlMigrationRunRegistryStore(
        run_path=tmp_path / "migration-runs.jsonl",
        report_path=tmp_path / "migration-reports.jsonl",
    )

    store.append_run(run_entry)
    store.append_report(report)
    assert store.append_run(run_entry) == run_entry
    assert store.append_report(report) == report

    reloaded = JsonlLegacySqlMigrationRunRegistryStore(
        run_path=tmp_path / "migration-runs.jsonl",
        report_path=tmp_path / "migration-reports.jsonl",
    )

    assert reloaded.get_run(tenant_id=run_entry.tenant_id, evidence_hash=run_entry.evidence_hash) == run_entry
    assert reloaded.get_run_by_ref(tenant_id=run_entry.tenant_id, migration_run_ref=run_entry.migration_run_ref) == (
        run_entry
    )
    assert (
        reloaded.get_run_by_idempotency_key_hash(
            tenant_id=run_entry.tenant_id,
            idempotency_key_hash=run_entry.idempotency_key_hash,
        )
        == run_entry
    )
    assert reloaded.list_runs(tenant_id=run_entry.tenant_id) == (run_entry,)
    assert reloaded.get_report(tenant_id=report.tenant_id, evidence_hash=report.evidence_hash) == report
    assert reloaded.get_report_by_ref(tenant_id=report.tenant_id, migration_report_ref=report.migration_report_ref) == (
        report
    )
    assert reloaded.list_reports_for_run(tenant_id=report.tenant_id, migration_run_hash=run_entry.evidence_hash) == (
        report,
    )
    assert len((tmp_path / "migration-runs.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    assert len((tmp_path / "migration-reports.jsonl").read_text(encoding="utf-8").splitlines()) == 1

    conflicting_run = migration_run_entry(migration_run_ref="migration-run:legacy-sql-conflict")
    with pytest.raises(ValueError, match="idempotency key already used"):
        reloaded.append_run(conflicting_run)

    conflicting_report = migration_report(run_entry, migration_report_ref="migration-report:legacy-sql-conflict")
    with pytest.raises(ValueError, match="idempotency key already used"):
        reloaded.append_report(conflicting_report)


def test_pg_legacy_sql_migration_run_registry_store_persists_metadata_with_tenant_isolation(
    live_database: LiveDatabase,
) -> None:
    suffix = uuid4().hex
    tenant_id = f"tenant-migration-run-{suffix}"
    run_entry = migration_run_entry(
        tenant_id=tenant_id,
        migration_run_ref=f"migration-run:legacy-sql-{suffix}",
        idempotency_key_ref=f"idempotency:legacy-sql-migration-run-{suffix}",
    )
    report = migration_report(
        run_entry,
        migration_report_ref=f"migration-report:legacy-sql-{suffix}",
        idempotency_key_ref=f"idempotency:legacy-sql-migration-report-{suffix}",
    )
    store = PgLegacySqlMigrationRunRegistryStore(database_dsn=live_database.worker_dsn)

    store.append_run(run_entry)
    store.append_report(report)
    assert store.append_run(run_entry) == run_entry
    assert store.append_report(report) == report

    assert store.get_run(tenant_id=tenant_id, evidence_hash=run_entry.evidence_hash) == run_entry
    assert store.get_run_by_ref(tenant_id=tenant_id, migration_run_ref=run_entry.migration_run_ref) == run_entry
    assert (
        store.get_run_by_idempotency_key_hash(
            tenant_id=tenant_id,
            idempotency_key_hash=run_entry.idempotency_key_hash,
        )
        == run_entry
    )
    assert store.list_runs(tenant_id=tenant_id) == (run_entry,)
    assert store.get_report(tenant_id=tenant_id, evidence_hash=report.evidence_hash) == report
    assert store.get_report_by_ref(tenant_id=tenant_id, migration_report_ref=report.migration_report_ref) == report
    assert store.list_reports(tenant_id=tenant_id) == (report,)
    assert store.list_reports_for_run(tenant_id=tenant_id, migration_run_hash=run_entry.evidence_hash) == (report,)

    with pytest.raises(KeyError, match="not found"):
        store.get_run(tenant_id=f"{tenant_id}-other", evidence_hash=run_entry.evidence_hash)
    with pytest.raises(KeyError, match="not found"):
        store.get_report(tenant_id=f"{tenant_id}-other", evidence_hash=report.evidence_hash)


def test_default_legacy_sql_migration_run_registry_store_uses_jsonl_paths(tmp_path: Path) -> None:
    store = build_default_legacy_sql_migration_run_registry_store(
        data_dir=tmp_path,
        environ={"SUITE_LEGACY_SQL_MIGRATION_RUN_REGISTRY_BACKEND": "jsonl"},
    )

    assert isinstance(store, JsonlLegacySqlMigrationRunRegistryStore)
    assert store.run_path == tmp_path / "legacy_sql_migration_runs.jsonl"
    assert store.report_path == tmp_path / "legacy_sql_migration_reports.jsonl"


def migration_run_entry(
    *,
    tenant_id: str = "tenant-demo",
    **command_updates: object,
) -> LegacySqlMigrationRunRegistryEntry:
    return build_legacy_sql_migration_run_registry_entry(
        command=migration_run_command(**command_updates),
        tenant_id=tenant_id,
        requested_at_utc=fixed_time(),
    )


def migration_report(
    run_entry: LegacySqlMigrationRunRegistryEntry,
    **command_updates: object,
) -> LegacySqlMigrationReportMetadata:
    return build_legacy_sql_migration_report_metadata(
        command=migration_report_command(migration_run_hash=run_entry.evidence_hash, **command_updates),
        tenant_id=run_entry.tenant_id,
    )


def migration_run_creation_boundary_command(**updates: object) -> LegacySqlMigrationRunCreationBoundaryCommand:
    values: dict[str, object] = {
        "source_system_ref": "legacy-sql:sqlserver-demo",
        "migration_run_ref": "migration-run:legacy-sql-boundary-demo",
        "approval_record_hash": fixture_hash("approval-record"),
        "approval_gate_evidence_hash": fixture_hash("approval-gate"),
        "dry_run_result_hash": fixture_hash("dry-run-result"),
        "idempotency_key_ref": "idempotency:legacy-sql-migration-run-boundary",
        "restore_evidence_hash": fixture_hash("restore-evidence"),
        "audit_event_id": "audit-event-legacy-sql-migration-run-boundary",
        "audit_chain_ref": "audit:legacy-sql-migration-run-boundary",
        "reason": "prepare a metadata-only migration run boundary without execution",
    }
    values.update(updates)
    return LegacySqlMigrationRunCreationBoundaryCommand.model_validate(values)


def migration_run_command(**updates: object) -> LegacySqlMigrationRunRegistryEntryCommand:
    values: dict[str, object] = {
        "source_system_ref": "legacy-sql:sqlserver-demo",
        "migration_run_ref": "migration-run:legacy-sql-demo",
        "approval_record_hash": fixture_hash("approval-record"),
        "approval_gate_evidence_hash": fixture_hash("approval-gate"),
        "dry_run_result_hash": fixture_hash("dry-run-result"),
        "idempotency_key_ref": "idempotency:legacy-sql-migration-run",
        "restore_evidence_hash": fixture_hash("restore-evidence"),
        "audit_event_id": "audit-event-legacy-sql-migration-run",
        "audit_chain_ref": "audit:legacy-sql-migration-run",
        "requested_by": "migration-run-test",
    }
    values.update(updates)
    return LegacySqlMigrationRunRegistryEntryCommand.model_validate(values)


def migration_report_command(**updates: object) -> LegacySqlMigrationReportMetadataCommand:
    values: dict[str, object] = {
        "source_system_ref": "legacy-sql:sqlserver-demo",
        "migration_run_hash": fixture_hash("migration-run"),
        "migration_report_ref": "migration-report:legacy-sql-demo",
        "idempotency_key_ref": "idempotency:legacy-sql-migration-report",
        "planned_table_count": 3,
        "table_result_count": 3,
        "row_count_manifest_hash": fixture_hash("row-count-manifest"),
        "checksum_manifest_hash": fixture_hash("checksum-manifest"),
        "restore_evidence_hash": fixture_hash("report-restore-evidence"),
        "audit_event_id": "audit-event-legacy-sql-migration-report",
        "audit_chain_ref": "audit:legacy-sql-migration-report",
    }
    values.update(updates)
    return LegacySqlMigrationReportMetadataCommand.model_validate(values)


def fixture_hash(label: str) -> str:
    return stable_hash(canonical_json({"fixture": label}))


def fixed_time() -> datetime:
    return datetime(2026, 6, 24, 11, tzinfo=UTC)
