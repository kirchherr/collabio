import pytest
from pydantic import ValidationError

from suite.platform.legacy_sql_discovery import LegacySqlConnectorKind
from suite.platform.legacy_sql_discovery_intake import (
    LegacySqlApprovedHostProfile,
    LegacySqlDiscoveryIntakeGate,
    LegacySqlDiscoveryIntakeRequest,
    LegacySqlDiscoveryIntakeStatus,
)


def approved_host_profile(**updates: object) -> LegacySqlApprovedHostProfile:
    values: dict[str, object] = {
        "host_profile_ref": "legacy-host:sqlserver-prod",
        "connector_kind": LegacySqlConnectorKind.SQLSERVER,
        "connector_policy_ref": "policy:legacy-sql-connector",
        "policy_snapshot_hash": "sha256:policy-hash",
        "approved_egress_ref": "egress:legacy-sql-prod",
        "connection_secret_ref": "secret:legacy-sql-prod",
        "connection_fingerprint_hash": "sha256:legacy-sql-fingerprint",
    }
    values.update(updates)
    return LegacySqlApprovedHostProfile.model_validate(values)


def intake_request(**updates: object) -> LegacySqlDiscoveryIntakeRequest:
    values: dict[str, object] = {
        "tenant_id": "tenant-1",
        "module_id": "crm_erp",
        "source_system_ref": "legacy-sql:sqlserver-prod",
        "connector_kind": LegacySqlConnectorKind.SQLSERVER,
        "requested_by": "tenant-admin-1",
        "approval_reference": "approval:legacy-sql-discovery",
        "audit_chain_ref": "audit:legacy-sql-discovery",
        "host_profile_ref": "legacy-host:sqlserver-prod",
        "connector_policy_ref": "policy:legacy-sql-connector",
        "policy_snapshot_hash": "sha256:policy-hash",
    }
    values.update(updates)
    return LegacySqlDiscoveryIntakeRequest.model_validate(values)


def test_legacy_sql_discovery_intake_builds_worker_command_without_leaking_secret_ref() -> None:
    result = LegacySqlDiscoveryIntakeGate().evaluate(
        request=intake_request(),
        host_profile=approved_host_profile(),
    )

    assert result.command is not None
    assert result.command.request.tenant_id == "tenant-1"
    assert result.command.request.module_id == "crm_erp"
    assert result.command.connection_secret_ref == "secret:legacy-sql-prod"
    assert result.command.connection_fingerprint_hash == "sha256:legacy-sql-fingerprint"
    assert result.evidence.schema_version == "legacy_sql_discovery_intake.v1"
    assert result.evidence.status == LegacySqlDiscoveryIntakeStatus.READY_FOR_METADATA_WORKER
    assert result.evidence.metadata_worker_command_ready
    assert result.evidence.metadata_discovery_allowed
    assert result.evidence.connection_secret_ref_present
    assert not result.evidence.import_dry_run_allowed
    assert not result.evidence.import_write_allowed
    assert not result.evidence.raw_data_import_allowed
    assert not result.evidence.destructive_actions_allowed
    assert result.evidence.blocking_reasons == ()
    assert result.evidence.evidence_hash.startswith("sha256:")

    evidence_json = result.evidence.model_dump_json()
    assert "secret:legacy-sql-prod" not in evidence_json
    assert "dsn" not in evidence_json.lower()


def test_legacy_sql_discovery_intake_blocks_policy_hash_mismatch() -> None:
    result = LegacySqlDiscoveryIntakeGate().evaluate(
        request=intake_request(policy_snapshot_hash="sha256:other-policy"),
        host_profile=approved_host_profile(),
    )

    assert result.command is None
    assert result.evidence.status == LegacySqlDiscoveryIntakeStatus.BLOCKED
    assert not result.evidence.metadata_worker_command_ready
    assert not result.evidence.metadata_discovery_allowed
    assert result.evidence.blocking_reasons == ("connector_policy_hash_mismatch",)


def test_legacy_sql_discovery_intake_blocks_row_counts_when_host_profile_disallows_them() -> None:
    result = LegacySqlDiscoveryIntakeGate().evaluate(
        request=intake_request(),
        host_profile=approved_host_profile(row_count_estimates_allowed=False),
    )

    assert result.command is None
    assert result.evidence.status == LegacySqlDiscoveryIntakeStatus.BLOCKED
    assert result.evidence.blocking_reasons == ("row_count_estimates_not_allowed",)


def test_legacy_sql_discovery_intake_rejects_dsn_and_import_requests() -> None:
    with pytest.raises(ValidationError, match="secret references"):
        intake_request(dsn="sqlserver://user:pass@example.invalid/db")

    with pytest.raises(ValidationError, match="metadata discovery"):
        intake_request(raw_data_requested=True)

    with pytest.raises(ValidationError, match="metadata discovery"):
        intake_request(import_dry_run_requested=True)


def test_legacy_sql_host_profile_rejects_raw_access_or_import_capabilities() -> None:
    with pytest.raises(ValidationError, match="raw data"):
        approved_host_profile(raw_data_access_allowed=True)

    with pytest.raises(ValidationError, match="raw data"):
        approved_host_profile(import_write_allowed=True)
