from __future__ import annotations

from dataclasses import replace

import pytest

from docx_paragraph_alignment_fixture import literal, paragraph, paragraph_alignment_docx
from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.platform.office_import_preview import OfficeImportPreviewInvalid, OfficeImportPreviewService
from suite.rag.parser_worker import ParsedTextArtifact, ParserWorkerRequest, hash_document_blocks
from suite.rag.rich_document_parser import RichDocumentParserWorker
from suite.storage.source_objects import InMemorySourceObjectRepository
from test_office_docx_table_spans import _artifact, _preview
from test_office_import_preview import command, source_record, user
from work_e2e_docx import synthetic_docx


def test_direct_docx_alignment_maps_to_native_paragraphs_and_heading() -> None:
    source = paragraph_alignment_docx()
    artifact = _artifact(source)
    nodes = _preview(source)["content"]
    assert artifact.document_blocks_hash == hash_document_blocks(artifact.document_blocks)
    assert [block["text_align"] for block in artifact.document_blocks] == [
        "center",
        "left",
        "center",
        "right",
        "justify",
    ]
    assert nodes[0]["type"] == "heading"
    assert nodes[0]["attrs"]["level"] == 1
    assert [node["attrs"]["textAlign"] for node in nodes] == ["center", "left", "center", "right", "justify"]
    assert artifact.text.splitlines()[:4] == ["MITTEKOPF", "LINKSBELEG", "MITTEBELEG", "RECHTSBELEG"]


def test_alignment_survives_inline_and_paragraph_page_breaks() -> None:
    source = synthetic_docx(
        body=paragraph(literal("Vorher") + '<w:r><w:br w:type="page"/></w:r>' + literal("Nachher"), alignment="center")
        + paragraph(literal("Neue Seite"), alignment="right", other_properties="<w:pageBreakBefore/>")
    )
    before, page, after, next_page = _preview(source)["content"]
    assert page == {"type": "pageBreak"}
    assert before["attrs"] == after["attrs"] == {"textAlign": "center"}
    assert next_page["attrs"] == {"pageBreakBefore": True, "textAlign": "right"}


@pytest.mark.parametrize(
    "properties",
    [
        '<w:jc w:val="start"/>',
        '<w:jc w:val="distribute"/>',
        '<w:jc w:val="center"/><w:jc w:val="left"/>',
        "<w:jc/>",
        '<w:jc w:val="center"><w:jc/></w:jc>',
        '<w:jc w:val="center" w:other="1"/>',
        '</w:pPr><w:jc w:val="center"/><w:pPr>',
    ],
)
def test_unsupported_direct_alignment_keeps_extracted_text_but_refuses_preview(properties: str) -> None:
    source = synthetic_docx(body=paragraph(literal("Lesbarer Text"), other_properties=properties))
    artifact = _artifact(source)
    assert artifact.text == "Lesbarer Text"
    assert artifact.document_blocks[0] == {"kind": "unsupported_paragraph_alignment"}
    with pytest.raises(OfficeImportPreviewInvalid, match="unsupported block"):
        _preview(source)


@pytest.mark.parametrize("marker", [False, 1, "both", "center; color:red", [], None])
def test_api_rejects_forged_alignment_even_with_matching_structure_hash(marker: object) -> None:
    source = paragraph_alignment_docx()

    def parser(request: ParserWorkerRequest) -> ParsedTextArtifact:
        artifact = RichDocumentParserWorker().parse(request)
        first, *rest = artifact.document_blocks
        blocks = ({**first, "text_align": marker}, *rest)
        return replace(artifact, document_blocks=blocks, document_blocks_hash=hash_document_blocks(blocks))

    service = OfficeImportPreviewService(
        source_repository=InMemorySourceObjectRepository((source_record(source),)),
        audit=InMemoryAuditLogger(),
        parser_dispatch=parser,
    )
    with pytest.raises(OfficeImportPreviewInvalid, match="paragraph alignment is invalid"):
        service.preview(user_context=user(), command=command())
