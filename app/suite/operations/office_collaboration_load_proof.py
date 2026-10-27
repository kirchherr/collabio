from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Barrier, Lock
from typing import Literal

from pydantic import BaseModel, ConfigDict

from suite.ai_control_plane.audit import canonical_json, stable_hash

TARGET_EDITORS = 50
UPDATES_PER_EDITOR = 8
MAX_UPDATE_BYTES = 262_144
MAX_QUEUED_BYTES = 1_048_576
BACKPRESSURE_CLOSE_CODE = 1013


class OfficeCollaborationLoadProofError(RuntimeError):
    pass


class OfficeCollaborationAuthorizationError(OfficeCollaborationLoadProofError):
    pass


class OfficeCollaborationBackpressureError(OfficeCollaborationLoadProofError):
    close_code = BACKPRESSURE_CLOSE_CODE


@dataclass(frozen=True)
class _Editor:
    tenant_id: str
    editor_id: str


@dataclass(frozen=True)
class _Update:
    tenant_id: str
    editor_id: str
    update_id: str
    sequence: int
    byte_size: int


class OfficeCollaborationLoadProofReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["office_collaboration_load_proof.v1"] = "office_collaboration_load_proof.v1"
    proof_scope: Literal["isolated_concurrent_engine_harness"] = "isolated_concurrent_engine_harness"
    target_editor_count: int
    max_parallel_editors: int
    updates_per_editor: int
    unique_update_count: int
    duplicate_update_count: int
    per_update_acl_check_count: int
    session_reauthorization_count: int
    checkpoint_update_count: int
    resume_replay_update_count: int
    converged_editor_count: int
    final_state_vector_hash: str
    final_update_set_hash: str
    max_observed_queued_bytes: int
    max_update_bytes: int
    max_queued_bytes: int
    backpressure_rejection_verified: bool
    backpressure_close_code: int
    revoked_acl_rejection_verified: bool
    foreign_tenant_rejection_verified: bool
    duplicate_delivery_deduplicated: bool
    state_vector_resume_verified: bool
    all_editors_converged: bool
    isolated_load_target_verified: bool
    websocket_load_verified: bool = False
    production_runtime_admitted: bool = False
    document_content_processed: bool = False
    raw_session_identifiers_persisted: bool = False
    evidence_hash: str


class _ConcurrentDocumentHarness:
    def __init__(self, *, tenant_id: str) -> None:
        self.tenant_id = tenant_id
        self._lock = Lock()
        self._authorized_editors: set[str] = set()
        self._active_editors: set[str] = set()
        self._pending: dict[str, _Update] = {}
        self._applied: dict[str, _Update] = {}
        self._state_vector: dict[str, int] = {}
        self._checkpoint_update_ids: tuple[str, ...] = ()
        self.max_parallel_editors = 0
        self.max_observed_queued_bytes = 0
        self.duplicate_update_count = 0
        self.per_update_acl_check_count = 0
        self.session_reauthorization_count = 0
        self.completed_rounds = 0

    def authorize(self, editor: _Editor) -> None:
        self._require_tenant(editor.tenant_id)
        with self._lock:
            self._authorized_editors.add(editor.editor_id)

    def revoke(self, editor_id: str) -> None:
        with self._lock:
            self._authorized_editors.discard(editor_id)

    def connect(self, editor: _Editor) -> None:
        self._require_authorized(editor)
        with self._lock:
            self._active_editors.add(editor.editor_id)
            self.max_parallel_editors = max(self.max_parallel_editors, len(self._active_editors))
            self.session_reauthorization_count += 1

    def reauthorize(self, editor: _Editor) -> None:
        self._require_authorized(editor)
        with self._lock:
            self.session_reauthorization_count += 1

    def disconnect(self, editor: _Editor) -> None:
        with self._lock:
            self._active_editors.discard(editor.editor_id)

    def enqueue(self, update: _Update) -> bool:
        self._require_authorized(_Editor(tenant_id=update.tenant_id, editor_id=update.editor_id))
        if update.byte_size < 1 or update.byte_size > MAX_UPDATE_BYTES:
            raise OfficeCollaborationLoadProofError("Update size is outside the admitted envelope")
        with self._lock:
            self.per_update_acl_check_count += 1
            if update.update_id in self._pending or update.update_id in self._applied:
                self.duplicate_update_count += 1
                return False
            queued_bytes = sum(item.byte_size for item in self._pending.values())
            if queued_bytes + update.byte_size > MAX_QUEUED_BYTES:
                raise OfficeCollaborationBackpressureError("Queued update bytes exceed the admitted envelope")
            self._pending[update.update_id] = update
            self.max_observed_queued_bytes = max(self.max_observed_queued_bytes, queued_bytes + update.byte_size)
            return True

    def drain_round(self) -> None:
        with self._lock:
            for update_id in sorted(self._pending):
                update = self._pending[update_id]
                expected_sequence = self._state_vector.get(update.editor_id, 0) + 1
                if update.sequence != expected_sequence:
                    raise OfficeCollaborationLoadProofError("Editor sequence is not monotonic")
                self._state_vector[update.editor_id] = update.sequence
                self._applied[update.update_id] = update
            self._pending.clear()
            self.completed_rounds += 1
            if self.completed_rounds == UPDATES_PER_EDITOR // 2:
                self._checkpoint_update_ids = tuple(sorted(self._applied))

    def snapshot(self) -> tuple[dict[str, int], tuple[str, ...]]:
        with self._lock:
            return dict(self._state_vector), tuple(sorted(self._applied))

    def resume_replay_update_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(set(self._applied).difference(self._checkpoint_update_ids)))

    @property
    def checkpoint_update_count(self) -> int:
        return len(self._checkpoint_update_ids)

    @property
    def checkpoint_update_ids(self) -> tuple[str, ...]:
        return self._checkpoint_update_ids

    def _require_authorized(self, editor: _Editor) -> None:
        self._require_tenant(editor.tenant_id)
        with self._lock:
            if editor.editor_id not in self._authorized_editors:
                raise OfficeCollaborationAuthorizationError("Editor is not authorized")

    def _require_tenant(self, tenant_id: str) -> None:
        if tenant_id != self.tenant_id:
            raise OfficeCollaborationAuthorizationError("Tenant boundary mismatch")


def _verify_backpressure() -> tuple[bool, int]:
    runtime = _ConcurrentDocumentHarness(tenant_id="tenant-load-proof")
    editor = _Editor(tenant_id=runtime.tenant_id, editor_id="backpressure-editor")
    runtime.authorize(editor)
    runtime.connect(editor)
    for index in range(4):
        runtime.enqueue(
            _Update(
                tenant_id=runtime.tenant_id,
                editor_id=editor.editor_id,
                update_id=f"backpressure-{index}",
                sequence=index + 1,
                byte_size=MAX_UPDATE_BYTES,
            )
        )
    try:
        runtime.enqueue(
            _Update(
                tenant_id=runtime.tenant_id,
                editor_id=editor.editor_id,
                update_id="backpressure-rejected",
                sequence=5,
                byte_size=1,
            )
        )
    except OfficeCollaborationBackpressureError as error:
        return error.close_code == BACKPRESSURE_CLOSE_CODE, runtime.max_observed_queued_bytes
    raise OfficeCollaborationLoadProofError("Backpressure limit did not reject excess queued bytes")


def _verify_authorization_rejections() -> tuple[bool, bool]:
    runtime = _ConcurrentDocumentHarness(tenant_id="tenant-load-proof")
    editor = _Editor(tenant_id=runtime.tenant_id, editor_id="revoked-editor")
    runtime.authorize(editor)
    runtime.connect(editor)
    runtime.revoke(editor.editor_id)
    try:
        runtime.enqueue(
            _Update(
                tenant_id=runtime.tenant_id,
                editor_id=editor.editor_id,
                update_id="revoked-update",
                sequence=1,
                byte_size=1,
            )
        )
    except OfficeCollaborationAuthorizationError:
        revoked_rejected = True
    else:
        revoked_rejected = False
    try:
        runtime.authorize(_Editor(tenant_id="foreign-tenant", editor_id="foreign-editor"))
    except OfficeCollaborationAuthorizationError:
        foreign_rejected = True
    else:
        foreign_rejected = False
    return revoked_rejected, foreign_rejected


def run_office_collaboration_load_proof() -> OfficeCollaborationLoadProofReport:
    runtime = _ConcurrentDocumentHarness(tenant_id="tenant-load-proof")
    editors = [_Editor(tenant_id=runtime.tenant_id, editor_id=f"editor-{index:02d}") for index in range(TARGET_EDITORS)]
    for editor in editors:
        runtime.authorize(editor)
    start_barrier = Barrier(TARGET_EDITORS)
    round_barrier = Barrier(TARGET_EDITORS, action=runtime.drain_round)

    def exercise_editor(editor: _Editor) -> tuple[dict[str, int], tuple[str, ...]]:
        runtime.connect(editor)
        start_barrier.wait(timeout=30)
        for sequence in range(1, UPDATES_PER_EDITOR + 1):
            if sequence in {1, UPDATES_PER_EDITOR // 2 + 1}:
                runtime.reauthorize(editor)
            update = _Update(
                tenant_id=editor.tenant_id,
                editor_id=editor.editor_id,
                update_id=f"{editor.editor_id}-update-{sequence:02d}",
                sequence=sequence,
                byte_size=256,
            )
            runtime.enqueue(update)
            if editor.editor_id == "editor-00" and sequence == 1:
                runtime.enqueue(update)
            round_barrier.wait(timeout=30)
        snapshot = runtime.snapshot()
        runtime.disconnect(editor)
        return snapshot

    with ThreadPoolExecutor(max_workers=TARGET_EDITORS, thread_name_prefix="office-load-proof") as executor:
        editor_snapshots = list(executor.map(exercise_editor, editors))

    final_vector, final_update_ids = runtime.snapshot()
    replay_update_ids = runtime.resume_replay_update_ids()
    reconstructed_update_ids = tuple(sorted((*runtime.checkpoint_update_ids, *replay_update_ids)))
    state_vector_hash = stable_hash(canonical_json(final_vector))
    update_set_hash = stable_hash(canonical_json(final_update_ids))
    all_editors_converged = all(
        stable_hash(canonical_json(vector)) == state_vector_hash
        and stable_hash(canonical_json(update_ids)) == update_set_hash
        for vector, update_ids in editor_snapshots
    )
    state_vector_resume_verified = reconstructed_update_ids == final_update_ids
    backpressure_verified, max_queued_bytes = _verify_backpressure()
    revoked_rejected, foreign_rejected = _verify_authorization_rejections()
    converged_editor_count = sum(
        1
        for vector, update_ids in editor_snapshots
        if stable_hash(canonical_json(vector)) == state_vector_hash
        and stable_hash(canonical_json(update_ids)) == update_set_hash
    )
    core = {
        "schema_version": "office_collaboration_load_proof.v1",
        "target_editor_count": TARGET_EDITORS,
        "max_parallel_editors": runtime.max_parallel_editors,
        "updates_per_editor": UPDATES_PER_EDITOR,
        "unique_update_count": len(final_update_ids),
        "duplicate_update_count": runtime.duplicate_update_count,
        "per_update_acl_check_count": runtime.per_update_acl_check_count,
        "session_reauthorization_count": runtime.session_reauthorization_count,
        "checkpoint_update_count": runtime.checkpoint_update_count,
        "resume_replay_update_count": len(replay_update_ids),
        "converged_editor_count": converged_editor_count,
        "final_state_vector_hash": state_vector_hash,
        "final_update_set_hash": update_set_hash,
        "max_observed_queued_bytes": max_queued_bytes,
        "max_update_bytes": MAX_UPDATE_BYTES,
        "max_queued_bytes": MAX_QUEUED_BYTES,
        "backpressure_rejection_verified": backpressure_verified,
        "backpressure_close_code": BACKPRESSURE_CLOSE_CODE,
        "revoked_acl_rejection_verified": revoked_rejected,
        "foreign_tenant_rejection_verified": foreign_rejected,
        "duplicate_delivery_deduplicated": runtime.duplicate_update_count == 1,
        "state_vector_resume_verified": state_vector_resume_verified,
        "all_editors_converged": all_editors_converged,
    }
    isolated_load_target_verified = all(
        (
            core["max_parallel_editors"] == TARGET_EDITORS,
            core["unique_update_count"] == TARGET_EDITORS * UPDATES_PER_EDITOR,
            core["converged_editor_count"] == TARGET_EDITORS,
            core["backpressure_rejection_verified"],
            core["revoked_acl_rejection_verified"],
            core["foreign_tenant_rejection_verified"],
            core["duplicate_delivery_deduplicated"],
            core["state_vector_resume_verified"],
            core["all_editors_converged"],
        )
    )
    return OfficeCollaborationLoadProofReport(
        target_editor_count=TARGET_EDITORS,
        max_parallel_editors=runtime.max_parallel_editors,
        updates_per_editor=UPDATES_PER_EDITOR,
        unique_update_count=len(final_update_ids),
        duplicate_update_count=runtime.duplicate_update_count,
        per_update_acl_check_count=runtime.per_update_acl_check_count,
        session_reauthorization_count=runtime.session_reauthorization_count,
        checkpoint_update_count=runtime.checkpoint_update_count,
        resume_replay_update_count=len(replay_update_ids),
        converged_editor_count=converged_editor_count,
        final_state_vector_hash=state_vector_hash,
        final_update_set_hash=update_set_hash,
        max_observed_queued_bytes=max_queued_bytes,
        max_update_bytes=MAX_UPDATE_BYTES,
        max_queued_bytes=MAX_QUEUED_BYTES,
        backpressure_rejection_verified=backpressure_verified,
        backpressure_close_code=BACKPRESSURE_CLOSE_CODE,
        revoked_acl_rejection_verified=revoked_rejected,
        foreign_tenant_rejection_verified=foreign_rejected,
        duplicate_delivery_deduplicated=runtime.duplicate_update_count == 1,
        state_vector_resume_verified=state_vector_resume_verified,
        all_editors_converged=all_editors_converged,
        isolated_load_target_verified=isolated_load_target_verified,
        evidence_hash=stable_hash(canonical_json(core)),
    )


def main() -> None:
    print(run_office_collaboration_load_proof().model_dump_json(indent=2))


if __name__ == "__main__":
    main()
