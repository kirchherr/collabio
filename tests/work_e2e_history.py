from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import UserContext
from suite.platform.authz_admin import ObjectAclEntryUpsertCommand, PgAuthzAdminStore
from suite.platform.office_documents import OfficeDocumentCreateCommand, OfficeDocumentSaveCommand
from suite.platform.principal_store import PgPrincipalDirectory
from suite.storage.s3_sdk_client import Boto3S3CompatibleObjectStoreClient
from suite.testing.work_e2e_guard import WORK_E2E_TENANT_ID, require_isolated_work_e2e_environment
from work_e2e_office import build_synthetic_office_service

HISTORY_EDITOR_ID = "work-history-editor-e2e"
HISTORY_READER_ID = "work-history-reader-e2e"
HISTORY_VERSION_COUNT = 225


def history_document(number: int) -> dict[str, Any]:
    if not 1 <= number <= HISTORY_VERSION_COUNT:
        raise ValueError("Synthetic history version is outside the fixture")
    if number != 1:
        return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": f"Synthetic saved history version {number:03d}."}]}]}
    return {
        "type": "doc",
        "content": [
            {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "History 001 — Café 😀"}]},
            {"type": "paragraph", "content": [{"type": "text", "text": "<script>literal earliest version</script>", "marks": [{"type": "bold"}]}]},
            {"type": "table", "content": [{"type": "tableRow", "content": [
                {"type": "tableHeader", "attrs": {"colspan": 1, "rowspan": 1}, "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Original owner"}]}]},
                {"type": "tableHeader", "attrs": {"colspan": 1, "rowspan": 1}, "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Original decision"}]}]},
            ]}]},
        ],
    }


def seed_synthetic_office_history(
    *, environment: Mapping[str, str], client: Boto3S3CompatibleObjectStoreClient
) -> tuple[int, int]:
    """Create one genuine append-only chain only in the guarded ephemeral test tenant."""
    require_isolated_work_e2e_environment(environment)
    database_dsn = environment["SUITE_DATABASE_DSN"]
    service = build_synthetic_office_service(database_dsn=database_dsn, client=client, audit=InMemoryAuditLogger())
    directory = PgPrincipalDirectory(database_dsn=database_dsn)

    def author() -> UserContext:
        return UserContext(
            tenant_id=WORK_E2E_TENANT_ID,
            user_id=HISTORY_EDITOR_ID,
            role_ids={"office-editor"},
            readable_object_ids=directory.readable_object_ids(
                tenant_id=WORK_E2E_TENANT_ID, user_id=HISTORY_EDITOR_ID, role_ids={"office-editor"}, group_ids=set()
            ),
        )

    saved = service.create(
        user_context=author(),
        command=OfficeDocumentCreateCommand(
            title="History 001 Café 😀 <img src=x>",
            document=history_document(1),
            mutation_reference="work-e2e-history-001",
            human_confirmation=True,
        ),
        write_enabled=True,
    )
    for number in range(2, HISTORY_VERSION_COUNT + 1):
        saved = service.save(
            user_context=author(),
            object_id=saved.document.object_id,
            command=OfficeDocumentSaveCommand(
                title=f"History {number:03d} saved title",
                document=history_document(number),
                expected_current_version_id=saved.version.version_id,
                mutation_reference=f"work-e2e-history-{number:03d}",
                human_confirmation=True,
            ),
            write_enabled=True,
        )
    PgAuthzAdminStore(database_dsn=environment["SUITE_AUTHZ_ADMIN_DATABASE_DSN"]).upsert_object_acl_entry(
        tenant_id=WORK_E2E_TENANT_ID,
        command=ObjectAclEntryUpsertCommand(
            object_id=saved.document.object_id,
            object_type="office.document",
            acl_subject_type="user",
            acl_subject_id=HISTORY_READER_ID,
            permission="read",
            acl_version=1,
            approval_reference="test-fixture:work-e2e-history-reader",
            reason="Synthetic isolated history proof only",
        ),
        audit_chain_ref="audit:work-e2e-history-reader",
    )
    return 1, HISTORY_VERSION_COUNT
