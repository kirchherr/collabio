from copy import deepcopy
from hashlib import sha256
from typing import Any

import pytest

from suite.ai_control_plane.audit import InMemoryAuditLogger, canonical_json
from suite.ai_control_plane.models import UserContext
from suite.platform.office_api import build_office_suggestion_service
from suite.platform.office_document_repository import InMemoryOfficeDocumentRepository
from suite.platform.office_document_schema import OfficeDocumentInvalidContentError, validate_office_document
from suite.platform.office_documents import OfficeDocumentCreateCommand, OfficeDocumentService
from suite.platform.office_reviews import ReviewAnchor, derive_review_quote
from suite.platform.office_suggestions import (
    SuggestionCreateCommand,
    SuggestionDecisionCommand,
    replace_suggestion_text,
)
from suite.storage.source_objects import InMemorySourceObjectRepository, source_object_content_bytes

FORMAT: dict[str, Any] = {"textAlign": "justify", "lineSpacing": "1.5", "spacingBefore": 6, "spacingAfter": 12}


def formatted_document() -> dict[str, Any]:
    return {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "attrs": dict(FORMAT),
                "content": [
                    {"type": "text", "text": "A😀 ", "marks": [{"type": "bold"}]},
                    {"type": "text", "text": "café PRIVATE"},
                ],
            },
            {"type": "heading", "attrs": {"level": 2, "textAlign": "center", "spacingAfter": 0}, "content": []},
        ],
    }


@pytest.mark.parametrize(
    "key,value",
    [("textAlign", value) for value in ("left", "center", "right", "justify")]
    + [("lineSpacing", value) for value in ("1", "1.15", "1.5", "2")]
    + [(key, value) for key in ("spacingBefore", "spacingAfter") for value in (0, 6, 12, 18, 24)],
)
@pytest.mark.parametrize("kind", ["paragraph", "heading"])
def test_paragraph_formatting_accepts_only_declared_values_without_normalization(
    key: str, value: Any, kind: str
) -> None:
    attrs = {key: value, **({"level": 1} if kind == "heading" else {})}
    document: dict[str, Any] = {"type": "doc", "content": [{"type": kind, "attrs": attrs}]}
    before = deepcopy(document)
    assert validate_office_document(document) is document
    assert document == before
    assert document["content"][0]["attrs"][key] == value


@pytest.mark.parametrize(
    "attrs",
    [
        {"textAlign": None},
        {"textAlign": "default"},
        {"textAlign": "start"},
        {"textAlign": []},
        {"textAlign": "center;color:red"},
        {"lineSpacing": 1},
        {"lineSpacing": 1.5},
        {"lineSpacing": True},
        {"lineSpacing": "normal"},
        {"lineSpacing": "1.50"},
        {"lineSpacing": None},
        {"lineSpacing": "url(https://example.invalid)"},
        {"spacingBefore": True},
        {"spacingAfter": 6.0},
        {"spacingBefore": "6"},
        {"spacingAfter": None},
        {"spacingBefore": -6},
        {"spacingAfter": 25},
        {"spacingBefore": {}},
        {"style": "text-align:center"},
        {"alignment": "left"},
    ],
)
def test_paragraph_formatting_rejects_coercion_css_unknown_values_and_nulls(attrs: dict[str, Any]) -> None:
    for kind in ("paragraph", "heading"):
        document: dict[str, Any] = {
            "type": "doc",
            "content": [{"type": kind, "attrs": {**attrs, **({"level": 1} if kind == "heading" else {})}}],
        }
        with pytest.raises(OfficeDocumentInvalidContentError):
            validate_office_document(document)


@pytest.mark.parametrize("attrs", [{}, {"level": True}, {"level": 1.0}, {"level": "1"}, {"level": 4}])
def test_heading_still_requires_strict_supported_level(attrs: dict[str, Any]) -> None:
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document({"type": "doc", "content": [{"type": "heading", "attrs": {**FORMAT, **attrs}}]})


@pytest.mark.parametrize(
    "kind",
    [
        "doc",
        "text",
        "hardBreak",
        "codeBlock",
        "blockquote",
        "table",
        "tableRow",
        "tableCell",
        "tableHeader",
        "bulletList",
        "orderedList",
        "listItem",
        "horizontalRule",
    ],
)
def test_paragraph_attributes_remain_forbidden_on_other_node_types(kind: str) -> None:
    paragraph: dict[str, Any] = {"type": "paragraph"}
    node: dict[str, Any] = {"type": kind}
    if kind == "text":
        node["text"] = "text"
    elif kind in {"doc", "blockquote", "listItem", "tableCell", "tableHeader"}:
        node["content"] = [paragraph]
    elif kind in {"bulletList", "orderedList"}:
        node["content"] = [{"type": "listItem", "content": [paragraph]}]
    elif kind == "tableRow":
        node["content"] = [{"type": "tableCell", "content": [paragraph]}]
    elif kind == "table":
        node["content"] = [{"type": "tableRow", "content": [{"type": "tableCell", "content": [paragraph]}]}]
    wrapper = node
    if kind in {"text", "hardBreak"}:
        wrapper = {"type": "paragraph", "content": [node]}
    elif kind == "listItem":
        wrapper = {"type": "bulletList", "content": [node]}
    elif kind in {"tableCell", "tableHeader", "tableRow"}:
        wrapper = {
            "type": "table",
            "content": [node if kind == "tableRow" else {"type": "tableRow", "content": [node]}],
        }
    document = wrapper if kind == "doc" else {"type": "doc", "content": [wrapper]}
    validate_office_document(document)
    node["attrs"] = dict(FORMAT)
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(document)


def test_formatted_paragraphs_and_headings_are_valid_in_lists_quotes_and_cells() -> None:
    blocks = formatted_document()["content"]
    document: dict[str, Any] = {
        "type": "doc",
        "content": [
            {"type": "bulletList", "content": [{"type": "listItem", "content": deepcopy(blocks)}]},
            {"type": "blockquote", "content": deepcopy(blocks)},
            {
                "type": "table",
                "content": [
                    {
                        "type": "tableRow",
                        "content": [
                            {"type": "tableHeader", "content": deepcopy(blocks)},
                            {"type": "tableCell", "content": deepcopy(blocks)},
                        ],
                    }
                ],
            },
        ],
    }
    assert validate_office_document(document) == document


def test_legacy_canonical_bytes_and_hash_are_unchanged_including_explicit_empty_attributes() -> None:
    document: dict[str, Any] = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "é😀"}]},
            {"type": "paragraph", "attrs": {}},
            {"type": "heading", "attrs": {"level": 2}},
        ],
    }
    expected = (
        b'{"content":[{"content":[{"text":"\\u00e9\\ud83d\\ude00","type":"text"}],"type":"paragraph"},'
        b'{"attrs":{},"type":"paragraph"},{"attrs":{"level":2},"type":"heading"}],"type":"doc"}'
    )
    assert validate_office_document(document) is document
    assert canonical_json(document).encode("utf-8") == expected
    sources = InMemorySourceObjectRepository()
    service = OfficeDocumentService(
        repository=InMemoryOfficeDocumentRepository(source_repository=sources),
        source_repository=sources,
        audit=InMemoryAuditLogger(),
    )
    created = service.create(
        user_context=UserContext(tenant_id="legacy-format", user_id="editor", role_ids={"office-editor"}),
        write_enabled=True,
        command=OfficeDocumentCreateCommand(
            title="Legacy", document=document, mutation_reference="legacy", human_confirmation=True
        ),
    )
    stored = sources.get(
        tenant_id="legacy-format", object_id=created.document.object_id, version_id=created.version.version_id
    )
    assert source_object_content_bytes(stored) == expected
    assert created.version.content_hash == "sha256:" + sha256(expected).hexdigest()


def test_attribute_bytes_count_toward_existing_document_resource_limit() -> None:
    # Both variants have fewer than 10,000 nodes and no text. Only the allowed
    # formatting attributes make the canonical representation exceed 400 KB.
    plain = {"type": "doc", "content": [{"type": "paragraph"} for _ in range(4_000)]}
    assert validate_office_document(plain) is plain
    formatted = {"type": "doc", "content": [{"type": "paragraph", "attrs": dict(FORMAT)} for _ in range(4_000)]}
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(formatted)


def test_review_anchor_offsets_and_replacement_preserve_paragraph_formatting_and_marks() -> None:
    document = formatted_document()
    original = deepcopy(document)
    anchor = ReviewAnchor.model_validate({"from": 2, "to": 9})
    assert derive_review_quote(document, anchor) == "😀 café"
    replaced = replace_suggestion_text(document, anchor, "NEU")
    assert document == original
    assert replaced["content"][0]["attrs"] == FORMAT
    assert replaced["content"][1] == original["content"][1]
    assert replaced["content"][0]["content"] == [
        {"type": "text", "text": "A", "marks": [{"type": "bold"}]},
        {"type": "text", "text": "NEU", "marks": [{"type": "bold"}]},
        {"type": "text", "text": " PRIVATE"},
    ]


def test_accepting_saved_text_suggestion_preserves_formatting_and_immutable_anchor_version() -> None:
    sources = InMemorySourceObjectRepository()
    documents = OfficeDocumentService(
        repository=InMemoryOfficeDocumentRepository(source_repository=sources),
        source_repository=sources,
        audit=InMemoryAuditLogger(),
    )
    user = UserContext(tenant_id="formatted-suggestion", user_id="editor", role_ids={"office-editor"})
    created = documents.create(
        user_context=user,
        write_enabled=True,
        command=OfficeDocumentCreateCommand(
            title="Formatted", document=formatted_document(), mutation_reference="initial", human_confirmation=True
        ),
    )
    object_id = created.document.object_id
    user.readable_object_ids.add(object_id)
    service = build_office_suggestion_service(document_service=documents, audit=InMemoryAuditLogger())
    proposal = service.mutate(
        user_context=user,
        object_id=object_id,
        write_enabled=True,
        command=SuggestionCreateCommand(
            anchor_version_id=created.version.version_id,
            expected_current_version_id=created.version.version_id,
            anchor=ReviewAnchor.model_validate({"from": 5, "to": 9}),
            replacement_text="NEU",
            mutation_reference="propose",
            human_confirmation=True,
        ),
    )
    command = SuggestionDecisionCommand(
        operation="accept",
        expected_revision=1,
        expected_current_version_id=created.version.version_id,
        mutation_reference="accept",
        human_confirmation=True,
    )
    accepted = service.mutate(
        user_context=user,
        object_id=object_id,
        suggestion_id=proposal.suggestion.suggestion_id,
        write_enabled=True,
        command=command,
    )
    assert accepted.document_result is not None
    assert accepted.document_result.content["content"][0]["attrs"] == FORMAT
    assert accepted.document_result.version.previous_version_id == created.version.version_id
    assert accepted.document_result.version.content_hash != created.version.content_hash
    old = documents.read_content(user_context=user, object_id=object_id, version_id=created.version.version_id)
    assert old.content == formatted_document()
    replay = service.mutate(
        user_context=user,
        object_id=object_id,
        suggestion_id=proposal.suggestion.suggestion_id,
        write_enabled=True,
        command=command,
    )
    assert replay.replayed and replay.document_result is not None
    assert replay.document_result.version == accepted.document_result.version
    assert replay.document_result.content == accepted.document_result.content
    assert "PRIVATE" not in canonical_json([event.model_dump() for event in service.audit.events])
