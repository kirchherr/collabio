"""Stored synthetic DOCX with exact native palette colors."""

from docx_paragraph_alignment_fixture import paragraph
from work_e2e_docx import synthetic_docx

SOURCE_ID = "work-e2e-stored-docx-text-color"
SOURCE_VERSION = "stored-docx-text-color-v1"
SOURCE_TITLE = "Synthetische gespeicherte DOCX-Quelle mit Textfarben"
PALETTE = (
    ("111827", "black", "SCHWARZ"),
    ("475569", "slate", "SCHIEFER"),
    ("B91C1C", "red", "ROT"),
    ("9A3412", "orange", "ORANGE"),
    ("166534", "green", "GRUEN"),
    ("115E59", "teal", "PETROL"),
    ("1D4ED8", "blue", "BLAU"),
    ("7E22CE", "purple", "VIOLETT"),
)


def colored_run(text: str, rgb: str, properties: str = "") -> str:
    return f'<w:r><w:rPr><w:color w:val="{rgb}"/>{properties}</w:rPr><w:t>{text}</w:t></w:r>'


def text_color_docx() -> bytes:
    body = paragraph(
        colored_run("SCHWARZ", "111827", '<w:sz w:val="48"/>'), other_properties='<w:pStyle w:val="Heading1"/>'
    )
    for rgb, color, text in PALETTE[1:6]:
        properties = '<w:b/><w:sz w:val="36"/>' if color == "red" else "<w:i/>" if color == "orange" else ""
        body += paragraph(colored_run(text, rgb, properties))
    body += "<w:tbl><w:tr><w:trPr><w:tblHeader/></w:trPr><w:tc><w:p>"
    body += colored_run("BLAU", "1D4ED8")
    body += "</w:p></w:tc></w:tr><w:tr><w:tc><w:p>" + colored_run("VIOLETT", "7E22CE")
    return synthetic_docx(body=body + "</w:p></w:tc></w:tr></w:tbl>")
