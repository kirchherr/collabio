"""Deterministic synthetic DOCX with default, inherited and cleared running text."""

from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile, ZipInfo

from work_e2e_docx import FIRST_SECTION, LAST_SECTION, synthetic_docx

WORD = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
RELATIONSHIP = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL_ROOT = "http://schemas.openxmlformats.org/package/2006/relationships"
SOURCE_ID = "work-e2e-stored-docx-running"
SOURCE_VERSION = "stored-docx-running-v1"
SOURCE_TITLE = "Synthetische gespeicherte DOCX-Quelle mit Kopf- und Fußzeilen"
HEADER = 'DOCX Header "literal"'
FOOTER = "DOCX Footer Alpha"
SECOND_FOOTER = "DOCX Footer Beta"


def _reference(kind: str, number: int) -> str:
    return f'<w:{kind}Reference xmlns:r="{RELATIONSHIP}" w:type="default" r:id="{kind}{number}"/>'


def _profile(geometry: str, references: str) -> str:
    return geometry.replace("<w:sectPr>", "<w:sectPr>" + references, 1)


def _paragraph(number: str, section: str = "") -> str:
    properties = f"<w:pPr>{section}</w:pPr>" if section else ""
    return f"<w:p>{properties}<w:r><w:t>DOCX Body {number}</w:t></w:r></w:p>"


RUNNING_BODY = (
    _paragraph("One", _profile(FIRST_SECTION, _reference("header", 1) + _reference("footer", 1)))
    + _paragraph("Two", _profile(LAST_SECTION, _reference("footer", 2)))
    + _paragraph("Three")
    + _profile(FIRST_SECTION, _reference("header", 2))
)
RELATIONSHIPS = (
    f'<Relationships xmlns="{REL_ROOT}">'
    + "".join(
        f'<Relationship Id="{kind}{number}" Type="{RELATIONSHIP}/{kind}" Target="{kind}{number}.xml"/>'
        for kind in ("header", "footer")
        for number in (1, 2)
    )
    + "</Relationships>"
)
_OVERRIDES = "".join(
    f'<Override PartName="/word/{kind}{number}.xml" '
    f'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.{kind}+xml"/>'
    for kind in ("header", "footer")
    for number in (1, 2)
)


def running_part(root: str, text: str = "") -> str:
    inner = f"<w:r><w:t>{text}</w:t></w:r>" if text else ""
    return f'<w:{root} xmlns:w="{WORD}"><w:p>{inner}</w:p></w:{root}>'


def running_docx(
    *,
    body: str = RUNNING_BODY,
    relationships: str = RELATIONSHIPS,
    overrides: str = _OVERRIDES,
    extra: dict[str, str | bytes | None] | None = None,
) -> bytes:
    members: dict[str, str | bytes | None] = {
        "word/_rels/document.xml.rels": relationships,
        "word/header1.xml": running_part("hdr", HEADER),
        "word/header2.xml": running_part("hdr"),
        "word/footer1.xml": running_part("ftr", FOOTER),
        "word/footer2.xml": running_part("ftr", SECOND_FOOTER),
        **(extra or {}),
    }
    output = BytesIO()
    with ZipFile(BytesIO(synthetic_docx(body=body))) as original, ZipFile(output, "w") as archive:
        for name in original.namelist():
            content = original.read(name)
            if name == "[Content_Types].xml":
                content = content.replace(b"</Types>", overrides.encode() + b"</Types>")
            archive.writestr(ZipInfo(name), content)
        for name, value in members.items():
            if value is not None:
                archive.writestr(ZipInfo(name), value)
    return output.getvalue()
