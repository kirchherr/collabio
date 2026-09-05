import pytest
from pydantic import ValidationError

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import DataClass, UserContext
from suite.platform.erp_suppliers import (
    CRM_ERP_MODULE_ID,
    ERP_SUPPLIER_OBJECT_TYPE,
    ERP_SUPPLIERS_FEATURE_ID,
    ErpSupplierRecord,
    ErpSupplierService,
    InMemoryErpSupplierRepository,
)
from suite.platform.persistent_metadata import (
    PERSISTENT_OBJECT_METADATA_SCHEMA_VERSION,
    PERSISTENT_OBJECT_REQUIRED_FIELDS,
)


def test_erp_supplier_records_require_personal_compliance_metadata() -> None:
    supplier = InMemoryErpSupplierRepository.demo().list_suppliers(tenant_id="tenant-demo")[0]

    assert supplier.object_type == ERP_SUPPLIER_OBJECT_TYPE
    assert supplier.data_classification == DataClass.PERSONAL
    assert supplier.retention_policy_id == "rp-standard"
    assert supplier.legal_hold_state == "none"
    assert supplier.kms_key_ref.startswith("kms:")
    assert supplier.audit_chain_ref.startswith("audit:")
    assert supplier.source_system == "native"
    assert supplier.schema_version == "erp_supplier.v1"


def test_erp_supplier_records_reject_wrong_object_type_or_internal_classification() -> None:
    values = {
        "tenant_id": "tenant-demo",
        "object_id": "erp-supplier-invalid",
        "owner_principal_id": "user-demo",
        "created_by": "system",
        "created_at_utc": "2026-06-11T14:00:00Z",
        "updated_at_utc": "2026-06-11T14:00:00Z",
        "kms_key_ref": "kms:tenant-demo:erp-supplier",
        "audit_chain_ref": "audit:erp-supplier-invalid",
        "supplier_number": "ERP-S-INVALID",
        "display_name": "Invalid Supplier",
    }

    with pytest.raises(ValidationError, match=r"erp\.supplier"):
        ErpSupplierRecord.model_validate({**values, "object_type": "erp.product"})

    with pytest.raises(ValidationError, match="personal"):
        ErpSupplierRecord.model_validate({**values, "data_classification": "internal"})

    with pytest.raises(ValidationError, match="ISO 3166"):
        ErpSupplierRecord.model_validate({**values, "country_code": "de"})


def test_erp_supplier_service_returns_only_current_tenant_and_audits_metadata_only() -> None:
    audit_logger = InMemoryAuditLogger()
    service = ErpSupplierService(
        repository=InMemoryErpSupplierRepository.demo(),
        audit_logger=audit_logger,
    )
    user_context = UserContext(
        tenant_id="tenant-demo",
        user_id="user-demo",
        role_ids={"knowledge-worker"},
        readable_object_ids={"erp-supplier-contoso-demo", "erp-supplier-fabrikam-demo"},
    )

    response = service.list_suppliers(user_context=user_context)

    assert response.tenant_id == "tenant-demo"
    assert response.module_id == CRM_ERP_MODULE_ID
    assert response.feature_id == ERP_SUPPLIERS_FEATURE_ID
    assert [supplier.display_name for supplier in response.suppliers] == ["Contoso Components", "Fabrikam Services"]
    assert all(supplier.object_type == ERP_SUPPLIER_OBJECT_TYPE for supplier in response.suppliers)
    assert {supplier.data_classification for supplier in response.suppliers} == {DataClass.PERSONAL}
    assert all(supplier.retention_policy_id == "rp-standard" for supplier in response.suppliers)
    assert all(supplier.access_checked for supplier in response.suppliers)
    assert "Other Tenant Supplier" not in {supplier.display_name for supplier in response.suppliers}

    event = audit_logger.events[-1]
    assert response.audit_event_id == event.event_id
    assert event.tenant_id == "tenant-demo"
    assert event.event_type == "erp.supplier.list"
    assert event.input_hash is None
    assert event.output_hash is None
    assert event.source_object_ids == ["erp-supplier-contoso-demo", "erp-supplier-fabrikam-demo"]
    assert event.metadata == {
        "feature_id": ERP_SUPPLIERS_FEATURE_ID,
        "module_id": CRM_ERP_MODULE_ID,
        "object_type": ERP_SUPPLIER_OBJECT_TYPE,
        "candidate_count": 2,
        "result_contract": "metadata_only",
        "persistent_metadata_contract": PERSISTENT_OBJECT_METADATA_SCHEMA_VERSION,
        "persistent_metadata_required_fields": PERSISTENT_OBJECT_REQUIRED_FIELDS,
        "result_count": 2,
    }


def test_erp_supplier_service_filters_unreadable_supplier_objects() -> None:
    audit_logger = InMemoryAuditLogger()
    service = ErpSupplierService(
        repository=InMemoryErpSupplierRepository.demo(),
        audit_logger=audit_logger,
    )
    user_context = UserContext(
        tenant_id="tenant-demo",
        user_id="user-demo",
        role_ids={"knowledge-worker"},
        readable_object_ids={"erp-supplier-fabrikam-demo"},
    )

    response = service.list_suppliers(user_context=user_context)

    assert [supplier.object_id for supplier in response.suppliers] == ["erp-supplier-fabrikam-demo"]
    event = audit_logger.events[-1]
    assert event.source_object_ids == ["erp-supplier-fabrikam-demo"]
    assert event.metadata["candidate_count"] == 2
    assert event.metadata["result_count"] == 1
