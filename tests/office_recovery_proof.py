"""Explicit synthetic-only PostgreSQL/S3 recovery proof after the Work browser run.

The operator supplies an already restored, separate database and its checked
pg_dump artifact. Only this short-lived proof runner joins both test networks.
It never creates/restores/drops a database or enables a module or Office engine.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import psycopg

from suite.ai_control_plane.audit import InMemoryAuditLogger, canonical_json, stable_hash
from suite.ai_control_plane.models import UserContext
from suite.operations.postgres_restore_drill import run_postgres_restore_drill_from_environment
from suite.platform.office_document_repository import PgOfficeDocumentRepository
from suite.platform.office_documents import OfficeDocumentNotFoundError, OfficeDocumentService
from suite.platform.principal_store import PgPrincipalDirectory
from suite.storage.adapter_policy import load_storage_adapter_policy
from suite.storage.exact_version_restore_drill import (
    build_restore_target_isolation_ref_hash,
    run_exact_version_restore_drill,
)
from suite.storage.retention import load_retention_manifest_policy
from suite.storage.s3_compatible_content_store import (
    S3CompatibleSourceObjectContentStore,
    build_s3_compatible_provider_profile_evidence,
)
from suite.storage.s3_sdk_client import build_boto3_s3_compatible_client, wait_for_s3_compatible_client
from suite.storage.source_object_storage import PgSourceObjectRepository
from suite.storage.source_objects import PgSourceObjectWriteReceiptStore, build_source_object_write_receipt_hash

TENANT_ID = "tenant-work-e2e"
EDITOR_ID = "work-office-editor-e2e"


def require_office_recovery_environment(env: Mapping[str, str]) -> None:
    if (
        env.get("SUITE_OFFICE_RECOVERY_MODE") != "isolated-office-recovery"
        or env.get("SUITE_ENV") != "dev"
        or env.get("SUITE_PRODUCTIVITY_PILOT_RUNTIME_ENABLED") != "0"
    ):
        raise ValueError("Office recovery requires the isolated development marker and closed pilot")
    expected = {
        "SUITE_POSTGRES_RESTORE_SOURCE_DSN": ("work-e2e-postgres", "collabio_work_e2e", "collabio_owner"),
        "SUITE_POSTGRES_RESTORE_TARGET_DSN": ("postgres-restore", "collabio_work_e2e_restore", "collabio_owner"),
        "SUITE_DATABASE_DSN": ("work-e2e-postgres", "collabio_work_e2e", "collabio_app"),
        "SUITE_OFFICE_RECOVERY_TARGET_DSN": ("postgres-restore", "collabio_work_e2e_restore", "collabio_app"),
    }
    for key, (host, database, user) in expected.items():
        parsed = urlparse(env.get(key, ""))
        if (
            parsed.scheme not in {"postgres", "postgresql"}
            or parsed.hostname != host
            or parsed.path != f"/{database}"
            or parsed.username != user
            or parsed.port != 5432
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Office recovery database is outside its isolated scope")
    if env.get("SUITE_S3_ENDPOINT_URL") != "http://work-e2e-minio:9000":
        raise ValueError("Office recovery source storage is outside its isolated scope")
    if env.get("SUITE_RESTORE_S3_ENDPOINT_URL") != "http://minio-restore:9000":
        raise ValueError("Office recovery target storage is outside its isolated scope")
    if (
        env.get("SUITE_POSTGRES_BACKUP_DIRECTORY") != "/proof-backup"
        or env.get("SUITE_POSTGRES_RESTORE_RECEIPT_PATH") != "/proof-backup/postgres-restore-receipt.sha256"
    ):
        raise ValueError("Office recovery must use its separately mounted backup artifact")


def _metadata_hash(database_dsn: str) -> str:
    rows: dict[str, list[Any]] = {}
    with psycopg.connect(database_dsn) as connection:
        connection.execute("SELECT set_config('app.tenant_id', %s, true)", (TENANT_ID,))
        for table in ("documents", "document_versions"):
            result = connection.execute(
                f"SELECT to_jsonb(record) FROM office.{table} AS record WHERE tenant_id = %s "
                "ORDER BY to_jsonb(record)::text",
                (TENANT_ID,),
            ).fetchall()
            rows[table] = [row[0] for row in result]
        result = connection.execute(
            "SELECT to_jsonb(acl) FROM collabio.object_acl_entries AS acl "
            "WHERE acl.tenant_id = %s AND acl.object_type = 'office.document' "
            "ORDER BY to_jsonb(acl)::text",
            (TENANT_ID,),
        ).fetchall()
        rows["acls"] = [row[0] for row in result]
    return stable_hash(canonical_json(rows))


def _restored_reader(database_dsn: str) -> UserContext:
    # Resolve the existing seeded principal and its current DB grants. No role or
    # readable-object browser headers are accepted by this proof.
    with psycopg.connect(database_dsn) as connection:
        connection.execute("SELECT set_config('app.tenant_id', %s, true)", (TENANT_ID,))
        principal = connection.execute(
            "SELECT p.user_id FROM collabio.tenant_principals AS p "
            "JOIN collabio.tenant_principal_memberships AS m "
            "ON m.tenant_id = p.tenant_id AND m.issuer = p.issuer AND m.subject = p.subject "
            "WHERE p.tenant_id = %s AND p.user_id = %s AND p.status = 'active' AND m.status = 'active'",
            (TENANT_ID, EDITOR_ID),
        ).fetchone()
    if principal is None:
        raise ValueError("Office recovery synthetic reader membership is missing")
    readable = PgPrincipalDirectory(database_dsn=database_dsn).readable_object_ids(
        tenant_id=TENANT_ID,
        user_id=EDITOR_ID,
        role_ids=set(),
        group_ids=set(),
    )
    return UserContext(tenant_id=TENANT_ID, user_id=EDITOR_ID, readable_object_ids=readable)


def run_office_recovery_proof(env: Mapping[str, str]) -> dict[str, Any]:
    require_office_recovery_environment(env)
    postgres = run_postgres_restore_drill_from_environment(env)
    if not postgres.restore_ready or not postgres.office_document_controls_verified:
        raise ValueError("Office recovery PostgreSQL controls are not verified")
    source_dsn = env["SUITE_DATABASE_DSN"]
    target_dsn = env["SUITE_OFFICE_RECOVERY_TARGET_DSN"]
    source_metadata_hash = _metadata_hash(source_dsn)
    if source_metadata_hash != _metadata_hash(target_dsn):
        raise ValueError("Office metadata and ACL snapshot do not match the source")
    storage_policy = load_storage_adapter_policy(Path("docs/storage_adapter_policy.json"))
    retention_policy = load_retention_manifest_policy(Path("docs/retention_manifest_policy.json"))
    source_client = build_boto3_s3_compatible_client(
        endpoint_url=env["SUITE_S3_ENDPOINT_URL"],
        access_key_id=env["SUITE_S3_ACCESS_KEY_ID"],
        secret_access_key=env["SUITE_S3_SECRET_ACCESS_KEY"],
        storage_provider="minio",
    )
    target_client = build_boto3_s3_compatible_client(
        endpoint_url=env["SUITE_RESTORE_S3_ENDPOINT_URL"],
        access_key_id=env["SUITE_RESTORE_S3_ACCESS_KEY_ID"],
        secret_access_key=env["SUITE_RESTORE_S3_SECRET_ACCESS_KEY"],
        storage_provider="minio-restore-target",
    )
    wait_for_s3_compatible_client(client=target_client, storage_policy=storage_policy)
    source_repository = PgSourceObjectRepository(
        database_dsn=source_dsn,
        storage_policy=storage_policy,
        retention_policy=retention_policy,
        content_store=S3CompatibleSourceObjectContentStore(client=source_client, storage_policy=storage_policy),
    )
    source_profile = build_s3_compatible_provider_profile_evidence(
        client=source_client,
        storage_policy=storage_policy,
        provider_profile_id="office-e2e-source",
    )
    target_profile = build_s3_compatible_provider_profile_evidence(
        client=target_client,
        storage_policy=storage_policy,
        provider_profile_id="office-e2e-restore",
    )
    objects = run_exact_version_restore_drill(
        repository=source_repository,
        target_client=target_client,
        storage_policy=storage_policy,
        retention_policy=retention_policy,
        source_provider_profile_evidence=source_profile,
        target_provider_profile_evidence=target_profile,
        target_isolation_ref_hash=build_restore_target_isolation_ref_hash(
            source_endpoint=env["SUITE_S3_ENDPOINT_URL"],
            target_endpoint=env["SUITE_RESTORE_S3_ENDPOINT_URL"],
            source_provider_profile_id="office-e2e-source",
            target_provider_profile_id="office-e2e-restore",
        ),
        tenant_ids=(TENANT_ID,),
    )
    if not objects.restore_ready:
        raise ValueError("Office exact-version object restoration is not verified")
    restored_sources = PgSourceObjectRepository(
        database_dsn=target_dsn,
        storage_policy=storage_policy,
        retention_policy=retention_policy,
        content_store=S3CompatibleSourceObjectContentStore(
            client=target_client,
            storage_policy=storage_policy,
            restore_reference_resolution_enabled=True,
        ),
    )
    receipt_store = PgSourceObjectWriteReceiptStore(database_dsn=target_dsn)
    restored = OfficeDocumentService(
        repository=PgOfficeDocumentRepository(
            database_dsn=target_dsn, source_repository=restored_sources, receipt_store=receipt_store
        ),
        source_repository=restored_sources,
        audit=InMemoryAuditLogger(),
        writes_available=False,
    )
    user = _restored_reader(target_dsn)
    documents = restored.list_documents(user_context=user).documents
    evidence: list[dict[str, Any]] = []
    multi_version_documents = 0
    for document in documents:
        history = restored.history(user_context=user, object_id=document.object_id)
        multi_version_documents += int(len(history.versions) >= 2)
        for version in history.versions:
            read = restored.read_content(user_context=user, object_id=document.object_id, version_id=version.version_id)
            receipt = receipt_store.get(tenant_id=TENANT_ID, receipt_hash=version.source_write_receipt_hash)
            source = source_repository.get(
                tenant_id=TENANT_ID, object_id=document.object_id, version_id=version.version_id
            )
            if (
                receipt.receipt_hash != build_source_object_write_receipt_hash(receipt)
                or receipt.object_id != document.object_id
                or receipt.version_id != version.version_id
                or receipt.content_hash != version.content_hash
                or receipt.manifest_hash != source.metadata.manifest_hash
                or stable_hash(canonical_json(read.content)) != source.metadata.content_hash
                or read.can_write
                or read.rag_indexing_allowed
                or read.search_indexing_allowed
            ):
                raise ValueError("Office restored version or receipt binding is invalid")
            evidence.append(
                {
                    "object_id": document.object_id,
                    "version_id": version.version_id,
                    "content_hash": version.content_hash,
                    "receipt_hash": receipt.receipt_hash,
                }
            )
    if multi_version_documents < 1 or len(evidence) < 2:
        raise ValueError("Office recovery requires a non-empty document with at least two saved versions")
    foreign = UserContext(
        tenant_id="tenant-work-e2e-foreign", user_id=EDITOR_ID, readable_object_ids={documents[0].object_id}
    )
    try:
        restored.read_content(user_context=foreign, object_id=documents[0].object_id)
    except OfficeDocumentNotFoundError:
        pass
    else:
        raise ValueError("Office restored tenant isolation did not deny a foreign reader")
    if source_metadata_hash != _metadata_hash(source_dsn) or source_metadata_hash != _metadata_hash(target_dsn):
        raise ValueError("Office recovery observed concurrent metadata changes")
    report = {
        "schema_version": "office_native_synthetic_recovery_proof.v1",
        "synthetic_only": True,
        "postgres_restore_report_hash": postgres.report_hash,
        "backup_sha256": postgres.backup_sha256,
        "exact_version_restore_report_hash": objects.report_hash,
        "office_metadata_hash": source_metadata_hash,
        "version_evidence_hash": stable_hash(canonical_json(evidence)),
        "document_count": len(documents),
        "verified_office_version_count": len(evidence),
        "multi_version_document_count": multi_version_documents,
        "restored_source_object_count": objects.restored_object_count,
        "authoritative_acl_verified": True,
        "receipt_bindings_verified": True,
        "foreign_tenant_denied": True,
        "recovery_ready": True,
        "content_included": False,
        "runtime_activated": False,
        "office_engine_admitted": False,
    }
    report["report_hash"] = stable_hash(canonical_json(report))
    return report


def main() -> int:
    try:
        report = run_office_recovery_proof(os.environ)
    except (KeyError, ValueError, OSError, psycopg.Error):
        print(
            json.dumps(
                {
                    "schema_version": "office_native_synthetic_recovery_proof.v1",
                    "recovery_ready": False,
                    "content_included": False,
                    "reason": "Office synthetic recovery proof failed",
                },
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
