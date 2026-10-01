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


def test_numbered_figures_add_only_a_stable_optional_identity() -> None:
    legacy = image_document()
    assert validate_office_document(legacy) == legacy
    numbered = deepcopy(legacy)
    numbered["content"][0]["attrs"]["figureId"] = "figure-" + "f" * 24
    assert validate_office_document(numbered) == numbered
    assert image_references(numbered)[0]["caption"] == "<literal>"
    assert image_references(numbered)[0]["figureId"] == "figure-" + "f" * 24


@pytest.mark.parametrize("figure_id", ["figure-short", "bookmark-" + "f" * 24, "figure-" + "F" * 24])
def test_numbered_figures_reject_invalid_identifiers(figure_id: str) -> None:
    document = image_document()
    document["content"][0]["attrs"]["figureId"] = figure_id
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(document)


def test_numbered_figures_require_captions_and_unique_unambiguous_targets() -> None:
    document = image_document()
    attrs = document["content"][0]["attrs"]
    attrs["figureId"] = "figure-" + "a" * 24
    attrs["caption"] = " "
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(document)
    attrs["caption"] = "Stable caption"
    duplicate = deepcopy(document["content"][0])
    document["content"].insert(1, duplicate)
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(document)
    document["content"].pop(1)
    document["content"].append(
        {
            "type": "paragraph",
            "content": [{"type": "bookmark", "attrs": {"id": attrs["figureId"], "label": "Collision"}}],
        }
    )
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(document)


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


@pytest.mark.parametrize(
    "wrap",
    [
        None,
        {},
        [],
        "left",
        {"side": "center", "gap": 16},
        {"side": [], "gap": 16},
        {"side": "left", "gap": -1},
        {"side": "right", "gap": 49},
        {"side": "left", "gap": True},
        {"side": "left", "gap": 0.5},
        {"side": "left", "gap": "16"},
        {"side": "left", "gap": 16, "position": "absolute"},
    ],
)
def test_image_wrap_rejects_ambiguous_unbounded_or_active_layout(wrap: Any) -> None:
    document = image_document()
    document["content"][0]["attrs"]["wrap"] = wrap
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(document)


@pytest.mark.parametrize("side,gap", [("left", 0), ("right", 48)])
def test_image_wrap_preserves_source_crop_and_legacy_bytes(side: str, gap: int) -> None:
    from suite.ai_control_plane.audit import canonical_json

    document = image_document()
    before = canonical_json(document)
    attrs = document["content"][0]["attrs"]
    attrs["crop"] = {"x": 1, "y": 0, "width": 1, "height": 1}
    attrs["wrap"] = {"side": side, "gap": gap}
    assert validate_office_document(document) == document
    assert image_references(document)[0] == attrs
    del attrs["wrap"]
    del attrs["crop"]
    assert canonical_json(validate_office_document(document)) == before


@pytest.mark.parametrize("layer,x,y", [("front", 0, -1200), ("behind", 1000, 1200)])
def test_image_free_position_is_bounded_inert_and_preserves_source(layer: str, x: int, y: int) -> None:
    document = image_document()
    attrs = document["content"][0]["attrs"]
    attrs["position"] = {"layer": layer, "x": x, "y": y}
    assert validate_office_document(document) == document
    assert image_references(document)[0] == attrs


@pytest.mark.parametrize(
    "position",
    [
        {},
        [],
        "front",
        {"layer": "middle", "x": 0, "y": 0},
        {"layer": "front", "x": -1, "y": 0},
        {"layer": "behind", "x": 1001, "y": 0},
        {"layer": "front", "x": True, "y": 0},
        {"layer": "front", "x": 0.5, "y": 0},
        {"layer": "front", "x": 0, "y": -1201},
        {"layer": "behind", "x": 0, "y": 1201},
        {"layer": "front", "x": 0, "y": 0, "style": "position:fixed"},
    ],
)
def test_image_free_position_rejects_active_ambiguous_or_unbounded_values(position: Any) -> None:
    document = image_document()
    document["content"][0]["attrs"]["position"] = position
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(document)


def test_image_free_position_and_text_wrap_are_mutually_exclusive() -> None:
    document = image_document()
    attrs = document["content"][0]["attrs"]
    attrs["position"] = {"layer": "front", "x": 500, "y": 0}
    attrs["wrap"] = {"side": "left", "gap": 16}
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(document)


@pytest.mark.parametrize(
    "transform",
    [
        {"rotation": 90, "flipX": False, "flipY": False},
        {"rotation": 180, "flipX": True, "flipY": False},
        {"rotation": 270, "flipX": True, "flipY": True},
        {"rotation": 0, "flipX": False, "flipY": True},
    ],
)
def test_image_transform_is_bounded_inert_and_preserves_source(transform: dict[str, Any]) -> None:
    document = image_document()
    attrs = document["content"][0]["attrs"]
    attrs["crop"] = {"x": 1, "y": 0, "width": 1, "height": 1}
    attrs["transform"] = transform
    assert validate_office_document(document) == document
    assert image_references(document)[0] == attrs


@pytest.mark.parametrize(
    "transform",
    [
        None,
        {},
        [],
        "rotate(90deg)",
        {"rotation": 45, "flipX": False, "flipY": False},
        {"rotation": True, "flipX": False, "flipY": False},
        {"rotation": 0, "flipX": False, "flipY": False},
        {"rotation": 90, "flipX": 1, "flipY": False},
        {"rotation": 90, "flipX": False, "flipY": False, "style": "url(external)"},
    ],
)
def test_image_transform_rejects_active_ambiguous_or_noncanonical_values(transform: Any) -> None:
    document = image_document()
    document["content"][0]["attrs"]["transform"] = transform
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(document)


def test_image_transform_reset_restores_legacy_canonical_bytes() -> None:
    from suite.ai_control_plane.audit import canonical_json

    document = image_document()
    before = canonical_json(document)
    document["content"][0]["attrs"]["transform"] = {"rotation": 90, "flipX": True, "flipY": False}
    assert validate_office_document(document) == document
    del document["content"][0]["attrs"]["transform"]
    assert canonical_json(validate_office_document(document)) == before


def image_group_document(*, count: int = 2, layout: str = "row", gap: int = 16) -> dict[str, Any]:
    images = []
    for index in range(count):
        attrs = image_attrs()
        attrs["assetId"] = "office-image-" + f"{index + 1:032x}"
        attrs["versionId"] = "office-image-version-" + f"{index + 1:032x}"
        attrs["alt"] = f"Grouped image {index + 1}"
        images.append({"type": "image", "attrs": attrs})
    return {"type": "doc", "content": [{"type": "imageGroup", "attrs": {
        "id": "image-group-" + "a" * 24, "layout": layout, "gap": gap,
    }, "content": images}]}


def test_image_groups_preserve_owned_references_and_member_presentation() -> None:
    document = image_group_document(count=8, layout="stack", gap=48)
    document["content"][0]["content"][0]["attrs"]["crop"] = {"x": 1, "y": 0, "width": 1, "height": 1}
    document["content"][0]["content"][1]["attrs"]["transform"] = {
        "rotation": 90, "flipX": True, "flipY": False,
    }
    assert validate_office_document(document) == document
    references = image_references(document)
    assert len(references) == 8
    assert references[0]["crop"] == {"x": 1, "y": 0, "width": 1, "height": 1}
    assert references[1]["transform"] == {"rotation": 90, "flipX": True, "flipY": False}


@pytest.mark.parametrize(
    "change",
    [
        {"id": "group-short", "layout": "row", "gap": 16},
        {"id": "image-group-" + "a" * 24, "layout": "grid", "gap": 16},
        {"id": "image-group-" + "a" * 24, "layout": "row", "gap": -1},
        {"id": "image-group-" + "a" * 24, "layout": "row", "gap": 49},
        {"id": "image-group-" + "a" * 24, "layout": "row", "gap": True},
        {"id": "image-group-" + "a" * 24, "layout": "row", "gap": 16, "style": "display:flex"},
    ],
)
def test_image_groups_reject_active_ambiguous_or_unbounded_attributes(change: dict[str, Any]) -> None:
    document = image_group_document()
    document["content"][0]["attrs"] = change
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(document)


def test_image_groups_require_two_to_eight_flow_images_at_document_root() -> None:
    for count in (1, 9):
        with pytest.raises(OfficeDocumentInvalidContentError):
            validate_office_document(image_group_document(count=count))
    for key, value in (("wrap", {"side": "left", "gap": 16}), ("position", {"layer": "front", "x": 0, "y": 0})):
        document = image_group_document()
        document["content"][0]["content"][0]["attrs"][key] = value
        with pytest.raises(OfficeDocumentInvalidContentError):
            validate_office_document(document)
    nested = {"type": "doc", "content": [{"type": "blockquote", "content": image_group_document()["content"]}]}
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(nested)


def test_image_groups_have_unique_bounded_identities() -> None:
    duplicate = image_group_document()
    duplicate["content"].append(deepcopy(duplicate["content"][0]))
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(duplicate)
    excessive = image_group_document()
    group = excessive["content"][0]
    excessive["content"] = []
    for index in range(21):
        entry = deepcopy(group)
        entry["attrs"]["id"] = "image-group-" + f"{index + 1:024x}"
        for member, image in enumerate(entry["content"]):
            image["attrs"]["assetId"] = "office-image-" + f"{index * 2 + member + 1:032x}"
            image["attrs"]["versionId"] = "office-image-version-" + f"{index * 2 + member + 1:032x}"
        excessive["content"].append(entry)
    with pytest.raises(OfficeDocumentInvalidContentError):
        validate_office_document(excessive)
