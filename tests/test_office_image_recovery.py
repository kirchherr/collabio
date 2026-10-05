from typing import Any
from unittest.mock import Mock

import pytest

from office_image_recovery import (
    verify_restored_crop_reset,
    verify_restored_group_duplicate,
    verify_restored_group_reset,
    verify_restored_image_duplicate,
    verify_restored_image_replacement,
    verify_restored_images,
    verify_restored_position_reset,
    verify_restored_transform_reset,
    verify_restored_wrap_reset,
)
from office_recovery_proof import require_office_recovery_environment
from test_office_recovery_proof import recovery_environment


@pytest.mark.parametrize("number", [268, 269, 270, 291, 307, 309])
def test_image_restore_target_requires_a_matching_separate_pair(number: int) -> None:
    env = recovery_environment()
    for key in ("SUITE_POSTGRES_RESTORE_TARGET_DSN", "SUITE_OFFICE_RECOVERY_TARGET_DSN"):
        env[key] = env[key].replace("/collabio_work_e2e_restore", f"/collabio_work_e2e_{number}_restore")
    if number == 309:
        env["SUITE_POSTGRES_RESTORE_RECEIPT_PATH"] = "/proof-backup/postgres-restore-receipt-309.sha256"
    require_office_recovery_environment(env)
    env["SUITE_POSTGRES_RESTORE_TARGET_DSN"] = recovery_environment()["SUITE_POSTGRES_RESTORE_TARGET_DSN"]
    with pytest.raises(ValueError):
        require_office_recovery_environment(env)


def test_image_recovery_denies_empty_and_unbound_assets_before_source_access() -> None:
    sources = Mock()
    for images, bindings in (
        ([], []),
        ([{"object_id": "a", "version_id": "v"}], []),
        ([], [{"asset_id": "a", "asset_version_id": "v"}]),
    ):
        with pytest.raises(ValueError):
            verify_restored_images(
                documents=Mock(),
                readers={},
                original_sources=sources,
                restored_sources=sources,
                receipts=Mock(),
                images=images,
                bindings=bindings,
            )
    assert not sources.mock_calls


def test_crop_recovery_requires_reset_after_crop_of_exact_same_owned_rendition() -> None:
    cropped = {
        "object_id": "doc",
        "asset_id": "asset",
        "asset_version_id": "pixels",
        "document_version_id": "cropped",
        "previous_document_version_id": "initial",
        "crop": {"x": 1, "y": 0, "width": 1, "height": 1},
    }
    reset = {**cropped, "document_version_id": "reset", "previous_document_version_id": "cropped", "crop": None}
    assert verify_restored_crop_reset([cropped, reset]) == {
        "verified_cropped_image_reference_count": 1,
        "cropped_and_reset_versions_verified": True,
    }
    for key in ("object_id", "asset_id", "asset_version_id", "previous_document_version_id"):
        with pytest.raises(ValueError):
            verify_restored_crop_reset([cropped, {**reset, key: "different"}])
    for bindings in ([], [cropped], [reset]):
        with pytest.raises(ValueError):
            verify_restored_crop_reset(bindings)


def test_wrap_recovery_requires_consecutive_layouts_with_same_owner_source_and_crop() -> None:
    left: dict[str, Any] = {
        "object_id": "doc",
        "asset_id": "asset",
        "asset_version_id": "pixels",
        "document_version_id": "left",
        "previous_document_version_id": "initial",
        "crop": {"x": 1, "y": 0, "width": 1, "height": 1},
        "wrap": {"side": "left", "gap": 16},
    }
    right = {
        **left,
        "document_version_id": "right",
        "previous_document_version_id": "left",
        "wrap": {"side": "right", "gap": 24},
    }
    reset = {**right, "document_version_id": "reset", "previous_document_version_id": "right", "wrap": None}
    assert verify_restored_wrap_reset([left, right, reset]) == {
        "verified_wrapped_image_reference_count": 2,
        "wrapped_and_reset_versions_verified": True,
    }
    for index in (1, 2):
        for key in ("object_id", "asset_id", "asset_version_id", "previous_document_version_id", "crop"):
            broken = [left, right, reset]
            broken[index] = {**broken[index], key: "different"}
            with pytest.raises(ValueError):
                verify_restored_wrap_reset(broken)
    for rows in ([], [left], [right, reset], [left, reset]):
        with pytest.raises(ValueError):
            verify_restored_wrap_reset(rows)


def test_position_recovery_requires_consecutive_layers_reset_and_same_owned_rendition() -> None:
    front: dict[str, Any] = {
        "object_id": "doc",
        "asset_id": "asset",
        "asset_version_id": "pixels",
        "document_version_id": "front",
        "previous_document_version_id": "initial",
        "crop": {"x": 1, "y": 0, "width": 1, "height": 1},
        "wrap": None,
        "position": {"layer": "front", "x": 120, "y": 34},
    }
    behind = {
        **front,
        "document_version_id": "behind",
        "previous_document_version_id": "front",
        "position": {"layer": "behind", "x": 880, "y": -24},
    }
    reset = {**behind, "document_version_id": "reset", "previous_document_version_id": "behind", "position": None}
    assert verify_restored_position_reset([front, behind, reset]) == {
        "verified_positioned_image_reference_count": 2,
        "positioned_and_reset_versions_verified": True,
    }
    for index in (1, 2):
        for key in ("object_id", "asset_id", "asset_version_id", "previous_document_version_id", "crop", "wrap"):
            broken = [front, behind, reset]
            broken[index] = {**broken[index], key: "different"}
            with pytest.raises(ValueError):
                verify_restored_position_reset(broken)
    for rows in ([], [front], [behind, reset], [front, reset]):
        with pytest.raises(ValueError):
            verify_restored_position_reset(rows)


def test_transform_recovery_requires_consecutive_rotation_mirroring_reset_and_same_rendition() -> None:
    rotated: dict[str, Any] = {
        "object_id": "doc",
        "asset_id": "asset",
        "asset_version_id": "pixels",
        "document_version_id": "rotated",
        "previous_document_version_id": "initial",
        "crop": None,
        "wrap": None,
        "position": None,
        "transform": {"rotation": 90, "flipX": True, "flipY": False},
    }
    mirrored = {
        **rotated,
        "document_version_id": "mirrored",
        "previous_document_version_id": "rotated",
        "transform": {"rotation": 270, "flipX": True, "flipY": True},
    }
    reset = {**mirrored, "document_version_id": "reset", "previous_document_version_id": "mirrored", "transform": None}
    assert verify_restored_transform_reset([rotated, mirrored, reset]) == {
        "verified_transformed_image_reference_count": 2,
        "transformed_and_reset_versions_verified": True,
    }
    for index in (1, 2):
        for key in (
            "object_id",
            "asset_id",
            "asset_version_id",
            "previous_document_version_id",
            "crop",
            "wrap",
            "position",
        ):
            broken = [rotated, mirrored, reset]
            broken[index] = {**broken[index], key: "different"}
            with pytest.raises(ValueError):
                verify_restored_transform_reset(broken)
    for rows in ([], [rotated], [mirrored, reset], [rotated, reset]):
        with pytest.raises(ValueError):
            verify_restored_transform_reset(rows)


def test_group_recovery_requires_consecutive_row_stack_reset_with_same_members() -> None:
    row: dict[str, Any] = {
        "object_id": "doc",
        "document_version_id": "row",
        "previous_document_version_id": "initial",
        "images": [("a", "1"), ("b", "2"), ("c", "3")],
        "groups": [{"id": "group", "layout": "row", "gap": 12, "images": [("a", "1"), ("b", "2"), ("c", "3")]}],
    }
    stack = {
        **row,
        "document_version_id": "stack",
        "previous_document_version_id": "row",
        "groups": [{**row["groups"][0], "layout": "stack", "gap": 24}],
    }
    reset = {**stack, "document_version_id": "reset", "previous_document_version_id": "stack", "groups": []}
    assert verify_restored_group_reset([row, stack, reset]) == {
        "verified_grouped_document_version_count": 2,
        "grouped_arranged_and_reset_versions_verified": True,
    }
    for broken in (
        {**stack, "previous_document_version_id": "other"},
        {**stack, "groups": [{**stack["groups"][0], "id": "other"}]},
        {**stack, "groups": [{**stack["groups"][0], "images": [("x", "1")]}]},
        {**reset, "images": [("x", "1")]},
    ):
        with pytest.raises(ValueError):
            verify_restored_group_reset([row, broken, reset])
    for rows in ([], [row], [stack, reset], [row, reset]):
        with pytest.raises(ValueError):
            verify_restored_group_reset(rows)


def test_group_duplicate_recovery_requires_fresh_assets_with_same_ordered_pixels() -> None:
    source_group: dict[str, Any] = {
        "id": "source",
        "layout": "row",
        "gap": 20,
        "images": [("a", "1"), ("b", "2")],
    }
    copied_group: dict[str, Any] = {
        "id": "copy",
        "layout": "row",
        "gap": 20,
        "images": [("c", "3"), ("d", "4")],
    }
    version = {
        "object_id": "doc",
        "document_version_id": "saved",
        "groups": [source_group, copied_group],
    }
    bindings = [
        {
            "object_id": "doc",
            "document_version_id": "saved",
            "asset_id": asset,
            "asset_version_id": image_version,
            "content_hash": content_hash,
        }
        for asset, image_version, content_hash in (
            ("a", "1", "red"),
            ("b", "2", "blue"),
            ("c", "3", "red"),
            ("d", "4", "blue"),
        )
    ]
    assert verify_restored_group_duplicate([version], bindings) == {
        "verified_duplicated_image_group_count": 1,
        "independently_owned_group_duplicate_verified": True,
    }
    for broken in (
        [{**version, "groups": [{**source_group}, {**copied_group, "id": "source"}]}],
        [{**version, "groups": [{**source_group}, {**copied_group, "layout": "stack"}]}],
        [
            {
                **version,
                "groups": [
                    {**source_group},
                    {**copied_group, "images": [("a", "1"), ("d", "4")]},
                ],
            }
        ],
    ):
        with pytest.raises(ValueError):
            verify_restored_group_duplicate(broken, bindings)


def test_image_duplicate_recovery_requires_fresh_asset_figure_pixels_and_bounded_offset() -> None:
    source = {
        "asset_id": "a",
        "asset_version_id": "1",
        "figure_id": "figure-source",
        "position": {"layer": "front", "x": 980, "y": 1190},
    }
    copied = {
        "asset_id": "b",
        "asset_version_id": "2",
        "figure_id": "figure-copy",
        "position": {"layer": "front", "x": 940, "y": 1166},
    }
    version = {
        "object_id": "doc",
        "document_version_id": "saved",
        "standalone_images": [source, copied],
    }
    bindings = [
        {
            "object_id": "doc",
            "document_version_id": "saved",
            "asset_id": attrs["asset_id"],
            "asset_version_id": attrs["asset_version_id"],
            "content_hash": "same-pixels",
        }
        for attrs in (source, copied)
    ]
    assert verify_restored_image_duplicate([version], bindings) == {
        "verified_duplicated_image_count": 1,
        "independently_owned_image_duplicate_verified": True,
    }
    for replacement in (
        {**copied, "asset_id": "a", "asset_version_id": "1"},
        {**copied, "figure_id": "figure-source"},
        {**copied, "position": {"layer": "front", "x": 960, "y": 1166}},
    ):
        with pytest.raises(ValueError):
            verify_restored_image_duplicate([{**version, "standalone_images": [source, replacement]}], bindings)


def test_image_replacement_recovery_requires_fresh_pixels_and_preserved_presentation() -> None:
    common = {
        "figure_id": "figure-stable",
        "position": {"layer": "front", "x": 640, "y": 120},
        "align": "left",
        "alt": "Blue and orange squares",
        "caption": "<literal image caption>",
        "decorative": False,
        "lock_aspect": True,
        "crop": None,
        "transform": {"rotation": 90, "flipX": True, "flipY": False},
    }
    source = {
        **common,
        "asset_id": "a",
        "asset_version_id": "1",
        "pixel_width": 320,
        "pixel_height": 160,
        "width": 300,
        "height": 150,
    }
    replacement = {
        **common,
        "asset_id": "b",
        "asset_version_id": "2",
        "pixel_width": 200,
        "pixel_height": 300,
        "width": 300,
        "height": 450,
    }
    versions = [
        {
            "object_id": "doc",
            "document_version_id": "old",
            "previous_document_version_id": None,
            "standalone_images": [source],
        },
        {
            "object_id": "doc",
            "document_version_id": "new",
            "previous_document_version_id": "old",
            "standalone_images": [replacement],
        },
    ]
    bindings = [
        {
            "object_id": "doc",
            "document_version_id": "old",
            "asset_id": "a",
            "asset_version_id": "1",
            "content_hash": "old-pixels",
        },
        {
            "object_id": "doc",
            "document_version_id": "new",
            "asset_id": "b",
            "asset_version_id": "2",
            "content_hash": "new-pixels",
        },
    ]
    assert verify_restored_image_replacement(versions, bindings) == {
        "verified_replaced_image_count": 1,
        "fresh_image_replacement_with_preserved_presentation_verified": True,
    }
    for broken in (
        {**replacement, "asset_id": "a", "asset_version_id": "1"},
        {**replacement, "figure_id": "different"},
        {**replacement, "height": 449},
        {**replacement, "crop": {"x": 0, "y": 0, "width": 100, "height": 100}},
    ):
        with pytest.raises(ValueError):
            verify_restored_image_replacement([versions[0], {**versions[1], "standalone_images": [broken]}], bindings)
    with pytest.raises(ValueError):
        verify_restored_image_replacement(versions, [{**bindings[1], "content_hash": "old-pixels"}, bindings[0]])
