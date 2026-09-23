from typing import Any
from unittest.mock import Mock

import pytest

from office_image_recovery import verify_restored_crop_reset, verify_restored_images, verify_restored_wrap_reset
from office_recovery_proof import require_office_recovery_environment
from test_office_recovery_proof import recovery_environment


@pytest.mark.parametrize("number", [268, 269, 270])
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
