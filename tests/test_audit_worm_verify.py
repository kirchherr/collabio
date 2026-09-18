import base64
import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa, utils

from suite.ai_control_plane.audit import InMemoryAuditLogger
from suite.ai_control_plane.models import UserContext
from suite.kms.signing import AuditCheckpointSignature, AuditSigningAlgorithm
from suite.operations.audit_worm_snapshot import (
    AuditSnapshotEvent,
    AuditWormSnapshotBundle,
    AuditWormSnapshotManifest,
)
from suite.operations.audit_worm_verify import (
    AuditSigningTrustPolicy,
    AuditTrustedSigningKey,
    AuditWormVerificationError,
    build_audit_signing_trust_policy_hash,
    main,
    verify_audit_worm_snapshot_bundle,
)

TENANT_ID = "tenant-audit"
GENERATED_AT = datetime(2026, 8, 17, 10, 0, tzinfo=UTC)
PROVIDER_KEY_ID = "arn:aws:kms:eu-central-1:123456789012:key/audit-signing"


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _hash(value: bytes) -> str:
    return "sha256:" + sha256(value).hexdigest()


def _events() -> tuple[AuditSnapshotEvent, ...]:
    logger = InMemoryAuditLogger()
    user = UserContext(user_id="security-admin", tenant_id=TENANT_ID)
    first = logger.record(
        user_context=user,
        event_type="audit.first",
        input_text="sensitive prompt",
        metadata={"purpose": "security_audit"},
    )
    second = logger.record(
        user_context=user,
        event_type="audit.second",
        output_text="sensitive output",
        source_object_ids=["restricted-object-id"],
    )
    return tuple(
        AuditSnapshotEvent(
            **event.model_dump(mode="json"),
            recorded_at_utc=f"2026-08-17T10:00:0{index}Z",
        )
        for index, event in enumerate((first, second), start=1)
    )


def _signed_bundle(
    algorithm: AuditSigningAlgorithm = AuditSigningAlgorithm.ECDSA_SHA_256,
) -> tuple[AuditWormSnapshotBundle, bytes, AuditSigningTrustPolicy]:
    private_key: ec.EllipticCurvePrivateKey | rsa.RSAPrivateKey
    if algorithm is AuditSigningAlgorithm.ECDSA_SHA_256:
        private_key = ec.generate_private_key(ec.SECP256R1())
    else:
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key_der = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    events = _events()
    events_hash = _hash(_canonical_bytes([event.model_dump(mode="json") for event in events]))
    manifest = AuditWormSnapshotManifest(
        tenant_id=TENANT_ID,
        checkpoint_id="audit-checkpoint-v2-test",
        through_sequence_number=2,
        event_count=2,
        first_event_hash=events[0].event_hash,
        last_event_hash=events[-1].event_hash,
        events_hash=events_hash,
        generated_at_utc="2026-08-17T10:00:00Z",
        generated_by="security-admin",
        retention_policy_id="audit-security-10y-v1",
        retain_until_utc="2036-08-14T10:00:00Z",
        legal_hold_state="none",
    )
    manifest_hash = _hash(_canonical_bytes(manifest.model_dump(mode="json")))
    digest = bytes.fromhex(manifest_hash.removeprefix("sha256:"))
    if isinstance(private_key, ec.EllipticCurvePrivateKey):
        detached_signature = private_key.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
    else:
        detached_signature = private_key.sign(
            digest,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=32),
            utils.Prehashed(hashes.SHA256()),
        )
    signature = AuditCheckpointSignature(
        tenant_id=TENANT_ID,
        signed_digest=manifest_hash,
        signing_algorithm=algorithm,
        kms_key_ref=f"kms-sign://{TENANT_ID}/audit/v4",
        kms_key_version=4,
        provider_profile="aws-kms",
        provider_key_id=PROVIDER_KEY_ID,
        public_key_der_base64=base64.b64encode(public_key_der).decode("ascii"),
        public_key_sha256=_hash(public_key_der),
        signature_base64=base64.b64encode(detached_signature).decode("ascii"),
        signature_sha256=_hash(detached_signature),
        signed_at_utc="2026-08-17T10:00:00Z",
        provider_sign_request_id="kms-sign-request",
        provider_verify_request_id="kms-verify-request",
        provider_verified=True,
    )
    bundle = AuditWormSnapshotBundle(
        manifest=manifest,
        manifest_hash=manifest_hash,
        signature=signature,
        events=list(events),
    )
    body = _canonical_bytes(bundle.model_dump(mode="json"))
    policy = AuditSigningTrustPolicy(
        policy_id="tenant-audit-signing-trust-v1",
        tenant_id=TENANT_ID,
        issued_at_utc=GENERATED_AT - timedelta(days=1),
        trusted_keys=(
            AuditTrustedSigningKey(
                kms_key_ref=signature.kms_key_ref,
                provider_profile=signature.provider_profile,
                provider_key_id=signature.provider_key_id,
                public_key_sha256=signature.public_key_sha256,
                allowed_signing_algorithms=(algorithm,),
                valid_from_utc=GENERATED_AT - timedelta(days=30),
                valid_until_utc=GENERATED_AT + timedelta(days=30),
            ),
        ),
    )
    return bundle, body, policy


@pytest.mark.parametrize(
    "algorithm",
    [AuditSigningAlgorithm.ECDSA_SHA_256, AuditSigningAlgorithm.RSASSA_PSS_SHA_256],
)
def test_offline_verifier_accepts_pinned_aws_kms_signature_formats_without_content_output(
    algorithm: AuditSigningAlgorithm,
) -> None:
    bundle, body, policy = _signed_bundle(algorithm)

    report = verify_audit_worm_snapshot_bundle(
        bundle_body=body,
        trust_policy=policy,
        expected_bundle_hash=_hash(body),
        expected_trust_policy_hash=build_audit_signing_trust_policy_hash(policy),
        expected_tenant_id=TENANT_ID,
        expected_checkpoint_id=bundle.manifest.checkpoint_id,
    )

    assert report.verified is True
    assert report.network_access_required is False
    assert report.signing_key_version == 4
    serialized = report.model_dump_json()
    assert "security-admin" not in serialized
    assert "restricted-object-id" not in serialized
    assert "security_audit" not in serialized


def test_offline_verifier_rejects_self_consistent_attacker_key_when_policy_is_pinned() -> None:
    bundle, _body, policy = _signed_bundle()
    attacker_key = ec.generate_private_key(ec.SECP256R1())
    attacker_public_key = attacker_key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    digest = bytes.fromhex(bundle.manifest_hash.removeprefix("sha256:"))
    attacker_signature = attacker_key.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
    replaced_signature = bundle.signature.model_copy(
        update={
            "public_key_der_base64": base64.b64encode(attacker_public_key).decode("ascii"),
            "public_key_sha256": _hash(attacker_public_key),
            "signature_base64": base64.b64encode(attacker_signature).decode("ascii"),
            "signature_sha256": _hash(attacker_signature),
        }
    )
    replaced = AuditWormSnapshotBundle(
        manifest=bundle.manifest,
        manifest_hash=bundle.manifest_hash,
        signature=replaced_signature,
        events=bundle.events,
    )
    replaced_body = _canonical_bytes(replaced.model_dump(mode="json"))

    with pytest.raises(AuditWormVerificationError, match="signing_key_identity_mismatch"):
        verify_audit_worm_snapshot_bundle(
            bundle_body=replaced_body,
            trust_policy=policy,
            expected_bundle_hash=_hash(replaced_body),
            expected_trust_policy_hash=build_audit_signing_trust_policy_hash(policy),
            expected_tenant_id=TENANT_ID,
        )


def test_offline_verifier_rejects_tampered_events_and_replaced_trust_policy() -> None:
    _bundle, body, policy = _signed_bundle()
    tampered_payload = json.loads(body)
    tampered_payload["events"][0]["metadata"]["purpose"] = "tampered"
    tampered_body = _canonical_bytes(tampered_payload)

    with pytest.raises(AuditWormVerificationError, match="invalid_bundle"):
        verify_audit_worm_snapshot_bundle(
            bundle_body=tampered_body,
            trust_policy=policy,
            expected_bundle_hash=_hash(tampered_body),
            expected_trust_policy_hash=build_audit_signing_trust_policy_hash(policy),
            expected_tenant_id=TENANT_ID,
        )

    replaced_policy = policy.model_copy(update={"policy_id": "attacker-policy"})
    with pytest.raises(AuditWormVerificationError, match="trust_policy_hash_mismatch"):
        verify_audit_worm_snapshot_bundle(
            bundle_body=body,
            trust_policy=replaced_policy,
            expected_bundle_hash=_hash(body),
            expected_trust_policy_hash=build_audit_signing_trust_policy_hash(policy),
            expected_tenant_id=TENANT_ID,
        )


def test_audit_verification_cli_emits_only_metadata_or_fixed_failure(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bundle, body, policy = _signed_bundle()
    bundle_path = tmp_path / "bundle.json"
    policy_path = tmp_path / "trust-policy.json"
    bundle_path.write_bytes(body)
    policy_path.write_text(policy.model_dump_json(), encoding="utf-8")
    arguments = [
        "--bundle",
        str(bundle_path),
        "--trust-policy",
        str(policy_path),
        "--expected-bundle-hash",
        _hash(body),
        "--expected-trust-policy-hash",
        build_audit_signing_trust_policy_hash(policy),
        "--expected-tenant-id",
        TENANT_ID,
        "--expected-checkpoint-id",
        bundle.manifest.checkpoint_id,
    ]

    assert main(arguments) == 0
    success = json.loads(capsys.readouterr().out)
    assert success["verified"] is True
    assert "events" not in success
    assert "generated_by" not in success

    arguments[arguments.index(_hash(body))] = "sha256:" + ("0" * 64)
    assert main(arguments) == 1
    failure = json.loads(capsys.readouterr().out)
    assert failure == {
        "content_included": False,
        "failure_code": "verification_failed",
        "schema_version": "audit_worm_snapshot_verification_failure.v2",
        "secrets_included": False,
        "verified": False,
    }


def test_audit_verification_compose_command_is_offline_read_only_and_default_off() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    runbook = Path("docs/operations/AUDIT_WORM_SNAPSHOTS.md").read_text(encoding="utf-8")
    roadmap = Path("docs/ROADMAP.md").read_text(encoding="utf-8")

    block = compose.split("  audit-worm-verify:", maxsplit=1)[1].split("\n  object-storage-profile-check:", maxsplit=1)[
        0
    ]
    assert 'profiles: ["audit-worm-verify"]' in block
    assert 'entrypoint: ["python", "-m", "suite.operations.audit_worm_verify"]' in block
    assert "network_mode: none" in block
    assert "read_only: true" in block
    assert "no-new-privileges:true" in block
    assert "ports:" not in block
    assert "depends_on:" not in block
    assert "expected-trust-policy-hash" in runbook
    assert "public key archived in a bundle is verification material, not a trust anchor" in runbook.lower()
    assert "[x] Audit Verification Command" in roadmap
