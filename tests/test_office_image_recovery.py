from typing import Any
from unittest.mock import Mock

import pytest

from office_image_recovery import (
    verify_restored_crop_reset,
    verify_restored_group_reset,
    verify_restored_images,
    verify_restored_position_reset,
    verify_restored_transform_reset,
    verify_restored_wrap_reset,
)
from office_recovery_proof import require_office_recovery_environment
from test_office_recovery_proof import recovery_environment


@pytest.mark.parametrize("number", [268, 269, 270, 291])
def test_image_restore_target_requires_a_matching_separate_pair(number: int) -> None:
    env = recovery_environment()
    for key in ("SUITE_POSTGRES_RESTORE_TARGET_DSN", "SUITE_OFFICE_RECOVERY_TARGET_DSN"):
        env[key] = env[key].replace("/collabio_work_e2e_restore", f"/collabio_work_e2e_{number}_restore")
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
    stack = {**row, "document_version_id": "stack", "previous_document_version_id": "row",
        "groups": [{**row["groups"][0], "layout": "stack", "gap": 24}]}
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
