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

SECTION_RECOVERY_TITLE = "Synthetic section recovery"


def _section_profile(*, paper: str, orientation: str, columns: str, header: str) -> dict[str, Any]:
    return {
        "page": {
            "paper": paper,
            "orientation": orientation,
            "columns": columns,
            "margins": {"top": 20, "right": 16, "bottom": 22, "left": 18},
        },
        "running": {"header": header, "footer": "Internal", "numbering": "pageOfPages"},
    }


def section_recovery_document(number: int) -> dict[str, Any]:
    if number not in (1, 2, 3, 4):
        raise ValueError("Synthetic section version is outside the fixture")
    document = deepcopy(paragraph_recovery_document(1))
    if number in (2, 3):
        document["content"].insert(
            1,
            {
                "type": "sectionBreak",
                "attrs": _section_profile(paper="letter", orientation="landscape", columns="two", header="Appendix"),
            },
        )
    if number == 3:
        document["content"].insert(
            4,
            {
                "type": "sectionBreak",
                "attrs": _section_profile(paper="a4", orientation="portrait", columns="three", header="Annex"),
            },
        )
    return document


def seed_synthetic_office_sections(
    *, environment: Mapping[str, str], client: Boto3S3CompatibleObjectStoreClient
) -> tuple[int, int]:
    require_isolated_work_e2e_environment(environment)
    database_dsn = environment["SUITE_DATABASE_DSN"]
    service = build_synthetic_office_service(database_dsn=database_dsn, client=client, audit=InMemoryAuditLogger())
    directory = PgPrincipalDirectory(database_dsn=database_dsn)
    user = UserContext(
        tenant_id=WORK_E2E_TENANT_ID,
        user_id=WORK_E2E_OFFICE_EDITOR_ID,
        role_ids={"office-editor"},
    )
    saved = None
    for number in (1, 2, 3, 4):
        user.readable_object_ids = directory.readable_object_ids(
            tenant_id=user.tenant_id,
            user_id=user.user_id,
            role_ids=user.role_ids,
            group_ids=set(),
        )
        fields: dict[str, Any] = {
            "title": SECTION_RECOVERY_TITLE,
            "document": section_recovery_document(number),
            "mutation_reference": f"work-e2e-section-recovery-{number}",
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
    return 1, 4
