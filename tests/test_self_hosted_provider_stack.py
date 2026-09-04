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
            rook=_artifact("rook", "v1.20.7"),
            ceph_csi_operator=_artifact("ceph-csi-operator", "1.0.4"),
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
            chart_version="0.29.4",
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
                    "ceph_csi_operator": _artifact("ceph-csi-operator", "1.0.3"),
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
    assert 'encryptedDevice: "true"' in cluster
    assert "nodes: []" in cluster
    assert "allowUninstallWithVolumes: false" in cluster
    assert (
        "image: quay.io/ceph/ceph:v20.2.4@sha256:6bb1c8a42fbc0bf87938946990b65174466997bc11c31eb5a323225a779fd8f9"
        in cluster
    )
    assert "KMS_PROVIDER: vault" in object_store
    assert "VAULT_ADDR: https://openbao-active.openbao.svc.cluster.local:8200" in object_store
    assert "object_lock" not in object_store.lower()
    assert 'tag: "2.6.2@sha256:11fd73a2102cda9c55d5d881a8c3210303146a7ec1e8ac76f526e175c6d24641"' in openbao
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


def test_dev001_provider_cluster_is_pinned_isolated_and_non_destructive() -> None:
    development = REPO_ROOT / "infra" / "self-hosted" / "development"
    versions = (development / "versions.env").read_text()
    k3d = (development / "k3d.yaml").read_text()
    audit_policy = (development / "audit-policy.yaml").read_text()
    ceph = (development / "ceph-cluster.yaml.template").read_text()
    local_block = (development / "local-block-storage.yaml").read_text()
    toolbox = (development / "ceph-toolbox-and-user.yaml").read_text()
    openbao = (development / "openbao-values.yaml").read_text()
    rook = (development / "rook-operator-values.yaml").read_text()
    storage_node = (development / "k3s-storage-node.Dockerfile").read_text()
    storage_entrypoint = (development / "k3s-storage-entrypoint.sh").read_text()
    lifecycle = (REPO_ROOT / "tools" / "self-hosted" / "provider-dev-stack.sh").read_text()

    assert "ROOK_CHART_VERSION=v1.20.7" in versions
    assert "OPENBAO_CHART_VERSION=0.29.4" in versions
    assert versions.count("@sha256:") == 5
    assert "K3S_BASE_IMAGE=rancher/k3s:v1.36.4-k3s1@sha256:" in versions
    assert "ALPINE_BASE_IMAGE=alpine:3.23@sha256:" in versions
    assert "LVM2_VERSION=2.03.35-r0" in versions
    assert "CRYPTSETUP_VERSION=2.8.1-r0" in versions
    assert "EUDEV_VERSION=3.2.14-r6" in versions
    assert "FROM ${ALPINE_BASE_IMAGE} AS storage_runtime" in storage_node
    assert "FROM ${K3S_BASE_IMAGE}" in storage_node
    assert '"lvm2=${LVM2_VERSION}"' in storage_node
    assert '"cryptsetup=${CRYPTSETUP_VERSION}"' in storage_node
    assert '"eudev=${EUDEV_VERSION}"' in storage_node
    assert "COPY --from=storage_runtime / /" not in storage_node
    assert "COPY --from=storage_runtime /lib/ /lib/" in storage_node
    assert "COPY --from=storage_runtime /usr/lib/ /usr/lib/" in storage_node
    assert "COPY --from=storage_runtime /usr/bin/ /usr/bin/" not in storage_node
    assert "/bin/k3d-entrypoint-storage.sh" in storage_node
    assert "/sbin/udevd --daemon --resolve-names=never" in storage_entrypoint
    assert "--subsystem-match=block" not in storage_entrypoint
    assert 'exec /bin/k3s "$@"' not in storage_entrypoint
    assert "servers: 3" in k3d
    assert "image: ${K3S_IMAGE}" in k3d
    assert "collabio.io/storage-node-runtime-fingerprint=${COLLABIO_STORAGE_NODE_RUNTIME_FINGERPRINT}" in k3d
    assert "hostIP: 127.0.0.1" in k3d
    assert 'hostPort: "26443"' in k3d
    assert "--secrets-encryption-provider=secretbox" in k3d
    assert "audit-log-mode=blocking-strict" in k3d
    assert "audit-policy.yaml:/etc/collabio/audit-policy.yaml:ro" in k3d
    assert "/run/udev:/run/udev" not in k3d
    assert "level: Metadata" in audit_policy
    assert "disableLoadbalancer: true" in k3d
    assert "useAllNodes: false" in ceph
    assert "useAllDevices: false" in ceph
    assert "storageClassDeviceSets:" in ceph
    assert "count: 3" in ceph
    assert "portable: false" in ceph
    assert "encrypted: true" in ceph
    assert "storageClassName: collabio-provider-local-block" in ceph
    assert "volumeMode: Block" in ceph
    assert (
        """    prepareosd:
      requests:
        cpu: 100m
        memory: 128Mi
      limits:
        memory: 2Gi"""
        in ceph
    )
    assert local_block.count("kind: PersistentVolume\n") == 3
    assert local_block.count("path: /dev/collabio-provider-osd") == 3
    assert local_block.count("persistentVolumeReclaimPolicy: Retain") == 3
    assert "provisioner: kubernetes.io/no-provisioner" in local_block
    assert "volumeBindingMode: WaitForFirstConsumer" in local_block
    assert local_block.count("k3d-collabio-provider-server-") == 3
    assert "serviceAccountName: rook-ceph-default" in toolbox
    assert "KEYRING_MOUNT=/var/lib/rook-ceph-mon/secret.keyring" in toolbox
    assert "printf '[%s]\\nkey = %s\\n'" in toolbox
    assert "runAsNonRoot: true" in toolbox
    assert "runAsUser: 2016" in toolbox
    assert "allowPrivilegeEscalation: false" in toolbox
    assert "secretName: rook-ceph-mon" in toolbox
    assert "replicas: 3" in openbao
    assert "tls_disable = 0" in openbao
    assert "storageClass: openbao-independent-rwo" in openbao
    assert 'audit "file" "audit-primary"' in openbao
    assert 'audit "file" "audit-secondary"' in openbao
    assert "configAnnotation: true" in openbao
    assert 'mode = "0600"' in openbao
    assert 'log_raw = "false"' in openbao
    assert "installCsiOperator: true" in rook
    assert "v1.0.4@sha256:c62933fd4083635f969f8a61932af45dba9902d48867e2b5d98a69d8e4344eb6" in rook
    assert "crd/cephconnections.csi.ceph.io" in lifecycle
    assert "deployment/ceph-csi-controller-manager" in lifecycle
    assert 'flock -w 1800 "$BUILD_LOCK" flock -w 1800 "$DOCKER_LOCK"' in lifecycle
    assert "docker compose ls" in lifecycle
    assert 'candidate=$(losetup --find | awk "{print \\$1}")' in lifecycle
    assert "--output NAME,BACK-INO,BACK-FILE" in lifecycle
    assert "build_storage_node_image" in lifecycle
    assert "image_runtime_fingerprint" in lifecycle
    assert "STORAGE_NODE_RUNTIME_FINGERPRINT" in lifecycle
    assert "export COLLABIO_STORAGE_NODE_RUNTIME_FINGERPRINT" in lifecycle
    assert "collabio.io/storage-node-runtime-fingerprint" in lifecycle
    assert "verify_cluster_node_image" in lifecycle
    assert "verify_storage_node_runtime" in lifecycle
    assert lifecycle.count("initialize_storage_udev_database") == 3
    assert "udevadm trigger --subsystem-match=block --action=add" in lifecycle
    assert "docker run --rm --network none --entrypoint /bin/sh" in lifecycle
    assert 'test "$(printf collabio | xargs printf %s)" = collabio' in lifecycle
    assert "bootstrap|reconcile|smoke|backup|start" in lifecycle
    assert 'wait --for=create "pod/$pod" --timeout=600s' in lifecycle
    assert "udevadm trigger --action=change" in lifecycle
    assert "stable_device=/dev/collabio-provider-osd" in lifecycle
    assert 'mknod "$stable_device" b 7 "$minor"' in lifecycle
    assert 'stat -c %t:%T "$stable_device"' in lifecycle
    assert lifecycle.count("prepare_kubelet_block_mapping_devices") == 2
    assert "last_minor=$((first_minor + 7))" in lifecycle
    assert 'mknod "$path" b 7 "$current"' in lifecycle
    assert 'printf "7:%x" "$current"' in lifecycle
    assert lifecycle.count("harden_cephx_cipher_policy") == 2
    assert "AUTH_INSECURE_CLIENT_KEY_TYPE" in lifecycle
    assert "AUTH_INSECURE_SERVICE_KEY_TYPE" in lifecycle
    assert "mon set auth_allowed_ciphers aes256k" in lifecycle
    assert "config set mon mon_auth_allow_insecure_key false" in lifecycle
    assert 'map(.name) == ["aes256k"]' in lifecycle
    assert "ceph_toolbox_exec status >/dev/null" in lifecycle
    assert lifecycle.count("verify_ceph_osd_topology") == 2
    assert ".num_osds == 3 and .num_up_osds == 3 and .num_in_osds == 3" in lifecycle
    assert 'startswith("k3d-collabio-provider-server-")' in lifecycle
    assert "all($hosts[]; (.children | length) == 1)" in lifecycle
    assert "status.observedGeneration" in lifecycle
    assert "Ceph object store did not reach observed Ready phase" in lifecycle
    assert "expected two ready RGW replicas" in lifecycle
    assert "rook-ceph-rgw-collabio-objects-b" not in lifecycle
    assert "cephobjectstore/collabio-objects --timeout=1200s" not in lifecycle
    assert 'apply -f "$CONFIG_DIR/local-block-storage.yaml"' in lifecycle
    assert "test -S /run/udev/control" in lifecycle
    assert "udev placeholder" not in lifecycle
    assert 'docker cp "$udev_record"' not in lifecycle
    assert "docker cp /run/udev/data/." not in lifecycle
    assert "rollout restart deployment/rook-ceph-operator" not in lifecycle
    assert 'mknod "$candidate" b 7 "$minor"' in lifecycle
    assert 'test -b "$candidate"' in lifecycle
    assert "--for=jsonpath='{.status.readyReplicas}'=3 statefulset/openbao" in lifecycle
    assert 'replace --raw="$endpoint" -f -' in lifecycle
    assert 'bao operator unseal "$share"' not in lifecycle
    assert "openbao_raft_has_peer" in lifecycle
    assert "-leader-ca-cert=@/openbao/tls/ca.crt" in lifecycle
    assert "-leader-client-cert=@/openbao/tls/tls.crt" in lifecycle
    assert "-leader-client-key=@/openbao/tls/tls.key" in lifecycle
    assert "BAO_ADDR=https://openbao-active.openbao.svc.cluster.local:8200" in lifecycle
    assert "BAO_TLS_SERVER_NAME=openbao-active.openbao.svc.cluster.local" in lifecycle
    assert "wait_for_openbao_active" in lifecycle
    assert "kubernetes.io/service-name=openbao-active" in lifecycle
    assert "declarative OpenBao audit devices are not active" in lifecycle
    assert "audit enable" not in lifecycle
    assert "unsafe_allow_api_audit_creation" not in openbao + lifecycle
    assert "docker system prune" not in lifecycle
    assert "docker volume prune" not in lifecycle
    assert "cluster delete" not in lifecycle
    assert "down -v" not in lifecycle


def test_development_rgw_uses_tls_and_non_exportable_openbao_transit_contract() -> None:
    development = REPO_ROOT / "infra" / "self-hosted" / "development"
    object_store = (development / "ceph-object-store.yaml").read_text()
    rgw_policy = (development / "openbao-rgw-policy.hcl").read_text()
    lifecycle = (REPO_ROOT / "tools" / "self-hosted" / "provider-dev-stack.sh").read_text()

    assert "securePort: 443" in object_store
    assert "instances: 2" in object_store
    assert "KMS_PROVIDER: vault" in object_store
    assert "VAULT_SECRET_ENGINE: transit" in object_store
    assert 'VAULT_VERIFY_SSL: "true"' in object_store
    assert "VAULT_CACERT: collabio-openbao-ca" in object_store
    assert "collabio-storage/datakey/plaintext/collabio-rgw-sse-kms" in rgw_policy
    assert "collabio-storage/decrypt/collabio-rgw-sse-kms" in rgw_policy
    assert "exportable=false" in lifecycle
    assert "deletion_allowed=false" in lifecycle
    assert "amazonaws.com" not in object_store + lifecycle
