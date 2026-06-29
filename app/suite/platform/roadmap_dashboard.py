from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.models import UserContext

ROADMAP_DASHBOARD_SCHEMA_VERSION = "platform_roadmap_dashboard.v1"


class RoadmapCapabilityStatus(StrEnum):
    OPERATIONAL = "operational"
    METADATA_ONLY = "metadata_only"
    GUARDED = "guarded"
    PLANNED = "planned"
    DEFERRED = "deferred"


class RoadmapCapability(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability_id: str
    title: str
    summary: str
    status: RoadmapCapabilityStatus
    capability_type: str
    evidence_refs: tuple[str, ...]
    api_routes: tuple[str, ...] = ()
    guardrails: tuple[str, ...] = ()
    next_action: str | None = None

    @field_validator("capability_id", "title", "summary", "capability_type")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("roadmap capability text fields must not be empty")
        return value

    @field_validator("evidence_refs", "guardrails", "api_routes")
    @classmethod
    def require_non_empty_items(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for item in value:
            if not item.strip():
                raise ValueError("roadmap capability list items must not be empty")
        return value

    @model_validator(mode="after")
    def require_evidence_for_ready_capabilities(self) -> RoadmapCapability:
        if (
            self.status
            in {
                RoadmapCapabilityStatus.OPERATIONAL,
                RoadmapCapabilityStatus.METADATA_ONLY,
                RoadmapCapabilityStatus.GUARDED,
            }
            and not self.evidence_refs
        ):
            raise ValueError("ready roadmap capabilities require evidence references")
        return self


class RoadmapCapabilityGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    group_id: str
    title: str
    summary: str
    capabilities: tuple[RoadmapCapability, ...]

    @field_validator("group_id", "title", "summary")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("roadmap group text fields must not be empty")
        return value

    @model_validator(mode="after")
    def require_capabilities(self) -> RoadmapCapabilityGroup:
        if not self.capabilities:
            raise ValueError("roadmap groups require at least one capability")
        return self


class RoadmapDashboardSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operational_count: int
    metadata_only_count: int
    guarded_count: int
    planned_count: int
    deferred_count: int
    foundation_ready_count: int
    total_count: int


class RoadmapDashboardResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = ROADMAP_DASHBOARD_SCHEMA_VERSION
    tenant_id: str
    title: str = "Collabio Foundation Roadmap"
    current_focus: str
    current_foundation_state: str
    summary: RoadmapDashboardSummary
    groups: tuple[RoadmapCapabilityGroup, ...]
    immediate_next_steps: tuple[str, ...]
    deferred_scope: tuple[str, ...]
    evidence_contracts: tuple[str, ...]
    content_included: bool = False
    persistent_task_created: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False

    @field_validator("tenant_id", "current_focus", "current_foundation_state")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("roadmap dashboard text fields must not be empty")
        return value

    @model_validator(mode="after")
    def require_metadata_only_dashboard(self) -> RoadmapDashboardResponse:
        if self.schema_version != ROADMAP_DASHBOARD_SCHEMA_VERSION:
            raise ValueError("roadmap dashboard schema version is invalid")
        if (
            self.content_included
            or self.persistent_task_created
            or self.destructive_actions_allowed
            or self.external_side_effect_allowed
        ):
            raise ValueError("roadmap dashboard must remain metadata-only and non-executing")
        return self


def build_roadmap_dashboard_response(*, user_context: UserContext) -> RoadmapDashboardResponse:
    groups = _roadmap_groups()
    summary = _roadmap_summary(groups)
    return RoadmapDashboardResponse(
        tenant_id=user_context.tenant_id,
        current_focus="crm_erp_vertical_slice_after_foundation",
        current_foundation_state="metadata_only_foundation_operational_with_crm_erp_slice_complete",
        summary=summary,
        groups=groups,
        immediate_next_steps=(
            "crm_accounts_contacts_activities_operational_hardening",
            "crm_erp_slice_complete_next_governed_rag_readiness",
            "crm_erp_search_acl_first_then_rag",
            "module_family_backlog_kb_lms_tickets_time_tracking",
        ),
        deferred_scope=(
            "full_office_suite_client",
            "mail_client_runtime",
            "productive_legacy_sql_import_writes",
            "full_content_preview_rendering",
            "automation_execution_for_tasks_tickets_lms_time_tracking",
        ),
        evidence_contracts=(
            "tenant_context_required",
            "audit_logged_metadata_only",
            "human_confirmation_before_destructive_or_external_actions",
            "no_raw_content_in_dashboard",
            "no_import_write_execution",
            "backup_failover_policy_must_follow_new_state",
        ),
    )


def _roadmap_summary(groups: tuple[RoadmapCapabilityGroup, ...]) -> RoadmapDashboardSummary:
    capabilities = tuple(capability for group in groups for capability in group.capabilities)
    operational = _status_count(capabilities, RoadmapCapabilityStatus.OPERATIONAL)
    metadata_only = _status_count(capabilities, RoadmapCapabilityStatus.METADATA_ONLY)
    guarded = _status_count(capabilities, RoadmapCapabilityStatus.GUARDED)
    planned = _status_count(capabilities, RoadmapCapabilityStatus.PLANNED)
    deferred = _status_count(capabilities, RoadmapCapabilityStatus.DEFERRED)
    return RoadmapDashboardSummary(
        operational_count=operational,
        metadata_only_count=metadata_only,
        guarded_count=guarded,
        planned_count=planned,
        deferred_count=deferred,
        foundation_ready_count=operational + metadata_only + guarded,
        total_count=len(capabilities),
    )


def _status_count(
    capabilities: tuple[RoadmapCapability, ...],
    status: RoadmapCapabilityStatus,
) -> int:
    return sum(1 for capability in capabilities if capability.status == status)


def _roadmap_groups() -> tuple[RoadmapCapabilityGroup, ...]:
    return (
        RoadmapCapabilityGroup(
            group_id="security_governance",
            title="Security, Tenancy und Governance",
            summary="Die Plattform hat Tenant-Kontext, Rechteverwaltung, Audit, AI-Policy und Backup-Leitplanken.",
            capabilities=(
                RoadmapCapability(
                    capability_id="tenant_authz",
                    title="Tenant-Kontext und Rechteverwaltung",
                    summary=("Dev-Header/JWT, Principal Store, Rollen, Gruppen und ACLs sind vorhanden."),
                    status=RoadmapCapabilityStatus.OPERATIONAL,
                    capability_type="platform_control",
                    evidence_refs=(
                        "tests/test_auth_context.py",
                        "tests/test_authz_admin_store.py",
                        "docs/AUTH_CONTEXT.md",
                    ),
                    api_routes=("/v1/admin/authz/*", "/v1/platform/modules"),
                    guardrails=("tenant_context_required", "principal_membership_required", "jwt_replay_guard"),
                ),
                RoadmapCapability(
                    capability_id="audit_chain",
                    title="Audit Chain und persistente Audit Stores",
                    summary="Audit-Events, Hash-Kette und Postgres-Writer sind in kritischen Flows angebunden.",
                    status=RoadmapCapabilityStatus.OPERATIONAL,
                    capability_type="compliance_control",
                    evidence_refs=(
                        "tests/test_audit_chain.py",
                        "tests/test_pg_audit_store.py",
                        "docs/AI_AUDIT_SCHEMA.md",
                    ),
                    guardrails=("hash_chained_events", "no_prompt_body_in_normal_logs", "metadata_only_dashboard"),
                ),
                RoadmapCapability(
                    capability_id="ai_control_plane",
                    title="AI Control Plane und Local LLM Gateway",
                    summary="Model-, Prompt- und Tool-Policies liegen hinter Tenant-Policy und Local Gateway.",
                    status=RoadmapCapabilityStatus.GUARDED,
                    capability_type="ai_boundary",
                    evidence_refs=("tests/test_ai_control_plane.py", "docs/AI_GOVERNANCE.md", "docs/MODEL_REGISTRY.md"),
                    api_routes=("/v1/ai/inference",),
                    guardrails=("tenant_policy_required", "tool_permission_registry", "audit_log_prompt_hashes"),
                ),
                RoadmapCapability(
                    capability_id="backup_failover",
                    title="Backup- und Failover-Kultur",
                    summary="Continuity Domains, Restore-Drills und Change-Control sind getestet.",
                    status=RoadmapCapabilityStatus.GUARDED,
                    capability_type="operations_control",
                    evidence_refs=("tests/test_backup_failover.py", "docs/operations/BACKUP_FAILOVER.md"),
                    guardrails=(
                        "continuity_domain_required",
                        "restore_drill_required",
                        "future_modules_must_extend_policy",
                    ),
                ),
            ),
        ),
        RoadmapCapabilityGroup(
            group_id="data_content_foundation",
            title="Daten, Storage und Content-Sicherheit",
            summary="SourceObjects, Retention, Legal Hold, KMS, Storage und RAG-Sicherheit sind vorbereitet.",
            capabilities=(
                RoadmapCapability(
                    capability_id="source_objects",
                    title="SourceObject Metadata Pipeline",
                    summary=("Workspace-Quellen werden ACL-geprueft als Metadaten sichtbar."),
                    status=RoadmapCapabilityStatus.METADATA_ONLY,
                    capability_type="data_foundation",
                    evidence_refs=(
                        "tests/test_source_objects.py",
                        "tests/test_source_object_storage_bridge.py",
                        "docs/SOURCE_OBJECT_MODEL.md",
                    ),
                    api_routes=("/v1/source-objects/{object_id}/versions/{version_id}/metadata",),
                    guardrails=("acl_checked", "content_included_false", "classification_retention_legal_hold_visible"),
                ),
                RoadmapCapability(
                    capability_id="storage_kms_retention",
                    title="Storage, KMS, Retention und Legal Hold",
                    summary="Content Hashing, Envelope Encryption, S3 Stores, Retention und Legal Hold stehen.",
                    status=RoadmapCapabilityStatus.GUARDED,
                    capability_type="data_protection",
                    evidence_refs=(
                        "tests/test_envelope_encryption.py",
                        "tests/test_retention_manifest.py",
                        "tests/test_legal_hold_service.py",
                    ),
                    guardrails=(
                        "content_hash_required",
                        "kms_key_refs",
                        "retention_policy_required",
                        "legal_hold_state_visible",
                    ),
                ),
                RoadmapCapability(
                    capability_id="rag_vector_security",
                    title="RAG und Vector Security",
                    summary=("Vector-Metadaten, ACL-Revalidierung und Source-Zitationen sind vorbereitet."),
                    status=RoadmapCapabilityStatus.GUARDED,
                    capability_type="rag_security",
                    evidence_refs=(
                        "tests/test_rag_security.py",
                        "tests/test_pgvector_migration.py",
                        "docs/RAG_SECURITY_MODEL.md",
                    ),
                    guardrails=(
                        "authoritative_acl_validation",
                        "source_object_ids_required",
                        "embeddings_not_anonymous",
                    ),
                ),
                RoadmapCapability(
                    capability_id="preview_renderer",
                    title="Preview Renderer Sandbox und Decision Ledger",
                    summary="Preview-Evidence und Decisions laufen metadata-only; Content-Rendering bleibt blockiert.",
                    status=RoadmapCapabilityStatus.METADATA_ONLY,
                    capability_type="content_boundary",
                    evidence_refs=(
                        "tests/test_source_object_preview_renderer_release_gate.py",
                        "tests/test_source_object_preview_decision_ledger.py",
                    ),
                    api_routes=(
                        "/v1/source-objects/{object_id}/versions/{version_id}/preview-renderer-runs",
                        "/v1/source-objects/{object_id}/versions/{version_id}/preview-decisions",
                    ),
                    guardrails=(
                        "metadata_only_no_source_content",
                        "human_confirmation_reference",
                        "content_release_allowed_false",
                    ),
                ),
            ),
        ),
        RoadmapCapabilityGroup(
            group_id="workspace_modules",
            title="Workspace, Module und erste Fachslices",
            summary=(
                "Modul-Discovery, Workspace Cockpit, KB, CRM, ERP und ACL-first Suche sind tenant-sicher angebunden."
            ),
            capabilities=(
                RoadmapCapability(
                    capability_id="module_registry",
                    title="Platform Module Registry",
                    summary="Module koennen pro Tenant entdeckt, provisioniert, aktiviert und deaktiviert werden.",
                    status=RoadmapCapabilityStatus.OPERATIONAL,
                    capability_type="module_system",
                    evidence_refs=(
                        "tests/test_platform_modules.py",
                        "tests/test_module_registry_operations.py",
                        "docs/operations/MODULE_REGISTRY_OPERATIONS.md",
                    ),
                    api_routes=(
                        "/v1/platform/modules",
                        "/v1/admin/tenant-modules/{module_id}/provision",
                        "/v1/admin/tenant-modules/{module_id}/enable",
                    ),
                    guardrails=(
                        "tenant_scoped_module_status",
                        "compliance_gate_surface",
                        "admin_role_required_for_mutation",
                    ),
                ),
                RoadmapCapability(
                    capability_id="workspace_cockpit",
                    title="Workspace Cockpit und MVP Snapshot",
                    summary=("Online Cockpit mit Modulstatus, Arbeitskorb und Snapshot-Export ist vorhanden."),
                    status=RoadmapCapabilityStatus.OPERATIONAL,
                    capability_type="operator_ui",
                    evidence_refs=(
                        "tests/test_api.py::test_workspace_shell_serves_static_module_cockpit_ui",
                        "app/suite/ui/workspace/index.html",
                    ),
                    api_routes=("/workspace", "/v1/platform/cockpit", "/v1/platform/cockpit/mvp-snapshot"),
                    guardrails=("metadata_only_ui", "explicit_confirmation_for_actions", "no_content_rendering"),
                ),
                RoadmapCapability(
                    capability_id="knowledge_base",
                    title="Knowledge Base Foundation",
                    summary="Artikel-Read-Slice, Write-Approval, Unit-of-Work und Runtime Activation sind vorbereitet.",
                    status=RoadmapCapabilityStatus.METADATA_ONLY,
                    capability_type="module_foundation",
                    evidence_refs=(
                        "tests/test_knowledge_base.py",
                        "tests/test_knowledge_base_write_unit_of_work.py",
                        "docs/modules/KNOWLEDGE_BASE_ARTICLES_VERTICAL_SLICE.md",
                    ),
                    api_routes=("/v1/kb/articles", "/v1/kb/write-approvals/*"),
                    guardrails=(
                        "write_approval_required",
                        "source_restore_evidence_required",
                        "runtime_activation_audited",
                    ),
                ),
                RoadmapCapability(
                    capability_id="crm_erp_first_slices",
                    title="CRM/ERP erste Vertical Slices",
                    summary=(
                        "CRM Accounts, Activities sowie ERP Products, Suppliers, Orders, Order Items, Invoices "
                        "und Invoice Items sind tenant-sicher."
                    ),
                    status=RoadmapCapabilityStatus.METADATA_ONLY,
                    capability_type="business_module_slice",
                    evidence_refs=(
                        "tests/test_crm_accounts.py",
                        "tests/test_crm_contacts.py",
                        "tests/test_crm_activities.py",
                        "tests/test_erp_products.py",
                        "tests/test_erp_sales.py",
                    ),
                    api_routes=(
                        "/v1/crm/accounts",
                        "/v1/crm/contacts",
                        "/v1/crm/activities",
                        "/v1/erp/products",
                        "/v1/erp/suppliers",
                        "/v1/erp/orders",
                        "/v1/erp/order-items",
                        "/v1/erp/invoices",
                        "/v1/erp/invoice-items",
                    ),
                    guardrails=("module_gate_required", "tenant_context_required", "no_ai_bypass"),
                    next_action="crm_erp_search_acl_first_search_ui_and_rag_guardrails",
                ),
                RoadmapCapability(
                    capability_id="crm_erp_acl_first_search",
                    title="CRM/ERP ACL-first Suche",
                    summary="Keyword-Suche ueber CRM/ERP-Metadaten ist tenant- und ACL-geprueft, ohne AI/RAG-Kontext.",
                    status=RoadmapCapabilityStatus.METADATA_ONLY,
                    capability_type="business_search_slice",
                    evidence_refs=(
                        "tests/test_crm_erp_search.py",
                        "tests/test_api.py::test_crm_erp_search_endpoint_returns_acl_checked_metadata_candidates_after_feature_enable",
                        "app/suite/platform/crm_erp_search.py",
                        "app/suite/platform/crm_erp_search_readiness.py",
                    ),
                    api_routes=(
                        "/v1/crm-erp/search",
                        "/v1/platform/search/crm-erp/readiness",
                        "/v1/platform/search/crm-erp/rag-readiness",
                    ),
                    guardrails=(
                        "module_gate_required",
                        "readiness_endpoint_metadata_only",
                        "authoritative_acl_validation",
                        "candidate_only_metadata_only",
                        "no_ai_or_rag_context",
                        "rag_readiness_explicitly_blocked_until_source_citation_and_audit_gates",
                    ),
                    next_action="implement_source_resolver_acl_trace_before_any_crm_erp_rag_context",
                ),
            ),
        ),
        RoadmapCapabilityGroup(
            group_id="legacy_sql_migration",
            title="Legacy SQL Migration Foundation",
            summary="Der Legacy-SQL-Pfad ist metadata-only bis zur Run/Report Registry geschlossen.",
            capabilities=(
                RoadmapCapability(
                    capability_id="legacy_discovery",
                    title="Discovery, Intake und Evidence Ledger",
                    summary="Legacy SQL Discovery, Intake, Host Profiles und Evidence Ledger laufen ohne Rohdaten.",
                    status=RoadmapCapabilityStatus.METADATA_ONLY,
                    capability_type="migration_foundation",
                    evidence_refs=(
                        "tests/test_legacy_sql_discovery.py",
                        "tests/test_legacy_sql_evidence_ledger.py",
                        "docs/LEGACY_SQL_DISCOVERY.md",
                    ),
                    guardrails=(
                        "approved_host_profile_required",
                        "no_connection_secret_in_metadata",
                        "evidence_hashes_required",
                    ),
                ),
                RoadmapCapability(
                    capability_id="legacy_connector_readiness",
                    title="Connector Readiness Gates",
                    summary="Sandbox, Provider Attestation, Connection Preflight und Runtime Gates sind vorbereitet.",
                    status=RoadmapCapabilityStatus.GUARDED,
                    capability_type="connector_boundary",
                    evidence_refs=(
                        "tests/test_legacy_sql_connector_runtime_activation_gate.py",
                        "tests/test_legacy_sql_connector_connection_preflight_gate.py",
                    ),
                    guardrails=("sandbox_profile_required", "timeout_circuit_breaker", "runtime_activation_gate"),
                ),
                RoadmapCapability(
                    capability_id="legacy_dry_run_approval",
                    title="Dry-Run und Import-Write Approval Gates",
                    summary="Staging-Profile, Dry-Run Results und Approval Records bleiben metadata-only speicherbar.",
                    status=RoadmapCapabilityStatus.METADATA_ONLY,
                    capability_type="migration_control",
                    evidence_refs=(
                        "tests/test_legacy_sql_import_dry_run_worker.py",
                        "tests/test_legacy_sql_import_write_approval_gate.py",
                    ),
                    api_routes=("/v1/admin/crm-erp/legacy-sql/import-write-approval-requests/boundary",),
                    guardrails=(
                        "dry_run_before_write",
                        "human_approval_before_import_write",
                        "import_write_execution_false",
                    ),
                ),
                RoadmapCapability(
                    capability_id="legacy_migration_registry",
                    title="Migration Run und Report Metadata Stores",
                    summary="Migration Runs und Reports koennen idempotent gespeichert und gelesen werden.",
                    status=RoadmapCapabilityStatus.METADATA_ONLY,
                    capability_type="migration_registry",
                    evidence_refs=("tests/test_legacy_sql_migration_run_registry.py", "docs/LEGACY_SQL_DISCOVERY.md"),
                    api_routes=(
                        "/v1/admin/crm-erp/legacy-sql/migration-runs",
                        "/v1/admin/crm-erp/legacy-sql/migration-reports",
                    ),
                    guardrails=("tenant_admin_required", "report_retrieval_false", "import_write_execution_false"),
                    next_action="crm_erp_vertical_slice_not_more_migration_depth",
                ),
            ),
        ),
        RoadmapCapabilityGroup(
            group_id="deferred_product_surfaces",
            title="Bewusst spaeter",
            summary="Diese Bereiche sind Suite-Scope, aber nicht Fundament-blockierend.",
            capabilities=(
                RoadmapCapability(
                    capability_id="office_mail_clients",
                    title="Office Suite und Mail Client",
                    summary="Architektur ist eingeplant; vollwertige Clients werden spaeter angedockt.",
                    status=RoadmapCapabilityStatus.DEFERRED,
                    capability_type="product_surface",
                    evidence_refs=("docs/OFFICE_MAIL_CORE.md",),
                    guardrails=(
                        "tenant_isolation_required",
                        "retention_and_legal_hold_required",
                        "no_always_on_capture",
                    ),
                    next_action="dock_after_core_crm_erp_and_content_release_policy",
                ),
                RoadmapCapability(
                    capability_id="future_modules",
                    title="LMS, Tickets, Zeiterfassung und weitere Module",
                    summary="Modulfamilien folgen nach stabilen Modul-, Rechte- und Datenvertraegen.",
                    status=RoadmapCapabilityStatus.PLANNED,
                    capability_type="module_backlog",
                    evidence_refs=("docs/ROADMAP.md",),
                    guardrails=("module_contract_first", "backup_failover_update_required", "tenant_admin_lifecycle"),
                    next_action="prioritize_after_crm_erp_vertical_slice",
                ),
                RoadmapCapability(
                    capability_id="productive_import_writes",
                    title="Produktive Legacy Import-Writes",
                    summary="Absichtlich nicht freigeschaltet; erst nach Review, Mapping, Restore und Approval.",
                    status=RoadmapCapabilityStatus.DEFERRED,
                    capability_type="destructive_boundary",
                    evidence_refs=("docs/LEGACY_SQL_DISCOVERY.md",),
                    guardrails=(
                        "explicit_human_confirmation_required",
                        "restore_evidence_required",
                        "write_execution_gate_required",
                    ),
                    next_action="remain_blocked_until_business_mapping_ready",
                ),
            ),
        ),
    )
