import pytest
from pydantic import ValidationError

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import DataClass, UserContext
from suite.platform.erp_products import (
    CRM_ERP_MODULE_ID,
    ERP_PRODUCT_OBJECT_TYPE,
    ERP_PRODUCTS_FEATURE_ID,
    ErpProductRecord,
    ErpProductService,
    InMemoryErpProductRepository,
)
from suite.platform.persistent_metadata import (
    PERSISTENT_OBJECT_METADATA_SCHEMA_VERSION,
    PERSISTENT_OBJECT_REQUIRED_FIELDS,
)


def test_erp_product_records_require_internal_compliance_metadata() -> None:
    product = InMemoryErpProductRepository.demo().list_products(tenant_id="tenant-demo")[0]

    assert product.object_type == ERP_PRODUCT_OBJECT_TYPE
    assert product.data_classification == DataClass.INTERNAL
    assert product.retention_policy_id == "rp-standard"
    assert product.legal_hold_state == "none"
    assert product.kms_key_ref.startswith("kms:")
    assert product.audit_chain_ref.startswith("audit:")
    assert product.source_system == "native"
    assert product.schema_version == "erp_product.v1"


def test_erp_product_records_reject_wrong_object_type_or_personal_classification() -> None:
    values = {
        "tenant_id": "tenant-demo",
        "object_id": "erp-product-invalid",
        "owner_principal_id": "user-demo",
        "created_by": "system",
        "created_at_utc": "2026-06-11T13:00:00Z",
        "updated_at_utc": "2026-06-11T13:00:00Z",
        "kms_key_ref": "kms:tenant-demo:erp-product",
        "audit_chain_ref": "audit:erp-product-invalid",
        "product_number": "ERP-P-INVALID",
        "display_name": "Invalid Product",
    }

    with pytest.raises(ValidationError, match=r"erp\.product"):
        ErpProductRecord.model_validate({**values, "object_type": "crm.account"})

    with pytest.raises(ValidationError, match="internal"):
        ErpProductRecord.model_validate({**values, "data_classification": "personal"})


def test_erp_product_service_returns_only_current_tenant_and_audits_metadata_only() -> None:
    audit_logger = InMemoryAuditLogger()
    service = ErpProductService(
        repository=InMemoryErpProductRepository.demo(),
        audit_logger=audit_logger,
    )
    user_context = UserContext(
        tenant_id="tenant-demo",
        user_id="user-demo",
        role_ids={"knowledge-worker"},
        readable_object_ids={"erp-product-standard-widget-demo", "erp-product-service-plan-demo"},
    )

    response = service.list_products(user_context=user_context)

    assert response.tenant_id == "tenant-demo"
    assert response.module_id == CRM_ERP_MODULE_ID
    assert response.feature_id == ERP_PRODUCTS_FEATURE_ID
    assert [product.display_name for product in response.products] == ["Service Plan", "Standard Widget"]
    assert all(product.object_type == ERP_PRODUCT_OBJECT_TYPE for product in response.products)
    assert {product.data_classification for product in response.products} == {DataClass.INTERNAL}
    assert all(product.access_checked for product in response.products)
    assert "Other Tenant Product" not in {product.display_name for product in response.products}

    event = audit_logger.events[-1]
    assert response.audit_event_id == event.event_id
    assert event.tenant_id == "tenant-demo"
    assert event.event_type == "erp.product.list"
    assert event.input_hash is None
    assert event.output_hash is None
    assert event.source_object_ids == ["erp-product-service-plan-demo", "erp-product-standard-widget-demo"]
    assert event.metadata == {
        "feature_id": ERP_PRODUCTS_FEATURE_ID,
        "module_id": CRM_ERP_MODULE_ID,
        "object_type": ERP_PRODUCT_OBJECT_TYPE,
        "candidate_count": 2,
        "result_contract": "metadata_only",
        "persistent_metadata_contract": PERSISTENT_OBJECT_METADATA_SCHEMA_VERSION,
        "persistent_metadata_required_fields": PERSISTENT_OBJECT_REQUIRED_FIELDS,
        "result_count": 2,
    }


def test_erp_product_service_filters_unreadable_product_objects() -> None:
    audit_logger = InMemoryAuditLogger()
    service = ErpProductService(
        repository=InMemoryErpProductRepository.demo(),
        audit_logger=audit_logger,
    )
    user_context = UserContext(
        tenant_id="tenant-demo",
        user_id="user-demo",
        role_ids={"knowledge-worker"},
        readable_object_ids={"erp-product-service-plan-demo"},
    )

    response = service.list_products(user_context=user_context)

    assert [product.object_id for product in response.products] == ["erp-product-service-plan-demo"]
    event = audit_logger.events[-1]
    assert event.source_object_ids == ["erp-product-service-plan-demo"]
    assert event.metadata["candidate_count"] == 2
    assert event.metadata["result_count"] == 1
