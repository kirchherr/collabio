from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from docx_navigation_fixture import (
    LINK,
    NAVIGATION_BODY,
    POINT,
    RELATIONSHIP,
    TARGET_END,
    TARGET_START,
    navigation_docx,
)
from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.platform.office_import_preview import OfficeImportPreviewInvalid, OfficeImportPreviewService
from suite.rag.parser_worker import ParsedTextArtifact, ParserWorkerRequest, hash_document_blocks
from suite.rag.rich_document_parser import DOCX_MIME_TYPE, RichDocumentParserWorker
from suite.storage.source_objects import InMemorySourceObjectRepository
from test_office_import_preview import command, source_record, user
from test_rich_document_parser import request_for

BODY_TEXT = "Zum Ziel springen\nNur lesbarer Fremdlink\nDokumentziel\nAbschluss"
TARGET = {"type": "crossReference", "attrs": {"targetId": "docx-bookmark-7"}}


def _artifact(content: bytes) -> ParsedTextArtifact:
    return RichDocumentParserWorker().parse(request_for(mime_type=DOCX_MIME_TYPE, content=content))


def _preview(content: bytes) -> dict[str, Any]:
    service = OfficeImportPreviewService(
        source_repository=InMemorySourceObjectRepository((source_record(content),)),
        audit=InMemoryAuditLogger(),
        parser_dispatch=RichDocumentParserWorker().parse,
    )
    return service.preview(user_context=user(), command=command()).document


def test_docx_preserves_bookmark_order_forward_link_marks_and_inert_external_text() -> None:
    content = navigation_docx()
    artifact = _artifact(content)
    assert artifact.text == BODY_TEXT
    changed = _artifact(navigation_docx(NAVIGATION_BODY.replace('w:id="7"', 'w:id="8"')))
    assert artifact.text_hash == changed.text_hash
    assert artifact.document_blocks_hash != changed.document_blocks_hash
    native = _preview(content)
    first, external, heading, final = native["content"]
    assert first["content"] == [
        {"type": "bookmark", "attrs": {"id": "docx-bookmark-1", "label": "Start_Point"}},
        {"type": "text", "text": "Zum Ziel", "marks": [{"type": "bold"}, TARGET]},
        {"type": "text", "text": " springen", "marks": [TARGET]},
    ]
    assert external["content"] == [{"type": "text", "text": "Nur lesbarer Fremdlink"}]
    assert heading["type"] == "heading"
    assert heading["content"][0] == {"type": "bookmark", "attrs": {"id": "docx-bookmark-7", "label": "Section_Target"}}
    assert final["content"] == [{"type": "text", "text": "Abschluss"}]


def test_docx_preserves_a_bookmark_only_paragraph_without_inserting_a_body_text_line() -> None:
    body = NAVIGATION_BODY.replace(POINT, "").replace(
        "</w:hyperlink></w:p>", f"</w:hyperlink></w:p><w:p>{POINT}</w:p>", 1
    )
    content = navigation_docx(body)
    assert _artifact(content).text == BODY_TEXT
    assert _preview(content)["content"][1]["content"] == [
        {"type": "bookmark", "attrs": {"id": "docx-bookmark-1", "label": "Start_Point"}}
    ]


@pytest.mark.parametrize(
    "body",
    [
        NAVIGATION_BODY.replace(TARGET_END, ""),
        NAVIGATION_BODY.replace(TARGET_END, TARGET_END * 2),
        NAVIGATION_BODY.replace(TARGET_START, TARGET_START.replace('w:id="7"', 'w:id="1"')),
        NAVIGATION_BODY.replace('w:name="Start_Point"', 'w:name="section_target"'),
        NAVIGATION_BODY.replace('w:id="7"', 'w:id="07"'),
        NAVIGATION_BODY.replace('w:name="Section_Target"', 'w:name="Section Target"'),
        NAVIGATION_BODY.replace(TARGET_START, TARGET_END).replace(
            f"Dokumentziel</w:t></w:r>{TARGET_END}", f"Dokumentziel</w:t></w:r>{TARGET_START}"
        ),
        NAVIGATION_BODY.replace(TARGET_END + "</w:p>", "</w:p><w:p>" + TARGET_END + "</w:p>"),
        NAVIGATION_BODY.replace(POINT, "").replace(TARGET_START, TARGET_START + POINT),
        NAVIGATION_BODY.replace('w:anchor="Section_Target"', 'w:anchor="section_target"'),
        NAVIGATION_BODY.replace('w:anchor="Section_Target"', 'w:anchor="_GoBack"'),
        NAVIGATION_BODY.replace('w:anchor="Section_Target"', 'w:anchor="https://example.invalid/"'),
        NAVIGATION_BODY.replace(
            'w:anchor="Section_Target"', f'xmlns:r="{RELATIONSHIP}" r:id="rIdExternal" w:anchor="Section_Target"'
        ),
        NAVIGATION_BODY.replace(LINK, f"<w:smartTag>{LINK}</w:smartTag>"),
        NAVIGATION_BODY.replace(LINK, "<w:fldSimple w:instr='REF Section_Target'/>" + LINK),
        NAVIGATION_BODY.replace("Zum Ziel</w:t>", "Zum Ziel</w:t><w:br/>"),
        NAVIGATION_BODY.replace("<w:b/>", "<w:vanish/>"),
        NAVIGATION_BODY.replace(
            f"<w:p>{POINT}{LINK}</w:p>", f"<w:tbl><w:tr><w:tc><w:p>{POINT}{LINK}</w:p></w:tc></w:tr></w:tbl>"
        ),
    ],
)
def test_ambiguous_docx_navigation_preserves_body_extraction_but_refuses_preview(body: str) -> None:
    content = navigation_docx(body)
    assert "Dokumentziel" in _artifact(content).text
    assert _artifact(content).document_blocks[0] == {"kind": "unsupported_navigation"}
    with pytest.raises(OfficeImportPreviewInvalid, match="unsupported block"):
        _preview(content)


def test_docx_navigation_count_limits_fail_closed() -> None:
    extra_bookmarks = "".join(
        f'<w:bookmarkStart w:id="{index}" w:name="Bookmark_{index}"/><w:bookmarkEnd w:id="{index}"/>'
        for index in range(100, 199)
    )
    repeated_links = '<w:hyperlink w:anchor="Section_Target">' + "<w:r><w:t>x</w:t></w:r>" * 201 + "</w:hyperlink>"
    for body in (
        NAVIGATION_BODY.replace(POINT, POINT + extra_bookmarks),
        NAVIGATION_BODY.replace(LINK, repeated_links),
    ):
        with pytest.raises(OfficeImportPreviewInvalid, match="unsupported block"):
            _preview(navigation_docx(body))


def test_bookmark_points_do_not_reduce_the_existing_body_run_extraction_limit() -> None:
    body = f"<w:p>{POINT}" + "<w:r><w:t>x</w:t></w:r>" * 4000 + "</w:p>"
    content = navigation_docx(body)
    assert _artifact(content).text == "x" * 4000
    with pytest.raises(OfficeImportPreviewInvalid, match="inline structure"):
        _preview(content)


def test_preview_rejects_a_missing_bookmark_in_rehashed_parser_evidence() -> None:
    content = navigation_docx()

    def parser(request: ParserWorkerRequest) -> ParsedTextArtifact:
        artifact = RichDocumentParserWorker().parse(request)
        first, *rest = artifact.document_blocks
        blocks = ({**first, "runs": [{"text": "Zum Ziel springen", "marks": [], "target": "docx-bookmark-99"}]}, *rest)
        return replace(artifact, document_blocks=blocks, document_blocks_hash=hash_document_blocks(blocks))

    service = OfficeImportPreviewService(
        source_repository=InMemorySourceObjectRepository((source_record(content),)),
        audit=InMemoryAuditLogger(),
        parser_dispatch=parser,
    )
    with pytest.raises(OfficeImportPreviewInvalid, match="internal link targets"):
        service.preview(user_context=user(), command=command())
