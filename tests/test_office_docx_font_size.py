from __future__ import annotations

from dataclasses import replace

import pytest

from docx_font_size_fixture import font_size_docx, sized_run
from docx_list_fixture import item, list_docx
from docx_navigation_fixture import TARGET_END, TARGET_START
from docx_paragraph_alignment_fixture import literal, paragraph
from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.platform.office_document_schema import FONT_SIZES
from suite.platform.office_import_preview import OfficeImportPreviewInvalid, OfficeImportPreviewService
from suite.rag.parser_worker import ParsedTextArtifact, ParserWorkerRequest, hash_document_blocks
from suite.rag.rich_document_parser import RichDocumentParserWorker
from suite.storage.source_objects import InMemorySourceObjectRepository
from test_office_docx_table_spans import _artifact, _preview
from test_office_import_preview import command, source_record, user
from work_e2e_docx import synthetic_docx


@pytest.mark.parametrize("points", sorted(FONT_SIZES))
def test_direct_half_point_sizes_map_exactly_to_the_native_enum(points: int) -> None:
    source = synthetic_docx(body=paragraph(sized_run("Text", str(points * 2))))
    artifact = _artifact(source)
    assert artifact.text == "Text"
    assert artifact.document_blocks[0]["runs"][0]["font_size"] == points
    assert artifact.document_blocks_hash == hash_document_blocks(artifact.document_blocks)
    assert _preview(source)["content"][0]["content"][0]["marks"] == [
        {"type": "textStyle", "attrs": {"fontSize": points}}
    ]


def test_font_size_composes_with_inline_marks_headings_and_header_cells() -> None:
    nodes = _preview(font_size_docx())["content"]
    assert nodes[0]["type"] == "heading"
    assert nodes[2]["content"][0]["marks"] == [{"type": "bold"}, {"type": "textStyle", "attrs": {"fontSize": 12}}]
    header = nodes[5]["content"][0]["content"][0]
    assert header["type"] == "tableHeader"
    assert header["content"][0]["content"][0]["marks"] == [{"type": "textStyle", "attrs": {"fontSize": 14}}]
    matching = synthetic_docx(body=paragraph(sized_run("Text", "24", '<w:szCs w:val="24"/>')))
    simple = synthetic_docx(body=paragraph(sized_run("Text", "24")))
    assert _artifact(matching).document_blocks == _artifact(simple).document_blocks
    changed = _artifact(synthetic_docx(body=paragraph(sized_run("Text", "28"))))
    assert changed.text_hash == _artifact(simple).text_hash
    assert changed.document_blocks_hash != _artifact(simple).document_blocks_hash


def test_size_survives_list_runs_internal_links_and_page_break_segments() -> None:
    listed = list_docx(
        body=item("Listenbeleg", 0).replace("<w:r><w:t>Listenbeleg</w:t></w:r>", sized_run("Listenbeleg", "24"))
    )
    mark = _preview(listed)["content"][0]["content"][0]["content"][0]["content"][0]["marks"][0]
    assert mark == {"type": "textStyle", "attrs": {"fontSize": 12}}
    linked = synthetic_docx(
        body=paragraph(TARGET_START + sized_run("Ziel", "24") + TARGET_END)
        + paragraph('<w:hyperlink w:anchor="Section_Target">' + sized_run("Sprung", "32", "<w:i/>") + "</w:hyperlink>")
    )
    marks = _preview(linked)["content"][1]["content"][0]["marks"]
    assert marks[1] == {"type": "textStyle", "attrs": {"fontSize": 16}}
    assert marks[2]["type"] == "crossReference"
    split = synthetic_docx(
        body=paragraph(sized_run("Vorher", "24").replace("</w:r>", '<w:br w:type="page"/><w:t>Nachher</w:t></w:r>'))
    )
    before, page, after = _preview(split)["content"]
    assert page == {"type": "pageBreak"}
    assert before["content"][0]["marks"] == after["content"][0]["marks"]


@pytest.mark.parametrize("half_points", ["27", "12pt"])
def test_internal_link_size_is_checked_by_the_shared_size_parser(half_points: str) -> None:
    source = synthetic_docx(
        body=paragraph(TARGET_START + literal("Ziel") + TARGET_END)
        + paragraph('<w:hyperlink w:anchor="Section_Target">' + sized_run("Sprung", half_points) + "</w:hyperlink>")
    )
    assert _artifact(source).text == "Ziel\nSprung"
    with pytest.raises(OfficeImportPreviewInvalid, match="inline run is invalid"):
        _preview(source)


@pytest.mark.parametrize(
    "properties",
    [
        '<w:sz w:val="27"/>',
        '<w:sz w:val="0"/>',
        '<w:sz w:val="-24"/>',
        '<w:sz w:val="12pt"/>',
        '<w:sz w:val="1000000000000000000000"/>',
        "<w:sz/>",
        '<w:sz w:val="24"/><w:sz w:val="24"/>',
        '<w:sz w:val="24" w:other="1"/>',
        '<w:sz w:val="24"><w:sz/></w:sz>',
        '<w:szCs w:val="24"/>',
        '<w:sz w:val="24"/><w:szCs w:val="28"/>',
        '<w:sz w:val="24"/><w:cs/>',
        '<w:sz w:val="24"/><w:rtl/>',
        '</w:rPr><w:sz w:val="24"/><w:rPr>',
    ],
)
def test_unsupported_size_refuses_office_preview_without_losing_extracted_text(properties: str) -> None:
    source = synthetic_docx(body=paragraph(f"<w:r><w:rPr>{properties}</w:rPr><w:t>Lesbarer Text</w:t></w:r>"))
    artifact = _artifact(source)
    assert artifact.text == "Lesbarer Text"
    assert artifact.document_blocks[0]["runs"][0]["unsupported_font_size"] is True
    with pytest.raises(OfficeImportPreviewInvalid, match="inline run is invalid"):
        _preview(source)


@pytest.mark.parametrize("size", [True, 0, 13, 12.0, "12", None, []])
def test_api_rejects_forged_size_even_with_matching_structure_hash(size: object) -> None:
    source = synthetic_docx(body=paragraph(sized_run("Text", "24")))

    def parser(request: ParserWorkerRequest) -> ParsedTextArtifact:
        artifact = RichDocumentParserWorker().parse(request)
        block = artifact.document_blocks[0]
        block["runs"][0]["font_size"] = size
        return replace(artifact, document_blocks_hash=hash_document_blocks(artifact.document_blocks))

    service = OfficeImportPreviewService(
        source_repository=InMemorySourceObjectRepository((source_record(source),)),
        audit=InMemoryAuditLogger(),
        parser_dispatch=parser,
    )
    with pytest.raises(OfficeImportPreviewInvalid, match="parser font size is invalid"):
        service.preview(user_context=user(), command=command())
