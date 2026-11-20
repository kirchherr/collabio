"""Stored synthetic DOCX with direct and special paragraph indents."""

from docx_paragraph_alignment_fixture import literal, paragraph
from work_e2e_docx import synthetic_docx

SOURCE_ID = "work-e2e-stored-docx-paragraph-indentation"
SOURCE_VERSION = "stored-docx-paragraph-indentation-v1"
SOURCE_TITLE = "Synthetische gespeicherte DOCX-Quelle mit Absatzeinzuegen"


def indented_paragraph(text: str, indentation: str, *, alignment: str = "", other_properties: str = "") -> str:
    runs = "<w:r><w:br/></w:r>".join(literal(line) for line in text.split("\n"))
    return paragraph(runs, alignment=alignment, other_properties=f"{other_properties}<w:ind {indentation}/>")


def paragraph_indentation_docx() -> bytes:
    return synthetic_docx(
        body=indented_paragraph(
            "EINZUGKOPF",
            'w:left="360"',
            other_properties='<w:pStyle w:val="Heading1"/><w:spacing w:before="0" w:after="120"/>',
        )
        + indented_paragraph("BASISLINKS", 'w:left="0" w:right="0" w:firstLine="0"')
        + indented_paragraph("LINKSEINZUG", 'w:left="720" w:right="360"')
        + indented_paragraph("RECHTSBASIS", 'w:left="0" w:right="0"', alignment="right")
        + indented_paragraph("RECHTSEINZUG", 'w:left="0" w:right="720"', alignment="right")
        + indented_paragraph("ERSTZEILE\nFOLGEZEILE", 'w:left="360" w:right="0" w:firstLine="720"')
        + indented_paragraph("HAENGEERSTE\nHAENGEFOLGE", 'w:left="720" w:right="0" w:hanging="360"')
    )
