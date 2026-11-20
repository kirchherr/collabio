from __future__ import annotations

import json
import os
import re
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, Self

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.models import UserContext
from suite.platform.productivity_pilot_admission import (
    ProductivityPilotPreflightStore,
)
from suite.platform.productivity_pilot_closure_report import (
    ProductivityPilotClosureReportStore,
    build_productivity_pilot_closure_report_hash,
)
from suite.platform.productivity_pilot_runtime_window import (
    build_productivity_pilot_principal_observation_hash,
)
from suite.storage.source_objects import sha256_bytes

PRODUCTIVITY_PILOT_REAL_USER_NOMINATION_SCHEMA_VERSION = "productivity_pilot_real_user_nomination.v1"
PRODUCTIVITY_PILOT_REAL_USER_ADMISSION_SCHEMA_VERSION = "productivity_pilot_real_user_admission.v1"
PRODUCTIVITY_PILOT_REAL_USER_NOMINATION_CONFIRMATION_STATEMENT = (
    "I explicitly nominate the listed active tenant principals for the stated, time-bounded "
    "productivity pilot purpose. This records metadata-only preparation and does not activate "
    "modules, open the runtime switch, authorize traffic, or execute business writes."
)
PRODUCTIVITY_PILOT_REAL_USER_ADMISSION_CONFIRMATION_STATEMENT = (
    "I independently approve this real-user productivity pilot nomination after verifying current "
    "identity, role, privacy, recovery, and control evidence. This approval remains non-executing "
    "and does not activate modules, open the runtime switch, authorize traffic, or execute writes."
)

SHA256_PATTERN = re.compile(r"^sha256:[a-f0-9]{64}$")
REFERENCE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_+.-]*:.+")
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,127}$")
PURPOSE_CODE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{2,127}$")
ROLE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,127}$")
ALLOWED_DATA_CLASSIFICATIONS = {"internal", "confidential"}
MAX_REAL_USER_PILOT_PRINCIPALS = 25
MAX_REAL_USER_PILOT_DURATION = timedelta(days=30)
MAX_CONTROL_EVIDENCE_AGE = timedelta(hours=24)
MAX_CLOCK_SKEW = timedelta(minutes=5)


class ProductivityPilotRealUserAdmissionConflict(ValueError):
    pass


class ProductivityPilotRealUserNominationNotFound(LookupError):
    pass


class ProductivityPilotParticipantIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal_id: str
    required_role_ids: tuple[str, ...]
    participation_notice_ref: str
    training_evidence_ref: str

    @field_validator("principal_id")
    @classmethod
    def require_principal_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized or len(normalized) > 255:
            raise ValueError("pilot principal ID must be present and bounded")
        return normalized

    @field_validator("required_role_ids")
    @classmethod
    def require_roles(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(sorted(set(value)))
        if not normalized or len(normalized) != len(value):
            raise ValueError("pilot participant roles must be present and unique")
        if any(not ROLE_ID_PATTERN.fullmatch(role_id) for role_id in normalized):
            raise ValueError("pilot participant role ID has an invalid format")
        return normalized

    @field_validator("participation_notice_ref", "training_evidence_ref")
    @classmethod
    def require_typed_reference(cls, value: str) -> str:
        if not REFERENCE_PATTERN.fullmatch(value):
            raise ValueError("pilot participant evidence references must be typed")
        return value


class ProductivityPilotPrincipalSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal_id: str
    role_ids: tuple[str, ...]
    active: bool = True


class ProductivityPilotParticipantDirectory(Protocol):
    def active_principal(self, *, tenant_id: str, principal_id: str) -> ProductivityPilotPrincipalSnapshot: ...


class InMemoryProductivityPilotParticipantDirectory:
    def __init__(
        self,
        snapshots: Mapping[tuple[str, str], ProductivityPilotPrincipalSnapshot] | None = None,
    ) -> None:
        self._snapshots = dict(snapshots or self._default_snapshots())

    @staticmethod
    def _default_snapshots() -> dict[tuple[str, str], ProductivityPilotPrincipalSnapshot]:
        tenant_id = "tenant-demo"
        return {
            (tenant_id, "user-demo"): ProductivityPilotPrincipalSnapshot(
                principal_id="user-demo",
                role_ids=("knowledge-worker",),
            ),
            (tenant_id, "tenant-admin-demo"): ProductivityPilotPrincipalSnapshot(
                principal_id="tenant-admin-demo",
                role_ids=("tenant-admin",),
            ),
            (tenant_id, "security-admin-demo"): ProductivityPilotPrincipalSnapshot(
                principal_id="security-admin-demo",
                role_ids=("security-admin",),
            ),
        }

    def active_principal(self, *, tenant_id: str, principal_id: str) -> ProductivityPilotPrincipalSnapshot:
        snapshot = self._snapshots.get((tenant_id, principal_id))
        if snapshot is None or not snapshot.active:
            raise ProductivityPilotRealUserAdmissionConflict(
                "nominated principal is not an active member of the tenant"
            )
        return snapshot


class PgProductivityPilotParticipantDirectory:
    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    def active_principal(self, *, tenant_id: str, principal_id: str) -> ProductivityPilotPrincipalSnapshot:
        with psycopg.connect(self.database_dsn) as connection, connection.transaction():
            _set_tenant(connection, tenant_id)
            row = connection.execute(
                """
                SELECT principal.user_id,
                       COALESCE(array_agg(assignment.role_id ORDER BY assignment.role_id)
                           FILTER (WHERE assignment.role_id IS NOT NULL), ARRAY[]::text[])
                FROM collabio.tenant_principals AS principal
                JOIN collabio.tenant_principal_memberships AS membership
                  ON membership.tenant_id = principal.tenant_id
                 AND membership.issuer = principal.issuer
                 AND membership.subject = principal.subject
                 AND membership.status = 'active'
                LEFT JOIN collabio.tenant_principal_role_assignments AS assignment
                  ON assignment.tenant_id = principal.tenant_id
                 AND assignment.issuer = principal.issuer
                 AND assignment.subject = principal.subject
                 AND assignment.status = 'active'
                LEFT JOIN collabio.tenant_roles AS role
                  ON role.tenant_id = assignment.tenant_id
                 AND role.role_id = assignment.role_id
                 AND role.status = 'active'
                WHERE principal.tenant_id = %s
                  AND principal.user_id = %s
                  AND principal.status = 'active'
                  AND (assignment.role_id IS NULL OR role.role_id IS NOT NULL)
                GROUP BY principal.user_id
                """,
                (tenant_id, principal_id),
            ).fetchone()
        if row is None:
            raise ProductivityPilotRealUserAdmissionConflict(
                "nominated principal is not an active member of the tenant"
            )
        return ProductivityPilotPrincipalSnapshot(
            principal_id=str(row[0]),
            role_ids=tuple(str(role_id) for role_id in row[1]),
        )


class ProductivityPilotParticipantEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    principal_id_hash: str
    authoritative_role_ids: tuple[str, ...]
    role_manifest_hash: str
    participation_notice_evidence_hash: str
    training_evidence_hash: str

    @field_validator(
        "principal_id_hash",
        "role_manifest_hash",
        "participation_notice_evidence_hash",
        "training_evidence_hash",
    )
    @classmethod
    def require_hash(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("pilot participant evidence must use sha256")
        return value


class ProductivityPilotRealUserNominationCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nomination_id: str
    baseline_closure_evidence_hash: str
    purpose_code: str
    purpose_ref: str
    lawful_basis_ref: str
    privacy_risk_assessment_ref: str
    retention_policy_id: str
    data_classification: str
    participants: tuple[ProductivityPilotParticipantIdentity, ...]
    scheduled_start_at_utc: datetime
    scheduled_end_at_utc: datetime
    dpia_required: bool
    dpia_ref: str | None = None
    works_council_review_required: bool
    works_council_approval_ref: str | None = None
    idempotency_key_ref: str
    change_request_ref: str
    human_confirmation_reference: str
    human_confirmation_statement: str
    audit_chain_ref: str
    nominated_at_utc: datetime
    nomination_requested: bool = True
    runtime_activation_requested: bool = False
    traffic_authorization_requested: bool = False
    business_write_requested: bool = False
    destructive_action_requested: bool = False
    external_action_requested: bool = False
    content_included: bool = False

    @field_validator("nomination_id", "retention_policy_id")
    @classmethod
    def require_id(cls, value: str) -> str:
        if not ID_PATTERN.fullmatch(value):
            raise ValueError("real-user pilot ID has an invalid format")
        return value

    @field_validator("baseline_closure_evidence_hash")
    @classmethod
    def require_hash(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("real-user pilot closure evidence must use sha256")
        return value

    @field_validator("purpose_code")
    @classmethod
    def require_purpose_code(cls, value: str) -> str:
        if not PURPOSE_CODE_PATTERN.fullmatch(value):
            raise ValueError("real-user pilot purpose code has an invalid format")
        return value

    @field_validator(
        "purpose_ref",
        "lawful_basis_ref",
        "privacy_risk_assessment_ref",
        "idempotency_key_ref",
        "change_request_ref",
        "human_confirmation_reference",
        "audit_chain_ref",
    )
    @classmethod
    def require_typed_reference(cls, value: str) -> str:
        if not REFERENCE_PATTERN.fullmatch(value):
            raise ValueError("real-user pilot references must be typed")
        return value

    @field_validator("dpia_ref", "works_council_approval_ref")
    @classmethod
    def require_optional_typed_reference(cls, value: str | None) -> str | None:
        if value is not None and not REFERENCE_PATTERN.fullmatch(value):
            raise ValueError("conditional real-user pilot references must be typed")
        return value

    @field_validator("data_classification")
    @classmethod
    def require_classification(cls, value: str) -> str:
        if value not in ALLOWED_DATA_CLASSIFICATIONS:
            raise ValueError("real-user pilot classification is not allowed")
        return value

    @field_validator("participants")
    @classmethod
    def require_participants(
        cls, value: tuple[ProductivityPilotParticipantIdentity, ...]
    ) -> tuple[ProductivityPilotParticipantIdentity, ...]:
        principal_ids = [participant.principal_id for participant in value]
        if not value or len(value) > MAX_REAL_USER_PILOT_PRINCIPALS or len(principal_ids) != len(set(principal_ids)):
            raise ValueError("real-user pilot principals must be present, unique, and bounded")
        return value

    @field_validator("human_confirmation_statement")
    @classmethod
    def require_confirmation(cls, value: str) -> str:
        if value != PRODUCTIVITY_PILOT_REAL_USER_NOMINATION_CONFIRMATION_STATEMENT:
            raise ValueError("exact real-user pilot nomination confirmation statement required")
        return value

    @field_validator("scheduled_start_at_utc", "scheduled_end_at_utc", "nominated_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("real-user pilot timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def require_metadata_only_nomination(self) -> Self:
        start = _utc(self.scheduled_start_at_utc)
        end = _utc(self.scheduled_end_at_utc)
        nominated = _utc(self.nominated_at_utc)
        if start < nominated or end <= start or end - start > MAX_REAL_USER_PILOT_DURATION:
            raise ValueError("real-user pilot schedule must be future, ordered, and at most 30 days")
        if self.dpia_required != (self.dpia_ref is not None):
            raise ValueError("DPIA reference must match the risk assessment outcome")
        if self.works_council_review_required != (self.works_council_approval_ref is not None):
            raise ValueError("works council approval reference must match the review outcome")
        if (
            not self.nomination_requested
            or self.runtime_activation_requested
            or self.traffic_authorization_requested
            or self.business_write_requested
            or self.destructive_action_requested
            or self.external_action_requested
            or self.content_included
        ):
            raise ValueError("real-user pilot nomination must remain metadata-only and non-executing")
        return self


class ProductivityPilotRealUserNomination(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    nomination_id: str
    baseline_closure_id: str
    baseline_closure_evidence_hash: str
    purpose_code: str
    purpose_ref: str
    lawful_basis_ref: str
    privacy_risk_assessment_ref: str
    retention_policy_id: str
    data_classification: str
    participants: tuple[ProductivityPilotParticipantEvidence, ...]
    participant_manifest_hash: str
    participant_count: int = Field(ge=1, le=MAX_REAL_USER_PILOT_PRINCIPALS)
    scheduled_start_at_utc: datetime
    scheduled_end_at_utc: datetime
    dpia_required: bool
    dpia_ref: str | None
    works_council_review_required: bool
    works_council_approval_ref: str | None
    command_hash: str
    idempotency_key_hash: str
    human_confirmation_statement_hash: str
    change_request_ref: str
    human_confirmation_reference: str
    audit_chain_ref: str
    nominated_by_principal_hash: str
    nominated_at_utc: datetime
    authoritative_principals_verified: bool = True
    authoritative_roles_verified: bool = True
    purpose_limitation_recorded: bool = True
    privacy_review_recorded: bool = True
    nomination_recorded: bool = True
    security_approval_recorded: bool = False
    runtime_activation_allowed: bool = False
    traffic_authorization_allowed: bool = False
    business_write_executed: bool = False
    destructive_action_executed: bool = False
    external_side_effect_executed: bool = False
    content_included: bool = False
    idempotent_replay: bool = False
    next_action: str = "refresh_controls_and_record_independent_security_admission"
    evidence_hash: str
    schema_version: str = PRODUCTIVITY_PILOT_REAL_USER_NOMINATION_SCHEMA_VERSION

    @model_validator(mode="after")
    def require_non_executing_record(self) -> Self:
        if (
            self.schema_version != PRODUCTIVITY_PILOT_REAL_USER_NOMINATION_SCHEMA_VERSION
            or len(self.participants) != self.participant_count
            or not self.authoritative_principals_verified
            or not self.authoritative_roles_verified
            or not self.purpose_limitation_recorded
            or not self.privacy_review_recorded
            or not self.nomination_recorded
            or self.security_approval_recorded
            or self.runtime_activation_allowed
            or self.traffic_authorization_allowed
            or self.business_write_executed
            or self.destructive_action_executed
            or self.external_side_effect_executed
            or self.content_included
        ):
            raise ValueError("real-user pilot nomination violates the non-executing boundary")
        return self


class ProductivityPilotRealUserAdmissionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    admission_id: str
    nomination_id: str
    nomination_evidence_hash: str
    participants: tuple[ProductivityPilotParticipantIdentity, ...]
    preflight_gate_hash: str
    policy_hash: str
    business_backend_release_gate_hash: str
    tenant_module_state_manifest_hash: str
    backup_sha256: str
    postgres_restore_drill_report_hash: str
    backend_foundation_gate_hash: str
    control_evidence_observed_at_utc: datetime
    security_review_ref: str
    privacy_approval_ref: str
    idempotency_key_ref: str
    change_request_ref: str
    human_confirmation_reference: str
    human_confirmation_statement: str
    audit_chain_ref: str
    approved_at_utc: datetime
    admission_requested: bool = True
    runtime_activation_requested: bool = False
    traffic_authorization_requested: bool = False
    business_write_requested: bool = False
    destructive_action_requested: bool = False
    external_action_requested: bool = False
    content_included: bool = False

    @field_validator("admission_id", "nomination_id")
    @classmethod
    def require_id(cls, value: str) -> str:
        if not ID_PATTERN.fullmatch(value):
            raise ValueError("real-user pilot admission ID has an invalid format")
        return value

    @field_validator(
        "nomination_evidence_hash",
        "preflight_gate_hash",
        "policy_hash",
        "business_backend_release_gate_hash",
        "tenant_module_state_manifest_hash",
        "backup_sha256",
        "postgres_restore_drill_report_hash",
        "backend_foundation_gate_hash",
    )
    @classmethod
    def require_hash(cls, value: str) -> str:
        if not SHA256_PATTERN.fullmatch(value):
            raise ValueError("real-user pilot admission evidence must use sha256")
        return value

    @field_validator(
        "security_review_ref",
        "privacy_approval_ref",
        "idempotency_key_ref",
        "change_request_ref",
        "human_confirmation_reference",
        "audit_chain_ref",
    )
    @classmethod
    def require_typed_reference(cls, value: str) -> str:
        if not REFERENCE_PATTERN.fullmatch(value):
            raise ValueError("real-user pilot admission references must be typed")
        return value

    @field_validator("participants")
    @classmethod
    def require_participants(
        cls, value: tuple[ProductivityPilotParticipantIdentity, ...]
    ) -> tuple[ProductivityPilotParticipantIdentity, ...]:
        principal_ids = [participant.principal_id for participant in value]
        if not value or len(value) > MAX_REAL_USER_PILOT_PRINCIPALS or len(principal_ids) != len(set(principal_ids)):
            raise ValueError("real-user pilot principals must be present, unique, and bounded")
        return value

    @field_validator("human_confirmation_statement")
    @classmethod
    def require_confirmation(cls, value: str) -> str:
        if value != PRODUCTIVITY_PILOT_REAL_USER_ADMISSION_CONFIRMATION_STATEMENT:
            raise ValueError("exact real-user pilot admission confirmation statement required")
        return value

    @field_validator("control_evidence_observed_at_utc", "approved_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("real-user pilot admission timestamps must include a timezone")
        return value

    @model_validator(mode="after")
    def require_non_executing_admission(self) -> Self:
        if (
            not self.admission_requested
            or self.runtime_activation_requested
            or self.traffic_authorization_requested
            or self.business_write_requested
            or self.destructive_action_requested
            or self.external_action_requested
            or self.content_included
        ):
            raise ValueError("real-user pilot admission must remain metadata-only and non-executing")
        return self


class ProductivityPilotRealUserAdmission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    admission_id: str
    nomination_id: str
    nomination_evidence_hash: str
    baseline_closure_evidence_hash: str
    participant_manifest_hash: str
    participant_count: int = Field(ge=1, le=MAX_REAL_USER_PILOT_PRINCIPALS)
    approved_principal_hashes: tuple[str, ...]
    preflight_gate_hash: str
    policy_hash: str
    business_backend_release_gate_hash: str
    tenant_module_state_manifest_hash: str
    backup_sha256: str
    postgres_restore_drill_report_hash: str
    backend_foundation_gate_hash: str
    control_evidence_observed_at_utc: datetime
    scheduled_start_at_utc: datetime
    scheduled_end_at_utc: datetime
    security_review_ref: str
    privacy_approval_ref: str
    command_hash: str
    idempotency_key_hash: str
    human_confirmation_statement_hash: str
    change_request_ref: str
    human_confirmation_reference: str
    audit_chain_ref: str
    approved_by_principal_hash: str
    approved_at_utc: datetime
    current_principals_verified: bool = True
    current_roles_verified: bool = True
    purpose_and_privacy_binding_verified: bool = True
    fresh_control_evidence_verified: bool = True
    four_eyes_verified: bool = True
    security_admission_recorded: bool = True
    runtime_activation_allowed: bool = False
    traffic_authorization_allowed: bool = False
    business_write_executed: bool = False
    destructive_action_executed: bool = False
    external_side_effect_executed: bool = False
    content_included: bool = False
    idempotent_replay: bool = False
    next_action: str = "create_new_start_chain_and_hash_only_runtime_binding"
    evidence_hash: str
    schema_version: str = PRODUCTIVITY_PILOT_REAL_USER_ADMISSION_SCHEMA_VERSION

    @model_validator(mode="after")
    def require_non_executing_record(self) -> Self:
        if (
            self.schema_version != PRODUCTIVITY_PILOT_REAL_USER_ADMISSION_SCHEMA_VERSION
            or len(self.approved_principal_hashes) != self.participant_count
            or not self.current_principals_verified
            or not self.current_roles_verified
            or not self.purpose_and_privacy_binding_verified
            or not self.fresh_control_evidence_verified
            or not self.four_eyes_verified
            or not self.security_admission_recorded
            or self.runtime_activation_allowed
            or self.traffic_authorization_allowed
            or self.business_write_executed
            or self.destructive_action_executed
            or self.external_side_effect_executed
            or self.content_included
        ):
            raise ValueError("real-user pilot admission violates the non-executing boundary")
        return self


def _canonical_hash(value: object) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ProductivityPilotRealUserAdmissionConflict("authoritative preflight timestamp has no timezone")
    return _utc(parsed)


def _set_tenant(connection: psycopg.Connection[Any], tenant_id: str) -> None:
    connection.execute("SELECT set_config('app.tenant_id', %s, true)", (tenant_id,))


def build_productivity_pilot_real_user_nomination_hash(
    record: ProductivityPilotRealUserNomination,
) -> str:
    return _canonical_hash(record.model_dump(mode="json", exclude={"evidence_hash", "idempotent_replay"}))


def build_productivity_pilot_real_user_admission_hash(
    record: ProductivityPilotRealUserAdmission,
) -> str:
    return _canonical_hash(record.model_dump(mode="json", exclude={"evidence_hash", "idempotent_replay"}))


class ProductivityPilotRealUserAdmissionStore(Protocol):
    def append_nomination(self, record: ProductivityPilotRealUserNomination) -> ProductivityPilotRealUserNomination: ...

    def nomination_for_idempotency(
        self, *, tenant_id: str, idempotency_key_hash: str
    ) -> ProductivityPilotRealUserNomination | None: ...

    def current_nomination(self, *, tenant_id: str) -> ProductivityPilotRealUserNomination | None: ...

    def append_admission(self, record: ProductivityPilotRealUserAdmission) -> ProductivityPilotRealUserAdmission: ...

    def admission_for_idempotency(
        self, *, tenant_id: str, idempotency_key_hash: str
    ) -> ProductivityPilotRealUserAdmission | None: ...

    def current_admission(self, *, tenant_id: str) -> ProductivityPilotRealUserAdmission | None: ...


class InMemoryProductivityPilotRealUserAdmissionStore:
    def __init__(
        self,
        *,
        nominations: Iterable[ProductivityPilotRealUserNomination] = (),
        admissions: Iterable[ProductivityPilotRealUserAdmission] = (),
    ) -> None:
        self.nominations: list[ProductivityPilotRealUserNomination] = []
        self.admissions: list[ProductivityPilotRealUserAdmission] = []
        for nomination in nominations:
            self.append_nomination(nomination)
        for admission in admissions:
            self.append_admission(admission)

    def append_nomination(self, record: ProductivityPilotRealUserNomination) -> ProductivityPilotRealUserNomination:
        if build_productivity_pilot_real_user_nomination_hash(record) != record.evidence_hash:
            raise ValueError("real-user pilot nomination hash is invalid")
        if any(
            item.tenant_id == record.tenant_id
            and (item.nomination_id == record.nomination_id or item.idempotency_key_hash == record.idempotency_key_hash)
            for item in self.nominations
        ):
            raise ProductivityPilotRealUserAdmissionConflict("real-user pilot nomination already exists")
        self.nominations.append(record)
        return record

    def nomination_for_idempotency(
        self, *, tenant_id: str, idempotency_key_hash: str
    ) -> ProductivityPilotRealUserNomination | None:
        return next(
            (
                item
                for item in reversed(self.nominations)
                if item.tenant_id == tenant_id and item.idempotency_key_hash == idempotency_key_hash
            ),
            None,
        )

    def current_nomination(self, *, tenant_id: str) -> ProductivityPilotRealUserNomination | None:
        return next(
            (item for item in reversed(self.nominations) if item.tenant_id == tenant_id),
            None,
        )

    def append_admission(self, record: ProductivityPilotRealUserAdmission) -> ProductivityPilotRealUserAdmission:
        if build_productivity_pilot_real_user_admission_hash(record) != record.evidence_hash:
            raise ValueError("real-user pilot admission hash is invalid")
        if any(
            item.tenant_id == record.tenant_id
            and (
                item.admission_id == record.admission_id
                or item.nomination_id == record.nomination_id
                or item.idempotency_key_hash == record.idempotency_key_hash
            )
            for item in self.admissions
        ):
            raise ProductivityPilotRealUserAdmissionConflict("real-user pilot admission already exists")
        self.admissions.append(record)
        return record

    def admission_for_idempotency(
        self, *, tenant_id: str, idempotency_key_hash: str
    ) -> ProductivityPilotRealUserAdmission | None:
        return next(
            (
                item
                for item in reversed(self.admissions)
                if item.tenant_id == tenant_id and item.idempotency_key_hash == idempotency_key_hash
            ),
            None,
        )

    def current_admission(self, *, tenant_id: str) -> ProductivityPilotRealUserAdmission | None:
        return next(
            (item for item in reversed(self.admissions) if item.tenant_id == tenant_id),
            None,
        )


class PgProductivityPilotRealUserAdmissionStore:
    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    def append_nomination(self, record: ProductivityPilotRealUserNomination) -> ProductivityPilotRealUserNomination:
        if build_productivity_pilot_real_user_nomination_hash(record) != record.evidence_hash:
            raise ValueError("real-user pilot nomination hash is invalid")
        try:
            with psycopg.connect(self.database_dsn) as connection, connection.transaction():
                _set_tenant(connection, record.tenant_id)
                connection.execute(
                    """
                    INSERT INTO collabio.productivity_pilot_real_user_nominations (
                        tenant_id, nomination_id, baseline_closure_id,
                        baseline_closure_evidence_hash, participant_manifest_hash,
                        participant_count, scheduled_start_at_utc, scheduled_end_at_utc,
                        command_hash, idempotency_key_hash,
                        human_confirmation_statement_hash, nominated_by_principal_hash,
                        nominated_at_utc, nomination_record, evidence_hash, schema_version
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        record.tenant_id,
                        record.nomination_id,
                        record.baseline_closure_id,
                        record.baseline_closure_evidence_hash,
                        record.participant_manifest_hash,
                        record.participant_count,
                        record.scheduled_start_at_utc,
                        record.scheduled_end_at_utc,
                        record.command_hash,
                        record.idempotency_key_hash,
                        record.human_confirmation_statement_hash,
                        record.nominated_by_principal_hash,
                        record.nominated_at_utc,
                        Jsonb(record.model_dump(mode="json")),
                        record.evidence_hash,
                        record.schema_version,
                    ),
                )
        except psycopg.errors.UniqueViolation as exc:
            raise ProductivityPilotRealUserAdmissionConflict("real-user pilot nomination already exists") from exc
        return record

    def nomination_for_idempotency(
        self, *, tenant_id: str, idempotency_key_hash: str
    ) -> ProductivityPilotRealUserNomination | None:
        return self._nomination_one(
            tenant_id=tenant_id,
            where_sql="idempotency_key_hash = %s",
            value=idempotency_key_hash,
        )

    def current_nomination(self, *, tenant_id: str) -> ProductivityPilotRealUserNomination | None:
        return self._nomination_one(
            tenant_id=tenant_id,
            where_sql="TRUE",
            value=None,
            order_sql="ORDER BY nominated_at_utc DESC, evidence_hash DESC",
        )

    def append_admission(self, record: ProductivityPilotRealUserAdmission) -> ProductivityPilotRealUserAdmission:
        if build_productivity_pilot_real_user_admission_hash(record) != record.evidence_hash:
            raise ValueError("real-user pilot admission hash is invalid")
        try:
            with psycopg.connect(self.database_dsn) as connection, connection.transaction():
                _set_tenant(connection, record.tenant_id)
                connection.execute(
                    """
                    INSERT INTO collabio.productivity_pilot_real_user_admissions (
                        tenant_id, admission_id, nomination_id, nomination_evidence_hash,
                        participant_manifest_hash, participant_count, preflight_gate_hash,
                        backup_sha256, postgres_restore_drill_report_hash,
                        backend_foundation_gate_hash, control_evidence_observed_at_utc,
                        scheduled_start_at_utc, scheduled_end_at_utc, command_hash,
                        idempotency_key_hash, human_confirmation_statement_hash,
                        approved_by_principal_hash, approved_at_utc, admission_record,
                        evidence_hash, schema_version
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        record.tenant_id,
                        record.admission_id,
                        record.nomination_id,
                        record.nomination_evidence_hash,
                        record.participant_manifest_hash,
                        record.participant_count,
                        record.preflight_gate_hash,
                        record.backup_sha256,
                        record.postgres_restore_drill_report_hash,
                        record.backend_foundation_gate_hash,
                        record.control_evidence_observed_at_utc,
                        record.scheduled_start_at_utc,
                        record.scheduled_end_at_utc,
                        record.command_hash,
                        record.idempotency_key_hash,
                        record.human_confirmation_statement_hash,
                        record.approved_by_principal_hash,
                        record.approved_at_utc,
                        Jsonb(record.model_dump(mode="json")),
                        record.evidence_hash,
                        record.schema_version,
                    ),
                )
        except psycopg.errors.UniqueViolation as exc:
            raise ProductivityPilotRealUserAdmissionConflict("real-user pilot admission already exists") from exc
        return record

    def admission_for_idempotency(
        self, *, tenant_id: str, idempotency_key_hash: str
    ) -> ProductivityPilotRealUserAdmission | None:
        return self._admission_one(
            tenant_id=tenant_id,
            where_sql="idempotency_key_hash = %s",
            value=idempotency_key_hash,
        )

    def current_admission(self, *, tenant_id: str) -> ProductivityPilotRealUserAdmission | None:
        return self._admission_one(
            tenant_id=tenant_id,
            where_sql="TRUE",
            value=None,
            order_sql="ORDER BY approved_at_utc DESC, evidence_hash DESC",
        )

    def _nomination_one(
        self,
        *,
        tenant_id: str,
        where_sql: str,
        value: str | None,
        order_sql: str = "",
    ) -> ProductivityPilotRealUserNomination | None:
        query = f"""
            SELECT nomination_record
            FROM collabio.productivity_pilot_real_user_nominations
            WHERE tenant_id = %s AND {where_sql}
            {order_sql}
            LIMIT 1
        """
        params: tuple[str, ...] = (tenant_id,) if value is None else (tenant_id, value)
        with psycopg.connect(self.database_dsn) as connection, connection.transaction():
            _set_tenant(connection, tenant_id)
            row = connection.execute(query, params).fetchone()
        if row is None:
            return None
        record = ProductivityPilotRealUserNomination.model_validate(row[0])
        if build_productivity_pilot_real_user_nomination_hash(record) != record.evidence_hash:
            raise ValueError("persisted real-user pilot nomination hash is invalid")
        return record

    def _admission_one(
        self,
        *,
        tenant_id: str,
        where_sql: str,
        value: str | None,
        order_sql: str = "",
    ) -> ProductivityPilotRealUserAdmission | None:
        query = f"""
            SELECT admission_record
            FROM collabio.productivity_pilot_real_user_admissions
            WHERE tenant_id = %s AND {where_sql}
            {order_sql}
            LIMIT 1
        """
        params: tuple[str, ...] = (tenant_id,) if value is None else (tenant_id, value)
        with psycopg.connect(self.database_dsn) as connection, connection.transaction():
            _set_tenant(connection, tenant_id)
            row = connection.execute(query, params).fetchone()
        if row is None:
            return None
        record = ProductivityPilotRealUserAdmission.model_validate(row[0])
        if build_productivity_pilot_real_user_admission_hash(record) != record.evidence_hash:
            raise ValueError("persisted real-user pilot admission hash is invalid")
        return record


class ProductivityPilotRealUserAdmissionService:
    def __init__(
        self,
        *,
        participant_directory: ProductivityPilotParticipantDirectory,
        closure_store: ProductivityPilotClosureReportStore,
        preflight_store: ProductivityPilotPreflightStore,
        record_store: ProductivityPilotRealUserAdmissionStore,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.participant_directory = participant_directory
        self.closure_store = closure_store
        self.preflight_store = preflight_store
        self.record_store = record_store
        self.clock = clock or (lambda: datetime.now(UTC))

    def nominate(
        self,
        *,
        user_context: UserContext,
        command: ProductivityPilotRealUserNominationCommand,
    ) -> ProductivityPilotRealUserNomination:
        if "tenant-admin" not in user_context.role_ids:
            raise PermissionError("tenant admin role required for real-user pilot nomination")
        now = _utc(self.clock())
        if abs(now - _utc(command.nominated_at_utc)) > MAX_CLOCK_SKEW:
            raise ProductivityPilotRealUserAdmissionConflict(
                "real-user pilot nomination timestamp is outside the allowed clock skew"
            )
        closure = self.closure_store.current(tenant_id=user_context.tenant_id)
        if closure is None:
            raise ProductivityPilotRealUserAdmissionConflict(
                "closed development pilot evidence is required before real-user nomination"
            )
        if (
            build_productivity_pilot_closure_report_hash(closure) != closure.evidence_hash
            or not closure.runtime_switch_closed
            or closure.evidence_hash != command.baseline_closure_evidence_hash
        ):
            raise ProductivityPilotRealUserAdmissionConflict(
                "real-user nomination does not match the authoritative closed pilot baseline"
            )

        participants = self._resolve_participants(
            tenant_id=user_context.tenant_id,
            participants=command.participants,
        )
        actor_hash = build_productivity_pilot_principal_observation_hash(
            tenant_id=user_context.tenant_id,
            principal_id=user_context.user_id,
        )
        if actor_hash in {item.principal_id_hash for item in participants}:
            raise ProductivityPilotRealUserAdmissionConflict("pilot nominator cannot be a nominated participant")
        command_hash = _canonical_hash(command.model_dump(mode="json"))
        idempotency_key_hash = _canonical_hash(
            {
                "schema_version": "productivity_pilot_real_user_nomination_idempotency.v1",
                "tenant_id": user_context.tenant_id,
                "idempotency_key_ref": command.idempotency_key_ref,
            }
        )
        existing = self.record_store.nomination_for_idempotency(
            tenant_id=user_context.tenant_id,
            idempotency_key_hash=idempotency_key_hash,
        )
        if existing is not None:
            if existing.command_hash != command_hash:
                raise ProductivityPilotRealUserAdmissionConflict(
                    "real-user nomination idempotency key was used for another command"
                )
            return existing.model_copy(update={"idempotent_replay": True})
        participant_manifest_hash = _canonical_hash(
            {
                "schema_version": "productivity_pilot_real_user_participant_manifest.v1",
                "tenant_id": user_context.tenant_id,
                "participants": [
                    item.model_dump(mode="json")
                    for item in sorted(participants, key=lambda item: item.principal_id_hash)
                ],
            }
        )
        draft = ProductivityPilotRealUserNomination(
            tenant_id=user_context.tenant_id,
            nomination_id=command.nomination_id,
            baseline_closure_id=closure.closure_id,
            baseline_closure_evidence_hash=closure.evidence_hash,
            purpose_code=command.purpose_code,
            purpose_ref=command.purpose_ref,
            lawful_basis_ref=command.lawful_basis_ref,
            privacy_risk_assessment_ref=command.privacy_risk_assessment_ref,
            retention_policy_id=command.retention_policy_id,
            data_classification=command.data_classification,
            participants=participants,
            participant_manifest_hash=participant_manifest_hash,
            participant_count=len(participants),
            scheduled_start_at_utc=command.scheduled_start_at_utc,
            scheduled_end_at_utc=command.scheduled_end_at_utc,
            dpia_required=command.dpia_required,
            dpia_ref=command.dpia_ref,
            works_council_review_required=command.works_council_review_required,
            works_council_approval_ref=command.works_council_approval_ref,
            command_hash=command_hash,
            idempotency_key_hash=idempotency_key_hash,
            human_confirmation_statement_hash=sha256_bytes(command.human_confirmation_statement.encode("utf-8")),
            change_request_ref=command.change_request_ref,
            human_confirmation_reference=command.human_confirmation_reference,
            audit_chain_ref=command.audit_chain_ref,
            nominated_by_principal_hash=actor_hash,
            nominated_at_utc=command.nominated_at_utc,
            evidence_hash="sha256:" + "0" * 64,
        )
        record = draft.model_copy(update={"evidence_hash": build_productivity_pilot_real_user_nomination_hash(draft)})
        return self.record_store.append_nomination(record)

    def approve(
        self,
        *,
        user_context: UserContext,
        command: ProductivityPilotRealUserAdmissionCommand,
    ) -> ProductivityPilotRealUserAdmission:
        if "security-admin" not in user_context.role_ids:
            raise PermissionError("security admin role required for real-user pilot admission")
        now = _utc(self.clock())
        approved_at = _utc(command.approved_at_utc)
        if abs(now - approved_at) > MAX_CLOCK_SKEW:
            raise ProductivityPilotRealUserAdmissionConflict(
                "real-user pilot approval timestamp is outside the allowed clock skew"
            )
        nomination = self.record_store.current_nomination(tenant_id=user_context.tenant_id)
        if (
            nomination is None
            or nomination.nomination_id != command.nomination_id
            or nomination.evidence_hash != command.nomination_evidence_hash
            or build_productivity_pilot_real_user_nomination_hash(nomination) != nomination.evidence_hash
        ):
            raise ProductivityPilotRealUserNominationNotFound("authoritative real-user pilot nomination not found")
        if approved_at >= _utc(nomination.scheduled_end_at_utc):
            raise ProductivityPilotRealUserAdmissionConflict("real-user pilot nomination is already expired")
        actor_hash = build_productivity_pilot_principal_observation_hash(
            tenant_id=user_context.tenant_id,
            principal_id=user_context.user_id,
        )
        if actor_hash == nomination.nominated_by_principal_hash:
            raise ProductivityPilotRealUserAdmissionConflict(
                "four-eyes control requires a security approver distinct from the nominator"
            )

        participants = self._resolve_participants(
            tenant_id=user_context.tenant_id,
            participants=command.participants,
        )
        if actor_hash in {item.principal_id_hash for item in participants}:
            raise ProductivityPilotRealUserAdmissionConflict("security approver cannot be a pilot participant")
        participant_manifest_hash = _canonical_hash(
            {
                "schema_version": "productivity_pilot_real_user_participant_manifest.v1",
                "tenant_id": user_context.tenant_id,
                "participants": [
                    item.model_dump(mode="json")
                    for item in sorted(participants, key=lambda item: item.principal_id_hash)
                ],
            }
        )
        if participant_manifest_hash != nomination.participant_manifest_hash:
            raise ProductivityPilotRealUserAdmissionConflict(
                "participant identity, role, notice, or training evidence changed after nomination"
            )

        closure = self.closure_store.current(tenant_id=user_context.tenant_id)
        if (
            closure is None
            or closure.evidence_hash != nomination.baseline_closure_evidence_hash
            or build_productivity_pilot_closure_report_hash(closure) != closure.evidence_hash
            or not closure.runtime_switch_closed
        ):
            raise ProductivityPilotRealUserAdmissionConflict("closed pilot baseline changed after nomination")
        gate = self.preflight_store.get(
            tenant_id=user_context.tenant_id,
            gate_hash=command.preflight_gate_hash,
        )
        gate_checked_at = _parse_datetime(gate.checked_at_utc)
        if (
            not gate.preflight_ready
            or gate.policy_hash != command.policy_hash
            or gate.business_backend_release_gate_hash != command.business_backend_release_gate_hash
            or gate.tenant_module_state_manifest_hash != command.tenant_module_state_manifest_hash
            or gate_checked_at < _utc(nomination.nominated_at_utc)
            or approved_at - gate_checked_at > MAX_CONTROL_EVIDENCE_AGE
        ):
            raise ProductivityPilotRealUserAdmissionConflict(
                "fresh authoritative productivity pilot preflight evidence is required"
            )
        control_observed_at = _utc(command.control_evidence_observed_at_utc)
        if (
            control_observed_at < _utc(nomination.nominated_at_utc)
            or control_observed_at > approved_at + MAX_CLOCK_SKEW
            or approved_at - control_observed_at > MAX_CONTROL_EVIDENCE_AGE
            or command.backup_sha256 == closure.recovery_evidence.backup_sha256
        ):
            raise ProductivityPilotRealUserAdmissionConflict("fresh post-nomination recovery evidence is required")

        command_hash = _canonical_hash(command.model_dump(mode="json"))
        idempotency_key_hash = _canonical_hash(
            {
                "schema_version": "productivity_pilot_real_user_admission_idempotency.v1",
                "tenant_id": user_context.tenant_id,
                "idempotency_key_ref": command.idempotency_key_ref,
            }
        )
        existing = self.record_store.admission_for_idempotency(
            tenant_id=user_context.tenant_id,
            idempotency_key_hash=idempotency_key_hash,
        )
        if existing is not None:
            if existing.command_hash != command_hash:
                raise ProductivityPilotRealUserAdmissionConflict(
                    "real-user admission idempotency key was used for another command"
                )
            return existing.model_copy(update={"idempotent_replay": True})
        current = self.record_store.current_admission(tenant_id=user_context.tenant_id)
        if current is not None and _utc(current.scheduled_end_at_utc) > now:
            raise ProductivityPilotRealUserAdmissionConflict("an unexpired real-user pilot admission already exists")

        draft = ProductivityPilotRealUserAdmission(
            tenant_id=user_context.tenant_id,
            admission_id=command.admission_id,
            nomination_id=nomination.nomination_id,
            nomination_evidence_hash=nomination.evidence_hash,
            baseline_closure_evidence_hash=nomination.baseline_closure_evidence_hash,
            participant_manifest_hash=participant_manifest_hash,
            participant_count=len(participants),
            approved_principal_hashes=tuple(sorted(item.principal_id_hash for item in participants)),
            preflight_gate_hash=gate.gate_hash,
            policy_hash=gate.policy_hash,
            business_backend_release_gate_hash=gate.business_backend_release_gate_hash,
            tenant_module_state_manifest_hash=gate.tenant_module_state_manifest_hash,
            backup_sha256=command.backup_sha256,
            postgres_restore_drill_report_hash=command.postgres_restore_drill_report_hash,
            backend_foundation_gate_hash=command.backend_foundation_gate_hash,
            control_evidence_observed_at_utc=command.control_evidence_observed_at_utc,
            scheduled_start_at_utc=nomination.scheduled_start_at_utc,
            scheduled_end_at_utc=nomination.scheduled_end_at_utc,
            security_review_ref=command.security_review_ref,
            privacy_approval_ref=command.privacy_approval_ref,
            command_hash=command_hash,
            idempotency_key_hash=idempotency_key_hash,
            human_confirmation_statement_hash=sha256_bytes(command.human_confirmation_statement.encode("utf-8")),
            change_request_ref=command.change_request_ref,
            human_confirmation_reference=command.human_confirmation_reference,
            audit_chain_ref=command.audit_chain_ref,
            approved_by_principal_hash=actor_hash,
            approved_at_utc=command.approved_at_utc,
            evidence_hash="sha256:" + "0" * 64,
        )
        record = draft.model_copy(update={"evidence_hash": build_productivity_pilot_real_user_admission_hash(draft)})
        return self.record_store.append_admission(record)

    def current_nomination(self, *, tenant_id: str) -> ProductivityPilotRealUserNomination | None:
        return self.record_store.current_nomination(tenant_id=tenant_id)

    def current_admission(self, *, tenant_id: str) -> ProductivityPilotRealUserAdmission | None:
        return self.record_store.current_admission(tenant_id=tenant_id)

    def _resolve_participants(
        self,
        *,
        tenant_id: str,
        participants: tuple[ProductivityPilotParticipantIdentity, ...],
    ) -> tuple[ProductivityPilotParticipantEvidence, ...]:
        evidence: list[ProductivityPilotParticipantEvidence] = []
        for participant in participants:
            snapshot = self.participant_directory.active_principal(
                tenant_id=tenant_id,
                principal_id=participant.principal_id,
            )
            authoritative_roles = tuple(sorted(set(snapshot.role_ids)))
            if not set(participant.required_role_ids).issubset(authoritative_roles):
                raise ProductivityPilotRealUserAdmissionConflict(
                    "nominated principal lacks a required authoritative role"
                )
            principal_hash = build_productivity_pilot_principal_observation_hash(
                tenant_id=tenant_id,
                principal_id=snapshot.principal_id,
            )
            evidence.append(
                ProductivityPilotParticipantEvidence(
                    principal_id_hash=principal_hash,
                    authoritative_role_ids=authoritative_roles,
                    role_manifest_hash=_canonical_hash(
                        {
                            "schema_version": "productivity_pilot_principal_roles.v1",
                            "tenant_id": tenant_id,
                            "principal_id_hash": principal_hash,
                            "authoritative_role_ids": authoritative_roles,
                            "required_role_ids": participant.required_role_ids,
                        }
                    ),
                    participation_notice_evidence_hash=_canonical_hash(
                        {
                            "schema_version": "productivity_pilot_participation_notice.v1",
                            "principal_id_hash": principal_hash,
                            "reference": participant.participation_notice_ref,
                        }
                    ),
                    training_evidence_hash=_canonical_hash(
                        {
                            "schema_version": "productivity_pilot_training_evidence.v1",
                            "principal_id_hash": principal_hash,
                            "reference": participant.training_evidence_ref,
                        }
                    ),
                )
            )
        return tuple(sorted(evidence, key=lambda item: item.principal_id_hash))


def build_default_productivity_pilot_participant_directory(
    environ: Mapping[str, str] | None = None,
) -> ProductivityPilotParticipantDirectory:
    env = os.environ if environ is None else environ
    backend = (
        env.get(
            "SUITE_PRODUCTIVITY_PILOT_PARTICIPANT_DIRECTORY_BACKEND",
            env.get("SUITE_PRINCIPAL_DIRECTORY_BACKEND", "memory"),
        )
        .strip()
        .lower()
    )
    if backend in {"memory", "inmemory", "in-memory"}:
        return InMemoryProductivityPilotParticipantDirectory()
    if backend in {"postgres", "postgresql", "pg"}:
        database_dsn = (
            env.get("SUITE_PRODUCTIVITY_PILOT_PARTICIPANT_DIRECTORY_DSN")
            or env.get("SUITE_AUTHZ_ADMIN_DATABASE_DSN")
            or env.get("SUITE_DATABASE_DSN")
        )
        if not database_dsn:
            raise ValueError("PostgreSQL pilot participant directory requires a database DSN")
        return PgProductivityPilotParticipantDirectory(database_dsn=database_dsn)
    raise ValueError(f"Unsupported pilot participant directory backend: {backend}")


def build_default_productivity_pilot_real_user_admission_store(
    environ: Mapping[str, str] | None = None,
) -> ProductivityPilotRealUserAdmissionStore:
    env = os.environ if environ is None else environ
    backend = (
        env.get(
            "SUITE_PRODUCTIVITY_PILOT_REAL_USER_ADMISSION_STORE_BACKEND",
            "memory",
        )
        .strip()
        .lower()
    )
    if backend in {"memory", "inmemory", "in-memory"}:
        return InMemoryProductivityPilotRealUserAdmissionStore()
    if backend in {"postgres", "postgresql", "pg"}:
        database_dsn = (
            env.get("SUITE_PRODUCTIVITY_PILOT_REAL_USER_ADMISSION_STORE_DSN")
            or env.get("SUITE_AUTHZ_ADMIN_DATABASE_DSN")
            or env.get("SUITE_DATABASE_DSN")
        )
        if not database_dsn:
            raise ValueError("PostgreSQL real-user pilot admission store requires a database DSN")
        return PgProductivityPilotRealUserAdmissionStore(database_dsn=database_dsn)
    raise ValueError(f"Unsupported real-user pilot admission store backend: {backend}")
