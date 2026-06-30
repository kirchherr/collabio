from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.models import UserContext
from suite.persistence.migration_catalog import MigrationManifestEntry
from suite.platform.lms_module import (
    LMS_CONTINUITY_DOMAIN,
    LMS_MODULE_ID,
    build_default_lms_object_rule_manifest,
    build_default_lms_subfeature_registry,
)
from suite.platform.lms_restore_drill_evidence import (
    LMS_RESTORE_DRILL_EVIDENCE_ENDPOINT,
    build_lms_restore_drill_evidence_response,
)
from suite.platform.modules import InMemoryModuleRegistry, PgModuleRegistry

LMS_PACKAGE_INSTALLATION_READINESS_SCHEMA_VERSION = "lms_package_installation_readiness.v1"
LMS_PACKAGE_INSTALLATION_READINESS_RESULT_CONTRACT = "metadata_only_lms_package_installation_readiness_no_install"
LMS_PACKAGE_INSTALLATION_READINESS_ENDPOINT = "/v1/platform/modules/families/lms/package-installation-readiness"
LMS_CATALOG_REGISTRATION_MIGRATION_VERSION = "0045"
LMS_METADATA_MIGRATION_NEXT_ACTION = "write_lms_metadata_schema_migration_before_package_installation"
LMS_RESTORE_EVIDENCE_NEXT_ACTION = "capture_lms_restore_drill_evidence_before_package_installation"
LMS_APPROVAL_NEXT_ACTION = "capture_tenant_admin_package_install_approval"
LMS_INSTALL_REVIEW_NEXT_ACTION = "review_lms_package_installation_execution_boundary"


class LmsPackageInstallationSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lms_manifest_migration_count: int
    lms_business_migration_count: int
    planned_first_object_type_count: int
    required_installation_evidence_count: int
    blocking_reason_count: int


class LmsPackageInstallationReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LMS_PACKAGE_INSTALLATION_READINESS_SCHEMA_VERSION
    tenant_id: str
    module_id: str = LMS_MODULE_ID
    endpoint: str = LMS_PACKAGE_INSTALLATION_READINESS_ENDPOINT
    result_contract: str = LMS_PACKAGE_INSTALLATION_READINESS_RESULT_CONTRACT
    continuity_domain: str = LMS_CONTINUITY_DOMAIN
    catalog_status: str | None
    tenant_module_status: str | None
    module_catalog_entry_present: bool
    module_package_installed: bool
    tenant_module_state_present: bool
    package_installation_ready: bool
    migration_plan_ready: bool
    restore_evidence_ready: bool = False
    human_approval_ready: bool = False
    tenant_provisioning_allowed: bool = False
    migration_execution_allowed: bool = False
    lms_business_api_allowed: bool = False
    content_included: bool = False
    package_installation_executed: bool = False
    module_activation_executed: bool = False
    persistent_task_created: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False
    existing_lms_migration_versions: tuple[str, ...]
    existing_lms_business_migration_versions: tuple[str, ...]
    lms_restore_drill_evidence_endpoint: str = LMS_RESTORE_DRILL_EVIDENCE_ENDPOINT
    lms_restore_drill_evidence_hash: str | None
    planned_first_object_types: tuple[str, ...]
    required_installation_evidence: tuple[str, ...]
    blocking_reasons: tuple[str, ...]
    summary: LmsPackageInstallationSummary
    evidence_refs: tuple[str, ...]
    next_action: str

    @field_validator(
        "tenant_id",
        "module_id",
        "endpoint",
        "result_contract",
        "continuity_domain",
        "lms_restore_drill_evidence_endpoint",
        "next_action",
    )
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("LMS package installation readiness text fields must not be empty")
        return value

    @field_validator("lms_restore_drill_evidence_hash")
    @classmethod
    def validate_optional_restore_evidence_hash(cls, value: str | None) -> str | None:
        if value is not None and not value.startswith("sha256:"):
            raise ValueError("LMS restore drill evidence hash must be a sha256 reference")
        return value

    @field_validator(
        "existing_lms_migration_versions",
        "existing_lms_business_migration_versions",
        "planned_first_object_types",
        "required_installation_evidence",
        "blocking_reasons",
        "evidence_refs",
    )
    @classmethod
    def require_non_empty_lists_except_business_migrations(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("LMS package installation readiness lists must not contain duplicates")
        for item in value:
            if not item.strip():
                raise ValueError("LMS package installation readiness list items must not be empty")
        return value

    @model_validator(mode="after")
    def require_metadata_only_contract(self) -> LmsPackageInstallationReadinessResponse:
        if self.schema_version != LMS_PACKAGE_INSTALLATION_READINESS_SCHEMA_VERSION:
            raise ValueError("LMS package installation readiness schema version is invalid")
        if self.endpoint != LMS_PACKAGE_INSTALLATION_READINESS_ENDPOINT:
            raise ValueError("LMS package installation readiness endpoint is invalid")
        if self.result_contract != LMS_PACKAGE_INSTALLATION_READINESS_RESULT_CONTRACT:
            raise ValueError("LMS package installation readiness result contract is invalid")
        if self.module_id != LMS_MODULE_ID:
            raise ValueError("LMS package installation readiness only applies to lms")
        if self.continuity_domain != LMS_CONTINUITY_DOMAIN:
            raise ValueError("LMS package installation readiness continuity domain is invalid")
        if self.module_package_installed != (self.catalog_status in {"available", "installed"}):
            raise ValueError("LMS package installed flag must match catalog status")
        if self.migration_plan_ready != bool(self.existing_lms_business_migration_versions):
            raise ValueError("LMS migration plan readiness must match business migration evidence")
        if self.restore_evidence_ready and self.lms_restore_drill_evidence_hash is None:
            raise ValueError("ready LMS restore evidence requires a restore evidence hash")
        expected_ready = (
            self.catalog_status == "not_installed"
            and self.migration_plan_ready
            and self.restore_evidence_ready
            and self.human_approval_ready
            and not self.tenant_module_state_present
            and not self.module_package_installed
        )
        if self.package_installation_ready != expected_ready:
            raise ValueError("LMS package installation readiness must match required gates")
        if self.package_installation_ready and self.blocking_reasons:
            raise ValueError("ready LMS package installation cannot have blocking reasons")
        if (
            self.tenant_provisioning_allowed
            or self.migration_execution_allowed
            or self.lms_business_api_allowed
            or self.content_included
            or self.package_installation_executed
            or self.module_activation_executed
            or self.persistent_task_created
            or self.destructive_actions_allowed
            or self.external_side_effect_allowed
        ):
            raise ValueError("LMS package installation readiness must remain metadata-only and non-executing")
        if self.summary.lms_manifest_migration_count != len(self.existing_lms_migration_versions):
            raise ValueError("LMS migration count must match migration version list")
        if self.summary.lms_business_migration_count != len(self.existing_lms_business_migration_versions):
            raise ValueError("LMS business migration count must match business migration list")
        if self.summary.planned_first_object_type_count != len(self.planned_first_object_types):
            raise ValueError("LMS planned object count must match planned object list")
        if self.summary.required_installation_evidence_count != len(self.required_installation_evidence):
            raise ValueError("LMS evidence count must match evidence list")
        if self.summary.blocking_reason_count != len(self.blocking_reasons):
            raise ValueError("LMS blocking reason count must match blocking reason list")
        return self


def build_lms_package_installation_readiness_response(
    *,
    user_context: UserContext,
    module_registry: InMemoryModuleRegistry | PgModuleRegistry,
    migration_manifest_entries: Iterable[MigrationManifestEntry],
) -> LmsPackageInstallationReadinessResponse:
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
    business_migration_versions = tuple(
        version for version in lms_migration_versions if version != LMS_CATALOG_REGISTRATION_MIGRATION_VERSION
    )
    restore_drill_evidence = build_lms_restore_drill_evidence_response(
        user_context=user_context,
        module_registry=module_registry,
        migration_manifest_entries=migration_manifest_entries,
    )
    required_installation_evidence = (
        "lms_metadata_schema_migration_sql",
        "lms_object_table_rls_policy_tests",
        "lms_restore_drill_evidence_hash",
        "lms_module_catalog_status_update_plan",
        "tenant_admin_package_install_approval",
        "no_lms_business_runtime_confirmation",
    )
    blocking_reasons = _blocking_reasons(
        catalog_status=catalog_status,
        tenant_module_status=tenant_module_status,
        business_migration_versions=business_migration_versions,
        restore_evidence_ready=restore_drill_evidence.restore_evidence_ready,
    )
    planned_first_object_types = ("lms.course", "lms.enrollment")
    return LmsPackageInstallationReadinessResponse(
        tenant_id=user_context.tenant_id,
        catalog_status=catalog_status,
        tenant_module_status=tenant_module_status,
        module_catalog_entry_present=catalog_status is not None,
        module_package_installed=catalog_status in {"available", "installed"},
        tenant_module_state_present=tenant_module_status is not None,
        package_installation_ready=False,
        migration_plan_ready=bool(business_migration_versions),
        restore_evidence_ready=restore_drill_evidence.restore_evidence_ready,
        lms_restore_drill_evidence_hash=restore_drill_evidence.evidence_hash,
        existing_lms_migration_versions=lms_migration_versions,
        existing_lms_business_migration_versions=business_migration_versions,
        planned_first_object_types=planned_first_object_types,
        required_installation_evidence=required_installation_evidence,
        blocking_reasons=blocking_reasons,
        summary=LmsPackageInstallationSummary(
            lms_manifest_migration_count=len(lms_migration_versions),
            lms_business_migration_count=len(business_migration_versions),
            planned_first_object_type_count=len(planned_first_object_types),
            required_installation_evidence_count=len(required_installation_evidence),
            blocking_reason_count=len(blocking_reasons),
        ),
        next_action=_next_action(
            migration_plan_ready=bool(business_migration_versions),
            restore_evidence_ready=restore_drill_evidence.restore_evidence_ready,
            human_approval_ready=False,
        ),
        evidence_refs=(
            "docs/modules/LMS_MODULE_CHARTER.md",
            "app/suite/platform/lms_module.py",
            "app/suite/platform/lms_package_installation_readiness.py",
            "app/suite/platform/lms_restore_drill_evidence.py",
            "app/suite/persistence/migrations/0045_lms_catalog_registration.sql",
            "app/suite/persistence/migrations/0046_lms_metadata_schema.sql",
            "docs/operations/BACKUP_FAILOVER.md",
            "tests/test_lms_package_installation_readiness.py",
            "tests/test_lms_restore_drill_evidence.py",
            "tests/test_pgvector_migration.py",
        ),
    )


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
    business_migration_versions: tuple[str, ...],
    restore_evidence_ready: bool,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if catalog_status is None:
        reasons.append("lms_catalog_entry_missing")
    elif catalog_status != "not_installed":
        reasons.append("lms_catalog_status_not_installable")
    if tenant_module_status is not None:
        reasons.append("tenant_module_state_already_exists")
    if not business_migration_versions:
        reasons.append("lms_business_metadata_migration_missing")
    if not restore_evidence_ready:
        reasons.append("lms_backup_restore_drill_evidence_missing")
    reasons.append("tenant_admin_package_install_approval_missing")
    return tuple(reasons)


def _next_action(
    *,
    migration_plan_ready: bool,
    restore_evidence_ready: bool,
    human_approval_ready: bool,
) -> str:
    if not migration_plan_ready:
        return LMS_METADATA_MIGRATION_NEXT_ACTION
    if not restore_evidence_ready:
        return LMS_RESTORE_EVIDENCE_NEXT_ACTION
    if not human_approval_ready:
        return LMS_APPROVAL_NEXT_ACTION
    return LMS_INSTALL_REVIEW_NEXT_ACTION
