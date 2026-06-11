import pytest
from pydantic import ValidationError

from suite.platform.legacy_sql_discovery import (
    LegacySqlColumnMetadata,
    LegacySqlConnectorKind,
    LegacySqlDiscoveryError,
    LegacySqlDiscoveryRequest,
    LegacySqlDiscoveryService,
    LegacySqlSchemaSnapshot,
    LegacySqlTableMetadata,
    _assert_no_raw_payload,
)


def discovery_request(*, include_row_counts: bool = True) -> LegacySqlDiscoveryRequest:
    return LegacySqlDiscoveryRequest(
        tenant_id="tenant-1",
        module_id="crm_erp",
        source_system_ref="legacy-sql:sqlserver-prod",
        connector_kind=LegacySqlConnectorKind.SQLSERVER,
        requested_by="admin-1",
        approval_reference="approval:legacy-sql-discovery",
        audit_chain_ref="audit:legacy-sql-discovery",
        include_row_counts=include_row_counts,
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
                columns=(
                    column("Id", 1, "int"),
                    column("Text", 2),
                ),
                primary_key_columns=("Id",),
            ),
        ),
    )


def test_legacy_sql_discovery_builds_metadata_only_manifest_and_import_plan() -> None:
    service = LegacySqlDiscoveryService()

    manifest = service.build_discovery_manifest(
        request=discovery_request(),
        snapshot=discovery_snapshot(),
    )
    plan = service.build_import_evidence_plan(manifest=manifest)

    assert manifest.tenant_id == "tenant-1"
    assert manifest.module_id == "crm_erp"
    assert manifest.table_count == 2
    assert manifest.column_count == 5
    assert manifest.estimated_row_count == 15
    assert manifest.snapshot_hash.startswith("sha256:")
    assert manifest.manifest_hash.startswith("sha256:")
    assert manifest.object_candidates[0].candidate_object_type == "crm.account"
    assert manifest.object_candidates[0].confidence == "medium"
    assert manifest.object_candidates[1].candidate_object_type == "legacy.row"

    assert plan.discovery_manifest_hash == manifest.manifest_hash
    assert plan.quarantine_table_refs == ("dbo.FreieTabelle",)
    assert plan.approval_required
    assert plan.dry_run_required
    assert not plan.raw_data_import_allowed
    assert not plan.destructive_actions_allowed
    assert plan.manifest_hash.startswith("sha256:")


def test_legacy_sql_discovery_can_omit_row_counts_from_hashable_manifest() -> None:
    service = LegacySqlDiscoveryService()

    manifest = service.build_discovery_manifest(
        request=discovery_request(include_row_counts=False),
        snapshot=discovery_snapshot(),
    )

    assert manifest.estimated_row_count is None
    assert manifest.snapshot_hash.startswith("sha256:")


def test_legacy_sql_discovery_rejects_raw_payload_or_sql_text() -> None:
    with pytest.raises(ValidationError, match="Extra inputs"):
        LegacySqlTableMetadata.model_validate(
            {
                "schema_name": "dbo",
                "table_name": "Contacts",
                "columns": [{"name": "Id", "ordinal_position": 1, "data_type": "int", "nullable": False}],
                "sample_rows": [{"Id": 1, "Email": "person@example.invalid"}],
            }
        )

    with pytest.raises(ValidationError, match="SQL statements"):
        column("Danger", 1, "nvarchar from customers")


def test_legacy_sql_discovery_raw_payload_guard_blocks_nested_preview_data() -> None:
    snapshot = discovery_snapshot()
    unsafe_payload = snapshot.model_dump(mode="json")
    unsafe_payload["tables"][0]["preview_values"] = ["secret"]

    with pytest.raises(LegacySqlDiscoveryError, match="raw legacy SQL payload"):
        _assert_no_raw_payload(unsafe_payload)
