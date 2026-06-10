from suite.ai_control_plane.audit import GENESIS_HASH, InMemoryAuditLogger, verify_audit_chain
from suite.ai_control_plane.models import UserContext


def demo_user() -> UserContext:
    return UserContext(user_id="user-1", tenant_id="tenant-1")


def test_audit_events_are_hash_chained_without_plaintext_payloads() -> None:
    logger = InMemoryAuditLogger()

    first = logger.record(
        user_context=demo_user(),
        event_type="ai.inference",
        input_text="sensitive prompt",
        output_text="sensitive output",
    )
    second = logger.record(
        user_context=demo_user(),
        event_type="rag.retrieval",
        source_object_ids=["doc-1"],
        input_text="question",
    )

    assert first.sequence_number == 1
    assert first.previous_event_hash == GENESIS_HASH
    assert first.event_hash.startswith("sha256:")
    assert first.input_hash != "sensitive prompt"
    assert first.output_hash != "sensitive output"
    assert second.sequence_number == 2
    assert second.previous_event_hash == first.event_hash

    result = logger.verify()
    assert result.ok
    assert result.verified_events == 2


def test_audit_chain_detects_event_content_tampering() -> None:
    logger = InMemoryAuditLogger()
    event = logger.record(
        user_context=demo_user(),
        event_type="ai.inference",
        metadata={"purpose": "summarization"},
    )

    event.metadata["purpose"] = "changed-after-write"

    result = logger.verify()
    assert not result.ok
    assert result.verified_events == 0
    assert result.failure == f"Event {event.event_id} has invalid event hash"


def test_audit_chain_detects_removed_middle_event() -> None:
    logger = InMemoryAuditLogger()
    logger.record(user_context=demo_user(), event_type="first")
    logger.record(user_context=demo_user(), event_type="second")
    logger.record(user_context=demo_user(), event_type="third")

    events_with_gap = (logger.events[0], logger.events[2])

    result = verify_audit_chain(events_with_gap)
    assert not result.ok
    assert result.verified_events == 1
    assert result.failure == "Expected sequence 2, found 3"
