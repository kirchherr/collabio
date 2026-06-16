from __future__ import annotations

import argparse
import json
import os
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from time import sleep
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from suite.ai_control_plane.audit import (
    InMemoryAuditLogger,
    build_default_audit_logger,
    canonical_json,
    stable_hash,
)
from suite.ai_control_plane.models import UserContext
from suite.platform.knowledge_base import KNOWLEDGE_BASE_MODULE_ID
from suite.platform.knowledge_base_runtime import (
    ZERO_HASH,
    InMemoryKnowledgeBaseRuntimeActivationStore,
    InMemoryKnowledgeBaseRuntimeReconciliationStore,
    KnowledgeBaseRuntimeActivation,
    KnowledgeBaseRuntimeReconciliationAction,
    KnowledgeBaseRuntimeReconciliationStatus,
    KnowledgeBaseRuntimeReconciliationWorker,
    PgKnowledgeBaseRuntimeActivationStore,
    PgKnowledgeBaseRuntimeReconciliationStore,
    build_default_knowledge_base_runtime_activation_store,
    build_default_knowledge_base_runtime_reconciliation_store,
)
from suite.platform.modules import (
    InMemoryModuleRegistry,
    ModuleGateDecision,
    ModuleLifecycleError,
    ModuleStatus,
    ModuleWorkerGate,
    default_module_registry,
)

ActivationStore = InMemoryKnowledgeBaseRuntimeActivationStore | PgKnowledgeBaseRuntimeActivationStore
ReconciliationStore = InMemoryKnowledgeBaseRuntimeReconciliationStore | PgKnowledgeBaseRuntimeReconciliationStore

CONTINUITY_DOMAINS = (
    "knowledge_base_content",
    "object_storage_records",
    "module_registry_state",
    "background_jobs_queues",
)


class KnowledgeBaseRuntimeReconciliationTenantSelectionStatus(StrEnum):
    SELECTED = "selected"
    NO_ACTIVE_RUNTIME = "no_active_runtime"
    MODULE_GATE_BLOCKED = "module_gate_blocked"


class KnowledgeBaseRuntimeReconciliationTenantRunStatus(StrEnum):
    READY = "ready"
    DRIFT_BLOCKED = "drift_blocked"
    NO_ACTIVE_RUNTIME = "no_active_runtime"
    MODULE_GATE_BLOCKED = "module_gate_blocked"
    FAILED = "failed"


class KnowledgeBaseRuntimeReconciliationAlertSeverity(StrEnum):
    NONE = "none"
    WARNING = "warning"
    CRITICAL = "critical"


class KnowledgeBaseRuntimeReconciliationRetryContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_attempts: int = Field(default=2, ge=1, le=5)
    retry_backoff_seconds: float = Field(default=0.0, ge=0.0, le=60.0)
    retryable_error_classes: tuple[str, ...] = ("ValueError", "RuntimeError", "LookupError")


class KnowledgeBaseRuntimeReconciliationRunConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    checked_by: str = "kb-runtime-reconciliation-worker"
    worker_id: str = "kb-runtime-reconciler"
    tenant_ids: tuple[str, ...] = ()
    retry_contract: KnowledgeBaseRuntimeReconciliationRetryContract = Field(
        default_factory=KnowledgeBaseRuntimeReconciliationRetryContract
    )

    @field_validator("checked_by", "worker_id")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("runtime reconciliation worker config fields must not be empty")
        return value

    @field_validator("tenant_ids")
    @classmethod
    def require_unique_tenant_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(tenant_id.strip() for tenant_id in value if tenant_id.strip())
        if len(cleaned) != len(set(cleaned)):
            raise ValueError("tenant_ids must not contain duplicates")
        return cleaned


class KnowledgeBaseRuntimeReconciliationTenantSelectionView(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    module_status: ModuleStatus | None
    selection_status: KnowledgeBaseRuntimeReconciliationTenantSelectionStatus
    activation_id: str | None = None
    restore_drill_report_hash: str | None = None
    blocking_reason: str | None = None


class KnowledgeBaseRuntimeReconciliationTenantResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str
    status: KnowledgeBaseRuntimeReconciliationTenantRunStatus
    activation_id: str | None = None
    attempts: int = Field(ge=0)
    reconciliation_status: KnowledgeBaseRuntimeReconciliationStatus | None = None
    recommended_action: KnowledgeBaseRuntimeReconciliationAction | None = None
    runtime_deactivated: bool = False
    restore_drill_report_hash: str | None = None
    evidence_hash: str | None = None
    alert_severity: KnowledgeBaseRuntimeReconciliationAlertSeverity = (
        KnowledgeBaseRuntimeReconciliationAlertSeverity.NONE
    )
    alert_reason: str | None = None
    last_error: str | None = None


class KnowledgeBaseRuntimeReconciliationRunbookEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    worker_id: str
    checked_by: str
    started_at_utc: str
    completed_at_utc: str
    command_ref: str = "docker-compose:kb-runtime-reconciler"
    continuity_domains: tuple[str, ...] = CONTINUITY_DOMAINS
    selected_tenants: tuple[str, ...]
    skipped_tenants: tuple[str, ...]
    restore_drill_report_hashes: tuple[str, ...]
    retry_contract: KnowledgeBaseRuntimeReconciliationRetryContract
    alert_contract: str = "alert_required=true when drift, module-gate mismatch, or worker failure appears"


class KnowledgeBaseRuntimeReconciliationRunReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    started_at_utc: str
    completed_at_utc: str
    checked_by: str
    worker_id: str
    selections: tuple[KnowledgeBaseRuntimeReconciliationTenantSelectionView, ...]
    tenant_results: tuple[KnowledgeBaseRuntimeReconciliationTenantResult, ...]
    attempted_count: int = Field(ge=0)
    ready_count: int = Field(ge=0)
    drift_blocked_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    skipped_count: int = Field(ge=0)
    alert_required: bool
    alert_severity: KnowledgeBaseRuntimeReconciliationAlertSeverity
    runbook_evidence: KnowledgeBaseRuntimeReconciliationRunbookEvidence
    evidence_hash: str = ZERO_HASH
    schema_version: str = "knowledge_base_runtime_reconciliation_run_report.v1"

    @model_validator(mode="after")
    def require_consistent_hash(self) -> KnowledgeBaseRuntimeReconciliationRunReport:
        if self.evidence_hash != ZERO_HASH and self.evidence_hash != build_reconciliation_run_report_hash(self):
            raise ValueError("knowledge base runtime reconciliation run report hash is invalid")
        return self


@dataclass(frozen=True)
class KnowledgeBaseRuntimeReconciliationTenantCandidate:
    tenant_id: str
    module_status: ModuleStatus | None
    selection_status: KnowledgeBaseRuntimeReconciliationTenantSelectionStatus
    activation: KnowledgeBaseRuntimeActivation | None = None
    gate_decision: ModuleGateDecision | None = None
    blocking_reason: str | None = None

    def view(self) -> KnowledgeBaseRuntimeReconciliationTenantSelectionView:
        return KnowledgeBaseRuntimeReconciliationTenantSelectionView(
            tenant_id=self.tenant_id,
            module_status=self.module_status,
            selection_status=self.selection_status,
            activation_id=self.activation.activation_id if self.activation else None,
            restore_drill_report_hash=self.activation.restore_drill_report_hash if self.activation else None,
            blocking_reason=self.blocking_reason,
        )


class KnowledgeBaseRuntimeReconciliationTenantSelector:
    def __init__(
        self,
        *,
        activation_store: ActivationStore,
        module_worker_gate: ModuleWorkerGate,
        module_registry: InMemoryModuleRegistry,
        module_id: str = KNOWLEDGE_BASE_MODULE_ID,
    ) -> None:
        self.activation_store = activation_store
        self.module_worker_gate = module_worker_gate
        self.module_registry = module_registry
        self.module_id = module_id

    def select(
        self,
        *,
        tenant_ids: Sequence[str] = (),
    ) -> tuple[KnowledgeBaseRuntimeReconciliationTenantCandidate, ...]:
        requested_tenant_ids = tuple(tenant_id.strip() for tenant_id in tenant_ids if tenant_id.strip())
        requested_filter = set(requested_tenant_ids)
        states = self.module_registry.list_tenant_modules_for_module(self.module_id)
        if requested_filter:
            states = tuple(state for state in states if state.tenant_id in requested_filter)

        candidates = [self._candidate_for_registered_tenant(state.tenant_id, state.status) for state in states]
        known_tenant_ids = {state.tenant_id for state in states}
        for tenant_id in requested_tenant_ids:
            if tenant_id not in known_tenant_ids:
                candidates.append(self._candidate_for_unregistered_tenant(tenant_id))

        return tuple(sorted(candidates, key=lambda candidate: candidate.tenant_id))

    def _candidate_for_registered_tenant(
        self,
        tenant_id: str,
        module_status: ModuleStatus,
    ) -> KnowledgeBaseRuntimeReconciliationTenantCandidate:
        activation = self.activation_store.get_active(tenant_id=tenant_id)
        if activation is None:
            return KnowledgeBaseRuntimeReconciliationTenantCandidate(
                tenant_id=tenant_id,
                module_status=module_status,
                selection_status=KnowledgeBaseRuntimeReconciliationTenantSelectionStatus.NO_ACTIVE_RUNTIME,
                blocking_reason="no_active_runtime_activation",
            )

        try:
            gate_decision = self.module_worker_gate.require_compliance_worker(
                tenant_id=tenant_id,
                module_id=self.module_id,
            )
        except (LookupError, ModuleLifecycleError) as exc:
            return KnowledgeBaseRuntimeReconciliationTenantCandidate(
                tenant_id=tenant_id,
                module_status=module_status,
                selection_status=KnowledgeBaseRuntimeReconciliationTenantSelectionStatus.MODULE_GATE_BLOCKED,
                activation=activation,
                blocking_reason=str(exc),
            )

        return KnowledgeBaseRuntimeReconciliationTenantCandidate(
            tenant_id=tenant_id,
            module_status=module_status,
            selection_status=KnowledgeBaseRuntimeReconciliationTenantSelectionStatus.SELECTED,
            activation=activation,
            gate_decision=gate_decision,
        )

    def _candidate_for_unregistered_tenant(
        self,
        tenant_id: str,
    ) -> KnowledgeBaseRuntimeReconciliationTenantCandidate:
        activation = self.activation_store.get_active(tenant_id=tenant_id)
        return KnowledgeBaseRuntimeReconciliationTenantCandidate(
            tenant_id=tenant_id,
            module_status=None,
            selection_status=KnowledgeBaseRuntimeReconciliationTenantSelectionStatus.MODULE_GATE_BLOCKED,
            activation=activation,
            blocking_reason=f"tenant module state is missing for {self.module_id}",
        )


class KnowledgeBaseRuntimeReconciliationRunner:
    def __init__(
        self,
        *,
        selector: KnowledgeBaseRuntimeReconciliationTenantSelector,
        worker: KnowledgeBaseRuntimeReconciliationWorker,
        audit_logger: InMemoryAuditLogger | None = None,
        sleep_fn: Callable[[float], None] = sleep,
    ) -> None:
        self.selector = selector
        self.worker = worker
        self.audit_logger = audit_logger
        self.sleep_fn = sleep_fn

    def run_once(
        self,
        config: KnowledgeBaseRuntimeReconciliationRunConfig | None = None,
    ) -> KnowledgeBaseRuntimeReconciliationRunReport:
        resolved_config = config or KnowledgeBaseRuntimeReconciliationRunConfig()
        run_id = f"kb-runtime-reconciliation-run-{uuid4().hex}"
        started_at_utc = _utc_now()
        candidates = self.selector.select(tenant_ids=resolved_config.tenant_ids)
        selections = tuple(candidate.view() for candidate in candidates)
        tenant_results: list[KnowledgeBaseRuntimeReconciliationTenantResult] = []

        for candidate in candidates:
            if candidate.selection_status == KnowledgeBaseRuntimeReconciliationTenantSelectionStatus.SELECTED:
                tenant_results.append(
                    self._run_candidate(
                        candidate=candidate,
                        config=resolved_config,
                        run_id=run_id,
                    )
                )
            else:
                tenant_results.append(_skipped_result(candidate))

        completed_at_utc = _utc_now()
        return build_reconciliation_run_report(
            run_id=run_id,
            started_at_utc=started_at_utc,
            completed_at_utc=completed_at_utc,
            config=resolved_config,
            selections=selections,
            tenant_results=tuple(tenant_results),
        )

    def _run_candidate(
        self,
        *,
        candidate: KnowledgeBaseRuntimeReconciliationTenantCandidate,
        config: KnowledgeBaseRuntimeReconciliationRunConfig,
        run_id: str,
    ) -> KnowledgeBaseRuntimeReconciliationTenantResult:
        if candidate.activation is None:
            return _skipped_result(candidate)

        last_error: str | None = None
        for attempt in range(1, config.retry_contract.max_attempts + 1):
            try:
                audit_chain_ref = self._audit_chain_ref(
                    tenant_id=candidate.tenant_id,
                    activation=candidate.activation,
                    config=config,
                    run_id=run_id,
                    attempt=attempt,
                )
                evidence = self.worker.reconcile_activation(
                    activation=candidate.activation,
                    checked_by=config.checked_by,
                    audit_chain_ref=audit_chain_ref,
                )
                status = (
                    KnowledgeBaseRuntimeReconciliationTenantRunStatus.DRIFT_BLOCKED
                    if evidence.reconciliation_status == KnowledgeBaseRuntimeReconciliationStatus.DRIFT_BLOCKED
                    else KnowledgeBaseRuntimeReconciliationTenantRunStatus.READY
                )
                return KnowledgeBaseRuntimeReconciliationTenantResult(
                    tenant_id=candidate.tenant_id,
                    activation_id=evidence.activation_id,
                    attempts=attempt,
                    status=status,
                    reconciliation_status=evidence.reconciliation_status,
                    recommended_action=evidence.recommended_action,
                    runtime_deactivated=evidence.runtime_deactivated,
                    restore_drill_report_hash=evidence.restore_drill_report_hash,
                    evidence_hash=evidence.evidence_hash,
                    alert_severity=(
                        KnowledgeBaseRuntimeReconciliationAlertSeverity.WARNING
                        if evidence.runtime_deactivated
                        else KnowledgeBaseRuntimeReconciliationAlertSeverity.NONE
                    ),
                    alert_reason="runtime_reconciliation_drift" if evidence.runtime_deactivated else None,
                )
            except Exception as exc:
                last_error = f"{exc.__class__.__name__}: {exc}"
                if attempt < config.retry_contract.max_attempts and config.retry_contract.retry_backoff_seconds:
                    self.sleep_fn(config.retry_contract.retry_backoff_seconds)

        return KnowledgeBaseRuntimeReconciliationTenantResult(
            tenant_id=candidate.tenant_id,
            activation_id=candidate.activation.activation_id,
            attempts=config.retry_contract.max_attempts,
            status=KnowledgeBaseRuntimeReconciliationTenantRunStatus.FAILED,
            restore_drill_report_hash=candidate.activation.restore_drill_report_hash,
            alert_severity=KnowledgeBaseRuntimeReconciliationAlertSeverity.CRITICAL,
            alert_reason="runtime_reconciliation_worker_failed",
            last_error=last_error,
        )

    def _audit_chain_ref(
        self,
        *,
        tenant_id: str,
        activation: KnowledgeBaseRuntimeActivation,
        config: KnowledgeBaseRuntimeReconciliationRunConfig,
        run_id: str,
        attempt: int,
    ) -> str:
        if self.audit_logger is None:
            return f"runbook:{run_id}:{tenant_id}:attempt-{attempt}"

        event = self.audit_logger.record(
            user_context=UserContext(
                tenant_id=tenant_id,
                user_id=config.checked_by,
                role_ids={"system:worker", "compliance-worker"},
                readable_object_ids=set(),
            ),
            event_type="knowledge_base.runtime.reconciliation_worker.run",
            source_object_ids=[f"knowledge_base_runtime:{tenant_id}"],
            metadata={
                "module_id": KNOWLEDGE_BASE_MODULE_ID,
                "surface": "compliance_worker",
                "run_id": run_id,
                "worker_id": config.worker_id,
                "activation_id": activation.activation_id,
                "activation_evidence_hash": activation.activation_evidence_hash,
                "restore_drill_report_hash": activation.restore_drill_report_hash,
                "attempt": attempt,
                "result_contract": "metadata_only",
                "continuity_domains": list(CONTINUITY_DOMAINS),
            },
        )
        return f"audit:{event.event_id}"


def build_reconciliation_run_report(
    *,
    run_id: str,
    started_at_utc: str,
    completed_at_utc: str,
    config: KnowledgeBaseRuntimeReconciliationRunConfig,
    selections: tuple[KnowledgeBaseRuntimeReconciliationTenantSelectionView, ...],
    tenant_results: tuple[KnowledgeBaseRuntimeReconciliationTenantResult, ...],
) -> KnowledgeBaseRuntimeReconciliationRunReport:
    attempted_count = sum(1 for result in tenant_results if result.attempts > 0)
    ready_count = sum(
        1 for result in tenant_results if result.status == KnowledgeBaseRuntimeReconciliationTenantRunStatus.READY
    )
    drift_blocked_count = sum(
        1
        for result in tenant_results
        if result.status == KnowledgeBaseRuntimeReconciliationTenantRunStatus.DRIFT_BLOCKED
    )
    failed_count = sum(
        1 for result in tenant_results if result.status == KnowledgeBaseRuntimeReconciliationTenantRunStatus.FAILED
    )
    skipped_count = len(tenant_results) - attempted_count
    selected_tenants = tuple(
        selection.tenant_id
        for selection in selections
        if selection.selection_status == KnowledgeBaseRuntimeReconciliationTenantSelectionStatus.SELECTED
    )
    skipped_tenants = tuple(
        selection.tenant_id
        for selection in selections
        if selection.selection_status != KnowledgeBaseRuntimeReconciliationTenantSelectionStatus.SELECTED
    )
    restore_drill_hashes = tuple(
        sorted(
            {
                result.restore_drill_report_hash
                for result in tenant_results
                if result.restore_drill_report_hash is not None
            }
        )
    )
    alert_severity = _highest_alert_severity(result.alert_severity for result in tenant_results)
    runbook_evidence = KnowledgeBaseRuntimeReconciliationRunbookEvidence(
        run_id=run_id,
        worker_id=config.worker_id,
        checked_by=config.checked_by,
        started_at_utc=started_at_utc,
        completed_at_utc=completed_at_utc,
        selected_tenants=selected_tenants,
        skipped_tenants=skipped_tenants,
        restore_drill_report_hashes=restore_drill_hashes,
        retry_contract=config.retry_contract,
    )
    draft = KnowledgeBaseRuntimeReconciliationRunReport(
        run_id=run_id,
        started_at_utc=started_at_utc,
        completed_at_utc=completed_at_utc,
        checked_by=config.checked_by,
        worker_id=config.worker_id,
        selections=selections,
        tenant_results=tenant_results,
        attempted_count=attempted_count,
        ready_count=ready_count,
        drift_blocked_count=drift_blocked_count,
        failed_count=failed_count,
        skipped_count=skipped_count,
        alert_required=alert_severity != KnowledgeBaseRuntimeReconciliationAlertSeverity.NONE,
        alert_severity=alert_severity,
        runbook_evidence=runbook_evidence,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_reconciliation_run_report_hash(draft)})


def build_reconciliation_run_report_hash(report: KnowledgeBaseRuntimeReconciliationRunReport) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def build_default_reconciliation_runner(
    environ: Mapping[str, str] | None = None,
) -> KnowledgeBaseRuntimeReconciliationRunner:
    env = environ or os.environ
    activation_store = build_default_knowledge_base_runtime_activation_store(env)
    reconciliation_store = build_default_knowledge_base_runtime_reconciliation_store(env)
    module_registry = default_module_registry()
    selector = KnowledgeBaseRuntimeReconciliationTenantSelector(
        activation_store=activation_store,
        module_worker_gate=ModuleWorkerGate(module_registry),
        module_registry=module_registry,
    )
    worker = KnowledgeBaseRuntimeReconciliationWorker(
        activation_store=activation_store,
        reconciliation_store=reconciliation_store,
        environ=env,
    )
    audit_logger = build_default_audit_logger(Path(env.get("SUITE_DATA_DIR", "data")))
    return KnowledgeBaseRuntimeReconciliationRunner(selector=selector, worker=worker, audit_logger=audit_logger)


def reconciliation_run_config_from_env(
    environ: Mapping[str, str] | None = None,
) -> KnowledgeBaseRuntimeReconciliationRunConfig:
    env = environ or os.environ
    return KnowledgeBaseRuntimeReconciliationRunConfig(
        checked_by=env.get("SUITE_KB_RUNTIME_RECONCILIATION_CHECKED_BY", "kb-runtime-reconciliation-worker"),
        worker_id=env.get("SUITE_KB_RUNTIME_RECONCILIATION_WORKER_ID", "kb-runtime-reconciler"),
        tenant_ids=_parse_tenant_ids(env.get("SUITE_KB_RUNTIME_RECONCILIATION_TENANT_IDS", "")),
        retry_contract=KnowledgeBaseRuntimeReconciliationRetryContract(
            max_attempts=int(env.get("SUITE_KB_RUNTIME_RECONCILIATION_MAX_ATTEMPTS", "2")),
            retry_backoff_seconds=float(env.get("SUITE_KB_RUNTIME_RECONCILIATION_RETRY_BACKOFF_SECONDS", "0")),
        ),
    )


def run_reconciliation_once_from_env(
    environ: Mapping[str, str] | None = None,
) -> KnowledgeBaseRuntimeReconciliationRunReport:
    runner = build_default_reconciliation_runner(environ)
    return runner.run_once(reconciliation_run_config_from_env(environ))


def exit_code_for_report(report: KnowledgeBaseRuntimeReconciliationRunReport) -> int:
    if report.alert_severity == KnowledgeBaseRuntimeReconciliationAlertSeverity.CRITICAL:
        return 2
    if report.alert_severity == KnowledgeBaseRuntimeReconciliationAlertSeverity.WARNING:
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run Knowledge Base runtime reconciliation once.")
    parser.add_argument("--once", action="store_true", help="Run one reconciliation pass and exit.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the metadata-only run report.")
    args = parser.parse_args(argv)
    del args.once

    report = run_reconciliation_once_from_env()
    print(
        json.dumps(
            report.model_dump(mode="json"),
            indent=2 if args.pretty else None,
            sort_keys=True,
        )
    )
    raise SystemExit(exit_code_for_report(report))


def _skipped_result(
    candidate: KnowledgeBaseRuntimeReconciliationTenantCandidate,
) -> KnowledgeBaseRuntimeReconciliationTenantResult:
    if candidate.selection_status == KnowledgeBaseRuntimeReconciliationTenantSelectionStatus.NO_ACTIVE_RUNTIME:
        return KnowledgeBaseRuntimeReconciliationTenantResult(
            tenant_id=candidate.tenant_id,
            activation_id=None,
            attempts=0,
            status=KnowledgeBaseRuntimeReconciliationTenantRunStatus.NO_ACTIVE_RUNTIME,
            alert_severity=KnowledgeBaseRuntimeReconciliationAlertSeverity.NONE,
            alert_reason=None,
        )
    return KnowledgeBaseRuntimeReconciliationTenantResult(
        tenant_id=candidate.tenant_id,
        activation_id=candidate.activation.activation_id if candidate.activation else None,
        attempts=0,
        status=KnowledgeBaseRuntimeReconciliationTenantRunStatus.MODULE_GATE_BLOCKED,
        restore_drill_report_hash=candidate.activation.restore_drill_report_hash if candidate.activation else None,
        alert_severity=(
            KnowledgeBaseRuntimeReconciliationAlertSeverity.WARNING
            if candidate.activation is not None
            else KnowledgeBaseRuntimeReconciliationAlertSeverity.NONE
        ),
        alert_reason=candidate.blocking_reason,
    )


def _highest_alert_severity(
    severities: Iterable[KnowledgeBaseRuntimeReconciliationAlertSeverity],
) -> KnowledgeBaseRuntimeReconciliationAlertSeverity:
    rank = {
        KnowledgeBaseRuntimeReconciliationAlertSeverity.NONE: 0,
        KnowledgeBaseRuntimeReconciliationAlertSeverity.WARNING: 1,
        KnowledgeBaseRuntimeReconciliationAlertSeverity.CRITICAL: 2,
    }
    severity_values = tuple(severities)
    if not severity_values:
        return KnowledgeBaseRuntimeReconciliationAlertSeverity.NONE
    return max(severity_values, key=lambda severity: rank[severity])


def _parse_tenant_ids(value: str) -> tuple[str, ...]:
    return tuple(tenant_id.strip() for tenant_id in value.split(",") if tenant_id.strip())


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
