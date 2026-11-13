from __future__ import annotations

from dataclasses import replace

import pytest

from docx_paragraph_alignment_fixture import literal, paragraph
from docx_paragraph_spacing_fixture import paragraph_spacing_docx, spaced_paragraph
from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.platform.office_import_preview import OfficeImportPreviewInvalid, OfficeImportPreviewService
from suite.rag.parser_worker import ParsedTextArtifact, ParserWorkerRequest, hash_document_blocks
from suite.rag.rich_document_parser import RichDocumentParserWorker
from suite.storage.source_objects import InMemorySourceObjectRepository
from test_office_docx_table_spans import _artifact, _preview
from test_office_import_preview import command, source_record, user
from work_e2e_docx import synthetic_docx


def test_spacing_maps_exact_units_and_preserves_heading_and_alignment() -> None:
    source = paragraph_spacing_docx()
    artifact = _artifact(source)
    assert artifact.document_blocks_hash == hash_document_blocks(artifact.document_blocks)
    nodes = _preview(source)["content"]
    assert nodes[0]["attrs"] == {
        "level": 1,
        "textAlign": "center",
        "spacingBefore": 0,
        "spacingAfter": 12,
        "lineSpacing": "1.15",
    }
    assert nodes[2]["attrs"] == {"spacingBefore": 12, "spacingAfter": 6, "lineSpacing": "2"}
    assert nodes[4]["attrs"] == {"spacingBefore": 24, "spacingAfter": 0, "lineSpacing": "1.5"}
    assert artifact.text.splitlines() == [
        "ABSTANDKOPF",
        "EINFACH1",
        "EINFACH2",
        "DOPPELT1",
        "DOPPELT2",
        "DANACH",
        "ABSTAND24",
        "ZEILEN15",
    ]


@pytest.mark.parametrize(("twips", "points"), [("0", 0), ("120", 6), ("240", 12), ("360", 18), ("480", 24)])
def test_before_and_after_map_without_rounding(twips: str, points: int) -> None:
    source = synthetic_docx(body=spaced_paragraph("Text", f'w:before="{twips}" w:after="{twips}"'))
    assert _preview(source)["content"][0]["attrs"] == {"spacingBefore": points, "spacingAfter": points}


def test_empty_spacing_is_legacy_and_auto_rule_is_canonical() -> None:
    bare = synthetic_docx(body=paragraph(literal("Text")))
    empty = synthetic_docx(body=spaced_paragraph("Text", ""))
    assert _artifact(bare).document_blocks == _artifact(empty).document_blocks
    implicit = synthetic_docx(body=spaced_paragraph("Text", 'w:line="240"'))
    explicit = synthetic_docx(body=spaced_paragraph("Text", 'w:line="240" w:lineRule="auto"'))
    assert _artifact(implicit).document_blocks == _artifact(explicit).document_blocks
    page = synthetic_docx(body=spaced_paragraph("Text", 'w:before="120"', other_properties="<w:pageBreakBefore/>"))
    assert _preview(page)["content"][0]["attrs"] == {"spacingBefore": 6, "pageBreakBefore": True}


@pytest.mark.parametrize(
    "properties",
    [
        '<w:spacing w:before="121"/>',
        '<w:spacing w:after="-1"/>',
        '<w:spacing w:before="1pt"/>',
        '<w:spacing w:before="1000000000000000000000"/>',
        '<w:spacing w:beforeLines="100"/>',
        '<w:spacing w:beforeAutospacing="0"/>',
        '<w:spacing w:line="240" w:lineRule="exact"/>',
        '<w:spacing w:line="300"/>',
        '<w:spacing w:lineRule="auto"/>',
        '<w:spacing w:before="0"/><w:spacing w:after="0"/>',
        '<w:spacing w:before="0"><w:spacing/></w:spacing>',
        '</w:pPr><w:spacing w:before="0"/><w:pPr>',
    ],
)
def test_unsupported_spacing_keeps_text_but_refuses_preview(properties: str) -> None:
    source = synthetic_docx(body=paragraph(literal("Lesbarer Text"), other_properties=properties))
    artifact = _artifact(source)
    assert artifact.text == "Lesbarer Text"
    assert artifact.document_blocks[0] == {"kind": "unsupported_paragraph_spacing"}
    with pytest.raises(OfficeImportPreviewInvalid, match="unsupported block"):
        _preview(source)


def test_spacing_with_inline_page_break_refuses_preview_but_preserves_text() -> None:
    source = synthetic_docx(
        body=paragraph(
            literal("Vorher") + '<w:r><w:br w:type="page"/></w:r>' + literal("Nachher"),
            other_properties='<w:spacing w:after="120"/>',
        )
    )
    assert _artifact(source).text == "Vorher\nNachher"
    with pytest.raises(OfficeImportPreviewInvalid, match="unsupported block"):
        _preview(source)


@pytest.mark.parametrize(
    ("field", "marker"),
    [
        ("spacing_before", True),
        ("spacing_after", "6"),
        ("spacing_before", 7),
        ("line_spacing", 1.5),
        ("line_spacing", "1.2"),
        ("line_spacing", []),
    ],
)
def test_api_refuses_forged_spacing_even_with_matching_hash(field: str, marker: object) -> None:
    source = paragraph_spacing_docx()

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
    with pytest.raises(OfficeImportPreviewInvalid, match="paragraph spacing is invalid"):
        service.preview(user_context=user(), command=command())
