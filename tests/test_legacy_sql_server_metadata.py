from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from suite.platform.legacy_sql_discovery import LegacySqlConnectorKind, LegacySqlDiscoveryRequest
from suite.platform.legacy_sql_server_metadata import (
    LegacySqlConnectorPolicyError,
    LegacySqlMetadataQuery,
    LegacySqlServerMetadataDiscoveryCommand,
    LegacySqlServerMetadataWorker,
    LegacySqlServerMetadataWorkerError,
    build_legacy_sql_connector_policy_hash,
    build_sql_server_metadata_query_plan,
    legacy_sql_connector_policy_summary,
    load_legacy_sql_connector_policy,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = REPO_ROOT / "docs" / "legacy_sql_connector_policy.json"


@dataclass
class CapturingMetadataExecutor:
    rows_by_query: dict[str, list[dict[str, Any]]]
    calls: list[LegacySqlMetadataQuery] = field(default_factory=list)
    connection_secret_refs: list[str] = field(default_factory=list)

    def fetch_all(
        self,
        *,
        connection_secret_ref: str,
        query: LegacySqlMetadataQuery,
    ) -> list[dict[str, Any]]:
        self.connection_secret_refs.append(connection_secret_ref)
        self.calls.append(query)
        return self.rows_by_query.get(query.name, [])


@dataclass
class CapturingLegacySqlAuditSink:
    events: list[dict[str, Any]] = field(default_factory=list)

    def record_worker_event(
        self,
        *,
        tenant_id: str,
        event_type: str,
        source_system_ref: str,
        metadata: dict[str, Any],
    ) -> str:
        self.events.append(
            {
                "tenant_id": tenant_id,
                "event_type": event_type,
                "source_system_ref": source_system_ref,
                "metadata": metadata,
            }
        )
        return f"audit-{len(self.events)}"


def discovery_request(*, include_row_counts: bool = True) -> LegacySqlDiscoveryRequest:
    return LegacySqlDiscoveryRequest(
        tenant_id="tenant-1",
        module_id="crm_erp",
        source_system_ref="legacy-sql:sqlserver-prod",
        connector_kind=LegacySqlConnectorKind.SQLSERVER,
        requested_by="admin-1",
        approval_reference="approval:legacy-sql-metadata",
        audit_chain_ref="audit:legacy-sql-metadata",
        include_row_counts=include_row_counts,
    )


def discovery_command(*, include_row_counts: bool = True) -> LegacySqlServerMetadataDiscoveryCommand:
    policy = load_legacy_sql_connector_policy(POLICY_PATH)
    return LegacySqlServerMetadataDiscoveryCommand(
        request=discovery_request(include_row_counts=include_row_counts),
        connection_secret_ref="secret:legacy-sql-prod",
        connection_fingerprint_hash="sha256:legacy-sql-fingerprint",
        connector_policy_ref="policy:legacy-sql-connector",
        policy_snapshot_hash=build_legacy_sql_connector_policy_hash(policy),
    )


def metadata_rows() -> dict[str, list[dict[str, Any]]]:
    return {
        "tables": [
            {"schema_name": "dbo", "table_name": "Kunden", "relation_kind": "table"},
            {"schema_name": "dbo", "table_name": "FreieTabelle", "relation_kind": "table"},
        ],
        "columns": [
            column_row("dbo", "Kunden", "KundenId", 1, "int", "NO"),
            column_row("dbo", "Kunden", "Name", 2, "nvarchar", "YES", max_length=255),
            column_row("dbo", "Kunden", "Email", 3, "nvarchar", "YES", max_length=255),
            column_row("dbo", "FreieTabelle", "Id", 1, "int", "NO"),
            column_row("dbo", "FreieTabelle", "Text", 2, "nvarchar", "YES", max_length=255),
        ],
        "primary_keys": [
            {"schema_name": "dbo", "table_name": "Kunden", "column_name": "KundenId", "ordinal_position": 1},
            {"schema_name": "dbo", "table_name": "FreieTabelle", "column_name": "Id", "ordinal_position": 1},
        ],
        "foreign_keys": [],
        "indexes": [
            {
                "schema_name": "dbo",
                "table_name": "Kunden",
                "index_name": "IX_Kunden_Email",
                "column_name": "Email",
                "ordinal_position": 1,
                "is_unique": False,
            }
        ],
        "row_counts": [
            {"schema_name": "dbo", "table_name": "Kunden", "row_count_estimate": 12},
            {"schema_name": "dbo", "table_name": "FreieTabelle", "row_count_estimate": 3},
        ],
    }


def column_row(
    schema_name: str,
    table_name: str,
    column_name: str,
    ordinal_position: int,
    data_type: str,
    is_nullable: str,
    *,
    max_length: int | None = None,
) -> dict[str, Any]:
    return {
        "schema_name": schema_name,
        "table_name": table_name,
        "column_name": column_name,
        "ordinal_position": ordinal_position,
        "data_type": data_type,
        "is_nullable": is_nullable,
        "max_length": max_length,
        "numeric_precision": None,
        "numeric_scale": None,
        "is_identity": ordinal_position == 1,
        "default_present": False,
    }


def test_legacy_sql_connector_policy_and_query_plan_are_metadata_only() -> None:
    policy = load_legacy_sql_connector_policy(POLICY_PATH)
    summary = legacy_sql_connector_policy_summary(policy)
    query_plan = build_sql_server_metadata_query_plan()

    assert summary["schema_version"] == "legacy_sql_server_connector_policy.v1"
    assert summary["connector_kind"] == "sqlserver"
    assert summary["isolated_worker_required"]
    assert summary["required_worker_network_mode"] == "approved_legacy_host_only"
    assert not summary["raw_row_reads_allowed"]
    assert summary["allowed_query_count"] == 6
    policy_hash = summary["policy_hash"]
    assert isinstance(policy_hash, str)
    assert policy_hash.startswith("sha256:")
    assert tuple(query.name for query in query_plan) == (
        "tables",
        "columns",
        "primary_keys",
        "foreign_keys",
        "indexes",
        "row_counts",
    )
    for query in query_plan:
        policy.assert_query_allowed(query)
        assert "select *" not in query.statement.lower()
        assert "dbo.Kunden" not in query.statement


def test_sql_server_metadata_worker_builds_discovery_and_import_evidence_without_raw_rows() -> None:
    policy = load_legacy_sql_connector_policy(POLICY_PATH)
    executor = CapturingMetadataExecutor(metadata_rows())
    audit_sink = CapturingLegacySqlAuditSink()
    worker = LegacySqlServerMetadataWorker(policy=policy, executor=executor, audit_sink=audit_sink)

    result = worker.discover(discovery_command())

    assert result.executed_query_names == (
        "tables",
        "columns",
        "primary_keys",
        "foreign_keys",
        "indexes",
        "row_counts",
    )
    assert executor.connection_secret_refs == ["secret:legacy-sql-prod"] * 6
    assert result.manifest.table_count == 2
    assert result.manifest.column_count == 5
    assert result.manifest.estimated_row_count == 15
    candidates_by_table = {
        candidate.source_table_ref: candidate.candidate_object_type for candidate in result.manifest.object_candidates
    }
    assert candidates_by_table["dbo.Kunden"] == "crm.account"
    assert candidates_by_table["dbo.FreieTabelle"] == "legacy.row"
    assert result.import_evidence_plan.quarantine_table_refs == ("dbo.FreieTabelle",)
    assert result.import_evidence_plan.dry_run_required
    assert not result.import_evidence_plan.raw_data_import_allowed
    assert result.worker_network_mode == "approved_legacy_host_only"

    assert [event["event_type"] for event in audit_sink.events] == [
        "legacy_sql.metadata_discovery.started",
        "legacy_sql.metadata_discovery.completed",
    ]
    completed_metadata = audit_sink.events[-1]["metadata"]
    assert completed_metadata["table_count"] == 2
    assert completed_metadata["column_count"] == 5
    assert completed_metadata["quarantine_table_count"] == 1
    assert "connection_secret_ref" not in completed_metadata
    assert "source_tables" not in completed_metadata


def test_sql_server_metadata_worker_omits_row_count_query_when_request_disables_counts() -> None:
    policy = load_legacy_sql_connector_policy(POLICY_PATH)
    executor = CapturingMetadataExecutor(metadata_rows())
    worker = LegacySqlServerMetadataWorker(policy=policy, executor=executor)

    result = worker.discover(discovery_command(include_row_counts=False))

    assert "row_counts" not in result.executed_query_names
    assert result.manifest.estimated_row_count is None
    assert [query.name for query in executor.calls] == ["tables", "columns", "primary_keys", "foreign_keys", "indexes"]


def test_sql_server_metadata_worker_rejects_raw_payload_result_fields() -> None:
    policy = load_legacy_sql_connector_policy(POLICY_PATH)
    rows = metadata_rows()
    rows["columns"][0]["sample_value"] = "person@example.invalid"
    worker = LegacySqlServerMetadataWorker(policy=policy, executor=CapturingMetadataExecutor(rows))

    with pytest.raises(LegacySqlConnectorPolicyError, match="forbidden"):
        worker.discover(discovery_command())


def test_sql_server_metadata_worker_requires_matching_policy_snapshot_hash() -> None:
    policy = load_legacy_sql_connector_policy(POLICY_PATH)
    command = discovery_command().model_copy(update={"policy_snapshot_hash": "sha256:wrong-policy"})
    worker = LegacySqlServerMetadataWorker(policy=policy, executor=CapturingMetadataExecutor(metadata_rows()))

    with pytest.raises(LegacySqlServerMetadataWorkerError, match="policy_snapshot_hash"):
        worker.discover(command)


def test_sql_server_connector_policy_rejects_user_table_queries() -> None:
    policy = load_legacy_sql_connector_policy(POLICY_PATH)

    with pytest.raises(LegacySqlConnectorPolicyError, match="forbidden fragment"):
        policy.assert_query_allowed(LegacySqlMetadataQuery(name="tables", statement="SELECT * FROM dbo.Customers"))
