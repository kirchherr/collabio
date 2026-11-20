from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from docx_list_fixture import item, list_docx
from docx_navigation_fixture import TARGET_END, TARGET_START
from docx_paragraph_alignment_fixture import literal, paragraph
from docx_text_color_fixture import PALETTE, colored_run, text_color_docx
from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.platform.office_import_preview import OfficeImportPreviewInvalid, OfficeImportPreviewService
from suite.rag.parser_worker import ParsedTextArtifact, ParserWorkerRequest, hash_document_blocks
from suite.rag.rich_document_parser import RichDocumentParserWorker
from suite.storage.source_objects import InMemorySourceObjectRepository
from test_office_docx_table_spans import _artifact, _preview
from test_office_import_preview import command, source_record, user
from work_e2e_docx import synthetic_docx


@pytest.mark.parametrize("rgb,name,_text", PALETTE)
def test_explicit_color_matches_native_css_exactly_and_canonicalizes_case(rgb: str, name: str, _text: str) -> None:
    source = synthetic_docx(body=paragraph(colored_run("Text", rgb)))
    lower = synthetic_docx(body=paragraph(colored_run("Text", rgb.lower())))
    artifact = _artifact(source)
    assert artifact.text == "Text"
    assert artifact.document_blocks[0]["runs"][0]["text_color"] == name
    assert artifact.document_blocks == _artifact(lower).document_blocks
    assert artifact.document_blocks_hash == hash_document_blocks(artifact.document_blocks)
    assert _preview(source)["content"][0]["content"][0]["marks"] == [
        {"type": "textStyle", "attrs": {"textColor": name}}
    ]
    css = (Path(__file__).resolve().parents[1] / "app/suite/ui/office/office.css").read_text()
    assert f'[data-office-text-color="{name}"]{{color:#{rgb.lower()};' in css


def test_absent_color_keeps_legacy_shape_and_color_changes_only_structure_hash() -> None:
    plain = _artifact(synthetic_docx(body=paragraph(literal("Text"))))
    assert plain.document_blocks[0]["runs"] == [{"text": "Text", "marks": []}]
    colored = _artifact(synthetic_docx(body=paragraph(colored_run("Text", "B91C1C"))))
    assert plain.text_hash == colored.text_hash
    assert plain.document_blocks_hash != colored.document_blocks_hash


def test_color_and_size_share_one_style_mark_in_heading_bold_text_and_table() -> None:
    nodes = _preview(text_color_docx())["content"]
    assert nodes[0]["type"] == "heading"
    assert nodes[0]["content"][0]["marks"] == [{"type": "textStyle", "attrs": {"fontSize": 24, "textColor": "black"}}]
    assert nodes[2]["content"][0]["marks"] == [
        {"type": "bold"},
        {"type": "textStyle", "attrs": {"fontSize": 18, "textColor": "red"}},
    ]
    header = nodes[6]["content"][0]["content"][0]
    assert header["type"] == "tableHeader"
    assert header["content"][0]["content"][0]["marks"] == [{"type": "textStyle", "attrs": {"textColor": "blue"}}]


def test_color_survives_shared_list_internal_link_and_page_break_conversion() -> None:
    listed = list_docx(
        body=item("Listenbeleg", 0).replace("<w:r><w:t>Listenbeleg</w:t></w:r>", colored_run("Listenbeleg", "115E59"))
    )
    assert _preview(listed)["content"][0]["content"][0]["content"][0]["content"][0]["marks"] == [
        {"type": "textStyle", "attrs": {"textColor": "teal"}}
    ]
    linked = synthetic_docx(
        body=paragraph(TARGET_START + literal("Ziel") + TARGET_END)
        + paragraph(
            '<w:hyperlink w:anchor="Section_Target">'
            + colored_run("Sprung", "1D4ED8", '<w:i/><w:sz w:val="32"/>')
            + "</w:hyperlink>"
        )
    )
    marks = _preview(linked)["content"][1]["content"][0]["marks"]
    assert marks[1] == {"type": "textStyle", "attrs": {"fontSize": 16, "textColor": "blue"}}
    assert marks[2]["type"] == "crossReference"
    split = synthetic_docx(
        body=paragraph(
            colored_run("Vorher", "7E22CE").replace("</w:r>", '<w:br w:type="page"/><w:t>Nachher</w:t></w:r>')
        )
    )
    before, page, after = _preview(split)["content"]
    assert page == {"type": "pageBreak"}
    assert before["content"][0]["marks"] == after["content"][0]["marks"]


@pytest.mark.parametrize("rgb", ["auto", "FF0000"])
def test_internal_link_color_semantics_stay_in_the_shared_parser(rgb: str) -> None:
    source = synthetic_docx(
        body=paragraph(TARGET_START + literal("Ziel") + TARGET_END)
        + paragraph('<w:hyperlink w:anchor="Section_Target">' + colored_run("Sprung", rgb) + "</w:hyperlink>")
    )
    assert _artifact(source).text == "Ziel\nSprung"
    with pytest.raises(OfficeImportPreviewInvalid, match="inline run is invalid"):
        _preview(source)


@pytest.mark.parametrize(
    "properties",
    [
        '<w:color w:val="auto"/>',
        '<w:color w:val="000000"/>',
        '<w:color w:val="FF0000"/>',
        '<w:color w:val="#B91C1C"/>',
        '<w:color w:val="red"/>',
        '<w:color w:val="B91C1"/>',
        '<w:color w:val=" B91C1C"/>',
        "<w:color/>",
        '<w:color w:val="B91C1C" w:themeColor="accent1"/>',
        '<w:color w:themeColor="accent1"/>',
        '<w:color w:val="B91C1C" w:themeTint="80"/>',
        '<w:color w:val="B91C1C" w:themeShade="80"/>',
        '<w:color w:val="B91C1C" w:other="1"/>',
        '<w:color w:val="B91C1C"/><w:color w:val="B91C1C"/>',
        '<w:color w:val="B91C1C"><w:color/></w:color>',
        '<w:color w:val="B91C1C">text</w:color>',
        '</w:rPr><w:color w:val="B91C1C"/><w:rPr>',
        '<w:color w:val="B91C1C"/></w:rPr><w:rPr>',
    ],
)
def test_unsupported_color_refuses_preview_without_losing_plain_text(properties: str) -> None:
    source = synthetic_docx(body=paragraph(f"<w:r><w:rPr>{properties}</w:rPr><w:t>Lesbarer Text</w:t></w:r>"))
    artifact = _artifact(source)
    assert artifact.text == "Lesbarer Text"
    assert artifact.document_blocks[0]["runs"][0]["unsupported_text_color"] is True
    with pytest.raises(OfficeImportPreviewInvalid, match="inline run is invalid"):
        _preview(source)


@pytest.mark.parametrize("color", [True, 12, None, [], {}, "B91C1C", "RED", "transparent", ""])
def test_api_rejects_forged_color_with_a_matching_structure_hash(color: object) -> None:
    source = synthetic_docx(body=paragraph(colored_run("Text", "B91C1C")))

    def parser(request: ParserWorkerRequest) -> ParsedTextArtifact:
        artifact = RichDocumentParserWorker().parse(request)
        artifact.document_blocks[0]["runs"][0]["text_color"] = color
        return replace(artifact, document_blocks_hash=hash_document_blocks(artifact.document_blocks))

    service = OfficeImportPreviewService(
        source_repository=InMemorySourceObjectRepository((source_record(source),)),
        audit=InMemoryAuditLogger(),
        parser_dispatch=parser,
    )
    with pytest.raises(OfficeImportPreviewInvalid, match="parser text color is invalid"):
        service.preview(user_context=user(), command=command())
