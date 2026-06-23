import base64
import hmac
import json
import os
from hashlib import sha256
from pathlib import Path
from typing import Annotated, Any, cast
from uuid import uuid4

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from main import app, require_module_api_gate
from suite.ai_control_plane.models import DataClass, TenantPolicy
from suite.persistence.migration_catalog import load_migration_manifest
from suite.persistence.migrator import apply_migrations
from suite.platform.context import DEFAULT_DEV_JWT_SECRET, DEFAULT_JWT_AUDIENCE, DEFAULT_JWT_ISSUER
from suite.platform.knowledge_base import (
    KnowledgeBaseSourceObjectWriteGuardDecision,
    KnowledgeBaseWriteApprovalState,
    KnowledgeBaseWriteOperation,
    build_source_object_write_guard_ref,
)
from suite.platform.modules import (
    InMemoryModuleRegistry,
    ModuleGateDecision,
    ModuleWorkerGate,
    PgModuleRegistry,
    default_module_registry,
)
from suite.platform.source_object_preview_decisions import (
    InMemorySourceObjectPreviewDecisionLedger,
    JsonlSourceObjectPreviewDecisionLedger,
)
from suite.platform.tenant_policies import InMemoryTenantPolicyRepository
from suite.platform.workspace_source_objects import (
    ConfiguredWorkspaceSourceObjectCatalog,
    WorkspaceSourceObjectRef,
    parse_workspace_source_object_refs,
)
from suite.storage.adapter_policy import load_storage_adapter_policy
from suite.storage.retention import load_retention_manifest_policy
from suite.storage.source_object_storage import InMemorySourceObjectContentStore, PgSourceObjectRepository
from suite.storage.source_objects import (
    InMemorySourceObjectRepository,
    LegalHoldState,
    SourceLifecycleState,
    SourceObjectMetadata,
    SourceObjectRecord,
    SourceObjectType,
    build_source_object_manifest_hash,
    sha256_bytes,
)

client = TestClient(app)
REPO_ROOT = Path(__file__).resolve().parents[1]
RETENTION_POLICY_PATH = REPO_ROOT / "docs" / "retention_manifest_policy.json"
STORAGE_POLICY_PATH = REPO_ROOT / "docs" / "storage_adapter_policy.json"

DEMO_HEADERS = {
    "X-Tenant-Id": "tenant-demo",
    "X-User-Id": "user-demo",
    "X-Role-Ids": "knowledge-worker",
    "X-Readable-Object-Ids": "doc-1,mail-1",
}
DEMO_ADMIN_HEADERS = {
    **DEMO_HEADERS,
    "X-Role-Ids": "tenant-admin",
}
DEMO_SECURITY_ADMIN_HEADERS = {
    **DEMO_HEADERS,
    "X-Role-Ids": "security-admin",
}
DEMO_CRM_ACCOUNT_HEADERS = {
    **DEMO_HEADERS,
    "X-Readable-Object-Ids": "doc-1,mail-1,crm-account-acme-demo,crm-account-northwind-demo",
}
DEMO_CRM_CONTACT_HEADERS = {
    **DEMO_HEADERS,
    "X-Readable-Object-Ids": (
        "doc-1,mail-1,crm-account-acme-demo,crm-account-northwind-demo,crm-contact-ada-demo,crm-contact-max-demo"
    ),
}
DEMO_CRM_ACTIVITY_HEADERS = {
    **DEMO_HEADERS,
    "X-Readable-Object-Ids": (
        "doc-1,mail-1,crm-account-acme-demo,crm-account-northwind-demo,"
        "crm-contact-ada-demo,crm-contact-max-demo,"
        "crm-activity-followup-demo,crm-activity-review-demo,"
        "crm-note-acme-demo,crm-note-northwind-demo"
    ),
}
DEMO_ERP_PRODUCT_HEADERS = {
    **DEMO_HEADERS,
    "X-Readable-Object-Ids": "doc-1,mail-1,erp-product-standard-widget-demo,erp-product-service-plan-demo",
}
DEMO_KB_ARTICLE_HEADERS = {
    **DEMO_HEADERS,
    "X-Readable-Object-Ids": (
        "doc-1,mail-1,"
        "kb-article-backup-runbook-demo,kb-article-version-backup-runbook-v1-demo,"
        "kb-article-security-baseline-demo,kb-article-version-security-baseline-v1-demo"
    ),
}
DECOMMISSION_REQUEST_PAYLOAD = {
    "approval_reference": "approval:module-decommission-request",
    "reason": "tenant requests controlled module decommission",
    "retention_evaluation_ref": "retention:eval-1",
    "legal_hold_check_ref": "legal-hold:check-1",
    "export_archive_decision_ref": "export:decision-1",
    "audit_evidence_ref": "audit:evidence-1",
    "backup_restore_evidence_ref": "backup:restore-1",
}
DECOMMISSION_BLOCK_PAYLOAD = {
    "approval_reference": "approval:module-decommission-block",
    "reason": "legal hold still blocks decommission completion",
    "blocker_report_ref": "decommission-blocker:report-1",
    "remediation_plan_ref": "decommission-remediation:plan-1",
}
DECOMMISSION_COMPLETE_PAYLOAD = {
    "approval_reference": "approval:module-decommission-complete",
    "reason": "all final disposition evidence is complete",
    "final_retention_disposition_ref": "retention:final-disposition-1",
    "final_legal_hold_clearance_ref": "legal-hold:clearance-1",
    "final_export_archive_manifest_ref": "export:archive-manifest-1",
    "final_audit_closure_ref": "audit:closure-1",
    "final_backup_disposition_ref": "backup:final-disposition-1",
    "final_data_disposition_ref": "data-disposition:final-1",
}
DECOMMISSION_CANCEL_PAYLOAD = {
    "approval_reference": "approval:module-decommission-cancel",
    "reason": "tenant cancels the decommission workflow",
    "cancel_approval_ref": "approval:module-decommission-cancel",
    "cancel_audit_evidence_ref": "audit:decommission-cancel-evidence-1",
}


class LiveModuleRegistryDatabase:
    def __init__(self, *, migration_dsn: str, app_dsn: str, worker_dsn: str) -> None:
        self.migration_dsn = migration_dsn
        self.app_dsn = app_dsn
        self.worker_dsn = worker_dsn


class LiveSourceObjectDetailDatabase:
    def __init__(self, *, migration_dsn: str, app_dsn: str) -> None:
        self.migration_dsn = migration_dsn
        self.app_dsn = app_dsn


def env_or_skip(name: str) -> str:
    value = os.environ.get(name)
    if value is None:
        pytest.skip(f"{name} is not configured")
    return value


@pytest.fixture(scope="module")
def live_module_registry_database() -> LiveModuleRegistryDatabase:
    migration_dsn = env_or_skip("SUITE_MIGRATION_DATABASE_DSN")
    app_dsn = env_or_skip("SUITE_DATABASE_DSN")
    worker_dsn = env_or_skip("SUITE_WORKER_DATABASE_DSN")
    apply_migrations(migration_dsn)
    return LiveModuleRegistryDatabase(migration_dsn=migration_dsn, app_dsn=app_dsn, worker_dsn=worker_dsn)


@pytest.fixture(scope="module")
def live_source_object_detail_database() -> LiveSourceObjectDetailDatabase:
    migration_dsn = env_or_skip("SUITE_MIGRATION_DATABASE_DSN")
    app_dsn = env_or_skip("SUITE_DATABASE_DSN")
    apply_migrations(migration_dsn)
    return LiveSourceObjectDetailDatabase(migration_dsn=migration_dsn, app_dsn=app_dsn)


def knowledge_base_source_record_for_api_write() -> SourceObjectRecord:
    text = "Backup restore runbook source content v2."
    content = text.encode("utf-8")
    draft = SourceObjectMetadata(
        tenant_id="tenant-demo",
        object_id="kb-article-version-backup-runbook-v2-demo",
        object_type=SourceObjectType.WIKI,
        version_id="v2",
        title="Backup Restore Runbook v2",
        owner_principal_id="user-demo",
        created_by="tenant-admin-demo",
        created_at_utc="2026-06-12T09:00:00Z",
        updated_at_utc="2026-06-12T09:00:00Z",
        classification=DataClass.INTERNAL,
        retention_policy_id="rp-standard",
        legal_hold_state=LegalHoldState.NONE,
        kms_key_ref="kms://tenant-demo/internal/v1",
        manifest_hash="sha256:" + "0" * 64,
        audit_chain_ref="audit:kb-article-version-backup-runbook-v2-demo",
        source_system="collabio",
        mime_type="text/plain",
        acl_hash="sha256:" + "a" * 64,
        acl_version=1,
        content_hash=sha256_bytes(content),
        content_byte_length=len(content),
        lifecycle_state=SourceLifecycleState.SAVED_VERSION,
    )
    return SourceObjectRecord(
        metadata=draft.model_copy(update={"manifest_hash": build_source_object_manifest_hash(draft)}),
        text=text,
    )


def workspace_source_record_for_detail_smoke(*, tenant_id: str, object_id: str, text: str) -> SourceObjectRecord:
    content = text.encode("utf-8")
    draft = SourceObjectMetadata(
        tenant_id=tenant_id,
        object_id=object_id,
        object_type=SourceObjectType.DOCUMENT,
        version_id="v1",
        title="Persistent detail smoke document",
        owner_principal_id=f"user-{tenant_id}",
        created_by=f"tenant-admin-{tenant_id}",
        created_at_utc="2026-06-17T08:00:00Z",
        updated_at_utc="2026-06-17T08:00:00Z",
        classification=DataClass.INTERNAL,
        retention_policy_id="rp-standard",
        legal_hold_state=LegalHoldState.NONE,
        kms_key_ref=f"kms://{tenant_id}/internal/v1",
        manifest_hash="sha256:" + "0" * 64,
        audit_chain_ref=f"audit:{object_id}",
        source_system="collabio",
        mime_type="text/plain",
        acl_hash="sha256:" + "b" * 64,
        acl_version=1,
        content_hash=sha256_bytes(content),
        content_byte_length=len(content),
        lifecycle_state=SourceLifecycleState.WORKING,
    )
    return SourceObjectRecord(
        metadata=draft.model_copy(update={"manifest_hash": build_source_object_manifest_hash(draft)}),
        text=text,
    )


def assert_metadata_first_preview_gate(slot: dict[str, Any]) -> dict[str, Any]:
    gate = dict(slot["gate"])
    assert gate["schema_version"] == "source_object_preview_gate.v1"
    assert gate["status"] == "metadata_ready_content_blocked"
    assert gate["metadata_first"] is True
    assert gate["raw_content_included"] is False
    assert gate["content_release_allowed"] is False
    assert "tenant_preview_policy_enabled" in gate["required_content_release_evidence"]
    assert "source_object_acl_checked" in gate["required_content_release_evidence"]
    assert "source_detail_audit_event" in gate["required_content_release_evidence"]
    assert "parser_sanitizer_evidence" in gate["required_content_release_evidence"]
    assert "human_content_release_confirmation" in gate["required_content_release_evidence"]
    assert "network_access_allowed=false" in gate["parser_boundaries"]
    assert "external_processes_allowed=false" in gate["parser_boundaries"]
    assert "strip_active_content=true" in gate["sanitizer_boundaries"]
    assert "external_resource_loading=false" in gate["sanitizer_boundaries"]
    return gate


DECOMMISSION_REOPEN_PAYLOAD = {
    "approval_reference": "approval:module-decommission-reopen",
    "reason": "decommission blocker has remediation evidence",
    "reopen_approval_ref": "approval:module-decommission-reopen",
    "blocker_remediation_evidence_ref": "decommission-remediation:evidence-1",
    "reopen_audit_evidence_ref": "audit:decommission-reopen-evidence-1",
}


def signed_jwt_for_api(subject: str = "user-demo", *, tenant_id: str = "tenant-demo") -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "iss": DEFAULT_JWT_ISSUER,
        "aud": DEFAULT_JWT_AUDIENCE,
        "sub": subject,
        "tenant_id": tenant_id,
        "iat": 1_780_000_000,
        "exp": 1_800_000_000,
        "roles": ["tenant-admin"],
        "readable_object_ids": ["secret-1"],
    }
    encoded_header = base64url_json(header)
    encoded_payload = base64url_json(payload)
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")
    signature = hmac.new(DEFAULT_DEV_JWT_SECRET.encode("utf-8"), signing_input, sha256).digest()
    return f"{encoded_header}.{encoded_payload}.{base64url_bytes(signature)}"


def base64url_json(payload: dict[str, Any]) -> str:
    return base64url_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def base64url_bytes(payload: bytes) -> str:
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def reset_module_registry() -> None:
    app.state.module_registry = default_module_registry()


def test_workspace_source_object_refs_parse_explicit_backend_config() -> None:
    refs = parse_workspace_source_object_refs(" doc-a:v1 , mail-a:v2 ")

    assert refs == (
        WorkspaceSourceObjectRef(object_id="doc-a", version_id="v1"),
        WorkspaceSourceObjectRef(object_id="mail-a", version_id="v2"),
    )
    with pytest.raises(ValueError, match="object_id:version_id"):
        parse_workspace_source_object_refs("doc-a")


def provision_and_enable_crm_accounts_for_demo() -> None:
    provision_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/provision",
        headers=DEMO_ADMIN_HEADERS,
        json={"approval_reference": "approval:module-provision", "reason": "prepare CRM accounts"},
    )
    assert provision_response.status_code == 200

    enable_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/enable",
        headers=DEMO_ADMIN_HEADERS,
        json={
            "approval_reference": "approval:module-enable",
            "reason": "activate CRM accounts",
            "enabled_features": {"crm_erp.crm.accounts": True},
        },
    )
    assert enable_response.status_code == 200


def provision_and_enable_crm_contacts_for_demo() -> None:
    provision_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/provision",
        headers=DEMO_ADMIN_HEADERS,
        json={"approval_reference": "approval:module-provision", "reason": "prepare CRM contacts"},
    )
    assert provision_response.status_code == 200

    enable_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/enable",
        headers=DEMO_ADMIN_HEADERS,
        json={
            "approval_reference": "approval:module-enable",
            "reason": "activate CRM contacts",
            "enabled_features": {"crm_erp.crm.contacts": True},
        },
    )
    assert enable_response.status_code == 200


def provision_and_enable_crm_activities_for_demo() -> None:
    provision_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/provision",
        headers=DEMO_ADMIN_HEADERS,
        json={"approval_reference": "approval:module-provision", "reason": "prepare CRM activities"},
    )
    assert provision_response.status_code == 200

    enable_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/enable",
        headers=DEMO_ADMIN_HEADERS,
        json={
            "approval_reference": "approval:module-enable",
            "reason": "activate CRM activities and notes",
            "enabled_features": {"crm_erp.crm.activities": True},
        },
    )
    assert enable_response.status_code == 200


def provision_and_enable_erp_products_for_demo() -> None:
    provision_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/provision",
        headers=DEMO_ADMIN_HEADERS,
        json={"approval_reference": "approval:module-provision", "reason": "prepare ERP products"},
    )
    assert provision_response.status_code == 200

    enable_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/enable",
        headers=DEMO_ADMIN_HEADERS,
        json={
            "approval_reference": "approval:module-enable",
            "reason": "activate ERP products",
            "enabled_features": {"crm_erp.erp.products": True},
        },
    )
    assert enable_response.status_code == 200


def provision_and_enable_knowledge_base_articles_for_demo() -> None:
    provision_response = client.post(
        "/v1/admin/tenant-modules/knowledge_base/provision",
        headers=DEMO_ADMIN_HEADERS,
        json={"approval_reference": "approval:module-provision", "reason": "prepare knowledge base articles"},
    )
    assert provision_response.status_code == 200

    enable_response = client.post(
        "/v1/admin/tenant-modules/knowledge_base/enable",
        headers=DEMO_ADMIN_HEADERS,
        json={
            "approval_reference": "approval:module-enable",
            "reason": "activate knowledge base articles",
            "enabled_features": {"knowledge_base.articles.read": True},
        },
    )
    assert enable_response.status_code == 200


def build_module_gate_probe_app(module_registry: InMemoryModuleRegistry) -> FastAPI:
    probe_app = FastAPI()
    probe_app.state.module_registry = module_registry
    probe_app.state.tenant_policy_repository = InMemoryTenantPolicyRepository.default()

    @probe_app.get("/normal", response_model=ModuleGateDecision)
    def normal_route(
        gate: Annotated[
            ModuleGateDecision,
            Depends(require_module_api_gate(module_id="crm_erp", feature_id="crm_erp.crm.accounts")),
        ],
    ) -> ModuleGateDecision:
        return gate

    @probe_app.get("/compliance", response_model=ModuleGateDecision)
    def compliance_route(
        gate: Annotated[
            ModuleGateDecision,
            Depends(require_module_api_gate(module_id="crm_erp", compliance=True)),
        ],
    ) -> ModuleGateDecision:
        return gate

    return probe_app


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_workspace_shell_serves_static_module_cockpit_ui() -> None:
    response = client.get("/workspace")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Module-Cockpit" in response.text
    assert "/workspace/assets/workspace.css" in response.text
    assert "/workspace/assets/workspace.js" in response.text
    assert "source-detail-panel" in response.text
    assert "Flow Readiness" in response.text
    assert "Arbeitskorb" in response.text
    assert "work-item-list" in response.text
    assert "work-evidence-panel" in response.text
    assert "mvp-readiness-panel" in response.text
    assert "snapshot-button" in response.text
    assert "metadata-ready-count" in response.text
    assert "metadata_only" in response.text
    assert "Board pack draft source content" not in response.text
    assert "Welcome message source" not in response.text


def test_workspace_shell_assets_are_served_and_call_cockpit_api_with_safe_actions() -> None:
    css_response = client.get("/workspace/assets/workspace.css")
    js_response = client.get("/workspace/assets/workspace.js")

    assert css_response.status_code == 200
    assert "workspace-shell" in css_response.text
    assert "detail-panel" in css_response.text
    assert ".detail-panel.denied" in css_response.text
    assert ".detail-panel.not-found" in css_response.text
    assert ".readiness-band" in css_response.text
    assert ".readiness-cell" in css_response.text
    assert ".mvp-readiness-panel" in css_response.text
    assert ".mvp-readiness-grid" in css_response.text
    assert ".mvp-readiness-decision" in css_response.text
    assert ".foundation-gap-plan" in css_response.text
    assert ".foundation-gap-action" in css_response.text
    assert ".foundation-gap-controls" in css_response.text
    assert ".foundation-gap-evidence-brief" in css_response.text
    assert ".foundation-gap-confirmation-brief" in css_response.text
    assert ".foundation-gap-content-release-brief" in css_response.text
    assert ".workspace-actions" in css_response.text
    assert ".work-item-list" in css_response.text
    assert ".work-evidence-panel" in css_response.text
    assert ".work-evidence-grid" in css_response.text
    assert "gradient" not in css_response.text.lower()
    assert js_response.status_code == 200
    assert "/v1/platform/cockpit" in js_response.text
    assert "/v1/platform/cockpit/mvp-snapshot" in js_response.text
    assert "downloadMvpSnapshot" in js_response.text
    assert "collabio-mvp-snapshot-" in js_response.text
    assert "JSON.stringify(body, null, 2)" in js_response.text
    assert "/v1/source-objects/" in js_response.text
    assert "/metadata" in js_response.text
    assert "Zugriff verweigert" in js_response.text
    assert "Nicht gefunden" in js_response.text
    assert "Preview Slots" in js_response.text
    assert "Flow Readiness" in js_response.text
    assert "metadata_ready_preview_decision_pending" in js_response.text
    assert "metadata_ready_preview_blocked" in js_response.text
    assert "metadata_only_no_source_content" in js_response.text
    assert "work_items" in js_response.text
    assert "work_item_operational_summary" in js_response.text
    assert "mvp_readiness_summary" in js_response.text
    assert "mvp_readiness_decision" in js_response.text
    assert "foundation_gap_actions" in js_response.text
    assert "renderMvpReadinessSummary" in js_response.text
    assert "renderMvpReadinessDecision" in js_response.text
    assert "data-mvp-readiness-decision" in js_response.text
    assert "metadata_only_productive_path" in js_response.text
    assert "backup_failover_gate_status" in js_response.text
    assert "renderFoundationGapActionPlan" in js_response.text
    assert "foundationGapEvidenceBrief" in js_response.text
    assert "foundationGapConfirmationBrief" in js_response.text
    assert "foundationGapContentReleaseBrief" in js_response.text
    assert "data-confirmation-brief" in js_response.text
    assert "data-content-release-brief" in js_response.text
    assert "content_release_brief" in js_response.text
    assert "metadata_only_mvp_ready" in js_response.text
    assert "next_confirmation_action" in js_response.text
    assert "evidence_required_now" in js_response.text
    assert "policy_blocking_reasons" in js_response.text
    assert "executeFoundationGapAction" in js_response.text
    assert "executeFoundationModuleActions" in js_response.text
    assert "complete_module_activation_work_items" in js_response.text
    assert "Module Actions" in js_response.text
    assert "No domain data, persistent tasks, automations or content release requested." in js_response.text
    assert "data-foundation-gap-id" in js_response.text
    assert "data-foundation-gap-action" in js_response.text
    assert "Pending Decisions" in js_response.text
    assert "skipConfirmation" in js_response.text
    assert "mvpReadinessTagList" in js_response.text
    assert "foundation_gaps" in js_response.text
    assert "deferred_items" in js_response.text
    assert "renderWorkItemOperationalSummary" in js_response.text
    assert "workEvidenceMetric" in js_response.text
    assert "workEvidenceTagList" in js_response.text
    assert "renderWorkItems" in js_response.text
    assert "data-work-item-id" in js_response.text
    assert "data-work-ui-action" in js_response.text
    assert "primary_action_hint" in js_response.text
    assert "secondary_action_hints" in js_response.text
    assert "required_roles" in js_response.text
    assert "data-work-required-roles" in js_response.text
    assert "data-work-state-gate" in js_response.text
    assert "data-work-requires-confirmation" in js_response.text
    assert "aria-disabled" in js_response.text
    assert "Erforderliche Rolle fehlt im aktuellen Kontext" in js_response.text
    assert "canUseAnyRole" in js_response.text
    assert "Action-Hint verletzt metadata-only Arbeitskorb-Regeln" in js_response.text
    assert "persistent_task_created=" in js_response.text
    assert "content_included=" in js_response.text
    assert "destructive=" in js_response.text
    assert "external=" in js_response.text
    assert "State signals" in js_response.text
    assert ".guided-preview-action" in css_response.text
    assert "guided-preview-decision" in js_response.text
    assert "guided_preview_decision" in js_response.text
    assert "/preview-renderer-runs" in js_response.text
    assert "/preview-decisions" in js_response.text
    assert "renderer_sandbox_evidence_ref" in js_response.text
    assert "human_confirmation_reference" in js_response.text
    assert "window.confirm" in js_response.text
    assert "no source content, rendered content or raw payload" in js_response.text
    assert "content_release_allowed bleibt policy-gesteuert blockiert" in js_response.text
    assert "metadata_ready_content_blocked" in js_response.text
    assert "content_release_allowed=false" in js_response.text
    assert "content_included=false" in js_response.text
    assert "/v1/admin/tenant-modules/" in js_response.text
    assert "X-Tenant-Id" in js_response.text
    assert "window.confirm" in js_response.text
    assert "approval:workspace-cockpit" in js_response.text
    assert "source-object=" in js_response.text
    assert "content_included" in js_response.text
    assert "metadata_only" in js_response.text
    assert "Board pack draft source content" not in js_response.text
    assert "Welcome message source" not in js_response.text


def test_tenant_data_endpoints_require_request_context() -> None:
    response = client.post("/v1/ai/inference", json={"input_text": "Bitte zusammenfassen."})
    assert response.status_code == 401
    assert response.json()["detail"] == "Tenant context requires X-Tenant-Id and X-User-Id headers"


def test_dev_header_tenant_context_is_disabled_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUITE_ENV", "production")
    monkeypatch.setenv("SUITE_AUTH_MODE", "dev")

    response = client.get("/v1/platform/modules", headers=DEMO_HEADERS)

    assert response.status_code == 503
    assert response.json()["detail"] == "Dev header tenant context is disabled in production"


def test_jwt_auth_mode_requires_bearer_token_and_ignores_dev_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUITE_AUTH_MODE", "jwt")

    response = client.get("/v1/platform/modules", headers=DEMO_HEADERS)

    assert response.status_code == 401
    assert response.json()["detail"] == "Bearer authorization header required"


def test_jwt_auth_mode_uses_signed_token_and_server_side_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUITE_AUTH_MODE", "jwt")
    forged_headers = {
        **DEMO_ADMIN_HEADERS,
        "X-Tenant-Id": "tenant-unknown",
        "X-Readable-Object-Ids": "doc-1,mail-1,secret-1",
        "Authorization": f"Bearer {signed_jwt_for_api()}",
    }

    response = client.get("/v1/platform/modules", headers=forged_headers)

    assert response.status_code == 200
    assert response.json()["tenant_id"] == "tenant-demo"

    admin_response = client.get("/v1/admin/tenant-policy", headers=forged_headers)
    assert admin_response.status_code == 403
    assert admin_response.json()["detail"] == "Tenant admin role required"

    inference_response = client.post(
        "/v1/ai/inference",
        headers=forged_headers,
        json={"input_text": "Bitte zusammenfassen.", "source_object_ids": ["secret-1"]},
    )
    assert inference_response.status_code == 403
    assert inference_response.json()["detail"] == "User cannot read one or more requested sources"


def test_unknown_tenant_policy_is_blocked() -> None:
    response = client.post(
        "/v1/ai/inference",
        headers={**DEMO_HEADERS, "X-Tenant-Id": "tenant-unknown"},
        json={"input_text": "Bitte zusammenfassen."},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Tenant policy is not available"


def test_platform_modules_discovery_requires_request_context() -> None:
    response = client.get("/v1/platform/modules")

    assert response.status_code == 401
    assert response.json()["detail"] == "Tenant context requires X-Tenant-Id and X-User-Id headers"


def test_platform_modules_discovery_returns_tenant_scoped_module_metadata() -> None:
    reset_module_registry()

    response = client.get("/v1/platform/modules", headers=DEMO_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant-demo"
    assert len(body["modules"]) == 2
    modules = {module["module_id"]: module for module in body["modules"]}
    crm_module = modules["crm_erp"]
    assert crm_module["display_name"] == "CRM/ERP"
    assert crm_module["status"] == "available"
    assert crm_module["normal_use_enabled"] is False
    assert crm_module["compliance_access_allowed"] is False
    assert crm_module["enabled_features"]["crm_erp.legacy_import.sqlserver"] is False

    kb_module = modules["knowledge_base"]
    assert kb_module["display_name"] == "Knowledge Base"
    assert kb_module["status"] == "available"
    assert kb_module["normal_use_enabled"] is False
    assert kb_module["enabled_features"]["knowledge_base.articles.read"] is True
    assert kb_module["enabled_features"]["knowledge_base.articles.write"] is False

    for module in body["modules"]:
        assert "audit_chain_ref" not in module
        assert "policy_snapshot_hash" not in module
        assert "changed_by" not in module


def test_platform_cockpit_requires_request_context() -> None:
    response = client.get("/v1/platform/cockpit")

    assert response.status_code == 401
    assert response.json()["detail"] == "Tenant context requires X-Tenant-Id and X-User-Id headers"


def test_platform_cockpit_returns_modules_and_authorized_document_mail_source_flows() -> None:
    reset_module_registry()
    previous_ledger = app.state.source_object_preview_decision_ledger
    app.state.source_object_preview_decision_ledger = InMemorySourceObjectPreviewDecisionLedger()
    starting_event_count = len(app.state.audit_logger.events)

    try:
        response = client.get("/v1/platform/cockpit", headers=DEMO_HEADERS)
    finally:
        app.state.source_object_preview_decision_ledger = previous_ledger

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant-demo"
    assert body["schema_version"] == "product_cockpit.v1"
    assert body["result_contract"] == "metadata_only_authorized_source_object_flow"
    modules = {module["module_id"]: module for module in body["modules"]}
    assert modules["knowledge_base"]["status"] == "available"
    assert modules["knowledge_base"]["next_action"] == "provision_module"
    assert modules["knowledge_base"]["continuity_domain"] == "knowledge_base_content"
    assert modules["crm_erp"]["continuity_domain"] == "crm_erp_business_records"

    work_items = body["work_items"]
    assert body["work_item_count"] == 4
    assert len(work_items) == 4
    assert all(item["schema_version"] == "product_cockpit_work_item.v1" for item in work_items)
    assert all(item["persistent_task_created"] is False for item in work_items)
    assert all(item["content_included"] is False for item in work_items)
    source_work_items = [item for item in work_items if item["scope"] == "source_object_flow"]
    module_work_items = [item for item in work_items if item["scope"] == "module"]
    assert len(source_work_items) == 2
    assert len(module_work_items) == 2
    assert {item["priority"] for item in source_work_items} == {"high"}
    assert {item["action"] for item in source_work_items} == {"request_preview_decision"}
    assert {item["source_object_id"] for item in source_work_items} == {"doc-1", "mail-1"}
    assert {item["module_id"] for item in module_work_items} == {"crm_erp", "knowledge_base"}
    assert {item["priority"] for item in module_work_items} == {"medium"}
    assert {item["action"] for item in module_work_items} == {"provision_module"}
    assert body["work_item_operational_summary"] == {
        "schema_version": "product_cockpit_work_item_operational_summary.v1",
        "work_item_count": 4,
        "action_hint_count": 6,
        "module_work_item_count": 2,
        "source_object_flow_work_item_count": 2,
        "high_priority_work_item_count": 2,
        "medium_priority_work_item_count": 2,
        "low_priority_work_item_count": 0,
        "confirmation_required_action_count": 4,
        "role_required_action_count": 2,
        "admin_role_required_action_count": 2,
        "metadata_only_action_count": 6,
        "content_included_action_count": 0,
        "persistent_task_created_count": 0,
        "destructive_action_count": 0,
        "external_side_effect_action_count": 0,
        "state_transition_signal_count": 2,
        "ui_actions": ["guided_preview_decision", "module_provision", "open_flow"],
        "state_gates": [
            "module_status_available_and_admin_role",
            "source_object_read_access_and_preview_gate_available",
            "source_object_read_access_checked",
        ],
        "role_gates": ["context", "tenant-admin,security-admin"],
        "state_transition_signals": ["module:provision_module", "source_object_flow:request_preview_decision"],
        "content_included": False,
    }
    assert body["mvp_readiness_summary"] == {
        "schema_version": "product_cockpit_mvp_readiness_summary.v1",
        "entrypoint_route": "/workspace",
        "mvp_entry_ready": True,
        "ready_surface_count": 4,
        "ready_surfaces": ["module_registry", "work_item_queue", "source_object_flows", "metadata_detail"],
        "foundation_gap_count": 4,
        "foundation_gaps": [
            "preview_decisions_pending",
            "module_activation_work_items_open",
            "human_confirmation_required",
            "content_release_gate_blocks_content",
        ],
        "deferred_item_count": 5,
        "deferred_items": [
            "office_editor_suite",
            "mail_client_runtime",
            "persistent_tasks_and_ticketing",
            "lms_time_tracking_activity_modules",
            "full_content_preview_rendering",
        ],
        "next_foundation_action": "resolve_preview_decision_work_items",
        "module_count": 2,
        "work_item_count": 4,
        "source_object_flow_count": 2,
        "detail_surface_ready": True,
        "content_included": False,
        "persistent_task_created": False,
    }
    assert body["mvp_readiness_decision"] == {
        "schema_version": "product_cockpit_mvp_readiness_decision.v1",
        "decision": "metadata_only_mvp_ready_with_deferred_content_release",
        "metadata_only_productive_path": True,
        "entrypoint_route": "/workspace",
        "snapshot_route": "/v1/platform/cockpit/mvp-snapshot",
        "role_gate_status": "role_gated_actions_visible",
        "required_roles": ["security-admin", "tenant-admin"],
        "audit_gate_status": "audit_visible",
        "audit_visible_flow_count": 2,
        "audit_required_flow_count": 2,
        "backup_failover_gate_status": "metadata_only_no_state_change",
        "backup_restore_verified_flow_count": 0,
        "backup_restore_deferred_flow_count": 2,
        "module_gate_status": "module_activation_required",
        "module_count": 2,
        "enabled_module_ids": [],
        "module_action_required_ids": ["crm_erp", "knowledge_base"],
        "foundation_gap_status": "work_items_open",
        "active_foundation_gap_ids": [
            "preview_decisions_pending",
            "module_activation_work_items_open",
            "human_confirmation_required",
            "content_release_gate_blocks_content",
        ],
        "ready_foundation_gap_ids": ["preview_decisions_pending", "module_activation_work_items_open"],
        "deferred_foundation_gap_ids": ["human_confirmation_required", "content_release_gate_blocks_content"],
        "content_gate_status": "deferred_metadata_only_ready",
        "next_foundation_action": "resolve_preview_decision_work_items",
        "content_included": False,
        "persistent_task_created": False,
        "automation_created": False,
    }
    assert body["foundation_gap_action_count"] == 4
    assert body["foundation_gap_actions"] == [
        {
            "schema_version": "product_cockpit_foundation_gap_action.v1",
            "priority": 1,
            "gap_id": "preview_decisions_pending",
            "status": "ready",
            "next_action": "resolve_preview_decision_work_items",
            "covered_by_work_item_ids": [
                "source-object-flow:document:doc-1:v1:request_preview_decision",
                "source-object-flow:mail:mail-1:v1:request_preview_decision",
            ],
            "source_object_ids": ["doc-1", "mail-1"],
            "module_ids": [],
            "ui_actions": ["guided_preview_decision", "open_flow"],
            "required_roles": [],
            "requires_confirmation": True,
            "metadata_only": True,
            "content_included": False,
            "persistent_task_created": False,
            "automation_created": False,
            "deferred_reason": None,
            "evidence_brief": None,
            "confirmation_brief": None,
            "content_release_brief": None,
        },
        {
            "schema_version": "product_cockpit_foundation_gap_action.v1",
            "priority": 2,
            "gap_id": "module_activation_work_items_open",
            "status": "ready",
            "next_action": "complete_module_activation_work_items",
            "covered_by_work_item_ids": [
                "module:crm_erp:provision_module",
                "module:knowledge_base:provision_module",
            ],
            "source_object_ids": [],
            "module_ids": ["crm_erp", "knowledge_base"],
            "ui_actions": ["module_provision"],
            "required_roles": ["security-admin", "tenant-admin"],
            "requires_confirmation": True,
            "metadata_only": True,
            "content_included": False,
            "persistent_task_created": False,
            "automation_created": False,
            "deferred_reason": None,
            "evidence_brief": None,
            "confirmation_brief": None,
            "content_release_brief": None,
        },
        {
            "schema_version": "product_cockpit_foundation_gap_action.v1",
            "priority": 3,
            "gap_id": "human_confirmation_required",
            "status": "deferred",
            "next_action": "covered_by_specific_foundation_gap_actions",
            "covered_by_work_item_ids": [
                "source-object-flow:document:doc-1:v1:request_preview_decision",
                "source-object-flow:mail:mail-1:v1:request_preview_decision",
                "module:crm_erp:provision_module",
                "module:knowledge_base:provision_module",
            ],
            "source_object_ids": ["doc-1", "mail-1"],
            "module_ids": ["crm_erp", "knowledge_base"],
            "ui_actions": ["guided_preview_decision", "module_provision", "open_flow"],
            "required_roles": ["security-admin", "tenant-admin"],
            "requires_confirmation": False,
            "metadata_only": True,
            "content_included": False,
            "persistent_task_created": False,
            "automation_created": False,
            "deferred_reason": "human_confirmations_are_covered_by_specific_foundation_gap_actions",
            "evidence_brief": None,
            "confirmation_brief": {
                "schema_version": "product_cockpit_foundation_gap_confirmation_brief.v1",
                "confirmation_work_item_ids": [
                    "source-object-flow:document:doc-1:v1:request_preview_decision",
                    "source-object-flow:mail:mail-1:v1:request_preview_decision",
                    "module:crm_erp:provision_module",
                    "module:knowledge_base:provision_module",
                ],
                "covered_by_specific_gap_work_item_ids": [
                    "source-object-flow:document:doc-1:v1:request_preview_decision",
                    "source-object-flow:mail:mail-1:v1:request_preview_decision",
                    "module:crm_erp:provision_module",
                    "module:knowledge_base:provision_module",
                ],
                "standalone_work_item_ids": [],
                "covering_gap_ids": ["preview_decisions_pending", "module_activation_work_items_open"],
                "next_confirmation_action": "use_specific_foundation_gap_actions_first",
                "requires_separate_foundation_action": False,
                "content_included": False,
                "persistent_task_created": False,
                "automation_created": False,
            },
            "content_release_brief": None,
        },
        {
            "schema_version": "product_cockpit_foundation_gap_action.v1",
            "priority": 4,
            "gap_id": "content_release_gate_blocks_content",
            "status": "deferred",
            "next_action": "keep_content_release_gate_deferred_for_mvp",
            "covered_by_work_item_ids": [],
            "source_object_ids": ["doc-1", "mail-1"],
            "module_ids": [],
            "ui_actions": [],
            "required_roles": [],
            "requires_confirmation": False,
            "metadata_only": True,
            "content_included": False,
            "persistent_task_created": False,
            "automation_created": False,
            "deferred_reason": "content_release_requires_policy_viewer_runtime_after_mvp",
            "evidence_brief": None,
            "confirmation_brief": None,
            "content_release_brief": {
                "schema_version": "product_cockpit_foundation_gap_content_release_brief.v1",
                "blocked_flow_ids": ["document:doc-1:v1", "mail:mail-1:v1"],
                "blocked_source_object_ids": ["doc-1", "mail-1"],
                "content_release_blocked_count": 2,
                "content_release_allowed_count": 0,
                "content_included_count": 0,
                "preview_decision_pending_count": 2,
                "preview_decision_blocked_count": 0,
                "preview_evidence_complete_but_content_blocked_count": 0,
                "metadata_only_mvp_ready": True,
                "deferred_dependencies": [
                    "content_release_gate_policy_review",
                    "viewer_adapter_runtime",
                    "full_content_preview_rendering",
                ],
                "next_release_action": "keep_content_release_gate_deferred_for_mvp",
                "blocking_reasons": [
                    "preview_decision_not_requested",
                    "content_release_requires_policy_acl_audit_and_sanitizer_evidence",
                    "mail_body_release_requires_policy_acl_audit_and_sanitizer_evidence",
                    "attachment_opening_requires_scan_and_explicit_confirmation",
                ],
                "content_release_allowed": False,
                "content_included": False,
                "persistent_task_created": False,
                "automation_created": False,
            },
        },
    ]
    assert all(
        item["primary_action_hint"]["schema_version"] == "product_cockpit_work_item_action_hint.v1"
        for item in work_items
    )
    assert all(item["primary_action_hint"]["metadata_only"] is True for item in work_items)
    assert all(item["primary_action_hint"]["content_included"] is False for item in work_items)
    assert all(item["primary_action_hint"]["persistent_task_created"] is False for item in work_items)
    assert all(item["primary_action_hint"]["destructive"] is False for item in work_items)
    assert all(item["primary_action_hint"]["external_side_effect"] is False for item in work_items)
    doc_work_item = next(item for item in source_work_items if item["source_object_id"] == "doc-1")
    doc_hint = doc_work_item["primary_action_hint"]
    assert doc_hint["ui_action"] == "guided_preview_decision"
    assert doc_hint["label"] == "Evidence + Decision"
    assert doc_hint["api_method"] == "POST"
    assert doc_hint["api_action"] == "guided_preview_decision"
    assert doc_hint["api_path_templates"] == [
        "/v1/source-objects/{source_object_id}/versions/{source_version_id}/preview-renderer-runs",
        "/v1/source-objects/{source_object_id}/versions/{source_version_id}/preview-decisions",
    ]
    assert doc_hint["required_roles"] == []
    assert doc_hint["state_gate"] == "source_object_read_access_and_preview_gate_available"
    assert doc_hint["requires_confirmation"] is True
    assert doc_hint["compliance_relevant"] is True
    assert doc_work_item["secondary_action_hints"][0]["ui_action"] == "open_flow"
    assert doc_work_item["secondary_action_hints"][0]["requires_confirmation"] is False
    assert doc_work_item["secondary_action_hints"][0]["target_route"].startswith(
        "/workspace#source-object=document%3Adoc-1%3Av1"
    )
    module_hint = module_work_items[0]["primary_action_hint"]
    assert module_hint["ui_action"] == "module_provision"
    assert module_hint["api_method"] == "POST"
    assert module_hint["api_action"] == "provision"
    assert module_hint["required_roles"] == ["tenant-admin", "security-admin"]
    assert module_hint["state_gate"] == "module_status_available_and_admin_role"
    assert module_hint["requires_confirmation"] is True
    assert module_hint["compliance_relevant"] is True

    flows = {flow["source_object_id"]: flow for flow in body["source_object_flows"]}
    assert set(flows) == {"doc-1", "mail-1"}
    assert flows["doc-1"]["origin"] == "document"
    assert flows["doc-1"]["source_object_type"] == "document"
    assert flows["mail-1"]["origin"] == "mail"
    assert flows["mail-1"]["source_object_type"] == "mail"
    assert flows["mail-1"]["data_classification"] == "personal"
    assert flows["doc-1"]["preview_slots"][0]["surface"] == "office.document.preview"
    assert flows["mail-1"]["preview_slots"][0]["surface"] == "mail.message.preview"
    document_gate = assert_metadata_first_preview_gate(flows["doc-1"]["preview_slots"][0])
    mail_gate = assert_metadata_first_preview_gate(flows["mail-1"]["preview_slots"][0])
    assert document_gate["policy_id"] == "preview-policy.document.metadata-first.v1"
    assert document_gate["parser_profile_id"] == "rich-document-parser-worker:1"
    assert mail_gate["policy_id"] == "preview-policy.mail.metadata-first.v1"
    assert mail_gate["parser_profile_id"] == "policy-enforced-parser-worker:1"
    assert "subject" in mail_gate["mail_header_metadata_fields"]
    assert "filename" in mail_gate["attachment_metadata_fields"]
    assert "attachment_opening_requires_scan_and_explicit_confirmation" in mail_gate["blocking_reasons"]
    assert all(
        slot["render_contract"] == "metadata_only_no_source_content"
        for flow in flows.values()
        for slot in flow["preview_slots"]
    )
    assert all(slot["content_included"] is False for flow in flows.values() for slot in flow["preview_slots"])
    assert body["flow_readiness_summary"] == {
        "schema_version": "product_cockpit_readiness_summary.v1",
        "metadata_ready_flow_count": 2,
        "access_checked_flow_count": 2,
        "audit_visible_flow_count": 2,
        "preview_decision_pending_count": 2,
        "preview_decision_blocked_count": 0,
        "preview_evidence_complete_but_content_blocked_count": 0,
        "content_release_allowed_count": 0,
        "content_included_count": 0,
    }
    assert all(flow["access_checked"] is True for flow in flows.values())
    assert all(flow["content_included"] is False for flow in flows.values())
    assert all(
        flow["readiness"]["schema_version"] == "product_cockpit_source_object_flow_readiness.v1"
        for flow in flows.values()
    )
    assert all(flow["readiness"]["status"] == "metadata_ready_preview_decision_pending" for flow in flows.values())
    assert all(flow["readiness"]["source_detail_ready"] is True for flow in flows.values())
    assert all(flow["readiness"]["access_checked"] is True for flow in flows.values())
    assert all(flow["readiness"]["audit_visible"] is True for flow in flows.values())
    assert all(flow["readiness"]["cockpit_audit_event_id"] == body["audit_event_id"] for flow in flows.values())
    assert all(flow["readiness"]["preview_decision_available"] is False for flow in flows.values())
    assert all(flow["readiness"]["content_release_allowed"] is False for flow in flows.values())
    assert all(flow["readiness"]["content_included"] is False for flow in flows.values())
    assert all(flow["readiness"]["next_action"] == "request_preview_decision" for flow in flows.values())
    assert all("preview_decision_not_requested" in flow["readiness"]["blocking_reasons"] for flow in flows.values())
    assert all(f"audit:{body['audit_event_id']}" in flow["readiness"]["evidence_refs"] for flow in flows.values())
    assert all(flow["manifest_hash"].startswith("sha256:") for flow in flows.values())
    assert all(flow["content_hash"].startswith("sha256:") for flow in flows.values())
    assert "Board pack draft source content" not in json.dumps(body)
    assert "Welcome message source" not in json.dumps(body)

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert new_events[-1].event_type == "platform.module_cockpit.read"
    assert new_events[-1].source_object_ids == ["doc-1", "mail-1"]
    assert new_events[-1].metadata["result_contract"] == "metadata_only"
    assert new_events[-1].metadata["content_included"] is False
    assert new_events[-1].metadata["access_checked"] is True
    assert new_events[-1].metadata["preview_decision_pending_count"] == 2
    assert new_events[-1].metadata["preview_decision_blocked_count"] == 0
    assert new_events[-1].metadata["work_item_count"] == 4
    assert new_events[-1].metadata["work_item_action_hint_count"] == 6
    assert new_events[-1].metadata["high_priority_work_item_count"] == 2
    assert new_events[-1].metadata["confirmation_required_work_item_count"] == 4
    assert new_events[-1].metadata["role_required_work_item_action_count"] == 2
    assert new_events[-1].metadata["admin_role_required_work_item_action_count"] == 2
    assert new_events[-1].metadata["work_item_state_transition_signal_count"] == 2
    assert new_events[-1].metadata["work_item_ui_actions"] == (
        "guided_preview_decision",
        "module_provision",
        "open_flow",
    )
    assert new_events[-1].metadata["work_item_state_gates"] == (
        "module_status_available_and_admin_role",
        "source_object_read_access_and_preview_gate_available",
        "source_object_read_access_checked",
    )
    assert new_events[-1].metadata["work_item_role_gates"] == ("context", "tenant-admin,security-admin")
    assert new_events[-1].metadata["work_item_state_transition_signals"] == (
        "module:provision_module",
        "source_object_flow:request_preview_decision",
    )
    assert new_events[-1].metadata["work_item_persistent_task_created_count"] == 0
    assert new_events[-1].metadata["work_item_content_included_action_count"] == 0
    assert new_events[-1].metadata["work_item_destructive_action_count"] == 0
    assert new_events[-1].metadata["work_item_external_side_effect_action_count"] == 0
    assert new_events[-1].metadata["mvp_entry_ready"] is True
    assert new_events[-1].metadata["mvp_ready_surfaces"] == (
        "module_registry",
        "work_item_queue",
        "source_object_flows",
        "metadata_detail",
    )
    assert new_events[-1].metadata["mvp_foundation_gap_count"] == 4
    assert new_events[-1].metadata["mvp_foundation_gaps"] == (
        "preview_decisions_pending",
        "module_activation_work_items_open",
        "human_confirmation_required",
        "content_release_gate_blocks_content",
    )
    assert new_events[-1].metadata["mvp_deferred_items"] == (
        "office_editor_suite",
        "mail_client_runtime",
        "persistent_tasks_and_ticketing",
        "lms_time_tracking_activity_modules",
        "full_content_preview_rendering",
    )
    assert new_events[-1].metadata["mvp_next_foundation_action"] == "resolve_preview_decision_work_items"
    assert new_events[-1].metadata["mvp_readiness_decision"] == "metadata_only_mvp_ready_with_deferred_content_release"
    assert new_events[-1].metadata["mvp_metadata_only_productive_path"] is True
    assert new_events[-1].metadata["mvp_role_gate_status"] == "role_gated_actions_visible"
    assert new_events[-1].metadata["mvp_audit_gate_status"] == "audit_visible"
    assert new_events[-1].metadata["mvp_backup_failover_gate_status"] == "metadata_only_no_state_change"
    assert new_events[-1].metadata["mvp_module_gate_status"] == "module_activation_required"
    assert new_events[-1].metadata["mvp_content_gate_status"] == "deferred_metadata_only_ready"
    assert new_events[-1].metadata["foundation_gap_action_count"] == 4
    assert new_events[-1].metadata["foundation_gap_action_ids"] == (
        "preview_decisions_pending",
        "module_activation_work_items_open",
        "human_confirmation_required",
        "content_release_gate_blocks_content",
    )
    assert new_events[-1].metadata["foundation_gap_ready_action_count"] == 2
    assert new_events[-1].metadata["foundation_gap_deferred_action_count"] == 2
    assert new_events[-1].metadata["foundation_gap_content_included"] is False
    assert new_events[-1].metadata["foundation_gap_persistent_task_created"] is False
    assert new_events[-1].metadata["foundation_gap_automation_created"] is False
    assert new_events[-1].metadata["mvp_content_included"] is False
    assert new_events[-1].metadata["mvp_persistent_task_created"] is False


def test_platform_cockpit_mvp_snapshot_requires_request_context() -> None:
    response = client.get("/v1/platform/cockpit/mvp-snapshot")

    assert response.status_code == 401
    assert response.json()["detail"] == "Tenant context requires X-Tenant-Id and X-User-Id headers"


def test_platform_cockpit_mvp_snapshot_exports_metadata_only_review_artifact() -> None:
    reset_module_registry()
    previous_ledger = app.state.source_object_preview_decision_ledger
    app.state.source_object_preview_decision_ledger = InMemorySourceObjectPreviewDecisionLedger()
    starting_event_count = len(app.state.audit_logger.events)

    try:
        response = client.get("/v1/platform/cockpit/mvp-snapshot", headers=DEMO_HEADERS)
    finally:
        app.state.source_object_preview_decision_ledger = previous_ledger

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant-demo"
    assert body["schema_version"] == "product_cockpit_mvp_snapshot.v1"
    assert body["result_contract"] == "metadata_only_mvp_handover_snapshot"
    assert body["snapshot_route"] == "/v1/platform/cockpit/mvp-snapshot"
    assert body["cockpit_route"] == "/v1/platform/cockpit"
    assert body["entrypoint_route"] == "/workspace"
    assert body["generated_from_cockpit_audit_event_id"]
    assert body["audit_event_id"] != body["generated_from_cockpit_audit_event_id"]
    assert body["review_sections"] == [
        "mvp_readiness_summary",
        "mvp_readiness_decision",
        "flow_readiness_summary",
        "work_item_operational_summary",
        "module_refs",
        "source_object_flow_refs",
        "work_item_refs",
        "foundation_gap_actions",
    ]
    assert body["mvp_readiness_summary"]["foundation_gaps"] == [
        "preview_decisions_pending",
        "module_activation_work_items_open",
        "human_confirmation_required",
        "content_release_gate_blocks_content",
    ]
    assert body["mvp_readiness_summary"]["deferred_items"] == [
        "office_editor_suite",
        "mail_client_runtime",
        "persistent_tasks_and_ticketing",
        "lms_time_tracking_activity_modules",
        "full_content_preview_rendering",
    ]
    assert body["mvp_readiness_decision"]["decision"] == "metadata_only_mvp_ready_with_deferred_content_release"
    assert body["mvp_readiness_decision"]["metadata_only_productive_path"] is True
    assert body["mvp_readiness_decision"]["role_gate_status"] == "role_gated_actions_visible"
    assert body["mvp_readiness_decision"]["audit_gate_status"] == "audit_visible"
    assert body["mvp_readiness_decision"]["backup_failover_gate_status"] == "metadata_only_no_state_change"
    assert body["mvp_readiness_decision"]["module_gate_status"] == "module_activation_required"
    assert body["mvp_readiness_decision"]["content_gate_status"] == "deferred_metadata_only_ready"
    assert body["mvp_readiness_decision"]["active_foundation_gap_ids"] == [
        "preview_decisions_pending",
        "module_activation_work_items_open",
        "human_confirmation_required",
        "content_release_gate_blocks_content",
    ]
    assert body["foundation_gap_action_count"] == 4
    assert [action["gap_id"] for action in body["foundation_gap_actions"]] == [
        "preview_decisions_pending",
        "module_activation_work_items_open",
        "human_confirmation_required",
        "content_release_gate_blocks_content",
    ]
    assert [action["status"] for action in body["foundation_gap_actions"]] == [
        "ready",
        "ready",
        "deferred",
        "deferred",
    ]
    assert all(action["content_included"] is False for action in body["foundation_gap_actions"])
    assert all(action["persistent_task_created"] is False for action in body["foundation_gap_actions"])
    assert all(action["automation_created"] is False for action in body["foundation_gap_actions"])
    assert body["foundation_gap_actions"][2]["next_action"] == "covered_by_specific_foundation_gap_actions"
    assert body["foundation_gap_actions"][2]["deferred_reason"] == (
        "human_confirmations_are_covered_by_specific_foundation_gap_actions"
    )
    assert body["foundation_gap_actions"][2]["confirmation_brief"]["covering_gap_ids"] == [
        "preview_decisions_pending",
        "module_activation_work_items_open",
    ]
    assert body["foundation_gap_actions"][2]["confirmation_brief"]["standalone_work_item_ids"] == []
    assert body["foundation_gap_actions"][2]["confirmation_brief"]["requires_separate_foundation_action"] is False
    assert body["foundation_gap_actions"][3]["deferred_reason"] == (
        "content_release_requires_policy_viewer_runtime_after_mvp"
    )
    content_release_brief = body["foundation_gap_actions"][3]["content_release_brief"]
    assert content_release_brief["schema_version"] == "product_cockpit_foundation_gap_content_release_brief.v1"
    assert content_release_brief["blocked_source_object_ids"] == ["doc-1", "mail-1"]
    assert content_release_brief["content_release_blocked_count"] == 2
    assert content_release_brief["preview_decision_pending_count"] == 2
    assert content_release_brief["metadata_only_mvp_ready"] is True
    assert content_release_brief["deferred_dependencies"] == [
        "content_release_gate_policy_review",
        "viewer_adapter_runtime",
        "full_content_preview_rendering",
    ]
    assert content_release_brief["content_included"] is False
    assert content_release_brief["persistent_task_created"] is False
    assert content_release_brief["automation_created"] is False
    assert body["next_foundation_action"] == "resolve_preview_decision_work_items"
    assert body["content_included"] is False
    assert body["persistent_task_created"] is False
    assert body["automation_created"] is False

    module_refs = {module["module_id"]: module for module in body["module_refs"]}
    assert set(module_refs) == {"crm_erp", "knowledge_base"}
    assert module_refs["knowledge_base"]["next_action"] == "provision_module"
    assert module_refs["crm_erp"]["continuity_domain"] == "crm_erp_business_records"

    flow_refs = {flow["source_object_id"]: flow for flow in body["source_object_flow_refs"]}
    assert set(flow_refs) == {"doc-1", "mail-1"}
    assert all(flow["content_included"] is False for flow in flow_refs.values())
    assert all(flow["readiness_status"] == "metadata_ready_preview_decision_pending" for flow in flow_refs.values())
    assert all(flow["next_action"] == "request_preview_decision" for flow in flow_refs.values())
    assert all(
        flow["cockpit_audit_event_id"] == body["generated_from_cockpit_audit_event_id"] for flow in flow_refs.values()
    )
    assert all(flow["evidence_ref_count"] > 0 for flow in flow_refs.values())

    assert len(body["work_item_refs"]) == 4
    assert {item["scope"] for item in body["work_item_refs"]} == {"module", "source_object_flow"}
    assert all(item["content_included"] is False for item in body["work_item_refs"])
    assert all(item["persistent_task_created"] is False for item in body["work_item_refs"])
    assert {item["primary_ui_action"] for item in body["work_item_refs"]} == {
        "guided_preview_decision",
        "module_provision",
    }
    assert "Board pack draft source content" not in json.dumps(body)
    assert "Welcome message source" not in json.dumps(body)

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert [event.event_type for event in new_events[-2:]] == [
        "platform.module_cockpit.read",
        "platform.mvp_snapshot.export",
    ]
    assert new_events[-1].source_object_ids == ["doc-1", "mail-1"]
    assert new_events[-1].metadata["result_contract"] == "metadata_only_mvp_handover_snapshot"
    assert (
        new_events[-1].metadata["generated_from_cockpit_audit_event_id"]
        == body["generated_from_cockpit_audit_event_id"]
    )
    assert new_events[-1].metadata["review_sections"] == tuple(body["review_sections"])
    assert new_events[-1].metadata["module_ref_count"] == 2
    assert new_events[-1].metadata["source_object_flow_ref_count"] == 2
    assert new_events[-1].metadata["work_item_ref_count"] == 4
    assert new_events[-1].metadata["foundation_gap_action_count"] == 4
    assert new_events[-1].metadata["foundation_gap_action_ids"] == (
        "preview_decisions_pending",
        "module_activation_work_items_open",
        "human_confirmation_required",
        "content_release_gate_blocks_content",
    )
    assert new_events[-1].metadata["foundation_gap_ready_action_count"] == 2
    assert new_events[-1].metadata["foundation_gap_deferred_action_count"] == 2
    assert new_events[-1].metadata["foundation_gap_content_included"] is False
    assert new_events[-1].metadata["foundation_gap_persistent_task_created"] is False
    assert new_events[-1].metadata["foundation_gap_automation_created"] is False
    assert new_events[-1].metadata["mvp_entry_ready"] is True
    assert new_events[-1].metadata["mvp_foundation_gap_count"] == 4
    assert new_events[-1].metadata["mvp_deferred_item_count"] == 5
    assert new_events[-1].metadata["mvp_next_foundation_action"] == "resolve_preview_decision_work_items"
    assert new_events[-1].metadata["mvp_readiness_decision"] == "metadata_only_mvp_ready_with_deferred_content_release"
    assert new_events[-1].metadata["mvp_metadata_only_productive_path"] is True
    assert new_events[-1].metadata["mvp_role_gate_status"] == "role_gated_actions_visible"
    assert new_events[-1].metadata["mvp_audit_gate_status"] == "audit_visible"
    assert new_events[-1].metadata["mvp_backup_failover_gate_status"] == "metadata_only_no_state_change"
    assert new_events[-1].metadata["mvp_module_gate_status"] == "module_activation_required"
    assert new_events[-1].metadata["mvp_content_gate_status"] == "deferred_metadata_only_ready"
    assert new_events[-1].metadata["content_included"] is False
    assert new_events[-1].metadata["persistent_task_created"] is False
    assert new_events[-1].metadata["automation_created"] is False


def test_platform_cockpit_mvp_release_candidate_smoke_requires_request_context() -> None:
    response = client.get("/v1/platform/cockpit/mvp-release-candidate-smoke")

    assert response.status_code == 401
    assert response.json()["detail"] == "Tenant context requires X-Tenant-Id and X-User-Id headers"


def test_platform_cockpit_mvp_release_candidate_smoke_documents_metadata_only_path() -> None:
    reset_module_registry()
    previous_ledger = app.state.source_object_preview_decision_ledger
    app.state.source_object_preview_decision_ledger = InMemorySourceObjectPreviewDecisionLedger()
    starting_event_count = len(app.state.audit_logger.events)

    try:
        response = client.get("/v1/platform/cockpit/mvp-release-candidate-smoke", headers=DEMO_ADMIN_HEADERS)
    finally:
        app.state.source_object_preview_decision_ledger = previous_ledger

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "product_cockpit_mvp_release_candidate_smoke_report.v1"
    assert body["result_contract"] == "metadata_only_mvp_release_candidate_smoke"
    assert body["tenant_id"] == "tenant-demo"
    assert body["run_id"].startswith("mvp-release-candidate-smoke:")
    assert body["checked_by"] == "user-demo"
    assert body["entrypoint_route"] == "/workspace"
    assert body["cockpit_route"] == "/v1/platform/cockpit"
    assert body["snapshot_route"] == "/v1/platform/cockpit/mvp-snapshot"
    assert body["cockpit_audit_event_id"]
    assert body["snapshot_audit_event_id"]
    assert body["audit_event_id"]
    assert body["audit_event_types"] == [
        "platform.module_cockpit.read",
        "platform.mvp_snapshot.export",
        "platform.mvp_release_candidate_smoke.export",
    ]
    assert body["audit_refs"] == [
        f"audit:{body['cockpit_audit_event_id']}",
        f"audit:{body['snapshot_audit_event_id']}",
        f"audit:{body['audit_event_id']}",
    ]
    assert body["snapshot_hash"].startswith("sha256:")
    assert body["snapshot_exported"] is True
    assert body["review_sections"] == [
        "mvp_readiness_summary",
        "mvp_readiness_decision",
        "flow_readiness_summary",
        "work_item_operational_summary",
        "module_refs",
        "source_object_flow_refs",
        "work_item_refs",
        "foundation_gap_actions",
    ]
    assert body["demo_tenant_checked"] is True
    assert body["role_matrix_checked"] is True
    assert body["context_role_ids"] == ["tenant-admin"]
    assert body["role_gates"] == ["context", "tenant-admin,security-admin"]
    assert body["required_roles"] == ["security-admin", "tenant-admin"]
    assert body["admin_role_required_action_count"] == 2
    assert body["mvp_readiness_decision"] == "metadata_only_mvp_ready_with_deferred_content_release"
    assert body["metadata_only_productive_path"] is True
    assert body["module_gate_status"] == "module_activation_required"
    assert body["content_gate_status"] == "deferred_metadata_only_ready"
    assert body["foundation_gap_status"] == "work_items_open"
    assert body["backup_failover_gate_status"] == "metadata_only_no_state_change"
    assert body["backup_restore_verified_flow_count"] == 0
    assert body["backup_restore_deferred_flow_count"] == 2
    assert body["source_object_flow_count"] == 2
    assert body["module_count"] == 2
    assert body["work_item_count"] == 4
    assert body["foundation_gap_action_count"] == 4
    assert body["content_included"] is False
    assert body["persistent_task_created"] is False
    assert body["automation_created"] is False
    assert body["smoke_passed"] is True
    assert body["recommended_actions"] == [
        "retain MVP snapshot and release-candidate smoke hashes with release evidence",
        "run this smoke before promoting viewer, Office, Mail, ticketing or automation paths",
        "keep content release gate deferred until policy and viewer runtime evidence are ready",
    ]
    assert body["evidence_hash"].startswith("sha256:")
    assert "Board pack draft source content" not in json.dumps(body)
    assert "Welcome message source" not in json.dumps(body)

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert [event.event_type for event in new_events[-3:]] == [
        "platform.module_cockpit.read",
        "platform.mvp_snapshot.export",
        "platform.mvp_release_candidate_smoke.export",
    ]
    assert new_events[-1].source_object_ids == ["doc-1", "mail-1"]
    assert new_events[-1].metadata["result_contract"] == "metadata_only_mvp_release_candidate_smoke"
    assert new_events[-1].metadata["snapshot_hash"] == body["snapshot_hash"]
    assert new_events[-1].metadata["snapshot_audit_event_id"] == body["snapshot_audit_event_id"]
    assert new_events[-1].metadata["cockpit_audit_event_id"] == body["cockpit_audit_event_id"]
    assert new_events[-1].metadata["mvp_readiness_decision"] == body["mvp_readiness_decision"]
    assert new_events[-1].metadata["metadata_only_productive_path"] is True
    assert new_events[-1].metadata["smoke_passed"] is True
    assert new_events[-1].metadata["role_matrix_checked"] is True
    assert new_events[-1].metadata["backup_failover_gate_status"] == "metadata_only_no_state_change"
    assert new_events[-1].metadata["content_included"] is False
    assert new_events[-1].metadata["persistent_task_created"] is False
    assert new_events[-1].metadata["automation_created"] is False


def test_platform_cockpit_mvp_release_handover_requires_request_context() -> None:
    response = client.get("/v1/platform/cockpit/mvp-release-handover")

    assert response.status_code == 401
    assert response.json()["detail"] == "Tenant context requires X-Tenant-Id and X-User-Id headers"


def test_platform_cockpit_mvp_release_handover_summarizes_smoke_snapshot_and_gaps() -> None:
    reset_module_registry()
    previous_ledger = app.state.source_object_preview_decision_ledger
    app.state.source_object_preview_decision_ledger = InMemorySourceObjectPreviewDecisionLedger()
    starting_event_count = len(app.state.audit_logger.events)

    try:
        response = client.get("/v1/platform/cockpit/mvp-release-handover", headers=DEMO_ADMIN_HEADERS)
    finally:
        app.state.source_object_preview_decision_ledger = previous_ledger

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "product_cockpit_mvp_release_handover.v1"
    assert body["result_contract"] == "metadata_only_mvp_release_handover"
    assert body["tenant_id"] == "tenant-demo"
    assert body["checked_by"] == "user-demo"
    assert body["handover_route"] == "/v1/platform/cockpit/mvp-release-handover"
    assert body["entrypoint_route"] == "/workspace"
    assert body["cockpit_route"] == "/v1/platform/cockpit"
    assert body["snapshot_route"] == "/v1/platform/cockpit/mvp-snapshot"
    assert body["smoke_route"] == "/v1/platform/cockpit/mvp-release-candidate-smoke"
    assert body["cockpit_audit_event_id"]
    assert body["snapshot_audit_event_id"]
    assert body["smoke_audit_event_id"]
    assert body["audit_event_id"]
    assert body["audit_refs"] == [
        f"audit:{body['cockpit_audit_event_id']}",
        f"audit:{body['snapshot_audit_event_id']}",
        f"audit:{body['smoke_audit_event_id']}",
        f"audit:{body['audit_event_id']}",
    ]
    assert body["snapshot_hash"].startswith("sha256:")
    assert body["release_candidate_smoke_hash"].startswith("sha256:")
    assert body["release_candidate_smoke_passed"] is True
    assert body["mvp_readiness_decision"] == "metadata_only_mvp_ready_with_deferred_content_release"
    assert body["metadata_only_productive_path"] is True
    assert body["handover_status"] == "ready_for_operator_reviewer_handover"
    assert body["operator_handover_summary"] == [
        "metadata-only MVP decision: metadata_only_mvp_ready_with_deferred_content_release",
        f"snapshot hash: {body['snapshot_hash']}",
        f"release-candidate smoke hash: {body['release_candidate_smoke_hash']}",
        (
            "open foundation gaps: preview_decisions_pending,module_activation_work_items_open,"
            "human_confirmation_required,content_release_gate_blocks_content"
        ),
        "content preview, Office/Mail clients, tickets and automations remain deferred",
    ]
    assert body["reviewer_checklist"] == [
        "verify release-candidate smoke_passed is true",
        "retain snapshot_hash and release_candidate_smoke_hash with release evidence",
        "review ready foundation gaps before pilot operation",
        "keep content release gate deferred until policy and viewer runtime evidence are ready",
    ]
    assert body["open_foundation_gap_ids"] == [
        "preview_decisions_pending",
        "module_activation_work_items_open",
        "human_confirmation_required",
        "content_release_gate_blocks_content",
    ]
    assert body["ready_foundation_gap_ids"] == ["preview_decisions_pending", "module_activation_work_items_open"]
    assert body["deferred_foundation_gap_ids"] == [
        "human_confirmation_required",
        "content_release_gate_blocks_content",
    ]
    assert body["next_foundation_action"] == "resolve_preview_decision_work_items"
    assert body["required_roles"] == ["security-admin", "tenant-admin"]
    assert body["role_gates"] == ["context", "tenant-admin,security-admin"]
    assert body["module_gate_status"] == "module_activation_required"
    assert body["content_gate_status"] == "deferred_metadata_only_ready"
    assert body["backup_failover_gate_status"] == "metadata_only_no_state_change"
    assert body["content_included"] is False
    assert body["persistent_task_created"] is False
    assert body["automation_created"] is False
    assert body["evidence_hash"].startswith("sha256:")
    assert body["evidence_hash"] != body["release_candidate_smoke_hash"]
    assert "Board pack draft source content" not in json.dumps(body)
    assert "Welcome message source" not in json.dumps(body)

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert [event.event_type for event in new_events[-4:]] == [
        "platform.module_cockpit.read",
        "platform.mvp_snapshot.export",
        "platform.mvp_release_candidate_smoke.export",
        "platform.mvp_release_handover.export",
    ]
    assert new_events[-1].source_object_ids == ["doc-1", "mail-1"]
    assert new_events[-1].metadata["result_contract"] == "metadata_only_mvp_release_handover"
    assert new_events[-1].metadata["handover_status"] == body["handover_status"]
    assert new_events[-1].metadata["snapshot_hash"] == body["snapshot_hash"]
    assert new_events[-1].metadata["release_candidate_smoke_hash"] == body["release_candidate_smoke_hash"]
    assert new_events[-1].metadata["release_candidate_smoke_passed"] is True
    assert new_events[-1].metadata["open_foundation_gap_ids"] == tuple(body["open_foundation_gap_ids"])
    assert new_events[-1].metadata["next_foundation_action"] == "resolve_preview_decision_work_items"
    assert new_events[-1].metadata["content_included"] is False
    assert new_events[-1].metadata["persistent_task_created"] is False
    assert new_events[-1].metadata["automation_created"] is False


def test_platform_cockpit_work_item_role_matrix_is_stable_and_gated_without_persistent_tasks() -> None:
    reset_module_registry()
    previous_ledger = app.state.source_object_preview_decision_ledger
    app.state.source_object_preview_decision_ledger = InMemorySourceObjectPreviewDecisionLedger()
    role_contexts = {
        "tenant-admin": DEMO_ADMIN_HEADERS,
        "security-admin": DEMO_SECURITY_ADMIN_HEADERS,
        "reader": DEMO_HEADERS,
    }

    try:
        bodies = {}
        for role_name, headers in role_contexts.items():
            response = client.get("/v1/platform/cockpit", headers=headers)
            assert response.status_code == 200
            bodies[role_name] = response.json()
    finally:
        app.state.source_object_preview_decision_ledger = previous_ledger

    def comparable_work_items(body: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "work_item_id": item["work_item_id"],
                "scope": item["scope"],
                "action": item["action"],
                "priority": item["priority"],
                "module_id": item["module_id"],
                "source_object_id": item["source_object_id"],
                "ui_action": item["primary_action_hint"]["ui_action"],
                "required_roles": item["primary_action_hint"]["required_roles"],
                "state_gate": item["primary_action_hint"]["state_gate"],
                "requires_confirmation": item["primary_action_hint"]["requires_confirmation"],
                "target_route": item["primary_action_hint"]["target_route"],
                "secondary_ui_actions": [hint["ui_action"] for hint in item["secondary_action_hints"]],
            }
            for item in body["work_items"]
        ]

    tenant_admin_items = comparable_work_items(bodies["tenant-admin"])
    assert comparable_work_items(bodies["security-admin"]) == tenant_admin_items
    assert comparable_work_items(bodies["reader"]) == tenant_admin_items

    expected_actionability = {
        "tenant-admin": {"module": True, "source_object_flow": True},
        "security-admin": {"module": True, "source_object_flow": True},
        "reader": {"module": False, "source_object_flow": True},
    }
    for role_name, headers in role_contexts.items():
        role_ids = set(headers["X-Role-Ids"].split(","))
        body = bodies[role_name]
        assert body["work_item_count"] == 4
        assert body["source_object_flow_count"] == 2
        for item in body["work_items"]:
            hint = item["primary_action_hint"]
            required_roles = set(hint["required_roles"])
            action_allowed = not required_roles or bool(required_roles & role_ids)
            assert action_allowed is expected_actionability[role_name][item["scope"]]
            assert hint["metadata_only"] is True
            assert hint["content_included"] is False
            assert hint["persistent_task_created"] is False
            assert hint["destructive"] is False
            assert hint["external_side_effect"] is False
            if item["scope"] == "module":
                assert hint["required_roles"] == ["tenant-admin", "security-admin"]
                assert hint["requires_confirmation"] is True
                assert hint["state_gate"].endswith("_and_admin_role")
            else:
                assert hint["required_roles"] == []
                assert item["source_object_id"] in {"doc-1", "mail-1"}
                assert hint["target_route"].startswith("/workspace#source-object=")

    assert "Board pack draft source content" not in json.dumps(bodies)
    assert "Welcome message source" not in json.dumps(bodies)


def test_platform_cockpit_work_items_recompute_after_preview_and_module_state_transitions() -> None:
    reset_module_registry()
    previous_ledger = app.state.source_object_preview_decision_ledger
    app.state.source_object_preview_decision_ledger = InMemorySourceObjectPreviewDecisionLedger()

    def cockpit_body() -> dict[str, Any]:
        response = client.get("/v1/platform/cockpit", headers=DEMO_ADMIN_HEADERS)
        assert response.status_code == 200
        return cast(dict[str, Any], response.json())

    def work_item_by_source(body: dict[str, Any], source_object_id: str) -> dict[str, Any]:
        return next(item for item in body["work_items"] if item["source_object_id"] == source_object_id)

    def work_item_by_module(body: dict[str, Any], module_id: str) -> dict[str, Any]:
        return next(item for item in body["work_items"] if item["module_id"] == module_id)

    try:
        initial = cockpit_body()
        initial_doc_item = work_item_by_source(initial, "doc-1")
        initial_kb_item = work_item_by_module(initial, "knowledge_base")
        assert initial["work_item_count"] == 4
        assert initial_doc_item["action"] == "request_preview_decision"
        assert initial_doc_item["primary_action_hint"]["ui_action"] == "guided_preview_decision"
        assert initial_kb_item["action"] == "provision_module"
        assert initial_kb_item["primary_action_hint"]["ui_action"] == "module_provision"

        renderer_response = client.post(
            "/v1/source-objects/doc-1/versions/v1/preview-renderer-runs",
            headers=DEMO_HEADERS,
            json={
                "preview_slot_id": "office.document.preview.metadata",
                "preview_policy_id": "preview-policy.document.metadata-first.v1",
                "parser_sanitizer_evidence_ref": "parser-sanitizer:workspace-transition-doc-1-v1",
                "backup_coverage_evidence_ref": "backup:workspace-transition-doc-1-v1",
                "restore_evidence_ref": "restore-drill:workspace-transition-doc-1-v1",
                "reason": "workspace transition renderer evidence",
            },
        )
        assert renderer_response.status_code == 200
        decision_response = client.post(
            "/v1/source-objects/doc-1/versions/v1/preview-decisions",
            headers=DEMO_HEADERS,
            json={
                "preview_slot_id": "office.document.preview.metadata",
                "preview_policy_id": "preview-policy.document.metadata-first.v1",
                "parser_sanitizer_evidence_ref": "parser-sanitizer:workspace-transition-doc-1-v1",
                "renderer_sandbox_evidence_ref": renderer_response.json()["renderer_sandbox_evidence_ref"],
                "backup_coverage_evidence_ref": "backup:workspace-transition-doc-1-v1",
                "restore_evidence_ref": "restore-drill:workspace-transition-doc-1-v1",
                "human_confirmation_reference": "approval:workspace-transition-doc-1-v1",
                "reason": "workspace transition preview decision",
            },
        )
        assert decision_response.status_code == 200

        after_preview = cockpit_body()
        after_preview_doc_item = work_item_by_source(after_preview, "doc-1")
        assert after_preview["work_item_count"] == 4
        assert initial_doc_item["work_item_id"] not in {item["work_item_id"] for item in after_preview["work_items"]}
        assert after_preview_doc_item["action"] == "review_latest_preview_decision"
        assert after_preview_doc_item["primary_action_hint"]["ui_action"] == "open_flow"
        assert after_preview_doc_item["primary_action_hint"]["requires_confirmation"] is False
        assert after_preview_doc_item["secondary_action_hints"] == []
        assert work_item_by_source(after_preview, "mail-1")["action"] == "request_preview_decision"

        provision_response = client.post(
            "/v1/admin/tenant-modules/knowledge_base/provision",
            headers=DEMO_ADMIN_HEADERS,
            json={
                "approval_reference": "approval:workspace-transition-kb-provision",
                "reason": "workspace transition provision",
            },
        )
        assert provision_response.status_code == 200

        after_provision = cockpit_body()
        after_provision_kb_item = work_item_by_module(after_provision, "knowledge_base")
        assert initial_kb_item["work_item_id"] not in {item["work_item_id"] for item in after_provision["work_items"]}
        assert after_provision_kb_item["action"] == "enable_module"
        assert after_provision_kb_item["primary_action_hint"]["ui_action"] == "module_enable"
        assert after_provision_kb_item["primary_action_hint"]["api_action"] == "enable"
        assert after_provision_kb_item["primary_action_hint"]["required_roles"] == ["tenant-admin", "security-admin"]

        enable_response = client.post(
            "/v1/admin/tenant-modules/knowledge_base/enable",
            headers=DEMO_ADMIN_HEADERS,
            json={
                "approval_reference": "approval:workspace-transition-kb-enable",
                "reason": "workspace transition enable",
                "enabled_features": {"knowledge_base.articles.read": True},
            },
        )
        assert enable_response.status_code == 200

        after_enable = cockpit_body()
        module_items_after_enable = [item for item in after_enable["work_items"] if item["scope"] == "module"]
        assert {item["module_id"] for item in module_items_after_enable} == {"crm_erp"}
        assert all(item["module_id"] != "knowledge_base" for item in after_enable["work_items"])
        assert after_enable["work_item_count"] == 3
        assert after_enable["work_item_operational_summary"]["work_item_count"] == 3
        assert after_enable["work_item_operational_summary"]["module_work_item_count"] == 1
        assert after_enable["work_item_operational_summary"]["source_object_flow_work_item_count"] == 2
        assert after_enable["work_item_operational_summary"]["state_transition_signals"] == [
            "module:provision_module",
            "source_object_flow:request_preview_decision",
            "source_object_flow:review_latest_preview_decision",
        ]
        assert after_enable["work_item_operational_summary"]["content_included"] is False
        assert after_enable["work_item_operational_summary"]["persistent_task_created_count"] == 0
        assert work_item_by_source(after_enable, "doc-1")["action"] == "review_latest_preview_decision"
        assert work_item_by_source(after_enable, "mail-1")["action"] == "request_preview_decision"
        assert "Board pack draft source content" not in json.dumps(after_enable)
    finally:
        app.state.source_object_preview_decision_ledger = previous_ledger


def test_module_activation_foundation_gap_is_removed_after_modules_enabled() -> None:
    reset_module_registry()
    previous_ledger = app.state.source_object_preview_decision_ledger
    app.state.source_object_preview_decision_ledger = InMemorySourceObjectPreviewDecisionLedger()

    def cockpit_body() -> dict[str, Any]:
        response = client.get("/v1/platform/cockpit", headers=DEMO_ADMIN_HEADERS)
        assert response.status_code == 200
        return cast(dict[str, Any], response.json())

    def module_gap(body: dict[str, Any]) -> dict[str, Any]:
        return next(
            action
            for action in body["foundation_gap_actions"]
            if action["gap_id"] == "module_activation_work_items_open"
        )

    def post_module_action(module_id: str, action: str, approval_suffix: str) -> None:
        response = client.post(
            f"/v1/admin/tenant-modules/{module_id}/{action}",
            headers=DEMO_ADMIN_HEADERS,
            json={
                "approval_reference": f"approval:foundation-module-gap-{approval_suffix}",
                "reason": "foundation module activation gap reduction without domain data or automation",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert "content_included" not in body

    try:
        initial = cockpit_body()
        initial_gap = module_gap(initial)
        assert initial_gap["next_action"] == "complete_module_activation_work_items"
        assert initial_gap["covered_by_work_item_ids"] == [
            "module:crm_erp:provision_module",
            "module:knowledge_base:provision_module",
        ]
        assert initial_gap["ui_actions"] == ["module_provision"]
        assert initial_gap["required_roles"] == ["security-admin", "tenant-admin"]
        assert initial_gap["requires_confirmation"] is True
        assert initial_gap["content_included"] is False
        assert initial_gap["persistent_task_created"] is False
        assert initial_gap["automation_created"] is False

        post_module_action("crm_erp", "provision", "crm-provision")
        post_module_action("knowledge_base", "provision", "kb-provision")

        after_provision = cockpit_body()
        provisioned_modules = {module["module_id"]: module for module in after_provision["modules"]}
        assert provisioned_modules["crm_erp"]["status"] == "disabled"
        assert provisioned_modules["knowledge_base"]["status"] == "disabled"
        provision_gap = module_gap(after_provision)
        assert provision_gap["covered_by_work_item_ids"] == [
            "module:crm_erp:enable_module",
            "module:knowledge_base:enable_module",
        ]
        assert provision_gap["ui_actions"] == ["module_enable"]
        assert provision_gap["next_action"] == "complete_module_activation_work_items"
        assert provision_gap["content_included"] is False
        assert provision_gap["persistent_task_created"] is False
        assert provision_gap["automation_created"] is False

        post_module_action("crm_erp", "enable", "crm-enable")
        post_module_action("knowledge_base", "enable", "kb-enable")

        after_enable = cockpit_body()
        enabled_modules = {module["module_id"]: module for module in after_enable["modules"]}
        assert enabled_modules["crm_erp"]["normal_use_enabled"] is True
        assert enabled_modules["knowledge_base"]["normal_use_enabled"] is True
        assert "module_activation_work_items_open" not in after_enable["mvp_readiness_summary"]["foundation_gaps"]
        assert after_enable["mvp_readiness_decision"]["module_gate_status"] == "modules_enabled"
        assert after_enable["mvp_readiness_decision"]["enabled_module_ids"] == ["crm_erp", "knowledge_base"]
        assert after_enable["mvp_readiness_decision"]["module_action_required_ids"] == []
        assert after_enable["mvp_readiness_decision"]["metadata_only_productive_path"] is True
        assert "module_activation_work_items_open" not in [
            action["gap_id"] for action in after_enable["foundation_gap_actions"]
        ]
        assert after_enable["work_item_operational_summary"]["module_work_item_count"] == 0
        assert after_enable["work_item_operational_summary"]["persistent_task_created_count"] == 0
        assert after_enable["work_item_operational_summary"]["content_included"] is False
        assert all(item["scope"] == "source_object_flow" for item in after_enable["work_items"])
        human_gap_after_modules = next(
            action
            for action in after_enable["foundation_gap_actions"]
            if action["gap_id"] == "human_confirmation_required"
        )
        assert human_gap_after_modules["status"] == "deferred"
        assert human_gap_after_modules["next_action"] == "covered_by_specific_foundation_gap_actions"
        assert human_gap_after_modules["confirmation_brief"]["covering_gap_ids"] == ["preview_decisions_pending"]
        assert human_gap_after_modules["confirmation_brief"]["standalone_work_item_ids"] == []
        assert human_gap_after_modules["confirmation_brief"]["covered_by_specific_gap_work_item_ids"] == [
            "source-object-flow:document:doc-1:v1:request_preview_decision",
            "source-object-flow:mail:mail-1:v1:request_preview_decision",
        ]
        assert all(action["content_included"] is False for action in after_enable["foundation_gap_actions"])
        assert all(action["persistent_task_created"] is False for action in after_enable["foundation_gap_actions"])
        assert all(action["automation_created"] is False for action in after_enable["foundation_gap_actions"])

        snapshot_response = client.get("/v1/platform/cockpit/mvp-snapshot", headers=DEMO_ADMIN_HEADERS)
        assert snapshot_response.status_code == 200
        snapshot = snapshot_response.json()
        assert "module_activation_work_items_open" not in snapshot["mvp_readiness_summary"]["foundation_gaps"]
        assert "module_activation_work_items_open" not in [
            action["gap_id"] for action in snapshot["foundation_gap_actions"]
        ]
        assert snapshot["mvp_readiness_decision"]["module_gate_status"] == "modules_enabled"
        assert snapshot["mvp_readiness_decision"]["metadata_only_productive_path"] is True
        assert snapshot["content_included"] is False
        assert snapshot["persistent_task_created"] is False
        assert snapshot["automation_created"] is False
        assert "Board pack draft source content" not in json.dumps(snapshot)
        assert "Welcome message source" not in json.dumps(snapshot)
    finally:
        app.state.source_object_preview_decision_ledger = previous_ledger
        reset_module_registry()


def test_preview_decision_foundation_gap_is_removed_after_all_pending_decisions() -> None:
    reset_module_registry()
    previous_ledger = app.state.source_object_preview_decision_ledger
    app.state.source_object_preview_decision_ledger = InMemorySourceObjectPreviewDecisionLedger()

    def cockpit_body() -> dict[str, Any]:
        response = client.get("/v1/platform/cockpit", headers=DEMO_HEADERS)
        assert response.status_code == 200
        return cast(dict[str, Any], response.json())

    def request_metadata_only_preview_decision(
        *, source_object_id: str, version_id: str, preview_slot_id: str, preview_policy_id: str
    ) -> None:
        ref_suffix = f"{source_object_id}-{version_id}-gap-reduction"
        renderer_response = client.post(
            f"/v1/source-objects/{source_object_id}/versions/{version_id}/preview-renderer-runs",
            headers=DEMO_HEADERS,
            json={
                "preview_slot_id": preview_slot_id,
                "preview_policy_id": preview_policy_id,
                "parser_sanitizer_evidence_ref": f"parser-sanitizer:{ref_suffix}",
                "backup_coverage_evidence_ref": f"backup:{ref_suffix}",
                "restore_evidence_ref": f"restore-drill:{ref_suffix}",
                "reason": "foundation gap reduction renderer evidence",
            },
        )
        assert renderer_response.status_code == 200
        decision_response = client.post(
            f"/v1/source-objects/{source_object_id}/versions/{version_id}/preview-decisions",
            headers=DEMO_HEADERS,
            json={
                "preview_slot_id": preview_slot_id,
                "preview_policy_id": preview_policy_id,
                "parser_sanitizer_evidence_ref": f"parser-sanitizer:{ref_suffix}",
                "renderer_sandbox_evidence_ref": renderer_response.json()["renderer_sandbox_evidence_ref"],
                "backup_coverage_evidence_ref": f"backup:{ref_suffix}",
                "restore_evidence_ref": f"restore-drill:{ref_suffix}",
                "human_confirmation_reference": f"approval:{ref_suffix}",
                "reason": "foundation gap reduction metadata-only preview decision",
            },
        )
        assert decision_response.status_code == 200
        decision = decision_response.json()
        assert decision["content_release_allowed"] is False
        assert decision["content_included"] is False

    try:
        initial = cockpit_body()
        assert initial["flow_readiness_summary"]["preview_decision_pending_count"] == 2
        assert initial["flow_readiness_summary"]["preview_decision_blocked_count"] == 0
        assert initial["mvp_readiness_summary"]["next_foundation_action"] == "resolve_preview_decision_work_items"
        assert initial["foundation_gap_actions"][0]["gap_id"] == "preview_decisions_pending"
        assert initial["foundation_gap_actions"][0]["next_action"] == "resolve_preview_decision_work_items"
        assert initial["foundation_gap_actions"][0]["status"] == "ready"

        request_metadata_only_preview_decision(
            source_object_id="doc-1",
            version_id="v1",
            preview_slot_id="office.document.preview.metadata",
            preview_policy_id="preview-policy.document.metadata-first.v1",
        )
        request_metadata_only_preview_decision(
            source_object_id="mail-1",
            version_id="v1",
            preview_slot_id="mail.message.preview.metadata",
            preview_policy_id="preview-policy.mail.metadata-first.v1",
        )

        after = cockpit_body()
        assert after["flow_readiness_summary"]["preview_decision_pending_count"] == 0
        assert after["flow_readiness_summary"]["preview_decision_blocked_count"] == 2
        assert "preview_decisions_pending" not in after["mvp_readiness_summary"]["foundation_gaps"]
        assert after["mvp_readiness_summary"]["foundation_gaps"][0] == "preview_decisions_blocked"
        assert after["mvp_readiness_summary"]["next_foundation_action"] == "complete_preview_release_evidence"
        action_ids = [action["gap_id"] for action in after["foundation_gap_actions"]]
        assert "preview_decisions_pending" not in action_ids
        assert action_ids == [
            "preview_decisions_blocked",
            "module_activation_work_items_open",
            "human_confirmation_required",
            "content_release_gate_blocks_content",
        ]
        human_action = after["foundation_gap_actions"][2]
        assert human_action["gap_id"] == "human_confirmation_required"
        assert human_action["status"] == "deferred"
        assert human_action["next_action"] == "covered_by_specific_foundation_gap_actions"
        assert human_action["confirmation_brief"]["covering_gap_ids"] == ["module_activation_work_items_open"]
        assert human_action["confirmation_brief"]["standalone_work_item_ids"] == []
        assert human_action["confirmation_brief"]["covered_by_specific_gap_work_item_ids"] == [
            "module:crm_erp:provision_module",
            "module:knowledge_base:provision_module",
        ]
        blocked_action = after["foundation_gap_actions"][0]
        assert blocked_action["status"] == "ready"
        assert blocked_action["next_action"] == "complete_preview_release_evidence"
        assert blocked_action["source_object_ids"] == ["doc-1", "mail-1"]
        assert blocked_action["ui_actions"] == ["open_flow"]
        assert blocked_action["requires_confirmation"] is False
        evidence_brief = blocked_action["evidence_brief"]
        assert evidence_brief["schema_version"] == "product_cockpit_foundation_gap_evidence_brief.v1"
        assert evidence_brief["evidence_required_now"] == ["tenant_preview_policy_enabled"]
        assert evidence_brief["missing_evidence"] == ["tenant_preview_policy_enabled"]
        assert "parser_sanitizer_evidence" in evidence_brief["provided_evidence"]
        assert evidence_brief["verified_evidence"] == [
            "renderer_sandbox_worker_evidence",
            "backup_coverage_evidence",
            "restore_drill_evidence",
            "human_content_release_confirmation",
        ]
        assert evidence_brief["deferred_evidence"] == [
            "content_release_gate_policy_review",
            "viewer_adapter_runtime",
            "full_content_preview_rendering",
        ]
        assert len(evidence_brief["decision_ledger_refs"]) == 2
        assert all(ref.startswith("preview-decision-ledger:sha256:") for ref in evidence_brief["decision_ledger_refs"])
        assert len(evidence_brief["audit_refs"]) == 2
        assert all(ref.startswith("audit:") for ref in evidence_brief["audit_refs"])
        assert (
            "content_preview_skeleton_blocks_release_until_renderer_operational"
            in evidence_brief["policy_blocking_reasons"]
        )
        assert evidence_brief["content_release_allowed"] is False
        assert evidence_brief["content_included"] is False
        assert all(action["content_included"] is False for action in after["foundation_gap_actions"])
        assert all(action["persistent_task_created"] is False for action in after["foundation_gap_actions"])
        assert all(action["automation_created"] is False for action in after["foundation_gap_actions"])

        snapshot_response = client.get("/v1/platform/cockpit/mvp-snapshot", headers=DEMO_HEADERS)
        assert snapshot_response.status_code == 200
        snapshot = snapshot_response.json()
        assert snapshot["next_foundation_action"] == "complete_preview_release_evidence"
        assert snapshot["mvp_readiness_decision"]["next_foundation_action"] == "complete_preview_release_evidence"
        assert snapshot["mvp_readiness_decision"]["backup_restore_verified_flow_count"] == 2
        assert snapshot["mvp_readiness_decision"]["backup_restore_deferred_flow_count"] == 0
        assert "preview_decisions_pending" not in [action["gap_id"] for action in snapshot["foundation_gap_actions"]]
        assert snapshot["foundation_gap_actions"][0]["gap_id"] == "preview_decisions_blocked"
        assert snapshot["foundation_gap_actions"][0]["evidence_brief"]["evidence_required_now"] == [
            "tenant_preview_policy_enabled"
        ]
        assert snapshot["foundation_gap_actions"][0]["evidence_brief"]["deferred_evidence"] == [
            "content_release_gate_policy_review",
            "viewer_adapter_runtime",
            "full_content_preview_rendering",
        ]
        assert snapshot["content_included"] is False
        assert snapshot["persistent_task_created"] is False
        assert snapshot["automation_created"] is False
        assert "Board pack draft source content" not in json.dumps(snapshot)
        assert "Welcome message source" not in json.dumps(snapshot)
    finally:
        app.state.source_object_preview_decision_ledger = previous_ledger


def test_platform_cockpit_surfaces_latest_preview_decision_readiness_without_content() -> None:
    reset_module_registry()
    previous_ledger = app.state.source_object_preview_decision_ledger
    app.state.source_object_preview_decision_ledger = InMemorySourceObjectPreviewDecisionLedger()

    try:
        decision_response = client.post(
            "/v1/source-objects/doc-1/versions/v1/preview-decisions",
            headers=DEMO_HEADERS,
            json={
                "preview_slot_id": "office.document.preview.metadata",
                "preview_policy_id": "preview-policy.document.metadata-first.v1",
                "reason": "request safe document preview decision for cockpit readiness",
            },
        )
        response = client.get("/v1/platform/cockpit", headers=DEMO_HEADERS)
    finally:
        app.state.source_object_preview_decision_ledger = previous_ledger

    assert decision_response.status_code == 200
    decision = decision_response.json()
    assert response.status_code == 200
    body = response.json()
    flows = {flow["source_object_id"]: flow for flow in body["source_object_flows"]}
    doc_readiness = flows["doc-1"]["readiness"]
    mail_readiness = flows["mail-1"]["readiness"]

    assert body["flow_readiness_summary"]["metadata_ready_flow_count"] == 2
    assert body["flow_readiness_summary"]["preview_decision_pending_count"] == 1
    assert body["flow_readiness_summary"]["preview_decision_blocked_count"] == 1
    assert body["flow_readiness_summary"]["content_release_allowed_count"] == 0
    assert body["flow_readiness_summary"]["content_included_count"] == 0
    assert body["work_item_count"] == 4
    doc_item = next(item for item in body["work_items"] if item["source_object_id"] == "doc-1")
    mail_item = next(item for item in body["work_items"] if item["source_object_id"] == "mail-1")
    assert doc_item["action"] == "review_latest_preview_decision"
    assert doc_item["priority"] == "high"
    assert doc_item["primary_action_hint"]["ui_action"] == "open_flow"
    assert doc_item["primary_action_hint"]["requires_confirmation"] is False
    assert doc_item["secondary_action_hints"] == []
    assert mail_item["action"] == "request_preview_decision"
    assert mail_item["priority"] == "high"
    assert doc_readiness["status"] == "metadata_ready_preview_blocked"
    assert doc_readiness["preview_decision_available"] is True
    assert doc_readiness["latest_preview_decision_status"] == "blocked"
    assert "tenant_preview_policy_enabled" in doc_readiness["latest_preview_decision_required_evidence"]
    assert "source_object_acl_checked" in doc_readiness["latest_preview_decision_provided_evidence"]
    assert doc_readiness["latest_preview_decision_evidence_hash"] == decision["preview_decision_evidence_hash"]
    assert doc_readiness["latest_preview_decision_ledger_ref"] == decision["decision_ledger_ref"]
    assert doc_readiness["latest_preview_decision_audit_event_id"] == decision["audit_event_id"]
    assert "tenant_preview_policy_enabled" in doc_readiness["latest_preview_decision_missing_evidence"]
    assert "content_preview_skeleton_blocks_release_until_renderer_operational" in doc_readiness["blocking_reasons"]
    assert doc_readiness["content_release_allowed"] is False
    assert doc_readiness["content_included"] is False
    assert doc_readiness["cockpit_audit_event_id"] == body["audit_event_id"]
    assert decision["decision_ledger_ref"] in doc_readiness["evidence_refs"]
    assert f"audit:{body['audit_event_id']}" in doc_readiness["evidence_refs"]
    assert mail_readiness["status"] == "metadata_ready_preview_decision_pending"
    assert "Board pack draft source content" not in json.dumps(body)


def test_workspace_guided_preview_sequence_updates_cockpit_readiness_without_content() -> None:
    reset_module_registry()
    previous_ledger = app.state.source_object_preview_decision_ledger
    app.state.source_object_preview_decision_ledger = InMemorySourceObjectPreviewDecisionLedger()

    try:
        renderer_response = client.post(
            "/v1/source-objects/doc-1/versions/v1/preview-renderer-runs",
            headers=DEMO_HEADERS,
            json={
                "preview_slot_id": "office.document.preview.metadata",
                "preview_policy_id": "preview-policy.document.metadata-first.v1",
                "parser_sanitizer_evidence_ref": "parser-sanitizer:workspace-preview-doc-1-v1-test",
                "backup_coverage_evidence_ref": "backup:workspace-preview-doc-1-v1-test",
                "restore_evidence_ref": "restore-drill:workspace-preview-doc-1-v1-test",
                "reason": "workspace guided metadata-only renderer evidence smoke",
            },
        )
        renderer_ref = renderer_response.json().get("renderer_sandbox_evidence_ref")
        decision_response = client.post(
            "/v1/source-objects/doc-1/versions/v1/preview-decisions",
            headers=DEMO_HEADERS,
            json={
                "preview_slot_id": "office.document.preview.metadata",
                "preview_policy_id": "preview-policy.document.metadata-first.v1",
                "parser_sanitizer_evidence_ref": "parser-sanitizer:workspace-preview-doc-1-v1-test",
                "renderer_sandbox_evidence_ref": renderer_ref,
                "backup_coverage_evidence_ref": "backup:workspace-preview-doc-1-v1-test",
                "restore_evidence_ref": "restore-drill:workspace-preview-doc-1-v1-test",
                "human_confirmation_reference": "approval:workspace-preview-decision-doc-1-v1-test",
                "reason": "workspace guided metadata-only preview decision smoke",
            },
        )
        response = client.get("/v1/platform/cockpit", headers=DEMO_HEADERS)
    finally:
        app.state.source_object_preview_decision_ledger = previous_ledger

    assert renderer_response.status_code == 200
    assert decision_response.status_code == 200
    decision = decision_response.json()
    assert renderer_ref in decision["provided_evidence_refs"]
    assert "parser_sanitizer_evidence" in decision["provided_evidence"]
    assert "renderer_sandbox_worker_evidence" in decision["provided_evidence"]
    assert "human_content_release_confirmation" in decision["provided_evidence"]
    assert "renderer_sandbox_worker_evidence" not in decision["missing_evidence"]
    assert "backup_coverage_evidence" not in decision["missing_evidence"]
    assert "restore_drill_evidence" not in decision["missing_evidence"]
    assert decision["content_release_allowed"] is False
    assert decision["content_included"] is False

    assert response.status_code == 200
    body = response.json()
    flows = {flow["source_object_id"]: flow for flow in body["source_object_flows"]}
    doc_readiness = flows["doc-1"]["readiness"]
    assert doc_readiness["status"] == "metadata_ready_preview_blocked"
    assert doc_readiness["latest_preview_decision_ledger_ref"] == decision["decision_ledger_ref"]
    assert "renderer_sandbox_worker_evidence" not in doc_readiness["latest_preview_decision_missing_evidence"]
    assert doc_readiness["content_release_allowed"] is False
    assert doc_readiness["content_included"] is False
    assert body["flow_readiness_summary"]["preview_decision_pending_count"] == 1
    assert body["flow_readiness_summary"]["preview_decision_blocked_count"] == 1
    assert "Board pack draft source content" not in json.dumps(body)


def test_platform_cockpit_uses_configured_workspace_source_refs_without_unreadable_lookup() -> None:
    reset_module_registry()
    object_id = f"doc-configured-{uuid4().hex}"
    source_text = "Configured cockpit source content must not leave the repository response boundary."
    record = workspace_source_record_for_detail_smoke(tenant_id="tenant-demo", object_id=object_id, text=source_text)
    previous_repository = app.state.workspace_source_object_repository
    previous_catalog = app.state.workspace_source_object_catalog
    app.state.workspace_source_object_repository = InMemorySourceObjectRepository(records=(record,))
    app.state.workspace_source_object_catalog = ConfiguredWorkspaceSourceObjectCatalog(
        refs=(
            WorkspaceSourceObjectRef(object_id=object_id, version_id="v1"),
            WorkspaceSourceObjectRef(object_id="doc-not-readable", version_id="v1"),
        )
    )

    try:
        response = client.get(
            "/v1/platform/cockpit",
            headers={**DEMO_HEADERS, "X-Readable-Object-Ids": object_id},
        )
    finally:
        app.state.workspace_source_object_repository = previous_repository
        app.state.workspace_source_object_catalog = previous_catalog

    assert response.status_code == 200
    body = response.json()
    flows = body["source_object_flows"]
    assert [flow["source_object_id"] for flow in flows] == [object_id]
    assert flows[0]["preview_slots"][0]["render_contract"] == "metadata_only_no_source_content"
    assert flows[0]["preview_slots"][0]["allowed_actions"] == ["open_metadata_detail"]
    assert_metadata_first_preview_gate(flows[0]["preview_slots"][0])
    assert source_text not in json.dumps(body)


def test_platform_cockpit_uses_pg_workspace_repository_and_configured_refs_without_content_leakage(
    live_source_object_detail_database: LiveSourceObjectDetailDatabase,
) -> None:
    reset_module_registry()
    object_id = f"doc-cockpit-pg-{uuid4().hex}"
    source_text = "Persistent cockpit source content must stay out of configured flow responses."
    record = workspace_source_record_for_detail_smoke(tenant_id="tenant-demo", object_id=object_id, text=source_text)
    repository = PgSourceObjectRepository(
        database_dsn=live_source_object_detail_database.app_dsn,
        content_store=InMemorySourceObjectContentStore(stored_at_clock=lambda: "2026-06-17T08:02:00Z"),
        retention_policy=load_retention_manifest_policy(RETENTION_POLICY_PATH),
        storage_policy=load_storage_adapter_policy(STORAGE_POLICY_PATH),
    )
    repository.add(record)
    previous_repository = app.state.workspace_source_object_repository
    previous_catalog = app.state.workspace_source_object_catalog
    app.state.workspace_source_object_repository = repository
    app.state.workspace_source_object_catalog = ConfiguredWorkspaceSourceObjectCatalog(
        refs=(WorkspaceSourceObjectRef(object_id=object_id, version_id="v1"),)
    )

    try:
        response = client.get(
            "/v1/platform/cockpit",
            headers={**DEMO_HEADERS, "X-Readable-Object-Ids": object_id},
        )
    finally:
        app.state.workspace_source_object_repository = previous_repository
        app.state.workspace_source_object_catalog = previous_catalog

    assert response.status_code == 200
    body = response.json()
    flows = body["source_object_flows"]
    assert [flow["source_object_id"] for flow in flows] == [object_id]
    assert flows[0]["origin"] == "document"
    assert flows[0]["content_included"] is False
    assert flows[0]["preview_slots"][0]["content_included"] is False
    assert_metadata_first_preview_gate(flows[0]["preview_slots"][0])
    assert source_text not in json.dumps(body)


def test_platform_cockpit_includes_knowledge_base_source_flow_after_feature_enable() -> None:
    reset_module_registry()
    provision_and_enable_knowledge_base_articles_for_demo()

    response = client.get("/v1/platform/cockpit", headers=DEMO_KB_ARTICLE_HEADERS)

    assert response.status_code == 200
    body = response.json()
    knowledge_flows = [flow for flow in body["source_object_flows"] if flow["origin"] == "knowledge_base"]
    assert len(knowledge_flows) == 2
    assert {flow["module_id"] for flow in knowledge_flows} == {"knowledge_base"}
    assert {flow["module_status"] for flow in knowledge_flows} == {"enabled"}
    assert all(flow["source_object_type"] == "wiki" for flow in knowledge_flows)
    assert all("knowledge_base.article.read" in flow["downstream_surfaces"] for flow in knowledge_flows)
    assert all("object_type:kb.article" in flow["evidence_refs"] for flow in knowledge_flows)
    assert all(flow["preview_slots"][0]["surface"] == "knowledge_base.article.preview" for flow in knowledge_flows)
    assert all(flow["preview_slots"][0]["content_included"] is False for flow in knowledge_flows)
    assert all(
        flow["preview_slots"][0]["gate"]["policy_id"] == "preview-policy.knowledge-base.metadata-first.v1"
        for flow in knowledge_flows
    )
    assert all(flow["content_included"] is False for flow in knowledge_flows)

    modules = {module["module_id"]: module for module in body["modules"]}
    assert modules["knowledge_base"]["normal_use_enabled"] is True
    assert modules["knowledge_base"]["next_action"] == "open_module"


def test_source_object_metadata_detail_requires_request_context() -> None:
    response = client.get("/v1/source-objects/doc-1/versions/v1/metadata")

    assert response.status_code == 401
    assert response.json()["detail"] == "Tenant context requires X-Tenant-Id and X-User-Id headers"


def test_source_object_metadata_detail_returns_document_metadata_without_content() -> None:
    starting_event_count = len(app.state.audit_logger.events)

    response = client.get("/v1/source-objects/doc-1/versions/v1/metadata", headers=DEMO_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant-demo"
    assert body["schema_version"] == "source_object_metadata_detail.v1"
    assert body["result_contract"] == "metadata_only_acl_checked_source_object_detail"
    assert body["origin"] == "document"
    assert body["source_object_id"] == "doc-1"
    assert body["source_version_id"] == "v1"
    assert body["source_object_type"] == "document"
    assert body["title"] == "Board Pack Draft"
    assert body["access_checked"] is True
    assert body["content_included"] is False
    assert body["preview_slots"][0]["surface"] == "office.document.preview"
    assert body["preview_slots"][0]["render_contract"] == "metadata_only_no_source_content"
    assert body["preview_slots"][0]["content_included"] is False
    assert_metadata_first_preview_gate(body["preview_slots"][0])
    assert body["manifest_hash"].startswith("sha256:")
    assert body["content_hash"].startswith("sha256:")
    assert "Board pack draft source content" not in json.dumps(body)

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert new_events[-1].event_type == "source_object.metadata_detail.read"
    assert new_events[-1].source_object_ids == ["doc-1"]
    assert new_events[-1].metadata["result_contract"] == "metadata_only"
    assert new_events[-1].metadata["access_checked"] is True
    assert new_events[-1].metadata["content_included"] is False


def test_source_object_metadata_detail_denies_unreadable_object_and_audits_acl_check() -> None:
    starting_event_count = len(app.state.audit_logger.events)

    response = client.get("/v1/source-objects/doc-other/versions/v1/metadata", headers=DEMO_HEADERS)

    assert response.status_code == 403
    assert response.json()["detail"] == "User cannot read requested source object metadata"
    new_events = app.state.audit_logger.events[starting_event_count:]
    assert new_events[-1].event_type == "source_object.metadata_detail.denied"
    assert new_events[-1].source_object_ids == ["doc-other"]
    assert new_events[-1].metadata["denial_reason"] == "acl_object_not_readable"
    assert new_events[-1].metadata["access_checked"] is True


def test_source_object_metadata_detail_returns_not_found_for_readable_missing_source() -> None:
    reset_module_registry()
    starting_event_count = len(app.state.audit_logger.events)

    response = client.get(
        "/v1/source-objects/doc-missing/versions/v1/metadata",
        headers={**DEMO_HEADERS, "X-Readable-Object-Ids": "doc-missing"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Source object metadata was not found"
    new_events = app.state.audit_logger.events[starting_event_count:]
    assert new_events[-1].event_type == "source_object.metadata_detail.not_found"
    assert new_events[-1].source_object_ids == ["doc-missing"]
    assert new_events[-1].metadata["origin"] == "workspace"
    assert new_events[-1].metadata["access_checked"] is True


def test_source_object_metadata_detail_uses_pg_workspace_repository_without_content_leakage(
    live_source_object_detail_database: LiveSourceObjectDetailDatabase,
) -> None:
    suffix = uuid4().hex
    tenant_id = "tenant-demo"
    object_id = f"doc-detail-{suffix}"
    source_text = "Persistent detail smoke content must stay out of the metadata detail response."
    record = workspace_source_record_for_detail_smoke(tenant_id=tenant_id, object_id=object_id, text=source_text)
    repository = PgSourceObjectRepository(
        database_dsn=live_source_object_detail_database.app_dsn,
        content_store=InMemorySourceObjectContentStore(stored_at_clock=lambda: "2026-06-17T08:01:00Z"),
        retention_policy=load_retention_manifest_policy(RETENTION_POLICY_PATH),
        storage_policy=load_storage_adapter_policy(STORAGE_POLICY_PATH),
    )
    repository.add(record)
    previous_repository = app.state.workspace_source_object_repository
    app.state.workspace_source_object_repository = repository
    starting_event_count = len(app.state.audit_logger.events)

    try:
        response = client.get(
            f"/v1/source-objects/{object_id}/versions/v1/metadata",
            headers={
                "X-Tenant-Id": tenant_id,
                "X-User-Id": "user-demo",
                "X-Role-Ids": "knowledge-worker",
                "X-Readable-Object-Ids": object_id,
            },
        )
    finally:
        app.state.workspace_source_object_repository = previous_repository

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == tenant_id
    assert body["origin"] == "document"
    assert body["source_object_id"] == object_id
    assert body["source_version_id"] == "v1"
    assert body["source_object_type"] == "document"
    assert body["title"] == "Persistent detail smoke document"
    assert body["access_checked"] is True
    assert body["content_included"] is False
    assert body["preview_slots"][0]["surface"] == "office.document.preview"
    assert body["preview_slots"][0]["allowed_actions"] == ["open_metadata_detail"]
    assert_metadata_first_preview_gate(body["preview_slots"][0])
    assert source_text not in json.dumps(body)
    new_events = app.state.audit_logger.events[starting_event_count:]
    assert new_events[-1].event_type == "source_object.metadata_detail.read"
    assert new_events[-1].metadata["origin"] == "document"
    assert new_events[-1].metadata["result_contract"] == "metadata_only"


def test_source_object_metadata_detail_returns_knowledge_base_metadata_after_feature_enable() -> None:
    reset_module_registry()
    provision_and_enable_knowledge_base_articles_for_demo()
    starting_event_count = len(app.state.audit_logger.events)

    response = client.get(
        "/v1/source-objects/kb-article-version-backup-runbook-v1-demo/versions/v1/metadata",
        headers=DEMO_KB_ARTICLE_HEADERS,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["origin"] == "knowledge_base"
    assert body["module_id"] == "knowledge_base"
    assert body["module_status"] == "enabled"
    assert body["source_object_type"] == "wiki"
    assert body["title"] == "Backup Restore Runbook v1"
    assert body["access_checked"] is True
    assert body["content_included"] is False
    assert body["preview_slots"][0]["surface"] == "knowledge_base.article.preview"
    assert body["preview_slots"][0]["content_included"] is False
    assert_metadata_first_preview_gate(body["preview_slots"][0])
    assert "knowledge_base.article.read" in body["downstream_surfaces"]
    assert "object_type:kb.article" in body["evidence_refs"]
    assert "Backup restore runbook source content" not in json.dumps(body)

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert new_events[-1].event_type == "source_object.metadata_detail.read"
    assert new_events[-1].source_object_ids == ["kb-article-version-backup-runbook-v1-demo"]
    assert new_events[-1].metadata["origin"] == "knowledge_base"
    assert new_events[-1].metadata["result_contract"] == "metadata_only"


def test_source_object_preview_decision_blocks_content_release_without_required_evidence() -> None:
    starting_event_count = len(app.state.audit_logger.events)
    ledger = app.state.source_object_preview_decision_ledger
    starting_ledger_count = len(ledger.list_decisions(tenant_id="tenant-demo"))

    response = client.post(
        "/v1/source-objects/doc-1/versions/v1/preview-decisions",
        headers=DEMO_HEADERS,
        json={
            "preview_slot_id": "office.document.preview.metadata",
            "preview_policy_id": "preview-policy.document.metadata-first.v1",
            "reason": "request safe document preview decision",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant-demo"
    assert body["schema_version"] == "source_object_preview_decision.v1"
    assert body["result_contract"] == "metadata_only_preview_decision"
    assert body["decision_status"] == "blocked"
    assert body["content_release_allowed"] is False
    assert body["content_included"] is False
    assert body["access_checked"] is True
    assert body["tenant_policy_checked"] is True
    assert body["tenant_preview_policy_enabled"] is False
    assert body["source_object_id"] == "doc-1"
    assert body["source_version_id"] == "v1"
    assert body["preview_slot_id"] == "office.document.preview.metadata"
    assert body["preview_policy_id"] == "preview-policy.document.metadata-first.v1"
    assert body["source_detail_audit_event_id"]
    assert_metadata_first_preview_gate({"gate": body["gate"]})
    assert "source_object_acl_checked" in body["provided_evidence"]
    assert "source_detail_audit_event" in body["provided_evidence"]
    assert "tenant_preview_policy_enabled" in body["missing_evidence"]
    assert "parser_sanitizer_evidence" in body["missing_evidence"]
    assert "human_content_release_confirmation" in body["missing_evidence"]
    assert "renderer_sandbox_worker_evidence" in body["missing_evidence"]
    assert "backup_coverage_evidence" in body["missing_evidence"]
    assert "restore_drill_evidence" in body["missing_evidence"]
    assert "content_preview_skeleton_blocks_release_until_renderer_operational" in body["blocking_reasons"]
    assert body["renderer_sandbox_evidence_verified"] is False
    assert body["backup_coverage_evidence_verified"] is False
    assert body["restore_evidence_verified"] is False
    assert body["human_confirmation_verified"] is False
    assert body["content_release_evidence_complete"] is False
    assert body["preview_decision_evidence_hash"].startswith("sha256:")
    assert body["decision_ledger_ref"] == f"preview-decision-ledger:{body['preview_decision_evidence_hash']}"
    assert body["ledger_entry_persisted"] is True
    assert "Board pack draft source content" not in json.dumps(body)

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert [event.event_type for event in new_events] == [
        "source_object.metadata_detail.read",
        "source_object.preview_decision.blocked",
    ]
    event = new_events[-1]
    assert event.source_object_ids == ["doc-1"]
    assert event.metadata["result_contract"] == "metadata_only"
    assert event.metadata["decision_status"] == "blocked"
    assert event.metadata["content_release_allowed"] is False
    assert event.metadata["content_included"] is False
    assert event.metadata["access_checked"] is True
    assert event.metadata["tenant_policy_checked"] is True
    assert event.metadata["tenant_preview_policy_enabled"] is False
    assert "renderer_sandbox_worker_evidence" in event.metadata["missing_evidence"]
    assert "backup_coverage_evidence" in event.metadata["missing_evidence"]
    assert "restore_drill_evidence" in event.metadata["missing_evidence"]
    assert event.metadata["reason_hash"].startswith("sha256:")
    assert "reason" not in event.metadata

    ledger_entries = ledger.list_decisions(tenant_id="tenant-demo")
    assert len(ledger_entries) == starting_ledger_count + 1
    ledger_evidence = ledger.get(tenant_id="tenant-demo", evidence_hash=body["preview_decision_evidence_hash"])
    assert ledger_evidence.decision_status == "blocked"
    assert ledger_evidence.content_release_allowed is False
    assert ledger_evidence.content_included is False
    assert ledger_evidence.audit_event_id == body["audit_event_id"]
    assert ledger_evidence.reason_hash == event.metadata["reason_hash"]
    assert "Board pack draft source content" not in ledger_evidence.model_dump_json()


def test_source_object_preview_renderer_run_records_metadata_only_evidence_and_audits() -> None:
    starting_event_count = len(app.state.audit_logger.events)
    store = app.state.source_object_preview_renderer_evidence_store
    starting_store_count = len(store.list_evidence(tenant_id="tenant-demo"))

    response = client.post(
        "/v1/source-objects/doc-1/versions/v1/preview-renderer-runs",
        headers=DEMO_HEADERS,
        json={
            "preview_slot_id": "office.document.preview.metadata",
            "preview_policy_id": "preview-policy.document.metadata-first.v1",
            "parser_sanitizer_evidence_ref": "parser-sanitizer:document-preview-worker-1",
            "backup_coverage_evidence_ref": "backup:document-preview-worker-1",
            "restore_evidence_ref": "restore-drill:document-preview-worker-1",
            "reason": "record metadata only renderer sandbox evidence",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant-demo"
    assert body["schema_version"] == "source_object_preview_renderer_sandbox_run.v1"
    assert body["result_contract"] == "metadata_only_renderer_sandbox_worker_evidence"
    assert body["source_object_id"] == "doc-1"
    assert body["source_version_id"] == "v1"
    assert body["source_object_type"] == "document"
    assert body["preview_slot_id"] == "office.document.preview.metadata"
    assert body["preview_policy_id"] == "preview-policy.document.metadata-first.v1"
    assert body["worker_profile_id"] == "source-preview-renderer-sandbox-worker:metadata-only.v1"
    assert body["worker_queue_id"] == "source-preview-renderer-runs"
    assert body["worker_job_id"].startswith("preview-renderer-job:sha256:")
    assert body["worker_idempotency_key_hash"].startswith("sha256:")
    assert body["worker_queue_binding_ref"] == (
        f"worker-queue:source-preview-renderer-runs:{body['worker_idempotency_key_hash']}"
    )
    assert body["access_checked"] is True
    assert body["rendering_allowed"] is False
    assert body["content_rendered"] is False
    assert body["content_included"] is False
    assert body["output_persisted"] is False
    assert body["external_fetch_allowed"] is False
    assert body["temporary_workspace_destroyed"] is True
    assert body["renderer_sandbox_evidence_hash"].startswith("sha256:")
    assert body["renderer_sandbox_evidence_ref"] == f"renderer-sandbox:{body['renderer_sandbox_evidence_hash']}"
    assert "raw_source_content_returned=false" in body["sandbox_boundaries"]
    assert "rendered_content_included=false" in body["sandbox_boundaries"]
    assert "Board pack draft source content" not in json.dumps(body)

    evidence = store.get(
        tenant_id="tenant-demo",
        evidence_hash=body["renderer_sandbox_evidence_hash"],
    )
    assert len(store.list_evidence(tenant_id="tenant-demo")) == starting_store_count + 1
    assert evidence.renderer_sandbox_evidence_ref == body["renderer_sandbox_evidence_ref"]
    assert evidence.source_object_id == "doc-1"
    assert evidence.source_manifest_hash.startswith("sha256:")
    assert evidence.source_content_hash.startswith("sha256:")
    assert evidence.source_acl_version == 1
    assert evidence.worker_queue_id == "source-preview-renderer-runs"
    assert evidence.worker_job_id == body["worker_job_id"]
    assert evidence.worker_idempotency_key_hash == body["worker_idempotency_key_hash"]
    assert evidence.worker_queue_binding_ref == body["worker_queue_binding_ref"]
    assert evidence.content_rendered is False
    assert evidence.content_included is False
    assert "Board pack draft source content" not in evidence.model_dump_json()
    assert "record metadata only renderer sandbox evidence" not in evidence.model_dump_json()

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert [event.event_type for event in new_events] == [
        "source_object.metadata_detail.read",
        "source_object.preview_renderer_run.recorded",
    ]
    event = new_events[-1]
    assert event.source_object_ids == ["doc-1"]
    assert event.metadata["result_contract"] == "metadata_only_renderer_sandbox_worker_evidence"
    assert event.metadata["worker_queue_id"] == "source-preview-renderer-runs"
    assert event.metadata["worker_job_id"] == body["worker_job_id"]
    assert event.metadata["worker_idempotency_key_hash"] == body["worker_idempotency_key_hash"]
    assert event.metadata["content_rendered"] is False
    assert event.metadata["content_included"] is False
    assert event.metadata["reason_hash"].startswith("sha256:")
    assert "reason" not in event.metadata


def test_source_object_preview_renderer_run_denies_unreadable_object_without_evidence() -> None:
    starting_event_count = len(app.state.audit_logger.events)
    store = app.state.source_object_preview_renderer_evidence_store
    starting_store_count = len(store.list_evidence(tenant_id="tenant-demo"))

    response = client.post(
        "/v1/source-objects/doc-other/versions/v1/preview-renderer-runs",
        headers=DEMO_HEADERS,
        json={
            "preview_slot_id": "office.document.preview.metadata",
            "preview_policy_id": "preview-policy.document.metadata-first.v1",
            "parser_sanitizer_evidence_ref": "parser-sanitizer:denied-worker-1",
            "backup_coverage_evidence_ref": "backup:denied-worker-1",
            "restore_evidence_ref": "restore-drill:denied-worker-1",
            "reason": "attempt renderer evidence for unreadable document",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "User cannot read requested source object metadata"
    assert len(store.list_evidence(tenant_id="tenant-demo")) == starting_store_count
    new_events = app.state.audit_logger.events[starting_event_count:]
    assert [event.event_type for event in new_events] == ["source_object.metadata_detail.denied"]
    assert new_events[-1].metadata["content_included"] is False


def test_source_object_preview_decision_records_evidence_refs_but_still_blocks_release() -> None:
    starting_event_count = len(app.state.audit_logger.events)
    renderer_response = client.post(
        "/v1/source-objects/mail-1/versions/v1/preview-renderer-runs",
        headers=DEMO_HEADERS,
        json={
            "preview_slot_id": "mail.message.preview.metadata",
            "preview_policy_id": "preview-policy.mail.metadata-first.v1",
            "parser_sanitizer_evidence_ref": "parser-sanitizer:mail-preview-smoke-1",
            "backup_coverage_evidence_ref": "backup:mail-preview-smoke-1",
            "restore_evidence_ref": "restore-drill:mail-preview-smoke-1",
            "reason": "record mail metadata renderer evidence",
        },
    )
    assert renderer_response.status_code == 200
    renderer_ref = renderer_response.json()["renderer_sandbox_evidence_ref"]

    response = client.post(
        "/v1/source-objects/mail-1/versions/v1/preview-decisions",
        headers=DEMO_HEADERS,
        json={
            "preview_slot_id": "mail.message.preview.metadata",
            "preview_policy_id": "preview-policy.mail.metadata-first.v1",
            "reason": "request mail metadata preview decision",
            "parser_sanitizer_evidence_ref": "parser-sanitizer:mail-preview-smoke-1",
            "renderer_sandbox_evidence_ref": renderer_ref,
            "backup_coverage_evidence_ref": "backup:mail-preview-smoke-1",
            "restore_evidence_ref": "restore-drill:mail-preview-smoke-1",
            "human_confirmation_reference": "approval:mail-preview-human-confirmation-1",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["decision_status"] == "blocked"
    assert body["content_release_allowed"] is False
    assert body["source_object_type"] == "mail"
    assert body["gate"]["policy_id"] == "preview-policy.mail.metadata-first.v1"
    assert "parser_sanitizer_evidence" in body["provided_evidence"]
    assert "renderer_sandbox_worker_evidence" in body["provided_evidence"]
    assert "human_content_release_confirmation" in body["provided_evidence"]
    assert "tenant_preview_policy_enabled" in body["missing_evidence"]
    assert "renderer_sandbox_worker_evidence" not in body["missing_evidence"]
    assert "backup_coverage_evidence" not in body["missing_evidence"]
    assert "restore_drill_evidence" not in body["missing_evidence"]
    assert "parser-sanitizer:mail-preview-smoke-1" in body["provided_evidence_refs"]
    assert renderer_ref in body["provided_evidence_refs"]
    assert "backup:mail-preview-smoke-1" in body["provided_evidence_refs"]
    assert "restore-drill:mail-preview-smoke-1" in body["provided_evidence_refs"]
    assert "approval:mail-preview-human-confirmation-1" in body["provided_evidence_refs"]
    assert body["renderer_sandbox_evidence_verified"] is True
    assert body["backup_coverage_evidence_verified"] is True
    assert body["restore_evidence_verified"] is True
    assert body["human_confirmation_verified"] is True
    assert body["content_release_evidence_complete"] is False
    assert "Welcome message source" not in json.dumps(body)

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert new_events[-1].event_type == "source_object.preview_decision.blocked"
    assert "parser_sanitizer_evidence" in new_events[-1].metadata["provided_evidence"]
    assert "renderer_sandbox_worker_evidence" in new_events[-1].metadata["provided_evidence"]
    assert "tenant_preview_policy_enabled" in new_events[-1].metadata["missing_evidence"]


def test_source_object_preview_decision_rejects_unstored_renderer_evidence_as_missing() -> None:
    response = client.post(
        "/v1/source-objects/doc-1/versions/v1/preview-decisions",
        headers=DEMO_HEADERS,
        json={
            "preview_slot_id": "office.document.preview.metadata",
            "preview_policy_id": "preview-policy.document.metadata-first.v1",
            "reason": "request preview with unknown renderer evidence",
            "parser_sanitizer_evidence_ref": "parser-sanitizer:unknown-renderer-1",
            "renderer_sandbox_evidence_ref": "renderer-sandbox:sha256:" + "0" * 64,
            "backup_coverage_evidence_ref": "backup:unknown-renderer-1",
            "restore_evidence_ref": "restore-drill:unknown-renderer-1",
            "human_confirmation_reference": "approval:unknown-renderer-1",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["renderer_sandbox_evidence_verified"] is False
    assert "renderer_sandbox_worker_evidence" in body["missing_evidence"]
    assert "renderer_sandbox_worker_evidence_not_found" in body["blocking_reasons"]
    assert "renderer-sandbox:sha256:" + "0" * 64 not in body["provided_evidence_refs"]
    assert body["renderer_sandbox_evidence_ref"] == "renderer-sandbox:sha256:" + "0" * 64
    assert body["content_release_evidence_complete"] is False


def test_source_object_preview_decision_with_enabled_policy_still_blocks_but_records_complete_evidence() -> None:
    previous_policy_repository = app.state.tenant_policy_repository
    app.state.tenant_policy_repository = InMemoryTenantPolicyRepository(
        policies={
            "tenant-demo": TenantPolicy(
                tenant_id="tenant-demo",
                ai_enabled=True,
                rag_enabled=True,
                voice_enabled=True,
                content_preview_enabled=True,
                raw_audio_storage_allowed=False,
                allowed_model_ids={"mock-summarizer"},
                allowed_data_classes={DataClass.INTERNAL, DataClass.PERSONAL, DataClass.AI_PROMPT},
            )
        }
    )

    try:
        renderer_response = client.post(
            "/v1/source-objects/doc-1/versions/v1/preview-renderer-runs",
            headers=DEMO_HEADERS,
            json={
                "preview_slot_id": "office.document.preview.metadata",
                "preview_policy_id": "preview-policy.document.metadata-first.v1",
                "parser_sanitizer_evidence_ref": "parser-sanitizer:document-preview-smoke-1",
                "backup_coverage_evidence_ref": "backup:preview-ledger-smoke-1",
                "restore_evidence_ref": "restore-drill:preview-ledger-smoke-1",
                "reason": "record document renderer evidence for complete decision",
            },
        )
        assert renderer_response.status_code == 200
        renderer_ref = renderer_response.json()["renderer_sandbox_evidence_ref"]

        response = client.post(
            "/v1/source-objects/doc-1/versions/v1/preview-decisions",
            headers=DEMO_HEADERS,
            json={
                "preview_slot_id": "office.document.preview.metadata",
                "preview_policy_id": "preview-policy.document.metadata-first.v1",
                "reason": "request fully evidenced preview decision",
                "parser_sanitizer_evidence_ref": "parser-sanitizer:document-preview-smoke-1",
                "renderer_sandbox_evidence_ref": renderer_ref,
                "backup_coverage_evidence_ref": "backup:preview-ledger-smoke-1",
                "restore_evidence_ref": "restore-drill:preview-ledger-smoke-1",
                "human_confirmation_reference": "approval:document-preview-human-confirmation-1",
            },
        )
    finally:
        app.state.tenant_policy_repository = previous_policy_repository

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_preview_policy_enabled"] is True
    assert body["missing_evidence"] == []
    assert body["content_release_evidence_complete"] is True
    assert body["renderer_sandbox_evidence_verified"] is True
    assert body["backup_coverage_evidence_verified"] is True
    assert body["restore_evidence_verified"] is True
    assert body["human_confirmation_verified"] is True
    assert "tenant_policy:tenant-demo:content_preview_enabled" in body["provided_evidence_refs"]
    assert "backup:preview-ledger-smoke-1" in body["provided_evidence_refs"]
    assert "restore-drill:preview-ledger-smoke-1" in body["provided_evidence_refs"]
    assert body["decision_status"] == "blocked"
    assert body["content_release_allowed"] is False
    assert "content_preview_skeleton_blocks_release_until_renderer_operational" in body["blocking_reasons"]


def test_source_object_preview_decision_jsonl_ledger_reloads_metadata_only(tmp_path: Path) -> None:
    previous_ledger = app.state.source_object_preview_decision_ledger
    ledger_path = tmp_path / "preview_decisions.jsonl"
    app.state.source_object_preview_decision_ledger = JsonlSourceObjectPreviewDecisionLedger(path=ledger_path)

    try:
        response = client.post(
            "/v1/source-objects/doc-1/versions/v1/preview-decisions",
            headers=DEMO_HEADERS,
            json={
                "preview_slot_id": "office.document.preview.metadata",
                "preview_policy_id": "preview-policy.document.metadata-first.v1",
                "reason": "request persisted preview decision",
            },
        )
    finally:
        app.state.source_object_preview_decision_ledger = previous_ledger

    assert response.status_code == 200
    body = response.json()
    assert ledger_path.exists()
    reloaded_ledger = JsonlSourceObjectPreviewDecisionLedger(path=ledger_path)
    reloaded = reloaded_ledger.get(
        tenant_id="tenant-demo",
        evidence_hash=body["preview_decision_evidence_hash"],
    )
    assert reloaded.source_object_id == "doc-1"
    assert reloaded.content_included is False
    assert reloaded.content_release_allowed is False
    persisted_text = ledger_path.read_text(encoding="utf-8")
    assert "Board pack draft source content" not in persisted_text
    assert "request persisted preview decision" not in persisted_text
    assert reloaded.reason_hash.startswith("sha256:")


def test_source_object_preview_decision_denies_unreadable_object_and_audits_acl_check() -> None:
    starting_event_count = len(app.state.audit_logger.events)
    ledger = app.state.source_object_preview_decision_ledger
    starting_ledger_count = len(ledger.list_decisions(tenant_id="tenant-demo"))

    response = client.post(
        "/v1/source-objects/doc-other/versions/v1/preview-decisions",
        headers=DEMO_HEADERS,
        json={
            "preview_slot_id": "office.document.preview.metadata",
            "preview_policy_id": "preview-policy.document.metadata-first.v1",
            "reason": "request preview for unreadable document",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "User cannot request preview decision for source object"
    new_events = app.state.audit_logger.events[starting_event_count:]
    assert [event.event_type for event in new_events] == ["source_object.preview_decision.denied"]
    assert new_events[-1].source_object_ids == ["doc-other"]
    assert new_events[-1].metadata["denial_reason"] == "acl_object_not_readable"
    assert new_events[-1].metadata["content_included"] is False
    assert new_events[-1].metadata["access_checked"] is True
    assert new_events[-1].metadata["reason_hash"].startswith("sha256:")
    assert len(ledger.list_decisions(tenant_id="tenant-demo")) == starting_ledger_count


def test_source_object_preview_decision_rejects_preview_policy_mismatch() -> None:
    starting_event_count = len(app.state.audit_logger.events)

    response = client.post(
        "/v1/source-objects/doc-1/versions/v1/preview-decisions",
        headers=DEMO_HEADERS,
        json={
            "preview_slot_id": "office.document.preview.metadata",
            "preview_policy_id": "preview-policy.mail.metadata-first.v1",
            "reason": "request preview with mismatched policy",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Preview policy does not match selected slot"
    new_events = app.state.audit_logger.events[starting_event_count:]
    assert [event.event_type for event in new_events] == [
        "source_object.metadata_detail.read",
        "source_object.preview_decision.rejected",
    ]
    assert new_events[-1].metadata["rejection_reason"] == "preview_policy_mismatch"
    assert new_events[-1].metadata["content_included"] is False
    assert new_events[-1].metadata["access_checked"] is True
    assert new_events[-1].metadata["reason_hash"].startswith("sha256:")


def test_module_api_gate_dependency_blocks_normal_routes_and_allows_compliance_routes() -> None:
    module_registry = default_module_registry()
    probe_client = TestClient(build_module_gate_probe_app(module_registry))

    unavailable_response = probe_client.get("/normal", headers=DEMO_HEADERS)
    assert unavailable_response.status_code == 403
    assert "not enabled" in unavailable_response.json()["detail"]

    module_registry.provision_tenant_module(
        tenant_id="tenant-demo",
        module_id="crm_erp",
        policy_snapshot_hash="sha256:policy",
        changed_by="admin-1",
        audit_chain_ref="audit:provision",
        migration_manifest_entries=load_migration_manifest(),
    )
    module_registry.enable_tenant_module(
        tenant_id="tenant-demo",
        module_id="crm_erp",
        policy_snapshot_hash="sha256:policy",
        changed_by="admin-1",
        audit_chain_ref="audit:enable",
        enabled_features={"crm_erp.crm.accounts": True},
    )

    normal_response = probe_client.get("/normal", headers=DEMO_HEADERS)
    assert normal_response.status_code == 200
    normal_body = normal_response.json()
    assert normal_body["tenant_id"] == "tenant-demo"
    assert normal_body["surface"] == "normal_api"
    assert normal_body["status"] == "enabled"
    assert normal_body["feature_id"] == "crm_erp.crm.accounts"
    assert normal_body["normal_use_enabled"] is True

    module_registry.disable_tenant_module(
        tenant_id="tenant-demo",
        module_id="crm_erp",
        policy_snapshot_hash="sha256:policy",
        changed_by="admin-1",
        audit_chain_ref="audit:disable",
    )

    disabled_normal_response = probe_client.get("/normal", headers=DEMO_HEADERS)
    assert disabled_normal_response.status_code == 403
    assert "not enabled" in disabled_normal_response.json()["detail"]

    compliance_response = probe_client.get("/compliance", headers=DEMO_HEADERS)
    assert compliance_response.status_code == 200
    compliance_body = compliance_response.json()
    assert compliance_body["surface"] == "compliance_api"
    assert compliance_body["status"] == "disabled"
    assert compliance_body["normal_use_enabled"] is False
    assert compliance_body["compliance_access_allowed"] is True


def test_crm_accounts_endpoint_requires_enabled_module_feature() -> None:
    reset_module_registry()

    response = client.get("/v1/crm/accounts", headers=DEMO_CRM_ACCOUNT_HEADERS)

    assert response.status_code == 403
    assert "not enabled" in response.json()["detail"]


def test_crm_accounts_endpoint_returns_tenant_scoped_accounts_after_feature_enable() -> None:
    reset_module_registry()
    starting_event_count = len(app.state.audit_logger.events)
    provision_and_enable_crm_accounts_for_demo()

    response = client.get("/v1/crm/accounts", headers=DEMO_CRM_ACCOUNT_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant-demo"
    assert body["module_id"] == "crm_erp"
    assert body["feature_id"] == "crm_erp.crm.accounts"
    assert body["audit_event_id"]
    assert [account["display_name"] for account in body["accounts"]] == ["Acme Demo GmbH", "Northwind Demo AG"]
    assert {account["object_type"] for account in body["accounts"]} == {"crm.account"}
    assert {account["data_classification"] for account in body["accounts"]} == {"personal"}
    assert {account["retention_policy_id"] for account in body["accounts"]} == {"rp-standard"}
    assert all(account["access_checked"] for account in body["accounts"])
    assert "Other Tenant AG" not in {account["display_name"] for account in body["accounts"]}

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert new_events[-1].event_type == "crm.account.list"
    assert new_events[-1].tenant_id == "tenant-demo"
    assert new_events[-1].input_hash is None
    assert new_events[-1].output_hash is None
    assert new_events[-1].metadata["candidate_count"] == 2
    assert new_events[-1].metadata["result_count"] == 2
    assert new_events[-1].metadata["result_contract"] == "metadata_only"


def test_crm_contacts_endpoint_requires_enabled_module_feature() -> None:
    reset_module_registry()

    response = client.get("/v1/crm/contacts", headers=DEMO_CRM_CONTACT_HEADERS)

    assert response.status_code == 403
    assert "not enabled" in response.json()["detail"]


def test_crm_contacts_endpoint_returns_tenant_scoped_contacts_after_feature_enable() -> None:
    reset_module_registry()
    starting_event_count = len(app.state.audit_logger.events)
    provision_and_enable_crm_contacts_for_demo()

    response = client.get("/v1/crm/contacts", headers=DEMO_CRM_CONTACT_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant-demo"
    assert body["module_id"] == "crm_erp"
    assert body["feature_id"] == "crm_erp.crm.contacts"
    assert body["audit_event_id"]
    assert [contact["display_name"] for contact in body["contacts"]] == ["Ada Demo", "Max Demo"]
    assert {contact["object_type"] for contact in body["contacts"]} == {"crm.contact"}
    assert {contact["data_classification"] for contact in body["contacts"]} == {"personal"}
    assert {contact["retention_policy_id"] for contact in body["contacts"]} == {"rp-standard"}
    assert [contact["account_object_id"] for contact in body["contacts"]] == [
        "crm-account-acme-demo",
        "crm-account-northwind-demo",
    ]
    assert all(contact["access_checked"] for contact in body["contacts"])
    assert all(contact["linked_account_access_checked"] for contact in body["contacts"])
    assert "Other Contact" not in {contact["display_name"] for contact in body["contacts"]}

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert new_events[-1].event_type == "crm.contact.list"
    assert new_events[-1].tenant_id == "tenant-demo"
    assert new_events[-1].input_hash is None
    assert new_events[-1].output_hash is None
    assert new_events[-1].metadata["candidate_count"] == 2
    assert new_events[-1].metadata["result_count"] == 2
    assert new_events[-1].metadata["redacted_account_link_count"] == 0
    assert new_events[-1].metadata["result_contract"] == "metadata_only"


def test_crm_activities_and_notes_endpoints_require_enabled_module_feature() -> None:
    reset_module_registry()

    activities_response = client.get("/v1/crm/activities", headers=DEMO_CRM_ACTIVITY_HEADERS)
    notes_response = client.get("/v1/crm/notes", headers=DEMO_CRM_ACTIVITY_HEADERS)

    assert activities_response.status_code == 403
    assert notes_response.status_code == 403
    assert "not enabled" in activities_response.json()["detail"]
    assert "not enabled" in notes_response.json()["detail"]


def test_crm_activities_endpoint_returns_tenant_scoped_activities_after_feature_enable() -> None:
    reset_module_registry()
    starting_event_count = len(app.state.audit_logger.events)
    provision_and_enable_crm_activities_for_demo()

    response = client.get("/v1/crm/activities", headers=DEMO_CRM_ACTIVITY_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant-demo"
    assert body["module_id"] == "crm_erp"
    assert body["feature_id"] == "crm_erp.crm.activities"
    assert body["audit_event_id"]
    assert [activity["subject"] for activity in body["activities"]] == ["Acme follow-up", "Northwind review"]
    assert {activity["object_type"] for activity in body["activities"]} == {"crm.activity"}
    assert {activity["data_classification"] for activity in body["activities"]} == {"personal"}
    assert {activity["retention_policy_id"] for activity in body["activities"]} == {"rp-standard"}
    assert [activity["contact_object_id"] for activity in body["activities"]] == [
        "crm-contact-ada-demo",
        "crm-contact-max-demo",
    ]
    assert all(activity["access_checked"] for activity in body["activities"])
    assert all(activity["linked_object_access_checked"] for activity in body["activities"])
    assert "Other tenant task" not in {activity["subject"] for activity in body["activities"]}

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert new_events[-1].event_type == "crm.activity.list"
    assert new_events[-1].tenant_id == "tenant-demo"
    assert new_events[-1].input_hash is None
    assert new_events[-1].output_hash is None
    assert new_events[-1].metadata["candidate_count"] == 2
    assert new_events[-1].metadata["result_count"] == 2
    assert new_events[-1].metadata["redacted_link_count"] == 0
    assert new_events[-1].metadata["result_contract"] == "metadata_only"


def test_crm_notes_endpoint_returns_metadata_only_notes_after_feature_enable() -> None:
    reset_module_registry()
    starting_event_count = len(app.state.audit_logger.events)
    provision_and_enable_crm_activities_for_demo()

    response = client.get("/v1/crm/notes", headers=DEMO_CRM_ACTIVITY_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant-demo"
    assert body["module_id"] == "crm_erp"
    assert body["feature_id"] == "crm_erp.crm.activities"
    assert body["audit_event_id"]
    assert [note["title"] for note in body["notes"]] == ["Acme onboarding note", "Northwind review note"]
    assert {note["object_type"] for note in body["notes"]} == {"crm.note"}
    assert {note["data_classification"] for note in body["notes"]} == {"personal"}
    assert {note["retention_policy_id"] for note in body["notes"]} == {"rp-standard"}
    assert all(note["access_checked"] for note in body["notes"])
    assert all(note["linked_object_access_checked"] for note in body["notes"])
    assert all("note_body" not in note for note in body["notes"])
    assert "Other tenant note" not in {note["title"] for note in body["notes"]}

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert new_events[-1].event_type == "crm.note.list"
    assert new_events[-1].tenant_id == "tenant-demo"
    assert new_events[-1].input_hash is None
    assert new_events[-1].output_hash is None
    assert new_events[-1].metadata["candidate_count"] == 2
    assert new_events[-1].metadata["result_count"] == 2
    assert new_events[-1].metadata["redacted_link_count"] == 0
    assert new_events[-1].metadata["result_contract"] == "metadata_only"


def test_erp_products_endpoint_requires_enabled_module_feature() -> None:
    reset_module_registry()

    response = client.get("/v1/erp/products", headers=DEMO_ERP_PRODUCT_HEADERS)

    assert response.status_code == 403
    assert "not enabled" in response.json()["detail"]


def test_erp_products_endpoint_returns_internal_products_after_feature_enable() -> None:
    reset_module_registry()
    starting_event_count = len(app.state.audit_logger.events)
    provision_and_enable_erp_products_for_demo()

    response = client.get("/v1/erp/products", headers=DEMO_ERP_PRODUCT_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant-demo"
    assert body["module_id"] == "crm_erp"
    assert body["feature_id"] == "crm_erp.erp.products"
    assert body["audit_event_id"]
    assert [product["display_name"] for product in body["products"]] == ["Service Plan", "Standard Widget"]
    assert {product["object_type"] for product in body["products"]} == {"erp.product"}
    assert {product["data_classification"] for product in body["products"]} == {"internal"}
    assert {product["retention_policy_id"] for product in body["products"]} == {"rp-standard"}
    assert all(product["access_checked"] for product in body["products"])
    assert "Other Tenant Product" not in {product["display_name"] for product in body["products"]}

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert new_events[-1].event_type == "erp.product.list"
    assert new_events[-1].tenant_id == "tenant-demo"
    assert new_events[-1].input_hash is None
    assert new_events[-1].output_hash is None
    assert new_events[-1].metadata["candidate_count"] == 2
    assert new_events[-1].metadata["result_count"] == 2
    assert new_events[-1].metadata["result_contract"] == "metadata_only"


def test_knowledge_base_articles_endpoint_requires_enabled_module_feature() -> None:
    reset_module_registry()

    response = client.get("/v1/kb/articles", headers=DEMO_KB_ARTICLE_HEADERS)

    assert response.status_code == 403
    assert "not enabled" in response.json()["detail"]


def test_knowledge_base_articles_endpoint_returns_metadata_after_feature_enable() -> None:
    reset_module_registry()
    starting_event_count = len(app.state.audit_logger.events)
    provision_and_enable_knowledge_base_articles_for_demo()

    response = client.get("/v1/kb/articles", headers=DEMO_KB_ARTICLE_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant-demo"
    assert body["module_id"] == "knowledge_base"
    assert body["feature_id"] == "knowledge_base.articles.read"
    assert body["audit_event_id"]
    assert body["restore_evidence_hash"].startswith("sha256:")
    assert len(body["source_version_evidence_hashes"]) == 2
    assert [article["title"] for article in body["articles"]] == ["Backup Restore Runbook", "Security Baseline"]
    assert {article["object_type"] for article in body["articles"]} == {"kb.article"}
    assert {article["data_classification"] for article in body["articles"]} == {"internal"}
    assert {article["retention_policy_id"] for article in body["articles"]} == {"rp-standard"}
    assert all(article["access_checked"] for article in body["articles"])
    assert all(article["source_version_access_checked"] for article in body["articles"])
    assert {article["current_source_version_id"] for article in body["articles"]} == {"v1"}
    assert all(article["source_version_evidence_hash"].startswith("sha256:") for article in body["articles"])
    assert all("article_body" not in article for article in body["articles"])
    assert "Other Tenant Article" not in {article["title"] for article in body["articles"]}

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert new_events[-1].event_type == "knowledge_base.article.list"
    assert new_events[-1].tenant_id == "tenant-demo"
    assert new_events[-1].input_hash is None
    assert new_events[-1].output_hash is None
    assert new_events[-1].metadata["candidate_count"] == 2
    assert new_events[-1].metadata["result_count"] == 2
    assert new_events[-1].metadata["result_contract"] == "metadata_only"
    assert new_events[-1].metadata["continuity_domain"] == "knowledge_base_content"
    assert new_events[-1].metadata["restore_evidence_hash"] == body["restore_evidence_hash"]
    assert new_events[-1].metadata["source_version_evidence_hashes"] == body["source_version_evidence_hashes"]


def test_knowledge_base_admin_evidence_endpoint_is_compliance_scoped_and_metadata_only() -> None:
    reset_module_registry()
    starting_event_count = len(app.state.audit_logger.events)
    provision_response = client.post(
        "/v1/admin/tenant-modules/knowledge_base/provision",
        headers=DEMO_ADMIN_HEADERS,
        json={"approval_reference": "approval:module-provision", "reason": "prepare knowledge base evidence"},
    )
    assert provision_response.status_code == 200
    assert provision_response.json()["status"] == "disabled"

    normal_response = client.get("/v1/kb/articles", headers=DEMO_KB_ARTICLE_HEADERS)
    assert normal_response.status_code == 403
    assert "not enabled" in normal_response.json()["detail"]

    non_admin_response = client.get("/v1/admin/kb/evidence", headers=DEMO_HEADERS)
    assert non_admin_response.status_code == 403
    assert non_admin_response.json()["detail"] == "Tenant admin role required"

    response = client.get("/v1/admin/kb/evidence", headers=DEMO_ADMIN_HEADERS)

    assert response.status_code == 200
    body = response.json()
    body_text = json.dumps(body)
    assert body["tenant_id"] == "tenant-demo"
    assert body["module_id"] == "knowledge_base"
    assert body["continuity_domain"] == "knowledge_base_content"
    assert len(body["source_version_evidence"]) == 2
    assert body["restore_evidence"]["source_version_evidence_count"] == 2
    assert body["restore_evidence"]["disabled_state_restore_verified"] is True
    assert body["restore_evidence"]["legal_hold_restore_verified"] is True
    assert body["restore_evidence"]["evidence_hash"].startswith("sha256:")
    assert {evidence["source_version_id"] for evidence in body["source_version_evidence"]} == {"v1"}
    assert all(evidence["evidence_hash"].startswith("sha256:") for evidence in body["source_version_evidence"])
    assert "article_body" not in body_text
    assert "source content" not in body_text
    assert "prompt_text" not in body_text
    assert "output_text" not in body_text

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert new_events[-1].event_type == "knowledge_base.evidence.read"
    assert new_events[-1].tenant_id == "tenant-demo"
    assert new_events[-1].input_hash is None
    assert new_events[-1].output_hash is None
    assert new_events[-1].metadata["surface"] == "compliance_api"
    assert new_events[-1].metadata["result_contract"] == "metadata_only"
    assert new_events[-1].metadata["restore_evidence_hash"] == body["restore_evidence"]["evidence_hash"]


def test_knowledge_base_runtime_reconcile_endpoint_requires_active_runtime() -> None:
    reset_module_registry()
    starting_event_count = len(app.state.audit_logger.events)
    provision_response = client.post(
        "/v1/admin/tenant-modules/knowledge_base/provision",
        headers=DEMO_ADMIN_HEADERS,
        json={"approval_reference": "approval:module-provision", "reason": "prepare knowledge base runtime reconcile"},
    )
    assert provision_response.status_code == 200

    non_admin_response = client.post("/v1/admin/kb/runtime/reconcile", headers=DEMO_HEADERS)
    assert non_admin_response.status_code == 403
    assert non_admin_response.json()["detail"] == "Tenant admin role required"

    response = client.post("/v1/admin/kb/runtime/reconcile", headers=DEMO_ADMIN_HEADERS)

    assert response.status_code == 404
    assert response.json()["detail"] == "No active Knowledge Base runtime"
    new_events = app.state.audit_logger.events[starting_event_count:]
    assert new_events[-1].event_type == "knowledge_base.runtime.reconcile"
    assert new_events[-1].tenant_id == "tenant-demo"
    assert new_events[-1].input_hash is None
    assert new_events[-1].output_hash is None
    assert new_events[-1].metadata["surface"] == "compliance_api"
    assert new_events[-1].metadata["result_contract"] == "metadata_only"


def test_knowledge_base_write_dry_run_endpoint_requires_admin_and_does_not_persist() -> None:
    reset_module_registry()
    starting_event_count = len(app.state.audit_logger.events)
    write_approval_ledger = app.state.knowledge_base_article_service.write_approval_ledger
    starting_ledger_count = len(write_approval_ledger.list_evidence(tenant_id="tenant-demo"))
    provision_response = client.post(
        "/v1/admin/tenant-modules/knowledge_base/provision",
        headers=DEMO_ADMIN_HEADERS,
        json={"approval_reference": "approval:module-provision", "reason": "prepare knowledge base write dry-run"},
    )
    assert provision_response.status_code == 200
    assert provision_response.json()["status"] == "disabled"
    proposed_source_record = knowledge_base_source_record_for_api_write()
    payload = {
        "approval_reference": "approval:kb-write-dry-run",
        "reason": "prepare controlled knowledge base edit",
        "operation": "edit",
        "article_object_id": "kb-article-backup-runbook-demo",
        "article_key": "KB-BACKUP-001",
        "title": "Backup Restore Runbook",
        "proposed_version_object_id": "kb-article-version-backup-runbook-v2-demo",
        "proposed_version_label": "v2",
        "proposed_source_object_id": "kb-article-version-backup-runbook-v2-demo",
        "proposed_source_version_id": "v2",
        "proposed_source_manifest_hash": proposed_source_record.metadata.manifest_hash,
        "proposed_content_hash": proposed_source_record.metadata.content_hash,
        "proposed_acl_version": 1,
        "expected_current_version_object_id": "kb-article-version-backup-runbook-v1-demo",
    }

    normal_response = client.get("/v1/kb/articles", headers=DEMO_KB_ARTICLE_HEADERS)
    assert normal_response.status_code == 403

    non_admin_response = client.post("/v1/admin/kb/articles/write-dry-run", headers=DEMO_HEADERS, json=payload)
    assert non_admin_response.status_code == 403
    assert non_admin_response.json()["detail"] == "Tenant admin role required"

    response = client.post("/v1/admin/kb/articles/write-dry-run", headers=DEMO_ADMIN_HEADERS, json=payload)

    assert response.status_code == 200
    body = response.json()
    body_text = json.dumps(body)
    assert body["tenant_id"] == "tenant-demo"
    assert body["module_id"] == "knowledge_base"
    assert body["feature_id"] == "knowledge_base.articles.write"
    assert body["operation"] == "edit"
    assert body["dry_run"] is True
    assert body["persistence_allowed"] is False
    assert body["rag_indexing_allowed"] is False
    assert body["source_authority_verified"] is False
    assert body["command_hash"].startswith("sha256:")
    assert body["proposed_source_version_evidence_hash"].startswith("sha256:")
    assert body["current_restore_evidence_hash"].startswith("sha256:")
    assert body["write_approval_evidence_hash"].startswith("sha256:")
    assert "write_approval_ledger_entry" in body["required_evidence"]
    assert "source_object_write_guard" in body["required_evidence"]
    ledger_evidences = write_approval_ledger.list_evidence(tenant_id="tenant-demo")
    assert len(ledger_evidences) == starting_ledger_count + 1
    ledger_evidence = next(
        evidence for evidence in ledger_evidences if evidence.evidence_hash == body["write_approval_evidence_hash"]
    )
    assert ledger_evidence.approval_reference == "approval:kb-write-dry-run"
    assert ledger_evidence.approval_state == "dry_run"
    assert ledger_evidence.persistence_allowed is False
    assert ledger_evidence.rag_indexing_allowed is False
    assert ledger_evidence.source_authority_verified is False
    assert write_approval_ledger.list_evidence(tenant_id="tenant-other") == ()
    assert "article_body" not in ledger_evidence.model_dump_json()
    assert "article_body" not in body_text
    assert "source content" not in body_text
    assert "prompt_text" not in body_text
    assert "output_text" not in body_text

    approval_payload = {
        "dry_run_write_approval_evidence_hash": body["write_approval_evidence_hash"],
        "approval_reference": "approval:kb-write-approve",
        "reason": "human approved guarded knowledge base write",
    }
    non_admin_approval_response = client.post(
        "/v1/admin/kb/articles/write-approvals/approve",
        headers=DEMO_HEADERS,
        json=approval_payload,
    )
    assert non_admin_approval_response.status_code == 403
    assert non_admin_approval_response.json()["detail"] == "Tenant admin role required"

    approval_response = client.post(
        "/v1/admin/kb/articles/write-approvals/approve",
        headers=DEMO_ADMIN_HEADERS,
        json=approval_payload,
    )
    assert approval_response.status_code == 200
    approval_body = approval_response.json()
    approval_body_text = json.dumps(approval_body)
    assert approval_body["tenant_id"] == "tenant-demo"
    assert approval_body["module_id"] == "knowledge_base"
    assert approval_body["feature_id"] == "knowledge_base.articles.write"
    assert approval_body["dry_run_write_approval_evidence_hash"] == body["write_approval_evidence_hash"]
    assert approval_body["approved_write_approval_evidence_hash"].startswith("sha256:")
    assert approval_body["approved_write_approval_evidence_hash"] != body["write_approval_evidence_hash"]
    assert approval_body["approval_state"] == "approved_for_write"
    assert approval_body["persistence_allowed"] is True
    assert approval_body["rag_indexing_allowed"] is False
    assert approval_body["source_authority_verified"] is False
    assert "approved_write_approval_ledger_entry" in approval_body["required_evidence"]
    ledger_evidences = write_approval_ledger.list_evidence(tenant_id="tenant-demo")
    assert len(ledger_evidences) == starting_ledger_count + 2
    approved_evidence = next(
        evidence
        for evidence in ledger_evidences
        if evidence.evidence_hash == approval_body["approved_write_approval_evidence_hash"]
    )
    assert approved_evidence.approval_state == "approved_for_write"
    assert approved_evidence.transition_source_evidence_hash == ledger_evidence.evidence_hash
    assert approved_evidence.persistence_allowed is True
    assert approved_evidence.rag_indexing_allowed is False
    assert approved_evidence.source_authority_verified is False
    assert "article_body" not in approval_body_text
    assert "source content" not in approval_body_text
    assert "prompt_text" not in approval_body_text
    assert "output_text" not in approval_body_text

    refresh_payload = {
        "approved_write_approval_evidence_hash": approval_body["approved_write_approval_evidence_hash"],
        "preview_reference": "preview:kb-refresh-api",
        "reason": "preview metadata-only source and restore evidence refresh",
    }
    non_admin_refresh_response = client.post(
        "/v1/admin/kb/articles/write-approvals/refresh-preview",
        headers=DEMO_HEADERS,
        json=refresh_payload,
    )
    assert non_admin_refresh_response.status_code == 403
    assert non_admin_refresh_response.json()["detail"] == "Tenant admin role required"

    refresh_response = client.post(
        "/v1/admin/kb/articles/write-approvals/refresh-preview",
        headers=DEMO_ADMIN_HEADERS,
        json=refresh_payload,
    )
    assert refresh_response.status_code == 200
    refresh_body = refresh_response.json()
    refresh_body_text = json.dumps(refresh_body)
    assert refresh_body["tenant_id"] == "tenant-demo"
    assert refresh_body["module_id"] == "knowledge_base"
    assert refresh_body["feature_id"] == "knowledge_base.articles.write"
    assert (
        refresh_body["approved_write_approval_evidence_hash"] == approval_body["approved_write_approval_evidence_hash"]
    )
    assert refresh_body["transition_source_evidence_hash"] == body["write_approval_evidence_hash"]
    assert refresh_body["operation"] == "edit"
    assert refresh_body["command_hash"] == approval_body["command_hash"]
    assert refresh_body["preview_command_hash"].startswith("sha256:")
    assert (
        refresh_body["proposed_source_version_evidence_hash"] == approval_body["proposed_source_version_evidence_hash"]
    )
    assert refresh_body["current_restore_evidence_hash"] == approval_body["current_restore_evidence_hash"]
    assert refresh_body["projected_restore_evidence_preview_hash"].startswith("sha256:")
    assert refresh_body["article_count_before"] == 2
    assert refresh_body["article_count_after"] == 2
    assert refresh_body["source_version_evidence_count_before"] == 2
    assert refresh_body["source_version_evidence_count_after"] == 2
    assert refresh_body["preview_only"] is True
    assert refresh_body["article_source_writes_allowed"] is False
    assert refresh_body["evidence_persistence_allowed"] is False
    assert refresh_body["rag_indexing_allowed"] is False
    assert refresh_body["source_authority_verified"] is False
    assert "projected_restore_evidence_preview_hash" in refresh_body["required_evidence"]
    assert (
        refresh_body["proposed_source_version_evidence_hash"]
        not in refresh_body["current_source_version_evidence_hashes"]
    )
    assert (
        refresh_body["proposed_source_version_evidence_hash"]
        in refresh_body["projected_source_version_evidence_hashes"]
    )
    assert len(write_approval_ledger.list_evidence(tenant_id="tenant-demo")) == starting_ledger_count + 2
    assert "article_body" not in refresh_body_text
    assert "source content" not in refresh_body_text
    assert "prompt_text" not in refresh_body_text
    assert "output_text" not in refresh_body_text

    guard_decision_draft = KnowledgeBaseSourceObjectWriteGuardDecision(
        tenant_id="tenant-demo",
        source_object_write_guard_ref="guard:pending",
        allowed=True,
        blocking_reasons=(),
        write_approval_evidence_hash=approval_body["approved_write_approval_evidence_hash"],
        approval_state=KnowledgeBaseWriteApprovalState.APPROVED_FOR_WRITE,
        operation=KnowledgeBaseWriteOperation.EDIT,
        article_object_id=str(payload["article_object_id"]),
        expected_current_version_object_id=str(payload["expected_current_version_object_id"]),
        proposed_source_object_id=str(payload["proposed_source_object_id"]),
        proposed_source_version_id=str(payload["proposed_source_version_id"]),
        proposed_source_version_evidence_hash=approval_body["proposed_source_version_evidence_hash"],
        current_restore_evidence_hash=approval_body["current_restore_evidence_hash"],
        persistence_allowed=True,
        rag_indexing_allowed=False,
        source_authority_verified=True,
    )
    guard_decision = guard_decision_draft.model_copy(
        update={"source_object_write_guard_ref": build_source_object_write_guard_ref(guard_decision_draft)}
    )
    execution_payload = {
        "approved_write_approval_evidence_hash": approval_body["approved_write_approval_evidence_hash"],
        "source_object_write_guard_decision": guard_decision.model_dump(mode="json"),
        "refresh_preview_command_hash": refresh_body["preview_command_hash"],
        "projected_restore_evidence_preview_hash": refresh_body["projected_restore_evidence_preview_hash"],
        "execution_reference": "execution:kb-write-api",
        "human_confirmation_reference": "human-confirmation:kb-write-api",
        "reason": "prepare guarded write execution skeleton",
    }
    non_admin_execution_response = client.post(
        "/v1/admin/kb/articles/write-approvals/execution-skeleton",
        headers=DEMO_HEADERS,
        json=execution_payload,
    )
    assert non_admin_execution_response.status_code == 403
    assert non_admin_execution_response.json()["detail"] == "Tenant admin role required"

    execution_response = client.post(
        "/v1/admin/kb/articles/write-approvals/execution-skeleton",
        headers=DEMO_ADMIN_HEADERS,
        json=execution_payload,
    )
    assert execution_response.status_code == 200
    execution_body = execution_response.json()
    execution_body_text = json.dumps(execution_body)
    assert execution_body["tenant_id"] == "tenant-demo"
    assert execution_body["module_id"] == "knowledge_base"
    assert execution_body["feature_id"] == "knowledge_base.articles.write"
    assert (
        execution_body["approved_write_approval_evidence_hash"]
        == approval_body["approved_write_approval_evidence_hash"]
    )
    assert execution_body["source_object_write_guard_ref"] == guard_decision.source_object_write_guard_ref
    assert execution_body["refresh_preview_command_hash"] == refresh_body["preview_command_hash"]
    assert (
        execution_body["projected_restore_evidence_preview_hash"]
        == refresh_body["projected_restore_evidence_preview_hash"]
    )
    assert execution_body["human_confirmation_reference"] == "human-confirmation:kb-write-api"
    assert execution_body["preconditions_verified"] is True
    assert execution_body["source_object_write_guard_verified"] is True
    assert execution_body["human_confirmation_verified"] is True
    assert execution_body["source_authority_verified"] is True
    assert execution_body["execution_allowed"] is False
    assert execution_body["article_source_writes_allowed"] is False
    assert execution_body["article_metadata_persistence_allowed"] is False
    assert execution_body["source_object_persistence_allowed"] is False
    assert execution_body["evidence_persistence_allowed"] is False
    assert execution_body["rag_indexing_allowed"] is False
    assert "write_execution_adapter_not_enabled" in execution_body["blocking_reasons"]
    assert "explicit_human_confirmation_reference" in execution_body["required_evidence"]
    assert execution_body["execution_command_hash"].startswith("sha256:")
    assert execution_body["execution_plan_hash"].startswith("sha256:")
    assert len(write_approval_ledger.list_evidence(tenant_id="tenant-demo")) == starting_ledger_count + 2
    assert "article_body" not in execution_body_text
    assert "source content" not in execution_body_text
    assert "prompt_text" not in execution_body_text
    assert "output_text" not in execution_body_text

    write_payload = {
        "approved_write_approval_evidence_hash": approval_body["approved_write_approval_evidence_hash"],
        "source_object_write_guard_decision": guard_decision.model_dump(mode="json"),
        "refresh_preview_command_hash": refresh_body["preview_command_hash"],
        "projected_restore_evidence_preview_hash": refresh_body["projected_restore_evidence_preview_hash"],
        "execution_skeleton_command_hash": execution_body["execution_command_hash"],
        "execution_plan_hash": execution_body["execution_plan_hash"],
        "execution_reference": "execution:kb-write-api",
        "human_confirmation_reference": "human-confirmation:kb-write-api",
        "proposed_source_record": proposed_source_record.model_dump(mode="json"),
        "reason": "execute guarded knowledge base edit",
    }
    non_admin_write_response = client.post(
        "/v1/admin/kb/articles/write-approvals/execute",
        headers=DEMO_HEADERS,
        json=write_payload,
    )
    assert non_admin_write_response.status_code == 403
    assert non_admin_write_response.json()["detail"] == "Tenant admin role required"

    write_response = client.post(
        "/v1/admin/kb/articles/write-approvals/execute",
        headers=DEMO_ADMIN_HEADERS,
        json=write_payload,
    )
    assert write_response.status_code == 200
    write_body = write_response.json()
    write_body_text = json.dumps(write_body)
    assert write_body["tenant_id"] == "tenant-demo"
    assert write_body["module_id"] == "knowledge_base"
    assert write_body["feature_id"] == "knowledge_base.articles.write"
    assert write_body["execution_allowed"] is True
    assert write_body["source_object_persisted"] is True
    assert write_body["source_object_write_receipt_persisted"] is True
    assert write_body["write_unit_of_work_committed"] is True
    assert write_body["write_unit_of_work_contract"] == "knowledge_base_write_unit_of_work.v1"
    assert write_body["write_unit_of_work_transaction_scope"] == "coordinated_repository_calls"
    assert write_body["source_content_recovery_required"] is False
    assert write_body["source_content_recovery_evidence_hash"] is None
    assert write_body["production_write_deployment_gate_evidence_hash"] is None
    assert write_body["article_metadata_persisted"] is True
    assert write_body["article_version_metadata_persisted"] is True
    assert write_body["source_version_evidence_refreshed"] is True
    assert write_body["restore_evidence_refreshed"] is True
    assert write_body["rag_indexing_allowed"] is False
    assert write_body["search_indexing_allowed"] is False
    assert write_body["execution_plan_hash"] == execution_body["execution_plan_hash"]
    assert write_body["current_version_object_id"] == payload["proposed_version_object_id"]
    assert write_body["current_source_version_id"] == payload["proposed_source_version_id"]
    assert (
        write_body["refreshed_source_version_evidence_hash"] == approval_body["proposed_source_version_evidence_hash"]
    )
    assert write_body["refreshed_restore_evidence_hash"].startswith("sha256:")
    assert write_body["refreshed_restore_evidence_hash"] != write_body["previous_restore_evidence_hash"]
    assert write_body["source_object_write_receipt_hash"].startswith("sha256:")
    assert "source_object_persisted" in write_body["required_evidence"]
    assert "source_object_write_receipt_hash" in write_body["required_evidence"]
    assert "write_unit_of_work_commit_contract" in write_body["required_evidence"]
    assert "write_unit_of_work_transaction_scope" in write_body["required_evidence"]
    assert "source_content_recovery_required" in write_body["required_evidence"]
    assert "source_content_recovery_evidence_hash" in write_body["required_evidence"]
    assert "production_write_deployment_gate_evidence_hash" in write_body["required_evidence"]
    assert len(write_approval_ledger.list_evidence(tenant_id="tenant-demo")) == starting_ledger_count + 2
    assert "article_body" not in write_body_text
    assert "source content" not in write_body_text
    assert "prompt_text" not in write_body_text
    assert "output_text" not in write_body_text

    after_response = client.get("/v1/admin/kb/evidence", headers=DEMO_ADMIN_HEADERS)
    assert after_response.status_code == 200
    after_body = after_response.json()
    assert {evidence["source_version_id"] for evidence in after_body["source_version_evidence"]} == {"v1", "v2"}
    assert after_body["restore_evidence"]["evidence_hash"] == write_body["refreshed_restore_evidence_hash"]

    invalid_body_response = client.post(
        "/v1/admin/kb/articles/write-dry-run",
        headers=DEMO_ADMIN_HEADERS,
        json={**payload, "article_body": "must not be accepted"},
    )
    assert invalid_body_response.status_code == 422

    new_events = app.state.audit_logger.events[starting_event_count:]
    dry_run_events = [event for event in new_events if event.event_type == "knowledge_base.write_approval.dry_run"]
    assert len(dry_run_events) == 1
    event = dry_run_events[0]
    assert event.input_hash is not None
    assert event.output_hash is None
    assert event.metadata["surface"] == "compliance_api"
    assert event.metadata["dry_run"] is True
    assert event.metadata["persistence_allowed"] is False
    assert event.metadata["command_hash"] == body["command_hash"]
    assert event.metadata["approval_reference"] == "approval:kb-write-dry-run"
    approval_events = [event for event in new_events if event.event_type == "knowledge_base.write_approval.approved"]
    assert len(approval_events) == 1
    approval_event = approval_events[0]
    assert approval_event.input_hash is not None
    assert approval_event.output_hash is None
    assert approval_event.metadata["approval_reference"] == "approval:kb-write-approve"
    assert approval_event.metadata["dry_run_write_approval_evidence_hash"] == body["write_approval_evidence_hash"]
    assert approval_event.metadata["persistence_allowed"] is True
    assert approval_event.metadata["rag_indexing_allowed"] is False
    refresh_events = [
        event for event in new_events if event.event_type == "knowledge_base.write_approval.refresh_preview"
    ]
    assert len(refresh_events) == 1
    refresh_event = refresh_events[0]
    assert refresh_event.input_hash is not None
    assert refresh_event.output_hash is None
    assert refresh_event.metadata["result_contract"] == "metadata_only"
    assert refresh_event.metadata["preview_reference"] == "preview:kb-refresh-api"
    assert (
        refresh_event.metadata["projected_restore_evidence_preview_hash"]
        == refresh_body["projected_restore_evidence_preview_hash"]
    )
    assert refresh_event.metadata["article_source_writes_allowed"] is False
    assert refresh_event.metadata["evidence_persistence_allowed"] is False
    execution_events = [
        event for event in new_events if event.event_type == "knowledge_base.write_approval.execution_skeleton"
    ]
    assert len(execution_events) == 1
    execution_event = execution_events[0]
    assert execution_event.input_hash is not None
    assert execution_event.output_hash is None
    assert execution_event.metadata["result_contract"] == "metadata_only"
    assert execution_event.metadata["execution_reference"] == "execution:kb-write-api"
    assert execution_event.metadata["human_confirmation_reference"] == "human-confirmation:kb-write-api"
    assert execution_event.metadata["execution_allowed"] is False
    assert execution_event.metadata["execution_plan_hash"] == execution_body["execution_plan_hash"]
    write_events = [event for event in new_events if event.event_type == "knowledge_base.write_approval.executed"]
    assert len(write_events) == 1
    write_event = write_events[0]
    assert write_event.input_hash is not None
    assert write_event.output_hash is None
    assert write_event.metadata["result_contract"] == "metadata_only"
    assert write_event.metadata["execution_reference"] == "execution:kb-write-api"
    assert write_event.metadata["source_object_persisted"] is True
    assert write_event.metadata["source_object_write_receipt_persisted"] is True
    assert write_event.metadata["source_object_write_receipt_hash"] == write_body["source_object_write_receipt_hash"]
    assert write_event.metadata["write_unit_of_work_committed"] is True
    assert write_event.metadata["write_unit_of_work_contract"] == "knowledge_base_write_unit_of_work.v1"
    assert write_event.metadata["write_unit_of_work_transaction_scope"] == "coordinated_repository_calls"
    assert write_event.metadata["source_content_recovery_required"] is False
    assert write_event.metadata["source_content_recovery_evidence_hash"] is None
    assert write_event.metadata["production_write_deployment_gate_evidence_hash"] is None
    assert write_event.metadata["article_metadata_persisted"] is True
    assert write_event.metadata["refreshed_restore_evidence_hash"] == write_body["refreshed_restore_evidence_hash"]


def test_tenant_module_admin_actions_require_admin_role_and_approval_reference() -> None:
    reset_module_registry()

    non_admin_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/provision",
        headers=DEMO_HEADERS,
        json={"approval_reference": "approval:module-provision", "reason": "prepare module"},
    )
    assert non_admin_response.status_code == 403
    assert non_admin_response.json()["detail"] == "Tenant admin role required"

    missing_approval_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/provision",
        headers=DEMO_ADMIN_HEADERS,
        json={"reason": "prepare module"},
    )
    assert missing_approval_response.status_code == 422


def test_tenant_admin_can_provision_enable_disable_and_suspend_module() -> None:
    reset_module_registry()
    starting_event_count = len(app.state.audit_logger.events)

    provision_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/provision",
        headers=DEMO_ADMIN_HEADERS,
        json={"approval_reference": "approval:module-provision", "reason": "prepare module"},
    )
    assert provision_response.status_code == 200
    provisioned = provision_response.json()
    assert provisioned["status"] == "disabled"
    assert provisioned["normal_use_enabled"] is False
    assert provisioned["compliance_access_allowed"] is True
    assert provisioned["audit_chain_ref"].startswith("audit:")
    assert [evidence["version"] for evidence in provisioned["migration_evidence"]] == [
        "0007",
        "0008",
        "0009",
        "0010",
        "0011",
        "0016",
        "0017",
        "0018",
        "0019",
        "0020",
    ]

    enable_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/enable",
        headers=DEMO_ADMIN_HEADERS,
        json={
            "approval_reference": "approval:module-enable",
            "reason": "activate CRM accounts",
            "enabled_features": {"crm_erp.crm.accounts": True},
        },
    )
    assert enable_response.status_code == 200
    enabled = enable_response.json()
    assert enabled["status"] == "enabled"
    assert enabled["normal_use_enabled"] is True
    assert enabled["enabled_features"]["crm_erp.crm.accounts"] is True

    disable_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/disable",
        headers=DEMO_ADMIN_HEADERS,
        json={"approval_reference": "approval:module-disable", "reason": "pause normal usage"},
    )
    assert disable_response.status_code == 200
    disabled = disable_response.json()
    assert disabled["status"] == "disabled"
    assert disabled["normal_use_enabled"] is False
    assert disabled["compliance_access_allowed"] is True

    suspend_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/suspend",
        headers=DEMO_ADMIN_HEADERS,
        json={"approval_reference": "approval:module-suspend", "reason": "compliance review"},
    )
    assert suspend_response.status_code == 200
    suspended = suspend_response.json()
    assert suspended["status"] == "suspended"
    assert suspended["compliance_access_allowed"] is True

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert [event.event_type for event in new_events[-4:]] == [
        "tenant_module.provisioned",
        "tenant_module.enabled",
        "tenant_module.disabled",
        "tenant_module.suspended",
    ]
    assert all(event.input_hash is not None and event.output_hash is None for event in new_events[-4:])
    assert all("reason" not in event.metadata for event in new_events[-4:])


def test_pg_backed_tenant_module_lifecycle_api_smoke_drives_worker_discovery_and_audit(
    live_module_registry_database: LiveModuleRegistryDatabase,
) -> None:
    tenant_id = f"tenant-api-module-smoke-{uuid4().hex}"
    headers = {
        "X-Tenant-Id": tenant_id,
        "X-User-Id": "tenant-admin-api-smoke",
        "X-Role-Ids": "tenant-admin",
        "X-Readable-Object-Ids": "doc-1",
    }
    previous_module_registry = app.state.module_registry
    previous_policy_repository = app.state.tenant_policy_repository
    app.state.module_registry = PgModuleRegistry(database_dsn=live_module_registry_database.app_dsn)
    app.state.tenant_policy_repository = InMemoryTenantPolicyRepository(
        {
            tenant_id: TenantPolicy(
                tenant_id=tenant_id,
                ai_enabled=False,
                allowed_model_ids=set(),
                allowed_data_classes={DataClass.INTERNAL, DataClass.PERSONAL},
                rag_enabled=False,
                voice_enabled=False,
                raw_audio_storage_allowed=False,
            )
        }
    )
    starting_event_count = len(app.state.audit_logger.events)

    try:
        provision_response = client.post(
            "/v1/admin/tenant-modules/knowledge_base/provision",
            headers=headers,
            json={
                "approval_reference": "approval:module-pg-smoke-provision",
                "reason": "prepare postgres module registry smoke tenant",
            },
        )
        enable_response = client.post(
            "/v1/admin/tenant-modules/knowledge_base/enable",
            headers=headers,
            json={
                "approval_reference": "approval:module-pg-smoke-enable",
                "reason": "activate postgres module registry smoke tenant",
                "enabled_features": {"knowledge_base.articles.read": True},
            },
        )
        discovery_response = client.get("/v1/platform/modules", headers=headers)
        disable_response = client.post(
            "/v1/admin/tenant-modules/knowledge_base/disable",
            headers=headers,
            json={
                "approval_reference": "approval:module-pg-smoke-disable",
                "reason": "pause postgres module registry smoke tenant",
            },
        )

        worker_registry = PgModuleRegistry(database_dsn=live_module_registry_database.worker_dsn)
        worker_decision = ModuleWorkerGate(worker_registry).require_compliance_worker(
            tenant_id=tenant_id,
            module_id="knowledge_base",
        )
        worker_states = worker_registry.list_tenant_modules_for_module("knowledge_base")
        new_events = app.state.audit_logger.events[starting_event_count:]
    finally:
        app.state.module_registry = previous_module_registry
        app.state.tenant_policy_repository = previous_policy_repository

    assert provision_response.status_code == 200
    assert provision_response.json()["status"] == "disabled"
    assert [evidence["version"] for evidence in provision_response.json()["migration_evidence"]][-5:] == [
        "0025",
        "0026",
        "0027",
        "0028",
        "0029",
    ]
    assert enable_response.status_code == 200
    assert enable_response.json()["status"] == "enabled"
    assert discovery_response.status_code == 200
    modules_by_id = {module["module_id"]: module for module in discovery_response.json()["modules"]}
    assert modules_by_id["knowledge_base"]["status"] == "enabled"
    assert modules_by_id["knowledge_base"]["normal_use_enabled"] is True
    assert disable_response.status_code == 200
    assert disable_response.json()["status"] == "disabled"
    assert worker_decision.status == "disabled"
    assert worker_decision.compliance_access_allowed
    assert any(state.tenant_id == tenant_id and state.status == "disabled" for state in worker_states)

    lifecycle_events = [event for event in new_events if event.event_type.startswith("tenant_module.")]
    assert [event.event_type for event in lifecycle_events[-3:]] == [
        "tenant_module.provisioned",
        "tenant_module.enabled",
        "tenant_module.disabled",
    ]
    assert all(event.metadata["continuity_domain"] == "module_registry_state" for event in lifecycle_events[-3:])
    assert all(event.metadata["worker_discovery_drill_required"] is True for event in lifecycle_events[-3:])
    assert all("tenant module states" in event.metadata["backup_evidence_artifacts"] for event in lifecycle_events[-3:])


def test_tenant_module_decommission_check_is_admin_scoped_and_audited() -> None:
    reset_module_registry()
    client.post(
        "/v1/admin/tenant-modules/crm_erp/provision",
        headers=DEMO_ADMIN_HEADERS,
        json={"approval_reference": "approval:module-provision", "reason": "prepare module"},
    )
    starting_event_count = len(app.state.audit_logger.events)

    response = client.get("/v1/admin/tenant-modules/crm_erp/decommission-check", headers=DEMO_ADMIN_HEADERS)

    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant-demo"
    assert body["module_id"] == "crm_erp"
    assert body["status"] == "disabled"
    assert body["can_decommission"] is False
    assert "Legal Hold check" in body["required_evidence"]
    assert "backup/restore evidence check" in body["required_evidence"]

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert new_events[-1].event_type == "tenant_module.decommission_check"
    assert new_events[-1].input_hash is None


def test_tenant_module_decommission_request_requires_evidence_and_blocks_normal_use() -> None:
    reset_module_registry()
    client.post(
        "/v1/admin/tenant-modules/crm_erp/provision",
        headers=DEMO_ADMIN_HEADERS,
        json={"approval_reference": "approval:module-provision", "reason": "prepare module"},
    )
    client.post(
        "/v1/admin/tenant-modules/crm_erp/enable",
        headers=DEMO_ADMIN_HEADERS,
        json={
            "approval_reference": "approval:module-enable",
            "reason": "activate CRM accounts",
            "enabled_features": {"crm_erp.crm.accounts": True},
        },
    )
    enabled_request_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/decommission-request",
        headers=DEMO_ADMIN_HEADERS,
        json=DECOMMISSION_REQUEST_PAYLOAD,
    )
    assert enabled_request_response.status_code == 400
    assert "disabled or suspended" in enabled_request_response.json()["detail"]

    client.post(
        "/v1/admin/tenant-modules/crm_erp/disable",
        headers=DEMO_ADMIN_HEADERS,
        json={"approval_reference": "approval:module-disable", "reason": "pause normal usage"},
    )
    starting_event_count = len(app.state.audit_logger.events)

    request_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/decommission-request",
        headers=DEMO_ADMIN_HEADERS,
        json=DECOMMISSION_REQUEST_PAYLOAD,
    )

    assert request_response.status_code == 200
    body = request_response.json()
    assert body["status"] == "decommission_requested"
    assert body["normal_use_enabled"] is False
    assert body["compliance_access_allowed"] is True
    assert body["enabled_features"]["crm_erp.crm.accounts"] is False
    assert body["decommission_evidence_refs"]["retention_evaluation_ref"] == "retention:eval-1"
    assert body["decommission_evidence_refs"]["legal_hold_check_ref"] == "legal-hold:check-1"
    assert body["decommission_evidence_refs"]["export_archive_decision_ref"] == "export:decision-1"
    assert body["decommission_evidence_refs"]["audit_evidence_ref"] == "audit:evidence-1"
    assert body["decommission_evidence_refs"]["backup_restore_evidence_ref"] == "backup:restore-1"

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert new_events[-1].event_type == "tenant_module.decommission_requested"
    assert new_events[-1].input_hash is not None
    assert new_events[-1].metadata["approval_reference"] == "approval:module-decommission-request"
    assert "reason" not in new_events[-1].metadata


def test_tenant_module_decommission_request_requires_all_evidence_refs() -> None:
    reset_module_registry()
    client.post(
        "/v1/admin/tenant-modules/crm_erp/provision",
        headers=DEMO_ADMIN_HEADERS,
        json={"approval_reference": "approval:module-provision", "reason": "prepare module"},
    )
    incomplete_payload = dict(DECOMMISSION_REQUEST_PAYLOAD)
    del incomplete_payload["backup_restore_evidence_ref"]

    response = client.post(
        "/v1/admin/tenant-modules/crm_erp/decommission-request",
        headers=DEMO_ADMIN_HEADERS,
        json=incomplete_payload,
    )

    assert response.status_code == 422


def test_tenant_module_decommission_cancel_returns_to_disabled_and_audits() -> None:
    reset_module_registry()
    client.post(
        "/v1/admin/tenant-modules/crm_erp/provision",
        headers=DEMO_ADMIN_HEADERS,
        json={"approval_reference": "approval:module-provision", "reason": "prepare module"},
    )
    client.post(
        "/v1/admin/tenant-modules/crm_erp/decommission-request",
        headers=DEMO_ADMIN_HEADERS,
        json=DECOMMISSION_REQUEST_PAYLOAD,
    )
    starting_event_count = len(app.state.audit_logger.events)

    cancel_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/decommission-cancel",
        headers=DEMO_ADMIN_HEADERS,
        json=DECOMMISSION_CANCEL_PAYLOAD,
    )

    assert cancel_response.status_code == 200
    cancelled = cancel_response.json()
    assert cancelled["status"] == "disabled"
    assert cancelled["normal_use_enabled"] is False
    assert cancelled["compliance_access_allowed"] is True
    assert cancelled["decommission_cancelled_at_utc"] is not None
    assert cancelled["enabled_features"]["crm_erp.crm.accounts"] is False
    assert cancelled["decommission_evidence_refs"]["cancel_approval_ref"] == "approval:module-decommission-cancel"
    assert cancelled["decommission_evidence_refs"]["cancel_audit_evidence_ref"] == (
        "audit:decommission-cancel-evidence-1"
    )

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert new_events[-1].event_type == "tenant_module.decommission_cancelled"
    assert new_events[-1].input_hash is not None
    assert new_events[-1].metadata["approval_reference"] == "approval:module-decommission-cancel"
    assert "reason" not in new_events[-1].metadata


def test_tenant_module_decommission_block_and_complete_are_audited() -> None:
    reset_module_registry()
    client.post(
        "/v1/admin/tenant-modules/crm_erp/provision",
        headers=DEMO_ADMIN_HEADERS,
        json={"approval_reference": "approval:module-provision", "reason": "prepare module"},
    )
    client.post(
        "/v1/admin/tenant-modules/crm_erp/decommission-request",
        headers=DEMO_ADMIN_HEADERS,
        json=DECOMMISSION_REQUEST_PAYLOAD,
    )
    starting_event_count = len(app.state.audit_logger.events)

    block_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/decommission-block",
        headers=DEMO_ADMIN_HEADERS,
        json=DECOMMISSION_BLOCK_PAYLOAD,
    )

    assert block_response.status_code == 200
    blocked = block_response.json()
    assert blocked["status"] == "decommission_blocked"
    assert blocked["normal_use_enabled"] is False
    assert blocked["compliance_access_allowed"] is True
    assert blocked["decommission_blocked_at_utc"] is not None
    assert blocked["decommission_evidence_refs"]["blocker_report_ref"] == "decommission-blocker:report-1"
    assert blocked["decommission_evidence_refs"]["remediation_plan_ref"] == "decommission-remediation:plan-1"

    incomplete_completion_payload = dict(DECOMMISSION_COMPLETE_PAYLOAD)
    del incomplete_completion_payload["final_data_disposition_ref"]
    incomplete_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/decommission-complete",
        headers=DEMO_ADMIN_HEADERS,
        json=incomplete_completion_payload,
    )
    assert incomplete_response.status_code == 422

    complete_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/decommission-complete",
        headers=DEMO_ADMIN_HEADERS,
        json=DECOMMISSION_COMPLETE_PAYLOAD,
    )

    assert complete_response.status_code == 200
    completed = complete_response.json()
    assert completed["status"] == "decommissioned"
    assert completed["normal_use_enabled"] is False
    assert completed["compliance_access_allowed"] is False
    assert completed["decommissioned_at_utc"] is not None
    assert completed["decommission_evidence_refs"]["final_data_disposition_ref"] == "data-disposition:final-1"
    assert completed["decommission_evidence_refs"]["blocker_report_ref"] == "decommission-blocker:report-1"

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert [event.event_type for event in new_events[-2:]] == [
        "tenant_module.decommission_blocked",
        "tenant_module.decommission_completed",
    ]
    assert all(event.input_hash is not None for event in new_events[-2:])
    assert all("reason" not in event.metadata for event in new_events[-2:])


def test_tenant_module_decommission_reopen_requires_evidence_and_audits() -> None:
    reset_module_registry()
    client.post(
        "/v1/admin/tenant-modules/crm_erp/provision",
        headers=DEMO_ADMIN_HEADERS,
        json={"approval_reference": "approval:module-provision", "reason": "prepare module"},
    )
    client.post(
        "/v1/admin/tenant-modules/crm_erp/decommission-request",
        headers=DEMO_ADMIN_HEADERS,
        json=DECOMMISSION_REQUEST_PAYLOAD,
    )
    client.post(
        "/v1/admin/tenant-modules/crm_erp/decommission-block",
        headers=DEMO_ADMIN_HEADERS,
        json=DECOMMISSION_BLOCK_PAYLOAD,
    )

    incomplete_payload = dict(DECOMMISSION_REOPEN_PAYLOAD)
    del incomplete_payload["reopen_audit_evidence_ref"]
    incomplete_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/decommission-reopen",
        headers=DEMO_ADMIN_HEADERS,
        json=incomplete_payload,
    )
    assert incomplete_response.status_code == 422

    starting_event_count = len(app.state.audit_logger.events)
    reopen_response = client.post(
        "/v1/admin/tenant-modules/crm_erp/decommission-reopen",
        headers=DEMO_ADMIN_HEADERS,
        json=DECOMMISSION_REOPEN_PAYLOAD,
    )

    assert reopen_response.status_code == 200
    reopened = reopen_response.json()
    assert reopened["status"] == "decommission_requested"
    assert reopened["normal_use_enabled"] is False
    assert reopened["compliance_access_allowed"] is True
    assert reopened["decommission_reopened_at_utc"] is not None
    assert reopened["decommission_evidence_refs"]["blocker_report_ref"] == "decommission-blocker:report-1"
    assert reopened["decommission_evidence_refs"]["blocker_remediation_evidence_ref"] == (
        "decommission-remediation:evidence-1"
    )
    assert reopened["decommission_evidence_refs"]["reopen_audit_evidence_ref"] == (
        "audit:decommission-reopen-evidence-1"
    )

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert new_events[-1].event_type == "tenant_module.decommission_reopened"
    assert new_events[-1].input_hash is not None
    assert new_events[-1].metadata["approval_reference"] == "approval:module-decommission-reopen"
    assert "reason" not in new_events[-1].metadata


def test_admin_tenant_policy_requires_admin_role() -> None:
    response = client.get("/v1/admin/tenant-policy", headers=DEMO_HEADERS)
    assert response.status_code == 403
    assert response.json()["detail"] == "Tenant admin role required"


def test_embedding_model_admin_requires_security_admin_role() -> None:
    response = client.get("/v1/admin/embedding-models", headers=DEMO_ADMIN_HEADERS)

    assert response.status_code == 403
    assert response.json()["detail"] == "Security admin role required"


def test_authz_admin_mutations_require_security_admin_role_and_approval_reference() -> None:
    non_security_response = client.post(
        "/v1/admin/authz/roles",
        headers=DEMO_ADMIN_HEADERS,
        json={
            "role_id": "auditor",
            "display_name": "Auditor",
            "approval_reference": "approval:authz-role",
            "reason": "create role",
        },
    )
    assert non_security_response.status_code == 403
    assert non_security_response.json()["detail"] == "Security admin role required"

    missing_approval_response = client.post(
        "/v1/admin/authz/roles",
        headers=DEMO_SECURITY_ADMIN_HEADERS,
        json={"role_id": "auditor", "display_name": "Auditor", "reason": "create role"},
    )
    assert missing_approval_response.status_code == 422


def test_security_admin_can_mutate_authz_store_and_replay_retention_with_audit() -> None:
    suffix = uuid4().hex
    subject = f"authz-subject-{suffix}"
    role_id = f"authz-role-{suffix}"
    group_id = f"authz-group-{suffix}"
    object_id = f"authz-doc-{suffix}"
    policy_id = f"authz-policy-{suffix}"
    starting_event_count = len(app.state.audit_logger.events)

    requests = [
        (
            "/v1/admin/authz/principals",
            {
                "issuer": DEFAULT_JWT_ISSUER,
                "subject": subject,
                "user_id": f"authz-user-{suffix}",
                "display_name": "Authz User",
                "approval_reference": "approval:authz-principal",
                "reason": "register authz principal",
            },
            "tenant_principal",
        ),
        (
            "/v1/admin/authz/memberships",
            {
                "issuer": DEFAULT_JWT_ISSUER,
                "subject": subject,
                "approval_reference": "approval:authz-membership",
                "reason": "activate tenant membership",
            },
            "tenant_principal_membership",
        ),
        (
            "/v1/admin/authz/roles",
            {
                "role_id": role_id,
                "display_name": "Authz Role",
                "approval_reference": "approval:authz-role",
                "reason": "create role",
            },
            "tenant_role",
        ),
        (
            "/v1/admin/authz/groups",
            {
                "group_id": group_id,
                "display_name": "Authz Group",
                "approval_reference": "approval:authz-group",
                "reason": "create group",
            },
            "tenant_group",
        ),
        (
            "/v1/admin/authz/role-assignments",
            {
                "issuer": DEFAULT_JWT_ISSUER,
                "subject": subject,
                "role_id": role_id,
                "approval_reference": "approval:authz-role-assignment",
                "reason": "assign role",
            },
            "tenant_principal_role_assignment",
        ),
        (
            "/v1/admin/authz/group-memberships",
            {
                "issuer": DEFAULT_JWT_ISSUER,
                "subject": subject,
                "group_id": group_id,
                "approval_reference": "approval:authz-group-membership",
                "reason": "assign group",
            },
            "tenant_principal_group_membership",
        ),
        (
            "/v1/admin/authz/object-acl-entries",
            {
                "object_id": object_id,
                "object_type": "document",
                "acl_subject_type": "group",
                "acl_subject_id": group_id,
                "permission": "read",
                "acl_version": 1,
                "approval_reference": "approval:authz-acl",
                "reason": "grant read access",
            },
            "object_acl_entry",
        ),
        (
            "/v1/admin/authz/abac-policy-bindings",
            {
                "policy_id": policy_id,
                "effect": "allow",
                "principal_selector": {"roles": [role_id]},
                "resource_selector": {"object_type": "document"},
                "condition": {"classification": {"not_in": ["confidential"]}},
                "priority": 10,
                "approval_reference": "approval:authz-abac",
                "reason": "bind ABAC policy",
            },
            "abac_policy_binding",
        ),
    ]

    for path, payload, resource_type in requests:
        response = client.post(path, headers=DEMO_SECURITY_ADMIN_HEADERS, json=payload)
        assert response.status_code == 200
        body = response.json()
        assert body["tenant_id"] == "tenant-demo"
        assert body["resource_type"] == resource_type
        assert body["audit_chain_ref"].startswith("audit:")

    purge_response = client.post(
        "/v1/admin/authz/jwt-replay-retention/purge",
        headers=DEMO_SECURITY_ADMIN_HEADERS,
        json={
            "expires_before_epoch": 2_000,
            "approval_reference": "approval:authz-jwt-retention",
            "reason": "purge expired replay tokens",
        },
    )
    assert purge_response.status_code == 200
    purge_body = purge_response.json()
    assert purge_body["tenant_id"] == "tenant-demo"
    assert purge_body["audit_chain_ref"].startswith("audit:")

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert [event.event_type for event in new_events[-9:]] == [
        "authz.principal.upsert",
        "authz.membership.upsert",
        "authz.role.upsert",
        "authz.group.upsert",
        "authz.role_assignment.upsert",
        "authz.group_membership.upsert",
        "authz.object_acl.upsert",
        "authz.abac_policy_binding.upsert",
        "authz.jwt_replay_retention.purge",
    ]
    assert all(event.input_hash is not None and event.output_hash is None for event in new_events[-9:])
    assert all("reason" not in event.metadata for event in new_events[-9:])


def test_admin_tenant_policy_rejects_unknown_allowed_model() -> None:
    response = client.patch(
        "/v1/admin/tenant-policy/ai-settings",
        headers=DEMO_ADMIN_HEADERS,
        json={"allowed_model_ids": ["unknown-model"]},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown model: unknown-model"


def test_admin_can_update_tenant_ai_settings() -> None:
    response = client.patch(
        "/v1/admin/tenant-policy/ai-settings",
        headers=DEMO_ADMIN_HEADERS,
        json={
            "ai_enabled": True,
            "rag_enabled": True,
            "voice_enabled": True,
            "external_ai_enabled": False,
            "content_preview_enabled": True,
            "allowed_model_ids": ["mock-summarizer"],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["tenant_id"] == "tenant-demo"
    assert body["ai_enabled"] is True
    assert body["rag_enabled"] is True
    assert body["voice_enabled"] is True
    assert body["external_ai_enabled"] is False
    assert body["content_preview_enabled"] is True
    assert set(body["allowed_model_ids"]) == {"mock-summarizer"}

    matching_audit_events = [
        event for event in app.state.audit_logger.events if event.event_type == "tenant_policy.ai_settings.update"
    ]
    assert matching_audit_events
    assert matching_audit_events[-1].metadata["allowed_model_count"] == 1
    assert matching_audit_events[-1].metadata["content_preview_enabled"] is True


def test_security_admin_can_register_approve_and_retire_embedding_model_version() -> None:
    model_id = f"api-embedding-{uuid4().hex}"
    registration_response = client.post(
        "/v1/admin/embedding-models",
        headers=DEMO_SECURITY_ADMIN_HEADERS,
        json={
            "embedding_model_id": model_id,
            "embedding_model_version": "2026-06-11",
            "provider": "local",
            "deployment": "deterministic-hash",
            "dimensions": 3,
            "distance_metric": "cosine",
            "checksum": "sha256:api-embedding-model",
            "approved_for_data_classes": ["internal", "personal"],
            "change_reference": "change:api-embedding-model",
        },
    )
    assert registration_response.status_code == 200
    registered = registration_response.json()
    assert registered["embedding_model_id"] == model_id
    assert registered["approved_at_utc"] is None

    approval_response = client.post(
        f"/v1/admin/embedding-models/{model_id}/versions/2026-06-11/approve",
        headers=DEMO_SECURITY_ADMIN_HEADERS,
        json={"approval_reference": "approval:api-embedding-model"},
    )
    assert approval_response.status_code == 200
    approved = approval_response.json()
    assert approved["approved_at_utc"] is not None

    retirement_response = client.post(
        f"/v1/admin/embedding-models/{model_id}/versions/2026-06-11/retire",
        headers=DEMO_SECURITY_ADMIN_HEADERS,
        json={
            "retirement_reference": "approval:api-embedding-model-retire",
            "reason": "superseded",
        },
    )
    assert retirement_response.status_code == 200
    retired = retirement_response.json()
    assert retired["retired_at_utc"] is not None

    matching_audit_events = [
        event for event in app.state.audit_logger.events if event.metadata.get("embedding_model_id") == model_id
    ]
    assert [event.event_type for event in matching_audit_events[-3:]] == [
        "embedding_model_version.registered",
        "embedding_model_version.approved",
        "embedding_model_version.retired",
    ]
    assert all(event.input_hash is None and event.output_hash is None for event in matching_audit_events[-3:])


def test_inference_writes_untrusted_output() -> None:
    response = client.post(
        "/v1/ai/inference",
        headers=DEMO_HEADERS,
        json={"input_text": "Bitte zusammenfassen.", "source_object_ids": ["doc-1"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["output_trust"] == "untrusted"
    assert body["model_id"] == "mock-summarizer"
    assert body["audit_event_id"]


def test_rag_filters_unauthorized_sources_before_context() -> None:
    response = client.post(
        "/v1/rag/query",
        headers=DEMO_HEADERS,
        json={"question": "Was ist die Policy?", "top_k": 2},
    )
    assert response.status_code == 200
    body = response.json()
    assert [source["object_id"] for source in body["sources"]] == ["doc-1"]
    assert all(source["access_checked"] for source in body["sources"])
    assert "secret-1" not in body["answer"]


def test_keyword_search_returns_candidate_only_authorized_results_and_audit() -> None:
    starting_event_count = len(app.state.audit_logger.events)

    response = client.post(
        "/v1/search/keyword",
        headers=DEMO_HEADERS,
        json={"query": "policy citations", "top_k": 5},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["search_policy_id"] == "keyword_candidate_acl_v1"
    assert body["audit_event_id"]
    assert [candidate["object_id"] for candidate in body["candidates"]] == ["doc-1"]
    assert body["candidates"][0]["access_checked"] is True
    assert "text" not in body["candidates"][0]
    assert "snippet" not in body["candidates"][0]
    assert "AI suggestions must remain drafts" not in response.text
    assert "This confidential source" not in response.text

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert new_events[-1].event_type == "search.keyword.query"
    assert new_events[-1].event_id == body["audit_event_id"]
    assert new_events[-1].input_hash is not None
    assert new_events[-1].output_hash is None
    assert new_events[-1].source_object_ids == ["doc-1"]
    assert new_events[-1].metadata["authorized_candidate_count"] == 1
    assert "query" not in new_events[-1].metadata


def test_voice_requires_push_to_talk() -> None:
    response = client.post(
        "/v1/voice/transcripts",
        headers=DEMO_HEADERS,
        json={"transcript": "Fasse diese Mail zusammen.", "push_to_talk_active": False},
    )
    assert response.status_code == 403
