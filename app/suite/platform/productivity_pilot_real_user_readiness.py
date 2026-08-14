from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from suite.ai_control_plane.models import UserContext
from suite.platform.productivity_pilot_real_user_admission import (
    ProductivityPilotRealUserAdmission,
    ProductivityPilotRealUserAdmissionStore,
    ProductivityPilotRealUserNomination,
    build_productivity_pilot_real_user_admission_hash,
    build_productivity_pilot_real_user_nomination_hash,
)
from suite.platform.productivity_pilot_real_user_closure_report import (
    ProductivityPilotRealUserClosureReport,
    ProductivityPilotRealUserClosureReportStore,
    build_productivity_pilot_real_user_closure_report_hash,
)
from suite.platform.productivity_pilot_real_user_runtime_window import (
    ProductivityPilotRealUserRuntimeObservation,
    ProductivityPilotRealUserRuntimeWindow,
    ProductivityPilotRealUserRuntimeWindowStore,
    build_productivity_pilot_real_user_runtime_observation_hash,
    build_productivity_pilot_real_user_runtime_window_hash,
)
from suite.platform.productivity_pilot_start_authorization import (
    ProductivityPilotStartAuthorization,
    ProductivityPilotStartAuthorizationStore,
    build_productivity_pilot_start_authorization_hash,
)
from suite.storage.source_objects import sha256_bytes

PRODUCTIVITY_PILOT_REAL_USER_READINESS_SCHEMA_VERSION = "productivity_pilot_real_user_readiness.v1"
SHA256_PREFIX = "sha256:"


class ProductivityPilotRealUserReadinessConflict(ValueError):
    pass


class ProductivityPilotRealUserReadinessStage(StrEnum):
    NOMINATION_REQUIRED = "nomination_required"
    ADMISSION_REQUIRED = "admission_required"
    START_CHAIN_REQUIRED = "start_chain_required"
    RUNTIME_WINDOW_REQUIRED = "runtime_window_required"
    RUNTIME_ACTIVE = "runtime_active"
    CLOSURE_REQUIRED = "closure_required"
    CLOSED = "closed"


class ProductivityPilotRealUserEvidenceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_type: str
    evidence_hash: str
    recorded_at_utc: datetime

    @field_validator("evidence_type")
    @classmethod
    def require_evidence_type(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("real-user productivity pilot evidence type must not be empty")
        return value

    @field_validator("evidence_hash")
    @classmethod
    def require_evidence_hash(cls, value: str) -> str:
        if len(value) != 71 or not value.startswith(SHA256_PREFIX):
            raise ValueError("real-user productivity pilot evidence hash must use sha256")
        try:
            int(value.removeprefix(SHA256_PREFIX), 16)
        except ValueError as exc:
            raise ValueError("real-user productivity pilot evidence hash must use sha256") from exc
        return value

    @field_validator("recorded_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("real-user productivity pilot evidence timestamp must include a timezone")
        return value


class ProductivityPilotRealUserReadinessResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = PRODUCTIVITY_PILOT_REAL_USER_READINESS_SCHEMA_VERSION
    tenant_id: str
    observed_at_utc: datetime
    stage: ProductivityPilotRealUserReadinessStage
    runtime_kill_switch_enabled: bool
    chain_integrity_verified: bool
    current_cycle_complete: bool
    participant_count: int
    allowed_api_operation_count: int
    observation_count: int
    domain_receipt_count: int
    available_evidence: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    evidence_refs: tuple[ProductivityPilotRealUserEvidenceRef, ...]
    blocking_reasons: tuple[str, ...]
    next_action: str
    evidence_hash: str
    runtime_activation_authorized: bool = False
    persistent_state_changed: bool = False
    business_write_executed: bool = False
    destructive_action_executed: bool = False
    external_side_effect_executed: bool = False
    content_included: bool = False

    @field_validator("tenant_id", "next_action")
    @classmethod
    def require_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("real-user productivity pilot readiness text must not be empty")
        return value

    @field_validator("available_evidence", "missing_evidence", "blocking_reasons")
    @classmethod
    def require_unique_values(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)) or any(not item.strip() for item in value):
            raise ValueError("real-user productivity pilot readiness values must be unique and non-empty")
        return value

    @model_validator(mode="after")
    def require_read_only_metadata(self) -> Self:
        if self.schema_version != PRODUCTIVITY_PILOT_REAL_USER_READINESS_SCHEMA_VERSION:
            raise ValueError("real-user productivity pilot readiness schema version is invalid")
        if (
            not self.chain_integrity_verified
            or self.runtime_activation_authorized
            or self.persistent_state_changed
            or self.business_write_executed
            or self.destructive_action_executed
            or self.external_side_effect_executed
            or self.content_included
        ):
            raise ValueError("real-user productivity pilot readiness must remain read-only and metadata-only")
        if self.current_cycle_complete != (self.stage == ProductivityPilotRealUserReadinessStage.CLOSED):
            raise ValueError("real-user productivity pilot completion state does not match the lifecycle stage")
        return self


def build_productivity_pilot_real_user_readiness_hash(
    response: ProductivityPilotRealUserReadinessResponse,
) -> str:
    payload = response.model_dump(mode="json", exclude={"evidence_hash"})
    return sha256_bytes(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))


class ProductivityPilotRealUserReadinessService:
    def __init__(
        self,
        *,
        admission_store: ProductivityPilotRealUserAdmissionStore,
        start_authorization_store: ProductivityPilotStartAuthorizationStore,
        runtime_window_store: ProductivityPilotRealUserRuntimeWindowStore,
        closure_report_store: ProductivityPilotRealUserClosureReportStore,
        runtime_enabled: bool,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.admission_store = admission_store
        self.start_authorization_store = start_authorization_store
        self.runtime_window_store = runtime_window_store
        self.closure_report_store = closure_report_store
        self.runtime_enabled = runtime_enabled
        self.clock = clock or (lambda: datetime.now(UTC))

    def current(
        self,
        *,
        user_context: UserContext,
    ) -> ProductivityPilotRealUserReadinessResponse:
        if user_context.role_ids.isdisjoint({"tenant-admin", "security-admin"}):
            raise PermissionError("tenant or security admin role required")
        tenant_id = user_context.tenant_id
        now = _utc(self.clock())
        nomination = self.admission_store.current_nomination(tenant_id=tenant_id)
        admission = self.admission_store.current_admission(tenant_id=tenant_id)
        start = self.start_authorization_store.current(tenant_id=tenant_id)
        window = self.runtime_window_store.current_window(tenant_id=tenant_id)
        closure = self.closure_report_store.current(tenant_id=tenant_id)

        self._validate_artifact_hashes(
            tenant_id=tenant_id,
            nomination=nomination,
            admission=admission,
            start=start,
            window=window,
            closure=closure,
        )

        blocking_reasons: list[str] = []
        current_admission = self._current_admission(
            nomination=nomination,
            admission=admission,
            blocking_reasons=blocking_reasons,
        )
        current_start = self._current_start(
            nomination=nomination,
            admission=current_admission,
            start=start,
            blocking_reasons=blocking_reasons,
        )
        current_window = self._current_window(
            nomination=nomination,
            admission=current_admission,
            start=current_start,
            window=window,
            blocking_reasons=blocking_reasons,
        )
        current_closure = self._current_closure(
            nomination=nomination,
            admission=current_admission,
            start=current_start,
            window=current_window,
            closure=closure,
            blocking_reasons=blocking_reasons,
        )

        observations: tuple[ProductivityPilotRealUserRuntimeObservation, ...] = ()
        if current_window is not None:
            observations = self.runtime_window_store.observations_for_window(
                tenant_id=tenant_id,
                window_id=current_window.window_id,
            )
            self._validate_observations(window=current_window, observations=observations)

        stage, next_action = self._stage(
            now=now,
            nomination=nomination,
            admission=current_admission,
            start=current_start,
            window=current_window,
            closure=current_closure,
            blocking_reasons=blocking_reasons,
        )
        evidence_refs = self._evidence_refs(
            nomination=nomination,
            admission=current_admission,
            start=current_start,
            window=current_window,
            closure=current_closure,
        )
        available_evidence = tuple(item.evidence_type for item in evidence_refs)
        required_evidence = (
            "real_user_nomination",
            "real_user_admission",
            "fresh_start_authorization",
            "real_user_runtime_window",
            "real_user_closure_report",
        )
        draft = ProductivityPilotRealUserReadinessResponse(
            tenant_id=tenant_id,
            observed_at_utc=now,
            stage=stage,
            runtime_kill_switch_enabled=self.runtime_enabled,
            chain_integrity_verified=True,
            current_cycle_complete=current_closure is not None,
            participant_count=nomination.participant_count if nomination is not None else 0,
            allowed_api_operation_count=(len(current_window.allowed_api_operations) if current_window else 0),
            observation_count=len(observations),
            domain_receipt_count=(len(current_closure.domain_receipts) if current_closure else 0),
            available_evidence=available_evidence,
            missing_evidence=tuple(item for item in required_evidence if item not in available_evidence),
            evidence_refs=evidence_refs,
            blocking_reasons=tuple(dict.fromkeys(blocking_reasons)),
            next_action=next_action,
            evidence_hash=SHA256_PREFIX + "0" * 64,
        )
        return draft.model_copy(update={"evidence_hash": build_productivity_pilot_real_user_readiness_hash(draft)})

    @staticmethod
    def _validate_artifact_hashes(
        *,
        tenant_id: str,
        nomination: ProductivityPilotRealUserNomination | None,
        admission: ProductivityPilotRealUserAdmission | None,
        start: ProductivityPilotStartAuthorization | None,
        window: ProductivityPilotRealUserRuntimeWindow | None,
        closure: ProductivityPilotRealUserClosureReport | None,
    ) -> None:
        invalid_label: str | None = None
        if nomination is not None and (
            nomination.tenant_id != tenant_id
            or build_productivity_pilot_real_user_nomination_hash(nomination) != nomination.evidence_hash
        ):
            invalid_label = "nomination"
        elif admission is not None and (
            admission.tenant_id != tenant_id
            or build_productivity_pilot_real_user_admission_hash(admission) != admission.evidence_hash
        ):
            invalid_label = "admission"
        elif start is not None and (
            start.tenant_id != tenant_id
            or build_productivity_pilot_start_authorization_hash(start) != start.evidence_hash
        ):
            invalid_label = "start authorization"
        elif window is not None and (
            window.tenant_id != tenant_id
            or build_productivity_pilot_real_user_runtime_window_hash(window) != window.evidence_hash
        ):
            invalid_label = "runtime window"
        elif closure is not None and (
            closure.tenant_id != tenant_id
            or build_productivity_pilot_real_user_closure_report_hash(closure) != closure.evidence_hash
        ):
            invalid_label = "closure report"
        if invalid_label is not None:
            raise ProductivityPilotRealUserReadinessConflict(
                f"authoritative real-user productivity pilot {invalid_label} is invalid"
            )

    @staticmethod
    def _current_admission(
        *,
        nomination: ProductivityPilotRealUserNomination | None,
        admission: ProductivityPilotRealUserAdmission | None,
        blocking_reasons: list[str],
    ) -> ProductivityPilotRealUserAdmission | None:
        if nomination is None or admission is None:
            return None
        if admission.nomination_id != nomination.nomination_id:
            blocking_reasons.append("current_admission_belongs_to_previous_nomination")
            return None
        if (
            admission.nomination_evidence_hash != nomination.evidence_hash
            or admission.baseline_closure_evidence_hash != nomination.baseline_closure_evidence_hash
            or admission.participant_manifest_hash != nomination.participant_manifest_hash
            or admission.participant_count != nomination.participant_count
            or tuple(sorted(admission.approved_principal_hashes))
            != tuple(sorted(item.principal_id_hash for item in nomination.participants))
        ):
            raise ProductivityPilotRealUserReadinessConflict(
                "real-user productivity pilot admission does not match the current nomination"
            )
        return admission

    @staticmethod
    def _current_start(
        *,
        nomination: ProductivityPilotRealUserNomination | None,
        admission: ProductivityPilotRealUserAdmission | None,
        start: ProductivityPilotStartAuthorization | None,
        blocking_reasons: list[str],
    ) -> ProductivityPilotStartAuthorization | None:
        if nomination is None or admission is None or start is None:
            return None
        if (
            start.preflight_gate_hash != admission.preflight_gate_hash
            or _utc(start.authorized_at_utc) < _utc(admission.approved_at_utc)
        ):
            blocking_reasons.append("current_start_authorization_belongs_to_previous_control_chain")
            return None
        if (
            _utc(start.effective_at_utc) < _utc(admission.scheduled_start_at_utc)
            or _utc(start.expires_at_utc) > _utc(admission.scheduled_end_at_utc)
        ):
            raise ProductivityPilotRealUserReadinessConflict(
                "real-user productivity pilot start authorization exceeds the admitted schedule"
            )
        return start

    @staticmethod
    def _current_window(
        *,
        nomination: ProductivityPilotRealUserNomination | None,
        admission: ProductivityPilotRealUserAdmission | None,
        start: ProductivityPilotStartAuthorization | None,
        window: ProductivityPilotRealUserRuntimeWindow | None,
        blocking_reasons: list[str],
    ) -> ProductivityPilotRealUserRuntimeWindow | None:
        if nomination is None or admission is None or start is None or window is None:
            return None
        if window.admission_id != admission.admission_id:
            blocking_reasons.append("current_runtime_window_belongs_to_previous_admission")
            return None
        if (
            window.real_user_admission_evidence_hash != admission.evidence_hash
            or window.nomination_id != nomination.nomination_id
            or window.nomination_evidence_hash != nomination.evidence_hash
            or window.authorization_id != start.authorization_id
            or window.start_authorization_evidence_hash != start.evidence_hash
            or window.route_scope_hash != start.route_scope_hash
            or window.allowed_api_operations != start.allowed_api_operations
        ):
            raise ProductivityPilotRealUserReadinessConflict(
                "real-user productivity pilot runtime window does not match the current control chain"
            )
        return window

    @staticmethod
    def _current_closure(
        *,
        nomination: ProductivityPilotRealUserNomination | None,
        admission: ProductivityPilotRealUserAdmission | None,
        start: ProductivityPilotStartAuthorization | None,
        window: ProductivityPilotRealUserRuntimeWindow | None,
        closure: ProductivityPilotRealUserClosureReport | None,
        blocking_reasons: list[str],
    ) -> ProductivityPilotRealUserClosureReport | None:
        if nomination is None or admission is None or start is None or window is None or closure is None:
            return None
        if closure.window_id != window.window_id:
            blocking_reasons.append("current_closure_belongs_to_previous_runtime_window")
            return None
        if (
            closure.runtime_window_evidence_hash != window.evidence_hash
            or closure.admission_id != admission.admission_id
            or closure.real_user_admission_evidence_hash != admission.evidence_hash
            or closure.nomination_id != nomination.nomination_id
            or closure.nomination_evidence_hash != nomination.evidence_hash
            or closure.authorization_id != start.authorization_id
            or closure.start_authorization_evidence_hash != start.evidence_hash
            or closure.designated_principal_manifest_hash != window.designated_principal_manifest_hash
            or closure.participant_role_snapshot_hash != window.participant_role_snapshot_hash
            or closure.route_scope_hash != window.route_scope_hash
        ):
            raise ProductivityPilotRealUserReadinessConflict(
                "real-user productivity pilot closure does not match the current control chain"
            )
        return closure

    @staticmethod
    def _validate_observations(
        *,
        window: ProductivityPilotRealUserRuntimeWindow,
        observations: tuple[ProductivityPilotRealUserRuntimeObservation, ...],
    ) -> None:
        for observation in observations:
            if (
                build_productivity_pilot_real_user_runtime_observation_hash(observation) != observation.evidence_hash
                or observation.tenant_id != window.tenant_id
                or observation.window_id != window.window_id
                or observation.window_evidence_hash != window.evidence_hash
            ):
                raise ProductivityPilotRealUserReadinessConflict(
                    "real-user productivity pilot runtime observation is invalid"
                )

    def _stage(
        self,
        *,
        now: datetime,
        nomination: ProductivityPilotRealUserNomination | None,
        admission: ProductivityPilotRealUserAdmission | None,
        start: ProductivityPilotStartAuthorization | None,
        window: ProductivityPilotRealUserRuntimeWindow | None,
        closure: ProductivityPilotRealUserClosureReport | None,
        blocking_reasons: list[str],
    ) -> tuple[ProductivityPilotRealUserReadinessStage, str]:
        if nomination is None:
            blocking_reasons.append("named_principals_purpose_privacy_and_retention_nomination_missing")
            return (
                ProductivityPilotRealUserReadinessStage.NOMINATION_REQUIRED,
                "collect_named_principals_and_record_tenant_owned_real_user_nomination",
            )
        if admission is None:
            if _utc(nomination.scheduled_end_at_utc) <= now:
                blocking_reasons.append("current_nomination_schedule_expired")
                return (
                    ProductivityPilotRealUserReadinessStage.NOMINATION_REQUIRED,
                    "record_new_time_bounded_real_user_nomination",
                )
            blocking_reasons.append("independent_security_admission_and_fresh_control_evidence_missing")
            return (
                ProductivityPilotRealUserReadinessStage.ADMISSION_REQUIRED,
                "refresh_control_evidence_and_record_independent_security_admission",
            )
        if start is None:
            if _utc(nomination.scheduled_end_at_utc) <= now:
                blocking_reasons.append("current_admitted_schedule_expired")
                return (
                    ProductivityPilotRealUserReadinessStage.NOMINATION_REQUIRED,
                    "record_new_time_bounded_real_user_nomination",
                )
            blocking_reasons.append("fresh_traffic_scope_monitoring_rollback_and_start_chain_missing")
            return (
                ProductivityPilotRealUserReadinessStage.START_CHAIN_REQUIRED,
                "create_fresh_traffic_scope_and_four_eyes_start_chain_inside_admitted_schedule",
            )
        if window is None:
            if _utc(start.expires_at_utc) <= now:
                blocking_reasons.append("current_start_authorization_expired")
                return (
                    ProductivityPilotRealUserReadinessStage.START_CHAIN_REQUIRED,
                    "create_fresh_traffic_scope_and_four_eyes_start_chain_inside_admitted_schedule",
                )
            if now < _utc(start.effective_at_utc):
                blocking_reasons.append("authorized_runtime_schedule_not_yet_effective")
            if not self.runtime_enabled:
                blocking_reasons.append("deployment_runtime_kill_switch_closed")
            return (
                ProductivityPilotRealUserReadinessStage.RUNTIME_WINDOW_REQUIRED,
                "obtain_explicit_runtime_change_approval_then_activate_bounded_hash_only_window",
            )
        if closure is not None:
            return (
                ProductivityPilotRealUserReadinessStage.CLOSED,
                "retain_closed_evidence_and_require_a_new_nomination_for_any_expansion",
            )
        if self.runtime_enabled and _utc(window.effective_at_utc) <= now < _utc(window.expires_at_utc):
            return (
                ProductivityPilotRealUserReadinessStage.RUNTIME_ACTIVE,
                "observe_only_approved_operations_then_close_switch_and_record_recovery_bound_closure",
            )
        blocking_reasons.append("real_user_runtime_window_requires_hash_only_closure")
        return (
            ProductivityPilotRealUserReadinessStage.CLOSURE_REQUIRED,
            "keep_runtime_closed_collect_recovery_evidence_and_record_independent_closure",
        )

    @staticmethod
    def _evidence_refs(
        *,
        nomination: ProductivityPilotRealUserNomination | None,
        admission: ProductivityPilotRealUserAdmission | None,
        start: ProductivityPilotStartAuthorization | None,
        window: ProductivityPilotRealUserRuntimeWindow | None,
        closure: ProductivityPilotRealUserClosureReport | None,
    ) -> tuple[ProductivityPilotRealUserEvidenceRef, ...]:
        refs: list[ProductivityPilotRealUserEvidenceRef] = []
        if nomination is not None:
            refs.append(
                ProductivityPilotRealUserEvidenceRef(
                    evidence_type="real_user_nomination",
                    evidence_hash=nomination.evidence_hash,
                    recorded_at_utc=nomination.nominated_at_utc,
                )
            )
        if admission is not None:
            refs.append(
                ProductivityPilotRealUserEvidenceRef(
                    evidence_type="real_user_admission",
                    evidence_hash=admission.evidence_hash,
                    recorded_at_utc=admission.approved_at_utc,
                )
            )
        if start is not None:
            refs.append(
                ProductivityPilotRealUserEvidenceRef(
                    evidence_type="fresh_start_authorization",
                    evidence_hash=start.evidence_hash,
                    recorded_at_utc=start.authorized_at_utc,
                )
            )
        if window is not None:
            refs.append(
                ProductivityPilotRealUserEvidenceRef(
                    evidence_type="real_user_runtime_window",
                    evidence_hash=window.evidence_hash,
                    recorded_at_utc=window.activated_at_utc,
                )
            )
        if closure is not None:
            refs.append(
                ProductivityPilotRealUserEvidenceRef(
                    evidence_type="real_user_closure_report",
                    evidence_hash=closure.evidence_hash,
                    recorded_at_utc=closure.closed_at_utc,
                )
            )
        return tuple(refs)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProductivityPilotRealUserReadinessConflict(
            "real-user productivity pilot evidence timestamp must include a timezone"
        )
    return value.astimezone(UTC)
