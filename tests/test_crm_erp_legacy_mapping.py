from __future__ import annotations

from datetime import UTC, datetime

import pytest

from suite.ai_control_plane.models import DataClass
from suite.platform.crm_erp_legacy_mapping import (
    CRM_ERP_LEGACY_IMPORT_DRY_RUN_PLAN_SCHEMA_VERSION,
    CRM_ERP_LEGACY_STAGING_METADATA_PLAN_SCHEMA_VERSION,
    CRM_ERP_LEGACY_STAGING_METADATA_PROFILE_OBJECT_TYPE,
    CrmErpLegacyChecksumStrategy,
    CrmErpLegacyImportDryRunStatus,
    CrmErpLegacyImportReadinessStatus,
    CrmErpLegacyMappingAction,
    CrmErpLegacyMappingEvidenceError,
    CrmErpLegacyMappingEvidenceService,
    CrmErpLegacyMappingOverride,
    CrmErpLegacyRowCountStrategy,
    build_crm_erp_legacy_import_dry_run_plan,
    build_crm_erp_legacy_import_readiness_evidence,
    build_crm_erp_legacy_staging_metadata_plan,
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
from suite.platform.persistent_metadata import (
    PERSISTENT_OBJECT_METADATA_SCHEMA_VERSION,
    PERSISTENT_OBJECT_REQUIRED_FIELDS,
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


def test_crm_erp_legacy_staging_metadata_plan_derives_persistent_profiles() -> None:
    manifest, plan = discovery_manifest_and_plan()
    service = CrmErpLegacyMappingEvidenceService()
    mapping = service.build_mapping_manifest(discovery_manifest=manifest, import_evidence_plan=plan)

    staging_plan = build_crm_erp_legacy_staging_metadata_plan(
        discovery_manifest=manifest,
        mapping_manifest=mapping,
        captured_at_utc=datetime(2026, 6, 20, 10, tzinfo=UTC),
    )

    assert staging_plan.schema_version == CRM_ERP_LEGACY_STAGING_METADATA_PLAN_SCHEMA_VERSION
    assert staging_plan.metadata_contract == PERSISTENT_OBJECT_METADATA_SCHEMA_VERSION
    assert staging_plan.required_metadata_fields == PERSISTENT_OBJECT_REQUIRED_FIELDS
    assert staging_plan.profile_count == 2
    assert staging_plan.manifest_hash.startswith("sha256:")
    assert staging_plan.dry_run_required
    assert not staging_plan.import_write_allowed
    assert not staging_plan.raw_data_import_allowed
    assert not staging_plan.destructive_actions_allowed

    profiles_by_table = {profile.source_table_ref: profile for profile in staging_plan.profiles}
    kunden = profiles_by_table["dbo.Kunden"]
    freie_tabelle = profiles_by_table["dbo.FreieTabelle"]

    assert kunden.object_type == CRM_ERP_LEGACY_STAGING_METADATA_PROFILE_OBJECT_TYPE
    assert kunden.target_object_type == "crm.account"
    assert kunden.classification == DataClass.PERSONAL
    assert kunden.retention_policy_id == "rp-standard"
    assert kunden.lifecycle_state == "staged"
    assert kunden.kms_key_ref == "kms:tenant-1:personal:legacy-sql-staging"
    assert kunden.source_system == "legacy_sql"
    assert kunden.schema_version == "crm_erp_legacy_staging_metadata_profile.v1"
    assert "{source_row_hash}" in kunden.row_object_id_template
    assert kunden.metadata_field_sources["object_id"] == "legacy_row_id_template"
    assert set(PERSISTENT_OBJECT_REQUIRED_FIELDS).issubset(kunden.metadata_field_sources)

    assert freie_tabelle.target_object_type == "legacy.row"
    assert freie_tabelle.classification == DataClass.CONFIDENTIAL
    assert freie_tabelle.retention_policy_id == "rp-restricted"
    assert freie_tabelle.quarantine_required
    assert freie_tabelle.lifecycle_state == "quarantined"
    assert not freie_tabelle.import_write_allowed

    plan_json = staging_plan.model_dump_json()
    assert "Email" not in plan_json
    assert "KundenId" not in plan_json
    assert "sample" not in plan_json.lower()


def test_crm_erp_legacy_staging_metadata_plan_rejects_broken_mapping_chain() -> None:
    manifest, plan = discovery_manifest_and_plan()
    service = CrmErpLegacyMappingEvidenceService()
    mapping = service.build_mapping_manifest(
        discovery_manifest=manifest,
        import_evidence_plan=plan,
    ).model_copy(update={"discovery_manifest_hash": "sha256:" + "9" * 64})

    with pytest.raises(CrmErpLegacyMappingEvidenceError, match="does not reference discovery manifest"):
        build_crm_erp_legacy_staging_metadata_plan(discovery_manifest=manifest, mapping_manifest=mapping)


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


def test_crm_erp_legacy_import_dry_run_plan_binds_ready_evidence_to_staging_profiles() -> None:
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
    staging_plan = build_crm_erp_legacy_staging_metadata_plan(
        discovery_manifest=manifest,
        mapping_manifest=mapping,
        captured_at_utc=datetime(2026, 6, 20, 10, tzinfo=UTC),
    )

    dry_run_plan = build_crm_erp_legacy_import_dry_run_plan(
        discovery_manifest=manifest,
        mapping_manifest=mapping,
        readiness_evidence=readiness,
        staging_metadata_plan=staging_plan,
    )

    assert dry_run_plan.schema_version == CRM_ERP_LEGACY_IMPORT_DRY_RUN_PLAN_SCHEMA_VERSION
    assert dry_run_plan.status == CrmErpLegacyImportDryRunStatus.READY_FOR_METADATA_DRY_RUN
    assert dry_run_plan.dry_run_execution_allowed
    assert dry_run_plan.discovery_manifest_hash == manifest.manifest_hash
    assert dry_run_plan.mapping_manifest_hash == mapping.manifest_hash
    assert dry_run_plan.readiness_evidence_hash == readiness.evidence_hash
    assert dry_run_plan.staging_metadata_plan_hash == staging_plan.manifest_hash
    assert dry_run_plan.table_count == 2
    assert dry_run_plan.planned_table_count == 2
    assert dry_run_plan.estimated_row_count_total == 15
    assert dry_run_plan.row_count_strategy == CrmErpLegacyRowCountStrategy.EXACT_READ_ONLY_COUNT_QUERY
    assert dry_run_plan.checksum_strategy == CrmErpLegacyChecksumStrategy.SHA256_CANONICAL_ROW_HASH_MANIFEST
    assert dry_run_plan.required_audit_event_types == (
        "legacy_sql.import_dry_run.started",
        "legacy_sql.import_dry_run.table_validated",
        "legacy_sql.import_dry_run.completed",
        "legacy_sql.import_dry_run.blocked",
    )
    assert not dry_run_plan.blocking_reasons
    assert not dry_run_plan.import_write_allowed
    assert not dry_run_plan.raw_data_import_allowed
    assert not dry_run_plan.destructive_actions_allowed

    profiles_by_table = {profile.source_table_ref: profile for profile in staging_plan.profiles}
    table_plans_by_table = {table_plan.source_table_ref: table_plan for table_plan in dry_run_plan.table_plans}
    assert table_plans_by_table["dbo.Kunden"].staging_profile_object_id == profiles_by_table["dbo.Kunden"].object_id
    assert table_plans_by_table["dbo.Kunden"].target_object_type == "crm.account"
    assert table_plans_by_table["dbo.FreieTabelle"].target_object_type == "crm.contact"
    assert all(table_plan.row_count_required for table_plan in dry_run_plan.table_plans)
    assert all(table_plan.checksum_required for table_plan in dry_run_plan.table_plans)
    assert all(table_plan.manifest_hash_required for table_plan in dry_run_plan.table_plans)

    plan_json = dry_run_plan.model_dump_json()
    assert "Email" not in plan_json
    assert "KundenId" not in plan_json
    assert "sample" not in plan_json.lower()


def test_crm_erp_legacy_import_dry_run_plan_blocks_when_readiness_is_not_clean() -> None:
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

    dry_run_plan = build_crm_erp_legacy_import_dry_run_plan(
        discovery_manifest=manifest,
        mapping_manifest=mapping,
        readiness_evidence=readiness,
        staging_metadata_plan=staging_plan,
    )

    assert dry_run_plan.status == CrmErpLegacyImportDryRunStatus.BLOCKED_BY_READINESS
    assert not dry_run_plan.dry_run_execution_allowed
    assert "quarantine_tables_require_manual_mapping" in dry_run_plan.blocking_reasons
    assert "legacy_row_fallbacks_require_mapping_review" in dry_run_plan.blocking_reasons
    assert not dry_run_plan.import_write_allowed
    assert not dry_run_plan.raw_data_import_allowed


def test_crm_erp_legacy_import_dry_run_plan_rejects_broken_staging_chain() -> None:
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
    ).model_copy(update={"manifest_hash": "sha256:" + "9" * 64})

    with pytest.raises(CrmErpLegacyMappingEvidenceError, match="staging metadata plan hash invalid"):
        build_crm_erp_legacy_import_dry_run_plan(
            discovery_manifest=manifest,
            mapping_manifest=mapping,
            readiness_evidence=readiness,
            staging_metadata_plan=staging_plan,
        )


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
