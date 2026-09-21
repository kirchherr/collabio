from __future__ import annotations

from collections.abc import Mapping

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import UserContext
from suite.platform.authz_admin import ObjectAclEntryUpsertCommand, PgAuthzAdminStore
from suite.platform.office_documents import OfficeDocumentCreateCommand
from suite.storage.s3_sdk_client import Boto3S3CompatibleObjectStoreClient
from suite.testing.work_e2e_guard import WORK_E2E_TENANT_ID, require_isolated_work_e2e_environment
from work_e2e_office import build_synthetic_office_service

DISCOVERY_EDITOR_ID = "work-discovery-editor-e2e"
DISCOVERY_READER_ID = "work-discovery-reader-e2e"
DISCOVERY_DOCUMENT_COUNT = 225


def discovery_title(index: int) -> str:
    if not 0 <= index < DISCOVERY_DOCUMENT_COUNT:
        raise ValueError("Synthetic discovery index is outside the fixture")
    suffixes = (
        "<img src=x onerror=alert(260)> & literal",
        "Café Straße 東京",
        r"literal 100%_path\marker",
        "literal 100XXpathZmarker",
        "CAFE STRASSE 東京",
    )
    suffix = suffixes[index] if index < len(suffixes) else "saved title"
    return f"Discovery {index:03d} {suffix}"


def seed_synthetic_office_discovery(
    *, environment: Mapping[str, str], client: Boto3S3CompatibleObjectStoreClient
) -> int:
    """Real writes after principal commit; never usable outside the isolated Compose fixture."""
    require_isolated_work_e2e_environment(environment)
    service = build_synthetic_office_service(
        database_dsn=environment["SUITE_DATABASE_DSN"], client=client, audit=InMemoryAuditLogger()
    )
    authz = PgAuthzAdminStore(database_dsn=environment["SUITE_AUTHZ_ADMIN_DATABASE_DSN"])
    user = UserContext(tenant_id=WORK_E2E_TENANT_ID, user_id=DISCOVERY_EDITOR_ID, role_ids={"office-editor"})
    for index in range(DISCOVERY_DOCUMENT_COUNT):
        saved = service.create(
            user_context=user,
            command=OfficeDocumentCreateCommand(
                title=discovery_title(index),
                document={
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": f"Synthetic discovery document {index:03d}."}],
                        }
                    ],
                },
                mutation_reference=f"work-e2e-discovery-{index:03d}",
                human_confirmation=True,
            ),
            write_enabled=True,
        )
        if index < 3:
            authz.upsert_object_acl_entry(
                tenant_id=WORK_E2E_TENANT_ID,
                command=ObjectAclEntryUpsertCommand(
                    object_id=saved.document.object_id,
                    object_type="office.document",
                    acl_subject_type="user",
                    acl_subject_id=DISCOVERY_READER_ID,
                    permission="read",
                    acl_version=1,
                    approval_reference="test-fixture:work-e2e-discovery-reader",
                    reason="Synthetic isolated discovery proof only",
                ),
                audit_chain_ref=f"audit:work-e2e-discovery-reader:{index:03d}",
            )
    return DISCOVERY_DOCUMENT_COUNT
