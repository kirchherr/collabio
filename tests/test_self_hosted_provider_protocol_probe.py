from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any

import pytest

from suite.kms.signing import AuditSigningProviderInspection
from suite.operations.self_hosted_provider_protocol_probe import (
    SIGNING_PROVIDER_KEY_ID,
    SelfHostedProviderProtocolProbeError,
    build_self_hosted_provider_protocol_probe_report_hash,
    main,
    probe_self_hosted_provider_protocols,
)


class FakeS3Client:
    def list_buckets(self) -> Mapping[str, Any]:
        return {
            "Buckets": [{"Name": "must-not-appear-in-report"}],
            "Owner": {"ID": "must-not-appear-in-report"},
            "ResponseMetadata": {
                "HTTPStatusCode": 200,
                "RequestId": "rgw-request-123",
            },
        }


class FakeSigningKeyInspector:
    def inspect_provider_key(self, *, provider_key_id: str) -> AuditSigningProviderInspection:
        assert provider_key_id == SIGNING_PROVIDER_KEY_ID
        return AuditSigningProviderInspection(
            provider_key_id=provider_key_id,
            key_type="ecdsa-p256",
            key_version=1,
            public_key_der=b"synthetic-public-key-der",
            request_id="openbao-request-123",
        )


def _sha256_ref(value: bytes) -> str:
    return "sha256:" + sha256(value).hexdigest()


def _status_bytes(observed_at: datetime, **overrides: object) -> bytes:
    value: dict[str, object] = {
        "schema_version": "self_hosted_provider_development_status.v1",
        "observed_at_utc": observed_at.isoformat().replace("+00:00", "Z"),
        "environment": "development-single-physical-host",
        "production_ha_claim": False,
        "tenant_content_included": False,
        "secrets_included": False,
        "cluster": "collabio-provider",
        "versions": {
            "kubernetes": "v1.36.4",
            "rook": "v1.20.7",
            "ceph": "20.2.4",
            "openbao_chart": "0.29.4",
            "openbao": "2.6.2",
        },
        "topology": {
            "kubernetes_nodes": 3,
            "simulated_failure_domains": 3,
            "physical_hosts": 1,
            "openbao_raft_voters": 3,
            "rgw_instances": 2,
        },
        "controls": {
            "kubernetes_secrets_encrypted": True,
            "kubernetes_audit_level": "Metadata",
            "network_policy_controller": "k3s-kube-router",
            "provider_endpoints_public": False,
            "ceph_health": "HEALTH_OK",
            "ceph_msgr2_encryption": True,
            "ceph_osd_encryption": True,
            "openbao_tls": True,
            "openbao_dev_mode": False,
            "openbao_audit_devices": 2,
            "openbao_storage_independent_from_ceph": True,
            "storage_and_signing_keys_distinct": True,
            "storage_key_exportable": False,
        },
    }
    value.update(overrides)
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")


def test_protocol_probe_reports_only_hashes_counts_and_closed_boundaries() -> None:
    checked_at = datetime(2026, 9, 5, 8, 0, tzinfo=UTC)
    status_bytes = _status_bytes(checked_at - timedelta(minutes=1))

    report = probe_self_hosted_provider_protocols(
        status_bytes=status_bytes,
        expected_status_sha256=_sha256_ref(status_bytes),
        runtime_image_id_sha256="sha256:" + "a" * 64,
        tls_ca_bytes=b"synthetic-development-ca",
        s3_client=FakeS3Client(),
        signing_key_inspector=FakeSigningKeyInspector(),
        checked_at_utc=checked_at,
    )

    assert report.ready is True
    assert report.visible_bucket_count == 1
    assert report.kubernetes_nodes == 3
    assert report.openbao_raft_voters == 3
    assert report.rgw_instances == 2
    assert report.ceph_health == "HEALTH_OK"
    assert report.authenticated_rgw_read_only_call_verified is True
    assert report.authenticated_openbao_key_read_verified is True
    assert report.bucket_names_included is False
    assert report.object_versions_read is False
    assert report.signature_operation_attempted is False
    assert report.write_attempted is False
    assert report.delete_attempted is False
    assert report.tenant_content_included is False
    assert report.secrets_included is False
    assert report.production_evidence_admissible is False
    assert report.production_ha_claim is False
    assert report.report_sha256 == build_self_hosted_provider_protocol_probe_report_hash(report)

    encoded = report.model_dump_json()
    assert "must-not-appear-in-report" not in encoded
    assert "rgw-request-123" not in encoded
    assert "openbao-request-123" not in encoded
    assert SIGNING_PROVIDER_KEY_ID not in encoded


@pytest.mark.parametrize(
    ("status_bytes", "expected_hash", "error"),
    (
        (
            _status_bytes(datetime(2026, 9, 5, 7, 0, tzinfo=UTC)),
            "sha256:" + "0" * 64,
            "provider_status_hash_mismatch",
        ),
        (
            _status_bytes(
                datetime(2026, 9, 5, 7, 0, tzinfo=UTC),
                production_ha_claim=True,
            ),
            None,
            "provider_status_invalid",
        ),
        (
            _status_bytes(
                datetime(2026, 9, 5, 7, 0, tzinfo=UTC),
                versions={
                    "kubernetes": "v1.36.5",
                    "rook": "v1.20.7",
                    "ceph": "20.2.4",
                    "openbao_chart": "0.29.4",
                    "openbao": "2.6.2",
                },
            ),
            None,
            "provider_status_invalid",
        ),
    ),
)
def test_protocol_probe_rejects_unbound_or_overclaimed_status(
    status_bytes: bytes,
    expected_hash: str | None,
    error: str,
) -> None:
    with pytest.raises(SelfHostedProviderProtocolProbeError, match=error):
        probe_self_hosted_provider_protocols(
            status_bytes=status_bytes,
            expected_status_sha256=expected_hash or _sha256_ref(status_bytes),
            runtime_image_id_sha256="sha256:" + "a" * 64,
            tls_ca_bytes=b"synthetic-development-ca",
            s3_client=FakeS3Client(),
            signing_key_inspector=FakeSigningKeyInspector(),
            checked_at_utc=datetime(2026, 9, 5, 7, 1, tzinfo=UTC),
        )


def test_protocol_probe_rejects_stale_status_before_provider_calls() -> None:
    checked_at = datetime(2026, 9, 5, 8, 0, tzinfo=UTC)
    status_bytes = _status_bytes(checked_at - timedelta(minutes=31))

    with pytest.raises(SelfHostedProviderProtocolProbeError, match="provider_status_not_fresh"):
        probe_self_hosted_provider_protocols(
            status_bytes=status_bytes,
            expected_status_sha256=_sha256_ref(status_bytes),
            runtime_image_id_sha256="sha256:" + "a" * 64,
            tls_ca_bytes=b"synthetic-development-ca",
            s3_client=FakeS3Client(),
            signing_key_inspector=FakeSigningKeyInspector(),
            checked_at_utc=checked_at,
        )


def test_protocol_probe_cli_fails_closed_without_enablement(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(env={}) == 1
    output = capsys.readouterr().out
    assert "self_hosted_provider_protocol_probe_failure.v1" in output
    assert '"ready":false' in output
    assert '"production_evidence_admissible":false' in output
    assert '"write_attempted":false' in output
    assert '"delete_attempted":false' in output
