from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import DataClass, UserContext
from suite.platform.crm_accounts import CRM_ERP_MODULE_ID, CrmAccountRepository
from suite.platform.crm_activities import CrmActivityRepository, CrmNoteRepository
from suite.platform.crm_contacts import CrmContactRepository
from suite.platform.crm_erp_search import CRM_ERP_SEARCH_FEATURE_ID, build_crm_erp_search_records
from suite.platform.erp_products import ErpProductRepository
from suite.platform.erp_sales import (
    ErpInvoiceItemRepository,
    ErpInvoiceRepository,
    ErpOrderItemRepository,
    ErpOrderRepository,
)
from suite.platform.erp_suppliers import ErpSupplierRepository
from suite.rag.repositories import ReadableObjectAclAuthorizer
from suite.search.keyword import KeywordIndexedChunk

CRM_ERP_SOURCE_RESOLVER_ACL_TRACE_SCHEMA_VERSION = "crm_erp_source_resolver_acl_trace.v1"
CRM_ERP_SOURCE_RESOLVER_ACL_TRACE_RESULT_CONTRACT = "metadata_only_source_resolver_acl_trace_no_context"
CRM_ERP_SOURCE_RESOLVER_ACL_TRACE_ENDPOINT = "/v1/platform/search/crm-erp/source-resolver-acl-trace"
MAX_SOURCE_RESOLVER_OBJECT_IDS = 50


class CrmErpSourceResolverAclTraceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_ids: tuple[str, ...] = Field(min_length=1, max_length=MAX_SOURCE_RESOLVER_OBJECT_IDS)

    @field_validator("object_ids")
    @classmethod
    def require_non_empty_unique_object_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        seen: set[str] = set()
        for object_id in value:
            candidate = object_id.strip()
            if not candidate:
                raise ValueError("source resolver object IDs must not be empty")
            if candidate in seen:
                continue
            seen.add(candidate)
            normalized.append(candidate)
        return tuple(normalized)


class CrmErpResolvedSourceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    object_id: str
    object_type: str
    version_id: str
    chunk_id: str
    classification: DataClass
    retention_policy_id: str
    legal_hold_state: str
    acl_version: int
    acl_hash: str
    content_hash: str
    access_checked: bool = True
    authorized: bool = True


class CrmErpSourceResolverAclTraceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = CRM_ERP_SOURCE_RESOLVER_ACL_TRACE_SCHEMA_VERSION
    tenant_id: str
    module_id: str = CRM_ERP_MODULE_ID
    feature_id: str = CRM_ERP_SEARCH_FEATURE_ID
    endpoint: str = CRM_ERP_SOURCE_RESOLVER_ACL_TRACE_ENDPOINT
    requested_object_ids: tuple[str, ...]
    resolved_source_refs: tuple[CrmErpResolvedSourceRef, ...]
    blocked_source_object_ids: tuple[str, ...]
    unresolved_source_object_ids: tuple[str, ...]
    candidate_count: int
    authorized_count: int
    blocked_count: int
    unresolved_count: int
    source_resolver_acl_trace_ready: bool
    audit_event_id: str
    guardrails: tuple[str, ...]
    result_contract: str = CRM_ERP_SOURCE_RESOLVER_ACL_TRACE_RESULT_CONTRACT
    content_included: bool = False
    ai_used: bool = False
    rag_context_created: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False

    @model_validator(mode="after")
    def require_metadata_only_trace(self) -> CrmErpSourceResolverAclTraceResponse:
        if self.content_included or self.ai_used or self.rag_context_created:
            raise ValueError("CRM/ERP source resolver trace must not include content, AI, or RAG context")
        if self.destructive_actions_allowed or self.external_side_effect_allowed:
            raise ValueError("CRM/ERP source resolver trace must not allow side effects")
        if self.candidate_count != len(self.requested_object_ids):
            raise ValueError("candidate_count must match requested object IDs")
        if self.authorized_count != len(self.resolved_source_refs):
            raise ValueError("authorized_count must match resolved source refs")
        if self.blocked_count != len(self.blocked_source_object_ids):
            raise ValueError("blocked_count must match blocked source object IDs")
        if self.unresolved_count != len(self.unresolved_source_object_ids):
            raise ValueError("unresolved_count must match unresolved source object IDs")
        expected_ready = self.candidate_count > 0 and self.blocked_count == 0 and self.unresolved_count == 0
        if self.source_resolver_acl_trace_ready != expected_ready:
            raise ValueError("source_resolver_acl_trace_ready must reflect authorized resolution state")
        return self


class CrmErpSourceResolverAclTraceService:
    def __init__(
        self,
        *,
        records: Sequence[KeywordIndexedChunk],
        audit_logger: InMemoryAuditLogger,
    ) -> None:
        self._records_by_object_id = {record.metadata.source_object_id: record for record in records}
        self._acl_authorizer = ReadableObjectAclAuthorizer()
        self._audit_logger = audit_logger

    def build_trace(
        self,
        *,
        request: CrmErpSourceResolverAclTraceRequest,
        user_context: UserContext,
    ) -> CrmErpSourceResolverAclTraceResponse:
        resolved: list[CrmErpResolvedSourceRef] = []
        blocked: list[str] = []
        unresolved: list[str] = []
        for object_id in request.object_ids:
            record = self._records_by_object_id.get(object_id)
            if record is None or record.metadata.tenant_id != user_context.tenant_id:
                unresolved.append(object_id)
                continue
            metadata = record.metadata
            if not self._acl_authorizer.can_read(
                user_context=user_context,
                object_id=metadata.source_object_id,
                acl_version=metadata.acl_version,
            ):
                blocked.append(object_id)
                continue
            resolved.append(
                CrmErpResolvedSourceRef(
                    tenant_id=metadata.tenant_id,
                    object_id=metadata.source_object_id,
                    object_type=metadata.source_object_type,
                    version_id=metadata.source_version_id,
                    chunk_id=metadata.chunk_id,
                    classification=metadata.classification,
                    retention_policy_id=metadata.retention_policy_id,
                    legal_hold_state=metadata.legal_hold_state,
                    acl_version=metadata.acl_version,
                    acl_hash=metadata.acl_hash,
                    content_hash=metadata.content_hash,
                )
            )

        event = self._audit_logger.record(
            user_context=user_context,
            event_type="crm_erp.source_resolver_acl_trace",
            source_object_ids=[source.object_id for source in resolved],
            metadata={
                "module_id": CRM_ERP_MODULE_ID,
                "feature_id": CRM_ERP_SEARCH_FEATURE_ID,
                "result_contract": CRM_ERP_SOURCE_RESOLVER_ACL_TRACE_RESULT_CONTRACT,
                "candidate_count": len(request.object_ids),
                "authorized_count": len(resolved),
                "blocked_count": len(blocked),
                "unresolved_count": len(unresolved),
                "content_included": False,
                "ai_used": False,
                "rag_context_created": False,
            },
        )
        return CrmErpSourceResolverAclTraceResponse(
            tenant_id=user_context.tenant_id,
            requested_object_ids=request.object_ids,
            resolved_source_refs=tuple(resolved),
            blocked_source_object_ids=tuple(blocked),
            unresolved_source_object_ids=tuple(unresolved),
            candidate_count=len(request.object_ids),
            authorized_count=len(resolved),
            blocked_count=len(blocked),
            unresolved_count=len(unresolved),
            source_resolver_acl_trace_ready=bool(request.object_ids) and not blocked and not unresolved,
            audit_event_id=event.event_id,
            guardrails=(
                "tenant_context_required",
                "server_side_candidate_metadata_only",
                "authoritative_acl_validation_required",
                "blocked_refs_exclude_metadata",
                "no_raw_source_payload_fields",
                "no_rag_context_created",
            ),
        )


def build_crm_erp_source_resolver_acl_trace_service(
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
) -> CrmErpSourceResolverAclTraceService:
    return CrmErpSourceResolverAclTraceService(
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
        ),
        audit_logger=audit_logger,
    )
