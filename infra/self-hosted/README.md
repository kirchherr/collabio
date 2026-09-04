# Self-Hosted Compliance Provider Stack

This directory contains both the production reference and a deliberately separate development deployment for Collabio object storage and key management. Production manifests remain fail-safe templates. The `development` profile provisions a container-isolated Kubernetes provider cluster on `dev001` for integration, restart and recovery testing.

## Reference stack

- Kubernetes `>=1.30.0`, with dedicated provider namespaces and enforced NetworkPolicy plus restricted Pod Security.
- Rook `v1.20.7` managing Ceph Tentacle `20.2.4`.
- Ceph RGW with TLS, bucket versioning, Object Lock, Compliance retention and SSE-KMS.
- OpenBao chart `0.29.4` running OpenBao `2.6.2` as three Raft voters with TLS and persistent audit storage.
- OpenBao Transit supplies separate non-exportable symmetric storage keys and asymmetric audit-signing keys. The two key identities and policies must never overlap.

Runtime images and downloadable development tools are pinned by release and SHA-256 digest. The preflight rejects non-digest image evidence.

## Deliberate safety stops

`rook/ceph-cluster.production.yaml` has no storage nodes or devices. This prevents an accidental apply from consuming shared or system disks. A reviewed site overlay must explicitly name at least three nodes, their failure domains and dedicated raw devices.

No TLS private key, OpenBao token, unseal share, root token or S3 credential belongs in this directory. Referenced Kubernetes Secrets are external inputs. OpenBao production initialization uses five Shamir shares with a threshold of three; shares stay in separate offline custody and never in Kubernetes.

The required `openbao-independent-rwo` storage class must not be backed by the Ceph cluster whose RGW encryption depends on OpenBao. OpenBao Raft snapshots also leave through an independent backup path. This removes a circular recovery dependency: restore OpenBao and its keys first, then Ceph and RGW, then Collabio data services.

The Ceph CR uses the provider identifier `vault` because that is the Ceph/Rook API name for the Vault-compatible protocol. Its address is the self-hosted OpenBao service. The S3 wire value `aws:kms` likewise identifies the compatible request protocol and does not select an AWS service.

## Deployment order

1. Prepare a dedicated Kubernetes cluster with at least three independent failure domains and dedicated Ceph devices.
2. Verify signatures, SBOMs and multi-arch digests for the pinned Rook, Ceph and OpenBao releases.
3. Install the Rook operator chart at exactly `v1.20.7`, then apply a reviewed CephCluster site overlay.
4. Install OpenBao chart `0.29.4` with `openbao/values.production.yaml`, site storage classes and digest-pinned images.
5. Initialize OpenBao with the approved Shamir ceremony, enable two independent audit devices and create separate Transit mounts/policies for RGW storage encryption and audit signing.
6. Create the renewable, least-privilege RGW machine token secret outside Git, then apply the CephObjectStore manifest.
7. Create record buckets with Object Lock enabled at creation time. Enable versioning and approved default retention before any Collabio write.
8. Run the non-content audit WORM provider acceptance, isolated Ceph restore and isolated OpenBao Raft snapshot restore.
9. Prove the independent Kubernetes control-plane restore, then build `self_hosted_provider_stack_evidence.v1` from all reports and run the metadata-only preflight. Production remains blocked until every production control passes.

## Proof versus production

The policy supports a one-node, disposable proof profile only to validate protocol compatibility with synthetic non-content data. It is never an HA or production claim. Production requires three failure domains, three Ceph monitors, two managers, at least three OSDs, two RGWs, three healthy OpenBao Raft voters, two audit devices, cross-site object replication and isolated restores.

The preflight never deploys, mutates, unseals, deletes or fails over a provider. It evaluates separately collected evidence and always reports `deployment_execution_allowed=false`.

## Complete development deployment on dev001

`tools/self-hosted/provider-dev-stack.sh` creates a three-server K3s cluster in Docker through k3d. It uses only the exact cluster name `collabio-provider`, a loopback Kubernetes API on the Collabio-reserved port `26443`, and state below the ignored `.provider-runtime/self-hosted` directory. The application itself continues to run under Compose project `collabio`; the nested provider cluster exists because Rook and its failure behavior must be tested on Kubernetes.

The development cluster has three simulated zones, an embedded etcd quorum, metadata-only Kubernetes auditing, NetworkPolicy enforcement, encrypted Kubernetes Secrets, three TLS-protected OpenBao Raft voters, two OpenBao audit devices, three encrypted Ceph OSDs backed only by sparse files, and two TLS-only RGW instances using a non-exportable OpenBao Transit key. Each OSD is exposed through a retained local block PV with exact node affinity; this prevents host-global loop discovery in nested k3d nodes from assigning every OSD to the same simulated host. The lifecycle also creates eight unbound loop-device nodes in each k3d node so kubelet can map the three block PVCs into their OSD pods. These reserve nodes have no backing files or attachments of their own. The stack never discovers or consumes a physical host disk. Generated CA keys, unseal shares, root token, machine tokens and S3 credentials remain outside Git in the mode-`0700` runtime directory.

The one-time encrypted OSD preparation is limited to `2Gi` per job. This is deliberately higher than the daemon request because LUKS2 and Ceph provisioning need a short memory burst; Rook warns that tight `prepareosd` limits can leave an incomplete encrypted device. Three concurrent jobs require at most `6Gi` under this development profile.

After Rook reports the cluster ready, bootstrap starts a non-root, capability-free Ceph toolbox from the same digest-pinned image. It verifies that no client or daemon still uses an insecure CephX key type, confirms that monitor preference and service tickets already use `aes256k`, then removes legacy `aes` authentication and disables creation of insecure keys. Administrative access and `HEALTH_OK` must both succeed afterward; health warnings are not muted.

Object-store readiness follows Rook's generation-aware `status.phase=Ready` contract. The two gateways are verified as two ready replicas of the single zone deployment that Rook creates for this store.

The bootstrap also fails closed unless Ceph reports exactly three OSDs, all `up` and `in`, with exactly one OSD below each simulated provider host. It never removes an unexpected OSD automatically.

This is functionally complete for local integration and node/container failure tests. It is intentionally **not** production HA: all three simulated failure domains share the one physical `dev001` host, and the development custody material is held by one operator account. Production admission still requires independent hosts, independent custody and cross-site restores.

Run only on `dev001` as `extern`, after reading `/home/extern/AGENTS.md`:

```sh
cd /home/extern/collabio
tools/self-hosted/provider-dev-stack.sh bootstrap
tools/self-hosted/provider-dev-stack.sh status
```

After a `dev001` restart, use `reconcile`; it starts the exact k3d cluster, reattaches only the Collabio sparse OSD files, unseals OpenBao from local custody and emits fresh metadata-only status evidence. The script deliberately provides no destructive command.

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
