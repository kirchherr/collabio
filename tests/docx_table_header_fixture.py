"""Synthetic stored DOCX whose table continues across printed pages."""

from docx_table_span_fixture import cell, row
from work_e2e_docx import synthetic_docx

SOURCE_ID = "work-e2e-stored-docx-table-header"
SOURCE_VERSION = "stored-docx-table-header-v1"
SOURCE_TITLE = "Synthetische gespeicherte DOCX-Quelle mit Tabellenkopf"
HEADER = "<w:tblHeader/>"


def mark_row(cells: str, marker: str = HEADER) -> str:
    return cells.replace("<w:tr>", f"<w:tr><w:trPr>{marker}</w:trPr>", 1)


def table_header_docx() -> bytes:
    head = mark_row(row(cell("KOPFBELEG"), cell("Bezeichnung")))
    body = "".join(row(cell(f"ZEILE-{index:03d}"), cell(f"Eintrag {index:03d}")) for index in range(1, 55))
    return synthetic_docx(body=f"<w:p><w:r><w:t>Tabellenkopfbeleg</w:t></w:r></w:p><w:tbl>{head}{body}</w:tbl>")
