from __future__ import annotations

from dataclasses import replace

import pytest

from docx_paragraph_alignment_fixture import literal, paragraph
from docx_paragraph_pagination_fixture import lines, paragraph_pagination_docx
from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.platform.office_import_preview import OfficeImportPreviewInvalid, OfficeImportPreviewService
from suite.rag.parser_worker import ParsedTextArtifact, ParserWorkerRequest, hash_document_blocks
from suite.rag.rich_document_parser import RichDocumentParserWorker
from suite.storage.source_objects import InMemorySourceObjectRepository
from test_office_docx_table_spans import _artifact, _preview
from test_office_import_preview import command, source_record, user
from work_e2e_docx import synthetic_docx


def test_paragraph_pagination_maps_true_false_and_preserves_heading_and_page_break() -> None:
    source = paragraph_pagination_docx()
    artifact = _artifact(source)
    assert artifact.document_blocks_hash == hash_document_blocks(artifact.document_blocks)
    nodes = _preview(source)["content"]
    assert nodes[0]["attrs"] == {"level": 1, "keepWithNext": False, "keepLines": False}
    assert nodes[1]["attrs"] == {"pageBreakBefore": True}
    assert nodes[5]["attrs"] == {"level": 2, "keepWithNext": True}
    assert nodes[6]["attrs"] == {"keepWithNext": False, "keepLines": True}
    assert "CONTROL-LINE-08" in artifact.text
    assert artifact.text.endswith("KEPT-LINE-08")


@pytest.mark.parametrize("name", ["keepNext", "keepLines"])
@pytest.mark.parametrize(
    ("value", "enabled"), [("true", True), ("1", True), ("on", True), ("false", False), ("0", False), ("off", False)]
)
def test_boolean_spellings_have_canonical_evidence(name: str, value: str, enabled: bool) -> None:
    source = synthetic_docx(body=lines("Text", f'<w:{name} w:val="{value}"/>'))
    canonical = f"<w:{name}/>" if enabled else f'<w:{name} w:val="false"/>'
    assert _artifact(source).document_blocks == _artifact(synthetic_docx(body=lines("Text", canonical))).document_blocks
    absent = _artifact(synthetic_docx(body=lines("Text"))).document_blocks
    assert _artifact(source).document_blocks != absent


@pytest.mark.parametrize("name", ["keepNext", "keepLines"])
@pytest.mark.parametrize(
    "marker",
    [
        '<w:{name} w:val="maybe"/>',
        '<w:{name} w:val="2"/>',
        '<w:{name} w:val="true" w:other="1"/>',
        "<w:{name}>text</w:{name}>",
        "<w:{name}><w:{name}/></w:{name}>",
        "<w:{name}/><w:{name}/>",
        "</w:pPr><w:{name}/><w:pPr>",
    ],
)
def test_malformed_pagination_refuses_preview_while_text_extraction_stays_available(name: str, marker: str) -> None:
    source = synthetic_docx(body=lines("Lesbarer Text", marker.format(name=name)))
    assert _artifact(source).text == "Lesbarer Text"
    assert _artifact(source).document_blocks[0] == {"kind": "unsupported_paragraph_pagination"}
    with pytest.raises(OfficeImportPreviewInvalid, match="unsupported block"):
        _preview(source)


def test_pagination_keeps_existing_format_and_refuses_inline_page_breaks() -> None:
    source = synthetic_docx(
        body=paragraph(
            literal("Text"),
            alignment="center",
            other_properties='<w:spacing w:after="120"/><w:ind w:left="360"/><w:keepLines/><w:pageBreakBefore/>',
        )
    )
    assert _preview(source)["content"][0]["attrs"] == {
        "textAlign": "center",
        "spacingAfter": 6,
        "indentLeft": 18,
        "keepLines": True,
        "pageBreakBefore": True,
    }
    split = synthetic_docx(
        body=paragraph(
            literal("Vorher") + '<w:r><w:br w:type="page"/></w:r>' + literal("Nachher"),
            other_properties="<w:keepLines/>",
        )
    )
    assert _artifact(split).text == "Vorher\nNachher"
    with pytest.raises(OfficeImportPreviewInvalid, match="unsupported block"):
        _preview(split)


@pytest.mark.parametrize("field", ["keep_with_next", "keep_lines"])
@pytest.mark.parametrize("marker", [0, 1, "true", None, []])
def test_api_refuses_nonboolean_pagination_even_with_matching_structure_hash(field: str, marker: object) -> None:
    source = paragraph_pagination_docx()

    def parser(request: ParserWorkerRequest) -> ParsedTextArtifact:
        artifact = RichDocumentParserWorker().parse(request)
        first, *rest = artifact.document_blocks
        blocks = ({**first, field: marker}, *rest)
        return replace(artifact, document_blocks=blocks, document_blocks_hash=hash_document_blocks(blocks))

    service = OfficeImportPreviewService(
        source_repository=InMemorySourceObjectRepository((source_record(source),)),
        audit=InMemoryAuditLogger(),
        parser_dispatch=parser,
    )
    with pytest.raises(OfficeImportPreviewInvalid, match="paragraph pagination is invalid"):
        service.preview(user_context=user(), command=command())
