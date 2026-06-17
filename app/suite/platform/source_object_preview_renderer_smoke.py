from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from uuid import uuid4

from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict

from suite.ai_control_plane.audit import canonical_json, stable_hash
from suite.platform.source_object_preview_renderer_operations import (
    SourceObjectPreviewRendererRecoveryDrillReport,
    SourceObjectPreviewRendererRecoveryTenantResult,
    SourceObjectPreviewRendererRecoveryTenantStatus,
    run_source_object_preview_renderer_recovery_drill_from_env,
)

PREVIEW_RENDERER_API_SMOKE_SCHEMA_VERSION = "source_object_preview_renderer_api_smoke_report.v1"
PREVIEW_RENDERER_RELEASE_GATE_SMOKE_SCHEMA_VERSION = "source_object_preview_renderer_release_gate_smoke_report.v1"
DEFAULT_SMOKE_TENANT_ID = "tenant-demo"
DEFAULT_SMOKE_USER_ID = "preview-renderer-smoke"
DEFAULT_SMOKE_SOURCE_OBJECT_ID = "doc-1"
DEFAULT_SMOKE_SOURCE_VERSION_ID = "v1"
DEFAULT_SMOKE_PREVIEW_SLOT_ID = "office.document.preview.metadata"
DEFAULT_SMOKE_PREVIEW_POLICY_ID = "preview-policy.document.metadata-first.v1"


class SourceObjectPreviewRendererApiSmokeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = PREVIEW_RENDERER_API_SMOKE_SCHEMA_VERSION
    tenant_id: str
    source_object_id: str
    source_version_id: str
    preview_slot_id: str
    preview_policy_id: str
    parser_sanitizer_evidence_ref: str
    backup_coverage_evidence_ref: str
    restore_evidence_ref: str
    renderer_sandbox_evidence_ref: str
    renderer_sandbox_evidence_hash: str
    preview_decision_evidence_hash: str
    preview_decision_ledger_ref: str
    renderer_run_audit_event_id: str
    preview_decision_audit_event_id: str
    recovery_drill_report_hash: str
    release_restore_evidence_ref: str
    recovery_tenant_status: str
    recovery_metadata_only_ok: bool
    smoke_passed: bool
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str


class SourceObjectPreviewRendererReleaseGateSmokeReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = PREVIEW_RENDERER_RELEASE_GATE_SMOKE_SCHEMA_VERSION
    tenant_id: str
    api_smoke_report_hash: str
    api_smoke_report_ref: str
    recovery_drill_report_hash: str
    recovery_drill_report_ref: str
    release_gate_evidence_hash: str
    release_gate_evidence_ref: str
    release_gate_status: str
    renderer_connection_allowed: bool
    viewer_connection_allowed: bool
    content_release_workflow_allowed: bool
    release_gate_persisted: bool
    checked_by: str
    checked_at_utc: datetime
    evidence_hash: str


def run_source_object_preview_renderer_api_smoke_from_env(
    environ: Mapping[str, str] | None = None,
) -> SourceObjectPreviewRendererApiSmokeReport:
    env = os.environ if environ is None else environ
    from main import build_app

    client = TestClient(build_app())
    return run_source_object_preview_renderer_api_smoke(
        client=client,
        tenant_id=env.get("SUITE_PREVIEW_RENDERER_SMOKE_TENANT_ID", DEFAULT_SMOKE_TENANT_ID),
        user_id=env.get("SUITE_PREVIEW_RENDERER_SMOKE_USER_ID", DEFAULT_SMOKE_USER_ID),
        source_object_id=env.get("SUITE_PREVIEW_RENDERER_SMOKE_SOURCE_OBJECT_ID", DEFAULT_SMOKE_SOURCE_OBJECT_ID),
        source_version_id=env.get("SUITE_PREVIEW_RENDERER_SMOKE_SOURCE_VERSION_ID", DEFAULT_SMOKE_SOURCE_VERSION_ID),
        preview_slot_id=env.get("SUITE_PREVIEW_RENDERER_SMOKE_PREVIEW_SLOT_ID", DEFAULT_SMOKE_PREVIEW_SLOT_ID),
        preview_policy_id=env.get("SUITE_PREVIEW_RENDERER_SMOKE_PREVIEW_POLICY_ID", DEFAULT_SMOKE_PREVIEW_POLICY_ID),
        checked_by=env.get("SUITE_PREVIEW_RENDERER_SMOKE_CHECKED_BY", "preview-renderer-smoke"),
        environ=env,
    )


def run_source_object_preview_renderer_release_gate_smoke_from_env(
    environ: Mapping[str, str] | None = None,
) -> SourceObjectPreviewRendererReleaseGateSmokeReport:
    env = os.environ if environ is None else environ
    from main import build_app

    client = TestClient(build_app())
    return run_source_object_preview_renderer_release_gate_smoke(
        client=client,
        tenant_id=env.get("SUITE_PREVIEW_RENDERER_SMOKE_TENANT_ID", DEFAULT_SMOKE_TENANT_ID),
        user_id=env.get("SUITE_PREVIEW_RENDERER_SMOKE_USER_ID", DEFAULT_SMOKE_USER_ID),
        source_object_id=env.get("SUITE_PREVIEW_RENDERER_SMOKE_SOURCE_OBJECT_ID", DEFAULT_SMOKE_SOURCE_OBJECT_ID),
        source_version_id=env.get("SUITE_PREVIEW_RENDERER_SMOKE_SOURCE_VERSION_ID", DEFAULT_SMOKE_SOURCE_VERSION_ID),
        preview_slot_id=env.get("SUITE_PREVIEW_RENDERER_SMOKE_PREVIEW_SLOT_ID", DEFAULT_SMOKE_PREVIEW_SLOT_ID),
        preview_policy_id=env.get("SUITE_PREVIEW_RENDERER_SMOKE_PREVIEW_POLICY_ID", DEFAULT_SMOKE_PREVIEW_POLICY_ID),
        checked_by=env.get("SUITE_PREVIEW_RENDERER_SMOKE_CHECKED_BY", "preview-renderer-smoke"),
        environ=env,
    )


def run_source_object_preview_renderer_api_smoke(
    *,
    client: TestClient,
    tenant_id: str,
    user_id: str,
    source_object_id: str,
    source_version_id: str,
    preview_slot_id: str,
    preview_policy_id: str,
    checked_by: str,
    environ: Mapping[str, str],
) -> SourceObjectPreviewRendererApiSmokeReport:
    report, _ = _run_source_object_preview_renderer_api_smoke_with_drill(
        client=client,
        tenant_id=tenant_id,
        user_id=user_id,
        source_object_id=source_object_id,
        source_version_id=source_version_id,
        preview_slot_id=preview_slot_id,
        preview_policy_id=preview_policy_id,
        checked_by=checked_by,
        environ=environ,
    )
    return report


def run_source_object_preview_renderer_release_gate_smoke(
    *,
    client: TestClient,
    tenant_id: str,
    user_id: str,
    source_object_id: str,
    source_version_id: str,
    preview_slot_id: str,
    preview_policy_id: str,
    checked_by: str,
    environ: Mapping[str, str],
) -> SourceObjectPreviewRendererReleaseGateSmokeReport:
    from suite.platform.source_object_preview_renderer_release_gate import (
        build_default_source_object_preview_renderer_release_gate_evidence_store,
        build_source_object_preview_renderer_release_gate,
        source_object_preview_renderer_release_gate_evidence_ref,
    )

    api_smoke_report, drill_report = _run_source_object_preview_renderer_api_smoke_with_drill(
        client=client,
        tenant_id=tenant_id,
        user_id=user_id,
        source_object_id=source_object_id,
        source_version_id=source_version_id,
        preview_slot_id=preview_slot_id,
        preview_policy_id=preview_policy_id,
        checked_by=checked_by,
        environ=environ,
    )
    gate = build_source_object_preview_renderer_release_gate(
        tenant_id=tenant_id,
        api_smoke_report=api_smoke_report,
        recovery_drill_report=drill_report,
    )
    gate_store = build_default_source_object_preview_renderer_release_gate_evidence_store(environ=environ)
    persisted_gate = gate_store.append(gate)
    draft = SourceObjectPreviewRendererReleaseGateSmokeReport(
        tenant_id=tenant_id,
        api_smoke_report_hash=api_smoke_report.evidence_hash,
        api_smoke_report_ref=f"preview-renderer-api-smoke:{api_smoke_report.evidence_hash}",
        recovery_drill_report_hash=drill_report.evidence_hash,
        recovery_drill_report_ref=f"preview-renderer-recovery-drill:{drill_report.evidence_hash}",
        release_gate_evidence_hash=persisted_gate.evidence_hash,
        release_gate_evidence_ref=source_object_preview_renderer_release_gate_evidence_ref(persisted_gate),
        release_gate_status=persisted_gate.gate_status,
        renderer_connection_allowed=persisted_gate.renderer_connection_allowed,
        viewer_connection_allowed=persisted_gate.viewer_connection_allowed,
        content_release_workflow_allowed=persisted_gate.content_release_workflow_allowed,
        release_gate_persisted=True,
        checked_by=checked_by,
        checked_at_utc=datetime.now(UTC),
        evidence_hash="sha256:" + "0" * 64,
    )
    return draft.model_copy(
        update={"evidence_hash": build_source_object_preview_renderer_release_gate_smoke_report_hash(draft)}
    )


def _run_source_object_preview_renderer_api_smoke_with_drill(
    *,
    client: TestClient,
    tenant_id: str,
    user_id: str,
    source_object_id: str,
    source_version_id: str,
    preview_slot_id: str,
    preview_policy_id: str,
    checked_by: str,
    environ: Mapping[str, str],
) -> tuple[SourceObjectPreviewRendererApiSmokeReport, SourceObjectPreviewRendererRecoveryDrillReport]:
    suffix = uuid4().hex
    parser_sanitizer_evidence_ref = f"parser-sanitizer:preview-renderer-api-smoke:{suffix}"
    backup_coverage_evidence_ref = f"backup:preview-renderer-api-smoke:{suffix}"
    restore_evidence_ref = f"restore-drill:preview-renderer-api-smoke:{suffix}"
    headers = {
        "X-Tenant-Id": tenant_id,
        "X-User-Id": user_id,
        "X-Role-Ids": "knowledge-worker",
        "X-Readable-Object-Ids": source_object_id,
    }

    renderer_response = client.post(
        f"/v1/source-objects/{source_object_id}/versions/{source_version_id}/preview-renderer-runs",
        headers=headers,
        json={
            "preview_slot_id": preview_slot_id,
            "preview_policy_id": preview_policy_id,
            "parser_sanitizer_evidence_ref": parser_sanitizer_evidence_ref,
            "backup_coverage_evidence_ref": backup_coverage_evidence_ref,
            "restore_evidence_ref": restore_evidence_ref,
            "reason": "preview renderer api smoke metadata-only renderer evidence",
        },
    )
    if renderer_response.status_code != 200:
        raise RuntimeError("preview renderer API smoke failed to create renderer evidence")
    renderer_body = renderer_response.json()

    decision_response = client.post(
        f"/v1/source-objects/{source_object_id}/versions/{source_version_id}/preview-decisions",
        headers=headers,
        json={
            "preview_slot_id": preview_slot_id,
            "preview_policy_id": preview_policy_id,
            "reason": "preview renderer api smoke metadata-only decision evidence",
            "parser_sanitizer_evidence_ref": parser_sanitizer_evidence_ref,
            "renderer_sandbox_evidence_ref": renderer_body["renderer_sandbox_evidence_ref"],
            "backup_coverage_evidence_ref": backup_coverage_evidence_ref,
            "restore_evidence_ref": restore_evidence_ref,
            "human_confirmation_reference": f"approval:preview-renderer-api-smoke:{suffix}",
        },
    )
    if decision_response.status_code != 200:
        raise RuntimeError("preview renderer API smoke failed to create decision evidence")
    decision_body = decision_response.json()

    drill_report = run_source_object_preview_renderer_recovery_drill_from_env(
        {
            **dict(environ),
            "SUITE_PREVIEW_RENDERER_DRILL_TENANT_IDS": tenant_id,
        }
    )
    tenant_result = _tenant_result(drill_report=drill_report, tenant_id=tenant_id)
    smoke_passed = (
        tenant_result.status == SourceObjectPreviewRendererRecoveryTenantStatus.READY
        and tenant_result.metadata_only_recovery_ok
        and renderer_body["renderer_sandbox_evidence_ref"] in tenant_result.recovered_renderer_refs
    )
    draft = SourceObjectPreviewRendererApiSmokeReport(
        tenant_id=tenant_id,
        source_object_id=source_object_id,
        source_version_id=source_version_id,
        preview_slot_id=preview_slot_id,
        preview_policy_id=preview_policy_id,
        parser_sanitizer_evidence_ref=parser_sanitizer_evidence_ref,
        backup_coverage_evidence_ref=backup_coverage_evidence_ref,
        restore_evidence_ref=restore_evidence_ref,
        renderer_sandbox_evidence_ref=renderer_body["renderer_sandbox_evidence_ref"],
        renderer_sandbox_evidence_hash=renderer_body["renderer_sandbox_evidence_hash"],
        preview_decision_evidence_hash=decision_body["preview_decision_evidence_hash"],
        preview_decision_ledger_ref=decision_body["decision_ledger_ref"],
        renderer_run_audit_event_id=renderer_body["audit_event_id"],
        preview_decision_audit_event_id=decision_body["audit_event_id"],
        recovery_drill_report_hash=drill_report.evidence_hash,
        release_restore_evidence_ref=f"preview-renderer-recovery-drill:{drill_report.evidence_hash}",
        recovery_tenant_status=tenant_result.status,
        recovery_metadata_only_ok=tenant_result.metadata_only_recovery_ok,
        smoke_passed=smoke_passed,
        checked_by=checked_by,
        checked_at_utc=datetime.now(UTC),
        evidence_hash="sha256:" + "0" * 64,
    )
    report = draft.model_copy(
        update={"evidence_hash": build_source_object_preview_renderer_api_smoke_report_hash(draft)}
    )
    return report, drill_report


def build_source_object_preview_renderer_api_smoke_report_hash(
    report: SourceObjectPreviewRendererApiSmokeReport,
) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def build_source_object_preview_renderer_release_gate_smoke_report_hash(
    report: SourceObjectPreviewRendererReleaseGateSmokeReport,
) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))


def exit_code_for_report(report: SourceObjectPreviewRendererApiSmokeReport) -> int:
    return 0 if report.smoke_passed else 1


def exit_code_for_release_gate_smoke_report(report: SourceObjectPreviewRendererReleaseGateSmokeReport) -> int:
    return 0 if report.release_gate_persisted and report.content_release_workflow_allowed else 1


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Run the source object preview renderer API smoke fixture.")
    parser.add_argument("--once", action="store_true", help="Run one metadata-only smoke fixture and exit.")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print the metadata-only smoke report.")
    parser.add_argument("--api-only", action="store_true", help="Emit only the API smoke report without release gate.")
    args = parser.parse_args(argv)
    del args.once

    if args.api_only:
        api_report = run_source_object_preview_renderer_api_smoke_from_env()
        print(json.dumps(api_report.model_dump(mode="json"), indent=2 if args.pretty else None, sort_keys=True))
        raise SystemExit(exit_code_for_report(api_report))

    release_gate_report = run_source_object_preview_renderer_release_gate_smoke_from_env()
    print(json.dumps(release_gate_report.model_dump(mode="json"), indent=2 if args.pretty else None, sort_keys=True))
    raise SystemExit(exit_code_for_release_gate_smoke_report(release_gate_report))


def _tenant_result(
    *,
    drill_report: SourceObjectPreviewRendererRecoveryDrillReport,
    tenant_id: str,
) -> SourceObjectPreviewRendererRecoveryTenantResult:
    for result in drill_report.tenant_results:
        if result.tenant_id == tenant_id:
            return result
    raise RuntimeError("preview renderer API smoke drill report did not include tenant")
