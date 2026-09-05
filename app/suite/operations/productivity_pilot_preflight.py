from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.operations.business_backend_release_gate import (
    BusinessBackendReleaseGate,
    build_business_backend_release_gate_hash,
    load_business_backend_release_gate,
)
from suite.storage.source_objects import sha256_bytes

PRODUCTIVITY_PILOT_POLICY_SCHEMA_VERSION = "productivity_pilot_policy.v1"
PRODUCTIVITY_PILOT_PREFLIGHT_SCHEMA_VERSION = "productivity_pilot_preflight_gate.v1"
REF_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")
ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
TENANT_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,127}$")
FEATURE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
API_OPERATION_PATTERN = re.compile(r"^(GET|POST|PUT|PATCH|DELETE) /v1/[a-z0-9_/{}/.-]+$")


class ProductivityPilotSlicePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slice_id: str
    module_id: str
    required_feature_ids: tuple[str, ...]
    forbidden_feature_ids: tuple[str, ...]

    @field_validator("slice_id", "module_id")
    @classmethod
    def require_id(cls, value: str) -> str:
        if not ID_PATTERN.fullmatch(value):
            raise ValueError("pilot slice and module IDs must be lowercase snake_case")
        return value

    @field_validator("required_feature_ids", "forbidden_feature_ids")
    @classmethod
    def require_unique_features(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)) or any(not FEATURE_ID_PATTERN.fullmatch(item) for item in value):
            raise ValueError("pilot feature IDs must be unique namespaced references")
        return value

    @model_validator(mode="after")
    def require_disjoint_features(self) -> Self:
        if not self.required_feature_ids:
            raise ValueError("pilot slices require at least one feature")
        if set(self.required_feature_ids) & set(self.forbidden_feature_ids):
            raise ValueError("required and forbidden pilot features must be disjoint")
        return self


class ProductivityPilotControl(BaseModel):
    model_config = ConfigDict(extra="forbid")

    control_id: str
    evidence_ref: str
    required_before_start: bool
    destructive_action_allowed: bool = False

    @field_validator("control_id")
    @classmethod
    def require_control_id(cls, value: str) -> str:
        if not ID_PATTERN.fullmatch(value):
            raise ValueError("pilot control IDs must be lowercase snake_case")
        return value

    @field_validator("evidence_ref")
    @classmethod
    def require_evidence_ref(cls, value: str) -> str:
        if not REF_PATTERN.fullmatch(value):
            raise ValueError("pilot control evidence must use a typed reference")
        return value

    @model_validator(mode="after")
    def require_non_destructive_control(self) -> Self:
        if not self.required_before_start or self.destructive_action_allowed:
            raise ValueError("pilot controls must be mandatory and non-destructive")
        return self


class ProductivityPilotPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = PRODUCTIVITY_PILOT_POLICY_SCHEMA_VERSION
    policy_id: str
    max_candidate_tenants: int = Field(ge=1, le=10)
    required_release_schema_version: str
    slices: tuple[ProductivityPilotSlicePolicy, ...]
    allowed_api_operations: tuple[str, ...]
    monitoring_controls: tuple[ProductivityPilotControl, ...]
    rollback_controls: tuple[ProductivityPilotControl, ...]
    human_admission_required: bool = True
    traffic_scope_enforcement_required: bool = True
    automatic_tenant_activation_allowed: bool = False
    destructive_rollback_allowed: bool = False

    @field_validator("policy_id")
    @classmethod
    def require_policy_id(cls, value: str) -> str:
        if not re.fullmatch(r"^[a-z][a-z0-9-]*$", value):
            raise ValueError("pilot policy ID must be lowercase kebab-case")
        return value

    @field_validator("allowed_api_operations")
    @classmethod
    def require_api_operations(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or len(value) != len(set(value)):
            raise ValueError("pilot API operations must be present and unique")
        if any(not API_OPERATION_PATTERN.fullmatch(item) for item in value):
            raise ValueError("pilot API operations must use METHOD /v1/path format")
        return value

    @model_validator(mode="after")
    def require_closed_policy(self) -> Self:
        slice_ids = [item.slice_id for item in self.slices]
        module_ids = [item.module_id for item in self.slices]
        monitoring_ids = [item.control_id for item in self.monitoring_controls]
        rollback_ids = [item.control_id for item in self.rollback_controls]
        if not self.slices or len(slice_ids) != len(set(slice_ids)) or len(module_ids) != len(set(module_ids)):
            raise ValueError("pilot policy slices and modules must be non-empty and unique")
        if not self.monitoring_controls or len(monitoring_ids) != len(set(monitoring_ids)):
            raise ValueError("pilot monitoring controls must be non-empty and unique")
        if not self.rollback_controls or len(rollback_ids) != len(set(rollback_ids)):
            raise ValueError("pilot rollback controls must be non-empty and unique")
        if (
            self.schema_version != PRODUCTIVITY_PILOT_POLICY_SCHEMA_VERSION
            or not self.human_admission_required
            or not self.traffic_scope_enforcement_required
            or self.automatic_tenant_activation_allowed
            or self.destructive_rollback_allowed
        ):
            raise ValueError("pilot policy must preserve human admission and non-destructive rollback")
        return self


class PilotTenantSliceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    slice_id: str
    module_id: str
    module_state_present: bool
    module_status: str
    required_feature_count: int = Field(ge=1)
    enabled_required_feature_count: int = Field(ge=0)
    forbidden_feature_count: int = Field(ge=0)
    enabled_forbidden_feature_count: int = Field(ge=0)
    module_state_hash: str
    blocking_reasons: tuple[str, ...] = ()
    ready: bool
    schema_version: str = "pilot_tenant_slice_evidence.v1"


class PilotTenantEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    slices: tuple[PilotTenantSliceEvidence, ...]
    ready_slice_count: int = Field(ge=0)
    ready: bool
    schema_version: str = "pilot_tenant_evidence.v1"


class ProductivityPilotPreflightGate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checked_at_utc: str
    runtime_environment: str
    policy_id: str
    policy_hash: str
    business_backend_release_gate_hash: str
    business_backend_release_ready: bool
    candidate_tenant_ids: tuple[str, ...]
    candidate_tenant_count: int = Field(ge=0)
    maximum_candidate_tenant_count: int = Field(ge=1)
    tenant_module_state_manifest_hash: str
    tenants: tuple[PilotTenantEvidence, ...]
    ready_tenant_count: int = Field(ge=0)
    productive_slice_count: int = Field(ge=1)
    route_scope_contract_verified: bool
    monitoring_contract_verified: bool
    monitoring_control_count: int = Field(ge=1)
    rollback_contract_verified: bool
    rollback_control_count: int = Field(ge=1)
    human_admission_required: bool
    human_admission_recorded: bool = False
    traffic_scope_enforcement_required: bool
    traffic_scope_enforced: bool = False
    tenant_state_changed: bool = False
    business_write_executed: bool = False
    content_included: bool = False
    destructive_actions_allowed: bool = False
    external_side_effect_allowed: bool = False
    blocking_reasons: tuple[str, ...] = ()
    preflight_ready: bool
    pilot_start_allowed: bool = False
    next_action: str
    gate_hash: str
    schema_version: str = PRODUCTIVITY_PILOT_PREFLIGHT_SCHEMA_VERSION

    @model_validator(mode="after")
    def require_non_executing_preflight(self) -> Self:
        if (
            self.human_admission_recorded
            or self.traffic_scope_enforced
            or self.tenant_state_changed
            or self.business_write_executed
            or self.content_included
            or self.destructive_actions_allowed
            or self.external_side_effect_allowed
            or self.pilot_start_allowed
        ):
            raise ValueError("productivity pilot preflight must remain non-executing")
        if self.preflight_ready == bool(self.blocking_reasons):
            raise ValueError("pilot preflight readiness must match blocking reasons")
        return self


def load_productivity_pilot_policy(path: Path) -> ProductivityPilotPolicy:
    return ProductivityPilotPolicy.model_validate_json(path.read_text(encoding="utf-8"))


def build_productivity_pilot_policy_hash(policy: ProductivityPilotPolicy) -> str:
    return sha256_bytes(
        json.dumps(policy.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode("utf-8")
    )


def _enabled_features(row: Mapping[str, object]) -> dict[str, bool]:
    value = row["enabled_features"]
    if not isinstance(value, Mapping):
        raise ValueError("tenant module enabled_features must be an object")
    features: dict[str, bool] = {}
    for feature_id, enabled in value.items():
        if not isinstance(enabled, bool):
            raise ValueError("tenant module feature state must be boolean")
        features[str(feature_id)] = enabled
    return features


def _module_state_hash(row: Mapping[str, object] | None) -> str:
    if row is None:
        return sha256_bytes(b"missing")
    payload = {
        "tenant_id": str(row["tenant_id"]),
        "module_id": str(row["module_id"]),
        "status": str(row["status"]),
        "enabled_features": dict(sorted(_enabled_features(row).items())),
    }
    return sha256_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _tenant_module_state_manifest_hash(rows: Sequence[Mapping[str, object]]) -> str:
    state_hashes = sorted(_module_state_hash(row) for row in rows)
    return sha256_bytes(json.dumps(state_hashes, separators=(",", ":")).encode("utf-8"))


def build_productivity_pilot_preflight_gate(
    *,
    business_gate: BusinessBackendReleaseGate,
    policy: ProductivityPilotPolicy,
    candidate_tenant_ids: Sequence[str],
    tenant_module_rows: Sequence[Mapping[str, object]],
    checked_at_utc: str | None = None,
) -> ProductivityPilotPreflightGate:
    if build_business_backend_release_gate_hash(business_gate) != business_gate.gate_hash:
        raise ValueError("business backend release gate hash is invalid")

    requested_tenants = tuple(item.strip() for item in candidate_tenant_ids if item.strip())
    invalid_tenants = tuple(item for item in requested_tenants if not TENANT_ID_PATTERN.fullmatch(item))
    if invalid_tenants:
        raise ValueError("candidate tenant IDs have an invalid format")
    normalized_tenants = tuple(sorted(set(requested_tenants)))
    row_by_key = {(str(row["tenant_id"]), str(row["module_id"])): row for row in tenant_module_rows}
    tenant_evidence: list[PilotTenantEvidence] = []

    for tenant_id in normalized_tenants:
        slice_evidence: list[PilotTenantSliceEvidence] = []
        for slice_policy in policy.slices:
            row = row_by_key.get((tenant_id, slice_policy.module_id))
            features = _enabled_features(row) if row is not None else {}
            module_status = str(row["status"]) if row is not None else "missing"
            enabled_required = sum(features.get(feature_id, False) for feature_id in slice_policy.required_feature_ids)
            enabled_forbidden = sum(
                features.get(feature_id, False) for feature_id in slice_policy.forbidden_feature_ids
            )
            checks = {
                "tenant_module_state_missing": row is not None,
                "tenant_module_not_enabled": module_status == "enabled",
                "required_pilot_feature_missing": enabled_required == len(slice_policy.required_feature_ids),
                "forbidden_pilot_feature_enabled": enabled_forbidden == 0,
            }
            reasons = tuple(sorted(reason for reason, passed in checks.items() if not passed))
            slice_evidence.append(
                PilotTenantSliceEvidence(
                    tenant_id=tenant_id,
                    slice_id=slice_policy.slice_id,
                    module_id=slice_policy.module_id,
                    module_state_present=row is not None,
                    module_status=module_status,
                    required_feature_count=len(slice_policy.required_feature_ids),
                    enabled_required_feature_count=enabled_required,
                    forbidden_feature_count=len(slice_policy.forbidden_feature_ids),
                    enabled_forbidden_feature_count=enabled_forbidden,
                    module_state_hash=_module_state_hash(row),
                    blocking_reasons=reasons,
                    ready=not reasons,
                )
            )
        tenant_evidence.append(
            PilotTenantEvidence(
                tenant_id=tenant_id,
                slices=tuple(slice_evidence),
                ready_slice_count=sum(item.ready for item in slice_evidence),
                ready=all(item.ready for item in slice_evidence),
            )
        )

    released_operations = {operation for item in business_gate.slices for operation in item.required_api_operations}
    route_scope_verified = released_operations == set(policy.allowed_api_operations)
    monitoring_verified = bool(policy.monitoring_controls) and all(
        item.required_before_start and not item.destructive_action_allowed for item in policy.monitoring_controls
    )
    rollback_verified = bool(policy.rollback_controls) and all(
        item.required_before_start and not item.destructive_action_allowed for item in policy.rollback_controls
    )
    global_checks = {
        "business_backend_release_not_ready": business_gate.release_ready,
        "release_schema_version_mismatch": business_gate.schema_version == policy.required_release_schema_version,
        "candidate_tenant_selection_missing": bool(normalized_tenants),
        "candidate_tenant_limit_exceeded": len(normalized_tenants) <= policy.max_candidate_tenants,
        "candidate_tenant_selection_contains_duplicates": len(requested_tenants) == len(normalized_tenants),
        "pilot_route_scope_contract_mismatch": route_scope_verified,
        "monitoring_contract_not_verified": monitoring_verified,
        "rollback_contract_not_verified": rollback_verified,
        "human_admission_not_required": policy.human_admission_required,
        "traffic_scope_enforcement_not_required": policy.traffic_scope_enforcement_required,
        "automatic_tenant_activation_allowed": not policy.automatic_tenant_activation_allowed,
        "destructive_rollback_allowed": not policy.destructive_rollback_allowed,
    }
    global_reasons = [reason for reason, passed in global_checks.items() if not passed]
    global_reasons.extend(f"tenant_not_ready:{item.tenant_id}" for item in tenant_evidence if not item.ready)
    preflight_ready = not global_reasons
    draft = ProductivityPilotPreflightGate(
        checked_at_utc=checked_at_utc or datetime.now(UTC).isoformat(),
        runtime_environment=business_gate.runtime_environment,
        policy_id=policy.policy_id,
        policy_hash=build_productivity_pilot_policy_hash(policy),
        business_backend_release_gate_hash=business_gate.gate_hash,
        business_backend_release_ready=business_gate.release_ready,
        candidate_tenant_ids=normalized_tenants,
        candidate_tenant_count=len(normalized_tenants),
        maximum_candidate_tenant_count=policy.max_candidate_tenants,
        tenant_module_state_manifest_hash=_tenant_module_state_manifest_hash(tenant_module_rows),
        tenants=tuple(tenant_evidence),
        ready_tenant_count=sum(item.ready for item in tenant_evidence),
        productive_slice_count=len(policy.slices),
        route_scope_contract_verified=route_scope_verified,
        monitoring_contract_verified=monitoring_verified,
        monitoring_control_count=len(policy.monitoring_controls),
        rollback_contract_verified=rollback_verified,
        rollback_control_count=len(policy.rollback_controls),
        human_admission_required=policy.human_admission_required,
        traffic_scope_enforcement_required=policy.traffic_scope_enforcement_required,
        blocking_reasons=tuple(sorted(global_reasons)),
        preflight_ready=preflight_ready,
        next_action=(
            "record_explicit_human_pilot_admission_and_enforce_traffic_scope"
            if preflight_ready
            else "resolve_productivity_pilot_preflight_blockers"
        ),
        gate_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(update={"gate_hash": build_productivity_pilot_preflight_gate_hash(draft)})


def build_productivity_pilot_preflight_gate_hash(gate: ProductivityPilotPreflightGate) -> str:
    return sha256_bytes(
        json.dumps(
            gate.model_dump(mode="json", exclude={"gate_hash"}),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    )


def persist_productivity_pilot_preflight_gate(
    *,
    database_dsn: str,
    gate: ProductivityPilotPreflightGate,
) -> ProductivityPilotPreflightGate:
    if build_productivity_pilot_preflight_gate_hash(gate) != gate.gate_hash:
        raise ValueError("productivity pilot preflight gate hash is invalid")
    if not gate.preflight_ready:
        raise ValueError("only ready productivity pilot preflight evidence may be persisted")
    with psycopg.connect(database_dsn) as connection, connection.transaction():
        connection.execute(
            """
            INSERT INTO collabio.productivity_pilot_preflight_reports (
                gate_hash, checked_at_utc, policy_hash,
                business_backend_release_gate_hash, tenant_module_state_manifest_hash,
                candidate_tenant_ids, report, schema_version
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (gate_hash) DO NOTHING
            """,
            (
                gate.gate_hash,
                gate.checked_at_utc,
                gate.policy_hash,
                gate.business_backend_release_gate_hash,
                gate.tenant_module_state_manifest_hash,
                Jsonb(list(gate.candidate_tenant_ids)),
                Jsonb(gate.model_dump(mode="json")),
                gate.schema_version,
            ),
        )
    return gate


def load_productivity_pilot_preflight_gate(
    *,
    database_dsn: str,
    tenant_id: str,
    gate_hash: str,
) -> ProductivityPilotPreflightGate:
    if not TENANT_ID_PATTERN.fullmatch(tenant_id):
        raise ValueError("tenant ID has an invalid format")
    with psycopg.connect(database_dsn) as connection, connection.transaction():
        connection.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))
        row = connection.execute(
            """
            SELECT report
            FROM collabio.productivity_pilot_preflight_reports
            WHERE gate_hash = %s
            """,
            (gate_hash,),
        ).fetchone()
    if row is None:
        raise KeyError("authoritative productivity pilot preflight evidence not found")
    gate = ProductivityPilotPreflightGate.model_validate(row[0])
    if build_productivity_pilot_preflight_gate_hash(gate) != gate.gate_hash:
        raise ValueError("persisted productivity pilot preflight gate hash is invalid")
    if tenant_id not in gate.candidate_tenant_ids:
        raise KeyError("authoritative productivity pilot preflight evidence not found")
    return gate


def _load_tenant_module_rows(
    *,
    database_dsn: str,
    tenant_ids: tuple[str, ...],
    module_ids: tuple[str, ...],
) -> list[dict[str, object]]:
    with psycopg.connect(database_dsn, row_factory=dict_row) as connection:
        rows = connection.execute(
            """
            SELECT tenant_id, module_id, status, enabled_features
            FROM collabio.tenant_modules
            WHERE tenant_id = ANY(%s) AND module_id = ANY(%s)
            ORDER BY tenant_id, module_id
            """,
            (list(tenant_ids), list(module_ids)),
        ).fetchall()
    return [dict(row) for row in rows]


def run_productivity_pilot_preflight_from_environment(
    env: Mapping[str, str],
) -> ProductivityPilotPreflightGate:
    business_gate = load_business_backend_release_gate(
        Path(
            env.get(
                "SUITE_BUSINESS_BACKEND_RELEASE_GATE_REPORT_PATH",
                "/backups/business-backend-release-gate.json",
            )
        )
    )
    policy = load_productivity_pilot_policy(
        Path(
            env.get(
                "SUITE_PRODUCTIVITY_PILOT_POLICY_PATH",
                "/workspace/docs/operations/productivity_pilot_policy.json",
            )
        )
    )
    tenant_ids = tuple(
        item.strip() for item in env.get("SUITE_PRODUCTIVITY_PILOT_TENANT_IDS", "").split(",") if item.strip()
    )
    module_ids = tuple(item.module_id for item in policy.slices)
    rows = _load_tenant_module_rows(
        database_dsn=env["SUITE_POSTGRES_RESTORE_SOURCE_DSN"],
        tenant_ids=tenant_ids,
        module_ids=module_ids,
    )
    gate = build_productivity_pilot_preflight_gate(
        business_gate=business_gate,
        policy=policy,
        candidate_tenant_ids=tenant_ids,
        tenant_module_rows=rows,
    )
    evidence_dsn = env.get("SUITE_PRODUCTIVITY_PILOT_EVIDENCE_DSN", "").strip()
    if evidence_dsn and gate.preflight_ready:
        persist_productivity_pilot_preflight_gate(database_dsn=evidence_dsn, gate=gate)
    return gate


def main() -> None:
    gate = run_productivity_pilot_preflight_from_environment(os.environ)
    print(json.dumps(gate.model_dump(mode="json"), sort_keys=True))
    raise SystemExit(0 if gate.preflight_ready else 2)


if __name__ == "__main__":
    main()
