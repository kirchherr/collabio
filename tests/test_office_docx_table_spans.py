from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from docx_table_span_fixture import CONTINUE, GRID, RESTART, SPAN, TABLE, cell, row, table_span_docx
from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.platform.office_import_preview import OfficeImportPreviewInvalid, OfficeImportPreviewService
from suite.rag.parser_worker import ParsedTextArtifact, ParserWorkerError, ParserWorkerRequest, hash_document_blocks
from suite.rag.rich_document_parser import DOCX_MIME_TYPE, RichDocumentParserWorker
from suite.storage.source_objects import InMemorySourceObjectRepository
from test_office_import_preview import command, source_record, user
from test_rich_document_parser import request_for


def _artifact(content: bytes) -> ParsedTextArtifact:
    return RichDocumentParserWorker().parse(request_for(mime_type=DOCX_MIME_TYPE, content=content))


def _preview(content: bytes) -> dict[str, Any]:
    service = OfficeImportPreviewService(
        source_repository=InMemorySourceObjectRepository((source_record(content),)),
        audit=InMemoryAuditLogger(),
        parser_dispatch=RichDocumentParserWorker().parse,
    )
    return service.preview(user_context=user(), command=command()).document


def test_docx_merges_rectangles_and_preserves_physical_cell_text_order() -> None:
    content = table_span_docx()
    artifact = _artifact(content)
    assert artifact.text == "Tabellenbeleg\nVerbundene Gruppe\tRechts oben\n\tRechts unten\nLinks\tQuer verbunden"
    assert artifact.document_blocks[1]["kind"] == "merged_table"
    assert artifact.document_blocks_hash == hash_document_blocks(artifact.document_blocks)
    doc = _preview(content)
    first, second, third = doc["content"][1]["content"]
    assert first["content"][0]["attrs"] == {"colspan": 2, "rowspan": 2}
    assert len(second["content"]) == 1
    assert third["content"][1]["attrs"] == {"colspan": 2}
    explicit = _artifact(table_span_docx(TABLE.replace(CONTINUE, '<w:vMerge w:val="continue"/>')))
    assert explicit.document_blocks == artifact.document_blocks


@pytest.mark.parametrize(
    "table",
    [
        TABLE.replace(SPAN, '<w:gridSpan w:val="21"/>', 1),
        TABLE.replace(SPAN, '<w:gridSpan w:val="0"/>', 1),
        TABLE.replace(SPAN, SPAN * 2, 1),
        TABLE.replace(CONTINUE, '<w:vMerge w:val="other"/>'),
        TABLE.replace(cell(properties=SPAN + CONTINUE), cell("Unzulässiger Text", SPAN + CONTINUE)),
        TABLE.replace(GRID, "<w:tblGrid><w:gridCol/></w:tblGrid>"),
        TABLE.replace("<w:tr>", '<w:tr><w:trPr><w:gridBefore w:val="1"/></w:trPr>', 1),
        TABLE.replace(SPAN, '<w:hMerge w:val="restart"/>', 1),
        TABLE.replace("Verbundene Gruppe</w:t></w:r></w:p>", "Verbundene Gruppe</w:t></w:r></w:p><w:tbl/>", 1),
    ],
)
def test_parser_rejects_unsupported_merge_xml(table: str) -> None:
    with pytest.raises(ParserWorkerError):
        _artifact(table_span_docx(table))


@pytest.mark.parametrize(
    "table",
    [
        TABLE.replace(RESTART, ""),
        TABLE.replace(
            row(cell(properties=SPAN + CONTINUE), cell("Rechts unten")),
            row(cell(properties=CONTINUE), cell("Mitte"), cell("Rechts unten")),
        ),
        "<w:tbl>" + row(cell("Einzige Zelle", RESTART)) + row(cell(properties=CONTINUE)) + "</w:tbl>",
    ],
)
def test_api_rejects_unmatched_or_unrepresentable_merge_rows(table: str) -> None:
    with pytest.raises(OfficeImportPreviewInvalid, match=r"merge|grid"):
        _preview(table_span_docx(table))


def test_api_refuses_forged_span_even_with_a_matching_structure_hash() -> None:
    content = table_span_docx()

    def parser(request: ParserWorkerRequest) -> ParsedTextArtifact:
        artifact = RichDocumentParserWorker().parse(request)
        paragraph, table = artifact.document_blocks
        table["rows"][0][0]["colspan"] = True
        blocks = (paragraph, table)
        return replace(artifact, document_blocks=blocks, document_blocks_hash=hash_document_blocks(blocks))

    service = OfficeImportPreviewService(
        source_repository=InMemorySourceObjectRepository((source_record(content),)),
        audit=InMemoryAuditLogger(),
        parser_dispatch=parser,
    )
    with pytest.raises(OfficeImportPreviewInvalid, match="span"):
        service.preview(user_context=user(), command=command())
