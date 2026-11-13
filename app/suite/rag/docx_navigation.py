"""Bounded bookmark points and explicit same-document links in the main DOCX part."""

from __future__ import annotations

import re
from dataclasses import dataclass
from xml.etree.ElementTree import Element

from suite.rag.docx_images import W

BOOKMARK_NUMBER = re.compile(r"0|[1-9][0-9]{0,8}")
BOOKMARK_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,39}")
BOOKMARK_PREFIX = "docx-bookmark-"
BOOKMARK_LIMIT = 100
LINK_RUN_LIMIT = 200
_HIDDEN_NAME = re.compile(r"_[A-Za-z0-9_]{1,39}")
_XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


class UnsupportedDocxNavigation(ValueError):
    pass


@dataclass(frozen=True)
class DocxNavigation:
    bookmarks: dict[Element, dict[str, str]]
    links: dict[Element, str]


def _invalid() -> UnsupportedDocxNavigation:
    return UnsupportedDocxNavigation("DOCX navigation is outside the bounded bookmark and internal link profile")


def _by_number(elements: list[Element]) -> dict[str, Element]:
    indexed: dict[str, Element] = {}
    for element in elements:
        identifier = element.get(f"{W}id", "")
        if BOOKMARK_NUMBER.fullmatch(identifier) is None or identifier in indexed:
            raise _invalid()
        indexed[identifier] = element
    return indexed


def _paragraph_locations(body: Element) -> dict[Element, tuple[Element, int]]:
    return {
        child: (paragraph, index)
        for paragraph in body.findall(f"{W}p")
        if paragraph.find(f"{W}pPr/{W}numPr") is None
        and not any(
            node.tag in {f"{W}lastRenderedPageBreak", f"{W}fldSimple", f"{W}fldChar", f"{W}instrText"}
            or (node.tag == f"{W}br" and node.get(f"{W}type") == "page")
            for node in paragraph.iter()
        )
        for index, child in enumerate(paragraph)
    }


def _plain_runs(link: Element) -> list[Element]:
    if (
        set(link.attrib) - {f"{W}anchor", f"{W}history"}
        or link.get(f"{W}history", "0") not in {"0", "1", "false", "true", "off", "on"}
        or (link.text or "").strip()
        or not 1 <= len(link) <= LINK_RUN_LIMIT
    ):
        raise _invalid()
    runs: list[Element] = []
    texts: list[str] = []
    for run in link:
        if run.tag != f"{W}r" or (run.text or "").strip() or (run.tail or "").strip():
            raise _invalid()
        children = list(run)
        if children and children[0].tag == f"{W}rPr":
            properties = children.pop(0)
            allowed = {
                f"{W}{tag}" for tag in ("b", "i", "u", "strike", "dstrike", "rStyle", "sz", "szCs", "color", "rFonts")
            }
            if (
                properties.attrib
                or (properties.text or "").strip()
                or (properties.tail or "").strip()
                or len({child.tag for child in properties}) != len(properties)
                or any(
                    child.tag not in allowed
                    or len(child)
                    or (child.text or "").strip()
                    or (child.tail or "").strip()
                    or set(child.attrib) - ({f"{W}ascii", f"{W}hAnsi"} if child.tag == f"{W}rFonts" else {f"{W}val"})
                    or (child.tag == f"{W}rStyle" and child.get(f"{W}val") != "Hyperlink")
                    for child in properties
                )
            ):
                raise _invalid()
        if not children or any(
            child.tag != f"{W}t"
            or len(child)
            or (child.tail or "").strip()
            or child.attrib not in ({}, {_XML_SPACE: "preserve"}, {_XML_SPACE: "default"})
            for child in children
        ):
            raise _invalid()
        text = "".join(child.text or "" for child in children)
        if not text or any(char in text for char in "\r\n\t"):
            raise _invalid()
        runs.append(run)
        texts.append(text)
    if not "".join(texts).strip():
        raise _invalid()
    return runs


def docx_navigation(root: Element, body: Element) -> DocxNavigation | None:
    starts = list(root.iter(f"{W}bookmarkStart"))
    visible = [element for element in starts if _HIDDEN_NAME.fullmatch(element.get(f"{W}name", "")) is None]
    hyperlinks = [link for link in root.iter(f"{W}hyperlink") if f"{W}anchor" in link.attrib]
    if not visible and not hyperlinks:
        if not starts and next(root.iter(f"{W}bookmarkEnd"), None) is not None:
            raise _invalid()
        return None
    if len(visible) > BOOKMARK_LIMIT or len(hyperlinks) > LINK_RUN_LIMIT:
        raise _invalid()
    ends = _by_number(list(root.iter(f"{W}bookmarkEnd")))
    if _by_number(starts).keys() != ends.keys():
        raise _invalid()
    locations = _paragraph_locations(body)
    bookmarks: dict[Element, dict[str, str]] = {}
    destinations: dict[str, str] = {}
    names: set[str] = set()
    last_end: dict[Element, int] = {}
    for start in visible:
        number = start.get(f"{W}id", "")
        label = start.get(f"{W}name", "")
        end = ends[number]
        position, ending = locations.get(start), locations.get(end)
        if (
            BOOKMARK_NAME.fullmatch(label) is None
            or label.lower() in names
            or set(start.attrib) != {f"{W}id", f"{W}name"}
            or set(end.attrib) != {f"{W}id"}
            or len(start)
            or len(end)
            or (start.text or "").strip()
            or (end.text or "").strip()
            or position is None
            or ending is None
            or position[0] is not ending[0]
            or not last_end.get(position[0], -1) < position[1] < ending[1]
        ):
            raise _invalid()
        identifier = BOOKMARK_PREFIX + number
        bookmarks[start] = {"id": identifier, "label": label}
        destinations[label] = identifier
        names.add(label.lower())
        last_end[position[0]] = ending[1]
    links: dict[Element, str] = {}
    for link in hyperlinks:
        target = destinations.get(link.get(f"{W}anchor", ""))
        if link not in locations or target is None:
            raise _invalid()
        links.update(dict.fromkeys(_plain_runs(link), target))
        if len(links) > LINK_RUN_LIMIT:
            raise _invalid()
    return DocxNavigation(bookmarks, links)
