from dataclasses import dataclass
from typing import Any
from unittest.mock import Mock

import pytest

from office_recovery_proof import (
    TENANT_ID, require_office_recovery_environment, restored_document_inventory, restored_version_inventory,
    verify_restored_paragraph_versions, verify_restored_reviews,
)
from office_suggestion_recovery import verify_restored_suggestions
from suite.ai_control_plane.audit import InMemoryAuditLogger, canonical_json
from suite.ai_control_plane.models import UserContext
from suite.platform.office_document_repository import InMemoryOfficeDocumentRepository
from suite.platform.office_documents import OfficeDocumentCreateCommand, OfficeDocumentSaveCommand, OfficeDocumentService
from suite.storage.source_objects import InMemorySourceObjectRepository
from test_office_recovery_proof import recovery_environment, review_recovery_fixture
from test_office_suggestion_recovery import suggestion_recovery_fixture
from work_e2e_paragraph import PARAGRAPH_RECOVERY_TITLE, paragraph_recovery_document


@dataclass
class RecoveryDocuments:
    service: OfficeDocumentService
    repository: InMemoryOfficeDocumentRepository
    users: tuple[UserContext, ...]
    inventory: list[Any]
    history_object_id: str


def recovery_documents(*, count: int = 2, versions: int = 2) -> RecoveryDocuments:
    sources = InMemorySourceObjectRepository()
    repository = InMemoryOfficeDocumentRepository(source_repository=sources)
    service = OfficeDocumentService(repository=repository, source_repository=sources, audit=InMemoryAuditLogger())
    users = tuple(UserContext(tenant_id=TENANT_ID, user_id=f"recovery-author-{index}", role_ids={"office-editor"}) for index in range(2))
    content = {"type": "doc", "content": [{"type": "paragraph"}]}
    history_object_id = ""
    for index in range(count):
        user = users[1 if index == count - 1 else 0]
        command = OfficeDocumentCreateCommand(title=f"Recovery {index}", document=content, mutation_reference=f"document-{index}", human_confirmation=True)
        result = service.create(user_context=user, command=command, write_enabled=True)
        user.readable_object_ids.add(result.document.object_id)
        if index == 0:
            history_object_id = result.document.object_id
            for number in range(1, versions):
                result = service.save(user_context=user, object_id=history_object_id, write_enabled=True, command=OfficeDocumentSaveCommand(**{**command.model_dump(), "mutation_reference": f"version-{number}"}, expected_current_version_id=result.version.version_id))
    service.writes_available = False
    return RecoveryDocuments(service, repository, users, [record.model_dump() for record in repository.documents.values()], history_object_id)


def test_recovery_reads_complete_document_and_version_pages_with_separate_current_acl_principals(monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = recovery_documents(count=206, versions=205)
    listing = Mock(wraps=fixture.service.list_documents)
    history = Mock(wraps=fixture.service.history)
    monkeypatch.setattr(fixture.service, "list_documents", listing)
    monkeypatch.setattr(fixture.service, "history", history)
    documents, readers = restored_document_inventory(documents=fixture.service, users=fixture.users, expected_documents=fixture.inventory)
    assert len(documents) == 206
    assert {reader.user_id for reader in readers.values()} == {user.user_id for user in fixture.users}
    document = next(document for document in documents if document.object_id == fixture.history_object_id)
    versions = restored_version_inventory(documents=fixture.service, user=readers[document.object_id], document=document)
    assert len(versions) == 205
    assert versions[0].version_id == document.current_version_id and versions[-1].previous_version_id is None
    assert listing.call_count == 3 and history.call_count == 2
    assert listing.call_args_list[1].kwargs["cursor"] is not None
    assert history.call_args_list[1].kwargs["cursor"] is not None
    assert len(fixture.repository.saved_versions) == 410


@pytest.mark.parametrize("tamper", ["missing-principal", "forged-readable", "missing-inventory", "foreign", "writable"])
def test_recovery_rejects_incomplete_inventory_or_unproven_permissions(tamper: str) -> None:
    fixture = recovery_documents()
    users = fixture.users
    if tamper == "missing-principal":
        users = users[:1]
    elif tamper == "forged-readable":
        users = (users[0].model_copy(update={"readable_object_ids": {row["object_id"] for row in fixture.inventory}}),)
    elif tamper == "missing-inventory":
        fixture.inventory.pop()
    elif tamper == "foreign":
        users = (users[0].model_copy(update={"tenant_id": "tenant-other"}),)
    else:
        fixture.service.writes_available = True
    with pytest.raises(ValueError):
        restored_document_inventory(documents=fixture.service, users=users, expected_documents=fixture.inventory)


@pytest.mark.parametrize("tamper", ["missing-link", "cycle", "head", "truncated", "duplicate"])
def test_recovery_rejects_broken_or_truncated_immutable_history(monkeypatch: pytest.MonkeyPatch, tamper: str) -> None:
    fixture = recovery_documents(versions=3)
    documents, readers = restored_document_inventory(documents=fixture.service, users=fixture.users, expected_documents=fixture.inventory)
    document = next(item for item in documents if item.object_id == fixture.history_object_id)
    user = readers[document.object_id]
    page = fixture.service.history(user_context=user, object_id=document.object_id)
    if tamper in {"missing-link", "cycle"}:
        version = fixture.repository.saved_versions[(TENANT_ID, document.object_id, page.versions[1].version_id)]
        fixture.repository.saved_versions[(TENANT_ID, document.object_id, version.version_id)] = version.model_copy(update={"previous_version_id": "missing" if tamper == "missing-link" else document.current_version_id})
    else:
        if tamper == "head":
            page = page.model_copy(update={"current_version_id": "different-head"})
        elif tamper == "truncated":
            page = page.model_copy(update={"versions": page.versions[:1]})
        else:
            page = page.model_copy(update={"versions": [page.versions[0], page.versions[0]]})
        monkeypatch.setattr(fixture.service, "history", Mock(return_value=page))
    with pytest.raises(ValueError):
        restored_version_inventory(documents=fixture.service, user=user, document=document)


def test_recovery_new_target_keeps_257_snapshot_separate_and_rejects_mismatched_target_pair() -> None:
    environment = recovery_environment()
    for key in ("SUITE_POSTGRES_RESTORE_TARGET_DSN", "SUITE_OFFICE_RECOVERY_TARGET_DSN"):
        environment[key] = environment[key].replace("/collabio_work_e2e_restore", "/collabio_work_e2e_262_restore")
    require_office_recovery_environment(environment)
    environment["SUITE_POSTGRES_RESTORE_TARGET_DSN"] = recovery_environment()["SUITE_POSTGRES_RESTORE_TARGET_DSN"]
    with pytest.raises(ValueError):
        require_office_recovery_environment(environment)


@pytest.mark.parametrize("name", ["collabio", "collabio_restore", "collabio_work_e2e", "collabio_work_e2e_263_restore"])
def test_recovery_target_remains_an_explicit_fixed_allowlist(name: str) -> None:
    environment = recovery_environment()
    for key in ("SUITE_POSTGRES_RESTORE_TARGET_DSN", "SUITE_OFFICE_RECOVERY_TARGET_DSN"):
        environment[key] = environment[key].replace("/collabio_work_e2e_restore", "/" + name)
    with pytest.raises(ValueError):
        require_office_recovery_environment(environment)


def test_review_and_suggestion_recovery_select_authorized_object_reader_without_granting_default_actor() -> None:
    reviews = review_recovery_fixture()
    denied = UserContext(tenant_id=TENANT_ID, user_id="unrelated", readable_object_ids={reviews.object_id})
    review_report = verify_restored_reviews(documents=reviews.documents, reviews=reviews.reviews, sources=reviews.sources, receipts=reviews.receipts, user=denied, users_by_object={reviews.object_id: reviews.user}, object_ids=(reviews.object_id,), expected_thread_ids={reviews.thread_id}, expected_event_ids=reviews.event_ids)
    assert review_report["verified_review_event_count"] == 4
    suggestions = suggestion_recovery_fixture()
    suggestion_report = verify_restored_suggestions(suggestions=suggestions.service, sources=suggestions.sources, receipts=suggestions.receipts, user=denied, users_by_object={suggestions.object_id: suggestions.user}, object_ids=(suggestions.object_id,), expected_suggestion_ids=suggestions.suggestion_ids, expected_decision_ids=suggestions.decision_ids)
    assert suggestion_report["verified_suggestion_decision_count"] == 2
    assert all(key[2] != denied.user_id for key in reviews.document_repository.grants)
    assert all(key[2] != denied.user_id for key in suggestions.document_repository.grants)


@pytest.mark.parametrize("tamper", [None, "missing", "format", "hash", "lineage"])
def test_recovery_binds_designated_legacy_and_formatted_sources_without_body_evidence(tamper: str | None) -> None:
    fixture = recovery_documents()
    fixture.service.writes_available = True
    user = fixture.users[0]
    created = fixture.service.create(user_context=user, write_enabled=True, command=OfficeDocumentCreateCommand(title=PARAGRAPH_RECOVERY_TITLE, document=paragraph_recovery_document(1), mutation_reference="work-e2e-paragraph-recovery-1", human_confirmation=True))
    object_id = created.document.object_id
    user.readable_object_ids.add(object_id)
    current = created
    for number in (2, 3):
        content = paragraph_recovery_document(number)
        if tamper == "format" and number == 2:
            content["content"][0]["attrs"]["textAlign"] = "right"
        current = fixture.service.save(user_context=user, object_id=object_id, write_enabled=True, command=OfficeDocumentSaveCommand(title=PARAGRAPH_RECOVERY_TITLE, document=content, mutation_reference=f"work-e2e-paragraph-recovery-{number}", human_confirmation=True, expected_current_version_id=current.version.version_id))
    fixture.service.writes_available = False
    versions = [record.model_dump() for record in fixture.repository.saved_versions.values() if record.object_id == object_id]
    if tamper == "missing":
        versions.pop()
    elif tamper == "hash":
        versions[1]["content_hash"] = "sha256:incorrect"
    elif tamper == "lineage":
        versions[1]["previous_version_id"] = None
    if tamper is not None:
        with pytest.raises(ValueError):
            verify_restored_paragraph_versions(documents=fixture.service, readers={object_id: user}, versions=versions)
    else:
        report = verify_restored_paragraph_versions(documents=fixture.service, readers={object_id: user}, versions=versions)
        assert report["verified_paragraph_fixture_version_count"] == 3
        assert report["verified_formatted_fixture_version_count"] == 2
        assert report["legacy_paragraph_canonical_hash_verified"]
        assert "Caf" not in canonical_json(report) and "textAlign" not in canonical_json(report)
