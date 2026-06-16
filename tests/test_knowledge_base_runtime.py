import os
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import UserContext
from suite.persistence.migrator import apply_migrations
from suite.platform.knowledge_base import (
    InMemoryKnowledgeBaseArticleRepository,
    KnowledgeBaseArticleService,
    PostgresKnowledgeBaseWriteUnitOfWork,
    demo_knowledge_base_source_object_repository,
)
from suite.platform.knowledge_base_runtime import (
    InMemoryKnowledgeBaseRuntimeActivationStore,
    KnowledgeBaseArticleServiceResolver,
    KnowledgeBaseRuntimeActivation,
    KnowledgeBaseRuntimeActivationCommand,
    KnowledgeBaseRuntimeBackend,
    PgKnowledgeBaseRuntimeActivationStore,
    PostgresS3KnowledgeBaseRuntimeConfig,
    build_configured_knowledge_base_article_service,
    build_knowledge_base_runtime_activation,
    build_knowledge_base_runtime_activation_hash,
    build_postgres_s3_knowledge_base_runtime,
    build_postgres_s3_knowledge_base_runtime_config_from_env,
    knowledge_base_runtime_activation_view,
    knowledge_base_runtime_backend_from_env,
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
