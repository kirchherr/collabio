from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from suite.ai_control_plane.audit import canonical_json, stable_hash

PREVIEW_RENDERER_API_SMOKE_SCHEMA_VERSION = "source_object_preview_renderer_api_smoke_report.v1"


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


def build_source_object_preview_renderer_api_smoke_report_hash(
    report: SourceObjectPreviewRendererApiSmokeReport,
) -> str:
    return stable_hash(canonical_json(report.model_dump(mode="json", exclude={"evidence_hash"})))
