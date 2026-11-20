"""Stored synthetic DOCX with explicit baseline, super- and subscript runs."""

from docx_paragraph_alignment_fixture import literal, paragraph
from work_e2e_docx import synthetic_docx

SOURCE_ID = "work-e2e-stored-docx-vertical-position"
SOURCE_VERSION = "stored-docx-vertical-position-v1"
SOURCE_TITLE = "Synthetische gespeicherte DOCX-Quelle mit Zeichenlagen"


def positioned_run(text: str, position: str, properties: str = "") -> str:
    return f'<w:r><w:rPr><w:vertAlign w:val="{position}"/>{properties}</w:rPr><w:t>{text}</w:t></w:r>'


def vertical_position_docx() -> bytes:
    size = '<w:sz w:val="24"/>'
    return synthetic_docx(
        body=paragraph(literal("ZEICHENLAGEN"), other_properties='<w:pStyle w:val="Heading1"/>')
        + paragraph(
            positioned_run("GRUNDBELEG", "baseline", size)
            + literal(" ")
            + positioned_run("HOCHBELEG", "superscript", size + '<w:b/><w:color w:val="B91C1C"/>')
            + literal(" ")
            + positioned_run("TIEFBELEG", "subscript", size + "<w:i/>")
        )
        + paragraph(
            positioned_run(
                "MISCHBELEG",
                "superscript",
                '<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/><w:sz w:val="28"/><w:color w:val="1D4ED8"/>',
            )
        )
        + paragraph(positioned_run("NORMALBELEG", "baseline", size + "<w:u/>"))
        + "<w:tbl><w:tr><w:trPr><w:tblHeader/></w:trPr><w:tc><w:p>"
        + positioned_run("KOPFHOCH", "superscript", size)
        + "</w:p></w:tc></w:tr><w:tr><w:tc><w:p>"
        + positioned_run("ZELLTIEF", "subscript", size)
        + "</w:p></w:tc></w:tr></w:tbl>"
    )
