import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import UserContext
from suite.persistence.migrator import apply_migrations
from suite.platform.knowledge_base import (
    KNOWLEDGE_BASE_MODULE_ID,
    InMemoryKnowledgeBaseArticleRepository,
    KnowledgeBaseArticleService,
    PostgresKnowledgeBaseWriteUnitOfWork,
    demo_knowledge_base_source_object_repository,
)
from suite.platform.knowledge_base_runtime import (
    InMemoryKnowledgeBaseRuntimeActivationStore,
    InMemoryKnowledgeBaseRuntimeReconciliationStore,
    KnowledgeBaseArticleServiceResolver,
    KnowledgeBaseRuntimeActivation,
    KnowledgeBaseRuntimeActivationCommand,
    KnowledgeBaseRuntimeBackend,
    KnowledgeBaseRuntimeReconciliationAction,
    KnowledgeBaseRuntimeReconciliationStatus,
    KnowledgeBaseRuntimeReconciliationWorker,
    PgKnowledgeBaseRuntimeActivationStore,
    PgKnowledgeBaseRuntimeReconciliationStore,
    PostgresS3KnowledgeBaseRuntimeConfig,
    build_configured_knowledge_base_article_service,
    build_knowledge_base_runtime_activation,
    build_knowledge_base_runtime_activation_hash,
    build_knowledge_base_runtime_reconciliation_evidence_hash,
    build_postgres_s3_knowledge_base_runtime,
    build_postgres_s3_knowledge_base_runtime_config_from_env,
    knowledge_base_runtime_activation_view,
    knowledge_base_runtime_backend_from_env,
    knowledge_base_runtime_reconciliation_view,
)
from suite.platform.knowledge_base_runtime_reconciliation_service import (
    KnowledgeBaseRuntimeReconciliationAlertSeverity,
    KnowledgeBaseRuntimeReconciliationRetryContract,
    KnowledgeBaseRuntimeReconciliationRunConfig,
    KnowledgeBaseRuntimeReconciliationRunner,
    KnowledgeBaseRuntimeReconciliationTenantRunStatus,
    KnowledgeBaseRuntimeReconciliationTenantSelector,
    build_reconciliation_run_report_hash,
    exit_code_for_report,
)
from suite.platform.modules import (
    InMemoryModuleRegistry,
    ModuleCatalogEntry,
    ModuleKind,
    ModuleStatus,
    ModuleWorkerGate,
    TenantModuleState,
)
from suite.storage.adapter_policy import ObjectLockMode, StorageAdapterPolicy, load_storage_adapter_policy
from suite.storage.s3_compatible_content_store import (
    S3CompatibleBucketCapabilities,
    S3CompatibleObjectWriteResult,
    S3CompatibleStoredObjectVersion,
)
from suite.storage.source_objects import build_default_source_object_write_receipt_store

REPO_ROOT = Path(__file__).resolve().parents[1]
RETENTION_POLICY_PATH = REPO_ROOT / "docs" / "retention_manifest_policy.json"
STORAGE_POLICY_PATH = REPO_ROOT / "docs" / "storage_adapter_policy.json"


@dataclass(frozen=True)
class LiveDatabase:
    migration_dsn: str
    app_dsn: str


class EmptyS3CompatibleClient:
    def __init__(self, *, storage_policy: StorageAdapterPolicy, break_object_lock: bool = False) -> None:
        self.capabilities: dict[str, S3CompatibleBucketCapabilities] = {}
        for bucket_profile in storage_policy.bucket_profiles:
            object_lock_enabled = bucket_profile.object_lock_required and not break_object_lock
            legal_hold_supported = bucket_profile.legal_hold_supported and not break_object_lock
            self.capabilities[bucket_profile.bucket_id] = S3CompatibleBucketCapabilities(
                bucket_id=bucket_profile.bucket_id,
                storage_provider="minio",
                versioning_enabled=True,
                object_lock_enabled=object_lock_enabled,
                legal_hold_supported=legal_hold_supported,
            )

    def bucket_capabilities(self, *, bucket_id: str) -> S3CompatibleBucketCapabilities:
        return self.capabilities[bucket_id]

    def put_object(
        self,
        *,
        bucket_id: str,
        object_key: str,
        body: bytes,
        metadata: dict[str, str],
        object_lock_mode: ObjectLockMode,
        legal_hold: bool,
    ) -> S3CompatibleObjectWriteResult:
        return S3CompatibleObjectWriteResult(
            bucket_id=bucket_id,
            object_key=object_key,
            object_version_id="unused-test-version",
            storage_provider="minio",
            stored_at_utc="2026-06-16T08:00:00Z",
        )

    def get_object(self, *, bucket_id: str, object_key: str, object_version_id: str) -> bytes:
        raise KeyError("empty runtime fake does not store object bodies")

    def list_object_versions(
        self,
        *,
        bucket_id: str,
        prefix: str,
    ) -> tuple[S3CompatibleStoredObjectVersion, ...]:
        return ()


def env_or_skip(name: str) -> str:
    value = os.environ.get(name)
    if value is None:
        pytest.skip(f"{name} is not configured")
    return value


def knowledge_base_catalog_entry() -> ModuleCatalogEntry:
    return ModuleCatalogEntry(
        module_id=KNOWLEDGE_BASE_MODULE_ID,
        display_name="Knowledge Base",
        module_version="0.1.0",
        module_kind=ModuleKind.BUSINESS_DOMAIN,
        status=ModuleStatus.INSTALLED,
        description="Governed knowledge base module.",
        manifest_hash="sha256:knowledge-base-module-manifest",
    )


def knowledge_base_tenant_module(tenant_id: str, status: ModuleStatus) -> TenantModuleState:
    timestamp = datetime(2026, 6, 16, 8, tzinfo=UTC)
    return TenantModuleState(
        tenant_id=tenant_id,
        module_id=KNOWLEDGE_BASE_MODULE_ID,
        status=status,
        enabled_features={},
        policy_snapshot_hash="sha256:test-module-policy",
        changed_by="system",
        audit_chain_ref=f"audit:{tenant_id}:module-state",
        disabled_at_utc=timestamp if status == ModuleStatus.DISABLED else None,
        enabled_at_utc=timestamp if status == ModuleStatus.ENABLED else None,
    )


def runtime_activation_for_tenant(
    *,
    live_database: LiveDatabase,
    storage_policy: StorageAdapterPolicy,
    tenant_id: str,
    provider_profile_id: str,
    restore_hash_digit: str,
) -> KnowledgeBaseRuntimeActivation:
    restore_drill_report_hash = f"sha256:{restore_hash_digit * 64}"
    wiring = build_postgres_s3_knowledge_base_runtime(
        config=PostgresS3KnowledgeBaseRuntimeConfig(
            tenant_id=tenant_id,
            database_dsn=live_database.app_dsn,
            restore_drill_report_hash=restore_drill_report_hash,
            storage_policy_path=STORAGE_POLICY_PATH,
            retention_policy_path=RETENTION_POLICY_PATH,
            provider_profile_id=provider_profile_id,
        ),
        object_store_client=EmptyS3CompatibleClient(storage_policy=storage_policy),
    )
    return build_knowledge_base_runtime_activation(
        tenant_id=tenant_id,
        activated_by="tenant-admin-runtime",
        provider_profile_id=provider_profile_id,
        restore_drill_report_hash=restore_drill_report_hash,
        source_content_recovery_evidence=wiring.source_content_recovery_evidence,
        provider_profile_evidence=wiring.provider_profile_evidence,
        production_write_deployment_gate_evidence=wiring.production_write_deployment_gate_evidence,
        approval_reference=f"approval:{tenant_id}:kb-runtime",
        audit_chain_ref=f"audit:{tenant_id}:kb-runtime",
        activated_at_utc="2026-06-16T08:00:00Z",
    )


@pytest.fixture(scope="module")
def live_database() -> LiveDatabase:
    migration_dsn = env_or_skip("SUITE_MIGRATION_DATABASE_DSN")
    app_dsn = env_or_skip("SUITE_DATABASE_DSN")
    apply_migrations(migration_dsn)
    return LiveDatabase(migration_dsn=migration_dsn, app_dsn=app_dsn)


def test_knowledge_base_runtime_backend_defaults_to_demo_and_can_auto_select_s3() -> None:
    assert knowledge_base_runtime_backend_from_env({}) == KnowledgeBaseRuntimeBackend.DEMO
    assert (
        knowledge_base_runtime_backend_from_env(
            {
                "SUITE_KB_RUNTIME_BACKEND": "auto",
                "SUITE_SOURCE_OBJECT_CONTENT_STORE_BACKEND": "s3_compatible",
            }
        )
        == KnowledgeBaseRuntimeBackend.POSTGRES_S3
    )


def test_postgres_s3_runtime_config_requires_explicit_tenant_and_restore_drill_hash() -> None:
    with pytest.raises(ValueError, match="SUITE_KB_RUNTIME_TENANT_ID"):
        build_postgres_s3_knowledge_base_runtime_config_from_env({"SUITE_DATABASE_DSN": "postgresql://example"})

    config = build_postgres_s3_knowledge_base_runtime_config_from_env(
        {
            "SUITE_KB_RUNTIME_TENANT_ID": "tenant-runtime",
            "SUITE_DATABASE_DSN": "postgresql://example",
            "SUITE_KB_RESTORE_DRILL_REPORT_HASH": "sha256:" + "b" * 64,
            "SUITE_S3_PROVIDER_PROFILE_ID": "minio-runtime-test",
        }
    )

    assert config.tenant_id == "tenant-runtime"
    assert config.provider_profile_id == "minio-runtime-test"
    assert config.bootstrap_bucket_profiles is False


def test_configured_knowledge_base_service_keeps_default_demo_backend() -> None:
    audit_logger = InMemoryAuditLogger()
    default_service = KnowledgeBaseArticleService(
        repository=InMemoryKnowledgeBaseArticleRepository.demo(),
        source_repository=demo_knowledge_base_source_object_repository(),
        audit_logger=audit_logger,
        source_object_write_receipt_store=build_default_source_object_write_receipt_store(),
    )

    configured_service = build_configured_knowledge_base_article_service(
        default_service=default_service,
        audit_logger=audit_logger,
        environ={},
    )

    assert configured_service is default_service


def test_postgres_s3_runtime_wires_provider_recovery_and_deployment_gate(
    live_database: LiveDatabase,
) -> None:
    suffix = uuid4().hex
    tenant_id = f"tenant-runtime-{suffix}"
    storage_policy = load_storage_adapter_policy(STORAGE_POLICY_PATH)
    config = PostgresS3KnowledgeBaseRuntimeConfig(
        tenant_id=tenant_id,
        database_dsn=live_database.app_dsn,
        restore_drill_report_hash="sha256:" + "c" * 64,
        storage_policy_path=STORAGE_POLICY_PATH,
        retention_policy_path=RETENTION_POLICY_PATH,
        provider_profile_id=f"minio-runtime-{suffix}",
    )

    wiring = build_postgres_s3_knowledge_base_runtime(
        config=config,
        object_store_client=EmptyS3CompatibleClient(storage_policy=storage_policy),
    )

    assert wiring.provider_profile_evidence.provider_profile_ready is True
    assert wiring.source_content_recovery_evidence.api_wiring_allowed is True
    assert wiring.production_write_deployment_gate_evidence.api_wiring_allowed is True
    assert wiring.production_write_deployment_gate_evidence.tenant_id == tenant_id
    assert wiring.write_unit_of_work.source_content_recovery_evidence is not None
    assert wiring.write_unit_of_work.production_write_deployment_gate_evidence is not None


def test_configured_service_activates_postgres_s3_runtime_with_explicit_env(
    live_database: LiveDatabase,
) -> None:
    suffix = uuid4().hex
    tenant_id = f"tenant-runtime-service-{suffix}"
    storage_policy = load_storage_adapter_policy(STORAGE_POLICY_PATH)
    audit_logger = InMemoryAuditLogger()
    default_service = KnowledgeBaseArticleService(
        repository=InMemoryKnowledgeBaseArticleRepository.demo(),
        source_repository=demo_knowledge_base_source_object_repository(),
        audit_logger=audit_logger,
        source_object_write_receipt_store=build_default_source_object_write_receipt_store(),
    )

    configured_service = build_configured_knowledge_base_article_service(
        default_service=default_service,
        audit_logger=audit_logger,
        environ={
            "SUITE_KB_RUNTIME_BACKEND": "postgres_s3",
            "SUITE_KB_RUNTIME_TENANT_ID": tenant_id,
            "SUITE_DATABASE_DSN": live_database.app_dsn,
            "SUITE_KB_RESTORE_DRILL_REPORT_HASH": "sha256:" + "d" * 64,
            "SUITE_STORAGE_POLICY_PATH": str(STORAGE_POLICY_PATH),
            "SUITE_RETENTION_POLICY_PATH": str(RETENTION_POLICY_PATH),
            "SUITE_S3_PROVIDER_PROFILE_ID": f"minio-runtime-service-{suffix}",
        },
        object_store_client=EmptyS3CompatibleClient(storage_policy=storage_policy),
    )

    assert configured_service is not default_service
    assert isinstance(configured_service.write_unit_of_work, PostgresKnowledgeBaseWriteUnitOfWork)
    assert configured_service.write_unit_of_work.source_content_recovery_evidence is not None
    assert configured_service.write_unit_of_work.production_write_deployment_gate_evidence is not None


def test_postgres_s3_runtime_blocks_when_provider_profile_is_not_ready(
    live_database: LiveDatabase,
) -> None:
    suffix = uuid4().hex
    storage_policy = load_storage_adapter_policy(STORAGE_POLICY_PATH)
    config = PostgresS3KnowledgeBaseRuntimeConfig(
        tenant_id=f"tenant-runtime-blocked-{suffix}",
        database_dsn=live_database.app_dsn,
        restore_drill_report_hash="sha256:" + "e" * 64,
        storage_policy_path=STORAGE_POLICY_PATH,
        retention_policy_path=RETENTION_POLICY_PATH,
        provider_profile_id=f"minio-runtime-blocked-{suffix}",
    )

    with pytest.raises(ValueError, match="provider_profile"):
        build_postgres_s3_knowledge_base_runtime(
            config=config,
            object_store_client=EmptyS3CompatibleClient(
                storage_policy=storage_policy,
                break_object_lock=True,
            ),
        )


def test_runtime_activation_hash_and_view_bind_gate_evidence(
    live_database: LiveDatabase,
) -> None:
    suffix = uuid4().hex
    tenant_id = f"tenant-runtime-activation-{suffix}"
    storage_policy = load_storage_adapter_policy(STORAGE_POLICY_PATH)
    wiring = build_postgres_s3_knowledge_base_runtime(
        config=PostgresS3KnowledgeBaseRuntimeConfig(
            tenant_id=tenant_id,
            database_dsn=live_database.app_dsn,
            restore_drill_report_hash="sha256:" + "1" * 64,
            storage_policy_path=STORAGE_POLICY_PATH,
            retention_policy_path=RETENTION_POLICY_PATH,
            provider_profile_id=f"minio-runtime-activation-{suffix}",
        ),
        object_store_client=EmptyS3CompatibleClient(storage_policy=storage_policy),
    )

    activation = build_knowledge_base_runtime_activation(
        tenant_id=tenant_id,
        activated_by="tenant-admin-runtime",
        provider_profile_id=f"minio-runtime-activation-{suffix}",
        restore_drill_report_hash="sha256:" + "1" * 64,
        source_content_recovery_evidence=wiring.source_content_recovery_evidence,
        provider_profile_evidence=wiring.provider_profile_evidence,
        production_write_deployment_gate_evidence=wiring.production_write_deployment_gate_evidence,
        approval_reference="approval:kb-runtime-activation",
        audit_chain_ref="audit:kb-runtime-activation",
        activated_at_utc="2026-06-16T08:00:00Z",
    )
    view = knowledge_base_runtime_activation_view(activation)

    assert activation.activation_evidence_hash == build_knowledge_base_runtime_activation_hash(activation)
    assert view.source_content_recovery_evidence_hash == wiring.source_content_recovery_evidence.evidence_hash
    assert view.provider_profile_evidence_hash == wiring.provider_profile_evidence.evidence_hash
    assert (
        view.production_write_deployment_gate_evidence_hash
        == wiring.production_write_deployment_gate_evidence.evidence_hash
    )
    view_payload = view.model_dump()
    assert "source_content_recovery_evidence" not in view_payload
    assert "source_content_recovery_evidence_hash" in view_payload


def test_tenant_runtime_resolver_uses_activation_only_for_matching_tenant(
    live_database: LiveDatabase,
) -> None:
    suffix = uuid4().hex
    tenant_id = f"tenant-runtime-resolver-{suffix}"
    storage_policy = load_storage_adapter_policy(STORAGE_POLICY_PATH)
    audit_logger = InMemoryAuditLogger()
    default_service = KnowledgeBaseArticleService(
        repository=InMemoryKnowledgeBaseArticleRepository.demo(),
        source_repository=demo_knowledge_base_source_object_repository(),
        audit_logger=audit_logger,
        source_object_write_receipt_store=build_default_source_object_write_receipt_store(),
    )
    resolver = KnowledgeBaseArticleServiceResolver(
        default_service=default_service,
        audit_logger=audit_logger,
        activation_store=InMemoryKnowledgeBaseRuntimeActivationStore(),
        environ={
            "SUITE_DATABASE_DSN": live_database.app_dsn,
            "SUITE_STORAGE_POLICY_PATH": str(STORAGE_POLICY_PATH),
            "SUITE_RETENTION_POLICY_PATH": str(RETENTION_POLICY_PATH),
        },
        object_store_client=EmptyS3CompatibleClient(storage_policy=storage_policy),
    )

    assert resolver.service_for_tenant(tenant_id=f"tenant-other-{suffix}") is default_service
    activation = resolver.activate_postgres_s3_runtime(
        command=KnowledgeBaseRuntimeActivationCommand(
            provider_profile_id=f"minio-runtime-resolver-{suffix}",
            restore_drill_report_hash="sha256:" + "2" * 64,
            approval_reference="approval:kb-runtime-resolver",
            reason="activate tenant-scoped runtime resolver",
            human_confirmation=True,
        ),
        user_context=UserContext(
            user_id="tenant-admin-runtime",
            tenant_id=tenant_id,
            role_ids={"tenant-admin"},
            readable_object_ids=set(),
        ),
        audit_chain_ref="audit:kb-runtime-resolver",
    )
    service = resolver.service_for_tenant(tenant_id=tenant_id)

    assert resolver.service_for_tenant(tenant_id=f"tenant-other-{suffix}") is default_service
    assert activation.tenant_id == tenant_id
    assert isinstance(service.write_unit_of_work, PostgresKnowledgeBaseWriteUnitOfWork)
    assert service.write_unit_of_work.production_write_deployment_gate_evidence is not None
    assert service.write_unit_of_work.production_write_deployment_gate_evidence.tenant_id == tenant_id


def test_pg_runtime_activation_store_persists_active_tenant_scope(
    live_database: LiveDatabase,
) -> None:
    suffix = uuid4().hex
    tenant_id = f"tenant-runtime-pg-store-{suffix}"
    storage_policy = load_storage_adapter_policy(STORAGE_POLICY_PATH)
    store = PgKnowledgeBaseRuntimeActivationStore(database_dsn=live_database.app_dsn)

    def activation_for_hash(hash_digit: str, provider_profile_id: str) -> KnowledgeBaseRuntimeActivation:
        wiring = build_postgres_s3_knowledge_base_runtime(
            config=PostgresS3KnowledgeBaseRuntimeConfig(
                tenant_id=tenant_id,
                database_dsn=live_database.app_dsn,
                restore_drill_report_hash=f"sha256:{hash_digit * 64}",
                storage_policy_path=STORAGE_POLICY_PATH,
                retention_policy_path=RETENTION_POLICY_PATH,
                provider_profile_id=provider_profile_id,
            ),
            object_store_client=EmptyS3CompatibleClient(storage_policy=storage_policy),
        )
        return build_knowledge_base_runtime_activation(
            tenant_id=tenant_id,
            activated_by="tenant-admin-runtime",
            provider_profile_id=provider_profile_id,
            restore_drill_report_hash=f"sha256:{hash_digit * 64}",
            source_content_recovery_evidence=wiring.source_content_recovery_evidence,
            provider_profile_evidence=wiring.provider_profile_evidence,
            production_write_deployment_gate_evidence=wiring.production_write_deployment_gate_evidence,
            approval_reference=f"approval:kb-runtime-pg-store-{hash_digit}",
            audit_chain_ref=f"audit:kb-runtime-pg-store-{hash_digit}",
            activated_at_utc=f"2026-06-16T08:0{hash_digit}:00Z",
        )

    first = store.activate(activation_for_hash("3", f"minio-runtime-pg-store-first-{suffix}"))
    second = store.activate(activation_for_hash("4", f"minio-runtime-pg-store-second-{suffix}"))
    active = store.get_active(tenant_id=tenant_id)

    assert active is not None
    assert active.activation_evidence_hash == second.activation_evidence_hash
    assert store.get_active(tenant_id=f"tenant-other-{suffix}") is None
    with psycopg.connect(live_database.app_dsn) as connection:
        connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))
        rows = connection.execute(
            """
            SELECT activation_evidence_hash, active
            FROM collabio.knowledge_base_runtime_activations
            WHERE tenant_id = %s
            ORDER BY activated_at_utc
            """,
            (tenant_id,),
        ).fetchall()

    assert [row[0] for row in rows] == [first.activation_evidence_hash, second.activation_evidence_hash]
    assert [row[1] for row in rows] == [False, True]


def test_runtime_reconciliation_refresh_keeps_clean_activation_active(
    live_database: LiveDatabase,
) -> None:
    suffix = uuid4().hex
    tenant_id = f"tenant-runtime-clean-reconcile-{suffix}"
    storage_policy = load_storage_adapter_policy(STORAGE_POLICY_PATH)
    activation_store = InMemoryKnowledgeBaseRuntimeActivationStore()
    reconciliation_store = InMemoryKnowledgeBaseRuntimeReconciliationStore()
    resolver = KnowledgeBaseArticleServiceResolver(
        default_service=KnowledgeBaseArticleService(
            repository=InMemoryKnowledgeBaseArticleRepository.demo(),
            source_repository=demo_knowledge_base_source_object_repository(),
            audit_logger=InMemoryAuditLogger(),
            source_object_write_receipt_store=build_default_source_object_write_receipt_store(),
        ),
        audit_logger=InMemoryAuditLogger(),
        activation_store=activation_store,
        environ={
            "SUITE_DATABASE_DSN": live_database.app_dsn,
            "SUITE_STORAGE_POLICY_PATH": str(STORAGE_POLICY_PATH),
            "SUITE_RETENTION_POLICY_PATH": str(RETENTION_POLICY_PATH),
        },
        object_store_client=EmptyS3CompatibleClient(storage_policy=storage_policy),
    )
    activation = resolver.activate_postgres_s3_runtime(
        command=KnowledgeBaseRuntimeActivationCommand(
            provider_profile_id=f"minio-runtime-clean-reconcile-{suffix}",
            restore_drill_report_hash="sha256:" + "5" * 64,
            approval_reference="approval:kb-runtime-clean-reconcile",
            reason="activate clean runtime reconciliation path",
            human_confirmation=True,
        ),
        user_context=UserContext(
            user_id="tenant-admin-runtime",
            tenant_id=tenant_id,
            role_ids={"tenant-admin"},
            readable_object_ids=set(),
        ),
        audit_chain_ref="audit:kb-runtime-clean-reconcile",
    )
    worker = KnowledgeBaseRuntimeReconciliationWorker(
        activation_store=activation_store,
        reconciliation_store=reconciliation_store,
        environ={
            "SUITE_DATABASE_DSN": live_database.app_dsn,
            "SUITE_STORAGE_POLICY_PATH": str(STORAGE_POLICY_PATH),
            "SUITE_RETENTION_POLICY_PATH": str(RETENTION_POLICY_PATH),
        },
        object_store_client=EmptyS3CompatibleClient(storage_policy=storage_policy),
    )

    evidence = worker.reconcile_active_tenant(
        tenant_id=tenant_id,
        checked_by="runtime-reconciler",
        audit_chain_ref="audit:kb-runtime-clean-reconcile-check",
    )
    assert evidence is not None
    view = knowledge_base_runtime_reconciliation_view(evidence)

    assert evidence.reconciliation_status == KnowledgeBaseRuntimeReconciliationStatus.READY
    assert evidence.recommended_action == KnowledgeBaseRuntimeReconciliationAction.KEEP_ACTIVE
    assert evidence.runtime_deactivated is False
    assert evidence.evidence_hash == build_knowledge_base_runtime_reconciliation_evidence_hash(evidence)
    assert activation_store.get_active(tenant_id=tenant_id) is not None
    assert reconciliation_store.latest_for_activation(tenant_id=tenant_id, activation_id=activation.activation_id)
    assert "observed_source_content_recovery_evidence" not in view.model_dump()
    assert view.observed_source_content_recovery_evidence_hash == (
        evidence.observed_source_content_recovery_evidence.evidence_hash
    )


def test_runtime_reconciliation_deactivates_activation_on_provider_drift(
    live_database: LiveDatabase,
) -> None:
    suffix = uuid4().hex
    tenant_id = f"tenant-runtime-drift-reconcile-{suffix}"
    storage_policy = load_storage_adapter_policy(STORAGE_POLICY_PATH)
    activation_store = InMemoryKnowledgeBaseRuntimeActivationStore()
    reconciliation_store = InMemoryKnowledgeBaseRuntimeReconciliationStore()
    default_service = KnowledgeBaseArticleService(
        repository=InMemoryKnowledgeBaseArticleRepository.demo(),
        source_repository=demo_knowledge_base_source_object_repository(),
        audit_logger=InMemoryAuditLogger(),
        source_object_write_receipt_store=build_default_source_object_write_receipt_store(),
    )
    resolver = KnowledgeBaseArticleServiceResolver(
        default_service=default_service,
        audit_logger=InMemoryAuditLogger(),
        activation_store=activation_store,
        environ={
            "SUITE_DATABASE_DSN": live_database.app_dsn,
            "SUITE_STORAGE_POLICY_PATH": str(STORAGE_POLICY_PATH),
            "SUITE_RETENTION_POLICY_PATH": str(RETENTION_POLICY_PATH),
        },
        object_store_client=EmptyS3CompatibleClient(storage_policy=storage_policy),
    )
    activation = resolver.activate_postgres_s3_runtime(
        command=KnowledgeBaseRuntimeActivationCommand(
            provider_profile_id=f"minio-runtime-drift-reconcile-{suffix}",
            restore_drill_report_hash="sha256:" + "6" * 64,
            approval_reference="approval:kb-runtime-drift-reconcile",
            reason="activate runtime before simulated provider drift",
            human_confirmation=True,
        ),
        user_context=UserContext(
            user_id="tenant-admin-runtime",
            tenant_id=tenant_id,
            role_ids={"tenant-admin"},
            readable_object_ids=set(),
        ),
        audit_chain_ref="audit:kb-runtime-drift-reconcile",
    )
    worker = KnowledgeBaseRuntimeReconciliationWorker(
        activation_store=activation_store,
        reconciliation_store=reconciliation_store,
        environ={
            "SUITE_DATABASE_DSN": live_database.app_dsn,
            "SUITE_STORAGE_POLICY_PATH": str(STORAGE_POLICY_PATH),
            "SUITE_RETENTION_POLICY_PATH": str(RETENTION_POLICY_PATH),
        },
        object_store_client=EmptyS3CompatibleClient(storage_policy=storage_policy, break_object_lock=True),
    )

    evidence = worker.reconcile_active_tenant(
        tenant_id=tenant_id,
        checked_by="runtime-reconciler",
        audit_chain_ref="audit:kb-runtime-drift-reconcile-check",
    )

    assert evidence is not None
    assert evidence.reconciliation_status == KnowledgeBaseRuntimeReconciliationStatus.DRIFT_BLOCKED
    assert evidence.recommended_action == KnowledgeBaseRuntimeReconciliationAction.DEACTIVATE_RUNTIME
    assert evidence.runtime_deactivated is True
    assert "provider_profile_not_ready" in evidence.blocking_reasons
    assert activation_store.get_active(tenant_id=tenant_id) is None
    assert resolver.service_for_tenant(tenant_id=tenant_id) is default_service
    assert reconciliation_store.latest_for_activation(tenant_id=tenant_id, activation_id=activation.activation_id)


def test_runtime_reconciliation_runner_selects_tenants_from_module_gate_and_activations(
    live_database: LiveDatabase,
) -> None:
    suffix = uuid4().hex
    storage_policy = load_storage_adapter_policy(STORAGE_POLICY_PATH)
    selected_tenant = f"tenant-runtime-runner-selected-{suffix}"
    blocked_tenant = f"tenant-runtime-runner-blocked-{suffix}"
    empty_tenant = f"tenant-runtime-runner-empty-{suffix}"
    activation_store = InMemoryKnowledgeBaseRuntimeActivationStore()
    reconciliation_store = InMemoryKnowledgeBaseRuntimeReconciliationStore()
    selected_activation = activation_store.activate(
        runtime_activation_for_tenant(
            live_database=live_database,
            storage_policy=storage_policy,
            tenant_id=selected_tenant,
            provider_profile_id=f"minio-runtime-runner-selected-{suffix}",
            restore_hash_digit="8",
        )
    )
    blocked_activation = activation_store.activate(
        runtime_activation_for_tenant(
            live_database=live_database,
            storage_policy=storage_policy,
            tenant_id=blocked_tenant,
            provider_profile_id=f"minio-runtime-runner-blocked-{suffix}",
            restore_hash_digit="9",
        )
    )
    module_registry = InMemoryModuleRegistry(
        catalog_entries=[knowledge_base_catalog_entry()],
        tenant_modules=[
            knowledge_base_tenant_module(selected_tenant, ModuleStatus.DISABLED),
            knowledge_base_tenant_module(blocked_tenant, ModuleStatus.AVAILABLE),
            knowledge_base_tenant_module(empty_tenant, ModuleStatus.DISABLED),
        ],
    )
    selector = KnowledgeBaseRuntimeReconciliationTenantSelector(
        activation_store=activation_store,
        module_worker_gate=ModuleWorkerGate(module_registry),
        module_registry=module_registry,
    )
    worker = KnowledgeBaseRuntimeReconciliationWorker(
        activation_store=activation_store,
        reconciliation_store=reconciliation_store,
        environ={
            "SUITE_DATABASE_DSN": live_database.app_dsn,
            "SUITE_STORAGE_POLICY_PATH": str(STORAGE_POLICY_PATH),
            "SUITE_RETENTION_POLICY_PATH": str(RETENTION_POLICY_PATH),
        },
        object_store_client=EmptyS3CompatibleClient(storage_policy=storage_policy),
    )
    audit_logger = InMemoryAuditLogger()
    runner = KnowledgeBaseRuntimeReconciliationRunner(
        selector=selector,
        worker=worker,
        audit_logger=audit_logger,
    )

    report = runner.run_once(
        KnowledgeBaseRuntimeReconciliationRunConfig(
            checked_by="kb-runtime-reconciler-test",
            retry_contract=KnowledgeBaseRuntimeReconciliationRetryContract(max_attempts=1),
        )
    )

    results_by_tenant = {result.tenant_id: result for result in report.tenant_results}
    assert report.attempted_count == 1
    assert report.ready_count == 1
    assert report.skipped_count == 2
    assert report.alert_required is True
    assert report.alert_severity == KnowledgeBaseRuntimeReconciliationAlertSeverity.WARNING
    assert report.evidence_hash == build_reconciliation_run_report_hash(report)
    assert report.runbook_evidence.selected_tenants == (selected_tenant,)
    assert selected_activation.restore_drill_report_hash in report.runbook_evidence.restore_drill_report_hashes
    assert blocked_activation.restore_drill_report_hash in report.runbook_evidence.restore_drill_report_hashes
    assert results_by_tenant[selected_tenant].status == KnowledgeBaseRuntimeReconciliationTenantRunStatus.READY
    assert results_by_tenant[blocked_tenant].status == (
        KnowledgeBaseRuntimeReconciliationTenantRunStatus.MODULE_GATE_BLOCKED
    )
    assert results_by_tenant[blocked_tenant].alert_severity == KnowledgeBaseRuntimeReconciliationAlertSeverity.WARNING
    assert results_by_tenant[empty_tenant].status == KnowledgeBaseRuntimeReconciliationTenantRunStatus.NO_ACTIVE_RUNTIME
    assert activation_store.get_active(tenant_id=selected_tenant) is not None
    assert reconciliation_store.latest_for_activation(
        tenant_id=selected_tenant,
        activation_id=selected_activation.activation_id,
    )
    assert len(audit_logger.events) == 1
    assert audit_logger.events[0].metadata["surface"] == "compliance_worker"
    assert audit_logger.events[0].metadata["result_contract"] == "metadata_only"
    assert exit_code_for_report(report) == 1


def test_runtime_reconciliation_runner_retries_and_reports_critical_failure(
    live_database: LiveDatabase,
) -> None:
    suffix = uuid4().hex
    tenant_id = f"tenant-runtime-runner-failure-{suffix}"
    storage_policy = load_storage_adapter_policy(STORAGE_POLICY_PATH)
    activation_store = InMemoryKnowledgeBaseRuntimeActivationStore()
    reconciliation_store = InMemoryKnowledgeBaseRuntimeReconciliationStore()
    activation = activation_store.activate(
        runtime_activation_for_tenant(
            live_database=live_database,
            storage_policy=storage_policy,
            tenant_id=tenant_id,
            provider_profile_id=f"minio-runtime-runner-failure-{suffix}",
            restore_hash_digit="a",
        )
    )
    module_registry = InMemoryModuleRegistry(
        catalog_entries=[knowledge_base_catalog_entry()],
        tenant_modules=[knowledge_base_tenant_module(tenant_id, ModuleStatus.DISABLED)],
    )
    selector = KnowledgeBaseRuntimeReconciliationTenantSelector(
        activation_store=activation_store,
        module_worker_gate=ModuleWorkerGate(module_registry),
        module_registry=module_registry,
    )
    worker = KnowledgeBaseRuntimeReconciliationWorker(
        activation_store=activation_store,
        reconciliation_store=reconciliation_store,
        environ={
            "SUITE_STORAGE_POLICY_PATH": str(STORAGE_POLICY_PATH),
            "SUITE_RETENTION_POLICY_PATH": str(RETENTION_POLICY_PATH),
        },
        object_store_client=EmptyS3CompatibleClient(storage_policy=storage_policy),
    )
    runner = KnowledgeBaseRuntimeReconciliationRunner(
        selector=selector,
        worker=worker,
        sleep_fn=lambda _: None,
    )

    report = runner.run_once(
        KnowledgeBaseRuntimeReconciliationRunConfig(
            retry_contract=KnowledgeBaseRuntimeReconciliationRetryContract(max_attempts=2),
        )
    )
    result = report.tenant_results[0]

    assert result.tenant_id == tenant_id
    assert result.activation_id == activation.activation_id
    assert result.status == KnowledgeBaseRuntimeReconciliationTenantRunStatus.FAILED
    assert result.attempts == 2
    assert result.alert_severity == KnowledgeBaseRuntimeReconciliationAlertSeverity.CRITICAL
    assert result.last_error is not None
    assert "SUITE_DATABASE_DSN" in result.last_error
    assert report.failed_count == 1
    assert report.alert_required is True
    assert exit_code_for_report(report) == 2


def test_pg_runtime_reconciliation_store_persists_evidence_and_deactivates_on_drift(
    live_database: LiveDatabase,
) -> None:
    suffix = uuid4().hex
    tenant_id = f"tenant-runtime-pg-reconcile-{suffix}"
    storage_policy = load_storage_adapter_policy(STORAGE_POLICY_PATH)
    activation_store = PgKnowledgeBaseRuntimeActivationStore(database_dsn=live_database.app_dsn)
    reconciliation_store = PgKnowledgeBaseRuntimeReconciliationStore(database_dsn=live_database.app_dsn)
    wiring = build_postgres_s3_knowledge_base_runtime(
        config=PostgresS3KnowledgeBaseRuntimeConfig(
            tenant_id=tenant_id,
            database_dsn=live_database.app_dsn,
            restore_drill_report_hash="sha256:" + "7" * 64,
            storage_policy_path=STORAGE_POLICY_PATH,
            retention_policy_path=RETENTION_POLICY_PATH,
            provider_profile_id=f"minio-runtime-pg-reconcile-{suffix}",
        ),
        object_store_client=EmptyS3CompatibleClient(storage_policy=storage_policy),
    )
    activation = activation_store.activate(
        build_knowledge_base_runtime_activation(
            tenant_id=tenant_id,
            activated_by="tenant-admin-runtime",
            provider_profile_id=f"minio-runtime-pg-reconcile-{suffix}",
            restore_drill_report_hash="sha256:" + "7" * 64,
            source_content_recovery_evidence=wiring.source_content_recovery_evidence,
            provider_profile_evidence=wiring.provider_profile_evidence,
            production_write_deployment_gate_evidence=wiring.production_write_deployment_gate_evidence,
            approval_reference="approval:kb-runtime-pg-reconcile",
            audit_chain_ref="audit:kb-runtime-pg-reconcile",
            activated_at_utc="2026-06-16T08:07:00Z",
        )
    )
    worker = KnowledgeBaseRuntimeReconciliationWorker(
        activation_store=activation_store,
        reconciliation_store=reconciliation_store,
        environ={
            "SUITE_DATABASE_DSN": live_database.app_dsn,
            "SUITE_STORAGE_POLICY_PATH": str(STORAGE_POLICY_PATH),
            "SUITE_RETENTION_POLICY_PATH": str(RETENTION_POLICY_PATH),
        },
        object_store_client=EmptyS3CompatibleClient(storage_policy=storage_policy, break_object_lock=True),
    )

    evidence = worker.reconcile_active_tenant(
        tenant_id=tenant_id,
        checked_by="runtime-reconciler",
        audit_chain_ref="audit:kb-runtime-pg-reconcile-check",
    )
    latest = reconciliation_store.latest_for_activation(tenant_id=tenant_id, activation_id=activation.activation_id)

    assert evidence is not None
    assert latest is not None
    assert latest.evidence_hash == evidence.evidence_hash
    assert activation_store.get_active(tenant_id=tenant_id) is None
    with psycopg.connect(live_database.app_dsn) as connection:
        connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))
        row = connection.execute(
            """
            SELECT active, deactivation_reason, deactivation_reconciliation_evidence_hash
            FROM collabio.knowledge_base_runtime_activations
            WHERE tenant_id = %s
              AND activation_id = %s
            """,
            (tenant_id, activation.activation_id),
        ).fetchone()

    assert row is not None
    assert row[0] is False
    assert row[1] == "runtime_reconciliation_drift"
    assert row[2] == evidence.evidence_hash
