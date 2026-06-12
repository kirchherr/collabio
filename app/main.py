import os
from collections.abc import Callable
from typing import Annotated, cast

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status

from suite.ai_control_plane.audit import build_default_audit_logger, canonical_json, stable_hash
from suite.ai_control_plane.models import (
    InferenceRequest,
    InferenceResponse,
    TenantPolicy,
    UserContext,
)
from suite.ai_control_plane.policy import PolicyEngine, PolicyViolation
from suite.ai_control_plane.registries import (
    InMemoryModelRegistry,
    InMemoryPromptRegistry,
    InMemoryToolPermissionRegistry,
    JsonFileModelRegistry,
    JsonFilePromptRegistry,
    JsonFileToolPermissionRegistry,
)
from suite.llm_gateway.gateway import LocalLLMGateway
from suite.llm_gateway.providers.mock import MockLLMProvider
from suite.llm_gateway.providers.ollama import OllamaProvider
from suite.llm_gateway.providers.openai_compatible import OpenAICompatibleProvider
from suite.persistence.migration_catalog import load_migration_manifest
from suite.platform.admin_models import TenantAiPolicyUpdate
from suite.platform.authz_admin import (
    AbacPolicyBindingUpsertCommand,
    AuthzAdminStore,
    AuthzMutationView,
    GroupUpsertCommand,
    JwtReplayRetentionPurgeCommand,
    JwtReplayRetentionPurgeView,
    ObjectAclEntryUpsertCommand,
    PrincipalGroupMembershipUpsertCommand,
    PrincipalMembershipUpsertCommand,
    PrincipalRoleAssignmentUpsertCommand,
    PrincipalUpsertCommand,
    RoleUpsertCommand,
    build_default_authz_admin_store,
)
from suite.platform.context import (
    DevHeaderAuthError,
    JwtAuthenticationError,
    PrincipalResolutionError,
    TenantRequestContext,
    build_default_principal_resolver,
    require_dev_header_auth_allowed,
)
from suite.platform.crm_accounts import (
    CRM_ACCOUNTS_FEATURE_ID,
    CRM_ERP_MODULE_ID,
    CrmAccountService,
    CrmAccountsResponse,
    InMemoryCrmAccountRepository,
)
from suite.platform.crm_activities import (
    CRM_ACTIVITIES_FEATURE_ID,
    CrmActivitiesResponse,
    CrmActivityService,
    CrmNotesResponse,
    InMemoryCrmActivityRepository,
    InMemoryCrmNoteRepository,
)
from suite.platform.crm_contacts import (
    CRM_CONTACTS_FEATURE_ID,
    CrmContactService,
    CrmContactsResponse,
    InMemoryCrmContactRepository,
)
from suite.platform.erp_products import (
    ERP_PRODUCTS_FEATURE_ID,
    ErpProductService,
    ErpProductsResponse,
    InMemoryErpProductRepository,
)
from suite.platform.knowledge_base import (
    KB_ARTICLES_FEATURE_ID,
    KNOWLEDGE_BASE_MODULE_ID,
    InMemoryKnowledgeBaseArticleRepository,
    KnowledgeBaseArticleService,
    KnowledgeBaseArticlesResponse,
    KnowledgeBaseEvidenceRefreshPreviewCommand,
    KnowledgeBaseEvidenceRefreshPreviewResponse,
    KnowledgeBaseEvidenceResponse,
    KnowledgeBaseWriteApprovalCommand,
    KnowledgeBaseWriteApprovalTransitionCommand,
    KnowledgeBaseWriteApprovalTransitionResponse,
    KnowledgeBaseWriteDryRunResponse,
    KnowledgeBaseWriteExecutionSkeletonCommand,
    KnowledgeBaseWriteExecutionSkeletonResponse,
    build_default_knowledge_base_write_approval_ledger,
    demo_knowledge_base_source_object_repository,
)
from suite.platform.modules import (
    InMemoryModuleRegistry,
    ModuleDecommissionBlockCommand,
    ModuleDecommissionCancelCommand,
    ModuleDecommissionCheck,
    ModuleDecommissionCompletionCommand,
    ModuleDecommissionReopenCommand,
    ModuleDecommissionRequestCommand,
    ModuleGateDecision,
    ModuleGateSurface,
    ModuleLifecycleCommand,
    ModuleLifecycleError,
    PlatformModulesResponse,
    TenantModuleAdminView,
    default_module_registry,
    tenant_module_admin_view,
)
from suite.platform.runtime import suite_auth_mode
from suite.platform.storage_paths import suite_data_dir
from suite.platform.tenant_policies import InMemoryTenantPolicyRepository, JsonFileTenantPolicyRepository
from suite.rag.embedding_model_admin import (
    EmbeddingModelVersionAdminService,
    EmbeddingModelVersionApprovalRequest,
    EmbeddingModelVersionRegistrationRequest,
    EmbeddingModelVersionRetirementRequest,
    EmbeddingModelVersionView,
    JsonFileEmbeddingModelVersionRegistry,
)
from suite.rag.models import RagQuery, RagResponse
from suite.rag.pipeline import RagPipeline
from suite.rag.repositories import (
    AuthorizedChunkRepository,
    InMemoryAclAuthorizer,
    InMemorySourceChunkRepository,
    InMemoryVectorStore,
)
from suite.rag.source_indexing import InMemoryEmbeddingModelVersionRegistry
from suite.search.keyword import InMemoryKeywordIndex, KeywordSearchService
from suite.search.models import KeywordSearchQuery, KeywordSearchResponse
from suite.voice.models import VoiceTranscriptRequest, VoiceTranscriptResponse
from suite.voice.privacy import VoicePrivacyGuard


def parse_csv_header(value: str | None) -> set[str]:
    if value is None:
        return set()
    return {item.strip() for item in value.split(",") if item.strip()}


def get_tenant_request_context(
    request: Request,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
    tenant_id: Annotated[str | None, Header(alias="X-Tenant-Id")] = None,
    user_id: Annotated[str | None, Header(alias="X-User-Id")] = None,
    role_ids: Annotated[str | None, Header(alias="X-Role-Ids")] = None,
    readable_object_ids: Annotated[str | None, Header(alias="X-Readable-Object-Ids")] = None,
) -> TenantRequestContext:
    auth_mode = suite_auth_mode()
    if auth_mode == "dev":
        return get_dev_header_tenant_request_context(
            request=request,
            tenant_id=tenant_id,
            user_id=user_id,
            role_ids=role_ids,
            readable_object_ids=readable_object_ids,
        )
    if auth_mode in {"jwt", "oidc"}:
        return get_jwt_tenant_request_context(request=request, authorization=authorization)
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"Unsupported SUITE_AUTH_MODE: {auth_mode}",
    )


def get_dev_header_tenant_request_context(
    *,
    request: Request,
    tenant_id: str | None,
    user_id: str | None,
    role_ids: str | None,
    readable_object_ids: str | None,
) -> TenantRequestContext:
    try:
        require_dev_header_auth_allowed()
    except DevHeaderAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    if not tenant_id or not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tenant context requires X-Tenant-Id and X-User-Id headers",
        )

    policy_repository: InMemoryTenantPolicyRepository = request.app.state.tenant_policy_repository
    try:
        tenant_policy = policy_repository.get(tenant_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant policy is not available",
        ) from exc

    return TenantRequestContext(
        user_context=UserContext(
            user_id=user_id,
            tenant_id=tenant_id,
            role_ids=parse_csv_header(role_ids),
            readable_object_ids=parse_csv_header(readable_object_ids),
        ),
        tenant_policy=tenant_policy,
    )


def get_jwt_tenant_request_context(*, request: Request, authorization: str | None) -> TenantRequestContext:
    principal_resolver = request.app.state.principal_resolver
    try:
        user_context = principal_resolver.resolve_authorization_header(authorization)
    except (JwtAuthenticationError, PrincipalResolutionError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    policy_repository: InMemoryTenantPolicyRepository = request.app.state.tenant_policy_repository
    try:
        tenant_policy = policy_repository.get(user_context.tenant_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant policy is not available",
        ) from exc
    return TenantRequestContext(user_context=user_context, tenant_policy=tenant_policy)


ADMIN_ROLE_IDS = {"tenant-admin", "security-admin"}


def require_tenant_admin(
    context: Annotated[TenantRequestContext, Depends(get_tenant_request_context)],
) -> TenantRequestContext:
    if context.user_context.role_ids.isdisjoint(ADMIN_ROLE_IDS):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant admin role required",
        )
    return context


def require_security_admin(
    context: Annotated[TenantRequestContext, Depends(get_tenant_request_context)],
) -> TenantRequestContext:
    if "security-admin" not in context.user_context.role_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Security admin role required",
        )
    return context


def require_module_api_gate(
    *,
    module_id: str,
    feature_id: str | None = None,
    compliance: bool = False,
) -> Callable[..., ModuleGateDecision]:
    surface = ModuleGateSurface.COMPLIANCE_API if compliance else ModuleGateSurface.NORMAL_API

    def dependency(
        request: Request,
        context: Annotated[TenantRequestContext, Depends(get_tenant_request_context)],
    ) -> ModuleGateDecision:
        module_registry: InMemoryModuleRegistry = request.app.state.module_registry
        try:
            return module_registry.require_module_gate(
                tenant_id=context.user_context.tenant_id,
                module_id=module_id,
                surface=surface,
                feature_id=feature_id,
            )
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ModuleLifecycleError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    return dependency


def build_app() -> FastAPI:
    app = FastAPI(title="Compliance-First Enterprise Suite", version="0.1.0")

    data_dir = suite_data_dir()
    registry_dir = data_dir / "registries"

    audit_logger = build_default_audit_logger(data_dir)
    model_registry = JsonFileModelRegistry.load_or_seed(
        registry_dir / "models.json",
        seed=InMemoryModelRegistry.default(),
    )
    prompt_registry = JsonFilePromptRegistry.load_or_seed(
        registry_dir / "prompts.json",
        seed=InMemoryPromptRegistry.default(),
    )
    tool_permission_registry = JsonFileToolPermissionRegistry.load_or_seed(
        registry_dir / "tool_permissions.json",
        seed=InMemoryToolPermissionRegistry.default(),
    )
    embedding_model_registry = JsonFileEmbeddingModelVersionRegistry.load_or_seed(
        registry_dir / "embedding_models.json",
        seed=InMemoryEmbeddingModelVersionRegistry.approved_single_model(),
    )
    policy_engine = PolicyEngine(
        model_registry=model_registry,
        tool_permission_registry=tool_permission_registry,
    )
    llm_gateway = LocalLLMGateway(
        providers={
            "mock": MockLLMProvider(),
            "ollama": OllamaProvider(base_url=os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")),
            "vllm": OpenAICompatibleProvider(base_url=os.getenv("VLLM_BASE_URL", "http://vllm:8000/v1")),
        },
        model_registry=model_registry,
        prompt_registry=prompt_registry,
        policy_engine=policy_engine,
        audit_logger=audit_logger,
    )
    acl_authorizer = InMemoryAclAuthorizer.demo()
    rag_pipeline = RagPipeline(
        vector_store=InMemoryVectorStore.demo(),
        chunk_repository=AuthorizedChunkRepository(
            chunk_repository=InMemorySourceChunkRepository.demo(),
            acl_authorizer=acl_authorizer,
        ),
        llm_gateway=llm_gateway,
        audit_logger=audit_logger,
    )
    keyword_search_service = KeywordSearchService(
        index=InMemoryKeywordIndex.demo(),
        acl_authorizer=acl_authorizer,
        audit_logger=audit_logger,
    )
    crm_account_service = CrmAccountService(
        repository=InMemoryCrmAccountRepository.demo(),
        audit_logger=audit_logger,
    )
    crm_contact_service = CrmContactService(
        repository=InMemoryCrmContactRepository.demo(),
        audit_logger=audit_logger,
    )
    crm_activity_service = CrmActivityService(
        activity_repository=InMemoryCrmActivityRepository.demo(),
        note_repository=InMemoryCrmNoteRepository.demo(),
        audit_logger=audit_logger,
    )
    erp_product_service = ErpProductService(
        repository=InMemoryErpProductRepository.demo(),
        audit_logger=audit_logger,
    )
    knowledge_base_article_service = KnowledgeBaseArticleService(
        repository=InMemoryKnowledgeBaseArticleRepository.demo(),
        source_repository=demo_knowledge_base_source_object_repository(),
        audit_logger=audit_logger,
        write_approval_ledger=build_default_knowledge_base_write_approval_ledger(),
    )
    voice_guard = VoicePrivacyGuard(audit_logger=audit_logger)
    tenant_policy_repository = JsonFileTenantPolicyRepository.load_or_seed(
        registry_dir / "tenant_policies.json",
        seed=InMemoryTenantPolicyRepository.default(),
    )
    module_registry = default_module_registry()
    migration_manifest = load_migration_manifest()
    authz_admin_store = build_default_authz_admin_store()
    embedding_model_admin = EmbeddingModelVersionAdminService(
        repository=embedding_model_registry,
        audit_logger=audit_logger,
    )
    principal_resolver = build_default_principal_resolver()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/platform/modules", response_model=PlatformModulesResponse)
    def list_platform_modules(
        request: Request,
        context: Annotated[TenantRequestContext, Depends(get_tenant_request_context)],
    ) -> PlatformModulesResponse:
        module_registry: InMemoryModuleRegistry = request.app.state.module_registry
        return module_registry.discover_tenant_modules(context.user_context.tenant_id)

    def tenant_policy_snapshot_hash(policy: TenantPolicy) -> str:
        return stable_hash(canonical_json(policy.model_dump(mode="json")))

    def authz_admin_audit_ref(
        *,
        event_type: str,
        resource_type: str,
        resource_id: str,
        approval_reference: str,
        reason: str,
        context: TenantRequestContext,
        metadata: dict[str, object] | None = None,
    ) -> str:
        audit_metadata: dict[str, object] = {
            "approval_reference": approval_reference,
            "resource_type": resource_type,
            "resource_id": resource_id,
        }
        if metadata is not None:
            audit_metadata.update(metadata)
        event = audit_logger.record(
            user_context=context.user_context,
            event_type=event_type,
            source_object_ids=[f"authz:{resource_type}:{resource_id}"],
            input_text=reason,
            metadata=audit_metadata,
        )
        return f"audit:{event.event_id}"

    def authz_admin_store_from_request(request: Request) -> AuthzAdminStore:
        return cast(AuthzAdminStore, request.app.state.authz_admin_store)

    def module_audit_ref(
        *,
        action: str,
        module_id: str,
        command: ModuleLifecycleCommand,
        context: TenantRequestContext,
        target_status: str,
    ) -> str:
        event = audit_logger.record(
            user_context=context.user_context,
            event_type=f"tenant_module.{action}",
            source_object_ids=[f"module:{module_id}"],
            input_text=command.reason,
            metadata={
                "module_id": module_id,
                "approval_reference": command.approval_reference,
                "target_status": target_status,
                "feature_count": len(command.enabled_features or {}),
            },
        )
        return f"audit:{event.event_id}"

    @app.post("/v1/admin/tenant-modules/{module_id}/provision", response_model=TenantModuleAdminView)
    def provision_tenant_module(
        module_id: str,
        command: ModuleLifecycleCommand,
        request: Request,
        context: Annotated[TenantRequestContext, Depends(require_tenant_admin)],
    ) -> TenantModuleAdminView:
        module_registry: InMemoryModuleRegistry = request.app.state.module_registry
        try:
            state = module_registry.provision_tenant_module(
                tenant_id=context.user_context.tenant_id,
                module_id=module_id,
                policy_snapshot_hash=tenant_policy_snapshot_hash(context.tenant_policy),
                changed_by=context.user_context.user_id,
                audit_chain_ref=module_audit_ref(
                    action="provisioned",
                    module_id=module_id,
                    command=command,
                    context=context,
                    target_status="disabled",
                ),
                enabled_features=command.enabled_features,
                migration_manifest_entries=request.app.state.migration_manifest,
            )
            return tenant_module_admin_view(state)
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ModuleLifecycleError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/v1/admin/tenant-modules/{module_id}/enable", response_model=TenantModuleAdminView)
    def enable_tenant_module(
        module_id: str,
        command: ModuleLifecycleCommand,
        request: Request,
        context: Annotated[TenantRequestContext, Depends(require_tenant_admin)],
    ) -> TenantModuleAdminView:
        module_registry: InMemoryModuleRegistry = request.app.state.module_registry
        try:
            state = module_registry.enable_tenant_module(
                tenant_id=context.user_context.tenant_id,
                module_id=module_id,
                policy_snapshot_hash=tenant_policy_snapshot_hash(context.tenant_policy),
                changed_by=context.user_context.user_id,
                audit_chain_ref=module_audit_ref(
                    action="enabled",
                    module_id=module_id,
                    command=command,
                    context=context,
                    target_status="enabled",
                ),
                enabled_features=command.enabled_features,
            )
            return tenant_module_admin_view(state)
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ModuleLifecycleError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/v1/admin/tenant-modules/{module_id}/disable", response_model=TenantModuleAdminView)
    def disable_tenant_module(
        module_id: str,
        command: ModuleLifecycleCommand,
        request: Request,
        context: Annotated[TenantRequestContext, Depends(require_tenant_admin)],
    ) -> TenantModuleAdminView:
        module_registry: InMemoryModuleRegistry = request.app.state.module_registry
        try:
            state = module_registry.disable_tenant_module(
                tenant_id=context.user_context.tenant_id,
                module_id=module_id,
                policy_snapshot_hash=tenant_policy_snapshot_hash(context.tenant_policy),
                changed_by=context.user_context.user_id,
                audit_chain_ref=module_audit_ref(
                    action="disabled",
                    module_id=module_id,
                    command=command,
                    context=context,
                    target_status="disabled",
                ),
            )
            return tenant_module_admin_view(state)
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ModuleLifecycleError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/v1/admin/tenant-modules/{module_id}/suspend", response_model=TenantModuleAdminView)
    def suspend_tenant_module(
        module_id: str,
        command: ModuleLifecycleCommand,
        request: Request,
        context: Annotated[TenantRequestContext, Depends(require_tenant_admin)],
    ) -> TenantModuleAdminView:
        module_registry: InMemoryModuleRegistry = request.app.state.module_registry
        try:
            state = module_registry.suspend_tenant_module(
                tenant_id=context.user_context.tenant_id,
                module_id=module_id,
                policy_snapshot_hash=tenant_policy_snapshot_hash(context.tenant_policy),
                changed_by=context.user_context.user_id,
                audit_chain_ref=module_audit_ref(
                    action="suspended",
                    module_id=module_id,
                    command=command,
                    context=context,
                    target_status="suspended",
                ),
            )
            return tenant_module_admin_view(state)
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ModuleLifecycleError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/v1/admin/tenant-modules/{module_id}/decommission-check", response_model=ModuleDecommissionCheck)
    def check_tenant_module_decommission(
        module_id: str,
        request: Request,
        context: Annotated[TenantRequestContext, Depends(require_tenant_admin)],
    ) -> ModuleDecommissionCheck:
        module_registry: InMemoryModuleRegistry = request.app.state.module_registry
        try:
            check = module_registry.decommission_check(tenant_id=context.user_context.tenant_id, module_id=module_id)
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

        audit_logger.record(
            user_context=context.user_context,
            event_type="tenant_module.decommission_check",
            source_object_ids=[f"module:{module_id}"],
            metadata={
                "module_id": module_id,
                "status": check.status,
                "can_decommission": check.can_decommission,
                "blocking_reason_count": len(check.blocking_reasons),
                "required_evidence_count": len(check.required_evidence),
            },
        )
        return check

    @app.post("/v1/admin/tenant-modules/{module_id}/decommission-request", response_model=TenantModuleAdminView)
    def request_tenant_module_decommission(
        module_id: str,
        command: ModuleDecommissionRequestCommand,
        request: Request,
        context: Annotated[TenantRequestContext, Depends(require_tenant_admin)],
    ) -> TenantModuleAdminView:
        module_registry: InMemoryModuleRegistry = request.app.state.module_registry
        try:
            state = module_registry.request_decommission(
                tenant_id=context.user_context.tenant_id,
                module_id=module_id,
                policy_snapshot_hash=tenant_policy_snapshot_hash(context.tenant_policy),
                changed_by=context.user_context.user_id,
                audit_chain_ref=module_audit_ref(
                    action="decommission_requested",
                    module_id=module_id,
                    command=command,
                    context=context,
                    target_status="decommission_requested",
                ),
                decommission_evidence_refs=command.evidence_refs(),
            )
            return tenant_module_admin_view(state)
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ModuleLifecycleError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/v1/admin/tenant-modules/{module_id}/decommission-block", response_model=TenantModuleAdminView)
    def block_tenant_module_decommission(
        module_id: str,
        command: ModuleDecommissionBlockCommand,
        request: Request,
        context: Annotated[TenantRequestContext, Depends(require_tenant_admin)],
    ) -> TenantModuleAdminView:
        module_registry: InMemoryModuleRegistry = request.app.state.module_registry
        try:
            state = module_registry.block_decommission(
                tenant_id=context.user_context.tenant_id,
                module_id=module_id,
                policy_snapshot_hash=tenant_policy_snapshot_hash(context.tenant_policy),
                changed_by=context.user_context.user_id,
                audit_chain_ref=module_audit_ref(
                    action="decommission_blocked",
                    module_id=module_id,
                    command=command,
                    context=context,
                    target_status="decommission_blocked",
                ),
                blocker_evidence_refs=command.evidence_refs(),
            )
            return tenant_module_admin_view(state)
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ModuleLifecycleError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/v1/admin/tenant-modules/{module_id}/decommission-cancel", response_model=TenantModuleAdminView)
    def cancel_tenant_module_decommission(
        module_id: str,
        command: ModuleDecommissionCancelCommand,
        request: Request,
        context: Annotated[TenantRequestContext, Depends(require_tenant_admin)],
    ) -> TenantModuleAdminView:
        module_registry: InMemoryModuleRegistry = request.app.state.module_registry
        try:
            state = module_registry.cancel_decommission(
                tenant_id=context.user_context.tenant_id,
                module_id=module_id,
                policy_snapshot_hash=tenant_policy_snapshot_hash(context.tenant_policy),
                changed_by=context.user_context.user_id,
                audit_chain_ref=module_audit_ref(
                    action="decommission_cancelled",
                    module_id=module_id,
                    command=command,
                    context=context,
                    target_status="disabled",
                ),
                cancel_evidence_refs=command.evidence_refs(),
            )
            return tenant_module_admin_view(state)
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ModuleLifecycleError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/v1/admin/tenant-modules/{module_id}/decommission-reopen", response_model=TenantModuleAdminView)
    def reopen_tenant_module_decommission(
        module_id: str,
        command: ModuleDecommissionReopenCommand,
        request: Request,
        context: Annotated[TenantRequestContext, Depends(require_tenant_admin)],
    ) -> TenantModuleAdminView:
        module_registry: InMemoryModuleRegistry = request.app.state.module_registry
        try:
            state = module_registry.reopen_decommission(
                tenant_id=context.user_context.tenant_id,
                module_id=module_id,
                policy_snapshot_hash=tenant_policy_snapshot_hash(context.tenant_policy),
                changed_by=context.user_context.user_id,
                audit_chain_ref=module_audit_ref(
                    action="decommission_reopened",
                    module_id=module_id,
                    command=command,
                    context=context,
                    target_status="decommission_requested",
                ),
                reopen_evidence_refs=command.evidence_refs(),
            )
            return tenant_module_admin_view(state)
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ModuleLifecycleError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/v1/admin/tenant-modules/{module_id}/decommission-complete", response_model=TenantModuleAdminView)
    def complete_tenant_module_decommission(
        module_id: str,
        command: ModuleDecommissionCompletionCommand,
        request: Request,
        context: Annotated[TenantRequestContext, Depends(require_tenant_admin)],
    ) -> TenantModuleAdminView:
        module_registry: InMemoryModuleRegistry = request.app.state.module_registry
        try:
            state = module_registry.complete_decommission(
                tenant_id=context.user_context.tenant_id,
                module_id=module_id,
                policy_snapshot_hash=tenant_policy_snapshot_hash(context.tenant_policy),
                changed_by=context.user_context.user_id,
                audit_chain_ref=module_audit_ref(
                    action="decommission_completed",
                    module_id=module_id,
                    command=command,
                    context=context,
                    target_status="decommissioned",
                ),
                completion_evidence_refs=command.evidence_refs(),
            )
            return tenant_module_admin_view(state)
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ModuleLifecycleError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/v1/admin/kb/evidence", response_model=KnowledgeBaseEvidenceResponse)
    def read_knowledge_base_evidence(
        request: Request,
        context: Annotated[TenantRequestContext, Depends(require_tenant_admin)],
        gate: Annotated[
            ModuleGateDecision,
            Depends(require_module_api_gate(module_id=KNOWLEDGE_BASE_MODULE_ID, compliance=True)),
        ],
    ) -> KnowledgeBaseEvidenceResponse:
        del gate
        articles = cast(KnowledgeBaseArticleService, request.app.state.knowledge_base_article_service)
        return articles.read_compliance_evidence(user_context=context.user_context)

    @app.post("/v1/admin/kb/articles/write-dry-run", response_model=KnowledgeBaseWriteDryRunResponse)
    def dry_run_knowledge_base_article_write(
        command: KnowledgeBaseWriteApprovalCommand,
        request: Request,
        context: Annotated[TenantRequestContext, Depends(require_tenant_admin)],
        gate: Annotated[
            ModuleGateDecision,
            Depends(require_module_api_gate(module_id=KNOWLEDGE_BASE_MODULE_ID, compliance=True)),
        ],
    ) -> KnowledgeBaseWriteDryRunResponse:
        del gate
        articles = cast(KnowledgeBaseArticleService, request.app.state.knowledge_base_article_service)
        try:
            return articles.dry_run_write_approval(command=command, user_context=context.user_context)
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post(
        "/v1/admin/kb/articles/write-approvals/approve",
        response_model=KnowledgeBaseWriteApprovalTransitionResponse,
    )
    def approve_knowledge_base_article_write(
        command: KnowledgeBaseWriteApprovalTransitionCommand,
        request: Request,
        context: Annotated[TenantRequestContext, Depends(require_tenant_admin)],
        gate: Annotated[
            ModuleGateDecision,
            Depends(require_module_api_gate(module_id=KNOWLEDGE_BASE_MODULE_ID, compliance=True)),
        ],
    ) -> KnowledgeBaseWriteApprovalTransitionResponse:
        del gate
        articles = cast(KnowledgeBaseArticleService, request.app.state.knowledge_base_article_service)
        try:
            return articles.approve_write_approval(command=command, user_context=context.user_context)
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post(
        "/v1/admin/kb/articles/write-approvals/refresh-preview",
        response_model=KnowledgeBaseEvidenceRefreshPreviewResponse,
    )
    def preview_knowledge_base_write_evidence_refresh(
        command: KnowledgeBaseEvidenceRefreshPreviewCommand,
        request: Request,
        context: Annotated[TenantRequestContext, Depends(require_tenant_admin)],
        gate: Annotated[
            ModuleGateDecision,
            Depends(require_module_api_gate(module_id=KNOWLEDGE_BASE_MODULE_ID, compliance=True)),
        ],
    ) -> KnowledgeBaseEvidenceRefreshPreviewResponse:
        del gate
        articles = cast(KnowledgeBaseArticleService, request.app.state.knowledge_base_article_service)
        try:
            return articles.preview_write_evidence_refresh(command=command, user_context=context.user_context)
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post(
        "/v1/admin/kb/articles/write-approvals/execution-skeleton",
        response_model=KnowledgeBaseWriteExecutionSkeletonResponse,
    )
    def prepare_knowledge_base_write_execution_skeleton(
        command: KnowledgeBaseWriteExecutionSkeletonCommand,
        request: Request,
        context: Annotated[TenantRequestContext, Depends(require_tenant_admin)],
        gate: Annotated[
            ModuleGateDecision,
            Depends(require_module_api_gate(module_id=KNOWLEDGE_BASE_MODULE_ID, compliance=True)),
        ],
    ) -> KnowledgeBaseWriteExecutionSkeletonResponse:
        del gate
        articles = cast(KnowledgeBaseArticleService, request.app.state.knowledge_base_article_service)
        try:
            return articles.prepare_write_execution_skeleton(command=command, user_context=context.user_context)
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.get("/v1/admin/tenant-policy", response_model=TenantPolicy)
    def get_tenant_policy(
        context: Annotated[TenantRequestContext, Depends(require_tenant_admin)],
    ) -> TenantPolicy:
        return context.tenant_policy

    @app.patch("/v1/admin/tenant-policy/ai-settings", response_model=TenantPolicy)
    def update_tenant_ai_settings(
        update: TenantAiPolicyUpdate,
        request: Request,
        context: Annotated[TenantRequestContext, Depends(require_tenant_admin)],
    ) -> TenantPolicy:
        update_fields = update.model_dump(exclude_unset=True)
        if not update_fields:
            return context.tenant_policy

        requested_model_ids = update.allowed_model_ids
        if requested_model_ids is not None:
            for model_id in requested_model_ids:
                try:
                    model_registry.get(model_id)
                except LookupError as exc:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Unknown model: {model_id}",
                    ) from exc

        policy_repository: InMemoryTenantPolicyRepository = request.app.state.tenant_policy_repository
        updated_policy = context.tenant_policy.model_copy(update=update_fields)
        try:
            persisted_policy = policy_repository.update(updated_policy)
        except LookupError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Tenant policy is not available",
            ) from exc

        audit_logger.record(
            user_context=context.user_context,
            event_type="tenant_policy.ai_settings.update",
            source_object_ids=[persisted_policy.tenant_id],
            metadata={
                "changed_fields": sorted(update_fields),
                "ai_enabled": persisted_policy.ai_enabled,
                "rag_enabled": persisted_policy.rag_enabled,
                "voice_enabled": persisted_policy.voice_enabled,
                "external_ai_enabled": persisted_policy.external_ai_enabled,
                "allowed_model_count": len(persisted_policy.allowed_model_ids),
            },
        )
        return persisted_policy

    @app.post("/v1/admin/authz/principals", response_model=AuthzMutationView)
    def upsert_authz_principal(
        command: PrincipalUpsertCommand,
        request: Request,
        context: Annotated[TenantRequestContext, Depends(require_security_admin)],
    ) -> AuthzMutationView:
        store = authz_admin_store_from_request(request)
        resource_id = f"{command.issuer}:{command.subject}"
        audit_ref = authz_admin_audit_ref(
            event_type="authz.principal.upsert",
            resource_type="tenant_principal",
            resource_id=resource_id,
            approval_reference=command.approval_reference,
            reason=command.reason,
            context=context,
            metadata={"status": command.status, "user_id": command.user_id},
        )
        return store.upsert_principal(
            tenant_id=context.user_context.tenant_id,
            command=command,
            audit_chain_ref=audit_ref,
        )

    @app.post("/v1/admin/authz/memberships", response_model=AuthzMutationView)
    def upsert_authz_membership(
        command: PrincipalMembershipUpsertCommand,
        request: Request,
        context: Annotated[TenantRequestContext, Depends(require_security_admin)],
    ) -> AuthzMutationView:
        store = authz_admin_store_from_request(request)
        resource_id = f"{command.issuer}:{command.subject}"
        audit_ref = authz_admin_audit_ref(
            event_type="authz.membership.upsert",
            resource_type="tenant_principal_membership",
            resource_id=resource_id,
            approval_reference=command.approval_reference,
            reason=command.reason,
            context=context,
            metadata={"status": command.status},
        )
        return store.upsert_membership(
            tenant_id=context.user_context.tenant_id,
            command=command,
            audit_chain_ref=audit_ref,
        )

    @app.post("/v1/admin/authz/roles", response_model=AuthzMutationView)
    def upsert_authz_role(
        command: RoleUpsertCommand,
        request: Request,
        context: Annotated[TenantRequestContext, Depends(require_security_admin)],
    ) -> AuthzMutationView:
        store = authz_admin_store_from_request(request)
        audit_ref = authz_admin_audit_ref(
            event_type="authz.role.upsert",
            resource_type="tenant_role",
            resource_id=command.role_id,
            approval_reference=command.approval_reference,
            reason=command.reason,
            context=context,
            metadata={"status": command.status, "system_role": command.system_role},
        )
        return store.upsert_role(
            tenant_id=context.user_context.tenant_id,
            command=command,
            audit_chain_ref=audit_ref,
        )

    @app.post("/v1/admin/authz/groups", response_model=AuthzMutationView)
    def upsert_authz_group(
        command: GroupUpsertCommand,
        request: Request,
        context: Annotated[TenantRequestContext, Depends(require_security_admin)],
    ) -> AuthzMutationView:
        store = authz_admin_store_from_request(request)
        audit_ref = authz_admin_audit_ref(
            event_type="authz.group.upsert",
            resource_type="tenant_group",
            resource_id=command.group_id,
            approval_reference=command.approval_reference,
            reason=command.reason,
            context=context,
            metadata={"status": command.status},
        )
        return store.upsert_group(
            tenant_id=context.user_context.tenant_id,
            command=command,
            audit_chain_ref=audit_ref,
        )

    @app.post("/v1/admin/authz/role-assignments", response_model=AuthzMutationView)
    def upsert_authz_role_assignment(
        command: PrincipalRoleAssignmentUpsertCommand,
        request: Request,
        context: Annotated[TenantRequestContext, Depends(require_security_admin)],
    ) -> AuthzMutationView:
        store = authz_admin_store_from_request(request)
        resource_id = f"{command.issuer}:{command.subject}:{command.role_id}"
        audit_ref = authz_admin_audit_ref(
            event_type="authz.role_assignment.upsert",
            resource_type="tenant_principal_role_assignment",
            resource_id=resource_id,
            approval_reference=command.approval_reference,
            reason=command.reason,
            context=context,
            metadata={"status": command.status, "role_id": command.role_id},
        )
        return store.upsert_role_assignment(
            tenant_id=context.user_context.tenant_id,
            command=command,
            audit_chain_ref=audit_ref,
        )

    @app.post("/v1/admin/authz/group-memberships", response_model=AuthzMutationView)
    def upsert_authz_group_membership(
        command: PrincipalGroupMembershipUpsertCommand,
        request: Request,
        context: Annotated[TenantRequestContext, Depends(require_security_admin)],
    ) -> AuthzMutationView:
        store = authz_admin_store_from_request(request)
        resource_id = f"{command.issuer}:{command.subject}:{command.group_id}"
        audit_ref = authz_admin_audit_ref(
            event_type="authz.group_membership.upsert",
            resource_type="tenant_principal_group_membership",
            resource_id=resource_id,
            approval_reference=command.approval_reference,
            reason=command.reason,
            context=context,
            metadata={"status": command.status, "group_id": command.group_id},
        )
        return store.upsert_group_membership(
            tenant_id=context.user_context.tenant_id,
            command=command,
            audit_chain_ref=audit_ref,
        )

    @app.post("/v1/admin/authz/object-acl-entries", response_model=AuthzMutationView)
    def upsert_authz_object_acl_entry(
        command: ObjectAclEntryUpsertCommand,
        request: Request,
        context: Annotated[TenantRequestContext, Depends(require_security_admin)],
    ) -> AuthzMutationView:
        store = authz_admin_store_from_request(request)
        resource_id = (
            f"{command.object_type}:{command.object_id}:"
            f"{command.acl_subject_type}:{command.acl_subject_id}:{command.permission}:{command.acl_version}"
        )
        audit_ref = authz_admin_audit_ref(
            event_type="authz.object_acl.upsert",
            resource_type="object_acl_entry",
            resource_id=resource_id,
            approval_reference=command.approval_reference,
            reason=command.reason,
            context=context,
            metadata={
                "status": command.status,
                "object_type": command.object_type,
                "acl_subject_type": command.acl_subject_type,
                "permission": command.permission,
                "acl_version": command.acl_version,
            },
        )
        return store.upsert_object_acl_entry(
            tenant_id=context.user_context.tenant_id,
            command=command,
            audit_chain_ref=audit_ref,
        )

    @app.post("/v1/admin/authz/abac-policy-bindings", response_model=AuthzMutationView)
    def upsert_authz_abac_policy_binding(
        command: AbacPolicyBindingUpsertCommand,
        request: Request,
        context: Annotated[TenantRequestContext, Depends(require_security_admin)],
    ) -> AuthzMutationView:
        store = authz_admin_store_from_request(request)
        audit_ref = authz_admin_audit_ref(
            event_type="authz.abac_policy_binding.upsert",
            resource_type="abac_policy_binding",
            resource_id=command.policy_id,
            approval_reference=command.approval_reference,
            reason=command.reason,
            context=context,
            metadata={
                "status": command.status,
                "effect": command.effect,
                "priority": command.priority,
                "principal_selector_keys": sorted(command.principal_selector),
                "resource_selector_keys": sorted(command.resource_selector),
                "condition_keys": sorted(command.condition),
            },
        )
        return store.upsert_abac_policy_binding(
            tenant_id=context.user_context.tenant_id,
            command=command,
            audit_chain_ref=audit_ref,
        )

    @app.post("/v1/admin/authz/jwt-replay-retention/purge", response_model=JwtReplayRetentionPurgeView)
    def purge_authz_jwt_replay_retention(
        command: JwtReplayRetentionPurgeCommand,
        request: Request,
        context: Annotated[TenantRequestContext, Depends(require_security_admin)],
    ) -> JwtReplayRetentionPurgeView:
        store = authz_admin_store_from_request(request)
        audit_ref = authz_admin_audit_ref(
            event_type="authz.jwt_replay_retention.purge",
            resource_type="jwt_replay_tokens",
            resource_id=f"expires_before:{command.expires_before_epoch}",
            approval_reference=command.approval_reference,
            reason=command.reason,
            context=context,
            metadata={"expires_before_epoch": command.expires_before_epoch},
        )
        return store.purge_expired_jwt_replay_tokens(
            tenant_id=context.user_context.tenant_id,
            command=command,
            audit_chain_ref=audit_ref,
        )

    @app.get("/v1/admin/embedding-models", response_model=list[EmbeddingModelVersionView])
    def list_embedding_model_versions(
        context: Annotated[TenantRequestContext, Depends(require_security_admin)],
    ) -> list[EmbeddingModelVersionView]:
        del context
        return list(embedding_model_admin.list_model_versions())

    @app.post("/v1/admin/embedding-models", response_model=EmbeddingModelVersionView)
    def register_embedding_model_version(
        registration: EmbeddingModelVersionRegistrationRequest,
        context: Annotated[TenantRequestContext, Depends(require_security_admin)],
    ) -> EmbeddingModelVersionView:
        try:
            return embedding_model_admin.register(registration, user_context=context.user_context)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post(
        "/v1/admin/embedding-models/{embedding_model_id}/versions/{embedding_model_version}/approve",
        response_model=EmbeddingModelVersionView,
    )
    def approve_embedding_model_version(
        embedding_model_id: str,
        embedding_model_version: str,
        approval: EmbeddingModelVersionApprovalRequest,
        context: Annotated[TenantRequestContext, Depends(require_security_admin)],
    ) -> EmbeddingModelVersionView:
        try:
            return embedding_model_admin.approve(
                embedding_model_id=embedding_model_id,
                embedding_model_version=embedding_model_version,
                request=approval,
                user_context=context.user_context,
            )
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post(
        "/v1/admin/embedding-models/{embedding_model_id}/versions/{embedding_model_version}/retire",
        response_model=EmbeddingModelVersionView,
    )
    def retire_embedding_model_version(
        embedding_model_id: str,
        embedding_model_version: str,
        retirement: EmbeddingModelVersionRetirementRequest,
        context: Annotated[TenantRequestContext, Depends(require_security_admin)],
    ) -> EmbeddingModelVersionView:
        try:
            return embedding_model_admin.retire(
                embedding_model_id=embedding_model_id,
                embedding_model_version=embedding_model_version,
                request=retirement,
                user_context=context.user_context,
            )
        except LookupError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @app.post("/v1/ai/inference", response_model=InferenceResponse)
    def infer(
        inference_request: InferenceRequest,
        context: Annotated[TenantRequestContext, Depends(get_tenant_request_context)],
    ) -> InferenceResponse:
        try:
            return llm_gateway.infer(
                request=inference_request,
                user_context=context.user_context,
                tenant_policy=context.tenant_policy,
            )
        except PolicyViolation as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.post("/v1/rag/query", response_model=RagResponse)
    def rag_query(
        query: RagQuery,
        context: Annotated[TenantRequestContext, Depends(get_tenant_request_context)],
    ) -> RagResponse:
        try:
            return rag_pipeline.answer(
                query=query,
                user_context=context.user_context,
                tenant_policy=context.tenant_policy,
            )
        except PolicyViolation as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    @app.post("/v1/search/keyword", response_model=KeywordSearchResponse)
    def keyword_search(
        query: KeywordSearchQuery,
        request: Request,
        context: Annotated[TenantRequestContext, Depends(get_tenant_request_context)],
    ) -> KeywordSearchResponse:
        keyword_service = cast(KeywordSearchService, request.app.state.keyword_search_service)
        return keyword_service.search(query=query, user_context=context.user_context)

    @app.get("/v1/crm/accounts", response_model=CrmAccountsResponse)
    def list_crm_accounts(
        request: Request,
        context: Annotated[TenantRequestContext, Depends(get_tenant_request_context)],
        gate: Annotated[
            ModuleGateDecision,
            Depends(require_module_api_gate(module_id=CRM_ERP_MODULE_ID, feature_id=CRM_ACCOUNTS_FEATURE_ID)),
        ],
    ) -> CrmAccountsResponse:
        del gate
        crm_accounts = cast(CrmAccountService, request.app.state.crm_account_service)
        return crm_accounts.list_accounts(user_context=context.user_context)

    @app.get("/v1/crm/contacts", response_model=CrmContactsResponse)
    def list_crm_contacts(
        request: Request,
        context: Annotated[TenantRequestContext, Depends(get_tenant_request_context)],
        gate: Annotated[
            ModuleGateDecision,
            Depends(require_module_api_gate(module_id=CRM_ERP_MODULE_ID, feature_id=CRM_CONTACTS_FEATURE_ID)),
        ],
    ) -> CrmContactsResponse:
        del gate
        crm_contacts = cast(CrmContactService, request.app.state.crm_contact_service)
        return crm_contacts.list_contacts(user_context=context.user_context)

    @app.get("/v1/crm/activities", response_model=CrmActivitiesResponse)
    def list_crm_activities(
        request: Request,
        context: Annotated[TenantRequestContext, Depends(get_tenant_request_context)],
        gate: Annotated[
            ModuleGateDecision,
            Depends(require_module_api_gate(module_id=CRM_ERP_MODULE_ID, feature_id=CRM_ACTIVITIES_FEATURE_ID)),
        ],
    ) -> CrmActivitiesResponse:
        del gate
        crm_activities = cast(CrmActivityService, request.app.state.crm_activity_service)
        return crm_activities.list_activities(user_context=context.user_context)

    @app.get("/v1/crm/notes", response_model=CrmNotesResponse)
    def list_crm_notes(
        request: Request,
        context: Annotated[TenantRequestContext, Depends(get_tenant_request_context)],
        gate: Annotated[
            ModuleGateDecision,
            Depends(require_module_api_gate(module_id=CRM_ERP_MODULE_ID, feature_id=CRM_ACTIVITIES_FEATURE_ID)),
        ],
    ) -> CrmNotesResponse:
        del gate
        crm_activities = cast(CrmActivityService, request.app.state.crm_activity_service)
        return crm_activities.list_notes(user_context=context.user_context)

    @app.get("/v1/erp/products", response_model=ErpProductsResponse)
    def list_erp_products(
        request: Request,
        context: Annotated[TenantRequestContext, Depends(get_tenant_request_context)],
        gate: Annotated[
            ModuleGateDecision,
            Depends(require_module_api_gate(module_id=CRM_ERP_MODULE_ID, feature_id=ERP_PRODUCTS_FEATURE_ID)),
        ],
    ) -> ErpProductsResponse:
        del gate
        erp_products = cast(ErpProductService, request.app.state.erp_product_service)
        return erp_products.list_products(user_context=context.user_context)

    @app.get("/v1/kb/articles", response_model=KnowledgeBaseArticlesResponse)
    def list_knowledge_base_articles(
        request: Request,
        context: Annotated[TenantRequestContext, Depends(get_tenant_request_context)],
        gate: Annotated[
            ModuleGateDecision,
            Depends(
                require_module_api_gate(
                    module_id=KNOWLEDGE_BASE_MODULE_ID,
                    feature_id=KB_ARTICLES_FEATURE_ID,
                )
            ),
        ],
    ) -> KnowledgeBaseArticlesResponse:
        del gate
        articles = cast(KnowledgeBaseArticleService, request.app.state.knowledge_base_article_service)
        return articles.list_articles(user_context=context.user_context)

    @app.post("/v1/voice/transcripts", response_model=VoiceTranscriptResponse)
    def voice_transcript(
        transcript_request: VoiceTranscriptRequest,
        context: Annotated[TenantRequestContext, Depends(get_tenant_request_context)],
    ) -> VoiceTranscriptResponse:
        try:
            return voice_guard.accept_transcript(
                request=transcript_request,
                user_context=context.user_context,
                tenant_policy=context.tenant_policy,
            )
        except PolicyViolation as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc

    app.state.audit_logger = audit_logger
    app.state.authz_admin_store = authz_admin_store
    app.state.crm_account_service = crm_account_service
    app.state.crm_activity_service = crm_activity_service
    app.state.crm_contact_service = crm_contact_service
    app.state.erp_product_service = erp_product_service
    app.state.knowledge_base_article_service = knowledge_base_article_service
    app.state.llm_gateway = llm_gateway
    app.state.embedding_model_admin = embedding_model_admin
    app.state.embedding_model_registry = embedding_model_registry
    app.state.keyword_search_service = keyword_search_service
    app.state.model_registry = model_registry
    app.state.migration_manifest = migration_manifest
    app.state.module_registry = module_registry
    app.state.principal_resolver = principal_resolver
    app.state.rag_pipeline = rag_pipeline
    app.state.tenant_policy_repository = tenant_policy_repository
    app.state.voice_guard = voice_guard

    return app


app = build_app()
