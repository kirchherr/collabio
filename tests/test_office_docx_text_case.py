from __future__ import annotations

from dataclasses import replace

import pytest

from docx_list_fixture import item, list_docx
from docx_navigation_fixture import TARGET_END, TARGET_START
from docx_paragraph_alignment_fixture import literal, paragraph
from docx_text_case_fixture import case_run, text_case_docx
from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.platform.office_import_preview import OfficeImportPreviewInvalid, OfficeImportPreviewService
from suite.rag.parser_worker import ParsedTextArtifact, ParserWorkerRequest, hash_document_blocks
from suite.rag.rich_document_parser import RichDocumentParserWorker
from suite.storage.source_objects import InMemorySourceObjectRepository
from test_office_docx_table_spans import _artifact, _preview
from test_office_import_preview import command, source_record, user
from work_e2e_docx import synthetic_docx


@pytest.mark.parametrize(("tag", "native"), [("caps", "uppercase"), ("smallCaps", "smallCaps")])
@pytest.mark.parametrize("value", [None, "true", "1", "on", "false", "0", "off"])
def test_direct_case_toggle_preserves_text_and_maps_to_native(tag: str, native: str, value: str | None) -> None:
    marker = f"<w:{tag}/>" if value is None else f'<w:{tag} w:val="{value}"/>'
    source = synthetic_docx(body=paragraph(case_run("Mixed Text", marker)))
    artifact = _artifact(source)
    enabled = value in {None, "true", "1", "on"}
    assert artifact.text == "Mixed Text"
    assert artifact.document_blocks[0]["runs"][0]["text_case"] == (native if enabled else "normal")
    assert artifact.document_blocks_hash == hash_document_blocks(artifact.document_blocks)
    node = _preview(source)["content"][0]["content"][0]
    assert node["text"] == "Mixed Text"
    assert node.get("marks", []) == ([{"type": "textStyle", "attrs": {"textCase": native}}] if enabled else [])


def test_absence_and_explicit_disabling_have_distinct_evidence_and_equal_native_text() -> None:
    plain = synthetic_docx(body=paragraph(literal("Mixed Text")))
    disabled = synthetic_docx(body=paragraph(case_run("Mixed Text", '<w:caps w:val="false"/>')))
    assert _artifact(plain).document_blocks[0]["runs"] == [{"text": "Mixed Text", "marks": []}]
    assert _artifact(plain).text_hash == _artifact(disabled).text_hash
    assert _artifact(plain).document_blocks_hash != _artifact(disabled).document_blocks_hash
    assert _preview(plain)["content"] == _preview(disabled)["content"]


def test_case_composes_with_existing_character_styles_and_header_cells() -> None:
    nodes = _preview(text_case_docx())["content"]
    assert nodes[1]["content"][0]["marks"] == [
        {"type": "bold"},
        {"type": "textStyle", "attrs": {"fontSize": 12, "textColor": "red", "textCase": "uppercase"}},
    ]
    assert nodes[2]["content"][0]["marks"] == [
        {"type": "italic"},
        {"type": "textStyle", "attrs": {"fontSize": 12, "textCase": "smallCaps"}},
    ]
    assert nodes[5]["content"][0]["marks"] == [
        {
            "type": "textStyle",
            "attrs": {
                "fontFamily": "mono",
                "fontSize": 14,
                "textColor": "blue",
                "verticalPosition": "superscript",
                "textCase": "uppercase",
            },
        }
    ]
    header = nodes[6]["content"][0]["content"][0]
    assert header["type"] == "tableHeader"
    assert header["content"][0]["content"][0]["marks"][0]["attrs"]["textCase"] == "uppercase"


@pytest.mark.parametrize(("tag", "native"), [("caps", "uppercase"), ("smallCaps", "smallCaps")])
def test_shared_conversion_covers_headings_lists_links_and_page_breaks(tag: str, native: str) -> None:
    run = case_run("Listenbeleg", f"<w:{tag}/>")
    expected = [{"type": "textStyle", "attrs": {"textCase": native}}]
    heading = _preview(synthetic_docx(body=paragraph(run, other_properties='<w:pStyle w:val="Heading1"/>')))["content"][
        0
    ]
    assert heading["type"] == "heading"
    assert heading["content"][0]["marks"] == expected
    listed = list_docx(body=item("Listenbeleg", 0).replace("<w:r><w:t>Listenbeleg</w:t></w:r>", run))
    assert _preview(listed)["content"][0]["content"][0]["content"][0]["content"][0]["marks"] == expected
    linked = synthetic_docx(
        body=paragraph(TARGET_START + literal("Ziel") + TARGET_END)
        + paragraph('<w:hyperlink w:anchor="Section_Target">' + run + "</w:hyperlink>")
    )
    marks = _preview(linked)["content"][1]["content"][0]["marks"]
    assert marks[0] == expected[0]
    assert marks[1]["type"] == "crossReference"
    split = synthetic_docx(body=paragraph(run.replace("</w:r>", '<w:br w:type="page"/><w:t>Nachher</w:t></w:r>')))
    before, page, after = _preview(split)["content"]
    assert page == {"type": "pageBreak"}
    assert before["content"][0]["marks"] == after["content"][0]["marks"] == expected


@pytest.mark.parametrize(
    "properties",
    [
        '<w:caps w:val="TRUE"/>',
        '<w:smallCaps w:val="yes"/>',
        '<w:caps w:val=" true"/>',
        '<w:caps w:val=""/>',
        '<w:smallCaps w:val="2"/>',
        "<w:caps/><w:caps/>",
        '<w:smallCaps/><w:smallCaps w:val="false"/>',
        "<w:caps/><w:smallCaps/>",
        '<w:caps w:val="false"/><w:smallCaps w:val="false"/>',
        "<w:caps/></w:rPr><w:rPr>",
        "</w:rPr><w:caps/><w:rPr>",
        "<w:smallCaps><w:caps/></w:smallCaps>",
        "<w:caps>text</w:caps>",
        '<w:smallCaps w:val="true" w:other="1"/>',
        '<w:caps val="true"/>',
        '<w:smallCaps w:val="uppercase;color:red"/>',
    ],
)
def test_unsupported_case_preserves_extraction_and_refuses_preview(properties: str) -> None:
    source = synthetic_docx(body=paragraph(case_run("Lesbarer Text", properties)))
    artifact = _artifact(source)
    assert artifact.text == "Lesbarer Text"
    assert artifact.document_blocks[0]["runs"][0]["unsupported_text_case"] is True
    with pytest.raises(OfficeImportPreviewInvalid, match="inline run is invalid"):
        _preview(source)


@pytest.mark.parametrize("properties", ['<w:caps w:val="yes"/>', "<w:caps/><w:smallCaps/>"])
def test_link_case_uses_shared_semantic_validation(properties: str) -> None:
    source = synthetic_docx(
        body=paragraph(TARGET_START + literal("Ziel") + TARGET_END)
        + paragraph('<w:hyperlink w:anchor="Section_Target">' + case_run("Sprung", properties) + "</w:hyperlink>")
    )
    assert _artifact(source).text == "Ziel\nSprung"
    with pytest.raises(OfficeImportPreviewInvalid, match="inline run is invalid"):
        _preview(source)


@pytest.mark.parametrize("value", [True, 12, None, [], {}, "caps", "NORMAL", "uppercase;color:red", ""])
def test_api_rejects_forged_case_even_with_matching_structure_hash(value: object) -> None:
    source = synthetic_docx(body=paragraph(case_run("Mixed Text", "<w:caps/>")))

    def parser(request: ParserWorkerRequest) -> ParsedTextArtifact:
        artifact = RichDocumentParserWorker().parse(request)
        artifact.document_blocks[0]["runs"][0]["text_case"] = value
        return replace(artifact, document_blocks_hash=hash_document_blocks(artifact.document_blocks))

    service = OfficeImportPreviewService(
        source_repository=InMemorySourceObjectRepository((source_record(source),)),
        audit=InMemoryAuditLogger(),
        parser_dispatch=parser,
    )
    with pytest.raises(OfficeImportPreviewInvalid, match="parser text case is invalid"):
        service.preview(user_context=user(), command=command())
