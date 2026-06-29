from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import UserContext
from suite.ai_control_plane.registries import InMemoryModelRegistry, InMemoryPromptRegistry
from suite.platform.crm_accounts import InMemoryCrmAccountRepository
from suite.platform.crm_activities import InMemoryCrmActivityRepository, InMemoryCrmNoteRepository
from suite.platform.crm_contacts import InMemoryCrmContactRepository
from suite.platform.crm_erp_prompt_audit_contract import build_crm_erp_prompt_audit_contract_service
from suite.platform.crm_erp_redaction_contract import (
    CRM_ERP_REDACTION_CONTRACT_RESULT_CONTRACT,
    CrmErpRedactionContractRequest,
    CrmErpRedactionContractService,
    build_crm_erp_redaction_contract_service,
)
from suite.platform.crm_erp_source_citations import build_crm_erp_source_citation_contract_service
from suite.platform.crm_erp_source_resolver import build_crm_erp_source_resolver_acl_trace_service
from suite.platform.erp_products import InMemoryErpProductRepository
from suite.platform.erp_sales import (
    InMemoryErpInvoiceItemRepository,
    InMemoryErpInvoiceRepository,
    InMemoryErpOrderItemRepository,
    InMemoryErpOrderRepository,
)
from suite.platform.erp_suppliers import InMemoryErpSupplierRepository


def user_context(*, readable_object_ids: set[str]) -> UserContext:
    return UserContext(
        tenant_id="tenant-demo",
        user_id="user-demo",
        role_ids={"knowledge-worker"},
        readable_object_ids=readable_object_ids,
    )


def build_service() -> tuple[CrmErpRedactionContractService, InMemoryAuditLogger]:
    audit_logger = InMemoryAuditLogger()
    source_resolver = build_crm_erp_source_resolver_acl_trace_service(
        account_repository=InMemoryCrmAccountRepository.demo(),
        contact_repository=InMemoryCrmContactRepository.demo(),
        activity_repository=InMemoryCrmActivityRepository.demo(),
        note_repository=InMemoryCrmNoteRepository.demo(),
        product_repository=InMemoryErpProductRepository.demo(),
        supplier_repository=InMemoryErpSupplierRepository.demo(),
        order_repository=InMemoryErpOrderRepository.demo(),
        invoice_repository=InMemoryErpInvoiceRepository.demo(),
        order_item_repository=InMemoryErpOrderItemRepository.demo(),
        invoice_item_repository=InMemoryErpInvoiceItemRepository.demo(),
        audit_logger=audit_logger,
    )
    source_citations = build_crm_erp_source_citation_contract_service(
        source_resolver_acl_trace_service=source_resolver,
        audit_logger=audit_logger,
    )
    prompt_audit = build_crm_erp_prompt_audit_contract_service(
        source_citation_contract_service=source_citations,
        model_registry=InMemoryModelRegistry.default(),
        prompt_registry=InMemoryPromptRegistry.default(),
        audit_logger=audit_logger,
    )
    return (
        build_crm_erp_redaction_contract_service(
            prompt_audit_contract_service=prompt_audit,
            audit_logger=audit_logger,
        ),
        audit_logger,
    )


def test_crm_erp_redaction_contract_defines_metadata_only_redaction_boundary_without_context() -> None:
    service, audit_logger = build_service()

    response = service.build_contract(
        request=CrmErpRedactionContractRequest(
            object_ids=(
                "crm-account-acme-demo",
                "erp-order-item-acme-widget-demo",
                "erp-supplier-contoso-demo",
                "erp-product-other-tenant",
                "crm-account-acme-demo",
            )
        ),
        user_context=user_context(
            readable_object_ids={
                "crm-account-acme-demo",
                "erp-order-item-acme-widget-demo",
            }
        ),
    )

    serialized_response = response.model_dump_json()
    source_resolver_event = audit_logger.events[-4]
    source_citation_event = audit_logger.events[-3]
    prompt_audit_event = audit_logger.events[-2]
    redaction_event = audit_logger.events[-1]
    assert response.tenant_id == "tenant-demo"
    assert response.module_id == "crm_erp"
    assert response.feature_id == "crm_erp.rag_indexing"
    assert response.endpoint == "/v1/platform/search/crm-erp/redaction-contract"
    assert response.requested_object_ids == (
        "crm-account-acme-demo",
        "erp-order-item-acme-widget-demo",
        "erp-supplier-contoso-demo",
        "erp-product-other-tenant",
    )
    assert [citation.source_object_id for citation in response.citations] == [
        "crm-account-acme-demo",
        "erp-order-item-acme-widget-demo",
    ]
    assert response.redaction_policy_id == "redaction-policy:crm-erp-rag-v1"
    assert "classification_aware_redaction_required" in response.required_redaction_steps
    assert "redacted_context_hash_required" in response.required_redaction_steps
    assert response.covered_source_data_classes == ("gobd", "personal")
    assert response.prompt_audit_contract_ready is False
    assert response.redaction_contract_ready is False
    assert response.contract_blocking_reasons == ("prompt_audit_contract_not_ready",)
    assert response.source_resolver_audit_event_id == source_resolver_event.event_id
    assert response.source_citation_contract_audit_event_id == source_citation_event.event_id
    assert response.prompt_audit_contract_audit_event_id == prompt_audit_event.event_id
    assert response.audit_event_id == redaction_event.event_id
    assert response.redaction_contract_hash.startswith("sha256:")
    assert response.prompt_audit_contract_hash.startswith("sha256:")
    assert response.result_contract == CRM_ERP_REDACTION_CONTRACT_RESULT_CONTRACT
    assert response.content_included is False
    assert response.redacted_content_included is False
    assert response.prompt_body_included is False
    assert response.output_body_included is False
    assert response.ai_used is False
    assert response.rag_context_created is False
    assert response.destructive_actions_allowed is False
    assert response.external_side_effect_allowed is False
    assert "index_text" not in serialized_response
    assert "snippet" not in serialized_response
    assert "Standard Widget" not in serialized_response
    assert "Contoso procurement desk" not in serialized_response
    assert "Question:" not in serialized_response
    assert "Authorized source blocks:" not in serialized_response

    assert source_resolver_event.event_type == "crm_erp.source_resolver_acl_trace"
    assert source_citation_event.event_type == "crm_erp.source_citation_contract"
    assert prompt_audit_event.event_type == "crm_erp.prompt_audit_contract"
    assert redaction_event.event_type == "crm_erp.redaction_contract"
    assert redaction_event.model_id == "mock-summarizer"
    assert redaction_event.prompt_template_id == "rag_answer_v1"
    assert redaction_event.source_object_ids == ["crm-account-acme-demo", "erp-order-item-acme-widget-demo"]
    assert redaction_event.input_hash is None
    assert redaction_event.output_hash is None
    assert redaction_event.metadata["result_contract"] == CRM_ERP_REDACTION_CONTRACT_RESULT_CONTRACT
    assert redaction_event.metadata["redaction_policy_id"] == "redaction-policy:crm-erp-rag-v1"
    assert redaction_event.metadata["redaction_contract_hash"] == response.redaction_contract_hash
    assert redaction_event.metadata["prompt_audit_contract_hash"] == response.prompt_audit_contract_hash
    assert redaction_event.metadata["source_resolver_audit_event_id"] == source_resolver_event.event_id
    assert redaction_event.metadata["source_citation_contract_audit_event_id"] == source_citation_event.event_id
    assert redaction_event.metadata["prompt_audit_contract_audit_event_id"] == prompt_audit_event.event_id
    assert redaction_event.metadata["citation_count"] == 2
    assert redaction_event.metadata["covered_source_data_classes"] == ("gobd", "personal")
    assert redaction_event.metadata["contract_blocking_reasons"] == ("prompt_audit_contract_not_ready",)
    assert redaction_event.metadata["content_included"] is False
    assert redaction_event.metadata["redacted_content_included"] is False
    assert redaction_event.metadata["prompt_body_included"] is False
    assert redaction_event.metadata["output_body_included"] is False
    assert redaction_event.metadata["ai_used"] is False
    assert redaction_event.metadata["rag_context_created"] is False


def test_crm_erp_redaction_contract_ready_when_prompt_audit_and_authorized_citations_exist() -> None:
    service, _audit_logger = build_service()

    response = service.build_contract(
        request=CrmErpRedactionContractRequest(
            object_ids=("erp-invoice-item-acme-widget-demo", "erp-invoice-item-acme-widget-demo")
        ),
        user_context=user_context(readable_object_ids={"erp-invoice-item-acme-widget-demo"}),
    )

    assert response.requested_object_ids == ("erp-invoice-item-acme-widget-demo",)
    assert [citation.source_object_id for citation in response.citations] == ["erp-invoice-item-acme-widget-demo"]
    assert response.prompt_audit_contract_ready is True
    assert response.redaction_contract_ready is True
    assert response.contract_blocking_reasons == ()
