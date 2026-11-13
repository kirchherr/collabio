"""Synthetic immutable DOCX with an explicit internal link and two bookmark placements."""

from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile, ZipInfo

from work_e2e_docx import synthetic_docx

SOURCE_ID = "work-e2e-stored-docx-navigation"
SOURCE_VERSION = "stored-docx-navigation-v1"
SOURCE_TITLE = "Synthetische gespeicherte DOCX-Quelle mit Textmarken"
RELATIONSHIP = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
LINK = (
    '<w:hyperlink w:anchor="Section_Target" w:history="1">'
    '<w:r><w:rPr><w:rStyle w:val="Hyperlink"/><w:b/></w:rPr><w:t>Zum Ziel</w:t></w:r>'
    '<w:r><w:t xml:space="preserve"> springen</w:t></w:r></w:hyperlink>'
)
POINT = '<w:bookmarkStart w:id="1" w:name="Start_Point"/><w:bookmarkEnd w:id="1"/>'
TARGET_START = '<w:bookmarkStart w:id="7" w:name="Section_Target"/>'
TARGET_END = '<w:bookmarkEnd w:id="7"/>'
NAVIGATION_BODY = (
    f"<w:p>{POINT}{LINK}</w:p>"
    f'<w:p><w:hyperlink xmlns:r="{RELATIONSHIP}" r:id="rIdExternal">'
    "<w:r><w:t>Nur lesbarer Fremdlink</w:t></w:r></w:hyperlink></w:p>"
    '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
    f"{TARGET_START}<w:r><w:t>Dokumentziel</w:t></w:r>{TARGET_END}</w:p>"
    '<w:p><w:bookmarkStart w:id="9" w:name="_GoBack"/><w:bookmarkEnd w:id="9"/>'
    "<w:r><w:t>Abschluss</w:t></w:r></w:p>"
)


def navigation_docx(body: str = NAVIGATION_BODY) -> bytes:
    output = BytesIO()
    with ZipFile(BytesIO(synthetic_docx(body=body))) as original, ZipFile(output, "w") as archive:
        for name in original.namelist():
            archive.writestr(ZipInfo(name), original.read(name))
        archive.writestr(
            ZipInfo("word/_rels/document.xml.rels"),
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rIdExternal" Type="{RELATIONSHIP}/hyperlink" '
            'Target="https://office-navigation.invalid/target" TargetMode="External"/></Relationships>',
        )
    return output.getvalue()
