#!/usr/bin/env bash

set -Eeuo pipefail
umask 077

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
CONFIG_DIR="$ROOT_DIR/infra/self-hosted/development"
RUNTIME_DIR="${COLLABIO_PROVIDER_RUNTIME:-$ROOT_DIR/.provider-runtime/self-hosted}"
BIN_DIR="$RUNTIME_DIR/bin"
CACHE_DIR="$RUNTIME_DIR/cache"
STATE_DIR="$RUNTIME_DIR/state"
CUSTODY_DIR="$RUNTIME_DIR/custody"
EVIDENCE_DIR="$RUNTIME_DIR/evidence"
GENERATED_DIR="$RUNTIME_DIR/generated"
KUBECONFIG_PATH="$STATE_DIR/kubeconfig.yaml"
CLUSTER_NAME="collabio-provider"
KUBE_API_PORT="26443"
BUILD_LOCK="/home/extern/.codex-coordination/build.lock"
DOCKER_LOCK="/home/extern/.codex-coordination/docker.lock"

# shellcheck source=/dev/null
source "$CONFIG_DIR/versions.env"

export COLLABIO_PROVIDER_RUNTIME="$RUNTIME_DIR"
export COLLABIO_PROVIDER_CONFIG="$CONFIG_DIR"
export K3S_IMAGE
export KUBECONFIG="$KUBECONFIG_PATH"

K3D="$BIN_DIR/k3d"
KUBECTL="$BIN_DIR/kubectl"
HELM="$BIN_DIR/helm"
STORAGE_NODE_IMAGE_ID=""
STORAGE_NODE_RUNTIME_FINGERPRINT=""

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

log() {
  printf '[collabio-provider] %s\n' "$*"
}

require_dev_host() {
  [[ "$(hostname -s)" == "dev001" ]] || die "this lifecycle is restricted to dev001"
  [[ "$(id -un)" == "extern" ]] || die "this lifecycle must run as extern"
  [[ "$ROOT_DIR" == "/home/extern/collabio" ]] || die "unexpected repository path: $ROOT_DIR"
  [[ -f /home/extern/AGENTS.md ]] || die "missing /home/extern/AGENTS.md"
  command -v docker >/dev/null || die "docker is required"
  command -v curl >/dev/null || die "curl is required"
  command -v jq >/dev/null || die "jq is required"
  command -v openssl >/dev/null || die "openssl is required"
  command -v flock >/dev/null || die "flock is required"
}

acquire_locks() {
  local command_name="$1"
  shift
  [[ "${COLLABIO_PROVIDER_LOCKED:-0}" == "1" ]] && return 0

  case "$command_name" in
    bootstrap|reconcile|smoke|backup|start)
      exec flock -w 1800 "$BUILD_LOCK" flock -w 1800 "$DOCKER_LOCK" \
        env COLLABIO_PROVIDER_LOCKED=1 "$0" "$command_name" "$@"
      ;;
    stop)
      exec flock -w 1800 "$DOCKER_LOCK" env COLLABIO_PROVIDER_LOCKED=1 "$0" "$command_name" "$@"
      ;;
  esac
}

prepare_runtime_dirs() {
  install -d -m 0700 "$RUNTIME_DIR" "$BIN_DIR" "$CACHE_DIR" "$STATE_DIR" \
    "$CUSTODY_DIR" "$EVIDENCE_DIR" "$GENERATED_DIR"
  local index
  for index in 0 1 2; do
    install -d -m 0700 \
      "$RUNTIME_DIR/nodes/server-$index/rook" \
      "$RUNTIME_DIR/nodes/server-$index/local-path" \
      "$RUNTIME_DIR/nodes/server-$index/osd"
  done
}

download_verified() {
  local url="$1"
  local expected_sha256="$2"
  local destination="$3"
  local temporary="$destination.download"

  if [[ -f "$destination" ]] && printf '%s  %s\n' "$expected_sha256" "$destination" | sha256sum --check --status; then
    return 0
  fi

  rm -f "$temporary"
  curl --fail --silent --show-error --location --proto '=https' --tlsv1.2 "$url" --output "$temporary"
  printf '%s  %s\n' "$expected_sha256" "$temporary" | sha256sum --check --status \
    || die "checksum mismatch for $url"
  mv "$temporary" "$destination"
}

install_tools() {
  log "installing verified project-local tools"
  download_verified \
    "https://github.com/k3d-io/k3d/releases/download/$K3D_VERSION/k3d-linux-amd64" \
    "$K3D_LINUX_AMD64_SHA256" "$K3D"
  chmod 0755 "$K3D"

  download_verified \
    "https://dl.k8s.io/release/$KUBECTL_VERSION/bin/linux/amd64/kubectl" \
    "$KUBECTL_LINUX_AMD64_SHA256" "$KUBECTL"
  chmod 0755 "$KUBECTL"

  local helm_archive="$CACHE_DIR/helm-$HELM_VERSION-linux-amd64.tar.gz"
  download_verified \
    "https://get.helm.sh/helm-$HELM_VERSION-linux-amd64.tar.gz" \
    "$HELM_LINUX_AMD64_SHA256" "$helm_archive"
  if [[ ! -x "$HELM" ]]; then
    tar -xzf "$helm_archive" -C "$CACHE_DIR" linux-amd64/helm
    install -m 0755 "$CACHE_DIR/linux-amd64/helm" "$HELM"
  fi

  download_verified \
    "https://charts.rook.io/release/rook-ceph-$ROOK_CHART_VERSION.tgz" \
    "$ROOK_CHART_SHA256" "$CACHE_DIR/rook-ceph-$ROOK_CHART_VERSION.tgz"
  download_verified \
    "https://github.com/openbao/openbao-helm/releases/download/openbao-$OPENBAO_CHART_VERSION/openbao-$OPENBAO_CHART_VERSION.tgz" \
    "$OPENBAO_CHART_SHA256" "$CACHE_DIR/openbao-$OPENBAO_CHART_VERSION.tgz"

  [[ "$($K3D version | awk '/k3d version/ {print $3}')" == "$K3D_VERSION" ]] \
    || die "unexpected k3d version"
  [[ "$($KUBECTL version --client -o json | jq -r .clientVersion.gitVersion)" == "$KUBECTL_VERSION" ]] \
    || die "unexpected kubectl version"
  [[ "$($HELM version --template '{{.Version}}')" == "$HELM_VERSION" ]] \
    || die "unexpected Helm version"
}

inspect_shared_docker_state() {
  log "shared Docker inventory before lifecycle operation"
  docker compose ls
  docker ps --filter label=com.docker.compose.project=collabio \
    --format '{{.Names}}|{{.Image}}|{{.Status}}|{{.Ports}}'
  docker ps --filter label=com.collabio.stack=self-hosted-provider-development \
    --format '{{.Names}}|{{.Image}}|{{.Status}}|{{.Ports}}'
}

image_runtime_fingerprint() {
  docker image inspect "$1" \
    | jq -S -c '.[0] | {
        rootfs_layers: .RootFS.Layers,
        runtime_config: {
          cmd: .Config.Cmd,
          entrypoint: .Config.Entrypoint,
          env: .Config.Env,
          labels: .Config.Labels,
          user: .Config.User,
          working_dir: .Config.WorkingDir
        }
      }' \
    | sha256sum \
    | awk '{print $1}'
}

build_storage_node_image() {
  log "building the pinned Collabio k3s storage-node image"
  docker build --pull=false \
    --build-arg "K3S_BASE_IMAGE=$K3S_BASE_IMAGE" \
    --build-arg "ALPINE_BASE_IMAGE=$ALPINE_BASE_IMAGE" \
    --build-arg "LVM2_VERSION=$LVM2_VERSION" \
    --build-arg "CRYPTSETUP_VERSION=$CRYPTSETUP_VERSION" \
    --build-arg "EUDEV_VERSION=$EUDEV_VERSION" \
    --build-arg "DEVICE_MAPPER_VERSION=$DEVICE_MAPPER_VERSION" \
    --build-arg "UTIL_LINUX_VERSION=$UTIL_LINUX_VERSION" \
    --file "$CONFIG_DIR/k3s-storage-node.Dockerfile" \
    --tag "$K3S_STORAGE_IMAGE" \
    "$ROOT_DIR"
  STORAGE_NODE_IMAGE_ID="$(docker image inspect "$K3S_STORAGE_IMAGE" --format '{{.Id}}')"
  [[ "$STORAGE_NODE_IMAGE_ID" =~ ^sha256:[a-f0-9]{64}$ ]] \
    || die "invalid storage-node image ID: $STORAGE_NODE_IMAGE_ID"
  STORAGE_NODE_RUNTIME_FINGERPRINT="$(image_runtime_fingerprint "$K3S_STORAGE_IMAGE")"
  [[ "$STORAGE_NODE_RUNTIME_FINGERPRINT" =~ ^[a-f0-9]{64}$ ]] \
    || die "invalid storage-node runtime fingerprint: $STORAGE_NODE_RUNTIME_FINGERPRINT"
  export COLLABIO_STORAGE_NODE_RUNTIME_FINGERPRINT="$STORAGE_NODE_RUNTIME_FINGERPRINT"
  docker run --rm --network none --entrypoint /bin/sh "$K3S_STORAGE_IMAGE" -eu -c '
    command -v lvm >/dev/null
    command -v cryptsetup >/dev/null
    command -v udevadm >/dev/null
    test -x /sbin/udevd
    test -x /bin/k3d-entrypoint-storage.sh
    test "$(printf collabio | xargs printf %s)" = collabio
  '
}

verify_cluster_node_image() {
  local node actual_image_id actual_image_reference actual_runtime_fingerprint
  for node in \
    k3d-collabio-provider-server-0 \
    k3d-collabio-provider-server-1 \
    k3d-collabio-provider-server-2; do
    actual_image_id="$(docker inspect "$node" --format '{{.Image}}')"
    actual_image_reference="$(docker inspect "$node" --format '{{.Config.Image}}')"
    actual_runtime_fingerprint="$(docker inspect "$node" \
      --format '{{index .Config.Labels "collabio.io/storage-node-runtime-fingerprint"}}')"
    [[ "$actual_image_reference" == "$K3S_STORAGE_IMAGE" ]] \
      || die "$node uses image reference $actual_image_reference instead of $K3S_STORAGE_IMAGE; reviewed recreation is required"
    [[ "$actual_runtime_fingerprint" == "$STORAGE_NODE_RUNTIME_FINGERPRINT" ]] \
      || die "$node runtime fingerprint $actual_runtime_fingerprint does not match reviewed image $STORAGE_NODE_IMAGE_ID fingerprint $STORAGE_NODE_RUNTIME_FINGERPRINT; reviewed recreation is required"
  done
}

cluster_exists() {
  "$K3D" cluster list --no-headers 2>/dev/null | awk '{print $1}' | grep -Fxq "$CLUSTER_NAME"
}

write_kubeconfig() {
  "$K3D" kubeconfig get "$CLUSTER_NAME" >"$KUBECONFIG_PATH"
  chmod 0600 "$KUBECONFIG_PATH"
}

create_cluster() {
  if cluster_exists; then
    verify_cluster_node_image
    log "k3d cluster already exists"
    write_kubeconfig
    return 0
  fi

  if ss -ltnH "sport = :$KUBE_API_PORT" | grep -q .; then
    die "reserved Kubernetes API port $KUBE_API_PORT is already in use"
  fi

  log "creating digest-pinned three-server k3d cluster"
  "$K3D" cluster create --config "$CONFIG_DIR/k3d.yaml"
  write_kubeconfig
}

wait_for_nodes() {
  "$KUBECTL" wait --for=condition=Ready node --all --timeout=300s
  local count version
  count="$($KUBECTL get nodes -o json | jq '.items | length')"
  version="$($KUBECTL version -o json | jq -r .serverVersion.gitVersion)"
  [[ "$count" == "3" ]] || die "expected three Kubernetes nodes, got $count"
  [[ "$version" == "$KUBECTL_VERSION+k3s1" ]] || die "unexpected Kubernetes server version: $version"
  docker exec k3d-collabio-provider-server-0 k3s secrets-encrypt status \
    | grep -q 'Encryption Status: Enabled' || die "Kubernetes secrets encryption is not enabled"
}

verify_storage_node_runtime() {
  local node
  for node in \
    k3d-collabio-provider-server-0 \
    k3d-collabio-provider-server-1 \
    k3d-collabio-provider-server-2; do
    docker exec "$node" sh -eu -c '
      command -v lvm >/dev/null
      command -v cryptsetup >/dev/null
      command -v udevadm >/dev/null
      test -S /run/udev/control
    ' || die "storage runtime prerequisites are unavailable in $node"
  done
}

initialize_storage_udev_database() {
  log "initializing the private udev block-device database on each k3d node"
  local node
  for node in \
    k3d-collabio-provider-server-0 \
    k3d-collabio-provider-server-1 \
    k3d-collabio-provider-server-2; do
    docker exec "$node" udevadm trigger --subsystem-match=block --action=add
    docker exec "$node" udevadm settle --timeout=30
    docker exec "$node" udevadm info --query=property /dev/loop0 >/dev/null \
      || die "private udev block-device database was not initialized in $node"
  done
}

attach_loop_device() {
  local node="$1"
  local output
  output="$(docker exec "$node" sh -eu -c '
    image=/var/lib/collabio-osd/osd.img
    truncate -s 8G "$image"
    inode=$(stat -c %i "$image")
    existing=$(losetup --list --noheadings --raw --output NAME,BACK-INO,BACK-FILE \
      | awk -v inode="$inode" -v image="$image" "\$2 == inode && \$3 == image {print \$1; exit}" \
      || true)
    if [ -n "$existing" ]; then
      printf "%s\n" "$existing"
    else
      candidate=$(losetup --find | awk "{print \$1}")
      case "$candidate" in
        /dev/loop*) minor=${candidate#/dev/loop} ;;
        *) printf "unsafe loop candidate: %s\n" "$candidate" >&2; exit 1 ;;
      esac
      case "$minor" in
        ""|*[!0-9]*) printf "unsafe loop minor: %s\n" "$minor" >&2; exit 1 ;;
      esac
      if [ ! -b "$candidate" ]; then
        mknod "$candidate" b 7 "$minor"
        chmod 0660 "$candidate"
      fi
      test -b "$candidate"
      losetup "$candidate" "$image"
      printf "%s\n" "$candidate"
    fi
  ')"
  [[ "$output" =~ ^/dev/loop[0-9]+$ ]] || die "unsafe loop device result for $node: $output"
  docker exec "$node" test -b "$output" || die "$output is not a block device in $node"
  docker exec "$node" udevadm trigger --action=change "/sys/block/${output##*/}"
  docker exec "$node" udevadm settle --timeout=30
  docker exec "$node" udevadm info --query=property "$output" >/dev/null \
    || die "udev did not identify $output in $node"
  docker exec "$node" sh -eu -c '
    source_device="$1"
    stable_device=/dev/collabio-provider-osd
    minor=${source_device#/dev/loop}
    case "$minor" in
      ""|*[!0-9]*) printf "unsafe loop minor: %s\n" "$minor" >&2; exit 1 ;;
    esac
    if [ -e "$stable_device" ] || [ -L "$stable_device" ]; then
      [ -b "$stable_device" ] || [ -L "$stable_device" ] || exit 1
      unlink "$stable_device"
    fi
    mknod "$stable_device" b 7 "$minor"
    chmod 0660 "$stable_device"
    test -b "$stable_device"
    test "$(stat -c %t:%T "$stable_device")" = "$(stat -c %t:%T "$source_device")"
  ' -- "$output" || die "stable local block device was not created in $node"
  printf '%s' "$output"
}

prepare_kubelet_block_mapping_devices() {
  local probe_node="k3d-collabio-provider-server-0"
  local first_device first_minor last_minor node
  first_device="$(docker exec "$probe_node" sh -eu -c \
    'losetup --find | awk "{print \$1}"')"
  [[ "$first_device" =~ ^/dev/loop[0-9]+$ ]] \
    || die "unsafe kubelet loop-device candidate: $first_device"
  first_minor="${first_device#/dev/loop}"
  last_minor=$((first_minor + 7))

  log "creating unbound loop-device nodes $first_device through /dev/loop$last_minor for kubelet block mapping"
  for node in \
    k3d-collabio-provider-server-0 \
    k3d-collabio-provider-server-1 \
    k3d-collabio-provider-server-2; do
    docker exec "$node" sh -eu -c '
      current="$1"
      last="$2"
      while [ "$current" -le "$last" ]; do
        path="/dev/loop$current"
        if [ -e "$path" ] || [ -L "$path" ]; then
          test -b "$path"
        else
          mknod "$path" b 7 "$current"
          chmod 0660 "$path"
        fi
        test "$(stat -c %t:%T "$path")" = "$(printf "7:%x" "$current")"
        current=$((current + 1))
      done
    ' -- "$first_minor" "$last_minor" \
      || die "kubelet block-mapping loop-device reserve was not created in $node"
  done
}

prepare_ceph_devices() {
  log "attaching one sparse Collabio-owned loop device per k3d node"
  local device0 device1 device2
  device0="$(attach_loop_device k3d-collabio-provider-server-0)"
  device1="$(attach_loop_device k3d-collabio-provider-server-1)"
  device2="$(attach_loop_device k3d-collabio-provider-server-2)"

  [[ "$device0" != "$device1" && "$device0" != "$device2" && "$device1" != "$device2" ]] \
    || die "each Ceph node must have a distinct loop device"

  prepare_kubelet_block_mapping_devices
  install -m 0600 "$CONFIG_DIR/ceph-cluster.yaml.template" "$GENERATED_DIR/ceph-cluster.yaml"
  printf 'SERVER_0_DEVICE=%s\nSERVER_1_DEVICE=%s\nSERVER_2_DEVICE=%s\n' \
    "$device0" "$device1" "$device2" >"$STATE_DIR/ceph-devices.env"
  chmod 0600 "$STATE_DIR/ceph-devices.env"
}

generate_tls_material() {
  local tls_dir="$CUSTODY_DIR/tls"
  install -d -m 0700 "$tls_dir"

  if [[ ! -s "$tls_dir/ca.key" ]]; then
    log "generating development-only provider CA and service certificates"
    openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out "$tls_dir/ca.key"
    openssl req -x509 -new -sha256 -days 1825 -key "$tls_dir/ca.key" \
      -subj '/CN=Collabio dev001 Provider Development CA' -out "$tls_dir/ca.crt"
  fi

  if [[ ! -s "$tls_dir/openbao.key" ]]; then
    openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out "$tls_dir/openbao.key"
    openssl req -new -sha256 -key "$tls_dir/openbao.key" \
      -subj '/CN=openbao.openbao.svc.cluster.local' -out "$tls_dir/openbao.csr"
    openssl x509 -req -sha256 -days 825 -in "$tls_dir/openbao.csr" \
      -CA "$tls_dir/ca.crt" -CAkey "$tls_dir/ca.key" -CAcreateserial \
      -extfile "$CONFIG_DIR/openbao-tls.ext" -out "$tls_dir/openbao.crt"
    cat "$tls_dir/openbao.crt" "$tls_dir/ca.crt" >"$tls_dir/openbao-fullchain.crt"
  fi

  if [[ ! -s "$tls_dir/rgw.key" ]]; then
    openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out "$tls_dir/rgw.key"
    openssl req -new -sha256 -key "$tls_dir/rgw.key" \
      -subj '/CN=rook-ceph-rgw-collabio-objects.rook-ceph.svc.cluster.local' -out "$tls_dir/rgw.csr"
    openssl x509 -req -sha256 -days 825 -in "$tls_dir/rgw.csr" \
      -CA "$tls_dir/ca.crt" -CAkey "$tls_dir/ca.key" -CAcreateserial \
      -extfile "$CONFIG_DIR/rgw-tls.ext" -out "$tls_dir/rgw.crt"
    cat "$tls_dir/rgw.crt" "$tls_dir/ca.crt" >"$tls_dir/rgw-fullchain.crt"
  fi

  chmod 0600 "$tls_dir"/*
  openssl verify -CAfile "$tls_dir/ca.crt" "$tls_dir/openbao.crt" "$tls_dir/rgw.crt" >/dev/null
}

apply_base_resources() {
  "$KUBECTL" apply -f "$CONFIG_DIR/namespaces-and-storage.yaml"
  "$KUBECTL" apply -f "$CONFIG_DIR/local-block-storage.yaml"
  local tls_dir="$CUSTODY_DIR/tls"
  "$KUBECTL" -n openbao create secret generic openbao-server-tls \
    --type=kubernetes.io/tls \
    --from-file=tls.crt="$tls_dir/openbao-fullchain.crt" \
    --from-file=tls.key="$tls_dir/openbao.key" \
    --from-file=ca.crt="$tls_dir/ca.crt" \
    --dry-run=client -o yaml | "$KUBECTL" apply -f -
  "$KUBECTL" -n rook-ceph create secret generic collabio-rgw-tls \
    --type=kubernetes.io/tls \
    --from-file=tls.crt="$tls_dir/rgw-fullchain.crt" \
    --from-file=tls.key="$tls_dir/rgw.key" \
    --dry-run=client -o yaml | "$KUBECTL" apply -f -
  "$KUBECTL" -n rook-ceph create secret generic collabio-provider-ca \
    --from-file=cabundle="$tls_dir/ca.crt" \
    --dry-run=client -o yaml | "$KUBECTL" apply -f -
  "$KUBECTL" -n rook-ceph create secret generic collabio-openbao-ca \
    --from-file=cert="$tls_dir/ca.crt" \
    --dry-run=client -o yaml | "$KUBECTL" apply -f -
}

deploy_openbao() {
  log "deploying OpenBao HA Raft with TLS"
  "$HELM" upgrade --install openbao "$CACHE_DIR/openbao-$OPENBAO_CHART_VERSION.tgz" \
    --namespace openbao --values "$CONFIG_DIR/openbao-values.yaml" --wait --timeout 10m
  local update_revision current_revision pod
  update_revision="$("$KUBECTL" -n openbao get statefulset openbao \
    -o jsonpath='{.status.updateRevision}')"
  [[ -n "$update_revision" ]] || die "OpenBao StatefulSet has no update revision"
  for pod in openbao-0 openbao-1 openbao-2; do
    "$KUBECTL" -n openbao wait --for=create "pod/$pod" --timeout=600s
    current_revision="$("$KUBECTL" -n openbao get pod "$pod" \
      -o jsonpath='{.metadata.labels.controller-revision-hash}')"
    if [[ "$current_revision" != "$update_revision" ]]; then
      log "replacing $pod to apply reviewed OpenBao configuration"
      "$KUBECTL" -n openbao delete pod "$pod" --wait=true
      "$KUBECTL" -n openbao wait --for=create "pod/$pod" --timeout=300s
      "$KUBECTL" -n openbao wait --for=condition=Ready "pod/$pod" --timeout=600s
    fi
  done
  "$KUBECTL" -n openbao wait \
    --for=jsonpath='{.status.readyReplicas}'=3 statefulset/openbao --timeout=600s
}

bao_exec() {
  local pod="$1"
  shift
  "$KUBECTL" -n openbao exec "$pod" -- env \
    BAO_ADDR="https://$pod.openbao-internal.openbao.svc.cluster.local:8200" \
    BAO_CACERT=/openbao/tls/ca.crt \
    BAO_TLS_SERVER_NAME=openbao.openbao.svc.cluster.local \
    bao "$@"
}

bao_unseal() {
  local pod="$1"
  local share="$2"
  local endpoint="/api/v1/namespaces/openbao/pods/https:$pod:8200/proxy/v1/sys/unseal"
  printf '{"key":"%s"}\n' "$share" \
    | "$KUBECTL" replace --raw="$endpoint" -f - >/dev/null
}

bao_root_exec() {
  local root_token="$1"
  shift
  printf '%s\n' "$root_token" | "$KUBECTL" -n openbao exec -i openbao-0 -- \
    sh -ec 'IFS= read -r BAO_TOKEN; export BAO_TOKEN; export BAO_ADDR=https://openbao-active.openbao.svc.cluster.local:8200; export BAO_CACERT=/openbao/tls/ca.crt; export BAO_TLS_SERVER_NAME=openbao-active.openbao.svc.cluster.local; exec bao "$@"' \
    sh "$@"
}

bao_root_policy_write() {
  local root_token="$1"
  local policy_name="$2"
  local policy_file="$3"
  { printf '%s\n' "$root_token"; cat "$policy_file"; } | \
    "$KUBECTL" -n openbao exec -i openbao-0 -- \
      sh -ec 'IFS= read -r BAO_TOKEN; export BAO_TOKEN; export BAO_ADDR=https://openbao-active.openbao.svc.cluster.local:8200; export BAO_CACERT=/openbao/tls/ca.crt; export BAO_TLS_SERVER_NAME=openbao-active.openbao.svc.cluster.local; exec bao policy write "$1" -' \
      sh "$policy_name" >/dev/null
}

openbao_initialized() {
  local status
  status="$(bao_exec openbao-0 status -format=json 2>/dev/null || true)"
  [[ -n "$status" ]] && [[ "$(jq -r '.initialized // false' <<<"$status")" == "true" ]]
}

openbao_sealed() {
  local pod="$1"
  local status
  status="$(bao_exec "$pod" status -format=json 2>/dev/null || true)"
  [[ -z "$status" ]] || [[ "$(jq -r '.sealed // true' <<<"$status")" == "true" ]]
}

openbao_raft_has_peer() {
  local root_token="$1"
  local pod="$2"
  bao_root_exec "$root_token" operator raft list-peers -format=json \
    | jq -e --arg pod "$pod" '.data.config.servers[] | select(.node_id == $pod)' >/dev/null
}

wait_for_openbao_active() {
  local deadline=$((SECONDS + 120))
  until "$KUBECTL" -n openbao get endpointslice \
    -l kubernetes.io/service-name=openbao-active -o json \
    | jq -e '[.items[].endpoints[]? | select(.conditions.ready == true) | .addresses[]?] | length > 0' \
      >/dev/null; do
    ((SECONDS < deadline)) || die "OpenBao active service has no ready endpoint"
    sleep 2
  done
}

initialize_and_unseal_openbao() {
  local init_file="$CUSTODY_DIR/openbao-init.json"
  if ! openbao_initialized; then
    [[ ! -e "$init_file" ]] || die "OpenBao is uninitialized but custody material already exists"
    log "initializing OpenBao with three shares and threshold two"
    bao_exec openbao-0 operator init -key-shares=3 -key-threshold=2 -format=json >"$init_file"
    chmod 0600 "$init_file"
  fi
  [[ -s "$init_file" ]] || die "OpenBao custody file is required to unseal the development cluster"

  local share1 share2 root_token pod
  share1="$(jq -r '.unseal_keys_b64[0]' "$init_file")"
  share2="$(jq -r '.unseal_keys_b64[1]' "$init_file")"
  root_token="$(jq -r .root_token "$init_file")"
  [[ -n "$share1" && "$share1" != "null" && -n "$share2" && "$share2" != "null" ]] \
    || die "invalid OpenBao custody material"
  [[ -n "$root_token" && "$root_token" != "null" ]] || die "invalid OpenBao root token"

  for pod in openbao-0 openbao-1 openbao-2; do
    if [[ "$pod" != "openbao-0" ]] && ! openbao_raft_has_peer "$root_token" "$pod"; then
      bao_exec "$pod" operator raft join \
        -leader-ca-cert=@/openbao/tls/ca.crt \
        -leader-client-cert=@/openbao/tls/tls.crt \
        -leader-client-key=@/openbao/tls/tls.key \
        https://openbao-0.openbao-internal.openbao.svc.cluster.local:8200 >/dev/null
    fi
    if openbao_sealed "$pod"; then
      bao_unseal "$pod" "$share1"
      bao_unseal "$pod" "$share2"
    fi
    [[ "$pod" != "openbao-0" ]] || wait_for_openbao_active
  done

  bao_root_exec "$root_token" operator raft list-peers -format=json \
    | jq -e '.data.config.servers | length == 3' >/dev/null \
    || die "OpenBao Raft does not have three peers"
}

enable_secret_engine() {
  local root_token="$1"
  local mount_path="$2"
  if ! bao_root_exec "$root_token" secrets list -format=json | jq -e --arg path "$mount_path/" 'has($path)' >/dev/null; then
    bao_root_exec "$root_token" secrets enable -path="$mount_path" transit >/dev/null
  fi
}

token_is_valid() {
  local token_file="$1"
  [[ -s "$token_file" ]] || return 1
  cat "$token_file" | "$KUBECTL" -n openbao exec -i openbao-0 -- \
    sh -ec 'IFS= read -r BAO_TOKEN; export BAO_TOKEN; export BAO_ADDR=https://openbao-0.openbao-internal.openbao.svc.cluster.local:8200; export BAO_CACERT=/openbao/tls/ca.crt; export BAO_TLS_SERVER_NAME=openbao.openbao.svc.cluster.local; bao token lookup -format=json' \
    2>/dev/null | jq -e '.data.renewable == true' >/dev/null
}

create_periodic_token() {
  local root_token="$1"
  local policy="$2"
  local token_file="$3"
  local response="$CUSTODY_DIR/$policy-token-response.json"
  if token_is_valid "$token_file"; then
    return 0
  fi
  bao_root_exec "$root_token" token create -orphan -period=24h -policy="$policy" -format=json >"$response"
  jq -er .auth.client_token "$response" >"$token_file"
  chmod 0600 "$response" "$token_file"
}

configure_openbao() {
  local init_file="$CUSTODY_DIR/openbao-init.json"
  local root_token
  root_token="$(jq -r .root_token "$init_file")"

  bao_root_exec "$root_token" audit list -format=json \
    | jq -e 'has("audit-primary/") and has("audit-secondary/")' >/dev/null \
    || die "declarative OpenBao audit devices are not active"
  enable_secret_engine "$root_token" collabio-storage
  enable_secret_engine "$root_token" collabio-signing

  bao_root_exec "$root_token" write collabio-storage/keys/collabio-rgw-sse-kms \
    type=aes256-gcm96 exportable=false allow_plaintext_backup=false >/dev/null
  bao_root_exec "$root_token" write collabio-storage/keys/collabio-rgw-sse-kms/config \
    deletion_allowed=false min_decryption_version=1 >/dev/null
  bao_root_exec "$root_token" write collabio-signing/keys/collabio-audit-signing \
    type=ecdsa-p256 exportable=false allow_plaintext_backup=false >/dev/null
  bao_root_exec "$root_token" write collabio-signing/keys/collabio-audit-signing/config \
    deletion_allowed=false min_decryption_version=1 >/dev/null

  bao_root_policy_write "$root_token" collabio-rgw "$CONFIG_DIR/openbao-rgw-policy.hcl"
  bao_root_policy_write "$root_token" collabio-application "$CONFIG_DIR/openbao-application-policy.hcl"
  create_periodic_token "$root_token" collabio-rgw "$CUSTODY_DIR/rgw-openbao.token"
  create_periodic_token "$root_token" collabio-application "$CUSTODY_DIR/application-openbao.token"

  "$KUBECTL" -n rook-ceph create secret generic collabio-rgw-openbao-token \
    --from-file=token="$CUSTODY_DIR/rgw-openbao.token" \
    --dry-run=client -o yaml | "$KUBECTL" apply -f -

  bao_root_exec "$root_token" read -format=json collabio-storage/keys/collabio-rgw-sse-kms \
    | jq -e '.data.exportable == false and .data.deletion_allowed == false' >/dev/null
  bao_root_exec "$root_token" read -format=json collabio-signing/keys/collabio-audit-signing \
    | jq -e '.data.exportable == false and .data.deletion_allowed == false' >/dev/null
}

ceph_toolbox_exec() {
  "$KUBECTL" -n rook-ceph exec deployment/rook-ceph-tools -- ceph "$@"
}

harden_cephx_cipher_policy() {
  local health_json mon_dump
  health_json="$(ceph_toolbox_exec --format=json health detail)"
  jq -e '
    [.checks | keys[] | select(. == "AUTH_INSECURE_CLIENT_KEY_TYPE"
      or . == "AUTH_INSECURE_ROTATING_SERVICE_KEY_TYPE"
      or . == "AUTH_INSECURE_SERVICE_KEY_TYPE"
      or . == "AUTH_INSECURE_SERVICE_TICKETS")] | length == 0
  ' <<<"$health_json" >/dev/null \
    || die "Ceph still has insecure entity keys or service tickets; refusing to restrict authentication ciphers"

  mon_dump="$(ceph_toolbox_exec --format=json mon dump)"
  jq -e '
    .auth_preferred_cipher.name == "aes256k"
      and .auth_service_cipher.name == "aes256k"
      and any(.auth_allowed_ciphers[]; .name == "aes256k")
  ' <<<"$mon_dump" >/dev/null \
    || die "Ceph monitor cipher policy is not ready for aes256k-only authentication"

  ceph_toolbox_exec mon set auth_allowed_ciphers aes256k
  ceph_toolbox_exec config set mon mon_auth_allow_insecure_key false
  mon_dump="$(ceph_toolbox_exec --format=json mon dump)"
  jq -e '
    (.auth_allowed_ciphers | map(.name) == ["aes256k"])
      and .auth_preferred_cipher.name == "aes256k"
      and .auth_service_cipher.name == "aes256k"
  ' <<<"$mon_dump" >/dev/null \
    || die "Ceph monitor cipher policy did not converge to aes256k-only authentication"
  ceph_toolbox_exec status >/dev/null
}

verify_ceph_osd_topology() {
  local osd_stat osd_tree
  osd_stat="$(ceph_toolbox_exec --format=json osd stat)"
  jq -e '.num_osds == 3 and .num_up_osds == 3 and .num_in_osds == 3' \
    <<<"$osd_stat" >/dev/null \
    || die "Ceph must have exactly three OSDs and all must be up and in"

  osd_tree="$(ceph_toolbox_exec --format=json osd tree)"
  jq -e '
    [.nodes[]
      | select(.type == "host")
      | select(.name | startswith("k3d-collabio-provider-server-"))] as $hosts
    | ($hosts | length) == 3
      and all($hosts[]; (.children | length) == 1)
  ' <<<"$osd_tree" >/dev/null \
    || die "Ceph must place exactly one OSD on each Collabio provider node"
}

deploy_rook_and_ceph() {
  log "deploying Rook operator and encrypted three-OSD Ceph cluster"
  "$HELM" upgrade --install rook-ceph "$CACHE_DIR/rook-ceph-$ROOK_CHART_VERSION.tgz" \
    --namespace rook-ceph --values "$CONFIG_DIR/rook-operator-values.yaml" --wait --timeout 10m
  "$KUBECTL" -n rook-ceph rollout status deployment/rook-ceph-operator --timeout=600s
  "$KUBECTL" wait --for=condition=Established \
    crd/cephconnections.csi.ceph.io --timeout=300s
  "$KUBECTL" -n rook-ceph rollout status \
    deployment/ceph-csi-controller-manager --timeout=600s
  "$KUBECTL" apply -f "$GENERATED_DIR/ceph-cluster.yaml"

  local deadline=$((SECONDS + 1800))
  local phase=""
  while ((SECONDS < deadline)); do
    phase="$($KUBECTL -n rook-ceph get cephcluster rook-ceph -o jsonpath='{.status.phase}' 2>/dev/null || true)"
    [[ "$phase" == "Ready" ]] && break
    sleep 15
  done
  [[ "$phase" == "Ready" ]] || die "Ceph cluster did not reach Ready phase (last phase: ${phase:-unknown})"

  "$KUBECTL" apply -f "$CONFIG_DIR/ceph-toolbox-and-user.yaml"
  "$KUBECTL" -n rook-ceph rollout status deployment/rook-ceph-tools --timeout=600s
  harden_cephx_cipher_policy

  local health=""
  while ((SECONDS < deadline)); do
    health="$($KUBECTL -n rook-ceph get cephcluster rook-ceph -o jsonpath='{.status.ceph.health}' 2>/dev/null || true)"
    [[ "$health" == "HEALTH_OK" ]] && break
    sleep 15
  done
  [[ "$health" == "HEALTH_OK" ]] || die "Ceph did not reach HEALTH_OK (last status: ${health:-unknown})"
  verify_ceph_osd_topology
}

deploy_object_store() {
  log "deploying TLS-only Ceph RGW with OpenBao Transit SSE-KMS"
  "$KUBECTL" apply -f "$CONFIG_DIR/ceph-object-store.yaml"
  local deadline=$((SECONDS + 1200))
  local generation observed_generation phase
  generation="$($KUBECTL -n rook-ceph get cephobjectstore collabio-objects \
    -o jsonpath='{.metadata.generation}')"
  while ((SECONDS < deadline)); do
    observed_generation="$($KUBECTL -n rook-ceph get cephobjectstore collabio-objects \
      -o jsonpath='{.status.observedGeneration}' 2>/dev/null || true)"
    phase="$($KUBECTL -n rook-ceph get cephobjectstore collabio-objects \
      -o jsonpath='{.status.phase}' 2>/dev/null || true)"
    [[ "$phase" == "Ready" && "$observed_generation" == "$generation" ]] && break
    sleep 10
  done
  [[ "$phase" == "Ready" && "$observed_generation" == "$generation" ]] \
    || die "Ceph object store did not reach observed Ready phase"

  "$KUBECTL" apply -f "$CONFIG_DIR/ceph-toolbox-and-user.yaml"
  "$KUBECTL" -n rook-ceph rollout status deployment/rook-ceph-tools --timeout=600s
  "$KUBECTL" -n rook-ceph rollout status deployment/rook-ceph-rgw-collabio-objects-a --timeout=1200s
  local ready_replicas
  ready_replicas="$($KUBECTL -n rook-ceph get deployment rook-ceph-rgw-collabio-objects-a \
    -o jsonpath='{.status.readyReplicas}')"
  [[ "$ready_replicas" == "2" ]] || die "expected two ready RGW replicas, got ${ready_replicas:-0}"

  local secret_name=rook-ceph-object-user-collabio-objects-collabio-dev
  deadline=$((SECONDS + 300))
  until "$KUBECTL" -n rook-ceph get secret "$secret_name" >/dev/null 2>&1; do
    ((SECONDS < deadline)) || die "Ceph object user secret was not created"
    sleep 5
  done
  "$KUBECTL" -n rook-ceph get secret "$secret_name" -o jsonpath='{.data.AccessKey}' \
    | base64 --decode >"$CUSTODY_DIR/rgw-access-key"
  "$KUBECTL" -n rook-ceph get secret "$secret_name" -o jsonpath='{.data.SecretKey}' \
    | base64 --decode >"$CUSTODY_DIR/rgw-secret-key"
  chmod 0600 "$CUSTODY_DIR/rgw-access-key" "$CUSTODY_DIR/rgw-secret-key"
}

apply_network_policies() {
  "$KUBECTL" apply -f "$CONFIG_DIR/network-policies.yaml"
}

write_status_evidence() {
  local output="$EVIDENCE_DIR/provider-development-status.json"
  local temp="$output.tmp"
  local ceph_health openbao_peers node_count rgw_count root_token
  ceph_health="$($KUBECTL -n rook-ceph get cephcluster rook-ceph -o jsonpath='{.status.ceph.health}')"
  root_token="$(jq -r .root_token "$CUSTODY_DIR/openbao-init.json")"
  openbao_peers="$(bao_root_exec "$root_token" operator raft list-peers -format=json \
    | jq '.data.config.servers | length')"
  unset root_token
  node_count="$($KUBECTL get nodes -o json | jq '.items | length')"
  rgw_count="$($KUBECTL -n rook-ceph get pods -l app=rook-ceph-rgw -o json | jq '[.items[] | select(.status.phase == "Running")] | length')"
  jq -n \
    --arg schema_version self_hosted_provider_development_status.v1 \
    --arg observed_at_utc "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --arg cluster "$CLUSTER_NAME" \
    --arg kubernetes "$KUBECTL_VERSION" \
    --arg rook "$ROOK_CHART_VERSION" \
    --arg ceph "20.2.4" \
    --arg openbao "2.6.2" \
    --arg openbao_chart "$OPENBAO_CHART_VERSION" \
    --arg ceph_health "$ceph_health" \
    --argjson nodes "$node_count" \
    --argjson openbao_peers "$openbao_peers" \
    --argjson rgw_instances "$rgw_count" \
    '{
      schema_version: $schema_version,
      observed_at_utc: $observed_at_utc,
      environment: "development-single-physical-host",
      production_ha_claim: false,
      tenant_content_included: false,
      secrets_included: false,
      cluster: $cluster,
      versions: {
        kubernetes: $kubernetes,
        rook: $rook,
        ceph: $ceph,
        openbao_chart: $openbao_chart,
        openbao: $openbao
      },
      topology: {
        kubernetes_nodes: $nodes,
        simulated_failure_domains: 3,
        physical_hosts: 1,
        openbao_raft_voters: $openbao_peers,
        rgw_instances: $rgw_instances
      },
      controls: {
        kubernetes_secrets_encrypted: true,
        kubernetes_audit_level: "Metadata",
        network_policy_controller: "k3s-kube-router",
        provider_endpoints_public: false,
        ceph_health: $ceph_health,
        ceph_msgr2_encryption: true,
        ceph_osd_encryption: true,
        openbao_tls: true,
        openbao_dev_mode: false,
        openbao_audit_devices: 2,
        openbao_storage_independent_from_ceph: true,
        storage_and_signing_keys_distinct: true,
        storage_key_exportable: false
      }
    }' >"$temp"
  mv "$temp" "$output"
  chmod 0600 "$output"
}

show_status() {
  prepare_runtime_dirs
  install_tools
  cluster_exists || die "cluster $CLUSTER_NAME does not exist"
  write_kubeconfig
  "$KUBECTL" get nodes -o wide
  "$KUBECTL" get pods -A -o wide
  "$KUBECTL" -n rook-ceph get cephcluster,cephobjectstore
  bao_exec openbao-0 status || true
  "$KUBECTL" -n rook-ceph exec deploy/rook-ceph-tools -- ceph status || true
}

bootstrap() {
  prepare_runtime_dirs
  install_tools
  inspect_shared_docker_state
  build_storage_node_image
  create_cluster
  wait_for_nodes
  verify_storage_node_runtime
  initialize_storage_udev_database
  prepare_ceph_devices
  generate_tls_material
  apply_base_resources
  deploy_openbao
  initialize_and_unseal_openbao
  configure_openbao
  deploy_rook_and_ceph
  deploy_object_store
  apply_network_policies
  write_status_evidence
  log "provider development stack is running; no production HA claim was made"
}

reconcile() {
  prepare_runtime_dirs
  install_tools
  inspect_shared_docker_state
  build_storage_node_image
  cluster_exists || die "cluster $CLUSTER_NAME does not exist; run bootstrap"
  "$K3D" cluster start "$CLUSTER_NAME"
  write_kubeconfig
  wait_for_nodes
  verify_cluster_node_image
  verify_storage_node_runtime
  initialize_storage_udev_database
  prepare_ceph_devices
  initialize_and_unseal_openbao
  write_status_evidence
}

start_stack() {
  prepare_runtime_dirs
  install_tools
  inspect_shared_docker_state
  build_storage_node_image
  cluster_exists || die "cluster $CLUSTER_NAME does not exist; run bootstrap"
  verify_cluster_node_image
  "$K3D" cluster start "$CLUSTER_NAME"
  write_kubeconfig
  log "cluster started; run reconcile to reattach Ceph loop devices and unseal OpenBao"
}

stop_stack() {
  prepare_runtime_dirs
  install_tools
  cluster_exists || die "cluster $CLUSTER_NAME does not exist"
  inspect_shared_docker_state
  "$K3D" cluster stop "$CLUSTER_NAME"
}

usage() {
  cat <<'EOF'
Usage: tools/self-hosted/provider-dev-stack.sh COMMAND

Commands:
  bootstrap   Create or converge the complete dev001 provider stack
  reconcile   Recover the existing stack after a host or cluster restart
  status      Show Kubernetes, OpenBao and Ceph status without changing state
  start       Start existing k3d containers; follow with reconcile
  stop        Stop only the exact collabio-provider k3d cluster

The script deliberately has no destroy command. Removal requires a separately
reviewed backup and explicit operator procedure.
EOF
}

main() {
  local command_name="${1:-}"
  shift || true
  require_dev_host
  case "$command_name" in
    bootstrap|reconcile|start|stop)
      acquire_locks "$command_name" "$@"
      "$command_name" "$@"
      ;;
    status)
      show_status
      ;;
    *)
      usage
      [[ -z "$command_name" || "$command_name" == "help" || "$command_name" == "--help" ]] || return 2
      ;;
  esac
}

main "$@"
