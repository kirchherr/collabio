"""Independent validation of inert parser media and temporary preview identities."""

from __future__ import annotations

import base64
from collections.abc import Callable
from typing import Any

from suite.ai_control_plane.audit import canonical_json
from suite.platform.office_image_codec import image_dimensions, normalize_image
from suite.platform.office_image_schema import validate_image_attributes
from suite.rag.docx_images import MAX_DOCX_IMAGE_PIXELS, MAX_DOCX_IMAGES, MAX_DOCX_MEDIA_BYTES
from suite.rag.parser_worker import sha256_bytes

ImageNormalizer = Callable[[bytes, str], tuple[bytes, int, int]]
IMPORT_IMAGE_IDENTITY_KEYS = (
    "documentId",
    "assetId",
    "versionId",
    "contentHash",
    "manifestHash",
    "pixelWidth",
    "pixelHeight",
)


class DocxPreviewImages:
    def __init__(self, binding: dict[str, Any], normalizer: ImageNormalizer = normalize_image) -> None:
        self.binding = binding
        self.normalizer = normalizer
        self.images: list[dict[str, Any]] = []
        self.bytes = 0
        self.pixels = 0

    def build(self, block: dict[str, Any]) -> dict[str, Any]:
        if set(block) != {"kind", "mime_type", "content_base64", "content_hash", "alt"} or (
            block["mime_type"] not in {"image/png", "image/jpeg"}
            or not isinstance(block["content_base64"], str)
            or len(block["content_base64"]) > 4 * ((MAX_DOCX_MEDIA_BYTES + 2) // 3)
            or not isinstance(block["alt"], str)
        ):
            raise ValueError("Invalid DOCX image block")
        raw = base64.b64decode(block["content_base64"], validate=True)
        self.bytes += len(raw)
        if not raw or self.bytes > MAX_DOCX_MEDIA_BYTES or len(self.images) >= MAX_DOCX_IMAGES:
            raise ValueError("DOCX image byte/count limit exceeded")
        if sha256_bytes(raw) != block["content_hash"]:
            raise ValueError("DOCX image hash mismatch")
        normalized, width, height = self.normalizer(raw, block["mime_type"])
        image_dimensions(width, height)
        self.pixels += width * height
        if self.pixels > MAX_DOCX_IMAGE_PIXELS:
            raise ValueError("DOCX aggregate pixel limit exceeded")
        content_hash = sha256_bytes(normalized)
        identity = {**self.binding, "ordinal": len(self.images), "content_hash": content_hash}
        digest = sha256_bytes(canonical_json(identity).encode())[7:]
        owner = sha256_bytes(canonical_json(self.binding).encode())[7:]
        display_width = min(width, 640)
        display_height = max(1, round(height * display_width / width))
        if display_height > 1600:
            display_width = max(1, round(display_width * 1600 / display_height))
            display_height = 1600
        attrs = {
            "documentId": f"office-doc-{owner[:32]}",
            "assetId": f"office-image-{digest[:32]}",
            "versionId": f"office-image-version-{digest[32:]}",
            "contentHash": content_hash,
            "manifestHash": sha256_bytes(canonical_json(identity).encode()),
            "pixelWidth": width,
            "pixelHeight": height,
            "width": display_width,
            "height": display_height,
            "align": "left",
            "alt": block["alt"],
            "caption": "",
            "decorative": False,
            "lockAspect": True,
        }
        validate_image_attributes(attrs)
        self.images.append({"image": attrs, "content_base64": base64.b64encode(normalized).decode("ascii")})
        return {"type": "image", "attrs": attrs}
