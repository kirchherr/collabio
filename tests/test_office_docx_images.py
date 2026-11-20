import base64
from copy import deepcopy
from io import BytesIO
from zipfile import ZipFile, ZipInfo

import pytest

from docx_image_fixture import alpha_png, drawing, image_docx
from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.platform.office_docx_images import DocxPreviewImages
from suite.platform.office_image_codec import png_from_pixels
from suite.platform.office_import_preview import OfficeImportPreviewInvalid, OfficeImportPreviewService
from suite.rag.parser_worker import ParserWorkerError
from suite.rag.rich_document_parser import RichDocumentParserWorker
from suite.storage.source_objects import InMemorySourceObjectRepository
from test_office_import_preview import command, source_record, user
from test_rich_document_parser import DOCX_MIME_TYPE, request_for


def replace_part(name: str, old: bytes, new: bytes) -> bytes:
    output = BytesIO()
    with ZipFile(BytesIO(image_docx())) as source, ZipFile(output, "w") as target:
        for member in source.namelist():
            content = source.read(member)
            target.writestr(ZipInfo(member), content.replace(old, new) if member == name else content)
    return output.getvalue()


def parse(content: bytes):  # type: ignore[no-untyped-def]
    return RichDocumentParserWorker().parse(request_for(mime_type=DOCX_MIME_TYPE, content=content))


def test_image_blocks_are_ordered_hash_bound_and_do_not_change_text() -> None:
    artifact = parse(image_docx())
    images = [block for block in artifact.document_blocks if block["kind"] == "image"]
    assert len(images) == 2
    assert [block["alt"] for block in images] == ["Erstes transparentes Quellbild", "Zweites Quellbild"]
    assert base64.b64decode(str(images[0]["content_base64"])) == alpha_png()
    record = source_record(image_docx())
    audit = InMemoryAuditLogger()
    preview = OfficeImportPreviewService(
        source_repository=InMemorySourceObjectRepository((record,)),
        audit=audit,
        parser_dispatch=RichDocumentParserWorker().parse,
        image_normalizer=lambda raw, mime: (raw, 320, 120),
    ).preview(user_context=user(), command=command())
    assert preview.content_persisted is False
    assert len(preview.image_previews) == 2
    assert preview.document["content"][-1]["type"] == "image"
    assert preview.image_previews[0]["image"]["assetId"] != preview.image_previews[1]["image"]["assetId"]
    assert "content_base64" not in str(audit.events[-1].metadata)
    assert "Transparent" not in str(audit.events[-1].metadata)


@pytest.mark.parametrize(
    "target",
    [
        b"../alpha.png",
        b"/word/media/alpha.png",
        b"https://example.invalid/a.png",
        b"media/a%2epng",
        b"media/a..png",
        b"media/missing.png",
    ],
)
def test_package_image_targets_fail_closed(target: bytes) -> None:
    with pytest.raises(ParserWorkerError):
        parse(replace_part("word/_rels/document.xml.rels", b"media/alpha.png", target))


@pytest.mark.parametrize(
    ("part", "old", "new"),
    [
        ("word/_rels/document.xml.rels", b'Target="', b'TargetMode="External" Target="'),
        ("word/_rels/document.xml.rels", b"</Relationships>", b'<Relationship Id="rIdImage"/></Relationships>'),
        ("[Content_Types].xml", b"image/png", b"image/svg+xml"),
        ("word/media/alpha.png", b"\x89PNG", b"XXXX"),
        ("word/document.xml", b"wp:inline", b"wp:anchor"),
        ("word/document.xml", b"<a:xfrm>", b'<a:xfrm rot="5400000">'),
        ("word/document.xml", b"<a:stretch>", b'<a:srcRect l="5"/><a:stretch>'),
        ("word/document.xml", b"<pic:spPr>", b"<pic:spPr><a:unknown/>"),
        ("word/document.xml", b'prst="rect"', b'prst="ellipse"'),
        ("word/document.xml", b'<a:off x="0"', b'<a:off x="10"'),
        ("word/document.xml", b"<a:fillRect/>", b'<a:fillRect l="10"/>'),
        ("word/document.xml", b"<wp:docPr ", b'<wp:docPr hidden="1" '),
        ("word/document.xml", b"</a:graphic>", b"</a:graphic><a:graphic/>"),
        ("word/document.xml", b"<w:drawing", b"<w:t>Mixed</w:t><w:drawing"),
        ("word/document.xml", b"<w:drawing", b"<w:pict/><w:drawing"),
        ("word/document.xml", b"<w:body>", b"<w:body>" + drawing().encode() * 9),
    ],
)
def test_unsupported_or_ambiguous_picture_content_fails_closed(part: str, old: bytes, new: bytes) -> None:
    with pytest.raises(ParserWorkerError):
        parse(replace_part(part, old, new))


@pytest.mark.parametrize("tamper", ["hash", "base64", "extra", "alt", "mime", "oversized"])
def test_api_independently_rejects_invalid_media_before_normalization(tamper: str) -> None:
    block = deepcopy(parse(image_docx()).document_blocks[-1])
    if tamper == "hash":
        block["content_hash"] = "sha256:" + "0" * 64
    elif tamper == "base64":
        block["content_base64"] = "!"
    elif tamper == "extra":
        block["url"] = "https://example.invalid"
    elif tamper == "alt":
        block["alt"] = "bad\nmetadata"
    elif tamper == "mime":
        block["mime_type"] = "image/svg+xml"
    else:
        block["content_base64"] = "A" * 1_400_000
    with pytest.raises(ValueError):
        DocxPreviewImages({}, lambda raw, mime: (alpha_png(), 320, 120)).build(block)


def test_aggregate_pixels_and_count_are_bounded_independently() -> None:
    block = parse(image_docx()).document_blocks[-1]
    pixels = DocxPreviewImages({}, lambda raw, mime: (b"trusted-test-png", 2000, 2000))
    pixels.build(block)
    with pytest.raises(ValueError, match="aggregate pixel"):
        pixels.build(block)
    count = DocxPreviewImages({}, lambda raw, mime: (png_from_pixels(1, 1, b"\0" * 4), 1, 1))
    for _ in range(8):
        count.build(block)
    with pytest.raises(ValueError):
        count.build(block)


def test_invalid_parser_image_errors_are_safe_import_errors() -> None:
    from dataclasses import replace

    from suite.rag.parser_worker import hash_document_blocks

    artifact = parse(image_docx())
    blocks = (*artifact.document_blocks[:-1], {**artifact.document_blocks[-1], "content_hash": "bad"})
    invalid = replace(artifact, document_blocks=blocks, document_blocks_hash=hash_document_blocks(blocks))
    service = OfficeImportPreviewService(
        source_repository=InMemorySourceObjectRepository((source_record(image_docx()),)),
        audit=InMemoryAuditLogger(),
        parser_dispatch=lambda request: invalid,
        image_normalizer=lambda raw, mime: (raw, 320, 120),
    )
    with pytest.raises(OfficeImportPreviewInvalid):
        service.preview(user_context=user(), command=command())


@pytest.mark.parametrize("part", ["word/document.xml", "word/_rels/document.xml.rels", "[Content_Types].xml"])
def test_utf16_declarations_cannot_bypass_the_xml_policy(part: str) -> None:
    with ZipFile(BytesIO(image_docx())) as archive:
        original = archive.read(part)
    forbidden = ('<!DOCTYPE root [<!ENTITY example "inert">]>' + original.decode()).encode("utf-16")
    with pytest.raises(ParserWorkerError):
        parse(replace_part(part, original, forbidden))
