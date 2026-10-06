from copy import deepcopy
from typing import Any

import pytest

from suite.ai_control_plane.audit import canonical_json
from suite.platform.office_document_schema import (
    OfficeDocumentInvalidContentError,
    office_document_reference_counts,
    office_document_references,
    validate_office_document,
)
from suite.platform.office_documents import (
    OfficeDocumentCreateCommand,
    OfficeDocumentListRequestError,
    OfficeDocumentNotFoundError,
    OfficeDocumentSaveCommand,
)
from test_office_documents import document_text
from test_office_documents import office as office

TARGET_OBJECT = "office-doc-" + "a" * 32
TARGET_VERSION = "office-version-" + "b" * 32


def referenced_document(object_id: str = TARGET_OBJECT, version_id: str = TARGET_VERSION) -> dict:
    return {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "Pinned source",
                        "marks": [
                            {
                                "type": "documentReference",
                                "attrs": {
                                    "targetObjectId": object_id,
                                    "targetVersionId": version_id,
                                },
                            }
                        ],
                    }
                ],
            }
        ],
    }


def document_card(mode: str = "snapshot") -> dict:
    return {
        "type": "documentCard",
        "attrs": {"targetObjectId": TARGET_OBJECT, "targetVersionId": TARGET_VERSION, "mode": mode},
    }


def test_document_card_is_inert_bounded_and_part_of_authoritative_reference_counts() -> None:
    for mode in ("snapshot", "linked"):
        document = {"type": "doc", "content": [document_card(mode), {"type": "paragraph"}]}
        assert validate_office_document(document) is document
        assert office_document_reference_counts(document) == ((TARGET_OBJECT, TARGET_VERSION, 1),)

    mixed = referenced_document()
    mixed["content"].append(document_card("linked"))
    assert office_document_reference_counts(mixed) == ((TARGET_OBJECT, TARGET_VERSION, 2),)

    for invalid in (
        {**document_card(), "attrs": {**document_card()["attrs"], "mode": "live"}},
        {**document_card(), "attrs": {**document_card()["attrs"], "title": "Stored title leak"}},
        {"type": "blockquote", "content": [document_card()]},
    ):
        candidate = {"type": "doc", "content": [invalid]}
        with pytest.raises(OfficeDocumentInvalidContentError):
            validate_office_document(candidate)

    excessive = {"type": "doc", "content": [document_card() for _ in range(101)]}
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(excessive)


def test_document_reference_schema_is_bounded_exact_and_deduplicated() -> None:
    document = referenced_document()
    document["content"].append(deepcopy(document["content"][0]))
    assert validate_office_document(document) is document
    assert office_document_references(document) == ((TARGET_OBJECT, TARGET_VERSION),)
    assert office_document_reference_counts(document) == ((TARGET_OBJECT, TARGET_VERSION, 2),)

    for attrs in (
        {"targetObjectId": "office-doc-invalid", "targetVersionId": TARGET_VERSION},
        {"targetObjectId": TARGET_OBJECT, "targetVersionId": "office-version-invalid"},
        {"targetObjectId": TARGET_OBJECT, "targetVersionId": TARGET_VERSION, "title": "leak"},
    ):
        invalid = referenced_document()
        invalid["content"][0]["content"][0]["marks"][0]["attrs"] = attrs
        with pytest.raises(OfficeDocumentInvalidContentError):
            validate_office_document(invalid)

    for conflicting in ("link", "crossReference"):
        invalid = referenced_document()
        attrs = {"href": "https://example.com"} if conflicting == "link" else {"targetId": "bookmark"}
        invalid["content"][0]["content"][0]["marks"].append({"type": conflicting, "attrs": attrs})
        with pytest.raises(OfficeDocumentInvalidContentError):
            validate_office_document(invalid)

    excessive = referenced_document()
    excessive["content"] = [deepcopy(excessive["content"][0]) for _ in range(101)]
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(excessive)


def test_outbound_reference_resolution_uses_fresh_target_acl_and_exact_version(office: Any) -> None:
    service, repository, user = office
    target = service.create(
        user_context=user,
        write_enabled=True,
        command=OfficeDocumentCreateCommand(
            title="Historical target title",
            document=document_text("target body"),
            mutation_reference="reference-target",
            human_confirmation=True,
        ),
    )
    target_id = target.document.object_id
    user.readable_object_ids.add(target_id)
    source_content = referenced_document(target_id, target.version.version_id)
    source = service.create(
        user_context=user,
        write_enabled=True,
        command=OfficeDocumentCreateCommand(
            title="Source title",
            document=source_content,
            mutation_reference="reference-source",
            human_confirmation=True,
        ),
    )
    source_id = source.document.object_id
    user.readable_object_ids.add(source_id)

    result = service.outbound_references(user_context=user, object_id=source_id)
    assert result.source_version_id == source.version.version_id
    assert result.content_included is False
    assert result.references[0].model_dump() == {
        "target_object_id": target_id,
        "target_version_id": target.version.version_id,
        "status": "resolved",
        "title": "Historical target title",
        "is_current_version": True,
    }

    del repository.grants[(user.tenant_id, target_id, user.user_id)]
    user.readable_object_ids.discard(target_id)
    unavailable = service.outbound_references(user_context=user, object_id=source_id)
    assert unavailable.references[0].model_dump() == {
        "target_object_id": target_id,
        "target_version_id": target.version.version_id,
        "status": "unavailable",
        "title": None,
        "is_current_version": None,
    }
    audit = canonical_json([event.model_dump(mode="json") for event in service.audit.events])
    assert "Historical target title" not in audit and "target body" not in audit
    assert service.audit.events[-1].metadata["resolved_count"] == 0


def test_backlinks_are_exact_current_source_version_acl_safe_and_title_free_in_audit(office: Any) -> None:
    service, repository, user = office
    target = service.create(
        user_context=user,
        write_enabled=True,
        command=OfficeDocumentCreateCommand(
            title="Target v1",
            document=document_text("target one"),
            mutation_reference="backlink-target-create",
            human_confirmation=True,
        ),
    )
    target_id = target.document.object_id
    user.readable_object_ids.add(target_id)
    target_v2 = service.save(
        user_context=user,
        object_id=target_id,
        write_enabled=True,
        command=OfficeDocumentSaveCommand(
            title="Target v2",
            document=document_text("target two"),
            mutation_reference="backlink-target-save",
            human_confirmation=True,
            expected_current_version_id=target.version.version_id,
        ),
    )

    source_v1_content = referenced_document(target_id, target.version.version_id)
    source_v1_content["content"].append(deepcopy(source_v1_content["content"][0]))
    source_v1 = service.create(
        user_context=user,
        write_enabled=True,
        command=OfficeDocumentCreateCommand(
            title="Readable backlink source",
            document=source_v1_content,
            mutation_reference="backlink-source-v1",
            human_confirmation=True,
        ),
    )
    source_v2 = service.create(
        user_context=user,
        write_enabled=True,
        command=OfficeDocumentCreateCommand(
            title="Other target version source",
            document=referenced_document(target_id, target_v2.version.version_id),
            mutation_reference="backlink-source-v2",
            human_confirmation=True,
        ),
    )
    hidden = service.create(
        user_context=user,
        write_enabled=True,
        command=OfficeDocumentCreateCommand(
            title="Hidden backlink source",
            document=referenced_document(target_id, target.version.version_id),
            mutation_reference="backlink-source-hidden",
            human_confirmation=True,
        ),
    )
    for source_id in (source_v1.document.object_id, source_v2.document.object_id, hidden.document.object_id):
        user.readable_object_ids.add(source_id)
    del repository.grants[(user.tenant_id, hidden.document.object_id, user.user_id)]
    user.readable_object_ids.discard(hidden.document.object_id)

    result = service.backlinks(
        user_context=user,
        object_id=target_id,
        version_id=target.version.version_id,
    )
    assert [backlink.model_dump() for backlink in result.backlinks] == [
        {
            "source_object_id": source_v1.document.object_id,
            "source_version_id": source_v1.version.version_id,
            "title": "Readable backlink source",
            "reference_count": 2,
        }
    ]
    assert result.content_included is False
    assert result.target_version_id == target.version.version_id
    assert result.has_more is False and result.next_cursor is None
    assert "Hidden backlink source" not in canonical_json(result.model_dump(mode="json"))
    audit = canonical_json([event.model_dump(mode="json") for event in service.audit.events])
    assert "Readable backlink source" not in audit and "Hidden backlink source" not in audit

    del repository.grants[(user.tenant_id, source_v1.document.object_id, user.user_id)]
    user.readable_object_ids.discard(source_v1.document.object_id)
    assert (
        service.backlinks(
            user_context=user,
            object_id=target_id,
            version_id=target.version.version_id,
        ).backlinks
        == []
    )

    del repository.grants[(user.tenant_id, target_id, user.user_id)]
    user.readable_object_ids.discard(target_id)
    with pytest.raises(OfficeDocumentNotFoundError):
        service.backlinks(user_context=user, object_id=target_id, version_id=target.version.version_id)


def test_backlink_pages_use_target_bound_tamper_evident_cursors(office: Any) -> None:
    service, _, user = office
    target = service.create(
        user_context=user,
        write_enabled=True,
        command=OfficeDocumentCreateCommand(
            title="Paged target",
            document=document_text("target"),
            mutation_reference="paged-backlink-target",
            human_confirmation=True,
        ),
    )
    user.readable_object_ids.add(target.document.object_id)
    for index in range(3):
        source = service.create(
            user_context=user,
            write_enabled=True,
            command=OfficeDocumentCreateCommand(
                title=f"Paged source {index}",
                document=referenced_document(target.document.object_id, target.version.version_id),
                mutation_reference=f"paged-backlink-source-{index}",
                human_confirmation=True,
            ),
        )
        user.readable_object_ids.add(source.document.object_id)

    first = service.backlinks(user_context=user, object_id=target.document.object_id, page_size=1)
    assert len(first.backlinks) == 1 and first.has_more and first.next_cursor
    second = service.backlinks(
        user_context=user,
        object_id=target.document.object_id,
        page_size=1,
        cursor=first.next_cursor,
    )
    assert len(second.backlinks) == 1
    assert second.backlinks[0].source_object_id != first.backlinks[0].source_object_id
    with pytest.raises(OfficeDocumentListRequestError):
        service.backlinks(
            user_context=user,
            object_id=target.document.object_id,
            page_size=1,
            cursor=f"{first.next_cursor}x",
        )
