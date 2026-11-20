from __future__ import annotations

from dataclasses import replace

import pytest

from docx_table_header_fixture import HEADER, mark_row, table_header_docx
from docx_table_span_fixture import SPAN, TABLE, cell, row, table_span_docx
from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.platform.office_import_preview import OfficeImportPreviewInvalid, OfficeImportPreviewService
from suite.rag.parser_worker import ParsedTextArtifact, ParserWorkerError, ParserWorkerRequest, hash_document_blocks
from suite.rag.rich_document_parser import RichDocumentParserWorker
from suite.storage.source_objects import InMemorySourceObjectRepository
from test_office_docx_table_spans import _artifact, _preview
from test_office_import_preview import command, source_record, user

FIRST = row(cell("Kopf"), cell("Bezeichnung"))
SECOND = row(cell("Eins"), cell("Eintrag"))


def test_table_header_evidence_preserves_text_and_native_cell_types() -> None:
    source = table_header_docx()
    artifact = _artifact(source)
    table = artifact.document_blocks[1]
    assert table["kind"] == "table"
    assert table["header_row"] is True
    assert artifact.document_blocks_hash == hash_document_blocks(artifact.document_blocks)
    assert artifact.text.splitlines()[1] == "KOPFBELEG\tBezeichnung"
    assert artifact.text.splitlines()[-1] == "ZEILE-054\tEintrag 054"
    rows = _preview(source)["content"][1]["content"]
    assert [cell["type"] for cell in rows[0]["content"]] == ["tableHeader", "tableHeader"]
    assert all(cell["type"] == "tableCell" for row in rows[1:] for cell in row["content"])


@pytest.mark.parametrize(
    ("value", "enabled"), [("on", True), ("1", True), ("true", True), ("off", False), ("0", False), ("false", False)]
)
def test_explicit_header_boolean_is_canonical(value: str, enabled: bool) -> None:
    marker = f'<w:tblHeader w:val="{value}"/>'
    source = table_span_docx(f"<w:tbl>{mark_row(FIRST, marker)}{SECOND}</w:tbl>")
    canonical = mark_row(FIRST) if enabled else FIRST
    assert (
        _artifact(source).document_blocks
        == _artifact(table_span_docx(f"<w:tbl>{canonical}{SECOND}</w:tbl>")).document_blocks
    )


@pytest.mark.parametrize(
    "rows",
    [
        FIRST + mark_row(SECOND),
        mark_row(FIRST) + mark_row(SECOND),
        mark_row(FIRST, HEADER * 2) + SECOND,
        mark_row(FIRST, '<w:tblHeader w:val="maybe"/>') + SECOND,
        mark_row(FIRST, '<w:tblHeader w:other="1"/>') + SECOND,
        FIRST.replace("<w:tr>", "<w:tr>" + HEADER, 1) + SECOND,
        mark_row("<w:tr></w:tr>") + SECOND,
        mark_row(FIRST).replace("</w:trPr>", '<w:gridBefore w:val="1"/></w:trPr>') + SECOND,
    ],
)
def test_parser_refuses_ambiguous_or_unsupported_header_rows(rows: str) -> None:
    with pytest.raises(ParserWorkerError, match=r"header|table layout"):
        _artifact(table_span_docx(f"<w:tbl>{rows}</w:tbl>"))


def test_header_accepts_horizontal_span_and_refuses_vertical_span_across_body() -> None:
    source = table_span_docx(f"<w:tbl>{mark_row(row(cell('Kopf', SPAN)))}{SECOND}</w:tbl>")
    header = _preview(source)["content"][1]["content"][0]["content"][0]
    assert header["type"] == "tableHeader"
    assert header["attrs"] == {"colspan": 2}
    crossing = TABLE.replace("<w:tr>", f"<w:tr><w:trPr>{HEADER}</w:trPr>", 1)
    with pytest.raises(OfficeImportPreviewInvalid, match="header merge crosses into the body"):
        _preview(table_span_docx(crossing))


@pytest.mark.parametrize("marker", [False, 1, "true", None])
def test_api_refuses_noncanonical_header_marker(marker: object) -> None:
    def parser(request: ParserWorkerRequest) -> ParsedTextArtifact:
        artifact = RichDocumentParserWorker().parse(request)
        paragraph, table = artifact.document_blocks
        blocks = (paragraph, {**table, "header_row": marker})
        return replace(artifact, document_blocks=blocks, document_blocks_hash=hash_document_blocks(blocks))

    service = OfficeImportPreviewService(
        source_repository=InMemorySourceObjectRepository((source_record(table_header_docx()),)),
        audit=InMemoryAuditLogger(),
        parser_dispatch=parser,
    )
    with pytest.raises(OfficeImportPreviewInvalid, match="table header marker is invalid"):
        service.preview(user_context=user(), command=command())
