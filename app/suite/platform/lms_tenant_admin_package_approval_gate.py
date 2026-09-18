from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.ai_control_plane.models import UserContext
from suite.persistence.migration_catalog import MigrationManifestEntry
from suite.platform.lms_module import (
    LMS_CONTINUITY_DOMAIN,
    LMS_MODULE_ID,
    build_default_lms_object_rule_manifest,
    build_default_lms_subfeature_registry,
)
from suite.platform.lms_restore_drill_evidence import (
    LMS_CATALOG_REGISTRATION_MIGRATION_VERSION,
    LMS_METADATA_SCHEMA_MIGRATION_VERSION,
    LMS_RESTORE_DRILL_EVIDENCE_ENDPOINT,
    build_lms_restore_drill_evidence_response,
)
from suite.platform.modules import InMemoryModuleRegistry, PgModuleRegistry

LMS_TENANT_ADMIN_PACKAGE_APPROVAL_GATE_SCHEMA_VERSION = "lms_tenant_admin_package_approval_gate.v1"
LMS_TENANT_ADMIN_PACKAGE_APPROVAL_GATE_RESULT_CONTRACT = (
    "metadata_only_lms_tenant_admin_package_approval_gate_no_approval_record"
)
LMS_TENANT_ADMIN_PACKAGE_APPROVAL_GATE_ENDPOINT = "/v1/platform/modules/families/lms/tenant-admin-package-approval-gate"
LMS_TENANT_ADMIN_PACKAGE_APPROVAL_GATE_NEXT_ACTION = (
    "record_tenant_admin_package_install_approval_with_explicit_human_confirmation"
)


class LmsTenantAdminPackageApprovalGateSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lms_manifest_migration_count: int
    required_approval_evidence_count: int
    approval_scope_count: int
    blocking_reason_count: int


class LmsTenantAdminPackageApprovalGateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LMS_TENANT_ADMIN_PACKAGE_APPROVAL_GATE_SCHEMA_VERSION
    tenant_id: str
    module_id: str = LMS_MODULE_ID
    endpoint: str = LMS_TENANT_ADMIN_PACKAGE_APPROVAL_GATE_ENDPOINT
    result_contract: str = LMS_TENANT_ADMIN_PACKAGE_APPROVAL_GATE_RESULT_CONTRACT
    continuity_domain: str = LMS_CONTINUITY_DOMAIN
    catalog_status: str | None
    tenant_module_status: str | None
    module_catalog_entry_present: bool
    module_package_installed: bool
    tenant_module_state_present: bool
    migration_plan_ready: bool
    restore_evidence_ready: bool
    lms_restore_drill_evidence_endpoint: str = LMS_RESTORE_DRILL_EVIDENCE_ENDPOINT
    lms_restore_drill_evidence_hash: str | None
    approval_gate_ready: bool
    human_approval_record_allowed: bool
    human_approval_record_created: bool = False
    human_approval_ready: bool = False
    package_installation_ready: bool = False
    package_installation_executed: bool = False
    module_activation_executed: bool = False
    tenant_provisioning_allowed: bool = False
    migration_execution_allowed: bool = False
    lms_business_api_allowed: bool = False
    persistent_task_created: bool = False
    content_included: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False
    existing_lms_migration_versions: tuple[str, ...]
    approval_scope: tuple[str, ...]
    required_approval_evidence: tuple[str, ...]
    blocking_reasons: tuple[str, ...]
    evidence_hash: str
    summary: LmsTenantAdminPackageApprovalGateSummary
    evidence_refs: tuple[str, ...]
    next_action: str = LMS_TENANT_ADMIN_PACKAGE_APPROVAL_GATE_NEXT_ACTION

    @field_validator(
        "tenant_id",
        "module_id",
        "endpoint",
        "result_contract",
        "continuity_domain",
        "lms_restore_drill_evidence_endpoint",
        "evidence_hash",
        "next_action",
    )
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("LMS tenant-admin package approval gate text fields must not be empty")
        return value

    @field_validator("lms_restore_drill_evidence_hash")
    @classmethod
    def validate_optional_restore_hash(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("sha256:"):
            raise ValueError("LMS tenant-admin package approval gate restore hash must be a sha256 reference")
        return value

    @field_validator("evidence_hash")
    @classmethod
    def validate_evidence_hash(cls, value: str) -> str:
        if not value.startswith("sha256:"):
            raise ValueError("LMS tenant-admin package approval gate hash must be a sha256 reference")
        return value

    @field_validator(
        "existing_lms_migration_versions",
        "approval_scope",
        "required_approval_evidence",
        "evidence_refs",
    )
    @classmethod
    def require_non_empty_unique_lists(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("LMS tenant-admin package approval gate lists must not be empty")
        if len(set(value)) != len(value):
            raise ValueError("LMS tenant-admin package approval gate lists must not contain duplicates")
        for item in value:
            if not item.strip():
                raise ValueError("LMS tenant-admin package approval gate list items must not be empty")
        return value

    @field_validator("blocking_reasons")
    @classmethod
    def require_unique_blocking_reasons(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("LMS tenant-admin package approval gate blocking reasons must not contain duplicates")
        for item in value:
            if not item.strip():
                raise ValueError("LMS tenant-admin package approval gate blocking reasons must not be empty")
        return value

    @model_validator(mode="after")
    def require_metadata_only_approval_gate_contract(self) -> LmsTenantAdminPackageApprovalGateResponse:
        if self.schema_version != LMS_TENANT_ADMIN_PACKAGE_APPROVAL_GATE_SCHEMA_VERSION:
            raise ValueError("LMS tenant-admin package approval gate schema version is invalid")
        if self.endpoint != LMS_TENANT_ADMIN_PACKAGE_APPROVAL_GATE_ENDPOINT:
            raise ValueError("LMS tenant-admin package approval gate endpoint is invalid")
        if self.result_contract != LMS_TENANT_ADMIN_PACKAGE_APPROVAL_GATE_RESULT_CONTRACT:
            raise ValueError("LMS tenant-admin package approval gate result contract is invalid")
        if self.module_id != LMS_MODULE_ID:
            raise ValueError("LMS tenant-admin package approval gate only applies to lms")
        if self.continuity_domain != LMS_CONTINUITY_DOMAIN:
            raise ValueError("LMS tenant-admin package approval gate continuity domain is invalid")
        if self.module_package_installed != (self.catalog_status in {"available", "installed"}):
            raise ValueError("LMS tenant-admin package approval gate package flag must match catalog status")
        if self.restore_evidence_ready and self.lms_restore_drill_evidence_hash is None:
            raise ValueError("ready LMS approval gate requires restore evidence hash")
        expected_gate_ready = (
            self.catalog_status == "not_installed"
            and not self.tenant_module_state_present
            and self.migration_plan_ready
            and self.restore_evidence_ready
            and not self.module_package_installed
            and not self.blocking_reasons
        )
        if self.approval_gate_ready != expected_gate_ready:
            raise ValueError("LMS tenant-admin package approval gate readiness must match prerequisites")
        if self.human_approval_record_allowed != self.approval_gate_ready:
            raise ValueError("LMS human approval record allowance must match approval gate readiness")
        if (
            self.human_approval_record_created
            or self.human_approval_ready
            or self.package_installation_ready
            or self.package_installation_executed
            or self.module_activation_executed
            or self.tenant_provisioning_allowed
            or self.migration_execution_allowed
            or self.lms_business_api_allowed
            or self.persistent_task_created
            or self.content_included
            or self.destructive_actions_allowed
            or self.external_side_effect_allowed
        ):
            raise ValueError("LMS tenant-admin package approval gate must remain non-executing")
        if self.summary.lms_manifest_migration_count != len(self.existing_lms_migration_versions):
            raise ValueError("LMS approval gate migration count must match migration versions")
        if self.summary.required_approval_evidence_count != len(self.required_approval_evidence):
            raise ValueError("LMS approval gate evidence count must match required evidence")
        if self.summary.approval_scope_count != len(self.approval_scope):
            raise ValueError("LMS approval gate scope count must match approval scope")
        if self.summary.blocking_reason_count != len(self.blocking_reasons):
            raise ValueError("LMS approval gate blocking count must match blocking reasons")
        return self


def build_lms_tenant_admin_package_approval_gate_response(
    *,
    user_context: UserContext,
    module_registry: InMemoryModuleRegistry | PgModuleRegistry,
    migration_manifest_entries: Iterable[MigrationManifestEntry],
) -> LmsTenantAdminPackageApprovalGateResponse:
    feature_registry = build_default_lms_subfeature_registry()
    object_rule_manifest = build_default_lms_object_rule_manifest()
    object_rule_manifest.validate_subfeature_registry(feature_registry)

    catalog_status = _catalog_status(module_registry=module_registry)
    tenant_module_status = _tenant_module_status(
        module_registry=module_registry,
        tenant_id=user_context.tenant_id,
        catalog_known=catalog_status is not None,
    )
    lms_migration_versions = _lms_migration_versions(migration_manifest_entries)
    migration_plan_ready = {
        LMS_CATALOG_REGISTRATION_MIGRATION_VERSION,
        LMS_METADATA_SCHEMA_MIGRATION_VERSION,
    }.issubset(set(lms_migration_versions))
    restore_drill_evidence = build_lms_restore_drill_evidence_response(
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest_entries,
    )
    blocking_reasons = _blocking_reasons(
        catalog_status=catalog_status,
        tenant_module_status=tenant_module_status,
        migration_plan_ready=migration_plan_ready,
        restore_evidence_ready=restore_drill_evidence.restore_evidence_ready,
    )
    approval_scope = (
        "install_lms_package_for_tenant",
        "bind_lms_migrations_0045_0046_0047_0048",
        "bind_lms_restore_drill_evidence_hash",
        "keep_lms_business_api_disabled_until_tenant_provisioning",
        "no_content_payload_or_worker_activation",
    )
    required_approval_evidence = (
        "tenant_admin_identity",
        "tenant_admin_role_membership",
        "restore_drill_evidence_hash",
        "lms_migration_manifest_versions",
        "change_request_reference",
        "no_lms_installation_execution_confirmation",
        "no_lms_tenant_module_state_confirmation",
        "future_installation_execution_gate_required",
    )
    approval_gate_ready = not blocking_reasons
    draft = LmsTenantAdminPackageApprovalGateResponse(
        tenant_id=user_context.tenant_id,
        catalog_status=catalog_status,
        tenant_module_status=tenant_module_status,
        module_catalog_entry_present=catalog_status is not None,
        module_package_installed=catalog_status in {"available", "installed"},
        tenant_module_state_present=tenant_module_status is not None,
        migration_plan_ready=migration_plan_ready,
        restore_evidence_ready=restore_drill_evidence.restore_evidence_ready,
        lms_restore_drill_evidence_hash=restore_drill_evidence.evidence_hash,
        approval_gate_ready=approval_gate_ready,
        human_approval_record_allowed=approval_gate_ready,
        existing_lms_migration_versions=lms_migration_versions,
        approval_scope=approval_scope,
        required_approval_evidence=required_approval_evidence,
        blocking_reasons=blocking_reasons,
        evidence_hash="sha256:pending",
        summary=LmsTenantAdminPackageApprovalGateSummary(
            lms_manifest_migration_count=len(lms_migration_versions),
            required_approval_evidence_count=len(required_approval_evidence),
            approval_scope_count=len(approval_scope),
            blocking_reason_count=len(blocking_reasons),
        ),
        evidence_refs=(
            "docs/modules/LMS_MODULE_CHARTER.md",
            "docs/modules/MODULE_IMPLEMENTATION_CONTRACT.md",
            "app/suite/platform/lms_tenant_admin_package_approval_gate.py",
            "app/suite/platform/lms_restore_drill_evidence.py",
            "app/suite/platform/lms_package_installation_readiness.py",
            "tests/test_lms_tenant_admin_package_approval_gate.py",
            "tests/test_lms_package_installation_readiness.py",
        ),
    )
    return draft.model_copy(update={"evidence_hash": build_lms_tenant_admin_package_approval_gate_hash(draft)})


def build_lms_tenant_admin_package_approval_gate_hash(
    response: LmsTenantAdminPackageApprovalGateResponse,
) -> str:
    return stable_hash(canonical_json(response.model_dump(mode="json", exclude={"evidence_hash"})))


def _catalog_status(*, module_registry: InMemoryModuleRegistry | PgModuleRegistry) -> str | None:
    try:
        return module_registry.get_catalog_entry(LMS_MODULE_ID).status.value
    except LookupError:
        return None


def _tenant_module_status(
    *,
    module_registry: InMemoryModuleRegistry | PgModuleRegistry,
    tenant_id: str,
    catalog_known: bool,
) -> str | None:
    if not catalog_known:
        return None
    state = module_registry.get_tenant_module_or_none(tenant_id=tenant_id, module_id=LMS_MODULE_ID)
    return state.status.value if state is not None else None


def _lms_migration_versions(
    migration_manifest_entries: Iterable[MigrationManifestEntry],
) -> tuple[str, ...]:
    return tuple(sorted(entry.version for entry in migration_manifest_entries if entry.module_id == LMS_MODULE_ID))


def _blocking_reasons(
    *,
    catalog_status: str | None,
    tenant_module_status: str | None,
    migration_plan_ready: bool,
    restore_evidence_ready: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if catalog_status is None:
        reasons.append("lms_catalog_entry_missing")
    elif catalog_status != "not_installed":
        reasons.append("lms_catalog_status_not_approval_eligible")
    if tenant_module_status is not None:
        reasons.append("tenant_module_state_already_exists")
    if not migration_plan_ready:
        reasons.append("lms_migration_plan_missing")
    if not restore_evidence_ready:
        reasons.append("lms_restore_drill_evidence_missing")
    return tuple(reasons)
