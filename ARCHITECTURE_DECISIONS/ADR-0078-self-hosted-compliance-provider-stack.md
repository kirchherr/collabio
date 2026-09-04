# ADR-0078: Self-Hosted Compliance Provider Stack

Status: Accepted

Date: 2026-09-03

## Context

The audit WORM and OpenBao adapters already define the application boundary, but a real production claim also depends on provider topology, supply-chain pins, TLS, recovery and measured live-provider behavior. Running one Ceph and one OpenBao container on the shared development host would test connectivity while falsely implying high availability and operational independence.

Collabio must not require AWS or another public cloud. The reference must remain deployable on operator-controlled infrastructure and must extend the existing backup/failover culture.

## Decision

The production reference stack is Kubernetes with Rook-managed Ceph RGW and OpenBao:

- Rook `v1.20.7`, Ceph Tentacle `20.2.4`, OpenBao chart `0.29.4` and OpenBao `2.6.2` are exact policy versions. Runtime images are pinned by verified multi-arch SHA-256 digests.
- Production uses at least three independent failure domains, three Ceph monitors, two managers, three OSDs, two RGW instances and three healthy OpenBao Raft voters.
- Ceph messenger v2 encryption and RGW TLS are mandatory. Record and evidence buckets are created with Object Lock, versioning and approved Compliance retention before their first write.
- Ceph RGW uses its `vault` compatibility backend against self-hosted OpenBao Transit for SSE-KMS. Storage keys are symmetric and non-exportable. Audit-signing keys are separate, asymmetric, non-exportable and non-deletable.
- OpenBao runs in HA/Raft mode with end-to-end TLS, no public service, no development mode, no runtime root token and at least two healthy audit devices.
- OpenBao Raft storage and snapshot targets are independent from the Ceph cluster whose RGW encryption depends on OpenBao. Ceph OSD devices are encrypted at rest. This gives recovery a non-circular order: OpenBao, then Ceph/RGW, then Collabio services.
- Initial production sealing uses five Shamir shares with a threshold of three. Unseal material remains in separate offline custody and is never stored in Kubernetes. A future self-hosted HSM or independently operated auto-unseal service may replace this only through another ADR and restore proof.
- Production readiness also requires replicated Ceph object data, isolated Ceph restore, OpenBao Raft snapshots, isolated OpenBao restore, Kubernetes control-plane restore, independent recovery credentials and a separate recovery failure domain.
- A one-node profile may be used only for disposable, synthetic, non-content protocol proof. Its report is labelled `proof` and can never satisfy production topology or recovery requirements.
- The checked-in CephCluster manifest has no nodes or devices. A site-specific reviewed overlay is mandatory, preventing accidental disk consumption.
- A separate `dev001` profile runs three K3s server containers through k3d, with sparse file-backed loop OSDs and independent local-path PVCs for OpenBao. This profile supports complete functional integration and simulated node failover but can never satisfy a multi-host production HA claim.
- The metadata-only preflight consumes separately collected evidence and a separately pinned policy hash. It cannot deploy, unseal, delete, change retention or execute failover.

The shared `dev001` host remains a Docker development runner. It hosts the containerized provider development cluster but must not host an improvised production or HA claim.

## Consequences

The application and reference deployment now converge on one self-hosted path. Ceph's names `vault` and `aws:kms` remain compatibility protocol identifiers only; neither establishes an AWS or HashiCorp service dependency.

Production remains intentionally blocked until a dedicated cluster exists and produces real audit WORM acceptance plus recovery evidence. The reference files make that deployment reproducible but do not turn configuration into proof.

## Verification

- `infra/self-hosted/provider-stack-policy.json` defines exact versions, Proof/Production minimums and mandatory controls.
- `infra/self-hosted/rook` and `infra/self-hosted/openbao` contain fail-safe reference configuration.
- `suite.operations.self_hosted_provider_stack` validates digest pins, topology, TLS, isolation, KMS, WORM, recovery, freshness and acceptance-report binding.
- `tests/test_self_hosted_provider_stack.py` covers positive Proof/Production paths and fail-closed drift.
- The existing live provider acceptance remains the authoritative exact-version Sign/Verify, retention and delete-denial proof.

## References

- https://docs.ceph.com/en/latest/releases/
- https://docs.ceph.com/en/tentacle/radosgw/config-ref/
- https://rook.io/docs/rook/latest-release/CRDs/Cluster/ceph-cluster-crd/
- https://rook.io/docs/rook/latest/CRDs/Object-Storage/ceph-object-store-crd/
- https://openbao.org/docs/platform/k8s/helm/run/
- https://openbao.org/docs/platform/k8s/helm/examples/ha-with-raft/
