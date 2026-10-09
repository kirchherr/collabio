#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SOURCE_PROFILE="$SCRIPT_DIR/usr.bin.runsc"
TARGET_PROFILE=/etc/apparmor.d/usr.bin.runsc

fail() {
  printf '%s\n' "$1" >&2
  exit 1
}

[ "$(id -u)" -eq 0 ] || fail "runsc AppArmor profile verification requires root"
[ -f "$SOURCE_PROFILE" ] || fail "versioned runsc AppArmor profile is missing"
[ -f "$TARGET_PROFILE" ] || fail "installed runsc AppArmor profile is missing"
cmp -s "$SOURCE_PROFILE" "$TARGET_PROFILE" || fail "installed runsc AppArmor profile drifted"
apparmor_parser --skip-kernel-load --skip-cache --Werror "$TARGET_PROFILE"
grep -Fq '/usr/bin/runsc (' /sys/kernel/security/apparmor/profiles || \
  fail "runsc AppArmor profile is not loaded"
[ "$(cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns)" = "1" ] || \
  fail "global AppArmor unprivileged-userns restriction must remain enabled"
[ "$(cat /proc/sys/kernel/unprivileged_userns_clone)" = "1" ] || \
  fail "kernel unprivileged_userns_clone must remain available for profiled runtimes"
[ "$(dpkg-query -S /usr/bin/runsc 2>/dev/null)" = "runsc: /usr/bin/runsc" ] || \
  fail "/usr/bin/runsc is not owned by the runsc Debian package"
[ "$(stat -c '%U:%G:%a' /usr/bin/runsc)" = "root:root:755" ] || \
  fail "/usr/bin/runsc ownership or mode is unexpected"

profile_sha256=$(sha256sum "$SOURCE_PROFILE" | cut -d ' ' -f 1)
runsc_version=$(dpkg-query -W -f='${Version}' runsc)
unconfined_restriction_enabled=false
if [ "$(cat /proc/sys/kernel/apparmor_restrict_unprivileged_unconfined)" = "1" ]; then
  unconfined_restriction_enabled=true
fi
printf '%s\n' \
  "{\"schema_version\":\"genoffice_runsc_host_profile_verification.v1\",\"profile_sha256\":\"sha256:$profile_sha256\",\"runsc_package_version\":\"$runsc_version\",\"package_managed\":true,\"profile_loaded\":true,\"global_userns_restriction_enabled\":true,\"global_unconfined_restriction_enabled\":$unconfined_restriction_enabled}"
