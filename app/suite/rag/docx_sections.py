"""Bounded main-body WordprocessingML section layout for the native Office preview."""

from __future__ import annotations

import re
from xml.etree.ElementTree import Element
from zipfile import ZipFile

from suite.rag.docx_running_text import RUNNING_TAGS, docx_running_profiles

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
SECTION = f"{W}sectPr"
_MARGINS = ("top", "right", "bottom", "left")
_REVISION_IDS = {f"{W}{name}" for name in ("rsidRPr", "rsidSect", "rsidDel", "rsidR")}
_SECTION_PROPERTIES = {f"{W}{name}" for name in ("pgSz", "pgMar", "type", "cols")} | RUNNING_TAGS


class UnsupportedDocxSection(ValueError):
    pass


def _attributes(element: Element, *, allowed: set[str]) -> dict[str, str]:
    if (
        len(element)
        or (element.text or "").strip()
        or any(name not in {f"{W}{key}" for key in allowed} for name in element.attrib)
    ):
        raise UnsupportedDocxSection("DOCX section property is unsupported")
    return {name.removeprefix(W): value for name, value in element.attrib.items()}


def _twips(value: str) -> int:
    if re.fullmatch(r"[0-9]{1,5}", value) is None:
        raise UnsupportedDocxSection("DOCX section measurement is invalid")
    return int(value)


def _page_profile(section: Element) -> dict[str, object]:
    properties = {child.tag: child for child in section}
    if (
        len(properties) != len(section)
        or set(properties) - _SECTION_PROPERTIES
        or any((child.tail or "").strip() for child in section)
        or (section.text or "").strip()
        or not {f"{W}pgSz", f"{W}pgMar"} <= properties.keys()
        or any(
            key not in _REVISION_IDS or re.fullmatch(r"[0-9A-Fa-f]{8}", value) is None
            for key, value in section.attrib.items()
        )
    ):
        raise UnsupportedDocxSection("DOCX section profile is unsupported")

    transition = properties.get(f"{W}type")
    if transition is not None and _attributes(transition, allowed={"val"}) != {"val": "nextPage"}:
        raise UnsupportedDocxSection("DOCX section transition is unsupported")

    size = _attributes(properties[f"{W}pgSz"], allowed={"w", "h", "orient"})
    dimensions = (_twips(size.get("w", "")), _twips(size.get("h", "")))
    orientation = size.get("orient", "portrait")
    if orientation == "landscape":
        dimensions = dimensions[::-1]
    elif orientation != "portrait":
        raise UnsupportedDocxSection("DOCX page orientation is unsupported")
    if dimensions[0] in (11906, 11907) and dimensions[1] in (16838, 16839):
        paper = "a4"
    elif dimensions == (12240, 15840):
        paper = "letter"
    else:
        raise UnsupportedDocxSection("DOCX paper dimensions are unsupported")

    margin_values = _attributes(properties[f"{W}pgMar"], allowed={*_MARGINS, "header", "footer", "gutter"})
    margins: dict[str, int] = {}
    for side in _MARGINS:
        twips = _twips(margin_values.get(side, ""))
        if not 283 <= twips <= 2835:
            raise UnsupportedDocxSection("DOCX page margin is outside the native range")
        margins[side] = (twips * 127 + 3600) // 7200
    if _twips(margin_values.get("gutter", "0")) or any(
        _twips(margin_values.get(side, "0")) > 2835 for side in ("header", "footer")
    ):
        raise UnsupportedDocxSection("DOCX gutter or running-content offset is unsupported")

    profile: dict[str, object] = {"paper": paper, "orientation": orientation, "margins": margins}
    columns = properties.get(f"{W}cols")
    if columns is not None:
        settings = _attributes(columns, allowed={"num", "space", "equalWidth", "sep"})
        count = settings.get("num", "1")
        if (
            count not in ("1", "2", "3")
            or settings.get("equalWidth", "1") not in ("1", "true", "on")
            or settings.get("sep", "0") not in ("0", "false", "off")
            or settings.get("space", "720") != "720"
        ):
            raise UnsupportedDocxSection("DOCX column layout is unsupported")
        if count != "1":
            profile["columns"] = {"2": "two", "3": "three"}[count]
    return profile


def docx_section_layout(
    archive: ZipFile, root: Element, body: Element
) -> tuple[dict[str, object] | None, dict[int, dict[str, object]]]:
    """Return the first profile and following profiles keyed by the start index in the body."""
    allowed: list[Element] = []
    starts = [0]
    final = body[-1] if len(body) and body[-1].tag == SECTION else None
    for index, paragraph in enumerate(body):
        if paragraph.tag != f"{W}p":
            continue
        properties = paragraph.findall(f"{W}pPr")
        sections = [section for prop in properties for section in prop.findall(SECTION)]
        if sections:
            if len(sections) != 1 or len(properties) != 1 or len(allowed) >= 12:
                raise UnsupportedDocxSection("DOCX section boundary is ambiguous or exceeds the preview limit")
            allowed.append(sections[0])
            starts.append(index + 1)
    if final is not None:
        allowed.append(final)
    if set(root.iter(SECTION)) != set(allowed) or (len(starts) > 1 and final is None):
        raise UnsupportedDocxSection("DOCX section properties are misplaced or incomplete")
    if not allowed or (
        len(starts) == 1 and not len(allowed[0]) and not allowed[0].attrib and not (allowed[0].text or "").strip()
    ):
        return None, {}
    profiles: list[dict[str, object]] = [{"page": _page_profile(section)} for section in allowed]
    running = docx_running_profiles(archive, allowed)
    if running is not None:
        for profile, literal in zip(profiles, running, strict=True):
            profile["running"] = literal
    return profiles[0], dict(zip(starts[1:], profiles[1:], strict=True))
