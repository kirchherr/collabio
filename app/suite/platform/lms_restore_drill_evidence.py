from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.ai_control_plane.models import UserContext
from suite.persistence.migration_catalog import MigrationManifestEntry, get_migration
from suite.platform.lms_module import (
    LMS_CONTINUITY_DOMAIN,
    LMS_MODULE_ID,
    build_default_lms_object_rule_manifest,
    build_default_lms_subfeature_registry,
)
from suite.platform.modules import InMemoryModuleRegistry, PgModuleRegistry

LMS_RESTORE_DRILL_EVIDENCE_SCHEMA_VERSION = "lms_restore_drill_evidence.v1"
LMS_RESTORE_DRILL_EVIDENCE_RESULT_CONTRACT = "metadata_only_lms_restore_drill_evidence_no_install"
LMS_RESTORE_DRILL_EVIDENCE_ENDPOINT = "/v1/platform/modules/families/lms/restore-drill-evidence"
LMS_CATALOG_REGISTRATION_MIGRATION_VERSION = "0045"
LMS_METADATA_SCHEMA_MIGRATION_VERSION = "0046"
LMS_RESTORE_DRILL_NEXT_ACTION = "capture_tenant_admin_package_install_approval"


class LmsRestoreDrillEvidenceSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lms_manifest_migration_count: int
    restored_table_count: int
    restored_object_type_count: int
    required_restore_evidence_count: int
    blocking_reason_count: int


class LmsRestoreDrillEvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LMS_RESTORE_DRILL_EVIDENCE_SCHEMA_VERSION
    tenant_id: str
    module_id: str = LMS_MODULE_ID
    endpoint: str = LMS_RESTORE_DRILL_EVIDENCE_ENDPOINT
    result_contract: str = LMS_RESTORE_DRILL_EVIDENCE_RESULT_CONTRACT
    continuity_domain: str = LMS_CONTINUITY_DOMAIN
    catalog_status: str | None
    tenant_module_status: str | None
    module_catalog_entry_present: bool
    module_package_installed: bool
    tenant_module_state_present: bool
    migration_plan_ready: bool
    catalog_registration_migration_present: bool
    metadata_schema_migration_present: bool
    table_restore_verified: bool
    rls_restore_verified: bool
    tenant_isolation_restore_verified: bool
    retention_restore_verified: bool
    legal_hold_restore_verified: bool
    kms_reference_restore_verified: bool
    audit_reference_restore_verified: bool
    no_content_payload_restore_verified: bool
    restore_evidence_ready: bool
    package_installation_executed: bool = False
    module_activation_executed: bool = False
    persistent_task_created: bool = False
    content_included: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False
    existing_lms_migration_versions: tuple[str, ...]
    restored_tables: tuple[str, ...]
    restored_object_types: tuple[str, ...]
    required_restore_evidence: tuple[str, ...]
    blocking_reasons: tuple[str, ...]
    evidence_hash: str
    summary: LmsRestoreDrillEvidenceSummary
    evidence_refs: tuple[str, ...]
    next_action: str = LMS_RESTORE_DRILL_NEXT_ACTION

    @field_validator(
        "tenant_id",
        "module_id",
        "endpoint",
        "result_contract",
        "continuity_domain",
        "evidence_hash",
        "next_action",
    )
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("LMS restore drill evidence text fields must not be empty")
        return value

    @field_validator("evidence_hash")
    @classmethod
    def require_hash_reference(cls, value: str) -> str:
        if not value.startswith("sha256:"):
            raise ValueError("LMS restore drill evidence hash must be a sha256 reference")
        return value

    @field_validator(
        "existing_lms_migration_versions",
        "restored_tables",
        "restored_object_types",
        "required_restore_evidence",
        "evidence_refs",
    )
    @classmethod
    def require_non_empty_unique_lists(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("LMS restore drill evidence lists must not be empty")
        if len(set(value)) != len(value):
            raise ValueError("LMS restore drill evidence lists must not contain duplicates")
        for item in value:
            if not item.strip():
                raise ValueError("LMS restore drill evidence list items must not be empty")
        return value

    @field_validator("blocking_reasons")
    @classmethod
    def require_unique_blocking_reasons(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("LMS restore drill blocking reasons must not contain duplicates")
        for item in value:
            if not item.strip():
                raise ValueError("LMS restore drill blocking reasons must not be empty")
        return value

    @model_validator(mode="after")
    def require_metadata_only_restore_contract(self) -> LmsRestoreDrillEvidenceResponse:
        if self.schema_version != LMS_RESTORE_DRILL_EVIDENCE_SCHEMA_VERSION:
            raise ValueError("LMS restore drill evidence schema version is invalid")
        if self.endpoint != LMS_RESTORE_DRILL_EVIDENCE_ENDPOINT:
            raise ValueError("LMS restore drill evidence endpoint is invalid")
        if self.result_contract != LMS_RESTORE_DRILL_EVIDENCE_RESULT_CONTRACT:
            raise ValueError("LMS restore drill evidence result contract is invalid")
        if self.module_id != LMS_MODULE_ID:
            raise ValueError("LMS restore drill evidence only applies to lms")
        if self.continuity_domain != LMS_CONTINUITY_DOMAIN:
            raise ValueError("LMS restore drill evidence continuity domain is invalid")
        if self.module_package_installed != (self.catalog_status in {"available", "installed"}):
            raise ValueError("LMS restore drill package flag must match catalog status")
        expected_ready = (
            self.catalog_status == "not_installed"
            and not self.tenant_module_state_present
            and self.migration_plan_ready
            and self.catalog_registration_migration_present
            and self.metadata_schema_migration_present
            and self.table_restore_verified
            and self.rls_restore_verified
            and self.tenant_isolation_restore_verified
            and self.retention_restore_verified
            and self.legal_hold_restore_verified
            and self.kms_reference_restore_verified
            and self.audit_reference_restore_verified
            and self.no_content_payload_restore_verified
            and not self.blocking_reasons
        )
        if self.restore_evidence_ready != expected_ready:
            raise ValueError("LMS restore drill evidence readiness must match restore checks")
        if (
            self.package_installation_executed
            or self.module_activation_executed
            or self.persistent_task_created
            or self.content_included
            or self.destructive_actions_allowed
            or self.external_side_effect_allowed
        ):
            raise ValueError("LMS restore drill evidence must remain metadata-only and non-executing")
        if self.summary.lms_manifest_migration_count != len(self.existing_lms_migration_versions):
            raise ValueError("LMS restore drill migration count must match migration versions")
        if self.summary.restored_table_count != len(self.restored_tables):
            raise ValueError("LMS restore drill table count must match restored tables")
        if self.summary.restored_object_type_count != len(self.restored_object_types):
            raise ValueError("LMS restore drill object count must match restored object types")
        if self.summary.required_restore_evidence_count != len(self.required_restore_evidence):
            raise ValueError("LMS restore drill evidence count must match required evidence")
        if self.summary.blocking_reason_count != len(self.blocking_reasons):
            raise ValueError("LMS restore drill blocking count must match blocking reasons")
        return self


def build_lms_restore_drill_evidence_response(
    *,
    user_context: UserContext,
    module_registry: InMemoryModuleRegistry | PgModuleRegistry,
    migration_manifest_entries: Iterable[MigrationManifestEntry],
) -> LmsRestoreDrillEvidenceResponse:
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
    catalog_migration_present = LMS_CATALOG_REGISTRATION_MIGRATION_VERSION in lms_migration_versions
    metadata_migration_present = LMS_METADATA_SCHEMA_MIGRATION_VERSION in lms_migration_versions
    sql_checks = _metadata_schema_sql_checks()
    migration_plan_ready = catalog_migration_present and metadata_migration_present
    blocking_reasons = _blocking_reasons(
        catalog_status=catalog_status,
        tenant_module_status=tenant_module_status,
        migration_plan_ready=migration_plan_ready,
        sql_checks=sql_checks,
    )
    restored_tables = ("lms.courses", "lms.enrollments")
    restored_object_types = ("lms.course", "lms.enrollment")
    required_restore_evidence = (
        "lms_catalog_registration_migration_0045",
        "lms_metadata_schema_migration_0046",
        "lms_course_enrollment_table_restore_check",
        "lms_rls_tenant_policy_restore_check",
        "lms_retention_legal_hold_restore_check",
        "lms_kms_audit_reference_restore_check",
        "no_lms_content_payload_restore_confirmed",
        "no_lms_package_or_tenant_activation_confirmed",
    )
    draft = LmsRestoreDrillEvidenceResponse(
        tenant_id=user_context.tenant_id,
        catalog_status=catalog_status,
        tenant_module_status=tenant_module_status,
        module_catalog_entry_present=catalog_status is not None,
        module_package_installed=catalog_status in {"available", "installed"},
        tenant_module_state_present=tenant_module_status is not None,
        migration_plan_ready=migration_plan_ready,
        catalog_registration_migration_present=catalog_migration_present,
        metadata_schema_migration_present=metadata_migration_present,
        table_restore_verified=sql_checks.table_restore_verified,
        rls_restore_verified=sql_checks.rls_restore_verified,
        tenant_isolation_restore_verified=sql_checks.tenant_isolation_restore_verified,
        retention_restore_verified=sql_checks.retention_restore_verified,
        legal_hold_restore_verified=sql_checks.legal_hold_restore_verified,
        kms_reference_restore_verified=sql_checks.kms_reference_restore_verified,
        audit_reference_restore_verified=sql_checks.audit_reference_restore_verified,
        no_content_payload_restore_verified=sql_checks.no_content_payload_restore_verified,
        restore_evidence_ready=not blocking_reasons,
        existing_lms_migration_versions=lms_migration_versions,
        restored_tables=restored_tables,
        restored_object_types=restored_object_types,
        required_restore_evidence=required_restore_evidence,
        blocking_reasons=blocking_reasons,
        evidence_hash="sha256:pending",
        summary=LmsRestoreDrillEvidenceSummary(
            lms_manifest_migration_count=len(lms_migration_versions),
            restored_table_count=len(restored_tables),
            restored_object_type_count=len(restored_object_types),
            required_restore_evidence_count=len(required_restore_evidence),
            blocking_reason_count=len(blocking_reasons),
        ),
        evidence_refs=(
            "docs/operations/BACKUP_FAILOVER.md",
            "docs/operations/backup_failover_policy.json",
            "docs/modules/LMS_MODULE_CHARTER.md",
            "app/suite/platform/lms_restore_drill_evidence.py",
            "app/suite/persistence/migrations/0045_lms_catalog_registration.sql",
            "app/suite/persistence/migrations/0046_lms_metadata_schema.sql",
            "tests/test_lms_restore_drill_evidence.py",
            "tests/test_pgvector_migration.py",
        ),
    )
    return draft.model_copy(update={"evidence_hash": build_lms_restore_drill_evidence_hash(draft)})


def build_lms_restore_drill_evidence_hash(response: LmsRestoreDrillEvidenceResponse) -> str:
    return stable_hash(canonical_json(response.model_dump(mode="json", exclude={"evidence_hash"})))


@dataclass(frozen=True)
class _MetadataSchemaSqlChecks:
    table_restore_verified: bool
    rls_restore_verified: bool
    tenant_isolation_restore_verified: bool
    retention_restore_verified: bool
    legal_hold_restore_verified: bool
    kms_reference_restore_verified: bool
    audit_reference_restore_verified: bool
    no_content_payload_restore_verified: bool


def _metadata_schema_sql_checks() -> _MetadataSchemaSqlChecks:
    sql = " ".join(get_migration(LMS_METADATA_SCHEMA_MIGRATION_VERSION).sql().lower().split())
    table_restore_verified = (
        "create table if not exists lms.courses" in sql and "create table if not exists lms.enrollments" in sql
    )
    rls_restore_verified = (
        "alter table lms.courses enable row level security" in sql
        and "alter table lms.courses force row level security" in sql
        and "alter table lms.enrollments enable row level security" in sql
        and "alter table lms.enrollments force row level security" in sql
        and "create policy lms_courses_tenant_select" in sql
        and "create policy lms_enrollments_tenant_select" in sql
    )
    tenant_isolation_restore_verified = "tenant_id = collabio.current_tenant_id()" in sql
    retention_restore_verified = "retention_policy_id text not null default 'rp-standard'" in sql
    legal_hold_restore_verified = "legal_hold_state text not null default 'none'" in sql
    kms_reference_restore_verified = "kms_key_ref text not null check" in sql
    audit_reference_restore_verified = "audit_chain_ref text not null check" in sql
    no_content_payload_restore_verified = all(
        forbidden not in sql
        for forbidden in (
            "course_content",
            "source_text",
            "raw_audio",
            "prompt",
            "ai_output",
        )
    )
    return _MetadataSchemaSqlChecks(
        table_restore_verified=table_restore_verified,
        rls_restore_verified=rls_restore_verified,
        tenant_isolation_restore_verified=tenant_isolation_restore_verified,
        retention_restore_verified=retention_restore_verified,
        legal_hold_restore_verified=legal_hold_restore_verified,
        kms_reference_restore_verified=kms_reference_restore_verified,
        audit_reference_restore_verified=audit_reference_restore_verified,
        no_content_payload_restore_verified=no_content_payload_restore_verified,
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
    migration_plan_ready: bool,
    sql_checks: _MetadataSchemaSqlChecks,
) -> tuple[str, ...]:
    reasons: list[str] = []
    if catalog_status is None:
        reasons.append("lms_catalog_entry_missing")
    elif catalog_status != "not_installed":
        reasons.append("lms_catalog_status_not_installable_for_restore_drill")
    if tenant_module_status is not None:
        reasons.append("tenant_module_state_already_exists")
    if not migration_plan_ready:
        reasons.append("lms_migration_plan_missing")
    if not sql_checks.table_restore_verified:
        reasons.append("lms_course_enrollment_table_restore_unverified")
    if not sql_checks.rls_restore_verified or not sql_checks.tenant_isolation_restore_verified:
        reasons.append("lms_tenant_rls_restore_unverified")
    if not sql_checks.retention_restore_verified or not sql_checks.legal_hold_restore_verified:
        reasons.append("lms_retention_legal_hold_restore_unverified")
    if not sql_checks.kms_reference_restore_verified or not sql_checks.audit_reference_restore_verified:
        reasons.append("lms_kms_audit_restore_unverified")
    if not sql_checks.no_content_payload_restore_verified:
        reasons.append("lms_content_payload_restore_boundary_failed")
    return tuple(reasons)
