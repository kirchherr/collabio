from __future__ import annotations

import json
import os
from pathlib import Path

import psycopg

from suite.storage.adapter_policy import load_storage_adapter_policy
from suite.storage.s3_sdk_client import build_boto3_s3_compatible_client, wait_for_s3_compatible_client
from suite.testing.work_e2e_guard import WORK_E2E_TENANT_ID, require_isolated_work_e2e_environment
from work_e2e_controls import WORK_E2E_OFFICE_EDITOR_ID, WORK_E2E_READER_ID
from work_e2e_crm import seed_synthetic_crm_records
from work_e2e_discovery import DISCOVERY_EDITOR_ID, DISCOVERY_READER_ID, seed_synthetic_office_discovery
from work_e2e_history import HISTORY_EDITOR_ID, HISTORY_READER_ID, seed_synthetic_office_history
from work_e2e_paragraph import seed_synthetic_office_paragraphs

SYNTHETIC_PRINCIPALS = (
    "work-user-e2e",
    "work-approver-e2e",
    "work-assignee-e2e",
    WORK_E2E_READER_ID,
    WORK_E2E_OFFICE_EDITOR_ID,
    DISCOVERY_EDITOR_ID,
    DISCOVERY_READER_ID,
    HISTORY_EDITOR_ID,
    HISTORY_READER_ID,
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

        crm_record_count = seed_synthetic_crm_records(connection)

    office_document_count = seed_synthetic_office_discovery(environment=os.environ, client=client)
    history_document_count, history_version_count = seed_synthetic_office_history(environment=os.environ, client=client)
    paragraph_document_count, paragraph_version_count = seed_synthetic_office_paragraphs(
        environment=os.environ, client=client
    )

    print(
        json.dumps(
            {
                "schema_version": "work_e2e_seed.v1",
                "tenant_id": WORK_E2E_TENANT_ID,
                "principal_count": len(SYNTHETIC_PRINCIPALS),
                "synthetic_crm_record_count": crm_record_count,
                "synthetic_office_document_count": office_document_count
                + history_document_count
                + paragraph_document_count,
                "synthetic_office_history_version_count": history_version_count,
                "synthetic_office_paragraph_version_count": paragraph_version_count,
                "tenant_content_included": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
