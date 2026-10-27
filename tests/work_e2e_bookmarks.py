from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import UserContext
from suite.platform.office_documents import OfficeDocumentCreateCommand, OfficeDocumentSaveCommand
from suite.platform.principal_store import PgPrincipalDirectory
from suite.storage.s3_sdk_client import Boto3S3CompatibleObjectStoreClient
from suite.testing.work_e2e_guard import WORK_E2E_TENANT_ID, require_isolated_work_e2e_environment
from work_e2e_controls import WORK_E2E_OFFICE_EDITOR_ID
from work_e2e_office import build_synthetic_office_service
from work_e2e_paragraph import paragraph_recovery_document

BOOKMARK_RECOVERY_TITLE = "Synthetic bookmark recovery"
BOOKMARK_RECOVERY_VERSION_COUNT = 5


def bookmark_recovery_document(number: int) -> dict[str, Any]:
    if not 1 <= number <= BOOKMARK_RECOVERY_VERSION_COUNT:
        raise ValueError("Synthetic bookmark version is outside the fixture")
    document = deepcopy(paragraph_recovery_document(1))
    paragraph = document["content"][1]
    text = paragraph["content"][0]
    if number in (2, 3):
        paragraph["content"].insert(
            0,
            {
                "type": "bookmark",
                "attrs": {
                    "id": "bookmark-overview",
                    "label": "Overview" if number == 2 else "Executive overview",
                },
            },
        )
    if number in (2, 3, 4):
        text["marks"].append({"type": "crossReference", "attrs": {"targetId": "bookmark-overview"}})
    return document


def seed_synthetic_office_bookmarks(
    *, environment: Mapping[str, str], client: Boto3S3CompatibleObjectStoreClient
) -> tuple[int, int]:
    """Persist legacy, target, rename, broken and reset versions through guarded PG/S3 commands."""
    require_isolated_work_e2e_environment(environment)
    database_dsn = environment["SUITE_DATABASE_DSN"]
    service = build_synthetic_office_service(database_dsn=database_dsn, client=client, audit=InMemoryAuditLogger())
    directory = PgPrincipalDirectory(database_dsn=database_dsn)
    saved = None
    for number in range(1, BOOKMARK_RECOVERY_VERSION_COUNT + 1):
        user = UserContext(
            tenant_id=WORK_E2E_TENANT_ID,
            user_id=WORK_E2E_OFFICE_EDITOR_ID,
            role_ids={"office-editor"},
            readable_object_ids=directory.readable_object_ids(
                tenant_id=WORK_E2E_TENANT_ID,
                user_id=WORK_E2E_OFFICE_EDITOR_ID,
                role_ids={"office-editor"},
                group_ids=set(),
            ),
        )
        fields: dict[str, Any] = {
            "title": BOOKMARK_RECOVERY_TITLE,
            "document": bookmark_recovery_document(number),
            "mutation_reference": f"work-e2e-bookmark-recovery-{number}",
            "human_confirmation": True,
        }
        if saved is None:
            saved = service.create(
                user_context=user,
                write_enabled=True,
                command=OfficeDocumentCreateCommand(**fields),
            )
        else:
            saved = service.save(
                user_context=user,
                object_id=saved.document.object_id,
                write_enabled=True,
                command=OfficeDocumentSaveCommand(**fields, expected_current_version_id=saved.version.version_id),
            )
    return 1, BOOKMARK_RECOVERY_VERSION_COUNT
