from __future__ import annotations

import pytest

from suite.ai_control_plane.models import DataClass
from suite.platform.crm_erp_legacy_mapping import (
    CrmErpLegacyMappingEvidenceService,
    CrmErpLegacyMappingManifest,
    default_crm_erp_target_profiles,
)
from suite.platform.crm_erp_object_rules import build_default_crm_erp_object_rule_manifest
from suite.platform.crm_erp_subfeatures import (
    CrmErpSubfeatureArea,
    CrmErpSubfeatureRegistryError,
    build_default_crm_erp_subfeature_registry,
    crm_erp_subfeature_registry_summary,
    default_crm_erp_subfeature_enabled_features,
)
from suite.platform.legacy_sql_discovery import (
    LegacySqlColumnMetadata,
    LegacySqlConnectorKind,
    LegacySqlDiscoveryRequest,
    LegacySqlDiscoveryService,
    LegacySqlSchemaSnapshot,
    LegacySqlTableMetadata,
)
from suite.platform.modules import default_module_registry


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
                columns=(column("KundenId", 1, "int"), column("Name", 2), column("Email", 3)),
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


def mapping_manifest() -> CrmErpLegacyMappingManifest:
    discovery_service = LegacySqlDiscoveryService()
    discovery_manifest = discovery_service.build_discovery_manifest(
        request=discovery_request(),
        snapshot=discovery_snapshot(),
    )
    import_evidence_plan = discovery_service.build_import_evidence_plan(manifest=discovery_manifest)
    return CrmErpLegacyMappingEvidenceService().build_mapping_manifest(
        discovery_manifest=discovery_manifest,
        import_evidence_plan=import_evidence_plan,
    )


def test_default_crm_erp_subfeature_registry_declares_initial_feature_set() -> None:
    registry = build_default_crm_erp_subfeature_registry()
    summary = crm_erp_subfeature_registry_summary(registry)

    assert registry.feature_ids == (
        "crm_erp.crm.accounts",
        "crm_erp.crm.contacts",
        "crm_erp.crm.activities",
        "crm_erp.erp.products",
        "crm_erp.erp.suppliers",
        "crm_erp.erp.orders",
        "crm_erp.erp.invoices",
        "crm_erp.legacy_import.sqlserver",
        "crm_erp.gobd_export",
        "crm_erp.legal_hold",
        "crm_erp.search.keyword",
        "crm_erp.rag_indexing",
        "crm_erp.ai_assist",
    )
    assert summary == {
        "module_id": "crm_erp",
        "registry_version": "crm_erp_subfeatures.v1",
        "feature_count": 13,
        "default_enabled_count": 9,
        "approval_required_count": 5,
        "compliance_relevant_count": 3,
        "manifest_hash": registry.manifest_hash,
    }
    assert registry.manifest_hash.startswith("sha256:")
    assert registry.feature("crm_erp.legacy_import.sqlserver").requires_approval
    assert registry.feature("crm_erp.ai_assist").dependency_feature_ids == ("crm_erp.rag_indexing",)
    assert registry.feature("crm_erp.legal_hold").compliance_relevant


def test_default_module_registry_uses_canonical_crm_erp_subfeature_defaults() -> None:
    module_registry = default_module_registry()
    tenant_state = module_registry.get_tenant_module("tenant-demo", "crm_erp")
    knowledge_base_catalog = module_registry.get_catalog_entry("knowledge_base")

    assert tenant_state.enabled_features == default_crm_erp_subfeature_enabled_features()
    assert tenant_state.enabled_features["crm_erp.crm.accounts"]
    assert tenant_state.enabled_features["crm_erp.erp.invoices"]
    assert tenant_state.enabled_features["crm_erp.legal_hold"]
    assert tenant_state.enabled_features["crm_erp.search.keyword"]
    assert not tenant_state.enabled_features["crm_erp.legacy_import.sqlserver"]
    assert not tenant_state.enabled_features["crm_erp.rag_indexing"]
    assert not tenant_state.enabled_features["crm_erp.ai_assist"]
    assert knowledge_base_catalog.required_migration_versions[-5:] == ("0025", "0026", "0027", "0028", "0029")


def test_crm_erp_subfeature_registry_covers_all_mapping_target_profiles() -> None:
    registry = build_default_crm_erp_subfeature_registry()
    object_rules = build_default_crm_erp_object_rule_manifest()

    for profile in default_crm_erp_target_profiles().values():
        feature = registry.feature(profile.feature_id)
        assert profile.object_type in feature.object_types
        assert profile.classification in feature.data_classes
        assert profile.retention_policy_id in feature.retention_policy_ids

    registry.validate_mapping_manifest(mapping_manifest())
    object_rules.validate_subfeature_registry(registry)


def test_crm_erp_subfeature_registry_rejects_unknown_mapping_feature() -> None:
    registry = build_default_crm_erp_subfeature_registry()
    manifest = mapping_manifest()
    first_decision = manifest.decisions[0].model_copy(update={"feature_id": "crm_erp.crm.ghost"})
    unsafe_manifest = manifest.model_copy(update={"decisions": (first_decision, *manifest.decisions[1:])})

    with pytest.raises(CrmErpSubfeatureRegistryError, match="unknown subfeature"):
        registry.validate_mapping_manifest(unsafe_manifest)


def test_crm_erp_high_risk_subfeatures_keep_approval_and_evidence_requirements() -> None:
    registry = build_default_crm_erp_subfeature_registry()

    legacy_import = registry.feature("crm_erp.legacy_import.sqlserver")
    gobd_export = registry.feature("crm_erp.gobd_export")
    keyword_search = registry.feature("crm_erp.search.keyword")
    rag_indexing = registry.feature("crm_erp.rag_indexing")
    ai_assist = registry.feature("crm_erp.ai_assist")

    assert legacy_import.area == CrmErpSubfeatureArea.LEGACY_IMPORT
    assert legacy_import.requires_approval
    assert "legacy_sql_mapping_manifest" in legacy_import.evidence_required
    assert "compliance_worker" in legacy_import.worker_surfaces

    assert gobd_export.area == CrmErpSubfeatureArea.COMPLIANCE
    assert gobd_export.requires_approval
    assert DataClass.GOBD in gobd_export.data_classes
    assert "rp-export-10y" in gobd_export.retention_policy_ids

    assert keyword_search.area == CrmErpSubfeatureArea.SEARCH
    assert not keyword_search.requires_approval
    assert "authoritative_acl_validation" in keyword_search.evidence_required

    assert rag_indexing.area == CrmErpSubfeatureArea.SEARCH_AI
    assert rag_indexing.requires_approval
    assert "source_resolver_acl_trace" in rag_indexing.evidence_required

    assert ai_assist.area == CrmErpSubfeatureArea.SEARCH_AI
    assert ai_assist.requires_approval
    assert ai_assist.dependency_feature_ids == ("crm_erp.rag_indexing",)
    assert "local_llm_gateway_audit" in ai_assist.evidence_required
