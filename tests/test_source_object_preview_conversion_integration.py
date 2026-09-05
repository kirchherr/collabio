from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from suite.persistence.migrator import apply_migrations
from suite.platform.source_object_preview_conversion import (
    PgPreviewConversionExecutionGateStore,
    PreviewConversionExecutionGateEvidence,
    PreviewConversionGateStatus,
    build_preview_conversion_execution_gate,
)


def _env_or_skip(name: str) -> str:
    value = os.environ.get(name)
    if value is None:
        pytest.skip(f"{name} is not configured")
    return value


def _gate(*, tenant_id: str, network_egress_denied: bool = True) -> PreviewConversionExecutionGateEvidence:
    return build_preview_conversion_execution_gate(
        tenant_id=tenant_id,
        worker_image_ref="registry.example.com/collabio/preview-renderer@sha256:" + ("1" * 64),
        sandbox_runtime_class="runsc",
        sandbox_runtime_evidence_hash="sha256:" + ("2" * 64),
        malware_scanner_profile_ref="clamav:1.4",
        malware_scanner_evidence_hash="sha256:" + ("3" * 64),
        cdr_profile_ref="cdr:office-preview.v1",
        cdr_evidence_hash="sha256:" + ("4" * 64),
        pdf_validator_profile_ref="qpdf-pdfinfo:12.3.2",
        pdf_validator_evidence_hash="sha256:" + ("5" * 64),
        font_baseline_hash="sha256:" + ("6" * 64),
        backup_restore_evidence_hash="sha256:" + ("7" * 64),
        viewer_origin="https://preview.example.test",
        viewer_csp_evidence_hash="sha256:" + ("8" * 64),
        network_egress_denied=network_egress_denied,
        evaluated_at_utc=datetime(2026, 8, 7, 10, 0, tzinfo=UTC),
    )


def test_postgres_execution_gate_store_persists_ready_and_blocked_evidence_with_rls() -> None:
    migration_dsn = _env_or_skip("SUITE_MIGRATION_DATABASE_DSN")
    app_dsn = _env_or_skip("SUITE_DATABASE_DSN")
    apply_migrations(migration_dsn)
    store = PgPreviewConversionExecutionGateStore(database_dsn=app_dsn)
    tenant_id = f"tenant-preview-conversion-{uuid4().hex}"

    ready = store.append(_gate(tenant_id=tenant_id))
    blocked = store.append(_gate(tenant_id=tenant_id, network_egress_denied=False))

    assert ready.gate_status == PreviewConversionGateStatus.READY
    assert blocked.gate_status == PreviewConversionGateStatus.BLOCKED
    assert store.get(tenant_id=tenant_id, evidence_hash=ready.evidence_hash) == ready
    assert store.get(tenant_id=tenant_id, evidence_hash=blocked.evidence_hash) == blocked
    with pytest.raises(KeyError):
        store.get(tenant_id="tenant-preview-conversion-other", evidence_hash=ready.evidence_hash)
