"""Stored synthetic DOCX with direct paragraph and heading alignment."""

from work_e2e_docx import synthetic_docx

SOURCE_ID = "work-e2e-stored-docx-paragraph-alignment"
SOURCE_VERSION = "stored-docx-paragraph-alignment-v1"
SOURCE_TITLE = "Synthetische gespeicherte DOCX-Quelle mit Absatzausrichtung"
JUSTIFIED = (
    "BLOCKBEGIN Ein synthetischer Absatz fuer den Nachweis der Ausrichtung im exportierten Dokument. "
    "Weitere Woerter sorgen dafuer, dass die erste Zeile im PDF bis zum rechten Rand reicht. BLOCKENDE"
)


def paragraph(runs: str, *, alignment: str = "", other_properties: str = "") -> str:
    marker = f'<w:jc w:val="{alignment}"/>' if alignment else ""
    return f"<w:p><w:pPr>{other_properties}{marker}</w:pPr>{runs}</w:p>"


def literal(text: str) -> str:
    return f"<w:r><w:t>{text}</w:t></w:r>"


def paragraph_alignment_docx() -> bytes:
    return synthetic_docx(
        body=paragraph(literal("MITTEKOPF"), alignment="center", other_properties='<w:pStyle w:val="Heading1"/>')
        + paragraph(literal("LINKSBELEG"), alignment="left")
        + paragraph(literal("MITTEBELEG"), alignment="center")
        + paragraph(literal("RECHTSBELEG"), alignment="right")
        + paragraph(literal(JUSTIFIED), alignment="both")
    )
