from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from office_recovery_proof import require_office_recovery_environment, verify_restored_figure_versions
from suite.ai_control_plane.audit import canonical_json, stable_hash
from test_office_recovery_proof import recovery_environment
from test_work_e2e_harness import valid_environment
from work_e2e_figures import FIGURE_RECOVERY_TITLE, figure_recovery_document, seed_synthetic_office_figures


def image_attrs(seed: str) -> dict[str, object]:
    return {
        "documentId": "office-doc-" + "a" * 32,
        "assetId": "office-image-" + seed * 32,
        "versionId": "office-image-version-" + seed * 32,
        "contentHash": "sha256:" + seed * 64,
        "manifestHash": "sha256:" + ("d" if seed == "b" else "e") * 64,
        "pixelWidth": 1,
        "pixelHeight": 1,
        "width": 1,
        "height": 1,
        "align": "left",
        "alt": "",
        "caption": "",
        "decorative": True,
        "lockAspect": True,
    }


def test_figure_seed_rejects_normal_environment_before_storage_access() -> None:
    environment = valid_environment()
    environment["SUITE_DATABASE_DSN"] = "postgresql://app:secret@postgres:5432/collabio"
    client = Mock()
    with pytest.raises(RuntimeError):
        seed_synthetic_office_figures(environment=environment, client=client)
    assert not client.mock_calls


def test_figure_restore_target_requires_matching_fixed_pair() -> None:
    env = recovery_environment()
    for key in ("SUITE_POSTGRES_RESTORE_TARGET_DSN", "SUITE_OFFICE_RECOVERY_TARGET_DSN"):
        env[key] = env[key].replace("/collabio_work_e2e_restore", "/collabio_work_e2e_278_restore")
    require_office_recovery_environment(env)
    env["SUITE_POSTGRES_RESTORE_TARGET_DSN"] = recovery_environment()["SUITE_POSTGRES_RESTORE_TARGET_DSN"]
    with pytest.raises(ValueError):
        require_office_recovery_environment(env)


@pytest.mark.parametrize("tamper", [None, "missing", "format", "hash", "lineage"])
def test_recovery_binds_exact_figure_add_reorder_broken_and_reset(tamper: str | None) -> None:
    images = [image_attrs("b"), image_attrs("c")]
    contents = {number: figure_recovery_document(number, images) for number in range(1, 6)}
    if tamper == "format":
        contents[3] = deepcopy(contents[3])
        contents[3]["content"][1]["attrs"]["caption"] = "Altered"
    versions = []
    reads = {}
    previous = None
    for number in range(1, 6):
        version_id = f"version-{number}"
        digest = stable_hash(canonical_json(contents[number]))
        versions.append(
            {
                "object_id": "office-doc-" + "a" * 32,
                "version_id": version_id,
                "previous_version_id": previous,
                "content_hash": digest,
                "mutation_reference": f"work-e2e-figure-recovery-{number}",
            }
        )
        reads[version_id] = SimpleNamespace(
            content=contents[number],
            version=SimpleNamespace(version_id=version_id, title=FIGURE_RECOVERY_TITLE, content_hash=digest),
            can_write=False,
        )
        previous = version_id
    if tamper == "missing":
        versions.pop()
    elif tamper == "hash":
        versions[1]["content_hash"] = "sha256:incorrect"
    elif tamper == "lineage":
        versions[1]["previous_version_id"] = None
    documents = Mock()
    documents.read_content.side_effect = lambda **kwargs: reads[kwargs["version_id"]]
    arguments = {
        "documents": documents,
        "readers": {"office-doc-" + "a" * 32: Mock()},
        "versions": versions,
    }
    if tamper is not None:
        with pytest.raises(ValueError):
            verify_restored_figure_versions(**arguments)
    else:
        report = verify_restored_figure_versions(**arguments)
        assert report["verified_figure_fixture_version_count"] == 5
        assert report["figures_reorder_broken_and_reset_verified"]
        assert report["legacy_figure_canonical_hash_verified"]
