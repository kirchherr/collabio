from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.platform.office_import_preview import OfficeImportPreviewInvalid, OfficeImportPreviewService
from suite.rag.parser_worker import ParsedTextArtifact, ParserWorkerRequest, hash_document_blocks
from suite.rag.rich_document_parser import DOCX_MIME_TYPE, RichDocumentParserWorker
from suite.storage.source_objects import InMemorySourceObjectRepository
from test_office_import_preview import command, source_record, user
from test_rich_document_parser import request_for
from work_e2e_docx import FIRST_SECTION, LAST_SECTION, section_docx, synthetic_docx

FIRST_PAGE = {"paper": "a4", "orientation": "portrait", "margins": {"top": 20, "right": 12, "bottom": 22, "left": 14}}
LAST_PAGE: dict[str, Any] = {
    "paper": "letter",
    "orientation": "landscape",
    "margins": {"top": 18, "right": 16, "bottom": 20, "left": 18},
    "columns": "two",
}
PARAGRAPH = "<w:p><w:r><w:t>Text</w:t></w:r></w:p>"
BOUNDARY = f"<w:p><w:pPr>{FIRST_SECTION}</w:pPr><w:r><w:t>Text</w:t></w:r></w:p>"


def preview_service(content: bytes) -> OfficeImportPreviewService:
    return OfficeImportPreviewService(
        source_repository=InMemorySourceObjectRepository((source_record(content),)),
        audit=InMemoryAuditLogger(),
        parser_dispatch=RichDocumentParserWorker().parse,
    )


def test_docx_transposes_ending_section_properties_into_starting_profiles() -> None:
    content = section_docx()
    artifact = RichDocumentParserWorker().parse(request_for(mime_type=DOCX_MIME_TYPE, content=content))
    assert artifact.text == "Erster Abschnitt auf A4\nZweiter Abschnitt auf Letter"
    assert [block["kind"] for block in artifact.document_blocks] == [
        "page_profile",
        "paragraph",
        "section_break",
        "paragraph",
    ]
    assert artifact.document_blocks[0]["page"] == FIRST_PAGE
    assert artifact.document_blocks[2]["page"] == LAST_PAGE
    assert artifact.document_blocks_hash == hash_document_blocks(artifact.document_blocks)
    preview = preview_service(content).preview(user_context=user(), command=command())
    assert preview.document["attrs"]["page"] == FIRST_PAGE
    assert preview.document["attrs"]["importProvenance"]["parserStructureHash"] == artifact.document_blocks_hash
    assert preview.document["content"][1] == {
        "type": "sectionBreak",
        "attrs": {"page": LAST_PAGE, "running": {"header": "", "footer": "", "numbering": "none"}},
    }


@pytest.mark.parametrize("section,expected", [("", None), ("<w:sectPr/>", None), (FIRST_SECTION, FIRST_PAGE)])
def test_docx_single_section_preserves_only_an_explicit_profile(section: str, expected: Any) -> None:
    preview = preview_service(synthetic_docx(body=PARAGRAPH + section)).preview(user_context=user(), command=command())
    assert preview.document["attrs"].get("page") == expected
    assert [node["type"] for node in preview.document["content"]] == ["paragraph"]


@pytest.mark.parametrize(
    "body",
    [
        BOUNDARY + PARAGRAPH,
        BOUNDARY + PARAGRAPH + "<w:sectPr/>",
        PARAGRAPH + FIRST_SECTION + PARAGRAPH,
        PARAGRAPH + FIRST_SECTION + LAST_SECTION,
        "<w:tbl><w:tr><w:tc>" + BOUNDARY + "</w:tc></w:tr></w:tbl>",
        BOUNDARY * 13 + PARAGRAPH + LAST_SECTION,
        PARAGRAPH + FIRST_SECTION.replace('w:w="11906"', 'w:w="11990"'),
        PARAGRAPH + FIRST_SECTION.replace('w:top="1134"', 'w:top="-1134"'),
        PARAGRAPH + FIRST_SECTION.replace('w:right="680"', 'w:right="2836"'),
        PARAGRAPH + FIRST_SECTION.replace('w:gutter="0"', 'w:gutter="720"'),
        PARAGRAPH + LAST_SECTION.replace('w:orient="landscape"', 'w:orient="portrait"'),
        PARAGRAPH + LAST_SECTION.replace("nextPage", "continuous"),
        PARAGRAPH + LAST_SECTION.replace("nextPage", "oddPage"),
        PARAGRAPH + LAST_SECTION.replace('w:num="2"', 'w:num="4"'),
        PARAGRAPH + LAST_SECTION.replace('w:equalWidth="1"', 'w:equalWidth="0"'),
        PARAGRAPH + LAST_SECTION.replace('w:space="720"', 'w:space="100"'),
        PARAGRAPH + LAST_SECTION.replace("</w:sectPr>", '<w:pgNumType w:start="2"/></w:sectPr>'),
        PARAGRAPH + LAST_SECTION.replace("</w:sectPr>", "<w:headerReference/></w:sectPr>"),
        PARAGRAPH + LAST_SECTION.replace("</w:sectPr>", "<w:sectPrChange/></w:sectPr>"),
        PARAGRAPH + LAST_SECTION.replace("</w:sectPr>", "<w:pgSz/></w:sectPr>"),
    ],
)
def test_unsupported_docx_section_refuses_office_preview_without_losing_extracted_text(body: str) -> None:
    content = synthetic_docx(body=body)
    artifact = RichDocumentParserWorker().parse(request_for(mime_type=DOCX_MIME_TYPE, content=content))
    assert artifact.text.startswith("Text")
    assert artifact.document_blocks[0] == {"kind": "unsupported_section_layout"}
    with pytest.raises(OfficeImportPreviewInvalid, match="unsupported block"):
        preview_service(content).preview(user_context=user(), command=command())


@pytest.mark.parametrize(
    "body",
    [
        BOUNDARY + LAST_SECTION,
        BOUNDARY + "<w:p><w:pPr>" + FIRST_SECTION + "</w:pPr></w:p>" + PARAGRAPH + LAST_SECTION,
        BOUNDARY + '<w:p><w:r><w:br w:type="page"/><w:t>Text</w:t></w:r></w:p>' + LAST_SECTION,
        BOUNDARY + "<w:p><w:pPr><w:pageBreakBefore/></w:pPr><w:r><w:t>Text</w:t></w:r></w:p>" + LAST_SECTION,
    ],
)
def test_docx_section_boundaries_cannot_produce_empty_or_duplicate_page_starts(body: str) -> None:
    with pytest.raises(OfficeImportPreviewInvalid):
        preview_service(synthetic_docx(body=body)).preview(user_context=user(), command=command())


def test_import_api_independently_rejects_out_of_range_hash_bound_section_geometry() -> None:
    content = section_docx()

    def forged_parser(request: ParserWorkerRequest) -> ParsedTextArtifact:
        artifact = RichDocumentParserWorker().parse(request)
        first, second, marker, final = artifact.document_blocks
        forged = {**marker, "page": {**LAST_PAGE, "margins": {**LAST_PAGE["margins"], "top": 51}}}
        blocks = (first, second, forged, final)
        return replace(artifact, document_blocks=blocks, document_blocks_hash=hash_document_blocks(blocks))

    service = OfficeImportPreviewService(
        source_repository=InMemorySourceObjectRepository((source_record(content),)),
        audit=InMemoryAuditLogger(),
        parser_dispatch=forged_parser,
    )
    with pytest.raises(OfficeImportPreviewInvalid, match="represented as a native preview"):
        service.preview(user_context=user(), command=command())
