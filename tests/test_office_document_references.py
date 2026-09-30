from copy import deepcopy

import pytest

from suite.ai_control_plane.audit import canonical_json
from suite.platform.office_document_schema import (
    OfficeDocumentInvalidContentError,
    office_document_references,
    validate_office_document,
)
from suite.platform.office_documents import OfficeDocumentCreateCommand
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


def test_document_reference_schema_is_bounded_exact_and_deduplicated() -> None:
    document = referenced_document()
    document["content"].append(deepcopy(document["content"][0]))
    assert validate_office_document(document) is document
    assert office_document_references(document) == ((TARGET_OBJECT, TARGET_VERSION),)

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


def test_outbound_reference_resolution_uses_fresh_target_acl_and_exact_version(office) -> None:
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
