from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from suite.platform.office_document_schema import OfficeDocumentInvalidContentError, validate_office_document
from suite.platform.office_image_codec import (
    OfficeImageInvalid,
    OfficeImageUnavailable,
    normalize_image,
    png_from_pixels,
)
from suite.platform.office_image_schema import image_references
from suite.platform.office_reviews import ReviewAnchor, derive_review_quote
from suite.platform.office_suggestions import replace_suggestion_text


def test_image_worker_is_isolated_without_credentials_or_network() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    worker = compose.split("\n  office-image-decoder:\n", 1)[1].split("\n  work-e2e-image-decoder:", 1)[0]
    for requirement in (
        'profiles: ["office-images"]',
        "network_mode: none",
        'user: "10001:10001"',
        "read_only: true",
        "cap_drop: [ALL]",
        'security_opt: ["no-new-privileges:true"]',
        "pids_limit: 16",
        "mem_limit: 384m",
        "cpus: 1",
        "/tmp:size=32m,noexec,nosuid,nodev",
        "office_image_socket:/run/office-images",
    ):
        assert requirement in worker
    for forbidden in ("environment:", "env_file:", "secrets:", "ports:", "./app:", "docker.sock"):
        assert forbidden not in worker
    synthetic = compose.split("\n  work-e2e-image-decoder:\n", 1)[1].split("\n  api:", 1)[0]
    assert "extends: office-image-decoder" in synthetic
    assert "work_e2e_image_socket:/run/office-images" in synthetic


def image_attrs() -> dict[str, Any]:
    return {
        "documentId": "office-doc-" + "a" * 32,
        "assetId": "office-image-" + "b" * 32,
        "versionId": "office-image-version-" + "c" * 32,
        "contentHash": "sha256:" + "d" * 64,
        "manifestHash": "sha256:" + "e" * 64,
        "pixelWidth": 2,
        "pixelHeight": 1,
        "width": 200,
        "height": 100,
        "align": "center",
        "alt": "Two colored pixels",
        "caption": "<literal>",
        "decorative": False,
        "lockAspect": True,
    }


def image_document() -> dict[str, Any]:
    return {
        "type": "doc",
        "content": [
            {"type": "image", "attrs": image_attrs()},
            {"type": "paragraph", "content": [{"type": "text", "text": "After image"}]},
        ],
    }


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("assetId", "https://example.test/x.png"),
        ("documentId", "other"),
        ("versionId", "current"),
        ("contentHash", "x"),
        ("manifestHash", "x"),
        ("width", 0),
        ("width", True),
        ("height", 1601),
        ("pixelWidth", 4097),
        ("align", "float"),
        ("alt", ""),
        ("alt", "x\x00"),
        ("caption", "x" * 1001),
        ("decorative", True),
        ("lockAspect", 1),
        ("src", "data:image/png;base64,x"),
    ],
)
def test_image_schema_rejects_unbounded_active_or_ambiguous_attributes(key: str, value: Any) -> None:
    document = image_document()
    document["content"][0]["attrs"][key] = value
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(document)


def test_images_are_bounded_leaf_nodes_and_preserve_review_offsets() -> None:
    document = image_document()
    assert validate_office_document(document) == document
    assert image_references(document) == [image_attrs()]
    assert derive_review_quote(document, ReviewAnchor.model_validate({"from": 2, "to": 7})) == "After"
    replaced = replace_suggestion_text(document, ReviewAnchor.model_validate({"from": 2, "to": 7}), "Before")
    assert replaced["content"][0] == document["content"][0]
    assert "".join(node["text"] for node in replaced["content"][1]["content"]) == "Before image"
    excessive = deepcopy(document)
    excessive["content"] = [excessive["content"][0]] * 41
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(excessive)


def test_image_normalization_rejects_input_before_contacting_worker() -> None:
    for data, mime in (
        (b"<svg/>", "image/svg+xml"),
        (b"x", "image/png"),
        (b"\xff\xd8\xff", "image/png"),
        (b"\x89PNG\r\n\x1a\n" + b"x" * 8388608, "image/png"),
    ):
        with pytest.raises(OfficeImageInvalid):
            normalize_image(data, mime, socket_path="/missing-office-image-worker")
    png = png_from_pixels(2, 1, b"\xff\0\0\xff\0\xff\0\xff")
    assert png.startswith(b"\x89PNG\r\n\x1a\n") and b"eXIf" not in png and b"tEXt" not in png
    with pytest.raises(OfficeImageUnavailable):
        normalize_image(png, "image/png", socket_path="/missing-office-image-worker")
    with pytest.raises(OfficeImageInvalid):
        png_from_pixels(4096, 4096, b"")


@pytest.mark.parametrize(
    "crop",
    [
        None,
        {},
        {"x": 0, "y": 0, "width": 0, "height": 1},
        {"x": -1, "y": 0, "width": 1, "height": 1},
        {"x": 1, "y": 0, "width": 2, "height": 1},
        {"x": 0, "y": 1, "width": 1, "height": 1},
        {"x": False, "y": 0, "width": 1, "height": 1},
        {"x": 0.5, "y": 0, "width": 1, "height": 1},
        {"x": 0, "y": 0, "width": 1, "height": 1, "url": "external"},
    ],
)
def test_image_crop_rejects_invalid_geometry(crop: Any) -> None:
    document = image_document()
    document["content"][0]["attrs"]["crop"] = crop
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(document)


def test_crop_preserves_legacy_attributes_and_exact_source_reference() -> None:
    document = image_document()
    legacy = deepcopy(document)
    assert validate_office_document(document) == legacy
    document["content"][0]["attrs"]["crop"] = {"x": 1, "y": 0, "width": 1, "height": 1}
    assert validate_office_document(document) == document
    assert {key: value for key, value in image_references(document)[0].items() if key != "crop"} == image_attrs()
