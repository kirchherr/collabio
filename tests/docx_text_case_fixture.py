"""Stored synthetic DOCX with direct display casing and unchanged source text."""

from docx_paragraph_alignment_fixture import literal, paragraph
from work_e2e_docx import synthetic_docx

SOURCE_ID = "work-e2e-stored-docx-text-case"
SOURCE_VERSION = "stored-docx-text-case-v1"
SOURCE_TITLE = "Synthetische gespeicherte DOCX-Quelle mit Schreibweisen"


def case_run(text: str, marker: str, properties: str = "") -> str:
    return f"<w:r><w:rPr>{marker}{properties}</w:rPr><w:t>{text}</w:t></w:r>"


def text_case_docx() -> bytes:
    size = '<w:sz w:val="24"/>'
    return synthetic_docx(
        body=paragraph(literal("SCHREIBWEISEN"), other_properties='<w:pStyle w:val="Heading1"/>')
        + paragraph(case_run("Versalienbeleg", "<w:caps/>", size + '<w:b/><w:color w:val="B91C1C"/>'))
        + paragraph(case_run("Kapitellbeleg", '<w:smallCaps w:val="true"/>', size + "<w:i/>"))
        + paragraph(case_run("Normalbeleg", '<w:caps w:val="false"/>', size))
        + paragraph(case_run("Ohnekapitell", '<w:smallCaps w:val="0"/>', size))
        + paragraph(
            case_run(
                "Mischbeleg",
                '<w:caps w:val="on"/>',
                '<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/><w:sz w:val="28"/>'
                '<w:color w:val="1D4ED8"/><w:vertAlign w:val="superscript"/>',
            )
        )
        + "<w:tbl><w:tr><w:trPr><w:tblHeader/></w:trPr><w:tc><w:p>"
        + case_run("Kopfbeleg", '<w:caps w:val="1"/>', size)
        + "</w:p></w:tc></w:tr><w:tr><w:tc><w:p>"
        + case_run("Zellbeleg", "<w:smallCaps/>", size)
        + "</w:p></w:tc></w:tr></w:tbl>"
    )
