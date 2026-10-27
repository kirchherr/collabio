from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import UserContext
from suite.platform.office_document_repository import PgOfficeDocumentRepository
from suite.platform.office_documents import OfficeDocumentCreateCommand, OfficeDocumentSaveCommand
from suite.platform.office_image_codec import png_from_pixels
from suite.platform.office_images import store_uploaded_image
from suite.platform.principal_store import PgPrincipalDirectory
from suite.storage.s3_sdk_client import Boto3S3CompatibleObjectStoreClient
from suite.testing.work_e2e_guard import WORK_E2E_TENANT_ID, require_isolated_work_e2e_environment
from work_e2e_controls import WORK_E2E_OFFICE_EDITOR_ID
from work_e2e_office import build_synthetic_office_service

FIGURE_RECOVERY_TITLE = "Synthetic figure recovery"
FIGURE_RECOVERY_VERSION_COUNT = 5
OVERVIEW_FIGURE_ID = "figure-111111111111111111111111"
DETAILS_FIGURE_ID = "figure-222222222222222222222222"


def _paragraph(*, referenced: bool) -> dict[str, Any]:
    text: dict[str, Any] = {"type": "text", "text": "See details"}
    if referenced:
        text["marks"] = [{"type": "crossReference", "attrs": {"targetId": DETAILS_FIGURE_ID}}]
    return {"type": "paragraph", "content": [text]}


def figure_recovery_document(number: int, images: Sequence[dict[str, Any]] = ()) -> dict[str, Any]:
    """Build legacy, add, reorder, broken-target and reset fixture versions."""
    if not 1 <= number <= FIGURE_RECOVERY_VERSION_COUNT:
        raise ValueError("Synthetic figure version is outside the fixture")
    if number == 1:
        return {"type": "doc", "content": [_paragraph(referenced=False)]}
    if len(images) != 2:
        raise ValueError("Synthetic figure versions require two owned images")
    overview, details = deepcopy(images[0]), deepcopy(images[1])
    overview.update({"alt": "Overview sample", "caption": "Overview", "decorative": False})
    details.update({"alt": "Details sample", "caption": "Details", "decorative": False})
    if number == 5:
        return {
            "type": "doc",
            "content": [
                _paragraph(referenced=False),
                {"type": "image", "attrs": overview},
                {"type": "image", "attrs": details},
            ],
        }
    overview["figureId"] = OVERVIEW_FIGURE_ID
    details["figureId"] = DETAILS_FIGURE_ID
    order = [overview, details] if number == 2 else [details, overview] if number == 3 else [overview]
    return {
        "type": "doc",
        "content": [_paragraph(referenced=True), *({"type": "image", "attrs": attrs} for attrs in order)],
    }


def seed_synthetic_office_figures(
    *, environment: Mapping[str, str], client: Boto3S3CompatibleObjectStoreClient
) -> tuple[int, int]:
    """Persist the exact legacy/add/reorder/broken/reset sequence with owned pixels."""
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

    fields: dict[str, Any] = {
        "title": FIGURE_RECOVERY_TITLE,
        "document": figure_recovery_document(1),
        "mutation_reference": "work-e2e-figure-recovery-1",
        "human_confirmation": True,
    }
    saved = service.create(user_context=editor(), write_enabled=True, command=OfficeDocumentCreateCommand(**fields))
    user = editor()
    repository = service.repository
    if not isinstance(repository, PgOfficeDocumentRepository):
        raise RuntimeError("Synthetic figure recovery requires PostgreSQL Office storage")
    images = (
        store_uploaded_image(
            repository, user, saved.document.object_id, png_from_pixels(1, 1, b"\x25\x63\xeb\xff"), 1, 1
        ),
        store_uploaded_image(
            repository, user, saved.document.object_id, png_from_pixels(1, 1, b"\xf9\x73\x16\xff"), 1, 1
        ),
    )
    for number in range(2, FIGURE_RECOVERY_VERSION_COUNT + 1):
        saved = service.save(
            user_context=editor(),
            object_id=saved.document.object_id,
            write_enabled=True,
            command=OfficeDocumentSaveCommand(
                title=FIGURE_RECOVERY_TITLE,
                document=figure_recovery_document(number, images),
                mutation_reference=f"work-e2e-figure-recovery-{number}",
                human_confirmation=True,
                expected_current_version_id=saved.version.version_id,
            ),
        )
    return 1, FIGURE_RECOVERY_VERSION_COUNT
