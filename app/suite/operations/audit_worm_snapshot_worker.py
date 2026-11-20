from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

from suite.kms.openbao_transit import OpenBaoTransitAuditCheckpointSigner, OpenBaoTransitHttpClient
from suite.kms.signing import AuditSigningAlgorithm
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
    s3_endpoint_url = _required_https_origin(env, "SUITE_S3_ENDPOINT_URL")
    openbao_address = _required_https_origin(env, "SUITE_OPENBAO_ADDR")
    openbao_token = _read_secret_file(_required_env(env, "SUITE_OPENBAO_TOKEN_FILE"))
    retention_days = _positive_int(env.get("SUITE_AUDIT_WORM_RETENTION_DAYS", "3650"))
    algorithm = AuditSigningAlgorithm(
        env.get("SUITE_AUDIT_SIGNING_ALGORITHM", AuditSigningAlgorithm.ECDSA_SHA_256.value).strip()
    )

    boto3_module = importlib.import_module("boto3")
    client_factory: Any = boto3_module.client
    s3_client = cast(
        S3SdkClient,
        client_factory(
            "s3",
            endpoint_url=s3_endpoint_url,
            aws_access_key_id=env.get("SUITE_S3_ACCESS_KEY_ID") or None,
            aws_secret_access_key=env.get("SUITE_S3_SECRET_ACCESS_KEY") or None,
            region_name=env.get("SUITE_S3_REGION", "us-east-1"),
        ),
    )
    openbao_client = OpenBaoTransitHttpClient(
        address=openbao_address,
        token=openbao_token,
        namespace=env.get("SUITE_OPENBAO_NAMESPACE") or None,
        tls_ca_file=env.get("SUITE_OPENBAO_TLS_CA_FILE") or None,
        client_cert_file=env.get("SUITE_OPENBAO_CLIENT_CERT_FILE") or None,
        client_key_file=env.get("SUITE_OPENBAO_CLIENT_KEY_FILE") or None,
    )

    service = AuditWormSnapshotService(
        repository=PgAuditWormSnapshotRepository(database_dsn=database_dsn),
        signer=OpenBaoTransitAuditCheckpointSigner(
            client=openbao_client,
            kms_key_ref=signing_key_ref,
            provider_key_id=signing_provider_key_id,
            signing_algorithm=algorithm,
            provider_profile=env.get("SUITE_AUDIT_SIGNING_PROVIDER_PROFILE", "openbao-transit"),
        ),
        object_store=Boto3AuditWormObjectStore(
            sdk_client=s3_client,
            provider_storage_key_id=storage_provider_key_id,
            storage_provider=env.get("SUITE_AUDIT_WORM_STORAGE_PROVIDER", "ceph-rgw"),
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


def _required_https_origin(env: dict[str, str], name: str) -> str:
    value = _required_env(env, name).rstrip("/")
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise RuntimeError(f"{name} must be an HTTPS origin without credentials or path")
    hostname = parsed.hostname.lower()
    if hostname.endswith(".amazonaws.com") or hostname.endswith(".amazonaws.com.cn"):
        raise RuntimeError(f"{name} must reference a self-hosted service")
    return value


def _read_secret_file(path_value: str) -> str:
    path = Path(path_value)
    try:
        if not path.is_file() or path.stat().st_size > 16_384:
            raise RuntimeError("OpenBao token file is missing or too large")
        token = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise RuntimeError("OpenBao token file is not readable") from exc
    if not token:
        raise RuntimeError("OpenBao token file is empty")
    return token


if __name__ == "__main__":
    main()
