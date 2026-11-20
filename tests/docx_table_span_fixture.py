"""Synthetic source with combined horizontal and vertical table spans."""

from __future__ import annotations

from work_e2e_docx import synthetic_docx

SOURCE_ID = "work-e2e-stored-docx-table-spans"
SOURCE_VERSION = "stored-docx-table-spans-v1"
SOURCE_TITLE = "Synthetische gespeicherte DOCX-Quelle mit Zellspannen"
SPAN = '<w:gridSpan w:val="2"/>'
RESTART = '<w:vMerge w:val="restart"/>'
CONTINUE = "<w:vMerge/>"
GRID = "<w:tblGrid>" + '<w:gridCol w:w="1200"/>' * 3 + "</w:tblGrid>"


def cell(text: str = "", properties: str = "") -> str:
    prop = f"<w:tcPr>{properties}</w:tcPr>" if properties else ""
    paragraph = f"<w:p><w:r><w:t>{text}</w:t></w:r></w:p>" if text else "<w:p/>"
    return f"<w:tc>{prop}{paragraph}</w:tc>"


def row(*cells: str) -> str:
    return "<w:tr>" + "".join(cells) + "</w:tr>"


TABLE = (
    "<w:tbl>"
    + GRID
    + row(cell("Verbundene Gruppe", SPAN + RESTART), cell("Rechts oben"))
    + row(cell(properties=SPAN + CONTINUE), cell("Rechts unten"))
    + row(cell("Links"), cell("Quer verbunden", SPAN))
    + "</w:tbl>"
)


def table_span_docx(table: str = TABLE) -> bytes:
    return synthetic_docx(body="<w:p><w:r><w:t>Tabellenbeleg</w:t></w:r></w:p>" + table)
