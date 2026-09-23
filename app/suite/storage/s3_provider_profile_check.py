from __future__ import annotations

import json
import os
from pathlib import Path

from suite.storage.adapter_policy import load_storage_adapter_policy
from suite.storage.s3_compatible_content_store import build_s3_compatible_provider_profile_evidence
from suite.storage.s3_sdk_client import build_boto3_s3_compatible_client, wait_for_s3_compatible_client


def main() -> None:
    storage_policy_path = Path(os.getenv("SUITE_STORAGE_POLICY_PATH", "docs/storage_adapter_policy.json"))
    storage_policy = load_storage_adapter_policy(storage_policy_path)
    client = build_boto3_s3_compatible_client(
        endpoint_url=os.getenv("SUITE_S3_ENDPOINT_URL"),
        access_key_id=_required_env("SUITE_S3_ACCESS_KEY_ID"),
        secret_access_key=_required_env("SUITE_S3_SECRET_ACCESS_KEY"),
        region_name=os.getenv("SUITE_S3_REGION", "us-east-1"),
        storage_provider=os.getenv("SUITE_S3_STORAGE_PROVIDER", "s3-compatible"),
    )
    if os.getenv("SUITE_S3_BOOTSTRAP_BUCKETS", "0") == "1":
        wait_for_s3_compatible_client(
            client=client,
            storage_policy=storage_policy,
            retries=int(os.getenv("SUITE_S3_PROFILE_CHECK_RETRIES", "30")),
            delay_seconds=float(os.getenv("SUITE_S3_PROFILE_CHECK_DELAY_SECONDS", "1")),
        )
    evidence = build_s3_compatible_provider_profile_evidence(
        client=client,
        storage_policy=storage_policy,
        provider_profile_id=os.getenv("SUITE_S3_PROVIDER_PROFILE_ID", "s3-compatible-provider"),
    )
    print(json.dumps(evidence.model_dump(mode="json"), sort_keys=True))
    raise SystemExit(0 if evidence.provider_profile_ready else 2)


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise RuntimeError(f"{name} is required")
    return value


if __name__ == "__main__":
    main()
