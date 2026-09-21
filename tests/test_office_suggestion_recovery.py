from dataclasses import dataclass
from typing import Any

import pytest

from office_suggestion_recovery import verify_restored_suggestions
from suite.ai_control_plane.audit import InMemoryAuditLogger, canonical_json
from suite.ai_control_plane.models import UserContext
from suite.platform.office_document_repository import InMemoryOfficeDocumentRepository
from suite.platform.office_documents import (
    OfficeDocumentCreateCommand,
    OfficeDocumentSaveCommand,
    OfficeDocumentService,
    office_document_command_hash,
)
from suite.platform.office_suggestion_repository import OfficeSuggestionRepositoryAdapter
from suite.platform.office_suggestions import (
    OfficeSuggestionService,
    SuggestionCreateCommand,
    SuggestionDecisionCommand,
)
from suite.storage.source_objects import (
    InMemorySourceObjectRepository,
    InMemorySourceObjectWriteReceiptStore,
    build_source_object_manifest_hash,
    build_source_object_write_receipt,
)


@dataclass
class SuggestionRecoveryFixture:
    service: OfficeSuggestionService
    repository: OfficeSuggestionRepositoryAdapter
    document_repository: InMemoryOfficeDocumentRepository
    sources: InMemorySourceObjectRepository
    receipts: InMemorySourceObjectWriteReceiptStore
    user: UserContext
    object_id: str
    suggestion_ids: set[str]
    decision_ids: set[str]

    def verify(self) -> dict[str, Any]:
        return verify_restored_suggestions(
            suggestions=self.service,
            sources=self.sources,
            receipts=self.receipts,
            user=self.user,
            object_ids=(self.object_id,),
            expected_suggestion_ids=self.suggestion_ids,
            expected_decision_ids=self.decision_ids,
        )


def suggestion_recovery_fixture(*, count: int = 2) -> SuggestionRecoveryFixture:
    sources = InMemorySourceObjectRepository()
    receipts = InMemorySourceObjectWriteReceiptStore()
    document_repository = InMemoryOfficeDocumentRepository(source_repository=sources, receipt_store=receipts)
    documents = OfficeDocumentService(
        repository=document_repository, source_repository=sources, audit=InMemoryAuditLogger()
    )
    user = UserContext(tenant_id="tenant-work-e2e", user_id="work-office-editor-e2e", role_ids={"office-editor"})
    saved = documents.create(
        user_context=user,
        write_enabled=True,
        command=OfficeDocumentCreateCommand(
            title="Synthetic suggestion recovery",
            document={
                "type": "doc",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "😀 private anchor"}]}],
            },
            mutation_reference="recovery-suggestion-doc",
            human_confirmation=True,
        ),
    )
    object_id = saved.document.object_id
    user.readable_object_ids.add(object_id)
    repository = OfficeSuggestionRepositoryAdapter(document_service=documents)
    service = OfficeSuggestionService(repository=repository, document_service=documents, audit=InMemoryAuditLogger())
    ids: list[str] = []
    for index in range(count):
        created = service.mutate(
            user_context=user,
            object_id=object_id,
            write_enabled=True,
            command=SuggestionCreateCommand.model_validate(
                {
                    "anchor_version_id": saved.version.version_id,
                    "expected_current_version_id": saved.version.version_id,
                    "anchor": {"from": 1, "to": 3},
                    "replacement_text": f"private replacement {index}",
                    "mutation_reference": f"suggestion-{index}",
                    "human_confirmation": True,
                }
            ),
        )
        ids.append(created.suggestion.suggestion_id)
    decisions: set[str] = set()
    for index, suggestion_id in enumerate(ids[:2]):
        decision = service.mutate(
            user_context=user,
            object_id=object_id,
            suggestion_id=suggestion_id,
            write_enabled=True,
            command=SuggestionDecisionCommand.model_validate(
                {
                    "operation": "accept" if index == 0 else "reject",
                    "expected_revision": 1,
                    "expected_current_version_id": saved.version.version_id if index == 0 else None,
                    "mutation_reference": f"decision-{index}",
                    "human_confirmation": True,
                }
            ),
        )
        assert decision.decision is not None
        decisions.add(decision.decision.decision_id)
    documents.writes_available = False
    return SuggestionRecoveryFixture(
        service, repository, document_repository, sources, receipts, user, object_id, set(ids), decisions
    )


def test_suggestion_recovery_reads_all_pages_exact_results_and_emits_only_metadata() -> None:
    fixture = suggestion_recovery_fixture(count=52)
    report = fixture.verify()
    assert report["verified_suggestion_count"] == 52
    assert report["verified_suggestion_decision_count"] == 2
    assert report["accepted_suggestion_count"] == report["rejected_suggestion_count"] == 1
    assert report["suggestion_result_versions_verified"]
    assert report["suggestion_authoritative_acl_verified"]
    assert report["suggestion_read_only_verified"]
    assert report["suggestion_receipt_bindings_verified"]
    assert "private" not in canonical_json(report) and "😀" not in canonical_json(report)


@pytest.mark.parametrize(
    "tamper",
    (
        "missing_proposal",
        "missing_decision",
        "anchor",
        "source",
        "receipt",
        "result",
        "rejected_result",
        "acl",
        "inventory",
        "writable",
    ),
)
def test_suggestion_recovery_denies_incomplete_content_lineage_or_permissions(tamper: str) -> None:
    fixture = suggestion_recovery_fixture()
    proposals = fixture.repository._memory["text_suggestions"]
    decisions = fixture.repository._memory["text_suggestion_decisions"]
    accepted_key, accepted = next((key, row) for key, row in decisions.items() if row["operation"] == "accept")
    proposal = proposals[accepted_key]
    if tamper == "missing_proposal":
        del proposals[accepted_key]
    elif tamper == "missing_decision":
        del decisions[accepted_key]
    elif tamper == "anchor":
        proposal["anchor_from"] = 3
        proposal["anchor_to"] = 4
    elif tamper == "source":
        key = (fixture.user.tenant_id, proposal["suggestion_id"], proposal["source_version_id"])
        fixture.sources._records[key] = fixture.sources._records[key].model_copy(update={"content_bytes": b"corrupt"})
    elif tamper == "receipt":
        key = (fixture.user.tenant_id, proposal["source_write_receipt_hash"])
        fixture.receipts._receipts[key] = fixture.receipts._receipts[key].model_copy(
            update={"parent_object_id": "wrong"}
        )
    elif tamper == "result":
        key = (fixture.user.tenant_id, fixture.object_id, accepted["result_version_id"])
        fixture.document_repository.saved_versions[key] = fixture.document_repository.saved_versions[key].model_copy(
            update={"previous_version_id": "unrelated"}
        )
    elif tamper == "rejected_result":
        rejected = next(row for row in decisions.values() if row["operation"] == "reject")
        rejected["result_version_id"] = accepted["result_version_id"]
    elif tamper == "acl":
        fixture.document_repository.grants.clear()
    elif tamper == "inventory":
        fixture.decision_ids.add("missing-decision")
    else:
        fixture.service.documents.writes_available = True
    with pytest.raises((KeyError, ValueError)):
        fixture.verify()


def test_suggestion_recovery_requires_both_accepted_and_rejected_evidence() -> None:
    with pytest.raises(ValueError, match="accepted and rejected"):
        suggestion_recovery_fixture(count=1).verify()


def test_suggestion_recovery_rejects_consistently_renamed_accepted_version() -> None:
    fixture = suggestion_recovery_fixture()
    accepted = next(
        row
        for row in fixture.repository._memory["text_suggestion_decisions"].values()
        if row["operation"] == "accept"
    )
    tenant_id = fixture.user.tenant_id
    key = (tenant_id, fixture.object_id, accepted["result_version_id"])
    version = fixture.document_repository.saved_versions[key]
    before = fixture.service.documents.read_content(
        user_context=fixture.user, object_id=fixture.object_id, version_id=version.version_id
    )
    renamed_title = "Unexpected additional rename"
    source = fixture.sources._records[key]
    metadata = source.metadata.model_copy(update={"title": renamed_title})
    metadata = metadata.model_copy(update={"manifest_hash": build_source_object_manifest_hash(metadata)})
    source = source.model_copy(update={"metadata": metadata})
    original_receipt = fixture.receipts.get(tenant_id=tenant_id, receipt_hash=version.source_write_receipt_hash)
    receipt = build_source_object_write_receipt(
        record=source,
        receipt_reference=original_receipt.receipt_reference,
        audit_chain_ref=original_receipt.audit_chain_ref,
        captured_at_utc=original_receipt.captured_at_utc,
    )
    assert version.previous_version_id is not None
    command = OfficeDocumentSaveCommand(
        title=renamed_title,
        document=before.content,
        expected_current_version_id=version.previous_version_id,
        mutation_reference=version.mutation_reference,
        human_confirmation=True,
    )
    # Keep source, receipt, head and version internally consistent: only the
    # cross-version promise that accepting a text suggestion preserves its title is broken.
    fixture.sources._records[key] = source
    del fixture.receipts._receipts[(tenant_id, original_receipt.receipt_hash)]
    fixture.receipts._receipts[(tenant_id, receipt.receipt_hash)] = receipt
    fixture.document_repository.saved_versions[key] = version.model_copy(
        update={
            "title": renamed_title,
            "source_manifest_hash": metadata.manifest_hash,
            "source_write_receipt_hash": receipt.receipt_hash,
            "command_hash": office_document_command_hash(
                user_context=fixture.user, object_id=fixture.object_id, command=command
            ),
        }
    )
    head_key = (tenant_id, fixture.object_id)
    fixture.document_repository.documents[head_key] = fixture.document_repository.documents[head_key].model_copy(
        update={"title": renamed_title}
    )
    result = fixture.service.documents.read_content(
        user_context=fixture.user, object_id=fixture.object_id, version_id=version.version_id
    )
    assert result.version.title == result.document.title == renamed_title
    assert result.content == before.content
    assert result.version.content_hash == before.version.content_hash
    with pytest.raises(ValueError, match="Office restored accepted document version is invalid"):
        fixture.verify()
