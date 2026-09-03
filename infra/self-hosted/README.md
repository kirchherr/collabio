# Self-Hosted Compliance Provider Stack

This directory is the production reference for Collabio object storage and key management. It does not provision a cluster by itself and it must not be applied to the shared `dev001` Docker host.

## Reference stack

- Kubernetes `>=1.30.0`, with dedicated provider namespaces and enforced NetworkPolicy plus restricted Pod Security.
- Rook `v1.19.6` managing Ceph Tentacle `20.2.4`.
- Ceph RGW with TLS, bucket versioning, Object Lock, Compliance retention and SSE-KMS.
- OpenBao chart `0.29.3` running OpenBao `2.6.2` as three Raft voters with TLS and persistent audit storage.
- OpenBao Transit supplies separate non-exportable symmetric storage keys and asymmetric audit-signing keys. The two key identities and policies must never overlap.

Images in the checked-in examples use readable release tags. A site overlay must replace every tag with a verified multi-arch `@sha256` digest before admission. The preflight rejects non-digest image evidence.

## Deliberate safety stops

`rook/ceph-cluster.production.yaml` has no storage nodes or devices. This prevents an accidental apply from consuming shared or system disks. A reviewed site overlay must explicitly name at least three nodes, their failure domains and dedicated raw devices.

No TLS private key, OpenBao token, unseal share, root token or S3 credential belongs in this directory. Referenced Kubernetes Secrets are external inputs. OpenBao production initialization uses five Shamir shares with a threshold of three; shares stay in separate offline custody and never in Kubernetes.

The required `openbao-independent-rwo` storage class must not be backed by the Ceph cluster whose RGW encryption depends on OpenBao. OpenBao Raft snapshots also leave through an independent backup path. This removes a circular recovery dependency: restore OpenBao and its keys first, then Ceph and RGW, then Collabio data services.

The Ceph CR uses the provider identifier `vault` because that is the Ceph/Rook API name for the Vault-compatible protocol. Its address is the self-hosted OpenBao service. The S3 wire value `aws:kms` likewise identifies the compatible request protocol and does not select an AWS service.

## Deployment order

1. Prepare a dedicated Kubernetes cluster with at least three independent failure domains and dedicated Ceph devices.
2. Verify signatures, SBOMs and multi-arch digests for the pinned Rook, Ceph and OpenBao releases.
3. Install the Rook operator chart at exactly `v1.19.6`, then apply a reviewed CephCluster site overlay.
4. Install OpenBao chart `0.29.3` with `openbao/values.production.yaml`, site storage classes and digest-pinned images.
5. Initialize OpenBao with the approved Shamir ceremony, enable two independent audit devices and create separate Transit mounts/policies for RGW storage encryption and audit signing.
6. Create the renewable, least-privilege RGW machine token secret outside Git, then apply the CephObjectStore manifest.
7. Create record buckets with Object Lock enabled at creation time. Enable versioning and approved default retention before any Collabio write.
8. Run the non-content audit WORM provider acceptance, isolated Ceph restore and isolated OpenBao Raft snapshot restore.
9. Prove the independent Kubernetes control-plane restore, then build `self_hosted_provider_stack_evidence.v1` from all reports and run the metadata-only preflight. Production remains blocked until every production control passes.

## Proof versus production

The policy supports a one-node, disposable proof profile only to validate protocol compatibility with synthetic non-content data. It is never an HA or production claim. Production requires three failure domains, three Ceph monitors, two managers, at least three OSDs, two RGWs, three healthy OpenBao Raft voters, two audit devices, cross-site object replication and isolated restores.

The preflight never deploys, mutates, unseals, deletes or fails over a provider. It evaluates separately collected evidence and always reports `deployment_execution_allowed=false`.

```sh
docker compose -p collabio --profile self-hosted-provider-preflight run --rm --no-deps \
  --volume "$INPUT_DIR:/input:ro" self-hosted-provider-preflight \
  --policy /workspace/infra/self-hosted/provider-stack-policy.json \
  --expected-policy-hash "sha256:<separately-pinned-policy-hash>" \
  --evidence /input/provider-stack-evidence.json
```

## Primary references

- Rook production cluster and CephCluster CRD: https://rook.io/docs/rook/latest-release/CRDs/Cluster/ceph-cluster-crd/
- Rook CephObjectStore TLS and KMS settings: https://rook.io/docs/rook/latest/CRDs/Object-Storage/ceph-object-store-crd/
- Ceph RGW encryption and Vault-compatible Transit backend: https://docs.ceph.com/en/tentacle/radosgw/config-ref/
- OpenBao Helm production guidance: https://openbao.org/docs/platform/k8s/helm/run/
- OpenBao HA with integrated Raft: https://openbao.org/docs/platform/k8s/helm/examples/ha-with-raft/
