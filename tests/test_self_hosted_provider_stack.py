from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Literal

import pytest
from pydantic import ValidationError

from suite.operations.self_hosted_provider_stack import (
    CephStackEvidence,
    ComponentArtifactEvidence,
    KubernetesStackEvidence,
    OpenBaoStackEvidence,
    ProviderRecoveryEvidence,
    SelfHostedProviderStackEvidence,
    SelfHostedProviderStackPolicy,
    build_self_hosted_provider_stack_policy_hash,
    build_self_hosted_provider_stack_report,
    build_self_hosted_provider_stack_report_hash,
    load_self_hosted_provider_stack_policy,
    main,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
POLICY_PATH = REPO_ROOT / "infra" / "self-hosted" / "provider-stack-policy.json"
CHECKED_AT = datetime(2026, 9, 3, 10, 0, tzinfo=UTC)


def _hash(value: str) -> str:
    return "sha256:" + sha256(value.encode("utf-8")).hexdigest()


def _artifact(name: str, version: str) -> ComponentArtifactEvidence:
    digest = _hash(f"{name}-{version}")
    return ComponentArtifactEvidence(
        version=version,
        image_reference=f"quay.io/collabio/{name}@{digest}",
        image_digest=digest,
        release_signature_verified=True,
        sbom_sha256=_hash(f"{name}-sbom"),
    )


def _evidence(*, target_profile: Literal["proof", "production"] = "production") -> SelfHostedProviderStackEvidence:
    production = target_profile == "production"
    return SelfHostedProviderStackEvidence(
        target_profile=target_profile,
        deployment_ref_sha256=_hash("deployment"),
        configuration_bundle_sha256=_hash("configuration"),
        observed_at_utc=CHECKED_AT - timedelta(minutes=10),
        kubernetes=KubernetesStackEvidence(
            version="1.34.1",
            node_count=3 if production else 1,
            failure_domain_count=3 if production else 1,
            network_policies_enforced=True,
            restricted_pod_security_enforced=True,
            provider_namespaces_dedicated=True,
            public_provider_endpoint_exposed=False,
        ),
        ceph=CephStackEvidence(
            rook=_artifact("rook", "v1.19.6"),
            ceph=_artifact("ceph", "20.2.4"),
            rgw_endpoint="https://rgw.internal.example",
            health_status="HEALTH_OK",
            monitor_count=3 if production else 1,
            manager_count=2 if production else 1,
            osd_count=3 if production else 1,
            rgw_instance_count=2 if production else 1,
            failure_domain_count=3 if production else 1,
            msgr2_encryption_verified=True,
            osd_device_encryption_verified=True,
            rgw_tls_verified=True,
            bucket_versioning_verified=True,
            object_lock_enabled_at_bucket_creation=True,
            compliance_retention_verified=True,
            exact_version_delete_denial_verified=True,
            sse_kms_openbao_transit_verified=True,
            storage_key_non_exportable_verified=True,
            storage_key_ref_sha256=_hash("storage-key"),
            health_report_sha256=_hash("ceph-health"),
        ),
        openbao=OpenBaoStackEvidence(
            chart_version="0.29.3",
            artifact=_artifact("openbao", "2.6.2"),
            endpoint="https://openbao.internal.example",
            initialized=True,
            sealed=False,
            high_availability_enabled=True,
            raft_voter_count=3 if production else 1,
            healthy_raft_voter_count=3 if production else 1,
            failure_domain_count=3 if production else 1,
            tls_verified=True,
            dev_mode_enabled=False,
            root_token_in_runtime_use=False,
            audit_device_count=2 if production else 1,
            audit_devices_healthy=True,
            transit_enabled=True,
            signing_key_non_exportable_verified=True,
            signing_key_deletion_disabled=True,
            signing_key_ref_sha256=_hash("signing-key"),
            seal_strategy="shamir-offline-custody",
            unseal_share_count=5 if production else 1,
            unseal_threshold=3 if production else 1,
            unseal_material_stored_in_cluster=False,
            storage_independent_from_ceph=True,
            health_report_sha256=_hash("openbao-health"),
        ),
        recovery=ProviderRecoveryEvidence(
            ceph_replication_verified=production,
            ceph_isolated_restore_verified=production,
            openbao_raft_snapshot_verified=production,
            openbao_isolated_restore_verified=production,
            independent_recovery_site_verified=production,
            recovery_credentials_independent=production,
            openbao_snapshot_target_independent_from_ceph=production,
            kubernetes_control_plane_restore_verified=production,
            ceph_restore_report_sha256=_hash("ceph-restore"),
            openbao_restore_report_sha256=_hash("openbao-restore"),
        ),
        audit_worm_provider_acceptance_report_sha256=_hash("worm-acceptance") if production else None,
        storage_and_signing_keys_distinct=True,
    )


def _policy() -> SelfHostedProviderStackPolicy:
    return load_self_hosted_provider_stack_policy(POLICY_PATH)


def test_production_stack_report_binds_versions_topology_recovery_and_acceptance() -> None:
    policy = _policy()
    report = build_self_hosted_provider_stack_report(
        policy=policy,
        expected_policy_hash=build_self_hosted_provider_stack_policy_hash(policy),
        evidence=_evidence(),
        checked_at_utc=CHECKED_AT,
    )

    assert report.ready is True
    assert report.blocking_reasons == ()
    assert report.deployment_execution_allowed is False
    assert report.report_sha256 == build_self_hosted_provider_stack_report_hash(report)


def test_proof_stack_is_accepted_without_misrepresenting_production_requirements() -> None:
    policy = _policy()
    report = build_self_hosted_provider_stack_report(
        policy=policy,
        expected_policy_hash=build_self_hosted_provider_stack_policy_hash(policy),
        evidence=_evidence(target_profile="proof"),
        checked_at_utc=CHECKED_AT,
    )

    assert report.target_profile == "proof"
    assert report.ready is True
    assert report.recovery_controls_verified is True
    assert report.audit_worm_acceptance_bound is False


def test_production_stack_fails_closed_on_version_topology_recovery_and_acceptance_drift() -> None:
    policy = _policy()
    evidence = _evidence().model_copy(
        update={
            "ceph": _evidence().ceph.model_copy(
                update={
                    "rook": _artifact("rook", "v1.19.5"),
                    "monitor_count": 1,
                }
            ),
            "recovery": _evidence().recovery.model_copy(update={"ceph_replication_verified": False}),
            "audit_worm_provider_acceptance_report_sha256": None,
        }
    )
    report = build_self_hosted_provider_stack_report(
        policy=policy,
        expected_policy_hash=build_self_hosted_provider_stack_policy_hash(policy),
        evidence=evidence,
        checked_at_utc=CHECKED_AT,
    )

    assert report.ready is False
    assert report.blocking_reasons == (
        "version_pins_not_verified",
        "topology_not_verified",
        "recovery_controls_not_verified",
        "audit_worm_acceptance_not_bound",
    )


def test_stack_evidence_rejects_public_cloud_endpoints_and_unpinned_images() -> None:
    with pytest.raises(ValidationError):
        CephStackEvidence.model_validate(
            {
                **_evidence().ceph.model_dump(),
                "rgw_endpoint": "https://s3.eu-central-1.amazonaws.com",
            }
        )

    artifact = _artifact("ceph", "20.2.4")
    with pytest.raises(ValidationError):
        ComponentArtifactEvidence.model_validate(
            {
                **artifact.model_dump(),
                "image_reference": "quay.io/ceph/ceph:v20.2.4",
            }
        )


def test_stack_report_rejects_stale_evidence() -> None:
    policy = _policy()
    evidence = _evidence().model_copy(update={"observed_at_utc": CHECKED_AT - timedelta(hours=25)})
    report = build_self_hosted_provider_stack_report(
        policy=policy,
        expected_policy_hash=build_self_hosted_provider_stack_policy_hash(policy),
        evidence=evidence,
        checked_at_utc=CHECKED_AT,
    )

    assert report.ready is False
    assert report.blocking_reasons == ("evidence_not_fresh",)


def test_preflight_cli_is_metadata_only_and_requires_separately_pinned_policy(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_text(json.dumps(_evidence(target_profile="proof").model_dump(mode="json")), encoding="utf-8")

    assert (
        main(
            [
                "--policy",
                str(POLICY_PATH),
                "--expected-policy-hash",
                _hash("wrong-policy"),
                "--evidence",
                str(evidence_path),
            ]
        )
        == 1
    )
    failure = json.loads(capsys.readouterr().out)
    assert failure == {
        "failure_code": "provider_stack_preflight_failed",
        "ready": False,
        "schema_version": "self_hosted_provider_stack_failure.v1",
        "secrets_included": False,
        "tenant_content_included": False,
    }


def test_reference_manifests_are_fail_safe_and_aws_infrastructure_free() -> None:
    cluster = (REPO_ROOT / "infra" / "self-hosted" / "rook" / "ceph-cluster.production.yaml").read_text()
    object_store = (REPO_ROOT / "infra" / "self-hosted" / "rook" / "ceph-object-store.production.yaml").read_text()
    openbao = (REPO_ROOT / "infra" / "self-hosted" / "openbao" / "values.production.yaml").read_text()

    assert "useAllNodes: false" in cluster
    assert "useAllDevices: false" in cluster
    assert "encryptedDevice: true" in cluster
    assert "nodes: []" in cluster
    assert "allowUninstallWithVolumes: false" in cluster
    assert "image: quay.io/ceph/ceph:v20.2.4" in cluster
    assert "KMS_PROVIDER: vault" in object_store
    assert "VAULT_ADDR: https://openbao-active.openbao.svc.cluster.local:8200" in object_store
    assert "object_lock" not in object_store.lower()
    assert 'tag: "2.6.2"' in openbao
    assert "storageClass: openbao-independent-rwo" in openbao
    assert "tls_disable = 0" in openbao
    assert "replicas: 3" in openbao
    assert "enabled: false" in openbao
    assert "amazonaws.com" not in cluster + object_store + openbao


def test_preflight_runtime_is_networkless_read_only_and_policy_bundled() -> None:
    compose = (REPO_ROOT / "docker-compose.yml").read_text()
    dockerfile = (REPO_ROOT / "Dockerfile").read_text()
    service = compose.split("  self-hosted-provider-preflight:\n", maxsplit=1)[1].split(
        "\n  object-storage-profile-check:", maxsplit=1
    )[0]

    assert 'profiles: ["self-hosted-provider-preflight"]' in service
    assert "network_mode: none" in service
    assert "read_only: true" in service
    assert "- ALL" in service
    assert "no-new-privileges:true" in service
    assert 'restart: "no"' in service
    assert "infra/self-hosted/provider-stack-policy.json" in dockerfile
