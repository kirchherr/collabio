from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

import suite.operations.audit_worm_provider_acceptance as acceptance_module
from suite.kms.signing import AuditSigningAlgorithm
from suite.operations.audit_worm_provider_acceptance import (
    EXECUTION_CONFIRMATION,
    AuditWormDeleteDenialProof,
    AuditWormLiveInspection,
    AuditWormLiveInspectionResult,
    AuditWormProviderAcceptanceError,
    AuditWormProviderAcceptancePolicy,
    AwsAuditWormProviderProbe,
    accept_audit_worm_provider,
    _require_synthetic_non_content_events,
    build_acceptance_policy_hash,
    build_acceptance_report_hash,
    build_audit_worm_object_receipt_hash,
    main,
)
from suite.operations.audit_worm_snapshot import AuditSnapshotEvent
from suite.operations.audit_worm_verify import (
    AuditSigningTrustPolicy,
    AuditTrustedSigningKey,
    AuditWormSnapshotVerificationReport,
    build_audit_signing_trust_policy_hash,
)
from suite.operations.postgres_restore_drill import (
    PostgresRestoreDrillReport,
    build_postgres_restore_drill_report_hash,
)
from suite.storage.audit_worm_store import AuditWormObjectReceipt

TENANT_ID = "tenant-worm-provider-proof"
CHECKED_AT = datetime(2026, 8, 18, 10, 30, tzinfo=UTC)
GENERATED_AT = datetime(2026, 8, 18, 10, 0, tzinfo=UTC)
RETAIN_UNTIL = GENERATED_AT + timedelta(days=1)
BUCKET_ID = "collabio-disposable-worm-proof"
OBJECT_PREFIX = "audit-snapshots/v2/proof-tenant/"
OBJECT_KEY = OBJECT_PREFIX + "00000000000000000001/checkpoint.json"
VERSION_ID = "proof-version-id"
SIGNING_KEY_ID = "arn:aws:kms:eu-central-1:123456789012:key/signing-proof"
STORAGE_KEY_ID = "arn:aws:kms:eu-central-1:123456789012:key/storage-proof"
BUNDLE_BODY = b'{"schema_version":"audit_worm_snapshot_bundle.v2"}'
SYNTHETIC_PRINCIPAL = "synthetic-worm-provider-proof"


def _hash(value: str | bytes) -> str:
    encoded = value.encode("utf-8") if isinstance(value, str) else value
    return "sha256:" + sha256(encoded).hexdigest()


def _policy() -> AuditWormProviderAcceptancePolicy:
    receipt = _receipt()
    trust_policy = _trust_policy()
    restore_report = _restore_report()
    return AuditWormProviderAcceptancePolicy(
        policy_id="aws-worm-provider-proof-20260818",
        tenant_id_sha256=_hash(TENANT_ID),
        synthetic_principal_id_sha256=_hash(SYNTHETIC_PRINCIPAL),
        region="eu-central-1",
        bucket_id=BUCKET_ID,
        object_key_prefix=OBJECT_PREFIX,
        signing_provider_key_id_sha256=_hash(SIGNING_KEY_ID),
        storage_provider_key_id_sha256=_hash(STORAGE_KEY_ID),
        expected_bundle_hash=_hash(BUNDLE_BODY),
        receipt_hash=build_audit_worm_object_receipt_hash(receipt),
        trust_policy_hash=build_audit_signing_trust_policy_hash(trust_policy),
        restore_report_hash=restore_report.report_hash,
        minimum_retention_hours=24,
        maximum_retention_hours=24,
        valid_from_utc=CHECKED_AT - timedelta(hours=1),
        valid_until_utc=CHECKED_AT + timedelta(hours=1),
        provider_calls_authorized=True,
        exact_version_delete_denial_probe_authorized=True,
        synthetic_non_content_tenant_required=True,
        legal_hold_required_off=True,
    )


def _receipt() -> AuditWormObjectReceipt:
    return AuditWormObjectReceipt(
        tenant_id=TENANT_ID,
        checkpoint_id="audit-checkpoint-v2-proof",
        storage_provider="aws-s3",
        bucket_id=BUCKET_ID,
        object_key=OBJECT_KEY,
        object_version_id=VERSION_ID,
        storage_uri=f"s3://{BUCKET_ID}/{OBJECT_KEY}?versionId={VERSION_ID}",
        bundle_hash=_hash(BUNDLE_BODY),
        object_lock_mode="compliance",
        object_lock_retain_until_utc=RETAIN_UNTIL.isoformat().replace("+00:00", "Z"),
        legal_hold_enabled=False,
        server_side_encryption="aws:kms",
        storage_kms_key_ref=f"kms://{TENANT_ID}/confidential/v1",
        provider_storage_key_id=STORAGE_KEY_ID,
        put_request_id="put-request",
        get_request_id="get-request",
        head_request_id="head-request",
        readback_verified=True,
        object_lock_verified=True,
        encryption_verified=True,
    )


def _trust_policy() -> AuditSigningTrustPolicy:
    return AuditSigningTrustPolicy(
        policy_id="proof-trust-policy",
        tenant_id=TENANT_ID,
        issued_at_utc=GENERATED_AT - timedelta(days=1),
        trusted_keys=(
            AuditTrustedSigningKey(
                kms_key_ref=f"kms-sign://{TENANT_ID}/audit/v1",
                provider_profile="aws-kms",
                provider_key_id=SIGNING_KEY_ID,
                public_key_sha256=_hash("public-key"),
                allowed_signing_algorithms=(AuditSigningAlgorithm.ECDSA_SHA_256,),
                valid_from_utc=GENERATED_AT - timedelta(days=1),
                valid_until_utc=GENERATED_AT + timedelta(days=1),
            ),
        ),
    )


def _restore_report() -> PostgresRestoreDrillReport:
    state_hash = _hash("restored-state")
    draft = PostgresRestoreDrillReport(
        checked_at_utc="2026-08-18T10:20:00Z",
        backup_artifact_evidence_hash=_hash("backup-evidence"),
        backup_sha256=_hash("backup"),
        source_database_ref_hash=_hash("source-db"),
        target_database_ref_hash=_hash("target-db"),
        target_isolation_ref_hash=_hash("isolation"),
        source_snapshot_hash=_hash("source-snapshot"),
        target_snapshot_hash=_hash("target-snapshot"),
        source_state_manifest_hash=state_hash,
        target_state_manifest_hash=state_hash,
        migration_count=75,
        table_count=100,
        row_count_total=2,
        crm_atomic_write_controls_verified=True,
        source_target_state_verified=True,
        backup_integrity_verified=True,
        tasks_activities_write_controls_verified=True,
        time_tracking_write_controls_verified=True,
        productivity_pilot_admission_controls_verified=True,
        productivity_pilot_traffic_scope_controls_verified=True,
        productivity_pilot_start_authorization_controls_verified=True,
        target_isolation_verified=True,
        migration_catalog_verified=True,
        schema_inventory_verified=True,
        exact_row_counts_verified=True,
        rls_policy_controls_verified=True,
        service_roles_and_grants_verified=True,
        tenant_iam_controls_verified=True,
        append_only_audit_controls_verified=True,
        module_registry_controls_verified=True,
        source_object_controls_verified=True,
        metadata_only_evidence_verified=True,
        restore_ready=True,
        report_hash="sha256:" + ("0" * 64),
    )
    return draft.model_copy(update={"report_hash": build_postgres_restore_drill_report_hash(draft)})


def _verification(policy: AuditSigningTrustPolicy) -> AuditWormSnapshotVerificationReport:
    return AuditWormSnapshotVerificationReport(
        tenant_id=TENANT_ID,
        checkpoint_id="audit-checkpoint-v2-proof",
        through_sequence_number=1,
        event_count=1,
        bundle_hash=_hash(BUNDLE_BODY),
        manifest_hash=_hash("manifest"),
        events_hash=_hash("events"),
        trust_policy_id=policy.policy_id,
        trust_policy_hash=build_audit_signing_trust_policy_hash(policy),
        signing_key_ref=f"kms-sign://{TENANT_ID}/audit/v1",
        signing_key_version=1,
        provider_profile="aws-kms",
        provider_key_id_hash=_hash(SIGNING_KEY_ID),
        public_key_sha256=_hash("public-key"),
        signature_sha256=_hash("signature"),
        signed_at_utc=GENERATED_AT.isoformat().replace("+00:00", "Z"),
        retain_until_utc=RETAIN_UNTIL.isoformat().replace("+00:00", "Z"),
    )


class FakeProviderProbe:
    def __init__(self) -> None:
        self.inspect_calls = 0
        self.delete_calls = 0

    def inspect(
        self,
        *,
        receipt: AuditWormObjectReceipt,
        signing_provider_key_id: str,
        expected_bundle_hash: str,
    ) -> AuditWormLiveInspectionResult:
        self.inspect_calls += 1
        assert receipt.object_version_id == VERSION_ID
        assert signing_provider_key_id == SIGNING_KEY_ID
        assert expected_bundle_hash == _hash(BUNDLE_BODY)
        return AuditWormLiveInspectionResult(
            bundle_body=BUNDLE_BODY,
            evidence=AuditWormLiveInspection(
                retain_until_utc=RETAIN_UNTIL,
                storage_provider_key_id_sha256=_hash(STORAGE_KEY_ID),
                signing_provider_key_id_sha256=_hash(SIGNING_KEY_ID),
                signing_key_spec="ECC_NIST_P256",
                initial_get_request_id_sha256=_hash("initial-get"),
                head_request_id_sha256=_hash("head"),
                describe_key_request_id_sha256=_hash("describe"),
            ),
        )

    def prove_exact_version_delete_denied(
        self,
        *,
        receipt: AuditWormObjectReceipt,
        expected_bundle_hash: str,
    ) -> AuditWormDeleteDenialProof:
        self.delete_calls += 1
        assert receipt.object_version_id == VERSION_ID
        assert expected_bundle_hash == _hash(BUNDLE_BODY)
        return AuditWormDeleteDenialProof(
            delete_request_id_sha256=_hash("delete"),
            post_denial_get_request_id_sha256=_hash("post-get"),
        )


def test_acceptance_gate_binds_policy_offline_verification_restore_and_live_denial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy = _policy()
    trust_policy = _trust_policy()
    restore_report = _restore_report()
    probe = FakeProviderProbe()
    monkeypatch.setattr(
        acceptance_module,
        "verify_audit_worm_snapshot_bundle",
        lambda **_kwargs: _verification(trust_policy),
    )
    monkeypatch.setattr(
        acceptance_module,
        "_require_synthetic_non_content_bundle",
        lambda _body: _hash(SYNTHETIC_PRINCIPAL),
    )

    report = accept_audit_worm_provider(
        policy=policy,
        expected_policy_hash=build_acceptance_policy_hash(policy),
        receipt=_receipt(),
        restore_report=restore_report,
        expected_restore_report_hash=restore_report.report_hash,
        trust_policy=trust_policy,
        expected_trust_policy_hash=build_audit_signing_trust_policy_hash(trust_policy),
        expected_bundle_hash=_hash(BUNDLE_BODY),
        expected_tenant_id=TENANT_ID,
        execution_confirmation=EXECUTION_CONFIRMATION,
        provider_probe=probe,
        checked_at_utc=CHECKED_AT,
    )

    assert report.accepted is True
    assert report.report_hash == build_acceptance_report_hash(report)
    assert report.content_included is False
    assert report.signatures_included is False
    assert report.public_keys_included is False
    assert report.bucket_id_sha256 == _hash(BUCKET_ID)
    assert report.synthetic_principal_id_sha256 == _hash(SYNTHETIC_PRINCIPAL)
    assert probe.inspect_calls == 1
    assert probe.delete_calls == 1
    serialized = report.model_dump_json()
    assert TENANT_ID not in serialized
    assert BUCKET_ID not in serialized
    assert SIGNING_KEY_ID not in serialized
    assert STORAGE_KEY_ID not in serialized


def test_acceptance_gate_rejects_unpinned_or_unconfirmed_execution_before_provider_calls() -> None:
    policy = _policy()
    trust_policy = _trust_policy()
    restore_report = _restore_report()
    probe = FakeProviderProbe()
    common = {
        "policy": policy,
        "receipt": _receipt(),
        "restore_report": restore_report,
        "expected_restore_report_hash": restore_report.report_hash,
        "trust_policy": trust_policy,
        "expected_trust_policy_hash": build_audit_signing_trust_policy_hash(trust_policy),
        "expected_bundle_hash": _hash(BUNDLE_BODY),
        "expected_tenant_id": TENANT_ID,
        "provider_probe": probe,
        "checked_at_utc": CHECKED_AT,
    }

    with pytest.raises(AuditWormProviderAcceptanceError, match="execution_confirmation_missing"):
        accept_audit_worm_provider(
            **common,
            expected_policy_hash=build_acceptance_policy_hash(policy),
            execution_confirmation="not-approved",
        )
    with pytest.raises(AuditWormProviderAcceptanceError, match="acceptance_policy_hash_mismatch"):
        accept_audit_worm_provider(
            **common,
            expected_policy_hash=_hash("different-policy"),
            execution_confirmation=EXECUTION_CONFIRMATION,
        )

    assert probe.inspect_calls == 0
    assert probe.delete_calls == 0


def test_acceptance_policy_rejects_long_retention_or_ambiguous_prefix() -> None:
    values = _policy().model_dump()
    values["maximum_retention_hours"] = 169
    with pytest.raises(ValidationError):
        AuditWormProviderAcceptancePolicy.model_validate(values)

    values = _policy().model_dump()
    values["object_key_prefix"] = "audit-snapshots/v2/proof-tenant"
    with pytest.raises(ValidationError, match="end with a slash"):
        AuditWormProviderAcceptancePolicy.model_validate(values)


def test_synthetic_non_content_scope_is_enforced() -> None:
    event = AuditSnapshotEvent(
        event_id="event-proof",
        schema_version="audit_event.v1",
        sequence_number=1,
        tenant_id=TENANT_ID,
        user_id=SYNTHETIC_PRINCIPAL,
        event_type="audit.worm_provider_acceptance.synthetic",
        metadata={"purpose": "audit_worm_provider_acceptance", "synthetic": True},
        previous_event_hash="sha256:" + ("0" * 64),
        event_hash=_hash("event-proof"),
        recorded_at_utc="2026-08-18T10:00:00Z",
    )

    assert _require_synthetic_non_content_events(
        generated_by=SYNTHETIC_PRINCIPAL,
        events=(event,),
    ) == _hash(SYNTHETIC_PRINCIPAL)

    with pytest.raises(AuditWormProviderAcceptanceError, match="synthetic_non_content_scope_invalid"):
        _require_synthetic_non_content_events(
            generated_by=SYNTHETIC_PRINCIPAL,
            events=(event.model_copy(update={"source_object_ids": ["forbidden-object"]}),),
        )

class AccessDeniedError(RuntimeError):
    def __init__(self) -> None:
        self.response = {
            "Error": {"Code": "AccessDenied"},
            "ResponseMetadata": {"HTTPStatusCode": 403, "RequestId": "delete-denied-request"},
        }


class FakeS3Client:
    def __init__(self) -> None:
        self.get_count = 0
        self.delete_call: dict[str, object] = {}

    def get_object(self, **kwargs: object) -> Mapping[str, Any]:
        self.get_count += 1
        assert kwargs == {
            "Bucket": BUCKET_ID,
            "Key": OBJECT_KEY,
            "VersionId": VERSION_ID,
            "ChecksumMode": "ENABLED",
        }
        return {
            "Body": BUNDLE_BODY,
            "ResponseMetadata": {"RequestId": f"get-{self.get_count}"},
        }

    def head_object(self, **kwargs: object) -> Mapping[str, Any]:
        assert kwargs["VersionId"] == VERSION_ID
        return {
            "ObjectLockMode": "COMPLIANCE",
            "ObjectLockRetainUntilDate": RETAIN_UNTIL,
            "ObjectLockLegalHoldStatus": "OFF",
            "ServerSideEncryption": "aws:kms",
            "SSEKMSKeyId": STORAGE_KEY_ID,
            "ResponseMetadata": {"RequestId": "head-request"},
        }

    def delete_object(self, **kwargs: object) -> Mapping[str, Any]:
        self.delete_call = dict(kwargs)
        raise AccessDeniedError


class FakeKmsClient:
    def describe_key(self, **kwargs: object) -> Mapping[str, Any]:
        assert kwargs == {"KeyId": SIGNING_KEY_ID}
        return {
            "KeyMetadata": {
                "Arn": SIGNING_KEY_ID,
                "Enabled": True,
                "KeyState": "Enabled",
                "KeyUsage": "SIGN_VERIFY",
                "KeySpec": "ECC_NIST_P256",
            },
            "ResponseMetadata": {"RequestId": "describe-request"},
        }


def test_aws_probe_uses_only_exact_version_delete_and_proves_post_denial_readback() -> None:
    s3_client = FakeS3Client()
    probe = AwsAuditWormProviderProbe(s3_client=s3_client, kms_client=FakeKmsClient())

    inspection = probe.inspect(
        receipt=_receipt(),
        signing_provider_key_id=SIGNING_KEY_ID,
        expected_bundle_hash=_hash(BUNDLE_BODY),
    )
    deletion = probe.prove_exact_version_delete_denied(
        receipt=_receipt(),
        expected_bundle_hash=_hash(BUNDLE_BODY),
    )

    assert inspection.evidence.object_lock_mode == "compliance"
    assert deletion.exact_version_delete_denied is True
    assert s3_client.delete_call == {
        "Bucket": BUCKET_ID,
        "Key": OBJECT_KEY,
        "VersionId": VERSION_ID,
    }
    assert s3_client.get_count == 2


def test_provider_acceptance_cli_is_default_off_and_compose_service_is_hardened(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "not-read-while-disabled.json"
    arguments = [
        "--policy",
        str(missing),
        "--expected-policy-hash",
        _hash("policy"),
        "--receipt",
        str(missing),
        "--restore-report",
        str(missing),
        "--expected-restore-report-hash",
        _hash("restore"),
        "--trust-policy",
        str(missing),
        "--expected-trust-policy-hash",
        _hash("trust"),
        "--expected-bundle-hash",
        _hash("bundle"),
        "--expected-tenant-id",
        TENANT_ID,
        "--execution-confirmation",
        EXECUTION_CONFIRMATION,
    ]
    assert main(arguments, env={}) == 1
    assert "acceptance_failed" in capsys.readouterr().out

    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    runbook = Path("docs/operations/AUDIT_WORM_SNAPSHOTS.md").read_text(encoding="utf-8")
    block = compose.split("  audit-worm-provider-acceptance:", maxsplit=1)[1].split(
        "\n  object-storage-profile-check:", maxsplit=1
    )[0]
    assert 'profiles: ["audit-worm-provider-acceptance"]' in block
    assert "SUITE_AUDIT_WORM_PROVIDER_ACCEPTANCE_ENABLED" in block
    assert "read_only: true" in block
    assert "no-new-privileges:true" in block
    assert "ports:" not in block
    assert "SUITE_S3_ACCESS_KEY_ID" not in block
    assert EXECUTION_CONFIRMATION in runbook
