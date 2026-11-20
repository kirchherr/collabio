from __future__ import annotations

from dataclasses import replace

import pytest

from docx_paragraph_alignment_fixture import literal, paragraph
from docx_paragraph_indentation_fixture import indented_paragraph, paragraph_indentation_docx
from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.platform.office_import_preview import OfficeImportPreviewInvalid, OfficeImportPreviewService
from suite.rag.parser_worker import ParsedTextArtifact, ParserWorkerRequest, hash_document_blocks
from suite.rag.rich_document_parser import RichDocumentParserWorker
from suite.storage.source_objects import InMemorySourceObjectRepository
from test_office_docx_table_spans import _artifact, _preview
from test_office_import_preview import command, source_record, user
from work_e2e_docx import synthetic_docx


def test_direct_indents_preserve_native_geometry_and_prior_paragraph_attributes() -> None:
    source = paragraph_indentation_docx()
    artifact = _artifact(source)
    assert artifact.document_blocks_hash == hash_document_blocks(artifact.document_blocks)
    nodes = _preview(source)["content"]
    assert nodes[0]["attrs"] == {"level": 1, "spacingBefore": 0, "spacingAfter": 6, "indentLeft": 18}
    assert nodes[2]["attrs"] == {"indentLeft": 36, "indentRight": 18}
    assert nodes[4]["attrs"] == {"textAlign": "right", "indentLeft": 0, "indentRight": 36}
    assert nodes[5]["attrs"] == {"indentLeft": 18, "indentRight": 0, "specialIndent": "firstLine36"}
    assert nodes[6]["attrs"] == {"indentLeft": 18, "indentRight": 0, "specialIndent": "hanging18"}
    assert artifact.text.splitlines()[-4:] == ["ERSTZEILE", "FOLGEZEILE", "HAENGEERSTE", "HAENGEFOLGE"]


@pytest.mark.parametrize(("twips", "points"), [("0", 0), ("360", 18), ("720", 36), ("1080", 54), ("1440", 72)])
def test_left_and_right_indents_map_exactly(twips: str, points: int) -> None:
    source = synthetic_docx(body=indented_paragraph("Text", f'w:left="{twips}" w:right="{twips}"'))
    assert _preview(source)["content"][0]["attrs"] == {"indentLeft": points, "indentRight": points}


@pytest.mark.parametrize(("left", "hanging", "native"), [("360", "360", 0), ("720", "720", 0), ("1440", "720", 36)])
def test_hanging_indent_accounts_for_native_padding(left: str, hanging: str, native: int) -> None:
    source = synthetic_docx(body=indented_paragraph("Text", f'w:left="{left}" w:hanging="{hanging}"'))
    node = _preview(source)["content"][0]
    assert node["attrs"]["indentLeft"] == native
    assert node["attrs"]["specialIndent"] == ("hanging18" if hanging == "360" else "hanging36")


def test_empty_and_explicit_zero_indentation_preserve_their_meaning() -> None:
    bare = synthetic_docx(body=paragraph(literal("Text")))
    empty = synthetic_docx(body=indented_paragraph("Text", ""))
    assert _artifact(bare).document_blocks == _artifact(empty).document_blocks
    first = synthetic_docx(body=indented_paragraph("Text", 'w:firstLine="0"'))
    hanging = synthetic_docx(body=indented_paragraph("Text", 'w:hanging="0"'))
    assert _artifact(first).document_blocks == _artifact(hanging).document_blocks
    assert _preview(first)["content"][0]["attrs"] == {"specialIndent": "none"}
    page = synthetic_docx(body=indented_paragraph("Text", 'w:left="360"', other_properties="<w:pageBreakBefore/>"))
    assert _preview(page)["content"][0]["attrs"] == {"pageBreakBefore": True, "indentLeft": 18}


@pytest.mark.parametrize(
    "properties",
    [
        '<w:ind w:left="361"/>',
        '<w:ind w:right="-360"/>',
        '<w:ind w:left="18pt"/>',
        '<w:ind w:left="1000000000000000000000"/>',
        '<w:ind w:start="360"/>',
        '<w:ind w:leftChars="100"/>',
        '<w:ind w:firstLine="1080"/>',
        '<w:ind w:hanging="360"/>',
        '<w:ind w:left="360" w:hanging="720"/>',
        '<w:ind w:firstLine="360" w:hanging="360"/>',
        '<w:ind w:left="0"/><w:ind w:right="0"/>',
        '<w:ind w:left="0"><w:ind/></w:ind>',
        '<w:ind w:left="360"/><w:bidi/>',
        '<w:ind w:left="360"/><w:mirrorIndents/>',
        '</w:pPr><w:ind w:left="0"/><w:pPr>',
    ],
)
def test_unsupported_indent_keeps_text_but_refuses_office_preview(properties: str) -> None:
    source = synthetic_docx(body=paragraph(literal("Lesbarer Text"), other_properties=properties))
    artifact = _artifact(source)
    assert artifact.text == "Lesbarer Text"
    assert artifact.document_blocks[0] == {"kind": "unsupported_paragraph_indentation"}
    with pytest.raises(OfficeImportPreviewInvalid, match="unsupported block"):
        _preview(source)


def test_inline_page_break_with_indent_refuses_preview_and_keeps_text() -> None:
    source = synthetic_docx(
        body=paragraph(
            literal("Vorher") + '<w:r><w:br w:type="page"/></w:r>' + literal("Nachher"),
            other_properties='<w:ind w:firstLine="360"/>',
        )
    )
    assert _artifact(source).text == "Vorher\nNachher"
    with pytest.raises(OfficeImportPreviewInvalid, match="unsupported block"):
        _preview(source)


@pytest.mark.parametrize(
    ("field", "marker"),
    [
        ("indent_left", True),
        ("indent_right", "18"),
        ("indent_left", -18),
        ("indent_right", 19),
        ("special_indent", "firstLine72"),
        ("special_indent", []),
        ("special_indent", None),
    ],
)
def test_api_rejects_forged_indent_even_with_matching_structure_hash(field: str, marker: object) -> None:
    source = paragraph_indentation_docx()

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
    with pytest.raises(OfficeImportPreviewInvalid, match="paragraph indentation is invalid"):
        service.preview(user_context=user(), command=command())
