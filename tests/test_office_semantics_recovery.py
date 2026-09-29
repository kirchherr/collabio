from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from office_recovery_proof import require_office_recovery_environment, verify_restored_semantic_versions
from suite.ai_control_plane.audit import canonical_json, stable_hash
from test_office_recovery_proof import recovery_environment
from test_work_e2e_harness import valid_environment
from work_e2e_semantics import (
    SEMANTIC_RECOVERY_TITLE,
    SEMANTIC_RECOVERY_VERSION_COUNT,
    seed_synthetic_office_semantics,
    semantic_recovery_document,
)


def test_semantic_seed_rejects_normal_environment_before_storage_access() -> None:
    environment = valid_environment()
    environment["SUITE_DATABASE_DSN"] = "postgresql://app:secret@postgres:5432/collabio"
    client = Mock()
    with pytest.raises(RuntimeError):
        seed_synthetic_office_semantics(environment=environment, client=client)
    assert not client.mock_calls


def test_semantic_restore_target_requires_matching_fixed_pair() -> None:
    env = recovery_environment()
    for key in ("SUITE_POSTGRES_RESTORE_TARGET_DSN", "SUITE_OFFICE_RECOVERY_TARGET_DSN"):
        env[key] = env[key].replace("/collabio_work_e2e_restore", "/collabio_work_e2e_286_restore")
    require_office_recovery_environment(env)
    env["SUITE_POSTGRES_RESTORE_TARGET_DSN"] = recovery_environment()["SUITE_POSTGRES_RESTORE_TARGET_DSN"]
    with pytest.raises(ValueError):
        require_office_recovery_environment(env)


@pytest.mark.parametrize("tamper", [None, "missing", "format", "hash", "lineage"])
def test_recovery_binds_all_semantic_structures_and_broken_reset_versions(tamper: str | None) -> None:
    contents = {number: semantic_recovery_document(number) for number in range(1, SEMANTIC_RECOVERY_VERSION_COUNT + 1)}
    if tamper == "format":
        contents[7] = deepcopy(contents[7])
        contents[7]["content"][-1]["attrs"]["source"] = "altered"
    versions, reads, previous = [], {}, None
    for number in range(1, SEMANTIC_RECOVERY_VERSION_COUNT + 1):
        version_id = f"version-{number}"
        digest = stable_hash(canonical_json(contents[number]))
        versions.append({"object_id": "office-doc-" + "a" * 32, "version_id": version_id,
            "previous_version_id": previous, "content_hash": digest,
            "mutation_reference": f"work-e2e-semantic-recovery-{number}"})
        reads[version_id] = SimpleNamespace(content=contents[number], version=SimpleNamespace(
            version_id=version_id, title=SEMANTIC_RECOVERY_TITLE, content_hash=digest), can_write=False)
        previous = version_id
    if tamper == "missing":
        versions.pop()
    elif tamper == "hash":
        versions[1]["content_hash"] = "sha256:incorrect"
    elif tamper == "lineage":
        versions[1]["previous_version_id"] = None
    documents = Mock()
    documents.read_content.side_effect = lambda **kwargs: reads[kwargs["version_id"]]
    readers = {"office-doc-" + "a" * 32: Mock()}
    if tamper is not None:
        with pytest.raises(ValueError):
            verify_restored_semantic_versions(documents=documents, readers=readers, versions=versions)
    else:
        report = verify_restored_semantic_versions(documents=documents, readers=readers, versions=versions)
        assert report["verified_semantic_fixture_version_count"] == SEMANTIC_RECOVERY_VERSION_COUNT
        assert report["fields_toc_notes_citations_equations_and_reference_index_verified"]
        assert report["broken_semantic_references_and_legacy_reset_verified"]
