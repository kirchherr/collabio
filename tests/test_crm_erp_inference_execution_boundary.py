from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import DataClass, RiskLevel, TenantPolicy, UserContext
from suite.ai_control_plane.policy import PolicyEngine
from suite.ai_control_plane.registries import InMemoryModelRegistry, InMemoryPromptRegistry
from suite.platform.crm_accounts import InMemoryCrmAccountRepository
from suite.platform.crm_activities import InMemoryCrmActivityRepository, InMemoryCrmNoteRepository
from suite.platform.crm_contacts import InMemoryCrmContactRepository
from suite.platform.crm_erp_authorized_context_contract import build_crm_erp_authorized_context_contract_service
from suite.platform.crm_erp_inference_execution_boundary import (
    CRM_ERP_INFERENCE_EXECUTION_BOUNDARY_RESULT_CONTRACT,
    CrmErpInferenceExecutionBoundaryRequest,
    CrmErpInferenceExecutionBoundaryService,
    build_crm_erp_inference_execution_boundary_service,
)
from suite.platform.crm_erp_prompt_audit_contract import build_crm_erp_prompt_audit_contract_service
from suite.platform.crm_erp_redaction_contract import build_crm_erp_redaction_contract_service
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


def tenant_policy() -> TenantPolicy:
    return TenantPolicy(
        tenant_id="tenant-demo",
        ai_enabled=True,
        rag_enabled=True,
        allowed_model_ids={"mock-summarizer"},
        allowed_data_classes={DataClass.INTERNAL, DataClass.PERSONAL, DataClass.AI_PROMPT},
    )


def build_service() -> tuple[CrmErpInferenceExecutionBoundaryService, InMemoryAuditLogger]:
    audit_logger = InMemoryAuditLogger()
    model_registry = InMemoryModelRegistry.default()
    prompt_registry = InMemoryPromptRegistry.default()
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
        model_registry=model_registry,
        prompt_registry=prompt_registry,
        audit_logger=audit_logger,
    )
    redaction = build_crm_erp_redaction_contract_service(
        prompt_audit_contract_service=prompt_audit,
        audit_logger=audit_logger,
    )
    authorized_context = build_crm_erp_authorized_context_contract_service(
        redaction_contract_service=redaction,
        audit_logger=audit_logger,
    )
    return (
        build_crm_erp_inference_execution_boundary_service(
            authorized_context_contract_service=authorized_context,
            model_registry=model_registry,
            prompt_registry=prompt_registry,
            policy_engine=PolicyEngine(model_registry=model_registry),
            audit_logger=audit_logger,
        ),
        audit_logger,
    )


def test_crm_erp_inference_execution_boundary_is_ready_without_executing_ai() -> None:
    service, audit_logger = build_service()

    response = service.build_boundary(
        request=CrmErpInferenceExecutionBoundaryRequest(
            object_ids=(
                "crm-account-acme-demo",
                "erp-product-standard-widget-demo",
                "crm-account-acme-demo",
            )
        ),
        user_context=user_context(
            readable_object_ids={
                "crm-account-acme-demo",
                "erp-product-standard-widget-demo",
            }
        ),
        tenant_policy=tenant_policy(),
    )

    serialized_response = response.model_dump_json()
    source_resolver_event = audit_logger.events[-6]
    source_citation_event = audit_logger.events[-5]
    prompt_audit_event = audit_logger.events[-4]
    redaction_event = audit_logger.events[-3]
    authorized_context_event = audit_logger.events[-2]
    boundary_event = audit_logger.events[-1]
    assert response.tenant_id == "tenant-demo"
    assert response.module_id == "crm_erp"
    assert response.feature_id == "crm_erp.rag_indexing"
    assert response.endpoint == "/v1/platform/search/crm-erp/inference-execution-boundary"
    assert response.requested_object_ids == ("crm-account-acme-demo", "erp-product-standard-widget-demo")
    assert [citation.source_object_id for citation in response.citations] == [
        "crm-account-acme-demo",
        "erp-product-standard-widget-demo",
    ]
    assert response.authorized_chunk_refs == tuple(
        f"{citation.source_object_id}:{citation.source_version_id}:{citation.source_chunk_id}"
        for citation in response.citations
    )
    assert response.model_id == "mock-summarizer"
    assert response.model_provider == "mock"
    assert response.model_approved_for_rag is True
    assert response.prompt_template_id == "rag_answer_v1"
    assert response.prompt_template_approval_status == "approved"
    assert response.tenant_ai_enabled is True
    assert response.tenant_rag_enabled is True
    assert response.external_ai_enabled is False
    assert response.risk_level == RiskLevel.MEDIUM
    assert response.purpose == "rag"
    assert response.inference_data_classes == ("ai_prompt", "internal", "personal")
    assert "input_hash_required" in response.required_inference_steps
    assert "output_hash_required" in response.required_inference_steps
    assert response.required_event_type == "ai.inference"
    assert response.authorized_context_contract_ready is True
    assert response.policy_authorized is True
    assert response.human_confirmation_required is False
    assert response.inference_execution_boundary_ready is True
    assert response.contract_blocking_reasons == ()
    assert response.inference_execution_boundary_hash.startswith("sha256:")
    assert response.result_contract == CRM_ERP_INFERENCE_EXECUTION_BOUNDARY_RESULT_CONTRACT
    assert response.local_llm_gateway_required is True
    assert response.tool_calls_allowed is False
    assert response.provider_call_executed is False
    assert response.answer_generation_executed is False
    assert response.content_included is False
    assert response.redacted_content_included is False
    assert response.context_body_created is False
    assert response.prompt_body_included is False
    assert response.output_body_included is False
    assert response.ai_used is False
    assert response.rag_context_created is False
    assert response.destructive_actions_allowed is False
    assert response.external_side_effect_allowed is False
    assert "index_text" not in serialized_response
    assert "snippet" not in serialized_response
    assert "Standard Widget" not in serialized_response
    assert "Question:" not in serialized_response
    assert "Authorized source blocks:" not in serialized_response

    assert source_resolver_event.event_type == "crm_erp.source_resolver_acl_trace"
    assert source_citation_event.event_type == "crm_erp.source_citation_contract"
    assert prompt_audit_event.event_type == "crm_erp.prompt_audit_contract"
    assert redaction_event.event_type == "crm_erp.redaction_contract"
    assert authorized_context_event.event_type == "crm_erp.authorized_context_contract"
    assert boundary_event.event_type == "crm_erp.inference_execution_boundary"
    assert boundary_event.event_id == response.audit_event_id
    assert boundary_event.model_id == "mock-summarizer"
    assert boundary_event.prompt_template_id == "rag_answer_v1"
    assert boundary_event.source_object_ids == ["crm-account-acme-demo", "erp-product-standard-widget-demo"]
    assert boundary_event.input_hash is None
    assert boundary_event.output_hash is None
    assert boundary_event.metadata["result_contract"] == CRM_ERP_INFERENCE_EXECUTION_BOUNDARY_RESULT_CONTRACT
    assert boundary_event.metadata["required_event_type"] == "ai.inference"
    assert boundary_event.metadata["inference_execution_boundary_hash"] == response.inference_execution_boundary_hash
    assert boundary_event.metadata["authorized_context_contract_hash"] == response.authorized_context_contract_hash
    assert boundary_event.metadata["source_resolver_audit_event_id"] == source_resolver_event.event_id
    assert boundary_event.metadata["source_citation_contract_audit_event_id"] == source_citation_event.event_id
    assert boundary_event.metadata["prompt_audit_contract_audit_event_id"] == prompt_audit_event.event_id
    assert boundary_event.metadata["redaction_contract_audit_event_id"] == redaction_event.event_id
    assert boundary_event.metadata["authorized_context_contract_audit_event_id"] == authorized_context_event.event_id
    assert boundary_event.metadata["authorized_chunk_count"] == 2
    assert boundary_event.metadata["policy_authorized"] is True
    assert boundary_event.metadata["human_confirmation_required"] is False
    assert boundary_event.metadata["contract_blocking_reasons"] == ()
    assert boundary_event.metadata["provider_call_executed"] is False
    assert boundary_event.metadata["answer_generation_executed"] is False
    assert boundary_event.metadata["context_body_created"] is False
    assert boundary_event.metadata["prompt_body_included"] is False
    assert boundary_event.metadata["output_body_included"] is False
    assert boundary_event.metadata["ai_used"] is False
    assert boundary_event.metadata["rag_context_created"] is False


def test_crm_erp_inference_execution_boundary_blocks_gobd_without_policy_allowance() -> None:
    service, audit_logger = build_service()

    response = service.build_boundary(
        request=CrmErpInferenceExecutionBoundaryRequest(object_ids=("erp-invoice-item-acme-widget-demo",)),
        user_context=user_context(readable_object_ids={"erp-invoice-item-acme-widget-demo"}),
        tenant_policy=tenant_policy(),
    )

    boundary_event = audit_logger.events[-1]
    assert response.authorized_context_contract_ready is True
    assert response.policy_authorized is False
    assert response.inference_execution_boundary_ready is False
    assert response.inference_data_classes == ("ai_prompt", "gobd")
    assert response.contract_blocking_reasons == ("tenant_policy_blocks_inference_data_classes",)
    assert response.provider_call_executed is False
    assert response.answer_generation_executed is False
    assert boundary_event.event_type == "crm_erp.inference_execution_boundary"
    assert boundary_event.metadata["policy_authorized"] is False
    assert boundary_event.metadata["contract_blocking_reasons"] == ("tenant_policy_blocks_inference_data_classes",)
    assert boundary_event.input_hash is None
    assert boundary_event.output_hash is None


def test_crm_erp_inference_execution_boundary_requires_confirmation_for_high_risk() -> None:
    service, _audit_logger = build_service()

    blocked = service.build_boundary(
        request=CrmErpInferenceExecutionBoundaryRequest(
            object_ids=("erp-product-standard-widget-demo",),
            risk_level=RiskLevel.HIGH,
        ),
        user_context=user_context(readable_object_ids={"erp-product-standard-widget-demo"}),
        tenant_policy=tenant_policy(),
    )
    ready = service.build_boundary(
        request=CrmErpInferenceExecutionBoundaryRequest(
            object_ids=("erp-product-standard-widget-demo",),
            risk_level=RiskLevel.HIGH,
            human_confirmation_ref="approval:crm-erp-rag-high-risk-demo",
        ),
        user_context=user_context(readable_object_ids={"erp-product-standard-widget-demo"}),
        tenant_policy=tenant_policy(),
    )

    assert blocked.human_confirmation_required is True
    assert blocked.human_confirmation_ref is None
    assert blocked.inference_execution_boundary_ready is False
    assert blocked.contract_blocking_reasons == ("human_confirmation_required",)
    assert ready.human_confirmation_required is True
    assert ready.human_confirmation_ref == "approval:crm-erp-rag-high-risk-demo"
    assert ready.inference_execution_boundary_ready is True
    assert ready.contract_blocking_reasons == ()
    assert ready.provider_call_executed is False
    assert ready.answer_generation_executed is False
