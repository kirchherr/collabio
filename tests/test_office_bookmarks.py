from __future__ import annotations

import pytest

from suite.platform.office_document_schema import OfficeDocumentInvalidContentError, validate_office_document


def document(*, bookmarks: list[tuple[str, str]], target: str | None = None) -> dict[str, object]:
    content: list[dict[str, object]] = []
    for identifier, label in bookmarks:
        content.append({"type": "bookmark", "attrs": {"id": identifier, "label": label}})
        content.append({"type": "text", "text": "Target"})
    reference: dict[str, object] = {"type": "text", "text": "See target"}
    if target is not None:
        reference["marks"] = [{"type": "crossReference", "attrs": {"targetId": target}}]
    content.append(reference)
    return {"type": "doc", "content": [{"type": "paragraph", "content": content}]}


def test_office_bookmarks_accept_stable_targets_and_explicit_broken_references() -> None:
    linked = document(bookmarks=[("bookmark-overview", "Overview")], target="bookmark-overview")
    assert validate_office_document(linked) == linked
    broken = document(bookmarks=[], target="bookmark-removed")
    assert validate_office_document(broken) == broken


@pytest.mark.parametrize(
    "identifier,label",
    [
        ("Bookmark", "Overview"),
        ("1-bookmark", "Overview"),
        ("bookmark space", "Overview"),
        ("bookmark-" + "x" * 48, "Overview"),
        ("bookmark", ""),
        ("bookmark", " Overview"),
        ("bookmark", "x" * 65),
        ("bookmark", "bad\nlabel"),
    ],
)
def test_office_bookmarks_reject_ambiguous_identifiers_and_labels(identifier: str, label: str) -> None:
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(document(bookmarks=[(identifier, label)]))


def test_office_bookmarks_require_unique_ids_and_casefolded_labels() -> None:
    for bookmarks in (
        [("bookmark-one", "One"), ("bookmark-one", "Two")],
        [("bookmark-one", "Overview"), ("bookmark-two", "overview")],
    ):
        with pytest.raises(OfficeDocumentInvalidContentError):
            validate_office_document(document(bookmarks=bookmarks))


def test_office_bookmarks_enforce_count_and_exact_node_shape() -> None:
    validate_office_document(
        document(bookmarks=[(f"bookmark-{number}", f"Bookmark {number}") for number in range(100)])
    )
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(
            document(bookmarks=[(f"bookmark-{number}", f"Bookmark {number}") for number in range(101)])
        )
    malformed = document(bookmarks=[("bookmark-one", "One")])
    malformed["content"][0]["content"][0]["attrs"]["extra"] = True  # type: ignore[index]
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(malformed)


def test_office_cross_references_require_exact_target_and_exclude_links_and_code() -> None:
    for mark in (
        {"type": "crossReference"},
        {"type": "crossReference", "attrs": {}},
        {"type": "crossReference", "attrs": {"targetId": "Bookmark"}},
        {"type": "crossReference", "attrs": {"targetId": "bookmark-one", "extra": True}},
    ):
        value = document(bookmarks=[("bookmark-one", "One")])
        value["content"][0]["content"][-1]["marks"] = [mark]  # type: ignore[index]
        with pytest.raises(OfficeDocumentInvalidContentError):
            validate_office_document(value)
    for other in ("link", "code"):
        value = document(bookmarks=[("bookmark-one", "One")], target="bookmark-one")
        mark: dict[str, object] = {"type": other}
        if other == "link":
            mark["attrs"] = {"href": "https://example.org/"}
        value["content"][0]["content"][-1]["marks"].append(mark)  # type: ignore[index]
        with pytest.raises(OfficeDocumentInvalidContentError):
            validate_office_document(value)
