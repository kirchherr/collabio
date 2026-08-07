from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from main import app
from suite.platform.source_object_preview_adapter import (
    DEFAULT_PREVIEW_ADAPTER_ID,
    CanonicalPdfSourceObjectPreviewAdapter,
    PreviewAdapterRoute,
    SourceObjectPreviewAdapterDryRunInput,
    build_default_source_object_preview_adapter_registry,
    build_source_object_preview_adapter_plan_hash,
    source_object_preview_renderer_release_gate_is_current,
)
from suite.platform.source_object_preview_renderer_release_gate import (
    InMemorySourceObjectPreviewRendererReleaseGateEvidenceStore,
    SourceObjectPreviewRendererReleaseGateEvidence,
    SourceObjectPreviewRendererReleaseGateStatus,
    build_source_object_preview_renderer_release_gate_hash,
)
from suite.storage.source_objects import SourceObjectType

ZERO_HASH = "sha256:" + ("0" * 64)
DEMO_HEADERS = {
    "X-Tenant-Id": "tenant-demo",
    "X-User-Id": "user-demo",
    "X-Role-Ids": "knowledge-worker",
    "X-Readable-Object-Ids": "doc-1,mail-1",
}


def test_canonical_pdf_adapter_separates_preview_from_future_wopi_editing() -> None:
    adapter = CanonicalPdfSourceObjectPreviewAdapter()

    assert adapter.descriptor.adapter_id == DEFAULT_PREVIEW_ADAPTER_ID
    assert adapter.descriptor.architecture == "canonical_pdf_preview"
    assert adapter.descriptor.converter_engine_family == "libreoffice_headless"
    assert adapter.descriptor.viewer_engine_family == "pdfjs"
    assert adapter.descriptor.collaboration_protocol == "none"
    assert adapter.descriptor.future_editing_protocol == "wopi"
    assert adapter.descriptor.engine_execution_enabled is False
    assert adapter.descriptor.content_input_allowed is False
    assert "gvisor_or_microvm_isolation_required" in adapter.descriptor.security_controls
    assert "current_tenant_content_preview_policy_required" in adapter.descriptor.security_controls
    assert "viewer_direct_storage_access_forbidden" in adapter.descriptor.security_controls


@pytest.mark.parametrize(
    ("mime_type", "expected_route"),
    [
        (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            PreviewAdapterRoute.ISOLATED_OFFICE_TO_PDF,
        ),
        ("application/vnd.oasis.opendocument.text", PreviewAdapterRoute.ISOLATED_OFFICE_TO_PDF),
        ("application/pdf", PreviewAdapterRoute.DIRECT_PDF_VIEWER),
        ("text/plain", PreviewAdapterRoute.ISOLATED_OFFICE_TO_PDF),
    ],
)
def test_canonical_pdf_adapter_builds_metadata_only_routes(
    mime_type: str,
    expected_route: PreviewAdapterRoute,
) -> None:
    plan = CanonicalPdfSourceObjectPreviewAdapter().dry_run(_input(mime_type=mime_type))

    assert plan.supported is True
    assert plan.route == expected_route
    assert plan.target_media_type == "application/pdf"
    assert plan.content_accessed is False
    assert plan.source_bytes_included is False
    assert plan.renderer_invoked is False
    assert plan.viewer_session_created is False
    assert plan.output_generated is False
    assert plan.output_persisted is False
    assert plan.external_network_allowed is False
    assert plan.wopi_session_created is False
    assert plan.plan_hash == build_source_object_preview_adapter_plan_hash(plan)


def test_canonical_pdf_adapter_blocks_mail_and_macro_enabled_formats() -> None:
    adapter = CanonicalPdfSourceObjectPreviewAdapter()

    mail_plan = adapter.dry_run(
        _input(
            source_object_type=SourceObjectType.MAIL,
            mime_type="message/rfc822",
        )
    )
    macro_plan = adapter.dry_run(_input(mime_type="application/vnd.ms-word.document.macroenabled.12"))

    assert mail_plan.route == PreviewAdapterRoute.UNSUPPORTED
    assert mail_plan.blocking_reasons == ("source_object_type_not_supported",)
    assert macro_plan.route == PreviewAdapterRoute.UNSUPPORTED
    assert macro_plan.blocking_reasons == ("source_mime_type_not_supported",)


def test_preview_adapter_input_rejects_content_fields() -> None:
    payload = _input().model_dump(mode="json")
    payload["content"] = "must never enter the adapter dry-run"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        SourceObjectPreviewAdapterDryRunInput.model_validate(payload)


def test_preview_adapter_request_rejects_non_hex_gate_hash() -> None:
    client = TestClient(app)

    response = client.post(
        "/v1/source-objects/doc-1/versions/v1/preview-adapter-dry-runs",
        headers=DEMO_HEADERS,
        json={
            "adapter_id": DEFAULT_PREVIEW_ADAPTER_ID,
            "preview_slot_id": "office.document.preview.metadata",
            "preview_policy_id": "preview-policy.document.metadata-first.v1",
            "renderer_release_gate_evidence_hash": "sha256:" + ("z" * 64),
            "reason": "invalid evidence must fail validation",
        },
    )

    assert response.status_code == 422


def test_preview_adapter_registry_fails_closed_for_unknown_configuration() -> None:
    with pytest.raises(ValueError, match="selected source object preview adapter is not registered"):
        build_default_source_object_preview_adapter_registry({"SUITE_SOURCE_PREVIEW_ADAPTER_ID": "unreviewed-adapter"})


def test_preview_adapter_endpoint_requires_fresh_release_gate_and_returns_no_content() -> None:
    client = TestClient(app)
    previous_store = app.state.source_object_preview_renderer_release_gate_store
    store = InMemorySourceObjectPreviewRendererReleaseGateEvidenceStore()
    gate = _ready_release_gate(tenant_id="tenant-demo")
    store.append(gate)
    app.state.source_object_preview_renderer_release_gate_store = store
    starting_event_count = len(app.state.audit_logger.events)
    reason = "verify canonical PDF adapter wiring"

    try:
        response = client.post(
            "/v1/source-objects/doc-1/versions/v1/preview-adapter-dry-runs",
            headers=DEMO_HEADERS,
            json={
                "adapter_id": DEFAULT_PREVIEW_ADAPTER_ID,
                "preview_slot_id": "office.document.preview.metadata",
                "preview_policy_id": "preview-policy.document.metadata-first.v1",
                "renderer_release_gate_evidence_hash": gate.evidence_hash,
                "reason": reason,
            },
        )
    finally:
        app.state.source_object_preview_renderer_release_gate_store = previous_store

    assert response.status_code == 200
    body = response.json()
    assert body["result_contract"] == "metadata_only_preview_adapter_wiring_dry_run"
    assert body["content_included"] is False
    assert body["execution_performed"] is False
    assert body["evidence_persisted_outside_audit"] is False
    assert body["plan"]["adapter_id"] == DEFAULT_PREVIEW_ADAPTER_ID
    assert body["plan"]["route"] == "isolated_office_to_pdf"
    assert body["plan"]["supported"] is True
    assert body["plan"]["content_accessed"] is False
    assert body["plan"]["renderer_invoked"] is False
    assert body["plan"]["viewer_session_created"] is False
    assert body["plan"]["wopi_session_created"] is False
    assert reason not in json.dumps(body)
    assert "Board pack draft source content" not in json.dumps(body)

    new_events = app.state.audit_logger.events[starting_event_count:]
    assert [event.event_type for event in new_events] == [
        "source_object.metadata_detail.read",
        "source_object.preview_adapter_dry_run.recorded",
    ]
    assert new_events[-1].metadata["plan_hash"] == body["plan"]["plan_hash"]
    assert new_events[-1].metadata["content_included"] is False
    assert new_events[-1].metadata["reason_hash"] == body["reason_hash"]
    assert "reason" not in new_events[-1].metadata


def test_preview_adapter_endpoint_blocks_missing_release_gate_before_adapter_use() -> None:
    client = TestClient(app)
    previous_store = app.state.source_object_preview_renderer_release_gate_store
    app.state.source_object_preview_renderer_release_gate_store = (
        InMemorySourceObjectPreviewRendererReleaseGateEvidenceStore()
    )

    try:
        response = client.post(
            "/v1/source-objects/doc-1/versions/v1/preview-adapter-dry-runs",
            headers=DEMO_HEADERS,
            json={
                "adapter_id": DEFAULT_PREVIEW_ADAPTER_ID,
                "preview_slot_id": "office.document.preview.metadata",
                "preview_policy_id": "preview-policy.document.metadata-first.v1",
                "renderer_release_gate_evidence_hash": "sha256:" + ("8" * 64),
                "reason": "missing gate must block",
            },
        )
    finally:
        app.state.source_object_preview_renderer_release_gate_store = previous_store

    assert response.status_code == 409
    assert response.json()["detail"] == "preview renderer release gate was not found"


def test_preview_adapter_rejects_stale_gate_evidence() -> None:
    now = datetime.now(UTC)
    stale_gate = _ready_release_gate(tenant_id="tenant-demo", checked_at_utc=now - timedelta(hours=25))

    assert (
        source_object_preview_renderer_release_gate_is_current(
            gate=stale_gate,
            checked_at_utc=now,
        )
        is False
    )


def test_preview_adapter_module_has_no_content_or_execution_clients() -> None:
    source = Path("app/suite/platform/source_object_preview_adapter.py").read_text(encoding="utf-8")

    for forbidden in (
        "import subprocess",
        "import httpx",
        "import requests",
        "import boto3",
        "source_object_content_bytes",
        "S3CompatibleSourceObjectContentStore",
    ):
        assert forbidden not in source


def _input(
    *,
    source_object_type: SourceObjectType = SourceObjectType.DOCUMENT,
    mime_type: str = "text/plain",
) -> SourceObjectPreviewAdapterDryRunInput:
    return SourceObjectPreviewAdapterDryRunInput(
        tenant_id="tenant-demo",
        source_object_id="doc-1",
        source_version_id="v1",
        source_object_type=source_object_type,
        source_mime_type=mime_type,
        source_manifest_hash="sha256:" + ("1" * 64),
        source_content_hash="sha256:" + ("2" * 64),
        source_acl_version=1,
        preview_slot_id="office.document.preview.metadata",
        preview_policy_id="preview-policy.document.metadata-first.v1",
        renderer_release_gate_evidence_hash="sha256:" + ("3" * 64),
    )


def _ready_release_gate(
    *,
    tenant_id: str,
    checked_at_utc: datetime | None = None,
) -> SourceObjectPreviewRendererReleaseGateEvidence:
    checked_at = checked_at_utc or datetime.now(UTC)
    draft = SourceObjectPreviewRendererReleaseGateEvidence(
        tenant_id=tenant_id,
        api_smoke_report_hash="sha256:" + ("4" * 64),
        recovery_drill_report_hash="sha256:" + ("5" * 64),
        api_smoke_checked_at_utc=checked_at,
        recovery_drill_checked_at_utc=checked_at,
        evaluated_at_utc=checked_at,
        freshness_window_hours=24,
        api_smoke_fresh=True,
        recovery_drill_fresh=True,
        api_smoke_passed=True,
        recovery_drill_ready=True,
        recovery_drill_bound=True,
        tenant_ready=True,
        metadata_only_boundary_verified=True,
        renderer_connection_allowed=True,
        viewer_connection_allowed=True,
        content_release_workflow_allowed=True,
        blocking_reasons=(),
        gate_status=SourceObjectPreviewRendererReleaseGateStatus.READY,
        evidence_hash=ZERO_HASH,
    )
    return draft.model_copy(update={"evidence_hash": build_source_object_preview_renderer_release_gate_hash(draft)})
