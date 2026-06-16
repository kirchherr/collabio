from __future__ import annotations

import importlib
import time
from collections.abc import Callable, Iterable, Mapping
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

from suite.storage.adapter_policy import ObjectLockMode, StorageAdapterPolicy
from suite.storage.s3_compatible_content_store import (
    S3CompatibleBucketCapabilities,
    S3CompatibleObjectWriteResult,
    S3CompatibleStoredObjectVersion,
)
from suite.storage.source_object_storage import SourceObjectStorageError


@runtime_checkable
class S3SdkStreamingBody(Protocol):
    def read(self) -> bytes: ...


class S3SdkPaginator(Protocol):
    def paginate(self, **kwargs: object) -> Iterable[Mapping[str, Any]]: ...


class S3SdkClient(Protocol):
    def create_bucket(self, **kwargs: object) -> Mapping[str, Any]: ...

    def get_bucket_versioning(self, **kwargs: object) -> Mapping[str, Any]: ...

    def put_bucket_versioning(self, **kwargs: object) -> Mapping[str, Any]: ...

    def get_object_lock_configuration(self, **kwargs: object) -> Mapping[str, Any]: ...

    def put_object_lock_configuration(self, **kwargs: object) -> Mapping[str, Any]: ...

    def put_object(self, **kwargs: object) -> Mapping[str, Any]: ...

    def get_object(self, **kwargs: object) -> Mapping[str, Any]: ...

    def head_object(self, **kwargs: object) -> Mapping[str, Any]: ...

    def list_object_versions(self, **kwargs: object) -> Mapping[str, Any]: ...

    def get_paginator(self, operation_name: str) -> S3SdkPaginator: ...


class Boto3S3CompatibleObjectStoreClient:
    def __init__(
        self,
        *,
        sdk_client: S3SdkClient,
        storage_provider: str = "s3-compatible",
        stored_at_clock: Callable[[], str] | None = None,
    ) -> None:
        if not storage_provider.strip():
            raise SourceObjectStorageError("storage_provider must not be empty")
        self.sdk_client = sdk_client
        self.storage_provider = storage_provider
        self.stored_at_clock = stored_at_clock or _utc_now

    def bucket_capabilities(self, *, bucket_id: str) -> S3CompatibleBucketCapabilities:
        try:
            versioning = self.sdk_client.get_bucket_versioning(Bucket=bucket_id)
        except Exception as exc:
            raise SourceObjectStorageError("S3-compatible SDK call failed: get_bucket_versioning") from exc
        object_lock_enabled = False
        try:
            object_lock_configuration = self.sdk_client.get_object_lock_configuration(Bucket=bucket_id)
        except Exception:
            object_lock_configuration = {}
        object_lock = object_lock_configuration.get("ObjectLockConfiguration", {})
        if isinstance(object_lock, Mapping):
            object_lock_enabled = object_lock.get("ObjectLockEnabled") == "Enabled"
        return S3CompatibleBucketCapabilities(
            bucket_id=bucket_id,
            storage_provider=self.storage_provider,
            versioning_enabled=versioning.get("Status") == "Enabled",
            object_lock_enabled=object_lock_enabled,
            legal_hold_supported=object_lock_enabled,
        )

    def ensure_bucket_profiles(self, *, storage_policy: StorageAdapterPolicy) -> None:
        for bucket_profile in storage_policy.bucket_profiles:
            bucket_id = bucket_profile.bucket_id
            create_params: dict[str, object] = {"Bucket": bucket_id}
            if bucket_profile.object_lock_required:
                create_params["ObjectLockEnabledForBucket"] = True
            try:
                self.sdk_client.create_bucket(**create_params)
            except Exception as exc:
                if not _looks_like_existing_bucket_error(exc):
                    raise SourceObjectStorageError(f"S3-compatible bucket bootstrap failed: {bucket_id}") from exc

            try:
                self.sdk_client.put_bucket_versioning(
                    Bucket=bucket_id,
                    VersioningConfiguration={"Status": "Enabled"},
                )
            except Exception as exc:
                raise SourceObjectStorageError("S3-compatible SDK call failed: put_bucket_versioning") from exc
            if bucket_profile.object_lock_required:
                try:
                    self.sdk_client.put_object_lock_configuration(
                        Bucket=bucket_id,
                        ObjectLockConfiguration={
                            "ObjectLockEnabled": "Enabled",
                            "Rule": {
                                "DefaultRetention": {
                                    "Mode": bucket_profile.object_lock_mode.value.upper(),
                                    "Days": bucket_profile.default_retention_days,
                                }
                            },
                        },
                    )
                except Exception as exc:
                    raise SourceObjectStorageError(
                        "S3-compatible SDK call failed: put_object_lock_configuration"
                    ) from exc

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
        put_params: dict[str, object] = {
            "Bucket": bucket_id,
            "Key": object_key,
            "Body": body,
            "Metadata": metadata,
        }
        if object_lock_mode != ObjectLockMode.NONE:
            put_params["Metadata"] = {**metadata, "collabio-object-lock-mode": object_lock_mode.value}
        if legal_hold:
            put_params["ObjectLockLegalHoldStatus"] = "ON"
        result = self._sdk_call("put_object", lambda: self.sdk_client.put_object(**put_params))
        version_id = str(result.get("VersionId", "")).strip()
        if not version_id:
            raise SourceObjectStorageError("S3-compatible object write did not return a VersionId")
        return S3CompatibleObjectWriteResult(
            bucket_id=bucket_id,
            object_key=object_key,
            object_version_id=version_id,
            storage_provider=self.storage_provider,
            stored_at_utc=self.stored_at_clock(),
        )

    def get_object(self, *, bucket_id: str, object_key: str, object_version_id: str) -> bytes:
        result = self._sdk_call(
            "get_object",
            lambda: self.sdk_client.get_object(Bucket=bucket_id, Key=object_key, VersionId=object_version_id),
        )
        return _body_to_bytes(result.get("Body"))

    def list_object_versions(
        self,
        *,
        bucket_id: str,
        prefix: str,
    ) -> tuple[S3CompatibleStoredObjectVersion, ...]:
        pages = self._list_object_version_pages(bucket_id=bucket_id, prefix=prefix)
        versions: list[S3CompatibleStoredObjectVersion] = []
        for page in pages:
            for version in page.get("Versions", ()):
                if not isinstance(version, Mapping):
                    continue
                object_key = str(version.get("Key", "")).strip()
                object_version_id = str(version.get("VersionId", "")).strip()
                if not object_key or not object_version_id:
                    continue
                try:
                    head = self.sdk_client.head_object(Bucket=bucket_id, Key=object_key, VersionId=object_version_id)
                except Exception as exc:
                    raise SourceObjectStorageError("S3-compatible SDK call failed: head_object") from exc
                metadata = head.get("Metadata", {})
                if not isinstance(metadata, Mapping):
                    metadata = {}
                versions.append(
                    S3CompatibleStoredObjectVersion(
                        bucket_id=bucket_id,
                        object_key=object_key,
                        object_version_id=object_version_id,
                        storage_provider=self.storage_provider,
                        stored_at_utc=str(
                            head.get("LastModified", version.get("LastModified", self.stored_at_clock()))
                        ),
                        metadata={str(key): str(value) for key, value in metadata.items()},
                    )
                )
        return tuple(sorted(versions, key=lambda item: (item.object_key, item.object_version_id)))

    def _list_object_version_pages(self, *, bucket_id: str, prefix: str) -> Iterable[Mapping[str, Any]]:
        try:
            paginator = self.sdk_client.get_paginator("list_object_versions")
        except Exception:
            return (
                self._sdk_call(
                    "list_object_versions",
                    lambda: self.sdk_client.list_object_versions(Bucket=bucket_id, Prefix=prefix),
                ),
            )
        return paginator.paginate(Bucket=bucket_id, Prefix=prefix)

    def _sdk_call(self, operation_name: str, action: Callable[[], Mapping[str, Any]]) -> Mapping[str, Any]:
        try:
            return action()
        except SourceObjectStorageError:
            raise
        except Exception as exc:
            raise SourceObjectStorageError(f"S3-compatible SDK call failed: {operation_name}") from exc


def build_boto3_s3_compatible_client(
    *,
    endpoint_url: str | None,
    access_key_id: str,
    secret_access_key: str,
    region_name: str = "us-east-1",
    storage_provider: str = "s3-compatible",
) -> Boto3S3CompatibleObjectStoreClient:
    try:
        boto3_module = importlib.import_module("boto3")
    except ModuleNotFoundError as exc:
        raise SourceObjectStorageError("boto3 is required for the S3-compatible SDK client") from exc
    boto3_client_factory = boto3_module.client
    sdk_client = boto3_client_factory(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name=region_name,
    )
    return Boto3S3CompatibleObjectStoreClient(sdk_client=sdk_client, storage_provider=storage_provider)


def wait_for_s3_compatible_client(
    *,
    client: Boto3S3CompatibleObjectStoreClient,
    storage_policy: StorageAdapterPolicy,
    retries: int = 30,
    delay_seconds: float = 1.0,
) -> None:
    last_error: SourceObjectStorageError | None = None
    for _attempt in range(retries):
        try:
            client.ensure_bucket_profiles(storage_policy=storage_policy)
            return
        except SourceObjectStorageError as exc:
            last_error = exc
            time.sleep(delay_seconds)
    if last_error is not None:
        raise last_error


def _body_to_bytes(body: object) -> bytes:
    if isinstance(body, bytes):
        return body
    if isinstance(body, bytearray):
        return bytes(body)
    if isinstance(body, S3SdkStreamingBody):
        data = body.read()
        if isinstance(data, bytes):
            return data
    raise SourceObjectStorageError("S3-compatible object body is not readable bytes")


def _looks_like_existing_bucket_error(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    if isinstance(response, Mapping):
        error = response.get("Error")
        if isinstance(error, Mapping) and error.get("Code") in {
            "BucketAlreadyOwnedByYou",
            "BucketAlreadyExists",
        }:
            return True
    message = str(exc)
    return "BucketAlreadyOwnedByYou" in message or "BucketAlreadyExists" in message


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
