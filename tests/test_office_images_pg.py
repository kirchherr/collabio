from copy import deepcopy
from typing import Any

import psycopg
import pytest

from office_image_recovery import verify_restored_images
from suite.platform.office_document_repository import PgOfficeDocumentRepository
from suite.platform.office_documents import (
    OfficeDocumentCreateCommand,
    OfficeDocumentInvalidContentError,
    OfficeDocumentNotFoundError,
    OfficeDocumentSaveCommand,
)
from suite.platform.office_image_codec import png_from_pixels
from suite.platform.office_images import read_image, store_uploaded_image
from suite.storage.source_object_storage import InMemorySourceObjectContentStore
from test_office_documents_pg import Database, command, counts, editor, service_for, set_tenant
from test_office_documents_pg import database as database


def test_pg_images_save_history_copy_and_replay_are_exact_and_independently_owned(database: Database) -> None:
    service = service_for(database, InMemorySourceObjectContentStore())
    user = editor()
    created = service.create(user_context=user, command=command(), write_enabled=True)
    object_id = created.document.object_id
    user.readable_object_ids.add(object_id)
    repository = service.repository
    assert isinstance(repository, PgOfficeDocumentRepository)
    png = png_from_pixels(2, 1, b"\xff\0\0\xff\0\xff\0\xff")
    attrs = store_uploaded_image(repository, user, object_id, png, 2, 1)
    assert service.read_content(user_context=user, object_id=object_id).content == created.content
    document = deepcopy(created.content)
    document["content"].append({"type": "image", "attrs": attrs})
    saved = service.save(
        user_context=user,
        object_id=object_id,
        write_enabled=True,
        command=OfficeDocumentSaveCommand(
            **{**command("with-image").model_dump(), "document": document},
            expected_current_version_id=created.version.version_id,
        ),
    )
    copy_command = OfficeDocumentCreateCommand(**{**command("copy").model_dump(), "document": document})
    copied = service.create(user_context=user, command=copy_command, write_enabled=True)
    user.readable_object_ids.add(copied.document.object_id)
    copy_attrs = copied.content["content"][-1]["attrs"]
    assert copy_attrs["documentId"] == copied.document.object_id
    assert copy_attrs["assetId"] != attrs["assetId"] and copy_attrs["versionId"] != attrs["versionId"]
    assert copy_attrs["contentHash"] == attrs["contentHash"] and copy_attrs["manifestHash"] != attrs["manifestHash"]
    replay = service.create(user_context=user, command=copy_command, write_enabled=True)
    assert replay.replayed and replay.content == copied.content and replay.version == copied.version
    removed = service.save(
        user_context=user,
        object_id=object_id,
        write_enabled=True,
        command=OfficeDocumentSaveCommand(
            **command("without-image").model_dump(), expected_current_version_id=saved.version.version_id
        ),
    )
    assert removed.content == created.content
    assert (
        service.read_content(user_context=user, object_id=object_id, version_id=saved.version.version_id).content
        == document
    )
    with psycopg.connect(database.app_dsn) as connection:
        set_tenant(connection, user.tenant_id)
        rows = connection.execute(
            "SELECT to_jsonb(record) FROM collabio.source_object_metadata AS record "
            "WHERE tenant_id = %s AND source_system = 'collabio_office_image' ORDER BY object_id",
            (user.tenant_id,),
        ).fetchall()
    bindings = [
        {
            "object_id": item["documentId"],
            "asset_id": item["assetId"],
            "asset_version_id": item["versionId"],
            "content_hash": item["contentHash"],
            "manifest_hash": item["manifestHash"],
        }
        for item in (attrs, copy_attrs)
    ]
    for tamper in (False, True):
        inventory = deepcopy([row[0] for row in rows])
        if tamper:
            inventory[0]["content_hash"] = "sha256:" + "0" * 64
        arguments: dict[str, Any] = dict(
            documents=service,
            readers={object_id: user, copied.document.object_id: user},
            original_sources=service.source_repository,
            restored_sources=service.source_repository,
            receipts=repository.receipt_store,
            images=inventory,
            bindings=bindings,
        )
        if tamper:
            with pytest.raises(ValueError):
                verify_restored_images(**arguments)
        else:
            proof = verify_restored_images(**arguments)
            assert proof["verified_image_asset_count"] == 2
            assert proof["verified_saved_image_reference_count"] == 2
            assert proof["image_bytes_and_receipts_verified"]
    with psycopg.connect(database.admin_dsn) as connection:
        set_tenant(connection, user.tenant_id)
        connection.execute(
            "UPDATE collabio.object_acl_entries SET status = 'revoked', revoked_at_utc = now() "
            "WHERE tenant_id = %s AND object_id = %s",
            (user.tenant_id, object_id),
        )
    with pytest.raises(OfficeDocumentNotFoundError):
        service.read_content(user_context=user, object_id=object_id)
    own_document = repository.get_document(user_context=user, object_id=copied.document.object_id)
    assert read_image(service.source_repository, own_document, copy_attrs)[1] == png
    assert service.read_content(user_context=user, object_id=copied.document.object_id).content == copied.content


def test_pg_wrong_owner_hash_and_foreign_tenant_images_fail_without_document_write(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = service_for(database, InMemorySourceObjectContentStore())
    user = editor()
    first = service.create(user_context=user, command=command("first"), write_enabled=True)
    second = service.create(user_context=user, command=command("second"), write_enabled=True)
    user.readable_object_ids.update((first.document.object_id, second.document.object_id))
    repository = service.repository
    assert isinstance(repository, PgOfficeDocumentRepository)
    attrs = store_uploaded_image(
        repository, user, first.document.object_id, png_from_pixels(1, 1, b"\0\0\xff\xff"), 1, 1
    )
    before = counts(database, user)
    for changes in ({}, {"documentId": second.document.object_id}, {"contentHash": "sha256:" + "0" * 64}):
        document = deepcopy(second.content)
        document["content"].append({"type": "image", "attrs": {**attrs, **changes}})
        with pytest.raises((OfficeDocumentInvalidContentError, OfficeDocumentNotFoundError)):
            service.save(
                user_context=user,
                object_id=second.document.object_id,
                write_enabled=True,
                command=OfficeDocumentSaveCommand(
                    **{**command("wrong-image").model_dump(), "document": document},
                    expected_current_version_id=second.version.version_id,
                ),
            )
        assert counts(database, user) == before
    foreign = editor()
    foreign.readable_object_ids.add(first.document.object_id)
    with pytest.raises(OfficeDocumentNotFoundError):
        store_uploaded_image(repository, foreign, first.document.object_id, png_from_pixels(1, 1, b"\0\0\0\xff"), 1, 1)
    owner = repository.get_document(user_context=user, object_id=first.document.object_id)
    with pytest.raises(OfficeDocumentInvalidContentError):
        read_image(service.source_repository, owner, {**attrs, "pixelWidth": 2})
    source = service.source_repository.get(
        tenant_id=user.tenant_id, object_id=attrs["assetId"], version_id=attrs["versionId"]
    )
    with monkeypatch.context() as patch:
        patch.setattr(service.source_repository, "get", lambda **kwargs: source.model_copy(update={"content_bytes": b"bad"}))
        with pytest.raises(OfficeDocumentInvalidContentError):
            read_image(service.source_repository, owner, attrs)
