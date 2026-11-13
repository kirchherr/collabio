"""Stored synthetic DOCX with explicit run sizes in native text structures."""

from docx_paragraph_alignment_fixture import paragraph
from work_e2e_docx import synthetic_docx

SOURCE_ID = "work-e2e-stored-docx-font-size"
SOURCE_VERSION = "stored-docx-font-size-v1"
SOURCE_TITLE = "Synthetische gespeicherte DOCX-Quelle mit Schriftgroessen"


def sized_run(text: str, half_points: str, properties: str = "") -> str:
    return f'<w:r><w:rPr><w:sz w:val="{half_points}"/>{properties}</w:rPr><w:t>{text}</w:t></w:r>'


def font_size_docx() -> bytes:
    return synthetic_docx(
        body=paragraph(sized_run("GROESSENKOPF", "48"), other_properties='<w:pStyle w:val="Heading1"/>')
        + paragraph(sized_run("GROESSE08", "16"))
        + paragraph(sized_run("GROESSE12", "24", "<w:b/>"))
        + paragraph(sized_run("GROESSE24", "48"))
        + paragraph(sized_run("GROESSE48", "96"))
        + "<w:tbl><w:tr><w:trPr><w:tblHeader/></w:trPr><w:tc><w:p>"
        + sized_run("TABELLENKOPF", "28")
        + "</w:p></w:tc></w:tr><w:tr><w:tc><w:p>"
        + sized_run("TABELLENTEXT", "20")
        + "</w:p></w:tc></w:tr></w:tbl>"
    )
