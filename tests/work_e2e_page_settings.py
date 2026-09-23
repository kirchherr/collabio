from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import UserContext
from suite.platform.office_documents import OfficeDocumentCreateCommand, OfficeDocumentSaveCommand
from suite.platform.principal_store import PgPrincipalDirectory
from suite.storage.s3_sdk_client import Boto3S3CompatibleObjectStoreClient
from suite.testing.work_e2e_guard import WORK_E2E_TENANT_ID, require_isolated_work_e2e_environment
from work_e2e_controls import WORK_E2E_OFFICE_EDITOR_ID
from work_e2e_office import build_synthetic_office_service
from work_e2e_page_breaks import page_break_recovery_document

PAGE_SETTINGS_RECOVERY_TITLE = "Synthetic page settings recovery"


def page_settings_recovery_document(number: int) -> dict[str, Any]:
    if number not in (1, 2, 3, 4):
        raise ValueError("Synthetic page settings version is outside the fixture")
    document = page_break_recovery_document(2)
    if number in (2, 3):
        document["attrs"] = {"page": {
            "paper": "letter" if number == 2 else "a4",
            "orientation": "landscape" if number == 2 else "portrait",
            "margins": {"top": 12, "right": 25, "bottom": 30, "left": 40} if number == 2 else
                       {"top": 5, "right": 50, "bottom": 50, "left": 5},
        }}
    return document


def seed_synthetic_office_page_settings(
    *, environment: Mapping[str, str], client: Boto3S3CompatibleObjectStoreClient
) -> tuple[int, int]:
    require_isolated_work_e2e_environment(environment)
    dsn = environment["SUITE_DATABASE_DSN"]
    service = build_synthetic_office_service(database_dsn=dsn, client=client, audit=InMemoryAuditLogger())
    directory = PgPrincipalDirectory(database_dsn=dsn)
    user = UserContext(tenant_id=WORK_E2E_TENANT_ID, user_id=WORK_E2E_OFFICE_EDITOR_ID, role_ids={"office-editor"})
    saved = None
    for number in (1, 2, 3, 4):
        user.readable_object_ids = directory.readable_object_ids(
            tenant_id=user.tenant_id, user_id=user.user_id, role_ids=user.role_ids, group_ids=set()
        )
        fields: dict[str, Any] = dict(
            title=PAGE_SETTINGS_RECOVERY_TITLE,
            document=page_settings_recovery_document(number),
            mutation_reference=f"work-e2e-page-settings-recovery-{number}",
            human_confirmation=True,
        )
        if saved is None:
            saved = service.create(user_context=user, write_enabled=True, command=OfficeDocumentCreateCommand(**fields))
        else:
            saved = service.save(
                user_context=user,
                object_id=saved.document.object_id,
                write_enabled=True,
                command=OfficeDocumentSaveCommand(**fields, expected_current_version_id=saved.version.version_id),
            )
    return 1, 4
