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

PARAGRAPH_RECOVERY_TITLE = "Synthetic paragraph recovery"
PARAGRAPH_RECOVERY_VERSION_COUNT = 3
PARAGRAPH_RECOVERY_PROFILES: tuple[dict[str, str | int], ...] = (
    {},
    {"textAlign": "center", "lineSpacing": "1.5", "spacingBefore": 6, "spacingAfter": 12},
    {"textAlign": "justify", "lineSpacing": "2", "spacingBefore": 18, "spacingAfter": 24},
)


def paragraph_recovery_document(number: int) -> dict[str, Any]:
    if not 1 <= number <= PARAGRAPH_RECOVERY_VERSION_COUNT:
        raise ValueError("Synthetic paragraph version is outside the fixture")
    formatting = PARAGRAPH_RECOVERY_PROFILES[number - 1]

    def paragraph(text: str) -> dict[str, Any]:
        return {
            "type": "paragraph",
            **({"attrs": dict(formatting)} if formatting else {}),
            "content": [{"type": "text", "text": text, "marks": [{"type": "bold"}]}],
        }

    return {
        "type": "doc",
        "content": [
            {
                "type": "heading",
                "attrs": {"level": 2, **formatting},
                "content": [{"type": "text", "text": "Paragraph recovery Café 😀"}],
            },
            paragraph("Literal <img src=x> paragraph recovery text"),
            {"type": "bulletList", "content": [{"type": "listItem", "content": [paragraph("List paragraph")]}]},
            {"type": "blockquote", "content": [paragraph("Quoted paragraph")]},
            {
                "type": "table",
                "content": [
                    {
                        "type": "tableRow",
                        "content": [
                            {
                                "type": "tableCell",
                                "attrs": {"colspan": 1, "rowspan": 1},
                                "content": [paragraph("Cell paragraph")],
                            }
                        ],
                    }
                ],
            },
        ],
    }


def seed_synthetic_office_paragraphs(
    *, environment: Mapping[str, str], client: Boto3S3CompatibleObjectStoreClient
) -> tuple[int, int]:
    """Persist legacy and formatted sources through real guarded PG/S3 commands."""
    require_isolated_work_e2e_environment(environment)
    database_dsn = environment["SUITE_DATABASE_DSN"]
    service = build_synthetic_office_service(database_dsn=database_dsn, client=client, audit=InMemoryAuditLogger())
    directory = PgPrincipalDirectory(database_dsn=database_dsn)

    def author() -> UserContext:
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
        user_context=author(),
        command=OfficeDocumentCreateCommand(
            title=PARAGRAPH_RECOVERY_TITLE,
            document=paragraph_recovery_document(1),
            mutation_reference="work-e2e-paragraph-recovery-1",
            human_confirmation=True,
        ),
        write_enabled=True,
    )
    for number in range(2, PARAGRAPH_RECOVERY_VERSION_COUNT + 1):
        saved = service.save(
            user_context=author(),
            object_id=saved.document.object_id,
            command=OfficeDocumentSaveCommand(
                title=PARAGRAPH_RECOVERY_TITLE,
                document=paragraph_recovery_document(number),
                expected_current_version_id=saved.version.version_id,
                mutation_reference=f"work-e2e-paragraph-recovery-{number}",
                human_confirmation=True,
            ),
            write_enabled=True,
        )
    return 1, PARAGRAPH_RECOVERY_VERSION_COUNT
