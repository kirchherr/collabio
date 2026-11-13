"""Resolve bounded default running text from an already inventoried DOCX package."""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from suite.rag.docx_images import CT, REL, R, W

RUNNING_TAGS = {f"{W}headerReference", f"{W}footerReference"}
NATIVE_RUNNING_FIELD_PREFIX = "{{field:"
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"
_RELATIONSHIP_TYPE = R[1:-1] + "/"
_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml."


class UnsupportedDocxRunningText(ValueError):
    pass


def _invalid() -> UnsupportedDocxRunningText:
    return UnsupportedDocxRunningText("DOCX running text is outside the bounded literal profile")


def _xml(archive: ZipFile, name: str, limit: int) -> ET.Element:
    try:
        info = archive.getinfo(name)
        if not 1 <= info.file_size <= limit:
            raise _invalid()
        raw = archive.read(info)
        declarations = raw.replace(b"\x00", b"").upper()
        if b"<!DOCTYPE" in declarations or b"<!ENTITY" in declarations:
            raise _invalid()
        return ET.fromstring(raw)
    except (KeyError, ET.ParseError, BadZipFile, RuntimeError, OSError) as exc:
        raise _invalid() from exc


def _children(element: ET.Element, tag: str) -> list[ET.Element]:
    if (
        element.tag != tag
        or element.attrib
        or (element.text or "").strip()
        or any((child.tail or "").strip() for child in element)
    ):
        raise _invalid()
    return list(element)


def _literal(archive: ZipFile, names: set[str], kind: str, name: str) -> str:
    root = _xml(archive, f"word/{name}", 16 * 1024)
    paragraphs = _children(root, f"{W}{'hdr' if kind == 'header' else 'ftr'}")
    if len(paragraphs) != 1 or f"word/_rels/{name}.rels".casefold() in names:
        raise _invalid()
    parts: list[str] = []
    for run in _children(paragraphs[0], f"{W}p"):
        values = _children(run, f"{W}r")
        if len(values) != 1:
            raise _invalid()
        text = values[0]
        if text.tag != f"{W}t" or len(text) or text.attrib not in ({}, {_XML_SPACE: "preserve"}):
            raise _invalid()
        parts.append(text.text or "")
    literal = "".join(parts)
    if (
        len(literal) > 64
        or NATIVE_RUNNING_FIELD_PREFIX in literal
        or any(ord(char) < 32 or 127 <= ord(char) <= 159 or char in "\u2028\u2029" for char in literal)
    ):
        raise _invalid()
    return literal


def _check_settings(archive: ZipFile, names: set[str], relationships: list[ET.Element]) -> None:
    settings = [entry for entry in relationships if entry.get("Type") == _RELATIONSHIP_TYPE + "settings"]
    if len(settings) > 1 or (
        settings
        and (settings[0].get("Target") != "settings.xml" or settings[0].get("TargetMode", "Internal") != "Internal")
    ):
        raise _invalid()
    if not settings and "word/settings.xml" not in names:
        return
    root = _xml(archive, "word/settings.xml", 128 * 1024)
    alternate = list(root.iter(f"{W}evenAndOddHeaders"))
    if (
        root.tag != f"{W}settings"
        or len(alternate) > 1
        or (
            alternate
            and (
                alternate[0] not in root
                or len(alternate[0])
                or (alternate[0].text or "").strip()
                or set(alternate[0].attrib) != {f"{W}val"}
                or alternate[0].get(f"{W}val") not in {"0", "false", "off"}
            )
        )
    ):
        raise _invalid()


def docx_running_profiles(archive: ZipFile, sections: list[ET.Element]) -> list[dict[str, str]] | None:
    if not any(child.tag in RUNNING_TAGS for section in sections for child in section):
        return None
    relationships = _children(_xml(archive, "word/_rels/document.xml.rels", 128 * 1024), f"{REL}Relationships")
    by_id = {entry.get("Id"): entry for entry in relationships}
    if len(by_id) != len(relationships) or not all(
        entry.tag == f"{REL}Relationship" and entry.get("Id") and not len(entry) and not (entry.text or "").strip()
        for entry in relationships
    ):
        raise _invalid()
    names = {name.casefold() for name in archive.namelist()}
    _check_settings(archive, names, relationships)
    types = _children(_xml(archive, "[Content_Types].xml", 128 * 1024), f"{CT}Types")
    overrides = [entry for entry in types if entry.tag == f"{CT}Override"]
    by_part = {entry.get("PartName"): entry.get("ContentType") for entry in overrides}
    if len(by_part) != len(overrides) or any(
        set(entry.attrib) != {"PartName", "ContentType"} or len(entry) or (entry.text or "").strip()
        for entry in overrides
    ):
        raise _invalid()

    cache: dict[str, str] = {}
    running = {"header": "", "footer": ""}
    profiles: list[dict[str, str]] = []
    for section in sections:
        for kind in ("header", "footer"):
            reference = section.find(f"{W}{kind}Reference")
            if reference is None:
                continue
            identifier = reference.get(f"{R}id", "")
            relationship = by_id.get(identifier)
            if (
                set(reference.attrib) != {f"{R}id", f"{W}type"}
                or reference.get(f"{W}type") != "default"
                or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]{0,63}", identifier) is None
                or len(reference)
                or (reference.text or "").strip()
                or relationship is None
                or set(relationship.attrib) not in ({"Id", "Type", "Target"}, {"Id", "Type", "Target", "TargetMode"})
                or relationship.get("Type") != _RELATIONSHIP_TYPE + kind
                or relationship.get("TargetMode", "Internal") != "Internal"
            ):
                raise _invalid()
            target = relationship.get("Target", "")
            if (
                re.fullmatch(rf"{kind}[A-Za-z0-9_-]{{0,48}}\.xml", target) is None
                or by_part.get(f"/word/{target}") != f"{_CONTENT_TYPE}{kind}+xml"
            ):
                raise _invalid()
            if target not in cache:
                cache[target] = _literal(archive, names, kind, target)
            running[kind] = cache[target]
        profiles.append(running.copy())
    return profiles
