from __future__ import annotations

import re

from suite.testing.work_e2e_guard import WORK_E2E_TENANT_ID

WORK_E2E_READER_ID = "work-reader-e2e"
WORK_E2E_CRM_OBJECT_TYPES = {
    "crm-account-work-e2e-main": "crm.account",
    "crm-account-work-e2e-other": "crm.account",
    "crm-account-work-e2e-empty": "crm.account",
    "crm-account-work-e2e-hidden": "crm.account",
    "crm-contact-work-e2e-main": "crm.contact",
    "crm-contact-work-e2e-hidden": "crm.contact",
    "crm-contact-work-e2e-other": "crm.contact",
    "crm-activity-work-e2e-main": "crm.activity",
    "crm-activity-work-e2e-linked": "crm.activity",
    "crm-activity-work-e2e-redacted": "crm.activity",
    "crm-activity-work-e2e-hidden": "crm.activity",
    "crm-activity-work-e2e-other": "crm.activity",
    "crm-note-work-e2e-main": "crm.note",
}


def crm_failure_requested(*, tenant_id: str | None, method: str, path: str, requested: bool) -> bool:
    return (
        tenant_id == WORK_E2E_TENANT_ID
        and method == "GET"
        and requested
        and re.fullmatch(r"/v1/crm/accounts/[^/]+/workspace", path) is not None
    )


def permits_crm_reader_acl_fixture(
    *, tenant_id: str, object_id: str, object_type: str, subject_type: str, subject_id: str, permission: str
) -> bool:
    return (
        tenant_id == WORK_E2E_TENANT_ID
        and WORK_E2E_CRM_OBJECT_TYPES.get(object_id) == object_type
        and subject_type == "user"
        and subject_id == WORK_E2E_READER_ID
        and permission == "read"
    )


def storage_failure_modes(
    *, tenant_id: str | None, method: str, path: str, requested: bool, allow_synthetic_traffic: bool
) -> tuple[bool, bool]:
    if tenant_id != WORK_E2E_TENANT_ID or not requested:
        return False, False
    return (
        allow_synthetic_traffic and method == "POST" and path == "/v1/admin/kb/articles/write-approvals/execute",
        method == "GET" and re.fullmatch(r"/v1/kb/articles/[^/]+/content", path) is not None,
    )


def permits_reader_acl_fixture(
    *, tenant_id: str, object_id: str, object_type: str, subject_type: str, subject_id: str, permission: str
) -> bool:
    prefixes = {"kb.article": "kb-article-", "kb.article_version": "kb-article-version-"}
    prefix = prefixes.get(object_type)
    return (
        tenant_id == WORK_E2E_TENANT_ID
        and prefix is not None
        and re.fullmatch(re.escape(prefix) + r"[a-f0-9]{32}", object_id) is not None
        and subject_type == "user"
        and subject_id == WORK_E2E_READER_ID
        and permission == "read"
    )
