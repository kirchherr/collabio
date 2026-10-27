#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
compose_project=${COMPOSE_PROJECT_NAME:-collabio}
runtime_tmp=$(mktemp "${TMPDIR:-/tmp}/collabio-requirements.XXXXXX")
dev_tmp=$(mktemp "${TMPDIR:-/tmp}/collabio-requirements-dev.XXXXXX")
preview_tmp=$(mktemp "${TMPDIR:-/tmp}/collabio-requirements-preview.XXXXXX")

cleanup() {
    rm -f -- "$runtime_tmp" "$dev_tmp" "$preview_tmp"
}
trap cleanup EXIT HUP INT TERM

cd "$repo_root"
docker compose -p "$compose_project" --profile tooling run -T --rm dependency-lock-runtime > "$runtime_tmp"
docker compose -p "$compose_project" --profile tooling run -T --rm dependency-lock-dev > "$dev_tmp"
docker compose -p "$compose_project" --profile tooling run -T --rm dependency-lock-preview > "$preview_tmp"

test -s "$runtime_tmp"
test -s "$dev_tmp"
test -s "$preview_tmp"
chmod 0644 "$runtime_tmp" "$dev_tmp" "$preview_tmp"
mv -f -- "$runtime_tmp" requirements.lock
mv -f -- "$dev_tmp" requirements-dev.lock
mv -f -- "$preview_tmp" requirements-preview.lock
