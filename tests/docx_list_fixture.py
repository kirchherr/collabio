"""Stored synthetic DOCX with nested lists, restart and continuation."""

from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile, ZipInfo

from work_e2e_docx import synthetic_docx

SOURCE_ID = "work-e2e-stored-docx-lists"
SOURCE_VERSION = "stored-docx-lists-v1"
SOURCE_TITLE = "Synthetische gespeicherte DOCX-Quelle mit Listen"
NUMBERING = (
    '<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    '<w:abstractNum w:abstractNumId="1">'
    '<w:lvl w:ilvl="0"><w:start w:val="4"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/></w:lvl>'
    '<w:lvl w:ilvl="1"><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/></w:lvl>'
    '<w:lvl w:ilvl="2"><w:start w:val="3"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%3."/></w:lvl>'
    '</w:abstractNum><w:num w:numId="5"><w:abstractNumId w:val="1"/></w:num>'
    '<w:num w:numId="6"><w:abstractNumId w:val="1"/>'
    '<w:lvlOverride w:ilvl="0"><w:startOverride w:val="9"/></w:lvlOverride></w:num></w:numbering>'
)


def item(text: str, depth: int, number: int = 5) -> str:
    return (
        f'<w:p><w:pPr><w:numPr><w:ilvl w:val="{depth}"/><w:numId w:val="{number}"/></w:numPr></w:pPr>'
        f"<w:r><w:t>{text}</w:t></w:r></w:p>"
    )


LIST_BODY = (
    "".join(
        item(text, depth)
        for text, depth in (
            ("Erster Hauptpunkt", 0),
            ("Ein Unterpunkt", 1),
            ("Dritter Tiefenpunkt", 2),
            ("Vierter Tiefenpunkt", 2),
            ("Neuer Unterpunkt", 1),
            ("Tiefenpunkt neu", 2),
            ("Zweiter Hauptpunkt", 0),
        )
    )
    + "<w:p><w:r><w:t>Zwischentext</w:t></w:r></w:p>"
    + (item("Fortsetzung", 0) + item("Neuer Start", 0, 6) + item("Alte Folge", 0))
)


def list_docx(body: str = LIST_BODY, numbering: str | None = NUMBERING) -> bytes:
    output = BytesIO()
    with ZipFile(BytesIO(synthetic_docx(body=body))) as original, ZipFile(output, "w") as archive:
        for name in original.namelist():
            archive.writestr(ZipInfo(name), original.read(name))
        if numbering is not None:
            archive.writestr(ZipInfo("word/numbering.xml"), numbering)
    return output.getvalue()
