from __future__ import annotations

import importlib
import json
import os
from typing import Any, cast

from suite.kms.signing import AuditSigningAlgorithm, AwsKmsAuditCheckpointSigner, AwsKmsSigningClient
from suite.operations.audit_worm_snapshot import AuditWormSnapshotService, PgAuditWormSnapshotRepository
from suite.storage.audit_worm_store import Boto3AuditWormObjectStore
from suite.storage.s3_sdk_client import S3SdkClient


def build_service_from_environment(env: dict[str, str]) -> tuple[AuditWormSnapshotService, str, str, bool]:
    if env.get("SUITE_AUDIT_WORM_SNAPSHOT_ENABLED", "").strip() != "1":
        raise RuntimeError("audit WORM snapshot execution requires SUITE_AUDIT_WORM_SNAPSHOT_ENABLED=1")

    tenant_id = _required_env(env, "SUITE_AUDIT_WORM_TENANT_ID")
    created_by = _required_env(env, "SUITE_AUDIT_WORM_CREATED_BY")
    database_dsn = _required_env(env, "SUITE_AUDIT_DATABASE_DSN")
    signing_key_ref = _required_env(env, "SUITE_AUDIT_SIGNING_KMS_KEY_REF")
    signing_provider_key_id = _required_env(env, "SUITE_AUDIT_SIGNING_PROVIDER_KEY_ID")
    storage_key_ref = _required_env(env, "SUITE_AUDIT_STORAGE_KMS_KEY_REF")
    storage_provider_key_id = _required_env(env, "SUITE_AUDIT_STORAGE_PROVIDER_KEY_ID")
    retention_days = _positive_int(env.get("SUITE_AUDIT_WORM_RETENTION_DAYS", "3650"))
    algorithm = AuditSigningAlgorithm(
        env.get("SUITE_AUDIT_SIGNING_ALGORITHM", AuditSigningAlgorithm.ECDSA_SHA_256.value).strip()
    )

    boto3_module = importlib.import_module("boto3")
    client_factory: Any = boto3_module.client
    kms_client = cast(
        AwsKmsSigningClient,
        client_factory(
            "kms",
            endpoint_url=env.get("SUITE_AUDIT_KMS_ENDPOINT_URL") or None,
            region_name=env.get("SUITE_AUDIT_KMS_REGION", env.get("AWS_REGION", "eu-central-1")),
        ),
    )
    s3_client = cast(
        S3SdkClient,
        client_factory(
            "s3",
            endpoint_url=env.get("SUITE_S3_ENDPOINT_URL") or None,
            aws_access_key_id=env.get("SUITE_S3_ACCESS_KEY_ID") or None,
            aws_secret_access_key=env.get("SUITE_S3_SECRET_ACCESS_KEY") or None,
            region_name=env.get("SUITE_S3_REGION", "eu-central-1"),
        ),
    )

    service = AuditWormSnapshotService(
        repository=PgAuditWormSnapshotRepository(database_dsn=database_dsn),
        signer=AwsKmsAuditCheckpointSigner(
            sdk_client=kms_client,
            kms_key_ref=signing_key_ref,
            provider_key_id=signing_provider_key_id,
            signing_algorithm=algorithm,
            provider_profile=env.get("SUITE_AUDIT_SIGNING_PROVIDER_PROFILE", "aws-kms"),
        ),
        object_store=Boto3AuditWormObjectStore(
            sdk_client=s3_client,
            provider_storage_key_id=storage_provider_key_id,
            storage_provider=env.get("SUITE_AUDIT_WORM_STORAGE_PROVIDER", "aws-s3"),
        ),
        storage_kms_key_ref=storage_key_ref,
        retention_policy_id=env.get("SUITE_AUDIT_WORM_RETENTION_POLICY_ID", "audit-security-10y-v1"),
        retention_days=retention_days,
        bucket_id=env.get("SUITE_AUDIT_WORM_BUCKET_ID", "evidence-records"),
    )
    legal_hold_enabled = env.get("SUITE_AUDIT_WORM_LEGAL_HOLD", "0").strip() == "1"
    return service, tenant_id, created_by, legal_hold_enabled


def main() -> None:
    service, tenant_id, created_by, legal_hold_enabled = build_service_from_environment(dict(os.environ))
    result = service.create_for_tenant(
        tenant_id=tenant_id,
        created_by=created_by,
        legal_hold_enabled=legal_hold_enabled,
    )
    print(json.dumps(result.model_dump(mode="json"), sort_keys=True))


def _required_env(env: dict[str, str], name: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise RuntimeError("audit WORM retention days must be positive")
    return parsed


if __name__ == "__main__":
    main()
