from __future__ import annotations

import importlib
import os
from collections.abc import Sequence
from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import psycopg
from fastapi import FastAPI, HTTPException, Request
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from suite.ai_control_plane.models import UserContext
from suite.operations.productivity_pilot_preflight import ProductivityPilotControl
from suite.platform.authz_admin import (
    AuthzMutationView,
    InMemoryAuthzAdminStore,
    ObjectAclEntryUpsertCommand,
    PgAuthzAdminStore,
)
from suite.platform.context import TenantRequestContext
from suite.platform.crm_accounts import CrmAccountRecord
from suite.platform.crm_erp_subfeatures import default_crm_erp_subfeature_enabled_features
from suite.platform.crm_runtime import PgCrmRepository
from suite.platform.knowledge_base import (
    KB_ARTICLES_WRITE_FEATURE_ID,
    default_knowledge_base_enabled_features,
)
from suite.platform.knowledge_base_runtime import (
    KnowledgeBaseArticleServiceResolver,
    KnowledgeBaseRuntimeActivationCommand,
)
from suite.platform.modules import (
    InMemoryModuleRegistry,
    ModuleStatus,
    TenantModuleState,
    default_module_catalog_entries,
)
from suite.platform.principal_store import PgPrincipalDirectory
from suite.platform.productivity_pilot_start_authorization import (
    ProductivityPilotControlEvidence,
    ProductivityPilotStartAuthorization,
    build_productivity_pilot_control_evidence_manifest_hash,
    build_productivity_pilot_start_authorization_hash,
)
from suite.platform.productivity_pilot_traffic_scope import (
    ProductivityPilotTrafficDecision,
    ProductivityPilotTrafficScopeEnforcement,
    build_productivity_pilot_traffic_scope_hash,
)
from suite.platform.tasks_activities_module import (
    TASKS_WORKFLOW_WRITE_FEATURE_ID,
    default_tasks_activities_enabled_features,
)
from suite.platform.tenant_policies import InMemoryTenantPolicyRepository
from suite.platform.time_tracking_module import (
    TIME_APPROVALS_WRITE_FEATURE_ID,
    TIME_ENTRIES_WRITE_FEATURE_ID,
    default_time_tracking_enabled_features,
)
from suite.storage.adapter_policy import ObjectLockMode
from suite.storage.s3_compatible_content_store import S3CompatibleObjectWriteResult
from suite.storage.s3_sdk_client import Boto3S3CompatibleObjectStoreClient, build_boto3_s3_compatible_client
from suite.storage.source_object_storage import SourceObjectStorageError
from suite.storage.source_objects import sha256_bytes
from suite.testing.work_e2e_guard import (
    WORK_E2E_TENANT_ID,
    require_isolated_work_e2e_environment,
)
from work_e2e_controls import (
    crm_failure_requested,
    permits_crm_reader_acl_fixture,
    permits_reader_acl_fixture,
    storage_failure_modes,
)

allow_synthetic_traffic = require_isolated_work_e2e_environment(os.environ)
main_module = importlib.import_module("main")
app = cast(FastAPI, main_module.app)
catalog_entries = tuple(default_module_catalog_entries())
catalog_registry = InMemoryModuleRegistry(catalog_entries=list(catalog_entries))
migration_manifest = tuple(app.state.migration_manifest)


def _enabled_state(module_id: str, enabled_features: dict[str, bool]) -> TenantModuleState:
    now = datetime.now(UTC)
    return TenantModuleState(
        tenant_id=WORK_E2E_TENANT_ID,
        module_id=module_id,
        status=ModuleStatus.ENABLED,
        enabled_features=enabled_features,
        policy_snapshot_hash="sha256:work-e2e-synthetic-policy",
        provisioned_at_utc=now,
        enabled_at_utc=now,
        changed_by="work-e2e-harness",
        audit_chain_ref="audit:work-e2e-module-state",
        migration_evidence=catalog_registry.migration_evidence_for_module(
            module_id=module_id,
            migration_manifest_entries=migration_manifest,
        ),
    )


task_features = default_tasks_activities_enabled_features()
task_features[TASKS_WORKFLOW_WRITE_FEATURE_ID] = True
time_features = default_time_tracking_enabled_features()
time_features[TIME_ENTRIES_WRITE_FEATURE_ID] = True
time_features[TIME_APPROVALS_WRITE_FEATURE_ID] = True
knowledge_features = default_knowledge_base_enabled_features()
knowledge_features[KB_ARTICLES_WRITE_FEATURE_ID] = allow_synthetic_traffic

app.state.module_registry = InMemoryModuleRegistry(
    catalog_entries=list(catalog_entries),
    tenant_modules=[
        _enabled_state("crm_erp", default_crm_erp_subfeature_enabled_features()),
        _enabled_state("knowledge_base", knowledge_features),
        _enabled_state("tasks_activities", task_features),
        _enabled_state("time_tracking", time_features),
    ],
)

base_policy = InMemoryTenantPolicyRepository.default().get("tenant-demo")
synthetic_policy = base_policy.model_copy(
    update={
        "tenant_id": WORK_E2E_TENANT_ID,
        "ai_enabled": False,
        "allowed_model_ids": set(),
        "rag_enabled": False,
        "voice_enabled": False,
        "raw_audio_storage_allowed": False,
    }
)
app.state.tenant_policy_repository = InMemoryTenantPolicyRepository(policies={WORK_E2E_TENANT_ID: synthetic_policy})


def _allow_isolated_synthetic_traffic() -> ProductivityPilotTrafficDecision:
    return ProductivityPilotTrafficDecision(
        tenant_id=WORK_E2E_TENANT_ID,
        operation="TEST /work-e2e",
        pilot_traffic_managed=False,
        operation_in_scope=False,
        tenant_scope_enforced=True,
        route_scope_enforced=True,
        default_deny_enabled=True,
        authorization_allowed=True,
        http_status_code=200,
    )


def _synthetic_hash(label: str) -> str:
    return sha256_bytes(f"work-e2e:{label}".encode())


_fail_storage_write: ContextVar[bool] = ContextVar("work_e2e_fail_storage_write", default=False)
_fail_storage_read: ContextVar[bool] = ContextVar("work_e2e_fail_storage_read", default=False)
_fail_crm_read: ContextVar[bool] = ContextVar("work_e2e_fail_crm_read", default=False)


class FailureInjectableCrmRepository(PgCrmRepository):
    def list_accounts(self, *, tenant_id: str) -> Sequence[CrmAccountRecord]:
        if _fail_crm_read.get():
            raise psycopg.OperationalError("synthetic Work E2E CRM database failure")
        return super().list_accounts(tenant_id=tenant_id)


class FailureInjectableObjectStoreClient(Boto3S3CompatibleObjectStoreClient):
    """Exercise real content access without a production failure-control API."""

    def get_object(self, *, bucket_id: str, object_key: str, object_version_id: str) -> bytes:
        if _fail_storage_read.get():
            raise SourceObjectStorageError("synthetic Work E2E object-store read failure")
        return super().get_object(bucket_id=bucket_id, object_key=object_key, object_version_id=object_version_id)

    def put_object(
        self,
        *,
        bucket_id: str,
        object_key: str,
        body: bytes,
        metadata: dict[str, str],
        object_lock_mode: ObjectLockMode,
        legal_hold: bool,
    ) -> S3CompatibleObjectWriteResult:
        if _fail_storage_write.get():
            raise SourceObjectStorageError("synthetic Work E2E object-store write failure")
        return super().put_object(
            bucket_id=bucket_id,
            object_key=object_key,
            body=body,
            metadata=metadata,
            object_lock_mode=object_lock_mode,
            legal_hold=legal_hold,
        )


@app.middleware("http")
async def _isolated_storage_failure(request: Request, call_next: RequestResponseEndpoint) -> Response:
    fail_write, fail_read = storage_failure_modes(
        tenant_id=request.headers.get("X-Tenant-Id"),
        method=request.method,
        path=request.url.path,
        requested=request.headers.get("X-Work-E2E-Fail-Storage") == "1",
        allow_synthetic_traffic=allow_synthetic_traffic,
    )
    write_token = _fail_storage_write.set(fail_write)
    read_token = _fail_storage_read.set(fail_read)
    crm_token = _fail_crm_read.set(crm_failure_requested(
        tenant_id=request.headers.get("X-Tenant-Id"),
        method=request.method,
        path=request.url.path,
        requested=request.headers.get("X-Work-E2E-Fail-CRM") == "1",
    ))
    try:
        return await call_next(request)
    finally:
        _fail_storage_write.reset(write_token)
        _fail_storage_read.reset(read_token)
        _fail_crm_read.reset(crm_token)


class SyntheticReaderAclStore(InMemoryAuthzAdminStore):
    def __init__(self, *, database_dsn: str) -> None:
        super().__init__()
        self.reader_acl_store = PgAuthzAdminStore(database_dsn=database_dsn)

    def upsert_object_acl_entry(
        self, *, tenant_id: str, command: ObjectAclEntryUpsertCommand, audit_chain_ref: str
    ) -> AuthzMutationView:
        fields = dict(
            tenant_id=tenant_id,
            object_id=command.object_id,
            object_type=command.object_type,
            subject_type=command.acl_subject_type,
            subject_id=command.acl_subject_id,
            permission=command.permission,
        )
        if not (permits_reader_acl_fixture(**fields) or permits_crm_reader_acl_fixture(**fields)):
            raise HTTPException(status_code=403, detail="Outside synthetic reader ACL fixture")
        return self.reader_acl_store.upsert_object_acl_entry(
            tenant_id=tenant_id, command=command, audit_chain_ref=audit_chain_ref
        )


def _install_synthetic_knowledge_runtime() -> None:
    resolver = cast(KnowledgeBaseArticleServiceResolver, app.state.knowledge_base_article_service_resolver)
    client = build_boto3_s3_compatible_client(
        endpoint_url=os.environ["SUITE_S3_ENDPOINT_URL"],
        access_key_id=os.environ["SUITE_S3_ACCESS_KEY_ID"],
        secret_access_key=os.environ["SUITE_S3_SECRET_ACCESS_KEY"],
        storage_provider="minio",
    )
    resolver.object_store_client = FailureInjectableObjectStoreClient(
        sdk_client=client.sdk_client,
        storage_provider="minio",
    )
    # This in-memory restore reference is only a fixture for the synthetic tenant.
    # Provider capabilities and empty content inventory are checked against real MinIO/PG.
    resolver.activate_postgres_s3_runtime(
        command=KnowledgeBaseRuntimeActivationCommand(
            provider_profile_id="work-e2e-synthetic-minio",
            restore_drill_report_hash=_synthetic_hash("empty-restore-fixture-not-production-evidence"),
            approval_reference="test-fixture:work-e2e-runtime",
            reason="isolated synthetic browser proof only",
            human_confirmation=True,
        ),
        user_context=UserContext(
            tenant_id=WORK_E2E_TENANT_ID,
            user_id="work-e2e-harness",
            role_ids={"tenant-admin"},
        ),
        audit_chain_ref="test-fixture:work-e2e-runtime",
    )


def _synthetic_authorized_context(request: Request) -> TenantRequestContext:
    context = cast(
        TenantRequestContext,
        main_module.get_dev_header_tenant_request_context(
            request=request,
            tenant_id=request.headers.get("X-Tenant-Id"),
            user_id=request.headers.get("X-User-Id"),
            role_ids=request.headers.get("X-Role-Ids"),
            readable_object_ids=request.headers.get("X-Readable-Object-Ids"),
        ),
    )
    if not request.url.path.startswith(("/v1/kb/", "/v1/admin/kb/", "/v1/crm/")):
        return context
    # KB and CRM visibility comes from fresh database ACLs, never browser-supplied IDs.
    directory = PgPrincipalDirectory(database_dsn=os.environ["SUITE_DATABASE_DSN"])
    readable = directory.readable_object_ids(
        tenant_id=context.user_context.tenant_id,
        user_id=context.user_context.user_id,
        role_ids=context.user_context.role_ids,
        group_ids=set(),
    )
    return context.model_copy(
        update={"user_context": context.user_context.model_copy(update={"readable_object_ids": readable})}
    )


_install_synthetic_knowledge_runtime()
crm_repository = FailureInjectableCrmRepository(database_dsn=os.environ["SUITE_DATABASE_DSN"])
app.state.crm_account_service.repository = crm_repository
app.state.crm_contact_service.repository = crm_repository
app.state.crm_activity_service.activity_repository = crm_repository
app.state.crm_activity_service.note_repository = crm_repository
app.state.crm_account_workspace_service.account_repository = crm_repository
app.state.crm_account_workspace_service.contact_repository = crm_repository
app.state.crm_account_workspace_service.activity_repository = crm_repository
app.state.crm_account_workspace_service.note_repository = crm_repository
app.state.authz_admin_store = SyntheticReaderAclStore(
    database_dsn=os.environ["SUITE_AUTHZ_ADMIN_DATABASE_DSN"]
)
app.dependency_overrides[main_module.get_tenant_request_context] = _synthetic_authorized_context


def _install_closed_runtime_fixture() -> None:
    service = app.state.productivity_pilot_start_authorization_service
    now = datetime.now(UTC)
    allowed_operations = tuple(service.policy.allowed_api_operations)
    traffic_scope_draft = ProductivityPilotTrafficScopeEnforcement(
        tenant_id=WORK_E2E_TENANT_ID,
        enforcement_id="work-e2e-traffic-scope",
        admission_id="work-e2e-admission",
        admission_evidence_hash=_synthetic_hash("admission"),
        preflight_gate_hash=_synthetic_hash("preflight"),
        policy_hash=service.policy_hash,
        allowed_api_operations=allowed_operations,
        route_scope_hash=_synthetic_hash("route-scope"),
        command_hash=_synthetic_hash("traffic-command"),
        idempotency_key_hash=_synthetic_hash("traffic-idempotency"),
        human_confirmation_statement_hash=_synthetic_hash("traffic-confirmation"),
        change_request_ref="change:work-e2e-traffic-scope",
        ingress_policy_ref="ingress:work-e2e-internal-only",
        human_confirmation_reference="test-fixture:work-e2e-traffic-scope",
        audit_chain_ref="audit:work-e2e-traffic-scope",
        enforced_by="work-e2e-harness",
        enforced_at_utc=now - timedelta(minutes=10),
        evidence_hash="sha256:" + "0" * 64,
    )
    traffic_scope = traffic_scope_draft.model_copy(
        update={"evidence_hash": build_productivity_pilot_traffic_scope_hash(traffic_scope_draft)}
    )
    app.state.productivity_pilot_traffic_scope_store.append(traffic_scope)

    observed_at = now - timedelta(minutes=5)
    valid_until = now + timedelta(hours=1)

    def control_evidence(
        controls: tuple[ProductivityPilotControl, ...],
    ) -> tuple[ProductivityPilotControlEvidence, ...]:
        return tuple(
            ProductivityPilotControlEvidence(
                control_id=control.control_id,
                evidence_hash=_synthetic_hash(f"control:{control.control_id}"),
                observed_at_utc=observed_at,
                valid_until_utc=valid_until,
            )
            for control in controls
        )

    monitoring_evidence = control_evidence(tuple(service.policy.monitoring_controls))
    rollback_evidence = control_evidence(tuple(service.policy.rollback_controls))
    start_draft = ProductivityPilotStartAuthorization(
        tenant_id=WORK_E2E_TENANT_ID,
        authorization_id="work-e2e-start-authorization",
        enforcement_id=traffic_scope.enforcement_id,
        traffic_scope_evidence_hash=traffic_scope.evidence_hash,
        route_scope_hash=traffic_scope.route_scope_hash,
        admission_evidence_hash=traffic_scope.admission_evidence_hash,
        preflight_gate_hash=traffic_scope.preflight_gate_hash,
        policy_hash=traffic_scope.policy_hash,
        allowed_api_operations=allowed_operations,
        monitoring_evidence=monitoring_evidence,
        rollback_evidence=rollback_evidence,
        monitoring_evidence_manifest_hash=build_productivity_pilot_control_evidence_manifest_hash(monitoring_evidence),
        rollback_evidence_manifest_hash=build_productivity_pilot_control_evidence_manifest_hash(rollback_evidence),
        command_hash=_synthetic_hash("start-command"),
        idempotency_key_hash=_synthetic_hash("start-idempotency"),
        human_confirmation_statement_hash=_synthetic_hash("start-confirmation"),
        change_request_ref="change:work-e2e-start",
        human_confirmation_reference="test-fixture:work-e2e-start",
        security_approval_ref="test-fixture:work-e2e-security",
        audit_chain_ref="audit:work-e2e-start",
        authorized_by="work-e2e-harness",
        authorized_at_utc=now - timedelta(minutes=4),
        effective_at_utc=now - timedelta(minutes=3),
        expires_at_utc=now + timedelta(minutes=30),
        evidence_hash="sha256:" + "0" * 64,
    )
    start = start_draft.model_copy(
        update={"evidence_hash": build_productivity_pilot_start_authorization_hash(start_draft)}
    )
    app.state.productivity_pilot_start_authorization_store.append(start)


if allow_synthetic_traffic:
    traffic_dependency = cast(Any, main_module.require_productivity_pilot_traffic_scope)
    app.dependency_overrides[traffic_dependency] = _allow_isolated_synthetic_traffic
else:
    _install_closed_runtime_fixture()
