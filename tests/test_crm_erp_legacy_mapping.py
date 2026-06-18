from __future__ import annotations

import pytest

from suite.ai_control_plane.models import DataClass
from suite.platform.crm_erp_legacy_mapping import (
    CrmErpLegacyImportReadinessStatus,
    CrmErpLegacyMappingAction,
    CrmErpLegacyMappingEvidenceError,
    CrmErpLegacyMappingEvidenceService,
    CrmErpLegacyMappingOverride,
    build_crm_erp_legacy_import_readiness_evidence,
    default_crm_erp_target_profiles,
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


def discovery_request() -> LegacySqlDiscoveryRequest:
    return LegacySqlDiscoveryRequest(
        tenant_id="tenant-1",
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
                columns=(
                    column("Id", 1, "int"),
                    column("Text", 2),
                ),
                primary_key_columns=("Id",),
            ),
        ),
    )


def discovery_manifest_and_plan() -> tuple[LegacySqlDiscoveryManifest, LegacySqlImportEvidencePlan]:
    service = LegacySqlDiscoveryService()
    manifest = service.build_discovery_manifest(request=discovery_request(), snapshot=discovery_snapshot())
    plan = service.build_import_evidence_plan(manifest=manifest)
    return manifest, plan


def test_crm_erp_mapping_evidence_maps_known_candidate_and_quarantines_unknown_table() -> None:
    manifest, plan = discovery_manifest_and_plan()
    service = CrmErpLegacyMappingEvidenceService()

    mapping = service.build_mapping_manifest(discovery_manifest=manifest, import_evidence_plan=plan)

    decisions_by_table = {decision.source_table_ref: decision for decision in mapping.decisions}
    kunden = decisions_by_table["dbo.Kunden"]
    freie_tabelle = decisions_by_table["dbo.FreieTabelle"]

    assert mapping.tenant_id == "tenant-1"
    assert mapping.module_id == "crm_erp"
    assert mapping.discovery_manifest_hash == manifest.manifest_hash
    assert mapping.import_evidence_plan_hash == plan.manifest_hash
    assert mapping.manifest_hash.startswith("sha256:")
    assert mapping.target_object_counts == {"crm.account": 1, "legacy.row": 1}
    assert mapping.quarantine_table_refs == ("dbo.FreieTabelle",)
    assert mapping.legacy_row_table_refs == ("dbo.FreieTabelle",)
    assert mapping.mapping_approval_required
    assert mapping.dry_run_required
    assert not mapping.raw_data_import_allowed
    assert not mapping.destructive_actions_allowed

    assert kunden.action == CrmErpLegacyMappingAction.MAP_TO_TARGET
    assert kunden.target_object_type == "crm.account"
    assert kunden.feature_id == "crm_erp.crm.accounts"
    assert kunden.classification == DataClass.PERSONAL
    assert kunden.retention_policy_id == "rp-standard"
    assert not kunden.quarantine_required

    assert freie_tabelle.action == CrmErpLegacyMappingAction.MAP_TO_LEGACY_ROW
    assert freie_tabelle.target_object_type == "legacy.row"
    assert freie_tabelle.feature_id == "crm_erp.legacy_import.sqlserver"
    assert freie_tabelle.classification == DataClass.CONFIDENTIAL
    assert freie_tabelle.retention_policy_id == "rp-restricted"
    assert freie_tabelle.quarantine_required


def test_crm_erp_mapping_override_can_promote_quarantined_table_with_approval() -> None:
    manifest, plan = discovery_manifest_and_plan()
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

    decision = {item.source_table_ref: item for item in mapping.decisions}["dbo.FreieTabelle"]
    assert decision.action == CrmErpLegacyMappingAction.MAP_TO_TARGET
    assert decision.target_object_type == "crm.contact"
    assert decision.feature_id == "crm_erp.crm.contacts"
    assert decision.classification == DataClass.PERSONAL
    assert decision.approval_reference == "approval:legacy-mapping-freie-tabelle"
    assert not decision.quarantine_required
    assert mapping.quarantine_table_refs == ()
    assert mapping.legacy_row_table_refs == ()
    assert mapping.target_object_counts == {"crm.account": 1, "crm.contact": 1}


def test_crm_erp_import_readiness_requires_manual_mapping_for_quarantined_legacy_rows() -> None:
    manifest, plan = discovery_manifest_and_plan()
    service = CrmErpLegacyMappingEvidenceService()
    mapping = service.build_mapping_manifest(discovery_manifest=manifest, import_evidence_plan=plan)

    readiness = build_crm_erp_legacy_import_readiness_evidence(
        discovery_manifest=manifest,
        import_evidence_plan=plan,
        mapping_manifest=mapping,
    )

    assert readiness.schema_version == "crm_erp_legacy_import_readiness.v1"
    assert readiness.status == CrmErpLegacyImportReadinessStatus.MANUAL_MAPPING_REQUIRED
    assert not readiness.dry_run_allowed
    assert not readiness.import_write_allowed
    assert not readiness.raw_data_import_allowed
    assert not readiness.destructive_actions_allowed
    assert readiness.table_count == 2
    assert readiness.candidate_count == 2
    assert readiness.target_mapping_count == 1
    assert readiness.quarantine_table_count == 1
    assert readiness.legacy_row_table_count == 1
    assert readiness.manual_review_required
    assert "quarantine_tables_require_manual_mapping" in readiness.blocking_reasons
    assert "legacy_row_fallbacks_require_mapping_review" in readiness.blocking_reasons
    assert readiness.evidence_hash.startswith("sha256:")
    assert "KundenId" not in readiness.model_dump_json()
    assert "Email" not in readiness.model_dump_json()


def test_crm_erp_import_readiness_allows_metadata_dry_run_after_approved_mapping_override() -> None:
    manifest, plan = discovery_manifest_and_plan()
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

    assert readiness.status == CrmErpLegacyImportReadinessStatus.READY_FOR_DRY_RUN
    assert readiness.dry_run_allowed
    assert readiness.dry_run_required
    assert readiness.manual_review_required
    assert not readiness.import_write_allowed
    assert not readiness.raw_data_import_allowed
    assert readiness.blocking_reasons == ()
    assert readiness.target_mapping_count == 2
    assert readiness.quarantine_table_count == 0
    assert readiness.legacy_row_table_count == 0
    assert "run metadata-only legacy import dry-run validation" in readiness.next_actions


def test_crm_erp_import_readiness_blocks_mismatched_mapping_manifest() -> None:
    manifest, plan = discovery_manifest_and_plan()
    service = CrmErpLegacyMappingEvidenceService()
    mapping = service.build_mapping_manifest(
        discovery_manifest=manifest,
        import_evidence_plan=plan,
    ).model_copy(update={"import_evidence_plan_hash": "sha256:other"})

    readiness = build_crm_erp_legacy_import_readiness_evidence(
        discovery_manifest=manifest,
        import_evidence_plan=plan,
        mapping_manifest=mapping,
    )

    assert readiness.status == CrmErpLegacyImportReadinessStatus.BLOCKED
    assert not readiness.dry_run_allowed
    assert "mapping_manifest_import_plan_hash_mismatch" in readiness.blocking_reasons
    assert "mapping_manifest_hash_invalid" in readiness.blocking_reasons
    assert "repair legacy SQL evidence chain before dry-run" in readiness.next_actions


def test_crm_erp_mapping_rejects_quarantined_target_override_without_approval() -> None:
    manifest, plan = discovery_manifest_and_plan()
    service = CrmErpLegacyMappingEvidenceService()

    with pytest.raises(CrmErpLegacyMappingEvidenceError, match="requires approval_reference"):
        service.build_mapping_manifest(
            discovery_manifest=manifest,
            import_evidence_plan=plan,
            overrides=(
                CrmErpLegacyMappingOverride(
                    source_table_ref="dbo.FreieTabelle",
                    action=CrmErpLegacyMappingAction.MAP_TO_TARGET,
                    target_object_type="crm.contact",
                    mapping_reason="manual schema review identified contact table",
                ),
            ),
        )


def test_crm_erp_mapping_rejects_import_evidence_for_different_manifest() -> None:
    manifest, plan = discovery_manifest_and_plan()
    mismatched_plan = plan.model_copy(update={"discovery_manifest_hash": "sha256:other-discovery-manifest"})
    service = CrmErpLegacyMappingEvidenceService()

    with pytest.raises(CrmErpLegacyMappingEvidenceError, match="does not reference"):
        service.build_mapping_manifest(discovery_manifest=manifest, import_evidence_plan=mismatched_plan)


def test_crm_erp_target_profiles_cover_initial_charter_object_types() -> None:
    profiles = default_crm_erp_target_profiles()

    assert set(profiles) >= {
        "crm.account",
        "crm.contact",
        "crm.activity",
        "crm.note",
        "erp.product",
        "erp.supplier",
        "erp.order",
        "erp.order_item",
        "erp.invoice",
        "erp.invoice_item",
        "erp.delivery_note",
        "erp.contract",
        "legacy.row",
    }
    assert profiles["erp.invoice"].classification == DataClass.GOBD
    assert profiles["erp.invoice"].retention_policy_id == "rp-gobd-10y"
    assert profiles["legacy.row"].classification == DataClass.CONFIDENTIAL
    assert profiles["legacy.row"].retention_policy_id == "rp-restricted"
