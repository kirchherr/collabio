from copy import deepcopy

import pytest

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.platform.office_documents import (
    OfficeDocumentConflictError,
    OfficeDocumentPermissionError,
    OfficeDocumentSaveCommand,
)
from suite.storage.source_object_storage import InMemorySourceObjectContentStore
from suite.storage.source_objects import PgSourceObjectWriteReceiptStore, source_object_content_bytes
from test_office_named_styles import styled_document
from test_office_documents_pg import Database, command, counts, editor, grant, service_for
from test_office_documents_pg import database as database


def test_pg_named_style_versions_preserve_legacy_sources_receipts_cas_and_acl(database: Database) -> None:
    store = InMemorySourceObjectContentStore()
    service = service_for(database, store)
    user = editor()
    created = service.create(user_context=user, write_enabled=True, command=command("legacy"))
    object_id = created.document.object_id
    user.readable_object_ids.add(object_id)
    first_content = styled_document()
    first = service.save(
        user_context=user,
        object_id=object_id,
        write_enabled=True,
        command=OfficeDocumentSaveCommand(
            **{**command("format-one").model_dump(), "document": first_content},
            expected_current_version_id=created.version.version_id,
        ),
    )
    second_content = deepcopy(first_content)
    second_content["attrs"]["styles"][0]["character"]["fontSize"] = 24
    second_command = OfficeDocumentSaveCommand(
        **{**command("format-two").model_dump(), "document": second_content},
        expected_current_version_id=first.version.version_id,
    )
    second = service.save(user_context=user, object_id=object_id, write_enabled=True, command=second_command)
    receipt_store = PgSourceObjectWriteReceiptStore(database_dsn=database.app_dsn)
    for result, expected in ((created, command("legacy").document), (first, first_content), (second, second_content)):
        version = result.version
        read = service.read_content(user_context=user, object_id=object_id, version_id=version.version_id)
        record = service.source_repository.get(
            tenant_id=user.tenant_id, object_id=object_id, version_id=version.version_id
        )
        receipt = receipt_store.get(tenant_id=user.tenant_id, receipt_hash=version.source_write_receipt_hash)
        assert read.content == expected
        assert source_object_content_bytes(record) == canonical_json(expected).encode("utf-8")
        assert (
            receipt.content_hash
            == record.metadata.content_hash
            == version.content_hash
            == stable_hash(canonical_json(expected))
        )
        assert receipt.manifest_hash == record.metadata.manifest_hash
        assert read.version.source_write_receipt_hash == receipt.receipt_hash
    assert len({created.version.content_hash, first.version.content_hash, second.version.content_hash}) == 3
    replay = service.save(user_context=user, object_id=object_id, write_enabled=True, command=second_command)
    assert replay.replayed and replay.version == second.version and replay.content == second_content
    before = counts(database, user)
    with pytest.raises(OfficeDocumentConflictError):
        service.save(
            user_context=user,
            object_id=object_id,
            write_enabled=True,
            command=second_command.model_copy(update={"mutation_reference": "stale-format"}),
        )
    reader = user.model_copy(update={"user_id": "format-reader", "role_ids": set()})
    grant(database, user, object_id, reader.user_id, "read")
    assert service.read_content(user_context=reader, object_id=object_id).content == second_content
    with pytest.raises(OfficeDocumentPermissionError):
        service.save(
            user_context=reader,
            object_id=object_id,
            write_enabled=True,
            command=second_command.model_copy(
                update={"expected_current_version_id": second.version.version_id, "mutation_reference": "reader-format"}
            ),
        )
    assert counts(database, user)[:-1] == before[:-1]
    assert len(store.list_stored_objects(tenant_id=user.tenant_id)) == 3
