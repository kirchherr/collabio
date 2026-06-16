from pathlib import Path

from suite.storage.adapter_policy import ObjectLockMode, load_storage_adapter_policy
from suite.storage.s3_compatible_content_store import build_s3_compatible_provider_profile_evidence
from suite.storage.s3_sdk_client import Boto3S3CompatibleObjectStoreClient

REPO_ROOT = Path(__file__).resolve().parents[1]
STORAGE_POLICY_PATH = REPO_ROOT / "docs" / "storage_adapter_policy.json"


class FakeStreamingBody:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def read(self) -> bytes:
        return self.body


class FakeListObjectVersionsPaginator:
    def __init__(self, sdk_client: "FakeBoto3S3Client") -> None:
        self.sdk_client = sdk_client

    def paginate(self, **kwargs: object) -> tuple[dict[str, object], ...]:
        return (self.sdk_client.list_object_versions(**kwargs),)


class FakeBoto3S3Client:
    def __init__(self) -> None:
        self.buckets: dict[str, dict[str, object]] = {}
        self.objects: dict[tuple[str, str, str], dict[str, object]] = {}
        self.put_object_calls: list[dict[str, object]] = []
        self.version_counter = 0

    def create_bucket(self, **kwargs: object) -> dict[str, object]:
        bucket = str(kwargs["Bucket"])
        self.buckets.setdefault(
            bucket,
            {
                "versioning": False,
                "object_lock": bool(kwargs.get("ObjectLockEnabledForBucket")),
                "legal_hold": bool(kwargs.get("ObjectLockEnabledForBucket")),
            },
        )
        return {}

    def get_bucket_versioning(self, **kwargs: object) -> dict[str, object]:
        bucket = str(kwargs["Bucket"])
        return {"Status": "Enabled"} if self.buckets.get(bucket, {}).get("versioning") else {}

    def put_bucket_versioning(self, **kwargs: object) -> dict[str, object]:
        bucket = str(kwargs["Bucket"])
        self.buckets.setdefault(bucket, {})["versioning"] = True
        return {}

    def get_object_lock_configuration(self, **kwargs: object) -> dict[str, object]:
        bucket = str(kwargs["Bucket"])
        if not self.buckets.get(bucket, {}).get("object_lock"):
            raise RuntimeError("ObjectLockConfigurationNotFoundError")
        return {"ObjectLockConfiguration": {"ObjectLockEnabled": "Enabled"}}

    def put_object_lock_configuration(self, **kwargs: object) -> dict[str, object]:
        bucket = str(kwargs["Bucket"])
        self.buckets.setdefault(bucket, {})["object_lock"] = True
        self.buckets.setdefault(bucket, {})["legal_hold"] = True
        self.buckets.setdefault(bucket, {})["object_lock_configuration"] = kwargs["ObjectLockConfiguration"]
        return {}

    def put_object(self, **kwargs: object) -> dict[str, object]:
        self.version_counter += 1
        version_id = f"version-{self.version_counter}"
        bucket = str(kwargs["Bucket"])
        object_key = str(kwargs["Key"])
        body = kwargs["Body"]
        assert isinstance(body, bytes)
        metadata = kwargs.get("Metadata", {})
        assert isinstance(metadata, dict)
        self.objects[(bucket, object_key, version_id)] = {
            "Body": body,
            "Metadata": metadata,
            "LastModified": "2026-06-12T12:00:00Z",
        }
        self.put_object_calls.append(kwargs)
        return {"VersionId": version_id}

    def get_object(self, **kwargs: object) -> dict[str, object]:
        stored = self.objects[(str(kwargs["Bucket"]), str(kwargs["Key"]), str(kwargs["VersionId"]))]
        body = stored["Body"]
        assert isinstance(body, bytes)
        return {"Body": FakeStreamingBody(body)}

    def head_object(self, **kwargs: object) -> dict[str, object]:
        stored = self.objects[(str(kwargs["Bucket"]), str(kwargs["Key"]), str(kwargs["VersionId"]))]
        return {"Metadata": stored["Metadata"], "LastModified": stored["LastModified"]}

    def list_object_versions(self, **kwargs: object) -> dict[str, object]:
        bucket = str(kwargs["Bucket"])
        prefix = str(kwargs["Prefix"])
        versions: list[dict[str, str]] = []
        for stored_bucket, object_key, version_id in sorted(self.objects):
            if stored_bucket == bucket and object_key.startswith(prefix):
                versions.append(
                    {
                        "Key": object_key,
                        "VersionId": version_id,
                        "LastModified": "2026-06-12T12:00:00Z",
                    }
                )
        return {"Versions": versions}

    def get_paginator(self, operation_name: str) -> FakeListObjectVersionsPaginator:
        assert operation_name == "list_object_versions"
        return FakeListObjectVersionsPaginator(self)


def test_boto3_s3_compatible_client_bootstraps_bucket_profiles_and_builds_provider_evidence() -> None:
    sdk_client = FakeBoto3S3Client()
    client = Boto3S3CompatibleObjectStoreClient(
        sdk_client=sdk_client,
        storage_provider="minio",
        stored_at_clock=lambda: "2026-06-12T12:00:00Z",
    )
    storage_policy = load_storage_adapter_policy(STORAGE_POLICY_PATH)

    client.ensure_bucket_profiles(storage_policy=storage_policy)
    evidence = build_s3_compatible_provider_profile_evidence(
        client=client,
        storage_policy=storage_policy,
        provider_profile_id="minio-compose",
        checked_at_utc="2026-06-12T12:00:01Z",
    )

    assert evidence.provider_profile_ready is True
    assert evidence.storage_provider == "s3-compatible"
    assert evidence.bucket_profile_count == 4
    assert evidence.object_lock_bucket_count == 2
    assert sdk_client.buckets["business-records"]["object_lock"] is True
    assert sdk_client.buckets["evidence-records"]["object_lock"] is True


def test_boto3_s3_compatible_client_put_get_and_list_versions() -> None:
    sdk_client = FakeBoto3S3Client()
    client = Boto3S3CompatibleObjectStoreClient(
        sdk_client=sdk_client,
        storage_provider="minio",
        stored_at_clock=lambda: "2026-06-12T12:00:00Z",
    )
    sdk_client.create_bucket(Bucket="business-records", ObjectLockEnabledForBucket=True)
    sdk_client.put_bucket_versioning(Bucket="business-records", VersioningConfiguration={"Status": "Enabled"})
    sdk_client.put_object_lock_configuration(
        Bucket="business-records",
        ObjectLockConfiguration={"ObjectLockEnabled": "Enabled"},
    )

    result = client.put_object(
        bucket_id="business-records",
        object_key="tenant-1/wiki/object-1/v1/content",
        body=b"hello",
        metadata={
            "tenant_id": "tenant-1",
            "object_id": "object-1",
            "version_id": "v1",
            "content_hash": "sha256:" + "a" * 64,
            "content_byte_length": "5",
        },
        object_lock_mode=ObjectLockMode.COMPLIANCE,
        legal_hold=True,
    )
    listed = client.list_object_versions(bucket_id="business-records", prefix="tenant-1/")

    assert result.object_version_id == "version-1"
    assert client.get_object(bucket_id="business-records", object_key=result.object_key, object_version_id="version-1")
    assert listed[0].metadata["tenant_id"] == "tenant-1"
    assert listed[0].metadata["object_id"] == "object-1"
    assert sdk_client.put_object_calls[0]["ObjectLockLegalHoldStatus"] == "ON"
    metadata = sdk_client.put_object_calls[0]["Metadata"]
    assert isinstance(metadata, dict)
    assert metadata["collabio-object-lock-mode"] == "compliance"
