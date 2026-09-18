from __future__ import annotations

from typing import Any

import psycopg
from psycopg import sql

from suite.platform.crm_accounts import CrmAccountRecord
from suite.platform.crm_activities import CrmActivityRecord, CrmActivityType, CrmNoteRecord
from suite.platform.crm_contacts import CrmContactRecord
from suite.testing.work_e2e_guard import WORK_E2E_TENANT_ID
from work_e2e_controls import WORK_E2E_CRM_OBJECT_TYPES, WORK_E2E_READER_ID

CrmFixtureRecord = CrmAccountRecord | CrmContactRecord | CrmActivityRecord | CrmNoteRecord


def synthetic_crm_records() -> tuple[CrmFixtureRecord, ...]:
    common: dict[str, Any] = {
        "tenant_id": WORK_E2E_TENANT_ID,
        "owner_principal_id": "work-user-e2e",
        "created_by": "work-user-e2e",
        "created_at_utc": "2026-09-18T08:00:00Z",
        "updated_at_utc": "2026-09-18T08:00:00Z",
        "kms_key_ref": "kms:work-e2e-synthetic-crm",
        "audit_chain_ref": "audit:work-e2e-synthetic-crm",
    }
    main_account = "crm-account-work-e2e-main"
    other_account = "crm-account-work-e2e-other"
    main_contact = "crm-contact-work-e2e-main"
    hidden_contact = "crm-contact-work-e2e-hidden"
    return (
        CrmAccountRecord(
            **common,
            object_id=main_account,
            account_number="CRM-E2E-MAIN",
            display_name="Synthetic E2E CRM account <script>window.crmUnsafe=true</script>",
        ),
        CrmAccountRecord(
            **common,
            object_id=other_account,
            account_number="CRM-E2E-OTHER",
            display_name="Synthetic other CRM account",
        ),
        CrmAccountRecord(
            **common,
            object_id="crm-account-work-e2e-empty",
            account_number="CRM-E2E-EMPTY",
            display_name="Synthetic empty CRM account",
        ),
        CrmAccountRecord(
            **common,
            object_id="crm-account-work-e2e-hidden",
            account_number="CRM-E2E-HIDDEN",
            display_name="Synthetic hidden CRM account",
        ),
        CrmContactRecord(
            **common,
            object_id=main_contact,
            account_object_id=main_account,
            contact_number="CRM-E2E-CONTACT",
            display_name=(
                "Synthetic CRM reader contact <img src=https://outside.invalid/x onerror=window.crmUnsafe=true>"
            ),
            primary_email="synthetic.crm@work-e2e.invalid",
            primary_phone="+49 000 0000",
            role_label="Synthetic reviewer",
        ),
        CrmContactRecord(
            **common,
            object_id=hidden_contact,
            account_object_id=main_account,
            display_name="Synthetic hidden CRM contact",
        ),
        CrmContactRecord(
            **common,
            object_id="crm-contact-work-e2e-other",
            account_object_id=other_account,
            display_name="Synthetic other CRM contact",
        ),
        CrmActivityRecord(
            **common,
            object_id="crm-activity-work-e2e-main",
            account_object_id=main_account,
            contact_object_id=main_contact,
            activity_number="CRM-E2E-ACTIVITY",
            activity_type=CrmActivityType.MEETING,
            subject="Synthetic CRM meeting <script>window.crmUnsafe=true</script>",
            due_at_utc="2026-09-19T09:00:00Z",
        ),
        CrmActivityRecord(
            **common,
            object_id="crm-activity-work-e2e-linked",
            contact_object_id=main_contact,
            activity_type=CrmActivityType.CALL,
            subject="Synthetic contact-linked CRM call",
            due_at_utc="2026-09-20T09:00:00Z",
        ),
        CrmActivityRecord(
            **common,
            object_id="crm-activity-work-e2e-redacted",
            account_object_id=main_account,
            contact_object_id=hidden_contact,
            activity_type=CrmActivityType.FOLLOW_UP,
            subject="Synthetic CRM redacted relation",
            due_at_utc="2026-09-21T09:00:00Z",
        ),
        CrmActivityRecord(
            **common,
            object_id="crm-activity-work-e2e-hidden",
            account_object_id=main_account,
            activity_type=CrmActivityType.EMAIL,
            subject="Synthetic hidden CRM activity",
        ),
        CrmActivityRecord(
            **common,
            object_id="crm-activity-work-e2e-other",
            account_object_id=other_account,
            contact_object_id="crm-contact-work-e2e-other",
            activity_type=CrmActivityType.TASK,
            subject="Synthetic other CRM activity",
        ),
        CrmNoteRecord(
            **common,
            object_id="crm-note-work-e2e-main",
            account_object_id=main_account,
            contact_object_id=hidden_contact,
            activity_object_id="crm-activity-work-e2e-hidden",
            title="Synthetic CRM note metadata only",
        ),
    )


def seed_synthetic_crm_records(connection: psycopg.Connection[Any]) -> int:
    records = synthetic_crm_records()
    table_by_type = {
        "crm.account": "accounts",
        "crm.contact": "contacts",
        "crm.activity": "activities",
        "crm.note": "notes",
    }
    connection.execute("SELECT set_config('app.tenant_id', %s, true)", (WORK_E2E_TENANT_ID,))
    for record in records:
        if (
            record.tenant_id != WORK_E2E_TENANT_ID
            or WORK_E2E_CRM_OBJECT_TYPES.get(record.object_id) != record.object_type
        ):
            raise RuntimeError("Outside synthetic CRM fixture")
        values = record.model_dump(mode="json")
        connection.execute(
            sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                sql.Identifier("crm", table_by_type[record.object_type]),
                sql.SQL(", ").join(sql.Identifier(column) for column in values),
                sql.SQL(", ").join(sql.Placeholder() for _ in values),
            ),
            tuple(values.values()),
        )
        if "-hidden" not in record.object_id:
            connection.execute(
                """
                INSERT INTO collabio.object_acl_entries (
                    tenant_id, object_id, object_type, acl_subject_type, acl_subject_id,
                    permission, acl_version, status, audit_chain_ref
                ) VALUES (%s, %s, %s, 'user', %s, 'read', 1, 'active', %s)
                """,
                (
                    WORK_E2E_TENANT_ID,
                    record.object_id,
                    record.object_type,
                    WORK_E2E_READER_ID,
                    "audit:work-e2e-synthetic-crm-acl",
                ),
            )
    return len(records)
