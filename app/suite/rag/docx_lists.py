"""Bounded main-body DOCX list structure and numbering."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from xml.etree.ElementTree import Element

from suite.rag.docx_images import W

LIST_DEPTH = 3
LIST_ITEMS = 1_000
LIST_MAX_NUMBER = 1_000_000
_ID = re.compile(r"0|[1-9][0-9]{0,8}")
_BULLETS = frozenset("•◦▪‣○■●·\uf0b7\uf0a7")


class UnsupportedDocxList(ValueError):
    pass


def _invalid() -> UnsupportedDocxList:
    return UnsupportedDocxList("DOCX list is outside the bounded numbering profile")


def _value(element: Element, name: str, default: str = "") -> str:
    children = element.findall(f"{W}{name}")
    if not children:
        return default
    if len(children) != 1 or set(children[0].attrib) != {f"{W}val"} or len(children[0]):
        raise _invalid()
    return children[0].get(f"{W}val", "")


def docx_list_reference(paragraph: Element) -> tuple[str, int] | None:
    properties = paragraph.findall(f"{W}pPr/{W}numPr")
    if not properties:
        return None
    if (
        len(properties) != 1
        or properties[0].attrib
        or any(child.tag not in {f"{W}ilvl", f"{W}numId"} for child in properties[0])
    ):
        raise _invalid()
    number = _value(properties[0], "numId")
    level = _value(properties[0], "ilvl", "0")
    if _ID.fullmatch(number) is None or level not in {"0", "1", "2"}:
        raise _invalid()
    return None if number == "0" else (number, int(level))


def _index(root: Element, name: str, attribute: str) -> dict[str, Element]:
    entries = root.findall(f"{W}{name}")
    result = {entry.get(f"{W}{attribute}", ""): entry for entry in entries}
    if len(entries) > 256 or len(result) != len(entries) or any(_ID.fullmatch(key) is None for key in result):
        raise _invalid()
    return result


class DocxNumbering:
    def __init__(self, root: Element | None) -> None:
        self._root = root
        self._profiles: dict[tuple[str, int], tuple[str, int]] = {}
        self._numbers: dict[str, Element] | None = None
        self._abstracts: dict[str, Element] = {}

    def resolve(self, number: str, depth: int) -> tuple[str, int]:
        key = (number, depth)
        if key not in self._profiles:
            self._profiles[key] = self._resolve(number, depth)
        return self._profiles[key]

    def _resolve(self, number: str, depth: int) -> tuple[str, int]:
        if self._numbers is None:
            if self._root is None or self._root.tag != f"{W}numbering":
                raise _invalid()
            self._abstracts = _index(self._root, "abstractNum", "abstractNumId")
            self._numbers = _index(self._root, "num", "numId")
        instance = self._numbers.get(number)
        if instance is None:
            raise _invalid()
        abstract = self._abstracts.get(_value(instance, "abstractNumId"))
        if (
            abstract is None
            or any(
                child.tag in {f"{W}numStyleLink", f"{W}styleLink"} or child.tag.endswith("}restartNumberingAfterBreak")
                for child in abstract
            )
            or any(
                key.endswith("}restartNumberingAfterBreak") and value not in {"0", "false", "off"}
                for key, value in abstract.attrib.items()
            )
        ):
            raise _invalid()
        level = _index(abstract, "lvl", "ilvl").get(str(depth))
        if level is None or any(child.tag in {f"{W}isLgl", f"{W}lvlPicBulletId", f"{W}pStyle"} for child in level):
            raise _invalid()
        restart = _value(level, "lvlRestart")
        if restart and (depth == 0 or restart != str(depth)):
            raise _invalid()
        fmt = _value(level, "numFmt")
        label = _value(level, "lvlText")
        if fmt == "bullet" and (not label or label in _BULLETS):
            kind = "bullet_list"
        elif fmt == "decimal" and label in {"", f"%{depth + 1}."}:
            kind = "ordered_list"
        else:
            raise _invalid()
        start = _value(level, "start", "1")
        override = _index(instance, "lvlOverride", "ilvl").get(str(depth))
        if override is not None:
            if len(override) != 1 or override[0].tag != f"{W}startOverride":
                raise _invalid()
            start = _value(override, "startOverride")
        if _ID.fullmatch(start) is None or not 1 <= int(start) <= LIST_MAX_NUMBER:
            raise _invalid()
        return kind, int(start)


@dataclass
class _Item:
    runs: list[dict[str, object]]
    child: _List | None = None


@dataclass
class _List:
    kind: str
    start: int
    items: list[_Item] = field(default_factory=list)

    def tree(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            **({"start": self.start} if self.kind == "ordered_list" else {}),
            "items": [
                {"runs": item.runs, **({"child": item.child.tree()} if item.child is not None else {})}
                for item in self.items
            ],
        }

    def block(self) -> dict[str, object]:
        if self.start == 1 and all(item.child is None for item in self.items):
            return {"kind": self.kind, "items": [item.runs for item in self.items]}
        return {"kind": "list_tree", "list": self.tree()}


class DocxListBuilder:
    def __init__(self, numbering: DocxNumbering, blocks: list[dict[str, object]]) -> None:
        self._numbering = numbering
        self._blocks = blocks
        self._stack: list[_List] = []
        self._next: dict[tuple[str, int], int] = {}
        self._active: str | None = None
        self.unsupported = False

    def flush(self) -> None:
        if self._stack:
            self._blocks.append(self._stack[0].block())
            self._stack.clear()
        self._active = None

    def append(self, reference: tuple[str, int], runs: list[dict[str, object]]) -> None:
        if self.unsupported:
            return
        try:
            self._append(reference, runs)
        except UnsupportedDocxList:
            self.unsupported = True
            self.flush()

    def _append(self, reference: tuple[str, int], runs: list[dict[str, object]]) -> None:
        number, depth = reference
        if number != self._active:
            if depth:
                raise _invalid()
            self.flush()
            self._active = number
        if depth > len(self._stack):
            raise _invalid()
        kind, start = self._numbering.resolve(number, depth)
        ordinal = self._next.get(reference, start) if kind == "ordered_list" else 1
        if ordinal > LIST_MAX_NUMBER:
            raise _invalid()
        del self._stack[depth + 1 :]
        if depth == len(self._stack):
            branch = _List(kind, ordinal)
            if depth:
                self._stack[-1].items[-1].child = branch
            self._stack.append(branch)
        current = self._stack[-1]
        if len(current.items) >= LIST_ITEMS:
            raise _invalid()
        current.items.append(_Item(runs))
        if kind == "ordered_list":
            self._next[reference] = ordinal + 1
        for child_depth in range(depth + 1, LIST_DEPTH):
            self._next.pop((number, child_depth), None)
