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

REFERENCE_TARGET_TITLE_V1 = "Synthetic document reference target v1"
REFERENCE_TARGET_TITLE_V2 = "Synthetic document reference target v2"
REFERENCE_SOURCE_TITLE = "Synthetic document reference source"


def reference_text(text: str, *, target_object_id: str | None = None, target_version_id: str | None = None) -> dict[str, Any]:
    node: dict[str, Any] = {"type": "text", "text": text}
    if target_object_id and target_version_id:
        node["marks"] = [{"type": "documentReference", "attrs": {
            "targetObjectId": target_object_id, "targetVersionId": target_version_id,
        }}]
    return {"type": "doc", "content": [{"type": "paragraph", "content": [node]}]}


def seed_synthetic_office_document_references(
    *, environment: Mapping[str, str], client: Boto3S3CompatibleObjectStoreClient
) -> tuple[int, int]:
    require_isolated_work_e2e_environment(environment)
    database_dsn = environment["SUITE_DATABASE_DSN"]
    service = build_synthetic_office_service(database_dsn=database_dsn, client=client, audit=InMemoryAuditLogger())
    directory = PgPrincipalDirectory(database_dsn=database_dsn)

    def editor() -> UserContext:
        return UserContext(tenant_id=WORK_E2E_TENANT_ID, user_id=WORK_E2E_OFFICE_EDITOR_ID,
            role_ids={"office-editor"}, readable_object_ids=directory.readable_object_ids(
                tenant_id=WORK_E2E_TENANT_ID, user_id=WORK_E2E_OFFICE_EDITOR_ID,
                role_ids={"office-editor"}, group_ids=set()))

    target = service.create(user_context=editor(), write_enabled=True, command=OfficeDocumentCreateCommand(
        title=REFERENCE_TARGET_TITLE_V1, document=reference_text("Target version one"),
        mutation_reference="work-e2e-document-reference-target-1", human_confirmation=True))
    source = service.create(user_context=editor(), write_enabled=True, command=OfficeDocumentCreateCommand(
        title=REFERENCE_SOURCE_TITLE, document=reference_text("Legacy source"),
        mutation_reference="work-e2e-document-reference-source-1", human_confirmation=True))
    source = service.save(user_context=editor(), object_id=source.document.object_id, write_enabled=True,
        command=OfficeDocumentSaveCommand(title=REFERENCE_SOURCE_TITLE,
            document=reference_text("Pinned target", target_object_id=target.document.object_id,
                target_version_id=target.version.version_id),
            mutation_reference="work-e2e-document-reference-source-2", human_confirmation=True,
            expected_current_version_id=source.version.version_id))
    service.save(user_context=editor(), object_id=target.document.object_id, write_enabled=True,
        command=OfficeDocumentSaveCommand(title=REFERENCE_TARGET_TITLE_V2, document=reference_text("Target version two"),
            mutation_reference="work-e2e-document-reference-target-2", human_confirmation=True,
            expected_current_version_id=target.version.version_id))
    return 2, 4
