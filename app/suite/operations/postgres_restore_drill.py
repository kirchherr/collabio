from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict
from psycopg.rows import dict_row
from pydantic import BaseModel, Field

from suite.persistence.migration_catalog import load_migrations
from suite.storage.source_objects import sha256_bytes

SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
SERVICE_ROLES = {
    "collabio_app",
    "collabio_audit_writer",
    "collabio_authz_admin",
    "collabio_worker",
}
TENANT_IAM_TABLES = {
    "collabio.abac_policy_bindings",
    "collabio.object_acl_entries",
    "collabio.tenant_groups",
    "collabio.tenant_principal_group_memberships",
    "collabio.tenant_principal_memberships",
    "collabio.tenant_principal_role_assignments",
    "collabio.tenant_principals",
    "collabio.tenant_roles",
}
AUDIT_TABLES = {
    "collabio.audit_checkpoints",
    "collabio.audit_events",
    "collabio.audit_worm_exports",
}
AUDIT_APPEND_ONLY_POLICIES_BY_TABLE = {
    "collabio.audit_checkpoints": {
        "audit_checkpoints_no_hard_delete",
        "audit_checkpoints_no_update",
    },
    "collabio.audit_events": {
        "audit_events_no_hard_delete",
        "audit_events_no_update",
    },
    "collabio.audit_worm_exports": {
        "audit_worm_exports_no_hard_delete",
        "audit_worm_exports_no_update",
    },
}
AUDIT_APPEND_ONLY_POLICIES = {
    policy_name for policy_names in AUDIT_APPEND_ONLY_POLICIES_BY_TABLE.values() for policy_name in policy_names
}
MODULE_REGISTRY_TABLES = {"collabio.module_catalog", "collabio.tenant_modules"}
SOURCE_OBJECT_TABLES = {
    "collabio.source_object_metadata",
    "collabio.source_object_storage_manifests",
    "collabio.source_object_write_receipts",
}
CRM_ATOMIC_WRITE_TABLES = {
    "crm.accounts",
    "crm.contacts",
    "crm.activities",
    "crm.notes",
    "crm.account_onboarding_receipts",
}
CRM_ATOMIC_RECEIPT_POLICIES = {
    "crm_account_onboarding_receipts_no_update",
    "crm_account_onboarding_receipts_no_hard_delete",
}
TASKS_ACTIVITIES_WRITE_TABLES = {
    "tasks.items",
    "tasks.activities",
    "tasks.creation_receipts",
}
TASKS_ACTIVITIES_APPEND_ONLY_POLICIES_BY_TABLE = {
    "tasks.items": {"tasks_items_no_update", "tasks_items_no_hard_delete"},
    "tasks.activities": {
        "tasks_activities_no_update",
        "tasks_activities_no_hard_delete",
    },
    "tasks.creation_receipts": {
        "tasks_creation_receipts_no_update",
        "tasks_creation_receipts_no_hard_delete",
    },
}
TIME_TRACKING_WRITE_TABLES = {
    "time_tracking.entries",
    "time_tracking.approvals",
    "time_tracking.entry_creation_receipts",
}
TIME_TRACKING_APPEND_ONLY_POLICIES_BY_TABLE = {
    "time_tracking.entries": {"time_entries_no_update", "time_entries_no_hard_delete"},
    "time_tracking.approvals": {"time_approvals_no_update", "time_approvals_no_hard_delete"},
    "time_tracking.entry_creation_receipts": {
        "time_entry_receipts_no_update",
        "time_entry_receipts_no_hard_delete",
    },
}
PRODUCTIVITY_PILOT_CONTROL_TABLES = {
    "collabio.productivity_pilot_preflight_reports",
    "collabio.productivity_pilot_admission_records",
    "collabio.productivity_pilot_real_user_nominations",
    "collabio.productivity_pilot_real_user_admissions",
}
PRODUCTIVITY_PILOT_APPEND_ONLY_POLICIES_BY_TABLE = {
    "collabio.productivity_pilot_preflight_reports": {
        "productivity_pilot_preflight_reports_no_update",
        "productivity_pilot_preflight_reports_no_hard_delete",
    },
    "collabio.productivity_pilot_admission_records": {
        "productivity_pilot_admission_records_no_update",
        "productivity_pilot_admission_records_no_hard_delete",
    },
    "collabio.productivity_pilot_real_user_nominations": {
        "productivity_pilot_real_user_nominations_no_update",
        "productivity_pilot_real_user_nominations_no_hard_delete",
    },
    "collabio.productivity_pilot_real_user_admissions": {
        "productivity_pilot_real_user_admissions_no_update",
        "productivity_pilot_real_user_admissions_no_hard_delete",
    },
}
PRODUCTIVITY_PILOT_APPEND_ONLY_TRIGGERS_BY_TABLE = {
    "collabio.productivity_pilot_preflight_reports": {
        "productivity_pilot_preflight_reports_append_only",
    },
    "collabio.productivity_pilot_admission_records": {
        "productivity_pilot_admission_records_append_only",
    },
    "collabio.productivity_pilot_real_user_nominations": {
        "productivity_pilot_real_user_nominations_append_only",
    },
    "collabio.productivity_pilot_real_user_admissions": {
        "productivity_pilot_real_user_admissions_append_only",
    },
}
PRODUCTIVITY_PILOT_TRAFFIC_SCOPE_TABLES = {
    "collabio.productivity_pilot_traffic_scope_enforcements",
}
PRODUCTIVITY_PILOT_TRAFFIC_SCOPE_APPEND_ONLY_POLICIES_BY_TABLE = {
    "collabio.productivity_pilot_traffic_scope_enforcements": {
        "productivity_pilot_traffic_scope_no_update",
        "productivity_pilot_traffic_scope_no_hard_delete",
    },
}
PRODUCTIVITY_PILOT_TRAFFIC_SCOPE_APPEND_ONLY_TRIGGERS_BY_TABLE = {
    "collabio.productivity_pilot_traffic_scope_enforcements": {
        "productivity_pilot_traffic_scope_append_only",
    },
}
PRODUCTIVITY_PILOT_START_AUTHORIZATION_TABLES = {
    "collabio.productivity_pilot_start_authorizations",
    "collabio.productivity_pilot_runtime_windows",
    "collabio.productivity_pilot_runtime_observations",
    "collabio.productivity_pilot_closure_reports",
    "collabio.productivity_pilot_real_user_runtime_windows",
    "collabio.productivity_pilot_real_user_runtime_observations",
}
PRODUCTIVITY_PILOT_START_AUTHORIZATION_APPEND_ONLY_POLICIES_BY_TABLE = {
    "collabio.productivity_pilot_start_authorizations": {
        "productivity_pilot_start_authorizations_no_update",
        "productivity_pilot_start_authorizations_no_hard_delete",
    },
    "collabio.productivity_pilot_runtime_windows": {
        "productivity_pilot_runtime_windows_no_update",
        "productivity_pilot_runtime_windows_no_hard_delete",
    },
    "collabio.productivity_pilot_runtime_observations": {
        "productivity_pilot_runtime_observations_no_update",
        "productivity_pilot_runtime_observations_no_hard_delete",
    },
    "collabio.productivity_pilot_closure_reports": {
        "productivity_pilot_closure_reports_no_update",
        "productivity_pilot_closure_reports_no_hard_delete",
    },
    "collabio.productivity_pilot_real_user_runtime_windows": {
        "productivity_pilot_real_user_runtime_windows_no_update",
        "productivity_pilot_real_user_runtime_windows_no_hard_delete",
    },
    "collabio.productivity_pilot_real_user_runtime_observations": {
        "productivity_pilot_real_user_runtime_observations_no_update",
        "productivity_pilot_real_user_runtime_observations_no_hard_delete",
    },
}
PRODUCTIVITY_PILOT_START_AUTHORIZATION_APPEND_ONLY_TRIGGERS_BY_TABLE = {
    "collabio.productivity_pilot_start_authorizations": {
        "productivity_pilot_start_authorizations_append_only",
    },
    "collabio.productivity_pilot_runtime_windows": {
        "productivity_pilot_runtime_windows_append_only",
    },
    "collabio.productivity_pilot_runtime_observations": {
        "productivity_pilot_runtime_observations_append_only",
    },
    "collabio.productivity_pilot_closure_reports": {
        "productivity_pilot_closure_reports_append_only",
    },
    "collabio.productivity_pilot_real_user_runtime_windows": {
        "productivity_pilot_real_user_runtime_windows_append_only",
    },
    "collabio.productivity_pilot_real_user_runtime_observations": {
        "productivity_pilot_real_user_runtime_observations_append_only",
    },
}


class PostgresBackupArtifactEvidence(BaseModel):
    artifact_ref_hash: str
    backup_sha256: str
    byte_length: int = Field(ge=1)
    checksum_sidecar_verified: bool
    restore_loader_receipt_verified: bool
    catalog_preflight_verified: bool
    evidence_hash: str
    schema_version: str = "postgres_backup_artifact_evidence.v1"


class PostgresDatabaseSnapshot(BaseModel):
    database_ref_hash: str
    schema_count: int = Field(ge=1)
    table_count: int = Field(ge=1)
    row_count_total: int = Field(ge=0)
    migration_count: int = Field(ge=1)
    rls_enabled_table_count: int = Field(ge=0)
    rls_forced_table_count: int = Field(ge=0)
    policy_count: int = Field(ge=0)
    constraint_count: int = Field(ge=0)
    index_count: int = Field(ge=0)
    trigger_count: int = Field(ge=0)
    extension_count: int = Field(ge=0)
    service_role_count: int = Field(ge=0)
    service_role_grant_count: int = Field(ge=0)
    schema_manifest_hash: str
    relation_manifest_hash: str
    crm_atomic_write_controls_verified: bool
    row_count_manifest_hash: str
    migration_manifest_hash: str
    tasks_activities_write_controls_verified: bool
    time_tracking_write_controls_verified: bool
    productivity_pilot_admission_controls_verified: bool
    productivity_pilot_traffic_scope_controls_verified: bool
    productivity_pilot_start_authorization_controls_verified: bool
    rls_policy_manifest_hash: str
    database_control_manifest_hash: str
    state_manifest_hash: str
    migration_catalog_verified: bool
    service_roles_verified: bool
    tenant_iam_controls_verified: bool
    append_only_audit_controls_verified: bool
    module_registry_controls_verified: bool
    source_object_controls_verified: bool
    content_included: bool = False
    snapshot_hash: str
    schema_version: str = "postgres_database_snapshot.v1"


class PostgresRestoreDrillReport(BaseModel):
    checked_at_utc: str
    backup_artifact_evidence_hash: str
    backup_sha256: str
    source_database_ref_hash: str
    target_database_ref_hash: str
    target_isolation_ref_hash: str
    source_snapshot_hash: str
    target_snapshot_hash: str
    source_state_manifest_hash: str
    target_state_manifest_hash: str
    migration_count: int = Field(ge=1)
    table_count: int = Field(ge=1)
    row_count_total: int = Field(ge=0)
    crm_atomic_write_controls_verified: bool
    source_target_state_verified: bool
    backup_integrity_verified: bool
    tasks_activities_write_controls_verified: bool
    time_tracking_write_controls_verified: bool
    productivity_pilot_admission_controls_verified: bool
    productivity_pilot_traffic_scope_controls_verified: bool
    productivity_pilot_start_authorization_controls_verified: bool
    target_isolation_verified: bool
    migration_catalog_verified: bool
    schema_inventory_verified: bool
    exact_row_counts_verified: bool
    rls_policy_controls_verified: bool
    service_roles_and_grants_verified: bool
    tenant_iam_controls_verified: bool
    append_only_audit_controls_verified: bool
    module_registry_controls_verified: bool
    source_object_controls_verified: bool
    metadata_only_evidence_verified: bool
    blocking_reasons: tuple[str, ...] = ()
    restore_ready: bool
    content_included: bool = False
    report_hash: str
    schema_version: str = "postgres_restore_drill_report.v1"


def build_postgres_backup_artifact_evidence(
    *,
    artifact_ref: str,
    backup_sha256: str,
    byte_length: int,
    checksum_sidecar_verified: bool,
    restore_loader_receipt_verified: bool,
) -> PostgresBackupArtifactEvidence:
    _require_sha256(backup_sha256, "backup_sha256")
    draft = PostgresBackupArtifactEvidence(
        artifact_ref_hash=_canonical_sha256({"artifact_ref": artifact_ref.strip()}),
        backup_sha256=backup_sha256,
        byte_length=byte_length,
        checksum_sidecar_verified=checksum_sidecar_verified,
        restore_loader_receipt_verified=restore_loader_receipt_verified,
        catalog_preflight_verified=restore_loader_receipt_verified,
        evidence_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"evidence_hash": build_postgres_backup_artifact_evidence_hash(draft)})


def build_postgres_backup_artifact_evidence_hash(evidence: PostgresBackupArtifactEvidence) -> str:
    return _canonical_sha256(evidence.model_dump(mode="json", exclude={"evidence_hash"}))


def build_postgres_database_snapshot(
    *,
    database_ref_hash: str,
    schemas: Sequence[Mapping[str, object]],
    tables: Sequence[Mapping[str, object]],
    columns: Sequence[Mapping[str, object]],
    row_counts: Sequence[Mapping[str, object]],
    migrations: Sequence[Mapping[str, object]],
    policies: Sequence[Mapping[str, object]],
    constraints: Sequence[Mapping[str, object]],
    indexes: Sequence[Mapping[str, object]],
    triggers: Sequence[Mapping[str, object]],
    extensions: Sequence[Mapping[str, object]],
    roles: Sequence[Mapping[str, object]],
    grants: Sequence[Mapping[str, object]],
) -> PostgresDatabaseSnapshot:
    _require_sha256(database_ref_hash, "database_ref_hash")
    normalized = {
        "schemas": _normalized_rows(schemas),
        "tables": _normalized_rows(tables),
        "columns": _normalized_rows(columns),
        "row_counts": _normalized_rows(row_counts),
        "migrations": _normalized_rows(migrations),
        "policies": _normalized_rows(policies),
        "constraints": _normalized_rows(constraints),
        "indexes": _normalized_rows(indexes),
        "triggers": _normalized_rows(triggers),
        "extensions": _normalized_rows(extensions),
        "roles": _normalized_rows(roles),
        "grants": _normalized_rows(grants),
    }
    table_names = {_qualified_name(row) for row in normalized["tables"]}
    forced_rls_tables = {_qualified_name(row) for row in normalized["tables"] if bool(row.get("rls_forced"))}
    policy_names_by_table = {
        table_name: {
            str(row.get("policy_name", "")) for row in normalized["policies"] if _qualified_name(row) == table_name
        }
        for table_name in AUDIT_TABLES
    }
    service_role_names = {str(row.get("role_name", "")) for row in normalized["roles"]}
    audit_writer_privileges_by_table = {
        table_name: {
            str(row.get("privilege_type", ""))
            for row in normalized["grants"]
            if row.get("grantee") == "collabio_audit_writer" and _qualified_name(row) == table_name
        }
        for table_name in AUDIT_TABLES
    }

    tenant_iam_verified = table_names >= TENANT_IAM_TABLES and forced_rls_tables >= TENANT_IAM_TABLES
    audit_verified = (
        table_names >= AUDIT_TABLES
        and forced_rls_tables >= AUDIT_TABLES
        and all(
            policy_names_by_table[table_name] >= expected_policies
            for table_name, expected_policies in AUDIT_APPEND_ONLY_POLICIES_BY_TABLE.items()
        )
        and all(
            {"SELECT", "INSERT"} <= privileges and not ({"UPDATE", "DELETE"} & privileges)
            for privileges in audit_writer_privileges_by_table.values()
        )
    )
    module_registry_verified = table_names >= MODULE_REGISTRY_TABLES and "collabio.tenant_modules" in forced_rls_tables
    source_object_verified = table_names >= SOURCE_OBJECT_TABLES and forced_rls_tables >= SOURCE_OBJECT_TABLES
    crm_receipt_policies = {
        str(row.get("policy_name", ""))
        for row in normalized["policies"]
        if _qualified_name(row) == "crm.account_onboarding_receipts"
    }
    crm_authz_privileges_by_table = {
        table_name: {
            str(row.get("privilege_type", ""))
            for row in normalized["grants"]
            if row.get("grantee") == "collabio_authz_admin" and _qualified_name(row) == table_name
        }
        for table_name in CRM_ATOMIC_WRITE_TABLES
    }
    crm_atomic_write_verified = (
        table_names >= CRM_ATOMIC_WRITE_TABLES
        and forced_rls_tables >= CRM_ATOMIC_WRITE_TABLES
        and crm_receipt_policies >= CRM_ATOMIC_RECEIPT_POLICIES
        and all(
            {"SELECT", "INSERT"} <= privileges and not ({"UPDATE", "DELETE"} & privileges)
            for privileges in crm_authz_privileges_by_table.values()
        )
    )
    tasks_policy_names_by_table = {
        table_name: {
            str(row.get("policy_name", "")) for row in normalized["policies"] if _qualified_name(row) == table_name
        }
        for table_name in TASKS_ACTIVITIES_WRITE_TABLES
    }
    tasks_authz_privileges_by_table = {
        table_name: {
            str(row.get("privilege_type", ""))
            for row in normalized["grants"]
            if row.get("grantee") == "collabio_authz_admin" and _qualified_name(row) == table_name
        }
        for table_name in TASKS_ACTIVITIES_WRITE_TABLES
    }
    tasks_app_privileges_by_table = {
        table_name: {
            str(row.get("privilege_type", ""))
            for row in normalized["grants"]
            if row.get("grantee") == "collabio_app" and _qualified_name(row) == table_name
        }
        for table_name in TASKS_ACTIVITIES_WRITE_TABLES
    }
    tasks_activities_write_verified = (
        table_names >= TASKS_ACTIVITIES_WRITE_TABLES
        and forced_rls_tables >= TASKS_ACTIVITIES_WRITE_TABLES
        and all(
            tasks_policy_names_by_table[table_name] >= expected_policies
            for table_name, expected_policies in TASKS_ACTIVITIES_APPEND_ONLY_POLICIES_BY_TABLE.items()
        )
        and all(
            {"SELECT", "INSERT"} <= privileges and not ({"UPDATE", "DELETE"} & privileges)
            for privileges in tasks_authz_privileges_by_table.values()
        )
        and all(
            "SELECT" in privileges and not ({"INSERT", "UPDATE", "DELETE"} & privileges)
            for privileges in tasks_app_privileges_by_table.values()
        )
    )
    time_tracking_policy_names_by_table = {
        table_name: {
            str(row.get("policy_name", "")) for row in normalized["policies"] if _qualified_name(row) == table_name
        }
        for table_name in TIME_TRACKING_WRITE_TABLES
    }
    time_tracking_authz_privileges_by_table = {
        table_name: {
            str(row.get("privilege_type", ""))
            for row in normalized["grants"]
            if row.get("grantee") == "collabio_authz_admin" and _qualified_name(row) == table_name
        }
        for table_name in TIME_TRACKING_WRITE_TABLES
    }
    time_tracking_app_privileges_by_table = {
        table_name: {
            str(row.get("privilege_type", ""))
            for row in normalized["grants"]
            if row.get("grantee") == "collabio_app" and _qualified_name(row) == table_name
        }
        for table_name in TIME_TRACKING_WRITE_TABLES
    }
    time_tracking_write_verified = (
        table_names >= TIME_TRACKING_WRITE_TABLES
        and forced_rls_tables >= TIME_TRACKING_WRITE_TABLES
        and all(
            time_tracking_policy_names_by_table[table_name] >= expected_policies
            for table_name, expected_policies in TIME_TRACKING_APPEND_ONLY_POLICIES_BY_TABLE.items()
        )
        and all(
            {"SELECT", "INSERT"} <= privileges and not ({"UPDATE", "DELETE"} & privileges)
            for privileges in time_tracking_authz_privileges_by_table.values()
        )
        and all(
            "SELECT" in privileges and not ({"INSERT", "UPDATE", "DELETE"} & privileges)
            for privileges in time_tracking_app_privileges_by_table.values()
        )
    )
    productivity_pilot_policy_names_by_table = {
        table_name: {
            str(row.get("policy_name", "")) for row in normalized["policies"] if _qualified_name(row) == table_name
        }
        for table_name in PRODUCTIVITY_PILOT_CONTROL_TABLES
    }
    productivity_pilot_trigger_names_by_table = {
        table_name: {
            str(row.get("trigger_name", "")) for row in normalized["triggers"] if _qualified_name(row) == table_name
        }
        for table_name in PRODUCTIVITY_PILOT_CONTROL_TABLES
    }
    productivity_pilot_authz_privileges_by_table = {
        table_name: {
            str(row.get("privilege_type", ""))
            for row in normalized["grants"]
            if row.get("grantee") == "collabio_authz_admin" and _qualified_name(row) == table_name
        }
        for table_name in PRODUCTIVITY_PILOT_CONTROL_TABLES
    }
    productivity_pilot_app_privileges_by_table = {
        table_name: {
            str(row.get("privilege_type", ""))
            for row in normalized["grants"]
            if row.get("grantee") == "collabio_app" and _qualified_name(row) == table_name
        }
        for table_name in PRODUCTIVITY_PILOT_CONTROL_TABLES
    }
    productivity_pilot_admission_verified = (
        table_names >= PRODUCTIVITY_PILOT_CONTROL_TABLES
        and forced_rls_tables >= PRODUCTIVITY_PILOT_CONTROL_TABLES
        and all(
            productivity_pilot_policy_names_by_table[table_name] >= expected_policies
            for table_name, expected_policies in PRODUCTIVITY_PILOT_APPEND_ONLY_POLICIES_BY_TABLE.items()
        )
        and all(
            productivity_pilot_trigger_names_by_table[table_name] >= expected_triggers
            for table_name, expected_triggers in PRODUCTIVITY_PILOT_APPEND_ONLY_TRIGGERS_BY_TABLE.items()
        )
        and productivity_pilot_authz_privileges_by_table["collabio.productivity_pilot_preflight_reports"] == {"SELECT"}
        and productivity_pilot_authz_privileges_by_table["collabio.productivity_pilot_admission_records"]
        == {"SELECT", "INSERT"}
        and all(not privileges for privileges in productivity_pilot_app_privileges_by_table.values())
    )
    productivity_pilot_traffic_policy_names_by_table = {
        table_name: {
            str(row.get("policy_name", "")) for row in normalized["policies"] if _qualified_name(row) == table_name
        }
        for table_name in PRODUCTIVITY_PILOT_TRAFFIC_SCOPE_TABLES
    }
    productivity_pilot_traffic_trigger_names_by_table = {
        table_name: {
            str(row.get("trigger_name", "")) for row in normalized["triggers"] if _qualified_name(row) == table_name
        }
        for table_name in PRODUCTIVITY_PILOT_TRAFFIC_SCOPE_TABLES
    }
    productivity_pilot_traffic_authz_privileges_by_table = {
        table_name: {
            str(row.get("privilege_type", ""))
            for row in normalized["grants"]
            if row.get("grantee") == "collabio_authz_admin" and _qualified_name(row) == table_name
        }
        for table_name in PRODUCTIVITY_PILOT_TRAFFIC_SCOPE_TABLES
    }
    productivity_pilot_traffic_app_privileges_by_table = {
        table_name: {
            str(row.get("privilege_type", ""))
            for row in normalized["grants"]
            if row.get("grantee") == "collabio_app" and _qualified_name(row) == table_name
        }
        for table_name in PRODUCTIVITY_PILOT_TRAFFIC_SCOPE_TABLES
    }
    productivity_pilot_traffic_scope_verified = (
        table_names >= PRODUCTIVITY_PILOT_TRAFFIC_SCOPE_TABLES
        and forced_rls_tables >= PRODUCTIVITY_PILOT_TRAFFIC_SCOPE_TABLES
        and all(
            productivity_pilot_traffic_policy_names_by_table[table_name] >= expected_policies
            for table_name, expected_policies in PRODUCTIVITY_PILOT_TRAFFIC_SCOPE_APPEND_ONLY_POLICIES_BY_TABLE.items()
        )
        and all(
            productivity_pilot_traffic_trigger_names_by_table[table_name] >= expected_triggers
            for table_name, expected_triggers in PRODUCTIVITY_PILOT_TRAFFIC_SCOPE_APPEND_ONLY_TRIGGERS_BY_TABLE.items()
        )
        and all(
            privileges == {"SELECT", "INSERT"}
            for privileges in productivity_pilot_traffic_authz_privileges_by_table.values()
        )
        and all(not privileges for privileges in productivity_pilot_traffic_app_privileges_by_table.values())
    )
    productivity_pilot_start_policy_names_by_table = {
        table_name: {
            str(row.get("policy_name", "")) for row in normalized["policies"] if _qualified_name(row) == table_name
        }
        for table_name in PRODUCTIVITY_PILOT_START_AUTHORIZATION_TABLES
    }
    productivity_pilot_start_trigger_names_by_table = {
        table_name: {
            str(row.get("trigger_name", "")) for row in normalized["triggers"] if _qualified_name(row) == table_name
        }
        for table_name in PRODUCTIVITY_PILOT_START_AUTHORIZATION_TABLES
    }
    productivity_pilot_start_authz_privileges_by_table = {
        table_name: {
            str(row.get("privilege_type", ""))
            for row in normalized["grants"]
            if row.get("grantee") == "collabio_authz_admin" and _qualified_name(row) == table_name
        }
        for table_name in PRODUCTIVITY_PILOT_START_AUTHORIZATION_TABLES
    }
    productivity_pilot_start_app_privileges_by_table = {
        table_name: {
            str(row.get("privilege_type", ""))
            for row in normalized["grants"]
            if row.get("grantee") == "collabio_app" and _qualified_name(row) == table_name
        }
        for table_name in PRODUCTIVITY_PILOT_START_AUTHORIZATION_TABLES
    }
    productivity_pilot_start_authorization_verified = (
        table_names >= PRODUCTIVITY_PILOT_START_AUTHORIZATION_TABLES
        and forced_rls_tables >= PRODUCTIVITY_PILOT_START_AUTHORIZATION_TABLES
        and all(
            productivity_pilot_start_policy_names_by_table[table_name] >= expected_policies
            for table_name, expected_policies in (
                PRODUCTIVITY_PILOT_START_AUTHORIZATION_APPEND_ONLY_POLICIES_BY_TABLE.items()
            )
        )
        and all(
            productivity_pilot_start_trigger_names_by_table[table_name] >= expected_triggers
            for table_name, expected_triggers in (
                PRODUCTIVITY_PILOT_START_AUTHORIZATION_APPEND_ONLY_TRIGGERS_BY_TABLE.items()
            )
        )
        and all(
            privileges == {"SELECT", "INSERT"}
            for privileges in productivity_pilot_start_authz_privileges_by_table.values()
        )
        and all(not privileges for privileges in productivity_pilot_start_app_privileges_by_table.values())
    )
    migration_catalog_verified = _migration_catalog_matches_code(normalized["migrations"])
    service_roles_verified = service_role_names >= SERVICE_ROLES

    schema_manifest_hash = _canonical_sha256(normalized["schemas"])
    relation_manifest_hash = _canonical_sha256(
        {
            "tables": normalized["tables"],
            "columns": normalized["columns"],
            "constraints": normalized["constraints"],
            "indexes": normalized["indexes"],
            "triggers": normalized["triggers"],
            "extensions": normalized["extensions"],
        }
    )
    row_count_manifest_hash = _canonical_sha256(normalized["row_counts"])
    migration_manifest_hash = _canonical_sha256(normalized["migrations"])
    rls_policy_manifest_hash = _canonical_sha256({"tables": normalized["tables"], "policies": normalized["policies"]})
    database_control_manifest_hash = _canonical_sha256({"roles": normalized["roles"], "grants": normalized["grants"]})
    state_payload = {
        "schema_manifest_hash": schema_manifest_hash,
        "relation_manifest_hash": relation_manifest_hash,
        "row_count_manifest_hash": row_count_manifest_hash,
        "migration_manifest_hash": migration_manifest_hash,
        "rls_policy_manifest_hash": rls_policy_manifest_hash,
        "database_control_manifest_hash": database_control_manifest_hash,
    }
    draft = PostgresDatabaseSnapshot(
        database_ref_hash=database_ref_hash,
        schema_count=len(normalized["schemas"]),
        table_count=len(normalized["tables"]),
        row_count_total=sum(_integer_value(row["row_count"]) for row in normalized["row_counts"]),
        migration_count=len(normalized["migrations"]),
        rls_enabled_table_count=sum(bool(row.get("rls_enabled")) for row in normalized["tables"]),
        rls_forced_table_count=sum(bool(row.get("rls_forced")) for row in normalized["tables"]),
        policy_count=len(normalized["policies"]),
        constraint_count=len(normalized["constraints"]),
        index_count=len(normalized["indexes"]),
        trigger_count=len(normalized["triggers"]),
        extension_count=len(normalized["extensions"]),
        service_role_count=len(normalized["roles"]),
        service_role_grant_count=len(normalized["grants"]),
        schema_manifest_hash=schema_manifest_hash,
        relation_manifest_hash=relation_manifest_hash,
        row_count_manifest_hash=row_count_manifest_hash,
        migration_manifest_hash=migration_manifest_hash,
        rls_policy_manifest_hash=rls_policy_manifest_hash,
        database_control_manifest_hash=database_control_manifest_hash,
        state_manifest_hash=_canonical_sha256(state_payload),
        migration_catalog_verified=migration_catalog_verified,
        service_roles_verified=service_roles_verified,
        tenant_iam_controls_verified=tenant_iam_verified,
        append_only_audit_controls_verified=audit_verified,
        module_registry_controls_verified=module_registry_verified,
        source_object_controls_verified=source_object_verified,
        crm_atomic_write_controls_verified=crm_atomic_write_verified,
        tasks_activities_write_controls_verified=tasks_activities_write_verified,
        time_tracking_write_controls_verified=time_tracking_write_verified,
        productivity_pilot_admission_controls_verified=productivity_pilot_admission_verified,
        productivity_pilot_traffic_scope_controls_verified=productivity_pilot_traffic_scope_verified,
        productivity_pilot_start_authorization_controls_verified=(productivity_pilot_start_authorization_verified),
        snapshot_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"snapshot_hash": build_postgres_database_snapshot_hash(draft)})


def build_postgres_database_snapshot_hash(snapshot: PostgresDatabaseSnapshot) -> str:
    return _canonical_sha256(snapshot.model_dump(mode="json", exclude={"snapshot_hash"}))


def build_postgres_restore_drill_report(
    *,
    backup_evidence: PostgresBackupArtifactEvidence,
    source_snapshot: PostgresDatabaseSnapshot,
    target_snapshot: PostgresDatabaseSnapshot,
    target_isolation_ref_hash: str,
    checked_at_utc: str | None = None,
) -> PostgresRestoreDrillReport:
    if build_postgres_backup_artifact_evidence_hash(backup_evidence) != backup_evidence.evidence_hash:
        raise ValueError("backup artifact evidence hash is invalid")
    if build_postgres_database_snapshot_hash(source_snapshot) != source_snapshot.snapshot_hash:
        raise ValueError("source database snapshot hash is invalid")
    if build_postgres_database_snapshot_hash(target_snapshot) != target_snapshot.snapshot_hash:
        raise ValueError("target database snapshot hash is invalid")
    _require_sha256(target_isolation_ref_hash, "target_isolation_ref_hash")

    source_target_state_verified = source_snapshot.state_manifest_hash == target_snapshot.state_manifest_hash
    schema_inventory_verified = (
        source_snapshot.schema_manifest_hash == target_snapshot.schema_manifest_hash
        and source_snapshot.relation_manifest_hash == target_snapshot.relation_manifest_hash
    )
    exact_row_counts_verified = source_snapshot.row_count_manifest_hash == target_snapshot.row_count_manifest_hash
    migration_catalog_verified = (
        source_snapshot.migration_catalog_verified
        and target_snapshot.migration_catalog_verified
        and source_snapshot.migration_manifest_hash == target_snapshot.migration_manifest_hash
    )
    rls_policy_controls_verified = source_snapshot.rls_policy_manifest_hash == target_snapshot.rls_policy_manifest_hash
    service_roles_and_grants_verified = (
        source_snapshot.service_roles_verified
        and target_snapshot.service_roles_verified
        and source_snapshot.database_control_manifest_hash == target_snapshot.database_control_manifest_hash
    )
    backup_integrity_verified = (
        backup_evidence.checksum_sidecar_verified
        and backup_evidence.restore_loader_receipt_verified
        and backup_evidence.catalog_preflight_verified
    )
    control_pairs = {
        "tenant_iam_controls_verified": (
            source_snapshot.tenant_iam_controls_verified and target_snapshot.tenant_iam_controls_verified
        ),
        "append_only_audit_controls_verified": (
            source_snapshot.append_only_audit_controls_verified and target_snapshot.append_only_audit_controls_verified
        ),
        "module_registry_controls_verified": (
            source_snapshot.module_registry_controls_verified and target_snapshot.module_registry_controls_verified
        ),
        "source_object_controls_verified": (
            source_snapshot.source_object_controls_verified and target_snapshot.source_object_controls_verified
        ),
        "crm_atomic_write_controls_verified": (
            source_snapshot.crm_atomic_write_controls_verified and target_snapshot.crm_atomic_write_controls_verified
        ),
        "tasks_activities_write_controls_verified": (
            source_snapshot.tasks_activities_write_controls_verified
            and target_snapshot.tasks_activities_write_controls_verified
        ),
        "time_tracking_write_controls_verified": (
            source_snapshot.time_tracking_write_controls_verified
            and target_snapshot.time_tracking_write_controls_verified
        ),
        "productivity_pilot_admission_controls_verified": (
            source_snapshot.productivity_pilot_admission_controls_verified
            and target_snapshot.productivity_pilot_admission_controls_verified
        ),
        "productivity_pilot_traffic_scope_controls_verified": (
            source_snapshot.productivity_pilot_traffic_scope_controls_verified
            and target_snapshot.productivity_pilot_traffic_scope_controls_verified
        ),
        "productivity_pilot_start_authorization_controls_verified": (
            source_snapshot.productivity_pilot_start_authorization_controls_verified
            and target_snapshot.productivity_pilot_start_authorization_controls_verified
        ),
    }
    metadata_only = not source_snapshot.content_included and not target_snapshot.content_included
    checks = {
        "source_target_state_mismatch": source_target_state_verified,
        "backup_integrity_not_verified": backup_integrity_verified,
        "migration_catalog_not_verified": migration_catalog_verified,
        "schema_inventory_mismatch": schema_inventory_verified,
        "exact_row_counts_mismatch": exact_row_counts_verified,
        "rls_policy_controls_mismatch": rls_policy_controls_verified,
        "service_roles_or_grants_mismatch": service_roles_and_grants_verified,
        "tenant_iam_controls_not_verified": control_pairs["tenant_iam_controls_verified"],
        "append_only_audit_controls_not_verified": control_pairs["append_only_audit_controls_verified"],
        "module_registry_controls_not_verified": control_pairs["module_registry_controls_verified"],
        "crm_atomic_write_controls_not_verified": control_pairs["crm_atomic_write_controls_verified"],
        "tasks_activities_write_controls_not_verified": control_pairs["tasks_activities_write_controls_verified"],
        "time_tracking_write_controls_not_verified": control_pairs["time_tracking_write_controls_verified"],
        "productivity_pilot_admission_controls_not_verified": control_pairs[
            "productivity_pilot_admission_controls_verified"
        ],
        "productivity_pilot_traffic_scope_controls_not_verified": control_pairs[
            "productivity_pilot_traffic_scope_controls_verified"
        ],
        "productivity_pilot_start_authorization_controls_not_verified": control_pairs[
            "productivity_pilot_start_authorization_controls_verified"
        ],
        "source_object_controls_not_verified": control_pairs["source_object_controls_verified"],
        "evidence_contains_content": metadata_only,
    }
    blocking_reasons = tuple(sorted(reason for reason, passed in checks.items() if not passed))
    draft = PostgresRestoreDrillReport(
        checked_at_utc=checked_at_utc or _now_utc(),
        backup_artifact_evidence_hash=backup_evidence.evidence_hash,
        backup_sha256=backup_evidence.backup_sha256,
        source_database_ref_hash=source_snapshot.database_ref_hash,
        target_database_ref_hash=target_snapshot.database_ref_hash,
        target_isolation_ref_hash=target_isolation_ref_hash,
        source_snapshot_hash=source_snapshot.snapshot_hash,
        target_snapshot_hash=target_snapshot.snapshot_hash,
        source_state_manifest_hash=source_snapshot.state_manifest_hash,
        target_state_manifest_hash=target_snapshot.state_manifest_hash,
        migration_count=source_snapshot.migration_count,
        table_count=source_snapshot.table_count,
        row_count_total=source_snapshot.row_count_total,
        source_target_state_verified=source_target_state_verified,
        backup_integrity_verified=backup_integrity_verified,
        target_isolation_verified=True,
        migration_catalog_verified=migration_catalog_verified,
        schema_inventory_verified=schema_inventory_verified,
        exact_row_counts_verified=exact_row_counts_verified,
        rls_policy_controls_verified=rls_policy_controls_verified,
        service_roles_and_grants_verified=service_roles_and_grants_verified,
        tenant_iam_controls_verified=control_pairs["tenant_iam_controls_verified"],
        append_only_audit_controls_verified=control_pairs["append_only_audit_controls_verified"],
        module_registry_controls_verified=control_pairs["module_registry_controls_verified"],
        crm_atomic_write_controls_verified=control_pairs["crm_atomic_write_controls_verified"],
        tasks_activities_write_controls_verified=control_pairs["tasks_activities_write_controls_verified"],
        time_tracking_write_controls_verified=control_pairs["time_tracking_write_controls_verified"],
        productivity_pilot_admission_controls_verified=control_pairs["productivity_pilot_admission_controls_verified"],
        productivity_pilot_traffic_scope_controls_verified=control_pairs[
            "productivity_pilot_traffic_scope_controls_verified"
        ],
        productivity_pilot_start_authorization_controls_verified=control_pairs[
            "productivity_pilot_start_authorization_controls_verified"
        ],
        source_object_controls_verified=control_pairs["source_object_controls_verified"],
        metadata_only_evidence_verified=metadata_only,
        blocking_reasons=blocking_reasons,
        restore_ready=not blocking_reasons,
        report_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"report_hash": build_postgres_restore_drill_report_hash(draft)})


def build_postgres_restore_drill_report_hash(report: PostgresRestoreDrillReport) -> str:
    return _canonical_sha256(report.model_dump(mode="json", exclude={"report_hash"}))


def build_postgres_restore_target_isolation_ref_hash(*, source_dsn: str, target_dsn: str) -> str:
    source_ref = _database_connection_ref(source_dsn)
    target_ref = _database_connection_ref(target_dsn)
    if source_ref == target_ref:
        raise ValueError("PostgreSQL restore target must be isolated from the source database")
    return _canonical_sha256({"source": source_ref, "target": target_ref})


def inspect_postgres_database(database_dsn: str) -> PostgresDatabaseSnapshot:
    database_ref_hash = _canonical_sha256(_database_connection_ref(database_dsn))
    with psycopg.connect(database_dsn, row_factory=dict_row) as connection:
        schemas = _fetch_rows(
            connection,
            """
            SELECT nspname AS schema_name
            FROM pg_namespace
            WHERE nspname NOT IN ('information_schema', 'pg_catalog', 'pg_toast')
              AND nspname NOT LIKE 'pg_temp_%'
              AND nspname NOT LIKE 'pg_toast_temp_%'
            ORDER BY nspname
            """,
        )
        tables = _fetch_rows(
            connection,
            """
            SELECT n.nspname AS schema_name,
                   c.relname AS table_name,
                   c.relkind::text AS relation_kind,
                   c.relrowsecurity AS rls_enabled,
                   c.relforcerowsecurity AS rls_forced
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind IN ('r', 'p')
              AND n.nspname NOT IN ('information_schema', 'pg_catalog', 'pg_toast')
              AND n.nspname NOT LIKE 'pg_temp_%'
              AND n.nspname NOT LIKE 'pg_toast_temp_%'
            ORDER BY n.nspname, c.relname
            """,
        )
        columns = _fetch_rows(
            connection,
            """
            SELECT table_schema AS schema_name,
                   table_name,
                   column_name,
                   ordinal_position,
                   data_type,
                   udt_schema,
                   udt_name,
                   is_nullable,
                   column_default
            FROM information_schema.columns
            WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
            ORDER BY table_schema, table_name, ordinal_position
            """,
        )
        policies = _fetch_rows(
            connection,
            """
            SELECT schemaname AS schema_name,
                   tablename AS table_name,
                   policyname AS policy_name,
                   permissive,
                   roles::text AS roles,
                   cmd,
                   qual,
                   with_check
            FROM pg_policies
            ORDER BY schemaname, tablename, policyname
            """,
        )
        constraints = _fetch_rows(
            connection,
            """
            SELECT n.nspname AS schema_name,
                   c.relname AS table_name,
                   con.conname AS constraint_name,
                   con.contype::text AS constraint_type,
                   pg_get_constraintdef(con.oid, true) AS constraint_definition
            FROM pg_constraint con
            JOIN pg_class c ON c.oid = con.conrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname NOT IN ('information_schema', 'pg_catalog', 'pg_toast')
            ORDER BY n.nspname, c.relname, con.conname
            """,
        )
        indexes = _fetch_rows(
            connection,
            """
            SELECT schemaname AS schema_name,
                   tablename AS table_name,
                   indexname AS index_name,
                   indexdef AS index_definition
            FROM pg_indexes
            WHERE schemaname NOT IN ('pg_catalog', 'pg_toast')
            ORDER BY schemaname, tablename, indexname
            """,
        )
        triggers = _fetch_rows(
            connection,
            """
            SELECT n.nspname AS schema_name,
                   c.relname AS table_name,
                   t.tgname AS trigger_name,
                   pg_get_triggerdef(t.oid, true) AS trigger_definition
            FROM pg_trigger t
            JOIN pg_class c ON c.oid = t.tgrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE NOT t.tgisinternal
              AND n.nspname NOT IN ('information_schema', 'pg_catalog', 'pg_toast')
            ORDER BY n.nspname, c.relname, t.tgname
            """,
        )
        extensions = _fetch_rows(
            connection,
            """
            SELECT extname AS extension_name, extversion AS extension_version
            FROM pg_extension
            ORDER BY extname
            """,
        )
        migrations = _fetch_rows(
            connection,
            """
            SELECT version, name, module_id, checksum, evidence_refs, blocks_startup
            FROM collabio.schema_migrations
            ORDER BY version
            """,
        )
        roles = _fetch_rows(
            connection,
            """
            SELECT rolname AS role_name,
                   rolcanlogin AS can_login,
                   rolinherit AS inherits_roles,
                   rolbypassrls AS bypasses_rls,
                   rolsuper AS is_superuser
            FROM pg_roles
            WHERE rolname = ANY(%s)
            ORDER BY rolname
            """,
            (sorted(SERVICE_ROLES),),
        )
        grants = _fetch_rows(
            connection,
            """
            SELECT table_schema AS schema_name,
                   table_name,
                   grantee,
                   privilege_type,
                   is_grantable
            FROM information_schema.role_table_grants
            WHERE grantee = ANY(%s)
            ORDER BY table_schema, table_name, grantee, privilege_type
            """,
            (sorted(SERVICE_ROLES),),
        )
        row_counts = _exact_row_counts(connection, tables)
    return build_postgres_database_snapshot(
        database_ref_hash=database_ref_hash,
        schemas=schemas,
        tables=tables,
        columns=columns,
        row_counts=row_counts,
        migrations=migrations,
        policies=policies,
        constraints=constraints,
        indexes=indexes,
        triggers=triggers,
        extensions=extensions,
        roles=roles,
        grants=grants,
    )


def discover_postgres_backup_artifact(
    *,
    backup_directory: Path,
    restore_receipt_path: Path,
) -> PostgresBackupArtifactEvidence:
    dumps = tuple(backup_directory.glob("*.dump"))
    if not dumps:
        raise FileNotFoundError(f"No PostgreSQL dump found in {backup_directory}")
    artifact = max(dumps, key=lambda path: (path.stat().st_mtime_ns, path.name))
    backup_sha256 = "sha256:" + _file_sha256(artifact)
    sidecar = Path(str(artifact) + ".sha256")
    sidecar_hash, sidecar_name = _parse_sha256_sidecar(sidecar)
    checksum_verified = sidecar_hash == backup_sha256 and Path(sidecar_name).name == artifact.name
    receipt_verified = (
        restore_receipt_path.is_file() and restore_receipt_path.read_text(encoding="ascii").strip() == backup_sha256
    )
    return build_postgres_backup_artifact_evidence(
        artifact_ref=artifact.name,
        backup_sha256=backup_sha256,
        byte_length=artifact.stat().st_size,
        checksum_sidecar_verified=checksum_verified,
        restore_loader_receipt_verified=receipt_verified,
    )


def run_postgres_restore_drill_from_environment(env: Mapping[str, str]) -> PostgresRestoreDrillReport:
    source_dsn = _required_env(env, "SUITE_POSTGRES_RESTORE_SOURCE_DSN")
    target_dsn = _required_env(env, "SUITE_POSTGRES_RESTORE_TARGET_DSN")
    backup_directory = Path(env.get("SUITE_POSTGRES_BACKUP_DIRECTORY", "/backups"))
    restore_receipt_path = Path(
        env.get("SUITE_POSTGRES_RESTORE_RECEIPT_PATH", "/backups/postgres-restore-receipt.sha256")
    )
    backup_evidence = discover_postgres_backup_artifact(
        backup_directory=backup_directory,
        restore_receipt_path=restore_receipt_path,
    )
    return build_postgres_restore_drill_report(
        backup_evidence=backup_evidence,
        source_snapshot=inspect_postgres_database(source_dsn),
        target_snapshot=inspect_postgres_database(target_dsn),
        target_isolation_ref_hash=build_postgres_restore_target_isolation_ref_hash(
            source_dsn=source_dsn,
            target_dsn=target_dsn,
        ),
    )


def _fetch_rows(
    connection: psycopg.Connection[dict[str, Any]],
    query: str,
    params: Sequence[object] | None = None,
) -> tuple[Mapping[str, object], ...]:
    return tuple(dict(row) for row in connection.execute(query, params).fetchall())


def _exact_row_counts(
    connection: psycopg.Connection[dict[str, Any]],
    tables: Sequence[Mapping[str, object]],
) -> tuple[Mapping[str, object], ...]:
    counts: list[Mapping[str, object]] = []
    for table in tables:
        schema_name = str(table["schema_name"])
        table_name = str(table["table_name"])
        row = connection.execute(
            sql.SQL("SELECT count(*) AS row_count FROM {}.{}").format(
                sql.Identifier(schema_name),
                sql.Identifier(table_name),
            )
        ).fetchone()
        if row is None:
            raise RuntimeError(f"Could not count restored relation {schema_name}.{table_name}")
        counts.append(
            {
                "schema_name": schema_name,
                "table_name": table_name,
                "row_count": int(row["row_count"]),
            }
        )
    return tuple(counts)


def _migration_catalog_matches_code(rows: Sequence[Mapping[str, object]]) -> bool:
    stored = {str(row.get("version")): row for row in rows}
    catalog = {migration.version: migration for migration in load_migrations()}
    for version, migration in catalog.items():
        row = stored.get(version)
        if row is None:
            if migration.blocks_startup:
                return False
            continue
        evidence_refs = row.get("evidence_refs")
        normalized_evidence = json.loads(evidence_refs) if isinstance(evidence_refs, str) else evidence_refs
        if not isinstance(normalized_evidence, list) or not all(isinstance(item, str) for item in normalized_evidence):
            return False
        if (
            row.get("name") != migration.name
            or row.get("module_id") != migration.module_id
            or row.get("checksum") != migration.checksum()
            or tuple(sorted(normalized_evidence)) != tuple(sorted(migration.evidence_refs))
            or bool(row.get("blocks_startup")) != migration.blocks_startup
        ):
            return False
    return not any(version not in catalog and bool(row.get("blocks_startup")) for version, row in stored.items())


def _database_connection_ref(database_dsn: str) -> dict[str, str]:
    values = conninfo_to_dict(database_dsn)
    return {
        "host": str(values.get("host") or ""),
        "port": str(values.get("port") or "5432"),
        "dbname": str(values.get("dbname") or ""),
        "user": str(values.get("user") or ""),
    }


def _integer_value(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("row_count must be an integer")
    return value


def _normalized_rows(rows: Sequence[Mapping[str, object]]) -> tuple[dict[str, object], ...]:
    normalized = tuple({str(key): _json_value(value) for key, value in sorted(row.items())} for row in rows)
    return tuple(sorted(normalized, key=lambda row: json.dumps(row, sort_keys=True, separators=(",", ":"))))


def _json_value(value: object) -> object:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_json_value(item) for item in value]
    return str(value)


def _qualified_name(row: Mapping[str, object]) -> str:
    return f"{row.get('schema_name', '')}.{row.get('table_name', '')}"


def _parse_sha256_sidecar(path: Path) -> tuple[str, str]:
    if not path.is_file():
        return "", ""
    parts = path.read_text(encoding="ascii").strip().split(maxsplit=1)
    if len(parts) != 2 or not re.fullmatch(r"[a-f0-9]{64}", parts[0]):
        return "", ""
    return "sha256:" + parts[0], parts[1].lstrip("*")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(payload: object) -> str:
    return sha256_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _require_sha256(value: str, field_name: str) -> None:
    if not SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"{field_name} must be a sha256 reference")


def _required_env(env: Mapping[str, str], name: str) -> str:
    value = env.get(name)
    if value is None or not value.strip():
        raise ValueError(f"Required environment variable missing: {name}")
    return value.strip()


def _now_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def main() -> None:
    report = run_postgres_restore_drill_from_environment(os.environ)
    print(json.dumps(report.model_dump(mode="json"), sort_keys=True))
    raise SystemExit(0 if report.restore_ready else 2)


if __name__ == "__main__":
    main()
