"""Stored synthetic DOCX comparing split and kept paragraphs at page boundaries."""

from docx_paragraph_alignment_fixture import literal, paragraph
from work_e2e_docx import synthetic_docx

SOURCE_ID = "work-e2e-stored-docx-paragraph-pagination"
SOURCE_VERSION = "stored-docx-paragraph-pagination-v1"
SOURCE_TITLE = "Synthetische gespeicherte DOCX-Quelle mit Absatzzusammenhalt"


def lines(text: str, properties: str = "") -> str:
    runs = "<w:r><w:br/></w:r>".join(literal(line) for line in text.split("\n"))
    return paragraph(runs, other_properties=properties)


def paragraph_pagination_docx() -> bytes:
    control_filler = "\n".join(f"CONTROL-FILL-{index:02d}" for index in range(1, 35))
    kept_filler = "\n".join(f"KEPT-FILL-{index:02d}" for index in range(1, 35))
    control_lines = "\n".join(f"CONTROL-LINE-{index:02d}" for index in range(1, 9))
    kept_lines = "\n".join(f"KEPT-LINE-{index:02d}" for index in range(1, 9))
    disabled = '<w:keepNext w:val="off"/><w:keepLines w:val="0"/>'
    heading = '<w:pStyle w:val="Heading2"/>'
    return synthetic_docx(
        body=lines("PAGINIERUNGSBELEG", '<w:pStyle w:val="Heading1"/>' + disabled)
        + lines(control_filler, "<w:pageBreakBefore/>")
        + lines("CONTROL-TITLE", heading + disabled)
        + lines(control_lines, disabled)
        + lines(kept_filler, "<w:pageBreakBefore/>")
        + lines("KEPT-TITLE", heading + "<w:keepNext/>")
        + lines(kept_lines, '<w:keepLines/><w:keepNext w:val="false"/>')
    )
