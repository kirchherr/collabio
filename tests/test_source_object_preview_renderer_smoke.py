import os
from dataclasses import dataclass
from pathlib import Path

import pytest

from suite.persistence.migrator import apply_migrations
from suite.platform.source_object_preview_decisions import PgSourceObjectPreviewDecisionLedger
from suite.platform.source_object_preview_renderer import PgSourceObjectPreviewRendererEvidenceStore
from suite.platform.source_object_preview_renderer_release_gate import (
    JsonlSourceObjectPreviewRendererReleaseGateEvidenceStore,
)
from suite.platform.source_object_preview_renderer_smoke import (
    build_source_object_preview_renderer_api_smoke_report_hash,
    build_source_object_preview_renderer_release_gate_smoke_report_hash,
    exit_code_for_release_gate_smoke_report,
    exit_code_for_report,
    run_source_object_preview_renderer_api_smoke_from_env,
    run_source_object_preview_renderer_release_gate_smoke_from_env,
)


@dataclass(frozen=True)
class LiveDatabase:
    migration_dsn: str
    app_dsn: str
    audit_dsn: str


def env_or_skip(name: str) -> str:
    value = os.environ.get(name)
    if value is None:
        pytest.skip(f"{name} is not configured")
    return value


@pytest.fixture(scope="module")
def live_database() -> LiveDatabase:
    migration_dsn = env_or_skip("SUITE_MIGRATION_DATABASE_DSN")
    app_dsn = env_or_skip("SUITE_DATABASE_DSN")
    audit_dsn = env_or_skip("SUITE_AUDIT_DATABASE_DSN")
    apply_migrations(migration_dsn)
    return LiveDatabase(migration_dsn=migration_dsn, app_dsn=app_dsn, audit_dsn=audit_dsn)


def test_preview_renderer_api_smoke_creates_postgres_evidence_and_references_drill_hash(
    live_database: LiveDatabase,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SUITE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SUITE_AUTH_MODE", "dev")
    monkeypatch.setenv("SUITE_AUDIT_LOGGER_BACKEND", "postgres")
    monkeypatch.setenv("SUITE_AUDIT_DATABASE_DSN", live_database.audit_dsn)
    monkeypatch.setenv("SUITE_SOURCE_PREVIEW_DECISION_LEDGER_BACKEND", "postgres")
    monkeypatch.setenv("SUITE_SOURCE_PREVIEW_DECISION_LEDGER_DSN", live_database.app_dsn)
    monkeypatch.setenv("SUITE_SOURCE_PREVIEW_RENDERER_EVIDENCE_STORE_BACKEND", "postgres")
    monkeypatch.setenv("SUITE_SOURCE_PREVIEW_RENDERER_EVIDENCE_STORE_DSN", live_database.app_dsn)
    monkeypatch.setenv("SUITE_PREVIEW_RENDERER_SMOKE_TENANT_ID", "tenant-demo")
    monkeypatch.setenv("SUITE_PREVIEW_RENDERER_DRILL_TENANT_IDS", "tenant-demo")

    report = run_source_object_preview_renderer_api_smoke_from_env()

    assert report.schema_version == "source_object_preview_renderer_api_smoke_report.v1"
    assert report.tenant_id == "tenant-demo"
    assert report.source_object_id == "doc-1"
    assert report.smoke_passed is True
    assert exit_code_for_report(report) == 0
    assert report.recovery_tenant_status == "ready"
    assert report.recovery_metadata_only_ok is True
    assert report.renderer_sandbox_evidence_ref == f"renderer-sandbox:{report.renderer_sandbox_evidence_hash}"
    assert report.preview_decision_ledger_ref == f"preview-decision-ledger:{report.preview_decision_evidence_hash}"
    assert report.recovery_drill_report_hash.startswith("sha256:")
    assert report.release_restore_evidence_ref == f"preview-renderer-recovery-drill:{report.recovery_drill_report_hash}"
    assert report.evidence_hash == build_source_object_preview_renderer_api_smoke_report_hash(report)
    assert "Board pack draft source content" not in report.model_dump_json()
    assert "preview renderer api smoke metadata-only" not in report.model_dump_json()

    renderer_store = PgSourceObjectPreviewRendererEvidenceStore(database_dsn=live_database.app_dsn)
    renderer_evidence = renderer_store.get(
        tenant_id=report.tenant_id,
        evidence_hash=report.renderer_sandbox_evidence_hash,
    )
    assert renderer_evidence.renderer_sandbox_evidence_ref == report.renderer_sandbox_evidence_ref
    assert renderer_evidence.content_included is False
    assert renderer_evidence.content_rendered is False

    decision_ledger = PgSourceObjectPreviewDecisionLedger(database_dsn=live_database.app_dsn)
    decision_evidence = decision_ledger.get(
        tenant_id=report.tenant_id,
        evidence_hash=report.preview_decision_evidence_hash,
    )
    assert decision_evidence.renderer_sandbox_evidence_ref == report.renderer_sandbox_evidence_ref
    assert decision_evidence.renderer_sandbox_evidence_verified is True
    assert decision_evidence.content_included is False
    assert decision_evidence.content_release_allowed is False


def test_preview_renderer_release_gate_smoke_persists_gate_evidence_for_compose_path(
    live_database: LiveDatabase,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("SUITE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SUITE_AUTH_MODE", "dev")
    monkeypatch.setenv("SUITE_AUDIT_LOGGER_BACKEND", "postgres")
    monkeypatch.setenv("SUITE_AUDIT_DATABASE_DSN", live_database.audit_dsn)
    monkeypatch.setenv("SUITE_SOURCE_PREVIEW_DECISION_LEDGER_BACKEND", "postgres")
    monkeypatch.setenv("SUITE_SOURCE_PREVIEW_DECISION_LEDGER_DSN", live_database.app_dsn)
    monkeypatch.setenv("SUITE_SOURCE_PREVIEW_RENDERER_EVIDENCE_STORE_BACKEND", "postgres")
    monkeypatch.setenv("SUITE_SOURCE_PREVIEW_RENDERER_EVIDENCE_STORE_DSN", live_database.app_dsn)
    monkeypatch.setenv("SUITE_SOURCE_PREVIEW_RENDERER_RELEASE_GATE_STORE_BACKEND", "jsonl")
    monkeypatch.setenv("SUITE_PREVIEW_RENDERER_SMOKE_TENANT_ID", "tenant-demo")
    monkeypatch.setenv("SUITE_PREVIEW_RENDERER_DRILL_TENANT_IDS", "tenant-demo")

    report = run_source_object_preview_renderer_release_gate_smoke_from_env()

    assert report.schema_version == "source_object_preview_renderer_release_gate_smoke_report.v1"
    assert report.tenant_id == "tenant-demo"
    assert report.release_gate_status == "ready"
    assert report.renderer_connection_allowed is True
    assert report.viewer_connection_allowed is True
    assert report.content_release_workflow_allowed is True
    assert report.release_gate_persisted is True
    assert report.api_smoke_report_ref == f"preview-renderer-api-smoke:{report.api_smoke_report_hash}"
    assert report.recovery_drill_report_ref == f"preview-renderer-recovery-drill:{report.recovery_drill_report_hash}"
    assert report.release_gate_evidence_ref == f"preview-renderer-release-gate:{report.release_gate_evidence_hash}"
    assert report.evidence_hash == build_source_object_preview_renderer_release_gate_smoke_report_hash(report)
    assert exit_code_for_release_gate_smoke_report(report) == 0
    assert "Board pack draft source content" not in report.model_dump_json()
    assert "preview renderer api smoke metadata-only" not in report.model_dump_json()

    gate_store = JsonlSourceObjectPreviewRendererReleaseGateEvidenceStore(
        path=tmp_path / "preview_renderer_release_gates.jsonl"
    )
    gate = gate_store.get(tenant_id=report.tenant_id, evidence_hash=report.release_gate_evidence_hash)
    assert gate.api_smoke_report_hash == report.api_smoke_report_hash
    assert gate.recovery_drill_report_hash == report.recovery_drill_report_hash
    assert gate.renderer_connection_allowed is True
