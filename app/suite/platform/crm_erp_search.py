from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import DataClass, UserContext
from suite.platform.crm_accounts import CRM_ERP_MODULE_ID, CrmAccountRecord, CrmAccountRepository
from suite.platform.crm_activities import (
    CrmActivityRecord,
    CrmActivityRepository,
    CrmNoteRecord,
    CrmNoteRepository,
)
from suite.platform.crm_contacts import CrmContactRecord, CrmContactRepository
from suite.platform.erp_products import ErpProductRecord, ErpProductRepository
from suite.platform.erp_sales import (
    ErpInvoiceItemRecord,
    ErpInvoiceItemRepository,
    ErpInvoiceRecord,
    ErpInvoiceRepository,
    ErpOrderItemRecord,
    ErpOrderItemRepository,
    ErpOrderRecord,
    ErpOrderRepository,
)
from suite.platform.erp_suppliers import ErpSupplierRecord, ErpSupplierRepository
from suite.rag.repositories import ReadableObjectAclAuthorizer
from suite.search.keyword import InMemoryKeywordIndex, KeywordIndexedChunk, KeywordSearchService, keyword_metadata
from suite.search.models import SEARCH_POLICY_ID, KeywordSearchCandidate, KeywordSearchQuery

CRM_ERP_SEARCH_FEATURE_ID = "crm_erp.search.keyword"
CRM_ERP_SEARCH_RESULT_CONTRACT = "candidate_only_metadata_only_acl_checked"
DEFAULT_CRM_ERP_SEARCH_TENANT_IDS = ("tenant-demo", "tenant-other")


class CrmErpSearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_id: str = CRM_ERP_MODULE_ID
    feature_id: str = CRM_ERP_SEARCH_FEATURE_ID
    candidates: list[KeywordSearchCandidate]
    search_policy_id: str = SEARCH_POLICY_ID
    audit_event_id: str
    result_contract: str = CRM_ERP_SEARCH_RESULT_CONTRACT
    ai_used: bool = False
    rag_context_created: bool = False
    content_included: bool = False


class SearchableBusinessRecord(Protocol):
    tenant_id: str
    object_id: str
    object_type: str
    data_classification: DataClass
    retention_policy_id: str
    legal_hold_state: str
    schema_version: str


class CrmErpSearchService:
    def __init__(self, *, keyword_search_service: KeywordSearchService) -> None:
        self.keyword_search_service = keyword_search_service

    def search(self, *, query: KeywordSearchQuery, user_context: UserContext) -> CrmErpSearchResponse:
        keyword_response = self.keyword_search_service.search(query=query, user_context=user_context)
        return CrmErpSearchResponse(
            tenant_id=user_context.tenant_id,
            candidates=keyword_response.candidates,
            audit_event_id=keyword_response.audit_event_id,
            search_policy_id=keyword_response.search_policy_id,
        )


def build_crm_erp_search_service(
    *,
    account_repository: CrmAccountRepository,
    contact_repository: CrmContactRepository,
    activity_repository: CrmActivityRepository,
    note_repository: CrmNoteRepository,
    product_repository: ErpProductRepository,
    supplier_repository: ErpSupplierRepository,
    order_repository: ErpOrderRepository,
    invoice_repository: ErpInvoiceRepository,
    order_item_repository: ErpOrderItemRepository,
    invoice_item_repository: ErpInvoiceItemRepository,
    audit_logger: InMemoryAuditLogger,
    tenant_ids: Sequence[str] = DEFAULT_CRM_ERP_SEARCH_TENANT_IDS,
) -> CrmErpSearchService:
    index = InMemoryKeywordIndex(
        records=build_crm_erp_search_records(
            account_repository=account_repository,
            contact_repository=contact_repository,
            activity_repository=activity_repository,
            note_repository=note_repository,
            product_repository=product_repository,
            supplier_repository=supplier_repository,
            order_repository=order_repository,
            invoice_repository=invoice_repository,
            order_item_repository=order_item_repository,
            invoice_item_repository=invoice_item_repository,
            tenant_ids=tenant_ids,
        )
    )
    keyword_service = KeywordSearchService(
        index=index,
        acl_authorizer=ReadableObjectAclAuthorizer(),
        audit_logger=audit_logger,
        audit_event_type="crm_erp.search.keyword.query",
        audit_metadata_context={
            "module_id": CRM_ERP_MODULE_ID,
            "feature_id": CRM_ERP_SEARCH_FEATURE_ID,
            "index_scope": "crm_erp_business_metadata",
            "ai_used": False,
            "rag_context_created": False,
            "content_included": False,
        },
        result_contract=CRM_ERP_SEARCH_RESULT_CONTRACT,
    )
    return CrmErpSearchService(keyword_search_service=keyword_service)


def build_crm_erp_search_records(
    *,
    account_repository: CrmAccountRepository,
    contact_repository: CrmContactRepository,
    activity_repository: CrmActivityRepository,
    note_repository: CrmNoteRepository,
    product_repository: ErpProductRepository,
    supplier_repository: ErpSupplierRepository,
    order_repository: ErpOrderRepository,
    invoice_repository: ErpInvoiceRepository,
    order_item_repository: ErpOrderItemRepository,
    invoice_item_repository: ErpInvoiceItemRepository,
    tenant_ids: Sequence[str] = DEFAULT_CRM_ERP_SEARCH_TENANT_IDS,
) -> list[KeywordIndexedChunk]:
    records: list[KeywordIndexedChunk] = []
    for tenant_id in tenant_ids:
        records.extend(_account_chunk(record) for record in account_repository.list_accounts(tenant_id=tenant_id))
        records.extend(_contact_chunk(record) for record in contact_repository.list_contacts(tenant_id=tenant_id))
        records.extend(_activity_chunk(record) for record in activity_repository.list_activities(tenant_id=tenant_id))
        records.extend(_note_chunk(record) for record in note_repository.list_notes(tenant_id=tenant_id))
        records.extend(_product_chunk(record) for record in product_repository.list_products(tenant_id=tenant_id))
        records.extend(_supplier_chunk(record) for record in supplier_repository.list_suppliers(tenant_id=tenant_id))
        records.extend(_order_chunk(record) for record in order_repository.list_orders(tenant_id=tenant_id))
        records.extend(_invoice_chunk(record) for record in invoice_repository.list_invoices(tenant_id=tenant_id))
        records.extend(
            _order_item_chunk(record) for record in order_item_repository.list_order_items(tenant_id=tenant_id)
        )
        records.extend(
            _invoice_item_chunk(record) for record in invoice_item_repository.list_invoice_items(tenant_id=tenant_id)
        )
    return records


def _account_chunk(record: CrmAccountRecord) -> KeywordIndexedChunk:
    return _metadata_chunk(
        record,
        title=record.display_name,
        index_parts=(record.display_name, record.account_number, record.account_kind.value, record.status.value),
    )


def _contact_chunk(record: CrmContactRecord) -> KeywordIndexedChunk:
    return _metadata_chunk(
        record,
        title=record.display_name,
        index_parts=(
            record.display_name,
            record.contact_number,
            record.given_name,
            record.family_name,
            record.role_label,
            record.account_object_id,
            record.status.value,
        ),
    )


def _activity_chunk(record: CrmActivityRecord) -> KeywordIndexedChunk:
    return _metadata_chunk(
        record,
        title=record.subject,
        index_parts=(
            record.subject,
            record.activity_number,
            record.activity_type.value,
            record.account_object_id,
            record.contact_object_id,
            record.due_at_utc,
            record.status.value,
        ),
    )


def _note_chunk(record: CrmNoteRecord) -> KeywordIndexedChunk:
    return _metadata_chunk(
        record,
        title=record.title,
        index_parts=(
            record.title,
            record.note_number,
            record.account_object_id,
            record.contact_object_id,
            record.activity_object_id,
            record.status.value,
        ),
    )


def _product_chunk(record: ErpProductRecord) -> KeywordIndexedChunk:
    return _metadata_chunk(
        record,
        title=record.display_name,
        index_parts=(
            record.display_name,
            record.product_number,
            record.product_kind.value,
            record.unit_code,
            record.status.value,
        ),
    )


def _supplier_chunk(record: ErpSupplierRecord) -> KeywordIndexedChunk:
    return _metadata_chunk(
        record,
        title=record.display_name,
        index_parts=(
            record.display_name,
            record.supplier_number,
            record.supplier_kind.value,
            record.primary_contact_label,
            record.country_code,
            record.status.value,
        ),
    )


def _order_chunk(record: ErpOrderRecord) -> KeywordIndexedChunk:
    return _metadata_chunk(
        record,
        title=record.order_number,
        index_parts=(
            record.order_number,
            record.account_object_id,
            *record.product_object_ids,
            record.order_date,
            record.currency_code,
            record.status.value,
        ),
    )


def _invoice_chunk(record: ErpInvoiceRecord) -> KeywordIndexedChunk:
    return _metadata_chunk(
        record,
        title=record.invoice_number,
        index_parts=(
            record.invoice_number,
            record.order_object_id,
            record.account_object_id,
            *record.product_object_ids,
            record.invoice_date,
            record.due_date,
            record.currency_code,
            record.status.value,
        ),
    )


def _order_item_chunk(record: ErpOrderItemRecord) -> KeywordIndexedChunk:
    return _metadata_chunk(
        record,
        title=f"{record.order_object_id} line {record.line_number}",
        index_parts=(
            record.order_object_id,
            record.product_object_id,
            record.line_number,
            record.description,
            record.unit_code,
            record.currency_code,
            record.status.value,
        ),
    )


def _invoice_item_chunk(record: ErpInvoiceItemRecord) -> KeywordIndexedChunk:
    return _metadata_chunk(
        record,
        title=f"{record.invoice_object_id} line {record.line_number}",
        index_parts=(
            record.invoice_object_id,
            record.order_item_object_id,
            record.product_object_id,
            record.line_number,
            record.description,
            record.unit_code,
            record.currency_code,
            record.status.value,
        ),
    )


def _metadata_chunk(
    record: SearchableBusinessRecord,
    *,
    title: str,
    index_parts: Sequence[object | None],
) -> KeywordIndexedChunk:
    return KeywordIndexedChunk(
        metadata=keyword_metadata(
            tenant_id=record.tenant_id,
            object_id=record.object_id,
            object_type=record.object_type,
            version_id=record.schema_version,
            chunk_id=f"{record.object_id}-metadata",
            classification=record.data_classification,
            retention_policy_id=record.retention_policy_id,
            legal_hold_state=record.legal_hold_state,
            acl_hash=f"sha256:acl-{record.object_id}",
            content_hash=f"sha256:{record.object_id}",
        ),
        title=title,
        index_text=_metadata_index_text(index_parts),
    )


def _metadata_index_text(parts: Sequence[object | None]) -> str:
    return " ".join(str(part).strip() for part in parts if part is not None and str(part).strip())
