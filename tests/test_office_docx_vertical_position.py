from __future__ import annotations

from dataclasses import replace

import pytest

from docx_list_fixture import item, list_docx
from docx_navigation_fixture import TARGET_END, TARGET_START
from docx_paragraph_alignment_fixture import literal, paragraph
from docx_vertical_position_fixture import positioned_run, vertical_position_docx
from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.platform.office_import_preview import OfficeImportPreviewInvalid, OfficeImportPreviewService
from suite.rag.parser_worker import ParsedTextArtifact, ParserWorkerRequest, hash_document_blocks
from suite.rag.rich_document_parser import RichDocumentParserWorker
from suite.storage.source_objects import InMemorySourceObjectRepository
from test_office_docx_table_spans import _artifact, _preview
from test_office_import_preview import command, source_record, user
from work_e2e_docx import synthetic_docx


@pytest.mark.parametrize("position", ["baseline", "superscript", "subscript"])
def test_direct_positions_are_bound_to_evidence_and_map_to_native_marks(position: str) -> None:
    source = synthetic_docx(body=paragraph(positioned_run("Text", position)))
    artifact = _artifact(source)
    assert artifact.text == "Text"
    assert artifact.document_blocks[0]["runs"][0]["vertical_position"] == position
    assert artifact.document_blocks_hash == hash_document_blocks(artifact.document_blocks)
    node = _preview(source)["content"][0]["content"][0]
    if position == "baseline":
        assert node == {"type": "text", "text": "Text"}
    else:
        assert node["marks"] == [{"type": "textStyle", "attrs": {"verticalPosition": position}}]


def test_absence_keeps_legacy_shape_and_explicit_baseline_has_distinct_evidence() -> None:
    plain = synthetic_docx(body=paragraph(literal("Text")))
    baseline = synthetic_docx(body=paragraph(positioned_run("Text", "baseline")))
    assert _artifact(plain).document_blocks[0]["runs"] == [{"text": "Text", "marks": []}]
    assert _artifact(plain).text_hash == _artifact(baseline).text_hash
    assert _artifact(plain).document_blocks_hash != _artifact(baseline).document_blocks_hash
    assert _preview(plain)["content"] == _preview(baseline)["content"]


def test_positions_compose_with_family_size_color_marks_and_table_header() -> None:
    heading = _preview(
        synthetic_docx(
            body=paragraph(positioned_run("Kopf", "superscript"), other_properties='<w:pStyle w:val="Heading1"/>')
        )
    )["content"][0]
    assert heading["type"] == "heading"
    assert heading["content"][0]["marks"] == [{"type": "textStyle", "attrs": {"verticalPosition": "superscript"}}]
    nodes = _preview(vertical_position_docx())["content"]
    marked = nodes[1]["content"][2]
    assert marked["text"] == "HOCHBELEG"
    assert marked["marks"] == [
        {"type": "bold"},
        {"type": "textStyle", "attrs": {"fontSize": 12, "textColor": "red", "verticalPosition": "superscript"}},
    ]
    assert nodes[2]["content"][0]["marks"] == [
        {
            "type": "textStyle",
            "attrs": {"fontFamily": "mono", "fontSize": 14, "textColor": "blue", "verticalPosition": "superscript"},
        }
    ]
    assert nodes[3]["content"][0]["marks"] == [{"type": "underline"}, {"type": "textStyle", "attrs": {"fontSize": 12}}]
    header = nodes[4]["content"][0]["content"][0]
    assert header["type"] == "tableHeader"
    assert header["content"][0]["content"][0]["marks"][0]["attrs"]["verticalPosition"] == "superscript"


@pytest.mark.parametrize("position", ["baseline", "superscript", "subscript"])
def test_shared_conversion_preserves_positions_in_lists_links_and_page_breaks(position: str) -> None:
    run = positioned_run("Listenbeleg", position)
    listed = list_docx(body=item("Listenbeleg", 0).replace("<w:r><w:t>Listenbeleg</w:t></w:r>", run))
    node = _preview(listed)["content"][0]["content"][0]["content"][0]["content"][0]
    assert node.get("marks", []) == (
        [] if position == "baseline" else [{"type": "textStyle", "attrs": {"verticalPosition": position}}]
    )
    linked = synthetic_docx(
        body=paragraph(TARGET_START + literal("Ziel") + TARGET_END)
        + paragraph(
            '<w:hyperlink w:anchor="Section_Target">'
            + positioned_run("Sprung", position, '<w:sz w:val="24"/>')
            + "</w:hyperlink>"
        )
    )
    marks = _preview(linked)["content"][1]["content"][0]["marks"]
    expected: dict[str, object] = {"fontSize": 12}
    if position != "baseline":
        expected["verticalPosition"] = position
    assert marks[0] == {"type": "textStyle", "attrs": expected}
    assert marks[1]["type"] == "crossReference"
    split = synthetic_docx(
        body=paragraph(
            positioned_run("Vorher", position).replace("</w:r>", '<w:br w:type="page"/><w:t>Nachher</w:t></w:r>')
        )
    )
    before, page, after = _preview(split)["content"]
    assert page == {"type": "pageBreak"}
    assert before["content"][0].get("marks") == after["content"][0].get("marks")


@pytest.mark.parametrize(
    "properties",
    [
        '<w:vertAlign w:val="super"/>',
        '<w:vertAlign w:val="Superscript"/>',
        '<w:vertAlign w:val="1"/>',
        '<w:vertAlign w:val=""/>',
        "<w:vertAlign/>",
        '<w:vertAlign w:val=" superscript"/>',
        '<w:vertAlign w:val="superscript" w:other="1"/>',
        '<w:vertAlign w:val="superscript"/><w:vertAlign w:val="superscript"/>',
        '<w:vertAlign w:val="superscript"><w:vertAlign/></w:vertAlign>',
        '<w:vertAlign w:val="superscript">text</w:vertAlign>',
        '</w:rPr><w:vertAlign w:val="superscript"/><w:rPr>',
        '<w:vertAlign w:val="superscript"/></w:rPr><w:rPr>',
        '<w:position w:val="0"/>',
        '<w:position w:val="12"/>',
        '<w:vertAlign w:val="baseline"/><w:position w:val="0"/>',
        '</w:rPr><w:position w:val="12"/><w:rPr>',
    ],
)
def test_unsupported_position_preserves_text_and_refuses_office_preview(properties: str) -> None:
    source = synthetic_docx(body=paragraph(f"<w:r><w:rPr>{properties}</w:rPr><w:t>Lesbarer Text</w:t></w:r>"))
    artifact = _artifact(source)
    assert artifact.text == "Lesbarer Text"
    assert artifact.document_blocks[0]["runs"][0]["unsupported_vertical_position"] is True
    with pytest.raises(OfficeImportPreviewInvalid, match="inline run is invalid"):
        _preview(source)


@pytest.mark.parametrize("properties", ['<w:vertAlign w:val="super"/>', '<w:position w:val="0"/>'])
def test_link_position_semantics_are_checked_by_the_shared_parser(properties: str) -> None:
    run = f"<w:r><w:rPr>{properties}</w:rPr><w:t>Sprung</w:t></w:r>"
    source = synthetic_docx(
        body=paragraph(TARGET_START + literal("Ziel") + TARGET_END)
        + paragraph('<w:hyperlink w:anchor="Section_Target">' + run + "</w:hyperlink>")
    )
    assert _artifact(source).text == "Ziel\nSprung"
    with pytest.raises(OfficeImportPreviewInvalid, match="inline run is invalid"):
        _preview(source)


@pytest.mark.parametrize("position", [True, 12, None, [], {}, "super", "BASELINE", "baseline;color:red", ""])
def test_api_refuses_forged_positions_with_matching_structure_hash(position: object) -> None:
    source = synthetic_docx(body=paragraph(positioned_run("Text", "superscript")))

    def parser(request: ParserWorkerRequest) -> ParsedTextArtifact:
        artifact = RichDocumentParserWorker().parse(request)
        artifact.document_blocks[0]["runs"][0]["vertical_position"] = position
        return replace(artifact, document_blocks_hash=hash_document_blocks(artifact.document_blocks))

    service = OfficeImportPreviewService(
        source_repository=InMemorySourceObjectRepository((source_record(source),)),
        audit=InMemoryAuditLogger(),
        parser_dispatch=parser,
    )
    with pytest.raises(OfficeImportPreviewInvalid, match="parser vertical position is invalid"):
        service.preview(user_context=user(), command=command())
