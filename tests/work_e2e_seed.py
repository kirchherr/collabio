from __future__ import annotations

import json
import os
from pathlib import Path

import psycopg

from suite.storage.adapter_policy import load_storage_adapter_policy
from suite.storage.s3_sdk_client import build_boto3_s3_compatible_client, wait_for_s3_compatible_client
from suite.testing.work_e2e_guard import WORK_E2E_TENANT_ID, require_isolated_work_e2e_environment
from work_e2e_controls import WORK_E2E_READER_ID

SYNTHETIC_PRINCIPALS = (
    "work-user-e2e",
    "work-approver-e2e",
    "work-assignee-e2e",
    WORK_E2E_READER_ID,
)


def main() -> int:
    require_isolated_work_e2e_environment(os.environ)
    client = build_boto3_s3_compatible_client(
        endpoint_url=os.environ["SUITE_S3_ENDPOINT_URL"],
        access_key_id=os.environ["SUITE_S3_ACCESS_KEY_ID"],
        secret_access_key=os.environ["SUITE_S3_SECRET_ACCESS_KEY"],
        storage_provider="minio",
    )
    wait_for_s3_compatible_client(
        client=client,
        storage_policy=load_storage_adapter_policy(Path("/workspace/docs/storage_adapter_policy.json")),
    )
    database_dsn = os.environ["SUITE_MIGRATION_DATABASE_DSN"]
    with psycopg.connect(database_dsn) as connection:
        for user_id in SYNTHETIC_PRINCIPALS:
            issuer = f"https://work-e2e.invalid/{user_id}"
            subject = f"subject-{user_id}"
            connection.execute(
                """
                INSERT INTO collabio.tenant_principals (
                    tenant_id, issuer, subject, user_id, display_name, audit_chain_ref
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    WORK_E2E_TENANT_ID,
                    issuer,
                    subject,
                    user_id,
                    "Synthetic Work E2E Principal",
                    f"audit:work-e2e-principal:{user_id}",
                ),
            )
            connection.execute(
                """
                INSERT INTO collabio.tenant_principal_memberships (
                    tenant_id, issuer, subject, audit_chain_ref
                ) VALUES (%s, %s, %s, %s)
                """,
                (
                    WORK_E2E_TENANT_ID,
                    issuer,
                    subject,
                    f"audit:work-e2e-membership:{user_id}",
                ),
            )

    print(
        json.dumps(
            {
                "schema_version": "work_e2e_seed.v1",
                "tenant_id": WORK_E2E_TENANT_ID,
                "principal_count": len(SYNTHETIC_PRINCIPALS),
                "tenant_content_included": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
