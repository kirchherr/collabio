"""Read-only validation of a nonempty restored saved-text suggestion inventory."""

from __future__ import annotations

import json
from typing import Any

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.ai_control_plane.models import UserContext
from suite.platform.office_documents import OfficeDocumentNotFoundError, OfficeDocumentPermissionError
from suite.platform.office_reviews import derive_review_quote
from suite.platform.office_suggestions import (
    OfficeSuggestionService,
    SuggestionDecisionCommand,
    replace_suggestion_text,
)
from suite.storage.source_objects import (
    SourceObjectRepository,
    SourceObjectType,
    SourceObjectWriteReceiptStore,
    build_source_object_write_receipt,
    source_object_content_bytes,
)


def verify_restored_suggestions(
    *,
    suggestions: OfficeSuggestionService,
    sources: SourceObjectRepository,
    receipts: SourceObjectWriteReceiptStore,
    user: UserContext,
    object_ids: tuple[str, ...],
    expected_suggestion_ids: set[str],
    expected_decision_ids: set[str],
) -> dict[str, Any]:
    evidence: list[dict[str, Any]] = []
    seen: set[str] = set()
    decisions: set[str] = set()
    accepted = rejected = 0
    denied_target: tuple[str, str] | None = None
    for object_id in object_ids:
        after: str | None = None
        while True:
            listing = suggestions.list_suggestions(
                user_context=user, object_id=object_id, after=after, limit=50, write_enabled=True
            )
            if listing.can_create or listing.rag_indexing_allowed or listing.search_indexing_allowed:
                raise ValueError("Office suggestion recovery must remain read-only")
            for view in listing.suggestions:
                if view.suggestion_id in seen or view.can_accept or view.can_reject:
                    raise ValueError("Office restored suggestion inventory or capabilities are invalid")
                seen.add(view.suggestion_id)
                denied_target = (object_id, view.suggestion_id)
                detail = suggestions.detail(
                    user_context=user, object_id=object_id, suggestion_id=view.suggestion_id, write_enabled=True
                )
                snapshot = suggestions.repository.detail(
                    user=user, object_id=object_id, suggestion_id=view.suggestion_id
                )
                proposal, decision = snapshot.suggestion, snapshot.decision
                anchor = suggestions.documents.read_content(
                    user_context=user, object_id=object_id, version_id=view.anchor_version_id
                )
                quote = derive_review_quote(anchor.content, view.anchor)
                if (
                    detail.suggestion != view
                    or detail.quote != quote
                    or anchor.can_write
                    or proposal.anchor_content_hash != anchor.version.content_hash
                    or detail.rag_indexing_allowed
                    or detail.search_indexing_allowed
                    or (decision is None) != (detail.decision is None)
                ):
                    raise ValueError("Office restored suggestion anchor or state is invalid")
                events = [proposal] if decision is None else [proposal, decision]
                for event in events:
                    source = sources.get(
                        tenant_id=user.tenant_id, object_id=view.suggestion_id, version_id=event.source_version_id
                    )
                    payload = json.loads(source_object_content_bytes(source).decode("utf-8"))
                    receipt = receipts.get(tenant_id=user.tenant_id, receipt_hash=event.source_write_receipt_hash)
                    expected_receipt = build_source_object_write_receipt(
                        record=source,
                        receipt_reference=receipt.receipt_reference,
                        audit_chain_ref=receipt.audit_chain_ref,
                        captured_at_utc=receipt.captured_at_utc,
                    )
                    is_decision = event is decision
                    if (
                        receipt != expected_receipt
                        or receipt.receipt_hash != event.source_write_receipt_hash
                        or receipt.content_hash != event.content_hash
                        or receipt.manifest_hash != event.source_manifest_hash
                        or source.metadata.object_type != SourceObjectType.COMMENT
                        or source.metadata.parent_object_id != object_id
                        or source.metadata.thread_id != view.suggestion_id
                        or stable_hash(canonical_json(payload)) != event.content_hash
                        or payload["quote"] != quote
                        or payload["replacement_text"] != detail.replacement_text
                        or payload["anchor_version_id"] != view.anchor_version_id
                        or payload["anchor_content_hash"] != anchor.version.content_hash
                        or payload["anchor"] != view.anchor.model_dump(by_alias=True)
                        or payload["operation"] != (decision.operation if is_decision and decision else "create")
                    ):
                        raise ValueError("Office restored suggestion source or receipt is invalid")
                    evidence.append(
                        {
                            "object_id": object_id,
                            "suggestion_id": view.suggestion_id,
                            "source_version_id": event.source_version_id,
                            "content_hash": event.content_hash,
                            "receipt_hash": receipt.receipt_hash,
                        }
                    )
                if decision is None:
                    if view.status != "open" or view.revision != 1 or view.result_version_id is not None:
                        raise ValueError("Office restored open suggestion has a decision")
                    continue
                if (
                    decision.decision_id in decisions
                    or decision.source_version_id != decision.decision_id
                    or view.revision != 2
                    or detail.decision is None
                    or detail.decision.decision_id != decision.decision_id
                    or detail.decision.operation != decision.operation
                ):
                    raise ValueError("Office restored suggestion decision is invalid")
                decisions.add(decision.decision_id)
                if decision.operation == "accept":
                    if not decision.result_version_id or view.status != "accepted":
                        raise ValueError("Office restored acceptance has no result")
                    result = suggestions.documents.read_content(
                        user_context=user, object_id=object_id, version_id=decision.result_version_id
                    )
                    expected_content = replace_suggestion_text(anchor.content, view.anchor, detail.replacement_text)
                    result_metadata = suggestions.documents.repository.get_version(
                        user_context=user,
                        object_id=object_id,
                        version_id=decision.result_version_id,
                    )
                    if (
                        result.content != expected_content
                        or result.can_write
                        or result.version.title != anchor.version.title
                        or result.version.content_hash != decision.result_content_hash
                        or result.version.previous_version_id != view.anchor_version_id
                        or result.version.created_by != decision.created_by
                        or result_metadata.mutation_reference != f"office-suggestion-accept:{decision.decision_id}"
                        or view.result_version_id != result.version.version_id
                    ):
                        raise ValueError("Office restored accepted document version is invalid")
                    accepted += 1
                else:
                    if (
                        view.status != "rejected"
                        or view.result_version_id is not None
                        or decision.result_version_id is not None
                        or decision.result_content_hash is not None
                    ):
                        raise ValueError("Office restored rejection contains a document result")
                    rejected += 1
            if listing.next_cursor is None:
                break
            if not listing.suggestions or listing.next_cursor == after or listing.next_cursor not in seen:
                raise ValueError("Office restored suggestion cursor is invalid")
            after = listing.next_cursor
    if seen != expected_suggestion_ids or decisions != expected_decision_ids:
        raise ValueError("Office suggestion recovery did not read the complete database inventory")
    if accepted < 1 or rejected < 1 or denied_target is None:
        raise ValueError("Office recovery requires nonempty accepted and rejected suggestions")
    object_id, suggestion_id = denied_target
    for denied in (
        UserContext(
            tenant_id="tenant-work-e2e-foreign", user_id=user.user_id, readable_object_ids={object_id, suggestion_id}
        ),
        UserContext(
            tenant_id=user.tenant_id, user_id="work-assignee-e2e", readable_object_ids={object_id, suggestion_id}
        ),
    ):
        try:
            suggestions.detail(user_context=denied, object_id=object_id, suggestion_id=suggestion_id)
        except OfficeDocumentNotFoundError:
            pass
        else:
            raise ValueError("Office restored suggestion access did not deny an unauthorized reader")
    try:
        suggestions.mutate(
            user_context=user,
            object_id=object_id,
            suggestion_id=suggestion_id,
            write_enabled=True,
            command=SuggestionDecisionCommand(
                operation="reject",
                expected_revision=1,
                mutation_reference="synthetic-recovery-suggestion-write-denied",
                human_confirmation=True,
            ),
        )
    except OfficeDocumentPermissionError:
        pass
    else:
        raise ValueError("Office suggestion recovery accepted a mutation")
    return {
        "suggestion_evidence_hash": stable_hash(canonical_json(evidence)),
        "verified_suggestion_count": len(seen),
        "verified_suggestion_decision_count": len(decisions),
        "accepted_suggestion_count": accepted,
        "rejected_suggestion_count": rejected,
        "suggestion_receipt_bindings_verified": True,
        "suggestion_result_versions_verified": True,
        "suggestion_authoritative_acl_verified": True,
        "suggestion_read_only_verified": True,
    }
