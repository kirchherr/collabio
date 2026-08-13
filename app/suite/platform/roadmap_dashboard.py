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
        current_focus="real_user_productivity_pilot_evidence_collection",
        current_foundation_state="production_continuity_evidence_read_model_ready_without_live_evidence",
        summary=summary,
        groups=groups,
        immediate_next_steps=(
            "collect_real_user_productivity_pilot_nomination",
            "refresh_real_user_productivity_pilot_control_evidence",
            "review_production_continuity_requirements_and_gate_status",
            "collect_current_production_continuity_topology_and_drill_evidence",
            "keep_runtime_closed_until_named_principals_and_four_eyes_approvals_are_complete",
        ),
        deferred_scope=(
            "full_office_suite_client",
            "mail_client_runtime",
            "productive_legacy_sql_import_writes",
            "erp_products_to_orders_invoices_slice",
            "crm_erp_search_acl_first_then_rag",
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
                    summary=(
                        "PostgreSQL und Object Storage sind auf unabhaengige Ziele restauriert und im "
                        "Backend-Completion-Gate gemeinsam abgenommen. Ein kontrollierter nicht-leerer runsc-Proof "
                        "mit getrennter Pixel-CDR-Grenze wurde ueber frisches Backup, isolierten Restore und "
                        "Derived-Preview-Reconciliation geschlossen; RGB-Scratch bleibt ausgeschlossen und "
                        "produktiver Dispatch separat gesperrt."
                    ),
                    status=RoadmapCapabilityStatus.GUARDED,
                    capability_type="operations_control",
                    evidence_refs=(
                        "tests/test_backup_failover.py",
                        "tests/test_exact_version_restore_drill.py",
                        "app/suite/storage/backend_storage_foundation_gate.py",
                        "app/suite/operations/postgres_restore_drill.py",
                        "app/suite/operations/backend_foundation_completion_gate.py",
                        "app/suite/operations/derived_preview_recovery_drill.py",
                        "tests/test_preview_conversion_non_empty_proof.py",
                        "tests/test_postgres_restore_drill.py",
                        "docs/operations/BACKUP_FAILOVER.md",
                        "docs/operations/PREVIEW_CDR.md",
                    ),
                    guardrails=(
                        "continuity_domain_required",
                        "independent_exact_version_restore_required",
                        "isolated_postgres_restore_required",
                        "backend_foundation_completion_gate_required",
                        "non_empty_derived_preview_recovery_verified_on_development_host",
                        "transient_cdr_bundles_excluded_from_backup",
                        "future_modules_must_extend_policy",
                    ),
                ),
                RoadmapCapability(
                    capability_id="production_continuity_deployment_gate",
                    title="Production Continuity Deployment Gate",
                    summary=(
                        "PITR/WAL, verschluesselte Offsite-Backups, HA-Promotion und standortgetrennter "
                        "PostgreSQL-/Object-Storage-/KMS-Failover besitzen einen gemeinsamen fail-closed "
                        "Deployment-Vertrag, einen Security-Admin-Read-Pfad fuer Anforderungen und Status sowie eine "
                        "private-key-freie Offline-Signaturzeremonie. Reale Produktionsevidenz steht noch aus."
                    ),
                    status=RoadmapCapabilityStatus.GUARDED,
                    capability_type="operations_deployment_control",
                    evidence_refs=(
                        "app/suite/operations/production_continuity_deployment_gate.py",
                        "app/suite/operations/production_continuity_attestation.py",
                        "app/suite/operations/production_continuity_attestation_ceremony.py",
                        "tests/test_production_continuity_attestation_ceremony.py",
                        "docs/operations/PRODUCTION_CONTINUITY_SIGNING_CEREMONY.md",
                        "app/suite/platform/production_continuity_read_model.py",
                        "tests/test_production_continuity_deployment_gate.py",
                        "tests/test_production_continuity_read_model.py",
                        "docs/operations/PRODUCTION_CONTINUITY_DEPLOYMENT_GATE.md",
                        "docs/operations/PRODUCTION_CONTINUITY_EVIDENCE_READ_MODEL.md",
                        "docs/operations/backup_failover_policy.json",
                        "docs/operations/BACKUP_FAILOVER.md",
                    ),
                    api_routes=(
                        "/v1/platform/production-continuity/evidence-requirements",
                        "/v1/platform/production-continuity/gate-status",
                    ),
                    guardrails=(
                        "fresh_hash_only_operator_evidence_required",
                        "postgres_complete_wal_chain_and_isolated_pitr_required",
                        "encrypted_immutable_offsite_restore_required",
                        "ha_fencing_split_brain_prevention_and_manual_promotion_drill_required",
                        "cross_site_postgres_object_storage_and_kms_recovery_required",
                        "object_lock_retention_legal_hold_and_tenant_isolation_required",
                        "automatic_failover_requires_separate_drill",
                        "three_external_role_signatures_required",
                        "offline_ceremony_has_no_private_key_or_provider_credential_path",
                        "runtime_switch_fails_closed_without_ready_gate_report",
                        "security_admin_metadata_only_requirements_and_status",
                        "no_evidence_upload_or_report_mutation_api",
                        "no_deployment_promotion_traffic_switch_or_business_write",
                    ),
                    next_action="collect_current_production_topology_and_drill_evidence",
                ),
                RoadmapCapability(
                    capability_id="business_backend_release_gate",
                    title="Business Backend Release Gate",
                    summary=(
                        "CRM-Onboarding, Tasks und Zeiterfassung sind als gemeinsames Backend-Paket durch "
                        "Restore, Modulkatalog, PostgreSQL-Konfiguration und Live-OpenAPI-Vertrag abgenommen."
                    ),
                    status=RoadmapCapabilityStatus.OPERATIONAL,
                    capability_type="operations_release_control",
                    evidence_refs=(
                        "app/suite/operations/business_backend_release_gate.py",
                        "tests/test_business_backend_release_gate.py",
                        "docs/operations/BUSINESS_BACKEND_RELEASE_GATE.md",
                        "docs/operations/BACKUP_FAILOVER.md",
                    ),
                    guardrails=(
                        "backend_foundation_gate_hash_required",
                        "live_api_health_and_openapi_contract_required",
                        "installed_module_and_migration_catalog_required",
                        "postgres_business_backends_required",
                        "metadata_only_release_evidence",
                        "no_tenant_activation_or_business_write",
                    ),
                    next_action="real_user_productivity_pilot_admission",
                ),
                RoadmapCapability(
                    capability_id="productivity_pilot_preflight",
                    title="Productivity Pilot Preflight",
                    summary=(
                        "Ausgewaehlte Tenants, drei produktive Slices, sichere Feature-Grenzen sowie Monitoring- und "
                        "Rollback-Vertraege werden hashgebunden geprueft, ohne den Pilot zu starten."
                    ),
                    status=RoadmapCapabilityStatus.OPERATIONAL,
                    capability_type="operations_pilot_control",
                    evidence_refs=(
                        "app/suite/operations/productivity_pilot_preflight.py",
                        "tests/test_productivity_pilot_preflight.py",
                        "docs/operations/productivity_pilot_policy.json",
                        "docs/operations/PRODUCTIVITY_PILOT_PREFLIGHT.md",
                    ),
                    guardrails=(
                        "explicit_candidate_tenant_selection",
                        "required_and_forbidden_feature_scope_verified",
                        "monitoring_and_non_destructive_rollback_contracts_required",
                        "human_admission_still_required",
                        "traffic_scope_enforcement_still_required",
                        "pilot_start_and_tenant_mutation_forbidden",
                    ),
                    next_action="real_user_productivity_pilot_admission",
                ),
                RoadmapCapability(
                    capability_id="productivity_pilot_admission",
                    title="Productivity Pilot Human Admission",
                    summary=(
                        "Tenant-Admins binden eine exakte Human-Admission append-only an den autoritativ "
                        "persistierten Preflight, ohne Aktivierung, Traffic-Freigabe oder Business-Write."
                    ),
                    status=RoadmapCapabilityStatus.OPERATIONAL,
                    capability_type="operations_pilot_control",
                    evidence_refs=(
                        "app/suite/platform/productivity_pilot_admission.py",
                        "app/suite/persistence/migrations/0061_productivity_pilot_admission.sql",
                        "tests/test_productivity_pilot_admission.py",
                        "docs/operations/PRODUCTIVITY_PILOT_ADMISSION.md",
                        "docs/operations/BACKUP_FAILOVER.md",
                    ),
                    guardrails=(
                        "tenant_admin_role_required",
                        "authoritative_tenant_scoped_preflight_required",
                        "exact_policy_release_and_module_state_hash_binding",
                        "append_only_rls_and_restore_controls_required",
                        "confirmation_body_never_persisted_or_logged",
                        "pilot_start_traffic_enforcement_activation_and_business_writes_forbidden",
                    ),
                    api_routes=("/v1/platform/productivity-pilot/admissions",),
                    next_action="real_user_productivity_pilot_admission",
                ),
                RoadmapCapability(
                    capability_id="productivity_pilot_traffic_scope_enforcement",
                    title="Productivity Pilot Traffic Scope",
                    summary=(
                        "Tenant- und Routenscope sind append-only an Admission, Preflight und Policy gebunden. "
                        "Default Deny blockiert den Pilot-Traffic bis zur separaten Start-Autorisierung."
                    ),
                    status=RoadmapCapabilityStatus.OPERATIONAL,
                    capability_type="operations_pilot_control",
                    evidence_refs=(
                        "app/suite/platform/productivity_pilot_traffic_scope.py",
                        "app/suite/persistence/migrations/0062_productivity_pilot_traffic_scope.sql",
                        "tests/test_productivity_pilot_traffic_scope.py",
                        "docs/operations/PRODUCTIVITY_PILOT_TRAFFIC_SCOPE.md",
                        "docs/operations/BACKUP_FAILOVER.md",
                    ),
                    guardrails=(
                        "tenant_admin_role_required",
                        "authoritative_admission_preflight_and_policy_hash_binding",
                        "exact_seven_operation_route_scope_required",
                        "append_only_rls_and_restore_controls_required",
                        "default_deny_before_start_authorization",
                        "pilot_start_activation_business_writes_and_external_actions_forbidden",
                    ),
                    api_routes=(
                        "/v1/platform/productivity-pilot/traffic-scope-enforcements",
                        "/v1/crm/*",
                        "/v1/tasks/*",
                        "/v1/time-tracking/*",
                    ),
                    next_action="real_user_productivity_pilot_admission",
                ),
                RoadmapCapability(
                    capability_id="productivity_pilot_start_authorization",
                    title="Productivity Pilot Start Authorization",
                    summary=(
                        "Security-Admins koennen genau sieben Pilot-Operationen zeitlich begrenzt oeffnen. "
                        "Vier-Augen-Prinzip, aktuelle Monitoring-/Rollback-Evidenz, automatische Ablaufzeit und "
                        "ein standardmaessig geschlossener Deployment-Kill-Switch werden bei jedem Request geprueft."
                    ),
                    status=RoadmapCapabilityStatus.OPERATIONAL,
                    capability_type="operations_pilot_control",
                    evidence_refs=(
                        "app/suite/platform/productivity_pilot_start_authorization.py",
                        "app/suite/persistence/migrations/0063_productivity_pilot_start_authorization.sql",
                        "tests/test_productivity_pilot_start_authorization.py",
                        "docs/operations/PRODUCTIVITY_PILOT_START_AUTHORIZATION.md",
                        "docs/operations/BACKUP_FAILOVER.md",
                    ),
                    guardrails=(
                        "security_admin_role_required",
                        "four_eyes_distinct_from_admission_and_traffic_enforcement",
                        "exact_monitoring_and_rollback_evidence_required_for_full_window",
                        "maximum_eight_hour_authorization",
                        "deployment_kill_switch_default_closed",
                        "automatic_expiry_checked_per_request",
                        "append_only_rls_and_restore_controls_required",
                        "no_tenant_module_business_destructive_or_external_mutation",
                    ),
                    api_routes=(
                        "/v1/platform/productivity-pilot/start-authorizations",
                        "POST /v1/crm/account-onboardings",
                        "POST /v1/tasks/items",
                        "GET /v1/tasks/items",
                        "GET /v1/tasks/activities",
                        "POST /v1/time-tracking/entries",
                        "GET /v1/time-tracking/entries",
                        "GET /v1/time-tracking/approvals",
                    ),
                    next_action="real_user_productivity_pilot_admission",
                ),
                RoadmapCapability(
                    capability_id="productivity_pilot_runtime_window",
                    title="Productivity Pilot Runtime Window",
                    summary=(
                        "Ein separates Runtime-Window beschraenkt die gueltige Startfreigabe auf explizit "
                        "designierte Pilotnutzer. Jeder zugelassene Zugriff erzeugt eine tenant-sichere, "
                        "append-only und inhaltsfreie Beobachtung."
                    ),
                    status=RoadmapCapabilityStatus.OPERATIONAL,
                    capability_type="operations_pilot_control",
                    evidence_refs=(
                        "app/suite/platform/productivity_pilot_runtime_window.py",
                        "app/suite/persistence/migrations/0064_productivity_pilot_runtime_window.sql",
                        "tests/test_productivity_pilot_start_authorization.py",
                        "docs/operations/PRODUCTIVITY_PILOT_RUNTIME_WINDOW.md",
                        "docs/operations/PRODUCTIVITY_PILOT_DEVELOPMENT_PROOF_20260731.md",
                        "docs/operations/BACKUP_FAILOVER.md",
                    ),
                    guardrails=(
                        "tenant_admin_runtime_operator_required",
                        "four_eyes_distinct_from_security_authorizer",
                        "designated_principal_allowlist_required",
                        "exact_start_authorization_and_route_hash_binding",
                        "metadata_only_authorization_observation",
                        "deployment_kill_switch_remains_authoritative",
                        "append_only_rls_and_restore_controls_required",
                    ),
                    api_routes=(
                        "/v1/platform/productivity-pilot/runtime-windows",
                        "/v1/platform/productivity-pilot/runtime-windows/current",
                    ),
                    next_action="real_user_productivity_pilot_admission",
                ),
                RoadmapCapability(
                    capability_id="productivity_pilot_closure_report",
                    title="Productivity Pilot Closure Report",
                    summary=(
                        "Der kontrollierte Entwicklungs-Pilot ist mit geschlossenem Kill-Switch, exakt sieben "
                        "Routenbeobachtungen, drei Domain-Receipts und Post-Closure-Restore append-only beendet."
                    ),
                    status=RoadmapCapabilityStatus.OPERATIONAL,
                    capability_type="operations_pilot_control",
                    evidence_refs=(
                        "app/suite/platform/productivity_pilot_closure_report.py",
                        "app/suite/persistence/migrations/0065_productivity_pilot_closure_report.sql",
                        "tests/test_productivity_pilot_closure_report.py",
                        "docs/operations/PRODUCTIVITY_PILOT_CLOSURE_REPORT.md",
                        "docs/operations/PRODUCTIVITY_PILOT_DEVELOPMENT_PROOF_20260731.md",
                        "docs/operations/BACKUP_FAILOVER.md",
                    ),
                    guardrails=(
                        "security_admin_four_eyes_closure_required",
                        "deployment_kill_switch_must_be_closed",
                        "exact_seven_route_observations_required",
                        "exact_three_authoritative_domain_receipts_required",
                        "designated_principal_hashes_only",
                        "refreshed_backup_restore_and_release_evidence_required",
                        "append_only_rls_and_restore_controls_required",
                        "no_record_mutation_deletion_content_or_external_action",
                    ),
                    api_routes=(
                        "/v1/platform/productivity-pilot/closure-reports",
                        "/v1/platform/productivity-pilot/closure-reports/current",
                    ),
                    next_action="real_user_productivity_pilot_admission",
                ),
                RoadmapCapability(
                    capability_id="productivity_pilot_real_user_admission_boundary",
                    title="Real User Pilot Admission Boundary",
                    summary=(
                        "Tenant-Admin-Nominierung und getrennte Security-Freigabe binden Zweck, "
                        "aktive IAM-Rollen, Datenschutz- und frische Recovery-Nachweise. Persistiert "
                        "werden nur pseudonymisierte Teilnehmerbelege; Laufzeit und Traffic bleiben aus."
                    ),
                    status=RoadmapCapabilityStatus.OPERATIONAL,
                    capability_type="operations_pilot_control",
                    evidence_refs=(
                        "app/suite/platform/productivity_pilot_real_user_admission.py",
                        "app/suite/persistence/migrations/0066_productivity_pilot_real_user_admission.sql",
                        "tests/test_productivity_pilot_real_user_admission.py",
                        "docs/operations/PRODUCTIVITY_PILOT_REAL_USER_ADMISSION.md",
                        "docs/operations/BACKUP_FAILOVER.md",
                    ),
                    guardrails=(
                        "authoritative_tenant_principal_and_role_resolution_required",
                        "purpose_lawful_basis_privacy_and_retention_binding_required",
                        "conditional_dpia_and_works_council_evidence_required",
                        "tenant_admin_security_admin_four_eyes_required",
                        "pseudonymized_participant_evidence_only",
                        "fresh_preflight_backup_restore_and_foundation_evidence_required",
                        "runtime_activation_and_traffic_remain_disabled",
                        "append_only_rls_and_restore_controls_required",
                    ),
                    api_routes=(
                        "/v1/platform/productivity-pilot/real-user-nominations",
                        "/v1/platform/productivity-pilot/real-user-nominations/current",
                        "/v1/platform/productivity-pilot/real-user-admissions",
                        "/v1/platform/productivity-pilot/real-user-admissions/current",
                    ),
                    next_action="collect_named_principals_and_fresh_control_evidence",
                ),
                RoadmapCapability(
                    capability_id="productivity_pilot_real_user_runtime_boundary",
                    title="Real User Pilot Hash-only Runtime Boundary",
                    summary=(
                        "Benannte Principals werden nur transient gegen IAM aufgeloest. Das Runtime-Ledger "
                        "speichert tenant-gebundene Hashes, prueft Rollen erneut und ersetzt nach einer "
                        "Realnutzer-Freigabe den Klartext-Runtime-v1-Pfad automatisch."
                    ),
                    status=RoadmapCapabilityStatus.OPERATIONAL,
                    capability_type="operations_pilot_control",
                    evidence_refs=(
                        "app/suite/platform/productivity_pilot_real_user_runtime_window.py",
                        "app/suite/persistence/migrations/0067_productivity_pilot_real_user_runtime_window.sql",
                        "app/suite/persistence/migrations/0071_productivity_pilot_real_user_runtime_owner_ref.sql",
                        "tests/test_productivity_pilot_real_user_runtime_window.py",
                        "docs/operations/PRODUCTIVITY_PILOT_REAL_USER_RUNTIME_WINDOW.md",
                        "docs/operations/BACKUP_FAILOVER.md",
                    ),
                    guardrails=(
                        "raw_principal_ids_are_transient_and_never_persisted",
                        "exact_real_user_admission_and_fresh_start_chain_required",
                        "current_authoritative_roles_checked_at_activation_and_access",
                        "runtime_operator_separated_from_nomination_admission_start_and_participants",
                        "legacy_plaintext_runtime_forbidden_after_real_user_admission",
                        "deployment_kill_switch_remains_authoritative_and_default_closed",
                        "metadata_only_hash_observations",
                        "append_only_rls_and_restore_controls_required",
                    ),
                    api_routes=(
                        "/v1/platform/productivity-pilot/real-user-runtime-windows",
                        "/v1/platform/productivity-pilot/real-user-runtime-windows/current",
                    ),
                    next_action="keep_runtime_closed_until_real_user_admission_and_start_evidence_are_complete",
                ),
                RoadmapCapability(
                    capability_id="productivity_pilot_real_user_closure_boundary",
                    title="Real User Pilot Hash-only Closure Boundary",
                    summary=(
                        "Ein separates append-only Closure-Ledger bindet Realnutzer-Admission, Start, "
                        "Runtime-Fenster, vollstaendiges Beobachtungsmanifest, zugehoerige Domain-Receipts "
                        "und frische Recovery-Nachweise ohne Klartext-Principal-IDs."
                    ),
                    status=RoadmapCapabilityStatus.OPERATIONAL,
                    capability_type="operations_pilot_control",
                    evidence_refs=(
                        "app/suite/platform/productivity_pilot_real_user_closure_report.py",
                        "app/suite/persistence/migrations/0069_productivity_pilot_real_user_closure_report.sql",
                        "app/suite/persistence/migrations/0070_productivity_pilot_real_user_closure_owner_refs.sql",
                        "tests/test_productivity_pilot_real_user_closure_report.py",
                        "docs/operations/PRODUCTIVITY_PILOT_REAL_USER_CLOSURE_REPORT.md",
                        "docs/operations/BACKUP_FAILOVER.md",
                    ),
                    guardrails=(
                        "security_admin_four_eyes_closure_required",
                        "deployment_kill_switch_must_be_closed",
                        "closed_by_principal_is_persisted_as_tenant_bound_hash_only",
                        "complete_hash_only_observation_manifest_required",
                        "persisted_pilot_writes_require_observation_bound_domain_receipts",
                        "unused_windows_can_close_without_invented_activity",
                        "fresh_backup_restore_and_release_evidence_required",
                        "append_only_rls_and_restore_controls_required",
                        "no_record_mutation_deletion_content_or_external_action",
                    ),
                    api_routes=(
                        "/v1/platform/productivity-pilot/real-user-closure-reports",
                        "/v1/platform/productivity-pilot/real-user-closure-reports/current",
                    ),
                    next_action="collect_real_user_nomination_and_current_human_control_evidence",
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
                    title="Persistente SourceObject Runtime",
                    summary=("PostgreSQL-Metadaten und exakte S3-Objektversionen sind im API-Startpfad verifiziert."),
                    status=RoadmapCapabilityStatus.OPERATIONAL,
                    capability_type="data_foundation",
                    evidence_refs=(
                        "tests/test_source_objects.py",
                        "tests/test_source_object_storage_bridge.py",
                        "tests/test_persistent_source_object_runtime.py",
                        "tests/test_exact_version_restore_drill.py",
                        "app/suite/storage/persistent_source_object_runtime.py",
                        "app/suite/storage/exact_version_restore_drill.py",
                        "docs/SOURCE_OBJECT_MODEL.md",
                    ),
                    api_routes=("/v1/source-objects/{object_id}/versions/{version_id}/metadata",),
                    guardrails=(
                        "acl_checked",
                        "fresh_repository_restart_read_verified",
                        "tenant_content_reconciliation_required",
                        "content_included_false",
                        "classification_retention_legal_hold_visible",
                    ),
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
                    title="Preview Renderer, Decision Ledger und Safe-Text-Release",
                    summary=(
                        "Preview-Evidence und Decisions bleiben metadata-only; ein evidence-gebundener, "
                        "ACL-gepruefter Klartext-Release ist guarded produktiv. Der Conversion-Worker besitzt eine "
                        "kryptografisch signierte Production-Admission-Grenze. ClamAV und die getrennte raw-RGB "
                        "Pixel-CDR-Grenze sind real im runsc-Entwicklungsproof samt Recovery nachgewiesen; Rich "
                        "Content, Mail, produktive CDR-/Malware-HA-Evidence und die signierte Evidence-Zeremonie "
                        "bleiben blockiert."
                    ),
                    status=RoadmapCapabilityStatus.GUARDED,
                    capability_type="content_boundary",
                    evidence_refs=(
                        "tests/test_source_object_preview_renderer_release_gate.py",
                        "tests/test_source_object_preview_decision_ledger.py",
                        "tests/test_source_object_preview_content_release.py",
                        "docs/modules/SOURCE_OBJECT_PREVIEW_CONTENT_RELEASE.md",
                        "app/suite/operations/preview_conversion_production_admission.py",
                        "tests/test_preview_conversion_production_admission.py",
                        "docs/operations/PREVIEW_CONVERSION_PRODUCTION_ADMISSION.md",
                        "app/suite/platform/preview_malware_scanner.py",
                        "tests/test_preview_malware_scanner.py",
                        "docs/operations/PREVIEW_MALWARE_SCANNER.md",
                        "app/suite/platform/preview_cdr.py",
                        "tests/test_preview_cdr.py",
                        "docs/operations/PREVIEW_CDR.md",
                    ),
                    api_routes=(
                        "/v1/source-objects/{object_id}/versions/{version_id}/preview-renderer-runs",
                        "/v1/source-objects/{object_id}/versions/{version_id}/preview-decisions",
                        "/v1/source-objects/{object_id}/versions/{version_id}/preview-content-releases",
                    ),
                    guardrails=(
                        "tenant_policy_and_authoritative_acl_revalidation",
                        "exact_human_confirmation",
                        "fresh_renderer_release_gate",
                        "manifest_content_hash_and_acl_version_binding",
                        "plain_text_and_markdown_allowlist",
                        "mail_attachments_html_and_binary_content_blocked",
                        "production_dispatch_requires_three_role_dsse_attestation",
                        "real_malware_and_cdr_service_evidence_required",
                        "clamav_scan_errors_and_stale_smoke_reports_quarantine",
                        "cdr_rebuilder_has_no_source_mount",
                        "raw_rgb_cdr_bundle_is_hash_bound_and_transient",
                        "worker_digest_sbom_and_provenance_verification_required",
                        "non_empty_recovery_and_separate_pdfjs_origin_required",
                        "preview_serving_remains_a_separate_gate",
                        "content_excluded_from_audit_and_release_receipts",
                    ),
                ),
                RoadmapCapability(
                    capability_id="office_edit_source_admission",
                    title="Office Quick Edit Source Admission",
                    summary=(
                        "Der GenOffice-DOCX-Kandidat ist auf exakte Archivbytes, ausgewaehlte Quelldateien, "
                        "Runtime-Abhaengigkeiten und byteverifizierten Vendorcode inventarisiert. Das validierte "
                        "CycloneDX-Pre-Build-SBOM und der netzlose Trivy-Scan decken exakt 23 Komponenten ohne "
                        "Finding ab. npm-Signatur, Publish-/SLSA-Attestierung, Fulcio-Identitaet und Rekor-Inclusion "
                        "sind kryptografisch verifiziert. Alle 21 Runtime-Archive und 42 Rechtsdateien sind im "
                        "no-network Legal-/NOTICE-/Trademark-Dossier hashgebunden. Ein deterministisches Drittanbieter-"
                        "NOTICE und die policy-gebundene Ed25519-Signier-Ceremony koennen nur den Development-Build "
                        "oeffnen. Request v2 ist maximal 72 Stunden gueltig, bindet Personen, Rollen und Key-IDs und "
                        "akzeptiert nur request-/message-hashgebundene externe Antworten. Ceremony-Ausgaben sind "
                        "privat und write-once; fehlende Datei-Binds werden nicht als Verzeichnisse erzeugt. Private "
                        "Schluessel bleiben ausserhalb von Repository und zentralem Assembler. Fuer die aktuelle "
                        "Ein-Personen-Organisation existiert daneben eine signierte, hoechstens 30 Tage gueltige "
                        "Solo-Founder-Ausnahme mit explizit ungueltigem Zwei-Personen-Nachweis. Sie oeffnet nur den "
                        "Development-Build-Context und verlangt vor jeder Runtime die regulaere Zwei-Personen-"
                        "Freigabe. "
                        "Der vorbereitete no-network Materializer erzeugt daraus erst nach realer Autorisierung ein "
                        "normalisiertes, manifestgebundenes TAR und fuehrt dabei keinen Upstream-Code aus. "
                        "Das daraus gebaute Alpine-Worker-Image ist durch zwei unabhaengige No-Cache-Builds, "
                        "Archiv-zu-Config-Bindung, eine autoritative CycloneDX-1.6-Runtime-SBOM, einen frischen "
                        "Offline-Vulnerability-Scan und eine externe Ed25519-Build-Attestierung verifiziert. Das "
                        "signierte Image ist nur als Development-Spike-Artefakt verfuegbar; sein Entry-Point und "
                        "der Admission-Report halten die Worker-Ausfuehrung geschlossen. Ein engine-unabhaengiger "
                        "19-Faelle-OOXML-Preflight prueft inzwischen Paketstruktur, Expansion, XML, externe "
                        "Relationships, VBA/OLE und unvalidierte Package-Signaturen ohne Extraktion. Safe-/High-"
                        "Fidelity-Regeln und eine kandidat-only source-blinde Revalidierung sind hashgebunden; der "
                        "Executable-Harness bleibt ohne echte Zwei-Personen-Freigabe und neues attestiertes Image "
                        "hart geschlossen. "
                        "Eine exakte 3x3-Fidelity-Studie bindet Word, LibreOffice und GenOffice an dieselben drei "
                        "synthetischen Fixtures, strukturelle OOXML-Baselines, CDR-RGB-Metriken und getrennte "
                        "Ed25519-Runner-Identitaeten. Selbst der vollstaendige signierte Matrix-Intake bleibt ohne "
                        "Evidenzbyte-Pruefung, kalibrierte Schwellen und Human Review ohne Kompatibilitaetswirkung. "
                        "Der separate source-blinde Evidence-Verifier kann inzwischen jedes Receipt-Artefakt, DOCX-"
                        "Preflight, OOXML-Struktur, Open-XML-/Font-Bindung, CDR-RGB-Byte und jeden visuellen Messwert "
                        "unabhaengig pruefen; reale Runner-Evidenz liegt weiterhin nicht vor. "
                        "Import, Engine, Content, Hosted Service, On-Prem und Produktion bleiben bis ihrer jeweils "
                        "eigenen Build-, Security-, Fidelity-, Recovery- und Deployment-Evidence geschlossen."
                    ),
                    status=RoadmapCapabilityStatus.GUARDED,
                    capability_type="office_edit_boundary",
                    evidence_refs=(
                        "app/suite/operations/genoffice_docx_source_admission.py",
                        "tests/test_genoffice_docx_source_admission.py",
                        "docs/operations/GENOFFICE_SOURCE_ADMISSION.md",
                        "docs/operations/genoffice_docx_source_admission_report.json",
                        "app/suite/operations/genoffice_vendored_provenance_admission.py",
                        "docs/operations/genoffice_vendored_provenance_report.json",
                        "app/suite/operations/genoffice_docx_prebuild_sbom.py",
                        "docs/operations/genoffice_docx_prebuild.cdx.json",
                        "app/suite/operations/genoffice_docx_supply_chain_admission.py",
                        "docs/operations/genoffice_docx_supply_chain_admission_report.json",
                        "app/suite/operations/genoffice_npm_provenance_admission.py",
                        "app/suite/kms/x509_evidence.py",
                        "docs/operations/genoffice_npm_provenance_admission_report.json",
                        "app/suite/operations/genoffice_license_material_collector.py",
                        "app/suite/operations/genoffice_legal_review_dossier.py",
                        "app/suite/operations/genoffice_third_party_notice.py",
                        "app/suite/operations/genoffice_internal_oss_ceremony.py",
                        "app/suite/operations/genoffice_internal_oss_admission.py",
                        "app/suite/operations/genoffice_solo_founder_exception.py",
                        "app/suite/operations/genoffice_development_build_context.py",
                        "app/suite/operations/genoffice_worker_image_admission.py",
                        "tests/test_genoffice_license_material_collector.py",
                        "tests/test_genoffice_legal_review_dossier.py",
                        "tests/test_genoffice_third_party_notice.py",
                        "tests/test_genoffice_internal_oss_ceremony.py",
                        "tests/test_genoffice_internal_oss_admission.py",
                        "tests/test_genoffice_solo_founder_exception.py",
                        "tests/test_genoffice_development_build_context.py",
                        "tests/test_genoffice_worker_image_admission.py",
                        "docs/operations/GENOFFICE_LEGAL_REVIEW.md",
                        "docs/operations/GENOFFICE_INTERNAL_OSS_ADMISSION.md",
                        "docs/operations/GENOFFICE_SOLO_FOUNDER_EXCEPTION.md",
                        "docs/operations/GENOFFICE_DEVELOPMENT_BUILD_CONTEXT.md",
                        "docs/operations/GENOFFICE_WORKER_IMAGE_ADMISSION.md",
                        "docs/operations/genoffice_license_material_collection_report.json",
                        "docs/operations/genoffice_legal_review_dossier_report.json",
                        "docs/operations/genoffice_legal_decision_record.schema.json",
                        "docs/operations/GENOFFICE_THIRD_PARTY_NOTICES.txt",
                        "docs/operations/genoffice_third_party_notice_report.json",
                        "docs/operations/genoffice_internal_oss_decision.schema.json",
                        "docs/operations/genoffice_internal_oss_signer_policy.schema.json",
                        "docs/operations/genoffice-solo-founder-policy.schema.json",
                        "docs/operations/genoffice-solo-founder-exception-request.schema.json",
                        "docs/operations/genoffice-solo-founder-signature-response.schema.json",
                        "docs/operations/genoffice-solo-founder-exception-report.schema.json",
                        "docs/operations/genoffice-worker-image-build-evidence.schema.json",
                        "docs/operations/genoffice-worker-build-signing-request.schema.json",
                        "docs/operations/genoffice-worker-build-signature-response.schema.json",
                        "docs/operations/genoffice-worker-image-admission-report.schema.json",
                        "app/suite/operations/genoffice_docx_quick_edit_preflight.py",
                        "tests/test_genoffice_docx_quick_edit_preflight.py",
                        "docs/operations/GENOFFICE_DOCX_QUICK_EDIT_PREFLIGHT.md",
                        "docs/operations/genoffice-docx-quick-edit-preflight-policy.schema.json",
                        "docs/operations/genoffice-docx-quick-edit-corpus-manifest.schema.json",
                        "docs/operations/genoffice-docx-quick-edit-preflight-report.schema.json",
                        "docs/operations/genoffice-docx-quick-edit-corpus-evaluation-report.schema.json",
                        "docs/operations/genoffice-docx-source-blind-revalidation-report.schema.json",
                        "docs/operations/genoffice-docx-quick-edit-harness-admission-report.schema.json",
                        "app/suite/operations/genoffice_docx_fidelity_study.py",
                        "tests/test_genoffice_docx_fidelity_study.py",
                        "docs/operations/GENOFFICE_DOCX_FIDELITY_STUDY.md",
                        "docs/operations/genoffice-docx-fidelity-study-policy.schema.json",
                        "docs/operations/genoffice-docx-fidelity-study-plan.schema.json",
                        "docs/operations/genoffice-docx-structural-fingerprint-report.schema.json",
                        "docs/operations/genoffice-docx-fidelity-baseline-report.schema.json",
                        "docs/operations/genoffice-docx-rgb-page-comparison-report.schema.json",
                        "docs/operations/genoffice-docx-fidelity-engine-result-payload.schema.json",
                        "docs/operations/genoffice-docx-fidelity-result-signer-policy.schema.json",
                        "docs/operations/genoffice-docx-fidelity-signed-result-envelope.schema.json",
                        "docs/operations/genoffice-docx-fidelity-result-matrix-intake-report.schema.json",
                        "docs/operations/genoffice-docx-fidelity-readiness-report.schema.json",
                        "app/suite/operations/genoffice_docx_fidelity_evidence.py",
                        "tests/test_genoffice_docx_fidelity_evidence.py",
                        "docs/operations/GENOFFICE_DOCX_FIDELITY_EVIDENCE.md",
                        "docs/operations/genoffice-docx-openxml-validation-report.schema.json",
                        "docs/operations/genoffice-docx-fidelity-font-baseline-report.schema.json",
                        "docs/operations/genoffice-docx-fidelity-cdr-manifest.schema.json",
                        "docs/operations/genoffice-docx-fidelity-visual-comparison-manifest.schema.json",
                        "docs/operations/genoffice-docx-fidelity-execution-receipt.schema.json",
                        "docs/operations/genoffice-docx-fidelity-evidence-verification-report.schema.json",
                        "ARCHITECTURE_DECISIONS/ADR-0062-genoffice-source-admission.md",
                        "ARCHITECTURE_DECISIONS/ADR-0063-genoffice-prebuild-supply-chain.md",
                        "ARCHITECTURE_DECISIONS/ADR-0064-genoffice-npm-cryptographic-provenance.md",
                        "ARCHITECTURE_DECISIONS/ADR-0065-genoffice-legal-review-dossier.md",
                        "ARCHITECTURE_DECISIONS/ADR-0066-genoffice-internal-oss-admission.md",
                        "ARCHITECTURE_DECISIONS/ADR-0067-genoffice-development-build-context.md",
                        "ARCHITECTURE_DECISIONS/ADR-0068-genoffice-solo-founder-development-exception.md",
                        "ARCHITECTURE_DECISIONS/ADR-0069-genoffice-worker-image-admission.md",
                        "ARCHITECTURE_DECISIONS/ADR-0070-genoffice-synthetic-runtime-proof-authorization.md",
                        "ARCHITECTURE_DECISIONS/ADR-0071-genoffice-docx-quick-edit-preflight.md",
                        "ARCHITECTURE_DECISIONS/ADR-0072-genoffice-docx-fidelity-study.md",
                        "ARCHITECTURE_DECISIONS/ADR-0073-genoffice-docx-fidelity-evidence-verification.md",
                    ),
                    api_routes=(
                        "/v1/source-objects/{object_id}/versions/{version_id}/office-edit-adapter-evaluations",
                    ),
                    guardrails=(
                        "exact_upstream_archive_sha256",
                        "archive_never_extracted",
                        "no_network_or_upstream_execution",
                        "prohibited_scopes_excluded_from_source_manifest",
                        "runtime_dependency_and_vendored_license_inventory",
                        "vendored_npm_tarball_byte_provenance",
                        "deterministic_cyclonedx_prebuild_sbom",
                        "network_separated_trivy_db_update_and_scan",
                        "exact_23_purl_inventory_and_fresh_db_gate",
                        "high_and_critical_findings_blocked",
                        "npm_registry_signature_and_publish_attestation_verified",
                        "slsa_fulcio_identity_and_rekor_inclusion_verified",
                        "exact_runtime_license_archives_integrity_verified",
                        "offline_notice_trademark_and_enterprise_scope_dossier",
                        "two_distinct_internal_oss_signers_required",
                        "signer_policy_hash_bound_into_signed_payload",
                        "public_input_only_envelope_assembler",
                        "signing_keys_remain_outside_collabio",
                        "ed25519_verification_behind_kms_adapter",
                        "signing_request_maximum_72_hour_validity",
                        "signer_role_identity_and_key_assignments_bound",
                        "external_signature_responses_bind_request_and_message_hashes",
                        "ceremony_outputs_private_and_write_once",
                        "missing_file_binds_never_auto_create_directories",
                        "solo_founder_exception_maximum_30_day_validity",
                        "solo_founder_exception_records_two_person_control_false",
                        "solo_founder_exception_allows_build_context_only",
                        "two_person_reauthorization_required_before_runtime",
                        "development_worker_build_blocked_until_signed_authorization",
                        "deterministic_tar_context_after_exactly_one_authorization",
                        "all_selected_source_files_rehashed_without_extraction",
                        "normalized_uid_gid_mode_order_and_source_date_epoch",
                        "materializer_performs_no_dependency_install_or_upstream_execution",
                        "two_independent_no_cache_worker_builds",
                        "worker_archive_config_digest_binding",
                        "authoritative_cyclonedx_runtime_image_sbom",
                        "fresh_offline_runtime_image_vulnerability_scan",
                        "external_ed25519_worker_build_attestation",
                        "development_image_available_with_worker_execution_false",
                        "bounded_ooxml_preflight_without_filesystem_extraction",
                        "external_active_embedded_and_ambiguous_package_content_rejected",
                        "signed_original_retained_and_derived_signature_invalidated",
                        "safe_and_high_fidelity_export_contracts_are_separate",
                        "candidate_only_source_blind_revalidation_required",
                        "executable_harness_closed_without_two_person_authorization_and_new_attested_image",
                        "exact_three_engine_by_three_fixture_fidelity_plan",
                        "microsoft_word_requires_interactive_windows_runner",
                        "libreoffice_requires_isolated_headless_runner",
                        "genoffice_runner_requires_two_person_runtime_authorization",
                        "structural_ooxml_and_cdr_rgb_metrics_are_separate_axes",
                        "one_distinct_ed25519_result_signer_per_engine",
                        "signed_matrix_intake_does_not_verify_referenced_evidence_bytes",
                        "source_blind_receipt_inventory_and_artifact_byte_verification",
                        "output_preflight_and_ooxml_structure_recomputed_from_docx_bytes",
                        "openxml_font_cdr_and_visual_measurements_cross_bound",
                        "single_result_evidence_verification_does_not_grant_compatibility",
                        "no_fidelity_claim_without_calibration_and_human_review",
                        "hosted_on_prem_and_production_profiles_remain_blocked",
                        "source_import_and_production_use_blocked",
                    ),
                ),
            ),
        ),
        RoadmapCapabilityGroup(
            group_id="workspace_modules",
            title="Workspace, Module und erste Fachslices",
            summary=(
                "Modul-Discovery, Workspace Cockpit, KB, CRM, ERP, Tickets-Dry-Run-Approval-Boundary "
                "und ACL-first Suche sind tenant-sicher angebunden."
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
                    capability_id="crm_account_workspace_runtime",
                    title="CRM Account Workspace Runtime",
                    summary=(
                        "Accounts, Contacts, Activities und Notes laufen ueber PostgreSQL-RLS und werden als "
                        "gemeinsamer ACL-gepruefter Account-Workflow gelesen."
                    ),
                    status=RoadmapCapabilityStatus.OPERATIONAL,
                    capability_type="productive_business_read_workflow",
                    evidence_refs=(
                        "app/suite/platform/crm_runtime.py",
                        "app/suite/platform/crm_workspace.py",
                        "tests/test_crm_runtime.py",
                        "tests/test_crm_workspace.py",
                        "tests/test_crm_workspace_api.py",
                        "docs/modules/CRM_ACCOUNT_WORKSPACE_VERTICAL_SLICE.md",
                    ),
                    api_routes=(
                        "/v1/crm/accounts",
                        "/v1/crm/contacts",
                        "/v1/crm/activities",
                        "/v1/crm/notes",
                        "/v1/crm/accounts/{account_object_id}/workspace",
                    ),
                    guardrails=(
                        "postgres_runtime_required",
                        "forced_tenant_rls",
                        "all_three_crm_feature_gates_required",
                        "authoritative_object_acl_filtering",
                        "linked_object_redaction",
                        "metadata_only_note_contract",
                        "backup_dependency_required",
                    ),
                    next_action="real_user_productivity_pilot_admission",
                ),
                RoadmapCapability(
                    capability_id="crm_atomic_account_onboarding_runtime",
                    title="CRM Atomic Account Onboarding",
                    summary=(
                        "Account, Contact, Activity, metadata-only Note, vier Owner-ACLs und ein unveraenderliches "
                        "Receipt werden in einer PostgreSQL-Transaktion geschrieben."
                    ),
                    status=RoadmapCapabilityStatus.OPERATIONAL,
                    capability_type="productive_business_write_workflow",
                    evidence_refs=(
                        "app/suite/platform/crm_onboarding.py",
                        "app/suite/persistence/migrations/0057_crm_atomic_account_onboarding.sql",
                        "tests/test_crm_onboarding.py",
                        "tests/test_crm_onboarding_api.py",
                        "tests/test_crm_onboarding_migration.py",
                        "docs/modules/CRM_ACCOUNT_ONBOARDING_VERTICAL_SLICE.md",
                    ),
                    api_routes=("/v1/crm/account-onboardings",),
                    guardrails=(
                        "all_three_crm_feature_gates_required",
                        "server_side_operator_role_required",
                        "forced_tenant_rls",
                        "business_rows_acl_and_receipt_one_transaction",
                        "actor_bound_idempotency",
                        "append_only_metadata_receipt",
                        "partial_write_rollback_proven",
                        "restore_control_verification_required",
                        "note_body_forbidden",
                    ),
                    next_action="real_user_productivity_pilot_admission",
                ),
                RoadmapCapability(
                    capability_id="tasks_activities_runtime",
                    title="Tasks and Activities Runtime",
                    summary=(
                        "Task, initiale Aktivitaet, autoritative ACLs und ein metadata-only Receipt werden "
                        "tenant-sicher und atomar in PostgreSQL angelegt und ACL-geprueft gelesen."
                    ),
                    status=RoadmapCapabilityStatus.OPERATIONAL,
                    capability_type="productive_business_write_workflow",
                    evidence_refs=(
                        "app/suite/platform/tasks_activities_service.py",
                        "app/suite/persistence/migrations/0059_tasks_activities_productive_slice.sql",
                        "tests/test_tasks_activities_productive_slice.py",
                        "tests/test_tasks_activities_api.py",
                        "docs/modules/TASKS_ACTIVITIES_PRODUCTIVE_VERTICAL_SLICE.md",
                    ),
                    api_routes=(
                        "/v1/tasks/items",
                        "/v1/tasks/activities",
                    ),
                    guardrails=(
                        "tenant_module_and_feature_gates_required",
                        "server_side_operator_role_required",
                        "forced_tenant_rls",
                        "authoritative_object_acl_filtering",
                        "task_activity_acl_and_receipt_one_transaction",
                        "actor_and_assignee_bound_idempotency",
                        "append_only_business_rows_and_metadata_receipt",
                        "linked_task_acl_required_for_activity_read",
                        "partial_write_rollback_proven",
                        "restore_control_verification_required",
                    ),
                    next_action="real_user_productivity_pilot_admission",
                ),
                RoadmapCapability(
                    capability_id="time_tracking_runtime",
                    title="Time Tracking Runtime",
                    summary=(
                        "Zeiteintrag, initialer Freigabestatus, autoritative ACLs und metadata-only Receipt werden "
                        "tenant-sicher und atomar in PostgreSQL angelegt und ACL-geprueft gelesen."
                    ),
                    status=RoadmapCapabilityStatus.OPERATIONAL,
                    capability_type="productive_business_write_workflow",
                    evidence_refs=(
                        "app/suite/platform/time_tracking_module.py",
                        "app/suite/platform/time_tracking_service.py",
                        "app/suite/persistence/migrations/0060_time_tracking_productive_slice.sql",
                        "tests/test_time_tracking_productive_slice.py",
                        "tests/test_time_tracking_api.py",
                        "docs/modules/TIME_TRACKING_MODULE_CHARTER.md",
                    ),
                    api_routes=(
                        "/v1/time-tracking/entries",
                        "/v1/time-tracking/approvals",
                    ),
                    guardrails=(
                        "tenant_module_and_feature_gates_required",
                        "server_side_creator_role_required",
                        "forced_tenant_rls",
                        "authoritative_object_acl_filtering",
                        "entry_approval_acl_and_receipt_one_transaction",
                        "actor_and_worker_bound_idempotency",
                        "append_only_business_rows_and_metadata_receipt",
                        "linked_entry_acl_required_for_approval_read",
                        "partial_write_rollback_proven",
                        "restore_control_verification_required",
                        "approval_decisions_and_payroll_exports_deferred",
                    ),
                    next_action="real_user_productivity_pilot_admission",
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
                        "/v1/platform/search/crm-erp/source-resolver-acl-trace",
                        "/v1/platform/search/crm-erp/source-citation-contract",
                        "/v1/platform/search/crm-erp/prompt-audit-contract",
                        "/v1/platform/search/crm-erp/redaction-contract",
                        "/v1/platform/search/crm-erp/authorized-context-contract",
                        "/v1/platform/search/crm-erp/inference-execution-boundary",
                    ),
                    guardrails=(
                        "module_gate_required",
                        "readiness_endpoint_metadata_only",
                        "authoritative_acl_validation",
                        "candidate_only_metadata_only",
                        "no_ai_or_rag_context",
                        "source_resolver_acl_trace_metadata_only",
                        "source_citation_contract_metadata_only",
                        "prompt_audit_contract_metadata_only",
                        "redaction_contract_metadata_only",
                        "authorized_context_contract_metadata_only",
                        "inference_execution_boundary_metadata_only",
                        "rag_readiness_contract_ready_without_answer_generation",
                    ),
                    next_action="decide_crm_erp_answer_execution_slice_or_return_to_cross_module_foundation",
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
                    summary=(
                        "Tasks & Activities und Zeiterfassung besitzen produktive atomare Write/Read-Slices. "
                        "Tickets & Incidents besitzt neben der vollstaendigen Aktivierungskontrollkette eine "
                        "produktive, tenant-sichere Ticket/Event-Vertikale. Die definierte Modul-Familien-Queue "
                        "ist geschlossen; naechster Fokus ist gemeinsame Backend-Release-Readiness."
                    ),
                    status=RoadmapCapabilityStatus.GUARDED,
                    capability_type="module_foundation_and_productive_vertical_slice",
                    evidence_refs=(
                        "docs/modules/MODULE_IMPLEMENTATION_CONTRACT.md",
                        "app/suite/platform/module_family_backlog.py",
                        "app/suite/platform/tasks_activities_module.py",
                        "app/suite/platform/tasks_activities_catalog_readiness.py",
                        "app/suite/platform/tickets_incidents_module.py",
                        "app/suite/platform/tickets_incidents_catalog_readiness.py",
                        "app/suite/platform/tickets_incidents_migration_evidence_gate.py",
                        "app/suite/platform/tickets_incidents_storage_migration_evidence.py",
                        "app/suite/platform/tickets_incidents_restore_drill_evidence.py",
                        "app/suite/platform/tickets_incidents_tenant_admin_activation_approval_gate.py",
                        "app/suite/platform/tickets_incidents_tenant_admin_activation_approval_record.py",
                        "app/suite/platform/tickets_incidents_activation_execution_boundary.py",
                        "app/suite/platform/tickets_incidents_activation_executor_skeleton.py",
                        "app/suite/platform/tickets_incidents_activation_dry_run_plan.py",
                        "app/suite/platform/tickets_incidents_activation_dry_run_execution_boundary.py",
                        "app/suite/platform/tickets_incidents_activation_dry_run_execution_skeleton.py",
                        "app/suite/platform/tickets_incidents_activation_dry_run_executor_implementation_review.py",
                        "app/suite/platform/tickets_incidents_activation_dry_run_result_contract.py",
                        "app/suite/platform/tickets_incidents_activation_dry_run_execution_gate.py",
                        "app/suite/platform/tickets_incidents_activation_dry_run_execution_request_boundary.py",
                        "app/suite/platform/tickets_incidents_activation_dry_run_executor_runtime_boundary.py",
                        "app/suite/platform/tickets_incidents_activation_dry_run_execution_preflight.py",
                        "app/suite/platform/tickets_incidents_activation_dry_run_execution_receipt_boundary.py",
                        "app/suite/platform/tickets_incidents_activation_dry_run_result_persistence_boundary.py",
                        "app/suite/platform/tickets_incidents_activation_dry_run_execution_activation_boundary.py",
                        "app/suite/platform/tickets_incidents_activation_dry_run_execution_start_boundary.py",
                        "app/suite/platform/tickets_incidents_activation_dry_run_execution_dispatch_boundary.py",
                        "app/suite/platform/tickets_incidents_activation_dry_run_execution_worker_boundary.py",
                        "app/suite/platform/tickets_incidents_activation_dry_run_execution_final_readiness_gate.py",
                        "app/suite/platform/tickets_incidents_activation_dry_run_execution_approval_boundary.py",
                        "app/suite/platform/tickets_incidents_activation_dry_run_execution_approval_record.py",
                        "app/suite/platform/tickets_incidents_service.py",
                        "app/suite/platform/lms_module.py",
                        "app/suite/platform/lms_catalog_readiness.py",
                        "app/suite/platform/lms_package_installation_readiness.py",
                        "app/suite/platform/lms_package_installation_execution_boundary.py",
                        "app/suite/platform/lms_package_installation_executor_skeleton.py",
                        "app/suite/platform/lms_package_installation_dry_run_plan.py",
                        "app/suite/platform/lms_package_installation_dry_run_execution_boundary.py",
                        "app/suite/platform/lms_package_installation_dry_run_execution_skeleton.py",
                        "app/suite/platform/lms_package_installation_dry_run_executor_implementation_review.py",
                        "app/suite/platform/lms_package_installation_dry_run_result_contract.py",
                        "app/suite/platform/lms_package_installation_dry_run_execution_gate.py",
                        "app/suite/platform/lms_package_installation_dry_run_execution_request_boundary.py",
                        "app/suite/platform/lms_package_installation_dry_run_executor_runtime_boundary.py",
                        "app/suite/platform/lms_package_installation_dry_run_execution_preflight.py",
                        "app/suite/platform/lms_package_installation_dry_run_execution_receipt_boundary.py",
                        "app/suite/platform/lms_package_installation_dry_run_result_persistence_boundary.py",
                        "app/suite/platform/lms_package_installation_dry_run_execution_activation_boundary.py",
                        "app/suite/platform/lms_package_installation_dry_run_execution_start_boundary.py",
                        "app/suite/platform/lms_package_installation_dry_run_execution_dispatch_boundary.py",
                        "app/suite/platform/lms_package_installation_dry_run_execution_worker_boundary.py",
                        "app/suite/platform/lms_package_installation_dry_run_execution_final_readiness_gate.py",
                        "app/suite/platform/lms_package_installation_dry_run_execution_approval_boundary.py",
                        "app/suite/platform/lms_package_installation_dry_run_execution_approval_record.py",
                        "app/suite/platform/lms_package_installation_dry_run_execution_admission_gate.py",
                        "app/suite/platform/lms_package_installation_dry_run_execution_runbook.py",
                        "app/suite/platform/lms_package_installation_dry_run_execution_plan.py",
                        "app/suite/platform/lms_package_installation_dry_run_execution_plan_review.py",
                        "app/suite/platform/lms_package_installation_dry_run_execution_scheduler_boundary.py",
                        "app/suite/platform/lms_package_installation_dry_run_execution_worker_image_boundary.py",
                        "app/suite/platform/lms_package_installation_dry_run_execution_job_outbox.py",
                        "app/suite/platform/lms_restore_drill_evidence.py",
                        "app/suite/platform/lms_tenant_admin_package_approval_gate.py",
                        "app/suite/platform/lms_tenant_admin_package_approval_record.py",
                        "app/suite/persistence/migrations/0046_lms_metadata_schema.sql",
                        "app/suite/persistence/migrations/0047_lms_package_install_approval_records.sql",
                        "app/suite/persistence/migrations/0048_lms_dry_run_execution_approval_records.sql",
                        "app/suite/persistence/migrations/0049_lms_dry_run_execution_job_outbox.sql",
                        "app/suite/persistence/migrations/0050_tasks_activities_catalog_registration.sql",
                        "app/suite/persistence/migrations/0059_tasks_activities_productive_slice.sql",
                        "app/suite/platform/tasks_activities_service.py",
                        "tests/test_tasks_activities_productive_slice.py",
                        "tests/test_tasks_activities_api.py",
                        "app/suite/platform/time_tracking_module.py",
                        "app/suite/platform/time_tracking_service.py",
                        "app/suite/persistence/migrations/0060_time_tracking_productive_slice.sql",
                        "tests/test_time_tracking_module_foundation.py",
                        "tests/test_time_tracking_productive_slice.py",
                        "tests/test_time_tracking_api.py",
                        "docs/modules/TIME_TRACKING_MODULE_CHARTER.md",
                        "app/suite/persistence/migrations/0051_tickets_incidents_catalog_registration.sql",
                        "app/suite/persistence/migrations/0052_tickets_incidents_metadata_schema.sql",
                        "app/suite/persistence/migrations/0053_tickets_incidents_dry_run_execution_approval_records.sql",
                        "tests/test_tickets_incidents_restore_drill_evidence.py",
                        "tests/test_tickets_incidents_tenant_admin_activation_approval_gate.py",
                        "tests/test_tickets_incidents_tenant_admin_activation_approval_record.py",
                        "tests/test_tickets_incidents_activation_execution_boundary.py",
                        "tests/test_tickets_incidents_activation_executor_skeleton.py",
                        "tests/test_tickets_incidents_activation_dry_run_plan.py",
                        "tests/test_tickets_incidents_activation_dry_run_execution_boundary.py",
                        "tests/test_tickets_incidents_activation_dry_run_execution_skeleton.py",
                        "tests/test_tickets_incidents_activation_dry_run_executor_implementation_review.py",
                        "tests/test_tickets_incidents_activation_dry_run_result_contract.py",
                        "tests/test_tickets_incidents_activation_dry_run_execution_gate.py",
                        "tests/test_tickets_incidents_activation_dry_run_execution_request_boundary.py",
                        "tests/test_tickets_incidents_activation_dry_run_executor_runtime_boundary.py",
                        "tests/test_tickets_incidents_activation_dry_run_execution_preflight.py",
                        "tests/test_tickets_incidents_activation_dry_run_execution_receipt_boundary.py",
                        "tests/test_tickets_incidents_activation_dry_run_result_persistence_boundary.py",
                        "tests/test_tickets_incidents_activation_dry_run_execution_activation_boundary.py",
                        "tests/test_tickets_incidents_activation_dry_run_execution_start_boundary.py",
                        "tests/test_tickets_incidents_activation_dry_run_execution_dispatch_boundary.py",
                        "tests/test_tickets_incidents_activation_dry_run_execution_worker_boundary.py",
                        "tests/test_tickets_incidents_activation_dry_run_execution_final_readiness_gate.py",
                        "tests/test_tickets_incidents_activation_dry_run_execution_approval_boundary.py",
                        "tests/test_tickets_incidents_activation_dry_run_execution_approval_record.py",
                        "tests/test_tickets_incidents_service.py",
                        "tests/test_tickets_incidents_api.py",
                        "docs/modules/TASKS_ACTIVITIES_MODULE_CHARTER.md",
                        "docs/modules/TICKETS_INCIDENTS_MODULE_CHARTER.md",
                        "docs/modules/LMS_MODULE_CHARTER.md",
                        "tests/test_module_family_backlog.py",
                        "tests/test_tasks_activities_module_foundation.py",
                        "tests/test_tasks_activities_catalog_readiness.py",
                        "tests/test_tickets_incidents_module_foundation.py",
                        "tests/test_tickets_incidents_catalog_readiness.py",
                        "tests/test_tickets_incidents_migration_evidence_gate.py",
                        "tests/test_tickets_incidents_storage_migration_evidence.py",
                        "tests/test_lms_module_foundation.py",
                        "tests/test_lms_catalog_readiness.py",
                        "tests/test_lms_package_installation_readiness.py",
                        "tests/test_lms_package_installation_execution_boundary.py",
                        "tests/test_lms_package_installation_executor_skeleton.py",
                        "tests/test_lms_package_installation_dry_run_plan.py",
                        "tests/test_lms_package_installation_dry_run_execution_boundary.py",
                        "tests/test_lms_package_installation_dry_run_execution_skeleton.py",
                        "tests/test_lms_package_installation_dry_run_executor_implementation_review.py",
                        "tests/test_lms_package_installation_dry_run_result_contract.py",
                        "tests/test_lms_package_installation_dry_run_execution_gate.py",
                        "tests/test_lms_package_installation_dry_run_execution_request_boundary.py",
                        "tests/test_lms_package_installation_dry_run_executor_runtime_boundary.py",
                        "tests/test_lms_package_installation_dry_run_execution_preflight.py",
                        "tests/test_lms_package_installation_dry_run_execution_receipt_boundary.py",
                        "tests/test_lms_package_installation_dry_run_result_persistence_boundary.py",
                        "tests/test_lms_package_installation_dry_run_execution_activation_boundary.py",
                        "tests/test_lms_package_installation_dry_run_execution_start_boundary.py",
                        "tests/test_lms_package_installation_dry_run_execution_dispatch_boundary.py",
                        "tests/test_lms_package_installation_dry_run_execution_worker_boundary.py",
                        "tests/test_lms_package_installation_dry_run_execution_final_readiness_gate.py",
                        "tests/test_lms_package_installation_dry_run_execution_approval_boundary.py",
                        "tests/test_lms_package_installation_dry_run_execution_approval_record.py",
                        "tests/test_lms_package_installation_dry_run_execution_admission_gate.py",
                        "tests/test_lms_package_installation_dry_run_execution_runbook.py",
                        "tests/test_lms_package_installation_dry_run_execution_plan.py",
                        "tests/test_lms_package_installation_dry_run_execution_plan_review.py",
                        "tests/test_lms_package_installation_dry_run_execution_scheduler_boundary.py",
                        "tests/test_lms_package_installation_dry_run_execution_worker_image_boundary.py",
                        "tests/test_lms_package_installation_dry_run_execution_job_outbox.py",
                        "tests/test_lms_restore_drill_evidence.py",
                        "tests/test_lms_tenant_admin_package_approval_gate.py",
                        "tests/test_lms_tenant_admin_package_approval_record.py",
                        "tests/test_pgvector_migration.py",
                    ),
                    api_routes=(
                        "/v1/platform/modules/families/backlog",
                        "/v1/platform/modules/families/next-slice-selection",
                        "/v1/platform/modules/families/tasks-activities/catalog-readiness",
                        "/v1/platform/modules/families/tickets-incidents/catalog-readiness",
                        "/v1/tasks/items",
                        "/v1/tasks/activities",
                        "/v1/time-tracking/entries",
                        "/v1/time-tracking/approvals",
                        "/v1/platform/modules/families/tickets-incidents/migration-evidence-gate",
                        "/v1/platform/modules/families/tickets-incidents/storage-migration-evidence",
                        "/v1/platform/modules/families/tickets-incidents/restore-drill-evidence",
                        "/v1/platform/modules/families/tickets-incidents/tenant-admin-activation-approval-gate",
                        "/v1/platform/modules/families/tickets-incidents/tenant-admin-activation-approval-records",
                        "/v1/platform/modules/families/tickets-incidents/activation-execution-boundary",
                        "/v1/platform/modules/families/tickets-incidents/activation-executor-skeleton",
                        "/v1/platform/modules/families/tickets-incidents/activation-dry-run-plan",
                        "/v1/platform/modules/families/tickets-incidents/activation-dry-run-execution-boundary",
                        "/v1/platform/modules/families/tickets-incidents/activation-dry-run-execution-skeleton",
                        "/v1/platform/modules/families/tickets-incidents/activation-dry-run-executor-implementation-review",
                        "/v1/platform/modules/families/tickets-incidents/activation-dry-run-result-contract",
                        "/v1/platform/modules/families/tickets-incidents/activation-dry-run-execution-gate",
                        "/v1/platform/modules/families/tickets-incidents/activation-dry-run-execution-request-boundary",
                        "/v1/platform/modules/families/tickets-incidents/activation-dry-run-executor-runtime-boundary",
                        "/v1/platform/modules/families/tickets-incidents/activation-dry-run-execution-preflight",
                        "/v1/platform/modules/families/tickets-incidents/activation-dry-run-execution-receipt-boundary",
                        "/v1/platform/modules/families/tickets-incidents/activation-dry-run-result-persistence-boundary",
                        "/v1/platform/modules/families/tickets-incidents/activation-dry-run-execution-activation-boundary",
                        "/v1/platform/modules/families/tickets-incidents/activation-dry-run-execution-start-boundary",
                        "/v1/platform/modules/families/tickets-incidents/activation-dry-run-execution-dispatch-boundary",
                        "/v1/platform/modules/families/tickets-incidents/activation-dry-run-execution-worker-boundary",
                        "/v1/platform/modules/families/tickets-incidents/activation-dry-run-execution-final-readiness-gate",
                        "/v1/platform/modules/families/tickets-incidents/activation-dry-run-execution-approval-boundary",
                        "/v1/platform/modules/families/tickets-incidents/activation-dry-run-execution-approval-records",
                        "/v1/tickets",
                        "/v1/tickets/{ticket_id}",
                        "/v1/tickets/{ticket_id}/events",
                        "/v1/tickets/{ticket_id}/transitions",
                        "/v1/platform/modules/families/lms/catalog-readiness",
                        "/v1/platform/modules/families/lms/restore-drill-evidence",
                        "/v1/platform/modules/families/lms/tenant-admin-package-approval-gate",
                        "/v1/platform/modules/families/lms/tenant-admin-package-approval-records",
                        "/v1/platform/modules/families/lms/package-installation-readiness",
                        "/v1/platform/modules/families/lms/package-installation-execution-boundary",
                        "/v1/platform/modules/families/lms/package-installation-executor-skeleton",
                        "/v1/platform/modules/families/lms/package-installation-dry-run-plan",
                        "/v1/platform/modules/families/lms/package-installation-dry-run-execution-boundary",
                        "/v1/platform/modules/families/lms/package-installation-dry-run-execution-skeleton",
                        "/v1/platform/modules/families/lms/package-installation-dry-run-executor-implementation-review",
                        "/v1/platform/modules/families/lms/package-installation-dry-run-result-contract",
                        "/v1/platform/modules/families/lms/package-installation-dry-run-execution-gate",
                        "/v1/platform/modules/families/lms/package-installation-dry-run-execution-request-boundary",
                        "/v1/platform/modules/families/lms/package-installation-dry-run-executor-runtime-boundary",
                        "/v1/platform/modules/families/lms/package-installation-dry-run-execution-preflight",
                        "/v1/platform/modules/families/lms/package-installation-dry-run-execution-receipt-boundary",
                        "/v1/platform/modules/families/lms/package-installation-dry-run-result-persistence-boundary",
                        "/v1/platform/modules/families/lms/package-installation-dry-run-execution-activation-boundary",
                        "/v1/platform/modules/families/lms/package-installation-dry-run-execution-start-boundary",
                        "/v1/platform/modules/families/lms/package-installation-dry-run-execution-dispatch-boundary",
                        "/v1/platform/modules/families/lms/package-installation-dry-run-execution-worker-boundary",
                        "/v1/platform/modules/families/lms/package-installation-dry-run-execution-final-readiness-gate",
                        "/v1/platform/modules/families/lms/package-installation-dry-run-execution-approval-boundary",
                        "/v1/platform/modules/families/lms/package-installation-dry-run-execution-approval-records",
                        "/v1/platform/modules/families/lms/package-installation-dry-run-execution-admission-gate",
                        "/v1/platform/modules/families/lms/package-installation-dry-run-execution-runbook",
                        "/v1/platform/modules/families/lms/package-installation-dry-run-execution-plan",
                        "/v1/platform/modules/families/lms/package-installation-dry-run-execution-plan-review",
                        "/v1/platform/modules/families/lms/package-installation-dry-run-execution-scheduler-boundary",
                        "/v1/platform/modules/families/lms/package-installation-dry-run-execution-worker-image-boundary",
                        "/v1/platform/modules/families/lms/package-installation-dry-run-execution-job-outbox",
                        "/v1/platform/modules/families/lms/package-installation-dry-run-execution-job-outbox/leases",
                        "/v1/platform/modules/families/lms/package-installation-dry-run-execution-job-outbox/retries",
                        "/v1/platform/modules/families/lms/package-installation-dry-run-execution-job-outbox/dead-letter-review",
                        "/v1/platform/modules/families/lms/package-installation-dry-run-execution-job-outbox/worker-admission-gate",
                        "/v1/platform/modules/families/lms/package-installation-dry-run-execution-job-outbox/worker-dispatch-admission",
                        "/v1/platform/modules/families/lms/package-installation-dry-run-execution-job-outbox/worker-queue-admission",
                        "/v1/platform/modules/families/lms/package-installation-dry-run-execution-job-outbox/worker-receipts",
                        "/v1/platform/modules/families/lms/package-installation-dry-run-execution-job-outbox/worker-result-stubs",
                        "/v1/platform/modules/families/lms/package-installation-dry-run-execution-job-outbox/result-metadata-records",
                        "/v1/platform/modules/families/lms/package-installation-dry-run-execution-job-outbox/result-read-model",
                        "/v1/platform/modules/families/lms/package-installation-dry-run-execution-job-outbox/result-reconciliation-gate",
                        "/v1/platform/modules/families/lms/package-installation-dry-run-execution-job-outbox/foundation-seal",
                    ),
                    guardrails=(
                        "module_contract_first",
                        "backup_failover_update_required",
                        "tenant_admin_lifecycle",
                        "no_runtime_activation_from_backlog",
                        "module_family_foundation_queue_complete",
                        "tasks_activities_foundation_contract_ready",
                        "tasks_activities_catalog_readiness_ready",
                        "tasks_activities_catalog_package_installed",
                        "tasks_activities_atomic_write_operational",
                        "tasks_activities_authoritative_acl_reads_operational",
                        "tasks_activities_restore_controls_required",
                        "time_tracking_foundation_contract_ready",
                        "time_tracking_catalog_package_installed",
                        "time_tracking_atomic_write_operational",
                        "time_tracking_authoritative_acl_reads_operational",
                        "time_tracking_restore_controls_required",
                        "tickets_incidents_foundation_contract_ready",
                        "tickets_incidents_catalog_readiness_ready",
                        "tickets_incidents_catalog_registered_not_installed",
                        "tickets_incidents_migration_evidence_gate_ready",
                        "tickets_incidents_storage_migration_evidence_ready",
                        "tickets_incidents_metadata_schema_migration_ready",
                        "tickets_incidents_restore_drill_evidence_ready",
                        "tickets_incidents_tenant_admin_activation_approval_gate_ready",
                        "tickets_incidents_tenant_admin_activation_approval_record_ready",
                        "tickets_incidents_activation_execution_boundary_ready",
                        "tickets_incidents_activation_executor_skeleton_ready",
                        "tickets_incidents_activation_dry_run_plan_ready",
                        "tickets_incidents_activation_dry_run_execution_boundary_ready",
                        "tickets_incidents_activation_dry_run_execution_skeleton_ready",
                        "tickets_incidents_activation_dry_run_executor_implementation_review_ready",
                        "tickets_incidents_activation_dry_run_result_contract_ready",
                        "tickets_incidents_activation_dry_run_execution_gate_ready",
                        "tickets_incidents_activation_dry_run_execution_request_boundary_ready",
                        "tickets_incidents_activation_dry_run_executor_runtime_boundary_ready",
                        "tickets_incidents_activation_dry_run_execution_preflight_ready",
                        "tickets_incidents_activation_dry_run_execution_receipt_boundary_ready",
                        "tickets_incidents_activation_dry_run_result_persistence_boundary_ready",
                        "tickets_incidents_activation_dry_run_execution_activation_boundary_ready",
                        "tickets_incidents_activation_dry_run_execution_start_boundary_ready",
                        "tickets_incidents_activation_dry_run_execution_dispatch_boundary_ready",
                        "tickets_incidents_activation_dry_run_execution_worker_boundary_ready",
                        "tickets_incidents_activation_dry_run_execution_final_readiness_gate_ready",
                        "tickets_incidents_activation_dry_run_execution_approval_boundary_ready",
                        "tickets_incidents_activation_dry_run_execution_approval_record_ready",
                        "tickets_incidents_productive_vertical_slice_code_ready",
                        "tickets_incidents_productive_routes_module_and_feature_gated",
                        "tickets_incidents_ticket_event_writes_atomic",
                        "tickets_incidents_persistent_approval_store_ready",
                        "tickets_incidents_two_step_controlled_pilot_ready_not_executed",
                        "tickets_incidents_pilot_receipts_append_only_and_tenant_scoped",
                        "tickets_incidents_admission_fail_closed_disabled",
                        "tickets_incidents_enablement_opens_exactly_four_features",
                        "tickets_incidents_restore_contract_includes_approval_and_pilot_receipts",
                        "lms_readiness_metadata_only",
                        "lms_catalog_registered_not_installed",
                        "lms_package_installation_readiness_blocks_install",
                        "lms_metadata_schema_migration_ready",
                        "lms_restore_drill_evidence_hash_ready",
                        "lms_tenant_admin_approval_gate_ready",
                        "lms_tenant_admin_approval_record_store_ready",
                        "lms_package_installation_execution_boundary_ready",
                        "lms_package_installation_executor_skeleton_ready",
                        "lms_package_installation_dry_run_plan_ready",
                        "lms_package_installation_dry_run_execution_boundary_ready",
                        "lms_package_installation_dry_run_execution_skeleton_ready",
                        "lms_package_installation_dry_run_executor_implementation_review_ready",
                        "lms_package_installation_dry_run_result_contract_ready",
                        "lms_package_installation_dry_run_execution_gate_ready",
                        "lms_package_installation_dry_run_execution_request_boundary_ready",
                        "lms_package_installation_dry_run_executor_runtime_boundary_ready",
                        "lms_package_installation_dry_run_execution_preflight_ready",
                        "lms_package_installation_dry_run_execution_receipt_boundary_ready",
                        "lms_package_installation_dry_run_result_persistence_boundary_ready",
                        "lms_package_installation_dry_run_execution_activation_boundary_ready",
                        "lms_package_installation_dry_run_execution_start_boundary_ready",
                        "lms_package_installation_dry_run_execution_dispatch_boundary_ready",
                        "lms_package_installation_dry_run_execution_worker_boundary_ready",
                        "lms_package_installation_dry_run_execution_final_readiness_gate_ready",
                        "lms_package_installation_dry_run_execution_approval_boundary_ready",
                        "lms_package_installation_dry_run_execution_approval_record_ready",
                        "lms_package_installation_dry_run_execution_admission_gate_ready",
                        "lms_package_installation_dry_run_execution_runbook_ready",
                        "lms_package_installation_dry_run_execution_plan_ready",
                        "lms_package_installation_dry_run_execution_plan_review_ready",
                        "lms_package_installation_dry_run_execution_scheduler_boundary_ready",
                        "lms_package_installation_dry_run_execution_worker_image_boundary_ready",
                        "lms_package_installation_dry_run_execution_job_outbox_ready",
                        "lms_package_installation_dry_run_execution_outbox_lease_consumer_ready",
                        "lms_package_installation_dry_run_execution_outbox_retry_api_ready",
                        "lms_package_installation_dry_run_execution_outbox_dead_letter_review_ready",
                        "lms_package_installation_dry_run_execution_outbox_worker_admission_gate_ready",
                        "lms_package_installation_dry_run_execution_outbox_worker_dispatch_admission_ready",
                        "lms_package_installation_dry_run_execution_outbox_worker_queue_admission_ready",
                        "lms_package_installation_dry_run_execution_outbox_worker_receipt_ready",
                        "lms_package_installation_dry_run_execution_outbox_worker_result_stub_ready",
                        "lms_package_installation_dry_run_execution_outbox_result_metadata_store_ready",
                        "lms_package_installation_dry_run_execution_outbox_result_read_model_ready",
                        "lms_package_installation_dry_run_execution_outbox_result_reconciliation_gate_ready",
                        "lms_package_installation_dry_run_execution_outbox_foundation_seal_ready",
                        "lms_not_installed_until_catalog_and_migration_evidence",
                    ),
                    next_action="execute_controlled_tickets_incidents_pilot_on_designated_test_tenant",
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
