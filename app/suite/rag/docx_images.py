"""Package-local inert picture extraction, used only inside the isolated parser."""

from __future__ import annotations

import base64
import re
from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from suite.rag.parser_worker import ParserWorkerError, sha256_bytes

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
WP = "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
PIC = "{http://schemas.openxmlformats.org/drawingml/2006/picture}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
CT = "{http://schemas.openxmlformats.org/package/2006/content-types}"
MAX_DOCX_IMAGES = 8
MAX_DOCX_MEDIA_BYTES = 1024 * 1024
MAX_DOCX_IMAGE_PIXELS = 4_000_000
IMAGE_RELATIONSHIP = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"


def _invalid() -> ParserWorkerError:
    return ParserWorkerError("DOCX picture is outside the bounded embedded image scope")


def _xml(archive: ZipFile, name: str) -> ET.Element:
    try:
        raw = archive.read(name)
        declarations = raw.replace(b"\x00", b"").upper()
        if len(raw) > MAX_DOCX_MEDIA_BYTES or b"<!DOCTYPE" in declarations or b"<!ENTITY" in declarations:
            raise _invalid()
        return ET.fromstring(raw)
    except (KeyError, ET.ParseError) as exc:
        raise _invalid() from exc


def extract_docx_images(content: bytes, root: ET.Element) -> dict[ET.Element, dict[str, object]]:
    drawings = list(root.iter(f"{W}drawing"))
    if any(node.tag in {f"{W}pict", f"{W}object", f"{WP}anchor"} for node in root.iter()):
        raise _invalid()
    if not drawings:
        return {}
    if len(drawings) > MAX_DOCX_IMAGES:
        raise _invalid()
    body = root.find(f"{W}body")
    if body is None:
        raise _invalid()
    result: dict[ET.Element, dict[str, object]] = {}
    byte_count = 0
    with ZipFile(BytesIO(content)) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise _invalid()
        relationships = _xml(archive, "word/_rels/document.xml.rels")
        if relationships.tag != f"{REL}Relationships":
            raise _invalid()
        targets: dict[str, str] = {}
        seen: set[str] = set()
        for relationship in relationships:
            identifier = relationship.get("Id", "")
            if relationship.tag != f"{REL}Relationship" or not identifier or identifier in seen:
                raise _invalid()
            seen.add(identifier)
            if relationship.get("Type") != IMAGE_RELATIONSHIP:
                continue
            target = relationship.get("Target", "")
            if (
                relationship.get("TargetMode", "Internal") != "Internal"
                or re.fullmatch(r"media/[A-Za-z0-9_-][A-Za-z0-9_.-]{0,120}\.(?:png|jpg|jpeg)", target) is None
                or ".." in target
            ):
                raise _invalid()
            targets[identifier] = target
        types = _xml(archive, "[Content_Types].xml")
        if types.tag != f"{CT}Types":
            raise _invalid()
        content_types: dict[str, str] = {}
        for entry in types:
            key = entry.get("PartName") if entry.tag == f"{CT}Override" else entry.get("Extension")
            if not key or key in content_types or entry.tag not in {f"{CT}Override", f"{CT}Default"}:
                raise _invalid()
            content_types[key] = entry.get("ContentType", "")
        for paragraph in body.findall(f"{W}p"):
            pictures = list(paragraph.iter(f"{W}drawing"))
            if not pictures:
                continue
            if (
                len(pictures) != 1
                or paragraph.find(f"{W}pPr/{W}numPr") is not None
                or paragraph.find(f"{W}pPr/{W}pStyle") is not None
            ):
                raise _invalid()
            # The picture occupies its own paragraph; mixed content cannot be reordered silently.
            allowed = {f"{W}p", f"{W}pPr", f"{W}pageBreakBefore", f"{W}r", f"{W}rPr", f"{W}drawing"}
            for node in paragraph.iter():
                if node in pictures[0].iter():
                    continue
                if node.tag not in allowed:
                    raise _invalid()
            drawing = pictures[0]
            if any(
                sum(1 for _ in drawing.iter(tag)) != 1
                for tag in (f"{WP}inline", f"{A}graphic", f"{A}graphicData", f"{PIC}pic", f"{A}blip")
            ):
                raise _invalid()
            drawing_tags = {
                f"{W}drawing",
                f"{WP}inline",
                f"{WP}extent",
                f"{WP}docPr",
                f"{WP}cNvGraphicFramePr",
                f"{A}graphic",
                f"{A}graphicData",
                f"{A}graphicFrameLocks",
                f"{PIC}pic",
                f"{PIC}nvPicPr",
                f"{PIC}cNvPr",
                f"{PIC}cNvPicPr",
                f"{PIC}blipFill",
                f"{A}blip",
                f"{A}stretch",
                f"{A}fillRect",
                f"{PIC}spPr",
                f"{A}xfrm",
                f"{A}off",
                f"{A}ext",
                f"{A}prstGeom",
                f"{A}avLst",
            }
            if any(node.tag not in drawing_tags for node in drawing.iter()):
                raise _invalid()
            for node in drawing.iter():
                if node.tag == f"{A}prstGeom" and node.get("prst") != "rect":
                    raise _invalid()
                if node.tag == f"{A}fillRect" and node.attrib:
                    raise _invalid()
                if node.tag == f"{A}off" and node.attrib != {"x": "0", "y": "0"}:
                    raise _invalid()
                if node.tag in {f"{WP}docPr", f"{PIC}cNvPr"} and node.get("hidden", "false") not in {"false", "0"}:
                    raise _invalid()
            if len(drawing) != 1 or drawing[0].tag != f"{WP}inline":
                raise _invalid()
            inline = drawing[0]
            graphic = inline.find(f"{A}graphic/{A}graphicData")
            if graphic is None or graphic.get("uri") != PIC[1:-1] or len(graphic) != 1:
                raise _invalid()
            picture = graphic[0]
            if picture.tag != f"{PIC}pic":
                raise _invalid()
            blips = list(picture.iter(f"{A}blip"))
            if len(blips) != 1 or set(blips[0].attrib) != {f"{R}embed"} or len(blips[0]):
                raise _invalid()
            if any(
                node.tag in {f"{A}srcRect", f"{A}effectLst", f"{A}effectDag", f"{A}extLst"} for node in picture.iter()
            ):
                raise _invalid()
            for transform in picture.iter(f"{A}xfrm"):
                if transform.attrib:
                    raise _invalid()
            target = targets.get(blips[0].get(f"{R}embed", ""), "")
            if not target:
                raise _invalid()
            mime = "image/png" if target.endswith(".png") else "image/jpeg"
            if content_types.get(f"/word/{target}", content_types.get(target.rsplit(".", 1)[1])) != mime:
                raise _invalid()
            try:
                info = archive.getinfo(f"word/{target}")
                byte_count += info.file_size
                if byte_count > MAX_DOCX_MEDIA_BYTES or info.file_size < 1:
                    raise _invalid()
                raw = archive.read(info)
            except KeyError as exc:
                raise _invalid() from exc
            if (mime == "image/png" and not raw.startswith(b"\x89PNG\r\n\x1a\n")) or (
                mime == "image/jpeg" and not raw.startswith(b"\xff\xd8\xff")
            ):
                raise _invalid()
            properties = inline.find(f"{WP}docPr")
            alt = "" if properties is None else properties.get("descr", properties.get("title", ""))
            if len(alt) > 500 or any(ord(c) < 32 or 127 <= ord(c) <= 159 for c in alt):
                raise _invalid()
            result[paragraph] = {
                "kind": "image",
                "mime_type": mime,
                "content_base64": base64.b64encode(raw).decode("ascii"),
                "content_hash": sha256_bytes(raw),
                "alt": alt.strip() or "Importiertes DOCX-Bild",
            }
        if len(result) != len(drawings):
            raise _invalid()
    return result
