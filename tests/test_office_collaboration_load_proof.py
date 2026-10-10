import json
from pathlib import Path

from suite.operations.office_collaboration_load_proof import (
    BACKPRESSURE_CLOSE_CODE,
    MAX_QUEUED_BYTES,
    TARGET_EDITORS,
    UPDATES_PER_EDITOR,
    run_office_collaboration_load_proof,
)


def test_office_collaboration_load_proof_exercises_fifty_parallel_editors_and_closed_runtime() -> None:
    report = run_office_collaboration_load_proof()

    assert report.target_editor_count == TARGET_EDITORS
    assert report.max_parallel_editors == TARGET_EDITORS
    assert report.updates_per_editor == UPDATES_PER_EDITOR
    assert report.unique_update_count == TARGET_EDITORS * UPDATES_PER_EDITOR
    assert report.converged_editor_count == TARGET_EDITORS
    assert report.per_update_acl_check_count == TARGET_EDITORS * UPDATES_PER_EDITOR + 1
    assert report.session_reauthorization_count == TARGET_EDITORS * 3
    assert report.checkpoint_update_count == TARGET_EDITORS * (UPDATES_PER_EDITOR // 2)
    assert report.resume_replay_update_count == TARGET_EDITORS * (UPDATES_PER_EDITOR // 2)
    assert report.duplicate_update_count == 1
    assert report.duplicate_delivery_deduplicated
    assert report.state_vector_resume_verified
    assert report.all_editors_converged
    assert report.isolated_load_target_verified
    assert report.backpressure_rejection_verified
    assert report.backpressure_close_code == BACKPRESSURE_CLOSE_CODE
    assert report.max_observed_queued_bytes == MAX_QUEUED_BYTES
    assert report.revoked_acl_rejection_verified
    assert report.foreign_tenant_rejection_verified
    assert not report.websocket_load_verified
    assert not report.production_runtime_admitted
    assert not report.document_content_processed
    assert not report.raw_session_identifiers_persisted
    assert report.final_state_vector_hash.startswith("sha256:")
    assert report.final_update_set_hash.startswith("sha256:")
    assert report.evidence_hash.startswith("sha256:")


def test_office_collaboration_load_proof_is_deterministic() -> None:
    first = run_office_collaboration_load_proof()
    second = run_office_collaboration_load_proof()

    assert first == second
    expected = json.loads(
        (Path(__file__).parent / "golden" / "office_collaboration_load_proof" / "current_report.json").read_text(
            encoding="utf-8"
        )
    )
    assert first.model_dump(mode="json") == expected
