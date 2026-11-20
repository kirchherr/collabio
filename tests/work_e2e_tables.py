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

TABLE_RECOVERY_TITLE = "Synthetic table caption recovery"
TABLE_RECOVERY_VERSION_COUNT = 5
OVERVIEW_TABLE_ID = "table-111111111111111111111111"
DETAILS_TABLE_ID = "table-222222222222222222222222"


def _paragraph(*, referenced: bool) -> dict[str, Any]:
    text: dict[str, Any] = {"type": "text", "text": "See details table"}
    if referenced:
        text["marks"] = [{"type": "crossReference", "attrs": {"targetId": DETAILS_TABLE_ID}}]
    return {"type": "paragraph", "content": [text]}


def _table(text: str, *, identifier: str | None = None, caption: str | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {
        "type": "table",
        "content": [
            {
                "type": "tableRow",
                "content": [
                    {
                        "type": "tableCell",
                        "attrs": {"colspan": 1, "rowspan": 1},
                        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
                    }
                ],
            }
        ],
    }
    if identifier is not None and caption is not None:
        value["attrs"] = {"tableId": identifier, "caption": caption}
    return value


def table_recovery_document(number: int) -> dict[str, Any]:
    """Build legacy, add, reorder, broken-target and reset fixture versions."""
    if not 1 <= number <= TABLE_RECOVERY_VERSION_COUNT:
        raise ValueError("Synthetic table caption version is outside the fixture")
    legacy = number in {1, 5}
    overview = _table("Overview value", **({} if legacy else {"identifier": OVERVIEW_TABLE_ID, "caption": "Overview"}))
    details = _table("Details value", **({} if legacy else {"identifier": DETAILS_TABLE_ID, "caption": "Details"}))
    if number in {1, 2, 5}:
        tables = [overview, details]
    elif number == 3:
        tables = [details, overview]
    else:
        tables = [overview]
    return {"type": "doc", "content": [_paragraph(referenced=number in {2, 3, 4}), *tables]}


def seed_synthetic_office_tables(
    *, environment: Mapping[str, str], client: Boto3S3CompatibleObjectStoreClient
) -> tuple[int, int]:
    """Persist the exact legacy/add/reorder/broken/reset table-caption sequence."""
    require_isolated_work_e2e_environment(environment)
    database_dsn = environment["SUITE_DATABASE_DSN"]
    service = build_synthetic_office_service(database_dsn=database_dsn, client=client, audit=InMemoryAuditLogger())
    directory = PgPrincipalDirectory(database_dsn=database_dsn)

    def editor() -> UserContext:
        return UserContext(
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

    saved = service.create(
        user_context=editor(),
        write_enabled=True,
        command=OfficeDocumentCreateCommand(
            title=TABLE_RECOVERY_TITLE,
            document=table_recovery_document(1),
            mutation_reference="work-e2e-table-caption-recovery-1",
            human_confirmation=True,
        ),
    )
    for number in range(2, TABLE_RECOVERY_VERSION_COUNT + 1):
        saved = service.save(
            user_context=editor(),
            object_id=saved.document.object_id,
            write_enabled=True,
            command=OfficeDocumentSaveCommand(
                title=TABLE_RECOVERY_TITLE,
                document=deepcopy(table_recovery_document(number)),
                mutation_reference=f"work-e2e-table-caption-recovery-{number}",
                human_confirmation=True,
                expected_current_version_id=saved.version.version_id,
            ),
        )
    return 1, TABLE_RECOVERY_VERSION_COUNT
