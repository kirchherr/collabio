from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol, cast

import psycopg
from pydantic import BaseModel, Field

from suite.ai_control_plane.models import DataClass
from suite.storage.adapter_policy import ObjectLockMode, StorageAdapterPolicy
from suite.storage.content_hash import ContentHashVerificationError, verify_content_hash
from suite.storage.retention import (
    RetentionManifest,
    RetentionManifestPolicy,
    build_retention_manifest,
    build_retention_manifest_hash,
)
from suite.storage.source_objects import (
    LegalHoldState,
    SourceLifecycleState,
    SourceObjectMetadata,
    SourceObjectRecord,
    SourceObjectType,
    SourceObjectWriteGuard,
    build_source_object_manifest_hash,
    sha256_bytes,
    source_object_content_bytes,
)
from suite.storage.storage_manifest import (
    StorageObjectManifest,
    build_storage_object_key,
    build_storage_object_manifest,
    build_storage_object_manifest_hash,
)


class SourceObjectStorageError(ValueError):
    pass


class StoredSourceObjectContent(BaseModel):
    tenant_id: str
    object_id: str
    version_id: str
    bucket_id: str
    object_key: str
    object_version_id: str
    storage_provider: str
    stored_at_utc: str
    content_hash: str
    content_byte_length: int = Field(ge=0)


class SourceObjectContentStore(Protocol):
    def put(
        self,
        *,
        record: SourceObjectRecord,
        bucket_id: str,
        object_key: str,
    ) -> StoredSourceObjectContent: ...

    def get(self, *, manifest: StorageObjectManifest) -> bytes: ...


class InMemorySourceObjectContentStore:
    def __init__(
        self,
        *,
        stored_at_clock: Callable[[], str] | None = None,
        storage_provider: str = "in-memory",
    ) -> None:
        self._objects: dict[tuple[str, str, str, str], bytes] = {}
        self.stored_at_clock = stored_at_clock or self._now_utc
        self.storage_provider = storage_provider

    def put(
        self,
        *,
        record: SourceObjectRecord,
        bucket_id: str,
        object_key: str,
    ) -> StoredSourceObjectContent:
        content = source_object_content_bytes(record)
        try:
            verify_content_hash(
                content=content,
                expected_hash=record.metadata.content_hash,
                verification_context="source_object_content_store_put",
            )
        except ContentHashVerificationError as exc:
            raise SourceObjectStorageError(f"content_hash verification failed: {exc}") from exc

        object_version_id = self._object_version_id(
            bucket_id=bucket_id,
            object_key=object_key,
            content_hash=record.metadata.content_hash,
        )
        key = (record.metadata.tenant_id, bucket_id, object_key, object_version_id)
        if key in self._objects and self._objects[key] != content:
            raise SourceObjectStorageError("content object version already exists with different bytes")
        self._objects[key] = content
        return StoredSourceObjectContent(
            tenant_id=record.metadata.tenant_id,
            object_id=record.metadata.object_id,
            version_id=record.metadata.version_id,
            bucket_id=bucket_id,
            object_key=object_key,
            object_version_id=object_version_id,
            storage_provider=self.storage_provider,
            stored_at_utc=self.stored_at_clock(),
            content_hash=record.metadata.content_hash,
            content_byte_length=len(content),
        )

    def get(self, *, manifest: StorageObjectManifest) -> bytes:
        key = (manifest.tenant_id, manifest.bucket_id, manifest.object_key, manifest.object_version_id)
        try:
            content = self._objects[key]
        except KeyError as exc:
            raise KeyError("source object content not found") from exc
        try:
            verify_content_hash(
                content=content,
                expected_hash=manifest.content_hash,
                verification_context="source_object_content_store_get",
            )
        except ContentHashVerificationError as exc:
            raise SourceObjectStorageError(f"content_hash verification failed: {exc}") from exc
        if len(content) != manifest.content_byte_length:
            raise SourceObjectStorageError("content_byte_length does not match storage manifest")
        return content

    def _object_version_id(self, *, bucket_id: str, object_key: str, content_hash: str) -> str:
        digest = sha256_bytes(f"{bucket_id}\x1f{object_key}\x1f{content_hash}".encode()).removeprefix("sha256:")
        return f"mem:{digest}"

    def _now_utc(self) -> str:
        return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


class PgSourceObjectRepository:
    def __init__(
        self,
        *,
        database_dsn: str,
        content_store: SourceObjectContentStore,
        retention_policy: RetentionManifestPolicy,
        storage_policy: StorageAdapterPolicy,
        write_guard: SourceObjectWriteGuard | None = None,
    ) -> None:
        if not database_dsn.strip():
            raise ValueError("database_dsn must not be empty")
        self.database_dsn = database_dsn
        self.content_store = content_store
        self.retention_policy = retention_policy
        self.storage_policy = storage_policy
        self.write_guard = write_guard or SourceObjectWriteGuard()

    def add(self, record: SourceObjectRecord) -> None:
        self.add_with_receipt(record=record, source_object_write_receipt_hash=None)

    def add_with_receipt(
        self,
        *,
        record: SourceObjectRecord,
        source_object_write_receipt_hash: str | None,
    ) -> None:
        try:
            with psycopg.connect(self.database_dsn) as connection:
                self.add_with_receipt_in_transaction(
                    connection,
                    record=record,
                    source_object_write_receipt_hash=source_object_write_receipt_hash,
                )
                connection.commit()
        except psycopg.errors.UniqueViolation as exc:
            raise ValueError("source object version already exists") from exc

    def add_with_receipt_in_transaction(
        self,
        connection: psycopg.Connection[Any],
        *,
        record: SourceObjectRecord,
        source_object_write_receipt_hash: str | None,
    ) -> None:
        retention_manifest, storage_manifest = self._prepare_storage_metadata(record)
        self._set_tenant(connection, record.metadata.tenant_id)
        try:
            self._insert_storage_manifest(connection, storage_manifest)
            self._insert_source_metadata(
                connection,
                record=record,
                retention_manifest=retention_manifest,
                storage_manifest=storage_manifest,
                source_object_write_receipt_hash=source_object_write_receipt_hash,
            )
        except psycopg.errors.UniqueViolation as exc:
            raise ValueError("source object version already exists") from exc

    def get(self, *, tenant_id: str, object_id: str, version_id: str) -> SourceObjectRecord:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            metadata_row = connection.execute(
                """
                SELECT
                    tenant_id,
                    object_id,
                    object_type,
                    version_id,
                    title,
                    owner_principal_id,
                    created_by,
                    created_at_utc,
                    updated_at_utc,
                    classification,
                    retention_policy_id,
                    legal_hold_state,
                    kms_key_ref,
                    manifest_hash,
                    audit_chain_ref,
                    source_system,
                    source_schema_version,
                    mime_type,
                    acl_hash,
                    acl_version,
                    content_hash,
                    content_byte_length,
                    lifecycle_state,
                    parent_object_id,
                    thread_id,
                    parser_profile_id,
                    storage_manifest_hash
                FROM collabio.source_object_metadata
                WHERE tenant_id = %s
                  AND object_id = %s
                  AND version_id = %s
                """,
                (tenant_id, object_id, version_id),
            ).fetchone()
            if metadata_row is None:
                raise KeyError("source object version not found")
            storage_manifest_hash = str(metadata_row[26])
            storage_row = self._select_storage_manifest_row(
                connection,
                tenant_id=tenant_id,
                manifest_hash=storage_manifest_hash,
            )

        metadata = self._metadata_from_row(metadata_row)
        storage_manifest = self._storage_manifest_from_row(storage_row)
        content = self.content_store.get(manifest=storage_manifest)
        record = self._record_from_content(metadata=metadata, content=content)
        self.write_guard.validate_before_write(record)
        self._require_storage_manifest_matches_record(storage_manifest, record)
        return record

    def latest(self, *, tenant_id: str, object_id: str) -> SourceObjectRecord:
        with psycopg.connect(self.database_dsn) as connection:
            self._set_tenant(connection, tenant_id)
            row = connection.execute(
                """
                SELECT version_id
                FROM collabio.source_object_metadata
                WHERE tenant_id = %s
                  AND object_id = %s
                ORDER BY persisted_at_utc DESC, version_id DESC
                LIMIT 1
                """,
                (tenant_id, object_id),
            ).fetchone()
        if row is None:
            raise KeyError("source object not found")
        return self.get(tenant_id=tenant_id, object_id=object_id, version_id=str(row[0]))

    def _insert_source_metadata(
        self,
        connection: psycopg.Connection[Any],
        *,
        record: SourceObjectRecord,
        retention_manifest: RetentionManifest,
        storage_manifest: StorageObjectManifest,
        source_object_write_receipt_hash: str | None,
    ) -> None:
        metadata = record.metadata
        connection.execute(
            """
            INSERT INTO collabio.source_object_metadata (
                tenant_id,
                object_id,
                object_type,
                version_id,
                title,
                owner_principal_id,
                created_by,
                created_at_utc,
                updated_at_utc,
                classification,
                retention_policy_id,
                legal_hold_state,
                kms_key_ref,
                manifest_hash,
                audit_chain_ref,
                source_system,
                source_schema_version,
                mime_type,
                acl_hash,
                acl_version,
                content_hash,
                content_byte_length,
                lifecycle_state,
                parent_object_id,
                thread_id,
                parser_profile_id,
                retention_manifest_hash,
                retention_policy_snapshot_hash,
                storage_manifest_hash,
                source_object_write_receipt_hash
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                metadata.tenant_id,
                metadata.object_id,
                metadata.object_type.value,
                metadata.version_id,
                metadata.title,
                metadata.owner_principal_id,
                metadata.created_by,
                metadata.created_at_utc,
                metadata.updated_at_utc,
                metadata.classification.value,
                metadata.retention_policy_id,
                metadata.legal_hold_state.value,
                metadata.kms_key_ref,
                metadata.manifest_hash,
                metadata.audit_chain_ref,
                metadata.source_system,
                metadata.schema_version,
                metadata.mime_type,
                metadata.acl_hash,
                metadata.acl_version,
                metadata.content_hash,
                metadata.content_byte_length,
                metadata.lifecycle_state.value,
                metadata.parent_object_id,
                metadata.thread_id,
                metadata.parser_profile_id,
                build_retention_manifest_hash(retention_manifest),
                retention_manifest.policy_snapshot_hash,
                storage_manifest.manifest_hash,
                source_object_write_receipt_hash,
            ),
        )

    def _prepare_storage_metadata(
        self,
        record: SourceObjectRecord,
    ) -> tuple[RetentionManifest, StorageObjectManifest]:
        self.write_guard.validate_before_write(record)
        retention_manifest = build_retention_manifest(record, self.retention_policy)
        bucket_profile = self.storage_policy.bucket(retention_manifest.storage_bucket_id)
        object_key = build_storage_object_key(record)
        stored_content = self.content_store.put(
            record=record,
            bucket_id=bucket_profile.bucket_id,
            object_key=object_key,
        )
        storage_manifest = build_storage_object_manifest(
            record=record,
            retention_manifest=retention_manifest,
            bucket_profile=bucket_profile,
            object_version_id=stored_content.object_version_id,
            stored_at_utc=stored_content.stored_at_utc,
            object_key=stored_content.object_key,
            storage_provider=stored_content.storage_provider,
        )
        self._require_stored_content_matches_manifest(stored_content, storage_manifest)
        return retention_manifest, storage_manifest

    def _insert_storage_manifest(
        self,
        connection: psycopg.Connection[Any],
        manifest: StorageObjectManifest,
    ) -> None:
        connection.execute(
            """
            INSERT INTO collabio.source_object_storage_manifests (
                tenant_id,
                object_id,
                object_type,
                source_version_id,
                bucket_id,
                object_key,
                object_version_id,
                storage_provider,
                stored_at_utc,
                classification,
                lifecycle_state,
                retention_policy_id,
                legal_hold_state,
                kms_key_ref,
                source_manifest_hash,
                content_hash,
                content_byte_length,
                retention_manifest_hash,
                retention_policy_snapshot_hash,
                object_lock_mode,
                object_lock_retain_until_utc,
                object_lock_legal_hold,
                worm_required,
                audit_chain_ref,
                manifest_hash,
                schema_version
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                manifest.tenant_id,
                manifest.object_id,
                manifest.object_type.value,
                manifest.source_version_id,
                manifest.bucket_id,
                manifest.object_key,
                manifest.object_version_id,
                manifest.storage_provider,
                manifest.stored_at_utc,
                manifest.classification.value,
                manifest.lifecycle_state.value,
                manifest.retention_policy_id,
                manifest.legal_hold_state.value,
                manifest.kms_key_ref,
                manifest.source_manifest_hash,
                manifest.content_hash,
                manifest.content_byte_length,
                manifest.retention_manifest_hash,
                manifest.retention_policy_snapshot_hash,
                manifest.object_lock_mode.value,
                manifest.object_lock_retain_until_utc,
                manifest.object_lock_legal_hold,
                manifest.worm_required,
                manifest.audit_chain_ref,
                manifest.manifest_hash,
                manifest.schema_version,
            ),
        )

    def _select_storage_manifest_row(
        self,
        connection: psycopg.Connection[Any],
        *,
        tenant_id: str,
        manifest_hash: str,
    ) -> tuple[Any, ...]:
        row = connection.execute(
            """
            SELECT
                schema_version,
                tenant_id,
                object_id,
                object_type,
                source_version_id,
                bucket_id,
                object_key,
                object_version_id,
                storage_provider,
                stored_at_utc,
                classification,
                lifecycle_state,
                retention_policy_id,
                legal_hold_state,
                kms_key_ref,
                source_manifest_hash,
                content_hash,
                content_byte_length,
                retention_manifest_hash,
                retention_policy_snapshot_hash,
                object_lock_mode,
                object_lock_retain_until_utc,
                object_lock_legal_hold,
                worm_required,
                audit_chain_ref,
                manifest_hash
            FROM collabio.source_object_storage_manifests
            WHERE tenant_id = %s
              AND manifest_hash = %s
            """,
            (tenant_id, manifest_hash),
        ).fetchone()
        if row is None:
            raise KeyError("source object storage manifest not found")
        return cast(tuple[Any, ...], row)

    def _metadata_from_row(self, row: tuple[Any, ...]) -> SourceObjectMetadata:
        return SourceObjectMetadata(
            tenant_id=str(row[0]),
            object_id=str(row[1]),
            object_type=SourceObjectType(str(row[2])),
            version_id=str(row[3]),
            title=str(row[4]),
            owner_principal_id=str(row[5]),
            created_by=str(row[6]),
            created_at_utc=self._utc_timestamp(row[7]),
            updated_at_utc=self._utc_timestamp(row[8]),
            classification=self._data_class(str(row[9])),
            retention_policy_id=str(row[10]),
            legal_hold_state=LegalHoldState(str(row[11])),
            kms_key_ref=str(row[12]),
            manifest_hash=str(row[13]),
            audit_chain_ref=str(row[14]),
            source_system=str(row[15]),
            schema_version=str(row[16]),
            mime_type=str(row[17]),
            acl_hash=str(row[18]),
            acl_version=int(row[19]),
            content_hash=str(row[20]),
            content_byte_length=int(row[21]),
            lifecycle_state=SourceLifecycleState(str(row[22])),
            parent_object_id=str(row[23]) if row[23] is not None else None,
            thread_id=str(row[24]) if row[24] is not None else None,
            parser_profile_id=str(row[25]) if row[25] is not None else None,
        )

    def _storage_manifest_from_row(self, row: tuple[Any, ...]) -> StorageObjectManifest:
        return StorageObjectManifest(
            schema_version=str(row[0]),
            tenant_id=str(row[1]),
            object_id=str(row[2]),
            object_type=SourceObjectType(str(row[3])),
            source_version_id=str(row[4]),
            bucket_id=str(row[5]),
            object_key=str(row[6]),
            object_version_id=str(row[7]),
            storage_provider=str(row[8]),
            stored_at_utc=self._utc_timestamp(row[9]),
            classification=DataClass(str(row[10])),
            lifecycle_state=SourceLifecycleState(str(row[11])),
            retention_policy_id=str(row[12]),
            legal_hold_state=LegalHoldState(str(row[13])),
            kms_key_ref=str(row[14]),
            source_manifest_hash=str(row[15]),
            content_hash=str(row[16]),
            content_byte_length=int(row[17]),
            retention_manifest_hash=str(row[18]),
            retention_policy_snapshot_hash=str(row[19]),
            object_lock_mode=ObjectLockMode(str(row[20])),
            object_lock_retain_until_utc=self._utc_timestamp(row[21]) if row[21] is not None else None,
            object_lock_legal_hold=bool(row[22]),
            worm_required=bool(row[23]),
            audit_chain_ref=str(row[24]),
            manifest_hash=str(row[25]),
        )

    def _record_from_content(self, *, metadata: SourceObjectMetadata, content: bytes) -> SourceObjectRecord:
        if metadata.mime_type.startswith("text/") or metadata.mime_type in {"application/json", "message/rfc822"}:
            try:
                return SourceObjectRecord(metadata=metadata, text=content.decode("utf-8"))
            except UnicodeDecodeError:
                pass
        return SourceObjectRecord(metadata=metadata, content_bytes=content)

    def _require_storage_manifest_matches_record(
        self,
        manifest: StorageObjectManifest,
        record: SourceObjectRecord,
    ) -> None:
        if build_storage_object_manifest_hash(manifest) != manifest.manifest_hash:
            raise SourceObjectStorageError("storage manifest hash is invalid")
        metadata = record.metadata
        expected_manifest_hash = build_source_object_manifest_hash(metadata)
        expected_values = {
            "tenant_id": metadata.tenant_id,
            "object_id": metadata.object_id,
            "object_type": metadata.object_type,
            "source_version_id": metadata.version_id,
            "classification": metadata.classification,
            "lifecycle_state": metadata.lifecycle_state,
            "retention_policy_id": metadata.retention_policy_id,
            "legal_hold_state": metadata.legal_hold_state,
            "kms_key_ref": metadata.kms_key_ref,
            "source_manifest_hash": metadata.manifest_hash,
            "content_hash": metadata.content_hash,
            "content_byte_length": metadata.content_byte_length,
            "audit_chain_ref": metadata.audit_chain_ref,
        }
        actual_values = {
            "tenant_id": manifest.tenant_id,
            "object_id": manifest.object_id,
            "object_type": manifest.object_type,
            "source_version_id": manifest.source_version_id,
            "classification": manifest.classification,
            "lifecycle_state": manifest.lifecycle_state,
            "retention_policy_id": manifest.retention_policy_id,
            "legal_hold_state": manifest.legal_hold_state,
            "kms_key_ref": manifest.kms_key_ref,
            "source_manifest_hash": manifest.source_manifest_hash,
            "content_hash": manifest.content_hash,
            "content_byte_length": manifest.content_byte_length,
            "audit_chain_ref": manifest.audit_chain_ref,
        }
        mismatches = sorted(field for field, expected in expected_values.items() if actual_values[field] != expected)
        if metadata.manifest_hash != expected_manifest_hash:
            mismatches.append("source_manifest_hash")
        if mismatches:
            raise SourceObjectStorageError(f"storage manifest does not match source object: {', '.join(mismatches)}")

    def _require_stored_content_matches_manifest(
        self,
        stored_content: StoredSourceObjectContent,
        manifest: StorageObjectManifest,
    ) -> None:
        expected_values = {
            "tenant_id": manifest.tenant_id,
            "object_id": manifest.object_id,
            "version_id": manifest.source_version_id,
            "bucket_id": manifest.bucket_id,
            "object_key": manifest.object_key,
            "object_version_id": manifest.object_version_id,
            "storage_provider": manifest.storage_provider,
            "stored_at_utc": manifest.stored_at_utc,
            "content_hash": manifest.content_hash,
            "content_byte_length": manifest.content_byte_length,
        }
        actual_values = {
            "tenant_id": stored_content.tenant_id,
            "object_id": stored_content.object_id,
            "version_id": stored_content.version_id,
            "bucket_id": stored_content.bucket_id,
            "object_key": stored_content.object_key,
            "object_version_id": stored_content.object_version_id,
            "storage_provider": stored_content.storage_provider,
            "stored_at_utc": stored_content.stored_at_utc,
            "content_hash": stored_content.content_hash,
            "content_byte_length": stored_content.content_byte_length,
        }
        mismatches = sorted(field for field, expected in expected_values.items() if actual_values[field] != expected)
        if mismatches:
            raise SourceObjectStorageError(f"stored content does not match storage manifest: {', '.join(mismatches)}")

    def _data_class(self, value: str) -> DataClass:
        return DataClass(value)

    def _set_tenant(self, connection: psycopg.Connection[Any], tenant_id: str) -> None:
        connection.execute("SELECT set_config('app.tenant_id', %s, false)", (tenant_id,))

    def _utc_timestamp(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
        return str(value)
