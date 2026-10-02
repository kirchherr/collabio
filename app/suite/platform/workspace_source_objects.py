from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from suite.ai_control_plane.models import DataClass
from suite.storage.adapter_policy import load_storage_adapter_policy
from suite.storage.retention import load_retention_manifest_policy
from suite.storage.s3_compatible_content_store import S3CompatibleSourceObjectContentStore
from suite.storage.s3_sdk_client import build_boto3_s3_compatible_client
from suite.storage.source_object_storage import (
    InMemorySourceObjectContentStore,
    PgSourceObjectRepository,
    SourceObjectContentStore,
)
from suite.storage.source_objects import (
    InMemorySourceObjectRepository,
    LegalHoldState,
    SourceLifecycleState,
    SourceObjectMetadata,
    SourceObjectRecord,
    SourceObjectRepository,
    SourceObjectType,
    build_source_object_manifest_hash,
    sha256_bytes,
)

DEFAULT_WORKSPACE_SOURCE_OBJECT_REFS = "doc-1:v1,mail-1:v1"


@dataclass(frozen=True)
class WorkspaceSourceObjectRef:
    object_id: str
    version_id: str

    def __post_init__(self) -> None:
        if not self.object_id.strip():
            raise ValueError("workspace source object ref object_id must not be empty")
        if not self.version_id.strip():
            raise ValueError("workspace source object ref version_id must not be empty")


class WorkspaceSourceObjectCatalog(Protocol):
    def list_refs(self) -> tuple[WorkspaceSourceObjectRef, ...]: ...


class ConfiguredWorkspaceSourceObjectCatalog:
    def __init__(self, refs: tuple[WorkspaceSourceObjectRef, ...]) -> None:
        self._refs = refs

    def list_refs(self) -> tuple[WorkspaceSourceObjectRef, ...]:
        return self._refs


def parse_workspace_source_object_refs(value: str | None) -> tuple[WorkspaceSourceObjectRef, ...]:
    raw_value = value if value is not None else DEFAULT_WORKSPACE_SOURCE_OBJECT_REFS
    refs: list[WorkspaceSourceObjectRef] = []
    for item in raw_value.split(","):
        ref = item.strip()
        if not ref:
            continue
        if ":" not in ref:
            raise ValueError("workspace source object refs must use object_id:version_id")
        object_id, version_id = (part.strip() for part in ref.split(":", maxsplit=1))
        refs.append(WorkspaceSourceObjectRef(object_id=object_id, version_id=version_id))
    return tuple(refs)


def build_default_workspace_source_object_catalog(
    environ: Mapping[str, str] | None = None,
) -> WorkspaceSourceObjectCatalog:
    env = environ or os.environ
    return ConfiguredWorkspaceSourceObjectCatalog(
        refs=parse_workspace_source_object_refs(env.get("SUITE_WORKSPACE_SOURCE_OBJECT_REFS")),
    )


def build_default_workspace_source_object_repository(
    environ: Mapping[str, str] | None = None,
) -> SourceObjectRepository:
    env = environ or os.environ
    backend = env.get("SUITE_WORKSPACE_SOURCE_OBJECT_REPOSITORY_BACKEND", "demo").strip().lower()
    if backend in {"demo", "memory", "inmemory", "in-memory"}:
        return InMemorySourceObjectRepository(records=demo_workspace_source_object_records())
    if backend not in {"postgres", "postgresql", "pg"}:
        raise ValueError(f"Unsupported SUITE_WORKSPACE_SOURCE_OBJECT_REPOSITORY_BACKEND: {backend}")

    storage_policy_path = Path(env.get("SUITE_STORAGE_POLICY_PATH", "docs/storage_adapter_policy.json"))
    retention_policy_path = Path(env.get("SUITE_RETENTION_POLICY_PATH", "docs/retention_manifest_policy.json"))
    storage_policy = load_storage_adapter_policy(storage_policy_path)
    retention_policy = load_retention_manifest_policy(retention_policy_path)
    content_store_backend = (
        env.get(
            "SUITE_WORKSPACE_SOURCE_OBJECT_CONTENT_STORE_BACKEND",
            env.get("SUITE_SOURCE_OBJECT_CONTENT_STORE_BACKEND", "memory"),
        )
        .strip()
        .lower()
    )
    content_store: SourceObjectContentStore
    if content_store_backend in {"memory", "inmemory", "in-memory"}:
        content_store = InMemorySourceObjectContentStore()
    elif content_store_backend in {"s3", "s3_compatible", "s3-compatible", "minio"}:
        client = build_boto3_s3_compatible_client(
            endpoint_url=env.get("SUITE_S3_ENDPOINT_URL"),
            access_key_id=_required_env(env, "SUITE_S3_ACCESS_KEY_ID"),
            secret_access_key=_required_env(env, "SUITE_S3_SECRET_ACCESS_KEY"),
            region_name=env.get("SUITE_S3_REGION", "us-east-1"),
            storage_provider=env.get("SUITE_S3_STORAGE_PROVIDER", "s3-compatible"),
        )
        content_store = S3CompatibleSourceObjectContentStore(
            client=client,
            storage_policy=storage_policy,
            restore_reference_resolution_enabled=_env_bool(
                env.get("SUITE_S3_RESTORE_REFERENCE_RESOLUTION_ENABLED"),
                default=False,
            ),
        )
    else:
        raise ValueError(f"Unsupported SUITE_WORKSPACE_SOURCE_OBJECT_CONTENT_STORE_BACKEND: {content_store_backend}")

    return PgSourceObjectRepository(
        database_dsn=_first_required_env(env, "SUITE_WORKSPACE_SOURCE_OBJECT_REPOSITORY_DSN", "SUITE_DATABASE_DSN"),
        content_store=content_store,
        retention_policy=retention_policy,
        storage_policy=storage_policy,
    )


def demo_workspace_source_object_records() -> tuple[SourceObjectRecord, ...]:
    return (
        _source_object_record(
            tenant_id="tenant-demo",
            object_id="doc-1",
            object_type=SourceObjectType.DOCUMENT,
            version_id="v1",
            title="Board Pack Draft",
            text="Board pack draft source content.",
            mime_type="text/plain",
            data_classification=DataClass.INTERNAL,
            lifecycle_state=SourceLifecycleState.WORKING,
            audit_chain_ref="audit:doc-1",
        ),
        _source_object_record(
            tenant_id="tenant-demo",
            object_id="mail-1",
            object_type=SourceObjectType.MAIL,
            version_id="v1",
            title="Welcome Message",
            text="From: team@example.test\nTo: demo@example.test\nSubject: Welcome\n\nWelcome message source.",
            mime_type="message/rfc822",
            data_classification=DataClass.PERSONAL,
            lifecycle_state=SourceLifecycleState.SAVED_VERSION,
            audit_chain_ref="audit:mail-1",
            thread_id="mail-thread-demo-1",
        ),
        _source_object_record(
            tenant_id="tenant-other",
            object_id="doc-other",
            object_type=SourceObjectType.DOCUMENT,
            version_id="v1",
            title="Other Tenant Document",
            text="Other tenant document source.",
            mime_type="text/plain",
            data_classification=DataClass.INTERNAL,
            lifecycle_state=SourceLifecycleState.WORKING,
            audit_chain_ref="audit:doc-other",
        ),
    )


def _first_required_env(env: Mapping[str, str], *names: str) -> str:
    for name in names:
        value = env.get(name)
        if value and value.strip():
            return value
    raise ValueError(f"Required environment variable missing: {' or '.join(names)}")


def _required_env(env: Mapping[str, str], name: str) -> str:
    value = env.get(name)
    if value and value.strip():
        return value
    raise ValueError(f"Required environment variable missing: {name}")


def _env_bool(value: str | None, *, default: bool) -> bool:
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError("Boolean environment value must use true/false, 1/0, yes/no, or on/off")


def _source_object_record(
    *,
    tenant_id: str,
    object_id: str,
    object_type: SourceObjectType,
    version_id: str,
    title: str,
    text: str,
    mime_type: str,
    data_classification: DataClass,
    lifecycle_state: SourceLifecycleState,
    audit_chain_ref: str,
    thread_id: str | None = None,
) -> SourceObjectRecord:
    content = text.encode("utf-8")
    draft = SourceObjectMetadata(
        tenant_id=tenant_id,
        object_id=object_id,
        object_type=object_type,
        version_id=version_id,
        title=title,
        owner_principal_id="user-demo" if tenant_id == "tenant-demo" else "user-other",
        created_by="system",
        created_at_utc="2026-06-17T08:00:00Z",
        updated_at_utc="2026-06-17T08:00:00Z",
        classification=data_classification,
        retention_policy_id="rp-standard",
        legal_hold_state=LegalHoldState.NONE,
        kms_key_ref=f"kms://{tenant_id}/{data_classification.value}/v1",
        manifest_hash="sha256:" + "0" * 64,
        audit_chain_ref=audit_chain_ref,
        source_system="collabio",
        mime_type=mime_type,
        acl_hash=sha256_bytes(f"{tenant_id}:{object_id}:acl".encode()),
        acl_version=1,
        content_hash=sha256_bytes(content),
        content_byte_length=len(content),
        lifecycle_state=lifecycle_state,
        thread_id=thread_id,
    )
    return SourceObjectRecord(
        metadata=draft.model_copy(update={"manifest_hash": build_source_object_manifest_hash(draft)}),
        text=text,
    )
