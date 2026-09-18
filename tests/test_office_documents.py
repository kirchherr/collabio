from copy import deepcopy
from typing import Any

import pytest
from pydantic import ValidationError

from suite.ai_control_plane.audit import InMemoryAuditLogger, canonical_json
from suite.ai_control_plane.models import UserContext
from suite.platform.office_document_repository import InMemoryOfficeDocumentRepository
from suite.platform.office_document_schema import OfficeDocumentInvalidContentError, validate_office_document
from suite.platform.office_documents import (
    OfficeDocumentConflictError,
    OfficeDocumentCreateCommand,
    OfficeDocumentNotFoundError,
    OfficeDocumentPermissionError,
    OfficeDocumentSaveCommand,
    OfficeDocumentService,
)
from suite.storage.source_object_storage import SourceObjectStorageError
from suite.storage.source_objects import InMemorySourceObjectRepository, SourceObjectRecord


def document_text(text: str = "Confidential native draft") -> dict[str, Any]:
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


def create_command(reference: str = "create-1") -> OfficeDocumentCreateCommand:
    return OfficeDocumentCreateCommand(
        title="Private document title", document=document_text(), mutation_reference=reference, human_confirmation=True
    )


def test_native_document_supports_bounded_rich_structure_without_active_content() -> None:
    paragraph = document_text()["content"][0]
    rich = {
        "type": "doc",
        "content": [
            {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Title"}]},
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "<script>literal</script>",
                        "marks": [{"type": "bold"}, {"type": "underline"}],
                    },
                    {"type": "hardBreak"},
                ],
            },
            {"type": "orderedList", "attrs": {"start": 3}, "content": [{"type": "listItem", "content": [paragraph]}]},
            {"type": "blockquote", "content": [paragraph]},
            {"type": "codeBlock", "attrs": {"language": None}, "content": [{"type": "text", "text": "a\n\tb"}]},
            {"type": "horizontalRule"},
            {
                "type": "table",
                "content": [
                    {
                        "type": "tableRow",
                        "content": [
                            {
                                "type": "tableHeader",
                                "attrs": {"colspan": 1, "rowspan": 1, "colwidth": None},
                                "content": [paragraph],
                            },
                            {"type": "tableCell", "content": [paragraph]},
                        ],
                    }
                ],
            },
        ],
    }
    assert validate_office_document(rich) == rich


@pytest.mark.parametrize(
    "node",
    [
        {"type": "image", "attrs": {"src": "https://example.invalid/private"}},
        {"type": "html", "text": "<img src=x>"},
        {"type": "paragraph", "attrs": {"onclick": "secret"}},
        {"type": "heading", "attrs": {"level": True}},
        {"type": "heading", "attrs": {"level": 4}},
        {
            "type": "paragraph",
            "content": [{"type": "text", "text": "x", "marks": [{"type": "link", "attrs": {"href": "x"}}]}],
        },
        {"type": "paragraph", "content": [{"type": "text", "text": "x", "marks": [{"type": "bold", "attrs": {}}]}]},
        {"type": "codeBlock", "content": [{"type": "text", "text": "x", "marks": [{"type": "bold"}]}]},
        {"type": "paragraph", "content": [{"type": "text", "text": "null\x00"}]},
        {"type": "paragraph", "content": [{"type": "text", "text": "\ud800"}]},
        {"type": "paragraph", "content": [{"type": []}]},
        {"type": "paragraph", "content": ["bad"]},
        {
            "type": "table",
            "content": [
                {
                    "type": "tableRow",
                    "content": [{"type": "tableCell", "attrs": {"rowspan": 2}, "content": [{"type": "paragraph"}]}],
                }
            ],
        },
        {"type": "paragraph", "data": "unexpected"},
    ],
)
def test_native_schema_rejects_active_unsupported_and_malformed_nodes(node: dict[str, Any]) -> None:
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document({"type": "doc", "content": [node]})


def test_native_schema_resource_limits_are_independent() -> None:
    deep: dict[str, Any] = {"type": "paragraph"}
    for _ in range(33):
        deep = {"type": "blockquote", "content": [deep]}
    for value in (
        {"type": "doc", "content": [deep]},
        {"type": "doc", "content": [{"type": "paragraph"}] * 10_001},
        document_text("a" * 100_001),
        document_text("\U0001f600" * 40_000),
    ):
        with pytest.raises(OfficeDocumentInvalidContentError):
            validate_office_document(value)


@pytest.fixture
def office() -> tuple[OfficeDocumentService, InMemoryOfficeDocumentRepository, UserContext]:
    sources = InMemorySourceObjectRepository()
    repository = InMemoryOfficeDocumentRepository(source_repository=sources)
    service = OfficeDocumentService(repository=repository, source_repository=sources, audit=InMemoryAuditLogger())
    user = UserContext(tenant_id="tenant-native-office", user_id="editor", role_ids={"office-editor"})
    return service, repository, user


def test_native_create_save_history_and_actor_bound_idempotency(office: Any) -> None:
    service, repository, user = office
    created = service.create(user_context=user, command=create_command(), write_enabled=True)
    object_id = created.document.object_id
    user.readable_object_ids.add(object_id)
    replay = service.create(user_context=user, command=create_command(), write_enabled=True)
    assert replay.replayed and replay.version == created.version
    saved = service.save(
        user_context=user,
        object_id=object_id,
        write_enabled=True,
        command=OfficeDocumentSaveCommand(
            title="Revised title",
            document=document_text("New text"),
            mutation_reference="save-1",
            human_confirmation=True,
            expected_current_version_id=created.version.version_id,
        ),
    )
    assert saved.version.previous_version_id == created.version.version_id
    assert saved.version.version_id != created.version.version_id
    assert service.read_content(user_context=user, object_id=object_id).content == document_text("New text")
    old = service.read_content(user_context=user, object_id=object_id, version_id=created.version.version_id)
    assert old.content == create_command().document and not old.is_current_version
    assert old.version.title == "Private document title" and old.document.title == "Revised title"
    late_replay = service.create(user_context=user, command=create_command(), write_enabled=True)
    assert late_replay.replayed and not late_replay.is_current_version
    assert late_replay.document.current_version_id == saved.version.version_id
    assert len(service.history(user_context=user, object_id=object_id).versions) == 2
    assert len(repository.receipt_store.list_receipts(tenant_id=user.tenant_id)) == 2
    with pytest.raises(OfficeDocumentConflictError):
        service.create(
            user_context=user, command=create_command().model_copy(update={"title": "Changed"}), write_enabled=True
        )
    assert not created.rag_indexing_allowed and not created.search_indexing_allowed
    audit_payload = canonical_json([event.model_dump() for event in service.audit.events])
    assert "Confidential native draft" not in audit_payload
    assert "Private document title" not in audit_payload
    assert "New text" not in audit_payload
    assert all(event.metadata["surface"] == "api" for event in service.audit.events)


def test_native_write_gates_readonly_acl_revoke_and_foreign_tenant(office: Any) -> None:
    service, repository, user = office
    with pytest.raises(OfficeDocumentPermissionError):
        service.create(user_context=user, command=create_command())
    viewer = user.model_copy(update={"role_ids": set()})
    with pytest.raises(OfficeDocumentPermissionError):
        service.create(user_context=viewer, command=create_command(), write_enabled=True)
    created = service.create(user_context=user, command=create_command(), write_enabled=True)
    object_id = created.document.object_id
    user.readable_object_ids.add(object_id)
    command = OfficeDocumentSaveCommand(
        **create_command("save").model_dump(), expected_current_version_id=created.version.version_id
    )
    repository.grants[(user.tenant_id, object_id, user.user_id)] = "read"
    assert service.read_content(user_context=user, object_id=object_id, write_enabled=True).can_write is False
    with pytest.raises(OfficeDocumentPermissionError):
        service.save(user_context=user, object_id=object_id, command=command, write_enabled=True)
    with pytest.raises(OfficeDocumentPermissionError):
        service.create(user_context=user, command=create_command(), write_enabled=True)
    foreign = user.model_copy(update={"tenant_id": "tenant-foreign"})
    with pytest.raises(OfficeDocumentNotFoundError):
        service.read_content(user_context=foreign, object_id=object_id)
    del repository.grants[(user.tenant_id, object_id, user.user_id)]
    with pytest.raises(OfficeDocumentNotFoundError):
        service.history(user_context=user, object_id=object_id)
    assert service.list_documents(user_context=user, write_enabled=True).documents == []


def test_stale_save_and_missing_confirmation_have_no_source_or_receipt_side_effect(office: Any) -> None:
    service, repository, user = office
    created = service.create(user_context=user, command=create_command(), write_enabled=True)
    user.readable_object_ids.add(created.document.object_id)
    command = OfficeDocumentSaveCommand(**create_command("save").model_dump(), expected_current_version_id="stale")
    with pytest.raises(OfficeDocumentConflictError):
        service.save(user_context=user, object_id=created.document.object_id, command=command, write_enabled=True)
    with pytest.raises(ValidationError):
        service.create(
            user_context=user,
            command=create_command().model_copy(update={"human_confirmation": False}),
            write_enabled=True,
        )
    with pytest.raises(ValidationError):
        OfficeDocumentCreateCommand.model_validate({**create_command().model_dump(), "human_confirmation": "true"})
    assert len(repository.saved_versions) == 1
    assert len(repository.receipt_store.list_receipts(tenant_id=user.tenant_id)) == 1


def test_unavailable_write_adapter_denies_writes_and_does_not_advertise_editing(office: Any) -> None:
    service, repository, user = office
    created = service.create(user_context=user, command=create_command(), write_enabled=True)
    object_id = created.document.object_id
    user.readable_object_ids.add(object_id)
    readonly = OfficeDocumentService(
        repository=repository,
        source_repository=repository.source_repository,
        audit=service.audit,
        writes_available=False,
    )
    listed = readonly.list_documents(user_context=user, write_enabled=True)
    assert not listed.can_create and not listed.documents[0].can_write
    read = readonly.read_content(user_context=user, object_id=object_id, write_enabled=True)
    assert not read.can_write and not read.document.can_write
    with pytest.raises(OfficeDocumentPermissionError):
        readonly.create(user_context=user, command=create_command("new"), write_enabled=True)
    with pytest.raises(OfficeDocumentPermissionError):
        readonly.save(
            user_context=user,
            object_id=object_id,
            write_enabled=True,
            command=OfficeDocumentSaveCommand(
                **create_command("save").model_dump(), expected_current_version_id=created.version.version_id
            ),
        )
    assert len(repository.saved_versions) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", "tenant-foreign"),
        ("mime_type", "text/html"),
        ("source_system", "other"),
        ("lifecycle_state", "restricted"),
        ("content_hash", "sha256:" + "f" * 64),
        ("content_byte_length", 400_001),
        ("created_by", "another-user"),
        ("acl_version", 99),
    ],
)
def test_source_metadata_corruption_is_rejected_before_content_read(
    office: Any, monkeypatch: Any, field: str, value: Any
) -> None:
    service, repository, user = office
    created = service.create(user_context=user, command=create_command(), write_enabled=True)
    object_id = created.document.object_id
    user.readable_object_ids.add(object_id)
    metadata = repository.source_repository.get_metadata(
        tenant_id=user.tenant_id, object_id=object_id, version_id=created.version.version_id
    )
    monkeypatch.setattr(
        repository.source_repository, "get_metadata", lambda **_: metadata.model_copy(update={field: value})
    )
    monkeypatch.setattr(
        repository.source_repository, "get", lambda **_: pytest.fail("preflight must block content access")
    )
    with pytest.raises(OfficeDocumentInvalidContentError):
        service.read_content(user_context=user, object_id=object_id)


def test_read_denied_before_metadata_and_storage_outage_is_not_misclassified(office: Any, monkeypatch: Any) -> None:
    service, repository, user = office
    created = service.create(user_context=user, command=create_command(), write_enabled=True)
    object_id = created.document.object_id
    monkeypatch.setattr(repository.source_repository, "get_metadata", lambda **_: pytest.fail("denied before metadata"))
    with pytest.raises(OfficeDocumentNotFoundError):
        service.read_content(user_context=user, object_id=object_id)
    monkeypatch.undo()
    user.readable_object_ids.add(object_id)

    def unavailable(**_: Any) -> SourceObjectRecord:
        raise SourceObjectStorageError("private storage endpoint must not leak")

    monkeypatch.setattr(repository.source_repository, "get", unavailable)
    with pytest.raises(SourceObjectStorageError):
        service.read_content(user_context=user, object_id=object_id)


def test_loaded_bytes_must_match_exact_manifest_and_canonical_document(office: Any, monkeypatch: Any) -> None:
    service, repository, user = office
    created = service.create(user_context=user, command=create_command(), write_enabled=True)
    object_id = created.document.object_id
    user.readable_object_ids.add(object_id)
    record = repository.source_repository.get(
        tenant_id=user.tenant_id, object_id=object_id, version_id=created.version.version_id
    )
    corrupted = deepcopy(record)
    corrupted.content_bytes = b"wrong bytes"
    monkeypatch.setattr(repository.source_repository, "get", lambda **_: corrupted)
    with pytest.raises(OfficeDocumentInvalidContentError):
        service.read_content(user_context=user, object_id=object_id)
