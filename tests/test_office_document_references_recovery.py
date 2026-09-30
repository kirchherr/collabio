from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from office_recovery_proof import verify_restored_document_reference_versions
from suite.ai_control_plane.audit import canonical_json, stable_hash
from work_e2e_document_references import (
    REFERENCE_SOURCE_TITLE,
    REFERENCE_TARGET_TITLE_V1,
    REFERENCE_TARGET_TITLE_V2,
    reference_text,
)


def recovery_fixture() -> tuple[Mock, dict[str, Mock], list[dict[str, str]]]:
    target_id, source_id = "office-doc-target", "office-doc-source"
    target_v1, target_v2 = "office-version-target-1", "office-version-target-2"
    source_v1, source_v2 = "office-version-source-1", "office-version-source-2"
    rows = [
        {
            "object_id": target_id,
            "version_id": target_v1,
            "previous_version_id": None,
            "mutation_reference": "work-e2e-document-reference-target-1",
        },
        {
            "object_id": target_id,
            "version_id": target_v2,
            "previous_version_id": target_v1,
            "mutation_reference": "work-e2e-document-reference-target-2",
        },
        {
            "object_id": source_id,
            "version_id": source_v1,
            "previous_version_id": None,
            "mutation_reference": "work-e2e-document-reference-source-1",
        },
        {
            "object_id": source_id,
            "version_id": source_v2,
            "previous_version_id": source_v1,
            "mutation_reference": "work-e2e-document-reference-source-2",
        },
    ]
    contents = {
        target_v1: (REFERENCE_TARGET_TITLE_V1, reference_text("Target version one")),
        target_v2: (REFERENCE_TARGET_TITLE_V2, reference_text("Target version two")),
        source_v1: (REFERENCE_SOURCE_TITLE, reference_text("Legacy source")),
        source_v2: (
            REFERENCE_SOURCE_TITLE,
            reference_text("Pinned target", target_object_id=target_id, target_version_id=target_v1),
        ),
    }
    reads = {}
    for row in rows:
        title, content = contents[row["version_id"]]
        digest = stable_hash(canonical_json(content))
        row["content_hash"] = digest
        reads[row["version_id"]] = SimpleNamespace(
            content=content,
            version=SimpleNamespace(title=title, content_hash=digest),
            can_write=False,
        )
    documents = Mock()
    documents.read_content.side_effect = lambda **kwargs: reads[kwargs["version_id"]]
    documents.outbound_references.return_value = SimpleNamespace(
        references=[SimpleNamespace(status="resolved", title=REFERENCE_TARGET_TITLE_V1, is_current_version=False)]
    )
    documents.backlinks.return_value = SimpleNamespace(
        backlinks=[
            SimpleNamespace(
                source_object_id=source_id,
                source_version_id=source_v2,
                title=REFERENCE_SOURCE_TITLE,
                reference_count=1,
            )
        ],
        has_more=False,
        content_included=False,
    )
    return documents, {target_id: Mock(), source_id: Mock()}, rows


def test_recovery_binds_exact_document_reference_and_authorized_backlink() -> None:
    documents, readers, versions = recovery_fixture()
    report = verify_restored_document_reference_versions(
        documents=documents,
        readers=readers,
        versions=versions,
    )
    assert report["verified_document_reference_fixture_version_count"] == 4
    assert report["exact_historical_document_reference_and_current_acl_verified"]
    assert report["exact_backlink_and_current_source_acl_verified"]


def test_recovery_rejects_missing_backlink_derivation() -> None:
    documents, readers, versions = recovery_fixture()
    documents.backlinks.return_value.backlinks = []
    with pytest.raises(ValueError, match="backlink derivation"):
        verify_restored_document_reference_versions(
            documents=documents,
            readers=readers,
            versions=versions,
        )
