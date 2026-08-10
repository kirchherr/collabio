from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from main import app
from suite.platform.office_edit_adapter import (
    DEFAULT_GENOFFICE_EVALUATION_POLICY_PATH,
    DOCX_MIME_TYPE,
    GENOFFICE_DOCX_EVALUATION_ADAPTER_ID,
    GENOFFICE_UPSTREAM_COMMIT,
    GenOfficeDocxQuickEditEvaluationAdapter,
    GenOfficeEvaluationPolicy,
    OfficeEditAdapterEvaluationInput,
    OfficeEditAdapterEvaluationPlan,
    OfficeEditAdapterEvaluationResponse,
    OfficeEditEvaluationRoute,
    build_default_office_edit_adapter_registry,
    build_office_edit_adapter_plan_hash,
    load_genoffice_evaluation_policy,
)
from suite.storage.source_objects import SourceObjectType

DEMO_HEADERS = {
    "X-Tenant-Id": "tenant-demo",
    "X-User-Id": "user-demo",
    "X-Role-Ids": "knowledge-worker",
    "X-Readable-Object-Ids": "doc-1,mail-1",
}


def test_genoffice_policy_pins_narrow_source_scope_and_keeps_import_closed() -> None:
    policy = load_genoffice_evaluation_policy(DEFAULT_GENOFFICE_EVALUATION_POLICY_PATH)

    assert policy.status == "evaluation_only"
    assert policy.adapter_id == GENOFFICE_DOCX_EVALUATION_ADAPTER_ID
    assert policy.upstream.commit == GENOFFICE_UPSTREAM_COMMIT
    assert policy.upstream.root_license_spdx == "Apache-2.0"
    assert policy.upstream.enterprise_tree == "ee/**"
    assert policy.upstream.enterprise_tree_included is False
    assert policy.upstream.trademark_use_allowed is False
    assert policy.upstream.mutable_ref_allowed is False
    assert policy.source_scope.selected_import_candidates == ("packages/docx-engine/**",)
    assert "ee/**" in policy.source_scope.prohibited_scopes
    assert "packages/ai-provider/**" in policy.source_scope.prohibited_scopes
    assert policy.source_scope.source_import_allowed is False
    assert policy.execution.content_access_allowed is False
    assert policy.execution.engine_execution_allowed is False
    assert policy.execution.candidate_write_allowed is False
    assert policy.execution.cloud_ai_allowed is False
    assert policy.execution.production_use_allowed is False


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (("upstream", "commit", "main"), "exact reviewed commit"),
        (("upstream", "enterprise_tree_included", True), "enterprise source tree"),
        (("source_scope", "source_import_allowed", True), "source import remains blocked"),
        (("execution", "content_access_allowed", True), "opened an unreviewed boundary"),
        (("execution", "cloud_ai_allowed", True), "opened an unreviewed boundary"),
    ],
)
def test_genoffice_policy_rejects_open_or_mutable_boundaries(
    mutation: tuple[str, str, object],
    message: str,
) -> None:
    payload = json.loads(DEFAULT_GENOFFICE_EVALUATION_POLICY_PATH.read_text(encoding="utf-8"))
    section, field, value = mutation
    changed = copy.deepcopy(payload)
    changed[section][field] = value

    with pytest.raises(ValidationError, match=message):
        GenOfficeEvaluationPolicy.model_validate(changed)


def test_office_edit_adapter_marks_only_docx_as_isolated_spike_candidate() -> None:
    policy = load_genoffice_evaluation_policy(DEFAULT_GENOFFICE_EVALUATION_POLICY_PATH)
    adapter = GenOfficeDocxQuickEditEvaluationAdapter(policy=policy)

    eligible = adapter.evaluate(_input(policy_hash=adapter.descriptor.policy_hash))
    unsupported = adapter.evaluate(
        _input(
            policy_hash=adapter.descriptor.policy_hash,
            mime_type="application/pdf",
        )
    )

    assert eligible.route == OfficeEditEvaluationRoute.DOCX_QUICK_EDIT_ISOLATED_SPIKE
    assert eligible.eligible_for_isolated_spike is True
    assert eligible.blocking_reasons == ()
    assert eligible.upstream_commit == GENOFFICE_UPSTREAM_COMMIT
    assert eligible.plan_hash == build_office_edit_adapter_plan_hash(eligible)
    assert unsupported.route == OfficeEditEvaluationRoute.UNSUPPORTED
    assert unsupported.eligible_for_isolated_spike is False
    assert unsupported.blocking_reasons == ("source_mime_type_not_supported",)

    for plan in (eligible, unsupported):
        assert plan.source_imported is False
        assert plan.content_accessed is False
        assert plan.source_bytes_included is False
        assert plan.engine_invoked is False
        assert plan.editor_session_created is False
        assert plan.candidate_version_written is False
        assert plan.persistent_state_written is False
        assert plan.external_network_allowed is False
        assert plan.cloud_ai_invoked is False
        assert plan.wopi_session_created is False
        assert plan.production_editing_allowed is False


def test_office_edit_plan_and_response_reject_open_or_drifted_contracts() -> None:
    registry = build_default_office_edit_adapter_registry()
    adapter = registry.selected(requested_adapter_id=GENOFFICE_DOCX_EVALUATION_ADAPTER_ID)
    plan = adapter.evaluate(_input(policy_hash=registry.policy_hash))
    plan_payload = plan.model_dump(mode="json")
    plan_payload["access_checked"] = False

    with pytest.raises(ValidationError, match="requires access and policy checks"):
        OfficeEditAdapterEvaluationPlan.model_validate(plan_payload)

    response_payload = {
        "plan": plan.model_dump(mode="json"),
        "source_detail_audit_event_id": "audit-detail-1",
        "audit_event_id": "audit-evaluation-1",
        "reason_hash": "sha256:" + ("3" * 64),
        "execution_performed": True,
    }
    with pytest.raises(ValidationError, match="opened a content or execution boundary"):
        OfficeEditAdapterEvaluationResponse.model_validate(response_payload)


def test_office_edit_adapter_rejects_content_fields_and_unknown_configuration() -> None:
    registry = build_default_office_edit_adapter_registry()
    payload = _input(policy_hash=registry.policy_hash).model_dump(mode="json")
    payload["content"] = "must never enter the office edit evaluation"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        OfficeEditAdapterEvaluationInput.model_validate(payload)
    with pytest.raises(ValueError, match="selected office edit adapter is not registered"):
        build_default_office_edit_adapter_registry({"SUITE_OFFICE_EDIT_ADAPTER_ID": "unreviewed-office-editor"})


def test_office_edit_endpoint_is_acl_checked_metadata_only_and_non_executing() -> None:
    client = TestClient(app)
    starting_event_count = len(app.state.audit_logger.events)
    reason = "evaluate the pinned DOCX quick edit source scope"

    response = client.post(
        "/v1/source-objects/doc-1/versions/v1/office-edit-adapter-evaluations",
        headers=DEMO_HEADERS,
        json={
            "adapter_id": GENOFFICE_DOCX_EVALUATION_ADAPTER_ID,
            "expected_policy_hash": app.state.office_edit_adapter_registry.policy_hash,
            "reason": reason,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["result_contract"] == "metadata_only_office_edit_adapter_evaluation"
    assert body["content_included"] is False
    assert body["source_import_performed"] is False
    assert body["execution_performed"] is False
    assert body["editor_session_created"] is False
    assert body["candidate_version_written"] is False
    assert body["evidence_persisted_outside_audit"] is False
    assert body["plan"]["upstream_commit"] == GENOFFICE_UPSTREAM_COMMIT
    assert body["plan"]["route"] == "unsupported"
    assert body["plan"]["blocking_reasons"] == ["source_mime_type_not_supported"]
    assert body["plan"]["content_accessed"] is False
    assert body["plan"]["engine_invoked"] is False
    assert reason not in json.dumps(body)
    assert "Board pack draft source content" not in json.dumps(body)

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert [event.event_type for event in new_events] == [
        "source_object.metadata_detail.read",
        "source_object.office_edit_adapter_evaluation.recorded",
    ]
    assert new_events[-1].metadata["content_included"] is False
    assert new_events[-1].metadata["source_imported"] is False
    assert new_events[-1].metadata["reason_hash"] == body["reason_hash"]
    assert "reason" not in new_events[-1].metadata


def test_office_edit_endpoint_fails_closed_on_policy_drift() -> None:
    client = TestClient(app)
    reason = "stale client policy must fail closed"
    starting_event_count = len(app.state.audit_logger.events)

    response = client.post(
        "/v1/source-objects/doc-1/versions/v1/office-edit-adapter-evaluations",
        headers=DEMO_HEADERS,
        json={
            "adapter_id": GENOFFICE_DOCX_EVALUATION_ADAPTER_ID,
            "expected_policy_hash": "sha256:" + ("9" * 64),
            "reason": reason,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "office edit adapter policy hash mismatch"
    new_events = app.state.audit_logger.events[starting_event_count:]
    assert [event.event_type for event in new_events] == [
        "source_object.metadata_detail.read",
        "source_object.office_edit_adapter_evaluation.rejected",
    ]
    assert new_events[-1].metadata["rejection_reason"] == "policy_hash_mismatch"
    assert new_events[-1].metadata["content_included"] is False
    assert reason not in json.dumps(new_events[-1].metadata)


def test_office_edit_endpoint_does_not_cross_tenant_boundary() -> None:
    client = TestClient(app)
    headers = {
        **DEMO_HEADERS,
        "X-Readable-Object-Ids": "doc-other",
    }

    response = client.post(
        "/v1/source-objects/doc-other/versions/v1/office-edit-adapter-evaluations",
        headers=headers,
        json={
            "adapter_id": GENOFFICE_DOCX_EVALUATION_ADAPTER_ID,
            "expected_policy_hash": app.state.office_edit_adapter_registry.policy_hash,
            "reason": "cross-tenant metadata must remain invisible",
        },
    )

    assert response.status_code == 404


def test_office_edit_adapter_module_has_no_content_execution_or_provider_clients() -> None:
    source = Path("app/suite/platform/office_edit_adapter.py").read_text(encoding="utf-8")

    for forbidden in (
        "import subprocess",
        "import httpx",
        "import requests",
        "import boto3",
        "S3CompatibleSourceObjectContentStore",
        "source_object_content_bytes",
        "suite.ai_control_plane.gateway",
    ):
        assert forbidden not in source


def test_backup_policy_reserves_complete_future_office_edit_state() -> None:
    policy = json.loads(Path("docs/operations/backup_failover_policy.json").read_text(encoding="utf-8"))
    office_domain = next(domain for domain in policy["continuity_domains"] if domain["domain_id"] == "office_documents")

    assert {
        "draft journals",
        "draft checkpoints",
        "saved versions",
        "candidate versions",
        "business records",
        "WORM evidence records",
        "collaboration manifests",
        "append-only office edit receipts",
        "office edit policy and engine manifests",
        "engine source commit and worker image digest bindings",
        "signed-original and derived-version signature state",
        "office edit recovery drill reports",
    }.issubset(set(office_domain["state_artifacts"]))


def test_runtime_image_contains_fail_closed_genoffice_policy() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")

    assert (
        "docs/operations/genoffice_evaluation_policy.json "
        "./docs/operations/genoffice_evaluation_policy.json" in dockerfile
    )


def _input(
    *,
    policy_hash: str,
    source_object_type: SourceObjectType = SourceObjectType.DOCUMENT,
    mime_type: str = DOCX_MIME_TYPE,
) -> OfficeEditAdapterEvaluationInput:
    return OfficeEditAdapterEvaluationInput(
        tenant_id="tenant-demo",
        source_object_id="doc-1",
        source_version_id="v1",
        source_object_type=source_object_type,
        source_mime_type=mime_type,
        source_manifest_hash="sha256:" + ("1" * 64),
        source_content_hash="sha256:" + ("2" * 64),
        source_acl_version=1,
        policy_hash=policy_hash,
    )
