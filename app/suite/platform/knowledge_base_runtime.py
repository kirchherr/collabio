from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, field_validator, model_validator

from suite.ai_control_plane.audit import InMemoryAuditLogger, canonical_json, stable_hash
from suite.ai_control_plane.models import UserContext
from suite.platform.knowledge_base import (
    KnowledgeBaseArticleService,
    KnowledgeBaseProductionWriteDeploymentGateEvidence,
    PgKnowledgeBaseArticleRepository,
    PostgresKnowledgeBaseWriteUnitOfWork,
    build_default_knowledge_base_write_approval_ledger,
    build_knowledge_base_production_write_deployment_gate,
    build_production_write_deployment_gate_hash,
)
from suite.storage.adapter_policy import StorageAdapterPolicy, load_storage_adapter_policy
from suite.storage.retention import RetentionManifestPolicy, load_retention_manifest_policy
from suite.storage.s3_compatible_content_store import (
    S3CompatibleObjectStoreClient,
    S3CompatibleProviderProfileEvidence,
    S3CompatibleSourceObjectContentStore,
    build_s3_compatible_provider_profile_evidence,
    build_s3_compatible_provider_profile_evidence_hash,
)
from suite.storage.s3_sdk_client import build_boto3_s3_compatible_client
from suite.storage.source_object_storage import (
    PgSourceObjectRepository,
    SourceObjectContentRecoveryEvidence,
    build_source_object_content_recovery_evidence_hash,
)
from suite.storage.source_objects import PgSourceObjectWriteReceiptStore


class KnowledgeBaseRuntimeBackend(StrEnum):
    DEMO = "demo"
    POSTGRES_S3 = "postgres_s3"


ZERO_HASH = "sha256:" + "0" * 64


class KnowledgeBaseRuntimeActivationCommand(BaseModel):
    provider_profile_id: str
    restore_drill_report_hash: str
    approval_reference: str
    reason: str
    human_confirmation: bool

    @field_validator("provider_profile_id", "approval_reference", "reason")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("knowledge base runtime activation fields must not be empty")
        return value

    @field_validator("restore_drill_report_hash")
    @classmethod
    def require_sha256_hash(cls, value: str) -> str:
        if not value.startswith("sha256:") or len(value) != 71:
            raise ValueError("restore_drill_report_hash must be a sha256 reference")
        return value

    @model_validator(mode="after")
    def require_explicit_human_confirmation(self) -> KnowledgeBaseRuntimeActivationCommand:
        if not self.human_confirmation:
            raise ValueError("knowledge base runtime activation requires explicit human confirmation")
        return self


class KnowledgeBaseRuntimeActivation(BaseModel):
    tenant_id: str
    activation_id: str = Field(default_factory=lambda: f"kb-runtime-activation-{uuid4().hex}")
    backend: KnowledgeBaseRuntimeBackend = KnowledgeBaseRuntimeBackend.POSTGRES_S3
    active: bool = True
    activated_at_utc: str = Field(default_factory=lambda: _utc_now())
    activated_by: str
    provider_profile_id: str
    restore_drill_report_hash: str
    source_content_recovery_evidence: SourceObjectContentRecoveryEvidence
    provider_profile_evidence: S3CompatibleProviderProfileEvidence
    production_write_deployment_gate_evidence: KnowledgeBaseProductionWriteDeploymentGateEvidence
    approval_reference: str
    audit_chain_ref: str
    activation_evidence_hash: str = ZERO_HASH
    schema_version: str = "knowledge_base_runtime_activation.v1"

    @field_validator(
        "tenant_id",
        "activation_id",
        "activated_by",
        "provider_profile_id",
        "restore_drill_report_hash",
        "approval_reference",
        "audit_chain_ref",
        "activation_evidence_hash",
    )
    @classmethod
    def require_non_empty_refs(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("knowledge base runtime activation references must not be empty")
        return value

    @model_validator(mode="after")
    def require_consistent_gate_evidence(self) -> KnowledgeBaseRuntimeActivation:
        if self.backend != KnowledgeBaseRuntimeBackend.POSTGRES_S3:
            raise ValueError("knowledge base runtime activation only supports postgres_s3")
        if self.source_content_recovery_evidence.tenant_id != self.tenant_id:
            raise ValueError("source content recovery evidence tenant does not match activation tenant")
        if self.production_write_deployment_gate_evidence.tenant_id != self.tenant_id:
            raise ValueError("production gate evidence tenant does not match activation tenant")
        if not self.source_content_recovery_evidence.api_wiring_allowed:
            raise ValueError("source content recovery evidence does not allow API wiring")
        if not self.provider_profile_evidence.provider_profile_ready:
            raise ValueError("provider profile evidence is not ready")
        if not self.production_write_deployment_gate_evidence.api_wiring_allowed:
            raise ValueError("production write deployment gate evidence does not allow API wiring")
        if (
            build_source_object_content_recovery_evidence_hash(self.source_content_recovery_evidence)
            != self.source_content_recovery_evidence.evidence_hash
        ):
            raise ValueError("source content recovery evidence hash is invalid")
        if (
            build_s3_compatible_provider_profile_evidence_hash(self.provider_profile_evidence)
            != self.provider_profile_evidence.evidence_hash
        ):
            raise ValueError("provider profile evidence hash is invalid")
        if (
            build_production_write_deployment_gate_hash(self.production_write_deployment_gate_evidence)
            != self.production_write_deployment_gate_evidence.evidence_hash
        ):
            raise ValueError("production gate evidence hash is invalid")
        if (
            self.production_write_deployment_gate_evidence.source_content_recovery_evidence_hash
            != self.source_content_recovery_evidence.evidence_hash
        ):
            raise ValueError("production gate does not reference the source content recovery evidence")
        if (
            self.production_write_deployment_gate_evidence.provider_profile_evidence_hash
            != self.provider_profile_evidence.evidence_hash
        ):
            raise ValueError("production gate does not reference the provider profile evidence")
        if self.production_write_deployment_gate_evidence.restore_drill_report_hash != self.restore_drill_report_hash:
            raise ValueError("production gate restore drill hash does not match activation")
        if self.source_content_recovery_evidence.restore_drill_report_hash != self.restore_drill_report_hash:
            raise ValueError("source content recovery restore drill hash does not match activation")
        if self.activation_evidence_hash != ZERO_HASH and (
            self.activation_evidence_hash != build_knowledge_base_runtime_activation_hash(self)
        ):
            raise ValueError("knowledge base runtime activation hash is invalid")
        return self


class KnowledgeBaseRuntimeActivationView(BaseModel):
    tenant_id: str
    activation_id: str
    backend: KnowledgeBaseRuntimeBackend
    active: bool
    activated_at_utc: str
    activated_by: str
    provider_profile_id: str
    restore_drill_report_hash: str
    source_content_recovery_evidence_hash: str
    provider_profile_evidence_hash: str
    production_write_deployment_gate_evidence_hash: str
    approval_reference: str
    audit_chain_ref: str
    activation_evidence_hash: str
    schema_version: str


class KnowledgeBaseRuntimeReconciliationStatus(StrEnum):
    READY = "ready"
    DRIFT_BLOCKED = "drift_blocked"


class KnowledgeBaseRuntimeReconciliationAction(StrEnum):
    KEEP_ACTIVE = "keep_active"
    DEACTIVATE_RUNTIME = "deactivate_runtime"


class KnowledgeBaseRuntimeReconciliationEvidence(BaseModel):
    tenant_id: str
    activation_id: str
    reconciliation_id: str = Field(default_factory=lambda: f"kb-runtime-reconciliation-{uuid4().hex}")
    checked_at_utc: str = Field(default_factory=lambda: _utc_now())
    checked_by: str
    activation_evidence_hash: str
    previous_source_content_recovery_evidence_hash: str
    observed_source_content_recovery_evidence: SourceObjectContentRecoveryEvidence
    previous_provider_profile_evidence_hash: str
    observed_provider_profile_evidence: S3CompatibleProviderProfileEvidence
    previous_production_write_deployment_gate_evidence_hash: str
    observed_production_write_deployment_gate_evidence: KnowledgeBaseProductionWriteDeploymentGateEvidence
    restore_drill_report_hash: str
    blocking_reasons: tuple[str, ...] = ()
    reconciliation_status: KnowledgeBaseRuntimeReconciliationStatus
    recommended_action: KnowledgeBaseRuntimeReconciliationAction
    runtime_deactivated: bool
    audit_chain_ref: str
    evidence_hash: str = ZERO_HASH
    schema_version: str = "knowledge_base_runtime_reconciliation_evidence.v1"

    @field_validator(
        "tenant_id",
        "activation_id",
        "reconciliation_id",
        "checked_by",
        "activation_evidence_hash",
        "previous_source_content_recovery_evidence_hash",
        "previous_provider_profile_evidence_hash",
        "previous_production_write_deployment_gate_evidence_hash",
        "restore_drill_report_hash",
        "audit_chain_ref",
        "evidence_hash",
    )
    @classmethod
    def require_non_empty_evidence_refs(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("knowledge base runtime reconciliation references must not be empty")
        return value

    @field_validator("blocking_reasons")
    @classmethod
    def require_unique_blocking_reasons(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)):
            raise ValueError("blocking reasons must be unique")
        for reason in value:
            if not reason.strip():
                raise ValueError("blocking reasons must not be empty")
        return value

    @model_validator(mode="after")
    def require_consistent_reconciliation_evidence(self) -> KnowledgeBaseRuntimeReconciliationEvidence:
        if self.observed_source_content_recovery_evidence.tenant_id != self.tenant_id:
            raise ValueError("observed source content recovery evidence tenant does not match")
        if self.observed_production_write_deployment_gate_evidence.tenant_id != self.tenant_id:
            raise ValueError("observed production gate evidence tenant does not match")
        if self.observed_source_content_recovery_evidence.restore_drill_report_hash != self.restore_drill_report_hash:
            raise ValueError("observed source recovery restore drill hash does not match")
        if (
            self.observed_production_write_deployment_gate_evidence.restore_drill_report_hash
            != self.restore_drill_report_hash
        ):
            raise ValueError("observed production gate restore drill hash does not match")
        if self.reconciliation_status == KnowledgeBaseRuntimeReconciliationStatus.READY and self.blocking_reasons:
            raise ValueError("ready reconciliation evidence must not have blocking reasons")
        if self.reconciliation_status == KnowledgeBaseRuntimeReconciliationStatus.DRIFT_BLOCKED and (
            not self.blocking_reasons
        ):
            raise ValueError("blocked reconciliation evidence requires blocking reasons")
        if (
            self.recommended_action == KnowledgeBaseRuntimeReconciliationAction.DEACTIVATE_RUNTIME
        ) != self.runtime_deactivated:
            raise ValueError("runtime_deactivated must match recommended action")
        if self.evidence_hash != ZERO_HASH and (
            self.evidence_hash != build_knowledge_base_runtime_reconciliation_evidence_hash(self)
        ):
            raise ValueError("knowledge base runtime reconciliation evidence hash is invalid")
        return self


class KnowledgeBaseRuntimeReconciliationView(BaseModel):
    tenant_id: str
    activation_id: str
    reconciliation_id: str
    checked_at_utc: str
    checked_by: str
    activation_evidence_hash: str
    observed_source_content_recovery_evidence_hash: str
    observed_provider_profile_evidence_hash: str
    observed_production_write_deployment_gate_evidence_hash: str
    restore_drill_report_hash: str
    blocking_reasons: tuple[str, ...]
    reconciliation_status: KnowledgeBaseRuntimeReconciliationStatus
    recommended_action: KnowledgeBaseRuntimeReconciliationAction
    runtime_deactivated: bool
    audit_chain_ref: str
    evidence_hash: str
    schema_version: str


@dataclass(frozen=True)
class PostgresS3KnowledgeBaseRuntimeConfig:
    tenant_id: str
    database_dsn: str
    restore_drill_report_hash: str
    storage_policy_path: Path = Path("docs/storage_adapter_policy.json")
    retention_policy_path: Path = Path("docs/retention_manifest_policy.json")
    provider_profile_id: str = "s3-compatible-runtime"
    s3_endpoint_url: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: str | None = None
    s3_region_name: str = "us-east-1"
    s3_storage_provider: str = "s3-compatible"
    bootstrap_bucket_profiles: bool = False

    def require_sdk_credentials(self) -> None:
        if not (self.s3_access_key_id and self.s3_access_key_id.strip()):
            raise ValueError("S3-compatible runtime requires SUITE_S3_ACCESS_KEY_ID")
        if not (self.s3_secret_access_key and self.s3_secret_access_key.strip()):
            raise ValueError("S3-compatible runtime requires SUITE_S3_SECRET_ACCESS_KEY")


@dataclass(frozen=True)
class KnowledgeBasePostgresS3RuntimeWiring:
    config: PostgresS3KnowledgeBaseRuntimeConfig
    storage_policy: StorageAdapterPolicy
    retention_policy: RetentionManifestPolicy
    content_store: S3CompatibleSourceObjectContentStore
    source_repository: PgSourceObjectRepository
    article_repository: PgKnowledgeBaseArticleRepository
    source_object_write_receipt_store: PgSourceObjectWriteReceiptStore
    provider_profile_evidence: S3CompatibleProviderProfileEvidence
    source_content_recovery_evidence: SourceObjectContentRecoveryEvidence
    production_write_deployment_gate_evidence: KnowledgeBaseProductionWriteDeploymentGateEvidence
    write_unit_of_work: PostgresKnowledgeBaseWriteUnitOfWork


@dataclass(frozen=True)
class KnowledgeBasePostgresS3RuntimeGateEvidence:
    config: PostgresS3KnowledgeBaseRuntimeConfig
    storage_policy: StorageAdapterPolicy
    retention_policy: RetentionManifestPolicy
    content_store: S3CompatibleSourceObjectContentStore
    source_repository: PgSourceObjectRepository
    provider_profile_evidence: S3CompatibleProviderProfileEvidence
    source_content_recovery_evidence: SourceObjectContentRecoveryEvidence
    production_write_deployment_gate_evidence: KnowledgeBaseProductionWriteDeploymentGateEvidence


class InMemoryKnowledgeBaseRuntimeActivationStore:
    def __init__(self, activations: tuple[KnowledgeBaseRuntimeActivation, ...] = ()) -> None:
        self._activations: dict[tuple[str, str], KnowledgeBaseRuntimeActivation] = {}
        for activation in activations:
            self.activate(activation)

    def activate(self, activation: KnowledgeBaseRuntimeActivation) -> KnowledgeBaseRuntimeActivation:
        for key, existing in tuple(self._activations.items()):
            if existing.tenant_id == activation.tenant_id and existing.active:
                self._activations[key] = existing.model_copy(update={"active": False})
        active_activation = activation.model_copy(update={"active": True})
        self._activations[(active_activation.tenant_id, active_activation.activation_id)] = active_activation
        return active_activation

    def get_active(self, *, tenant_id: str) -> KnowledgeBaseRuntimeActivation | None:
        candidates = [
            activation
            for activation in self._activations.values()
            if activation.tenant_id == tenant_id and activation.active
        ]
        if not candidates:
            return None
        return sorted(candidates, key=lambda activation: activation.activated_at_utc)[-1]

    def list_active(self) -> tuple[KnowledgeBaseRuntimeActivation, ...]:
        return tuple(
            sorted(
                (activation for activation in self._activations.values() if activation.active),
                key=lambda activation: (activation.tenant_id, activation.activated_at_utc, activation.activation_id),
            )
        )

    def deactivate(
        self,
        *,
        tenant_id: str,
        activation_id: str,
        deactivated_by: str,
        reason: str,
        reconciliation_evidence_hash: str,
    ) -> None:
        del deactivated_by, reason, reconciliation_evidence_hash
        key = (tenant_id, activation_id)
        activation = self._activations.get(key)
        if activation is None:
            raise LookupError("knowledge base runtime activation not found")
        self._activations[key] = activation.model_copy(update={"active": False})


class PgKnowledgeBaseRuntimeActivationStore:
    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    def activate(self, activation: KnowledgeBaseRuntimeActivation) -> KnowledgeBaseRuntimeActivation:
        activation = activation.model_copy(update={"active": True})
        with psycopg.connect(self.database_dsn) as connection, connection.transaction():
            self._set_tenant(connection, activation.tenant_id)
            connection.execute(
                """
                UPDATE collabio.knowledge_base_runtime_activations
                SET active = false
                    , deactivated_at_utc = COALESCE(deactivated_at_utc, %s)
                    , deactivated_by = COALESCE(deactivated_by, %s)
                    , deactivation_reason = COALESCE(deactivation_reason, %s)
                WHERE tenant_id = %s
                  AND active = true
                """,
                (
                    activation.activated_at_utc,
                    activation.activated_by,
                    "superseded_by_runtime_activation",
                    activation.tenant_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO collabio.knowledge_base_runtime_activations (
                    tenant_id,
                    activation_id,
                    backend,
                    active,
                    activated_at_utc,
                    activated_by,
                    provider_profile_id,
                    restore_drill_report_hash,
                    source_content_recovery_evidence_hash,
                    provider_profile_evidence_hash,
                    production_write_deployment_gate_evidence_hash,
                    source_content_recovery_evidence,
                    provider_profile_evidence,
                    production_write_deployment_gate_evidence,
                    approval_reference,
                    audit_chain_ref,
                    activation_evidence_hash,
                    schema_version
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s
                )
                """,
                self._activation_values(activation),
            )
        return activation

    def get_active(self, *, tenant_id: str) -> KnowledgeBaseRuntimeActivation | None:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            row = connection.execute(
                """
                SELECT
                    tenant_id,
                    activation_id,
                    backend,
                    active,
                    activated_at_utc,
                    activated_by,
                    provider_profile_id,
                    restore_drill_report_hash,
                    source_content_recovery_evidence,
                    provider_profile_evidence,
                    production_write_deployment_gate_evidence,
                    approval_reference,
                    audit_chain_ref,
                    activation_evidence_hash,
                    schema_version
                FROM collabio.knowledge_base_runtime_activations
                WHERE tenant_id = %s
                  AND active = true
                ORDER BY activated_at_utc DESC, activation_id DESC
                LIMIT 1
                """,
                (tenant_id,),
            ).fetchone()
        if row is None:
            return None
        return self._activation_from_row(row)

    def list_active(self) -> tuple[KnowledgeBaseRuntimeActivation, ...]:
        with psycopg.connect(self.database_dsn) as connection:
            rows = connection.execute(
                """
                SELECT
                    tenant_id,
                    activation_id,
                    backend,
                    active,
                    activated_at_utc,
                    activated_by,
                    provider_profile_id,
                    restore_drill_report_hash,
                    source_content_recovery_evidence,
                    provider_profile_evidence,
                    production_write_deployment_gate_evidence,
                    approval_reference,
                    audit_chain_ref,
                    activation_evidence_hash,
                    schema_version
                FROM collabio.knowledge_base_runtime_activations
                WHERE active = true
                ORDER BY tenant_id, activated_at_utc DESC, activation_id DESC
                """
            ).fetchall()
        return tuple(self._activation_from_row(row) for row in rows)

    def deactivate(
        self,
        *,
        tenant_id: str,
        activation_id: str,
        deactivated_by: str,
        reason: str,
        reconciliation_evidence_hash: str,
    ) -> None:
        with psycopg.connect(self.database_dsn) as connection, connection.transaction():
            self._set_tenant(connection, tenant_id)
            result = connection.execute(
                """
                UPDATE collabio.knowledge_base_runtime_activations
                SET active = false,
                    deactivated_at_utc = now(),
                    deactivated_by = %s,
                    deactivation_reason = %s,
                    deactivation_reconciliation_evidence_hash = %s
                WHERE tenant_id = %s
                  AND activation_id = %s
                  AND active = true
                """,
                (deactivated_by, reason, reconciliation_evidence_hash, tenant_id, activation_id),
            )
            if result.rowcount != 1:
                raise LookupError("active knowledge base runtime activation not found")

    def _activation_values(self, activation: KnowledgeBaseRuntimeActivation) -> tuple[Any, ...]:
        return (
            activation.tenant_id,
            activation.activation_id,
            activation.backend.value,
            activation.active,
            activation.activated_at_utc,
            activation.activated_by,
            activation.provider_profile_id,
            activation.restore_drill_report_hash,
            activation.source_content_recovery_evidence.evidence_hash,
            activation.provider_profile_evidence.evidence_hash,
            activation.production_write_deployment_gate_evidence.evidence_hash,
            Jsonb(activation.source_content_recovery_evidence.model_dump(mode="json")),
            Jsonb(activation.provider_profile_evidence.model_dump(mode="json")),
            Jsonb(activation.production_write_deployment_gate_evidence.model_dump(mode="json")),
            activation.approval_reference,
            activation.audit_chain_ref,
            activation.activation_evidence_hash,
            activation.schema_version,
        )

    def _activation_from_row(self, row: tuple[Any, ...]) -> KnowledgeBaseRuntimeActivation:
        return KnowledgeBaseRuntimeActivation(
            tenant_id=str(row[0]),
            activation_id=str(row[1]),
            backend=KnowledgeBaseRuntimeBackend(str(row[2])),
            active=bool(row[3]),
            activated_at_utc=_utc_timestamp(row[4]),
            activated_by=str(row[5]),
            provider_profile_id=str(row[6]),
            restore_drill_report_hash=str(row[7]),
            source_content_recovery_evidence=SourceObjectContentRecoveryEvidence.model_validate(row[8]),
            provider_profile_evidence=S3CompatibleProviderProfileEvidence.model_validate(row[9]),
            production_write_deployment_gate_evidence=KnowledgeBaseProductionWriteDeploymentGateEvidence.model_validate(
                row[10]
            ),
            approval_reference=str(row[11]),
            audit_chain_ref=str(row[12]),
            activation_evidence_hash=str(row[13]),
            schema_version=str(row[14]),
        )

    def _set_tenant(self, connection: psycopg.Connection[Any], tenant_id: str) -> None:
        connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))


class InMemoryKnowledgeBaseRuntimeReconciliationStore:
    def __init__(self, evidences: tuple[KnowledgeBaseRuntimeReconciliationEvidence, ...] = ()) -> None:
        self._evidences: dict[tuple[str, str], KnowledgeBaseRuntimeReconciliationEvidence] = {
            (evidence.tenant_id, evidence.reconciliation_id): evidence for evidence in evidences
        }

    def append(
        self,
        evidence: KnowledgeBaseRuntimeReconciliationEvidence,
    ) -> KnowledgeBaseRuntimeReconciliationEvidence:
        key = (evidence.tenant_id, evidence.reconciliation_id)
        if key in self._evidences:
            raise ValueError("knowledge base runtime reconciliation evidence already exists")
        self._evidences[key] = evidence
        return evidence

    def latest_for_activation(
        self,
        *,
        tenant_id: str,
        activation_id: str,
    ) -> KnowledgeBaseRuntimeReconciliationEvidence | None:
        candidates = [
            evidence
            for evidence in self._evidences.values()
            if evidence.tenant_id == tenant_id and evidence.activation_id == activation_id
        ]
        if not candidates:
            return None
        return sorted(candidates, key=lambda evidence: evidence.checked_at_utc)[-1]


class PgKnowledgeBaseRuntimeReconciliationStore:
    def __init__(self, *, database_dsn: str) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn

    def append(
        self,
        evidence: KnowledgeBaseRuntimeReconciliationEvidence,
    ) -> KnowledgeBaseRuntimeReconciliationEvidence:
        with psycopg.connect(self.database_dsn) as connection, connection.transaction():
            self._set_tenant(connection, evidence.tenant_id)
            connection.execute(
                """
                INSERT INTO collabio.knowledge_base_runtime_reconciliation_evidence (
                    tenant_id,
                    activation_id,
                    reconciliation_id,
                    checked_at_utc,
                    checked_by,
                    activation_evidence_hash,
                    previous_source_content_recovery_evidence_hash,
                    observed_source_content_recovery_evidence_hash,
                    previous_provider_profile_evidence_hash,
                    observed_provider_profile_evidence_hash,
                    previous_production_write_deployment_gate_evidence_hash,
                    observed_production_write_deployment_gate_evidence_hash,
                    observed_source_content_recovery_evidence,
                    observed_provider_profile_evidence,
                    observed_production_write_deployment_gate_evidence,
                    restore_drill_report_hash,
                    blocking_reasons,
                    reconciliation_status,
                    recommended_action,
                    runtime_deactivated,
                    audit_chain_ref,
                    evidence_hash,
                    schema_version
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                self._evidence_values(evidence),
            )
        return evidence

    def latest_for_activation(
        self,
        *,
        tenant_id: str,
        activation_id: str,
    ) -> KnowledgeBaseRuntimeReconciliationEvidence | None:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            row = connection.execute(
                """
                SELECT
                    tenant_id,
                    activation_id,
                    reconciliation_id,
                    checked_at_utc,
                    checked_by,
                    activation_evidence_hash,
                    previous_source_content_recovery_evidence_hash,
                    observed_source_content_recovery_evidence,
                    previous_provider_profile_evidence_hash,
                    observed_provider_profile_evidence,
                    previous_production_write_deployment_gate_evidence_hash,
                    observed_production_write_deployment_gate_evidence,
                    restore_drill_report_hash,
                    blocking_reasons,
                    reconciliation_status,
                    recommended_action,
                    runtime_deactivated,
                    audit_chain_ref,
                    evidence_hash,
                    schema_version
                FROM collabio.knowledge_base_runtime_reconciliation_evidence
                WHERE tenant_id = %s
                  AND activation_id = %s
                ORDER BY checked_at_utc DESC, reconciliation_id DESC
                LIMIT 1
                """,
                (tenant_id, activation_id),
            ).fetchone()
        if row is None:
            return None
        return self._evidence_from_row(row)

    def _evidence_values(self, evidence: KnowledgeBaseRuntimeReconciliationEvidence) -> tuple[Any, ...]:
        return (
            evidence.tenant_id,
            evidence.activation_id,
            evidence.reconciliation_id,
            evidence.checked_at_utc,
            evidence.checked_by,
            evidence.activation_evidence_hash,
            evidence.previous_source_content_recovery_evidence_hash,
            evidence.observed_source_content_recovery_evidence.evidence_hash,
            evidence.previous_provider_profile_evidence_hash,
            evidence.observed_provider_profile_evidence.evidence_hash,
            evidence.previous_production_write_deployment_gate_evidence_hash,
            evidence.observed_production_write_deployment_gate_evidence.evidence_hash,
            Jsonb(evidence.observed_source_content_recovery_evidence.model_dump(mode="json")),
            Jsonb(evidence.observed_provider_profile_evidence.model_dump(mode="json")),
            Jsonb(evidence.observed_production_write_deployment_gate_evidence.model_dump(mode="json")),
            evidence.restore_drill_report_hash,
            Jsonb(list(evidence.blocking_reasons)),
            evidence.reconciliation_status.value,
            evidence.recommended_action.value,
            evidence.runtime_deactivated,
            evidence.audit_chain_ref,
            evidence.evidence_hash,
            evidence.schema_version,
        )

    def _evidence_from_row(self, row: tuple[Any, ...]) -> KnowledgeBaseRuntimeReconciliationEvidence:
        return KnowledgeBaseRuntimeReconciliationEvidence(
            tenant_id=str(row[0]),
            activation_id=str(row[1]),
            reconciliation_id=str(row[2]),
            checked_at_utc=_utc_timestamp(row[3]),
            checked_by=str(row[4]),
            activation_evidence_hash=str(row[5]),
            previous_source_content_recovery_evidence_hash=str(row[6]),
            observed_source_content_recovery_evidence=SourceObjectContentRecoveryEvidence.model_validate(row[7]),
            previous_provider_profile_evidence_hash=str(row[8]),
            observed_provider_profile_evidence=S3CompatibleProviderProfileEvidence.model_validate(row[9]),
            previous_production_write_deployment_gate_evidence_hash=str(row[10]),
            observed_production_write_deployment_gate_evidence=(
                KnowledgeBaseProductionWriteDeploymentGateEvidence.model_validate(row[11])
            ),
            restore_drill_report_hash=str(row[12]),
            blocking_reasons=tuple(str(reason) for reason in row[13]),
            reconciliation_status=KnowledgeBaseRuntimeReconciliationStatus(str(row[14])),
            recommended_action=KnowledgeBaseRuntimeReconciliationAction(str(row[15])),
            runtime_deactivated=bool(row[16]),
            audit_chain_ref=str(row[17]),
            evidence_hash=str(row[18]),
            schema_version=str(row[19]),
        )

    def _set_tenant(self, connection: psycopg.Connection[Any], tenant_id: str) -> None:
        connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))


class KnowledgeBaseArticleServiceResolver:
    def __init__(
        self,
        *,
        default_service: KnowledgeBaseArticleService,
        audit_logger: InMemoryAuditLogger,
        activation_store: InMemoryKnowledgeBaseRuntimeActivationStore | PgKnowledgeBaseRuntimeActivationStore,
        environ: Mapping[str, str] | None = None,
        object_store_client: S3CompatibleObjectStoreClient | None = None,
    ) -> None:
        self.default_service = default_service
        self.audit_logger = audit_logger
        self.activation_store = activation_store
        self.environ = environ
        self.object_store_client = object_store_client

    def service_for_tenant(self, *, tenant_id: str) -> KnowledgeBaseArticleService:
        activation = self.activation_store.get_active(tenant_id=tenant_id)
        if activation is None:
            return self.default_service
        return self._service_from_activation(activation)

    def activate_postgres_s3_runtime(
        self,
        *,
        command: KnowledgeBaseRuntimeActivationCommand,
        user_context: UserContext,
        audit_chain_ref: str,
    ) -> KnowledgeBaseRuntimeActivation:
        config = build_postgres_s3_knowledge_base_runtime_config_for_tenant(
            tenant_id=user_context.tenant_id,
            restore_drill_report_hash=command.restore_drill_report_hash,
            provider_profile_id=command.provider_profile_id,
            environ=self.environ,
        )
        wiring = build_postgres_s3_knowledge_base_runtime(
            config=config,
            object_store_client=self.object_store_client,
        )
        activation = build_knowledge_base_runtime_activation(
            tenant_id=user_context.tenant_id,
            activated_by=user_context.user_id,
            provider_profile_id=command.provider_profile_id,
            restore_drill_report_hash=command.restore_drill_report_hash,
            source_content_recovery_evidence=wiring.source_content_recovery_evidence,
            provider_profile_evidence=wiring.provider_profile_evidence,
            production_write_deployment_gate_evidence=wiring.production_write_deployment_gate_evidence,
            approval_reference=command.approval_reference,
            audit_chain_ref=audit_chain_ref,
        )
        return self.activation_store.activate(activation)

    def _service_from_activation(self, activation: KnowledgeBaseRuntimeActivation) -> KnowledgeBaseArticleService:
        config = build_postgres_s3_knowledge_base_runtime_config_for_tenant(
            tenant_id=activation.tenant_id,
            restore_drill_report_hash=activation.restore_drill_report_hash,
            provider_profile_id=activation.provider_profile_id,
            environ=self.environ,
        )
        storage_policy = load_storage_adapter_policy(config.storage_policy_path)
        retention_policy = load_retention_manifest_policy(config.retention_policy_path)
        client = self.object_store_client
        if client is None:
            config.require_sdk_credentials()
            client = build_boto3_s3_compatible_client(
                endpoint_url=config.s3_endpoint_url,
                access_key_id=config.s3_access_key_id or "",
                secret_access_key=config.s3_secret_access_key or "",
                region_name=config.s3_region_name,
                storage_provider=config.s3_storage_provider,
            )
        content_store = S3CompatibleSourceObjectContentStore(client=client, storage_policy=storage_policy)
        source_repository = PgSourceObjectRepository(
            database_dsn=config.database_dsn,
            content_store=content_store,
            retention_policy=retention_policy,
            storage_policy=storage_policy,
        )
        article_repository = PgKnowledgeBaseArticleRepository(database_dsn=config.database_dsn)
        receipt_store = PgSourceObjectWriteReceiptStore(database_dsn=config.database_dsn)
        write_unit_of_work = PostgresKnowledgeBaseWriteUnitOfWork(
            database_dsn=config.database_dsn,
            article_repository=article_repository,
            source_repository=source_repository,
            source_object_write_receipt_store=receipt_store,
            source_content_recovery_evidence=activation.source_content_recovery_evidence,
            production_write_deployment_gate_evidence=activation.production_write_deployment_gate_evidence,
            require_source_content_recovery_gate=True,
        )
        return KnowledgeBaseArticleService(
            repository=article_repository,
            source_repository=source_repository,
            audit_logger=self.audit_logger,
            write_approval_ledger=build_default_knowledge_base_write_approval_ledger(),
            source_object_write_receipt_store=receipt_store,
            write_unit_of_work=write_unit_of_work,
        )


class KnowledgeBaseRuntimeReconciliationWorker:
    def __init__(
        self,
        *,
        activation_store: InMemoryKnowledgeBaseRuntimeActivationStore | PgKnowledgeBaseRuntimeActivationStore,
        reconciliation_store: InMemoryKnowledgeBaseRuntimeReconciliationStore
        | PgKnowledgeBaseRuntimeReconciliationStore,
        environ: Mapping[str, str] | None = None,
        object_store_client: S3CompatibleObjectStoreClient | None = None,
    ) -> None:
        self.activation_store = activation_store
        self.reconciliation_store = reconciliation_store
        self.environ = environ
        self.object_store_client = object_store_client

    def reconcile_active_tenant(
        self,
        *,
        tenant_id: str,
        checked_by: str,
        audit_chain_ref: str,
    ) -> KnowledgeBaseRuntimeReconciliationEvidence | None:
        activation = self.activation_store.get_active(tenant_id=tenant_id)
        if activation is None:
            return None
        return self.reconcile_activation(
            activation=activation,
            checked_by=checked_by,
            audit_chain_ref=audit_chain_ref,
        )

    def reconcile_activation(
        self,
        *,
        activation: KnowledgeBaseRuntimeActivation,
        checked_by: str,
        audit_chain_ref: str,
    ) -> KnowledgeBaseRuntimeReconciliationEvidence:
        config = build_postgres_s3_knowledge_base_runtime_config_for_tenant(
            tenant_id=activation.tenant_id,
            restore_drill_report_hash=activation.restore_drill_report_hash,
            provider_profile_id=activation.provider_profile_id,
            environ=self.environ,
        )
        gate_evidence = build_postgres_s3_knowledge_base_runtime_gate_evidence(
            config=config,
            object_store_client=self.object_store_client,
            bootstrap_bucket_profiles=False,
        )
        evidence = build_knowledge_base_runtime_reconciliation_evidence(
            activation=activation,
            observed_source_content_recovery_evidence=gate_evidence.source_content_recovery_evidence,
            observed_provider_profile_evidence=gate_evidence.provider_profile_evidence,
            observed_production_write_deployment_gate_evidence=gate_evidence.production_write_deployment_gate_evidence,
            checked_by=checked_by,
            audit_chain_ref=audit_chain_ref,
        )
        appended = self.reconciliation_store.append(evidence)
        if appended.runtime_deactivated:
            self.activation_store.deactivate(
                tenant_id=activation.tenant_id,
                activation_id=activation.activation_id,
                deactivated_by=checked_by,
                reason="runtime_reconciliation_drift",
                reconciliation_evidence_hash=appended.evidence_hash,
            )
        return appended


def build_knowledge_base_runtime_activation(
    *,
    tenant_id: str,
    activated_by: str,
    provider_profile_id: str,
    restore_drill_report_hash: str,
    source_content_recovery_evidence: SourceObjectContentRecoveryEvidence,
    provider_profile_evidence: S3CompatibleProviderProfileEvidence,
    production_write_deployment_gate_evidence: KnowledgeBaseProductionWriteDeploymentGateEvidence,
    approval_reference: str,
    audit_chain_ref: str,
    activated_at_utc: str | None = None,
) -> KnowledgeBaseRuntimeActivation:
    draft = KnowledgeBaseRuntimeActivation(
        tenant_id=tenant_id,
        activated_at_utc=activated_at_utc or _utc_now(),
        activated_by=activated_by,
        provider_profile_id=provider_profile_id,
        restore_drill_report_hash=restore_drill_report_hash,
        source_content_recovery_evidence=source_content_recovery_evidence,
        provider_profile_evidence=provider_profile_evidence,
        production_write_deployment_gate_evidence=production_write_deployment_gate_evidence,
        approval_reference=approval_reference,
        audit_chain_ref=audit_chain_ref,
        activation_evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"activation_evidence_hash": build_knowledge_base_runtime_activation_hash(draft)})


def build_knowledge_base_runtime_activation_hash(activation: KnowledgeBaseRuntimeActivation) -> str:
    return stable_hash(
        canonical_json(activation.model_dump(mode="json", exclude={"active", "activation_evidence_hash"}))
    )


def build_knowledge_base_runtime_reconciliation_evidence(
    *,
    activation: KnowledgeBaseRuntimeActivation,
    observed_source_content_recovery_evidence: SourceObjectContentRecoveryEvidence,
    observed_provider_profile_evidence: S3CompatibleProviderProfileEvidence,
    observed_production_write_deployment_gate_evidence: KnowledgeBaseProductionWriteDeploymentGateEvidence,
    checked_by: str,
    audit_chain_ref: str,
    checked_at_utc: str | None = None,
) -> KnowledgeBaseRuntimeReconciliationEvidence:
    blocking_reasons = _runtime_reconciliation_blocking_reasons(
        activation=activation,
        observed_source_content_recovery_evidence=observed_source_content_recovery_evidence,
        observed_provider_profile_evidence=observed_provider_profile_evidence,
        observed_production_write_deployment_gate_evidence=observed_production_write_deployment_gate_evidence,
    )
    blocked = bool(blocking_reasons)
    draft = KnowledgeBaseRuntimeReconciliationEvidence(
        tenant_id=activation.tenant_id,
        activation_id=activation.activation_id,
        checked_at_utc=checked_at_utc or _utc_now(),
        checked_by=checked_by,
        activation_evidence_hash=activation.activation_evidence_hash,
        previous_source_content_recovery_evidence_hash=activation.source_content_recovery_evidence.evidence_hash,
        observed_source_content_recovery_evidence=observed_source_content_recovery_evidence,
        previous_provider_profile_evidence_hash=activation.provider_profile_evidence.evidence_hash,
        observed_provider_profile_evidence=observed_provider_profile_evidence,
        previous_production_write_deployment_gate_evidence_hash=(
            activation.production_write_deployment_gate_evidence.evidence_hash
        ),
        observed_production_write_deployment_gate_evidence=observed_production_write_deployment_gate_evidence,
        restore_drill_report_hash=activation.restore_drill_report_hash,
        blocking_reasons=blocking_reasons,
        reconciliation_status=(
            KnowledgeBaseRuntimeReconciliationStatus.DRIFT_BLOCKED
            if blocked
            else KnowledgeBaseRuntimeReconciliationStatus.READY
        ),
        recommended_action=(
            KnowledgeBaseRuntimeReconciliationAction.DEACTIVATE_RUNTIME
            if blocked
            else KnowledgeBaseRuntimeReconciliationAction.KEEP_ACTIVE
        ),
        runtime_deactivated=blocked,
        audit_chain_ref=audit_chain_ref,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_knowledge_base_runtime_reconciliation_evidence_hash(draft)})


def build_knowledge_base_runtime_reconciliation_evidence_hash(
    evidence: KnowledgeBaseRuntimeReconciliationEvidence,
) -> str:
    return stable_hash(canonical_json(evidence.model_dump(mode="json", exclude={"evidence_hash"})))


def knowledge_base_runtime_activation_view(
    activation: KnowledgeBaseRuntimeActivation,
) -> KnowledgeBaseRuntimeActivationView:
    return KnowledgeBaseRuntimeActivationView(
        tenant_id=activation.tenant_id,
        activation_id=activation.activation_id,
        backend=activation.backend,
        active=activation.active,
        activated_at_utc=activation.activated_at_utc,
        activated_by=activation.activated_by,
        provider_profile_id=activation.provider_profile_id,
        restore_drill_report_hash=activation.restore_drill_report_hash,
        source_content_recovery_evidence_hash=activation.source_content_recovery_evidence.evidence_hash,
        provider_profile_evidence_hash=activation.provider_profile_evidence.evidence_hash,
        production_write_deployment_gate_evidence_hash=activation.production_write_deployment_gate_evidence.evidence_hash,
        approval_reference=activation.approval_reference,
        audit_chain_ref=activation.audit_chain_ref,
        activation_evidence_hash=activation.activation_evidence_hash,
        schema_version=activation.schema_version,
    )


def knowledge_base_runtime_reconciliation_view(
    evidence: KnowledgeBaseRuntimeReconciliationEvidence,
) -> KnowledgeBaseRuntimeReconciliationView:
    return KnowledgeBaseRuntimeReconciliationView(
        tenant_id=evidence.tenant_id,
        activation_id=evidence.activation_id,
        reconciliation_id=evidence.reconciliation_id,
        checked_at_utc=evidence.checked_at_utc,
        checked_by=evidence.checked_by,
        activation_evidence_hash=evidence.activation_evidence_hash,
        observed_source_content_recovery_evidence_hash=(
            evidence.observed_source_content_recovery_evidence.evidence_hash
        ),
        observed_provider_profile_evidence_hash=evidence.observed_provider_profile_evidence.evidence_hash,
        observed_production_write_deployment_gate_evidence_hash=(
            evidence.observed_production_write_deployment_gate_evidence.evidence_hash
        ),
        restore_drill_report_hash=evidence.restore_drill_report_hash,
        blocking_reasons=evidence.blocking_reasons,
        reconciliation_status=evidence.reconciliation_status,
        recommended_action=evidence.recommended_action,
        runtime_deactivated=evidence.runtime_deactivated,
        audit_chain_ref=evidence.audit_chain_ref,
        evidence_hash=evidence.evidence_hash,
        schema_version=evidence.schema_version,
    )


def build_default_knowledge_base_runtime_activation_store(
    environ: Mapping[str, str] | None = None,
) -> InMemoryKnowledgeBaseRuntimeActivationStore | PgKnowledgeBaseRuntimeActivationStore:
    env = environ or os.environ
    backend = env.get("SUITE_KB_RUNTIME_ACTIVATION_STORE_BACKEND", "memory").strip().lower()
    if backend in {"memory", "inmemory", "in-memory"}:
        return InMemoryKnowledgeBaseRuntimeActivationStore()
    if backend in {"postgres", "postgresql", "pg"}:
        database_dsn = env.get("SUITE_KB_RUNTIME_ACTIVATION_DSN") or env.get("SUITE_DATABASE_DSN")
        if not database_dsn:
            raise ValueError(
                "PostgreSQL knowledge base runtime activation store requires "
                "SUITE_KB_RUNTIME_ACTIVATION_DSN or SUITE_DATABASE_DSN"
            )
        return PgKnowledgeBaseRuntimeActivationStore(database_dsn=database_dsn)
    raise ValueError(f"Unsupported SUITE_KB_RUNTIME_ACTIVATION_STORE_BACKEND: {backend}")


def build_default_knowledge_base_runtime_reconciliation_store(
    environ: Mapping[str, str] | None = None,
) -> InMemoryKnowledgeBaseRuntimeReconciliationStore | PgKnowledgeBaseRuntimeReconciliationStore:
    env = environ or os.environ
    backend = env.get("SUITE_KB_RUNTIME_RECONCILIATION_STORE_BACKEND", "memory").strip().lower()
    if backend in {"memory", "inmemory", "in-memory"}:
        return InMemoryKnowledgeBaseRuntimeReconciliationStore()
    if backend in {"postgres", "postgresql", "pg"}:
        database_dsn = env.get("SUITE_KB_RUNTIME_RECONCILIATION_DSN") or env.get("SUITE_DATABASE_DSN")
        if not database_dsn:
            raise ValueError(
                "PostgreSQL knowledge base runtime reconciliation store requires "
                "SUITE_KB_RUNTIME_RECONCILIATION_DSN or SUITE_DATABASE_DSN"
            )
        return PgKnowledgeBaseRuntimeReconciliationStore(database_dsn=database_dsn)
    raise ValueError(f"Unsupported SUITE_KB_RUNTIME_RECONCILIATION_STORE_BACKEND: {backend}")


def knowledge_base_runtime_backend_from_env(
    environ: Mapping[str, str] | None = None,
) -> KnowledgeBaseRuntimeBackend:
    env = environ or os.environ
    raw_backend = env.get("SUITE_KB_RUNTIME_BACKEND", "demo").strip().lower()
    if raw_backend in {"demo", "memory", "inmemory", "in-memory"}:
        return KnowledgeBaseRuntimeBackend.DEMO
    if raw_backend in {"postgres_s3", "postgres-s3", "postgres+s3", "postgres_s3_compatible"}:
        return KnowledgeBaseRuntimeBackend.POSTGRES_S3
    if raw_backend in {"auto", "configured"}:
        content_backend = env.get("SUITE_SOURCE_OBJECT_CONTENT_STORE_BACKEND", "memory").strip().lower()
        if content_backend in {"s3", "s3_compatible", "s3-compatible", "minio"}:
            return KnowledgeBaseRuntimeBackend.POSTGRES_S3
        return KnowledgeBaseRuntimeBackend.DEMO
    raise ValueError(f"Unsupported SUITE_KB_RUNTIME_BACKEND: {raw_backend}")


def build_postgres_s3_knowledge_base_runtime_config_from_env(
    environ: Mapping[str, str] | None = None,
) -> PostgresS3KnowledgeBaseRuntimeConfig:
    env = environ or os.environ
    return build_postgres_s3_knowledge_base_runtime_config_for_tenant(
        tenant_id=_required_env(env, "SUITE_KB_RUNTIME_TENANT_ID"),
        restore_drill_report_hash=_required_env(env, "SUITE_KB_RESTORE_DRILL_REPORT_HASH"),
        provider_profile_id=env.get("SUITE_S3_PROVIDER_PROFILE_ID", "s3-compatible-runtime"),
        environ=env,
    )


def build_postgres_s3_knowledge_base_runtime_config_for_tenant(
    *,
    tenant_id: str,
    restore_drill_report_hash: str,
    provider_profile_id: str,
    environ: Mapping[str, str] | None = None,
) -> PostgresS3KnowledgeBaseRuntimeConfig:
    env = environ or os.environ
    return PostgresS3KnowledgeBaseRuntimeConfig(
        tenant_id=tenant_id,
        database_dsn=_first_required_env(env, "SUITE_KB_RUNTIME_DATABASE_DSN", "SUITE_DATABASE_DSN"),
        restore_drill_report_hash=restore_drill_report_hash,
        storage_policy_path=Path(env.get("SUITE_STORAGE_POLICY_PATH", "docs/storage_adapter_policy.json")),
        retention_policy_path=Path(env.get("SUITE_RETENTION_POLICY_PATH", "docs/retention_manifest_policy.json")),
        provider_profile_id=provider_profile_id,
        s3_endpoint_url=_optional_env(env, "SUITE_S3_ENDPOINT_URL"),
        s3_access_key_id=_optional_env(env, "SUITE_S3_ACCESS_KEY_ID"),
        s3_secret_access_key=_optional_env(env, "SUITE_S3_SECRET_ACCESS_KEY"),
        s3_region_name=env.get("SUITE_S3_REGION", "us-east-1"),
        s3_storage_provider=env.get("SUITE_S3_STORAGE_PROVIDER", "s3-compatible"),
        bootstrap_bucket_profiles=_env_flag(env.get("SUITE_S3_BOOTSTRAP_BUCKETS", "0")),
    )


def build_configured_knowledge_base_article_service(
    *,
    default_service: KnowledgeBaseArticleService,
    audit_logger: InMemoryAuditLogger,
    environ: Mapping[str, str] | None = None,
    object_store_client: S3CompatibleObjectStoreClient | None = None,
) -> KnowledgeBaseArticleService:
    backend = knowledge_base_runtime_backend_from_env(environ)
    if backend == KnowledgeBaseRuntimeBackend.DEMO:
        return default_service

    config = build_postgres_s3_knowledge_base_runtime_config_from_env(environ)
    wiring = build_postgres_s3_knowledge_base_runtime(
        config=config,
        object_store_client=object_store_client,
    )
    return KnowledgeBaseArticleService(
        repository=wiring.article_repository,
        source_repository=wiring.source_repository,
        audit_logger=audit_logger,
        write_approval_ledger=build_default_knowledge_base_write_approval_ledger(),
        source_object_write_receipt_store=wiring.source_object_write_receipt_store,
        write_unit_of_work=wiring.write_unit_of_work,
    )


def build_postgres_s3_knowledge_base_runtime_gate_evidence(
    *,
    config: PostgresS3KnowledgeBaseRuntimeConfig,
    object_store_client: S3CompatibleObjectStoreClient | None = None,
    bootstrap_bucket_profiles: bool | None = None,
) -> KnowledgeBasePostgresS3RuntimeGateEvidence:
    storage_policy = load_storage_adapter_policy(config.storage_policy_path)
    retention_policy = load_retention_manifest_policy(config.retention_policy_path)
    client = object_store_client
    if client is None:
        config.require_sdk_credentials()
        client = build_boto3_s3_compatible_client(
            endpoint_url=config.s3_endpoint_url,
            access_key_id=config.s3_access_key_id or "",
            secret_access_key=config.s3_secret_access_key or "",
            region_name=config.s3_region_name,
            storage_provider=config.s3_storage_provider,
        )
    should_bootstrap = (
        config.bootstrap_bucket_profiles if bootstrap_bucket_profiles is None else bootstrap_bucket_profiles
    )
    if should_bootstrap:
        ensure_bucket_profiles = getattr(client, "ensure_bucket_profiles", None)
        if not callable(ensure_bucket_profiles):
            raise ValueError("configured S3-compatible client cannot bootstrap bucket profiles")
        ensure_bucket_profiles(storage_policy=storage_policy)

    content_store = S3CompatibleSourceObjectContentStore(client=client, storage_policy=storage_policy)
    source_repository = PgSourceObjectRepository(
        database_dsn=config.database_dsn,
        content_store=content_store,
        retention_policy=retention_policy,
        storage_policy=storage_policy,
    )
    provider_profile_evidence = build_s3_compatible_provider_profile_evidence(
        client=client,
        storage_policy=storage_policy,
        provider_profile_id=config.provider_profile_id,
    )
    source_content_recovery_evidence = source_repository.build_content_recovery_evidence(
        tenant_id=config.tenant_id,
        restore_drill_report_hash=config.restore_drill_report_hash,
    )
    production_gate_evidence = build_knowledge_base_production_write_deployment_gate(
        tenant_id=config.tenant_id,
        source_content_recovery_evidence=source_content_recovery_evidence,
        provider_profile_evidence=provider_profile_evidence,
        restore_drill_report_hash=config.restore_drill_report_hash,
    )
    return KnowledgeBasePostgresS3RuntimeGateEvidence(
        config=config,
        storage_policy=storage_policy,
        retention_policy=retention_policy,
        content_store=content_store,
        source_repository=source_repository,
        provider_profile_evidence=provider_profile_evidence,
        source_content_recovery_evidence=source_content_recovery_evidence,
        production_write_deployment_gate_evidence=production_gate_evidence,
    )


def build_postgres_s3_knowledge_base_runtime(
    *,
    config: PostgresS3KnowledgeBaseRuntimeConfig,
    object_store_client: S3CompatibleObjectStoreClient | None = None,
) -> KnowledgeBasePostgresS3RuntimeWiring:
    gate_evidence = build_postgres_s3_knowledge_base_runtime_gate_evidence(
        config=config,
        object_store_client=object_store_client,
    )
    production_gate_evidence = gate_evidence.production_write_deployment_gate_evidence
    if not production_gate_evidence.api_wiring_allowed:
        reasons = ", ".join(production_gate_evidence.blocking_reasons) or production_gate_evidence.gate_status
        raise ValueError(f"knowledge base production runtime gate is blocked: {reasons}")

    article_repository = PgKnowledgeBaseArticleRepository(database_dsn=config.database_dsn)
    receipt_store = PgSourceObjectWriteReceiptStore(database_dsn=config.database_dsn)
    write_unit_of_work = PostgresKnowledgeBaseWriteUnitOfWork(
        database_dsn=config.database_dsn,
        article_repository=article_repository,
        source_repository=gate_evidence.source_repository,
        source_object_write_receipt_store=receipt_store,
        source_content_recovery_evidence=gate_evidence.source_content_recovery_evidence,
        production_write_deployment_gate_evidence=production_gate_evidence,
        require_source_content_recovery_gate=True,
    )
    return KnowledgeBasePostgresS3RuntimeWiring(
        config=config,
        storage_policy=gate_evidence.storage_policy,
        retention_policy=gate_evidence.retention_policy,
        content_store=gate_evidence.content_store,
        source_repository=gate_evidence.source_repository,
        article_repository=article_repository,
        source_object_write_receipt_store=receipt_store,
        provider_profile_evidence=gate_evidence.provider_profile_evidence,
        source_content_recovery_evidence=gate_evidence.source_content_recovery_evidence,
        production_write_deployment_gate_evidence=production_gate_evidence,
        write_unit_of_work=write_unit_of_work,
    )


def _required_env(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name)
    if value is None or not value.strip():
        raise ValueError(f"{name} is required")
    return value


def _first_required_env(environ: Mapping[str, str], *names: str) -> str:
    for name in names:
        value = environ.get(name)
        if value is not None and value.strip():
            return value
    raise ValueError(f"One of {', '.join(names)} is required")


def _optional_env(environ: Mapping[str, str], name: str) -> str | None:
    value = environ.get(name)
    if value is None or not value.strip():
        return None
    return value


def _env_flag(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    raise ValueError(f"Unsupported boolean environment flag: {value}")


def _runtime_reconciliation_blocking_reasons(
    *,
    activation: KnowledgeBaseRuntimeActivation,
    observed_source_content_recovery_evidence: SourceObjectContentRecoveryEvidence,
    observed_provider_profile_evidence: S3CompatibleProviderProfileEvidence,
    observed_production_write_deployment_gate_evidence: KnowledgeBaseProductionWriteDeploymentGateEvidence,
) -> tuple[str, ...]:
    blocking_reasons: list[str] = []
    if observed_source_content_recovery_evidence.tenant_id != activation.tenant_id:
        blocking_reasons.append("source_content_recovery_tenant_mismatch")
    if observed_production_write_deployment_gate_evidence.tenant_id != activation.tenant_id:
        blocking_reasons.append("production_gate_tenant_mismatch")
    if observed_source_content_recovery_evidence.restore_drill_report_hash != activation.restore_drill_report_hash:
        blocking_reasons.append("source_content_recovery_restore_drill_mismatch")
    if observed_production_write_deployment_gate_evidence.restore_drill_report_hash != (
        activation.restore_drill_report_hash
    ):
        blocking_reasons.append("production_gate_restore_drill_mismatch")
    if (
        build_source_object_content_recovery_evidence_hash(observed_source_content_recovery_evidence)
        != observed_source_content_recovery_evidence.evidence_hash
    ):
        blocking_reasons.append("source_content_recovery_evidence_hash_invalid")
    if (
        build_s3_compatible_provider_profile_evidence_hash(observed_provider_profile_evidence)
        != observed_provider_profile_evidence.evidence_hash
    ):
        blocking_reasons.append("provider_profile_evidence_hash_invalid")
    if (
        build_production_write_deployment_gate_hash(observed_production_write_deployment_gate_evidence)
        != observed_production_write_deployment_gate_evidence.evidence_hash
    ):
        blocking_reasons.append("production_gate_evidence_hash_invalid")
    if not observed_source_content_recovery_evidence.api_wiring_allowed:
        blocking_reasons.append("source_content_recovery_not_ready")
    if not observed_provider_profile_evidence.provider_profile_ready:
        blocking_reasons.append("provider_profile_not_ready")
    if not observed_production_write_deployment_gate_evidence.api_wiring_allowed:
        blocking_reasons.append("production_gate_not_ready")
    if _source_recovery_state_hash(activation.source_content_recovery_evidence) != _source_recovery_state_hash(
        observed_source_content_recovery_evidence
    ):
        blocking_reasons.append("source_content_recovery_state_drift")
    if _provider_profile_state_hash(activation.provider_profile_evidence) != _provider_profile_state_hash(
        observed_provider_profile_evidence
    ):
        blocking_reasons.append("provider_profile_state_drift")
    if _production_gate_state_hash(activation.production_write_deployment_gate_evidence) != _production_gate_state_hash(
        observed_production_write_deployment_gate_evidence
    ):
        blocking_reasons.append("production_gate_state_drift")
    return tuple(sorted(set(blocking_reasons)))


def _source_recovery_state_hash(evidence: SourceObjectContentRecoveryEvidence) -> str:
    return stable_hash(canonical_json(evidence.model_dump(mode="json", exclude={"checked_at_utc", "evidence_hash"})))


def _provider_profile_state_hash(evidence: S3CompatibleProviderProfileEvidence) -> str:
    return stable_hash(canonical_json(evidence.model_dump(mode="json", exclude={"checked_at_utc", "evidence_hash"})))


def _production_gate_state_hash(evidence: KnowledgeBaseProductionWriteDeploymentGateEvidence) -> str:
    return stable_hash(
        canonical_json(
            evidence.model_dump(
                mode="json",
                exclude={
                    "source_content_recovery_evidence_hash",
                    "provider_profile_evidence_hash",
                    "evidence_hash",
                },
            )
        )
    )


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _utc_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    return str(value)
