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

SEMANTIC_RECOVERY_TITLE = "Synthetic semantic structures recovery"
SEMANTIC_RECOVERY_VERSION_COUNT = 10
FIELD = {"key": "project", "label": "Project", "value": "Apollo"}
SOURCE = {
    "id": "source-111111111111111111111111",
    "author": "Ada Lovelace",
    "title": "Notes",
    "year": "1843",
    "locator": "Archive",
}


def semantic_recovery_document(number: int) -> dict[str, Any]:
    """Build legacy then additive field, navigation, note, source, formula, broken and reset versions."""
    if not 1 <= number <= SEMANTIC_RECOVERY_VERSION_COUNT:
        raise ValueError("Synthetic semantic version is outside the fixture")
    if number in {1, 10}:
        return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Legacy"}]}]}
    attrs: dict[str, Any] = {"documentFields": [deepcopy(FIELD)]}
    content: list[dict[str, Any]] = [
        {"type": "heading", "attrs": {"level": 1}, "content": [{"type": "text", "text": "Overview"}]},
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": "Project "}, {"type": "documentField", "attrs": {"key": "project"}}],
        },
    ]
    if number >= 3:
        content.insert(0, {"type": "tableOfContents", "attrs": {"maxLevel": 3}})
    paragraph = content[2 if number >= 3 else 1]
    if number >= 4:
        paragraph["content"].append(
            {
                "type": "noteReference",
                "attrs": {"id": "note-222222222222222222222222", "kind": "footnote", "text": "Primary evidence"},
            }
        )
    if number >= 5:
        paragraph["content"].append(
            {
                "type": "noteReference",
                "attrs": {"id": "note-333333333333333333333333", "kind": "endnote", "text": "Closing evidence"},
            }
        )
    if number >= 6:
        attrs["citationSources"] = [deepcopy(SOURCE)]
        paragraph["content"].append(
            {"type": "citationReference", "attrs": {"sourceId": SOURCE["id"], "locator": "p. 12"}}
        )
        content.append({"type": "bibliography"})
    if number >= 7:
        content.append(
            {
                "type": "equation",
                "attrs": {
                    "id": "equation-444444444444444444444444",
                    "source": "E = mc^2",
                    "alt": "Energy equals mass times light speed squared",
                },
            }
        )
    if number >= 8:
        content.append({"type": "referenceIndex"})
    if number == 9:
        attrs = {}
    return {"type": "doc", "attrs": attrs, "content": content}


def seed_synthetic_office_semantics(
    *, environment: Mapping[str, str], client: Boto3S3CompatibleObjectStoreClient
) -> tuple[int, int]:
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
            title=SEMANTIC_RECOVERY_TITLE,
            document=semantic_recovery_document(1),
            mutation_reference="work-e2e-semantic-recovery-1",
            human_confirmation=True,
        ),
    )
    for number in range(2, SEMANTIC_RECOVERY_VERSION_COUNT + 1):
        saved = service.save(
            user_context=editor(),
            object_id=saved.document.object_id,
            write_enabled=True,
            command=OfficeDocumentSaveCommand(
                title=SEMANTIC_RECOVERY_TITLE,
                document=deepcopy(semantic_recovery_document(number)),
                mutation_reference=f"work-e2e-semantic-recovery-{number}",
                human_confirmation=True,
                expected_current_version_id=saved.version.version_id,
            ),
        )
    return 1, SEMANTIC_RECOVERY_VERSION_COUNT
