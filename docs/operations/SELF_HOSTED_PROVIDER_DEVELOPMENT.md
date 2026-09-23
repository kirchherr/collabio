# Self-Hosted Provider Development on dev001

## Purpose and boundary

The `collabio-provider` k3d cluster is Collabio's complete local integration target for Ceph RGW and OpenBao. It runs on the shared Docker daemon without changing the Tricert or Webcut projects. The existing Collabio PostgreSQL, API, MinIO and scanner services remain in Compose project `collabio`.

Three K3s server containers provide Kubernetes and embedded etcd quorum behavior. They represent three simulated zones, but they are not three physical failure domains. Evidence from this cluster must use `environment=development-single-physical-host` and `production_ha_claim=false`.

## Safety properties

- Kubernetes API binds only to `127.0.0.1:26443`.
- k3d, kubectl and Helm are project-local, checksum-verified tools; no package is installed globally.
- K3s, Rook, Ceph and OpenBao images are multi-architecture digest pins.
- Kubernetes Secret encryption uses `secretbox`; API auditing records metadata, never request or response bodies.
- OpenBao uses TLS, three Raft voters, two file audit devices and independent local-path PVCs.
- Ceph uses three retained local block PVs with exact node affinity. Each PV resolves through a real `/dev/collabio-provider-osd` block-device alias inside its assigned k3d node to an 8 GiB sparse file below `.provider-runtime/self-hosted/nodes`; `useAllDevices` and `useAllNodes` remain false.
- RGW uses TLS and OpenBao Transit SSE-KMS. The storage master key is non-exportable and distinct from the asymmetric audit-signing key.
- Runtime credentials, TLS private keys and OpenBao custody material are mode `0600` below the ignored runtime directory.
- The lifecycle script acquires `build.lock` before `docker.lock`, prints the shared Docker inventory before starts, and has no delete or destroy command.
- The Ceph toolbox has a read-only root filesystem, RuntimeDefault seccomp, explicit non-root pod/container identities and only bounded `emptyDir` write paths.
- The k3d storage-node image must run root-only node services and block-device setup. Its sole Trivy exception is path-scoped to that development Dockerfile, carries a rationale, expires after 90 days and cannot suppress findings in application or production images.
- The application protocol probe is an ephemeral Restricted-PSS Job with an unmounted service-account token, a read-only root filesystem and exact DNS, RGW and OpenBao egress only. It cannot write objects, sign, delete or emit bucket names.

## Lifecycle

```sh
cd /home/extern/collabio
tools/self-hosted/provider-dev-stack.sh bootstrap
tools/self-hosted/provider-dev-stack.sh status
tools/self-hosted/provider-dev-stack.sh stop
tools/self-hosted/provider-dev-stack.sh start
tools/self-hosted/provider-dev-stack.sh reconcile
tools/self-hosted/provider-dev-stack.sh protocol-probe I_APPROVE_READ_ONLY_PROVIDER_PROTOCOL_PROBE
```

`bootstrap` is convergent. `start` starts only the exact `collabio-provider` cluster. `reconcile` is the normal recovery command after a host restart because Linux loop devices and Shamir unseal state do not survive that restart by themselves.

`protocol-probe` is a separately confirmed, non-tenant integration check. It builds and imports the current Collabio runtime image, creates one at-most-ten-minute and single-use OpenBao token with exact signing-key metadata-read permission, and runs authenticated TLS reads against RGW and OpenBao. The temporary Job, Secret, ConfigMap and token are removed after success or failure. The metadata-only report is written to `.provider-runtime/self-hosted/evidence/provider-protocol-probe-report.json`; it is development evidence and always states `production_evidence_admissible=false` and `production_ha_claim=false`.

The development profile deliberately has no automated destruction path. Removal requires a reviewed backup, verification that the exact target remains under `/home/extern/collabio`, and explicit operator authorization.

## Access

No RGW or OpenBao service is permanently published. Run an on-demand loopback-only port-forward after checking `ss -ltn` and the active Compose profiles:

```sh
export KUBECONFIG=/home/extern/collabio/.provider-runtime/self-hosted/state/kubeconfig.yaml
.provider-runtime/self-hosted/bin/kubectl -n openbao port-forward service/openbao-active 29101:8200
.provider-runtime/self-hosted/bin/kubectl -n rook-ceph port-forward service/rook-ceph-rgw-collabio-objects 29100:443
```

Ports `29100` and `29101` are already reserved to Collabio but are also used by the optional MinIO restore profile. A port collision is a stop condition; never run both access paths at once.

## Recovery order

1. Restore or start the Kubernetes control plane and verify all three etcd members.
2. Reattach the exact sparse OSD backing files.
3. Restore OpenBao PVCs if needed, unseal all voters and verify Raft quorum.
4. Verify the non-exportable storage and signing keys.
5. Recover Ceph monitors and OSDs, then require `HEALTH_OK`.
6. Start RGW and verify TLS, KMS, versioning, Object Lock and exact-version reads.
7. Run the read-only Collabio protocol probe before preparing any provider mutation.
8. Run the separately authorized synthetic WORM acceptance and isolated restore before enabling development writes against RGW.

OpenBao must remain recoverable independently of Ceph. A same-cluster snapshot is useful development evidence but never substitutes for the production isolated-restore and cross-site requirements.
