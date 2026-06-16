from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.platform.knowledge_base import (
    KnowledgeBaseArticleService,
    KnowledgeBaseProductionWriteDeploymentGateEvidence,
    PgKnowledgeBaseArticleRepository,
    PostgresKnowledgeBaseWriteUnitOfWork,
    build_default_knowledge_base_write_approval_ledger,
    build_knowledge_base_production_write_deployment_gate,
)
from suite.storage.adapter_policy import StorageAdapterPolicy, load_storage_adapter_policy
from suite.storage.retention import RetentionManifestPolicy, load_retention_manifest_policy
from suite.storage.s3_compatible_content_store import (
    S3CompatibleObjectStoreClient,
    S3CompatibleProviderProfileEvidence,
    S3CompatibleSourceObjectContentStore,
    build_s3_compatible_provider_profile_evidence,
)
from suite.storage.s3_sdk_client import build_boto3_s3_compatible_client
from suite.storage.source_object_storage import (
    PgSourceObjectRepository,
    SourceObjectContentRecoveryEvidence,
)
from suite.storage.source_objects import PgSourceObjectWriteReceiptStore


class KnowledgeBaseRuntimeBackend(StrEnum):
    DEMO = "demo"
    POSTGRES_S3 = "postgres_s3"


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
    return PostgresS3KnowledgeBaseRuntimeConfig(
        tenant_id=_required_env(env, "SUITE_KB_RUNTIME_TENANT_ID"),
        database_dsn=_first_required_env(env, "SUITE_KB_RUNTIME_DATABASE_DSN", "SUITE_DATABASE_DSN"),
        restore_drill_report_hash=_required_env(env, "SUITE_KB_RESTORE_DRILL_REPORT_HASH"),
        storage_policy_path=Path(env.get("SUITE_STORAGE_POLICY_PATH", "docs/storage_adapter_policy.json")),
        retention_policy_path=Path(env.get("SUITE_RETENTION_POLICY_PATH", "docs/retention_manifest_policy.json")),
        provider_profile_id=env.get("SUITE_S3_PROVIDER_PROFILE_ID", "s3-compatible-runtime"),
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


def build_postgres_s3_knowledge_base_runtime(
    *,
    config: PostgresS3KnowledgeBaseRuntimeConfig,
    object_store_client: S3CompatibleObjectStoreClient | None = None,
) -> KnowledgeBasePostgresS3RuntimeWiring:
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
    if config.bootstrap_bucket_profiles:
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
    if not production_gate_evidence.api_wiring_allowed:
        reasons = ", ".join(production_gate_evidence.blocking_reasons) or production_gate_evidence.gate_status
        raise ValueError(f"knowledge base production runtime gate is blocked: {reasons}")

    article_repository = PgKnowledgeBaseArticleRepository(database_dsn=config.database_dsn)
    receipt_store = PgSourceObjectWriteReceiptStore(database_dsn=config.database_dsn)
    write_unit_of_work = PostgresKnowledgeBaseWriteUnitOfWork(
        database_dsn=config.database_dsn,
        article_repository=article_repository,
        source_repository=source_repository,
        source_object_write_receipt_store=receipt_store,
        source_content_recovery_evidence=source_content_recovery_evidence,
        production_write_deployment_gate_evidence=production_gate_evidence,
        require_source_content_recovery_gate=True,
    )
    return KnowledgeBasePostgresS3RuntimeWiring(
        config=config,
        storage_policy=storage_policy,
        retention_policy=retention_policy,
        content_store=content_store,
        source_repository=source_repository,
        article_repository=article_repository,
        source_object_write_receipt_store=receipt_store,
        provider_profile_evidence=provider_profile_evidence,
        source_content_recovery_evidence=source_content_recovery_evidence,
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
