#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
SOURCE_PROFILE="$SCRIPT_DIR/usr.bin.runsc"
TARGET_PROFILE=/etc/apparmor.d/usr.bin.runsc

fail() {
  printf '%s\n' "$1" >&2
  exit 1
}

[ "$(id -u)" -eq 0 ] || fail "runsc AppArmor profile installation requires root"
[ -f "$SOURCE_PROFILE" ] || fail "versioned runsc AppArmor profile is missing"
[ -x /usr/bin/runsc ] || fail "package-managed /usr/bin/runsc is missing"
[ "$(dpkg-query -S /usr/bin/runsc 2>/dev/null)" = "runsc: /usr/bin/runsc" ] || \
  fail "/usr/bin/runsc is not owned by the runsc Debian package"
[ "$(stat -c '%U:%G:%a' /usr/bin/runsc)" = "root:root:755" ] || \
  fail "/usr/bin/runsc ownership or mode is unexpected"
command -v apparmor_parser >/dev/null 2>&1 || fail "apparmor_parser is unavailable"

apparmor_parser --skip-kernel-load --skip-cache --Werror "$SOURCE_PROFILE"

installed_new=0
if [ -e "$TARGET_PROFILE" ]; then
  cmp -s "$SOURCE_PROFILE" "$TARGET_PROFILE" || \
    fail "$TARGET_PROFILE exists with different content; refusing to overwrite"
else
  install -o root -g root -m 0644 "$SOURCE_PROFILE" "$TARGET_PROFILE"
  installed_new=1
fi

if ! apparmor_parser --replace --skip-cache --Werror "$TARGET_PROFILE"; then
  if [ "$installed_new" -eq 1 ]; then
    rm -f "$TARGET_PROFILE"
  fi
  fail "runsc AppArmor profile could not be loaded"
fi

grep -Fq '/usr/bin/runsc (' /sys/kernel/security/apparmor/profiles || \
  fail "runsc AppArmor profile was not loaded"

printf '%s\n' "runsc AppArmor userns profile installed and loaded"
