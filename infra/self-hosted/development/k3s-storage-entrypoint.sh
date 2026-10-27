#!/bin/sh

set -eu

install -d -m 0755 /run/udev

if [ ! -S /run/udev/control ]; then
  /sbin/udevd --daemon --resolve-names=never
fi

attempt=0
while [ ! -S /run/udev/control ]; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 50 ]; then
    printf 'udev control socket did not become ready\n' >&2
    exit 1
  fi
  sleep 0.1
done
