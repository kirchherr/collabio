from __future__ import annotations

import json
import os

import psycopg

from suite.testing.work_e2e_guard import WORK_E2E_TENANT_ID, require_isolated_work_e2e_environment

SYNTHETIC_PRINCIPALS = (
    "work-user-e2e",
    "work-approver-e2e",
    "work-assignee-e2e",
)


def main() -> int:
    require_isolated_work_e2e_environment(os.environ)
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
