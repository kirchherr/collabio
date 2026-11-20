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

LINK_RECOVERY_TITLE = "Synthetic link recovery"
LINK_RECOVERY_VERSION_COUNT = 4


def link_recovery_document(number: int) -> dict[str, Any]:
    if not 1 <= number <= LINK_RECOVERY_VERSION_COUNT:
        raise ValueError("Synthetic link version is outside the fixture")
    document = deepcopy(paragraph_recovery_document(1))
    text = document["content"][1]["content"][0]
    if number == 2:
        text["marks"].append({"type": "link", "attrs": {"href": "https://example.org/office/reference"}})
    elif number == 3:
        text["marks"].append({"type": "link", "attrs": {"href": "mailto:office@example.org"}})
    return document


def seed_synthetic_office_links(
    *, environment: Mapping[str, str], client: Boto3S3CompatibleObjectStoreClient
) -> tuple[int, int]:
    """Persist legacy, HTTPS, mail and reset link versions through guarded PG/S3 commands."""
    require_isolated_work_e2e_environment(environment)
    database_dsn = environment["SUITE_DATABASE_DSN"]
    service = build_synthetic_office_service(database_dsn=database_dsn, client=client, audit=InMemoryAuditLogger())
    directory = PgPrincipalDirectory(database_dsn=database_dsn)
    saved = None
    for number in range(1, LINK_RECOVERY_VERSION_COUNT + 1):
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
            "title": LINK_RECOVERY_TITLE,
            "document": link_recovery_document(number),
            "mutation_reference": f"work-e2e-link-recovery-{number}",
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
                command=OfficeDocumentSaveCommand(
                    **fields,
                    expected_current_version_id=saved.version.version_id,
                ),
            )
    return 1, LINK_RECOVERY_VERSION_COUNT
