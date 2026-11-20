from collections.abc import Mapping
from typing import Any

import pytest

from suite.storage.audit_worm_store import (
    AuditWormObjectWriteRequest,
    AuditWormStorageError,
    Boto3AuditWormObjectStore,
)


class FakeAuditWormS3Client:
    def __init__(self) -> None:
        self.body = b""
        self.metadata: dict[str, str] = {}
        self.put_call: dict[str, object] = {}
        self.object_lock_mode = "COMPLIANCE"
        self.readback_override: bytes | None = None

    def create_bucket(self, **kwargs: object) -> Mapping[str, Any]:
        return {}

    def get_bucket_versioning(self, **kwargs: object) -> Mapping[str, Any]:
        return {"Status": "Enabled"}

    def put_bucket_versioning(self, **kwargs: object) -> Mapping[str, Any]:
        return {}

    def get_object_lock_configuration(self, **kwargs: object) -> Mapping[str, Any]:
        return {"ObjectLockConfiguration": {"ObjectLockEnabled": "Enabled"}}

    def put_object_lock_configuration(self, **kwargs: object) -> Mapping[str, Any]:
        return {}

    def put_object(self, **kwargs: object) -> Mapping[str, Any]:
        self.put_call = dict(kwargs)
        body = kwargs["Body"]
        metadata = kwargs["Metadata"]
        assert isinstance(body, bytes)
        assert isinstance(metadata, dict)
        self.body = body
        self.metadata = {str(key): str(value) for key, value in metadata.items()}
        return {
            "VersionId": "object-version-1",
            "ResponseMetadata": {"RequestId": "s3-put-request"},
        }

    def get_object(self, **kwargs: object) -> Mapping[str, Any]:
        assert kwargs["VersionId"] == "object-version-1"
        return {
            "Body": self.readback_override if self.readback_override is not None else self.body,
            "ResponseMetadata": {"RequestId": "s3-get-request"},
        }

    def head_object(self, **kwargs: object) -> Mapping[str, Any]:
        assert kwargs["VersionId"] == "object-version-1"
        return {
            "Metadata": self.metadata,
            "ObjectLockMode": self.object_lock_mode,
            "ObjectLockRetainUntilDate": self.put_call["ObjectLockRetainUntilDate"],
            "ObjectLockLegalHoldStatus": self.put_call["ObjectLockLegalHoldStatus"],
            "ServerSideEncryption": "aws:kms",
            "SSEKMSKeyId": "arn:aws:kms:eu-central-1:123456789012:key/storage-key",
            "ResponseMetadata": {"RequestId": "s3-head-request"},
        }

    def list_object_versions(self, **kwargs: object) -> Mapping[str, Any]:
        return {"Versions": []}

    def get_paginator(self, operation_name: str) -> "FakePaginator":
        return FakePaginator()


class FakePaginator:
    def paginate(self, **kwargs: object) -> tuple[Mapping[str, Any], ...]:
        return ()


def write_request(body: bytes) -> AuditWormObjectWriteRequest:
    from hashlib import sha256

    return AuditWormObjectWriteRequest(
        tenant_id="tenant-audit",
        checkpoint_id="audit-checkpoint-v2-1234",
        object_key="audit-snapshots/v2/tenant/0001/checkpoint.json",
        bundle_hash="sha256:" + sha256(body).hexdigest(),
        manifest_hash="sha256:" + ("a" * 64),
        signature_hash="sha256:" + ("b" * 64),
        retain_until_utc="2036-08-14T10:00:00Z",
        storage_kms_key_ref="kms://tenant-audit/confidential/v2",
    )


def object_store(client: FakeAuditWormS3Client) -> Boto3AuditWormObjectStore:
    return Boto3AuditWormObjectStore(
        sdk_client=client,
        provider_storage_key_id="arn:aws:kms:eu-central-1:123456789012:key/storage-key",
    )


def test_boto3_audit_worm_store_writes_exact_version_and_verifies_controls() -> None:
    client = FakeAuditWormS3Client()
    store = object_store(client)
    body = b'{"schema_version":"audit_worm_snapshot_bundle.v2"}'

    receipt = store.put_verified(request=write_request(body), body=body)

    assert receipt.object_version_id == "object-version-1"
    assert receipt.object_lock_mode == "compliance"
    assert receipt.object_lock_retain_until_utc == "2036-08-14T10:00:00Z"
    assert receipt.server_side_encryption == "aws:kms"
    assert receipt.readback_verified is True
    assert receipt.object_lock_verified is True
    assert receipt.encryption_verified is True
    assert receipt.storage_uri.endswith("?versionId=object-version-1")
    assert client.put_call["ObjectLockMode"] == "COMPLIANCE"
    assert client.put_call["ObjectLockLegalHoldStatus"] == "OFF"
    assert client.put_call["ServerSideEncryption"] == "aws:kms"
    assert client.put_call["SSEKMSKeyId"] == "arn:aws:kms:eu-central-1:123456789012:key/storage-key"
    metadata = client.put_call["Metadata"]
    assert isinstance(metadata, dict)
    assert "tenant-audit" not in str(metadata)
    assert "collabio-tenant-sha256" in metadata


def test_boto3_audit_worm_store_fails_closed_on_readback_or_object_lock_drift() -> None:
    body = b"verified-bundle"
    readback_client = FakeAuditWormS3Client()
    readback_client.readback_override = b"tampered-bundle"
    with pytest.raises(AuditWormStorageError, match="readback hash"):
        object_store(readback_client).put_verified(request=write_request(body), body=body)

    lock_client = FakeAuditWormS3Client()
    lock_client.object_lock_mode = "GOVERNANCE"
    with pytest.raises(AuditWormStorageError, match="Object Lock"):
        object_store(lock_client).put_verified(request=write_request(body), body=body)


def test_boto3_audit_worm_store_rejects_body_hash_mismatch_before_provider_call() -> None:
    client = FakeAuditWormS3Client()
    request = write_request(b"expected")

    with pytest.raises(AuditWormStorageError, match="bundle hash"):
        object_store(client).put_verified(request=request, body=b"different")

    assert client.put_call == {}
