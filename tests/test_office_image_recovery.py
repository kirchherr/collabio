from unittest.mock import Mock

import pytest

from office_image_recovery import verify_restored_images
from office_recovery_proof import require_office_recovery_environment
from test_office_recovery_proof import recovery_environment


@pytest.mark.parametrize("number", [268, 269])
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
