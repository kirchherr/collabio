from copy import deepcopy
from typing import Any

import psycopg
import pytest

from docx_image_fixture import image_docx
from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import UserContext
from suite.platform import office_import_preview
from suite.platform.office_documents import (
    OfficeDocumentCreateCommand,
    OfficeDocumentInvalidContentError,
    OfficeDocumentPermissionError,
    OfficeDocumentService,
    OfficeInformationClassification,
)
from suite.platform.office_images import read_image
from suite.platform.office_import_preview import OfficeImportPreviewResponse
from suite.rag.rich_document_parser import RichDocumentParserWorker
from suite.storage.source_object_storage import InMemorySourceObjectContentStore
from suite.storage.source_objects import SourceObjectRecord, build_source_object_manifest_hash
from test_office_documents_pg import Database, counts, editor, service_for, set_tenant
from test_office_documents_pg import database as database
from test_office_import_preview import command, source_record


def setup_import(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> tuple[OfficeDocumentService, UserContext, OfficeImportPreviewResponse]:
    service = service_for(database, InMemorySourceObjectContentStore())
    user = editor()
    record = source_record(image_docx())
    metadata = record.metadata.model_copy(
        update={
            "tenant_id": user.tenant_id,
            "owner_principal_id": user.user_id,
            "created_by": user.user_id,
            "kms_key_ref": f"kms://{user.tenant_id}/internal/v1",
        }
    )
    metadata = metadata.model_copy(update={"manifest_hash": build_source_object_manifest_hash(metadata)})
    service.source_repository.add(SourceObjectRecord(metadata=metadata, content_bytes=record.content_bytes))
    with psycopg.connect(database.admin_dsn) as connection:
        set_tenant(connection, user.tenant_id)
        connection.execute(
            "INSERT INTO collabio.object_acl_entries "
            "(tenant_id, object_id, object_type, acl_subject_type, acl_subject_id, permission, "
            "acl_version, audit_chain_ref) "
            "VALUES (%s, %s, 'document', 'user', %s, 'read', 1, 'audit:docx-source')",
            (user.tenant_id, metadata.object_id, user.user_id),
        )
    user.readable_object_ids.add(metadata.object_id)
    original = office_import_preview.OfficeImportPreviewService

    def preview_service(**kwargs: Any) -> office_import_preview.OfficeImportPreviewService:
        return original(
            **kwargs,
            parser_dispatch=RichDocumentParserWorker().parse,
            image_normalizer=lambda raw, mime: (raw, 320, 120),
        )

    monkeypatch.setattr(office_import_preview, "OfficeImportPreviewService", preview_service)
    preview = preview_service(source_repository=service.source_repository, audit=InMemoryAuditLogger()).preview(
        user_context=user, command=command()
    )
    return service, user, preview


def test_import_materializes_owned_assets_atomically_and_retries_without_the_source(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, user, preview = setup_import(database, monkeypatch)
    create = OfficeDocumentCreateCommand(
        title="Imported", mutation_reference="docx-images", human_confirmation=True, document=preview.document
    )
    result = service.create(user_context=user, command=create, write_enabled=True)
    user.readable_object_ids.add(result.document.object_id)
    attrs = [node["attrs"] for node in result.content["content"] if node["type"] == "image"]
    assert len(attrs) == 2
    assert attrs[0]["assetId"] != attrs[1]["assetId"]
    assert all(item["documentId"] == result.document.object_id for item in attrs)
    record = service.repository.get_document(user_context=user, object_id=result.document.object_id)
    assert read_image(service.source_repository, record, attrs[0])[1].startswith(b"\x89PNG")
    assert result.content["attrs"]["importProvenance"] == preview.document["attrs"]["importProvenance"]
    before = counts(database, user)
    user.readable_object_ids.remove(preview.source_object_id)
    replay = service.create(user_context=user, command=create, write_enabled=True)
    assert replay.replayed and replay.content == result.content
    assert counts(database, user) == before


@pytest.mark.parametrize("tamper", ["revoked", "during_parse", "hash", "dimensions", "provenance", "classification"])
def test_import_revalidates_source_and_rolls_back_failed_materialization(
    database: Database, monkeypatch: pytest.MonkeyPatch, tamper: str
) -> None:
    service, user, preview = setup_import(database, monkeypatch)
    content = deepcopy(preview.document)
    classification: OfficeInformationClassification = "internal"
    if tamper == "revoked":
        with psycopg.connect(database.admin_dsn) as connection:
            set_tenant(connection, user.tenant_id)
            connection.execute(
                "UPDATE collabio.object_acl_entries SET status = 'revoked', revoked_at_utc = now() "
                "WHERE tenant_id = %s",
                (user.tenant_id,),
            )
    elif tamper == "during_parse":
        factory = office_import_preview.OfficeImportPreviewService

        def revoke_after_parse(**kwargs: Any) -> Any:
            inner = factory(**kwargs)
            original_preview = inner.preview

            def preview_then_revoke(**arguments: Any) -> Any:
                response = original_preview(**arguments)
                with psycopg.connect(database.admin_dsn) as connection:
                    set_tenant(connection, user.tenant_id)
                    query = "UPDATE collabio.object_acl_entries SET status = 'revoked', revoked_at_utc = now() "
                    connection.execute(
                        query + "WHERE tenant_id = %s AND object_id = %s", (user.tenant_id, preview.source_object_id)
                    )
                return response

            monkeypatch.setattr(inner, "preview", preview_then_revoke)
            return inner

        monkeypatch.setattr(office_import_preview, "OfficeImportPreviewService", revoke_after_parse)
    elif tamper == "hash":
        content["content"][-1]["attrs"]["contentHash"] = "sha256:" + "0" * 64
    elif tamper == "dimensions":
        content["content"][-1]["attrs"]["pixelWidth"] = 319
    elif tamper == "provenance":
        content["attrs"]["importProvenance"]["parserStructureHash"] = "sha256:" + "0" * 64
    else:
        classification = "public"
        # An administrator may normally create public documents; imported content
        # still cannot bypass its source classification floor.
        user.role_ids.add("tenant-admin")
    before = counts(database, user)
    with pytest.raises((OfficeDocumentPermissionError, OfficeDocumentInvalidContentError)):
        service.create(
            user_context=user,
            write_enabled=True,
            command=OfficeDocumentCreateCommand(
                title="Rejected import",
                mutation_reference=f"invalid-{tamper}",
                human_confirmation=True,
                information_classification=classification,
                document=content,
            ),
        )
    assert counts(database, user) == before
