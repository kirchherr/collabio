ARG K3S_BASE_IMAGE
ARG ALPINE_BASE_IMAGE

FROM ${ALPINE_BASE_IMAGE} AS storage_runtime

ARG LVM2_VERSION
ARG CRYPTSETUP_VERSION
ARG EUDEV_VERSION
ARG DEVICE_MAPPER_VERSION
ARG UTIL_LINUX_VERSION

RUN apk add --no-cache \
      "cryptsetup=${CRYPTSETUP_VERSION}" \
      "device-mapper=${DEVICE_MAPPER_VERSION}" \
      "eudev=${EUDEV_VERSION}" \
      "lvm2=${LVM2_VERSION}" \
      "util-linux=${UTIL_LINUX_VERSION}"

FROM ${K3S_BASE_IMAGE}

ARG K3S_BASE_IMAGE
ARG ALPINE_BASE_IMAGE
ARG LVM2_VERSION
ARG CRYPTSETUP_VERSION
ARG EUDEV_VERSION
ARG DEVICE_MAPPER_VERSION
ARG UTIL_LINUX_VERSION

COPY --from=storage_runtime /lib/ /lib/
COPY --from=storage_runtime /usr/lib/ /usr/lib/
COPY --from=storage_runtime /sbin/ /sbin/
COPY --from=storage_runtime /usr/sbin/ /usr/sbin/
COPY --from=storage_runtime /bin/udevadm /bin/udevadm
COPY --from=storage_runtime /etc/lvm/ /etc/lvm/
COPY --from=storage_runtime /etc/udev/ /etc/udev/
COPY infra/self-hosted/development/k3s-storage-entrypoint.sh /bin/k3d-entrypoint-storage.sh

RUN chmod 0755 /bin/k3d-entrypoint-storage.sh \
    && mkdir -p /run/udev \
    && chmod 1777 /tmp

LABEL org.opencontainers.image.title="Collabio K3s Storage Node" \
      org.opencontainers.image.description="Pinned k3s development node with Rook Ceph host prerequisites" \
      org.opencontainers.image.source="https://github.com/kirchherr/collabio" \
      collabio.io/k3s-base-image="${K3S_BASE_IMAGE}" \
      collabio.io/alpine-base-image="${ALPINE_BASE_IMAGE}" \
      collabio.io/lvm2-version="${LVM2_VERSION}" \
      collabio.io/cryptsetup-version="${CRYPTSETUP_VERSION}" \
      collabio.io/eudev-version="${EUDEV_VERSION}" \
      collabio.io/device-mapper-version="${DEVICE_MAPPER_VERSION}" \
      collabio.io/util-linux-version="${UTIL_LINUX_VERSION}"
