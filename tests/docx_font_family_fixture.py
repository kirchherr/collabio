"""Stored synthetic DOCX with directly assigned native primary font families."""

from docx_paragraph_alignment_fixture import literal, paragraph
from work_e2e_docx import synthetic_docx

SOURCE_ID = "work-e2e-stored-docx-font-family"
SOURCE_VERSION = "stored-docx-font-family-v1"
SOURCE_TITLE = "Synthetische gespeicherte DOCX-Quelle mit Schriftfamilien"
FAMILIES = (("Arial", "sans"), ("Georgia", "serif"), ("Consolas", "mono"))


def family_run(text: str, font: str, properties: str = "") -> str:
    return f'<w:r><w:rPr><w:rFonts w:ascii="{font}" w:hAnsi="{font}"/>{properties}</w:rPr><w:t>{text}</w:t></w:r>'


def font_family_docx() -> bytes:
    return synthetic_docx(
        body=paragraph(
            family_run("FAMILIENKOPF", "Arial", '<w:sz w:val="48"/>'), other_properties='<w:pStyle w:val="Heading1"/>'
        )
        + paragraph(family_run("SANSBELEG", "Arial"))
        + paragraph(family_run("SERIFBELEG", "Georgia", '<w:b/><w:sz w:val="36"/><w:color w:val="B91C1C"/>'))
        + paragraph(family_run("MONOBELEG", "Consolas", '<w:i/><w:sz w:val="24"/>'))
        + paragraph(
            family_run("IIIIIIII", "Consolas", '<w:sz w:val="24"/>')
            + literal(" ")
            + family_run("WWWWWWWW", "Consolas", '<w:sz w:val="24"/>')
        )
        + "<w:tbl><w:tr><w:trPr><w:tblHeader/></w:trPr><w:tc><w:p>"
        + family_run("MONOKOPF", "Consolas", '<w:sz w:val="28"/>')
        + "</w:p></w:tc></w:tr><w:tr><w:tc><w:p>"
        + family_run("SERIFZELLE", "Georgia", '<w:color w:val="1D4ED8"/>')
        + "</w:p></w:tc></w:tr></w:tbl>"
    )
