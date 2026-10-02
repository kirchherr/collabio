from __future__ import annotations

import pytest

from suite.platform.office_document_schema import OfficeDocumentInvalidContentError, validate_office_document


def linked(href: str) -> dict[str, object]:
    return {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Reference", "marks": [{"type": "link", "attrs": {"href": href}}]}
                ],
            }
        ],
    }


@pytest.mark.parametrize(
    "href",
    ["https://example.org/", "https://docs.example.org/a?q=1#part", "mailto:name@example.org"],
)
def test_office_links_accept_only_bounded_explicit_safe_targets(href: str) -> None:
    assert validate_office_document(linked(href)) == linked(href)


@pytest.mark.parametrize(
    "href",
    [
        "http://example.org",
        "javascript:alert(1)",
        "data:text/html,x",
        "file:///tmp/x",
        "https://user:secret@example.org",
        "https://example.org\\evil",
        "mailto:a@example.org?subject=x",
        "mailto:a@example.org,b@example.org",
        "https://example.org/<x>",
    ],
)
def test_office_links_reject_unsafe_or_ambiguous_targets(href: str) -> None:
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(linked(href))


def test_office_links_require_exact_single_href_attribute_and_do_not_mix_with_code() -> None:
    for mark in (
        {"type": "link"},
        {"type": "link", "attrs": {}},
        {"type": "link", "attrs": {"href": "https://example.org/", "title": "x"}},
    ):
        document = linked("https://example.org/")
        document["content"][0]["content"][0]["marks"] = [mark]  # type: ignore[index]
        with pytest.raises(OfficeDocumentInvalidContentError):
            validate_office_document(document)
    document = linked("https://example.org/")
    document["content"][0]["content"][0]["marks"].append({"type": "code"})  # type: ignore[index]
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(document)
