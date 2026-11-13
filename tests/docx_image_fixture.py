"""Deterministic synthetic image-bearing DOCX; no customer data."""

from io import BytesIO
from zipfile import ZipFile, ZipInfo

from suite.platform.office_image_codec import png_from_pixels
from work_e2e_docx import synthetic_docx


def alpha_png() -> bytes:
    row = b"\0\x80\xff\0" * 80 + b"\0\x80\xff\x80" * 80 + b"\0\x80\xff\xff" * 160
    return png_from_pixels(320, 120, row * 120)


def drawing(alt: str = "Transparentes Quellbild") -> str:
    return (
        '<w:p><w:r><w:drawing xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<wp:inline><wp:extent cx="3048000" cy="1143000"/><wp:docPr id="1" name="Bild" descr="{alt}"/>'
        '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic><pic:blipFill><a:blip r:embed="rIdImage"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
        '<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="3048000" cy="1143000"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
        "</a:graphicData></a:graphic></wp:inline></w:drawing></w:r></w:p>"
    )


def image_docx() -> bytes:
    output = BytesIO()
    with ZipFile(BytesIO(synthetic_docx())) as source, ZipFile(output, "w") as target:
        for name in source.namelist():
            content = source.read(name)
            if name == "[Content_Types].xml":
                content = content.replace(b"</Types>", b'<Default Extension="png" ContentType="image/png"/></Types>')
            if name == "word/document.xml":
                content = content.replace(
                    b"</w:body>",
                    (drawing("Erstes transparentes Quellbild") + drawing("Zweites Quellbild") + "</w:body>").encode(),
                )
            target.writestr(ZipInfo(name), content)
        target.writestr(ZipInfo("word/media/alpha.png"), alpha_png())
        target.writestr(
            ZipInfo("word/_rels/document.xml.rels"),
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rIdImage" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
            'Target="media/alpha.png"/></Relationships>',
        )
    return output.getvalue()
