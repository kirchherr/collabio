"""Immutable image references and bounded inert presentation attributes."""

from __future__ import annotations

import re
from typing import Any

IMAGE_ATTRIBUTES = {
    "documentId",
    "assetId",
    "versionId",
    "contentHash",
    "manifestHash",
    "pixelWidth",
    "pixelHeight",
    "width",
    "height",
    "align",
    "alt",
    "caption",
    "decorative",
    "lockAspect",
}


def validate_image_attributes(attrs: dict[str, Any]) -> None:
    if set(attrs) - {"crop"} != IMAGE_ATTRIBUTES:
        raise ValueError("Invalid image attributes")
    for key, prefix in (
        ("documentId", "office-doc-"),
        ("assetId", "office-image-"),
        ("versionId", "office-image-version-"),
    ):
        if not isinstance(attrs[key], str) or re.fullmatch(prefix + r"[a-f0-9]{32}", attrs[key]) is None:
            raise ValueError("Invalid image identity")
    for key in ("contentHash", "manifestHash"):
        if not isinstance(attrs[key], str) or re.fullmatch(r"sha256:[a-f0-9]{64}", attrs[key]) is None:
            raise ValueError("Invalid image hash")
    for key, maximum in (("pixelWidth", 4096), ("pixelHeight", 4096), ("width", 1600), ("height", 1600)):
        if type(attrs[key]) is not int or not 1 <= attrs[key] <= maximum:
            raise ValueError("Invalid image dimensions")
    if attrs["pixelWidth"] * attrs["pixelHeight"] > 4_000_000:
        raise ValueError("Invalid image pixel count")
    if "crop" in attrs:
        crop = attrs["crop"]
        if not isinstance(crop, dict) or set(crop) != {"x", "y", "width", "height"}:
            raise ValueError("Invalid image crop")
        if any(type(value) is not int for value in crop.values()) or not (
            0 <= crop["x"] < attrs["pixelWidth"]
            and 0 <= crop["y"] < attrs["pixelHeight"]
            and 1 <= crop["width"] <= attrs["pixelWidth"] - crop["x"]
            and 1 <= crop["height"] <= attrs["pixelHeight"] - crop["y"]
        ):
            raise ValueError("Invalid image crop bounds")
    if not isinstance(attrs["align"], str) or attrs["align"] not in {"left", "center", "right"}:
        raise ValueError("Invalid image alignment")
    if type(attrs["decorative"]) is not bool or type(attrs["lockAspect"]) is not bool:
        raise ValueError("Invalid image options")
    for key, maximum in (("alt", 500), ("caption", 1000)):
        value = attrs[key]
        if (
            not isinstance(value, str)
            or len(value) > maximum
            or any(ord(c) < 32 or 127 <= ord(c) <= 159 or 0xD800 <= ord(c) <= 0xDFFF for c in value)
        ):
            raise ValueError("Invalid image description")
    if (attrs["decorative"] and attrs["alt"]) or (not attrs["decorative"] and not attrs["alt"].strip()):
        raise ValueError("Image requires alternative text or an explicit decorative choice")


def image_references(document: dict[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []

    def walk(node: dict[str, Any]) -> None:
        if node["type"] == "image":
            result.append(node["attrs"])
        for child in node.get("content", []):
            walk(child)

    walk(document)
    return result
