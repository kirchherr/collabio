from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.persistence.migrator import apply_migrations
from suite.platform.crm_erp_legacy_mapping import (
    CrmErpLegacyImportDryRunPlan,
    CrmErpLegacyImportDryRunStatus,
    CrmErpLegacyMappingAction,
    CrmErpLegacyMappingEvidenceService,
    CrmErpLegacyMappingOverride,
    build_crm_erp_legacy_import_dry_run_plan,
    build_crm_erp_legacy_import_readiness_evidence,
    build_crm_erp_legacy_staging_metadata_plan,
)
from suite.platform.legacy_sql_discovery import (
    LegacySqlColumnMetadata,
    LegacySqlConnectorKind,
    LegacySqlDiscoveryManifest,
    LegacySqlDiscoveryRequest,
    LegacySqlDiscoveryService,
    LegacySqlImportEvidencePlan,
    LegacySqlSchemaSnapshot,
    LegacySqlTableMetadata,
)
from suite.platform.legacy_sql_import_dry_run_worker import (
    JsonlLegacySqlImportDryRunResultStore,
    LegacySqlImportDryRunResultStatus,
    PgLegacySqlImportDryRunResultStore,
    build_legacy_sql_import_dry_run_result_hash,
    build_legacy_sql_import_dry_run_worker_report_hash,
    execute_legacy_sql_import_dry_run_plan,
    exit_code_for_report,
    legacy_sql_import_dry_run_result_ref,
    run_legacy_sql_import_dry_run_worker_from_env,
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


def test_legacy_sql_import_dry_run_worker_executes_ready_plan_metadata_only() -> None:
    dry_run_plan = ready_dry_run_plan()
    result = execute_legacy_sql_import_dry_run_plan(
        dry_run_plan=dry_run_plan,
        row_count_observations={"dbo.Kunden": 12, "dbo.FreieTabelle": 3},
        checksum_manifest_hashes=checksum_hashes(dry_run_plan),
        executed_by="dry-run-test",
        executed_at_utc=datetime(2026, 6, 21, 9, tzinfo=UTC),
    )

    assert dry_run_plan.status == CrmErpLegacyImportDryRunStatus.READY_FOR_METADATA_DRY_RUN
    assert result.schema_version == "legacy_sql_import_dry_run_result.v1"
    assert result.status == LegacySqlImportDryRunResultStatus.COMPLETED_METADATA_ONLY
    assert result.result_hash == build_legacy_sql_import_dry_run_result_hash(result)
    assert legacy_sql_import_dry_run_result_ref(result) == f"legacy-sql-import-dry-run-result:{result.result_hash}"
    assert result.dry_run_plan_hash == dry_run_plan.manifest_hash
    assert result.table_result_count == 2
    assert result.expected_table_count == 2
    assert result.dry_run_execution_attempted
    assert result.dry_run_execution_completed
    assert result.metadata_only_ok
    assert not result.real_connection_used
    assert not result.raw_data_import_allowed
    assert not result.import_write_executed
    assert not result.destructive_actions_executed
    assert {table_result.observed_row_count for table_result in result.table_results} == {3, 12}
    assert all(table_result.checksum_manifest_hash.startswith("sha256:") for table_result in result.table_results)
    assert all(table_result.table_result_hash.startswith("sha256:") for table_result in result.table_results)

    payload = result.model_dump_json().lower()
    assert "kundenid" not in payload
    assert "email" not in payload
    assert "sample_value" not in payload
    assert "connection_secret_ref" not in payload
    assert "sqlserver://" not in payload


def test_legacy_sql_import_dry_run_worker_blocks_unclean_plan_without_table_results() -> None:
    dry_run_plan = blocked_dry_run_plan()
    result = execute_legacy_sql_import_dry_run_plan(
        dry_run_plan=dry_run_plan,
        row_count_observations={},
        checksum_manifest_hashes={},
        executed_by="dry-run-test",
        executed_at_utc=datetime(2026, 6, 21, 9, tzinfo=UTC),
    )

    assert result.status == LegacySqlImportDryRunResultStatus.BLOCKED_BY_PLAN
    assert result.table_result_count == 0
    assert result.table_results == ()
    assert not result.dry_run_execution_attempted
    assert not result.dry_run_execution_completed
    assert "quarantine_tables_require_manual_mapping" in result.blocking_reasons
    assert "legacy_row_fallbacks_require_mapping_review" in result.blocking_reasons
    assert not result.import_write_executed


def test_legacy_sql_import_dry_run_result_store_replays_jsonl(tmp_path: Path) -> None:
    dry_run_plan = ready_dry_run_plan()
    result = execute_legacy_sql_import_dry_run_plan(
        dry_run_plan=dry_run_plan,
        row_count_observations={"dbo.Kunden": 12, "dbo.FreieTabelle": 3},
        checksum_manifest_hashes=checksum_hashes(dry_run_plan),
        executed_by="dry-run-jsonl-test",
        executed_at_utc=datetime(2026, 6, 21, 9, tzinfo=UTC),
    )
    path = tmp_path / "legacy-sql-import-dry-run-results.jsonl"
    store = JsonlLegacySqlImportDryRunResultStore(path=path)

    persisted = store.append(result)
    reloaded = JsonlLegacySqlImportDryRunResultStore(path=path)

    assert persisted == result
    assert reloaded.get(tenant_id=result.tenant_id, result_hash=result.result_hash) == result
    assert reloaded.list_results(tenant_id=result.tenant_id) == (result,)
    with pytest.raises(ValueError, match="already exists"):
        reloaded.append(result)


def test_pg_legacy_sql_import_dry_run_result_store_persists_with_tenant_isolation(
    live_database: LiveDatabase,
) -> None:
    suffix = uuid4().hex
    dry_run_plan = ready_dry_run_plan(tenant_id=f"tenant-dry-run-{suffix}")
    result = execute_legacy_sql_import_dry_run_plan(
        dry_run_plan=dry_run_plan,
        row_count_observations={"dbo.Kunden": 12, "dbo.FreieTabelle": 3},
        checksum_manifest_hashes=checksum_hashes(dry_run_plan),
        executed_by="dry-run-pg-test",
        executed_at_utc=datetime(2026, 6, 21, 9, tzinfo=UTC),
    )
    store = PgLegacySqlImportDryRunResultStore(database_dsn=live_database.worker_dsn)

    store.append(result)

    assert store.get(tenant_id=result.tenant_id, result_hash=result.result_hash) == result
    assert store.list_results(tenant_id=result.tenant_id) == (result,)
    with pytest.raises(KeyError, match="not found"):
        store.get(tenant_id=f"{result.tenant_id}-other", result_hash=result.result_hash)


def test_legacy_sql_import_dry_run_worker_report_is_metadata_only_and_hashable(tmp_path: Path) -> None:
    store_path = tmp_path / "dry-run-results.jsonl"
    report = run_legacy_sql_import_dry_run_worker_from_env(
        {
            "SUITE_LEGACY_SQL_IMPORT_DRY_RUN_RESULT_STORE_WRITE": "true",
            "SUITE_LEGACY_SQL_IMPORT_DRY_RUN_RESULT_STORE_BACKEND": "jsonl",
            "SUITE_LEGACY_SQL_IMPORT_DRY_RUN_RESULT_STORE_PATH": str(store_path),
        }
    )

    assert report.schema_version == "legacy_sql_import_dry_run_worker_report.v1"
    assert report.worker_passed
    assert exit_code_for_report(report) == 0
    assert report.result_status == LegacySqlImportDryRunResultStatus.COMPLETED_METADATA_ONLY
    assert report.metadata_only_ok
    assert report.result_store_write_enabled
    assert report.result_store_backend == "jsonl"
    assert report.table_result_count == 2
    assert report.evidence_hash == build_legacy_sql_import_dry_run_worker_report_hash(report)
    assert store_path.exists()

    payload = report.model_dump_json()
    assert "dbo.Kunden" not in payload
    assert "dbo.FreieTabelle" not in payload
    assert "KundenId" not in payload
    assert "Email" not in payload
    assert "secret:legacy-sql-dry-run" not in payload
    assert "connection_secret_ref" not in payload


def discovery_request(*, tenant_id: str = "tenant-1") -> LegacySqlDiscoveryRequest:
    return LegacySqlDiscoveryRequest(
        tenant_id=tenant_id,
        module_id="crm_erp",
        source_system_ref="legacy-sql:sqlserver-prod",
        connector_kind=LegacySqlConnectorKind.SQLSERVER,
        requested_by="admin-1",
        approval_reference="approval:legacy-sql-discovery",
        audit_chain_ref="audit:legacy-sql-discovery",
    )


def column(name: str, ordinal_position: int, data_type: str = "nvarchar") -> LegacySqlColumnMetadata:
    return LegacySqlColumnMetadata(
        name=name,
        ordinal_position=ordinal_position,
        data_type=data_type,
        nullable=ordinal_position != 1,
        max_length=255,
    )


def discovery_snapshot() -> LegacySqlSchemaSnapshot:
    return LegacySqlSchemaSnapshot(
        connection_fingerprint_hash="sha256:legacy-sql-fingerprint",
        tables=(
            LegacySqlTableMetadata(
                schema_name="dbo",
                table_name="Kunden",
                row_count_estimate=12,
                columns=(
                    column("KundenId", 1, "int"),
                    column("Name", 2),
                    column("Email", 3),
                ),
                primary_key_columns=("KundenId",),
            ),
            LegacySqlTableMetadata(
                schema_name="dbo",
                table_name="FreieTabelle",
                row_count_estimate=3,
                columns=(column("Id", 1, "int"), column("Text", 2)),
                primary_key_columns=("Id",),
            ),
        ),
    )


def discovery_manifest_and_plan(
    *, tenant_id: str = "tenant-1"
) -> tuple[
    LegacySqlDiscoveryManifest,
    LegacySqlImportEvidencePlan,
]:
    service = LegacySqlDiscoveryService()
    manifest = service.build_discovery_manifest(
        request=discovery_request(tenant_id=tenant_id), snapshot=discovery_snapshot()
    )
    plan = service.build_import_evidence_plan(manifest=manifest)
    return manifest, plan


def ready_dry_run_plan(*, tenant_id: str = "tenant-1") -> CrmErpLegacyImportDryRunPlan:
    manifest, plan = discovery_manifest_and_plan(tenant_id=tenant_id)
    service = CrmErpLegacyMappingEvidenceService()
    mapping = service.build_mapping_manifest(
        discovery_manifest=manifest,
        import_evidence_plan=plan,
        overrides=(
            CrmErpLegacyMappingOverride(
                source_table_ref="dbo.FreieTabelle",
                action=CrmErpLegacyMappingAction.MAP_TO_TARGET,
                target_object_type="crm.contact",
                mapping_reason="manual schema review identified contact table",
                approval_reference="approval:legacy-mapping-freie-tabelle",
            ),
        ),
    )
    readiness = build_crm_erp_legacy_import_readiness_evidence(
        discovery_manifest=manifest,
        import_evidence_plan=plan,
        mapping_manifest=mapping,
    )
    staging_plan = build_crm_erp_legacy_staging_metadata_plan(
        discovery_manifest=manifest,
        mapping_manifest=mapping,
        captured_at_utc=datetime(2026, 6, 20, 10, tzinfo=UTC),
    )
    return build_crm_erp_legacy_import_dry_run_plan(
        discovery_manifest=manifest,
        mapping_manifest=mapping,
        readiness_evidence=readiness,
        staging_metadata_plan=staging_plan,
    )


def blocked_dry_run_plan() -> CrmErpLegacyImportDryRunPlan:
    manifest, plan = discovery_manifest_and_plan()
    service = CrmErpLegacyMappingEvidenceService()
    mapping = service.build_mapping_manifest(discovery_manifest=manifest, import_evidence_plan=plan)
    readiness = build_crm_erp_legacy_import_readiness_evidence(
        discovery_manifest=manifest,
        import_evidence_plan=plan,
        mapping_manifest=mapping,
    )
    staging_plan = build_crm_erp_legacy_staging_metadata_plan(
        discovery_manifest=manifest,
        mapping_manifest=mapping,
        captured_at_utc=datetime(2026, 6, 20, 10, tzinfo=UTC),
    )
    return build_crm_erp_legacy_import_dry_run_plan(
        discovery_manifest=manifest,
        mapping_manifest=mapping,
        readiness_evidence=readiness,
        staging_metadata_plan=staging_plan,
    )


def checksum_hashes(dry_run_plan: CrmErpLegacyImportDryRunPlan) -> dict[str, str]:
    row_counts = {"dbo.Kunden": 12, "dbo.FreieTabelle": 3}
    return {
        table_plan.source_table_ref: stable_hash(
            canonical_json(
                {
                    "dry_run_plan_hash": dry_run_plan.manifest_hash,
                    "observed_row_count": row_counts[table_plan.source_table_ref],
                    "source_system_ref": dry_run_plan.source_system_ref,
                    "source_table_ref": table_plan.source_table_ref,
                }
            )
        )
        for table_plan in dry_run_plan.table_plans
    }


def normalized(sql: str) -> str:
    return re.sub(r"\s+", " ", sql.lower()).strip()
