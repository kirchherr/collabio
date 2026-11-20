from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from docx_font_family_fixture import FAMILIES, family_run, font_family_docx
from docx_list_fixture import item, list_docx
from docx_navigation_fixture import TARGET_END, TARGET_START
from docx_paragraph_alignment_fixture import literal, paragraph
from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.platform.office_import_preview import OfficeImportPreviewInvalid, OfficeImportPreviewService
from suite.rag.parser_worker import ParsedTextArtifact, ParserWorkerRequest, hash_document_blocks
from suite.rag.rich_document_parser import RichDocumentParserWorker
from suite.storage.source_objects import InMemorySourceObjectRepository
from test_office_docx_table_spans import _artifact, _preview
from test_office_import_preview import command, source_record, user
from work_e2e_docx import synthetic_docx


@pytest.mark.parametrize("font,family", FAMILIES)
def test_paired_direct_fonts_match_native_primary_faces_and_canonicalize_case(font: str, family: str) -> None:
    source = synthetic_docx(body=paragraph(family_run("Größe \u2013 € e\u0301", font)))
    lower = synthetic_docx(body=paragraph(family_run("Größe \u2013 € e\u0301", font.lower())))
    artifact = _artifact(source)
    assert artifact.text == "Größe \u2013 € e\u0301"
    assert artifact.document_blocks[0]["runs"][0]["font_family"] == family
    assert artifact.document_blocks == _artifact(lower).document_blocks
    assert artifact.document_blocks_hash == hash_document_blocks(artifact.document_blocks)
    assert _preview(source)["content"][0]["content"][0]["marks"] == [
        {"type": "textStyle", "attrs": {"fontFamily": family}}
    ]
    css = (Path(__file__).resolve().parents[1] / "app/suite/ui/office/office.css").read_text()
    assert f'[data-office-font-family="{family}"]{{font-family:{font},' in css


def test_absent_family_keeps_legacy_shape_and_assignment_changes_structure_only() -> None:
    plain = _artifact(synthetic_docx(body=paragraph(literal("Text"))))
    assert plain.document_blocks[0]["runs"] == [{"text": "Text", "marks": []}]
    family = _artifact(synthetic_docx(body=paragraph(family_run("Text", "Arial"))))
    assert family.text_hash == plain.text_hash
    assert family.document_blocks_hash != plain.document_blocks_hash


def test_family_size_color_and_marks_combine_once_in_headings_and_cells() -> None:
    nodes = _preview(font_family_docx())["content"]
    assert nodes[0]["type"] == "heading"
    assert nodes[2]["content"][0]["marks"] == [
        {"type": "bold"},
        {"type": "textStyle", "attrs": {"fontFamily": "serif", "fontSize": 18, "textColor": "red"}},
    ]
    header = nodes[5]["content"][0]["content"][0]
    assert header["type"] == "tableHeader"
    assert header["content"][0]["content"][0]["marks"] == [
        {"type": "textStyle", "attrs": {"fontFamily": "mono", "fontSize": 14}}
    ]


def test_family_survives_lists_links_and_page_break_segments() -> None:
    listed = list_docx(
        body=item("Listenbeleg", 0).replace("<w:r><w:t>Listenbeleg</w:t></w:r>", family_run("Listenbeleg", "Georgia"))
    )
    assert _preview(listed)["content"][0]["content"][0]["content"][0]["content"][0]["marks"] == [
        {"type": "textStyle", "attrs": {"fontFamily": "serif"}}
    ]
    linked = synthetic_docx(
        body=paragraph(TARGET_START + literal("Ziel") + TARGET_END)
        + paragraph(
            '<w:hyperlink w:anchor="Section_Target">'
            + family_run("Sprung", "Arial", '<w:i/><w:sz w:val="24"/><w:color w:val="1D4ED8"/>')
            + "</w:hyperlink>"
        )
    )
    marks = _preview(linked)["content"][1]["content"][0]["marks"]
    assert marks[1] == {"type": "textStyle", "attrs": {"fontFamily": "sans", "fontSize": 12, "textColor": "blue"}}
    assert marks[2]["type"] == "crossReference"
    split = synthetic_docx(
        body=paragraph(
            family_run("Vorher", "Consolas").replace("</w:r>", '<w:br w:type="page"/><w:t>Nachher</w:t></w:r>')
        )
    )
    before, page, after = _preview(split)["content"]
    assert page == {"type": "pageBreak"}
    assert before["content"][0]["marks"] == after["content"][0]["marks"]


@pytest.mark.parametrize("font", ["Calibri", "serif"])
def test_link_font_semantics_stay_in_the_shared_parser(font: str) -> None:
    source = synthetic_docx(
        body=paragraph(TARGET_START + literal("Ziel") + TARGET_END)
        + paragraph('<w:hyperlink w:anchor="Section_Target">' + family_run("Sprung", font) + "</w:hyperlink>")
    )
    assert _artifact(source).text == "Ziel\nSprung"
    with pytest.raises(OfficeImportPreviewInvalid, match="inline run is invalid"):
        _preview(source)


@pytest.mark.parametrize(
    "properties",
    [
        '<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/>',
        '<w:rFonts w:ascii="Arial"/>',
        '<w:rFonts w:hAnsi="Arial"/>',
        "<w:rFonts/>",
        '<w:rFonts w:ascii="Arial" w:hAnsi="Georgia"/>',
        '<w:rFonts w:ascii="Arial " w:hAnsi="Arial "/>',
        '<w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:asciiTheme="minorAscii"/>',
        '<w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:hAnsiTheme="minorHAnsi"/>',
        '<w:rFonts w:asciiTheme="minorAscii" w:hAnsiTheme="minorHAnsi"/>',
        '<w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:cs="Arial"/>',
        '<w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:eastAsia="Arial"/>',
        '<w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:hint="default"/>',
        '<w:rFonts w:ascii="Arial" w:hAnsi="Arial"/><w:cs/>',
        '<w:rFonts w:ascii="Arial" w:hAnsi="Arial"/><w:rtl/>',
        '<w:rFonts w:ascii="Arial" w:hAnsi="Arial"/><w:rFonts w:ascii="Arial" w:hAnsi="Arial"/>',
        '<w:rFonts w:ascii="Arial" w:hAnsi="Arial"><w:rFonts/></w:rFonts>',
        '<w:rFonts w:ascii="Arial" w:hAnsi="Arial">text</w:rFonts>',
        '</w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial"/><w:rPr>',
        '<w:rFonts w:ascii="Arial" w:hAnsi="Arial"/></w:rPr><w:rPr>',
    ],
)
def test_unsupported_font_evidence_refuses_preview_without_losing_text(properties: str) -> None:
    source = synthetic_docx(body=paragraph(f"<w:r><w:rPr>{properties}</w:rPr><w:t>Lesbarer Text</w:t></w:r>"))
    artifact = _artifact(source)
    assert artifact.text == "Lesbarer Text"
    assert artifact.document_blocks[0]["runs"][0]["unsupported_font_family"] is True
    with pytest.raises(OfficeImportPreviewInvalid, match="inline run is invalid"):
        _preview(source)


@pytest.mark.parametrize("text", ["العربية", "漢字", "\u03b1", "🙂"])
def test_unadmitted_script_selection_preserves_text_and_refuses_preview(text: str) -> None:
    source = synthetic_docx(body=paragraph(family_run(text, "Arial")))
    assert _artifact(source).text == text
    with pytest.raises(OfficeImportPreviewInvalid, match="inline run is invalid"):
        _preview(source)


@pytest.mark.parametrize("family", [True, 12, None, [], {}, "Arial", "SANS", "serif;color:red", ""])
def test_api_independently_refuses_forged_family_with_matching_hash(family: object) -> None:
    source = synthetic_docx(body=paragraph(family_run("Text", "Arial")))

    def parser(request: ParserWorkerRequest) -> ParsedTextArtifact:
        artifact = RichDocumentParserWorker().parse(request)
        artifact.document_blocks[0]["runs"][0]["font_family"] = family
        return replace(artifact, document_blocks_hash=hash_document_blocks(artifact.document_blocks))

    service = OfficeImportPreviewService(
        source_repository=InMemorySourceObjectRepository((source_record(source),)),
        audit=InMemoryAuditLogger(),
        parser_dispatch=parser,
    )
    with pytest.raises(OfficeImportPreviewInvalid, match="parser font family is invalid"):
        service.preview(user_context=user(), command=command())
