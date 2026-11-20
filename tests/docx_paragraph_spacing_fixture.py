"""Synthetic stored DOCX with direct line and paragraph spacing."""

from docx_paragraph_alignment_fixture import literal, paragraph
from work_e2e_docx import synthetic_docx

SOURCE_ID = "work-e2e-stored-docx-paragraph-spacing"
SOURCE_VERSION = "stored-docx-paragraph-spacing-v1"
SOURCE_TITLE = "Synthetische gespeicherte DOCX-Quelle mit Absatzabstaenden"


def spaced_paragraph(text: str, spacing: str, *, other_properties: str = "", alignment: str = "") -> str:
    runs = "<w:r><w:br/></w:r>".join(literal(line) for line in text.split("\n"))
    return paragraph(runs, alignment=alignment, other_properties=f"{other_properties}<w:spacing {spacing}/>")


def paragraph_spacing_docx() -> bytes:
    return synthetic_docx(
        body=spaced_paragraph(
            "ABSTANDKOPF",
            'w:before="0" w:after="240" w:line="276" w:lineRule="auto"',
            other_properties='<w:pStyle w:val="Heading1"/>',
            alignment="center",
        )
        + spaced_paragraph("EINFACH1\nEINFACH2", 'w:before="0" w:after="0" w:line="240"')
        + spaced_paragraph("DOPPELT1\nDOPPELT2", 'w:before="240" w:after="120" w:line="480"')
        + spaced_paragraph("DANACH", 'w:before="0" w:after="0" w:line="240"')
        + spaced_paragraph("ABSTAND24\nZEILEN15", 'w:before="480" w:after="0" w:line="360"')
    )
